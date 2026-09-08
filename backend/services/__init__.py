"""AIROBOT service package bootstrap.

Safety-critical patches live here only when every existing caller must receive
the same behaviour without maintaining parallel API/scheduler implementations.
"""

# Auto-trading API and scheduler both import services.auto_trade_engine directly.
# Install the durable per-stock authorisation guard once at package load so every
# caller reaches the same fail-closed executor.
from . import auto_trade_engine as _auto_trade_engine
from .auto_trade_guard import install_auto_trade_guard

install_auto_trade_guard(_auto_trade_engine)
