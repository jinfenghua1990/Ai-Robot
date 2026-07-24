"""AI 个股分析提供商注册中心"""
from typing import Optional

from typing import Optional
from api.hermes_native.services.ai_advice.base import BaseProvider, AnalysisReport, StockInfo

_registry: dict[str, BaseProvider] = {}


def register(provider: BaseProvider) -> BaseProvider:
    _registry[provider.key] = provider
    return provider


def get_provider(key: str) -> Optional[BaseProvider]:
    return _registry.get(key)


def list_providers() -> list[dict]:
    return [p.get_info() for p in _registry.values()]


def get_default_provider() -> Optional[BaseProvider]:
    keys = list(_registry.keys())
    return _registry.get(keys[0]) if keys else None


# 延迟导入，避免循环依赖
def _auto_register():
    from api.hermes_native.services.ai_advice.eastmoney import EastMoneyProvider
    from api.hermes_native.services.ai_advice.guoxin import GuoxinProvider
    from api.hermes_native.services.ai_advice.openclaw import OpenClawProvider
    from api.hermes_native.services.ai_advice.hermes_provider import HermesProvider
    _registry.setdefault(EastMoneyProvider.key, EastMoneyProvider())
    _registry.setdefault(GuoxinProvider.key, GuoxinProvider())
    _registry.setdefault(OpenClawProvider.key, OpenClawProvider())
    _registry.setdefault(HermesProvider.key, HermesProvider())


_auto_register()