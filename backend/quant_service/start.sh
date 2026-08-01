#!/usr/bin/env bash
# Quant Service 启动脚本（独立 Python 3.11 venv，不污染 9000 主服务）。
set -e
PY=/opt/homebrew/bin/python3.11
ROOT="$(cd "$(dirname "$0")" && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
  echo "[quant] 创建 venv (Python 3.11) ..."
  "$PY" -m venv "$VENV"
fi

echo "[quant] 安装运行依赖 ..."
"$VENV/bin/pip" install -q -r "$ROOT/requirements.txt"

# 如需启用 Qlib/VectorBT（Phase 1+），取消下行注释（安装较重，建议另开终端后台跑）：
# "$VENV/bin/pip" install -q -r "$ROOT/requirements-ml.txt"

cd "$ROOT"
echo "[quant] 启动 Quant Service @ ${QUANT_HOST:-0.0.0.0}:${QUANT_PORT:-9003}"
exec "$VENV/bin/python" service.py
