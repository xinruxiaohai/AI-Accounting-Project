import datetime
import sqlite3
from pathlib import Path

# 数据库文件固定在 database.py 同目录下，这样不管从哪个目录启动 app.py 都找得到
DB_PATH = Path(__file__).resolve().parent / "records.db"

# 分类与支付账户的候选值。集中放在这里，前端下拉框统一从后端取，避免前后端各写一份对不上
CATEGORIES = ["餐饮", "交通", "购物", "娱乐", "其他"]
ACCOUNTS = ["现金", "微信", "支付宝", "银行卡"]

# 老库升级时给历史数据兜底的账户名
DEFAULT_ACCOUNT = "现金"

# 账目类型：expense = 支出（余额减），income = 收入（余额加）
RECORD_TYPES = ("expense", "income")
DEFAULT_TYPE = "expense"


def get_conn():
    """开一个新连接。sqlite3 的连接不能跨线程共用，所以每次用完就关。"""
    conn = sqlite3.connect(DB_PATH)
    # 打开 row_factory 后，查询结果可以用 row["amount"] 按列名取，不用记下标
    conn.row_factory = sqlite3.Row
    return conn


def _signed(amount, record_type):
    """把金额换算成「对余额的影响」：收入为正，支出为负。

    余额联动全靠这一个换算，所有增删改都调用它，口径就不会三处不一致。
    """
    return amount if record_type == "income" else -amount


def _apply_balance(conn, account, delta):
    """在同一个事务里把某账户余额加减 delta。

    账户可能不在 accounts 表里（比如接口传了自定义账户名，或老数据里的账户），
    所以先 INSERT OR IGNORE 补一条 0 余额的记录，再 UPDATE —— 否则余额变更会静默丢失。
    """
    conn.execute("INSERT OR IGNORE INTO accounts (name, balance) VALUES (?, 0)", (account,))
    conn.execute(
        "UPDATE accounts SET balance = balance + ? WHERE name = ?", (delta, account)
    )


def init_db():
    """建表 + 兼容旧库升级。反复启动不会报错，旧库也不会丢数据。"""
    conn = get_conn()
    try:
        with conn:  # 进 with 就是开事务，正常退出自动 commit，出错自动 rollback
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS records (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    amount   REAL    NOT NULL,
                    category TEXT    NOT NULL,
                    note     TEXT    NOT NULL DEFAULT '',
                    date     TEXT    NOT NULL,
                    account  TEXT    NOT NULL DEFAULT '现金',
                    type     TEXT    NOT NULL DEFAULT 'expense'
                )
                """
            )

            # 兼容 v0.01/v0.02 建的老表：那时没有 account 列。
            # ALTER TABLE ... ADD COLUMN 带非空默认值是安全操作，已有行会自动填默认值，一行都不会丢。
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(records)")]
            if "account" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN account TEXT NOT NULL DEFAULT '现金'"
                )
            # v0.03 前半段的老表没有 type 列，历史数据一律按「支出」补齐（当时只有支出）
            if "type" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'"
                )

            # 账户表：name 做主键，balance 是当前余额。
            # 注意它是「余额的唯一真相」，不靠账目实时算 —— 因为用户允许手动改余额。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    name    TEXT PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0
                )
                """
            )

            # 预置四个常用账户，余额 0。INSERT OR IGNORE 保证重复启动不会重复插入，也不会覆盖已有余额
            for name in ACCOUNTS:
                conn.execute(
                    "INSERT OR IGNORE INTO accounts (name, balance) VALUES (?, 0)", (name,)
                )

            # 老账目里出现过的自定义账户也补进账户表，否则列表里查不到它
            conn.execute(
                "INSERT OR IGNORE INTO accounts (name, balance) "
                "SELECT DISTINCT account, 0 FROM records"
            )
    finally:
        conn.close()  # with 只管事务，连接必须手动关


def add_record(amount, category, note, date, account=DEFAULT_ACCOUNT, record_type=DEFAULT_TYPE):
    """插入一笔账并联动余额，返回数据库自动分配的 id。

    写账目和改余额在同一个 conn、同一个事务里，要么都成功要么都回滚，
    不会出现「账记上了但余额没变」的脏数据。
    """
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO records (amount, category, note, date, account, type)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (amount, category, note, date, account, record_type),
            )
            _apply_balance(conn, account, _signed(amount, record_type))
            return cur.lastrowid
    finally:
        conn.close()


def update_record(
    record_id,
    amount,
    category,
    note,
    date,
    account=DEFAULT_ACCOUNT,
    record_type=DEFAULT_TYPE,
):
    """按 id 整条覆盖更新，并修正两个账户的余额。更新到了返回 True，id 不存在返回 False。

    余额修正分两步，顺序不能反：
    1. 把改动前的旧账对旧账户的影响撤销掉（delta 取反）
    2. 把新账对新账户的影响加上
    这样「改金额」「改类型」「改账户」三种情况用同一套逻辑就都对了。
    """
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if old is None:
                return False

            conn.execute(
                """
                UPDATE records
                   SET amount = ?, category = ?, note = ?, date = ?, account = ?, type = ?
                 WHERE id = ?
                """,
                (amount, category, note, date, account, record_type, record_id),
            )
            _apply_balance(conn, old["account"], -_signed(old["amount"], old["type"]))
            _apply_balance(conn, account, _signed(amount, record_type))
            return True
    finally:
        conn.close()


def delete_record(record_id):
    """按 id 删除一条记录，并把余额回滚。删到了返回 True，id 不存在返回 False。"""
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type FROM records WHERE id = ?", (record_id,)
            ).fetchone()
            if old is None:
                return False

            conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            _apply_balance(conn, old["account"], -_signed(old["amount"], old["type"]))
            return True
    finally:
        conn.close()


def list_records(account=None):
    """取出账目，最新记的排最前。传 account 就只返回该账户的流水。"""
    sql = "SELECT id, amount, category, note, date, account, type FROM records"
    params = []
    if account:
        sql += " WHERE account = ?"
        params.append(account)
    # 排序规则写死在这条 SQL 里：id 倒序 = 最新在前，不依赖存储层默认行为
    sql += " ORDER BY id DESC"

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        # sqlite3.Row 不是标准 dict，转一下才能被 jsonify 直接序列化
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_accounts():
    """返回所有账户及余额。按插入顺序排，展示时不会一会儿现金一会儿银行卡。"""
    conn = get_conn()
    try:
        rows = conn.execute("SELECT name, balance FROM accounts ORDER BY rowid").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def update_account_balance(name, balance):
    """手动把某账户余额改成指定值。账户不存在返回 False。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE accounts SET balance = ? WHERE name = ?", (balance, name)
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def get_statistics():
    """总览：总收入、总支出、总余额。

    - 总收入 / 总支出：按 type 分别求和，COALESCE 保证没有记录时是 0 而不是 NULL
    - 总余额：直接 SUM(accounts.balance)，而不是「收入-支出」。
      因为余额允许手动修改，账目求和已经不等于真实余额了，账户表才是唯一真相。
    """
    conn = get_conn()
    try:
        income_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records WHERE type = 'income'"
        ).fetchone()["total"]
        expense_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records WHERE type = 'expense'"
        ).fetchone()["total"]
        balance_total = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS total FROM accounts"
        ).fetchone()["total"]
    finally:
        conn.close()

    # 浮点数求和会有 0.30000000000000004 这类尾巴，四舍五入到分再返回
    return {
        "income_total": round(income_total, 2),
        "expense_total": round(expense_total, 2),
        "balance_total": round(balance_total, 2),
    }


def get_all_categories():
    """返回分类候选项（餐饮 / 交通 / 购物 / 娱乐 / 其他）。"""
    return list(CATEGORIES)


def get_all_accounts():
    """返回支付账户候选项（现金 / 微信 / 支付宝 / 银行卡）。"""
    return list(ACCOUNTS)
