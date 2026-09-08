"""Canonical market and security-code normalization."""

from __future__ import annotations

from dataclasses import dataclass


MARKET_ALIASES = {
    "A": "A",
    "CN": "A",
    "CN_A": "A",
    "A股": "A",
    "HK": "HK",
    "HKEX": "HK",
    "港股": "HK",
    "US": "US",
    "USA": "US",
    "NASDAQ": "US",
    "NYSE": "US",
    "美股": "US",
}


def normalize_market(value: str) -> str:
    market = MARKET_ALIASES.get(str(value or "").strip().upper())
    if not market:
        raise ValueError(f"unsupported market: {value}")
    return market


def normalize_symbol(market: str, value: str) -> str:
    market = normalize_market(market)
    raw = str(value or "").strip().upper().replace("$", "")
    if market == "HK":
        raw = raw.replace(".HK", "")
        if raw.startswith("HK"):
            raw = raw[2:]
        if not raw.isdigit():
            raise ValueError(f"invalid HK symbol: {value}")
        return str(int(raw)).zfill(5)
    if market == "A":
        raw = raw.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
        if not raw.isdigit() or len(raw) != 6:
            raise ValueError(f"invalid A-share symbol: {value}")
        return raw
    # Keep dots and hyphens: BRK.B, BF-B and similar US symbols are valid.
    for suffix in (".US", ".NASDAQ", ".NYSE"):
        if raw.endswith(suffix):
            raw = raw[: -len(suffix)]
    if not raw or len(raw) > 32 or any(ch.isspace() for ch in raw):
        raise ValueError(f"invalid US symbol: {value}")
    return raw


def provider_symbol(market: str, value: str) -> str:
    market = normalize_market(market)
    symbol = normalize_symbol(market, value)
    if market == "HK":
        # Yahoo/Sina use four digits for HKEX equities; the canonical DB key
        # remains five digits so 00700 cannot collide with other markets.
        return f"{int(symbol):04d}.HK"
    if market == "A":
        return symbol
    return symbol


@dataclass(frozen=True)
class InstrumentIdentity:
    market: str
    symbol: str
    provider_symbol: str
    exchange: str

    @classmethod
    def from_value(cls, market: str, value: str) -> "InstrumentIdentity":
        normalized_market = normalize_market(market)
        return cls(
            market=normalized_market,
            symbol=normalize_symbol(normalized_market, value),
            provider_symbol=provider_symbol(normalized_market, value),
            exchange={"A": "CN", "HK": "XHKG", "US": "XNAS"}[normalized_market],
        )
