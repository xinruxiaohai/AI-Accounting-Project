import datetime
import sqlite3
from pathlib import Path

# 数据库文件固定在 database.py 同目录下，这样不管从哪个目录启动 app.py 都找得到
DB_PATH = Path(__file__).resolve().parent / "records.db"

# ---------------- 默认数据（缺了才补，不动已有数据） ----------------

# 两级分类种子：(一级分类, [二级分类...])
CATEGORY_SEEDS = [
    ("餐饮", ["早餐", "午餐", "晚餐", "外卖"]),
    ("交通", ["打车", "地铁", "公交", "加油"]),
    ("购物", ["日用品", "服饰", "数码"]),
    ("娱乐", ["电影", "游戏", "旅游"]),
    ("居住", ["房租", "水电", "物业"]),
    ("其他", []),
]

# 账户大类：只认这三种，前端用 <optgroup> 分组展示
ACCOUNT_GROUPS = ("资金账户", "储蓄账户", "投资账户")
DEFAULT_GROUP = "资金账户"

# 账户种子：(账户名, 大类)
ACCOUNT_SEEDS = [
    ("现金", "资金账户"),
    ("微信", "资金账户"),
    ("支付宝", "资金账户"),
    ("招行卡", "储蓄账户"),
    ("建行卡", "储蓄账户"),
    ("余额宝", "投资账户"),
    ("基金", "投资账户"),
]

DEFAULT_ACCOUNT = "现金"
DEFAULT_CATEGORY = "其他"

# 分类最多两级：一级 + 二级，二级下面不能再挂
MAX_CATEGORY_LEVEL = 2

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
    """把金额换算成「对余额的影响」：收入为正，支出为负。"""
    return amount if record_type == "income" else -amount


def normalize_date(value):
    """把 date 统一成「YYYY-MM-DD HH:MM」，让老数据和新数据长得一样。

    - 老数据只有 10 位日期（2026-10-25）：补成 2026-10-25 00:00
    - 新数据可能带秒、也可能用 T 分隔（2026-10-26T14:30）：统一成空格 + 截到分钟
    注意这是「读时补全」，不回头改库里的老数据，所以升级零风险。
    """
    if not value:
        return ""
    text = str(value).strip().replace("T", " ")
    if len(text) <= 10:
        return text + " 00:00"
    return text[:16]  # 2026-10-26 14:30:59 → 2026-10-26 14:30


def _apply_balance(conn, account, delta):
    """在同一个事务里把某账户余额加减 delta。

    账户可能不在 accounts 表里（接口传了自定义账户名），所以先 INSERT OR IGNORE
    补一条 0 余额的记录，再 UPDATE —— 否则余额变更会静默丢失。
    """
    conn.execute(
        "INSERT OR IGNORE INTO accounts (name, balance, group_name) VALUES (?, 0, ?)",
        (account, DEFAULT_GROUP),
    )
    conn.execute(
        "UPDATE accounts SET balance = balance + ? WHERE name = ?", (delta, account)
    )


def _row_to_category(row):
    """把 categories 的一行转成前端友好的字典。"""
    return {
        "id": row["id"],
        "name": row["name"],
        "parent_id": row["parent_id"],
        "children": [],
    }


def _ensure_category(conn, name, parent_id=None):
    """按 (名字, 父级) 找分类，没有就插一条，返回 id。幂等，可反复调用。"""
    if parent_id is None:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL", (name,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM categories WHERE name = ? AND parent_id = ?", (name, parent_id)
        ).fetchone()
    if row is not None:
        return row["id"]

    cur = conn.execute(
        "INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id)
    )
    return cur.lastrowid


def _seed_categories(conn):
    """按 CATEGORY_SEEDS 补齐默认分类，已有同名同级的直接跳过。"""
    for top_name, children in CATEGORY_SEEDS:
        top_id = _ensure_category(conn, top_name, None)
        for child_name in children:
            _ensure_category(conn, child_name, top_id)


def _seed_accounts(conn):
    """按 ACCOUNT_SEEDS 补齐默认账户。INSERT OR IGNORE 不会覆盖已有余额。"""
    for name, group_name in ACCOUNT_SEEDS:
        conn.execute(
            "INSERT OR IGNORE INTO accounts (name, balance, group_name) VALUES (?, 0, ?)",
            (name, group_name),
        )


def _backfill_category_ids(conn):
    """给老账目补 category_id。

    老库的 records 只存 category 文本（甚至是用户随手写的「卫浴」「二分」），
    这里分三步：
    1. 账目里出现过、分类表里没有的名字 → 补成一枚一级分类（不丢数据、不丢展示）
    2. 按「一级分类同名」回填 category_id
    3. 还剩下没填上的（名字只存在于二级分类），按任意同名分类回填
    """
    known = {row["name"] for row in conn.execute("SELECT name FROM categories")}
    for row in conn.execute(
        "SELECT DISTINCT category FROM records "
        "WHERE category IS NOT NULL AND TRIM(category) <> ''"
    ):
        name = str(row["category"]).strip()
        if name and name not in known:
            _ensure_category(conn, name, None)
            known.add(name)

    conn.execute(
        """
        UPDATE records
           SET category_id = (
                   SELECT c.id FROM categories c
                    WHERE c.name = records.category AND c.parent_id IS NULL)
         WHERE category_id IS NULL
        """
    )
    conn.execute(
        """
        UPDATE records
           SET category_id = (
                   SELECT c.id FROM categories c
                    WHERE c.name = records.category
                    ORDER BY c.parent_id IS NOT NULL, c.id
                    LIMIT 1)
         WHERE category_id IS NULL
        """
    )


def init_db():
    """建表 + 兼容旧库升级。反复启动不会报错，旧库也不会丢数据。"""
    conn = get_conn()
    try:
        # 第一段：只做结构（DDL）。SQLite 的 DDL 会先提交已有事务，所以单独一段更清楚
        with conn:
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
            # ALTER TABLE ... ADD COLUMN 带非空默认值是安全操作，已有行自动填默认值，一行都不会丢
            columns = [row["name"] for row in conn.execute("PRAGMA table_info(records)")]
            if "account" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN account TEXT NOT NULL DEFAULT '现金'"
                )
            if "type" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'"
                )
            # v0.05 新增：账目指向分类表的外键。可空，老数据由下方回填
            if "category_id" not in columns:
                conn.execute("ALTER TABLE records ADD COLUMN category_id INTEGER")

            # 账户表：name 主键，balance 当前余额，group_name 大类（资金/储蓄/投资）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    name    TEXT PRIMARY KEY,
                    balance REAL NOT NULL DEFAULT 0
                )
                """
            )
            account_columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(accounts)")
            ]
            if "group_name" not in account_columns:
                # 老账户统一归到「资金账户」，用户之后可以在账户管理里改大类
                conn.execute(
                    "ALTER TABLE accounts ADD COLUMN group_name TEXT NOT NULL DEFAULT '资金账户'"
                )

            # 分类表：parent_id 自关联实现两级分类。parent_id 为 NULL 即一级分类
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id        INTEGER PRIMARY KEY AUTOINCREMENT,
                    name      TEXT    NOT NULL,
                    parent_id INTEGER REFERENCES categories(id)
                )
                """
            )
            # 同一父级下不允许同名。parent_id 为 NULL 时 COALESCE 成 0，避免 NULL 不参与唯一约束
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories "
                "ON categories (COALESCE(parent_id, 0), name)"
            )

        # 第二段：补种子数据 + 回填老数据（DML，失败可以整体回滚）
        with conn:
            _seed_categories(conn)
            _seed_accounts(conn)
            _backfill_category_ids(conn)
            # 老账目里出现过的自定义账户也补进账户表，否则列表里查不到它
            conn.execute(
                "INSERT OR IGNORE INTO accounts (name, balance, group_name) "
                "SELECT DISTINCT account, 0, ? FROM records",
                (DEFAULT_GROUP,),
            )
    finally:
        conn.close()  # with 只管事务，连接必须手动关


# ---------------- 分类 ----------------

def get_category(category_id):
    """按 id 取一个分类，取不到返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, parent_id FROM categories WHERE id = ?", (category_id,)
        ).fetchone()
        return _row_to_category(row) if row is not None else None
    finally:
        conn.close()


def ensure_category(name):
    """按名字找一级分类，没有就建一个（兼容老前端直接传分类文本的写法）。"""
    conn = get_conn()
    try:
        with conn:
            new_id = _ensure_category(conn, name, None)
        row = conn.execute(
            "SELECT id, name, parent_id FROM categories WHERE id = ?", (new_id,)
        ).fetchone()
        return _row_to_category(row)
    finally:
        conn.close()


def list_categories_tree():
    """返回两级分类树：[{id, name, children: [...]}]，一级在前、按创建顺序排。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, parent_id FROM categories ORDER BY id"
        ).fetchall()
    finally:
        conn.close()

    # 先摆一级，再往对应父级里塞二级。分两趟，避免依赖行的先后顺序
    tops = {}
    tree = []
    for row in rows:
        if row["parent_id"] is None:
            node = _row_to_category(row)
            tops[node["id"]] = node
            tree.append(node)
    for row in rows:
        if row["parent_id"] is not None:
            parent = tops.get(row["parent_id"])
            if parent is not None:  # 父级不存在的孤儿行直接跳过，不会渲染成幽灵节点
                parent["children"].append(_row_to_category(row))
    return tree


def create_category(name, parent_id=None):
    """新建分类，返回 (分类字典, 错误信息)。parent_id 为空表示一级分类。"""
    conn = get_conn()
    try:
        with conn:
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT id, parent_id FROM categories WHERE id = ?", (parent_id,)
                ).fetchone()
                if parent is None:
                    return None, "父级分类不存在"
                if parent["parent_id"] is not None:
                    return None, "最多支持两级分类，二级分类下不能再建子分类"

            if parent_id is None:
                dup = conn.execute(
                    "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL",
                    (name,),
                ).fetchone()
            else:
                dup = conn.execute(
                    "SELECT id FROM categories WHERE name = ? AND parent_id = ?",
                    (name, parent_id),
                ).fetchone()
            if dup is not None:
                return None, "同级下已存在同名分类"

            cur = conn.execute(
                "INSERT INTO categories (name, parent_id) VALUES (?, ?)", (name, parent_id)
            )
            return {
                "id": cur.lastrowid,
                "name": name,
                "parent_id": parent_id,
                "children": [],
            }, None
    finally:
        conn.close()


def rename_category(category_id, name):
    """给分类改名，返回 (分类字典, 错误信息)。不支持改父级（改层级容易把历史账目搞乱）。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT id, name, parent_id FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if row is None:
                return None, "分类不存在"

            if row["parent_id"] is None:
                dup = conn.execute(
                    "SELECT id FROM categories WHERE name = ? AND parent_id IS NULL AND id <> ?",
                    (name, category_id),
                ).fetchone()
            else:
                dup = conn.execute(
                    "SELECT id FROM categories "
                    "WHERE name = ? AND parent_id = ? AND id <> ?",
                    (name, row["parent_id"], category_id),
                ).fetchone()
            if dup is not None:
                return None, "同级下已存在同名分类"

            conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
            # 账目里冗余存着分类名，改名要跟着改，否则列表还显示旧名字
            conn.execute(
                "UPDATE records SET category = ? WHERE category_id = ?", (name, category_id)
            )
            return {
                "id": category_id,
                "name": name,
                "parent_id": row["parent_id"],
                "children": [],
            }, None
    finally:
        conn.close()


def delete_category(category_id):
    """删分类，返回 (是否删除, 错误信息)。有子分类或被账目使用就拒绝，避免出现悬空引用。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT id, name FROM categories WHERE id = ?", (category_id,)
            ).fetchone()
            if row is None:
                return False, "分类不存在"

            children = conn.execute(
                "SELECT COUNT(*) AS c FROM categories WHERE parent_id = ?", (category_id,)
            ).fetchone()["c"]
            if children:
                return False, "该分类下还有 %d 个子分类，请先删掉子分类" % children

            used = conn.execute(
                "SELECT COUNT(*) AS c FROM records WHERE category_id = ?", (category_id,)
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目在用这个分类，删了会让它们失去分类" % used

            conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            return True, None
    finally:
        conn.close()


def get_all_categories():
    """一级分类名字列表。给旧模板的下拉框用，保持向后兼容。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM categories WHERE parent_id IS NULL ORDER BY id"
        ).fetchall()
        return [row["name"] for row in rows]
    finally:
        conn.close()


# ---------------- 账户 ----------------

def list_accounts():
    """返回所有账户及余额、大类。按插入顺序排，展示时不会一会儿现金一会儿银行卡。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name, balance, group_name FROM accounts ORDER BY rowid"
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def list_accounts_grouped():
    """按大类分组返回账户：[{name: 大类, accounts: [...]}]，前端直接用 <optgroup>。"""
    accounts = list_accounts()
    groups = [{"name": group, "accounts": []} for group in ACCOUNT_GROUPS]
    index = {group["name"]: group for group in groups}
    for account in accounts:
        # 大类名不认识（老数据/手改过库）就塞进第一个组，不让账户凭空消失
        index.get(account["group_name"], groups[0])["accounts"].append(account)
    return groups


def create_account(name, group_name=DEFAULT_GROUP, balance=0):
    """新建账户，返回 (账户字典, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            if group_name not in ACCOUNT_GROUPS:
                return None, "未知的账户大类：%s" % group_name
            exists = conn.execute(
                "SELECT name FROM accounts WHERE name = ?", (name,)
            ).fetchone()
            if exists is not None:
                return None, "账户已存在"
            conn.execute(
                "INSERT INTO accounts (name, balance, group_name) VALUES (?, ?, ?)",
                (name, round(balance, 2), group_name),
            )
            return {"name": name, "balance": round(balance, 2), "group_name": group_name}, None
    finally:
        conn.close()


def update_account(name, balance=None, group_name=None):
    """改账户余额和/或大类，返回 (账户字典, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT name, balance, group_name FROM accounts WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return None, "账户不存在"
            if group_name is not None and group_name not in ACCOUNT_GROUPS:
                return None, "未知的账户大类：%s" % group_name

            new_balance = row["balance"] if balance is None else round(balance, 2)
            new_group = row["group_name"] if group_name is None else group_name
            conn.execute(
                "UPDATE accounts SET balance = ?, group_name = ? WHERE name = ?",
                (new_balance, new_group, name),
            )
            return {"name": name, "balance": new_balance, "group_name": new_group}, None
    finally:
        conn.close()


def delete_account(name):
    """删账户，返回 (是否删除, 错误信息)。还有账目引用它就不让删。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT name FROM accounts WHERE name = ?", (name,)
            ).fetchone()
            if row is None:
                return False, "账户不存在"

            used = conn.execute(
                "SELECT COUNT(*) AS c FROM records WHERE account = ?", (name,)
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目在这个账户下，先处理掉再删" % used

            conn.execute("DELETE FROM accounts WHERE name = ?", (name,))
            return True, None
    finally:
        conn.close()


def get_all_accounts():
    """账户名字列表。给旧模板的下拉框用，保持向后兼容。"""
    return [account["name"] for account in list_accounts()]


# ---------------- 账目 ----------------

def add_record(
    amount,
    category,
    note,
    date,
    account=DEFAULT_ACCOUNT,
    record_type=DEFAULT_TYPE,
    category_id=None,
):
    """插入一笔账并联动余额，返回数据库自动分配的 id。

    写账目和改余额在同一个 conn、同一个事务里，要么都成功要么都回滚。
    """
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO records (amount, category, category_id, note, date, account, type)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    amount,
                    category,
                    category_id,
                    note,
                    normalize_date(date),
                    account,
                    record_type,
                ),
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
    category_id=None,
):
    """按 id 整条覆盖更新，并修正两个账户的余额。更新到了返回 True。

    余额修正分两步，顺序不能反：先撤销旧账，再加新账。
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
                   SET amount = ?, category = ?, category_id = ?, note = ?, date = ?,
                       account = ?, type = ?
                 WHERE id = ?
                """,
                (
                    amount,
                    category,
                    category_id,
                    note,
                    normalize_date(date),
                    account,
                    record_type,
                    record_id,
                ),
            )
            _apply_balance(conn, old["account"], -_signed(old["amount"], old["type"]))
            _apply_balance(conn, account, _signed(amount, record_type))
            return True
    finally:
        conn.close()


def delete_record(record_id):
    """按 id 删除一条记录，并把余额回滚。删到了返回 True。"""
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


def list_records(account=None, category_id=None, parent_id=None):
    """取出账目，最新记的排最前。

    三个筛选条件可以叠加：账户名、具体分类、一级分类（含它的所有二级）。
    顺带 LEFT JOIN 出二级分类的父级名，前端能显示「餐饮 / 早餐」。
    """
    sql = (
        "SELECT r.id, r.amount, r.category, r.category_id, r.note, r.date, "
        "       r.account, r.type, p.name AS category_parent "
        "  FROM records r "
        "  LEFT JOIN categories c ON c.id = r.category_id "
        "  LEFT JOIN categories p ON p.id = c.parent_id"
    )
    conditions = []
    params = []
    if account:
        conditions.append("r.account = ?")
        params.append(account)
    if category_id is not None:
        conditions.append("r.category_id = ?")
        params.append(category_id)
    if parent_id is not None:
        # 一级分类筛选：命中它自己，也命中挂在它下面的所有二级分类
        conditions.append("r.category_id IN (SELECT id FROM categories WHERE id = ? OR parent_id = ?)")
        params.extend([parent_id, parent_id])
    if conditions:
        sql += " WHERE " + " AND ".join(conditions)
    sql += " ORDER BY r.id DESC"

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["date"] = normalize_date(record["date"])
        return records
    finally:
        conn.close()


def get_statistics():
    """总览：总收入、总支出、总余额。

    - 总收入 / 总支出：按 type 分别求和，COALESCE 保证没有记录时是 0 而不是 NULL
    - 总余额：直接 SUM(accounts.balance)，账户表才是余额的唯一真相
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
