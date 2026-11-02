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

import json
import os
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


def search_or_fallback(keyword, limit=EASTMONEY_MAX_RESULTS):
    """先试东财，失败 / 超时 / 断网时自动降级回退到 invest_mock 本地字典。

    降级只发生在**网络层异常**（失败、超时、断网）。东财正常返回空列表表示「全市场确无此标的」，
    此时**不回退**（否则会把本地字典里已过时的标的一股脑塞给用户，反而失真）。
    """
    try:
        return search_eastmoney(keyword, limit)
    except Exception:  # noqa: BLE001 - 网络层异常一律兜底，绝不让搜索功能瘫痪
        return invest_mock.search_securities(keyword, limit)
