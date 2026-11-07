# v0.14.1 智汇账 Flask 应用镜像
# 基础镜像按要求使用 Python 3.10-slim。
FROM python:3.10-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    PIP_NO_CACHE_DIR=1

# tzdata：让 datetime.now() 与 MySQL 的 time_zone='+08:00' 口径一致，
# 否则容器默认 UTC，账目日期会在 08:00 前整体差一天。
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# 运行期上传目录：与 compose 的 volume 对应，容器重建不丢图
RUN mkdir -p /app/static/uploads/avatars

EXPOSE 5000

# 用 Python 自带 urllib 做健康检查，镜像里不必额外装 curl
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/health', timeout=3)" || exit 1

# 关键：-w 1（单进程多线程）。
# cache_ext 用的是 SimpleCache（进程内内存缓存），多 worker 时写请求落在 A 进程
# 只清掉 A 的缓存，B 进程那份还是旧数据 —— 用户就会看到旧图表。
# 单进程下 delete_memoized 对全部线程生效。将来要多机/多进程部署，
# 必须把 CACHE_TYPE 换成 RedisCache，代码里的失效调用不用改。
CMD ["gunicorn", "-w", "1", "--threads", "4", "-b", "0.0.0.0:5000", \
     "--timeout", "120", "--access-logfile", "-", "--error-logfile", "-", "app:app"]
