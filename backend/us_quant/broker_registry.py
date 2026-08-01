"""
券商插件注册表

V2.2: 券商统一通过注册表管理，后续添加新券商只需在 BROKERS 中添加配置。

用法:
    from us_quant.broker_registry import get_broker, list_brokers
    broker = get_broker("IBKR")  # 获取盈透证券配置
    broker["place_order"](symbol="AAPL", qty=100, side="BUY")
"""

from __future__ import annotations

import logging
from typing import Optional, Callable
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class BrokerConfig:
    """券商配置"""
    key: str
    name: str
    region: str              # US / CN / HK
    api_type: str            # REST / FIX / WebSocket
    base_url: str = ""
    requires_auth: bool = True
    supports_paper_trading: bool = False
    default_currency: str = "USD"
    env_prefix: str = ""     # 环境变量前缀，如 "IBKR_"
    features: list[str] = field(default_factory=lambda: ["market_order", "limit_order", "stop_order"])
    module: str = ""         # 插件模块路径
    order_func: str = ""     # 下单函数名
    account_func: str = ""   # 账户查询函数名


# ═══════════════════════════════════════════════════════════════
# 注册表（后续扩展只需在此添加配置）
# ═══════════════════════════════════════════════════════════════

BROKERS: dict[str, BrokerConfig] = {
    "IBKR": BrokerConfig(
        key="IBKR",
        name="盈透证券 Interactive Brokers",
        region="US",
        api_type="REST",
        base_url="https://api.ibkr.com/v1/api",
        env_prefix="IBKR_",
        supports_paper_trading=True,
        features=["market_order", "limit_order", "stop_order", "trailing_stop", "option_trading"],
        module="us_quant.brokers.ibkr",
        order_func="place_order",
        account_func="get_account_summary",
    ),
    "ALPACA": BrokerConfig(
        key="ALPACA",
        name="Alpaca Trading",
        region="US",
        api_type="REST",
        base_url="https://paper-api.alpaca.markets",
        env_prefix="ALPACA_",
        supports_paper_trading=True,
        features=["market_order", "limit_order", "stop_order", "algorithmic_trading"],
        module="us_quant.brokers.alpaca",
        order_func="place_order",
        account_func="get_account",
    ),
    "MX": BrokerConfig(
        key="MX",
        name="东方财富妙想",
        region="CN",
        api_type="WebSocket",
        base_url="wss://push.eastmoney.com",
        env_prefix="MX_",
        features=["watchlist_sync", "market_data", "portfolio"],
        module="us_quant.brokers.mx",
        order_func="place_order",
        account_func="get_portfolio",
    ),
    "SIMULATED": BrokerConfig(
        key="SIMULATED",
        name="模拟交易",
        region="US",
        api_type="REST",
        base_url="",
        requires_auth=False,
        default_currency="USD",
        features=["market_order", "limit_order", "stop_order"],
        module="",
        order_func="",
        account_func="",
    ),
}


def get_broker(key: str) -> Optional[BrokerConfig]:
    """按 key 获取券商配置"""
    return BROKERS.get(key.upper())


def list_brokers() -> list[dict]:
    """列出所有注册券商"""
    return [
        {
            "key": b.key, "name": b.name, "region": b.region,
            "api_type": b.api_type, "supports_paper": b.supports_paper_trading,
            "features": b.features, "default_currency": b.default_currency,
        }
        for b in BROKERS.values()
    ]


def load_broker_module(broker: BrokerConfig) -> Optional[object]:
    """动态加载券商插件模块

    返回模块对象，可通过 getattr 获取下单/查询函数。
    """
    if not broker.module:
        logger.warning(f"[broker_registry] {broker.key} 没有配置插件模块")
        return None
    try:
        mod = __import__(broker.module, fromlist=[""])
        return mod
    except ImportError as e:
        logger.error(f"[broker_registry] 加载 {broker.key} 模块失败: {e}")
        return None


def get_active_broker() -> Optional[BrokerConfig]:
    """获取当前活跃券商（通过环境变量或配置检测）"""
    import os
    # 优先级: IBKR > ALPACA > MX > SIMULATED
    for key in ["IBKR", "ALPACA", "MX"]:
        broker = get_broker(key)
        if broker and broker.env_prefix:
            # 检查对应环境变量是否存在
            token = os.getenv(f"{broker.env_prefix}TOKEN") or os.getenv(f"{broker.env_prefix}API_KEY")
            if token:
                return broker
    return get_broker("SIMULATED")