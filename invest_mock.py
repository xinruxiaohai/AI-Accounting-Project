# -*- coding: utf-8 -*-
"""投资 Mock 行情模块（v0.13.3-DEV）。

定位：
- **只做本地常量匹配**，不发任何网络请求、不引第三方包（设计 D11 / §1.2 第 1 条）。
- 返回体结构与未来的真实行情模块**完全一致**，将来接行情时只需替换本文件的
  `search_securities()` 实现，调用方（`app.py` 的 `/api/invest/search`、
  `ai_service` 的 ticker 补全）一行都不用改。
- 不 import Flask / database，保证纯函数、可单测。

字段口径：
- `price` 恒为 **Mock 参考价**（> 0），`source` 恒为 `"mock"`。
- 注意：Mock 价**不会**写进 `holdings.current_price`（该列 0 表示未接行情，见设计 D8），
  它只用于「新建持仓弹窗里选中候选后回填单价」与 AI 补 ticker / name。
"""

import difflib

# 20 条常量：基金 / 股票 / ETF / 债券，代码与名称取真实存在的标的，便于手工测试。
# price 是**参考价**，不是实时净值；接真实行情后整段替换为接口返回值。
MOCK_SECURITIES = (
    # ---- 场外基金 ----
    {"ticker": "005827", "name": "易方达蓝筹精选", "asset_type": "fund", "price": 2.1350},
    {"ticker": "161725", "name": "招商中证白酒指数", "asset_type": "fund", "price": 0.9842},
    {"ticker": "110022", "name": "易方达消费行业股票", "asset_type": "fund", "price": 3.5620},
    {"ticker": "163402", "name": "兴全趋势投资混合", "asset_type": "fund", "price": 0.6713},
    {"ticker": "000961", "name": "天弘沪深300ETF联接A", "asset_type": "fund", "price": 1.8456},
    {"ticker": "270042", "name": "广发纳斯达克100指数", "asset_type": "fund", "price": 5.2130},
    {"ticker": "040046", "name": "华安纯债债券A", "asset_type": "bond", "price": 1.1284},
    {"ticker": "000216", "name": "华安黄金易ETF联接A", "asset_type": "fund", "price": 1.9475},
    # ---- 场内 ETF ----
    {"ticker": "510300", "name": "沪深300ETF", "asset_type": "fund", "price": 3.8920},
    {"ticker": "510500", "name": "中证500ETF", "asset_type": "fund", "price": 5.6740},
    {"ticker": "588000", "name": "科创50ETF", "asset_type": "fund", "price": 0.8925},
    {"ticker": "512880", "name": "证券ETF", "asset_type": "fund", "price": 0.9312},
    {"ticker": "515790", "name": "光伏ETF", "asset_type": "fund", "price": 0.7743},
    {"ticker": "159941", "name": "纳指ETF", "asset_type": "fund", "price": 1.6328},
    {"ticker": "518880", "name": "黄金ETF", "asset_type": "fund", "price": 6.2415},
    # ---- 股票 ----
    {"ticker": "600519", "name": "贵州茅台", "asset_type": "stock", "price": 1523.00},
    {"ticker": "000858", "name": "五粮液", "asset_type": "stock", "price": 138.66},
    {"ticker": "601318", "name": "中国平安", "asset_type": "stock", "price": 47.32},
    {"ticker": "300750", "name": "宁德时代", "asset_type": "stock", "price": 198.45},
    {"ticker": "00700", "name": "腾讯控股", "asset_type": "stock", "price": 372.60},
)

# 搜索返回条数上限（前端候选下拉最多展示 8 条，这里留一点余量）
MAX_SEARCH_RESULTS = 10

# difflib 兜底的相似度下限：低于它就认为「没命中」，避免搜什么都返回一堆
FUZZY_CUTOFF = 0.5


def _clean(keyword):
    """把搜索词规整成小写、去空格的字符串；None / 非字符串一律当空串。"""
    if not isinstance(keyword, str):
        return ""
    return keyword.strip().lower()


def _hit(item):
    """把常量条目拷贝成对外返回体（含 source 标记），避免调用方改到模块常量。"""
    return {
        "ticker": item["ticker"],
        "name": item["name"],
        "asset_type": item["asset_type"],
        "price": round(float(item["price"]), 4),
        "source": "mock",
    }


def search_securities(keyword, limit=MAX_SEARCH_RESULTS):
    """按关键字搜标的，返回 [{ticker, name, asset_type, price, source}]。

    匹配优先级（设计 §3.2 T01 第 8 条）：
    1. 代码**精确**命中；
    2. 代码**前缀**命中；
    3. 名称**包含**关键字；
    4. `difflib` 模糊兜底（相似度 ≥ 0.5）。

    未命中返回空列表（**不是 None**），让路由层统一回 `{total: 0, items: []}`。
    """
    key = _clean(keyword)
    if not key:
        return []
    try:
        max_items = int(limit)
    except (TypeError, ValueError):
        max_items = MAX_SEARCH_RESULTS
    if max_items <= 0:
        max_items = MAX_SEARCH_RESULTS

    exact = []
    prefix = []
    contains = []
    for item in MOCK_SECURITIES:
        ticker_lower = item["ticker"].lower()
        name_lower = item["name"].lower()
        if ticker_lower == key:
            exact.append(item)
        elif ticker_lower.startswith(key):
            prefix.append(item)
        elif key in name_lower:
            contains.append(item)

    ordered = exact + prefix + contains
    if not ordered:
        # 兜底：名字拼写接近（例如「易方达蓝筹精选」输成「易方达篮筹」）
        names = [item["name"] for item in MOCK_SECURITIES]
        close = difflib.get_close_matches(key, names, n=max_items, cutoff=FUZZY_CUTOFF)
        if not close:
            # 也允许拿代码做模糊匹配（5 位数代码输错一位）
            tickers = [item["ticker"] for item in MOCK_SECURITIES]
            close_tickers = difflib.get_close_matches(
                key, tickers, n=max_items, cutoff=FUZZY_CUTOFF
            )
            close = close_tickers
        name_to_item = {item["name"]: item for item in MOCK_SECURITIES}
        ticker_to_item = {item["ticker"]: item for item in MOCK_SECURITIES}
        ordered = [
            name_to_item.get(name) or ticker_to_item.get(name)
            for name in close
        ]
        ordered = [item for item in ordered if item is not None]

    # 去重保序：同一条只可能出现一次
    seen = set()
    result = []
    for item in ordered:
        if item["ticker"] in seen:
            continue
        seen.add(item["ticker"])
        result.append(_hit(item))
        if len(result) >= max_items:
            break
    return result


def lucky_one(keyword):
    """取第一条命中，没有就返回 None。AI 补 ticker / name 时用。"""
    items = search_securities(keyword, limit=1)
    return items[0] if items else None


def get_by_ticker(ticker):
    """按代码精确取一条，取不到返回 None（AI 归一化补名称时用）。"""
    key = _clean(ticker)
    if not key:
        return None
    for item in MOCK_SECURITIES:
        if item["ticker"].lower() == key:
            return _hit(item)
    return None
