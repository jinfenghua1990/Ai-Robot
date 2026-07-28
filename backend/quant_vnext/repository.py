from __future__ import annotations

import json
from dataclasses import asdict

from sqlalchemy import text

from .contracts import FactorValue, SignalSnapshot
from .persistence import FACTOR_VALUES_DDL, OUTCOME_DDL, RESEARCH_DDL, RESONANCE_DDL


def ensure_schema(connection) -> None:
    for statement in (FACTOR_VALUES_DDL, RESEARCH_DDL, RESONANCE_DDL, OUTCOME_DDL):
        connection.exec_driver_sql(statement)


def save_factor_values(connection, values: list[FactorValue]) -> int:
    statement = text("""
        INSERT INTO factor_values
          (ts_code, trade_date, factor_name, category, raw_value, normalized, valid, reason)
        VALUES (:ts_code, :trade_date, :factor_name, :category, :raw_value, :normalized, :valid, :reason)
        ON CONFLICT (ts_code, trade_date, factor_name) DO UPDATE SET
          raw_value=EXCLUDED.raw_value, normalized=EXCLUDED.normalized,
          valid=EXCLUDED.valid, reason=EXCLUDED.reason
    """)
    rows = []
    for value in values:
        row = asdict(value)
        row["factor_name"] = row.pop("name")
        rows.append(row)
    connection.execute(statement, rows)
    return len(values)


def save_resonance(connection, snapshot: SignalSnapshot) -> None:
    statement = text("""
        INSERT INTO resonance_snapshot
          (ts_code, trade_date, resonance_count, dimensions_json, failed_dimensions_json, eligible, reason)
        VALUES (:ts_code, :trade_date, :count, :dimensions, :failed, :eligible, :reason)
        ON CONFLICT (ts_code, trade_date) DO UPDATE SET
          resonance_count=EXCLUDED.resonance_count,
          dimensions_json=EXCLUDED.dimensions_json,
          failed_dimensions_json=EXCLUDED.failed_dimensions_json,
          eligible=EXCLUDED.eligible, reason=EXCLUDED.reason
    """)
    connection.execute(statement, {
        "ts_code": snapshot.ts_code,
        "trade_date": snapshot.trade_date,
        "count": snapshot.resonance.count,
        "dimensions": json.dumps(snapshot.resonance.dimensions, ensure_ascii=False),
        "failed": json.dumps(snapshot.resonance.failed_dimensions, ensure_ascii=False),
        "eligible": snapshot.resonance.eligible,
        "reason": snapshot.resonance.reason,
    })


def save_factor_validation(connection, rows: list[dict]) -> int:
    statement = text("""
        INSERT INTO factor_validation
          (factor_name, period_days, sample_count, ic, rank_ic, mean_forward_return, passed)
        VALUES (:factor_name, :period_days, :sample_count, :ic, :rank_ic, :mean_forward_return, :passed)
    """)
    payload = []
    for row in rows:
        payload.append({**row, "passed": row.get("rank_ic") is not None and row["rank_ic"] > 0})
    connection.execute(statement, payload)
    return len(payload)


def save_signal_outcomes(connection, rows: list[dict]) -> int:
    statement = text("""
        INSERT INTO signal_outcome
          (ts_code, signal_date, trading_state, return_1d, return_3d, return_5d, return_10d, return_20d)
        VALUES (:ts_code, :signal_date, :trading_state, :return_1d, :return_3d, :return_5d, :return_10d, :return_20d)
        ON CONFLICT (ts_code, signal_date) DO UPDATE SET
          trading_state=EXCLUDED.trading_state,
          return_1d=EXCLUDED.return_1d, return_3d=EXCLUDED.return_3d,
          return_5d=EXCLUDED.return_5d, return_10d=EXCLUDED.return_10d,
          return_20d=EXCLUDED.return_20d
    """)
    payload = []
    for row in rows:
        returns = row.get("returns", {})
        payload.append({
            "ts_code": row["ts_code"],
            "signal_date": row["signal_date"],
            "trading_state": row["trading_state"],
            "return_1d": returns.get("1"),
            "return_3d": returns.get("3"),
            "return_5d": returns.get("5"),
            "return_10d": returns.get("10"),
            "return_20d": returns.get("20"),
        })
    connection.execute(statement, payload)
    return len(payload)
