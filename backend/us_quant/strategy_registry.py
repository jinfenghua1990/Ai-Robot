"""
US Quant System — 策略注册表（插件化）

后续添加新策略只需在 STRATEGIES 中添加一条配置 + 实现 score_xxx 函数。
当前注册: 3 套传统策略 + 10 套因子策略 = 13 套
"""

from __future__ import annotations

from typing import Optional, Callable
import logging
import importlib

logger = logging.getLogger(__name__)

# ============================================================
# 策略注册表（后续扩展只需在此添加配置）
# ============================================================

STRATEGIES = [
    # ── 传统策略（us_quant.strategies）─────────────────────────────────
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
    # ── 因子策略（us_quant.factor_strategies）───────────────────────────
    {
        'key': 'momentum_factor',
        'name': '动量因子 V1',
        'icon': '📊',
        'module': 'us_quant.factor_strategies',
        'func': 'score_momentum_factor',
        'description': '中期动量+风险调整动量+短期反转+趋势确认',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'low_volatility',
        'name': '低波动率 V1',
        'icon': '🛡️',
        'module': 'us_quant.factor_strategies',
        'func': 'score_low_volatility',
        'description': '低波动+波动率收缩+低ATR+稳定趋势',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'volume_price',
        'name': '量价共振 V1',
        'icon': '📶',
        'module': 'us_quant.factor_strategies',
        'func': 'score_volume_price',
        'description': 'CMF+MFI+OBV+量比+量价趋势',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'mean_reversion',
        'name': '均值回归 V1',
        'icon': '🔄',
        'module': 'us_quant.factor_strategies',
        'func': 'score_mean_reversion',
        'description': '布林带超卖+RSI超卖+底背离+价格回归',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'value_factor',
        'name': '价值型 V1',
        'icon': '💰',
        'module': 'us_quant.factor_strategies',
        'func': 'score_value_factor',
        'description': '52周低点价值+均线偏离+布林位置+回撤深度+趋势过滤',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'quality_trend',
        'name': '质量趋势 V1',
        'icon': '⭐',
        'module': 'us_quant.factor_strategies',
        'func': 'score_quality_trend',
        'description': '趋势稳定性+收益稳定性+自相关+回撤比+加速度',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'composite_alpha',
        'name': '复合Alpha V1',
        'icon': '🎯',
        'module': 'us_quant.factor_strategies',
        'func': 'score_composite_alpha',
        'description': '动量+价值+质量+低波+量价+季节多因子共振',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'short_term_reversal',
        'name': '短期反转 V1',
        'icon': '🔁',
        'module': 'us_quant.factor_strategies',
        'func': 'score_short_term_reversal',
        'description': '1/3/5日超跌+RSI超卖+放量恐慌+支撑反弹',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'breakout_momentum',
        'name': '突破动量 V1',
        'icon': '🚀',
        'module': 'us_quant.factor_strategies',
        'func': 'score_breakout_momentum',
        'description': '价格突破+动量确认+量能放大+趋势强度+相对强度',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'seasonality_momentum',
        'name': '季节动量 V1',
        'icon': '📅',
        'module': 'us_quant.factor_strategies',
        'func': 'score_seasonality_momentum',
        'description': '月份效应+月末月初+周几效应+6个月动量+趋势排列',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'technical_indicator',
        'name': '技术指标 V1',
        'icon': '📊',
        'module': 'us_quant.factor_strategies',
        'func': 'score_technical_indicator',
        'description': 'KDJ+WILLR+ADX+CCI+AROON+DMI+Chaikin技术指标共振',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'risk_adjusted',
        'name': '风险调整 V1',
        'icon': '🛡️',
        'module': 'us_quant.factor_strategies',
        'func': 'score_risk_adjusted',
        'description': '夏普+索提诺+CVaR+下半方差+溃疡指数+下行波动',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'trend_following',
        'name': '趋势跟踪 V1',
        'icon': '📈',
        'module': 'us_quant.factor_strategies',
        'func': 'score_trend_following',
        'description': 'ADX+AROON+DMI+价格通道+资金流+EMA排列',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'volume_flow',
        'name': '成交量流动 V1',
        'icon': '📶',
        'module': 'us_quant.factor_strategies',
        'func': 'score_volume_flow',
        'description': 'A/D线+量价确认+运动轻松度+资金流比率+Chaikin',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'enhanced_technical',
        'name': '增强技术 V1',
        'icon': '⚡',
        'module': 'us_quant.factor_strategies',
        'func': 'score_enhanced_technical',
        'description': '技术+风险+量价+趋势+动量五维度综合评分',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
    {
        'key': 'allrounder_alpha',
        'name': '全能Alpha V1',
        'icon': '🎯',
        'module': 'us_quant.factor_strategies',
        'func': 'score_allrounder_alpha',
        'description': '技术+风险+量价+趋势+价值+质量+动量+季节8维共振',
        'needs_klines': True,
        'needs_market_regime': False,
        'default_params': {},
    },
]


def list_strategies() -> list[dict]:
    """返回所有策略配置的只读列表"""
    return list(STRATEGIES)


def get_strategy(key: str) -> Optional[dict]:
    """根据 key 获取策略配置"""
    for s in STRATEGIES:
        if s['key'] == key:
            return dict(s)
    return None


def _import_strategy_func(cfg: dict):
    """动态导入策略评分函数"""
    module = importlib.import_module(cfg['module'])
    return getattr(module, cfg['func'])


def run_all_strategies(**kwargs) -> list[dict]:
    """运行 STRATEGIES 中注册的所有策略，返回统一格式评分列表。

    每个元素包含:
        - key: 策略唯一标识
        - name: 策略显示名称
        - score: 总分（从返回对象的 .total 读取）
        - hard_pass: 是否通过硬条件
        - hard_fail_reasons: 硬条件失败原因列表
    """
    results = []
    for cfg in STRATEGIES:
        try:
            func = _import_strategy_func(cfg)
            score_obj = func(**kwargs)
            score = float(getattr(score_obj, 'total', 0) or 0)
            hard_pass = bool(getattr(score_obj, 'hard_pass', False))
            fail_reasons = list(getattr(score_obj, 'hard_fail_reasons', []) or [])
        except Exception as exc:
            logger.warning(f"[strategy_registry] 策略 {cfg['key']} 运行失败: {exc}")
            score = 0.0
            hard_pass = False
            fail_reasons = [f"策略运行异常: {exc}"]
        results.append({
            'key': cfg['key'],
            'name': cfg['name'],
            'score': score,
            'hard_pass': hard_pass,
            'hard_fail_reasons': fail_reasons,
        })
    return results