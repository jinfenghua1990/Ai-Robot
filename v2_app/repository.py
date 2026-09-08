from __future__ import annotations

import json
from datetime import date, datetime

from sqlalchemy import text

from .db import engine
from .engine import serialize_signal
from .factors import DIMENSION_LABELS, FACTOR_CATALOG, FACTOR_STATUS_LABELS, FACTOR_STATUSES


DDL = [
    """
    CREATE TABLE IF NOT EXISTS v2_factor_values (
      code VARCHAR(20) NOT NULL,
      trade_date DATE NOT NULL,
      factor_name VARCHAR(80) NOT NULL,
      category VARCHAR(40) NOT NULL,
      raw_value DOUBLE PRECISION,
      normalized DOUBLE PRECISION,
      valid BOOLEAN NOT NULL,
      reason VARCHAR(200),
      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
      PRIMARY KEY (code, trade_date, factor_name)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_signal_snapshots (
      code VARCHAR(20) NOT NULL,
      trade_date DATE NOT NULL,
      name VARCHAR(80),
      sector VARCHAR(80),
      rank INTEGER,
      factor_score DOUBLE PRECISION,
      resonance_count INTEGER NOT NULL,
      resonance_dimensions_json TEXT NOT NULL,
      failed_dimensions_json TEXT NOT NULL,
      eligible BOOLEAN NOT NULL,
      resonance_reason VARCHAR(500),
      patterns_json TEXT NOT NULL,
      lifecycle VARCHAR(20),
      trading_state VARCHAR(20),
      valid_until DATE,
      market_state VARCHAR(20),
      reasons_json TEXT NOT NULL,
      score_mode VARCHAR(30) NOT NULL DEFAULT 'RESEARCH',
      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
      PRIMARY KEY (code, trade_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_factor_registry (
      factor_name VARCHAR(80) PRIMARY KEY,
      label VARCHAR(120) NOT NULL,
      category VARCHAR(40) NOT NULL,
      source VARCHAR(160),
      validity VARCHAR(20) NOT NULL DEFAULT 'research',
      allow_production BOOLEAN NOT NULL DEFAULT FALSE,
      formula TEXT,
      inputs_json TEXT NOT NULL,
      period INTEGER,
      direction SMALLINT NOT NULL,
      status VARCHAR(20) NOT NULL DEFAULT 'observation',
      enabled_in_score BOOLEAN NOT NULL DEFAULT TRUE,
      status_reason VARCHAR(500),
      first_seen DATE NOT NULL DEFAULT CURRENT_DATE,
      last_reviewed DATE,
      updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_factor_validation (
      id BIGSERIAL PRIMARY KEY,
      factor_name VARCHAR(80) NOT NULL,
      horizon INTEGER NOT NULL,
      sample_count INTEGER NOT NULL,
      ic DOUBLE PRECISION,
      rank_ic DOUBLE PRECISION,
      icir DOUBLE PRECISION,
      mean_forward_return DOUBLE PRECISION,
      cost_adjusted_return DOUBLE PRECISION,
      missing_rate DOUBLE PRECISION,
      outlier_rate DOUBLE PRECISION,
      monotonicity DOUBLE PRECISION,
      quantile_returns_json TEXT,
      top_quantile_return DOUBLE PRECISION,
      bottom_quantile_return DOUBLE PRECISION,
      max_profit DOUBLE PRECISION,
      max_loss DOUBLE PRECISION,
      max_drawdown DOUBLE PRECISION,
      market_state_json TEXT,
      correlation_mean_abs DOUBLE PRECISION,
      future_function BOOLEAN NOT NULL DEFAULT FALSE,
      price_basis VARCHAR(20) NOT NULL DEFAULT 'raw',
      passed BOOLEAN NOT NULL,
      validation_status VARCHAR(20) NOT NULL DEFAULT 'observation',
      recommended_status VARCHAR(20) NOT NULL DEFAULT 'observation',
      validation_reason VARCHAR(1000),
      research_universe INTEGER,
      research_days INTEGER,
      created_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_signal_outcomes (
      code VARCHAR(20) NOT NULL,
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
      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
      PRIMARY KEY (code, signal_date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_trade_config (
      id INTEGER PRIMARY KEY,
      enabled BOOLEAN NOT NULL DEFAULT FALSE,
      account_source VARCHAR(20) NOT NULL DEFAULT 'displayed',
      max_positions INTEGER NOT NULL DEFAULT 10,
      max_buy_count INTEGER NOT NULL DEFAULT 5,
      single_position_pct DOUBLE PRECISION NOT NULL DEFAULT 10,
      stop_loss_pct DOUBLE PRECISION NOT NULL DEFAULT -6,
      take_profit_pct DOUBLE PRECISION NOT NULL DEFAULT 15,
      updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS v2_trade_audit (
      id BIGSERIAL PRIMARY KEY,
      trade_date DATE NOT NULL,
      signal_date DATE,
      account_source VARCHAR(20),
      code VARCHAR(20),
      name VARCHAR(80),
      action VARCHAR(10) NOT NULL,
      reason VARCHAR(500),
      factor_score DOUBLE PRECISION,
      resonance_count INTEGER,
      trading_state VARCHAR(20),
      quantity INTEGER,
      requested_price DOUBLE PRECISION,
      filled_quantity INTEGER DEFAULT 0,
      filled_price DOUBLE PRECISION,
      order_id VARCHAR(100),
      status VARCHAR(20) NOT NULL,
      fill_status VARCHAR(20),
      raw_result TEXT,
      created_at TIMESTAMP NOT NULL DEFAULT NOW(),
      updated_at TIMESTAMP NOT NULL DEFAULT NOW()
    )
    """,
]


def ensure_schema() -> None:
    with engine.begin() as conn:
        for statement in DDL:
            conn.execute(text(statement))
        # Existing V2 databases were created with the smaller validation
        # schema.  Keep the migration additive and safe to run on every
        # startup.
        conn.execute(text(
            "ALTER TABLE v2_signal_snapshots "
            "ADD COLUMN IF NOT EXISTS score_mode VARCHAR(30) NOT NULL DEFAULT 'RESEARCH'"
        ))
        for table, columns in {
            "v2_factor_registry": {
                "validity": "VARCHAR(20) NOT NULL DEFAULT 'research'",
                "allow_production": "BOOLEAN NOT NULL DEFAULT FALSE",
            },
            "v2_factor_validation": {
                "future_function": "BOOLEAN NOT NULL DEFAULT FALSE",
                "price_basis": "VARCHAR(20) NOT NULL DEFAULT 'raw'",
            },
        }.items():
            for column, definition in columns.items():
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}"))
        for column, definition in {
            "icir": "DOUBLE PRECISION",
            "cost_adjusted_return": "DOUBLE PRECISION",
            "missing_rate": "DOUBLE PRECISION",
            "outlier_rate": "DOUBLE PRECISION",
            "monotonicity": "DOUBLE PRECISION",
            "quantile_returns_json": "TEXT",
            "top_quantile_return": "DOUBLE PRECISION",
            "bottom_quantile_return": "DOUBLE PRECISION",
            "max_profit": "DOUBLE PRECISION",
            "max_loss": "DOUBLE PRECISION",
            "max_drawdown": "DOUBLE PRECISION",
            "market_state_json": "TEXT",
            "correlation_mean_abs": "DOUBLE PRECISION",
            "validation_status": "VARCHAR(20) NOT NULL DEFAULT 'observation'",
            "recommended_status": "VARCHAR(20) NOT NULL DEFAULT 'observation'",
            "validation_reason": "VARCHAR(1000)",
        }.items():
            conn.execute(text(f"ALTER TABLE v2_factor_validation ADD COLUMN IF NOT EXISTS {column} {definition}"))
        conn.execute(text("""
            INSERT INTO v2_trade_config (id) VALUES (1)
            ON CONFLICT (id) DO NOTHING
        """))
        for item in FACTOR_CATALOG:
            conn.execute(text("""
                INSERT INTO v2_factor_registry
                  (factor_name, label, category, source, validity, allow_production,
                   formula, inputs_json, period, direction, status, enabled_in_score,
                   status_reason)
                VALUES (:factor_name, :label, :category, :source, :validity,
                        :allow_production, :formula, :inputs_json, :period, :direction,
                        :status, :enabled_in_score, :status_reason)
                ON CONFLICT (factor_name) DO NOTHING
            """), {
                "factor_name": item.name,
                "label": item.label,
                "category": item.category,
                "source": item.source,
                "validity": item.validity,
                "allow_production": item.allow_production,
                "formula": item.formula,
                "inputs_json": json.dumps(list(item.inputs), ensure_ascii=False),
                "period": item.period,
                "direction": item.direction,
                "status": item.status,
                "enabled_in_score": item.status in {"observation", "production"},
                "status_reason": "已实现公式，等待滚动样本外验证",
            })


def factor_registry() -> list[dict]:
    ensure_schema()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT * FROM v2_factor_registry ORDER BY category, factor_name
        """)).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        item["inputs"] = json.loads(item.pop("inputs_json") or "[]")
        item["category_label"] = DIMENSION_LABELS.get(item.get("category"), item.get("category"))
        item["status_label"] = FACTOR_STATUS_LABELS.get(item.get("status"), item.get("status"))
        item["production"] = item.get("status") == "production"
        result.append(item)
    return result


def factor_status_summary() -> dict:
    rows = factor_registry()
    summary = {status: 0 for status in FACTOR_STATUSES}
    for row in rows:
        summary[row.get("status", "candidate")] = summary.get(row.get("status", "candidate"), 0) + 1
    return summary


def latest_factor_reviews(limit: int = 500) -> list[dict]:
    ensure_schema()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT DISTINCT ON (factor_name) *
              FROM v2_factor_validation
             ORDER BY factor_name, created_at DESC
        """)).mappings().all()
    result = [dict(row) for row in rows]
    result.sort(key=lambda row: (row.get("recommended_status") or "", abs(row.get("rank_ic") or 0)), reverse=True)
    return result[:max(1, min(limit, 1000))]


def active_factor_names(prefer_production: bool = True) -> tuple[set[str], str, dict]:
    rows = factor_registry()
    summary = {status: 0 for status in FACTOR_STATUSES}
    for row in rows:
        summary[row.get("status", "candidate")] = summary.get(row.get("status", "candidate"), 0) + 1
    production = {
        row["factor_name"] for row in rows
        if row.get("status") == "production"
        and row.get("enabled_in_score")
        and row.get("allow_production", True)
    }
    observation = {row["factor_name"] for row in rows if row.get("status") == "observation" and row.get("enabled_in_score")}
    if prefer_production and production:
        return production, "PRODUCTION", summary
    if observation:
        return observation, "OBSERVATION_RESEARCH", summary
    return set(), "NO_ACTIVE_FACTORS", summary


def sync_factor_reviews(result: dict) -> int:
    """Apply conservative lifecycle recommendations to the registry.

    A short research window can move a formula between candidate and
    observation, but it cannot promote a factor to production. Production
    promotion requires at least 120 research sessions/days and the explicit
    production gate calculated by the validator.
    """
    rows = result.get("rows") or []
    if not rows:
        return 0
    review_date = result.get("trade_date")
    research_days = int(result.get("research_days") or 0)
    changed = 0
    with engine.begin() as conn:
        current_rows = conn.execute(text("SELECT factor_name, status FROM v2_factor_registry")).mappings().all()
        current = {row["factor_name"]: row["status"] for row in current_rows}
        for row in rows:
            name = row["factor_name"]
            old_status = current.get(name, "candidate")
            if old_status in {"retired", "suspended"}:
                continue
            recommended = row.get("recommended_status") or "candidate"
            # A short window is for sample accumulation, not demotion.  Keep
            # an already audited observation factor in observation until a
            # meaningful rolling window is available.
            if old_status == "candidate" and research_days < 60:
                recommended = "candidate"
            if old_status == "observation" and research_days < 60:
                recommended = "observation"
            if recommended == "production" and research_days < 120:
                recommended = "observation"
            if old_status == "production" and research_days < 120:
                recommended = "production"
            enabled = recommended in {"observation", "production"}
            conn.execute(text("""
                UPDATE v2_factor_registry
                   SET status=:status, enabled_in_score=:enabled_in_score,
                       allow_production=:allow_production,
                       status_reason=:status_reason, last_reviewed=:last_reviewed,
                       updated_at=NOW()
                 WHERE factor_name=:factor_name
            """), {
                "status": recommended,
                "enabled_in_score": enabled,
                "allow_production": recommended == "production",
                "status_reason": row.get("validation_reason") or "验证中心自动评估",
                "last_reviewed": review_date,
                "factor_name": name,
            })
            changed += 1
    return changed


def save_run(result: dict) -> dict:
    trade_date = result["trade_date"]
    signals = result["all_signals"]
    raw = result["raw"]
    normalized = result["normalized"]
    with engine.begin() as conn:
        factor_rows = []
        for code, factors in raw.items():
            for name, value in factors.items():
                definition = __import__("v2_app.factors", fromlist=["FACTOR_BY_NAME"]).FACTOR_BY_NAME[name]
                factor_rows.append({
                    "code": code, "trade_date": trade_date, "factor_name": name,
                    "category": definition.category, "raw_value": value,
                    "normalized": normalized.get(code, {}).get(name),
                    "valid": value is not None,
                    "reason": "" if value is not None else "数据不足",
                })
        if factor_rows:
            conn.execute(text("""
                INSERT INTO v2_factor_values
                  (code, trade_date, factor_name, category, raw_value, normalized, valid, reason)
                VALUES (:code, :trade_date, :factor_name, :category, :raw_value, :normalized, :valid, :reason)
                ON CONFLICT (code, trade_date, factor_name) DO UPDATE SET
                  raw_value=EXCLUDED.raw_value, normalized=EXCLUDED.normalized,
                  valid=EXCLUDED.valid, reason=EXCLUDED.reason, created_at=NOW()
            """), factor_rows)
        signal_rows = []
        for signal in signals:
            item = serialize_signal(signal)
            signal_rows.append({
                "code": signal.code, "trade_date": trade_date, "name": signal.name,
                "sector": signal.sector, "rank": signal.rank, "factor_score": signal.factor_score,
                "resonance_count": signal.resonance_count,
                "resonance_dimensions_json": json.dumps(signal.resonance_dimensions, ensure_ascii=False),
                "failed_dimensions_json": json.dumps(signal.failed_dimensions, ensure_ascii=False),
                "eligible": signal.resonance_eligible,
                "resonance_reason": signal.resonance_reason,
                "patterns_json": json.dumps(signal.patterns, ensure_ascii=False),
                "lifecycle": signal.lifecycle, "trading_state": signal.trading_state,
                "valid_until": signal.signal_valid_until,
                "market_state": signal.market_state,
                "reasons_json": json.dumps(signal.reasons, ensure_ascii=False),
                "score_mode": signal.score_mode,
            })
        if signal_rows:
            conn.execute(text("""
                INSERT INTO v2_signal_snapshots
                  (code, trade_date, name, sector, rank, factor_score, resonance_count,
                   resonance_dimensions_json, failed_dimensions_json, eligible, resonance_reason,
                   patterns_json, lifecycle, trading_state, valid_until, market_state, reasons_json, score_mode)
                VALUES (:code, :trade_date, :name, :sector, :rank, :factor_score, :resonance_count,
                        :resonance_dimensions_json, :failed_dimensions_json, :eligible, :resonance_reason,
                        :patterns_json, :lifecycle, :trading_state, :valid_until, :market_state, :reasons_json,
                        :score_mode)
                ON CONFLICT (code, trade_date) DO UPDATE SET
                  name=EXCLUDED.name, sector=EXCLUDED.sector, rank=EXCLUDED.rank,
                  factor_score=EXCLUDED.factor_score, resonance_count=EXCLUDED.resonance_count,
                  resonance_dimensions_json=EXCLUDED.resonance_dimensions_json,
                  failed_dimensions_json=EXCLUDED.failed_dimensions_json, eligible=EXCLUDED.eligible,
                  resonance_reason=EXCLUDED.resonance_reason, patterns_json=EXCLUDED.patterns_json,
                  lifecycle=EXCLUDED.lifecycle, trading_state=EXCLUDED.trading_state,
                  valid_until=EXCLUDED.valid_until, market_state=EXCLUDED.market_state,
                  reasons_json=EXCLUDED.reasons_json, score_mode=EXCLUDED.score_mode, created_at=NOW()
            """), signal_rows)
    return {"factors": len(factor_rows), "snapshots": len(signal_rows)}


def get_config() -> dict:
    ensure_schema()
    with engine.connect() as conn:
        row = conn.execute(text("SELECT * FROM v2_trade_config WHERE id=1")).mappings().first()
    return dict(row) if row else {"id": 1, "enabled": False, "account_source": "displayed"}


def update_config(values: dict) -> dict:
    allowed = {"enabled", "account_source", "max_positions", "max_buy_count", "single_position_pct", "stop_loss_pct", "take_profit_pct"}
    values = {key: value for key, value in values.items() if key in allowed and value is not None}
    if not values:
        return get_config()
    values["updated_at"] = datetime.now()
    assignments = ", ".join(f"{key} = :{key}" for key in values)
    ensure_schema()
    with engine.begin() as conn:
        conn.execute(text(f"UPDATE v2_trade_config SET {assignments} WHERE id=1"), values)
    return get_config()


def save_audit(row: dict) -> int:
    ensure_schema()
    statement = text("""
        INSERT INTO v2_trade_audit
          (trade_date, signal_date, account_source, code, name, action, reason, factor_score,
           resonance_count, trading_state, quantity, requested_price, filled_quantity,
           filled_price, order_id, status, fill_status, raw_result)
        VALUES (:trade_date, :signal_date, :account_source, :code, :name, :action, :reason, :factor_score,
                :resonance_count, :trading_state, :quantity, :requested_price, :filled_quantity,
                :filled_price, :order_id, :status, :fill_status, :raw_result)
        RETURNING id
    """)
    with engine.begin() as conn:
        return int(conn.execute(statement, row).scalar())


def list_audits(limit: int = 100) -> list[dict]:
    ensure_schema()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT * FROM v2_trade_audit ORDER BY created_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return [dict(row) for row in rows]


def load_signal_snapshot(trade_date: date) -> list[dict]:
    """Read the persisted daily V2 signals for fast, read-only page rendering."""
    ensure_schema()
    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT code, trade_date, name, sector, rank, factor_score,
                   resonance_count, resonance_dimensions_json, failed_dimensions_json,
                   eligible, resonance_reason, patterns_json, lifecycle, trading_state,
                   valid_until, market_state, reasons_json, score_mode
              FROM v2_signal_snapshots
             WHERE trade_date = :trade_date
             ORDER BY rank NULLS LAST, code
        """), {"trade_date": trade_date}).mappings().all()
    result = []
    for row in rows:
        item = dict(row)
        result.append({
            "code": item["code"], "name": item.get("name") or item["code"],
            "sector": item.get("sector") or "未分类", "trade_date": item["trade_date"].isoformat(),
            "rank": item.get("rank"), "factor_score": item.get("factor_score"),
            "resonance_count": item.get("resonance_count", 0),
            "resonance_dimensions": json.loads(item.get("resonance_dimensions_json") or "[]"),
            "failed_dimensions": json.loads(item.get("failed_dimensions_json") or "[]"),
            "resonance_eligible": bool(item.get("eligible")),
            "resonance_reason": item.get("resonance_reason") or "",
            "patterns": json.loads(item.get("patterns_json") or "[]"),
            "lifecycle": item.get("lifecycle") or "关注",
            "trading_state": item.get("trading_state") or "WATCH",
            "signal_valid_until": item["valid_until"].isoformat() if item.get("valid_until") else None,
            "market_state": item.get("market_state") or "RANGE",
            "reasons": json.loads(item.get("reasons_json") or "[]"),
            "score_mode": item.get("score_mode") or "RESEARCH",
            "production_ready": item.get("score_mode") == "PRODUCTION",
        })
    return result
