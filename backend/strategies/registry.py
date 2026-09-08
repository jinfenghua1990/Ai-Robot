#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""选股策略统一注册表（轻量统一接口）。

设计目标：把分散在 6 个文件里的选股策略收敛到一个可枚举、可统一调用的清单，
为后续「UI 自定义信号 / AI 生成策略」铺设统一入口。

说明：
- 本模块 **不** 强制各策略改为类继承，而是用函数式注册表描述每个策略的
  (name, 单票分析函数, 批量扫描函数)，对现有实现零侵入、零回归。
- 各策略模块通过 importlib 延迟导入，避免包内循环依赖。
- 数据源统一走 strategies.data_feed，指标统一走 strategies._shared。
"""
import importlib
import logging
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 每项策略的元数据。strategy=单票分析函数名(接收 kline, day_index=-1 -> dict|None)，
# screen=批量扫描函数名(接收 stock_list -> list[dict])。
_STRATEGY_REGISTRY: List[Dict] = [
    {'name': 'baihu_v30', 'module': 'strategies.baihu_v30',
     'strategy': 'baihu_strategy_v30', 'screen': 'run_baihu_v30_screen'},
    {'name': 'liangjia_report', 'module': 'strategies.liangjia_report',
     'strategy': 'liangjia_report_strategy', 'screen': 'run_liangjia_report_screen'},
    {'name': 'macd_golden_cross', 'module': 'strategies.macd_golden_cross',
     'strategy': 'macd_golden_cross_strategy', 'screen': 'run_macd_golden_cross_screen'},
    {'name': 'qinglong', 'module': 'strategies.qinglong',
     'strategy': 'qinglong_strategy', 'screen': 'run_qinglong_screen'},
    {'name': 'risk_exit', 'module': 'strategies.risk_exit',
     'strategy': 'risk_exit_check', 'screen': 'run_risk_exit_screen'},
    {'name': 'rsi_bounce', 'module': 'strategies.rsi_bounce',
     'strategy': 'rsi_bounce_strategy', 'screen': 'run_rsi_bounce_screen'},
]


def list_strategies() -> List[str]:
    """返回所有已注册策略名称。"""
    return [s['name'] for s in _STRATEGY_REGISTRY]


def get_strategy(name: str) -> Optional[Dict]:
    """按名称取策略元数据；不存在返回 None。"""
    for s in _STRATEGY_REGISTRY:
        if s['name'] == name:
            return s
    return None


def _load_screen_fn(name: str) -> Optional[Callable]:
    """延迟导入指定策略的批量扫描函数。"""
    meta = get_strategy(name)
    if not meta:
        return None
    try:
        mod = importlib.import_module(meta['module'])
        return getattr(mod, meta['screen'], None)
    except Exception as e:
        logger.warning(f"[registry] 加载策略 {name} 失败: {e}")
        return None


def run_strategy(name: str, stock_list, trade_date=None):
    """运行单个策略的批量扫描，返回命中结果列表。"""
    fn = _load_screen_fn(name)
    if not fn:
        return []
    try:
        return fn(stock_list, trade_date=trade_date) if trade_date is not None else fn(stock_list)
    except Exception as e:
        logger.warning(f"[registry] 运行策略 {name} 失败: {e}")
        return []


def run_all(stock_list, trade_date=None) -> Dict[str, list]:
    """运行全部策略，返回 {策略名: 命中列表}。"""
    out: Dict[str, list] = {}
    for s in _STRATEGY_REGISTRY:
        out[s['name']] = run_strategy(s['name'], stock_list, trade_date)
    return out
