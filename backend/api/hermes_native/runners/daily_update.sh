#!/bin/bash
# 每日盘后数据更新定时任务
# 盘后15:30执行

cd /Users/gino/Projects/AIROBOT/backend/hermes_backend

# 激活虚拟环境
source .venv/bin/activate

# 运行更新脚本
python runners/daily_update.py >> /tmp/daily_update.log 2>&1