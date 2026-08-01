"""
US Quant System — 策略注册表（插件化）

后续添加新策略只需在 STRATEGIES 中添加一条配置 + 实现 score_xxx 函数。
"""

from __future__ import annotations

from typing import Optional, Callable
import logging

logger = logging.getLogger(__name__)

# ============================================================
# 策略注册表（后续扩展只需在此添加配置）
# ============================================================

STRATEGIES = [
    {
        'key': 'breakout',
        'name': '平台突破 Breakout V1',
        'icon': '📈',
        'module': 'us_quant.strategies',
        'func': 'score_breakout',
        'description': '平台整理突破 + 量能确认 + 相对强度',
        'needs_klines': True,
        'needs_market_regime': True,
        'default_params': {
            'min_breakout_score': 60,
            'volume_confirmation': True,
            'min_volume_ratio': 1.5,
        },
    },
    {
        'key': 'pullback',
        'name': '趋势回踩 Pullback V1',
        'icon': '📉',
        'module': 'us_quant.strategies',
        'func': 'score_pullback',
        'description': '中期趋势向上 + 回踩关键均线 + 缩量整理',
        'needs_klines': True,
        'needs_market_regime': True,
        'default_params': {
            'min_pullback_score': 60,
            'ema_period': 20,
            'max_pullback_pct': 8,
        },
    },
    {
        'key': 'earnings_gap',
        'name': '财报跳空 Earnings Gap V1',
        'icon': '💰',
        'module': 'us_quant.strategies',
        'func': 'score_earnings_gap',
        'description': '财报超预期跳空 + 成交量确认 + 催化剂评级',
        'needs_klines': True,
        'needs_market_regime': True,
        'default_params': {
            'min_gap_score': 60,
            'min_gap_pct': 2.0,
            'require_volume_spike': True,
        },
    },
]


def get_strategy(key: str) -> Optional[dict]:
    """按 key 获取策略元数据"""
    for s in STRATEGIES:
        if s['key'] == key:
            return dict(s)
    return None


def list_strategies() -> list[dict]:
    """列出所有已注册策略"""
    return [dict(s) for s in STRATEGIES]


def load_strategy_func(strategy: dict) -> Optional[Callable]:
    """动态加载策略评分函数（插件化加载）"""
    try:
        mod = __import__(strategy['module'], fromlist=[strategy['func']])
        func = getattr(mod, strategy['func'])
        return func
    except (ImportError, AttributeError) as e:
        logger.error(f"[strategy_registry] 加载策略 {strategy['key']} 失败: {e}")
        return None


def run_strategy(strategy_key: str, **kwargs):
    """运行单个策略，返回评分结果"""
    meta = get_strategy(key=strategy_key)
    if not meta:
        logger.warning(f"[strategy_registry] 未知策略: {strategy_key}")
        return None
    func = load_strategy_func(meta)
    if not func:
        return None
    try:
        return func(**kwargs)
    except Exception as e:
        logger.error(f"[strategy_registry] 策略 {strategy_key} 执行失败: {e}")
        return None
