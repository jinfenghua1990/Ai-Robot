#!/bin/bash
# AIROBOT 日常启动：构建前端 + 起后端（单端口 9000）
# 用法：./run.sh   访问：http://127.0.0.1:9000
cd "$(dirname "$0")"
set -e

echo "=== 构建前端 ==="
cd frontend && npm run build && cd ..

echo "=== 启动后端 (端口 9000) ==="
# 先停掉可能在跑的旧进程
lsof -ti :9000 -P -n 2>/dev/null | xargs kill -9 2>/dev/null || true
cd backend && exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log
