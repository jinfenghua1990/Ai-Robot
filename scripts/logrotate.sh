#!/bin/bash
# AIROBOT 日志轮转脚本（每日 04:00 由 LaunchAgent 触发）
# 策略：超 50MB 的日志压缩为 .1，超 200MB 直接清空（保留下最近一次）
set -u
LOG=/tmp/airobot_logrotate_run.log
ts() { date '+%Y-%m-%d %H:%M:%S'; }
echo "[$(ts)] 日志轮转开始" >> "$LOG"

# airobot_backend.log 已由 autostart.sh 内 rotatelogs 按 10MB/7 份自动轮转
for f in /tmp/airobot_autostart.log /tmp/airobot_backend_debug.log; do
    [ -f "$f" ] || continue
    size=$(/bin/ls -l "$f" 2>/dev/null | /usr/bin/awk '{print $5}')
    size_mb=$((size / 1024 / 1024))
    if [ "$size_mb" -gt 200 ]; then
        # 超过 200MB：保留最后 5MB，其余清空
        /usr/bin/tail -c 5242880 "$f" > "$f.tmp" && /bin/mv "$f.tmp" "$f"
        echo "[$(ts)] $f: ${size_mb}MB → 5MB（紧急截断）" >> "$LOG"
    elif [ "$size_mb" -gt 50 ]; then
        # 50-200MB：滚动为 .1
        if [ -f "$f.1" ]; then
            /bin/rm -f "$f.1"
        fi
        /bin/mv "$f" "$f.1"
        : > "$f"
        echo "[$(ts)] $f: ${size_mb}MB → 滚动到 $f.1" >> "$LOG"
    fi
done

# 清理 30 天前的旧日志（保留 rotatelogs 自动管理的 backend.log.* 备份）
/usr/bin/find /tmp -maxdepth 1 \( -name "airobot_autostart.log.*" -o -name "airobot_backend_debug.log.*" \) -mtime +30 -delete 2>/dev/null
/usr/bin/find /tmp -maxdepth 1 -name "airobot_*.log" -mtime +90 -delete 2>/dev/null
echo "[$(ts)] 日志轮转结束" >> "$LOG"
