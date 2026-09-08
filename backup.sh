#!/bin/bash
# ============================================================
# AIROBOT 自动备份脚本
# 定时执行：每天 00:00 / 12:00（由 WorkBuddy automation 触发）
# 保留周期：超过 5 天的备份自动清理
# ============================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")" && pwd)"
BACKUP_DIR="${AIROBOT_BACKUP_DIR:-$REPO_ROOT/backups}"
DB_NAME="${AIROBOT_DB_NAME:-airobot}"
DB_USER="${AIROBOT_DB_USER:-airobot}"
DB_HOST="${AIROBOT_DB_HOST:-localhost}"
RETENTION_DAYS="${AIROBOT_BACKUP_RETENTION_DAYS:-5}"
TIMESTAMP=$(date "+%Y-%m-%d-%H%M")
LOG_FILE="${AIROBOT_BACKUP_LOG:-/tmp/airobot_backup.log}"
PG_DUMP="${PG_DUMP_BIN:-$(command -v pg_dump 2>/dev/null || true)}"
GZIP_BIN="${GZIP_BIN:-$(command -v gzip 2>/dev/null || true)}"

mkdir -p "$BACKUP_DIR"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== AIROBOT 备份开始 ==="

# ---------- 1. 备份 PostgreSQL 数据库（压缩） ----------
DUMP_FILE="${BACKUP_DIR}/airobot-${TIMESTAMP}.sql.gz"
log "正在备份数据库 ${DB_NAME} → ${DUMP_FILE} ..."

if [ -z "$PG_DUMP" ] || [ -z "$GZIP_BIN" ]; then
  log "❌ 数据库备份失败：未找到 pg_dump 或 gzip"
else
  if "$PG_DUMP" -h "$DB_HOST" -U "$DB_USER" "$DB_NAME" 2>/dev/null | "$GZIP_BIN" > "$DUMP_FILE"; then
    SIZE=$(du -h "$DUMP_FILE" | cut -f1)
    log "✅ 数据库备份完成（${SIZE}）"
  else
    rc=$?
    log "❌ 数据库备份失败（退出码=${rc}）"
    rm -f "$DUMP_FILE"
  fi
fi

# ---------- 2. 清理超过保留期的旧备份 ----------
log "清理 ${RETENTION_DAYS} 天前的旧备份..."
CLEANED=0

# macOS 使用 date -v / stat -f；GNU/Linux 使用 date -d / stat -c。
if date -v-1d +%s >/dev/null 2>&1; then
  CUTOFF=$(date -v-${RETENTION_DAYS}d +%s)
  get_mtime() { stat -f %m "$1" 2>/dev/null || true; }
else
  CUTOFF=$(date -d "-${RETENTION_DAYS} days" +%s)
  get_mtime() { stat -c %Y "$1" 2>/dev/null || true; }
fi

for f in "${BACKUP_DIR}"/airobot-*.sql.gz; do
  [ -f "$f" ] || continue
  FILE_MTIME=$(get_mtime "$f")
  if [ -n "$FILE_MTIME" ] && [ "$FILE_MTIME" -le "$CUTOFF" ]; then
    rm -f "$f"
    log "  删除旧备份: $(basename "$f")"
    # 避免 `set -e` + `((CLEANED++))` 在第一次自增（表达式值为0）时误退出。
    CLEANED=$((CLEANED + 1))
  fi
done

log "  共清理 ${CLEANED} 个旧备份"

# ---------- 3. 报告当前备份概况 ----------
TOTAL=$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'airobot-*.sql.gz' | wc -l | tr -d ' ')
log "当前备份总量: ${TOTAL} 个"
log "=== AIROBOT 备份完成 ==="
