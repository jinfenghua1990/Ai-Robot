"""Multi-market research and production snapshot services.

The package is deliberately separate from the legacy A-share tables.  It
provides a market/symbol keyed data layer for HK and US while keeping the
existing A-share APIs and schemas compatible.
"""

from .identity import InstrumentIdentity, normalize_market, normalize_symbol, provider_symbol
from .repository import ensure_schema

__all__ = [
    "InstrumentIdentity",
    "normalize_market",
    "normalize_symbol",
    "provider_symbol",
    "ensure_schema",
]
