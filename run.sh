#!/bin/bash
# AIROBOT 日常启动：构建前端 + 起后端（单端口 9000）
# 用法：./run.sh   访问：http://127.0.0.1:9000
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_PY="$ROOT_DIR/backend/.venv/bin/python"
LEGACY_PY="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"

resolve_python() {
  if [ -x "$VENV_PY" ]; then
    printf '%s\n' "$VENV_PY"
    return 0
  fi
  if [ -x "$LEGACY_PY" ] && "$LEGACY_PY" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    printf '%s\n' "$LEGACY_PY"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1 && python3 -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  echo "未找到可运行 AIROBOT 的 Python 环境。优先创建 backend/.venv 并安装 backend/requirements.txt。" >&2
  return 1
}

PYTHON="${AIROBOT_PYTHON:-$(resolve_python)}"

if ! "$PYTHON" -c 'import fastapi, uvicorn' >/dev/null 2>&1; then
  echo "Python 环境缺少 fastapi/uvicorn: $PYTHON" >&2
  exit 1
fi

echo "=== 构建前端 ==="
cd "$ROOT_DIR/frontend"
npm run build

echo "=== 启动后端 (端口 9000) ==="
lsof -ti :9000 -P -n 2>/dev/null | xargs kill -9 2>/dev/null || true
cd "$ROOT_DIR/backend"
exec "$PYTHON" -m uvicorn main:app \
  --host 0.0.0.0 \
  --port 9000 \
  --limit-concurrency 200 \
  --timeout-keep-alive 15 \
  --no-access-log
