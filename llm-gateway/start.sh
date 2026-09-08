#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ENV_FILE="/Users/gino/Projects/AIROBOT/.env"
if [ -f "$ENV_FILE" ]; then
  export LLM_API_KEY="$(sed -n 's/^LLM_API_KEY=//p' "$ENV_FILE" | head -1)"
  export LLM_MODEL="$(sed -n 's/^LLM_MODEL=//p' "$ENV_FILE" | head -1)"
  export LLM_UPSTREAM_BASE_URL="$(sed -n 's/^LLM_UPSTREAM_BASE_URL=//p' "$ENV_FILE" | head -1)"
  export LLM_UPSTREAM_API_KEY="$(sed -n 's/^LLM_UPSTREAM_API_KEY=//p' "$ENV_FILE" | head -1)"
fi
exec "$PYTHON_BIN" -m uvicorn app:app --app-dir "$ROOT" --host 0.0.0.0 --port 9002
