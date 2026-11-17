# -*- coding: utf-8 -*-
"""v0.13.4-DEV · 东方财富标的全市场搜索代理模块。

职责：
- 只做「代理请求东方财富免鉴权 search-api」这一件事，返回体结构与 invest_mock 完全一致
  （``[{ticker, name, asset_type, price, source}]``），调用方（app.py 的 /api/invest/search、
  ai_service 的 ticker 补全）无需区分来源。
- 红线：对外部接口的请求**强制至少 1 秒最小请求间隔**（进程级互斥锁 + 时间戳），
  防止高频抓取触发东财风控、IP 被封。
- 网络失败 / 超时 / 断网一律向上抛异常，由上层（app.py 的 /api/invest/search）
  决定降级回退到 invest_mock 本地字典。

字段映射（东财 suggest 原始字段 → 本模块返回体）：
- ``Code`` → ticker；``Name`` → name；
- ``Classify`` / ``SecurityTypeName`` / ``Name`` → asset_type
  （股票 stock / 基金 fund / 债券 bond / 黄金 gold / 其它 other）；
- suggest 接口不返回实时价，price 恒为 0（与 invest_mock 的「参考价」不同，见设计 D8）。
"""

import datetime
import json
import os
import re
import threading
import time
import urllib.parse
import urllib.request

import invest_mock

# 东财免费、免鉴权的搜索建议接口（token 为公开常量）
# 允许环境变量覆盖：换域名时不用改代码；自测模拟「断网」时指向不可达地址即可
EASTMONEY_SEARCH_URL = (
    (os.getenv("EASTMONEY_SEARCH_URL") or "").strip()
    or "https://searchapi.eastmoney.com/api/suggest/get"
)
EASTMONEY_SEARCH_TOKEN = "D43BF722C8E33BDC906FB84D85E326E8"

# 红线：两次外部请求之间的最小间隔（秒）。宁可慢，也不触发东财风控。
EASTMONEY_MIN_INTERVAL = 1.0
# 外部请求超时（秒）。超过即判定网络断开，走本地兜底。
EASTMONEY_TIMEOUT = 4.0
# 单次请求结果上限（前端候选最多 8 条，这里多留余量）
EASTMONEY_MAX_RESULTS = 10

# 进程级「上一次请求东财」的时间戳 + 互斥锁（多线程安全）
_last_request_at = 0.0
_request_lock = threading.Lock()

# 明确不可作为「持仓标的」的 Classify（指数 / 板块等）
_NON_INVESTABLE_CLASSIFY = {"index", "bk", "zs", "block"}


def _classify_to_asset_type(classify, name):
    """把东财的 Classify 映射成本项目的 asset_type（fund/stock/bond/gold/cash/other）。

    黄金优先判断：黄金 ETF 在东财里 Classify 是 ``Fund``，但本项目把黄金单列
    （计价单位元/克与基金份额差异大，见 invest_mock 模块头注释），须按名称单独识别。
    """
    classify = (classify or "").strip().lower()
    name = (name or "").strip()
    if "黄金" in name:
        return "gold"
    if "stock" in classify or classify == "hk":  # AStock/BStock/HStock/HKSTOCK/港股 HK
        return "stock"
    if "fund" in classify:  # Fund（场内基金/ETF）/ OTCFUND（场外基金）
        return "fund"
    if "bond" in classify or "债" in name:
        return "bond"
    return "other"


def _is_investable(item):
    """过滤掉指数 / 期货 / 期权 / 板块等不能作为「持仓标的」的结果。"""
    classify = (item.get("Classify") or "").strip().lower()
    sec_type_name = (item.get("SecurityTypeName") or "").strip()
    if classify in _NON_INVESTABLE_CLASSIFY:
        return False
    if any(tag in sec_type_name for tag in ("期货", "期权", "指数", "板块")):
        return False
    return True


def _enforce_rate_limit():
    """进程级限流：保证距上次请求东财至少 1 秒（红线要求）。"""
    global _last_request_at
    with _request_lock:
        wait = EASTMONEY_MIN_INTERVAL - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        _last_request_at = time.time()


def search_eastmoney(keyword, limit=EASTMONEY_MAX_RESULTS):
    """请求东财 suggest 接口，返回 ``[{ticker, name, asset_type, price, source}]``。

    网络错误 / 超时 / 非 200 / JSON 解析失败一律**抛异常**，由上层降级。
    命中为空返回 ``[]``（不是 None）——东财是权威全市场数据源，空 = 真没有。
    """
    if not keyword or not isinstance(keyword, str) or not keyword.strip():
        return []
    try:
        max_items = int(limit)
    except (TypeError, ValueError):
        max_items = EASTMONEY_MAX_RESULTS
    if max_items <= 0:
        max_items = EASTMONEY_MAX_RESULTS

    # count 多取一点，过滤掉指数/期货后再截断，保证返回数量够用
    query = urllib.parse.urlencode(
        {
            "input": keyword.strip(),
            "type": "14",
            "token": EASTMONEY_SEARCH_TOKEN,
            "count": str(min(max_items * 3, 30)),
        }
    )
    url = EASTMONEY_SEARCH_URL + "?" + query

    _enforce_rate_limit()

    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=EASTMONEY_TIMEOUT) as resp:
        payload = json.loads(resp.read().decode("utf-8"))

    table = payload.get("QuotationCodeTable") or {}
    data = table.get("Data") or []
    if not isinstance(data, list):
        return []

    result = []
    for item in data:
        if not isinstance(item, dict) or not _is_investable(item):
            continue
        ticker = str(item.get("Code") or "").strip()
        name = str(item.get("Name") or "").strip()
        if not ticker or not name:
            continue
        result.append(
            {
                "ticker": ticker,
                "name": name,
                "asset_type": _classify_to_asset_type(item.get("Classify"), name),
                "price": 0,
                "source": "eastmoney",
            }
        )
        if len(result) >= max_items:
            break
    return result


def search_with_fallback_info(keyword, limit=EASTMONEY_MAX_RESULTS):
    """先试东财，失败 / 超时 / 断网时回退本地字典，并告诉调用方「是否降级、为什么」。

    返回 `(items, fallback, reason)`：
      - 东财正常应答（含空结果）→ `fallback=False`，`reason=""`；
      - 网络层异常（连不上、超时、断网）→ `fallback=True`，`reason` 是异常文本，items 来自本地字典。

    降级只发生在**网络层异常**。东财正常返回空列表表示「全市场确无此标的」，
    此时**不回退**（否则会把本地字典里已过时的标的一股脑塞给用户，反而失真）。
    搜索的主链路永远是东财 API，本地字典只在断网时兜底（v0.13.4 需求：搜索不靠字典，
    字典以后只承担「自动补全标的资料」的职责）。
    """
    try:
        return search_eastmoney(keyword, limit), False, ""
    except Exception as exc:  # noqa: BLE001 - 网络层异常一律兜底，绝不让搜索功能瘫痪
        return invest_mock.search_securities(keyword, limit), True, "%s: %s" % (type(exc).__name__, exc)


def search_or_fallback(keyword, limit=EASTMONEY_MAX_RESULTS):
    """兼容旧调用方的薄封装：只要结果列表，不要降级标记。"""
    items, _fallback, _reason = search_with_fallback_info(keyword, limit)
    return items

# ==========================================================================
# 历史 K 线 / 实时报价（v0.14.4 新增）
#
# 数据源选择理由（详见 temp/ai-invest-kline/report.md）：
# - 股票 / ETF / 场内基金：push2his 的 kline 接口。免鉴权，klt=101/102/103 直接给
#   日 / 周 / 月，fqt=1 给前复权，lmt 一次最多取 500 根，画图 + dataZoom 足够。
# - 场外基金：同一个 kline 接口对 6 位场外基金代码返回空 klines（实测 005827），
#   所以回落到 f10/lsjz 净值历史（必须带 Referer，否则东财返回拒绝页），
#   拿单位净值当收盘价，周 / 月由日净值在本地聚合。
# - 实时价：ulist.np 批量接口一次可查多只，fltt=2 让数值直接是小数，
#   避免再按 f1 小数位做二次换算（ETF 3 位小数会被截断成 2 位）。
#   场外基金不在批量接口里，逐只回落到净值接口的最新一条。
# 以上所有外部请求都复用 _enforce_rate_limit()：与 search 共用同一把 ≥1 秒的锁，
# 任何一条链路都不可能把东财打成高频。
# ==========================================================================

EASTMONEY_KLINE_URL = (
    (os.getenv("EASTMONEY_KLINE_URL") or "").strip()
    or "https://push2his.eastmoney.com/api/qt/stock/kline/get"
)
EASTMONEY_QUOTE_URL = (
    (os.getenv("EASTMONEY_QUOTE_URL") or "").strip()
    or "https://push2.eastmoney.com/api/qt/ulist.np/get"
)
EASTMONEY_FUND_NAV_URL = (
    (os.getenv("EASTMONEY_FUND_NAV_URL") or "").strip()
    or "https://api.fund.eastmoney.com/f10/lsjz"
)
# 基金净值接口的防盗链校验：不带这个 Referer 会拿到 HTML 拒绝页
EASTMONEY_FUND_REFERER = "http://fundf10.eastmoney.com/"
# 场外基金全量净值走势（一个 JS 文件里带 Data_netWorthTrend 数组，含全部历史）
EASTMONEY_FUND_TREND_URL = (
    (os.getenv("EASTMONEY_FUND_TREND_URL") or "").strip()
    or "https://fund.eastmoney.com/pingzhongdata/%s.js"
)

# 周期 → 东财 klt 参数（101 日线 / 102 周线 / 103 月线）
KLINE_PERIOD_CODES = {"day": 101, "week": 102, "month": 103}
# 各周期默认取多少根：日线多给一些，缩放后才不会一拖就露白
KLINE_DEFAULT_LIMITS = {"day": 240, "week": 180, "month": 120}
# 单次请求上限（东财接口自身 lmt 上限 500 左右，再多也是重复数据）
KLINE_MAX_LIMIT = 500
# 批量报价一次最多查多少只，防止 URL 被拉爆
QUOTE_MAX_CODES = 50


def secid_for(code):
    """把裸代码转成东财 secid（1.600519 / 0.000001）。

    规则与东财网页端一致：沪市（5xx 场内基金 / 6xx 股票 / 9xx B 股）用 1，
    深市与北交所（0/1/2/3/4/8 开头）用 0。无法识别返回空串，由调用方决定降级。
    """
    text = (code or "").strip().upper()
    if not text:
        return ""
    # 已经带市场前缀的写法原样支持：SH600519 / SZ000001 / 1.600519
    if text[:2] in ("SH", "SZ", "BJ") and len(text) > 2:
        market = "1" if text[:2] == "SH" else "0"
        return "%s.%s" % (market, text[2:].strip())
    if "." in text:
        left, right = text.split(".", 1)
        if left in ("0", "1") and right.strip():
            return "%s.%s" % (left, right.strip())
    digits = text
    if digits.isdigit() and len(digits) == 6:
        return ("1." if digits[0] in ("5", "6", "9") else "0.") + digits
    return ""


def _eastmoney_get_json(url, headers=None):
    """带 ≥1 秒限流的 GET + JSON 解析。任何网络 / 解析异常都向上抛，由上层降级。"""
    _enforce_rate_limit()
    request_headers = {"User-Agent": "Mozilla/5.0"}
    if headers:
        request_headers.update(headers)
    req = urllib.request.Request(url, headers=request_headers)
    with urllib.request.urlopen(req, timeout=EASTMONEY_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _as_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    if number != number or number in (float("inf"), float("-inf")):  # NaN / Inf
        return default
    return number


def _fetch_kline_rows(code, period, limit):
    """拉股票 / ETF 的 K 线原始行，返回 (points, name)；无数据返回 ([], "")。"""
    secid = secid_for(code)
    if not secid:
        return [], ""
    query = urllib.parse.urlencode(
        {
            "secid": secid,
            "klt": str(KLINE_PERIOD_CODES[period]),
            "fqt": "1",  # 1 = 前复权，除权日不会出现假跳空
            "end": "20500101",
            "lmt": str(limit),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57",
        }
    )
    payload = _eastmoney_get_json(EASTMONEY_KLINE_URL + "?" + query)
    data = payload.get("data") or {}
    name = str(data.get("name") or "").strip()
    rows = data.get("klines") or []
    if not isinstance(rows, list):
        return [], name
    points = []
    for raw in rows:
        if not isinstance(raw, str):
            continue
        parts = raw.split(",")
        if len(parts) < 6:
            continue
        # 东财文本行顺序（fields2=f51..f57）：日期,开,收,最高,最低,成交量,成交额
        # 实测 600519 2026-11-17 为 1458.88,1457.70,1461.60,1437.71：
        # 只有「第 4 位是最高、第 5 位是最低」才满足 low <= open/close <= high。
        date = parts[0].strip()
        open_price = _as_float(parts[1], -1)
        close_price = _as_float(parts[2], -1)
        high_price = _as_float(parts[3], -1)
        low_price = _as_float(parts[4], -1)
        if not date or min(open_price, close_price, low_price, high_price) < 0:
            continue
        # 数据源偶发的越界值（最高 < 收盘）会让 K 线画歪，这里夹紧到合法区间
        high_price = max(high_price, open_price, close_price)
        low_price = min(low_price, open_price, close_price)
        points.append(
            {
                "date": date,
                "open": open_price,
                "close": close_price,
                "low": low_price,
                "high": high_price,
                "volume": int(_as_float(parts[5], 0)),
            }
        )
    return points, name


# 从 JS 里抠数组 / 名称，避免为一个变量引入 JS 引擎
_FUND_TREND_RE = re.compile(r"Data_netWorthTrend\s*=\s*(\[.*?\])\s*;", re.S)
_FUND_NAME_RE = re.compile(r'fS_name\s*=\s*"([^"]*)"')


def _fetch_fund_nav_trend(code):
    """拉场外基金全量净值走势（pingzhongdata JS），返回 (rows, name)。

    比 f10/lsjz 分页接口强的地方：一次请求就拿到全部历史，不用翻页
    （lsjz 实测 pageSize 最大只认 20 条，画月 K 要翻 100+ 页，每页还受 1 秒限流）。
    """
    url = (EASTMONEY_FUND_TREND_URL % code.strip()) if "%s" in EASTMONEY_FUND_TREND_URL else EASTMONEY_FUND_TREND_URL
    _enforce_rate_limit()
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=EASTMONEY_TIMEOUT) as resp:
        text = resp.read().decode("utf-8", "replace")
    match = _FUND_TREND_RE.search(text)
    if not match:
        return [], ""
    try:
        rows = json.loads(match.group(1))
    except (TypeError, ValueError):
        return [], ""
    name_match = _FUND_NAME_RE.search(text)
    name = name_match.group(1).strip() if name_match else ""
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            stamp = float(row.get("x")) / 1000.0
            nav = float(row.get("y"))
        except (TypeError, ValueError):
            continue
        if nav <= 0 or stamp <= 0:
            continue
        day = datetime.datetime.fromtimestamp(stamp, datetime.timezone.utc).date()
        points.append(
            {
                "date": day.isoformat(),
                "nav": round(nav, 4),
                "change_percent": _as_float(row.get("equityReturn"), 0),
            }
        )
    points.sort(key=lambda item: item["date"])
    return points, name


def _fetch_fund_nav_lsjz(code, page_size):
    """f10/lsjz 最近若干条净值（升序）。pageSize 实测最大只认 20 条。"""
    query = urllib.parse.urlencode(
        {"fundCode": code, "pageIndex": "1", "pageSize": str(max(1, int(page_size)))}
    )
    payload = _eastmoney_get_json(
        EASTMONEY_FUND_NAV_URL + "?" + query,
        headers={"Referer": EASTMONEY_FUND_REFERER},
    )
    data = payload.get("Data") or {}
    rows = data.get("LSJZList") or []
    if not isinstance(rows, list):
        return []
    points = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("FSRQ") or "").strip()
        nav = _as_float(row.get("DWJZ"), 0)
        if not date or nav <= 0:
            continue
        points.append(
            {
                "date": date,
                "nav": nav,
                "change_percent": _as_float(row.get("JZZZL"), 0),
            }
        )
    # 接口是新→旧，本地统一成旧→新，后面聚合与图表都按时间正序
    points.sort(key=lambda item: item["date"])
    return points


def _merge_nav_rows(base, extra):
    """按日期合并两段净值（extra 覆盖 base 同一天的值），返回升序列表。

    pingzhongdata 的全量走势偶尔比净值页晚 1~2 个交易日（CDN 缓存），
    所以「全量历史 + 最近 20 条」拼起来，图和报价才都落在最新一天。
    """
    merged = {row["date"]: row for row in base}
    for row in extra:
        merged[row["date"]] = row
    return [merged[date] for date in sorted(merged)]


def _fetch_fund_nav_rows(code, page_size):
    """场外基金净值历史（升序）+ 名称，返回 (rows, name)。

    全量历史来自 pingzhongdata，最新几天用 f10/lsjz 补齐；
    两条都失败时返回空列表（上层会降级本地模拟曲线）。
    """
    text = (code or "").strip()
    if not text:
        return [], ""
    points, name = [], ""
    try:
        points, name = _fetch_fund_nav_trend(text)
    except Exception:  # noqa: BLE001 - 全量走势失败就只用最近 20 条兜底
        points, name = [], ""
    try:
        fresh = _fetch_fund_nav_lsjz(text, page_size)
    except Exception:  # noqa: BLE001 - 补最新失败不影响历史曲线
        fresh = []
    return _merge_nav_rows(points, fresh), name


def _aggregate_fund_nav(points, period, limit):
    """日净值聚合为周 / 月 K 线（开=首日净值，收=末日净值，高低=区间极值）。"""
    if period == "day":
        return [
            {
                "date": item["date"],
                "open": item["nav"],
                "close": item["nav"],
                "low": item["nav"],
                "high": item["nav"],
                "volume": 0,
            }
            for item in points[-limit:]
        ]
    buckets = {}
    order = []
    for item in points:
        try:
            day = datetime.date.fromisoformat(item["date"][:10])
        except ValueError:
            continue
        if period == "week":
            year, week = day.isocalendar()[:2]
            key = "%04d-W%02d" % (year, week)
        else:
            key = "%04d-%02d" % (day.year, day.month)
        bucket = buckets.get(key)
        if bucket is None:
            bucket = {
                "date": item["date"],
                "first": item["nav"],
                "last": item["nav"],
                "high": item["nav"],
                "low": item["nav"],
            }
            buckets[key] = bucket
            order.append(key)
        bucket["date"] = item["date"]  # 用区间最后一天做刻度，和「周K 收于周五」一致
        bucket["last"] = item["nav"]
        bucket["high"] = max(bucket["high"], item["nav"])
        bucket["low"] = min(bucket["low"], item["nav"])
    merged = [
        {
            "date": buckets[key]["date"],
            "open": buckets[key]["first"],
            "close": buckets[key]["last"],
            "low": buckets[key]["low"],
            "high": buckets[key]["high"],
            "volume": 0,
        }
        for key in order
    ]
    return merged[-limit:]


def fetch_kline(code, period="day", limit=None):
    """取标准化 K 线，返回 {code, period, name, source, points}。

    先按股票 / ETF 查；拿到空数据再按场外基金净值查（两类标的的接口不同）。
    两条路都拿不到就抛 ValueError，由上层决定是否降级本地模拟曲线。
    """
    text = (code or "").strip()
    cycle = (period or "day").strip().lower()
    if not text:
        raise ValueError("标的代码不能为空")
    if cycle not in KLINE_PERIOD_CODES:
        raise ValueError("period 仅支持 day/week/month")
    try:
        want = int(limit) if limit else KLINE_DEFAULT_LIMITS[cycle]
    except (TypeError, ValueError):
        want = KLINE_DEFAULT_LIMITS[cycle]
    want = max(1, min(want, KLINE_MAX_LIMIT))

    points, name = _fetch_kline_rows(text, cycle, want)
    if points:
        return {
            "code": text,
            "period": cycle,
            "name": name or text,
            "source": "eastmoney",
            "points": points,
        }

    # 周 / 月要先把足够多的日净值取回来再聚合，否则一根月 K 只能拿到几天
    nav_span = {"day": want, "week": want * 6, "month": want * 23}[cycle]
    nav_rows, fund_name = _fetch_fund_nav_rows(text, max(60, min(nav_span, 2000)))
    nav_points = _aggregate_fund_nav(nav_rows, cycle, want)
    if nav_points:
        return {
            "code": text,
            "period": cycle,
            "name": fund_name or text,
            "source": "eastmoney-fund",
            "points": nav_points,
        }
    raise ValueError("东财未返回 %s 的 K 线数据" % text)


def _fetch_fund_quote(code):
    """单只场外基金的最新净值报价；取不到返回 None。"""
    rows, name = _fetch_fund_nav_rows(code, 2)
    if not rows:
        return None
    latest = rows[-1]
    percent = latest.get("change_percent", 0.0)
    prev_close = latest["nav"] / (1 + percent / 100.0) if percent != -100 else latest["nav"]
    return {
        "code": code,
        "name": name or code,
        "price": round(latest["nav"], 4),
        "prev_close": round(prev_close, 4),
        "change": round(latest["nav"] - prev_close, 4),
        "change_percent": round(percent, 2),
        "source": "eastmoney-fund",
    }


def fetch_quote_batch(codes):
    """批量报价：[{code, name, price, prev_close, change, change_percent, source}]。

    只返回**查到了的**标的；查不到的由调用方跳过（不编价格）。网络异常向上抛。
    """
    cleaned = []
    for code in codes or []:
        text = str(code or "").strip()
        if text and text not in cleaned:
            cleaned.append(text)
    cleaned = cleaned[:QUOTE_MAX_CODES]
    if not cleaned:
        return []

    secid_map = {}
    for code in cleaned:
        secid = secid_for(code)
        if secid:
            secid_map[code] = secid

    quotes = {}
    if secid_map:
        query = urllib.parse.urlencode(
            {
                "secids": ",".join(secid_map.values()),
                "fields": "f1,f2,f3,f4,f12,f13,f14,f18",
                # fltt=2：数值直接给小数（ETF 的 3 位小数不会被截断）
                "fltt": "2",
                "invt": "2",
                "np": "1",
            }
        )
        payload = _eastmoney_get_json(EASTMONEY_QUOTE_URL + "?" + query)
        diff = (payload.get("data") or {}).get("diff") or []
        if isinstance(diff, dict):  # 个别通道把 diff 下发成 {"0": {...}}
            diff = list(diff.values())
        for item in diff:
            if not isinstance(item, dict):
                continue
            quote_code = str(item.get("f12") or "").strip()
            price = _as_float(item.get("f2"), 0)
            if not quote_code or price <= 0:
                continue
            quotes[quote_code] = {
                "code": quote_code,
                "name": str(item.get("f14") or quote_code).strip(),
                "price": round(price, 4),
                "prev_close": round(_as_float(item.get("f18"), 0), 4),
                "change": round(_as_float(item.get("f4"), 0), 4),
                "change_percent": round(_as_float(item.get("f3"), 0), 2),
                "source": "eastmoney",
            }

    # 批量接口查不到的（典型是场外基金）逐只回落到净值接口
    for code in cleaned:
        if code in quotes:
            continue
        try:
            quote = _fetch_fund_quote(code)
        except Exception:  # noqa: BLE001 - 单只失败不该拖垮整批
            quote = None
        if quote:
            quotes[code] = quote

    # 按入参顺序输出，前端 / 同步逻辑不用再排序
    return [quotes[code] for code in cleaned if code in quotes]

