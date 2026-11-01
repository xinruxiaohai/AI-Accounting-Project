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

资产类型（v0.13.3 补第 6 类 `gold`）：
`fund` 基金 / `stock` 股票 / `bond` 债券 / `gold` 黄金 / `cash` 现金 / `other` 其它。
黄金单列是因为它的计价单位（元/克、元/份）与基金份额差异太大，
混在 `fund` 里会让看板的「类型分布」失真。
"""

import difflib

# 50 条常量：基金 / 股票 / ETF / 债券 / 黄金，代码与名称取真实存在的标的，便于手工测试。
# price 是**参考价**，不是实时净值；接真实行情后整段替换为接口返回值。
MOCK_SECURITIES = (
    # ---- 场外基金 ----
    {"ticker": "005827", "name": "易方达蓝筹精选混合", "asset_type": "fund", "price": 2.1350},
    {"ticker": "161725", "name": "招商中证白酒指数A", "asset_type": "fund", "price": 0.9842},
    {"ticker": "110022", "name": "易方达消费行业股票", "asset_type": "fund", "price": 3.5620},
    {"ticker": "163402", "name": "兴全趋势投资混合", "asset_type": "fund", "price": 0.6713},
    {"ticker": "000961", "name": "天弘沪深300ETF联接A", "asset_type": "fund", "price": 1.8456},
    {"ticker": "270042", "name": "广发纳斯达克100指数A", "asset_type": "fund", "price": 5.2130},
    {"ticker": "040046", "name": "华安纯债债券A", "asset_type": "bond", "price": 1.1284},
    {"ticker": "003376", "name": "广发中债7-10年国开债A", "asset_type": "bond", "price": 1.2345},
    {"ticker": "000001", "name": "华夏成长混合", "asset_type": "fund", "price": 1.1050},
    {"ticker": "519066", "name": "汇添富蓝筹稳健混合A", "asset_type": "fund", "price": 1.8420},
    {"ticker": "001102", "name": "前海开源国家比较优势混合", "asset_type": "fund", "price": 3.2140},
    {"ticker": "002190", "name": "农银新能源主题混合A", "asset_type": "fund", "price": 4.5120},
    {"ticker": "005911", "name": "广发双擎升级混合A", "asset_type": "fund", "price": 2.8640},
    {"ticker": "260108", "name": "景顺长城新兴成长混合A", "asset_type": "fund", "price": 2.4130},
    {"ticker": "519005", "name": "海富通股票混合", "asset_type": "fund", "price": 0.9340},
    {"ticker": "003096", "name": "中欧医疗健康混合A", "asset_type": "fund", "price": 2.2760},
    {"ticker": "001593", "name": "天弘创业板ETF联接A", "asset_type": "fund", "price": 0.8120},
    {"ticker": "000248", "name": "汇添富中证主要消费ETF联接A", "asset_type": "fund", "price": 2.9450},
    {"ticker": "001186", "name": "富国文体健康股票A", "asset_type": "fund", "price": 1.3890},
    {"ticker": "110011", "name": "易方达优质精选混合", "asset_type": "fund", "price": 6.1520},
    {"ticker": "040025", "name": "华安科技动力混合", "asset_type": "fund", "price": 3.1250},
    {"ticker": "162411", "name": "华宝标普油气上游股票", "asset_type": "fund", "price": 0.6420},
    {"ticker": "161226", "name": "国投瑞银白银期货LOF", "asset_type": "fund", "price": 1.0140},
    # ---- 场内 ETF ----
    {"ticker": "510300", "name": "沪深300ETF", "asset_type": "fund", "price": 3.8920},
    {"ticker": "510500", "name": "中证500ETF", "asset_type": "fund", "price": 5.6740},
    {"ticker": "588000", "name": "科创50ETF", "asset_type": "fund", "price": 0.8925},
    {"ticker": "512880", "name": "证券ETF", "asset_type": "fund", "price": 0.9312},
    {"ticker": "512000", "name": "券商ETF", "asset_type": "fund", "price": 1.0520},
    {"ticker": "515790", "name": "光伏ETF", "asset_type": "fund", "price": 0.7743},
    {"ticker": "159941", "name": "纳指ETF", "asset_type": "fund", "price": 1.6328},
    {"ticker": "513100", "name": "纳指ETF易方达", "asset_type": "fund", "price": 2.1180},
    {"ticker": "159915", "name": "创业板ETF", "asset_type": "fund", "price": 1.8760},
    {"ticker": "510880", "name": "红利ETF", "asset_type": "fund", "price": 3.2410},
    {"ticker": "512690", "name": "酒ETF", "asset_type": "fund", "price": 0.7830},
    {"ticker": "516160", "name": "新能源ETF", "asset_type": "fund", "price": 0.6540},
    # ---- 黄金（独立类型：计价单位与基金份额不同）----
    {"ticker": "518880", "name": "黄金ETF", "asset_type": "gold", "price": 6.2415},
    {"ticker": "000216", "name": "华安黄金易ETF联接A", "asset_type": "gold", "price": 1.9475},
    {"ticker": "002610", "name": "博时黄金ETF联接A", "asset_type": "gold", "price": 1.5860},
    {"ticker": "000307", "name": "易方达黄金ETF联接A", "asset_type": "gold", "price": 2.1040},
    # ---- 股票 ----
    {"ticker": "600519", "name": "贵州茅台", "asset_type": "stock", "price": 1523.00},
    {"ticker": "000858", "name": "五粮液", "asset_type": "stock", "price": 138.66},
    {"ticker": "601318", "name": "中国平安", "asset_type": "stock", "price": 47.32},
    {"ticker": "300750", "name": "宁德时代", "asset_type": "stock", "price": 198.45},
    {"ticker": "601899", "name": "紫金矿业", "asset_type": "stock", "price": 17.86},
    {"ticker": "600036", "name": "招商银行", "asset_type": "stock", "price": 38.42},
    {"ticker": "000651", "name": "格力电器", "asset_type": "stock", "price": 39.85},
    {"ticker": "600030", "name": "中信证券", "asset_type": "stock", "price": 28.64},
    {"ticker": "002594", "name": "比亚迪", "asset_type": "stock", "price": 268.30},
    {"ticker": "688981", "name": "中芯国际", "asset_type": "stock", "price": 88.45},
    {"ticker": "300059", "name": "东方财富", "asset_type": "stock", "price": 20.13},
    {"ticker": "601012", "name": "隆基绿能", "asset_type": "stock", "price": 19.72},
    {"ticker": "000333", "name": "美的集团", "asset_type": "stock", "price": 72.15},
    {"ticker": "600900", "name": "长江电力", "asset_type": "stock", "price": 28.05},
    {"ticker": "00700", "name": "腾讯控股", "asset_type": "stock", "price": 372.60},
    {"ticker": "09988", "name": "阿里巴巴-W", "asset_type": "stock", "price": 118.50},
    {"ticker": "03690", "name": "美团-W", "asset_type": "stock", "price": 168.20},
)

# 搜索返回条数上限（前端候选下拉最多展示 8 条，这里留一点余量）
MAX_SEARCH_RESULTS = 10

# difflib 兜底的相似度下限：低于它就认为「没命中」，避免搜什么都返回一堆。
# v0.13.3 从 0.5 提到 0.62 —— 0.5 会把「006679」错配到「00700」「600519」，
# 用户看到的就是「输入一个不存在的代码，弹出一堆无关的股票」。
FUZZY_CUTOFF = 0.62

# 名称模糊兜底的最短输入长度：两个字的词做 difflib 只会乱配
FUZZY_MIN_LEN = 3


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


def _within_one_edit(left, right):
    """判断两个**等长**字符串是否只差一个字符（含替换 / 少一位 / 多一位的等长近似）。

    只用于「代码输错一位」的兜底。6 位数字串之间做 difflib 的相似度是 0.5~0.67，
    跟名称短词的相似度完全不在一个量纲上，混在一起排序必然乱弹，
    所以代码的模糊匹配单独用「编辑距离 ≤ 1」这条硬规则，不进 difflib。
    """
    if not left or not right or len(left) != len(right):
        return False
    diff = 0
    for i in range(len(left)):
        if left[i] != right[i]:
            diff += 1
            if diff > 1:
                return False
    return diff == 1


def search_securities(keyword, limit=MAX_SEARCH_RESULTS):
    """按关键字搜标的，返回 [{ticker, name, asset_type, price, source}]。

    匹配优先级（v0.13.3 重写，修「006679 弹出腾讯/茅台」的乱弹 bug）：
    1. **纯数字 / 代码形态**（字母数字混排如 09988、00700 也算）：
       只做 代码精确 → 代码前缀 → 代码包含 → 等长且编辑距离 1 的代码。
       **绝不**用 difflib 去和名称比相似度。
    2. **中文 / 文字关键字**：名称精确 → 名称前缀 → 名称包含 → 代码包含
       → difflib 名称模糊（cutoff 0.62，且长度差 ≤ 2）。
    3. 都没有 → 返回空列表（**不是 None**），前端显示「没有匹配的标的」。

    未命中返回空列表，让路由层统一回 `{total: 0, items: []}`。
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

    # ---- 分支 1：代码形态（纯数字 5~6 位，或字母数字混排且不含中文）----
    looks_like_code = key.isdigit() or (key.isascii() and key.isalnum())

    exact = []
    prefix = []
    contains = []
    near_code = []
    for item in MOCK_SECURITIES:
        ticker_lower = item["ticker"].lower()
        name_lower = item["name"].lower()
        if ticker_lower == key:
            exact.append(item)
            continue
        if ticker_lower.startswith(key):
            prefix.append(item)
            continue
        if key in ticker_lower:
            contains.append(item)
            continue
        if looks_like_code:
            # 代码就差一位（例如 510301 想打 510300）才允许兜底
            if _within_one_edit(key, ticker_lower):
                near_code.append(item)
            continue
        if key in name_lower:
            contains.append(item)

    if looks_like_code:
        ordered = exact + prefix + contains + near_code
    else:
        ordered = []
        name_exact = [item for item in MOCK_SECURITIES if item["name"].lower() == key]
        name_prefix = [
            item
            for item in MOCK_SECURITIES
            if item["name"].lower().startswith(key) and item not in name_exact
        ]
        ordered = name_exact + name_prefix + contains

    if not ordered and not looks_like_code and len(key) >= FUZZY_MIN_LEN:
        # 名称拼写轻微出错（「易方达篮筹精选」），长度差超过 2 的直接排除，
        # 否则「茅台」会跟「美的集团」凑出 0.62 的相似度
        candidates = [
            item["name"]
            for item in MOCK_SECURITIES
            if abs(len(item["name"]) - len(key)) <= 2
        ]
        close = difflib.get_close_matches(key, candidates, n=max_items, cutoff=FUZZY_CUTOFF)
        name_to_item = {item["name"]: item for item in MOCK_SECURITIES}
        ordered = [name_to_item[name] for name in close if name in name_to_item]

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