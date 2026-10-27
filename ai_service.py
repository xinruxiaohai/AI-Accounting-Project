"""AI 记账管家 · 智谱 GLM 接入层（v0.07 Step 1）

对外只暴露一个入口：

    parse_record("昨天打车花了30")
    -> {"amount": 30.0, "type": "expense", "category": "交通", ...}

设计原则：
1. 模型只负责「把一句话拆成字段」，不碰数据库、不算余额；
2. 返回值必须先过本地校验（金额 > 0、类型白名单、日期格式），
   任何一项不合格都抛 AIServiceError，绝不把脏数据写进账本；
3. 密钥只从环境变量 / .env 读取，不落日志、不进代码。
"""

from __future__ import annotations

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
BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"
API_KEY_ENV = "ZHIPU_API_KEY"
REQUEST_TIMEOUT = 20.0

RECORD_TYPES = ("expense", "income", "transfer")

DATE_FORMATS = (
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
)

SYSTEM_PROMPT = """你是一个中文记账助手，只做一件事：把用户的一句自然语言账单，抽取成固定字段的 JSON。

【输出要求】
- 只输出一个 JSON 对象，不要 Markdown 代码块、不要解释、不要多余文字。
- 字段必须且只能是下面这 8 个，键名不得改动、不得增删：
  amount       数字，金额，必须大于 0，不带货币符号
  type         字符串，只能是 "expense"（支出）、"income"（收入）、"transfer"（账户间转账）
  category     字符串，支出/收入的分类，如 餐饮、交通、购物、工资、奖金；转账时填空字符串 ""
  account      字符串，付款账户或收款账户；用户没提就填空字符串 ""
  to_account   字符串，仅转账时填写转入账户，其余情况填空字符串 ""
  fee          数字，仅转账时的手续费，其余情况填 0
  date         字符串，格式固定为 "YYYY-MM-DD HH:MM"，24 小时制
  note         字符串，一句话摘要，保留原文关键信息，不超过 30 个字

【分类规则】
- 打车、地铁、公交、高铁、机票 → 交通
- 吃饭、外卖、奶茶、咖啡、聚餐 → 餐饮
- 买菜、日用品、超市 → 购物
- 房租、水电、物业、话费 → 居住
- 工资、奖金、报销、红包收入 → 对应收入类分类
- 判断不了分类时填 "其他"

【时间规则】
- 今天是 {today}（{weekday}），当前时间 {now}。
- “昨天”“前天”“上周五”等相对时间，必须换算成具体日期。
- 用户没提时间，date 用当前时间 {now}。
- 只说了日期没说时刻，时刻填 00:00。

【类型规则】
- “花了/买了/付了/支出” → expense
- “收到/发了/工资/奖金/退款” → income
- “从 A 转到 B / 转到 / 充值到” → transfer，account 是转出方，to_account 是转入方
- 一句话里出现多个金额时，取最主要的那笔；手续费单独填 fee，不并入 amount

【示例】
用户：昨天打车花了30
输出：{{"amount": 30, "type": "expense", "category": "交通", "account": "", "to_account": "", "fee": 0, "date": "{yesterday} 00:00", "note": "打车"}}

用户：工资到账 8000
输出：{{"amount": 8000, "type": "income", "category": "工资", "account": "", "to_account": "", "fee": 0, "date": "{now}", "note": "工资到账"}}

用户：从微信转 500 到支付宝，手续费 1 块
输出：{{"amount": 500, "type": "transfer", "category": "", "account": "微信", "to_account": "支付宝", "fee": 1, "date": "{now}", "note": "微信转支付宝"}}
"""


class AIServiceError(Exception):
    """AI 解析失败：密钥缺失、网络错误、模型输出不是合法 JSON，都走这里。"""


def is_configured() -> bool:
    """给路由/页面判断「现在能不能用 AI」，不触发任何网络请求。"""
    return bool(os.getenv(API_KEY_ENV, "").strip())


def _client() -> OpenAI:
    key = os.getenv(API_KEY_ENV, "").strip()
    if not key:
        raise AIServiceError(
            "未配置 ZHIPU_API_KEY：请在项目根目录的 .env 里写入 ZHIPU_API_KEY=你的密钥，"
            "保存后重启 Flask 再试"
        )
    return OpenAI(api_key=key, base_url=BASE_URL, timeout=REQUEST_TIMEOUT)


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


def _normalize(payload: dict[str, Any], now: datetime) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AIServiceError("模型返回的不是 JSON 对象")

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
        "formula": "",
    }


def parse_record(text: str, now: Optional[datetime] = None) -> dict[str, Any]:
    """把一句自然语言账单解析成可直接写库的字段。

    失败一律抛 AIServiceError（带中文原因），调用方转成 400/502 即可。
    """
    cleaned = (text or "").strip()
    if not cleaned:
        raise AIServiceError("说一句话再解析，比如「昨天打车花了 30」")
    if len(cleaned) > 200:
        raise AIServiceError("这句话太长了，记一笔控制在 200 字以内")

    moment = now or datetime.now()
    client = _client()

    kwargs: dict[str, Any] = {
        "model": MODEL,
        "messages": _build_messages(cleaned, moment),
        "temperature": 0.1,
        "max_tokens": 300,
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

    return _normalize(payload, moment)
