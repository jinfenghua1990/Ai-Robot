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

# === 2. 确保 PostgreSQL 已启动（pg_ctl 直启，避免 brew services 在 LaunchAgent 中死锁）===
if ! lsof -ti :5432 -P -n >/dev/null 2>&1; then
  echo "[$(ts)] 5432 未监听，启动 PostgreSQL@16..." >> "$LOG"
  pg_ctl -D "$PG_DATA" -l "$PG_DATA/server.log" start >/dev/null 2>&1 || true
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

# 先清理所有残留 uvicorn 进程（防止孤儿进程占用端口）
pkill -f "uvicorn.*9000" 2>/dev/null || true
sleep 1

# 端口预检：若 9000 仍被占用（上一轮未完全退出 / 孤儿进程），先回收，
# 避免 KeepAlive 重启时因 address already in use 而启动失败
PORT_PID=$(/usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t 2>/dev/null | head -1)
if [ -n "${PORT_PID:-}" ]; then
  echo "[$(ts)] 9000 仍被 PID $PORT_PID 占用，回收残留进程..." >> "$LOG"
  kill "$PORT_PID" 2>/dev/null || true
  for i in $(seq 1 10); do
    /usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t >/dev/null 2>&1 || break
    sleep 1
  done
  /usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t >/dev/null 2>&1 \
    && echo "[$(ts)] ⚠️ 9000 仍被占用，uvicorn 可能启动失败" >> "$LOG" \
    || echo "[$(ts)] 9000 已释放" >> "$LOG"
fi

cd /Users/gino/Projects/AIROBOT/backend
# 日志轮转：单文件 10MB，保留 7 个备份（-l 本地时间，-f 启动时立即打开）
/usr/bin/python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log 2>&1 | /usr/sbin/rotatelogs -l -f -n 7 /tmp/airobot_backend.log 10M &
UVPID=$!

# 等待端口就绪（最多 30 秒）
for i in $(seq 1 30); do
  /usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t >/dev/null 2>&1 && break
  sleep 1
done

# 预热：单独拉 /scanner（不带 regime/sectors 的前置请求，避免撞 Nasdaq 限流），
# 把 watchlist 真实行情填进 120s 缓存；用户访问 /overview 时 scanner 直接命中缓存。
echo "[$(ts)] 预热 US-Quant 行情缓存（scanner）..." >> "$LOG"
for i in $(seq 1 8); do
  /usr/bin/curl -s --max-time 60 "http://127.0.0.1:9000/api/us-quant/scanner?symbols=AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META,TSM" -o /tmp/airobot_warmup.json
  CNT=$(/usr/bin/python3 -c "import json;d=json.load(open('/tmp/airobot_warmup.json'));print(d.get('count',0))" 2>/dev/null || echo "0")
  if [ "$CNT" = "8" ]; then
    echo "[$(ts)] 预热完成（第 $i 轮，scanner=$CNT）" >> "$LOG"
    break
  fi
  echo "[$(ts)] 预热第 $i 轮不足（scanner=${CNT:-0}），重试..." >> "$LOG"
  sleep $((i * 3))
done

# 前台等待 uvicorn（其崩溃则由 launchd KeepAlive 重启整个 job）
wait $UVPID
