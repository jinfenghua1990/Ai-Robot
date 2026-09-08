#!/bin/bash
# 重新构建 Vibe / DSA / Hermes 前端并复制到后端静态目录
# 关键：每次 cp 前先 rm -rf，避免旧 build 文件残留
set -eu
cd "$(dirname "$0")/../.."

AIROBOT_ROOT=/Users/gino/Projects/AIROBOT
STATIC=$AIROBOT_ROOT/backend/static

# Vibe-Research
echo "==> Vibe-Research"
cd $AIROBOT_ROOT/.vibe-research/frontend
rm -rf dist
npm run build > /tmp/build_vibe.log 2>&1
rm -rf $STATIC/vibe
cp -R dist $STATIC/vibe
echo "    Vibe: $(/bin/ls $STATIC/vibe/assets/ | /usr/bin/grep '^index' | /usr/bin/tr '\n' ' ')"

# DSA
echo "==> DSA"
cd $AIROBOT_ROOT/.dsa/apps/dsa-web
rm -rf dist
npm run build > /tmp/build_dsa.log 2>&1
rm -rf $STATIC/dsa
cp -R dist $STATIC/dsa
echo "    DSA: $(/bin/ls $STATIC/dsa/assets/ | /usr/bin/grep '^index' | /usr/bin/tr '\n' ' ')"

# Hermes
echo "==> Hermes"
cd $AIROBOT_ROOT/.hermes/frontend
rm -rf dist
npm run build > /tmp/build_hermes.log 2>&1
rm -rf $STATIC/hermes
cp -R dist $STATIC/hermes
echo "    Hermes: $(/bin/ls $STATIC/hermes/assets/ | /usr/bin/grep '^index' | /usr/bin/tr '\n' ' ')"

# AIROBOT frontend
echo "==> AIROBOT"
cd $AIROBOT_ROOT/frontend
rm -rf dist
npx vite build > /tmp/build_airobot.log 2>&1
echo "    AIROBOT: $(/bin/ls dist/assets/ 2>/dev/null | /usr/bin/grep '^index' | /usr/bin/tr '\n' ' ')"

echo "==> 全部构建完成。AIROBOT dist 在 $AIROBOT_ROOT/frontend/dist，需要手动 cp 到后端静态。"
