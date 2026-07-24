#!/bin/bash
# AIROBOT 后端启动脚本
# --limit-concurrency: 限制最大并发连接数，防止积压
# --timeout-keep-alive: 空闲连接15秒后关闭，避免积压
# --access-log: 关闭访问日志提升性能
cd "$(dirname "$0")"

# 运行时：使用系统 Python 3.9（Hermes 后端代码已移除，不再需要 3.12 venv）
VENV_PY="$(dirname "$0")/hermes_backend/.venv/bin/python"
if [ ! -x "$VENV_PY" ]; then
  VENV_PY="python3"
fi

# 从项目根目录 .env 加载密钥与配置（避免把明文密钥写进 LaunchAgent plist）
if [ -f "$(dirname "$0")/../.env" ]; then
  set -a
  . "$(dirname "$0")/../.env"
  set +a
fi
exec "$VENV_PY" -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log \
  "$@"
