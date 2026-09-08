#!/bin/bash
cd "$(dirname "$0")"
echo "=== AIROBOT 启动 ==="
# 系统 3.9 环境装有全部依赖（homebrew python3 3.14 无 uvicorn）
PY39=/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python
# 1. 确保PostgreSQL运行
brew services start postgresql@16 2>/dev/null
sleep 2
# 2. 安装后端依赖
cd backend && "$PY39" -m pip install -r requirements.txt -q
# 3. 初始化数据库
"$PY39" -c "from db.connection import init_db; init_db()"
# 4. 构建前端
cd ../frontend && npm install && npm run build
# 5. 启动后端（服务API+前端）
cd ../backend && "$PY39" -m uvicorn main:app --host 0.0.0.0 --port 9000
