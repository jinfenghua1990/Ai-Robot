#!/bin/bash
# 一键将 AIROBOT Vibe-Research MCP Server 注册到 Claude Code
# 用法：./backend/mcp/register.sh
set -e

PROJECT_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="${PROJECT_DIR}/backend/.venv/bin/python"

# 优先使用虚拟环境 Python；若不存在则回退系统 python3
if [ ! -x "$PYTHON" ]; then
    PYTHON="$(which python3 || which python || echo '')"
fi

if [ -z "$PYTHON" ]; then
    echo "❌ 未找到可用的 Python 解释器"
    exit 1
fi

echo "Using Python: $PYTHON"
echo "MCP Server:   ${PROJECT_DIR}/backend/mcp/vibe_mcp_server.py"

claude mcp add airobat-vibe -- "$PYTHON" "${PROJECT_DIR}/backend/mcp/vibe_mcp_server.py"
echo "✅ 已注册 airobat-vibe MCP Server"
echo ""
echo "使用方式：在 Claude Code 对话中，模型会自动调用 query_vibe_* 工具获取 Vibe 数据。"
echo "确保 AIROBOT 后端已在 127.0.0.1:9000 运行，否则工具会返回错误。"
