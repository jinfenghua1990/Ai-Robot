#!/bin/bash
# AIROBOT 开机自启脚本
# 功能：1) 清理 PostgreSQL 残留锁文件  2) 确保 PG 运行  3) 启动后端 uvicorn
# 由 LaunchAgent (com.airobot.autostart) 在登录后自动调用
set -u

export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
LOG=/tmp/airobot_autostart.log
PG_DATA=/opt/homebrew/var/postgresql@16
PG_PID_FILE="$PG_DATA/postmaster.pid"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# === 1. 清理 PostgreSQL 残留锁文件（断电/强制关机后会留下）===
if [ -f "$PG_PID_FILE" ]; then
  PID=$(head -1 "$PG_PID_FILE" 2>/dev/null)
  if [ -n "${PID:-}" ] && ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PG_PID_FILE"
    echo "[$(ts)] 清理残留 postmaster.pid (PID $PID 已死)" >> "$LOG"
  fi
fi

# === 2. 确保 PostgreSQL 已启动（brew services 自启失败时兜底）===
if ! lsof -ti :5432 -P -n >/dev/null 2>&1; then
  echo "[$(ts)] 5432 未监听，启动 PostgreSQL@16..." >> "$LOG"
  brew services restart postgresql@16 >/dev/null 2>&1
  # 等待 PG 就绪（最多 15 秒）
  for i in $(seq 1 15); do
    lsof -ti :5432 -P -n >/dev/null 2>&1 && break
    sleep 1
  done
  lsof -ti :5432 -P -n >/dev/null 2>&1 \
    && echo "[$(ts)] PostgreSQL 已就绪" >> "$LOG" \
    || echo "[$(ts)] ⚠️ PostgreSQL 仍未就绪，后端可能连不上 DB" >> "$LOG"
fi

# === 3. 启动后端 uvicorn（前台运行，由 LaunchAgent KeepAlive 管理）===
echo "[$(ts)] 启动后端 uvicorn (9000)..." >> "$LOG"
cd /Users/gino/Projects/AIROBOT/backend
exec /usr/bin/python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log
