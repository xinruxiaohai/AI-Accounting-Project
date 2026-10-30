import datetime
import difflib
import json
import re
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

# 账目类型：expense = 支出（余额减），income = 收入（余额加），
# transfer = 转账（转出账户减「金额 + 手续费」，转入账户加金额）
RECORD_TYPES = ("expense", "income", "transfer")
DEFAULT_TYPE = "expense"

# 转账记录没有分类概念，category 固定存这个名字，列表里就显示成「转账」
TRANSFER_CATEGORY = "转账"

# 公式（比如 "15.5+20*2"）只做留存展示，不参与任何计算，长度限制防止存进一整段垃圾文本
MAX_FORMULA_LENGTH = 200


class RecordError(Exception):
    """写账目时的业务校验失败（转账余额不足、转出转入账户相同等）。

    add_record / update_record 内部抛它，`with conn:` 会自动回滚整个事务，
    外层捕获后转成 400，保证「要么全成功、要么什么都没发生」。
    """


def get_conn():
    """开一个新连接。sqlite3 的连接不能跨线程共用，所以每次用完就关。"""
    conn = sqlite3.connect(DB_PATH)
    # 打开 row_factory 后，查询结果可以用 row["amount"] 按列名取，不用记下标
    conn.row_factory = sqlite3.Row
    return conn


def _balance_effects(record_type, account, to_account, amount, fee):
    """把一笔账换算成「哪些账户的余额要加减多少」。

    返回 [(账户名, 变化量), ...]：
    - expense  支出：本账户 -金额
    - income   收入：本账户 +金额
    - transfer 转账：转出账户 -(金额 + 手续费)，转入账户 +金额

    新增、编辑、删除都复用这一个函数，回滚时把它整体取反即可，
    不会出现「某处算支出、某处算转账」两套规则对不上的情况。
    """
    if record_type == "income":
        return [(account, amount)]
    if record_type == "transfer":
        return [(account, -(amount + fee)), (to_account, amount)]
    return [(account, -amount)]


def _reverse_effects(effects):
    """把余额影响整体取反，用于删除或编辑时撤销旧账。"""
    return [(name, -delta) for name, delta in effects]


def _apply_effects(conn, effects):
    """按 (账户, 变化量) 列表逐个改余额，全部在调用方的事务里完成。"""
    for name, delta in effects:
        # 转账里 to_account 可能是空串（异常数据保护），空账户名直接跳过
        if not name:
            continue
        _apply_balance(conn, name, delta)


def _debt_effects(debt_type, account, amount):
    """借贷对资金账户的影响：借出扣钱，借入加钱。"""
    return [(account, -amount if debt_type == "lend" else amount)]


def _debt_balance_problem(conn, account):
    """借贷必须落到一个真实存在的资金账户上，否则余额无处加减。"""
    row = conn.execute("SELECT 1 FROM accounts WHERE name = ?", (account,)).fetchone()
    return None if row is not None else "账户「%s」不存在" % account


def _transfer_problem(conn, account, to_account, amount, fee):
    """转账的业务校验，没问题返回 None，有问题返回给用户看的中文原因。"""
    if not to_account:
        return "转账必须指定转入账户"
    if to_account == account:
        return "转出账户和转入账户不能相同"

    # 转账不像支出可以透支：两个账户必须真实存在，否则钱会转移到一个凭空冒出来的账户里
    for name in (account, to_account):
        row = conn.execute(
            "SELECT name FROM accounts WHERE name = ?", (name,)
        ).fetchone()
        if row is None:
            return "账户不存在：%s" % name

    balance = conn.execute(
        "SELECT balance FROM accounts WHERE name = ?", (account,)
    ).fetchone()["balance"]
    cost = amount + fee
    # 留 1e-9 的余量：0.1 + 0.2 这种浮点误差不该被判成「余额不足」
    if balance + 1e-9 < cost:
        return "转出账户余额不足：当前 %.2f，本次需要 %.2f" % (balance, cost)
    return None


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


def _seed_notifications(conn):
    """通知表为空时插一条上线通知，免得前台第一次点信封是空白页。"""
    count = conn.execute("SELECT COUNT(*) AS n FROM notifications").fetchone()["n"]
    if count:
        return
    conn.execute(
        "INSERT INTO notifications (title, content, image_url, publish_date) "
        "VALUES (?, ?, ?, ?)",
        (
            "v0.06.2-DEV 上线，全新三栏看板与暗黑模式！",
            "三栏 Dashboard、纯色日历热力图、账单详情弹窗、通知中心已经就位；"
            "点击右上角信封图标查看通知，月亮图标一键切换深色模式。",
            "",
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        ),
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
    # 这一轮是不是刚补的 sort_order 列：只有刚补时才按旧顺序回填，
    # 否则每次启动都会把用户拖拽出来的顺序重置回「按 id / rowid」
    categories_need_order = False
    accounts_need_order = False
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
                    type     TEXT    NOT NULL DEFAULT 'expense',
                    formula  TEXT    NOT NULL DEFAULT '',
                    to_account TEXT  NOT NULL DEFAULT '',
                    fee      REAL    NOT NULL DEFAULT 0,
                    deleted_at TEXT,
                    is_reimbursable INTEGER NOT NULL DEFAULT 0,
                    reimbursement_contact_id INTEGER,
                    reimbursed_amount REAL NOT NULL DEFAULT 0,
                    total_reimbursement REAL NOT NULL DEFAULT 0,
                    image_path TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT ''
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
            # v0.06 新增：公式留存、转账的转入账户与手续费
            if "formula" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN formula TEXT NOT NULL DEFAULT ''"
                )
            if "to_account" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN to_account TEXT NOT NULL DEFAULT ''"
                )
            if "fee" not in columns:
                conn.execute("ALTER TABLE records ADD COLUMN fee REAL NOT NULL DEFAULT 0")
            # v0.07 新增：软删除与报销。默认值让老数据保持「未删除、不报销、已报 0 元」
            if "deleted_at" not in columns:
                conn.execute("ALTER TABLE records ADD COLUMN deleted_at TEXT")
            if "is_reimbursable" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN is_reimbursable INTEGER NOT NULL DEFAULT 0"
                )
            if "reimbursement_contact_id" not in columns:
                conn.execute("ALTER TABLE records ADD COLUMN reimbursement_contact_id INTEGER")
            if "reimbursed_amount" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN reimbursed_amount REAL NOT NULL DEFAULT 0"
                )
            if "total_reimbursement" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN total_reimbursement REAL NOT NULL DEFAULT 0"
                )
            # v0.11 新增：截图记账的原图相对路径（空串表示没有截图）
            if "image_path" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN image_path TEXT NOT NULL DEFAULT ''"
                )
            # v0.11.4 新增：入库时间，10 分钟防重复检测靠它判断「最近刚记过没有」。
            # 老数据补空串，表示「时间未知」，不会被误判成刚才记的。
            if "created_at" not in columns:
                conn.execute(
                    "ALTER TABLE records ADD COLUMN created_at TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_created ON records (created_at)"
            )

            # 账户表：name 主键，balance 当前余额，group_name 大类（资金/储蓄/投资）
            # sort_order 供「账户管理」里拖拽排序，新账户一律排到同组最后
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    name       TEXT PRIMARY KEY,
                    balance    REAL NOT NULL DEFAULT 0,
                    group_name TEXT NOT NULL DEFAULT '资金账户',
                    sort_order INTEGER NOT NULL DEFAULT 0
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
            if "sort_order" not in account_columns:
                conn.execute(
                    "ALTER TABLE accounts ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
                )
                accounts_need_order = True

            # 分类表：parent_id 自关联实现两级分类。parent_id 为 NULL 即一级分类
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL,
                    parent_id  INTEGER REFERENCES categories(id),
                    sort_order INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            category_columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(categories)")
            ]
            if "sort_order" not in category_columns:
                conn.execute(
                    "ALTER TABLE categories ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
                )
                categories_need_order = True
            # 同一父级下不允许同名。parent_id 为 NULL 时 COALESCE 成 0，避免 NULL 不参与唯一约束
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories "
                "ON categories (COALESCE(parent_id, 0), name)"
            )

            # 通知表（v0.06.2）：开发者发布，前台右上角信封图标里按发布倒序展示。
            # image_url 存 /static/uploads/xxx 这种站内相对路径，没有图就空串
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS notifications (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    title        TEXT    NOT NULL,
                    content      TEXT    NOT NULL DEFAULT '',
                    image_url    TEXT    NOT NULL DEFAULT '',
                    publish_date TEXT    NOT NULL,
                    visible_at   TEXT    NOT NULL DEFAULT '',
                    status       TEXT    NOT NULL DEFAULT 'published'
                )
                """
            )
            # v0.11.1 新增：status 区分草稿与已发布。老表升级时补列，历史通知一律视为已发布
            notify_columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(notifications)")
            ]
            if "status" not in notify_columns:
                conn.execute(
                    "ALTER TABLE notifications ADD COLUMN status TEXT NOT NULL DEFAULT 'published'"
                )
            # v0.11.7：visible_at = 生效时间，publish_date 只负责「展示时间」。
            # 老数据没有这一列：补列后把 publish_date 回填进去，历史通知立即可见
            if "visible_at" not in notify_columns:
                conn.execute(
                    "ALTER TABLE notifications ADD COLUMN visible_at TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "UPDATE notifications SET visible_at = publish_date "
                "WHERE visible_at IS NULL OR visible_at = ''"
            )
            # 前台只查 published，后台分开查草稿与已发布，状态索引避免全表扫
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_status "
                "ON notifications (status)"
            )

            # 站点级配置（v0.11.1）：目前只放访问密码（逗号分隔的加盐哈希）与验证超时分钟数。
            # 单行 key/value 结构，后续新配置直接加 key，不用再改表。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS admin_config (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
                """
            )
            # 访问会话（v0.11.1）：验证成功发一个随机 token，前端每次请求带上；
            # 服务端按 created_at + verify_timeout 判定是否过期，过期即要求重新输入密码。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS access_sessions (
                    token      TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL
                )
                """
            )

            # 通讯录（v0.07）：name 唯一，避免同一人建两遍导致借贷对不上账
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS contacts (
                    id       INTEGER PRIMARY KEY AUTOINCREMENT,
                    name     TEXT    NOT NULL UNIQUE,
                    identity TEXT    NOT NULL DEFAULT '',
                    phone    TEXT    NOT NULL DEFAULT '',
                    wechat   TEXT    NOT NULL DEFAULT ''
                )
                """
            )

            # 借贷（v0.07）：lend=我借出（对方欠我），borrow=我借入（我欠对方）
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS debts (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    contact_id INTEGER NOT NULL REFERENCES contacts(id),
                    account    TEXT    NOT NULL DEFAULT '现金',
                    amount     REAL    NOT NULL,
                    type       TEXT    NOT NULL DEFAULT 'lend',
                    date       TEXT    NOT NULL,
                    status     TEXT    NOT NULL DEFAULT 'unpaid'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_debts_contact ON debts (contact_id)"
            )
            # 软删除过滤是每条账单查询的必经条件，单独建索引
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_records_deleted ON records (deleted_at)"
            )

            # AI 反馈记忆库（v0.10）：AI 解析失败 / 用户纠正的原始文本与结构化结果都留档，
            # 后台「AI 反馈与记忆」Tab 里逐条看，标成 processed 表示这条已经消化进 Prompt 迭代。
            # parsed_json / corrected_json 存 JSON 字符串（TEXT），status 只认 pending / processed。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_feedback (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    raw_text       TEXT    NOT NULL,
                    parsed_json    TEXT,
                    corrected_json TEXT,
                    source         TEXT,
                    status         TEXT    DEFAULT 'pending',
                    created_at     TEXT    DEFAULT CURRENT_TIMESTAMP,
                    updated_at     TEXT
                )
                """
            )
            # 后台默认按状态筛选 + 按时间倒序，状态索引让这个查询不必全表扫
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_ai_feedback_status "
                "ON ai_feedback (status)"
            )

            # AI 纠错记忆库（v0.11.4）：用户人工纠正分类后留一条，
            # 下次解析前取最近 3 条注入 Prompt，让模型「记住」这位用户的叫法。
            # 和 ai_feedback 分开存：feedback 是待消化的原始反馈，memory 是已经确认的纠错结论。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_memory (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    original_text      TEXT    NOT NULL,
                    raw_category       TEXT,
                    corrected_category TEXT    NOT NULL,
                    note               TEXT,
                    created_at         TEXT    DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

            # AI 纠错审计日志（v0.11.5）：气泡里多轮纠错、详情页改分类都留一条，
            # 后台「AI 纠错与反馈中心」右栏据此展示「改前 → 改后」对比。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_correction_log (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    record_id          INTEGER,
                    source             TEXT    NOT NULL DEFAULT 'bubble',
                    original_text      TEXT,
                    before_json        TEXT,
                    after_json         TEXT,
                    confidence         INTEGER,
                    auto_corrected_msg TEXT,
                    created_at         TEXT    DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

        # 第二段：补种子数据 + 回填老数据（DML，失败可以整体回滚）
        with conn:
            _seed_categories(conn)
            _seed_accounts(conn)
            _seed_notifications(conn)
            _backfill_category_ids(conn)
            # 只有刚补列的那一次才回填：分类按 id、账户按 rowid，
            # 正好等于升级前「按创建先后」的显示顺序
            if categories_need_order:
                conn.execute("UPDATE categories SET sort_order = id")
            # 老账目里出现过的自定义账户也补进账户表，否则列表里查不到它
            conn.execute(
                "INSERT OR IGNORE INTO accounts (name, balance, group_name) "
                "SELECT DISTINCT account, 0, ? FROM records",
                (DEFAULT_GROUP,),
            )
            # 账户回填放在补账户之后：新补进来的行 rowid 最大，理应排最后
            if accounts_need_order:
                conn.execute("UPDATE accounts SET sort_order = rowid")
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
            "SELECT id, name, parent_id FROM categories ORDER BY sort_order, id"
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

            sibling_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM categories WHERE parent_id IS ?",
                (parent_id,),
            ).fetchone()["m"]
            cur = conn.execute(
                "INSERT INTO categories (name, parent_id, sort_order) VALUES (?, ?, ?)",
                (name, parent_id, sibling_order + 1),
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
                "SELECT COUNT(*) AS c FROM records "
                "WHERE category_id = ? AND deleted_at IS NULL",
                (category_id,),
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目在用这个分类，删了会让它们失去分类" % used

            conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
            return True, None
    finally:
        conn.close()


def reorder_categories(ids, parent_id=None):
    """按拖拽后的顺序重排某一级下的分类，返回错误信息（成功为 None）。

    只接受「同一父级」的完整 id 列表：一半一级、一半二级混着传会把树拖乱。
    """
    if not isinstance(ids, list) or not ids:
        return "ids 必须是非空数组"
    if len(ids) != len(set(ids)):
        return "ids 里有重复的分类"
    if any(isinstance(item, bool) or not isinstance(item, int) for item in ids):
        return "ids 必须全是整数"

    conn = get_conn()
    try:
        with conn:
            placeholders = ",".join("?" for _ in ids)
            rows = conn.execute(
                "SELECT id, parent_id FROM categories WHERE id IN (%s)" % placeholders,
                ids,
            ).fetchall()
            if len(rows) != len(ids):
                return "有分类不存在，刷新后再试"
            for row in rows:
                if (row["parent_id"] or None) != (parent_id or None):
                    return "只能重排同一父级下的分类"
            for index, category_id in enumerate(ids):
                conn.execute(
                    "UPDATE categories SET sort_order = ? WHERE id = ?",
                    (index, category_id),
                )
            return None
    finally:
        conn.close()


def get_all_categories():
    """一级分类名字列表。给旧模板的下拉框用，保持向后兼容。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM categories WHERE parent_id IS NULL ORDER BY sort_order, id"
        ).fetchall()
        return [row["name"] for row in rows]
    finally:
        conn.close()


# ---------------- 账户 ----------------

def list_accounts():
    """返回所有账户及余额、大类。按插入顺序排，展示时不会一会儿现金一会儿银行卡。

    余额是 SQLite 里一条条 UPDATE 累加出来的浮点数，会留 78.19999999999999 这种尾巴。
    这里是所有「读账户」的必经之路，出口统一收敛到两位小数，
    保证前端 / 模板 / 统计永远只拿到 78.2。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name, balance, group_name FROM accounts ORDER BY sort_order, rowid"
        ).fetchall()
        accounts = []
        for row in rows:
            account = dict(row)
            account["balance"] = round(account["balance"], 2)
            accounts.append(account)
        return accounts
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
            account_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM accounts"
            ).fetchone()["m"]
            conn.execute(
                "INSERT INTO accounts (name, balance, group_name, sort_order) "
                "VALUES (?, ?, ?, ?)",
                (name, round(balance, 2), group_name, account_order + 1),
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

            # 只改大类时余额原样返回，但也要收敛，否则前端拿到库里的浮点尾巴
            new_balance = round(row["balance"], 2) if balance is None else round(balance, 2)
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
                "SELECT COUNT(*) AS c FROM records "
                "WHERE (account = ? OR (type = 'transfer' AND to_account = ?)) "
                "  AND deleted_at IS NULL",
                (name, name),
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目和这个账户有关，先处理掉再删" % used

            conn.execute("DELETE FROM accounts WHERE name = ?", (name,))
            return True, None
    finally:
        conn.close()


def rename_account(old_name, new_name):
    """账户改名（v0.11.6）：accounts 主键 + 所有引用这个账户名的账目/借贷一起改。

    account / to_account / debts.account 都是纯文本列（没有外键），所以改名必须
    在这里一次性同步，否则旧名字的账目会变成「幽灵账户」。
    返回 (账户字典, 错误信息)。
    """
    old_name = str(old_name or "").strip()
    new_name = str(new_name or "").strip()
    if not old_name:
        return None, "原账户名不能为空"
    if not new_name:
        return None, "新账户名不能为空"

    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT name, balance, group_name FROM accounts WHERE name = ?",
                (old_name,),
            ).fetchone()
            if row is None:
                return None, "账户不存在"
            if new_name == old_name:
                return {
                    "name": old_name,
                    "balance": round(row["balance"], 2),
                    "group_name": row["group_name"],
                }, None
            exists = conn.execute(
                "SELECT name FROM accounts WHERE name = ?", (new_name,)
            ).fetchone()
            if exists is not None:
                return None, "账户名「%s」已存在" % new_name

            conn.execute(
                "UPDATE accounts SET name = ? WHERE name = ?", (new_name, old_name)
            )
            conn.execute(
                "UPDATE records SET account = ? WHERE account = ?", (new_name, old_name)
            )
            conn.execute(
                "UPDATE records SET to_account = ? WHERE to_account = ?",
                (new_name, old_name),
            )
            conn.execute(
                "UPDATE debts SET account = ? WHERE account = ?", (new_name, old_name)
            )
            return {
                "name": new_name,
                "balance": round(row["balance"], 2),
                "group_name": row["group_name"],
            }, None
    finally:
        conn.close()


def merge_account(source, target):
    """把 source 账户合并进 target（v0.11.6）：余额相加、账目/借贷迁移，再删掉 source。

    用于 AI 自动建户后用户发现「这其实是我已有的账户」：合并后不会生成任何
    未记账的差额，因为源账户余额原样加进目标账户。
    返回 (合并后的目标账户字典, 错误信息)。
    """
    source = str(source or "").strip()
    target = str(target or "").strip()
    if not source or not target:
        return None, "源账户与目标账户都不能为空"
    if source == target:
        return None, "不能合并到它自己"

    conn = get_conn()
    try:
        with conn:
            src = conn.execute(
                "SELECT name, balance, group_name FROM accounts WHERE name = ?", (source,)
            ).fetchone()
            if src is None:
                return None, "账户「%s」不存在" % source
            tgt = conn.execute(
                "SELECT name, balance, group_name FROM accounts WHERE name = ?", (target,)
            ).fetchone()
            if tgt is None:
                return None, "账户「%s」不存在" % target

            new_balance = round(float(src["balance"] or 0) + float(tgt["balance"] or 0), 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE name = ?", (new_balance, target)
            )
            conn.execute(
                "UPDATE records SET account = ? WHERE account = ?", (target, source)
            )
            conn.execute(
                "UPDATE records SET to_account = ? WHERE to_account = ?", (target, source)
            )
            conn.execute(
                "UPDATE debts SET account = ? WHERE account = ?", (target, source)
            )
            conn.execute("DELETE FROM accounts WHERE name = ?", (source,))
            return {
                "name": target,
                "balance": new_balance,
                "group_name": tgt["group_name"],
            }, None
    finally:
        conn.close()


def set_records_category(record_ids, category_name):
    """批量改分类（v0.11.6）：只动 category / category_id，不重算余额、不校验账户。

    返回 (成功改动的条数, 错误信息)。分类不存在会自动建一个二级分类。
    """
    if not isinstance(record_ids, (list, tuple)) or not record_ids:
        return 0, "record_ids 必须是非空数组"
    try:
        ids = [int(item) for item in record_ids]
    except (TypeError, ValueError):
        return 0, "record_ids 里必须都是整数"

    try:
        category = ensure_category(category_name)
    except RecordError as error:
        return 0, str(error)

    conn = get_conn()
    try:
        with conn:
            changed = 0
            for record_id in ids:
                cursor = conn.execute(
                    "UPDATE records SET category = ?, category_id = ? "
                    "WHERE id = ? AND deleted_at IS NULL",
                    (category["name"], category["id"], record_id),
                )
                changed += cursor.rowcount
            return changed, None
    finally:
        conn.close()


def reorder_accounts(names):
    """按拖拽后的顺序重排账户（跨大类一起排），返回错误信息（成功为 None）。

    账户列表是「全量顺序」，分组只是展示时再按大类切开，
    所以拖到别的组里也不算错——只要名字都在。
    """
    if not isinstance(names, list) or not names:
        return "names 必须是非空数组"
    if len(names) != len(set(names)):
        return "names 里有重复的账户"

    conn = get_conn()
    try:
        with conn:
            rows = conn.execute(
                "SELECT name FROM accounts WHERE name IN (%s)"
                % ",".join("?" for _ in names),
                names,
            ).fetchall()
            if len(rows) != len(names):
                return "有账户不存在，刷新后再试"
            for index, name in enumerate(names):
                conn.execute(
                    "UPDATE accounts SET sort_order = ? WHERE name = ?", (index, name)
                )
            return None
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
    formula="",
    to_account="",
    fee=0,
    is_reimbursable=0,
    reimbursement_contact_id=None,
    reimbursed_amount=0,
    total_reimbursement=0,
    image_path="",
):
    """插入一笔账并联动余额，返回 (新 id, 错误信息)。

    写账目和改余额在同一个 conn、同一个事务里，要么都成功要么都回滚。
    转账会先校验两个账户和转出余额，校验不过抛 RecordError，整个事务回滚。

    报销字段是 v0.10 新增的**可选**参数（默认全不报销），老调用方不传时行为完全不变；
    AI 代买 / 垫付场景由 app.py 在写库时一并带进来，避免「先写普通记录再改报销」两步。
    """
    conn = get_conn()
    try:
        with conn:
            if record_type == "transfer":
                problem = _transfer_problem(conn, account, to_account, amount, fee)
                if problem is not None:
                    raise RecordError(problem)

            cur = conn.execute(
                """
                INSERT INTO records
                       (amount, category, category_id, note, date, account, type,
                        formula, to_account, fee, is_reimbursable,
                        reimbursement_contact_id, reimbursed_amount, total_reimbursement,
                        image_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                """,
                (
                    amount,
                    category,
                    category_id,
                    note,
                    normalize_date(date),
                    account,
                    record_type,
                    formula,
                    to_account,
                    fee,
                    1 if is_reimbursable else 0,
                    reimbursement_contact_id,
                    round(float(reimbursed_amount), 2),
                    round(float(total_reimbursement), 2),
                    image_path or "",
                ),
            )
            _apply_effects(
                conn,
                _balance_effects(record_type, account, to_account, amount, fee),
            )
            return cur.lastrowid, None
    except RecordError as exc:
        # 事务已经回滚，账目和余额都没动
        return None, str(exc)
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
    formula="",
    to_account="",
    fee=0,
):
    """按 id 整条覆盖更新，并修正余额，返回 (是否更新到, 错误信息)。

    余额修正分三步，顺序不能反：
    1. 先撤销旧账（把旧的影响整体取反）
    2. 再校验新账（转账要看撤销后的余额，否则「把转出账户从 A 改成 B」会误判余额不足）
    3. 最后加新账
    第 2 步失败时抛 RecordError，连同第 1 步的撤销一起回滚。
    """
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type, to_account, fee FROM records WHERE id = ?",
                (record_id,),
            ).fetchone()
            if old is None:
                return False, None

            _apply_effects(
                conn,
                _reverse_effects(
                    _balance_effects(
                        old["type"], old["account"], old["to_account"], old["amount"], old["fee"]
                    )
                ),
            )

            if record_type == "transfer":
                problem = _transfer_problem(conn, account, to_account, amount, fee)
                if problem is not None:
                    raise RecordError(problem)

            conn.execute(
                """
                UPDATE records
                   SET amount = ?, category = ?, category_id = ?, note = ?, date = ?,
                       account = ?, type = ?, formula = ?, to_account = ?, fee = ?
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
                    formula,
                    to_account,
                    fee,
                    record_id,
                ),
            )
            _apply_effects(
                conn,
                _balance_effects(record_type, account, to_account, amount, fee),
            )
            return True, None
    except RecordError as exc:
        return False, str(exc)
    finally:
        conn.close()


def delete_record(record_id):
    """按 id 删除一条记录，并把余额回滚。删到了返回 True。"""
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type, to_account, fee FROM records WHERE id = ?",
                (record_id,),
            ).fetchone()
            if old is None:
                return False

            conn.execute("DELETE FROM records WHERE id = ?", (record_id,))
            _apply_effects(
                conn,
                _reverse_effects(
                    _balance_effects(
                        old["type"], old["account"], old["to_account"], old["amount"], old["fee"]
                    )
                ),
            )
            return True
    finally:
        conn.close()


_RECORD_SELECT = (
    "SELECT r.id, r.amount, r.category, r.category_id, r.note, r.date, "
    "       r.account, r.type, r.formula, r.to_account, r.fee, "
    "       r.is_reimbursable, r.reimbursement_contact_id, r.reimbursed_amount, "
    "       r.total_reimbursement, r.deleted_at, r.image_path, "
    "       p.name AS category_parent, ct.name AS reimbursement_contact_name "
    "  FROM records r "
    "  LEFT JOIN categories c ON c.id = r.category_id "
    "  LEFT JOIN categories p ON p.id = c.parent_id "
    "  LEFT JOIN contacts ct ON ct.id = r.reimbursement_contact_id"
)


def list_records(account=None, category_id=None, parent_id=None):
    """取出账目，最新记的排最前。

    三个筛选条件可以叠加：账户名、具体分类、一级分类（含它的所有二级）。
    顺带 LEFT JOIN 出二级分类的父级名和报销人姓名，前端一次拿全。
    """
    sql = _RECORD_SELECT
    conditions = ["r.deleted_at IS NULL"]
    params = []
    if account:
        # 转账会同时牵动转出和转入两个账户，查任何一个账户都该看到这笔转账
        conditions.append("(r.account = ? OR (r.type = 'transfer' AND r.to_account = ?))")
        params.extend([account, account])
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


def search_records(keyword, limit=200):
    """全局搜索账目（v0.11.8）：备注 / 分类 / 账户 / 金额都能搜，最新记的排最前。

    关键词只做 LIKE 包含匹配，% 和 _ 先转义掉，避免用户输入把整库匹配出来；
    limit 夹在 1~500 之间，前端按 10 条一批自己分段渲染。
    """
    text = (keyword or "").strip()
    if not text:
        return []
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    like = "%" + escaped + "%"
    try:
        limit = max(1, min(500, int(limit)))
    except (TypeError, ValueError):
        limit = 200

    sql = (
        _RECORD_SELECT
        + " WHERE r.deleted_at IS NULL AND ("
        + "r.note LIKE ? ESCAPE '\\' OR r.category LIKE ? ESCAPE '\\'"
        + " OR r.account LIKE ? ESCAPE '\\' OR r.to_account LIKE ? ESCAPE '\\'"
        + " OR CAST(r.amount AS TEXT) LIKE ? ESCAPE '\\'"
        + ") ORDER BY r.id DESC LIMIT ?"
    )
    conn = get_conn()
    try:
        rows = conn.execute(sql, (like, like, like, like, like, limit)).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["date"] = normalize_date(record["date"])
        return records
    finally:
        conn.close()


def list_records_with_images():
    """相册：取出所有带截图凭证的账目，最新记的排最前。

    回收站里的账目不算（图还在，但用户在相册里看到的应该只是有效账目）；
    排序用 id 而不是 date，保证「刚识别的那张」一定在最前面。
    """
    sql = (
        _RECORD_SELECT
        + " WHERE r.deleted_at IS NULL"
        + "   AND r.image_path IS NOT NULL AND r.image_path <> ''"
        + " ORDER BY r.id DESC"
    )
    conn = get_conn()
    try:
        rows = conn.execute(sql).fetchall()
    finally:
        conn.close()
    return [dict(row) for row in rows]


def set_record_image(record_id, image_path):
    """给账目挂上/换掉/清空截图路径，只改这一列，不动余额和其它字段。

    返回是否命中这条账目；传空字符串表示解绑（相册里删图时用）。
    """
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE records SET image_path = ? WHERE id = ?",
                (image_path or "", record_id),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def get_record(record_id):
    """按 id 取一条账目（带报销字段与报销人姓名），不存在返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(_RECORD_SELECT + " WHERE r.id = ?", (record_id,)).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["date"] = normalize_date(record["date"])
        return record
    finally:
        conn.close()


def set_record_reimbursement(
    record_id,
    is_reimbursable,
    contact_id=None,
    total_reimbursement=0,
    reimbursed_amount=0,
):
    """更新一条账目的报销设置，返回 (是否更新到, 错误信息)。

    - 关闭报销：四个字段一起清零，历史数据不会留半截
    - 开启报销：只允许支出账目，报销人必须真实存在，报销金额 0 < 金额 ≤ 账目金额，
      已报销金额落在 0 和报销金额之间
    - 报销不影响账户余额，这是「公司/别人会还我」的标记，不是收付款
    """
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT type, amount FROM records WHERE id = ? AND deleted_at IS NULL",
                (record_id,),
            ).fetchone()
            if row is None:
                return False, None

            if not is_reimbursable:
                conn.execute(
                    """
                    UPDATE records
                       SET is_reimbursable = 0, reimbursement_contact_id = NULL,
                           reimbursed_amount = 0, total_reimbursement = 0
                     WHERE id = ?
                    """,
                    (record_id,),
                )
                return True, None

            if row["type"] != "expense":
                return False, "只有支出账目可以报销"

            if contact_id is None:
                return False, "开启报销前请选择报销人"
            exists = conn.execute(
                "SELECT 1 FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if exists is None:
                return False, "报销人不存在"

            total = round(float(total_reimbursement), 2)
            amount = round(float(row["amount"]), 2)
            if total <= 0 or total > amount + 0.005:
                return False, "报销金额必须大于 0 且不超过账目金额"

            paid = round(float(reimbursed_amount), 2)
            if paid < 0 or paid > total + 0.005:
                return False, "已报销金额必须落在 0 和报销金额之间"

            conn.execute(
                """
                UPDATE records
                   SET is_reimbursable = 1, reimbursement_contact_id = ?,
                       reimbursed_amount = ?, total_reimbursement = ?
                 WHERE id = ?
                """,
                (contact_id, paid, total, record_id),
            )
            return True, None
    finally:
        conn.close()


def list_deleted_records():
    """回收站列表：deleted_at 不为空的账目，最近删除的排前面。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            _RECORD_SELECT
            + " WHERE r.deleted_at IS NOT NULL ORDER BY r.deleted_at DESC, r.id DESC"
        ).fetchall()
        records = [dict(row) for row in rows]
        for record in records:
            record["date"] = normalize_date(record["date"])
        return records
    finally:
        conn.close()


def soft_delete_record(record_id):
    """移到回收站：写 deleted_at 并回滚余额，账目本身保留。删到了返回 True。"""
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type, to_account, fee FROM records "
                "WHERE id = ? AND deleted_at IS NULL",
                (record_id,),
            ).fetchone()
            if old is None:
                return False
            conn.execute(
                "UPDATE records SET deleted_at = ? WHERE id = ?",
                (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), record_id),
            )
            _apply_effects(
                conn,
                _reverse_effects(
                    _balance_effects(
                        old["type"], old["account"], old["to_account"], old["amount"], old["fee"]
                    )
                ),
            )
            return True
    finally:
        conn.close()


def restore_record(record_id):
    """从回收站恢复：清掉 deleted_at 并把余额影响重新套上。恢复到返回 True。"""
    conn = get_conn()
    try:
        with conn:
            old = conn.execute(
                "SELECT account, amount, type, to_account, fee FROM records "
                "WHERE id = ? AND deleted_at IS NOT NULL",
                (record_id,),
            ).fetchone()
            if old is None:
                return False
            conn.execute("UPDATE records SET deleted_at = NULL WHERE id = ?", (record_id,))
            _apply_effects(
                conn,
                _balance_effects(
                    old["type"], old["account"], old["to_account"], old["amount"], old["fee"]
                ),
            )
            return True
    finally:
        conn.close()


def purge_record(record_id):
    """彻底删除：只允许删回收站里的账目，不再动余额。删到了返回 True。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "DELETE FROM records WHERE id = ? AND deleted_at IS NOT NULL", (record_id,)
            )
            return cur.rowcount > 0
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
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records "
            "WHERE type = 'income' AND deleted_at IS NULL"
        ).fetchone()["total"]
        expense_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records "
            "WHERE type = 'expense' AND deleted_at IS NULL"
        ).fetchone()["total"]
        balance_total = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS total FROM accounts"
        ).fetchone()["total"]
        reimb = conn.execute(
            "SELECT "
            "  COALESCE(SUM(MAX(total_reimbursement - reimbursed_amount, 0)), 0) AS pending, "
            "  COALESCE(SUM(reimbursed_amount), 0) AS done "
            "FROM records "
            "WHERE type = 'expense' AND is_reimbursable = 1 AND deleted_at IS NULL"
        ).fetchone()
    finally:
        conn.close()

    # 浮点数求和会有 0.30000000000000004 这类尾巴，四舍五入到分再返回
    return {
        "income_total": round(income_total, 2),
        "expense_total": round(expense_total, 2),
        "balance_total": round(balance_total, 2),
        "reimbursement_pending": round(reimb["pending"], 2),
        "reimbursement_done": round(reimb["done"], 2),
    }


# ---------------- 通讯录与借贷（v0.07） ----------------

DEBT_TYPES = ("lend", "borrow")  # lend=我借出（对方欠我），borrow=我借入（我欠对方）
DEBT_STATUSES = ("unpaid", "paid")


def _row_to_contact(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "identity": row["identity"],
        "phone": row["phone"],
        "wechat": row["wechat"],
    }


def list_contacts():
    """全部联系人，顺带带出借贷条数，前端列表不用逐个人再查一次。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT c.id, c.name, c.identity, c.phone, c.wechat, "
            "       COUNT(d.id) AS debt_count "
            "  FROM contacts c LEFT JOIN debts d ON d.contact_id = c.id "
            " GROUP BY c.id "
            " ORDER BY c.id"
        ).fetchall()
        contacts = []
        for row in rows:
            contact = _row_to_contact(row)
            contact["debt_count"] = row["debt_count"]
            contacts.append(contact)
        return contacts
    finally:
        conn.close()


def get_contact(contact_id):
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, name, identity, phone, wechat FROM contacts WHERE id = ?",
            (contact_id,),
        ).fetchone()
        return _row_to_contact(row) if row is not None else None
    finally:
        conn.close()


def create_contact(name, identity="", phone="", wechat=""):
    """新建联系人，返回 (联系人字典, 错误信息)。姓名重复直接拒绝。"""
    name = (name or "").strip()
    if not name:
        return None, "联系人姓名不能为空"

    conn = get_conn()
    contact_id = None
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO contacts (name, identity, phone, wechat) VALUES (?, ?, ?, ?)",
                (
                    name,
                    (identity or "").strip(),
                    (phone or "").strip(),
                    (wechat or "").strip(),
                ),
            )
            contact_id = cur.lastrowid
    except sqlite3.IntegrityError:
        return None, "联系人「%s」已存在" % name
    finally:
        conn.close()
    return get_contact(contact_id), None


def update_contact(contact_id, name=None, identity=None, phone=None, wechat=None):
    """改联系人，只改传进来的字段，返回 (联系人字典, 错误信息)。"""
    fields = {}
    if name is not None:
        name = name.strip()
        if not name:
            return None, "联系人姓名不能为空"
        fields["name"] = name
    for key, value in (("identity", identity), ("phone", phone), ("wechat", wechat)):
        if value is not None:
            fields[key] = value.strip()
    if not fields:
        return None, "没有要修改的字段"

    conn = get_conn()
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if exists is None:
                return None, "联系人不存在"
            assignments = ", ".join("%s = ?" % key for key in fields)
            conn.execute(
                "UPDATE contacts SET " + assignments + " WHERE id = ?",
                list(fields.values()) + [contact_id],
            )
    except sqlite3.IntegrityError:
        return None, "联系人姓名已存在"
    finally:
        conn.close()
    return get_contact(contact_id), None


def delete_contact(contact_id):
    """删联系人，返回 (是否删除, 错误信息)。还有借贷或报销关联时不让删。"""
    conn = get_conn()
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if exists is None:
                return False, "联系人不存在"

            debts_used = conn.execute(
                "SELECT COUNT(*) AS c FROM debts WHERE contact_id = ?", (contact_id,)
            ).fetchone()["c"]
            if debts_used:
                return False, "该联系人还有 %d 条借贷记录，先处理掉再删" % debts_used

            records_used = conn.execute(
                "SELECT COUNT(*) AS c FROM records "
                "WHERE reimbursement_contact_id = ? AND deleted_at IS NULL",
                (contact_id,),
            ).fetchone()["c"]
            if records_used:
                return False, "还有 %d 条账单关联这个联系人的报销" % records_used

            conn.execute("DELETE FROM contacts WHERE id = ?", (contact_id,))
            return True, None
    finally:
        conn.close()


def _row_to_debt(row):
    return {
        "id": row["id"],
        "contact_id": row["contact_id"],
        "contact_name": row["contact_name"],
        "account": row["account"],
        "amount": round(row["amount"], 2),
        "type": row["type"],
        "date": normalize_date(row["date"]),
        "status": row["status"],
    }


DEBT_SELECT = (
    "SELECT d.id, d.contact_id, c.name AS contact_name, d.account, d.amount, "
    "       d.type, d.date, d.status "
    "  FROM debts d JOIN contacts c ON c.id = d.contact_id"
)


def list_debts(contact_id=None, status=None):
    """借贷列表，新的排前面；可按联系人、结清状态筛选。"""
    conn = get_conn()
    try:
        sql = DEBT_SELECT
        conditions = []
        params = []
        if contact_id is not None:
            conditions.append("d.contact_id = ?")
            params.append(contact_id)
        if status:
            conditions.append("d.status = ?")
            params.append(status)
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY d.date DESC, d.id DESC"
        return [_row_to_debt(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_debt(debt_id):
    conn = get_conn()
    try:
        row = conn.execute(DEBT_SELECT + " WHERE d.id = ?", (debt_id,)).fetchone()
        return _row_to_debt(row) if row is not None else None
    finally:
        conn.close()


def _check_debt_amount(amount):
    """金额必须是大于 0 的有限数字，返回错误信息（合法为 None）。"""
    if isinstance(amount, bool) or not isinstance(amount, (int, float)):
        return "amount 必须是数字"
    if not (0 < float(amount) < float("inf")):
        return "amount 必须是大于 0 的数字"
    return None


def create_debt(
    contact_id,
    amount,
    debt_type="lend",
    account=DEFAULT_ACCOUNT,
    date=None,
    status="unpaid",
):
    """新增一条借贷，返回 (借贷字典, 错误信息)。"""
    if isinstance(contact_id, bool) or not isinstance(contact_id, int):
        return None, "contact_id 必须是整数"
    problem = _check_debt_amount(amount)
    if problem is not None:
        return None, problem
    if debt_type not in DEBT_TYPES:
        return None, "type 只能是 lend / borrow"
    if status not in DEBT_STATUSES:
        return None, "status 只能是 unpaid / paid"
    account = (account or "").strip()
    if not account:
        return None, "account 不能为空"
    if not date:
        date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    conn = get_conn()
    debt_id = None
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM contacts WHERE id = ?", (contact_id,)
            ).fetchone()
            if exists is None:
                return None, "联系人不存在"
            problem = _debt_balance_problem(conn, account)
            if problem is not None:
                return None, problem
            debt_id = 0
            cur = conn.execute(
                "INSERT INTO debts (contact_id, account, amount, type, date, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (contact_id, account, round(float(amount), 2), debt_type, normalize_date(date), status),
            )
            debt_id = cur.lastrowid
            # 借出=钱从账户出去，借入=钱进账户，和账单共用同一套余额规则
            _apply_effects(conn, _debt_effects(debt_type, account, round(float(amount), 2)))
    finally:
        conn.close()
    return get_debt(debt_id), None


def update_debt(
    debt_id,
    contact_id=None,
    amount=None,
    debt_type=None,
    account=None,
    date=None,
    status=None,
):
    """改借贷，只改传进来的字段，返回 (借贷字典, 错误信息)。"""
    fields = {}
    if contact_id is not None:
        if isinstance(contact_id, bool) or not isinstance(contact_id, int):
            return None, "contact_id 必须是整数"
        fields["contact_id"] = contact_id
    if amount is not None:
        problem = _check_debt_amount(amount)
        if problem is not None:
            return None, problem
        fields["amount"] = round(float(amount), 2)
    if debt_type is not None:
        if debt_type not in DEBT_TYPES:
            return None, "type 只能是 lend / borrow"
        fields["type"] = debt_type
    if account is not None:
        account = account.strip()
        if not account:
            return None, "account 不能为空"
        fields["account"] = account
    if date is not None:
        fields["date"] = normalize_date(date)
    if status is not None:
        if status not in DEBT_STATUSES:
            return None, "status 只能是 unpaid / paid"
        fields["status"] = status
    if not fields:
        return None, "没有要修改的字段"

    conn = get_conn()
    try:
        with conn:
            exists = conn.execute("SELECT 1 FROM debts WHERE id = ?", (debt_id,)).fetchone()
            if exists is None:
                return None, "借贷记录不存在"
            if "contact_id" in fields:
                contact = conn.execute(
                    "SELECT 1 FROM contacts WHERE id = ?", (fields["contact_id"],)
                ).fetchone()
                if contact is None:
                    return None, "联系人不存在"
            old = conn.execute(
                "SELECT account, amount, type FROM debts WHERE id = ?", (debt_id,)
            ).fetchone()
            new_account = fields.get("account", old["account"])
            if "account" in fields:
                problem = _debt_balance_problem(conn, new_account)
                if problem is not None:
                    return None, problem
            # 金额/类型/账户任一变化，先把旧影响整体撤回，再按新值记一次
            _apply_effects(
                conn, _reverse_effects(_debt_effects(old["type"], old["account"], old["amount"]))
            )
            _apply_effects(
                conn,
                _debt_effects(
                    fields.get("type", old["type"]),
                    new_account,
                    fields.get("amount", old["amount"]),
                ),
            )
            assignments = ", ".join("%s = ?" % key for key in fields)
            conn.execute(
                "UPDATE debts SET " + assignments + " WHERE id = ?",
                list(fields.values()) + [debt_id],
            )
    finally:
        conn.close()
    return get_debt(debt_id), None


def delete_debt(debt_id):
    """删除借贷，返回 (是否删除, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            exists = conn.execute(
                "SELECT account, amount, type FROM debts WHERE id = ?", (debt_id,)
            ).fetchone()
            if exists is None:
                return False, "借贷记录不存在"
            conn.execute("DELETE FROM debts WHERE id = ?", (debt_id,))
            # 删掉借贷就把当时动过的余额还回去
            _apply_effects(
                conn,
                _reverse_effects(
                    _debt_effects(exists["type"], exists["account"], exists["amount"])
                ),
            )
            return True, None
    finally:
        conn.close()


# ---------------- 通知（v0.06.2） ----------------


# 通知状态（v0.11.1）：draft=AI 起草或人工存草稿，待后台审核；published=前台可见
NOTIFICATION_STATUSES = ("draft", "published")
NOTIFICATION_COLUMNS = (
    "id, title, content, image_url, publish_date, visible_at, status"
)


def _row_to_notification(row):
    return {
        "id": row["id"],
        "title": row["title"],
        "content": row["content"],
        "image_url": row["image_url"],
        "publish_date": row["publish_date"],
        "visible_at": row["visible_at"] if "visible_at" in row.keys() else row["publish_date"],
        "status": row["status"] if "status" in row.keys() else "published",
    }


def list_notifications(status=None, visible_only=False):
    """通知列表，按展示时间倒序（新发的排最上面）。

    status 传 "published" 只给前台已发布列表，传 "draft" 是后台待审核草稿；
    visible_only=True 时只返回「已到生效时间」的已发布通知（前台严格用这个）。
    生效时间没到（比如设成明天）的通知今天绝对不可见。
    """
    sql = "SELECT " + NOTIFICATION_COLUMNS + " FROM notifications"
    params = []
    where = []
    if status:
        if status not in NOTIFICATION_STATUSES:
            raise RecordError("status 只能是 draft / published")
        where.append("status = ?")
        params.append(status)
    if visible_only:
        where.append("status = 'published'")
        where.append("visible_at <= ?")
        params.append(datetime.datetime.now().strftime("%Y-%m-%d %H:%M"))
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY publish_date DESC, id DESC"

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_notification(row) for row in rows]
    finally:
        conn.close()


def create_notification(
    title, content="", image_url="", publish_date=None, status="published", visible_at=None
):
    """发布一条通知（或存草稿），返回入库后的完整字典。

    v0.11.7 双时间：
    - publish_date 只作为「展示时间」；
    - visible_at 是「生效时间」，前台按它过滤；
    - 发布时间留空时用生效时间兜底；生效时间留空时用发布时间兜底。
    """
    title = (title or "").strip()
    if not title:
        raise RecordError("通知标题不能为空")

    status = (status or "published").strip()
    if status not in NOTIFICATION_STATUSES:
        raise RecordError("status 只能是 draft / published")

    publish_date = (publish_date or "").strip()
    visible_at = (visible_at or "").strip()
    if not publish_date:
        publish_date = visible_at or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    if not visible_at:
        visible_at = publish_date

    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO notifications "
                "       (title, content, image_url, publish_date, visible_at, status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (title, content or "", image_url or "", publish_date, visible_at, status),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT " + NOTIFICATION_COLUMNS + " FROM notifications WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_notification(row)
    finally:
        conn.close()


def publish_notification(notify_id):
    """把草稿发布出去：status 改 published。

    v0.11.7：不动用户排好的生效时间；只有没生效时间时才补成当前时间。
    展示时间没填也补成现在。
    """
    conn = get_conn()
    try:
        exists = conn.execute(
            "SELECT publish_date, visible_at FROM notifications WHERE id = ?", (notify_id,)
        ).fetchone()
        if exists is None:
            return None
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        publish_date = (exists["publish_date"] or "").strip() or now
        visible_at = (exists["visible_at"] or "").strip() or now
        with conn:
            conn.execute(
                "UPDATE notifications SET status = 'published', publish_date = ?, "
                "visible_at = ? WHERE id = ?",
                (publish_date, visible_at, notify_id),
            )
        row = conn.execute(
            "SELECT " + NOTIFICATION_COLUMNS + " FROM notifications WHERE id = ?",
            (notify_id,),
        ).fetchone()
        return _row_to_notification(row)
    finally:
        conn.close()


def update_notification(
    notify_id,
    title=None,
    content=None,
    image_url=None,
    publish_date=None,
    status=None,
    visible_at=None,
):
    """改通知：只更新传进来的字段（None 表示不动），返回改后的完整字典。

    没有这条通知返回 None，由 app.py 转成 404。
    """
    fields = {}
    if title is not None:
        title = str(title).strip()
        if not title:
            raise RecordError("通知标题不能为空")
        fields["title"] = title
    if status is not None:
        status = str(status).strip()
        if status not in NOTIFICATION_STATUSES:
            raise RecordError("status 只能是 draft / published")
        fields["status"] = status
    if content is not None:
        fields["content"] = content
    if image_url is not None:
        fields["image_url"] = image_url
    if publish_date is not None:
        fields["publish_date"] = publish_date
    if visible_at is not None:
        fields["visible_at"] = visible_at

    conn = get_conn()
    try:
        exists = conn.execute("SELECT 1 FROM notifications WHERE id = ?", (notify_id,)).fetchone()
        if exists is None:
            return None
        if fields:
            assignments = ", ".join("%s = ?" % key for key in fields)
            with conn:
                conn.execute(
                    "UPDATE notifications SET " + assignments + " WHERE id = ?",
                    list(fields.values()) + [notify_id],
                )
        row = conn.execute(
            "SELECT " + NOTIFICATION_COLUMNS + " FROM notifications WHERE id = ?",
            (notify_id,),
        ).fetchone()
        return _row_to_notification(row)
    finally:
        conn.close()


def delete_notification(notify_id):
    """删一条通知，返回 True / False。"""
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM notifications WHERE id = ?", (notify_id,))
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------- AI 反馈记忆库（v0.10） ----------------

# 反馈状态只有两种：pending=待消化，processed=已经处理（比如已固化进 Prompt 或已人工纠正）
FEEDBACK_STATUSES = ("pending", "processed")


def _row_to_feedback(row):
    return {
        "id": row["id"],
        "raw_text": row["raw_text"],
        "parsed_json": row["parsed_json"],
        "corrected_json": row["corrected_json"],
        "source": row["source"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _dump_feedback_json(value):
    """parsed / corrected 既允许存 JSON 字符串，也允许直接传 dict/list，统一序列化成文本。

    None 和空字符串都落成 NULL，方便前端区分「这条没有解析结果」。
    """
    if value is None or value == "":
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False)


def add_feedback(raw_text, parsed_json=None, corrected_json=None, source=None):
    """记一条 AI 反馈，返回入库后的完整字典（含 id）。raw_text 为空直接抛 RecordError。"""
    raw_text = (raw_text or "").strip()
    if not raw_text:
        raise RecordError("反馈原文不能为空")
    if len(raw_text) > 2000:
        raise RecordError("反馈原文最多 2000 个字符")

    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO ai_feedback (raw_text, parsed_json, corrected_json, source) "
                "VALUES (?, ?, ?, ?)",
                (
                    raw_text,
                    _dump_feedback_json(parsed_json),
                    _dump_feedback_json(corrected_json),
                    (source or "").strip() or None,
                ),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, raw_text, parsed_json, corrected_json, source, status, "
            "       created_at, updated_at FROM ai_feedback WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_feedback(row)
    finally:
        conn.close()


def list_feedback(status=None):
    """列出反馈，新的在前；status 传 pending / processed 时按状态过滤。"""
    sql = (
        "SELECT id, raw_text, parsed_json, corrected_json, source, status, "
        "       created_at, updated_at FROM ai_feedback"
    )
    params = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC"

    conn = get_conn()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [_row_to_feedback(row) for row in rows]
    finally:
        conn.close()


def update_feedback_status(feedback_id, status):
    """改一条反馈的状态，返回 (改后的字典, 错误信息)。

    状态只认 pending / processed；id 不存在返回 (None, None)，由 app.py 转 404。
    """
    status = (status or "").strip()
    if status not in FEEDBACK_STATUSES:
        return None, "status 只能是 pending / processed"

    conn = get_conn()
    try:
        exists = conn.execute(
            "SELECT 1 FROM ai_feedback WHERE id = ?", (feedback_id,)
        ).fetchone()
        if exists is None:
            return None, None
        with conn:
            conn.execute(
                "UPDATE ai_feedback SET status = ?, updated_at = datetime('now','localtime') "
                "WHERE id = ?",
                (status, feedback_id),
            )
        row = conn.execute(
            "SELECT id, raw_text, parsed_json, corrected_json, source, status, "
            "       created_at, updated_at FROM ai_feedback WHERE id = ?",
            (feedback_id,),
        ).fetchone()
        return _row_to_feedback(row), None
    finally:
        conn.close()


# ---------------- AI 纠错记忆库（v0.11.4） ----------------


def _row_to_memory(row):
    return {
        "id": row["id"],
        "original_text": row["original_text"],
        "raw_category": row["raw_category"],
        "corrected_category": row["corrected_category"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def add_ai_memory(original_text, raw_category, corrected_category, note=""):
    """记一条人工纠错，返回入库后的完整字典（含 id）。

    这是「用户教 AI」的持久记忆：下次解析前取最近几条塞进 Prompt 当 few-shot。
    纠正后的分类必填，原始文本可以为空（比如详情页只改了分类没留原话）。
    """
    original_text = (original_text or "").strip()
    corrected_category = (corrected_category or "").strip()
    if not corrected_category:
        raise RecordError("纠正后的分类不能为空")
    if len(original_text) > 2000:
        raise RecordError("原始文本最多 2000 个字符")

    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO ai_memory "
                "       (original_text, raw_category, corrected_category, note) "
                "VALUES (?, ?, ?, ?)",
                (
                    original_text,
                    (raw_category or "").strip() or None,
                    corrected_category,
                    (note or "").strip()[:200] or None,
                ),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, original_text, raw_category, corrected_category, note, created_at "
            "FROM ai_memory WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_memory(row)
    finally:
        conn.close()


def list_ai_memories(limit=50):
    """列出纠错记忆，新的在前；limit 夹在 1~200 之间，避免一次拉全库。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(200, limit))

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, original_text, raw_category, corrected_category, note, created_at "
            "FROM ai_memory ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_memory(row) for row in rows]
    finally:
        conn.close()


def list_recent_ai_memories(limit=3):
    """取最近几条纠错给 Prompt 当 few-shot；条数固定很小，避免提示词被撑爆。"""
    return list_ai_memories(limit)


def search_ai_memories(text, limit=3):
    """按关键词 + 模糊相似度从记忆库里挑最相关的几条（v0.11.5 RAG）。

    和 v0.11.4 的「只取最近 3 条」相比，这里会真的读用户这次说的话：
    - difflib 相似度衡量整句像不像；
    - 2 字片段命中数当作关键词重合度（不引第三方分词，够用且快）；
    - 分数太低的直接不要，不足 limit 时用最近的记忆补齐，保证 Prompt 里总有几条参考。
    """
    query = re.sub(r"\s+", "", (text or "").strip().lower())
    memories = list_ai_memories(200)
    if not query:
        return memories[:limit]

    grams = {query[index : index + 2] for index in range(len(query) - 1)}
    scored = []
    for item in memories:
        original = re.sub(r"\s+", "", (item.get("original_text") or "").lower())
        if not original:
            continue
        ratio = difflib.SequenceMatcher(None, query, original).ratio()
        hits = sum(1 for gram in grams if gram in original)
        score = ratio + min(hits, 5) * 0.15
        if score >= 0.2:
            scored.append((score, item))
    scored.sort(key=lambda pair: pair[0], reverse=True)
    picked = [item for _, item in scored[:limit]]
    if len(picked) < limit:
        for item in memories:
            if item not in picked:
                picked.append(item)
            if len(picked) >= limit:
                break
    return picked[:limit]


def _row_to_correction_log(row):
    def load(raw):
        try:
            value = json.loads(raw) if raw else None
        except (TypeError, ValueError):
            return None
        return value

    return {
        "id": row["id"],
        "record_id": row["record_id"],
        "source": row["source"],
        "original_text": row["original_text"],
        "before": load(row["before_json"]),
        "after": load(row["after_json"]),
        "confidence": row["confidence"],
        "auto_corrected_msg": row["auto_corrected_msg"],
        "created_at": row["created_at"],
    }


def add_ai_correction_log(
    record_id,
    before,
    after,
    original_text="",
    source="bubble",
    confidence=None,
    auto_corrected_msg="",
):
    """记一条 AI 纠错审计日志，返回入库后的完整字典（含 id）。

    before / after 是整条账单的字典（改前 / 改后），后台右栏拿来做前后对比；
    写日志失败不应该影响主流程，调用方自行 try/except 即可。
    """
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO ai_correction_log "
                "       (record_id, source, original_text, before_json, after_json, "
                "        confidence, auto_corrected_msg) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    record_id,
                    (source or "bubble").strip()[:20],
                    (original_text or "").strip()[:2000],
                    json.dumps(before, ensure_ascii=False, default=str) if before is not None else None,
                    json.dumps(after, ensure_ascii=False, default=str) if after is not None else None,
                    confidence,
                    (auto_corrected_msg or "").strip()[:500] or None,
                ),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, record_id, source, original_text, before_json, after_json, "
            "       confidence, auto_corrected_msg, created_at "
            "FROM ai_correction_log WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_correction_log(row)
    finally:
        conn.close()


def list_ai_correction_logs(limit=50):
    """列出最近的纠错审计日志，新的在前；limit 夹在 1~200 之间。"""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 50
    limit = max(1, min(200, limit))

    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, record_id, source, original_text, before_json, after_json, "
            "       confidence, auto_corrected_msg, created_at "
            "FROM ai_correction_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_correction_log(row) for row in rows]
    finally:
        conn.close()


def delete_ai_memory(memory_id):
    """删一条纠错记忆，返回是否真的删到了。"""
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM ai_memory WHERE id = ?", (memory_id,))
            return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------- 10 分钟防重检测（v0.11.4） ----------------

# 商户/备注相似度用最长公共子串衡量：不引入分词依赖，两个字的公共片段就够像
DUPLICATE_MINUTES = 10
DUPLICATE_MIN_COMMON = 2


def _longest_common_substring(left, right):
    """两个字符串的最长公共子串长度（经典 DP，只保留上一行，空间 O(n)）。"""
    if not left or not right:
        return 0
    best = 0
    previous_row = [0] * (len(right) + 1)
    for char in left:
        current_row = [0]
        for index, other in enumerate(right, start=1):
            if char == other:
                value = previous_row[index - 1] + 1
                current_row.append(value)
                if value > best:
                    best = value
            else:
                current_row.append(0)
        previous_row = current_row
    return best


def _texts_similar(left, right):
    """备注/商户名是否相似：去空白后互相包含，或公共子串达到 2 个字。"""
    a = re.sub(r"\s+", "", (left or "").lower())
    b = re.sub(r"\s+", "", (right or "").lower())
    if not a or not b:
        return False
    if a in b or b in a:
        return True
    return _longest_common_substring(a, b) >= DUPLICATE_MIN_COMMON


def find_recent_duplicate(
    amount,
    account="",
    note="",
    minutes=DUPLICATE_MINUTES,
    exclude_id=None,
):
    """保存前查最近 minutes 分钟内金额相同、商户/账户相似的账目。

    命中返回整条账目 dict，否则 None。只比较入库时间 created_at：
    老数据 created_at 是空串（升级前没有这个字段），一律不参与防重，
    宁可漏判，也不要把几年前的旧账翻出来弹窗。
    """
    try:
        amount_value = round(float(amount), 2)
    except (TypeError, ValueError):
        return None
    try:
        minutes = max(1, int(minutes))
    except (TypeError, ValueError):
        minutes = DUPLICATE_MINUTES

    sql = (
        _RECORD_SELECT
        + " WHERE r.deleted_at IS NULL"
        + "   AND ABS(r.amount - ?) < 0.005"
        + "   AND r.created_at <> ''"
        + "   AND r.created_at >= datetime('now','localtime', ?)"
    )
    params = [amount_value, "-%d minutes" % minutes]
    if exclude_id:
        sql += " AND r.id <> ?"
        params.append(exclude_id)
    sql += " ORDER BY r.id DESC LIMIT 20"

    conn = get_conn()
    try:
        rows = [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()

    account = (account or "").strip()
    note = (note or "").strip()
    for record in rows:
        record_note = (record.get("note") or "").strip()
        same_account = bool(account) and account == (record.get("account") or "")
        if _texts_similar(note, record_note):
            return record
        # 两边都没写商户名时，只能靠「同账户 + 同金额 + 10 分钟内」兜底
        if same_account and (not note or not record_note):
            return record
    return None


# ---------------- 站点访问密码与验证会话（v0.11.1） ----------------

# 访问密码存在 admin_config.value 里，多个密码用逗号拼接。
# v0.11.2 起改为可回显格式「p1$Base64(明文)」：后台「查看密码」需要现场二次验证后显示明文；
# 兼容 v0.11.1 的旧格式「随机盐$SHA256」，旧格式仍可校验但无法回显，提示删除后重设。
ACCESS_PASSWORD_KEY = "access_password"
ACCESS_TIMEOUT_KEY = "verify_timeout"
PASSWORD_STORE_PREFIX = "p1$"
DEFAULT_VERIFY_TIMEOUT_MINUTES = 60
MIN_VERIFY_TIMEOUT_MINUTES = 10
MAX_VERIFY_TIMEOUT_MINUTES = 1440
PASSWORD_MIN_LENGTH = 4
PASSWORD_MAX_LENGTH = 64


def _hash_password(raw_password, salt=None):
    """返回「盐$哈希」；校验时把同一盐和用户输入再算一遍比对。"""
    import hashlib
    import secrets

    salt = salt or secrets.token_hex(8)
    digest = hashlib.sha256((salt + ":" + raw_password).encode("utf-8")).hexdigest()
    return salt + "$" + digest


def _encode_password(raw_password):
    """v0.11.2 起的新存储格式：p1$ + urlsafe Base64，可解码用于「查看密码」。"""
    import base64

    token = base64.urlsafe_b64encode(str(raw_password).encode("utf-8")).decode("ascii")
    return PASSWORD_STORE_PREFIX + token


def _decode_password(stored):
    """把 p1$ 存储还原成明文；v0.11.1 的盐$哈希返回 None（不可逆）。"""
    import base64

    if not stored or not stored.startswith(PASSWORD_STORE_PREFIX):
        return None
    token = stored[len(PASSWORD_STORE_PREFIX):]
    try:
        raw = base64.urlsafe_b64decode(token.encode("ascii"))
    except (ValueError, TypeError, UnicodeError):
        return None
    return raw.decode("utf-8", "replace")


def _password_matches(raw_password, stored):
    if not stored:
        return False
    plain = _decode_password(stored)
    if plain is not None:
        import hmac

        return hmac.compare_digest(plain, raw_password)
    if "$" not in stored:
        return False
    salt, _, _digest = stored.partition("$")
    return _hash_password(raw_password, salt) == stored


def _config_get(conn, key, default=""):
    row = conn.execute(
        "SELECT value FROM admin_config WHERE key = ?", (key,)
    ).fetchone()
    return row["value"] if row is not None else default


def _config_set(conn, key, value):
    conn.execute(
        "INSERT INTO admin_config (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def get_access_config():
    """前端启动时问一次：有没有设密码、多长的验证超时。"""
    conn = get_conn()
    try:
        hashes = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        raw_timeout = _config_get(conn, ACCESS_TIMEOUT_KEY, "")
        try:
            timeout = int(raw_timeout) if raw_timeout else DEFAULT_VERIFY_TIMEOUT_MINUTES
        except (TypeError, ValueError):
            timeout = DEFAULT_VERIFY_TIMEOUT_MINUTES
        timeout = max(MIN_VERIFY_TIMEOUT_MINUTES, min(MAX_VERIFY_TIMEOUT_MINUTES, timeout))
        return {
            "protected": bool(hashes),
            "password_count": len(hashes),
            "timeout_minutes": timeout,
        }
    finally:
        conn.close()


def verify_access_password(raw_password):
    """比对任意一个已设密码；没设密码时视为通过（不强制拦截）。"""
    raw_password = str(raw_password or "")
    conn = get_conn()
    try:
        if not _config_get(conn, ACCESS_PASSWORD_KEY, ""):
            return True
        hashes = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        return any(_password_matches(raw_password, stored) for stored in hashes)
    finally:
        conn.close()


def list_access_passwords():
    """后台密码列表：只回掩码与序号，绝不回明文或哈希。"""
    conn = get_conn()
    try:
        hashes = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        return [{"index": index, "label": "密码 %d" % (index + 1)} for index in range(len(hashes))]
    finally:
        conn.close()


def reveal_access_password(index, raw_password):
    """查看指定序号的明文密码：必须现场输入任意一个当前密码二次验证。

    不复用 5 分钟免密会话（由调用方保证），这里只认请求体里的明文密码；
    v0.11.1 的旧哈希无法还原，返回提示让用户删掉重设。
    返回 (是否成功, 错误信息, 明文)。
    """
    try:
        index = int(index)
    except (TypeError, ValueError):
        return False, "密码序号不合法", ""
    raw_password = str(raw_password or "")

    conn = get_conn()
    try:
        stored_list = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        if not stored_list:
            return False, "还没有设置密码", ""
        if not any(_password_matches(raw_password, stored) for stored in stored_list):
            return False, "当前密码不正确", ""
        if index < 0 or index >= len(stored_list):
            return False, "密码不存在", ""
        plain = _decode_password(stored_list[index])
        if plain is None:
            return False, "这个密码是旧版哈希存储，无法回显；请删除后重新添加", ""
        return True, None, plain
    finally:
        conn.close()


def add_access_password(raw_password):
    """新增一个访问密码，返回 (是否成功, 错误信息, 密码数量)。"""
    raw_password = str(raw_password or "")
    if len(raw_password) < PASSWORD_MIN_LENGTH:
        return False, "密码至少 %d 位" % PASSWORD_MIN_LENGTH, 0
    if len(raw_password) > PASSWORD_MAX_LENGTH:
        return False, "密码最多 %d 位" % PASSWORD_MAX_LENGTH, 0

    conn = get_conn()
    try:
        hashes = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        if any(_password_matches(raw_password, stored) for stored in hashes):
            return False, "这个密码已经存在了", len(hashes)
        hashes.append(_encode_password(raw_password))
        with conn:
            _config_set(conn, ACCESS_PASSWORD_KEY, ",".join(hashes))
        return True, None, len(hashes)
    finally:
        conn.close()


def remove_access_password(index):
    """按序号删一个密码，返回 (是否成功, 错误信息, 剩余数量)。"""
    try:
        index = int(index)
    except (TypeError, ValueError):
        return False, "密码序号不合法", 0

    conn = get_conn()
    try:
        hashes = [
            item for item in _config_get(conn, ACCESS_PASSWORD_KEY, "").split(",") if item
        ]
        if index < 0 or index >= len(hashes):
            return False, "密码不存在", len(hashes)
        hashes.pop(index)
        with conn:
            _config_set(conn, ACCESS_PASSWORD_KEY, ",".join(hashes))
            # 删到没有密码时清掉全部会话，站点立刻回到免密状态
            if not hashes:
                conn.execute("DELETE FROM access_sessions")
        return True, None, len(hashes)
    finally:
        conn.close()


def set_access_timeout(minutes):
    """改验证超时（10 分钟 ~ 1 天），返回 (是否成功, 错误信息, 分钟数)。"""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return False, "超时时间必须是整数分钟", 0
    if minutes < MIN_VERIFY_TIMEOUT_MINUTES or minutes > MAX_VERIFY_TIMEOUT_MINUTES:
        return False, "超时时间要在 %d ~ %d 分钟之间" % (
            MIN_VERIFY_TIMEOUT_MINUTES,
            MAX_VERIFY_TIMEOUT_MINUTES,
        ), 0

    conn = get_conn()
    try:
        with conn:
            _config_set(conn, ACCESS_TIMEOUT_KEY, minutes)
        return True, None, minutes
    finally:
        conn.close()


def create_access_session():
    """验证成功后发 token，返回 token 字符串。"""
    import secrets

    token = secrets.token_urlsafe(24)
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_conn()
    try:
        with conn:
            # 顺手清掉一天前的会话，避免表无限长
            conn.execute(
                "DELETE FROM access_sessions WHERE created_at < ?",
                ((datetime.datetime.now() - datetime.timedelta(days=1)).strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),),
            )
            conn.execute(
                "INSERT INTO access_sessions (token, created_at) VALUES (?, ?)",
                (token, now),
            )
        return token
    finally:
        conn.close()


def get_access_session_age(token):
    """返回 token 已存在的秒数；token 不存在返回 None。"""
    token = str(token or "").strip()
    if not token:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT created_at FROM access_sessions WHERE token = ?", (token,)
        ).fetchone()
        if row is None:
            return None
        try:
            created = datetime.datetime.strptime(row["created_at"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
        return max(0, int((datetime.datetime.now() - created).total_seconds()))
    finally:
        conn.close()


def check_access_session(token, timeout_minutes=None):
    """token 是否仍在验证有效期内。"""
    if timeout_minutes is None:
        timeout_minutes = get_access_config()["timeout_minutes"]
    age = get_access_session_age(token)
    if age is None:
        return False
    return age < timeout_minutes * 60


def revoke_access_session(token):
    token = str(token or "").strip()
    if not token:
        return
    conn = get_conn()
    try:
        with conn:
            conn.execute("DELETE FROM access_sessions WHERE token = ?", (token,))
    finally:
        conn.close()
