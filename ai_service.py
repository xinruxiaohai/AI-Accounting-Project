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
- 字段键名固定为下面 14 个，不得增删、不得改名；每个意图只填自己需要的字段，其余留空字符串 ""、0 或 false：
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
输出：{{"action": "record", "amount": 30, "type": "expense", "category": "交通", "account": "", "to_account": "", "fee": 0, "date": "{yesterday} 00:00", "note": "打车", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：工资到账 8000
输出：{{"action": "record", "amount": 8000, "type": "income", "category": "工资", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "工资到账", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：帮同事小明代买咖啡30
输出：{{"action": "record", "amount": 30, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "帮小明代买咖啡", "is_reimbursable": true, "contact_name": "小明", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：给公司垫付打车50，记得报销
输出：{{"action": "record", "amount": 50, "type": "expense", "category": "交通", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "垫付打车报销", "is_reimbursable": true, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：测试乙41215 买了奶茶20元
输出：{{"action": "record", "amount": 20, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "买奶茶", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：借给小王20元
输出：{{"action": "debt", "amount": 20, "type": "lend", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "借给小王20元", "is_reimbursable": false, "contact_name": "小王", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：向小李借了100
输出：{{"action": "debt", "amount": 100, "type": "borrow", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "向小李借100", "is_reimbursable": false, "contact_name": "小李", "identity": "", "phone": "", "wechat": "", "name": ""}}

用户：添加小王，他是亲戚，电话13800000000
输出：{{"action": "add_contact", "amount": 0, "type": "", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "添加联系人小王", "is_reimbursable": false, "contact_name": "", "identity": "亲戚", "phone": "13800000000", "wechat": "", "name": "小王"}}

用户：今天天气不错
输出：{{"action": "unknown", "amount": 0, "type": "", "category": "", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}}
"""


VISION_PROMPT = """你是中文记账助手的「截图识别」模块。用户会给你一张手机截图，可能是微信/支付宝的支付成功页、账单列表、超市小票、银行短信或聊天转账记录。

【任务】判断这张图是不是一笔可以记账的交易（消费、收入、转账、借贷），是就抽取字段，只输出一个 JSON 对象；不是账单（聊天闲谈、表情包、风景照、无关页面）就输出 {"action": "unknown"}。

【输出要求】
- 不要 Markdown 代码块、不要解释、不要多余文字。
- 字段键名固定为下面 14 个，不得增删、不得改名；不适用的填空字符串 ""、0 或 false：
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

【金额识别强约束】
- 只取「实付/支付/消费/收款/转账」那笔交易金额，例如「-30.00」「实付 ¥30.00」「收款 100.00」。
- 绝不把余额、优惠券面额、订单号、手机号、时间（12:31）、日期（2026-10-28）里的数字当金额。
- 图里有多个金额时，取本次实际交易的那一笔；手续费单独放进 fee。
- 看不清或没有明确金额 → 输出 {"action": "unknown"}，绝不猜。

【类型与分类】
- 「支付/付款/消费/买了」→ expense；「收款/退款/红包/工资到账」→ income（金额填正数）；「转给/转到」→ transfer。
- 分类按商户判断：麦当劳/奶茶/咖啡/外卖/餐厅 → 餐饮；滴滴/地铁/公交/加油 → 交通；超市/淘宝/京东/日用品 → 购物；房租/水电/话费 → 居住；判断不了填 "其他"。
- account：截图里出现的付款方式（零钱、余额、招商银行储蓄卡、花呗）能映射成账户名就填，判断不了填空字符串。

【时间】
- 截图里有交易时间就用它；只有日期填 00:00；完全没有时间用当前时间 __NOW__（今天 __TODAY__）。

【示例】
截图内容：支付成功 / 麦当劳 / 实付 ¥30.00 / 2026-10-28 12:31
输出：{"action": "record", "amount": 30, "type": "expense", "category": "餐饮", "account": "", "to_account": "", "fee": 0, "date": "2026-10-28 12:31", "note": "麦当劳 午餐", "is_reimbursable": false, "contact_name": "", "identity": "", "phone": "", "wechat": "", "name": ""}

截图内容：一张猫的照片
输出：{"action": "unknown"}
"""


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


def _build_messages(text: str, now: datetime) -> list[dict[str, str]]:
    weekday = "一二三四五六日"[now.weekday()]
    yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    system = SYSTEM_PROMPT.format(
        today=now.strftime("%Y-%m-%d"),
        weekday="星期" + weekday,
        now=now.strftime("%Y-%m-%d %H:%M"),
        yesterday=yesterday,
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
        "category": _as_text(payload.get("category")),
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


def _normalize_intent(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AIServiceError("模型返回的不是 JSON 对象")

    action = _as_text(payload.get("action")).lower()
    if action not in ACTIONS:
        # 模型漏了 action 或写了别的词，一律当听不懂，不猜意图
        return {"action": "unknown"}
    if action == "unknown":
        return {"action": "unknown"}

    result = _normalize_record(payload, now) if action == "record" else None
    if action == "debt":
        result = _normalize_debt(payload, now)
    elif action == "add_contact":
        result = _normalize_contact(payload)
    return {"action": action, **result}


def _chat(text: str, now: datetime) -> dict[str, Any]:
    cleaned = (text or "").strip()
    if not cleaned:
        raise AIServiceError("说一句话再解析，比如「昨天打车花了 30」")
    if len(cleaned) > 200:
        raise AIServiceError("这句话太长了，记一笔控制在 200 字以内")

    client = _client()
    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": _build_messages(cleaned, now),
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

    return _normalize_intent(payload, now)


def parse_intent(text: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """理解一句话的意图，返回带 action 的字段；失败抛 AIServiceError。"""
    return _chat(text, now or datetime.now())


def parse_record(text: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """兼容 v0.08 的记账专用入口：只接受 record 意图，返回原来的 8 字段 + formula。"""
    result = parse_intent(text, now)
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
    image_base64: str, mime: str, now: datetime
) -> list[dict[str, Any]]:
    # 提示词里本身就有大量 JSON 花括号，不能用 str.format，改用占位符替换
    prompt = VISION_PROMPT.replace(
        "__TODAY__", now.strftime("%Y-%m-%d")
    ).replace("__NOW__", now.strftime("%Y-%m-%d %H:%M"))
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
            messages=_build_vision_messages(raw_base64, mime, moment),
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

    # 复用文本版的归一化：金额校验、日期换算、报销字段都走同一套规则
    return _normalize_intent(payload, moment)
