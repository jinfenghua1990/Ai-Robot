# -*- coding: utf-8 -*-
"""横盘蓄势策略包

策略核心（对齐用户方案）：
  大盘过滤 → 板块过滤 → 横盘箱体识别 → 量价健康 → 信号分类（A接近突破/B突破启动/C回踩确认/D突破失败）→ 100分评分

数据来源全部来自本地 stock_daily_kline（日线）+ concept_sectors（概念板块成分），盘后运行。
"""
from strategies.horizontal.runner import run_scan  # noqa: F401

__all__ = ["run_scan"]
