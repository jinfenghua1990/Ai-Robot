"""collectors package — AIROBOT 数据采集层。

包含实时行情、资金流、龙虎榜、生命周期、研报等采集器，供 API 与定时任务共用。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("collectors")

# 对历史扩展采集器应用小范围正确性修复。放在 package 初始化阶段，确保
# `from collectors.extended_collectors import ...` 也拿到修复后的函数。
try:
    from collectors.extended_runtime_fixes import apply_extended_collector_fixes

    apply_extended_collector_fixes()
except Exception:
    # 不能因为备用数据源补丁失败阻断主采集链；preflight/pytest 会把问题暴露出来。
    logger.exception("failed to apply extended collector runtime fixes")
