#!/bin/bash
# 安全停止 AIROBOT 后端（端口 9000）
set -u

PIDS=$(lsof -ti :9000 -P -n 2>/dev/null || true)
if [ -z "$PIDS" ]; then
  echo "端口 9000 上没有进程在跑"
  exit 0
fi

AIROBOT_PIDS=""
UNKNOWN=""
for pid in $PIDS; do
  cmd=$(ps -p "$pid" -o command= 2>/dev/null || true)
  case "$cmd" in
    *uvicorn*main:app*) AIROBOT_PIDS="$AIROBOT_PIDS $pid" ;;
    *) UNKNOWN="$UNKNOWN $pid" ;;
  esac
done

if [ -n "${UNKNOWN// /}" ] && [ "${AIROBOT_FORCE_STOP_PORT:-0}" != "1" ]; then
  echo "拒绝停止：端口 9000 存在非 AIROBOT 进程:${UNKNOWN}" >&2
  for pid in $UNKNOWN; do
    ps -p "$pid" -o pid=,command= 2>/dev/null >&2 || true
  done
  echo "确认必须释放端口时，可设置 AIROBOT_FORCE_STOP_PORT=1 后重试。" >&2
  exit 2
fi

TARGETS="$AIROBOT_PIDS"
if [ "${AIROBOT_FORCE_STOP_PORT:-0}" = "1" ]; then
  TARGETS="$PIDS"
fi
TARGETS=$(echo "$TARGETS" | xargs 2>/dev/null || true)

if [ -z "$TARGETS" ]; then
  echo "没有识别到 AIROBOT uvicorn 进程"
  exit 0
fi

echo "停止 AIROBOT 进程: $TARGETS"
kill $TARGETS 2>/dev/null || true

for _ in $(seq 1 15); do
  alive=""
  for pid in $TARGETS; do
    kill -0 "$pid" 2>/dev/null && alive="$alive $pid"
  done
  [ -z "${alive// /}" ] && break
  sleep 1
done

alive=""
for pid in $TARGETS; do
  kill -0 "$pid" 2>/dev/null && alive="$alive $pid"
done
if [ -n "${alive// /}" ]; then
  echo "进程未在 15 秒内退出，强制回收:$alive"
  kill -9 $alive 2>/dev/null || true
fi

echo "AIROBOT 已停止"
