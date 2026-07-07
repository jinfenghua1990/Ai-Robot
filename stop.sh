#!/bin/bash
# 停掉 AIROBOT 后端（端口 9000）
cd "$(dirname "$0")"
PIDS=$(lsof -ti :9000 -P -n 2>/dev/null)
if [ -z "$PIDS" ]; then
  echo "端口 9000 上没有进程在跑"
else
  echo "停止进程: $PIDS"
  echo "$PIDS" | xargs kill -9 2>/dev/null
  echo "已停止"
fi
