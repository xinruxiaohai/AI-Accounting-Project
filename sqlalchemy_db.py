"""v0.14.1 商业化重构：SQLAlchemy 引擎层 + ORM 映射（渐进式 / 绞杀者模式）。

设计取舍（很重要，请连同交付说明一起读）
------------------------------------------
database.py 有 6697 行、数百条已经跑在真实账目上的手写 SQL，其中多用户隔离、
转账/平账的余额联动、分类迁移、投资体系都是「改一个符号就是资损」的核心逻辑。
把它们一次性改写成 session.query() 会同时踩两条红线：

  * 「表结构 / 外键关系 / 索引完全不变」—— ORM 的 create_all() 会重新生成 DDL；
  * 「原有业务零破坏」—— 全量重写无法在本次交付里做到等价回归。

因此本模块采用分层的渐进式迁移：

  1. **连接层交给 SQLAlchemy**：.env / 环境变量里的 DB_URI
     （mysql+pymysql://user:pwd@host:3306/dbname）直接 create_engine，
     带连接池、pool_pre_ping、连接级 sql_mode / 时区初始化；
  2. **业务 SQL 原样保留**：database.py 通过 sqlite3 语义的连接适配器执行，
     MySQL 方言翻译复用已有的 db_compat.py（PRAGMA / ? 占位符 / INSERT OR
     IGNORE / datetime('now') / 标量 MAX 等）；
  3. **新增功能走真正的 ORM**：工单系统用声明式模型映射「已存在」的表，
     全项目从不调用 Base.metadata.create_all()，因此不产生任何 DDL，
     表结构、外键、索引一个字节都不变；
  4. **未配置 DB_URI 时 get_conn() 返回 None**，database.py 回退到原生
     sqlite3.connect()，本地单机部署与 v0.14.0 行为完全一致。

对外接口
--------
    DB_URI / HAS_SQLALCHEMY / is_mysql_runtime()
    get_engine()             SQLAlchemy Engine（ORM 用；SQLite 回退时也指向本地库）
    get_conn()               给 database.get_conn() 用的 DBAPI 连接，None = 用原生 sqlite3
    session_scope()          ORM 会话上下文（异常自动 rollback）
    list_my_feedback(uid)    工单：查自己的反馈与官方回复
    reply_feedback(fid, ...) 工单：管理员回复
    UserFeedbackTicket       ORM 模型（仅映射，不建表）
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - python-dotenv 缺失时不影响纯 SQLite 部署
    def load_dotenv(*args, **kwargs):
        return False


PROJECT_DIR = Path(__file__).resolve().parent
# QA 隔离开关：设置后所有 SQLite 读写（含 ORM 引擎）都指向副本，绝不碰主库。
SQLITE_PATH = Path(
    os.getenv("ZHZ_SQLITE_PATH") or (PROJECT_DIR / "records.db")
).resolve()

# app.py 的 load_dotenv() 发生在 import database 之后，这里必须自己再读一次，
# 否则 import 期读不到 DB_URI。
load_dotenv(PROJECT_DIR / ".env", override=False)

DB_URI = (os.getenv("DB_URI") or os.getenv("DATABASE_URL") or "").strip()
IS_MYSQL_URI = DB_URI.lower().startswith("mysql")

try:
    from sqlalchemy import Column, Integer, String, Text, create_engine, event
    from sqlalchemy.orm import declarative_base, sessionmaker
    from sqlalchemy.pool import NullPool

    HAS_SQLALCHEMY = True
except ImportError:  # pragma: no cover - 没装依赖时降级为纯 SQLite 运行
    HAS_SQLALCHEMY = False


_engine = None
_session_factory = None
_resolved = False
Base = declarative_base() if HAS_SQLALCHEMY else None


def log(message):
    print("[sqlalchemy_db] %s" % message, file=sys.stderr, flush=True)


# ---------------- ORM 映射：只映射已存在的表，绝不建表 ----------------

if Base is not None:

    class UserFeedbackTicket(Base):
        """user_feedback 工单表。

        列定义与 database.init_db() 的 DDL 一一对应；status / admin_reply 是
        v0.14.1 通过 _ensure_feedback_ticket_schema() 幂等补上的两列。
        本类只用于 SELECT / UPDATE，不调用 create_all()，不产生任何 DDL。
        """

        __tablename__ = "user_feedback"

        id = Column(Integer, primary_key=True, autoincrement=True)
        user_id = Column(Integer, nullable=False)
        email = Column(String(255), default="")
        nickname = Column(String(255), default="")
        issue_description = Column(Text, default="")
        occur_date = Column(String(32), default="")
        image_path = Column(Text, default="")
        contact_type = Column(String(32), default="")
        contact_info = Column(String(255), default="")
        created_at = Column(String(32), default="")
        status = Column(String(20), default="pending")
        admin_reply = Column(Text)
        # v0.14.2 三态字段：只映射已存在的列，不调用 create_all，不产生任何 DDL
        read_status = Column(Integer, default=0)
        process_status = Column(Integer, default=0)
        cc_email = Column(Integer, default=0)

        def as_dict(self):
            return {
                "id": self.id,
                "user_id": self.user_id,
                "uid": self.user_id,
                "email": self.email or "",
                "nickname": self.nickname or "",
                "issue_description": self.issue_description or "",
                "occur_date": self.occur_date or "",
                "image_path": self.image_path or "",
                "contact_type": self.contact_type or "",
                "contact_info": self.contact_info or "",
                "created_at": self.created_at or "",
                "status": self.status or "pending",
                "admin_reply": self.admin_reply or "",
                "read_status": int(self.read_status or 0),
                "process_status": int(self.process_status or 0),
                "cc_email": int(self.cc_email or 0),
            }

else:  # pragma: no cover - 未安装 SQLAlchemy 时的占位，避免 import * 崩掉
    UserFeedbackTicket = None


# ---------------- Engine ----------------

def _sqlite_url():
    # Windows 绝对路径用正斜杠；SQLAlchemy 接受 sqlite:///D:/xxx/records.db
    return "sqlite:///" + SQLITE_PATH.as_posix()


def _build_engine():
    if not HAS_SQLALCHEMY:
        return None

    if DB_URI:
        kwargs = {
            "pool_pre_ping": True,   # MySQL 8 小时断连自动重连
            "pool_recycle": 3600,
            "future": True,
        }
        if IS_MYSQL_URI:
            kwargs["pool_size"] = int(os.getenv("DB_POOL_SIZE") or 10)
            kwargs["max_overflow"] = int(os.getenv("DB_MAX_OVERFLOW") or 20)
        engine = create_engine(DB_URI, **kwargs)

        if IS_MYSQL_URI:
            @event.listens_for(engine, "connect")
            def _init_mysql_session(dbapi_conn, _record):
                """与 db_compat._connect_mysql() 保持一致：
                关掉 ONLY_FULL_GROUP_BY（SQLite 允许 GROUP BY 选非分组列），
                并把会话时区钉在 +08:00，让 NOW() 等价于 datetime('now','localtime')。
                """
                cur = dbapi_conn.cursor()
                try:
                    cur.execute(
                        "SET SESSION sql_mode = "
                        "'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION'"
                    )
                    cur.execute("SET time_zone = '+08:00'")
                finally:
                    cur.close()

        log("SQLAlchemy Engine 已创建：%s" % engine.url.render_as_string(hide_password=True))
        return engine

    # 没配 DB_URI：ORM 仍需要 engine（工单接口用），指向本地 SQLite。
    # 用 NullPool：每次开新连接，避免 SQLAlchemy 池长期持有文件句柄，
    # 与 database.get_conn() 的原生 sqlite3 连接并存时互相锁库。
    return create_engine(
        _sqlite_url(),
        poolclass=NullPool,
        connect_args={"timeout": 30, "check_same_thread": False},
        future=True,
    )


def get_engine():
    global _engine
    if _engine is None:
        _engine = _build_engine()
    return _engine


def _sessionmaker():
    global _session_factory
    if _session_factory is None:
        engine = get_engine()
        if engine is None:
            return None
        _session_factory = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return _session_factory


@contextmanager
def session_scope():
    """ORM 会话：正常提交、异常回滚、一定关闭。"""
    factory = _sessionmaker()
    if factory is None:
        raise RuntimeError("SQLAlchemy 未安装，无法使用 ORM 会话")
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# ---------------- 给 database.get_conn() 用的连接 ----------------

def _resolve_once():
    """启动时只做一次：解析 DB_URI 并锁定 db_compat 的方言与连接配置。"""
    global _resolved
    if _resolved:
        return
    import db_compat

    if DB_URI and IS_MYSQL_URI:
        db_compat.configure_from_db_uri(DB_URI)
        if not HAS_SQLALCHEMY:
            raise RuntimeError(
                "配置了 DB_URI 但未安装 SQLAlchemy，请先 pip install -r requirements.txt"
            )
        if db_compat.pymysql is None:
            raise RuntimeError(
                "DB_URI 使用 mysql+pymysql，但未安装 PyMySQL，"
                "请先 pip install -r requirements.txt"
            )
    else:
        # 兼容「之前的进度」：DB_ENGINE / DB_HOST 那套配置走 db_compat 自带的探测，
        # MySQL 连不上时按 ALLOW_SQLITE_FALLBACK 决定是否降级。
        db_compat.resolve_engine()
    _resolved = True


def is_mysql_runtime():
    """当前实际连的是不是 MySQL（供 init_db 的守卫与日志使用）。"""
    _resolve_once()
    import db_compat
    return bool((DB_URI and IS_MYSQL_URI) or db_compat.is_mysql())


def get_conn():
    """返回 sqlite3 语义的连接；返回 None 表示「沿用原生 sqlite3.connect」。

    MySQL 分支的连接来自 SQLAlchemy 连接池（engine.raw_connection()），
    再套 db_compat.CompatConnection 完成方言翻译 + Row 模拟；
    database.py 里所有 with conn: / fetchone() / row["col"] 写法都不用改。
    """
    _resolve_once()
    import db_compat

    if DB_URI and IS_MYSQL_URI:
        raw = get_engine().raw_connection()  # _ConnectionFairy，.close() 归还连接池
        try:
            return db_compat.CompatConnection(raw)
        except Exception:
            raw.close()
            raise

    if db_compat.is_mysql():
        # 旧配置路径：DB_ENGINE=mysql + DB_HOST/DB_USER/...
        return db_compat.connect()

    return None


# ---------------- 工单系统（新功能，走 ORM） ----------------

def orm_available():
    return HAS_SQLALCHEMY and Base is not None


def list_my_feedback(user_id, limit=200):
    """用户查自己的反馈（含管理员回复）。按提交时间倒序，强制 user_id 过滤。"""
    if not orm_available():
        import database
        return database.list_my_feedback(user_id, limit=limit)

    uid = int(user_id)
    with session_scope() as session:
        rows = (
            session.query(UserFeedbackTicket)
            .filter(UserFeedbackTicket.user_id == uid)
            .order_by(
                UserFeedbackTicket.created_at.desc(),
                UserFeedbackTicket.id.desc(),
            )
            .limit(limit)
            .all()
        )
        return [row.as_dict() for row in rows]


def reply_feedback(feedback_id, reply, status="replied"):
    """管理员回复工单。返回更新后的字典；工单不存在返回 None。"""
    if not orm_available():
        import database
        return database.reply_user_feedback(feedback_id, reply, status=status)

    with session_scope() as session:
        row = session.get(UserFeedbackTicket, int(feedback_id))
        if row is None:
            return None
        row.admin_reply = reply
        row.status = status
        session.flush()
        return row.as_dict()


__all__ = [
    "DB_URI",
    "SQLITE_PATH",
    "HAS_SQLALCHEMY",
    "Base",
    "UserFeedbackTicket",
    "get_engine",
    "get_conn",
    "is_mysql_runtime",
    "orm_available",
    "session_scope",
    "list_my_feedback",
    "reply_feedback",
]
