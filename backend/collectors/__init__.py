"""collectors package — AIROBOT 数据采集层。

包含实时行情、资金流、龙虎榜、生命周期、研报等采集器，供 API 与定时任务共用。
"""
from __future__ import annotations

import logging

logger = logging.getLogger("collectors")
