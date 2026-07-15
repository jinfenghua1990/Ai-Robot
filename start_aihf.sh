#!/bin/bash
# 启动 ai-hedge-fund (AIHF) 后端，供 AIROBOT 反向代理
# 后端跑在 8002（与 DSA 8000、AIROBOT 9000 隔离）
# 由 LaunchAgent (com.airobot.aihf, KeepAlive) 管理
set -u

PROJECT_DIR="/Users/gino/Projects/AIROBOT/stock-tools/ai-hedge-fund"
PORT=8002

# 端口守护：若已在监听则回收占用进程后再启动
# （用 kill 而非 exit，保证 LaunchAgent 的 KeepAlive 能持续自愈、且始终单实例）
if /usr/sbin/lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t >/dev/null 2>&1; then
  OLD=$(/usr/sbin/lsof -nP -iTCP:${PORT} -sTCP:LISTEN -t 2>/dev/null | head -1)
  echo "[aihf] ${PORT} 被 PID ${OLD} 占用，回收后重启"
  kill "${OLD}" 2>/dev/null || true
  for i in $(seq 1 10); do
    /usr/sbin/lsof -nP -iTCP:${PORT} -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 1
  done
fi

cd "${PROJECT_DIR}"
# 复用项目自带 venv（依赖已装好）
if [ ! -d ".venv" ]; then
  echo "[aihf] 未找到 .venv，请先安装依赖"
  exit 1
fi
source .venv/bin/activate
export PYTHONPATH="${PROJECT_DIR}"

# 导出 .env 到环境（与 /api/aihf/start 行为一致，确保 Key 始终生效，
# 即便 ai-hedge-fund 自身未自动 load_dotenv 也不影响）
if [ -f ".env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|\#*) continue ;; esac
    export "$k=$v"
  done < .env
fi

echo "[aihf] 启动后端：http://127.0.0.1:${PORT}"
exec .venv/bin/python -m uvicorn app.backend.main:app \
  --host 127.0.0.1 \
  --port ${PORT} \
  --no-access-log
