"""AI 记账管家 · 智谱 GLM 接入层（v0.08.1 意图路由）

对外入口：

    parse_intent("昨天打车花了30")
    -> {"action": "record", "amount": 30.0, "type": "expense", ...}

    parse_intent("借给小王20元")
    -> {"action": "debt", "amount": 20.0, "contact_name": "小王", "type": "lend", ...}

    parse_intent("添加小王，他是亲戚")
    -> {"action": "add_contact", "name": "小王", "identity": "亲戚", ...}

    parse_intent("今天天气不错")
    -> {"action": "unknown"}

设计原则：
1. 模型只负责「理解一句话 + 拆字段」，不碰数据库、不算余额；
2. action 与各分支字段必须先过本地校验，不合格一律抛 AIServiceError；
3. 密钥只从环境变量 / .env 读取，不落日志、不进代码。
"""

from __future__ import annotations

import base64
import difflib
import json
import os
import re
from datetime import datetime, timedelta
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# override=False：已经在环境变量里配好的值优先，.env 只做兜底
load_dotenv(os.path.join(BASE_DIR, ".env"), override=False)

MODEL = "glm-4-flash"
VISION_MODEL = "glm-4v-flash"
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
API_KEY_ENV = "ZHIPU_API_KEY"
REQUEST_TIMEOUT = 20.0
# 视觉模型要先把图片编码进上下文，明显比纯文本慢，单独给更长的超时
VISION_TIMEOUT = 45.0
# 智谱多模态接口对单张图片有大小限制，前端会先压缩到 1600px / JPEG 0.82，这里再兜一层
IMAGE_MAX_BYTES = 5 * 1024 * 1024
IMAGE_MIME_FALLBACK = "image/jpeg"

ACTIONS = ("record", "debt", "add_contact", "unknown")
RECORD_TYPES = ("expense", "income", "transfer")

# v0.11.4 同义词纠错：模型经常把商户名/口语直接当分类返回（「滴滴」「星巴克」），
# 这里在归一化阶段强制改写成标准分类，避免给用户凭空建出一堆商户分类。
CATEGORY_MAPPING = {
    "滴滴": "交通",
    "滴滴出行": "交通",
    "打撤": "交通",
    "打车": "交通",
    "出租车": "交通",
    "网约车": "交通",
    "地铁": "交通",
    "公交": "交通",
    "加油": "交通",
    "星巴克": "餐饮",
    "瑞幸": "餐饮",
    "麦当劳": "餐饮",
    "肯德基": "餐饮",
    "美团": "餐饮",
    "饿了么": "餐饮",
    "外卖": "餐饮",
    "奶茶": "餐饮",
    "咖啡": "餐饮",
    "淘宝": "购物",
    "京东": "购物",
    "拼多多": "购物",
    "超市": "购物",
    "房租": "居住",
    "水电": "居住",
    "话费": "居住",
    "物业": "居住",
}

# v0.11.5 账户 / 联系人模糊匹配：模型常把用户口语里的叫法原样返回
# （「威信零钱通」「支付宝余额」），这里在归一化阶段跟库里的真实名字比对。
# 规则顺序很重要：先认精确同名 → 再认「子账户后缀」→ 再认常见错字别名 → 最后才用 difflib。
FUZZY_CUTOFF = 0.8
# 支付账户的常见子账户后缀，长后缀放前面，避免「零钱通」被「零钱」先截断
ACCOUNT_SUFFIXES = ("零钱通", "零钱", "钱包", "余额宝", "余额", "支付", "账户")
# 常见同音错字 / 口语叫法 → 标准账户名；只做「账户品牌」层面的替换，
# 不影响「微信零钱」这种品牌写对了、只是多了子账户后缀的情况。
ACCOUNT_ALIASES = {
    "威信": "微信",
    "薇信": "微信",
    "维信": "微信",
    "威信支付": "微信",
    "微信支付": "微信",
    "支付宝账户": "支付宝",
    "银行": "银行卡",
    "银行卡支付": "银行卡",
}
CONTACT_FUZZY_CUTOFF = 0.8

# 模型可能写中文，统一映射到数据库的 lend / borrow
DEBT_TYPE_ALIASES = {
    "lend": "lend",
    "借出": "lend",
    "借给": "lend",
    "借给别人": "lend",
    "borrow": "borrow",
    "借入": "borrow",
    "向别人借": "borrow",
    "找我借": "borrow",
}

DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)

SYSTEM_PROMPT = """你是中文记账助手，先判断用户这句话的意图，再按意图抽取字段，只输出一个 JSON 对象。

【输出要求】
- 不要 Markdown 代码块、不要解释、不要多余文字。
- 字段键名固定为下面 16 个，不得增删、不得改名；每个意图只填自己需要的字段，其余留空字符串 ""、0 或 false：
  action          字符串，只能是 "record"（记账）、"debt"（借贷）、"add_contact"（添加联系人）、"unknown"（听不懂）
  amount          数字，金额，必须大于 0，不带货币符号
  type            记账时只能是 "expense"/"income"/"transfer"；借贷时只能是 "lend"（我借出）/ "borrow"（我借入）
  category        字符串，记账分类，如 餐饮、交通、购物、工资；不适用时填 ""
  account         字符串，账户名；用户没提就填空字符串 ""
  to_account      字符串，仅转账时填转入账户，其余填 ""
  fee             数字，仅转账手续费，其余填 0
  date            字符串，格式固定 "YYYY-MM-DD HH:MM"，24 小时制
  note            字符串，一句话摘要，不超过 30 字
  is_reimbursable 布尔值，仅记账时用：帮别人代买/给公司垫付、之后要报销时为 true；普通记账填 false
  contact_name    字符串，借贷对象的姓名；记账且 is_reimbursable=true 时填报销人/垫付对象姓名，没有就填 ""
  identity        字符串，联系人身份/关系，如 亲戚、同学、同事
  phone           字符串，联系人电话
  wechat          字符串，联系人微信
  name            字符串，添加联系人时的姓名
  confidence      整数 0-100，你对本次解析结果的确定程度：金额、分类、时间都能从原话明确确定时给 90 以上；有猜测成分、语句含糊、字段靠默认值补齐时给低分（低于 80）

【置信度规则】
- 每一次输出都必须带 confidence，任何意图都不能省略。
- 这只是「模型自评」，用于前端提醒用户核对；不要因为怕错就一律写低分。

【金额提取强约束（历史踩坑最多，务必遵守）】
- 金额只认「带货币单位」或明显在花钱语境里的数字：数字后面紧跟 元 / 块 / ￥ / ¥，或句子里有「花了、买了、付了、垫付、代买、报销、借、还」等动作时代表钱的那个数。
- 绝不把人名、备注、时间、电话、编号里的数字当金额：
  「测试乙41215 买了奶茶20元」→ amount 是 20，测试乙41215 是人名，原样保留，绝不拆成 6607712.5 之类；
  「3月8日买花38元」→ amount 是 38，日期里的 3、8 不是金额；
  「给小王转500」→ amount 是 500，小王不是数字。
- 一句话里有多个数字时，取真正要记的那一笔金额；手续费单独填 fee。
- 人名一律原样保留：不得删字、不得去掉「测试」等前缀、不得把名字里的数字挪进 amount。

【意图判断】
- action = "record"：用户在记一笔自己的收支、替别人代买/垫付，或账户转账，例如「昨天打车30」「工资到账8000」「帮同事代买咖啡30」。
- action = "debt"：用户在和某个人发生借入/借出，例如「借给小王20元」「向小李借了100」。
- action = "add_contact"：用户只想存一个联系人信息，例如「添加小王，他是亲戚，电话13800000000」。
- action = "unknown"：闲聊、提问、没有金额也看不出记账/借贷/联系人意图，例如「今天天气不错」「你好」。
- 一句话同时像记账又像借贷时，以「钱是否借给了某个人、之后要还」为准，选 debt；代买/垫付之后要找对方或公司报销的，仍然选 record 并标 is_reimbursable。

【record 规则】
- 分类：打车/地铁/公交 → 交通；吃饭/外卖/奶茶/咖啡 → 餐饮；买菜/日用品/超市 → 购物；房租/水电/话费 → 居住；工资/奖金/退款 → 对应收入类分类；判断不了填 "其他"。
- 分类必须是标准分类名（交通/餐饮/购物/居住/工资/其他 等），绝对不要把商户名当分类（「滴滴」「星巴克」是商户，不是分类）。
- 账户（v0.11.5）：account 优先从 Prompt 末尾的【用户真实账户列表】里选；用户说的是具体子账户（「微信零钱」「支付宝余额」「招行卡尾号1234」）时原样保留，不要向上合并成大类账户；用户说的是账户名的错别字/同音字（「威信」「薇信」）也先原样输出，后端会统一纠正并提示。
- 类型：「花了/买了/付了」→ expense；「收到/工资/奖金/退款」→ income；「从A转到B」→ transfer，account 转出、to_account 转入；多个金额取最主要那笔，手续费单独填 fee。
- 时间：今天是 {today}（{weekday}），当前时间 {now}；「昨天/前天/上周五」换算成具体日期；没提时间用 {now}；只提日期时刻填 00:00。
- 报销（代买/垫付）：用户替别人或公司花钱、之后要收回来时，is_reimbursable 填 true；
  「帮小明买咖啡30」→ contact_name 是 "小明"；「帮同事代买咖啡30」「给公司垫付打车50 报销」没有具体姓名 → contact_name 留 "";
  普通自己花钱记账 is_reimbursable 填 false、contact_name 留 ""。
- 报销和借贷别混淆：之后对方要「还我」的是 debt；我先垫钱、走公司/个人报销流程的是 record + is_reimbursable。

【debt 规则】
- type：我借给别人 → "lend"；我向别人借 → "borrow"。
- contact_name 必填，从原句提取人名；姓名必须原样保留、不得删字（如「借给小王20元」→ "小王"）。
- identity/phone/wechat/name 留空；is_reimbursable 填 false。
- account 是资金账户，没提填 ""（后端用默认账户）；date 规则同记账。

【add_contact 规则】
- name 必填；姓名必须原样保留、不得删字，也不要把「测试」这类前缀当废话删掉（如「添加测试阿星，他是同事」→ name 是 "测试阿星"）。
- identity、phone、wechat 有就填，没有留空。
- amount 填 0，type 留空字符串，is_reimbursable 填 false，category/account/date/note 等其余字段留空或按格式补 0。

【示例】
用户：昨天打车花了30
输出：{{"action": "record", "amount": 30, "type": "expense", "category": "交通", "account": "", "to_account": "", "fee": 0, "date": "{yesterday} 00:00", "note": "打车", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：工资到账 8000
输出：{{"action": "record", "amount": 8000, "type": "income", "category": "工资", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "工资到账", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：帮同事小明代买咖啡30
输出：{{"action": "record", "amount": 30, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "帮小明代买咖啡", "is_reimbursable": true, "contact_name": "小明", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：给公司垫付打车50，记得报销
输出：{{"action": "record", "amount": 50, "type": "expense", "category": "交通", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "垫付打车报销", "is_reimbursable": true, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：测试乙41215 买了奶茶20元
输出：{{"action": "record", "amount": 20, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "买奶茶", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：借给小王20元
输出：{{"action": "debt", "amount": 20, "type": "lend", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "借给小王20元", "is_reimbursable": false, "contact_name": "小王", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：向小李借了100
输出：{{"action": "debt", "amount": 100, "type": "borrow", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "向小李借100", "is_reimbursable": false, "contact_name": "小李", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}

用户：添加小王，他是亲戚，电话13800000000
输出：{{"action": "add_contact", "amount": 0, "type": "", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "添加联系人小王", "is_reimbursable": false, "contact_name": "", "identity": "亲戚", "phone": "13800000000", "wechat": "", "name": "小王"}}

用户：今天天气不错
输出：{{"action": "unknown", "amount": 0, "type": "", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}}
"""


VISION_PROMPT = """你是中文记账助手的「截图识别」模块。用户会给你一张手机截图，可能是微信/支付宝的支付成功页、账单列表、超市小票、银行短信或聊天转账记录。

【任务】判断这张图是不是一笔可以记账的交易（消费、收入、转账、借贷），是就抽取字段，只输出一个 JSON 对象；不是账单（聊天闲谈、表情包、风景照、无关页面）就输出 {"action": "unknown"}。

【输出要求】
- 不要 Markdown 代码块、不要解释、不要多余文字。
- 字段键名固定为下面 15 个，不得增删、不得改名；不适用的填空字符串 ""、0 或 false：
  action          字符串，只能是 "record"（记账）、"debt"（借贷）、"unknown"（不是账单/看不清）
  amount          数字，本笔交易金额，必须大于 0，不带货币符号
  type            只能是 "expense"（支出）、"income"（收入/退款）、"transfer"（账户转账）
  category        字符串，分类，如 餐饮、交通、购物、居住
  account         字符串，付款账户名，截图能看出来才填，否则 ""
  to_account      字符串，仅转账时填转入账户
  fee             数字，手续费，没有填 0
  date            字符串，交易时间，格式固定 "YYYY-MM-DD HH:MM"；只有日期填 00:00
  note            字符串，商户/商品名 + 一句话摘要，不超过 30 字
  is_reimbursable 布尔值，这张图是帮别人代付/垫付、之后要报销时为 true
  contact_name    字符串，借贷对象或垫付对象姓名，没有填 ""
  identity        字符串，联系人身份，如 同事、同学
  phone           字符串，联系人电话，没有填 ""
  wechat          字符串，联系人微信，没有填 ""
  name            字符串，添加联系人时的姓名，没有填 ""
  confidence      整数 0-100，你对这张图识别结果的确定程度：金额和分类都清晰可辨时给 90 以上；图糊、金额靠猜、分类靠推断时给低分（低于 80）

【金额识别强约束】
- 只取「实付/支付/消费/收款/转账」那笔交易金额，例如「-30.00」「实付 ¥30.00」「收款 100.00」。
- 绝不把余额、优惠券面额、订单号、手机号、时间（12:31）、日期（2026-10-28）里的数字当金额。
- 图里有多个金额时，取本次实际交易的那一笔；手续费单独放进 fee。
- 看不清或没有明确金额 → 输出 {"action": "unknown"}，绝不猜。

【类型与分类】
- 「支付/付款/消费/买了」→ expense；「收款/退款/红包/工资到账」→ income（金额填正数）；「转给/转到」→ transfer。
- 分类按商户判断：麦当劳/奶茶/咖啡/外卖/餐厅 → 餐饮；滴滴/地铁/公交/加油 → 交通；超市/淘宝/京东/日用品 → 购物；房租/水电/话费 → 居住；判断不了填 "其他"。
- account：截图里出现的付款方式（零钱、余额、招商银行储蓄卡、花呗）能映射成账户名就填，判断不了填空字符串；用户库里已有具体子账户时（微信零钱、支付宝余额）原样保留，不要合并成「微信」「支付宝」。

【时间】
- 截图里有交易时间就用它；只有日期填 00:00；完全没有时间用当前时间 __NOW__（今天 __TODAY__）。

【示例】
截图内容：支付成功 / 麦当劳 / 实付 ¥30.00 / 2026-10-28 12:31
输出：{"action": "record", "amount": 30, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "2026-10-28 12:31", "note": "麦当劳 午餐", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": "", "confidence": 95}

截图内容：一张猫的照片
输出：{"action": "unknown"}
"""


NOTIFICATION_PROMPT = """你是记账应用「AI记账管家」的更新公告撰稿人。用户不会给你主题，你要为指定版本号写一条面向普通用户的中文更新公告，唯一依据是随消息附带的「该版本真实开发日志」。只输出一个 JSON 对象。

【绝对依据】
- 只能基于附带的真实开发日志写：日志里提到什么改动就写什么，用普通用户能听懂的话解释「在哪里能看到、怎么用」。
- 严禁编造日志里没有的功能；严禁写「修复了若干已知问题」「优化了性能」「提升稳定性」这类没有日志依据的空话。
- 日志里确实没有面向用户的变化时，就写最保守的内部维护说明，不要硬凑功能。

【标题规范（必须严格遵守）】
- title 必须严格以「版本号 版本更新：」开头，版本号原样使用给定的值，不要加方括号。
- 例如：v0.11.3-DEV 版本更新：后台密码与首页趋势图
- 冒号后接一句不超过 20 个汉字的概括，不要用「重磅」「震撼」这类营销词。

【正文规范】
- content：纯文本，不带 Markdown、不带 HTML 标签、不用表情或符号装饰，语气平实客观。
- 分点列出：用 1. 2. 3. 分行，每条一到两句话，讲清楚「改了什么、用户能怎么用、注意什么」。
- 3 到 5 条，总字数控制在 200 字以内；不夸大、不编造没提到的功能。

【输出】
- 只输出两个键：title（字符串）、content（字符串，条目之间用 \\n 分隔）。
"""


# ---------------- 通知起草参考真实开发日志（v0.11.2） ----------------

DEV_LOG_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "docs", "dev-log.md"
)
DEV_LOG_ENTRY_MAX_CHARS = 3600
_VERSION_LINE_RE = re.compile(r"^v\d+\.\d+")


def latest_dev_log_entry() -> str:
    """读取 docs/dev-log.md 中最后一个版本段落的原文，给通知起草当唯一依据。

    开发日志按「v0.xx-DEV 日期 标题」分段，段落之间用破折号分隔；
    这里只取最后一段，并去掉末尾的分隔线与多余空行。
    """
    try:
        with open(DEV_LOG_PATH, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    starts = [
        index
        for index, line in enumerate(lines)
        if _VERSION_LINE_RE.match(line.strip())
    ]
    if not starts:
        return ""

    block = []
    for line in lines[starts[-1]:]:
        if block and _VERSION_LINE_RE.match(line.strip()):
            break
        block.append(line)
    while block and (not block[-1] or set(block[-1]) <= set("—-")):
        block.pop()

    entry = "\n".join(block).strip()
    return entry[:DEV_LOG_ENTRY_MAX_CHARS]


def dev_log_entry_for_version(version: str) -> str:
    """读取 docs/dev-log.md 中指定版本号的段落原文（v0.11.3）。

    generate_notification 用它拿「这个版本到底改了什么」当唯一写作依据；
    找不到该版本段落时返回空字符串，由调用方回落到最新一段。
    """
    target = (version or "").strip()
    if not target:
        return ""
    try:
        with open(DEV_LOG_PATH, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError:
        return ""

    lines = [line.rstrip() for line in text.splitlines()]
    pattern = re.compile(r"^" + re.escape(target) + r"(?:\s|$)")
    start = None
    for index, line in enumerate(lines):
        if pattern.match(line.strip()):
            start = index
            break
    if start is None:
        return ""

    block = []
    for line in lines[start:]:
        if block and _VERSION_LINE_RE.match(line.strip()):
            break
        block.append(line)
    while block and (not block[-1] or set(block[-1]) <= set("—-")):
        block.pop()

    entry = "\n".join(block).strip()
    return entry[:DEV_LOG_ENTRY_MAX_CHARS]


class AIServiceError(Exception):
    """AI 解析失败：密钥缺失、网络错误、模型输出不是合法 JSON，都走这里。"""


def is_configured() -> bool:
    """给路由/页面判断「现在能不能用 AI」，不触发任何网络请求。"""
    return bool(os.getenv(API_KEY_ENV, "").strip())


def _client(timeout: float = REQUEST_TIMEOUT) -> OpenAI:
    key = os.getenv(API_KEY_ENV, "").strip()
    if not key:
        raise AIServiceError(
            "未配置 ZHIPU_API_KEY：请在项目根目录的 .env 里写入 ZHIPU_API_KEY=你的密钥，"
            "保存后重启 Flask 再试"
        )
    return OpenAI(api_key=key, base_url=BASE_URL, timeout=timeout)


def _compact_name(value: Any) -> str:
    """去掉空白/连字符/括号等装饰字符，只留可比较的名字主体。"""
    return re.sub(r"[\s\-_·（）()【】\[\]、,，.。]+", "", _as_text(value))


def _account_base(name: str) -> tuple[str, str]:
    """把「微信零钱通」拆成 (品牌「微信」, 后缀「零钱通」)；没有后缀时 suffix 为空。"""
    compact = _compact_name(name)
    for suffix in ACCOUNT_SUFFIXES:
        if compact.endswith(suffix) and len(compact) > len(suffix):
            return compact[: -len(suffix)], suffix
    return compact, ""


def _closest_name(name: str, candidates: list[str], cutoff: float = FUZZY_CUTOFF) -> str:
    """返回 candidates 里与 name 相似度最高且 >= cutoff 的那个，没有就返回空串。"""
    target = _compact_name(name)
    if not target:
        return ""
    best_name = ""
    best_ratio = 0.0
    for candidate in candidates:
        current = _compact_name(candidate)
        if not current:
            continue
        ratio = difflib.SequenceMatcher(None, target, current).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = candidate
    return best_name if best_ratio >= cutoff else ""


def _match_account(name: Any, accounts: Optional[list[str]]) -> tuple[str, bool]:
    """把 AI 抽到的账户名对齐到库里的真实账户，返回 (最终名字, 是否被纠正)。

    规则顺序（很重要，别随便调）：
    1. 一字不差 → 原样返回，不算纠正；
    2. 品牌写对、只是多了子账户后缀（微信零钱 / 支付宝余额）→ 保留子账户名，
       这是用户真实在用的具体账户，不该被强行吞成大类账户；
    3. 品牌本身是错字/同音（威信）→ 换成标准账户名，并标记已纠正；
    4. 其余情况用 difflib 相似度 >= 0.8 兜底（招商银行 ↔ 招行卡 这类近名）。
    """
    raw = _as_text(name)
    if not raw or not accounts:
        return raw, False
    compact = _compact_name(raw)
    exact = {_compact_name(item): item for item in accounts if _as_text(item)}
    if compact in exact:
        return exact[compact], False

    base, suffix = _account_base(raw)
    alias_target = ACCOUNT_ALIASES.get(base) or ACCOUNT_ALIASES.get(compact, "")
    if alias_target and _compact_name(alias_target) in exact:
        matched = exact[_compact_name(alias_target)]
        # 品牌本身写对了、只是带了子账户后缀（微信零钱通 → 微信）：保留用户的具体账户，
        # 不能因为别名表里有「微信」就把子账户吞掉；只有品牌写错（威信 → 微信）才替换
        if suffix and _compact_name(base) == _compact_name(matched):
            return raw, False
        if matched != raw:
            return matched, True

    # 品牌写对、只多了子账户后缀：当作合法子账户保留（如「微信」→「微信零钱」）
    for current, original in exact.items():
        if suffix and current == base:
            return raw, False

    similar = _closest_name(raw, accounts)
    if similar and _compact_name(similar) != compact:
        return similar, True
    return raw, False


def _match_contact(name: Any, contacts: Optional[list[str]]) -> tuple[str, bool]:
    """联系人姓名模糊匹配：相似度 >= 0.8 时用库里的名字，避免「小王」「晓王」记成两个人。"""
    raw = _as_text(name)
    if not raw or not contacts:
        return raw, False
    compact = _compact_name(raw)
    exact = {_compact_name(item): item for item in contacts if _as_text(item)}
    if compact in exact:
        return exact[compact], False
    similar = _closest_name(raw, contacts, CONTACT_FUZZY_CUTOFF)
    if similar and _compact_name(similar) != compact:
        return similar, True
    return raw, False


def _memory_block(memories: Optional[list[dict[str, Any]]]) -> str:
    """把最近几条人工纠错拼成 few-shot 提示段（v0.11.4 AI 记忆库）。

    只取 corrected_category 非空的条目，最多 3 条；没有记忆时返回空串，Prompt 不受影响。
    """
    lines: list[str] = []
    for item in (memories or [])[:3]:
        if not isinstance(item, dict):
            continue
        corrected = (item.get("corrected_category") or "").strip()
        if not corrected:
            continue
        raw_category = (item.get("raw_category") or "").strip()
        original = (item.get("original_text") or "").strip()
        piece = "- "
        if original:
            piece += "用户原话「%s」" % original[:60]
        if raw_category:
            piece += "，AI 曾错分成「%s」" % raw_category
        piece += "，正确分类应为「%s」" % corrected
        lines.append(piece)
    if not lines:
        return ""
    return (
        "\n\n【用户历史纠错记忆（越新越重要：遇到相同商户、相同叫法时，"
        "必须按这里的结论给分类，不要再重复同样的错误）】\n" + "\n".join(lines)
    )


def _accounts_block(
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> str:
    """把数据库里真实存在的账户/联系人拼成提示段（v0.11.5 精准度）。

    让模型优先用用户自己的账户名，别每次把「零钱」这种口语当新账户；
    但明确要求它保留用户说出的具体子账户（微信零钱、支付宝余额），
    标准化交给后端的 difflib 模糊匹配，而不是靠模型猜。
    """
    account_names = [str(item).strip() for item in (accounts or []) if str(item).strip()]
    contact_names = [str(item).strip() for item in (contacts or []) if str(item).strip()]
    if not account_names and not contact_names:
        return ""
    block = ""
    if account_names:
        block += (
            "\n\n【用户真实账户列表（记账/借贷/转账的 account 优先从这里选）】\n"
            + "、".join(account_names[:40])
            + "\n说明：用户提到具体子账户（如「微信零钱」「支付宝余额」「招行卡尾号1234」）时，"
            "原样保留用户的具体叫法，不要向上合并成大类账户；用户说的是这些账户的常见错别字或同音字"
            "（如「威信」「薇信」）时，也先原样输出，后端会统一纠正。"
        )
    if contact_names:
        block += (
            "\n\n【用户已有联系人（借贷/报销对象优先从这里选）】\n"
            + "、".join(contact_names[:40])
        )
    return block


def _previous_record_block(previous_record: Optional[dict[str, Any]]) -> str:
    """补充修改账单时把原账单完整 JSON 注入 Prompt（v0.11.5 多轮覆盖）。

    和 v0.11.4 的区别：不再只给 9 个字段的快照，而是把整条账单（含报销字段）交给模型，
    并要求它返回**完整** JSON——没提到的字段必须继承原值，后端拿这份 JSON 做全量 UPDATE。
    """
    if not previous_record:
        return ""
    snapshot = {
        key: value
        for key, value in previous_record.items()
        if key not in ("deleted_at", "created_at", "updated_at")
    }
    return (
        "\n\n【补充修改账单上下文】\n"
        "用户正在补充修改这笔已有账单，请覆盖原数据。\n"
        "原账单完整 JSON：" + json.dumps(snapshot, ensure_ascii=False) + "\n"
        "用户这次说的话是对上面这笔账单的补充或修改（补商户、改分类、改金额、"
        "改支付账户、改报销人等）。请输出修改后的最终完整结果，action 仍为 record。\n"
        "【继承规则】用户这次没提到的字段，必须从上面的原账单 JSON 里原样继承，"
        "金额、类型、分类、账户、日期、备注一个都不能丢、不能填空串；"
        "返回的 16 个字段必须齐全，后端会用这份完整 JSON 覆盖更新原账单。"
    )


def _build_messages(
    text: str,
    now: datetime,
    previous_record: Optional[dict[str, Any]] = None,
    memories: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> list[dict[str, str]]:
    weekday = "一二三四五六日"[now.weekday()]
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.format(
        today=now.strftime("%Y-%m-%d"),
        weekday="星期" + weekday,
        now=now.strftime("%Y-%m-%d %H:%M"),
        yesterday=yesterday,
    )
    system += (
        _accounts_block(accounts, contacts)
        + _memory_block(memories)
        + _previous_record_block(previous_record)
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": text.strip()},
    ]


def _strip_fence(content: str) -> str:
    """模型偶尔会包一层 ```json，这里统一剥掉，再取第一个完整对象。"""
    cleaned = content.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise AIServiceError("模型没有返回 JSON：" + cleaned[:120])
    return cleaned[start : end + 1]


def _as_amount(value: Any, field: str, minimum: float = 0.0) -> float:
    try:
        number = float(str(value).replace(",", "").replace("¥", "").strip())
    except (TypeError, ValueError):
        raise AIServiceError("%s 不是数字：%r" % (field, value))
    if number != number or number in (float("inf"), float("-inf")):
        raise AIServiceError("%s 不是有限数字：%r" % (field, value))
    if number < minimum:
        raise AIServiceError("%s 不能小于 %s：%r" % (field, minimum, value))
    return round(number, 2)


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


# 模型偶尔把布尔值写成中文/数字字符串，这里一并认，认不出的按 false 处理
_TRUE_TOKENS = {"true", "1", "yes", "y", "是", "需要", "要", "报销"}
_FALSE_TOKENS = {"false", "0", "no", "n", "否", "不需要", ""}


def _as_bool(value: Any, default: bool = False) -> bool:
    """把模型返回的 is_reimbursable 统一成 Python bool（只认明确真值，其余为 false）。"""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    return default


def _as_confidence(value: Any, default: int = 80) -> int:
    """把模型自评的 confidence 夹到 0-100 的整数；模型漏给或写坏时按 80 处理。"""
    try:
        number = int(round(float(str(value).replace("%", "").strip())))
    except (TypeError, ValueError):
        return default
    return max(0, min(100, number))


# 标准分类的兜底：先按 AI 给的分类名精确映射，再按「包含关系」取最长命中的键，
# 这样「滴滴出行-快车」「星巴克咖啡」也能落到交通/餐饮，不会在库里长出商户分类。
def _normalize_category(value: Any) -> str:
    name = _as_text(value)
    if not name:
        return ""
    if name in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[name]
    compact = re.sub(r"\s+", "", name)
    best_key = ""
    best_target = ""
    for key, target in CATEGORY_MAPPING.items():
        if key in compact and len(key) > len(best_key):
            best_key = key
            best_target = target
    return best_target or name


def _normalize_date(value: Any, now: datetime) -> str:
    raw = _as_text(value)
    if not raw:
        return now.strftime("%Y-%m-%d %H:%M")
    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(raw, fmt)
        except ValueError:
            continue
        return parsed.strftime("%Y-%m-%d %H:%M")
    # 模型给了「10月26日」这类写法时，退化成今天，宁可少一点信息也不写坏数据
    return now.strftime("%Y-%m-%d %H:%M")


def _normalize_record(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    record_type = _as_text(payload.get("type")).lower()
    if record_type not in RECORD_TYPES:
        record_type = "expense"

    amount = _as_amount(payload.get("amount"), "amount")
    if amount <= 0:
        raise AIServiceError("金额必须大于 0，模型给的是 %r" % payload.get("amount"))

    fee = _as_amount(payload.get("fee", 0), "fee")
    to_account = _as_text(payload.get("to_account"))
    if record_type == "transfer" and not to_account:
        raise AIServiceError("识别成转账，但没有转入账户")

    return {
        "amount": amount,
        "type": record_type,
        "category": _normalize_category(payload.get("category")),
        "account": _as_text(payload.get("account")),
        "to_account": to_account,
        "fee": fee,
        "date": _normalize_date(payload.get("date"), now),
        "note": _as_text(payload.get("note"))[:50],
        # 代买 / 垫付标记：只有 record 分支带这两个字段，其余分支后端不会读
        "is_reimbursable": _as_bool(payload.get("is_reimbursable")),
        "contact_name": _as_text(payload.get("contact_name"))[:50],
        "formula": "",
    }


def _normalize_debt(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    amount = _as_amount(payload.get("amount"), "amount")
    if amount <= 0:
        raise AIServiceError("借贷金额必须大于 0，模型给的是 %r" % payload.get("amount"))

    contact_name = _as_text(payload.get("contact_name"))
    if not contact_name:
        raise AIServiceError("识别成借贷，但没有提取到对方姓名")

    debt_type = DEBT_TYPE_ALIASES.get(_as_text(payload.get("type")).lower())
    if debt_type is None:
        raise AIServiceError("借贷类型只认借出 / 借入，模型给的是 %r" % payload.get("type"))

    return {
        "amount": amount,
        "contact_name": contact_name[:50],
        "type": debt_type,
        "account": _as_text(payload.get("account")),
        "date": _normalize_date(payload.get("date"), now),
        "note": _as_text(payload.get("note"))[:50],
    }


def _normalize_contact(payload: dict[str, Any]) -> dict[str, Any]:
    name = _as_text(payload.get("name")) or _as_text(payload.get("contact_name"))
    if not name:
        raise AIServiceError("识别成添加联系人，但没有提取到姓名")
    return {
        "name": name[:50],
        "identity": _as_text(payload.get("identity"))[:50],
        "phone": _as_text(payload.get("phone"))[:30],
        "wechat": _as_text(payload.get("wechat"))[:50],
    }


def _apply_fuzzy_names(
    result: dict[str, Any],
    action: str,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    """对归一化后的结果做账户/联系人模糊纠错，返回纠正明细列表。

    每个明细形如 {"field": "account", "raw": "威信零钱通", "matched": "微信", "kind": "account"}，
    前端拿 auto_corrected_msg 显示一句灰色小字，管理员在后台能看到逐字段明细。
    """
    corrections: list[dict[str, Any]] = []

    def fix(field: str, kind: str, matcher):
        raw = result.get(field)
        if not raw:
            return
        matched, changed = matcher(raw)
        if changed and matched != raw:
            result[field] = matched
            corrections.append(
                {"field": field, "raw": raw, "matched": matched, "kind": kind}
            )

    if action in ("record", "debt"):
        if action == "record":
            fix("account", "account", lambda value: _match_account(value, accounts))
            fix("to_account", "account", lambda value: _match_account(value, accounts))
        else:
            fix("account", "account", lambda value: _match_account(value, accounts))
        fix("contact_name", "contact", lambda value: _match_contact(value, contacts))
    return corrections


def _correction_message(corrections: list[dict[str, Any]]) -> str:
    """把纠正明细拼成给用户看的一句中文提示；没有纠正时返回空串。"""
    pieces: list[str] = []
    for item in corrections:
        if item["kind"] == "account":
            sentence = "识别到相似账户，已自动匹配为「%s」" % item["matched"]
        else:
            sentence = "识别到相似联系人，已自动匹配为「%s」" % item["matched"]
        if sentence not in pieces:
            pieces.append(sentence)
    return "；".join(pieces)


def _normalize_intent(
    payload: dict[str, Any],
    now: datetime,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AIServiceError("模型返回的不是 JSON 对象")

    confidence = _as_confidence(payload.get("confidence"))
    action = _as_text(payload.get("action")).lower()
    if action not in ACTIONS:
        # 模型漏了 action 或写了别的词，一律当听不懂，不猜意图
        return {
            "action": "unknown",
            "confidence": confidence,
            "auto_corrected": [],
            "auto_corrected_msg": "",
        }
    if action == "unknown":
        return {
            "action": "unknown",
            "confidence": confidence,
            "auto_corrected": [],
            "auto_corrected_msg": "",
        }

    result = _normalize_record(payload, now) if action == "record" else None
    if action == "debt":
        result = _normalize_debt(payload, now)
    elif action == "add_contact":
        result = _normalize_contact(payload)

    corrections = _apply_fuzzy_names(result, action, accounts, contacts)
    result["auto_corrected"] = corrections
    result["auto_corrected_msg"] = _correction_message(corrections)
    return {"action": action, "confidence": confidence, **result}


def _chat(
    text: str,
    now: datetime,
    previous_record: Optional[dict[str, Any]] = None,
    memories: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise AIServiceError("说一句话再解析，比如「昨天打车花了 30」")
    if len(cleaned) > 200:
        raise AIServiceError("这句话太长了，记一笔控制在 200 字以内")

    client = _client()
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": _build_messages(
            cleaned, now, previous_record, memories, accounts, contacts
        ),
        "temperature": 0.1,
        "max_tokens": 400,
    }

    try:
        completion = client.chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception as error:
        # 部分模型/网关不认 response_format，去掉再试一次；其余错误直接上抛
        if "response_format" not in str(error) and "json_object" not in str(error):
            raise AIServiceError("调用智谱接口失败：%s" % error)
        completion = client.chat.completions.create(**kwargs)

    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError):
        raise AIServiceError("智谱接口返回结构异常")

    if not content:
        raise AIServiceError("模型返回了空内容")

    try:
        payload = json.loads(_strip_fence(content))
    except json.JSONDecodeError as error:
        raise AIServiceError("模型返回的不是合法 JSON：%s" % error)

    return _normalize_intent(payload, now, accounts, contacts)


def parse_intent(
    text: str,
    now: Optional[datetime] = None,
    previous_record: Optional[dict[str, Any]] = None,
    memories: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """理解一句话的意图，返回带 action 与 confidence 的字段；失败抛 AIServiceError。

    previous_record 非空表示「补充修改账单」，会把原账单完整 JSON 注入 Prompt；
    memories 是关键词命中的历史纠错（AI 记忆库），当 few-shot 注入；
    accounts / contacts 是库里的真实名字，用于 Prompt 提示 + 返回后的 difflib 强制纠正。
    """
    return _chat(
        text, now or datetime.now(), previous_record, memories, accounts, contacts
    )


def parse_record(
    text: str,
    now: Optional[datetime] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """兼容 v0.08 的记账专用入口：只接受 record 意图，返回原来的 8 字段 + formula。"""
    result = parse_intent(text, now, accounts=accounts, contacts=contacts)
    if result["action"] != "record":
        raise AIServiceError("这句话不是记账指令，当前接口只支持记账")
    return {key: value for key, value in result.items() if key != "action"}


def _split_data_url(image: str) -> tuple[str, str]:
    """允许前端直接传 dataURL 或裸 Base64，返回 (裸 base64, mime)。"""
    data = (image or "").strip()
    mime = IMAGE_MIME_FALLBACK
    if data.startswith("data:"):
        header, _, data = data.partition(",")
        if ";" in header:
            mime = header[5:].split(";")[0].strip() or mime
    return data.strip(), mime


def _build_vision_messages(
    image_base64: str,
    mime: str,
    now: datetime,
    memories: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> list[dict[str, Any]]:
    # 提示词里本身就有大量 JSON 花括号，不能用 str.format，改用占位符替换
    prompt = VISION_PROMPT.replace(
        "__TODAY__", now.strftime("%Y-%m-%d")
    ).replace("__NOW__", now.strftime("%Y-%m-%d %H:%M"))
    prompt += _accounts_block(accounts, contacts) + _memory_block(memories)
    return [
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {
                        "url": "data:%s;base64,%s" % (mime, image_base64),
                    },
                },
                {"type": "text", "text": prompt},
            ],
        }
    ]


def parse_image(
    image_base64: str,
    mime: str = IMAGE_MIME_FALLBACK,
    now: Optional[datetime] = None,
    memories: Optional[list[dict[str, Any]]] = None,
    accounts: Optional[list[str]] = None,
    contacts: Optional[list[str]] = None,
) -> dict[str, Any]:
    """识别一张账单截图，返回与 parse_intent 同结构的字段；不是账单返回 {"action": "unknown"}。

    前端已用 Canvas 压缩过图片，这里仍然做一次大小与 Base64 合法性校验，
    避免把明显超限的图片发给视觉模型导致超时或 413。
    """
    raw_base64, detected_mime = _split_data_url(image_base64)
    mime = detected_mime or mime or IMAGE_MIME_FALLBACK
    if not raw_base64:
        raise AIServiceError("没有收到图片数据，请重新选择截图")

    try:
        image_bytes = base64.b64decode(raw_base64, validate=False)
    except Exception:
        raise AIServiceError("图片数据不是合法的 Base64，请重新选择截图")
    if not image_bytes:
        raise AIServiceError("图片内容为空，请重新选择截图")
    if len(image_bytes) > IMAGE_MAX_BYTES:
        raise AIServiceError(
            "图片太大（%.1fMB，上限 %.0fMB），请裁剪或压缩后重试"
            % (len(image_bytes) / 1024.0 / 1024.0, IMAGE_MAX_BYTES / 1024.0 / 1024.0)
        )
    if not mime.startswith("image/"):
        raise AIServiceError("只支持图片格式，收到的是 %s" % mime)

    moment = now or datetime.now()
    client = _client(VISION_TIMEOUT)
    try:
        completion = client.chat.completions.create(
            model=VISION_MODEL,
            messages=_build_vision_messages(
                raw_base64, mime, moment, memories, accounts, contacts
            ),
            temperature=0.1,
            max_tokens=500,
        )
    except Exception as error:
        raise AIServiceError("调用智谱视觉接口失败：%s" % error)

    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError):
        raise AIServiceError("智谱视觉接口返回结构异常")

    if isinstance(content, list):
        # 个别网关把 content 返回成 [{type: text, text: ...}]
        content = "".join(
            part.get("text", "") for part in content if isinstance(part, dict)
        )
    if not content:
        raise AIServiceError("视觉模型没有返回内容，请换一张更清晰的截图")

    try:
        payload = json.loads(_strip_fence(content))
    except json.JSONDecodeError as error:
        raise AIServiceError("视觉模型返回的不是合法 JSON：%s" % error)

    if not isinstance(payload, dict):
        raise AIServiceError("视觉模型返回的不是 JSON 对象")

    # 复用文本版的归一化：金额校验、日期换算、报销字段、账户模糊匹配都走同一套规则
    return _normalize_intent(payload, moment, accounts, contacts)


def generate_notification(
    version: str, hint: str = "", now: Optional[datetime] = None
) -> dict[str, Any]:
    """为指定版本起草更新公告，返回 {"title", "content"}（v0.11.3 全自动）。

    版本号由调用方从 detect_version() 读出来传进来；这里自己去 docs/dev-log.md
    取该版本的真实日志，拼进 Prompt 当唯一依据。前端不再传主题。
    content 保持纯文本（\\n 分行）；标题强制以「版本号 版本更新：」开头。
    """
    version = (version or "").strip()
    if not version:
        raise AIServiceError("读不到当前版本号，无法起草更新公告")
    hint = (hint or "").strip()

    now = now or datetime.now()
    client = _client()

    reference = dev_log_entry_for_version(version)
    if reference:
        reference_block = (
            "\n\n【该版本真实开发日志（唯一依据，不得编造日志之外的内容）】\n"
            + reference
        )
    else:
        latest = latest_dev_log_entry()
        if latest:
            reference_block = (
                "\n\n【最新真实开发日志（没有找到 " + version + " 的独立段落，先以最新一段为参考）】\n"
                + latest
            )
        else:
            reference_block = (
                "\n\n【真实开发日志】\n（没有读到开发日志：请只做最保守的概括，"
                "不要编造具体功能与「修复已知问题」类空话）"
            )

    ask = (
        "\n\n请基于真实日志，为版本 "
        + version
        + " 撰写更新公告。标题必须严格以“"
        + version
        + " 版本更新：”开头，正文纯文本、无表情、平实客观、分点列出。"
    )
    if hint:
        ask += "\n\n补充重点（可选，只能写日志里已有的事实）：" + hint

    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": [
            {
                "role": "user",
                "content": NOTIFICATION_PROMPT
                + reference_block
                + ask
                + "\n\n现在日期："
                + now.strftime("%Y-%m-%d"),
            }
        ],
        "temperature": 0.6,
        "max_tokens": 900,
    }

    try:
        completion = client.chat.completions.create(
            **kwargs, response_format={"type": "json_object"}
        )
    except Exception as error:
        if "response_format" not in str(error) and "json_object" not in str(error):
            raise AIServiceError("调用智谱接口失败：%s" % error)
        completion = client.chat.completions.create(**kwargs)

    try:
        content = completion.choices[0].message.content
    except (AttributeError, IndexError):
        raise AIServiceError("智谱接口返回结构异常")
    if not content:
        raise AIServiceError("模型返回了空内容")

    try:
        payload = json.loads(_strip_fence(content))
    except json.JSONDecodeError as error:
        raise AIServiceError("模型返回的不是合法 JSON：%s" % error)
    if not isinstance(payload, dict):
        raise AIServiceError("模型返回的不是 JSON 对象")

    title = _as_text(payload.get("title"))
    body = _as_text(payload.get("content"))

    # 标题规范：强制「版本号 版本更新：」开头，模型自己加的版本号/方括号都剥掉
    prefix = version + " 版本更新："
    rest = title.strip()
    rest = re.sub(
        r"^[\[\(（【]?" + re.escape(version) + r"[\]\)）】]?\s*版本更新[：:]\s*",
        "",
        rest,
    )
    rest = re.sub(r"^版本更新[：:]\s*", "", rest)
    rest = re.sub(r"^[\[\(（【]?" + re.escape(version) + r"[\]\)）】]\s*", "", rest)
    rest = rest.strip(" ：:")
    title = (prefix + rest).strip()
    if len(title) > 80:
        title = title[:80]
    if len(title) <= len(prefix):
        title = prefix + "本次更新说明"

    # 纯文本规范：去掉 HTML 标签与 Markdown 强调符号，压掉多余空行
    body = re.sub(r"<[^>]+>", "", body)
    body = body.replace("**", "").replace("__", "").replace("#", "").replace("`", "")
    lines = [line.strip() for line in body.splitlines()]
    lines = [line for line in lines if line]
    body = "\n".join(lines)
    if not body:
        raise AIServiceError("模型没有写出正文，请稍后重试")
    if len(body) > 1200:
        body = body[:1200]

    return {"title": title, "content": body}
