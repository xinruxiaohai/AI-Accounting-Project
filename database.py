import sqlite3
from pathlib import Path

# 数据库文件固定在 database.py 同目录下，这样不管从哪个目录启动 app.py 都找得到
DB_PATH = Path(__file__).resolve().parent / "records.db"


def get_conn():
    """开一个新连接。sqlite3 的连接不能跨线程共用，所以每次用完就关。"""
    conn = sqlite3.connect(DB_PATH)
    # 打开 row_factory 后，查询结果可以用 row["amount"] 按列名取，不用记下标
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """建表。IF NOT EXISTS 保证反复启动不会报「表已存在」。"""
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
                    date     TEXT    NOT NULL
                )
                """
            )
    finally:
        conn.close()  # with 只管事务，连接必须手动关


def add_record(amount, category, note, date):
    """插入一笔账，返回数据库自动分配的 id。

    值全部用 ? 占位符传入，绝不拼接字符串 —— 这是防 SQL 注入的标准做法。
    """
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO records (amount, category, note, date) VALUES (?, ?, ?, ?)",
                (amount, category, note, date),
            )
            return cur.lastrowid
    finally:
        conn.close()


def list_records():
    """取出全部账目，最新记的排在最前面。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, amount, category, note, date FROM records ORDER BY id DESC"
        ).fetchall()
        # sqlite3.Row 不是标准 dict，转一下才能被 jsonify 直接序列化
        return [dict(row) for row in rows]
    finally:
        conn.close()
