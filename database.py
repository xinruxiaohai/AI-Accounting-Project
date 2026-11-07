import contextvars
import datetime
import difflib
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

# 数据库文件固定在 database.py 同目录下，这样不管从哪个目录启动 app.py 都找得到
DB_PATH = Path(__file__).resolve().parent / "records.db"

# v0.13.1：迁移前的 DB 备份目录。**必须放在项目目录之外**（HANDOFF 红线：测试产物不进项目目录）
MIGRATION_BACKUP_DIR = Path(r"D:\Project\temp\db-backup")

# 本进程已做过的迁移备份文件路径（避免重复 init_db 时堆出一串同样的备份）
_MIGRATION_BACKUP_FILE = ""

# ---------------- 默认数据（缺了才补，不动已有数据） ----------------

# 两级分类种子：(一级分类, [二级分类...])
# v0.14.0：科学重构默认分类体系（替换 v0.13 及以前的「早餐/午餐/晚餐」「地铁/公交」等拍脑袋分组）。
# 「其他」必须保留：它是 DEFAULT_CATEGORY，脏分类清洗与老账单兜底都挂到它下面。
CATEGORY_SEEDS = [
    ("餐饮", ["三餐", "外卖", "零食饮料", "下馆子"]),
    ("交通", ["公交地铁", "打车", "加油/停车"]),
    ("购物", ["日用品", "衣服鞋包", "数码电器"]),
    ("娱乐", ["游戏", "电影", "旅游"]),
    ("居住", ["房租", "水电燃气", "物业"]),
    ("医疗", ["药品", "门诊挂号"]),
    ("人情", ["红包", "送礼"]),
    ("其他", []),
]

# v0.13 及以前由种子写进库、但 v0.14.0 新体系里已经不需要的默认分类名。
# 只在「没有任何账单引用」时才删除（有引用的保留，绝不为了好看丢真实数据）。
LEGACY_DEFAULT_CATEGORY_NAMES = frozenset(
    {
        "早餐",
        "午餐",
        "晚餐",
        "打车",
        "地铁",
        "公交",
        "加油",
        "服饰",
        "数码",
        "电影",
        "游戏",
        "旅游",
        "房租",
        "水电",
        "物业",
        # 旧收入分类（新体系用「工资薪酬」「退款/报销」「红包/礼金」）
        "工资",
        "红包",
        "利息",
        "退款",
    }
)

# 账户大类：只认这三种，前端用 <optgroup> 分组展示
ACCOUNT_GROUPS = ("资金账户", "储蓄账户", "投资账户")
DEFAULT_GROUP = "资金账户"

# 账户种子：(账户名, 大类)
# v0.14.0：按「资金 / 储蓄 / 投资」三层重排——资金账户放日常支付工具，
# 储蓄账户放银行卡，投资账户放证券/基金户，用户一眼能分清钱在哪一层。
ACCOUNT_SEEDS = [
    ("现金", "资金账户"),
    ("微信", "资金账户"),
    ("支付宝", "资金账户"),
    ("储蓄卡", "储蓄账户"),
    ("信用卡", "储蓄账户"),
    ("基金账户", "投资账户"),
    ("股票账户", "投资账户"),
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

# ---------------- 投资体系（v0.13.3） ----------------

# 账户**功能类型**（与 group_name 的「展示分组」并存但不等价）：
#   normal      = 普通账户（走今天的流水列表）
#   investment  = 投资账户（资产页渲染投资看板，可建平台 / 持仓 / 定投）
# 列上加 NOT NULL DEFAULT 'normal'，取值由应用层白名单校验（设计 U2：不加 CHECK 约束，
# 否则「新库带 CHECK / 老库无 CHECK」会形成双形态，违反幂等迁移结构一致的纪律）。
ACCOUNT_TYPES = ("normal", "investment")
DEFAULT_ACCOUNT_TYPE = "normal"
INVESTMENT_ACCOUNT_TYPE = "investment"

# 持仓资产类型白名单；非法值一律回落 fund（不报错，避免 AI 乱吐词导致建仓失败）
# v0.13.3：补 `gold`（黄金）——黄金的计价单位（元/克、元/份）与基金份额差异大，
# 混在 fund 里会让看板的类型分布失真，用户也一直要求下拉里有「黄金」这一项。
INVEST_ASSET_TYPES = ("fund", "stock", "bond", "gold", "cash", "other")
DEFAULT_ASSET_TYPE = "fund"

# 投资平台默认名：每个投资账户至少有一个「默认」平台（迁移步 9 与 ensure_default_platform 补）
INVEST_PLATFORM_DEFAULT = "默认"

# 分类口径（设计 §8）：买入侧与清仓侧**不能共用同一个分类名**，因为
# uq_categories_user (user_id, COALESCE(parent_id,0), name) 不含 type，同名不同 type 会撞唯一约束。
# v0.13.3 决策 B 下 invest_buy **不写 records**，这两个常量只作为分类名留存与未来扩展用，
# 但常量必须保留：AI / 导入 / 未来的 CSV 都按它对齐名字，杜绝各处硬编码字符串。
INVEST_BUY_CATEGORY = "投资买入"
INVEST_REFUND_CATEGORY = "投资理财"

# 定投频率与状态白名单（本期只落库 + 展示，不自动生成任何账目，设计 §1.2 第 3 条）
DCA_FREQUENCIES = ("weekly", "biweekly", "monthly", "quarterly")
DCA_STATUSES = ("active", "paused")
DEFAULT_DCA_FREQUENCY = "monthly"
DEFAULT_DCA_STATUS = "active"

# 名称长度上限：平台名 20 字（设计 §3.7 #4），标的名 40 字
MAX_PLATFORM_NAME_LENGTH = 20
MAX_HOLDING_NAME_LENGTH = 40


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


# ---------------- 多用户（v0.12） ----------------

# 当前请求的用户 id。app.py 在 before_request 里按 JWT 调 set_current_user()，
# 数据库层所有「按用户隔离」的查询统一从这里取，避免把 user_id 一路透传到几十个函数签名。
_CURRENT_USER_ID = contextvars.ContextVar("current_user_id", default=1)

ADMIN_USER_ID = 1
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_INITIAL_PASSWORD = os.getenv("ADMIN_INITIAL_PASSWORD", "Admin@2026!")
DEFAULT_USER_ID_START = 10
USER_ID_RESERVED_MAX = 9


def set_current_user(user_id):
    """设置本请求的用户 id。

    F2 修复（v0.13.1）：**只有 None / 非法值才兜底成 1 号管理员，0 必须保持 0**。
    原写法 `int(user_id or ADMIN_USER_ID)` 里 `0 or 1` 求值为 1，导致公开路径
    （注册 / 登录 / 游客看通知）调 set_current_user(0) 后实际以管理员身份查库。
    因此这里禁止使用真值判断，只判断 `is None`。
    """
    if user_id is None:
        _CURRENT_USER_ID.set(ADMIN_USER_ID)
        return
    try:
        _CURRENT_USER_ID.set(int(user_id))
    except (TypeError, ValueError):
        _CURRENT_USER_ID.set(ADMIN_USER_ID)


def current_user_id():
    """取当前上下文的用户 id。

    同样遵循 F2：0 是「未登录 / 不属于任何用户」的合法取值，
    绝不因为 `0 or 1 == 1` 被兜底成管理员。只有 None / 非法值才回落 1 号。
    """
    value = _CURRENT_USER_ID.get()
    if value is None:
        return ADMIN_USER_ID
    try:
        return int(value)
    except (TypeError, ValueError):
        return ADMIN_USER_ID


def _uid():
    return current_user_id()


def _resolve_user_id(user_id=None):
    """把显式传入的 user_id 归一成整数；None 才回落到当前上下文 `_uid()`。

    F3：种子 / 迁移 / 注册补齐这类「不在请求上下文里」的调用必须显式传 user_id，
    因为 ContextVar 的 default=1，任何非请求上下文都会以 1 号管理员身份写入。
    只有对外的高层便利函数才允许走这里的回落。0 是合法值，不做真值兜底。
    """
    if user_id is None:
        return _uid()
    try:
        return int(user_id)
    except (TypeError, ValueError):
        return _uid()


def _row_to_user(row):
    return {
        "id": row["id"],
        "email": row["email"],
        "phone": row["phone"],
        "nickname": row["nickname"] if "nickname" in row.keys() else "",
        "avatar": (row["avatar"] if "avatar" in row.keys() else "") or "",
        "created_at": row["created_at"],
    }


def create_user(email, password_hash, phone="", nickname=""):
    """新建用户，返回 (用户字典, 错误信息)。id 由 AUTOINCREMENT 分配（管理员占 1~9）。

    nickname 是侧边栏展示用的昵称；不填就取邮箱 @ 前面的部分，保证永远有名字可显示。
    """
    email = (email or "").strip().lower()
    if not email or "@" not in email:
        return None, "邮箱格式不正确"
    conn = get_conn()
    try:
        with conn:
            exists = conn.execute(
                "SELECT id FROM users WHERE email = ?", (email,)
            ).fetchone()
            if exists is not None:
                return None, "该邮箱已注册"
            nickname = (nickname or "").strip() or email.split("@")[0]
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash, phone, nickname, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
                (email, password_hash, (phone or "").strip(), nickname[:30]),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, email, phone, nickname, avatar, created_at FROM users WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_user(row), None
    finally:
        conn.close()


def get_user_by_email(email):
    """按邮箱取用户（含 password_hash，只给登录校验用，绝不返回给前端）。"""
    email = (email or "").strip().lower()
    if not email:
        return None
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash, phone, nickname, avatar, created_at FROM users WHERE email = ?",
            (email,),
        ).fetchone()
        if row is None:
            return None
        user = _row_to_user(row)
        user["password_hash"] = row["password_hash"]
        return user
    finally:
        conn.close()


def get_user(user_id):
    """按 id 取用户（不含密码哈希）。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, phone, nickname, avatar, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return _row_to_user(row) if row is not None else None
    finally:
        conn.close()


def seed_default_accounts_for(user_id):
    """新用户注册后给一套默认账户（现金 / 微信 / 支付宝 / 银行卡），余额都是 0。"""
    conn = get_conn()
    try:
        with conn:
            for index, name in enumerate(("现金", "微信", "支付宝", "银行卡")):
                conn.execute(
                    "INSERT OR IGNORE INTO accounts (user_id, name, balance, group_name, sort_order) "
                    "VALUES (?, ?, 0, ?, ?)",
                    (int(user_id), name, DEFAULT_GROUP, index),
                )
    finally:
        conn.close()


def list_users():
    """后台用户列表（不含密码）。

    v0.13.7：多带一个 `uid` 字段（就是 users.id 本身）与记录数，
    后台「用户管理」直接用 uid 定位用户，避免把昵称/邮箱当成主键看。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT u.id, u.email, u.phone, u.nickname, u.avatar, u.created_at, "
            "       (SELECT COUNT(*) FROM records r "
            "         WHERE r.user_id = u.id AND r.deleted_at IS NULL) AS record_count "
            "  FROM users u ORDER BY u.id"
        ).fetchall()
        users = []
        for row in rows:
            user = _row_to_user(row)
            user["uid"] = row["id"]
            user["record_count"] = row["record_count"]
            users.append(user)
        return users
    finally:
        conn.close()

# ---------------- 登录安全与账号设置（v0.12.2） ----------------

LOGIN_MAX_FAILS = 5
LOGIN_LOCK_MINUTES = 15


def _login_lock_until(conn, email):
    """读该邮箱的锁定截止时间（已过期就顺手清掉），没有锁定返回 None。"""
    row = conn.execute(
        "SELECT fail_count, locked_until FROM login_attempts WHERE email = ?", (email,)
    ).fetchone()
    if row is None:
        return None
    locked_until = (row["locked_until"] or "").strip()
    if not locked_until:
        return None
    try:
        until = datetime.datetime.strptime(locked_until, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if until <= datetime.datetime.now():
        conn.execute(
            "UPDATE login_attempts SET fail_count = 0, locked_until = '' WHERE email = ?",
            (email,),
        )
        return None
    return until


def get_login_lock(email):
    """登录前查锁定状态：返回 (是否锁定, 解锁时间字符串, 剩余秒数)。"""
    email = (email or "").strip().lower()
    if not email:
        return False, "", 0
    conn = get_conn()
    try:
        with conn:
            until = _login_lock_until(conn, email)
            if until is None:
                return False, "", 0
            remaining = int((until - datetime.datetime.now()).total_seconds())
            return True, until.strftime("%Y-%m-%d %H:%M:%S"), max(0, remaining)
    finally:
        conn.close()


def record_login_failure(email):
    """记一次密码错误；连续 5 次锁定 15 分钟。返回 (失败次数, 锁定截止时间或 None)。"""
    email = (email or "").strip().lower()
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT fail_count FROM login_attempts WHERE email = ?", (email,)
            ).fetchone()
            count = (row["fail_count"] if row is not None else 0) + 1
            locked_until = ""
            if count >= LOGIN_MAX_FAILS:
                until = datetime.datetime.now() + datetime.timedelta(minutes=LOGIN_LOCK_MINUTES)
                locked_until = until.strftime("%Y-%m-%d %H:%M:%S")
                count = 0  # 锁定后重新计数，下轮从 0 开始
            conn.execute(
                "INSERT INTO login_attempts (email, fail_count, locked_until) "
                "VALUES (?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET "
                "  fail_count = excluded.fail_count, locked_until = excluded.locked_until",
                (email, count, locked_until),
            )
            return count, (locked_until or None)
    finally:
        conn.close()


def clear_login_failures(email):
    """登录成功 / 改密成功后清空失败计数与锁定。"""
    email = (email or "").strip().lower()
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "UPDATE login_attempts SET fail_count = 0, locked_until = '' WHERE email = ?",
                (email,),
            )
    finally:
        conn.close()


def update_user_password(user_id, password_hash):
    """改密：只更新 password_hash，返回是否命中用户。"""
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (password_hash, int(user_id)),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def update_user_nickname(user_id, nickname):
    """更新昵称；空昵称回退成邮箱前缀。返回最新用户字典或 None。"""
    nickname = (nickname or "").strip()
    conn = get_conn()
    try:
        with conn:
            row = conn.execute("SELECT email FROM users WHERE id = ?", (user_id,)).fetchone()
            if row is None:
                return None
            if not nickname:
                nickname = str(row["email"]).split("@")[0]
            conn.execute(
                "UPDATE users SET nickname = ? WHERE id = ?", (nickname[:30], int(user_id))
            )
        return get_user(user_id)
    finally:
        conn.close()


def update_user_avatar(user_id, avatar):
    """更新头像 URL；空串表示恢复成昵称首字母。返回最新用户字典或 None。"""
    avatar = (avatar or "").strip()
    conn = get_conn()
    try:
        with conn:
            exists = conn.execute("SELECT id FROM users WHERE id = ?", (int(user_id),)).fetchone()
            if exists is None:
                return None
            conn.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar[:500], int(user_id)))
        return get_user(user_id)
    finally:
        conn.close()


# ---------------- 账单导入（v0.12） ----------------

IMPORT_SOURCES = ("wechat", "alipay", "unknown")


def add_import_history(source, total, imported, duplicated, filename=""):
    """记一次导入，返回入库后的字典（id 等）。"""
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO import_history "
                "       (user_id, source, filename, total, imported, duplicated, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, datetime('now','localtime'))",
                (
                    _uid(),
                    (source or "unknown")[:20],
                    (filename or "")[:200],
                    int(total or 0),
                    int(imported or 0),
                    int(duplicated or 0),
                ),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, user_id, source, filename, total, imported, duplicated, created_at "
            "FROM import_history WHERE id = ?",
            (new_id,),
        ).fetchone()
        return dict(row)
    finally:
        conn.close()


def list_import_history(limit=50):
    """最近导入记录（当前用户），新的在前。"""
    try:
        limit = max(1, min(200, int(limit)))
    except (TypeError, ValueError):
        limit = 50
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, user_id, source, filename, total, imported, duplicated, created_at "
            "FROM import_history WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (_uid(), limit),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


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
    row = conn.execute(
        "SELECT 1 FROM accounts WHERE name = ? AND user_id = ?", (account, _uid())
    ).fetchone()
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
            "SELECT name FROM accounts WHERE name = ? AND user_id = ?", (name, _uid())
        ).fetchone()
        if row is None:
            return "账户不存在：%s" % name

    balance = conn.execute(
        "SELECT balance FROM accounts WHERE name = ? AND user_id = ?", (account, _uid())
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
        "INSERT OR IGNORE INTO accounts (user_id, name, balance, group_name) VALUES (?, ?, 0, ?)",
        (_uid(), account, DEFAULT_GROUP),
    )
    conn.execute(
        "UPDATE accounts SET balance = balance + ? WHERE name = ? AND user_id = ?",
        (delta, account, _uid()),
    )


def _row_to_category(row):
    """把 categories 的一行转成前端友好的字典。

    v0.13.1：新增字段一律可空兼容（icon_key/color 空串、is_disabled 0、disabled_at 空串），
    老前端不读这几个字段也不会坏。`is_disabled` 是「停用」的唯一判定列，必须带下去。
    """
    keys = row.keys()
    return {
        "id": row["id"],
        "user_id": row["user_id"] if "user_id" in keys else _uid(),
        "name": row["name"],
        "parent_id": row["parent_id"],
        "type": row["type"] if "type" in keys else "expense",
        "icon_key": (row["icon_key"] if "icon_key" in keys else "") or "",
        "color": (row["color"] if "color" in keys else "") or "",
        "is_disabled": int(row["is_disabled"] or 0) if "is_disabled" in keys else 0,
        "disabled_at": (row["disabled_at"] if "disabled_at" in keys else "") or "",
        "children": [],
    }


def _ensure_category(conn, name, parent_id=None, category_type="expense", user_id=None):
    """按 (user_id, 名字, 父级) 找分类，没有就插一条，返回 id。幂等，可反复调用。

    category_type: 'expense' / 'income'，决定该分类在记账弹窗里归哪个收支分组。
    user_id: F3 强制 —— 种子 / 注册补齐必须显式传，绝不能依赖 `_uid()`
             （ContextVar default=1，非请求上下文会把新用户的分类种到管理员名下）。

    D19：这里**绝不加 `is_disabled = 0`** —— 停用只影响「新增场景的选项可见性」，
    不影响「历史账单的引用写入」，否则编辑旧账单的回填会被后端打回。
    """
    uid = _resolve_user_id(user_id)
    if parent_id is None:
        row = conn.execute(
            "SELECT id FROM categories WHERE user_id = ? AND name = ? AND parent_id IS NULL",
            (uid, name),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT id FROM categories WHERE user_id = ? AND name = ? AND parent_id = ?",
            (uid, name, parent_id),
        ).fetchone()
    if row is not None:
        return row["id"]

    cat_type = "income" if category_type == "income" else "expense"
    cur = conn.execute(
        "INSERT INTO categories (user_id, name, parent_id, type) VALUES (?, ?, ?, ?)",
        (uid, name, parent_id, cat_type),
    )
    return cur.lastrowid


# 默认收入分类（一级，无二级）；已存在同名一级分类则跳过，幂等
# v0.14.0：「工资」「红包」「退款」升级为更明确的「工资薪酬」「红包/礼金」「退款/报销」，
# 并补「其他收入」兜底；旧名由 LEGACY_DEFAULT_CATEGORY_NAMES 在迁移时清理（无引用才删）。
INCOME_CATEGORY_SEEDS = (
    "工资薪酬",
    "兼职外快",
    "投资理财",
    "退款/报销",
    "红包/礼金",
    "其他收入",
)


def _seed_categories(conn, user_id=None):
    """按 CATEGORY_SEEDS 给指定用户补齐默认支出分类，已有同名同级的直接跳过（补缺不覆盖）。"""
    uid = _resolve_user_id(user_id)
    for top_name, children in CATEGORY_SEEDS:
        top_id = _ensure_category(conn, top_name, None, "expense", uid)
        for child_name in children:
            _ensure_category(conn, child_name, top_id, "expense", uid)


def _seed_income_categories(conn, user_id=None):
    """给指定用户补齐默认收入分类；已存在同名一级分类则跳过（幂等，补缺不覆盖）。"""
    uid = _resolve_user_id(user_id)
    for name in INCOME_CATEGORY_SEEDS:
        _ensure_category(conn, name, None, "income", uid)


# ---------------- v0.14.0：默认分类体系迁移（脏数据清洗 + 科学重构） ----------------

# 迁移标记键：写在 schema_migrations 表里（v0.13.3 起复用的迁移标记表）。
# **只能跑一次**——跑过之后再启动不会重新补种，否则「用户删过的分类下次重启又冒出来」，
# 破坏 v0.13 起就承诺过的口径。
TAXONOMY_MIGRATION_KEY = "taxonomy_v0140"


def _expense_category_map():
    """新体系里的支出分类位置：{名字: 父分类名}（一级分类父名是 None）。

    只比「名字」不够——旧版有个一级「红包」（income），新版「红包」是「人情」的二级子类，
    同名但不同位置，必须按 type + parent 一起判断是不是新体系里的那一颗。
    """
    mapping = {}
    for top_name, children in CATEGORY_SEEDS:
        mapping[top_name] = None
        for child in children:
            mapping[child] = top_name
    return mapping


def _default_category_names():
    """新体系里所有默认分类名（一级 + 二级），用来区分「默认模板」和「用户自定义」。"""
    return set(_expense_category_map()) | set(INCOME_CATEGORY_SEEDS)


def _is_in_new_taxonomy(row, rows_by_id):
    """这条分类是不是新体系里的默认节点（名字 + 类型 + 父分类三者都要对上）。"""
    name = str(row["name"] or "").strip()
    if row["type"] == "income":
        return name in INCOME_CATEGORY_SEEDS
    parent = rows_by_id.get(row["parent_id"])
    parent_name = str(parent["name"] or "").strip() if parent is not None else None
    return _expense_category_map().get(name, "__missing__") == parent_name


def _user_category_rows(conn, uid):
    return conn.execute(
        "SELECT id, name, parent_id, type FROM categories WHERE user_id = ? ORDER BY id",
        (uid,),
    ).fetchall()


def _category_record_count(conn, uid, category_id, name):
    """这条分类被多少条账单引用（按 id 优先，老数据只有文本时按名字兜底）。

    回收站里的账单也算引用：恢复一条「213」账单时分类必须还在，
    所以这里**不加 deleted_at IS NULL**。
    """
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM records "
        " WHERE user_id = ? "
        "   AND (category_id = ? OR (category_id IS NULL AND category = ?))",
        (uid, category_id, name),
    ).fetchone()
    return row["n"]


def _move_records_to_category(conn, uid, from_id, from_name, to_id, to_name):
    """把某分类下的账单改挂到兜底分类（金额 / 备注 / 时间全部原样保留，只换分类）。

    回收站（软删除）里的账单同样要迁：不然它一恢复，又会带回「213」这种孤儿分类。
    """
    conn.execute(
        "UPDATE records SET category = ?, category_id = ? "
        " WHERE user_id = ? "
        "   AND (category_id = ? OR (category_id IS NULL AND category = ?))",
        (to_name, to_id, uid, from_id, from_name),
    )


def _cleanup_dirty_categories(conn):
    """v0.14.0：清掉历史遗留的脏分类（纯数字名、空名，例如「213」）。

    纪律：**绝不直接删账单**。先把它们名下的账单改挂到「其他 / 其他收入」，
    保留金额、备注、时间，再删分类行；整个过程按 user_id 隔离。
    返回删除掉的分类条数（重复调用返回 0，幂等）。
    """
    removed = 0
    user_ids = [row["user_id"] for row in conn.execute("SELECT DISTINCT user_id FROM categories")]
    for uid in user_ids:
        rows = _user_category_rows(conn, uid)
        dirty = [
            row
            for row in rows
            if not str(row["name"] or "").strip() or str(row["name"]).strip().isdigit()
        ]
        for row in dirty:
            is_income = row["type"] == "income"
            fallback_name = "其他收入" if is_income else DEFAULT_CATEGORY
            fallback_type = "income" if is_income else "expense"
            fallback_id = _ensure_category(conn, fallback_name, None, fallback_type, uid)
            _move_records_to_category(conn, uid, row["id"], row["name"], fallback_id, fallback_name)
            # 脏分类如果还挂着子分类，孩子同样先迁账再一起删（不留下孤儿分类）
            for child in rows:
                if child["parent_id"] != row["id"]:
                    continue
                _move_records_to_category(
                    conn, uid, child["id"], child["name"], fallback_id, fallback_name
                )
                conn.execute(
                    "DELETE FROM categories WHERE id = ? AND user_id = ?", (child["id"], uid)
                )
                removed += 1
            conn.execute("DELETE FROM categories WHERE id = ? AND user_id = ?", (row["id"], uid))
            removed += 1
    return removed


def _cleanup_legacy_default_categories(conn):
    """v0.14.0：删掉旧版默认模板里、新体系**位置已经对不上**且没有任何账单引用的分类。

    判断只看「名字」是不够的：旧版有个一级收入分类「红包」，新版「红包」是「人情」的
    二级子类——同名不同位置，必须按 type + parent 一起判断（`_is_in_new_taxonomy`）。
    有引用的（例如「早餐」还挂着 1 条真实账单）一律保留——宁可界面多一点，
    也不为了好看让历史账单变成孤儿。按 user_id 隔离，重复调用幂等。
    返回删除掉的分类条数。
    """
    removed = 0
    user_ids = [row["user_id"] for row in conn.execute("SELECT DISTINCT user_id FROM categories")]
    for uid in user_ids:
        rows = _user_category_rows(conn, uid)
        rows_by_id = {row["id"]: row for row in rows}
        for row in rows:
            name = str(row["name"] or "").strip()
            if name not in LEGACY_DEFAULT_CATEGORY_NAMES:
                continue
            if _is_in_new_taxonomy(row, rows_by_id):
                continue
            if _category_record_count(conn, uid, row["id"], name):
                continue
            children = [child for child in rows if child["parent_id"] == row["id"]]
            if any(_category_record_count(conn, uid, c["id"], c["name"]) for c in children):
                continue
            # 孩子已经落进新体系时不能连坐删除——那会让用户丢掉新分类
            if any(_is_in_new_taxonomy(c, rows_by_id) for c in children):
                continue
            for child in children:
                conn.execute(
                    "DELETE FROM categories WHERE id = ? AND user_id = ?", (child["id"], uid)
                )
            conn.execute("DELETE FROM categories WHERE id = ? AND user_id = ?", (row["id"], uid))
            removed += 1
    return removed


def _migrate_v0140_taxonomy(conn):
    """v0.14.0 一次性迁移：清洗脏分类 → 清理旧默认分类 → 给所有用户补种新默认分类与账户。

    为什么要用 schema_migrations 记标记：`_seed_categories` 是「补缺不覆盖」，
    如果每次启动都跑，用户主动删掉的默认分类会在重启后复活（v0.13 起明确不许）。
    迁移只跑一次，之后注册链路走 `ensure_category_templates` 给新用户补种。

    额外兜底：v0.14.0 开发期有一轮初始化把「基金账户 / 股票账户」写成了 normal，
    这里按名字一次性纠正成 investment（只跑一次，之后用户手动改的类型不再被覆盖）。
    """
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "  name TEXT PRIMARY KEY, applied_at TEXT DEFAULT CURRENT_TIMESTAMP)"
    )
    done = conn.execute(
        "SELECT 1 FROM schema_migrations WHERE name = ?", (TAXONOMY_MIGRATION_KEY,)
    ).fetchone()
    if done is not None:
        return False
    dirty_removed = _cleanup_dirty_categories(conn)
    legacy_removed = _cleanup_legacy_default_categories(conn)
    user_ids = [row["id"] for row in conn.execute("SELECT id FROM users ORDER BY id")]
    for uid in user_ids:
        _seed_categories(conn, uid)
        _seed_income_categories(conn, uid)
        _seed_accounts(conn, uid)
    conn.execute(
        "UPDATE accounts SET type = ? WHERE group_name = ? AND type = ? AND name IN (?, ?)",
        (
            INVESTMENT_ACCOUNT_TYPE,
            "投资账户",
            DEFAULT_ACCOUNT_TYPE,
            "基金账户",
            "股票账户",
        ),
    )
    conn.execute(
        "INSERT OR REPLACE INTO schema_migrations (name) VALUES (?)",
        (TAXONOMY_MIGRATION_KEY,),
    )
    print(
        "[v0.14.0] 默认分类体系迁移完成：脏分类 %d 条、旧默认分类 %d 条"
        % (dirty_removed, legacy_removed),
        flush=True,
    )
    return True


def ensure_category_templates(user_id=None):
    """给指定用户补齐一整套默认分类模板，返回**本次新增的条数**（幂等，重复调用返回 0）。

    A5/A6：注册成功与前端登录后兜底都调它。「补缺不覆盖」——已存在的同名同级分类
    不会被覆盖也不会重复插入（第二次调用返回 0）。

    口径澄清：**这是「显式补齐」动作**（注册 / 用户手动点「同步默认分类」才会跑），
    `init_db()` 启动只给 1 号管理员补种，不会给既有用户补种，
    所以「用户删过的分类不会因为重启 App 而复活」这条保证成立。
    user_id 必须显式传（F3），注册链路不在请求上下文里。
    """
    uid = _resolve_user_id(user_id)
    conn = get_conn()
    try:
        with conn:
            before = conn.execute(
                "SELECT COUNT(*) AS n FROM categories WHERE user_id = ?", (uid,)
            ).fetchone()["n"]
            _seed_categories(conn, uid)
            _seed_income_categories(conn, uid)
            after = conn.execute(
                "SELECT COUNT(*) AS n FROM categories WHERE user_id = ?", (uid,)
            ).fetchone()["n"]
        return after - before
    finally:
        conn.close()


def _seed_accounts(conn, user_id=None):
    """按 ACCOUNT_SEEDS 补齐默认账户。INSERT OR IGNORE 不会覆盖已有余额。

    v0.14.0：支持指定用户（迁移要给所有用户补新默认账户），并按大类顺手写对
    `accounts.type`——「投资账户」下的基金账户 / 股票账户直接标成 investment，
    省得用户建完还要去资产页手动切类型。
    """
    uid = _resolve_user_id(user_id)
    for name, group_name in ACCOUNT_SEEDS:
        account_type = (
            INVESTMENT_ACCOUNT_TYPE if group_name == "投资账户" else DEFAULT_ACCOUNT_TYPE
        )
        conn.execute(
            "INSERT OR IGNORE INTO accounts (user_id, name, balance, group_name, type) "
            "VALUES (?, ?, 0, ?, ?)",
            (uid, name, group_name, account_type),
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


# v0.14.1：AI 记忆库默认纠错示例。
# 只做「缺哪条补哪条」的幂等插入，绝不覆盖或删除用户已有记忆；
# note 统一带【系统示例】前缀，方便管理员识别、且在 AI 取 few-shot 时排除，
# 这样列表丰满但不会把示例当成用户真实纠错习惯喂给模型。
DEFAULT_AI_MEMORIES = (
    ("中午点了一份外卖 35 元", "餐饮", "外卖", "【系统示例】外卖类商户统一归到「外卖」"),
    ("美团外卖 28 块", "餐饮美食", "外卖", "【系统示例】美团 / 饿了么一律判为外卖，不按商户名建分类"),
    ("打车去公司花了 23", "交通", "打车", "【系统示例】打车 / 出租 / 网约车归到「打车」"),
    ("滴滴快车 17.5", "出行", "打车", "【系统示例】平台名不是分类，按出行场景回标准分类"),
    ("地铁 4 元", "交通出行", "公共交通", "【系统示例】地铁 / 公交与打车分开记账"),
    ("午饭 15.5+20*2", "其他", "餐饮", "【系统示例】金额算式取实付合计，不取单个分项"),
    ("实付 39.9，优惠前 59", "购物", "购物", "【系统示例】金额只认「实付」，忽略划线价 / 优惠前"),
    ("微信零钱付款 18", "支付宝", "微信", "【系统示例】按支付渠道纠正账户，不猜品牌别名"),
)

SEED_MEMORY_MARK = "【系统示例】"


def _seed_ai_memory_defaults(conn):
    """幂等补齐默认 Few-Shot 纠错示例；按 original_text 判重，重复启动不会插入重复行。"""
    for original_text, raw, corrected, note in DEFAULT_AI_MEMORIES:
        exists = conn.execute(
            "SELECT 1 FROM ai_memory WHERE original_text = ? LIMIT 1",
            (original_text,),
        ).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO ai_memory (original_text, raw_category, corrected_category, note) "
            "VALUES (?, ?, ?, ?)",
            (original_text, raw, corrected, note),
        )


def _backfill_category_ids(conn):
    """给老账目补 category_id（**逐用户进行**，杜绝把 A 用户的分类建到 1 号名下）。

    老库的 records 只存 category 文本（甚至是用户随手写的「卫浴」「二分」），
    对每个 user_id 分三步：
    1. 该用户账目里出现过、他名下分类表里没有的名字 → 补成一枚一级分类（不丢数据、不丢展示）
    2. 按「一级分类同名」回填 category_id
    3. 还剩下没填上的（名字只存在于二级分类），按任意同名分类回填
    """
    user_rows = conn.execute(
        "SELECT DISTINCT user_id FROM records WHERE user_id IS NOT NULL"
    ).fetchall()
    user_ids = [int(row["user_id"]) for row in user_rows]
    if not user_ids:
        user_ids = [ADMIN_USER_ID]

    for uid in user_ids:
        if uid <= 0:
            uid = ADMIN_USER_ID

        known = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM categories WHERE user_id = ?", (uid,)
            )
        }
        for row in conn.execute(
            "SELECT DISTINCT category FROM records "
            "WHERE user_id = ? AND category IS NOT NULL AND TRIM(category) <> ''",
            (uid,),
        ):
            name = str(row["category"]).strip()
            if name and name not in known:
                _ensure_category(conn, name, None, "expense", uid)
                known.add(name)

        conn.execute(
            """
            UPDATE records
               SET category_id = (
                       SELECT c.id FROM categories c
                        WHERE c.name = records.category AND c.parent_id IS NULL
                          AND c.user_id = records.user_id)
             WHERE category_id IS NULL AND user_id = ?
            """,
            (uid,),
        )
        conn.execute(
            """
            UPDATE records
               SET category_id = (
                       SELECT c.id FROM categories c
                        WHERE c.name = records.category AND c.user_id = records.user_id
                        ORDER BY c.parent_id IS NOT NULL, c.id
                        LIMIT 1)
             WHERE category_id IS NULL AND user_id = ?
            """,
            (uid,),
        )


def _ensure_user_schema(conn):
    """v0.12 多用户基建：users / import_history 建表、核心表补 user_id、老数据回填 1 号。

    迁移只做结构，不删任何数据：
    - 账户表若是 v0.11 的 name 单主键，重建成 (user_id, name) 复合主键，
      老账户全部归 1 号管理员，余额/分组/排序原样保留；
    - records / debts / contacts / categories / ai_memory / ai_correction_log /
      notifications / feedback 补 user_id 列，老数据回填 1；
    - 建 1 号超级管理员（邮箱与初始密码见常量），并把 users 的 sqlite_sequence
      钉在 9，保证普通注册从 id=10 开始，1-9 号永远留给系统账号。
    """
    from werkzeug.security import generate_password_hash

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    NOT NULL UNIQUE,
            password_hash TEXT    NOT NULL,
            phone         TEXT    NOT NULL DEFAULT '',
            nickname      TEXT    NOT NULL DEFAULT '',
            avatar        TEXT    NOT NULL DEFAULT '',
            created_at    TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    user_columns = [row["name"] for row in conn.execute("PRAGMA table_info(users)")]
    if "phone" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
    if "nickname" not in user_columns:
        # v0.12.2：老用户没昵称，回填成邮箱 @ 前面的部分，侧边栏永远有字可显示
        conn.execute("ALTER TABLE users ADD COLUMN nickname TEXT NOT NULL DEFAULT ''")
        conn.execute(
            "UPDATE users SET nickname = substr(email, 1, instr(email, '@') - 1) "
            "WHERE nickname = ''"
        )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS login_attempts (
            email        TEXT PRIMARY KEY,
            fail_count   INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT    NOT NULL DEFAULT ''
        )
        """
    )
    if "created_at" not in user_columns:
        conn.execute("ALTER TABLE users ADD COLUMN created_at TEXT NOT NULL DEFAULT ''")
    if "avatar" not in user_columns:
        # v0.12.7：个人中心支持上传头像；空串表示继续用昵称首字母色块
        conn.execute("ALTER TABLE users ADD COLUMN avatar TEXT NOT NULL DEFAULT ''")

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS import_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL DEFAULT 1,
            source     TEXT    NOT NULL DEFAULT 'wechat',
            filename   TEXT    NOT NULL DEFAULT '',
            total      INTEGER NOT NULL DEFAULT 0,
            imported   INTEGER NOT NULL DEFAULT 0,
            duplicated INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    NOT NULL DEFAULT ''
        )
        """
    )

    # 1) 账户表：老库是 name 单主键，多用户同名账户会撞车，必须重建成 (user_id, name)
    account_columns = [row["name"] for row in conn.execute("PRAGMA table_info(accounts)")]
    if "user_id" not in account_columns:
        conn.execute("ALTER TABLE accounts RENAME TO accounts_legacy_v0118")
        conn.execute(
            """
            CREATE TABLE accounts (
                user_id    INTEGER NOT NULL DEFAULT 1,
                name       TEXT    NOT NULL,
                balance    REAL    NOT NULL DEFAULT 0,
                group_name TEXT    NOT NULL DEFAULT '资金账户',
                sort_order INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, name)
            )
            """
        )
        conn.execute(
            "INSERT INTO accounts (user_id, name, balance, group_name, sort_order) "
            "SELECT 1, name, balance, group_name, sort_order FROM accounts_legacy_v0118"
        )
        conn.execute("DROP TABLE accounts_legacy_v0118")

    # 2) 其余核心表补 user_id：老数据全部归 1 号管理员
    core_tables = (
        "records",
        "debts",
        "contacts",
        "categories",
        "ai_memory",
        "ai_correction_log",
        "ai_feedback",
        "notifications",
        "feedback",
    )
    existing_tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    for table in core_tables:
        if table not in existing_tables:
            continue
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(%s)" % table)]
        if "user_id" not in columns:
            conn.execute("ALTER TABLE %s ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1" % table)
        conn.execute("UPDATE %s SET user_id = 1 WHERE user_id IS NULL OR user_id <= 0" % table)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_%s_user ON %s (user_id)" % (table, table)
        )

    # 3) 借贷字段扩展（v0.12.3）：due_date / interest / image_path
    if "debts" in existing_tables:
        debt_columns = [row["name"] for row in conn.execute("PRAGMA table_info(debts)")]
        if "due_date" not in debt_columns:
            conn.execute("ALTER TABLE debts ADD COLUMN due_date TEXT NOT NULL DEFAULT ''")
        if "interest" not in debt_columns:
            conn.execute("ALTER TABLE debts ADD COLUMN interest REAL NOT NULL DEFAULT 0")
        if "image_path" not in debt_columns:
            conn.execute("ALTER TABLE debts ADD COLUMN image_path TEXT NOT NULL DEFAULT ''")
        # v0.13.8：已还金额，支持部分还款；remaining = amount - repaid
        if "repaid" not in debt_columns:
            conn.execute("ALTER TABLE debts ADD COLUMN repaid REAL NOT NULL DEFAULT 0")

    # 图标素材库（v0.12.3）：系统图标 user_id=0，用户上传挂自己的 id
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS icons (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL DEFAULT '',
            path       TEXT    NOT NULL,
            is_system  INTEGER NOT NULL DEFAULT 0,
            user_id    INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS user_icon_settings (
            user_id INTEGER NOT NULL,
            kind    TEXT    NOT NULL,
            name    TEXT    NOT NULL,
            icon_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, kind, name)
        )
        """
    )

    # 4) 1 号超级管理员：只建一次，之后改密码走接口
    admin = conn.execute("SELECT id FROM users WHERE id = ?", (ADMIN_USER_ID,)).fetchone()
    if admin is None:
        conn.execute(
            "INSERT INTO users (id, email, password_hash, phone, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                ADMIN_USER_ID,
                ADMIN_EMAIL,
                generate_password_hash(ADMIN_INITIAL_PASSWORD),
                "",
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )

    # 4) ID 预留：把 users 自增序列钉在 9，普通注册必然从 10 开始
    sequence = conn.execute(
        "SELECT seq FROM sqlite_sequence WHERE name = 'users'"
    ).fetchone()
    if sequence is None:
        conn.execute(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('users', ?)",
            (USER_ID_RESERVED_MAX,),
        )
    elif sequence["seq"] < USER_ID_RESERVED_MAX:
        conn.execute(
            "UPDATE sqlite_sequence SET seq = ? WHERE name = 'users'",
            (USER_ID_RESERVED_MAX,),
        )


def _backup_db():
    """迁移前把 records.db 复制一份到 temp 备份目录，返回备份文件的绝对路径。

    备份失败一律抛出，由 `_migrate_category_isolation` 中止迁移——宁可启动失败，
    也不允许在没备份的情况下改表结构。同一进程内只备份一次（迁移幂等，重复启动无需重复拷贝）。
    """
    global _MIGRATION_BACKUP_FILE
    if _MIGRATION_BACKUP_FILE and Path(_MIGRATION_BACKUP_FILE).exists():
        return _MIGRATION_BACKUP_FILE
    if not DB_PATH.exists():
        # 全新库：文件还没落盘，没有任何数据可丢
        return ""
    MIGRATION_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    target = MIGRATION_BACKUP_DIR / ("records.db.bak-%s" % stamp)
    shutil.copy2(DB_PATH, target)
    _MIGRATION_BACKUP_FILE = str(target)
    return _MIGRATION_BACKUP_FILE


def _migrate_category_isolation(conn):
    """v0.13.1 分类隔离迁移（幂等，严格按 9 步顺序执行，顺序不可调换）。

    步 0 备份（失败即中止）→ 1 判表 → 2 补 user_id → 3 回填 user_id → 4 建索引
    → 5 补 type → 6 补 icon_key/color/is_disabled/disabled_at
    → 7 建 (user_id, parent, name) 唯一索引（失败即中止）
    → 8 删旧的 uq_categories（失败仅告警）→ 9 建 recurring_templates。

    **关键口径**：步 3 的回填必须在步 7 建唯一索引之前——SQLite 视 NULL 互不相等，
    顺序反了会让「同名 + NULL user_id」的行静默绕过唯一约束。
    调用点固定在 `init_db()` 里 `_ensure_user_schema()` 之后、第二段 DML 之前。
    """
    # 步 0：迁移前备份，失败即中止（不允许裸奔）
    try:
        backup_path = _backup_db()
    except Exception as exc:  # noqa: BLE001 - 备份失败必须整体中止
        raise RuntimeError(
            "[v0.13.1] 迁移前备份 records.db 失败，已中止分类隔离迁移：%s" % exc
        )
    if backup_path:
        print("[v0.13.1] 迁移前备份完成：%s" % backup_path, flush=True)

    # 步 1：categories 表不存在（全新库首启）→ 直接返回，后续 CREATE TABLE 已带齐新列
    table_exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'categories'"
    ).fetchone()
    if table_exists is None:
        return

    def _columns():
        return [row["name"] for row in conn.execute("PRAGMA table_info(categories)")]

    # 步 2：补 user_id（已有则跳过）
    if "user_id" not in _columns():
        conn.execute("ALTER TABLE categories ADD COLUMN user_id INTEGER NOT NULL DEFAULT 1")

    # 步 3：回填 user_id。必须在建唯一索引之前做
    conn.execute("UPDATE categories SET user_id = 1 WHERE user_id IS NULL OR user_id <= 0")

    # 步 4：user_id 查询索引
    conn.execute("CREATE INDEX IF NOT EXISTS idx_categories_user ON categories (user_id)")

    # 步 5：补 type（收支分组）+ 空值回填
    if "type" not in _columns():
        conn.execute(
            "ALTER TABLE categories ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'"
        )
    conn.execute("UPDATE categories SET type = 'expense' WHERE type IS NULL OR type = ''")

    # 步 6：逐列补展示/停用字段，已存在则跳过
    extra_columns = (
        ("icon_key", "ALTER TABLE categories ADD COLUMN icon_key TEXT DEFAULT ''"),
        ("color", "ALTER TABLE categories ADD COLUMN color TEXT DEFAULT ''"),
        (
            "is_disabled",
            "ALTER TABLE categories ADD COLUMN is_disabled INTEGER NOT NULL DEFAULT 0",
        ),
        ("disabled_at", "ALTER TABLE categories ADD COLUMN disabled_at TEXT"),
    )
    for column_name, statement in extra_columns:
        if column_name not in _columns():
            conn.execute(statement)

    # 步 7：跨用户同名唯一索引。失败 = 库里有脏同名数据，必须人工处理，故中止
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_categories_user "
            "ON categories (user_id, COALESCE(parent_id, 0), name)"
        )
    except sqlite3.Error as exc:
        raise RuntimeError(
            "[v0.13.1] 建立 uq_categories_user 失败（库内存在同一用户下的同名分类，"
            "需人工清理后重启）：%s" % exc
        )

    # 步 8：删掉旧的全局唯一索引。失败只告警——新索引已生效，不影响隔离语义
    try:
        conn.execute("DROP INDEX IF EXISTS uq_categories")
    except sqlite3.Error as exc:
        print("[v0.13.1] 警告：删除旧索引 uq_categories 失败（不影响隔离，可手工清理）：%s" % exc, flush=True)

    # 步 9：周期账单模板表（C3 的数据底座，本轮只建表）
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS recurring_templates (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id        INTEGER NOT NULL DEFAULT 1,
            name           TEXT    NOT NULL DEFAULT '',
            record_type    TEXT    NOT NULL DEFAULT 'expense',
            amount         REAL    NOT NULL DEFAULT 0,
            category_id    INTEGER,
            account        TEXT    NOT NULL DEFAULT '',
            note           TEXT    NOT NULL DEFAULT '',
            day_of_month   INTEGER NOT NULL DEFAULT 1,
            last_posted_at TEXT    NOT NULL DEFAULT '',
            is_active      INTEGER NOT NULL DEFAULT 1,
            created_at     TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_recurring_user ON recurring_templates (user_id)"
    )


def _migrate_investment_schema(conn, accounts_need_type=False):
    """v0.13.3 投资体系迁移（幂等，严格按 10 步顺序执行，顺序不可调换）。

    步 0 备份（失败即中止）→ 1 判列补 `accounts.type` + 建迁移标记表
    → 2 **按标记位一次性回填 investment** → 3 净化非法 type → 4 明确不建 type 索引
    → 5 建 invest_platforms → 6 平台索引 + 唯一索引（失败即中止）
    → 7 建 holdings + 索引 + 唯一索引（失败即中止）→ 8 建 dca_plans + 索引
    → 9 给每个投资账户补「默认」子平台 → 10 打印日志。

    **步 2 为什么改用 `schema_migrations` 标记位**（v0.13.3 实测踩坑）：
    原实现是「只在刚补出 type 列的那一轮回填」，靠 `accounts_need_type` 标志位判断。
    但本机真实库是**先落了 type 列、后补迁移函数**的——列早就存在，标志位永远是 False，
    回填永远不执行，结果 10 个账户全是 normal，「投资账户」分组也挂不上看板。
    标记位方案可恢复：只要没打过 `invest_type_backfill_v0133` 标记就回填一次并打标记，
    打过之后**用户手动改过的 type 永不被覆盖**（幂等 + 可自愈，两者兼得）。

    **为什么独占一个 `with conn:` 块且挂在 `_migrate_category_isolation()` 之后、
    第二段 DML 之前**（设计 D4）：
    ① SQLite 的 DDL 会隐式提交当前事务，三张新表的 DDL 必须与其它 DML 分开提交；
    ② 挂在第二段 DML 之后会让「本段给投资账户补默认平台」时表还不存在；
    ③ 与 v0.13.1 的九步范式完全同构，审计时一眼能对上。

    `accounts_need_type` 由 `init_db()` 传入（第一段 DDL 里刚 ALTER 出来的那一轮为 True）；
    本函数内部若自己补了列也会置 True，保证「标志位只由真实补列动作驱动」。
    """
    # 步 0：迁移前备份，失败即中止（不允许裸奔改表）
    # 注意：`_backup_db()` 是进程级单例，v0.13.1 与本轮共用同一份 BASELINE 备份（设计 F8）。
    try:
        backup_path = _backup_db()
    except Exception as exc:  # noqa: BLE001 - 备份失败必须整体中止
        raise RuntimeError(
            "[v0.13.3] 迁移前备份 records.db 失败，已中止投资体系迁移：%s" % exc
        )
    if backup_path:
        print("[v0.13.3] 迁移前备份完成：%s" % backup_path, flush=True)

    # 步 1：accounts 没有 type 就补（带非空默认值，已有行自动填 'normal'，一行不丢）
    has_accounts = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'accounts'"
    ).fetchone()
    if has_accounts is not None:
        account_columns = [
            row["name"] for row in conn.execute("PRAGMA table_info(accounts)")
        ]
        if "type" not in account_columns:
            conn.execute(
                "ALTER TABLE accounts ADD COLUMN type TEXT NOT NULL DEFAULT 'normal'"
            )
            accounts_need_type = True

    # 步 1.5：迁移标记表。单行一个标记名，供后续各版迁移「一次性动作」复用
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            name       TEXT PRIMARY KEY,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # 步 2：**按标记位一次性回填**——展示分组为「投资账户」的账户升级为投资账户。
    # 标记位兜住是硬性要求：回填只做一次，之后用户手动改的 type 永不被覆盖。
    marker = "invest_type_backfill_v0133"
    already_done = conn.execute(
        "SELECT name FROM schema_migrations WHERE name = ?", (marker,)
    ).fetchone()
    if already_done is None or accounts_need_type:
        conn.execute(
            "UPDATE accounts SET type = ? WHERE group_name = ?",
            (INVESTMENT_ACCOUNT_TYPE, "投资账户"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO schema_migrations (name) VALUES (?)", (marker,)
        )

    # 步 3：净化非法取值（每次执行成本极低，可重复）。无 CHECK 约束，靠这里兜底
    conn.execute(
        "UPDATE accounts SET type = ? WHERE type IS NULL OR type NOT IN (?, ?)",
        (DEFAULT_ACCOUNT_TYPE, DEFAULT_ACCOUNT_TYPE, INVESTMENT_ACCOUNT_TYPE),
    )

    # 步 4：明确**不建** type 索引——基数只有 2，且 (user_id, name) 已覆盖所有查询

    # 步 5：投资子平台（账户 → 平台 一对多）。
    # 注意列名叫 `account`（账户**名**）而不是 account_id：accounts 主键是 (user_id, name)
    # 没有单列 id，全项目引用账户一律用名字（设计 U1 / F1）。
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS invest_platforms (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL DEFAULT 1,
            account    TEXT    NOT NULL,
            name       TEXT    NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )

    # 步 6：平台索引。唯一索引失败 = 库里有同名脏数据，必须人工处理，故中止
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ip_user ON invest_platforms (user_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_ip_user_account "
        "ON invest_platforms (user_id, account)"
    )
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_ip_user_account_name "
            "ON invest_platforms (user_id, account, name)"
        )
    except sqlite3.Error as exc:
        raise RuntimeError(
            "[v0.13.3] 建立 uq_ip_user_account_name 失败（同一投资账户下存在同名子平台，"
            "需人工清理后重启）：%s" % exc
        )

    # 步 7：持仓。current_price 恒存 0 表示「未接行情」，读取时由 _row_to_holding 回落 cost_price
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS holdings (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL DEFAULT 1,
            platform_id   INTEGER NOT NULL REFERENCES invest_platforms(id),
            ticker        TEXT    NOT NULL DEFAULT '',
            name          TEXT    NOT NULL,
            asset_type    TEXT    NOT NULL DEFAULT 'fund',
            shares        REAL    NOT NULL DEFAULT 0,
            cost_price    REAL    NOT NULL DEFAULT 0,
            current_price REAL    NOT NULL DEFAULT 0,
            cost_total    REAL    NOT NULL DEFAULT 0,
            record_id     INTEGER,
            created_at    TEXT    DEFAULT CURRENT_TIMESTAMP,
            updated_at    TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_h_user ON holdings (user_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_h_user_platform ON holdings (user_id, platform_id)"
    )
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_h_user_platform_name "
            "ON holdings (user_id, platform_id, name)"
        )
    except sqlite3.Error as exc:
        raise RuntimeError(
            "[v0.13.3] 建立 uq_h_user_platform_name 失败（同一平台下存在同名持仓，"
            "需人工清理后重启）：%s" % exc
        )

    # 步 8：定投计划。本期只落库 + 展示，不自动生成任何账目
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS dca_plans (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id    INTEGER NOT NULL DEFAULT 1,
            holding_id INTEGER NOT NULL REFERENCES holdings(id),
            amount     REAL    NOT NULL DEFAULT 0,
            frequency  TEXT    NOT NULL DEFAULT 'monthly',
            next_date  TEXT    NOT NULL DEFAULT '',
            source_account TEXT NOT NULL DEFAULT '',
            status     TEXT    NOT NULL DEFAULT 'active',
            created_at TEXT    DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_dca_user ON dca_plans (user_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dca_user_holding "
        "ON dca_plans (user_id, holding_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_dca_user_next ON dca_plans (user_id, next_date)"
    )

    # 步 8.5（v0.13.3 补）：定投计划的**扣款来源账户**。
    # 15 位的旧库里 dca_plans 没有这一列，靠 PRAGMA 判存在后再 ALTER，幂等且可自愈。
    # 空串表示「就用投资账户自己的可用资金」，与买入不指定来源时的口径一致。
    dca_columns = [row["name"] for row in conn.execute("PRAGMA table_info(dca_plans)")]
    if "source_account" not in dca_columns:
        conn.execute(
            "ALTER TABLE dca_plans ADD COLUMN source_account TEXT NOT NULL DEFAULT ''"
        )

    # 步 9：给每个投资账户补一个「默认」子平台。
    # INSERT OR IGNORE + 唯一索引双保险：重复执行行数绝不增长（迁移幂等的核心验证点之一）
    conn.execute(
        "INSERT OR IGNORE INTO invest_platforms (user_id, account, name, sort_order) "
        "SELECT user_id, name, ?, 0 FROM accounts WHERE type = ?",
        (INVEST_PLATFORM_DEFAULT, INVESTMENT_ACCOUNT_TYPE),
    )

    # 步 10：一行日志，便于现场确认迁移跑过
    platform_count = conn.execute(
        "SELECT COUNT(*) AS c FROM invest_platforms"
    ).fetchone()["c"]
    print("[v0.13.3] 投资体系迁移完成：platforms=%d" % platform_count, flush=True)


# ---------------- 邮箱验证码（v0.13.4） ----------------

EMAIL_CODE_MAX_ATTEMPTS = 5


def _migrate_email_verification(conn):
    """v0.13.4 邮箱验证码迁移（幂等）：建 email_verifications 表 + 索引。

    验证码**只存哈希**（永不存明文，加盐哈希在 app.py 侧计算）、5 分钟过期、
    5 次尝试上限。expires_at / created_at 存 epoch 秒（REAL），便于与 time.time() 直接比较。
    """
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS email_verifications (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            email      TEXT    NOT NULL,
            code_hash  TEXT    NOT NULL,
            purpose    TEXT    NOT NULL DEFAULT 'register',
            attempts   INTEGER NOT NULL DEFAULT 0,
            expires_at REAL    NOT NULL,
            created_at REAL    NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_email_verifications_email_purpose "
        "ON email_verifications(email, purpose)"
    )


def save_email_code(email, code_hash, purpose, ttl_seconds):
    """写 / 覆盖一条验证码（同一 email+purpose 只保留最新一条），返回 created_at（epoch 秒）。"""
    now = time.time()
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "DELETE FROM email_verifications WHERE email = ? AND purpose = ?",
                (email, purpose),
            )
            conn.execute(
                "INSERT INTO email_verifications "
                "(email, code_hash, purpose, attempts, expires_at, created_at) "
                "VALUES (?, ?, ?, 0, ?, ?)",
                (email, code_hash, purpose, now + ttl_seconds, now),
            )
    finally:
        conn.close()
    return now


def get_email_code(email, purpose):
    """取该 email+purpose 的最新验证码记录，无则 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, email, code_hash, purpose, attempts, expires_at, created_at "
            "  FROM email_verifications WHERE email = ? AND purpose = ? "
            " ORDER BY id DESC LIMIT 1",
            (email, purpose),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def email_code_recent(email, purpose, interval_seconds):
    """最近 interval_seconds 秒内是否已发过验证码（防刷）。"""
    row = get_email_code(email, purpose)
    if row is None:
        return False
    return (time.time() - row["created_at"]) < interval_seconds


def register_email_code_attempt(email, purpose):
    """验证失败时记一次尝试；达到上限则删除记录（作废，须重新发码）。返回本次累计次数。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT id, attempts FROM email_verifications "
                " WHERE email = ? AND purpose = ? ORDER BY id DESC LIMIT 1",
                (email, purpose),
            ).fetchone()
            if row is None:
                return 0
            attempts = row["attempts"] + 1
            if attempts >= EMAIL_CODE_MAX_ATTEMPTS:
                conn.execute(
                    "DELETE FROM email_verifications WHERE id = ?", (row["id"],)
                )
            else:
                conn.execute(
                    "UPDATE email_verifications SET attempts = ? WHERE id = ?",
                    (attempts, row["id"]),
                )
            return attempts
    finally:
        conn.close()


def consume_email_code(email, purpose):
    """验证成功 / 作废时删除记录（标记失效）。"""
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "DELETE FROM email_verifications WHERE email = ? AND purpose = ?",
                (email, purpose),
            )
    finally:
        conn.close()


def init_db():
    """建表 + 兼容旧库升级。反复启动不会报错，旧库也不会丢数据。"""
    conn = get_conn()
    # 这一轮是不是刚补的 sort_order 列：只有刚补时才按旧顺序回填，
    # 否则每次启动都会把用户拖拽出来的顺序重置回「按 id / rowid」
    categories_need_order = False
    accounts_need_order = False
    # v0.13.3：这一轮是不是刚给 accounts 补的 type 列——只有刚补时才回填
    # 「投资账户」分组的账户类型，否则每次启动都会把用户手动改过的类型重置回去
    accounts_need_type = False
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
                    user_id    INTEGER NOT NULL DEFAULT 1,
                    name       TEXT NOT NULL,
                    balance    REAL NOT NULL DEFAULT 0,
                    group_name TEXT NOT NULL DEFAULT '资金账户',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    type       TEXT NOT NULL DEFAULT 'normal',
                    PRIMARY KEY (user_id, name)
                )
                """
            )
            account_columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(accounts)")
            ]
            # v0.13.3 F6 双保险：type 直接写进 CREATE（新库一步到位），
            # 老库由下面的幂等 ALTER 补齐。只有「刚补列的那一次」才回填
            # group_name='投资账户' → type='investment'（accounts_need_type 标志控制）。
            if "type" not in account_columns:
                conn.execute(
                    "ALTER TABLE accounts ADD COLUMN type TEXT NOT NULL DEFAULT 'normal'"
                )
                accounts_need_type = True
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
            # F6 双保险：user_id / type 直接写进 CREATE（新库一步到位），
            # 老库仍由 _ensure_user_schema + _migrate_category_isolation 的幂等 ALTER 补齐
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id    INTEGER NOT NULL DEFAULT 1,
                    name       TEXT    NOT NULL,
                    parent_id  INTEGER REFERENCES categories(id),
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    type       TEXT    NOT NULL DEFAULT 'expense'
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
            if "type" not in category_columns:
                # v0.13.1：分类区分「支出 / 收入」，记账弹窗按收支严格过滤，互不串
                conn.execute(
                    "ALTER TABLE categories ADD COLUMN type TEXT NOT NULL DEFAULT 'expense'"
                )
            # 老分类无 type 一律按支出回填（历史账目几乎都是支出），幂等可重复执行
            conn.execute(
                "UPDATE categories SET type = 'expense' WHERE type IS NULL OR type = ''"
            )
            # v0.13.1：分类唯一性改由 `_migrate_category_isolation` 的
            # `uq_categories_user (user_id, COALESCE(parent_id,0), name)` 承担，
            # 这里**不再重建旧的全局 uq_categories**——跨用户同名是合法数据，
            # 每次启动重建它会直接撞 UNIQUE 约束导致 init_db 失败（App 起不来）。

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
                    status     TEXT    NOT NULL DEFAULT 'unpaid',
                    due_date   TEXT    NOT NULL DEFAULT '',
                    interest   REAL    NOT NULL DEFAULT 0,
                    image_path TEXT    NOT NULL DEFAULT '',
                    repaid     REAL    NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_debts_contact ON debts (contact_id)"
            )
            # 图标素材库（v0.12.3）：is_system=1 是内置图标（user_id=0），user_id>0 是用户上传
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS icons (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    name       TEXT    NOT NULL DEFAULT '',
                    path       TEXT    NOT NULL,
                    is_system  INTEGER NOT NULL DEFAULT 0,
                    user_id    INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT    DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # 用户个性化：某个分类/账户用哪张图标
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_icon_settings (
                    user_id INTEGER NOT NULL,
                    kind    TEXT    NOT NULL,
                    name    TEXT    NOT NULL,
                    icon_id INTEGER NOT NULL,
                    PRIMARY KEY (user_id, kind, name)
                )
                """
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

            # v0.14.0：后台「提示文案管理」的文案库。toast() 优先取这里 is_active=1 的
            # 随机文案，接口不可用时才回退前端内置的颜文字保底文案。
            # type 走应用层白名单（success / error / info / warn），不加 CHECK，
            # 保持「新库 / 老库」结构一致。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS system_tips (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    type       TEXT    NOT NULL DEFAULT 'success',
                    content    TEXT    NOT NULL,
                    location   TEXT    NOT NULL DEFAULT '',
                    is_active  INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT    NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_system_tips_type ON system_tips (type, is_active)"
            )
            # v0.14.0：老库的 system_tips 没有 location 列（场景位置标签），
            # 新库建表时已直接带上，这里 PRAGMA 幂等检查，缺了才补，已有行自动填空串。
            tip_columns = [
                row["name"] for row in conn.execute("PRAGMA table_info(system_tips)")
            ]
            if "location" not in tip_columns:
                conn.execute(
                    "ALTER TABLE system_tips ADD COLUMN location TEXT NOT NULL DEFAULT ''"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_system_tips_location "
                "ON system_tips (location, is_active)"
            )

            # v0.14.0：设置弹窗「帮助与反馈」提交的用户反馈。
            # 与 v0.10 的 ai_feedback 分开存：ai_feedback 是 AI 解析纠错样本，
            # 这张表是用户找客服的问题单，后台「用户反馈」Tab 直接读它。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS user_feedback (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id           INTEGER NOT NULL,
                    email             TEXT    NOT NULL DEFAULT '',
                    nickname          TEXT    NOT NULL DEFAULT '',
                    issue_description TEXT    NOT NULL DEFAULT '',
                    occur_date        TEXT    NOT NULL DEFAULT '',
                    image_path        TEXT    NOT NULL DEFAULT '',
                    contact_type      TEXT    NOT NULL DEFAULT '',
                    contact_info      TEXT    NOT NULL DEFAULT '',
                    created_at        TEXT    NOT NULL DEFAULT ''
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_feedback_user "
                "ON user_feedback (user_id, created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_user_feedback_created "
                "ON user_feedback (created_at)"
            )

            # v0.14.0：帮助内容配置（FAQ / 快捷键 / 联系方式 / 反馈占位文案）。
            # 单行 key/value 配置表，缺 key 时由 _seed_help_settings 灌默认值，
            # 管理员在后台改过之后就算键已存在也不会被默认值覆盖。
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key   TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                )
                """
            )

        # v0.12：多用户基建（users / import_history / 核心表 user_id / 账户复合主键 / 1 号管理员）
        with conn:
            _ensure_user_schema(conn)

        # v0.13.1：分类隔离迁移。**顺序不可调换**——必须在 _ensure_user_schema 之后
        # （categories 表此时才存在）、第二段 DML 之前（种子要用新的唯一索引语义）。
        # 迁移独占一个 with conn: 块（SQLite DDL 会隐式提交现有事务）
        with conn:
            _migrate_category_isolation(conn)

        # v0.13.3：投资体系迁移。**顺序不可调换**——必须在 _migrate_category_isolation
        # 之后（同属结构迁移段）、第二段 DML 之前（本段自己会 INSERT 默认子平台）。
        # 同样独占一个 with conn: 块（SQLite DDL 隐式提交）。
        with conn:
            _migrate_investment_schema(conn, accounts_need_type=accounts_need_type)

        # v0.13.4：邮箱验证码表（幂等）。挂在投资迁移之后、第二段 DML 之前。
        with conn:
            _migrate_email_verification(conn)

        # 第二段：补种子数据 + 回填老数据（DML，失败可以整体回滚）。
        # D5/F3：种子固定传 ADMIN_USER_ID，保持老用户 1 号的分类体系不动
        with conn:
            # v0.14.0：分类体系一次性迁移必须排在常规补种之前——
            # 先清洗「213」这类脏分类、清理无引用的旧默认分类，再按新体系补种，
            # 这样迁移日志里「脏分类先转挂到其他、再删除」的顺序才是可验证的。
            _migrate_v0140_taxonomy(conn)
            _seed_categories(conn, ADMIN_USER_ID)
            _seed_income_categories(conn, ADMIN_USER_ID)
            _seed_accounts(conn)
            _seed_notifications(conn)
            # v0.14.1：记忆库默认纠错示例（幂等补种，不覆盖 / 不删除用户已有记忆）
            _seed_ai_memory_defaults(conn)
            _seed_system_tips(conn)
            # v0.14.0：老库的 6 条默认文案是先于 location 列存在的，补列后 location 全是空串，
            # 这里按「原文一字不改」的对应关系把场景位置补上（已有值的行不动，删光的也不复活）。
            _backfill_tip_locations(conn)
            # v0.14.0：帮助内容默认值（只补缺失的 key，管理员改过的内容不会被覆盖）
            _seed_help_settings(conn)
            _backfill_category_ids(conn)
            # 只有刚补列的那一次才回填：分类按 id、账户按 rowid，
            # 正好等于升级前「按创建先后」的显示顺序
            if categories_need_order:
                conn.execute("UPDATE categories SET sort_order = id")
            # 老账目里出现过的自定义账户也补进账户表，否则列表里查不到它
            conn.execute(
                "INSERT OR IGNORE INTO accounts (user_id, name, balance, group_name) "
                "SELECT DISTINCT user_id, account, 0, ? FROM records",
                (DEFAULT_GROUP,),
            )
            # 账户回填放在补账户之后：新补进来的行 rowid 最大，理应排最后
            if accounts_need_order:
                conn.execute("UPDATE accounts SET sort_order = rowid")
    finally:
        conn.close()  # with 只管事务，连接必须手动关


# ---------------- 分类 ----------------

def get_category(category_id):
    """按 id 取一个分类，取不到返回 None（跨用户取不到 = 取不到，返回 None → 上层 400）。

    D19：WHERE **只校验 id + user_id，绝不加 is_disabled = 0**。
    停用只影响「新增场景的选项可见性」，不影响「历史账单的引用写入」。
    """
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, user_id, name, parent_id, type, icon_key, color, is_disabled, disabled_at "
            "  FROM categories WHERE id = ? AND user_id = ?",
            (category_id, _uid()),
        ).fetchone()
        return _row_to_category(row) if row is not None else None
    finally:
        conn.close()


def ensure_category(name, category_type="expense"):
    """按名字找一级分类，没有就建一个（兼容老前端直接传分类文本的写法）。
    category_type 决定新增分类的收支归属。新建的行落在当前上下文用户（_uid()）名下。"""
    conn = get_conn()
    try:
        with conn:
            new_id = _ensure_category(conn, name, None, category_type, _uid())
        row = conn.execute(
            "SELECT id, user_id, name, parent_id, type, icon_key, color, is_disabled, disabled_at "
            "  FROM categories WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_category(row)
    finally:
        conn.close()


def list_categories_tree(include_disabled=False):
    """返回两级分类树：[{id, name, children: [...]}]，一级在前、按创建顺序排。

    v0.13.1 停用语义（P0）：
    - 默认 `include_disabled=False` → `WHERE user_id=? AND is_disabled=0`，新增场景的干净列表；
    - `include_disabled=True` 才返回全量，**只允许分类管理弹窗的「已停用」管理区使用**
      （D18：编辑态不给列表 API 加这个开关，走前端 record 自带字段零请求合成）；
    - 返回的节点**必带 is_disabled**。
    """
    conn = get_conn()
    try:
        sql = (
            "SELECT id, user_id, name, parent_id, type, icon_key, color, is_disabled, disabled_at "
            "  FROM categories WHERE user_id = ?"
        )
        if not include_disabled:
            sql += " AND is_disabled = 0"
        sql += " ORDER BY sort_order, id"
        rows = conn.execute(sql, (_uid(),)).fetchall()
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


def create_category(name, parent_id=None, category_type="expense", icon_key="", color=""):
    """新建分类，返回 (分类字典, 错误信息)。parent_id 为空表示一级分类。

    category_type: 'expense' / 'income'，决定这个分类在记账弹窗里归哪个收支分组。
    A4：父级必须属于同一用户，否则 400（杜绝把子分类挂到别人的一级分类下）。
    F5：「SELECT 后 INSERT」在并发同名时会抛 IntegrityError，
        这里捕获后转成「已存在」文案，由 app.py 映射成 409（而不是 500）。
    """
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            if parent_id is not None:
                parent = conn.execute(
                    "SELECT id, parent_id FROM categories WHERE id = ? AND user_id = ?",
                    (parent_id, uid),
                ).fetchone()
                if parent is None:
                    return None, "父级分类不存在"
                if parent["parent_id"] is not None:
                    return None, "最多支持两级分类，二级分类下不能再建子分类"

            if parent_id is None:
                dup = conn.execute(
                    "SELECT id FROM categories WHERE user_id = ? AND name = ? AND parent_id IS NULL",
                    (uid, name),
                ).fetchone()
            else:
                dup = conn.execute(
                    "SELECT id FROM categories WHERE user_id = ? AND name = ? AND parent_id = ?",
                    (uid, name, parent_id),
                ).fetchone()
            if dup is not None:
                return None, "同级下已存在同名分类"

            sibling_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM categories "
                "WHERE user_id = ? AND parent_id IS ?",
                (uid, parent_id),
            ).fetchone()["m"]
            cat_type = "income" if category_type == "income" else "expense"
            try:
                cur = conn.execute(
                    "INSERT INTO categories (user_id, name, parent_id, sort_order, type, icon_key, color) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (uid, name, parent_id, sibling_order + 1, cat_type, icon_key or "", color or ""),
                )
            except sqlite3.IntegrityError:
                # 并发窗口内的同名插入：转成「已存在」语义，app.py 靠这四个字判 409
                return None, "同级下已存在同名分类"
            return {
                "id": cur.lastrowid,
                "user_id": uid,
                "name": name,
                "parent_id": parent_id,
                "type": cat_type,
                "icon_key": icon_key or "",
                "color": color or "",
                "is_disabled": 0,
                "disabled_at": "",
                "children": [],
            }, None
    finally:
        conn.close()


def rename_category(category_id, name):
    """给分类改名，返回 (分类字典, 错误信息)。不支持改父级（改层级容易把历史账目搞乱）。"""
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            row = conn.execute(
                "SELECT id, name, parent_id, type FROM categories WHERE id = ? AND user_id = ?",
                (category_id, uid),
            ).fetchone()
            if row is None:
                return None, "分类不存在"

            if row["parent_id"] is None:
                dup = conn.execute(
                    "SELECT id FROM categories "
                    "WHERE user_id = ? AND name = ? AND parent_id IS NULL AND id <> ?",
                    (uid, name, category_id),
                ).fetchone()
            else:
                dup = conn.execute(
                    "SELECT id FROM categories "
                    "WHERE user_id = ? AND name = ? AND parent_id = ? AND id <> ?",
                    (uid, name, row["parent_id"], category_id),
                ).fetchone()
            if dup is not None:
                return None, "同级下已存在同名分类"

            conn.execute(
                "UPDATE categories SET name = ? WHERE id = ? AND user_id = ?",
                (name, category_id, uid),
            )
            # 账目里冗余存着分类名，改名要跟着改，否则列表还显示旧名字
            conn.execute(
                "UPDATE records SET category = ? WHERE category_id = ? AND user_id = ?",
                (name, category_id, uid),
            )
            updated = conn.execute(
                "SELECT id, user_id, name, parent_id, type, icon_key, color, is_disabled, disabled_at "
                "  FROM categories WHERE id = ?",
                (category_id,),
            ).fetchone()
            return _row_to_category(updated), None
    finally:
        conn.close()


def delete_category(category_id):
    """删分类，返回 (是否删除, 错误信息)。有子分类或被账目使用就拒绝，避免出现悬空引用。"""
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            row = conn.execute(
                "SELECT id, name FROM categories WHERE id = ? AND user_id = ?",
                (category_id, uid),
            ).fetchone()
            if row is None:
                return False, "分类不存在"

            children = conn.execute(
                "SELECT COUNT(*) AS c FROM categories WHERE parent_id = ? AND user_id = ?",
                (category_id, uid),
            ).fetchone()["c"]
            if children:
                return False, "该分类下还有 %d 个子分类，请先删掉子分类" % children

            used = conn.execute(
                "SELECT COUNT(*) AS c FROM records "
                "WHERE user_id = ? AND category_id = ? AND deleted_at IS NULL",
                (uid, category_id),
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目在用这个分类，删了会让它们失去分类" % used

            conn.execute("DELETE FROM categories WHERE id = ? AND user_id = ?", (category_id, uid))
            return True, None
    finally:
        conn.close()


def _category_row(conn, category_id, user_id):
    """按 (id, user_id) 取一行完整分类，取不到返回 None（供停用 / 合并回读用）。"""
    return conn.execute(
        "SELECT id, user_id, name, parent_id, type, icon_key, color, is_disabled, disabled_at "
        "  FROM categories WHERE id = ? AND user_id = ?",
        (category_id, user_id),
    ).fetchone()


def _disable_category_scope(conn, user_id, category_id):
    """把 category_id 及其一级子分类批量置为停用，返回被置停用的 id 列表。

    项目最多两级（`create_category` 已禁止在二级分类下再建子分类），
    所以按 parent_id 处理一层就足够覆盖全部后代，无需递归。
    先按 id ASC 排好，保证返回的 id 列表稳定，便于前端与审计对齐。
    """
    rows = conn.execute(
        "SELECT id FROM categories WHERE user_id = ? AND (id = ? OR parent_id = ?) "
        "ORDER BY id",
        (user_id, category_id, category_id),
    ).fetchall()
    ids = [row["id"] for row in rows]
    if not ids:  # 调用方已校验存在，这里只是兜底防拼出空 IN ()
        return []
    placeholders = ",".join("?" for _ in ids)
    conn.execute(
        "UPDATE categories SET is_disabled = 1, disabled_at = datetime('now','localtime') "
        " WHERE user_id = ? AND id IN (%s)" % placeholders,
        [user_id] + ids,
    )
    return ids


def set_category_disabled(category_id, disabled):
    """停用 / 恢复一个分类，返回 (分类字典, 错误信息)。

    v0.13.1（T05 / D12 / D16）：`is_disabled` 是**唯一**停用判定列，`disabled_at` 只做审计留痕；
    「停用」≠「消失」——分类行永不被删除，历史账单里的引用仍然可回读（D19）。

    三条语义取舍（写死在代码里，改动需同步 docs/design-v0131.md）：
    1. **停用父分类时，其一级子分类一并停用**：父级不可选后，孤立的二级分类在默认列表里
       也渲染不出来（`list_categories_tree` 会跳过父级缺失的孤儿行），连带停用才是自洽状态。
    2. **恢复只恢复用户显式点击的那一个**：子分类需要用户自己逐个恢复，避免一次误点
       把用户此前故意停用的子分类全部复活（宁可少恢复，也不静默改用户意图）。
    3. **恢复子分类前必须先恢复父级**：父级仍停用时恢复子级会让「操作成功但默认树里看不见」，
       这种「成功但结果不对」比直接报错更伤用户，故前置拦成「请先恢复上级分类」。
    4. **幂等**：重复停用 / 重复恢复都返回成功，`disabled_at` 会刷新为「最近一次停用时间」，
       不抛错、不产生重复行。
    """
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            row = _category_row(conn, category_id, uid)
            if row is None:
                return None, "分类不存在"

            if disabled:
                _disable_category_scope(conn, uid, category_id)
            else:
                # 取舍 3：父级仍停用时不允许恢复子级（否则子级在默认树里永远不显示）
                if row["parent_id"] is not None:
                    parent = _category_row(conn, row["parent_id"], uid)
                    if parent is not None and int(parent["is_disabled"] or 0):
                        return None, "请先恢复上级分类"
                # 取舍 2：只恢复这一条，子分类留给用户自己恢复
                conn.execute(
                    "UPDATE categories SET is_disabled = 0, disabled_at = NULL "
                    " WHERE id = ? AND user_id = ?",
                    (category_id, uid),
                )

            updated = _category_row(conn, category_id, uid)
            return _row_to_category(updated), None
    finally:
        conn.close()


def merge_categories(source_id, target_id):
    """把源分类合并进目标分类，返回 (结果字典, 错误信息)。

    v0.13.1（T05 / D12）：合并 = **迁移账目 + 停用源分类**，源分类不物理删除（D19）。
    两步必须同事务，任一步失败整体回滚。

    红线（改分类不改钱）：这里**只动 records 的 category_id / category 两个分类字段**，
    绝不触碰 amount / account / to_account / fee / type / 报销字段，也绝不碰 accounts.balance。
    分类只是标签，迁移标签不得产生任何金额副作用。

    校验顺序（错误文案要能被前端直接展示）：
    1. 源、目标都必须属于当前用户 → 否则「分类不存在」（跨用户不泄露他人分类是否存在）
    2. 源与目标相同 → 「不能合并到自己」
    3. 目标分类必须未停用 → 否则「目标分类已停用」
    4. 源与目标必须同一 type（支出不能并到收入）
    5. 目标不能是源的子分类（合并会把源连同子分类一起停用，那样目标会被自己停用）
    """
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            source = _category_row(conn, source_id, uid)
            if source is None:
                return None, "分类不存在"
            target = _category_row(conn, target_id, uid)
            if target is None:
                return None, "分类不存在"
            if source_id == target_id:
                return None, "不能合并到自己"
            if int(target["is_disabled"] or 0):
                return None, "目标分类已停用，请先恢复后再合并"
            source_type = source["type"] or "expense"
            target_type = target["type"] or "expense"
            if source_type != target_type:
                return None, "支出分类和收入分类不能互相合并"
            if target["parent_id"] is not None and target["parent_id"] == source_id:
                return None, "不能把父分类合并到它自己的子分类"

            # 第一步：迁移账目。category_id 指向目标，category 冗余名字同步（否则列表仍显示旧名）
            cur = conn.execute(
                "UPDATE records SET category_id = ?, category = ? "
                " WHERE user_id = ? AND category_id = ?",
                (target_id, target["name"], uid, source_id),
            )
            moved = cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0

            # 第二步：停用源分类（连同其一级子分类，理由见 _disable_category_scope）
            disabled_ids = _disable_category_scope(conn, uid, source_id)

            return {
                "source_id": source_id,
                "target_id": target_id,
                "moved": moved,
                "migrated_records": moved,
                "disabled_source_ids": disabled_ids,
                "source": _row_to_category(_category_row(conn, source_id, uid)),
                "target": _row_to_category(_category_row(conn, target_id, uid)),
            }, None
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
                "SELECT id, parent_id FROM categories "
                "WHERE user_id = ? AND id IN (%s)" % placeholders,
                [_uid()] + list(ids),
            ).fetchall()
            if len(rows) != len(ids):
                return "有分类不存在，刷新后再试"
            for row in rows:
                if (row["parent_id"] or None) != (parent_id or None):
                    return "只能重排同一父级下的分类"
            for index, category_id in enumerate(ids):
                conn.execute(
                    "UPDATE categories SET sort_order = ? WHERE id = ? AND user_id = ?",
                    (index, category_id, _uid()),
                )
            return None
    finally:
        conn.close()


def get_all_categories():
    """当前用户的一级分类名字列表。给旧模板的下拉框用，保持向后兼容。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT name FROM categories "
            "WHERE user_id = ? AND parent_id IS NULL ORDER BY sort_order, id",
            (_uid(),),
        ).fetchall()
        return [row["name"] for row in rows]
    finally:
        conn.close()


# ---------------- 账户 ----------------

def _clean_account_type(value):
    """把账户类型收敛到白名单，非法 / 空值一律回落 'normal'（应用层校验，列上无 CHECK）。"""
    text = str(value or "").strip().lower()
    return text if text in ACCOUNT_TYPES else DEFAULT_ACCOUNT_TYPE


def list_accounts():
    """当前用户的账户列表（复合主键 user_id + name），余额统一收敛到两位小数。

    v0.13.3：多下发 `type`（normal / investment）。老前端不读这个键也完全不坏，
    符合「新增字段一律可空兼容」纪律（设计 §3.5 保障 2）。

    v0.14.0-TST：多下发 `market_value`（投资账户持仓市值）与 `total`（余额 + 市值）。
    `balance` 的语义**不变**，仍是账户可用资金，行内编辑/投资看板都照旧用它；
    只是「总资产」和资产页账户总额改为读 `total`，否则持仓市值就被漏算。
    口径与 `_row_to_holding()` 完全一致：current_price 为 0 时回落 cost_price。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT a.name, a.balance, a.group_name, a.type,"
            "       COALESCE(mv.market_value, 0) AS market_value"
            "  FROM accounts a"
            "  LEFT JOIN ("
            "      SELECT p.account AS account_name,"
            "             SUM(h.shares * CASE WHEN h.current_price > 0"
            "                                 THEN h.current_price ELSE h.cost_price END) AS market_value"
            "        FROM holdings h"
            "        JOIN invest_platforms p"
            "          ON p.id = h.platform_id AND p.user_id = h.user_id"
            "       WHERE h.user_id = ?"
            "       GROUP BY p.account"
            "  ) mv ON mv.account_name = a.name"
            " WHERE a.user_id = ?"
            " ORDER BY a.sort_order, a.rowid",
            (_uid(), _uid()),
        ).fetchall()
        accounts = []
        for row in rows:
            account = dict(row)
            account["balance"] = round(account["balance"] or 0, 2)
            account["type"] = _clean_account_type(account.get("type"))
            market_value = round(float(account.get("market_value") or 0), 2)
            account["market_value"] = market_value
            # 投资账户对外可见总额 = 可用资金 + 持仓市值；普通账户 market_value 恒 0
            account["total"] = round(account["balance"] + market_value, 2)
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
        index.get(account["group_name"], groups[0])["accounts"].append(account)
    return groups


def create_account(name, group_name=DEFAULT_GROUP, balance=0, account_type=DEFAULT_ACCOUNT_TYPE):
    """新建账户，返回 (账户字典, 错误信息)。同名账户只在当前用户空间内判重。

    v0.13.3：`account_type` 可选（normal / investment），非法值回落 normal。
    建成投资账户时顺带补一个「默认」子平台（幂等），保证数据永远三层整齐。
    """
    account_type = _clean_account_type(account_type)
    conn = get_conn()
    try:
        with conn:
            if group_name not in ACCOUNT_GROUPS:
                return None, "未知的账户大类：%s" % group_name
            exists = conn.execute(
                "SELECT name FROM accounts WHERE name = ? AND user_id = ?", (name, _uid())
            ).fetchone()
            if exists is not None:
                return None, "账户已存在"
            account_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM accounts WHERE user_id = ?",
                (_uid(),),
            ).fetchone()["m"]
            conn.execute(
                "INSERT INTO accounts (user_id, name, balance, group_name, sort_order, type) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    _uid(),
                    name,
                    round(balance, 2),
                    group_name,
                    account_order + 1,
                    account_type,
                ),
            )
            if account_type == INVESTMENT_ACCOUNT_TYPE:
                ensure_default_platform(conn, name, _uid())
            return {
                "name": name,
                "balance": round(balance, 2),
                "group_name": group_name,
                "type": account_type,
            }, None
    finally:
        conn.close()


def update_account(name, balance=None, group_name=None, account_type=None):
    """改账户余额 / 大类 / 功能类型，返回 (账户字典, 错误信息)。

    v0.13.3：`account_type` 可选。切到 investment 时幂等补「默认」子平台；
    切回 normal 时**不删**已有平台与持仓（用户可能只是临时关掉看板，数据必须留着）。
    """
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT name, balance, group_name, type FROM accounts "
                "WHERE name = ? AND user_id = ?",
                (name, _uid()),
            ).fetchone()
            if row is None:
                return None, "账户不存在"
            if group_name is not None and group_name not in ACCOUNT_GROUPS:
                return None, "未知的账户大类：%s" % group_name

            new_balance = round(row["balance"], 2) if balance is None else round(balance, 2)
            new_group = row["group_name"] if group_name is None else group_name
            new_type = (
                _clean_account_type(row["type"])
                if account_type is None
                else _clean_account_type(account_type)
            )
            conn.execute(
                "UPDATE accounts SET balance = ?, group_name = ?, type = ? "
                "WHERE name = ? AND user_id = ?",
                (new_balance, new_group, new_type, name, _uid()),
            )
            if new_type == INVESTMENT_ACCOUNT_TYPE:
                ensure_default_platform(conn, name, _uid())
            return {
                "name": name,
                "balance": new_balance,
                "group_name": new_group,
                "type": new_type,
            }, None
    finally:
        conn.close()


def adjust_account_balance(
    name,
    new_balance,
    generate_record=True,
    note="账户余额修改",
    category_id=None,
    record_date=None,
):
    """把账户余额直接改成 new_balance，并按差额可选补一笔流水（v0.14.0-TST）。

    与 `update_account()` 的区别：这里会算差额并**生成账单**，让「改余额」在流水里
    留下可追溯的一笔，而不是悄悄改数字。

    三个关键实现点：
    1. 余额用 UPDATE 直接覆盖，保证落库值精确等于用户输入（不受浮点累加影响）；
    2. 生成账单时裸插 records，**不调 add_record()**：add_record 会走 `_apply_effects`
       再把差额加一次余额，余额就变成 new_balance + diff；
    3. 差额绝对值 < 0.01 视为没变，只改余额、不生成流水，避免出现 0 元账单。
    """
    new_balance = round(float(new_balance), 2)
    conn = get_conn()
    try:
        with conn:
            uid = _uid()
            row = conn.execute(
                "SELECT name, balance FROM accounts WHERE name = ? AND user_id = ?",
                (name, uid),
            ).fetchone()
            if row is None:
                return None, "账户不存在"

            old_balance = round(float(row["balance"] or 0), 2)
            diff = round(new_balance - old_balance, 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE name = ? AND user_id = ?",
                (new_balance, name, uid),
            )

            record_id = None
            record_type = ""
            category_label = ""
            if generate_record and abs(diff) >= 0.01:
                record_type = "income" if diff > 0 else "expense"
                resolved_id = None
                resolved_name = ""
                # 用户显式选的分类优先；非法 / 越权 / 已删的 id 一律回落到「其他」
                if category_id is not None:
                    cat = conn.execute(
                        "SELECT id, name FROM categories WHERE id = ? AND user_id = ?",
                        (int(category_id), uid),
                    ).fetchone()
                    if cat is not None:
                        resolved_id = int(cat["id"])
                        resolved_name = cat["name"]
                if resolved_id is None:
                    cat = conn.execute(
                        "SELECT id, name FROM categories WHERE name = ? AND user_id = ? "
                        "ORDER BY (parent_id IS NOT NULL), id LIMIT 1",
                        (DEFAULT_CATEGORY, uid),
                    ).fetchone()
                    if cat is not None:
                        resolved_id = int(cat["id"])
                        resolved_name = cat["name"]
                if not resolved_name:
                    resolved_name = DEFAULT_CATEGORY

                cur = conn.execute(
                    "INSERT INTO records "
                    "(user_id, amount, category, category_id, note, date, account, type, "
                    " formula, to_account, fee, is_reimbursable, reimbursed_amount, "
                    " total_reimbursement, image_path, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', '', 0, 0, 0, 0, '', "
                    " datetime('now','localtime'))",
                    (
                        uid,
                        round(abs(diff), 2),
                        resolved_name,
                        resolved_id,
                        (note or "").strip() or "账户余额修改",
                        normalize_date(record_date or datetime.date.today().isoformat()),
                        name,
                        record_type,
                    ),
                )
                record_id = cur.lastrowid
                category_label = resolved_name

            return {
                "account": name,
                "old_balance": old_balance,
                "balance": new_balance,
                "diff": diff,
                "record_id": record_id,
                "record_type": record_type,
                "record_amount": round(abs(diff), 2) if record_id else 0.0,
                "category": category_label,
            }, None
    finally:
        conn.close()


def delete_account(name):
    """删账户，返回 (是否删除, 错误信息)。还有账目引用它就不让删。

    v0.13.3 级联：删账户必须同时删掉它的投资平台 → 持仓 → 定投计划（设计 F5）。
    少了这一步会留下一批「账户没了但平台和持仓还在」的孤儿数据，看板再也查不到。
    """
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT name FROM accounts WHERE name = ? AND user_id = ?", (name, _uid())
            ).fetchone()
            if row is None:
                return False, "账户不存在"

            used = conn.execute(
                "SELECT COUNT(*) AS c FROM records "
                "WHERE user_id = ? "
                "  AND (account = ? OR (type = 'transfer' AND to_account = ?)) "
                "  AND deleted_at IS NULL",
                (_uid(), name, name),
            ).fetchone()["c"]
            if used:
                return False, "还有 %d 条账目和这个账户有关，先处理掉再删" % used

            _cascade_delete_invest(conn, name, _uid())
            conn.execute("DELETE FROM accounts WHERE name = ? AND user_id = ?", (name, _uid()))
            return True, None
    finally:
        conn.close()


def rename_account(old_name, new_name):
    """账户改名（v0.11.6）：当前用户的主键 + 账目/借贷/投资平台引用一起改。"""
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
                "SELECT name, balance, group_name, type FROM accounts "
                "WHERE name = ? AND user_id = ?",
                (old_name, _uid()),
            ).fetchone()
            if row is None:
                return None, "账户不存在"
            if new_name == old_name:
                return {
                    "name": old_name,
                    "balance": round(row["balance"], 2),
                    "group_name": row["group_name"],
                    "type": _clean_account_type(row["type"]),
                }, None
            exists = conn.execute(
                "SELECT name FROM accounts WHERE name = ? AND user_id = ?", (new_name, _uid())
            ).fetchone()
            if exists is not None:
                return None, "账户名「%s」已存在" % new_name

            conn.execute(
                "UPDATE accounts SET name = ? WHERE name = ? AND user_id = ?",
                (new_name, old_name, _uid()),
            )
            conn.execute(
                "UPDATE records SET account = ? WHERE account = ? AND user_id = ?",
                (new_name, old_name, _uid()),
            )
            conn.execute(
                "UPDATE records SET to_account = ? WHERE to_account = ? AND user_id = ?",
                (new_name, old_name, _uid()),
            )
            conn.execute(
                "UPDATE debts SET account = ? WHERE account = ? AND user_id = ?",
                (new_name, old_name, _uid()),
            )
            # v0.13.3 级联：投资平台按**账户名**引用账户（设计 U1），改名不改这里的话，
            # 改个账户名就会让该账户下所有持仓「找不到家」（设计 F6）。
            conn.execute(
                "UPDATE invest_platforms SET account = ? "
                "WHERE account = ? AND user_id = ?",
                (new_name, old_name, _uid()),
            )
            return {
                "name": new_name,
                "balance": round(row["balance"], 2),
                "group_name": row["group_name"],
                "type": _clean_account_type(row["type"]),
            }, None
    finally:
        conn.close()


def merge_account(source, target):
    """把 source 账户合并进 target（v0.11.6），两个账户都必须在当前用户空间。"""
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
                "SELECT name, balance, group_name, type FROM accounts "
                "WHERE name = ? AND user_id = ?",
                (source, _uid()),
            ).fetchone()
            if src is None:
                return None, "账户「%s」不存在" % source
            tgt = conn.execute(
                "SELECT name, balance, group_name, type FROM accounts "
                "WHERE name = ? AND user_id = ?",
                (target, _uid()),
            ).fetchone()
            if tgt is None:
                return None, "账户「%s」不存在" % target

            new_balance = round(float(src["balance"] or 0) + float(tgt["balance"] or 0), 2)
            conn.execute(
                "UPDATE accounts SET balance = ? WHERE name = ? AND user_id = ?",
                (new_balance, target, _uid()),
            )
            conn.execute(
                "UPDATE records SET account = ? WHERE account = ? AND user_id = ?",
                (target, source, _uid()),
            )
            conn.execute(
                "UPDATE records SET to_account = ? WHERE to_account = ? AND user_id = ?",
                (target, source, _uid()),
            )
            conn.execute(
                "UPDATE debts SET account = ? WHERE account = ? AND user_id = ?",
                (target, source, _uid()),
            )
            # v0.13.3 级联：源账户的投资平台迁到目标账户；目标已有同名平台则合并持仓后删源平台
            _cascade_merge_invest(conn, source, target, _uid())
            conn.execute(
                "DELETE FROM accounts WHERE name = ? AND user_id = ?", (source, _uid())
            )
            return {
                "name": target,
                "balance": new_balance,
                "group_name": tgt["group_name"],
                "type": _clean_account_type(tgt["type"]),
            }, None
    finally:
        conn.close()


def set_records_category(record_ids, category_name):
    """批量改分类（v0.11.6）：只动 category / category_id，不重算余额。"""
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
                    "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                    (category["name"], category["id"], record_id, _uid()),
                )
                changed += cursor.rowcount
            return changed, None
    finally:
        conn.close()


def reorder_accounts(names):
    """按拖拽后的顺序重排当前用户的账户。"""
    if not isinstance(names, list) or not names:
        return "names 必须是非空数组"
    if len(names) != len(set(names)):
        return "names 里有重复的账户"

    conn = get_conn()
    try:
        with conn:
            rows = conn.execute(
                "SELECT name FROM accounts WHERE user_id = ? AND name IN (%s)"
                % ",".join("?" for _ in names),
                [_uid()] + names,
            ).fetchall()
            if len(rows) != len(names):
                return "有账户不存在，刷新后再试"
            for index, name in enumerate(names):
                conn.execute(
                    "UPDATE accounts SET sort_order = ? WHERE name = ? AND user_id = ?",
                    (index, name, _uid()),
                )
            return None
    finally:
        conn.close()


def get_all_accounts():
    """账户名字列表。给旧模板的下拉框用，保持向后兼容。"""
    return [account["name"] for account in list_accounts()]


# ---------------- 投资（v0.13.3） ----------------
#
# 资金口径（team-lead 决策 B —— 与 v0.13.3 设计文档 §3.7 第 7 条不同，**以决策 B 为准**）：
#   ① accounts.balance = 该账户的「可用资金」，永不含持仓市值；
#   ② 买入 = 扣 balance + 写（或加仓）holdings，**不写 records**。
#      理由：需求原文是「买入 → 直接写入 holdings」，且只有转入 / 转出走 records。
#      若按 expense + 分类「投资买入」写 records，「买入 1000 元」会让本月支出凭空多 1000，
#      那不是支出。因此勾稽口径改为：
#          账户可用资金 + 持仓成本市值 = 累计转入 - 累计转出
#   ③ 删除持仓 = 撤销式清仓：balance 加回累计成本（≡ 成本价 × 份额）并删 holdings；
#   ④ ②③的「改 balance + 改 holdings」必须在**同一个 with conn: 事务**里完成。
# 全项目只有 buy_holding / liquidate_holding 两处能动这两张表，
# app.py 里禁止出现第二条扣款路径。


def _row_to_platform(row):
    """平台行 → 字典。holding_count / market_value 由调用方按需补。"""
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "account": row["account"],
        "name": row["name"],
        "sort_order": int(row["sort_order"] or 0),
        "created_at": row["created_at"] or "",
    }


def _row_to_holding(row):
    """持仓行 → 字典。**市值 / 盈亏只在服务端算**（设计 §8：禁止前端二次计算）。

    D8：current_price 存 0 表示未接行情，读取时统一回落 cost_price，
    `price` 就是对外可见的单价；未来接行情只改这一处函数，前端零改动。
    D9：day_pl 固定占位（未接行情），未来补了 prev_close 再改成 available=True。
    """
    shares = round(float(row["shares"] or 0), 4)
    cost_price = round(float(row["cost_price"] or 0), 4)
    current_price = round(float(row["current_price"] or 0), 4)
    # 唯一的「价格回落」逻辑：有行情价用行情价，没有就用成本价
    price = current_price if current_price > 0 else cost_price
    cost_total = round(float(row["cost_total"] or 0), 2)
    market_value = round(shares * price, 2)
    profit = round(market_value - cost_total, 2)
    profit_percent = round(profit / cost_total * 100, 2) if cost_total > 0 else 0.0
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "platform_id": int(row["platform_id"]),
        "ticker": row["ticker"] or "",
        "name": row["name"],
        "asset_type": row["asset_type"] or DEFAULT_ASSET_TYPE,
        "shares": shares,
        "cost_price": cost_price,
        "current_price": current_price,
        "price": price,
        "cost_total": cost_total,
        "market_value": market_value,
        "pl": profit,
        "pl_percent": profit_percent,
        "record_id": row["record_id"],
        "created_at": row["created_at"] or "",
        "updated_at": row["updated_at"] or "",
        "day_pl": {"amount": 0.0, "percent": 0.0, "available": False},
    }


def _row_to_dca(row):
    """定投计划行 → 字典。"""
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "holding_id": int(row["holding_id"]),
        "amount": round(float(row["amount"] or 0), 2),
        "frequency": row["frequency"] or DEFAULT_DCA_FREQUENCY,
        "next_date": row["next_date"] or "",
        "status": row["status"] or DEFAULT_DCA_STATUS,
        "created_at": row["created_at"] or "",
    }


def _clean_asset_type(value):
    """资产类型收敛到白名单，非法值回落 fund（AI 乱吐词不该让建仓失败）。"""
    text = str(value or "").strip().lower()
    return text if text in INVEST_ASSET_TYPES else DEFAULT_ASSET_TYPE


def _clean_frequency(value):
    """定投频率收敛到白名单，非法值回落 monthly。"""
    text = str(value or "").strip().lower()
    return text if text in DCA_FREQUENCIES else DEFAULT_DCA_FREQUENCY


def _clean_dca_status(value):
    """定投状态收敛到白名单，非法值回落 active。"""
    text = str(value or "").strip().lower()
    return text if text in DCA_STATUSES else DEFAULT_DCA_STATUS


def _account_row(conn, account_name, user_id):
    """取指定用户的账户行；不存在返回 None。"""
    return conn.execute(
        "SELECT name, balance, group_name, type FROM accounts "
        "WHERE name = ? AND user_id = ?",
        (account_name, user_id),
    ).fetchone()


def _require_invest_account(conn, account_name, user_id):
    """校验「账户存在 且 是投资账户」，返回 (账户行, 错误信息)。

    跨用户 / 不存在走**同一条文案**，由上层统一映射成 404，不泄露资源的存在性。
    """
    name = str(account_name or "").strip()
    if not name:
        return None, "请先指定投资账户"
    row = _account_row(conn, name, user_id)
    if row is None:
        return None, "账户「%s」不存在" % name
    if _clean_account_type(row["type"]) != INVESTMENT_ACCOUNT_TYPE:
        return None, "「%s」不是投资账户，请先在账户管理里切换账户类型" % name
    return row, None


def _platform_row(conn, platform_id, user_id):
    """取平台行；不存在 / 跨用户 / 非整数 id 一律返回 None（统一按「不存在」处理）。"""
    try:
        pid = int(platform_id)
    except (TypeError, ValueError):
        return None
    return conn.execute(
        "SELECT * FROM invest_platforms WHERE id = ? AND user_id = ?", (pid, user_id)
    ).fetchone()


def _holding_row(conn, holding_id, user_id):
    """取持仓行；不存在 / 跨用户 / 非整数 id 一律返回 None。"""
    try:
        hid = int(holding_id)
    except (TypeError, ValueError):
        return None
    return conn.execute(
        "SELECT * FROM holdings WHERE id = ? AND user_id = ?", (hid, user_id)
    ).fetchone()


def _dca_row(conn, plan_id, user_id):
    """取定投计划行；不存在 / 跨用户 / 非整数 id 一律返回 None。"""
    try:
        did = int(plan_id)
    except (TypeError, ValueError):
        return None
    return conn.execute(
        "SELECT * FROM dca_plans WHERE id = ? AND user_id = ?", (did, user_id)
    ).fetchone()


def _holding_by_name(conn, platform_id, name, user_id, exclude_id=None):
    """按「同平台 + 同名」找持仓，用于加仓判定与改名查重。"""
    sql = (
        "SELECT * FROM holdings WHERE user_id = ? AND platform_id = ? AND name = ?"
    )
    params = [user_id, platform_id, name]
    if exclude_id is not None:
        sql += " AND id <> ?"
        params.append(exclude_id)
    return conn.execute(sql, params).fetchone()


def ensure_default_platform(conn, account_name, user_id=None):
    """保证某投资账户下有一个「默认」子平台，返回平台 id。

    幂等：靠 `uq_ip_user_account_name` 唯一索引 + INSERT OR IGNORE，重复调用行数不增长。
    必须在调用方的事务里执行（不自己开关连接）。
    """
    uid = _resolve_user_id(user_id)
    conn.execute(
        "INSERT OR IGNORE INTO invest_platforms (user_id, account, name, sort_order) "
        "VALUES (?, ?, ?, 0)",
        (uid, account_name, INVEST_PLATFORM_DEFAULT),
    )
    row = conn.execute(
        "SELECT id FROM invest_platforms WHERE user_id = ? AND account = ? AND name = ?",
        (uid, account_name, INVEST_PLATFORM_DEFAULT),
    ).fetchone()
    return int(row["id"]) if row is not None else None


def _cascade_delete_invest(conn, account_name, user_id):
    """删账户时级联清理：定投计划 → 持仓 → 平台（设计 F5）。

    不做这一步会留下「账户没了但平台/持仓还在」的孤儿数据，看板永远查不到。
    """
    platforms = conn.execute(
        "SELECT id FROM invest_platforms WHERE user_id = ? AND account = ?",
        (user_id, account_name),
    ).fetchall()
    for platform in platforms:
        holdings = conn.execute(
            "SELECT id FROM holdings WHERE user_id = ? AND platform_id = ?",
            (user_id, platform["id"]),
        ).fetchall()
        for holding in holdings:
            conn.execute(
                "DELETE FROM dca_plans WHERE user_id = ? AND holding_id = ?",
                (user_id, holding["id"]),
            )
        conn.execute(
            "DELETE FROM holdings WHERE user_id = ? AND platform_id = ?",
            (user_id, platform["id"]),
        )
    conn.execute(
        "DELETE FROM invest_platforms WHERE user_id = ? AND account = ?",
        (user_id, account_name),
    )


def _merge_platform_holdings(conn, source_platform_id, target_platform_id, user_id):
    """把源平台的持仓并进目标平台（账户合并时用）。

    同名持仓走**加权合并**：份额相加、成本相加、成本价重算；定投计划改挂到存活的持仓上，
    不静默丢数据。不同名的直接改 platform_id。
    """
    holdings = conn.execute(
        "SELECT * FROM holdings WHERE user_id = ? AND platform_id = ?",
        (user_id, source_platform_id),
    ).fetchall()
    for holding in holdings:
        same = _holding_by_name(conn, target_platform_id, holding["name"], user_id)
        if same is None:
            conn.execute(
                "UPDATE holdings SET platform_id = ? WHERE id = ? AND user_id = ?",
                (target_platform_id, holding["id"], user_id),
            )
            continue
        new_shares = round(float(same["shares"] or 0) + float(holding["shares"] or 0), 4)
        new_cost = round(float(same["cost_total"] or 0) + float(holding["cost_total"] or 0), 2)
        new_price = round(new_cost / new_shares, 4) if new_shares > 0 else 0.0
        conn.execute(
            "UPDATE holdings SET shares = ?, cost_total = ?, cost_price = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
            (new_shares, new_cost, new_price, same["id"], user_id),
        )
        conn.execute(
            "UPDATE dca_plans SET holding_id = ? WHERE user_id = ? AND holding_id = ?",
            (same["id"], user_id, holding["id"]),
        )
        conn.execute(
            "DELETE FROM holdings WHERE id = ? AND user_id = ?", (holding["id"], user_id)
        )


def _cascade_merge_invest(conn, source_account, target_account, user_id):
    """账户合并时级联迁移投资平台（设计 F5）。

    目标账户已有同名平台 → 合并持仓后删源平台；否则直接把平台改挂到目标账户。
    """
    platforms = conn.execute(
        "SELECT id, name FROM invest_platforms WHERE user_id = ? AND account = ?",
        (user_id, source_account),
    ).fetchall()
    for platform in platforms:
        same = conn.execute(
            "SELECT id FROM invest_platforms WHERE user_id = ? AND account = ? AND name = ?",
            (user_id, target_account, platform["name"]),
        ).fetchone()
        if same is None:
            conn.execute(
                "UPDATE invest_platforms SET account = ? WHERE id = ? AND user_id = ?",
                (target_account, platform["id"], user_id),
            )
        else:
            _merge_platform_holdings(conn, platform["id"], same["id"], user_id)
            conn.execute(
                "DELETE FROM invest_platforms WHERE id = ? AND user_id = ?",
                (platform["id"], user_id),
            )


def list_invest_platforms(account_name):
    """某投资账户下的平台列表（带持仓数与市值），返回 (列表, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            account, error = _require_invest_account(conn, account_name, _uid())
            if error is not None:
                return None, error
            rows = conn.execute(
                "SELECT * FROM invest_platforms WHERE user_id = ? AND account = ? "
                "ORDER BY sort_order, id",
                (_uid(), account["name"]),
            ).fetchall()
            platforms = []
            for row in rows:
                platform = _row_to_platform(row)
                holdings = conn.execute(
                    "SELECT * FROM holdings WHERE user_id = ? AND platform_id = ? "
                    "ORDER BY id",
                    (_uid(), platform["id"]),
                ).fetchall()
                platform["holding_count"] = len(holdings)
                platform["market_value"] = round(
                    sum(_row_to_holding(h)["market_value"] for h in holdings), 2
                )
                platforms.append(platform)
            return platforms, None
    finally:
        conn.close()


def get_invest_platform(platform_id):
    """按 id 取平台（带持仓数与市值），返回 (平台字典, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            row = _platform_row(conn, platform_id, _uid())
            if row is None:
                return None, "平台不存在"
            platform = _row_to_platform(row)
            holdings = conn.execute(
                "SELECT * FROM holdings WHERE user_id = ? AND platform_id = ? ORDER BY id",
                (_uid(), platform["id"]),
            ).fetchall()
            platform["holding_count"] = len(holdings)
            platform["market_value"] = round(
                sum(_row_to_holding(h)["market_value"] for h in holdings), 2
            )
            return platform, None
    finally:
        conn.close()


def create_platform(account_name, name):
    """在某投资账户下新建子平台，返回 (平台字典, 错误信息)。

    同名平台在这个账户下直接拒绝（409）；上限 20 字（设计 §3.7 #4）。
    """
    name = str(name or "").strip()
    if not name:
        return None, "平台名称不能为空"
    if len(name) > MAX_PLATFORM_NAME_LENGTH:
        return None, "平台名称不能超过 %d 个字" % MAX_PLATFORM_NAME_LENGTH

    conn = get_conn()
    try:
        with conn:
            account, error = _require_invest_account(conn, account_name, _uid())
            if error is not None:
                return None, error
            exists = conn.execute(
                "SELECT id FROM invest_platforms "
                "WHERE user_id = ? AND account = ? AND name = ?",
                (_uid(), account["name"], name),
            ).fetchone()
            if exists is not None:
                return None, "该账户下已有平台「%s」" % name
            sort_order = conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS m FROM invest_platforms "
                "WHERE user_id = ? AND account = ?",
                (_uid(), account["name"]),
            ).fetchone()["m"]
            cursor = conn.execute(
                "INSERT INTO invest_platforms (user_id, account, name, sort_order) "
                "VALUES (?, ?, ?, ?)",
                (_uid(), account["name"], name, int(sort_order or 0) + 1),
            )
            row = _platform_row(conn, cursor.lastrowid, _uid())
            platform = _row_to_platform(row)
            platform["holding_count"] = 0
            platform["market_value"] = 0.0
            return platform, None
    except sqlite3.IntegrityError as exc:
        return None, "该账户下已有平台「%s」" % name
    finally:
        conn.close()


def rename_platform(platform_id, name):
    """平台改名，返回 (平台字典, 错误信息)。只改名字，不动任何持仓与资金。"""
    name = str(name or "").strip()
    if not name:
        return None, "平台名称不能为空"
    if len(name) > MAX_PLATFORM_NAME_LENGTH:
        return None, "平台名称不能超过 %d 个字" % MAX_PLATFORM_NAME_LENGTH

    conn = get_conn()
    try:
        with conn:
            row = _platform_row(conn, platform_id, _uid())
            if row is None:
                return None, "平台不存在"
            if row["name"] == name:
                return _row_to_platform(row), None
            exists = conn.execute(
                "SELECT id FROM invest_platforms "
                "WHERE user_id = ? AND account = ? AND name = ?",
                (_uid(), row["account"], name),
            ).fetchone()
            if exists is not None:
                return None, "该账户下已有平台「%s」" % name
            conn.execute(
                "UPDATE invest_platforms SET name = ? WHERE id = ? AND user_id = ?",
                (name, row["id"], _uid()),
            )
            return _row_to_platform(_platform_row(conn, row["id"], _uid())), None
    except sqlite3.IntegrityError:
        return None, "该账户下已有平台「%s」" % name
    finally:
        conn.close()


def delete_platform(platform_id):
    """删平台，返回 (是否删除, 错误信息)。

    平台下还有持仓就拒绝删除——先清仓再删平台，避免资金「蒸发」在看不见的地方。
    """
    conn = get_conn()
    try:
        with conn:
            row = _platform_row(conn, platform_id, _uid())
            if row is None:
                return False, "平台不存在"
            count = conn.execute(
                "SELECT COUNT(*) AS c FROM holdings WHERE user_id = ? AND platform_id = ?",
                (_uid(), row["id"]),
            ).fetchone()["c"]
            if count:
                return False, "该平台下还有 %d 个持仓，请先清仓再删除平台" % count
            conn.execute(
                "DELETE FROM invest_platforms WHERE id = ? AND user_id = ?",
                (row["id"], _uid()),
            )
            return True, None
    finally:
        conn.close()


def get_holding(holding_id):
    """按 id 取持仓（带平台名与账户名），返回 (持仓字典, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            row = _holding_row(conn, holding_id, _uid())
            if row is None:
                return None, "持仓不存在"
            holding = _row_to_holding(row)
            platform = _platform_row(conn, row["platform_id"], _uid())
            holding["platform_name"] = platform["name"] if platform else ""
            holding["account"] = platform["account"] if platform else ""
            return holding, None
    finally:
        conn.close()


def buy_holding(
    account_name,
    platform_id=None,
    name="",
    ticker="",
    asset_type=DEFAULT_ASSET_TYPE,
    shares=0,
    price=0,
    amount=0,
    dca=None,
    record_id=None,
    source_account="",
):
    """**全局唯一的投资入账口**：扣可用资金 + 写（或加仓）持仓，返回 (payload, 错误信息)。

    payload = {"holding", "platform", "balance", "added", "dca", "record", "transfer"}
    - `added=True` 表示命中同平台同名持仓走了**加权加仓**（设计 D6），False 表示新建；
    - `record` 恒为 None：决策 B 下不写 records，保留键位只为契约稳定。

    **必须在同一个 with conn: 事务里**完成「扣 balance + 写 holdings」：
    任何一步失败都整体回滚，绝不出现「钱扣了但持仓没建」。

    v0.13.3 新增 `source_account`（扣款来源账户，如「微信」「现金」）：
    - 空串 / 与投资账户同名 → 老行为：直接从投资账户的可用资金里扣；
    - 其它账户 → 先在同一事务里从来源账户**转出** amount，并**转入**投资账户的可用资金，
      随后照旧从投资账户扣款。净效果：来源账户 −amount、投资账户可用资金不变、
      持仓 +amount。两笔 UPDATE 与写持仓同事务，任何一步失败全部回滚，
      不会出现「微信的钱扣了、持仓没建」。
    """
    name = str(name or "").strip()
    ticker = str(ticker or "").strip()
    source_account = str(source_account or "").strip()
    if not name:
        return None, "请填写标的名称"
    if len(name) > MAX_HOLDING_NAME_LENGTH:
        return None, "标的名称不能超过 %d 个字" % MAX_HOLDING_NAME_LENGTH

    # ---- 金额 / 份额 / 单价 三者推导（设计 D7 的 4 种组合）----
    try:
        shares = float(shares or 0)
        price = float(price or 0)
        amount = float(amount or 0)
    except (TypeError, ValueError):
        return None, "份额 / 单价 / 金额必须是数字"
    if shares < 0 or price < 0 or amount < 0:
        return None, "份额 / 单价 / 金额不能是负数"

    if shares > 0 and price > 0:
        # 组合 1：份额 + 单价都有 → 金额由二者算出，自洽
        amount = round(shares * price, 2)
    elif shares > 0 and amount > 0:
        # 组合 2：份额 + 金额 → 反推单价
        price = round(amount / shares, 4)
    elif shares > 0:
        # 组合 3：只有份额 → 单价回落 1.0，金额 = 份额（「投入金额 ≡ 市值」自洽）
        price = 1.0
        amount = round(shares * price, 2)
    elif amount > 0 and price > 0:
        # 组合 4：金额 + 单价 → 反推份额
        shares = round(amount / price, 4)
    elif amount > 0:
        # 组合 5：只有金额 → 单价 1.0，份额 = 金额
        price = 1.0
        shares = round(amount / price, 4)
    else:
        return None, "请填写份额或投入金额"

    if amount <= 0 or shares <= 0:
        return None, "份额与金额都必须大于 0"
    amount = round(amount, 2)
    asset_type = _clean_asset_type(asset_type)

    conn = get_conn()
    try:
        with conn:
            account, error = _require_invest_account(conn, account_name, _uid())
            if error is not None:
                return None, error

            # 平台：不传就用该账户的「默认」子平台（不存在则幂等补一个）
            if platform_id is None or str(platform_id).strip() == "":
                platform_row = None
            else:
                platform_row = _platform_row(conn, platform_id, _uid())
                if platform_row is None:
                    return None, "平台不存在"
                if platform_row["account"] != account["name"]:
                    return None, "该平台不属于账户「%s」" % account["name"]
            if platform_row is None:
                platform_id = ensure_default_platform(conn, account["name"], _uid())
                platform_row = _platform_row(conn, platform_id, _uid())

            balance = round(float(account["balance"] or 0), 2)

            # ---- 第零写（v0.13.3）：先把钱从「扣款来源账户」转进投资账户的可用资金 ----
            # 与买入同事务：转出→转入→扣款→写持仓，四步要么全成要么全回滚。
            transfer = None
            if source_account and source_account != account["name"]:
                source_row = conn.execute(
                    "SELECT name, balance, type FROM accounts WHERE name = ? AND user_id = ?",
                    (source_account, _uid()),
                ).fetchone()
                if source_row is None:
                    return None, "扣款来源账户「%s」不存在" % source_account
                if _clean_account_type(source_row["type"]) == INVESTMENT_ACCOUNT_TYPE:
                    return None, "扣款来源不能是同业投资账户「%s」" % source_account
                source_balance = round(float(source_row["balance"] or 0), 2)
                if source_balance + 1e-6 < amount:
                    return None, (
                        "「%s」余额不足：当前 %.2f 元，本次需要 %.2f 元"
                        % (source_account, source_balance, amount)
                    )
                conn.execute(
                    "UPDATE accounts SET balance = ROUND(balance - ?, 2) "
                    "WHERE name = ? AND user_id = ?",
                    (amount, source_account, _uid()),
                )
                conn.execute(
                    "UPDATE accounts SET balance = ROUND(balance + ?, 2) "
                    "WHERE name = ? AND user_id = ?",
                    (amount, account["name"], _uid()),
                )
                balance = round(balance + amount, 2)
                transfer = {
                    "from": source_account,
                    "from_balance": round(source_balance - amount, 2),
                    "to": account["name"],
                    "amount": amount,
                }

            # 余额不足直接拒绝（设计 U8）：引导用户先转账，不做隐式透支
            if balance + 1e-6 < amount:
                return None, (
                    "「%s」可用资金不足：当前 %.2f 元，本次需要 %.2f 元，"
                    "请先从其他账户转入" % (account["name"], balance, amount)
                )

            # ---- 第一写：扣可用资金（唯一合法扣款点）----
            conn.execute(
                "UPDATE accounts SET balance = ROUND(balance - ?, 2) "
                "WHERE name = ? AND user_id = ?",
                (amount, account["name"], _uid()),
            )

            # ---- 第二写：新建或加权加仓 ----
            same = _holding_by_name(conn, platform_row["id"], name, _uid())
            if same is not None:
                new_shares = round(float(same["shares"] or 0) + shares, 4)
                new_cost_total = round(float(same["cost_total"] or 0) + amount, 2)
                new_cost_price = (
                    round(new_cost_total / new_shares, 4) if new_shares > 0 else price
                )
                conn.execute(
                    "UPDATE holdings SET shares = ?, cost_price = ?, cost_total = ?, "
                    "ticker = ?, asset_type = ?, updated_at = CURRENT_TIMESTAMP "
                    "WHERE id = ? AND user_id = ?",
                    (
                        new_shares,
                        new_cost_price,
                        new_cost_total,
                        ticker or same["ticker"],
                        asset_type,
                        same["id"],
                        _uid(),
                    ),
                )
                holding_id = int(same["id"])
                added = True
            else:
                cursor = conn.execute(
                    "INSERT INTO holdings (user_id, platform_id, ticker, name, asset_type, "
                    "shares, cost_price, current_price, cost_total, record_id) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (
                        _uid(),
                        platform_row["id"],
                        ticker,
                        name,
                        asset_type,
                        shares,
                        price,
                        amount,
                        record_id,
                    ),
                )
                holding_id = int(cursor.lastrowid)
                added = False

            # 可选：建仓时顺手挂一条定投计划
            dca_row = None
            if isinstance(dca, dict) and dca.get("amount"):
                # 同一事务内插计划（不另开 with conn:，见 _insert_dca_plan 注释）
                dca_row = _insert_dca_plan(
                    conn,
                    holding_id,
                    dca.get("amount", 0),
                    _clean_frequency(dca.get("frequency")),
                    str(dca.get("next_date") or "").strip(),
                    DEFAULT_DCA_STATUS,
                    source_account,
                )

            holding = _row_to_holding(_holding_row(conn, holding_id, _uid()))
            holding["platform_name"] = platform_row["name"]
            holding["account"] = platform_row["account"]
            new_balance = conn.execute(
                "SELECT ROUND(balance, 2) AS b FROM accounts WHERE name = ? AND user_id = ?",
                (account["name"], _uid()),
            ).fetchone()["b"]
            return {
                "holding": holding,
                "platform": _row_to_platform(platform_row),
                "balance": round(float(new_balance or 0), 2),
                "added": added,
                "dca": dca_row,
                "record": None,
                "transfer": transfer,
            }, None
    finally:
        conn.close()


def update_holding_meta(holding_id, name=None, ticker=None, asset_type=None, platform_id=None):
    """只改持仓**元信息**（名称 / 代码 / 资产类型 / 平台），返回 (持仓字典, 错误信息)。

    决策 D：**份额 / 成本一律不许改**——金额填错了走「删除（清仓退款）后重建」，
    否则 shares / cost_price / cost_total 三者会漂移，勾稽再也对齐不上。
    跨账户搬平台也被拒绝（会把资金从一个账户的勾稽口径里挪走）。
    """
    if name is not None:
        name = str(name or "").strip()
        if not name:
            return None, "标的名称不能为空"
        if len(name) > MAX_HOLDING_NAME_LENGTH:
            return None, "标的名称不能超过 %d 个字" % MAX_HOLDING_NAME_LENGTH

    conn = get_conn()
    try:
        with conn:
            row = _holding_row(conn, holding_id, _uid())
            if row is None:
                return None, "持仓不存在"

            target_platform_id = int(row["platform_id"])
            if platform_id is not None:
                platform = _platform_row(conn, platform_id, _uid())
                if platform is None:
                    return None, "平台不存在"
                if platform["account"] != _account_of_platform(conn, row["platform_id"], _uid()):
                    return None, "不能把持仓移动到其他账户的平台下"
                target_platform_id = int(platform["id"])

            new_name = row["name"] if name is None else name
            if new_name != row["name"] or target_platform_id != int(row["platform_id"]):
                same = _holding_by_name(
                    conn, target_platform_id, new_name, _uid(), exclude_id=row["id"]
                )
                if same is not None:
                    return None, "该平台下已有同名持仓「%s」" % new_name

            new_ticker = row["ticker"] if ticker is None else str(ticker or "").strip()
            new_asset_type = (
                row["asset_type"] if asset_type is None else _clean_asset_type(asset_type)
            )
            conn.execute(
                "UPDATE holdings SET name = ?, ticker = ?, asset_type = ?, platform_id = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND user_id = ?",
                (new_name, new_ticker, new_asset_type, target_platform_id, row["id"], _uid()),
            )
            holding = _row_to_holding(_holding_row(conn, row["id"], _uid()))
            platform = _platform_row(conn, target_platform_id, _uid())
            holding["platform_name"] = platform["name"] if platform else ""
            holding["account"] = platform["account"] if platform else ""
            return holding, None
    except sqlite3.IntegrityError:
        return None, "该平台下已有同名持仓"
    finally:
        conn.close()


def _account_of_platform(conn, platform_id, user_id):
    """取平台所属账户名；平台不在当前用户空间时返回空串。"""
    row = _platform_row(conn, platform_id, user_id)
    return row["account"] if row is not None else ""


def liquidate_holding(holding_id):
    """撤销式清仓：可用资金加回累计成本 + 删持仓，返回 (payload, 错误信息)。

    退款额取 `cost_total`（≡ 成本价 × 份额，取累计成本可避免浮点漂移），
    保证「买入 → 删除 → 再买，余额回到初值」精确成立。
    挂在该持仓下的定投计划一并暂停（不删，保留用户设定）。
    """
    conn = get_conn()
    try:
        with conn:
            row = _holding_row(conn, holding_id, _uid())
            if row is None:
                return None, "持仓不存在"
            platform = _platform_row(conn, row["platform_id"], _uid())
            if platform is None:
                return None, "持仓所属平台不存在"

            refund = round(float(row["cost_total"] or 0), 2)
            # ---- 第一写：退款回可用资金（唯一合法退款点）----
            conn.execute(
                "UPDATE accounts SET balance = ROUND(balance + ?, 2) "
                "WHERE name = ? AND user_id = ?",
                (refund, platform["account"], _uid()),
            )
            conn.execute(
                "UPDATE dca_plans SET status = ? WHERE user_id = ? AND holding_id = ?",
                ("paused", _uid(), row["id"]),
            )
            # ---- 第二写：删持仓 ----
            conn.execute(
                "DELETE FROM holdings WHERE id = ? AND user_id = ?", (row["id"], _uid())
            )
            new_balance = conn.execute(
                "SELECT ROUND(balance, 2) AS b FROM accounts WHERE name = ? AND user_id = ?",
                (platform["account"], _uid()),
            ).fetchone()["b"]
            return {
                "deleted": int(row["id"]),
                "name": row["name"],
                "account": platform["account"],
                "refunded": refund,
                "balance": round(float(new_balance or 0), 2),
            }, None
    finally:
        conn.close()


def list_invest_board(account_name):
    """投资看板聚合数据（设计 §3.3）：返回 (board, 错误信息)。

    board = {
        account: {name, type, balance, cash_label},
        total_market_value, total_cost, day_pl,
        platforms: [{..., market_value, holdings: [...] }]
    }
    市值 / 盈亏一律在这里算好下发，前端不做二次计算（设计 §8）。
    """
    conn = get_conn()
    try:
        with conn:
            account, error = _require_invest_account(conn, account_name, _uid())
            if error is not None:
                return None, error
            platforms = []
            total_market_value = 0.0
            total_cost = 0.0
            rows = conn.execute(
                "SELECT * FROM invest_platforms WHERE user_id = ? AND account = ? "
                "ORDER BY sort_order, id",
                (_uid(), account["name"]),
            ).fetchall()
            for row in rows:
                platform = _row_to_platform(row)
                holding_rows = conn.execute(
                    "SELECT * FROM holdings WHERE user_id = ? AND platform_id = ? ORDER BY id",
                    (_uid(), platform["id"]),
                ).fetchall()
                holdings = [_row_to_holding(h) for h in holding_rows]
                # 定投计划挂在持仓上，看板一次带出去：否则「定了投但界面上查不到」
                plan_rows = conn.execute(
                    "SELECT d.* FROM dca_plans d JOIN holdings h ON h.id = d.holding_id "
                    "WHERE d.user_id = ? AND h.platform_id = ? ORDER BY d.next_date, d.id",
                    (_uid(), platform["id"]),
                ).fetchall()
                plans_by_holding = {}
                for plan_row in plan_rows:
                    plans_by_holding.setdefault(int(plan_row["holding_id"]), []).append(
                        _row_to_dca(plan_row)
                    )
                for holding in holdings:
                    holding["dca_plans"] = plans_by_holding.get(holding["id"], [])
                market_value = round(sum(h["market_value"] for h in holdings), 2)
                platform["holding_count"] = len(holdings)
                platform["market_value"] = market_value
                platform["holdings"] = holdings
                platforms.append(platform)
                total_market_value += market_value
                total_cost += round(sum(h["cost_total"] for h in holdings), 2)

            return {
                "account": {
                    "name": account["name"],
                    "type": _clean_account_type(account["type"]),
                    "balance": round(float(account["balance"] or 0), 2),
                    "cash_label": "可用资金",
                },
                "total_market_value": round(total_market_value, 2),
                "total_cost": round(total_cost, 2),
                "day_pl": {"amount": 0.0, "percent": 0.0, "available": False},
                "platforms": platforms,
            }, None
    finally:
        conn.close()


def _insert_dca_plan(
    conn, holding_id, amount, frequency, next_date, status, source_account=""
):
    """在**调用方已有事务**里插一条定投计划，返回计划字典。

    刻意不开自己的 `with conn:`：buy_holding 建仓挂计划时必须与「扣款 + 写持仓」
    同属一个事务，嵌套 with 会让内层提前 COMMIT，破坏原子性。
    """
    row = _holding_row(conn, holding_id, _uid())
    if row is None:
        return None
    cursor = conn.execute(
        "INSERT INTO dca_plans (user_id, holding_id, amount, frequency, "
        "next_date, status, source_account) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            _uid(),
            row["id"],
            round(amount, 2),
            frequency,
            next_date,
            status,
            str(source_account or "").strip(),
        ),
    )
    return _row_to_dca(_dca_row(conn, cursor.lastrowid, _uid()))


def create_dca_plan(
    holding_id, amount, frequency=None, next_date="", status=None, source_account=""
):
    """给持仓挂一条定投计划，返回 (计划字典, 错误信息)。

    本期只落库 + 展示（设计 §1.2 第 3 条），**绝不自动生成任何账目**。
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return None, "定投金额必须是数字"
    if amount <= 0:
        return None, "定投金额必须大于 0"
    frequency = _clean_frequency(frequency)
    next_date = str(next_date or "").strip()
    status = _clean_dca_status(status) if status is not None else DEFAULT_DCA_STATUS

    conn = get_conn()
    try:
        with conn:
            row = _holding_row(conn, holding_id, _uid())
            if row is None:
                return None, "持仓不存在"
            plan = _insert_dca_plan(
                conn, row["id"], amount, frequency, next_date, status, source_account
            )
            return plan, None
    finally:
        conn.close()


def update_dca_plan(plan_id, amount=None, frequency=None, next_date=None, status=None):
    """改定投计划，返回 (计划字典, 错误信息)。本期只改计划本身，不产生任何账目。"""
    conn = get_conn()
    try:
        with conn:
            row = _dca_row(conn, plan_id, _uid())
            if row is None:
                return None, "定投计划不存在"
            new_amount = round(float(row["amount"] or 0), 2)
            if amount is not None:
                try:
                    new_amount = round(float(amount), 2)
                except (TypeError, ValueError):
                    return None, "定投金额必须是数字"
                if new_amount <= 0:
                    return None, "定投金额必须大于 0"
            new_frequency = row["frequency"] if frequency is None else _clean_frequency(frequency)
            new_next_date = row["next_date"] if next_date is None else str(next_date or "").strip()
            new_status = row["status"] if status is None else _clean_dca_status(status)
            conn.execute(
                "UPDATE dca_plans SET amount = ?, frequency = ?, next_date = ?, status = ? "
                "WHERE id = ? AND user_id = ?",
                (new_amount, new_frequency, new_next_date, new_status, row["id"], _uid()),
            )
            return _row_to_dca(_dca_row(conn, row["id"], _uid())), None
    finally:
        conn.close()


def delete_dca_plan(plan_id):
    """删定投计划，返回 (是否删除, 错误信息)。只删计划，不动持仓与资金。"""
    conn = get_conn()
    try:
        with conn:
            row = _dca_row(conn, plan_id, _uid())
            if row is None:
                return False, "定投计划不存在"
            conn.execute(
                "DELETE FROM dca_plans WHERE id = ? AND user_id = ?", (row["id"], _uid())
            )
            return True, None
    finally:
        conn.close()


def list_dca_plans(holding_id=None):
    """当前用户的定投计划列表（可按持仓过滤），按 next_date 升序。"""
    conn = get_conn()
    try:
        with conn:
            if holding_id is None:
                rows = conn.execute(
                    "SELECT * FROM dca_plans WHERE user_id = ? "
                    "ORDER BY next_date, id",
                    (_uid(),),
                ).fetchall()
            else:
                try:
                    hid = int(holding_id)
                except (TypeError, ValueError):
                    return []
                rows = conn.execute(
                    "SELECT * FROM dca_plans WHERE user_id = ? AND holding_id = ? "
                    "ORDER BY next_date, id",
                    (_uid(), hid),
                ).fetchall()
            return [_row_to_dca(row) for row in rows]
    finally:
        conn.close()


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
                       (user_id, amount, category, category_id, note, date, account, type,
                        formula, to_account, fee, is_reimbursable,
                        reimbursement_contact_id, reimbursed_amount, total_reimbursement,
                        image_path, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'))
                """,
                (
                    _uid(),
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
                "SELECT account, amount, type, to_account, fee FROM records "
                "WHERE id = ? AND user_id = ?",
                (record_id, _uid()),
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
                 WHERE id = ? AND user_id = ?
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
                    _uid(),
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
                "SELECT account, amount, type, to_account, fee FROM records "
                "WHERE id = ? AND user_id = ?",
                (record_id, _uid()),
            ).fetchone()
            if old is None:
                return False

            conn.execute(
                "DELETE FROM records WHERE id = ? AND user_id = ?", (record_id, _uid())
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


_RECORD_SELECT = (
    "SELECT r.id, r.amount, r.category, r.category_id, r.note, r.date, "
    "       r.account, r.type, r.formula, r.to_account, r.fee, "
    "       r.is_reimbursable, r.reimbursement_contact_id, r.reimbursed_amount, "
    "       r.total_reimbursement, r.deleted_at, r.image_path, "
    "       p.name AS category_parent, c.parent_id AS category_parent_id, "
    "       ct.name AS reimbursement_contact_name "
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
    conditions = ["r.deleted_at IS NULL", "r.user_id = ?"]
    params = [_uid()]
    if account:
        # 转账会同时牵动转出和转入两个账户，查任何一个账户都该看到这笔转账
        conditions.append("(r.account = ? OR (r.type = 'transfer' AND r.to_account = ?))")
        params.extend([account, account])
    if category_id is not None:
        conditions.append("r.category_id = ?")
        params.append(category_id)
    if parent_id is not None:
        # 一级分类筛选：命中它自己，也命中挂在它下面的所有二级分类。
        # v0.13.1：限定本用户，跨用户的同名 id 不会串进来
        conditions.append(
            "r.category_id IN (SELECT id FROM categories "
            "WHERE user_id = ? AND (id = ? OR parent_id = ?))"
        )
        params.extend([_uid(), parent_id, parent_id])
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
        + " WHERE r.deleted_at IS NULL AND r.user_id = ? AND ("
        + "r.note LIKE ? ESCAPE '\\' OR r.category LIKE ? ESCAPE '\\'"
        + " OR r.account LIKE ? ESCAPE '\\' OR r.to_account LIKE ? ESCAPE '\\'"
        + " OR CAST(r.amount AS TEXT) LIKE ? ESCAPE '\\'"
        + ") ORDER BY r.id DESC LIMIT ?"
    )
    conn = get_conn()
    try:
        rows = conn.execute(sql, (_uid(), like, like, like, like, like, limit)).fetchall()
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
        + "   AND r.user_id = ?"
        + "   AND r.image_path IS NOT NULL AND r.image_path <> ''"
        + " ORDER BY r.id DESC"
    )
    conn = get_conn()
    try:
        rows = conn.execute(sql, (_uid(),)).fetchall()
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
                "UPDATE records SET image_path = ? WHERE id = ? AND user_id = ?",
                (image_path or "", record_id, _uid()),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def get_record(record_id):
    """按 id 取一条账目（带报销字段与报销人姓名），不存在返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            _RECORD_SELECT + " WHERE r.id = ? AND r.user_id = ?", (record_id, _uid())
        ).fetchone()
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
                "SELECT type, amount FROM records "
                "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (record_id, _uid()),
            ).fetchone()
            if row is None:
                return False, None

            if not is_reimbursable:
                conn.execute(
                    """
                    UPDATE records
                       SET is_reimbursable = 0, reimbursement_contact_id = NULL,
                           reimbursed_amount = 0, total_reimbursement = 0
                     WHERE id = ? AND user_id = ?
                    """,
                    (record_id, _uid()),
                )
                return True, None

            if row["type"] != "expense":
                return False, "只有支出账目可以报销"

            if contact_id is None:
                return False, "开启报销前请选择报销人"
            exists = conn.execute(
                "SELECT 1 FROM contacts WHERE id = ? AND user_id = ?",
                (contact_id, _uid()),
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
                 WHERE id = ? AND user_id = ?
                """,
                (contact_id, paid, total, record_id, _uid()),
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
            + " WHERE r.deleted_at IS NOT NULL AND r.user_id = ? "
            "ORDER BY r.deleted_at DESC, r.id DESC",
            (_uid(),),
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
                "WHERE id = ? AND user_id = ? AND deleted_at IS NULL",
                (record_id, _uid()),
            ).fetchone()
            if old is None:
                return False
            conn.execute(
                "UPDATE records SET deleted_at = ? WHERE id = ? AND user_id = ?",
                (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), record_id, _uid()),
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
                "WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL",
                (record_id, _uid()),
            ).fetchone()
            if old is None:
                return False
            conn.execute(
                "UPDATE records SET deleted_at = NULL WHERE id = ? AND user_id = ?",
                (record_id, _uid()),
            )
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
                "DELETE FROM records WHERE id = ? AND user_id = ? AND deleted_at IS NOT NULL",
                (record_id, _uid()),
            )
            return cur.rowcount > 0
    finally:
        conn.close()


def get_statistics():
    """总览：总收入、总支出、总余额、待报销 / 已报销。

    - 总收入 / 总支出：按 type 分别求和，COALESCE 保证没有记录时是 0 而不是 NULL
    - 总余额：直接 SUM(accounts.balance)，账户表才是余额的唯一真相
    - 待报销 / 已报销：**必须带 user_id 过滤**（v0.13.7 越权修复）。原来这里只按
      type / is_reimbursable / deleted_at 过滤，等于把全库所有用户的报销金额加在一起，
      新账号会看到老用户的钱、点开明细又是空的（口径对不上）。
    """
    conn = get_conn()
    try:
        income_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records "
            "WHERE user_id = ? AND type = 'income' AND deleted_at IS NULL",
            (_uid(),),
        ).fetchone()["total"]
        expense_total = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM records "
            "WHERE user_id = ? AND type = 'expense' AND deleted_at IS NULL",
            (_uid(),),
        ).fetchone()["total"]
        balance_total = conn.execute(
            "SELECT COALESCE(SUM(balance), 0) AS total FROM accounts WHERE user_id = ?",
            (_uid(),),
        ).fetchone()["total"]
        reimb = conn.execute(
            "SELECT "
            "  COALESCE(SUM(MAX(total_reimbursement - reimbursed_amount, 0)), 0) AS pending, "
            "  COALESCE(SUM(reimbursed_amount), 0) AS done "
            "FROM records "
            "WHERE user_id = ? AND type = 'expense' AND is_reimbursable = 1 "
            "  AND deleted_at IS NULL",
            (_uid(),),
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
            "       AND d.user_id = c.user_id "
            " WHERE c.user_id = ? "
            " GROUP BY c.id "
            " ORDER BY c.id",
            (_uid(),),
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
            "SELECT id, name, identity, phone, wechat FROM contacts WHERE id = ? AND user_id = ?",
            (contact_id, _uid()),
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
                "INSERT INTO contacts (user_id, name, identity, phone, wechat) VALUES (?, ?, ?, ?, ?)",
                (
                    _uid(),
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
                "SELECT 1 FROM contacts WHERE id = ? AND user_id = ?",
                (contact_id, _uid()),
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
                "SELECT 1 FROM contacts WHERE id = ? AND user_id = ?",
                (contact_id, _uid()),
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
    keys = row.keys()
    repaid = round(row["repaid"] or 0, 2) if "repaid" in keys else 0.0
    amount = round(row["amount"], 2)
    return {
        "id": row["id"],
        "contact_id": row["contact_id"],
        "contact_name": row["contact_name"],
        "account": row["account"],
        "amount": amount,
        "repaid": repaid,
        "remaining": round(max(amount - repaid, 0), 2),
        "type": row["type"],
        "date": normalize_date(row["date"]),
        "status": row["status"],
        "due_date": normalize_date(row["due_date"]) if row["due_date"] else "",
        "interest": round(row["interest"] or 0, 2),
        "image_path": row["image_path"] if "image_path" in keys else "",
        "image_url": row["image_path"] if "image_path" in keys else "",
    }


DEBT_SELECT = (
    "SELECT d.id, d.contact_id, c.name AS contact_name, d.account, d.amount, "
    "       d.type, d.date, d.status, d.due_date, d.interest, d.image_path, d.repaid "
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
        conditions.append("d.user_id = ?")
        params.append(_uid())
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY d.date DESC, d.id DESC"
        return [_row_to_debt(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def get_debt(debt_id):
    conn = get_conn()
    try:
        row = conn.execute(
        DEBT_SELECT + " WHERE d.id = ? AND d.user_id = ?", (debt_id, _uid())
    ).fetchone()
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
    due_date="",
    interest=0,
    image_path="",
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
                "SELECT 1 FROM contacts WHERE id = ? AND user_id = ?",
                (contact_id, _uid()),
            ).fetchone()
            if exists is None:
                return None, "联系人不存在"
            problem = _debt_balance_problem(conn, account)
            if problem is not None:
                return None, problem
            debt_id = 0
            cur = conn.execute(
                "INSERT INTO debts (user_id, contact_id, account, amount, type, date, "
                "                   status, due_date, interest, image_path) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    _uid(),
                    contact_id,
                    account,
                    round(float(amount), 2),
                    debt_type,
                    normalize_date(date),
                    status,
                    normalize_date(due_date) if due_date else "",
                    round(float(interest or 0), 2),
                    image_path or "",
                ),
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
    due_date=None,
    interest=None,
    image_path=None,
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
    if due_date is not None:
        fields["due_date"] = normalize_date(due_date) if str(due_date).strip() else ""
    if interest is not None:
        try:
            value = round(float(interest), 2)
        except (TypeError, ValueError):
            return None, "interest 必须是数字"
        if value < 0:
            return None, "利息不能是负数"
        fields["interest"] = value
    if image_path is not None:
        fields["image_path"] = str(image_path)
    if not fields:
        return None, "没有要修改的字段"

    conn = get_conn()
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM debts WHERE id = ? AND user_id = ?", (debt_id, _uid())
            ).fetchone()
            if exists is None:
                return None, "借贷记录不存在"
            if "contact_id" in fields:
                contact = conn.execute(
                    "SELECT 1 FROM contacts WHERE id = ?", (fields["contact_id"],)
                ).fetchone()
                if contact is None:
                    return None, "联系人不存在"
            old = conn.execute(
                "SELECT account, amount, type FROM debts WHERE id = ? AND user_id = ?",
                (debt_id, _uid()),
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
            # v0.13.8：金额调小到低于已还金额时，已还金额跟着收敛，避免出现负数待还
            if "amount" in fields:
                current_repaid = conn.execute(
                    "SELECT repaid FROM debts WHERE id = ? AND user_id = ?",
                    (debt_id, _uid()),
                ).fetchone()["repaid"] or 0
                fields["repaid"] = round(min(float(current_repaid), fields["amount"]), 2)
            assignments = ", ".join("%s = ?" % key for key in fields)
            conn.execute(
                "UPDATE debts SET " + assignments + " WHERE id = ? AND user_id = ?",
                list(fields.values()) + [debt_id, _uid()],
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
                "SELECT account, amount, type FROM debts WHERE id = ? AND user_id = ?",
                (debt_id, _uid()),
            ).fetchone()
            if exists is None:
                return False, "借贷记录不存在"
            conn.execute("DELETE FROM debts WHERE id = ? AND user_id = ?", (debt_id, _uid()))
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



def settle_debt(debt_id, settle_date=None):
    """结清一条借贷：标记 paid；有利息时自动生成一笔利息收支账单。

    借出（lend）收到利息 = 收入；借入（borrow）付出利息 = 支出。
    返回 (借贷字典, 利息账单或 None, 错误信息)。
    """
    debt = get_debt(debt_id)
    if debt is None:
        return None, None, "借贷记录不存在"
    if debt["status"] == "paid":
        return debt, None, None
    settled, settle_error = update_debt(debt_id, status="paid")
    if settle_error is not None or settled is None:
        return None, None, settle_error or "结清失败"
    interest = round(float(debt.get("interest") or 0), 2)
    record = None
    if interest > 0:
        category = "利息收入" if debt["type"] == "lend" else "利息支出"
        note = "借贷利息：%s" % (debt.get("contact_name") or "")
        record_id, error = add_record(
            interest,
            category,
            note,
            normalize_date(settle_date) if settle_date else datetime.datetime.now().strftime("%Y-%m-%d"),
            debt.get("account") or DEFAULT_ACCOUNT,
            "income" if debt["type"] == "lend" else "expense",
        )
        if error is None:
            record = get_record(record_id)
    return get_debt(debt_id), record, None


def repay_debt(debt_id, amount, account=None, repay_date=None):
    """v0.13.8 还款/收款闭环：一次事务里改余额 + 生成流水 + 累加已还 + 结清。

    - 借入（borrow）还款：资金账户 **减少**，生成一条 expense 流水，分类「借入还款」
    - 借出（lend）收回：资金账户 **增加**，生成一条 income 流水，分类「借出收款」
    部分还款时 debt.status 仍为 unpaid，累加到 repaid；还满自动置 paid。
    返回 (借贷字典, 流水字典或 None, 错误信息)。
    """
    problem = _check_debt_amount(amount)
    if problem is not None:
        return None, None, problem
    amount = round(float(amount), 2)
    conn = get_conn()
    record_id = None
    try:
        with conn:
            row = conn.execute(
                "SELECT d.id, c.name AS contact_name, d.account, d.amount, d.type, "
                "       d.status, d.repaid "
                "  FROM debts d JOIN contacts c ON c.id = d.contact_id "
                " WHERE d.id = ? AND d.user_id = ?",
                (debt_id, _uid()),
            ).fetchone()
            if row is None:
                return None, None, "借贷记录不存在"
            if row["status"] == "paid":
                return None, None, "这笔借贷已经结清"
            repaid = round(row["repaid"] or 0, 2)
            remaining = round(row["amount"] - repaid, 2)
            if amount > remaining + 1e-9:
                return None, None, "还款金额不能超过剩余待还 %.2f" % remaining
            use_account = (account or row["account"] or "").strip()
            if not use_account:
                return None, None, "account 不能为空"
            exists = conn.execute(
                "SELECT 1 FROM accounts WHERE name = ? AND user_id = ?",
                (use_account, _uid()),
            ).fetchone()
            if exists is None:
                return None, None, "账户「%s」不存在" % use_account

            is_borrow = row["type"] == "borrow"
            record_type = "expense" if is_borrow else "income"
            category = "借入还款" if is_borrow else "借出收款"
            note = ("借入还款" if is_borrow else "借出收款") + " #%d · %s" % (
                debt_id,
                row["contact_name"] or "",
            )
            when = (
                normalize_date(repay_date)
                if repay_date
                else datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            cur = conn.execute(
                """
                INSERT INTO records
                       (user_id, amount, category, category_id, note, date, account, type,
                        formula, to_account, fee, is_reimbursable,
                        reimbursement_contact_id, reimbursed_amount, total_reimbursement,
                        image_path, created_at)
                VALUES (?, ?, ?, NULL, ?, ?, ?, ?, '', '', 0, 0, NULL, 0, 0, '',
                        datetime('now','localtime'))
                """,
                (_uid(), amount, category, note, when, use_account, record_type),
            )
            record_id = cur.lastrowid
            _apply_effects(conn, _balance_effects(record_type, use_account, "", amount, 0))
            new_repaid = round(repaid + amount, 2)
            status = "paid" if new_repaid >= row["amount"] - 1e-9 else "unpaid"
            conn.execute(
                "UPDATE debts SET repaid = ?, status = ? WHERE id = ? AND user_id = ?",
                (min(new_repaid, round(row["amount"], 2)), status, debt_id, _uid()),
            )
    finally:
        conn.close()
    return get_debt(debt_id), get_record(record_id), None


def reimburse_record(record_id, amount=None, account=None, reimburse_date=None):
    """v0.13.8 报销闭环：把一条可报销支出的未报销部分入账。

    流程与借贷对称：资金账户 **增加**（公司/对方打钱进来），生成一条 income 流水
    （分类「报销入账」，备注带原账目 id），同时累加 records.reimbursed_amount。
    不传 amount 时默认把剩余未报销金额全部结清。
    返回 (账目字典, 流水字典或 None, 错误信息)。
    """
    record = get_record(record_id)
    if record is None:
        return None, None, "账目不存在"
    if not record.get("is_reimbursable"):
        return None, None, "这条账目没有开启报销"
    total = round(float(record.get("total_reimbursement") or 0), 2)
    paid = round(float(record.get("reimbursed_amount") or 0), 2)
    remaining = round(total - paid, 2)
    if remaining <= 0:
        return None, None, "这条账目已经全部报销"
    if amount is None:
        amount = remaining
    problem = _check_debt_amount(amount)
    if problem is not None:
        return None, None, problem
    amount = round(float(amount), 2)
    if amount > remaining + 1e-9:
        return None, None, "报销金额不能超过待报销 %.2f" % remaining
    use_account = (account or "").strip()
    if not use_account:
        return None, None, "报销必须选择一个入账账户"
    conn = get_conn()
    record_new_id = None
    try:
        with conn:
            exists = conn.execute(
                "SELECT 1 FROM accounts WHERE name = ? AND user_id = ?",
                (use_account, _uid()),
            ).fetchone()
            if exists is None:
                return None, None, "账户「%s」不存在" % use_account
            when = (
                normalize_date(reimburse_date)
                if reimburse_date
                else datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            )
            note = "报销入账 #%d · %s" % (
                record_id,
                (record.get("note") or record.get("category") or "").strip(),
            )
            cur = conn.execute(
                """
                INSERT INTO records
                       (user_id, amount, category, category_id, note, date, account, type,
                        formula, to_account, fee, is_reimbursable,
                        reimbursement_contact_id, reimbursed_amount, total_reimbursement,
                        image_path, created_at)
                VALUES (?, ?, '报销入账', NULL, ?, ?, ?, 'income', '', '', 0, 0, NULL, 0, 0,
                        '', datetime('now','localtime'))
                """,
                (_uid(), amount, note, when, use_account),
            )
            record_new_id = cur.lastrowid
            _apply_effects(conn, _balance_effects("income", use_account, "", amount, 0))
            conn.execute(
                "UPDATE records SET reimbursed_amount = ? WHERE id = ? AND user_id = ?",
                (round(min(paid + amount, total), 2), record_id, _uid()),
            )
    finally:
        conn.close()
    return get_record(record_id), get_record(record_new_id), None


# ---------------- 图标素材库（v0.12.3） ----------------


def _row_to_icon(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "path": row["path"],
        "is_system": bool(row["is_system"]),
        "user_id": row["user_id"],
        "created_at": row["created_at"],
    }


def list_icons(include_others=False):
    """图标列表：系统内置 + 当前用户上传；include_others 是管理端看所有人上传。"""
    conn = get_conn()
    try:
        if include_others:
            rows = conn.execute(
                "SELECT id, name, path, is_system, user_id, created_at FROM icons "
                "ORDER BY is_system DESC, id ASC"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, path, is_system, user_id, created_at FROM icons "
                "WHERE is_system = 1 OR user_id = ? ORDER BY is_system DESC, id ASC",
                (_uid(),),
            ).fetchall()
        return [_row_to_icon(row) for row in rows]
    finally:
        conn.close()


def add_icon(name, path, is_system=False, owner_id=None):
    """新增图标，返回图标字典；普通用户只能给自己加。"""
    name = (name or "").strip()[:40]
    path = (path or "").strip()
    if not path:
        raise RecordError("图标地址不能为空")
    user_id = 0 if is_system else (owner_id if owner_id is not None else _uid())
    conn = get_conn()
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO icons (name, path, is_system, user_id) VALUES (?, ?, ?, ?)",
                (name, path, 1 if is_system else 0, user_id),
            )
        row = conn.execute(
            "SELECT id, name, path, is_system, user_id, created_at FROM icons WHERE id = ?",
            (cur.lastrowid,),
        ).fetchone()
        return _row_to_icon(row)
    finally:
        conn.close()


def delete_icon(icon_id):
    """删除自己的图标；系统内置与别人的图标删不掉。返回 (是否删除, 错误信息)。"""
    conn = get_conn()
    try:
        with conn:
            row = conn.execute(
                "SELECT is_system, user_id FROM icons WHERE id = ?", (icon_id,)
            ).fetchone()
            if row is None:
                return False, "图标不存在"
            if row["is_system"]:
                return False, "系统内置图标不能删除"
            if row["user_id"] != _uid():
                return False, "只能删除自己上传的图标"
            conn.execute("DELETE FROM icons WHERE id = ?", (icon_id,))
            conn.execute("DELETE FROM user_icon_settings WHERE icon_id = ?", (icon_id,))
            return True, None
    finally:
        conn.close()


def set_user_icon(kind, name, icon_id):
    """把某个分类/账户换成指定图标；返回 True/False。"""
    if kind not in ("category", "account"):
        raise RecordError("kind 只能是 category / account")
    icon = None
    conn = get_conn()
    try:
        with conn:
            icon = conn.execute("SELECT id FROM icons WHERE id = ?", (icon_id,)).fetchone()
            if icon is None:
                return False
            conn.execute(
                "INSERT INTO user_icon_settings (user_id, kind, name, icon_id) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(user_id, kind, name) DO UPDATE SET icon_id = excluded.icon_id",
                (_uid(), kind, name, icon_id),
            )
            return True
    finally:
        conn.close()


def clear_user_icon(kind, name):
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "DELETE FROM user_icon_settings WHERE user_id = ? AND kind = ? AND name = ?",
                (_uid(), kind, name),
            )
            return True
    finally:
        conn.close()


def list_user_icons():
    """当前用户的图标覆盖设置：{category: {名字: 图标}, account: {...}}。"""
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT s.kind, s.name, s.icon_id, i.path, i.name AS icon_name "
            "  FROM user_icon_settings s JOIN icons i ON i.id = s.icon_id "
            " WHERE s.user_id = ?",
            (_uid(),),
        ).fetchall()
        result = {"category": {}, "account": {}}
        for row in rows:
            result.setdefault(row["kind"], {})[row["name"]] = {
                "icon_id": row["icon_id"],
                "path": row["path"],
                "icon_name": row["icon_name"],
            }
        return result
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


def list_ai_memories_for_prompt(limit=200):
    """给 AI Prompt 用的记忆：排除【系统示例】，示例只用于后台列表展示。

    v0.14.1：默认纠错示例写进了同一张表，若直接喂给模型会把所有人的
    few-shot 都变成内置例句。这里按 note 前缀过滤，用户自己写的记忆不受影响。
    """
    return [
        item
        for item in list_ai_memories(limit)
        if SEED_MEMORY_MARK not in (item.get("note") or "")
    ]


def list_recent_ai_memories(limit=3):
    """取最近几条纠错给 Prompt 当 few-shot；条数固定很小，避免提示词被撑爆。"""
    return list_ai_memories_for_prompt(limit)


def search_ai_memories(text, limit=3):
    """按关键词 + 模糊相似度从记忆库里挑最相关的几条（v0.11.5 RAG）。

    和 v0.11.4 的「只取最近 3 条」相比，这里会真的读用户这次说的话：
    - difflib 相似度衡量整句像不像；
    - 2 字片段命中数当作关键词重合度（不引第三方分词，够用且快）；
    - 分数太低的直接不要，不足 limit 时用最近的记忆补齐，保证 Prompt 里总有几条参考。
    """
    query = re.sub(r"\s+", "", (text or "").strip().lower())
    memories = list_ai_memories_for_prompt(200)
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
        + "   AND r.user_id = ?"
        + "   AND ABS(r.amount - ?) < 0.005"
        + "   AND r.created_at <> ''"
        + "   AND r.created_at >= datetime('now','localtime', ?)"
    )
    params = [_uid(), amount_value, "-%d minutes" % minutes]
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


# ---------------- 提示文案库（v0.14.0，后台 Tips 管理） ----------------

# toast() 的状态类型白名单：success / error / info / warn。
# 前三种是需求定的；warn 是 v0.11.4 起就存在的黄色提醒，允许后台补文案，前端有内置兜底。
TIP_TYPES = ("success", "error", "info", "warn")
DEFAULT_TIP_TYPE = "success"
MAX_TIP_LENGTH = 80

# 首次建表时的默认颜文字文案（严禁 Emoji，全部用 Kaomoji）。
# 与 static/script.js 里的 TOAST_COPY 保底池保持同一套话术，接口挂了也不会变味。
# 每条：(type, content, location)。location 是「场景位置」短标签（≤20 字），
# 后台提示文案管理用来分场景定位文案；文案本身沿用原来的 6 条原文，一字不改。
DEFAULT_SYSTEM_TIPS = (
    ("success", r"0v0 记账成功，又存下了一笔！", "记账成功"),
    ("success", r"(≧∇≦)ﾉ 保存成功啦！", "保存"),
    ("success", r"(๑•̀ㅂ•́)و✧ 数据已安全同步至云端！", "云同步"),
    ("error", r">_< 网络开小差了，请稍后再试", "网络"),
    ("error", r"(´･ω･\) 操作失败了，检查一下网络吧", "网络"),
    ("info", r"(・ω・)ノ 正在为您拉取最新数据...", "通用"),
)


# 场景位置标签上限：后台输入框 maxlength 也是 20，服务端再兜一层
MAX_TIP_LOCATION_LENGTH = 20


def _row_to_tip(row):
    return {
        "id": row["id"],
        "type": row["type"],
        "content": row["content"],
        "location": row["location"] or "",
        "is_active": int(row["is_active"] or 0),
        "created_at": row["created_at"] or "",
    }


def _seed_system_tips(conn):
    """提示文案表为空时灌入默认颜文字文案。只在空表时灌，管理员删光也不会复活。"""
    count = conn.execute("SELECT COUNT(*) AS n FROM system_tips").fetchone()["n"]
    if count:
        return
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    for tip_type, content, location in DEFAULT_SYSTEM_TIPS:
        conn.execute(
            "INSERT INTO system_tips (type, content, location, is_active, created_at) "
            "VALUES (?, ?, ?, 1, ?)",
            (tip_type, content, location, now),
        )


def _backfill_tip_locations(conn):
    """v0.14.0：给「先于 location 列存在」的 6 条默认文案补场景位置。

    老库升级时 location 列是 ALTER 出来的、已有行全是空串，后台表格会显示一片「—」。
    这里只按默认文案原文精确匹配、且只在 location 为空时回填：
    - 管理员改过的文案不会被动到；
    - 管理员删掉的文案也不会复活（本函数不插行）；
    - 重复执行幂等（已有 location 的行不再 matches 空条件）。
    """
    updated = 0
    for _tip_type, content, location in DEFAULT_SYSTEM_TIPS:
        cursor = conn.execute(
            "UPDATE system_tips SET location = ? "
            " WHERE content = ? AND (location IS NULL OR TRIM(location) = '')",
            (location, content),
        )
        updated += cursor.rowcount or 0
    if updated:
        print("[v0.14.0] 提示文案场景位置回填：%d 条" % updated)
    return updated


def list_system_tips(active_only=False):
    """提示文案列表（后台管理看全量，前端只看启用中的）。按类型 + id 排序，顺序稳定。"""
    sql = "SELECT id, type, content, location, is_active, created_at FROM system_tips"
    if active_only:
        sql += " WHERE is_active = 1"
    sql += " ORDER BY type, id"
    conn = get_conn()
    try:
        return [_row_to_tip(row) for row in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def active_tips_by_type():
    """前端 toast() 用的结构：{"success": [...], "error": [...], "info": [...], "warn": [...]}。

    只返回 is_active=1 的文案；某个类型一条都没有时给空列表，前端自动回退内置保底池。
    """
    grouped = {tip_type: [] for tip_type in TIP_TYPES}
    for tip in list_system_tips(active_only=True):
        grouped.setdefault(tip["type"], []).append(tip["content"])
    return grouped


def _normalize_tip_input(tip_type, content, is_active, location=""):
    tip_type = str(tip_type or DEFAULT_TIP_TYPE).strip()
    if tip_type not in TIP_TYPES:
        raise RecordError("提示类型只能是 success / error / info / warn")
    content = str(content or "").strip()
    if not content:
        raise RecordError("提示文案不能为空")
    if len(content) > MAX_TIP_LENGTH:
        raise RecordError("提示文案最多 %d 个字" % MAX_TIP_LENGTH)
    # 场景位置是可选短标签：去空白后截断到 20 字，不填就是空串（后台显示为空）
    location = str(location or "").strip()[:MAX_TIP_LOCATION_LENGTH]
    try:
        active = 1 if int(is_active) else 0
    except (TypeError, ValueError):
        active = 1
    return tip_type, content, active, location


def create_system_tip(tip_type="success", content="", is_active=1, location=""):
    """新增一条提示文案，返回入库后的字典。类型 / 空文案 / 长度都在这里校验。"""
    tip_type, content, active, location = _normalize_tip_input(
        tip_type, content, is_active, location
    )
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute(
                "INSERT INTO system_tips (type, content, location, is_active, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (tip_type, content, location, active, now),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, type, content, location, is_active, created_at "
            "FROM system_tips WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_tip(row)
    finally:
        conn.close()


def update_system_tip(tip_id, tip_type=None, content=None, is_active=None, location=None):
    """按 id 局部更新提示文案；字段传 None 表示不改。找不到返回 None。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT id, type, content, location, is_active FROM system_tips WHERE id = ?",
            (tip_id,),
        ).fetchone()
        if row is None:
            return None
        next_type = row["type"] if tip_type is None else tip_type
        next_content = row["content"] if content is None else content
        next_active = row["is_active"] if is_active is None else is_active
        next_location = row["location"] if location is None else location
        next_type, next_content, next_active, next_location = _normalize_tip_input(
            next_type, next_content, next_active, next_location
        )
        with conn:
            conn.execute(
                "UPDATE system_tips SET type = ?, content = ?, location = ?, "
                "is_active = ? WHERE id = ?",
                (next_type, next_content, next_location, next_active, tip_id),
            )
        updated = conn.execute(
            "SELECT id, type, content, location, is_active, created_at "
            "FROM system_tips WHERE id = ?",
            (tip_id,),
        ).fetchone()
        return _row_to_tip(updated)
    finally:
        conn.close()


def delete_system_tip(tip_id):
    """按 id 删除提示文案，返回是否真的删掉了一条。"""
    conn = get_conn()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM system_tips WHERE id = ?", (tip_id,))
        return cursor.rowcount > 0
    finally:
        conn.close()


# ---------------- 帮助内容配置 + 用户反馈（v0.14.0） ----------------

# app_settings 里的四个帮助内容键；后台「帮助与反馈内容配置」直接编辑这四段文本
HELP_FAQ_KEY = "help_faq"
HELP_SHORTCUTS_KEY = "help_shortcuts"
HELP_CONTACT_KEY = "help_contact"
HELP_PLACEHOLDER_KEY = "help_feedback_placeholder"
MAX_HELP_TEXT_LENGTH = 8000

# 默认帮助内容（只在该 key 还不存在时灌入，管理员改过就永久保留自己的版本）。
# 多行文本行格式：FAQ「问题|答案」、快捷键「按键|说明」、联系方式「名称|值」。
_DEFAULT_HELP_FAQ = "\n".join(
    (
        "如何快速记一笔？|按一下键盘 N，或点右下角钢笔悬浮球，填写金额与分类后回车即可保存。",
        "账单记错了怎么改？|在账单列表里右键该条账单，选择「编辑」，改完保存即可。",
        "数据会丢吗？|账本已安全同步云端；也可以在「我的 → 导入/导出账单」里随时导出 CSV/XLSX 备份。",
        "支持哪些导入格式？|支持微信、支付宝导出的 CSV / XLSX 账单，导入前会先预览、重复项默认不勾选。",
    )
)
_DEFAULT_HELP_SHORTCUTS = "\n".join(
    (
        "N|新建账单",
        "Ctrl+K|搜索账单",
        "Ctrl+S|保存当前弹窗（如记账）",
        "Esc|关闭当前弹窗",
    )
)
_DEFAULT_HELP_CONTACT = "\n".join(
    (
        "客服邮箱|support@zhihuizhang.example.com",
        "客服 QQ|800100000",
        "工作时间|工作日 9:00 - 18:00",
    )
)
_DEFAULT_HELP_PLACEHOLDER = "抱歉，工程师是小呆呆，有什么问题和诉求请在这里留言！(・ω・)ノ"

HELP_SETTING_DEFAULTS = (
    (HELP_FAQ_KEY, _DEFAULT_HELP_FAQ),
    (HELP_SHORTCUTS_KEY, _DEFAULT_HELP_SHORTCUTS),
    (HELP_CONTACT_KEY, _DEFAULT_HELP_CONTACT),
    (HELP_PLACEHOLDER_KEY, _DEFAULT_HELP_PLACEHOLDER),
)


def _seed_help_settings(conn):
    """帮助内容只在缺 key 时灌默认值；管理员改过的内容不会被默认值覆盖。"""
    for key, value in HELP_SETTING_DEFAULTS:
        conn.execute(
            "INSERT OR IGNORE INTO app_settings (key, value) VALUES (?, ?)", (key, value)
        )


def get_app_setting(key, default=""):
    """读 app_settings 里的单个配置；没有这个 key 时返回 default。"""
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (str(key),)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return default
    value = row["value"]
    return default if value is None else value


def set_app_setting(key, value):
    """写单个配置（有则覆盖、无则新增），返回写入后的字符串值。"""
    key = str(key or "").strip()
    if not key:
        raise RecordError("配置键不能为空")
    value = "" if value is None else str(value)
    conn = get_conn()
    try:
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                (key, value),
            )
    finally:
        conn.close()
    return value


def get_help_raw():
    """后台编辑用的帮助内容原文：FAQ / 快捷键 / 联系方式 / 反馈占位文案。"""
    return {
        "faq": get_app_setting(HELP_FAQ_KEY, _DEFAULT_HELP_FAQ),
        "shortcuts": get_app_setting(HELP_SHORTCUTS_KEY, _DEFAULT_HELP_SHORTCUTS),
        "contact": get_app_setting(HELP_CONTACT_KEY, _DEFAULT_HELP_CONTACT),
        "feedback_placeholder": get_app_setting(
            HELP_PLACEHOLDER_KEY, _DEFAULT_HELP_PLACEHOLDER
        ),
    }


def _parse_help_rows(raw):
    """把「A|B」多行文本解析成 [(A, B)]：空行忽略，| 只切第一次。"""
    rows = []
    for line in str(raw or "").splitlines():
        line = line.strip()
        if not line:
            continue
        left, _, right = line.partition("|")
        rows.append((left.strip(), right.strip()))
    return rows


def get_help_content():
    """设置弹窗「帮助与反馈」用的结构化内容，前端直接按字段渲染。"""
    raw = get_help_raw()
    return {
        "faq": [
            {"q": question, "a": answer}
            for question, answer in _parse_help_rows(raw["faq"])
        ],
        "shortcuts": [
            {"keys": keys, "desc": desc}
            for keys, desc in _parse_help_rows(raw["shortcuts"])
        ],
        "contact": [
            {"label": label, "value": value}
            for label, value in _parse_help_rows(raw["contact"])
        ],
        "feedback_placeholder": raw["feedback_placeholder"],
    }


def update_help_content(
    faq=None, shortcuts=None, contact=None, feedback_placeholder=None
):
    """后台保存帮助内容：只更新传入项（None=不改），每项上限 8000 字，返回最新原文。"""
    updates = (
        (HELP_FAQ_KEY, faq),
        (HELP_SHORTCUTS_KEY, shortcuts),
        (HELP_CONTACT_KEY, contact),
        (HELP_PLACEHOLDER_KEY, feedback_placeholder),
    )
    conn = get_conn()
    try:
        with conn:
            for key, value in updates:
                if value is None:
                    continue
                if not isinstance(value, str):
                    raise RecordError("帮助内容必须是文本")
                value = value.strip()
                if len(value) > MAX_HELP_TEXT_LENGTH:
                    raise RecordError("帮助内容最多 %d 个字" % MAX_HELP_TEXT_LENGTH)
                conn.execute(
                    "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)",
                    (key, value),
                )
    finally:
        conn.close()
    return get_help_raw()


# 用户反馈：问题描述上限、联系方式类型白名单、10 秒防刷
MAX_FEEDBACK_LENGTH = 2000
MAX_FEEDBACK_CONTACT_LENGTH = 100
FEEDBACK_CONTACT_TYPES = ("", "qq", "wechat", "phone")
FEEDBACK_COOLDOWN_SECONDS = 10


def _feedback_now():
    """反馈时间统一用「YYYY-MM-DD HH:MM:SS」：列表可读，10 秒防刷也算得准。"""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_user_feedback(row):
    return {
        "id": row["id"],
        "user_id": row["user_id"],
        # 后台卡片用 uid 展示，等价于 user_id，语义跟用户管理保持一致
        "uid": row["user_id"],
        "email": row["email"] or "",
        "nickname": row["nickname"] or "",
        "issue_description": row["issue_description"] or "",
        "occur_date": row["occur_date"] or "",
        "image_path": row["image_path"] or "",
        "contact_type": row["contact_type"] or "",
        "contact_info": row["contact_info"] or "",
        "created_at": row["created_at"] or "",
    }


def create_user_feedback(
    issue_description,
    occur_date="",
    image_path="",
    contact_type="",
    contact_info="",
    email="",
    nickname="",
):
    """新增一条用户反馈，返回入库后的字典。

    user_id 一律取当前登录用户上下文（app.py 的 JWT 守卫已注入）；
    issue 必填且 ≤2000 字；occur_date 可空，非空要求 YYYY-MM-DD；
    contact_type 只允许 ""/qq/wechat/phone；联系方式 ≤100 字。
    服务端兜底 10 秒防刷：同一用户最近一条反馈距今不足 10 秒直接抛 RecordError。
    """
    user_id = current_user_id()
    issue = str(issue_description or "").strip()
    if not issue:
        raise RecordError("反馈内容不能为空")
    if len(issue) > MAX_FEEDBACK_LENGTH:
        raise RecordError("反馈内容最多 %d 个字" % MAX_FEEDBACK_LENGTH)

    occur_date = str(occur_date or "").strip()
    if occur_date:
        try:
            datetime.datetime.strptime(occur_date, "%Y-%m-%d")
        except ValueError:
            raise RecordError("发生日期格式应为 YYYY-MM-DD")

    contact_type = str(contact_type or "").strip().lower()
    if contact_type not in FEEDBACK_CONTACT_TYPES:
        raise RecordError("联系方式类型只能是 qq / wechat / phone")

    contact_info = str(contact_info or "").strip()
    if len(contact_info) > MAX_FEEDBACK_CONTACT_LENGTH:
        raise RecordError("联系方式最多 %d 个字" % MAX_FEEDBACK_CONTACT_LENGTH)

    image_path = str(image_path or "").strip()
    email = str(email or "").strip()
    nickname = str(nickname or "").strip()
    # 前端没带邮箱/昵称时按 user_id 回表兜底，保证后台卡片一定能看到联系方式
    if not email or not nickname:
        user = get_user(user_id)
        if user:
            email = email or (user.get("email") or "")
            nickname = nickname or (user.get("nickname") or "")

    now = datetime.datetime.now()
    conn = get_conn()
    try:
        last = conn.execute(
            "SELECT created_at FROM user_feedback WHERE user_id = ? "
            "ORDER BY created_at DESC, id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if last is not None and last["created_at"]:
            try:
                last_time = datetime.datetime.strptime(
                    last["created_at"], "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                last_time = None
            if (
                last_time is not None
                and (now - last_time).total_seconds() < FEEDBACK_COOLDOWN_SECONDS
            ):
                raise RecordError("发送太频繁，请 10 秒后再试")

        with conn:
            cursor = conn.execute(
                "INSERT INTO user_feedback "
                "(user_id, email, nickname, issue_description, occur_date, image_path, "
                " contact_type, contact_info, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    email,
                    nickname,
                    issue,
                    occur_date,
                    image_path,
                    contact_type,
                    contact_info,
                    now.strftime("%Y-%m-%d %H:%M:%S"),
                ),
            )
            new_id = cursor.lastrowid
        row = conn.execute(
            "SELECT id, user_id, email, nickname, issue_description, occur_date, "
            "       image_path, contact_type, contact_info, created_at "
            "  FROM user_feedback WHERE id = ?",
            (new_id,),
        ).fetchone()
        return _row_to_user_feedback(row)
    finally:
        conn.close()


def list_user_feedback():
    """后台「用户反馈」列表：所有用户的反馈，按提交时间倒序。

    管理员专用接口（app.py 里 _require_admin_access 守卫），所以不带 user_id 过滤；
    email / nickname 优先用反馈里存的那份，users 表兜底老数据。
    """
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT f.id, f.user_id, f.email, f.nickname, f.issue_description, "
            "       f.occur_date, f.image_path, f.contact_type, f.contact_info, "
            "       f.created_at, u.email AS user_email, u.nickname AS user_nickname "
            "  FROM user_feedback f LEFT JOIN users u ON u.id = f.user_id "
            " ORDER BY f.created_at DESC, f.id DESC"
        ).fetchall()
        items = []
        for row in rows:
            item = _row_to_user_feedback(row)
            item["email"] = row["email"] or row["user_email"] or ""
            item["nickname"] = row["nickname"] or row["user_nickname"] or ""
            items.append(item)
        return items
    finally:
        conn.close()
