#!/bin/bash
# AIROBOT 后端启动脚本
# --limit-concurrency: 限制最大并发连接数，防止积压
# --timeout-keep-alive: 空闲连接15秒后关闭，避免积压
# --access-log: 关闭访问日志提升性能
cd "$(dirname "$0")"
exec python3 -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log \
  "$@"
