#!/bin/bash
# AIROBOT 开机自启脚本
# 功能：1) 清理 PostgreSQL 残留锁文件  2) 确保 PG 运行  3) 启动后端 uvicorn
# 由 LaunchAgent (com.airobot.autostart) 在登录后自动调用
set -u
set -o pipefail

export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin
ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG=/tmp/airobot_autostart.log
PG_DATA=/opt/homebrew/var/postgresql@16
PG_PID_FILE="$PG_DATA/postmaster.pid"
PYTHON="$ROOT_DIR/backend/.venv/bin/python"

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

if [ ! -x "$PYTHON" ]; then
  echo "[$(ts)] 后端启动失败：Python 虚拟环境不存在 ($PYTHON)" >> "$LOG"
  exit 1
fi

pkill -f "uvicorn.*9000" 2>/dev/null || true
for i in $(seq 1 5); do
  pgrep -f "uvicorn.*9000" >/dev/null 2>&1 || break
  sleep 1
done
if pgrep -f "uvicorn.*9000" >/dev/null 2>&1; then
  echo "[$(ts)] 旧 uvicorn 超时未退出，强制回收..." >> "$LOG"
  pkill -9 -f "uvicorn.*9000" 2>/dev/null || true
fi

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

cd "$ROOT_DIR/backend"
"$PYTHON" -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --timeout-graceful-shutdown 15 \
  --no-access-log \
  > >(/usr/sbin/rotatelogs -l -f -n 7 /tmp/airobot_backend.log 10M) 2>&1 &
UVPID=$!

PORT_READY=0
for i in $(seq 1 120); do
  if /usr/sbin/lsof -nP -iTCP:9000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    PORT_READY=1
    break
  fi
  sleep 1
done
if [ "$PORT_READY" -ne 1 ]; then
  echo "[$(ts)] 后端启动失败：120 秒内未监听 9000，停止本轮预热" >> "$LOG"
  kill "$UVPID" 2>/dev/null || true
  wait "$UVPID" 2>/dev/null || true
  exit 1
fi

echo "[$(ts)] 预热 US-Quant 行情缓存（scanner）..." >> "$LOG"
WARMUP_FILE=$(mktemp /tmp/airobot_warmup.XXXXXX)
trap 'rm -f "$WARMUP_FILE"' EXIT
for i in $(seq 1 3); do
  if /usr/bin/curl -fsS --max-time 60 "http://127.0.0.1:9000/api/us-quant/scanner?symbols=AAPL,MSFT,GOOGL,AMZN,NVDA,TSLA,META,TSM" -o "$WARMUP_FILE"; then
    CNT=$("$PYTHON" -c "import json,sys;d=json.load(open(sys.argv[1]));print(d.get('count',0))" "$WARMUP_FILE" 2>/dev/null || echo "0")
  else
    CNT=0
  fi
  if [ "${CNT:-0}" -gt 0 ] 2>/dev/null; then
    echo "[$(ts)] 预热完成（第 $i 轮，scanner=$CNT/8）" >> "$LOG"
    break
  fi
  echo "[$(ts)] 预热第 $i 轮不足（scanner=${CNT:-0}），重试..." >> "$LOG"
  sleep $((i * 3))
done

wait $UVPID
