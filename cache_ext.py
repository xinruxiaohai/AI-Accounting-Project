"""v0.14.1 轻量级缓存：Flask-Caching / SimpleCache（进程内内存缓存）。

对外接口
--------
    cache                      Flask-Caching 实例
    init_cache(app)            在 app.py 创建 Flask 实例后调用
    statistics_data(uid)       @cache.memoize(timeout=600) 的统计结果
    recent_7_days_data(uid)    @cache.memoize(timeout=600) 的近 7 天图表结果
    invalidate_record_caches() 清掉上述两份缓存（写操作后必须调用）

为什么不直接装饰无参的 view 函数
--------------------------------
/api/statistics 这类接口的结果**取决于当前登录用户**。如果给一个无参 view
直接套 @cache.memoize，缓存 key 里没有 user_id，A 用户看完图表后 B 用户会
命中同一份数据 —— 直接击穿「多用户隔离」红线。所以这里把「取数」抽成带
显式 user_id 形参的函数，让 memoize 的 key 天然包含 uid，并且把同一个 uid
显式传给 database.get_statistics(user_id=...)，key 与 SQL 用的是同一个值。

部署约束（写进 Dockerfile 的原因）
----------------------------------
SimpleCache 是**进程内**缓存。Gunicorn 开多个 worker 时，写请求落在 A 进程、
缓存清了，B 进程那份还是旧的，用户就会看到旧数据。因此容器固定
`-w 1 --threads 4`（单进程多线程），保证失效对全进程生效；将来上多机部署
必须把 CACHE_TYPE 换成 RedisCache，那时本文件的失效调用不用改。
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

try:
    from flask_caching import Cache

    HAS_FLASK_CACHING = True
except ImportError:  # pragma: no cover - 缺依赖时降级为「不缓存」，接口照样能用
    HAS_FLASK_CACHING = False

    class _NoCache:
        """零依赖兜底：memoize 退化成恒等装饰器，delete_memoized 空操作。"""

        def __init__(self, *args, **kwargs):
            pass

        def init_app(self, app, config=None):
            return None

        def memoize(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator

        def delete_memoized(self, *args, **kwargs):
            return None

    Cache = _NoCache


CACHE_TIMEOUT = 600  # 10 分钟

# 跨进程「缓存代际号」：SimpleCache 是进程内缓存，云端一旦开多 worker，
# delete_memoized() 只能清掉当前 worker 的那份，其它 worker 会继续返回旧数据。
# 所以写操作除了清本进程缓存，还会原子地递增这个共享文件的代际号；
# 代际号进入 memoize 的 key，所有 worker 下一次取数自动换 key，旧值自然失效
# （旧条目仍由 SimpleCache 的 600s 超时回收，不会无限增长）。
def _generation_file():
    """优先放 temp/（已被 .gitignore 忽略，不污染工作区）；不可写才退回项目根目录。"""
    project = Path(__file__).resolve().parent
    preferred = project / "temp" / ".cache_generation"
    try:
        preferred.parent.mkdir(parents=True, exist_ok=True)
        return preferred
    except OSError:
        return project / ".cache_generation"


_GENERATION_FILE = _generation_file()


def current_generation():
    """读共享代际号；文件不存在 / 读失败一律回 0，绝不影响读接口。"""
    try:
        return int(_GENERATION_FILE.read_text(encoding="utf-8").strip())
    except (OSError, ValueError, TypeError):
        return 0


def _bump_generation():
    """原子写一个全新的代际号（同机多进程/多线程共享，天然单调）。"""
    value = str(time.time_ns())
    tmp = _GENERATION_FILE.with_name(
        "%s.tmp.%d.%d" % (_GENERATION_FILE.name, os.getpid(), threading.get_ident())
    )
    try:
        tmp.write_text(value, encoding="utf-8")
        os.replace(str(tmp), str(_GENERATION_FILE))
    except OSError as exc:  # 写失败只告警：本进程的 delete_memoized 仍生效
        print("[cache_ext] 代际号写入失败：%s" % exc, file=sys.stderr, flush=True)
        try:
            tmp.unlink()
        except OSError:
            pass


def _cache_config():
    """本地默认 SimpleCache；云端多进程 / 多机部署用环境变量切 RedisCache。

    v0.14.1 收尾：原先 CACHE_TYPE 是写死的，文档里「设环境变量换 RedisCache」
    根本不生效。这里改成可由环境变量覆盖，默认值不变（零配置仍是 SimpleCache）。
    """
    config = {
        "CACHE_TYPE": (os.getenv("CACHE_TYPE") or "SimpleCache").strip(),
        "CACHE_DEFAULT_TIMEOUT": CACHE_TIMEOUT,
        "CACHE_KEY_PREFIX": "zhz_v0141_",
    }
    redis_url = (os.getenv("CACHE_REDIS_URL") or "").strip()
    if redis_url:
        config["CACHE_REDIS_URL"] = redis_url
    return config


cache = Cache(config=_cache_config())


def init_cache(app):
    cache.init_app(app)
    return cache


@cache.memoize(timeout=CACHE_TIMEOUT)
def _statistics_cached(user_id, generation):
    """被缓存的取数函数。key = 函数名 + user_id + generation。

    generation 不参与查询，只用来让所有 worker 在写操作后自动换 key。
    """
    import database

    return database.get_statistics(user_id=user_id)


@cache.memoize(timeout=CACHE_TIMEOUT)
def _recent_7_days_cached(user_id, generation):
    import database

    return database.recent_7_days(user_id)


def statistics_data(user_id):
    return _statistics_cached(user_id, current_generation())


def recent_7_days_data(user_id):
    return _recent_7_days_cached(user_id, current_generation())


def invalidate_record_caches():
    """任何「新增 / 修改 / 删除账单」或「平账」之后调用。

    两层保障：
      1) delete_memoized 不带参数 = 清掉本进程这两个函数的所有参数组合，
         不需要知道刚才是哪个 uid 写的，也不会漏掉别的用户；
      2) 递增共享代际号 = 让同机其它 Gunicorn worker 的旧缓存 key 立即作废，
         补上 SimpleCache 跨进程失效的短板。
    """
    cache.delete_memoized(_statistics_cached)
    cache.delete_memoized(_recent_7_days_cached)
    _bump_generation()


__all__ = [
    "cache",
    "CACHE_TIMEOUT",
    "HAS_FLASK_CACHING",
    "init_cache",
    "statistics_data",
    "recent_7_days_data",
    "invalidate_record_caches",
]
