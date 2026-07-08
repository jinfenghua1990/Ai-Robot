#!/bin/bash
# 启动 Hermes Cockpit 后端，供 AIROBOT 反向代理
# Hermes 后端独立运行在 127.0.0.1:8788，AIROBOT 通过 /_hermes/api/* 代理
# 用法：./start_hermes.sh
set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
HERMES_DIR="${PROJECT_DIR}/.hermes"

if [ ! -d "$HERMES_DIR/backend" ]; then
    echo "❌ Hermes 目录不存在：$HERMES_DIR"
    exit 1
fi

# 优先复用 hermes-cockpit 项目的 venv（与当前已运行进程一致）
HERMES_VENV="/Users/gino/Projects/hermes-cockpit/backend/.venv/bin/python"
# 备选：robot-1 专用 venv
ROBOT_VENV="/Users/gino/.hermes/robot-1/.venv/bin/python"

if [ -x "$HERMES_VENV" ]; then
    PYTHON="$HERMES_VENV"
elif [ -x "$ROBOT_VENV" ]; then
    PYTHON="$ROBOT_VENV"
elif [ -x "/opt/homebrew/bin/python3.11" ]; then
    PYTHON="/opt/homebrew/bin/python3.11"
else
    PYTHON="python3"
fi

# 从 .env 加载配置
if [ -f "$HERMES_DIR/.env" ]; then
    set -a
    source "$HERMES_DIR/.env"
    set +a
fi

# 默认值（与 .hermes/start.sh 保持一致）
COCKPIT_PORT="${COCKPIT_PORT:-8788}"
COCKPIT_HOST="${COCKPIT_HOST:-127.0.0.1}"
HERMES_HOME="${HERMES_HOME:-/Users/gino/.hermes}"

# 端口占用检查
if lsof -nP -iTCP:"$COCKPIT_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    EXISTING_PID=$(lsof -nP -iTCP:"$COCKPIT_PORT" -sTCP:LISTEN -t 2>/dev/null | head -1)
    echo "⚠️  端口 $COCKPIT_PORT 已被占用（PID=$EXISTING_PID），Hermes 后端可能已在运行"
    echo "   如需重启：kill $EXISTING_PID && ./start_hermes.sh"
    exit 0
fi

# 装依赖（如缺）
$PYTHON -c "import fastapi" 2>/dev/null || {
    echo "⚠️  缺少 fastapi，正在装依赖..."
    $PYTHON -m pip install -r "$HERMES_DIR/backend/requirements.txt"
}

# 数据库搜索路径
export PYTHONPATH="$HERMES_HOME/database:$PYTHONPATH"
export HERMES_HOME
export COCKPIT_PORT
export COCKPIT_HOST

echo "🚀 启动 Hermes Cockpit 后端..."
echo "   Python: $PYTHON"
echo "   端口: $COCKPIT_PORT"
echo "   HERMES_HOME: $HERMES_HOME"
echo "   后端目录: $HERMES_DIR/backend"
echo "   前端目录: $HERMES_DIR/frontend/dist"
echo "   AIROBOT 反向代理：http://127.0.0.1:9000/_hermes/"
echo

cd "$HERMES_DIR/backend"
exec $PYTHON -m uvicorn main:app --host "$COCKPIT_HOST" --port "$COCKPIT_PORT"
