#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$ROOT_DIR/backend/.venv"
PYTHON="$VENV_DIR/bin/python"
LEGACY_PY="/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python"

echo "=== AIROBOT 启动 ==="

# 1. 确保 PostgreSQL 运行（本机未安装 brew 时给出明确提示）
if command -v brew >/dev/null 2>&1; then
  brew services start postgresql@16 >/dev/null 2>&1 || true
else
  echo "提示：未找到 Homebrew，跳过 PostgreSQL 自动启动，请确认 5432 已就绪。"
fi
sleep 2

# 2. 统一使用项目 venv，避免测试环境和正式运行环境不一致
if [ ! -x "$PYTHON" ]; then
  if [ -x "$LEGACY_PY" ]; then
    BASE_PY="$LEGACY_PY"
  elif command -v python3 >/dev/null 2>&1; then
    BASE_PY="$(command -v python3)"
  else
    echo "未找到 Python，无法创建 backend/.venv" >&2
    exit 1
  fi
  "$BASE_PY" -m venv "$VENV_DIR"
fi

"$PYTHON" -m pip install -r "$ROOT_DIR/backend/requirements.txt" -q

# 3. 初始化数据库（backend 是应用真实运行根）
cd "$ROOT_DIR/backend"
"$PYTHON" -c "from db.connection import init_db; init_db()"

# 4. 构建前端
cd "$ROOT_DIR/frontend"
npm install
npm run build

# 5. 启动后端（服务 API + 前端）
cd "$ROOT_DIR/backend"
exec "$PYTHON" -m uvicorn main:app --host 0.0.0.0 --port 9000
