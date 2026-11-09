#!/usr/bin/env bash
# =============================================================================
# 智汇账 · 数据库每日备份脚本（v0.14.3.1）
# -----------------------------------------------------------------------------
# 做两件事，按实际部署形态自动选择，两边都做也不冲突：
#   1) SQLite：/opt/zhihuizhang/records.db  →  /opt/backups/records.db-<时间戳>.gz
#      优先用 `sqlite3 .backup`（在线热备，不加锁、不中断业务），
#      备份完立刻 `PRAGMA integrity_check`，不是 ok 就判失败并保留现场。
#   2) MySQL（Docker 部署）：docker compose exec db mysqldump
#      → /opt/backups/mysql-<时间戳>.sql.gz；没装 docker 时回退到本机 mysqldump + DB_URI。
#
# 保留策略：/opt/backups 下只保留最近 KEEP_DAYS 天（默认 7 天），更早的自动删除。
#
# 安装（云端服务器，root 或能读 records.db 的账号执行一次）：
#   sudo mkdir -p /opt/backups /var/log/zhihuizhang
#   sudo chmod +x /opt/zhihuizhang/deploy/backup_db.sh
#
# crontab（每天凌晨 3 点）：
#   sudo crontab -e
#   0 3 * * * /opt/zhihuizhang/deploy/backup_db.sh >> /var/log/zhihuizhang/backup.log 2>&1
#
# 手动试跑一次（强烈建议，别等到凌晨才发现路径不对）：
#   sudo /opt/zhihuizhang/deploy/backup_db.sh
#   ls -lh /opt/backups
#
# 可用环境变量覆盖默认值：APP_DIR / BACKUP_DIR / KEEP_DAYS / MYSQL_SERVICE
#   例：sudo APP_DIR=/srv/zhihuizhang BACKUP_DIR=/data/backups KEEP_DAYS=14 \
#         /opt/zhihuizhang/deploy/backup_db.sh
# =============================================================================
set -Eeuo pipefail

APP_DIR="${APP_DIR:-/opt/zhihuizhang}"
BACKUP_DIR="${BACKUP_DIR:-/opt/backups}"
KEEP_DAYS="${KEEP_DAYS:-7}"
MYSQL_SERVICE="${MYSQL_SERVICE:-db}"
STAMP="$(date +%Y%m%d-%H%M%S)"

log() {
  printf '[%s] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

die() {
  printf '[%s] [ERROR] %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2
  exit 1
}

trap 'die "第 ${LINENO} 行执行失败（命令：${BASH_COMMAND}）"' ERR

# ---------------------------------------------------------------------------
# 0. 环境检查
# ---------------------------------------------------------------------------
[ -d "$APP_DIR" ] || die "APP_DIR 不存在：$APP_DIR（用 APP_DIR=... 覆盖）"
command -v gzip >/dev/null 2>&1 || die "缺少 gzip，无法压缩备份"
mkdir -p "$BACKUP_DIR" || die "无法创建备份目录：$BACKUP_DIR"

log "开始备份：APP_DIR=$APP_DIR BACKUP_DIR=$BACKUP_DIR 保留 ${KEEP_DAYS} 天"
backed_up=0

# ---------------------------------------------------------------------------
# 1. SQLite：records.db（当前默认引擎）
# ---------------------------------------------------------------------------
SQLITE_FILE="$APP_DIR/records.db"
if [ -f "$SQLITE_FILE" ]; then
  SQLITE_OUT="$BACKUP_DIR/records.db-$STAMP"
  if command -v sqlite3 >/dev/null 2>&1; then
    # .backup 是 sqlite 官方的在线热备，不会阻塞正在写入的 Flask 进程
    sqlite3 "$SQLITE_FILE" ".timeout 5000" ".backup '$SQLITE_OUT'" \
      || die "sqlite3 .backup 失败：$SQLITE_FILE"
    check="$(sqlite3 "$SQLITE_OUT" 'PRAGMA integrity_check;' | head -n 1)"
    [ "$check" = "ok" ] || die "备份完整性校验未通过：$check（现场保留在 $SQLITE_OUT）"
    log "SQLite 完整性校验通过"
  else
    # 没装 sqlite3 命令行时退化为冷拷贝；建议生产装 sqlite3，热备更安全
    cp -p "$SQLITE_FILE" "$SQLITE_OUT" || die "copy 失败：$SQLITE_FILE"
    log "未找到 sqlite3 命令，已退化为文件拷贝（建议 apt install sqlite3）"
  fi
  gzip -9 -f "$SQLITE_OUT" || die "gzip 压缩失败：$SQLITE_OUT"
  log "SQLite 备份完成：$SQLITE_OUT.gz（$(du -h "$SQLITE_OUT.gz" | cut -f1)）"
  backed_up=1
else
  log "跳过 SQLite：$SQLITE_FILE 不存在（纯 MySQL 部署时正常）"
fi

# ---------------------------------------------------------------------------
# 2. MySQL：docker compose 部署时从 db 容器里 dump
# ---------------------------------------------------------------------------
MYSQL_OUT="$BACKUP_DIR/mysql-$STAMP.sql"
mysql_done=0

if command -v docker >/dev/null 2>&1 && [ -f "$APP_DIR/docker-compose.yml" ]; then
  if docker compose -f "$APP_DIR/docker-compose.yml" ps --status running 2>/dev/null | grep -q "$MYSQL_SERVICE"; then
    # 密码从 compose 注入的容器环境里取，不落盘到命令行参数
    if docker compose -f "$APP_DIR/docker-compose.yml" exec -T "$MYSQL_SERVICE" \
        sh -c 'exec mysqldump --single-transaction --quick --routines --triggers \
               -u root -p"$MYSQL_ROOT_PASSWORD" "$MYSQL_DATABASE"' > "$MYSQL_OUT" 2>"$MYSQL_OUT.err"; then
      [ -s "$MYSQL_OUT" ] || die "mysqldump 输出为空：$MYSQL_OUT"
      rm -f "$MYSQL_OUT.err"
      mysql_done=1
      log "MySQL(docker) 备份完成"
    else
      log "MySQL(docker) 备份失败，错误见 $MYSQL_OUT.err"
    fi
  fi
fi

# 回退：本机 mysqldump + .env 里的 DB_URI
if [ "$mysql_done" -eq 0 ] && command -v mysqldump >/dev/null 2>&1 && [ -f "$APP_DIR/.env" ]; then
  DB_URI="$(grep -E '^[[:space:]]*DB_URI[[:space:]]*=' "$APP_DIR/.env" | tail -n 1 | cut -d= -f2- | tr -d '"' | sed "s/'//g")"
  if [ -n "$DB_URI" ]; then
    # mysql+pymysql://user:pass@host:3306/dbname?charset=utf8mb4 → 各字段
    parsed="$(DB_URI="$DB_URI" python3 - <<'PY'
import os, urllib.parse as up
uri = os.environ["DB_URI"].split("://", 1)[-1]
creds, _, rest = uri.partition("@")
user, _, password = creds.partition(":")
host, _, dbpart = rest.partition("/")
dbname = dbpart.split("?", 1)[0]
print(user, up.unquote(password), host, dbname)
PY
)" || die "DB_URI 解析失败"
    read -r DB_USER DB_PASS DB_HOST DB_NAME <<< "$parsed"
    MYSQL_PWD="$DB_PASS" mysqldump --single-transaction --quick --routines --triggers \
      -h "${DB_HOST%%:*}" -P "${DB_HOST##*:}" -u "$DB_USER" "$DB_NAME" > "$MYSQL_OUT" \
      || die "mysqldump 失败（$DB_USER@$DB_HOST/$DB_NAME）"
    mysql_done=1
    log "MySQL(本地) 备份完成"
  fi
fi

if [ "$mysql_done" -eq 1 ]; then
  gzip -9 -f "$MYSQL_OUT" || die "gzip 压缩失败：$MYSQL_OUT"
  log "MySQL 备份文件：$MYSQL_OUT.gz（$(du -h "$MYSQL_OUT.gz" | cut -f1)）"
  backed_up=1
else
  log "跳过 MySQL：未检测到 docker compose 中的 $MYSQL_SERVICE 服务，也没有可用的 mysqldump + DB_URI"
fi

[ "$backed_up" -eq 1 ] || die "没有备份到任何数据库，请检查 APP_DIR 与部署形态"

# ---------------------------------------------------------------------------
# 3. 保留策略：只留最近 KEEP_DAYS 天
# ---------------------------------------------------------------------------
log "清理 ${KEEP_DAYS} 天前的旧备份"
find "$BACKUP_DIR" -maxdepth 1 -type f \
  \( -name 'records.db-*' -o -name 'mysql-*.sql' -o -name 'mysql-*.sql.gz' \) \
  -mtime +"$KEEP_DAYS" -print -delete || true

log "当前备份目录（$(du -sh "$BACKUP_DIR" | cut -f1)）："
ls -lh "$BACKUP_DIR" | tail -n "+2" || true
log "备份结束，退出码 0"