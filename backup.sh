#!/bin/bash
# ============================================================
# AIROBOT 自动备份脚本
# 定时执行：每天 00:00 / 12:00（由 WorkBuddy automation 触发）
# 保留周期：超过 5 天的备份自动清理
# ============================================================
set -euo pipefail

BACKUP_DIR="/Users/gino/Projects/AIROBOT/backups"
DB_NAME="airobot"
DB_USER="airobot"
DB_HOST="localhost"
RETENTION_DAYS=5
TIMESTAMP=$(date "+%Y-%m-%d-%H%M")
LOG_FILE="/tmp/airobot_backup.log"

mkdir -p "$BACKUP_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== AIROBOT 备份开始 ==="

# ---------- 1. 备份 PostgreSQL 数据库（压缩） ----------
DUMP_FILE="${BACKUP_DIR}/airobot-${TIMESTAMP}.sql.gz"
log "正在备份数据库 ${DB_NAME} → ${DUMP_FILE} ..."

if /opt/homebrew/bin/pg_dump -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" 2>/dev/null | gzip > "$DUMP_FILE"; then
  SIZE=$(du -h "$DUMP_FILE" | cut -f1)
  log "✅ 数据库备份完成（${SIZE}）"
else
  log "❌ 数据库备份失败（pg_dump 退出码=$?）"
  rm -f "$DUMP_FILE"
fi

# ---------- 2. 清理超过 5 天的旧备份 ----------
log "清理 ${RETENTION_DAYS} 天前的旧备份..."
CLEANED=0
for f in "${BACKUP_DIR}"/airobot-*.sql.gz; do
  [ -f "$f" ] || continue
  if [ $(stat -f %m "$f" 2>/dev/null) -le $(date -v-${RETENTION_DAYS}d +%s) ]; then
    rm -f "$f"
    log "  删除旧备份: $(basename "$f")"
    ((CLEANED++))
  fi
done

# 如果用 Linux 的 stat（macOS 用 stat -f %m, Linux 用 stat -c %Y）
# 兼容处理：如果上面 stat 失败，尝试 Linux 方式
if [ "$CLEANED" -eq 0 ]; then
  for f in "${BACKUP_DIR}"/airobot-*.sql.gz; do
    [ -f "$f" ] || continue
    FILE_MTIME=$(stat -c %Y "$f" 2>/dev/null || stat -f %m "$f" 2>/dev/null)
    if [ -n "$FILE_MTIME" ] && [ "$FILE_MTIME" -le $(date -d "-${RETENTION_DAYS} days" +%s 2>/dev/null || date -v-${RETENTION_DAYS}d +%s) ]; then
      rm -f "$f"
      log "  删除旧备份（Linux fallback）: $(basename "$f")"
      ((CLEANED++))
    fi
  done
fi

log "  共清理 ${CLEANED} 个旧备份"

# ---------- 3. 报告当前备份概况 ----------
TOTAL=$(ls -1 "${BACKUP_DIR}"/airobot-*.sql.gz 2>/dev/null | wc -l | tr -d ' ')
log "当前备份总量: ${TOTAL} 个"
log "=== AIROBOT 备份完成 ==="
