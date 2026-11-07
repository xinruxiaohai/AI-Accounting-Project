"""数据库驱动兼容层（v0.14.1）：SQLite / MySQL 双引擎。

背景
----
v0.14.0 及以前，整个后端是「手写 SQL + sqlite3」，database.py 里近 7000 行 SQL
已经跑通并被真实数据验证过。商业化改造要切 MySQL，但**不值得**把这几千行 SQL
重写成 ORM —— 那等于把「已经正确的业务逻辑」再赌一次。

所以这里做的是「方言翻译层」：
    * 业务代码继续写 `?` 占位符、`INSERT OR IGNORE`、`datetime('now','localtime')`
      这些 SQLite 写法；
    * 连 SQLite 时原样透传（本地开发、老用户单机部署完全不受影响）；
    * 连 MySQL 时在 execute() 里把这些方言**就地翻译**成 MySQL 语法，
      并把 pymysql 的 cursor 包装成 sqlite3.Cursor 的样子（fetchone 返回可按列名
      取值的 Row 对象）。

翻译是运行时的、无状态的，唯一需要配合的是建表：MySQL 的 DDL 差异太大
（TEXT 不能进主键、表达式默认值、功能索引），所以建表走 schema_mysql.py，
而不是让翻译器去猜。database.init_db() 在 MySQL 下走独立分支。

对外接口
--------
    is_mysql()               当前实际使用的引擎
    connect()                sqlite3 / pymysql 统一连接（带 sqlite3 语义）
    resolve_engine()         启动时探测 MySQL 是否真的可连，必要时降级 SQLite
    sqlite_compat            `from db_compat import sqlite_compat as sqlite3`
                             —— 让 except sqlite3.Error 同时抓住两种驱动的异常
"""

from __future__ import annotations

import os
import re
import sqlite3 as _sqlite3
import sys
from pathlib import Path

try:  # 本地 SQLite 部署不一定装了 pymysql，缺了也能跑
    import pymysql
    from pymysql import err as _mysql_err
    from pymysql.cursors import Cursor as _MysqlCursor

    _HAS_PYMYSQL = True
except Exception:  # pragma: no cover - 只在不装 pymysql 的机器上走这里
    pymysql = None
    _mysql_err = None
    _MysqlCursor = None
    _HAS_PYMYSQL = False

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover
    def load_dotenv(*args, **kwargs):
        return False


PROJECT_DIR = Path(__file__).resolve().parent
SQLITE_PATH = PROJECT_DIR / "records.db"

# app.py 里的 load_dotenv 发生在 `import database` 之后，所以这里必须自己再读一次，
# 否则 DB_HOST/DB_PASSWORD 在 import 期读不到。
load_dotenv(PROJECT_DIR / ".env", override=False)


def _flag(name, default=False):
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "y")


def _text(name, default=""):
    return (os.getenv(name) or "").strip() or default


# ---------------- 配置 ----------------

DB_ENGINE = _text("DB_ENGINE").lower()
if DB_ENGINE not in ("mysql", "sqlite"):
    # 没显式指定时：配了 DB_HOST 就按 MySQL 跑，否则保持 SQLite。
    # 这样「老用户直接 python app.py」永远不会因为缺 MySQL 而炸掉。
    DB_ENGINE = "mysql" if _text("DB_HOST") else "sqlite"

MYSQL_CONFIG = {
    "host": _text("DB_HOST", "127.0.0.1"),
    "port": int(_text("DB_PORT", "3306") or 3306),
    "user": _text("DB_USER", "zhihuizhang"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": _text("DB_NAME", "zhihuizhang"),
    "charset": "utf8mb4",
    "connect_timeout": int(_text("DB_CONNECT_TIMEOUT", "10") or 10),
    "read_timeout": int(_text("DB_READ_TIMEOUT", "60") or 60),
    "write_timeout": int(_text("DB_WRITE_TIMEOUT", "60") or 60),
}

# MySQL 连不上时是否允许退回 SQLite。
# 本地开发默认允许（保证 python app.py 一定能起来）；
# Docker/生产用 ALLOW_SQLITE_FALLBACK=0 快速失败，避免「以为在写 MySQL，其实写进了容器内 sqlite」。
ALLOW_SQLITE_FALLBACK = _flag("ALLOW_SQLITE_FALLBACK", default=DB_ENGINE == "sqlite")

_ACTIVE_ENGINE = DB_ENGINE
_ENGINE_RESOLVED = DB_ENGINE == "sqlite"


def is_mysql():
    return _ACTIVE_ENGINE == "mysql"


def engine_name():
    return _ACTIVE_ENGINE


def log(message):
    """统一走 stderr，不干扰 Flask 的 stdout 日志。"""
    print("[db_compat] %s" % message, file=sys.stderr)


def configure_from_db_uri(uri):
    """v0.14.1：解析 SQLAlchemy 风格的 DB_URI，覆盖 MySQL 连接配置并锁定引擎。

    例：mysql+pymysql://root:password@localhost:3306/dbname?charset=utf8mb4
    解析结果写进 MYSQL_CONFIG，然后把本模块的运行时引擎钉死为 mysql ——
    CompatCursor._prepare() 依赖 is_mysql() 决定是否做方言翻译，必须显式设置，
    否则 SQL 里的 `?` / INSERT OR IGNORE / datetime('now') 会原样发给 MySQL 直接报错。
    """
    from urllib.parse import parse_qs, unquote, urlsplit

    global DB_ENGINE, _ACTIVE_ENGINE, _ENGINE_RESOLVED, ALLOW_SQLITE_FALLBACK

    parts = urlsplit((uri or "").strip())
    if parts.scheme.lower() not in ("mysql", "mysql+pymysql", "mysql+mysqldb"):
        raise RuntimeError("DB_URI 不是 MySQL 连接串：%s" % parts.scheme)
    query = parse_qs(parts.query)
    MYSQL_CONFIG.update(
        {
            "host": parts.hostname or "127.0.0.1",
            "port": parts.port or 3306,
            "user": unquote(parts.username or "root"),
            "password": unquote(parts.password or ""),
            "database": (parts.path or "/").lstrip("/") or "zhihuizhang",
            "charset": (query.get("charset") or ["utf8mb4"])[0],
        }
    )
    DB_ENGINE = "mysql"
    _ACTIVE_ENGINE = "mysql"
    _ENGINE_RESOLVED = True
    ALLOW_SQLITE_FALLBACK = False
    log(
        "DB_URI 已生效：%s@%s:%s/%s"
        % (
            MYSQL_CONFIG["user"],
            MYSQL_CONFIG["host"],
            MYSQL_CONFIG["port"],
            MYSQL_CONFIG["database"],
        )
    )


# ---------------- Row ----------------

class Row:
    """模拟 sqlite3.Row：支持 row["col"] / row[0] / keys() / dict(row)。"""

    __slots__ = ("_keys", "_index", "_values")

    def __init__(self, keys, values):
        self._keys = tuple(keys)
        self._index = {k: i for i, k in enumerate(self._keys)}
        self._values = tuple(values)

    def keys(self):
        return list(self._keys)

    def __getitem__(self, item):
        if isinstance(item, (int, slice)):
            return self._values[item]
        try:
            return self._values[self._index[item]]
        except KeyError:
            raise IndexError("no such column: %s" % item)

    def get(self, item, default=None):
        try:
            return self[item]
        except (KeyError, IndexError):
            return default

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def __contains__(self, item):
        return item in self._values

    def __eq__(self, other):
        if isinstance(other, Row):
            return self._keys == other._keys and self._values == other._values
        if isinstance(other, tuple):
            return self._values == other
        return NotImplemented

    def __repr__(self):
        return "Row(%r)" % (dict(zip(self._keys, self._values)),)


# ---------------- SQL 方言翻译 ----------------

_PRAGMA_TABLE_INFO = re.compile(
    r"PRAGMA\s+table_info\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", re.I
)

# sqlite_master 在 SQL 里总是当表用（SELECT ... FROM sqlite_master [WHERE ...]）。
# 这里换成一个同名派生表，原来的 WHERE name=/type= 就还能照常工作。
_SQLITE_MASTER_VIEW = (
    "(SELECT TABLE_NAME AS name, 'table' AS type FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_TYPE = 'BASE TABLE') AS sqlite_master"
)
_SQLITE_SEQUENCE_VIEW = (
    "(SELECT TABLE_NAME AS name, AUTO_INCREMENT AS seq FROM information_schema.TABLES "
    "WHERE TABLE_SCHEMA = DATABASE() AND AUTO_INCREMENT IS NOT NULL) AS sqlite_sequence"
)

_INTEGRITY_DUPLICATE_CODES = (1060, 1061, 1050, 1091, 1826)
# 1060 Duplicate column、1061 Duplicate key、1050 Table exists、1091 Can't drop、1826 Duplicate FK


def _split_quotes(sql):
    """返回 [(片段, 是否在引号内)]，用于只在引号外做替换。"""
    parts = []
    buf = []
    quote = None
    i = 0
    length = len(sql)
    while i < length:
        ch = sql[i]
        if quote:
            buf.append(ch)
            if ch == "\\" and i + 1 < length:
                buf.append(sql[i + 1])
                i += 2
                continue
            if ch == quote:
                if i + 1 < length and sql[i + 1] == quote:  # '' 转义
                    buf.append(sql[i + 1])
                    i += 2
                    continue
                quote = None
                parts.append(("".join(buf), True))
                buf = []
            i += 1
            continue
        if ch in ("'", '"', "`"):
            if buf:
                parts.append(("".join(buf), False))
            buf = [ch]
            quote = ch
            i += 1
            continue
        buf.append(ch)
        i += 1
    if buf:
        parts.append(("".join(buf), bool(quote)))
    return parts


def _map_outside_quotes(sql, func):
    return "".join(func(text) if not quoted else text for text, quoted in _split_quotes(sql))


def _replace_placeholders(sql):
    """`?` → `%s`（引号外），同时把字面 `%` 变成 `%%` 供 pymysql 做参数格式化。"""
    out = []
    for text, quoted in _split_quotes(sql):
        if quoted:
            # 引号内的 % 同样要转义：pymysql 是对整条 SQL 做 % 格式化的
            out.append(text.replace("%", "%%"))
        else:
            out.append(text.replace("%", "%%").replace("?", "%s"))
    return "".join(out)


_ON_CONFLICT = re.compile(
    r"ON\s+CONFLICT\s*\(([^)]*)\)\s*DO\s+UPDATE\s+SET\s+(.*?)(?=(?:\bWHERE\b|\bRETURNING\b|$))",
    re.I | re.S,
)
_EXCLUDED = re.compile(r"\bexcluded\.([A-Za-z_][A-Za-z0-9_]*)", re.I)
_KEY_COLUMN = re.compile(
    r"(?<![`\w.])key(?![`\w])(?=\s*(?:,|\)|=|\bASC\b|\bDESC\b|\bIS\b|\bLIKE\b))", re.I
)
_SCALAR_MAX = re.compile(r"\bMAX\(\s*([^(),]*(?:[-+*/])[^(),]*)\s*,\s*0\s*\)", re.I)


def translate(sql):
    """把 SQLite 方言翻译成 MySQL 方言。"""
    if not sql:
        return sql
    text = sql

    # 1) PRAGMA table_info(x) —— 迁移代码用它判断列是否存在
    def _pragma(match):
        table = match.group(1)
        # 注意：不能包成子查询 —— 代码是直接把 PRAGMA 当独立结果集遍历的
        return (
            "SELECT COLUMN_NAME AS name, DATA_TYPE AS type, IS_NULLABLE AS notnull, "
            "COLUMN_DEFAULT AS dflt_value, 0 AS pk "
            "FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '%s' "
            "ORDER BY ORDINAL_POSITION" % table
        )

    text = _PRAGMA_TABLE_INFO.sub(_pragma, text)
    # 少数地方写的是 PRAGMA table_info(%s) % table 拼出来的，上面那条兜不住，
    # 这里再兜一次「已经拼成常量表名」的写法。
    text = re.sub(r"PRAGMA\s+table_info\s*\(\s*%s\s*\)\s*%\s*([A-Za-z_][A-Za-z0-9_]*)",
                  lambda m: _pragma(m), text, flags=re.I)

    # 2) sqlite 元数据表 → information_schema 派生表
    text = re.sub(r"\bsqlite_master\b", _SQLITE_MASTER_VIEW, text, flags=re.I)
    text = re.sub(r"\bsqlite_sequence\b", _SQLITE_SEQUENCE_VIEW, text, flags=re.I)

    # 3) INSERT 的冲突策略
    text = re.sub(r"\bINSERT\s+OR\s+IGNORE\b", "INSERT IGNORE", text, flags=re.I)
    text = re.sub(r"\bINSERT\s+OR\s+REPLACE\b", "REPLACE", text, flags=re.I)
    text = re.sub(r"\bINSERT\s+OR\s+ABORT\b", "INSERT", text, flags=re.I)
    text = re.sub(r"\bINSERT\s+OR\s+ROLLBACK\b", "INSERT", text, flags=re.I)
    text = re.sub(r"\bINSERT\s+OR\s+FAIL\b", "INSERT", text, flags=re.I)

    # 4) UPSERT
    def _upsert(match):
        tail = _EXCLUDED.sub(lambda m: "VALUES(%s)" % m.group(1), match.group(2))
        return "ON DUPLICATE KEY UPDATE " + tail

    text = _ON_CONFLICT.sub(lambda m: _upsert(m), text)

    # 5) 时间函数
    # 注意：这里写单个 %，由 _replace_placeholders() 在有参数时统一转成 %%（pymysql 会
    # 对整条 SQL 做一次 % 格式化，提前转义会变成 %%%%Y）。
    text = re.sub(
        r"\bdatetime\s*\(\s*'now'\s*,\s*'localtime'\s*\)",
        "DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s')",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"\bdatetime\s*\(\s*'now'\s*\)",
        "DATE_FORMAT(NOW(), '%Y-%m-%d %H:%i:%s')",
        text,
        flags=re.I,
    )
    text = re.sub(r"\bdate\s*\(\s*'now'\s*,\s*'localtime'\s*\)", "CURDATE()", text, flags=re.I)

    # 6) SQLite 的 substr(x, 1, instr(x,'@') - 1) → SUBSTRING_INDEX
    text = re.sub(
        r"substr\s*\(\s*([A-Za-z_][\w.]*)\s*,\s*1\s*,\s*instr\s*\(\s*\1\s*,\s*'([^']*)'\s*\)\s*-\s*1\s*\)",
        lambda m: "SUBSTRING_INDEX(%s, '%s', 1)" % (m.group(1), m.group(2)),
        text,
        flags=re.I,
    )

    # 7) CAST(x AS TEXT) → CHAR
    text = re.sub(r"\bAS\s+TEXT\b", "AS CHAR", text, flags=re.I)

    # 8) 两参数 MAX(a - b, 0) → GREATEST（SQLite 的标量 max；单参数 MAX() 是聚合，不能动）
    text = _SCALAR_MAX.sub(lambda m: "GREATEST(%s, 0)" % m.group(1), text)

    # 9) rowid：本项目只有 accounts 用到（承接「按创建先后」排序），MySQL 侧用 id
    text = re.sub(
        r"(?<![\w.])([A-Za-z_]\w*\.)?rowid\b",
        lambda m: (m.group(1) or "") + "id",
        text,
        flags=re.I,
    )

    # 9.1) LIKE ... ESCAPE '\'：MySQL 里反斜杠本身就是默认转义符，
    #      且 '\' 这个字面量在 MySQL 里是「未闭合字符串」，必须去掉
    text = re.sub(r"\s+ESCAPE\s+'\\'", "", text, flags=re.I)

    # 10) key 是 MySQL 保留字
    text = _map_outside_quotes(text, lambda s: _KEY_COLUMN.sub("`key`", s))

    # 11) 建表语句里的 SQLite 类型
    head = text.lstrip().upper()
    if head.startswith("CREATE TABLE") or head.startswith("ALTER TABLE"):
        text = re.sub(r"\bAUTOINCREMENT\b", "AUTO_INCREMENT", text, flags=re.I)
        text = re.sub(r"\bINTEGER\b", "BIGINT", text, flags=re.I)
        text = re.sub(r"\bREAL\b", "DOUBLE", text, flags=re.I)
        text = re.sub(r"\bBLOB\b", "LONGBLOB", text, flags=re.I)
    text = re.sub(r"CREATE\s+(UNIQUE\s+)?INDEX\s+IF\s+NOT\s+EXISTS", lambda m: "CREATE %sINDEX" % (m.group(1) or ""), text, flags=re.I)

    return text


def _prepare(sql, params):
    if not is_mysql():
        return sql, params
    text = translate(sql)
    args = params
    if args is not None and not isinstance(args, (list, tuple)):
        args = (args,)
    if args:
        text = _replace_placeholders(text)
        if isinstance(args, tuple):
            args = tuple(args)
        else:
            args = list(args)
    return text, args


# ---------------- 游标 / 连接包装 ----------------

class CompatCursor:
    def __init__(self, raw):
        self._raw = raw
        self._description = None

    # 与 sqlite3.Cursor 一致：execute 返回 self，可以链式 .fetchone()
    def execute(self, sql, params=None):
        text, args = _prepare(sql, params)
        try:
            self._raw.execute(text, args)
        except Exception as exc:
            if is_mysql() and getattr(exc, "args", None) and exc.args[0] in _INTEGRITY_DUPLICATE_CODES:
                # 幂等迁移里「列/索引/表已存在」不该炸掉整个 init_db
                log("忽略重复对象：%s" % (exc.args[1] if len(exc.args) > 1 else exc.args[0]))
            else:
                raise
        if self._raw.description:
            self._description = tuple(
                (d[0],) + tuple(d[1:]) for d in self._raw.description
            )
        return self

    def executemany(self, sql, seq_of_params):
        # 逐条 execute：每条参数都要独立做占位符/%% 转义，交给 _prepare 统一处理最稳
        for row in seq_of_params:
            self.execute(sql, row)
        return self

    def _wrap(self, raw):
        if raw is None:
            return None
        keys = [d[0] for d in (self._raw.description or ())]
        if not keys:
            return raw
        return Row(keys, raw)

    def fetchone(self):
        return self._wrap(self._raw.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._raw.fetchall()]

    def fetchmany(self, size=None):
        raw = self._raw.fetchmany(size) if size is not None else self._raw.fetchmany()
        return [self._wrap(row) for row in raw]

    def __iter__(self):
        for row in self._raw:
            yield self._wrap(row)

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    @property
    def lastrowid(self):
        return self._raw.lastrowid

    @property
    def rowcount(self):
        return self._raw.rowcount

    @property
    def description(self):
        return self._description

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
        return False


class CompatConnection:
    """sqlite3.Connection 的最小子集：execute/executemany/cursor/commit/rollback/close
    以及 `with conn:`（成功 commit、异常 rollback，**不关闭连接**）。"""

    def __init__(self, raw):
        self._raw = raw

    def execute(self, sql, params=None):
        return CompatCursor(self._raw.cursor()).execute(sql, params)

    def executemany(self, sql, seq_of_params):
        return CompatCursor(self._raw.cursor()).executemany(sql, seq_of_params)

    def cursor(self):
        return CompatCursor(self._raw.cursor())

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        try:
            self._raw.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


# ---------------- 连接 ----------------

def _connect_mysql():
    if not _HAS_PYMYSQL:
        raise RuntimeError(
            "DB_ENGINE=mysql 但没装 PyMySQL，请先 pip install -r requirements.txt"
        )
    raw = pymysql.connect(
        **MYSQL_CONFIG,
        autocommit=False,
        cursorclass=_MysqlCursor,
    )
    cur = raw.cursor()
    try:
        # ONLY_FULL_GROUP_BY 会让 SQLite 里合法的 GROUP BY 报错（SQLite 允许选非分组列）；
        # 时区固定 +08:00，让 NOW()/CURDATE() 和原来的 datetime('now','localtime') 一致。
        cur.execute(
            "SET SESSION sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'"
        )
        cur.execute("SET time_zone = '+08:00'")
    finally:
        cur.close()
    return CompatConnection(raw)


def _connect_sqlite(path=None):
    conn = _sqlite3.connect(str(path or SQLITE_PATH))
    conn.row_factory = _sqlite3.Row
    return conn


def connect(sqlite_path=None):
    """开一个连接。MySQL 连不上时**不**在这里静默降级 ——
    降级只在启动时 resolve_engine() 里做一次，避免中途「一半 MySQL 一半 SQLite」把数据写乱。"""
    if is_mysql():
        return _connect_mysql()
    return _connect_sqlite(sqlite_path)


def resolve_engine():
    """启动时探测一次真实可用性；MySQL 不可用且允许降级时切回 SQLite。"""
    global _ACTIVE_ENGINE, _ENGINE_RESOLVED
    if _ENGINE_RESOLVED:
        return _ACTIVE_ENGINE
    if DB_ENGINE != "mysql":
        _ACTIVE_ENGINE = "sqlite"
        _ENGINE_RESOLVED = True
        return _ACTIVE_ENGINE
    try:
        conn = _connect_mysql()
        conn.close()
        _ACTIVE_ENGINE = "mysql"
        log("使用 MySQL：%s@%s:%s/%s" % (
            MYSQL_CONFIG["user"], MYSQL_CONFIG["host"],
            MYSQL_CONFIG["port"], MYSQL_CONFIG["database"]))
    except Exception as exc:
        if not ALLOW_SQLITE_FALLBACK:
            _ENGINE_RESOLVED = True
            raise
        _ACTIVE_ENGINE = "sqlite"
        log("MySQL 不可用（%s），已降级为 SQLite。生产环境请设 ALLOW_SQLITE_FALLBACK=0。" % exc)
    _ENGINE_RESOLVED = True
    return _ACTIVE_ENGINE


def check_mysql_version(conn):
    """MySQL 8.0.13 才支持表达式默认值 / 功能索引，低于此版本直接给出明确报错。"""
    row = conn.execute("SELECT VERSION() AS v").fetchone()
    version = str(row["v"]) if row else ""
    match = re.match(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        return version
    major, minor, patch = (int(x) for x in match.groups())
    if (major, minor, patch) < (8, 0, 13):
        raise RuntimeError(
            "MySQL 版本过低（%s）。本项目 schema 使用表达式默认值与功能索引，"
            "请使用 MySQL 8.0.13+（推荐 8.0.36 / 8.4）。" % version
        )
    return version


# ---------------- 异常兼容 ----------------

class _SqliteCompat:
    """`except sqlite3.Error` 同时匹配 sqlite3 与 pymysql 的异常。

    用元组即可完成 except；这里再暴露 connect/Row 等名字，方便代码里继续写 sqlite3.xxx。
    """

    Error = (_sqlite3.Error, _mysql_err.MySQLError) if _HAS_PYMYSQL else _sqlite3.Error
    IntegrityError = (
        (_sqlite3.IntegrityError, _mysql_err.IntegrityError)
        if _HAS_PYMYSQL
        else _sqlite3.IntegrityError
    )
    OperationalError = (
        (_sqlite3.OperationalError, _mysql_err.OperationalError)
        if _HAS_PYMYSQL
        else _sqlite3.OperationalError
    )
    ProgrammingError = (
        (_sqlite3.ProgrammingError, _mysql_err.ProgrammingError)
        if _HAS_PYMYSQL
        else _sqlite3.ProgrammingError
    )
    Row = Row
    Cursor = CompatCursor
    Connection = CompatConnection
    connect = staticmethod(connect)


sqlite_compat = _SqliteCompat

__all__ = [
    "Row",
    "CompatCursor",
    "CompatConnection",
    "connect",
    "translate",
    "is_mysql",
    "engine_name",
    "resolve_engine",
    "configure_from_db_uri",
    "check_mysql_version",
    "sqlite_compat",
    "MYSQL_CONFIG",
    "SQLITE_PATH",
]