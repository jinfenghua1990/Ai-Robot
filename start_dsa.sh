#!/bin/bash
# 启动 daily_stock_analysis (DSA) 后端，供 AIROBOT 反向代理
# DSA server.py 硬编码端口 8000，与 AIROBOT 9000 隔离
# 用法：./start_dsa.sh
set -e
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
DSA_DIR="${PROJECT_DIR}/.dsa"

# 端口守护：若 8000 已被占用，回收占用进程后再启动
# （用 kill 而非 exit，保证 LaunchAgent 的 KeepAlive 能持续自愈、且始终单实例）
if /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
  OLD=$(/usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1)
  echo "[dsa] 8000 被 PID ${OLD} 占用，回收后重启"
  kill "${OLD}" 2>/dev/null || true
  for i in $(seq 1 10); do
    /usr/sbin/lsof -nP -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
fi

cd "${DSA_DIR}"

# 首次运行：安装依赖（使用 Python 3.11+）
if [ ! -d ".venv" ]; then
    echo "首次运行，创建虚拟环境并安装依赖..."
    PYTHON_BIN="${PYTHON_BIN:-python3.11}"
    if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
        PYTHON_BIN="python3"
    fi
    "$PYTHON_BIN" -m venv .venv
    . .venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    . .venv/bin/activate
fi

# 复制环境变量模板
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "已生成 .env，请编辑 ${DSA_DIR}/.env 配置 AI 模型 Key、通知渠道等"
fi

export CORS_ALLOW_ALL=true
export ADMIN_AUTH_ENABLED=false

echo "启动 DSA 后端：http://127.0.0.1:8000"
echo "API 文档：http://127.0.0.1:8000/docs"
# 日志轮转：单文件 10MB，保留 5 个备份
exec python server.py 2>&1 | /usr/sbin/rotatelogs -l -f -n 5 /tmp/airobot_dsa.log 10M
