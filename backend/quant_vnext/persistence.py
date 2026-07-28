from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .contracts import FactorValue, SignalSnapshot


FACTOR_VALUES_DDL = """
CREATE TABLE IF NOT EXISTS factor_values (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(20) NOT NULL,
  trade_date DATE NOT NULL,
  factor_name VARCHAR(80) NOT NULL,
  category VARCHAR(40) NOT NULL,
  raw_value DOUBLE PRECISION,
  normalized DOUBLE PRECISION,
  valid BOOLEAN NOT NULL,
  reason VARCHAR(120),
  UNIQUE (ts_code, trade_date, factor_name)
);
"""

RESEARCH_DDL = """
CREATE TABLE IF NOT EXISTS factor_validation (
  id BIGSERIAL PRIMARY KEY,
  factor_name VARCHAR(80) NOT NULL,
  period_days INTEGER NOT NULL,
  sample_count INTEGER NOT NULL,
  ic DOUBLE PRECISION,
  rank_ic DOUBLE PRECISION,
  mean_forward_return DOUBLE PRECISION,
  passed BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);
"""

RESONANCE_DDL = """
CREATE TABLE IF NOT EXISTS resonance_snapshot (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(20) NOT NULL,
  trade_date DATE NOT NULL,
  resonance_count INTEGER NOT NULL,
  dimensions_json TEXT NOT NULL,
  failed_dimensions_json TEXT NOT NULL,
  eligible BOOLEAN NOT NULL,
  reason VARCHAR(500),
  UNIQUE (ts_code, trade_date)
);
"""

OUTCOME_DDL = """
CREATE TABLE IF NOT EXISTS signal_outcome (
  id BIGSERIAL PRIMARY KEY,
  ts_code VARCHAR(20) NOT NULL,
  signal_date DATE NOT NULL,
  trading_state VARCHAR(20) NOT NULL,
  return_1d DOUBLE PRECISION,
  return_3d DOUBLE PRECISION,
  return_5d DOUBLE PRECISION,
  return_10d DOUBLE PRECISION,
  return_20d DOUBLE PRECISION,
  max_profit DOUBLE PRECISION,
  max_loss DOUBLE PRECISION,
  max_drawdown DOUBLE PRECISION,
  UNIQUE (ts_code, signal_date)
);
"""


def factor_row(value: FactorValue) -> dict[str, Any]:
    return asdict(value)


def signal_row(snapshot: SignalSnapshot) -> dict[str, Any]:
    data = asdict(snapshot)
    data["resonance"] = asdict(snapshot.resonance)
    data["dimensions"] = {key: asdict(value) for key, value in snapshot.dimensions.items()}
    return data
