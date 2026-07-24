from __future__ import annotations

import json
import re
import threading
from datetime import date, datetime
from typing import Any, Optional

import requests

from api.hermes_native.db_connector import execute_one, execute_query, execute_write

_DDL_LOCK = threading.Lock()
_DDL_READY = False


def _row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return row
    return dict(row) if row else {}


def _normalize_code(code: Any) -> str:
    text = str(code or "").strip().upper()
    for suffix in (".SZ", ".SH", ".BJ", ".HK", ".US"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
            break
    return text.zfill(6) if text.isdigit() else text


def _infer_market(code: Any, market: Any = "") -> str:
    market_text = str(market or "").strip().upper()
    if market_text in {"SH", "SZ", "BJ", "HK", "US"}:
        return market_text
    normalized = _normalize_code(code)
    if normalized.startswith(("6", "7", "9")):
        return "SH"
    if normalized.startswith(("8", "4")):
        return "BJ"
    return "SZ" if normalized else ""


def _json(value: Any) -> str:
    return json.dumps(value if value is not None else {}, ensure_ascii=False)


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except Exception:
        return None


def _first_non_empty(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", "--"):
            return value
    return default


def _normalize_percent(value: Any) -> Optional[float]:
    num = _safe_float(value)
    if num is None:
        return None
    if abs(num) <= 1.5:
        return num * 100.0
    return num


def _clean_display_name(value: Any, fallback: str = "") -> str:
    text = str(value or "").strip()
    if not text:
        return fallback
    if re.match(r"^\d{4}-\d{2}-\d{2}", text):
        return fallback or text
    if "(" in text and text.endswith(")"):
        text = re.sub(r"\([0-9]{6}(?:\.[A-Z]+)?\)$", "", text).strip()
    return text or fallback


def _format_query_code(code: Any) -> str:
    normalized = _normalize_code(code)
    if not normalized:
        return ""
    if str(code or "").strip().upper().endswith((".SZ", ".SH", ".BJ", ".HK", ".US")):
        return str(code).strip().upper()
    market = _infer_market(normalized)
    return f"{normalized}.{market}" if market else normalized


def _normalize_realtime_quote(raw: dict[str, Any]) -> dict[str, Any]:
    code = _normalize_code(_first_non_empty(raw, "code", "ts_code", "symbol", "secCode", "代码", "证券代码"))
    market = _infer_market(code, _first_non_empty(raw, "market", "市场", default=""))
    price = _safe_float(_first_non_empty(raw, "price", "最新价", "现价", "now", "current_price", "收盘价", "close"))
    change_pct = _normalize_percent(_first_non_empty(raw, "change_pct", "涨跌幅", "pct", "priceChangePct"))
    change = _safe_float(_first_non_empty(raw, "change", "涨跌额", "priceChange"))
    open_price = _safe_float(_first_non_empty(raw, "open", "今开", "开盘价"))
    high = _safe_float(_first_non_empty(raw, "high", "最高"))
    low = _safe_float(_first_non_empty(raw, "low", "最低"))
    close = _safe_float(_first_non_empty(raw, "close", "收盘价", "昨收", "close_price"))
    prev_close = _safe_float(_first_non_empty(raw, "prev_close", "昨收", "pre_close"))
    volume = _safe_float(_first_non_empty(raw, "volume", "成交量"))
    amount = _safe_float(_first_non_empty(raw, "amount", "成交额"))
    turnover_rate = _safe_float(_first_non_empty(raw, "turnover_rate", "换手率"))
    pe = _safe_float(_first_non_empty(raw, "pe", "市盈率"))
    pb = _safe_float(_first_non_empty(raw, "pb", "市净率"))
    market_cap = _safe_float(_first_non_empty(raw, "market_cap", "总市值"))
    head_name = _clean_display_name(_first_non_empty(raw, "headName", "head_name", default=""), fallback="")
    name = _clean_display_name(
        _first_non_empty(raw, "name", "名称", "股票名称", "secName", default=head_name or code or ""),
        fallback=head_name or code or "",
    )
    updated_at = raw.get("updated_at") or raw.get("updatedAt") or raw.get("quote_time")
    if not updated_at:
        updated_at = datetime.now()
    return {
        "code": code,
        "name": name or code,
        "market": market,
        "price": price,
        "change_pct": change_pct,
        "change": change,
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "prev_close": prev_close,
        "volume": volume,
        "amount": amount,
        "turnover_rate": turnover_rate,
        "pe": pe,
        "pb": pb,
        "market_cap": market_cap,
        "source_type": str(raw.get("source_type") or "miaoxiang"),
        "source_key": str(raw.get("source_key") or "api/ops/realtime/quotes"),
        "raw_payload": raw,
        "updated_at": updated_at,
    }


def _eastmoney_quote_fallback(code: str) -> Optional[dict[str, Any]]:
    normalized = _normalize_code(code)
    if not normalized:
        return None
    secid = f"1.{normalized}" if normalized.startswith(("6", "7", "9")) else f"0.{normalized}"
    try:
        resp = requests.get(
            "https://push2.eastmoney.com/api/qt/stock/get",
            params={
                "secid": secid,
                "fields": "f43,f44,f45,f46,f47,f48,f57,f58,f60,f169,f170,f171,f173,f177",
            },
            timeout=6,
        )
        data = resp.json()
        item = data.get("data") if data.get("rc") == 0 else None
        if not item:
            return None
        price = _safe_float(item.get("f43") / 100 if item.get("f43") is not None else None)
        close = _safe_float(item.get("f60") / 100 if item.get("f60") is not None else None)
        open_price = _safe_float(item.get("f44") / 100 if item.get("f44") is not None else None)
        high = _safe_float(item.get("f45") / 100 if item.get("f45") is not None else None)
        low = _safe_float(item.get("f46") / 100 if item.get("f46") is not None else None)
        change_pct = _safe_float(item.get("f170") / 100 if item.get("f170") is not None else None)
        change = _safe_float(item.get("f169") / 100 if item.get("f169") is not None else None)
        return {
            "code": normalized,
            "name": str(item.get("f58") or normalized).strip(),
            "market": _infer_market(normalized),
            "price": price,
            "change_pct": change_pct,
            "change": change,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "prev_close": close,
            "volume": _safe_float(item.get("f47")),
            "amount": _safe_float(item.get("f48")),
            "turnover_rate": None,
            "pe": None,
            "pb": None,
            "market_cap": None,
            "source_type": "eastmoney",
            "source_key": "fallback",
            "raw_payload": {"source": "eastmoney", "code": normalized, "data": item},
            "updated_at": datetime.now(),
        }
    except Exception:
        return None


def ensure_monitor_schema() -> None:
    global _DDL_READY
    if _DDL_READY:
        return
    with _DDL_LOCK:
        if _DDL_READY:
            return
        statements = [
            "CREATE SCHEMA IF NOT EXISTS monitor",
            """
            CREATE TABLE IF NOT EXISTS monitor.stock_pool (
                id BIGSERIAL PRIMARY KEY,
                code VARCHAR(16) NOT NULL UNIQUE,
                name VARCHAR(64) NOT NULL,
                market VARCHAR(8) NOT NULL,
                industry VARCHAR(64),
                tracking_status VARCHAR(32) NOT NULL DEFAULT 'watching',
                execution_status VARCHAR(32) NOT NULL DEFAULT 'flat',
                in_wave_pool BOOLEAN NOT NULL DEFAULT FALSE,
                in_monitor_pool BOOLEAN NOT NULL DEFAULT TRUE,
                manual_priority INTEGER NOT NULL DEFAULT 0,
                tags JSONB NOT NULL DEFAULT '[]'::jsonb,
                notes TEXT,
                latest_signal_date DATE,
                latest_signal_type VARCHAR(32),
                latest_source_type VARCHAR(32),
                latest_source_key VARCHAR(64),
                broker_account_status VARCHAR(32),
                last_price NUMERIC(18,4),
                last_trade_date DATE,
                position_qty INTEGER NOT NULL DEFAULT 0,
                cost_price NUMERIC(18,4),
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                archived_at TIMESTAMP WITHOUT TIME ZONE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.stock_pool_sources (
                id BIGSERIAL PRIMARY KEY,
                pool_id BIGINT NOT NULL REFERENCES monitor.stock_pool(id) ON DELETE CASCADE,
                source_type VARCHAR(32) NOT NULL,
                source_key VARCHAR(64),
                source_ref VARCHAR(128),
                signal_date DATE,
                score NUMERIC(18,4),
                signal VARCHAR(32),
                reason TEXT,
                metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
                active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.stock_pool_events (
                id BIGSERIAL PRIMARY KEY,
                pool_id BIGINT NOT NULL REFERENCES monitor.stock_pool(id) ON DELETE CASCADE,
                event_type VARCHAR(32) NOT NULL,
                actor_type VARCHAR(32) NOT NULL DEFAULT 'system',
                actor_name VARCHAR(64),
                source_page VARCHAR(64),
                payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.broker_position_snapshots (
                id BIGSERIAL PRIMARY KEY,
                batch_time TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                account_id VARCHAR(64),
                code VARCHAR(16) NOT NULL,
                name VARCHAR(64),
                market VARCHAR(8),
                qty INTEGER NOT NULL DEFAULT 0,
                avail_qty INTEGER NOT NULL DEFAULT 0,
                cost_price NUMERIC(18,4),
                current_price NUMERIC(18,4),
                market_value NUMERIC(18,4),
                profit NUMERIC(18,4),
                profit_pct NUMERIC(18,4),
                raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.trade_action_queue (
                id BIGSERIAL PRIMARY KEY,
                pool_id BIGINT REFERENCES monitor.stock_pool(id) ON DELETE SET NULL,
                code VARCHAR(16) NOT NULL,
                name VARCHAR(64),
                action_type VARCHAR(32) NOT NULL,
                qty INTEGER NOT NULL DEFAULT 0,
                price_hint NUMERIC(18,4),
                request_source VARCHAR(64),
                status VARCHAR(32) NOT NULL DEFAULT 'pending',
                broker_response JSONB NOT NULL DEFAULT '{}'::jsonb,
                error_message TEXT,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.realtime_quotes (
                code VARCHAR(16) PRIMARY KEY,
                name VARCHAR(64) NOT NULL,
                market VARCHAR(8) NOT NULL,
                price NUMERIC(18,4),
                change_pct NUMERIC(18,4),
                change_amount NUMERIC(18,4),
                open_price NUMERIC(18,4),
                high_price NUMERIC(18,4),
                low_price NUMERIC(18,4),
                close_price NUMERIC(18,4),
                prev_close NUMERIC(18,4),
                volume NUMERIC(24,4),
                amount NUMERIC(24,4),
                turnover_rate NUMERIC(18,4),
                pe NUMERIC(18,4),
                pb NUMERIC(18,4),
                market_cap NUMERIC(24,4),
                source_type VARCHAR(32) NOT NULL DEFAULT 'miaoxiang',
                source_key VARCHAR(64) NOT NULL DEFAULT 'api/ops/realtime/quotes',
                raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS monitor.wave_watchlist (
                code VARCHAR(16) PRIMARY KEY,
                name VARCHAR(64) NOT NULL,
                market VARCHAR(8) NOT NULL,
                note TEXT,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMP WITHOUT TIME ZONE NOT NULL DEFAULT NOW()
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_monitor_stock_pool_active ON monitor.stock_pool (is_active, in_monitor_pool, in_wave_pool, execution_status)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_stock_pool_sources_pool ON monitor.stock_pool_sources (pool_id, active)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_stock_pool_events_pool ON monitor.stock_pool_events (pool_id, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_broker_snapshots_code ON monitor.broker_position_snapshots (code, batch_time DESC)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_trade_queue_status ON monitor.trade_action_queue (status, created_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_realtime_quotes_updated_at ON monitor.realtime_quotes (updated_at DESC)",
            "CREATE INDEX IF NOT EXISTS idx_monitor_realtime_quotes_source ON monitor.realtime_quotes (source_type, source_key)",
        ]
        for sql in statements:
            execute_write(sql)
        _DDL_READY = True


def get_pool_row(code: Any) -> Optional[dict[str, Any]]:
    ensure_monitor_schema()
    normalized = _normalize_code(code)
    if not normalized:
        return None
    row = execute_one("SELECT * FROM monitor.stock_pool WHERE code = %s", (normalized,))
    return _row_to_dict(row) if row else None


def upsert_pool_stock(
    *,
    code: Any,
    name: Any = None,
    market: Any = "",
    industry: Any = None,
    tracking_status: Any = None,
    execution_status: Any = None,
    in_wave_pool: Optional[bool] = None,
    in_monitor_pool: Optional[bool] = None,
    manual_priority: Optional[int] = None,
    notes: Any = None,
    latest_signal_date: Any = None,
    latest_signal_type: Any = None,
    latest_source_type: Any = None,
    latest_source_key: Any = None,
    broker_account_status: Any = None,
    last_price: Any = None,
    last_trade_date: Any = None,
    position_qty: Optional[int] = None,
    cost_price: Any = None,
    is_active: Optional[bool] = None,
) -> dict[str, Any]:
    ensure_monitor_schema()
    normalized = _normalize_code(code)
    if not normalized:
        raise ValueError("invalid code")
    existing = get_pool_row(normalized) or {}

    resolved_name = str(name or existing.get("name") or normalized).strip() or normalized
    resolved_market = _infer_market(normalized, market or existing.get("market") or "")
    resolved_tracking = str(
        tracking_status
        or existing.get("tracking_status")
        or ("wave_pool" if in_wave_pool else "watching")
    )
    resolved_execution = str(execution_status or existing.get("execution_status") or "flat")
    resolved_in_wave = existing.get("in_wave_pool", False) if in_wave_pool is None else bool(in_wave_pool)
    resolved_in_monitor = existing.get("in_monitor_pool", True) if in_monitor_pool is None else bool(in_monitor_pool)
    resolved_priority = int(manual_priority if manual_priority is not None else existing.get("manual_priority") or 0)
    resolved_notes = notes if notes is not None else existing.get("notes")
    resolved_signal_date = latest_signal_date if latest_signal_date is not None else existing.get("latest_signal_date")
    resolved_signal_type = latest_signal_type if latest_signal_type is not None else existing.get("latest_signal_type")
    resolved_source_type = latest_source_type if latest_source_type is not None else existing.get("latest_source_type")
    resolved_source_key = latest_source_key if latest_source_key is not None else existing.get("latest_source_key")
    resolved_broker_status = broker_account_status if broker_account_status is not None else existing.get("broker_account_status")
    resolved_last_price = last_price if last_price is not None else existing.get("last_price")
    resolved_last_trade_date = last_trade_date if last_trade_date is not None else existing.get("last_trade_date")
    resolved_position_qty = int(position_qty if position_qty is not None else existing.get("position_qty") or 0)
    resolved_cost_price = cost_price if cost_price is not None else existing.get("cost_price")
    resolved_industry = industry if industry not in (None, "") else existing.get("industry")
    resolved_is_active = bool(existing.get("is_active", True)) if is_active is None else bool(is_active)
    archived_at = "NOW()" if (not resolved_is_active and resolved_execution == "flat" and not resolved_in_monitor and not resolved_in_wave) else "NULL"

    row = execute_one(
        f"""
        INSERT INTO monitor.stock_pool (
            code, name, market, industry, tracking_status, execution_status,
            in_wave_pool, in_monitor_pool, manual_priority, notes, latest_signal_date,
            latest_signal_type, latest_source_type, latest_source_key,
            broker_account_status, last_price, last_trade_date, position_qty,
            cost_price, is_active, updated_at, archived_at
        ) VALUES (
            %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s,
            %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s, NOW(), {archived_at}
        )
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            market = EXCLUDED.market,
            industry = EXCLUDED.industry,
            tracking_status = EXCLUDED.tracking_status,
            execution_status = EXCLUDED.execution_status,
            in_wave_pool = EXCLUDED.in_wave_pool,
            in_monitor_pool = EXCLUDED.in_monitor_pool,
            manual_priority = EXCLUDED.manual_priority,
            notes = EXCLUDED.notes,
            latest_signal_date = EXCLUDED.latest_signal_date,
            latest_signal_type = EXCLUDED.latest_signal_type,
            latest_source_type = EXCLUDED.latest_source_type,
            latest_source_key = EXCLUDED.latest_source_key,
            broker_account_status = EXCLUDED.broker_account_status,
            last_price = EXCLUDED.last_price,
            last_trade_date = EXCLUDED.last_trade_date,
            position_qty = EXCLUDED.position_qty,
            cost_price = EXCLUDED.cost_price,
            is_active = EXCLUDED.is_active,
            updated_at = NOW(),
            archived_at = CASE
                WHEN EXCLUDED.is_active = FALSE
                 AND EXCLUDED.execution_status = 'flat'
                 AND EXCLUDED.in_monitor_pool = FALSE
                 AND EXCLUDED.in_wave_pool = FALSE
                THEN NOW()
                ELSE NULL
            END
        RETURNING *
        """,
        (
            normalized,
            resolved_name,
            resolved_market,
            resolved_industry,
            resolved_tracking,
            resolved_execution,
            resolved_in_wave,
            resolved_in_monitor,
            resolved_priority,
            resolved_notes,
            resolved_signal_date,
            resolved_signal_type,
            resolved_source_type,
            resolved_source_key,
            resolved_broker_status,
            resolved_last_price,
            resolved_last_trade_date,
            resolved_position_qty,
            resolved_cost_price,
            resolved_is_active,
        ),
    )
    return _row_to_dict(row)


def ensure_source(
    pool_id: int,
    *,
    source_type: str,
    source_key: Optional[str] = None,
    source_ref: Optional[str] = None,
    signal_date: Any = None,
    score: Any = None,
    signal: Optional[str] = None,
    reason: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
    active: bool = True,
) -> None:
    ensure_monitor_schema()
    existing = execute_one(
        """
        SELECT id
        FROM monitor.stock_pool_sources
        WHERE pool_id = %s
          AND source_type = %s
          AND COALESCE(source_key, '') = COALESCE(%s, '')
          AND COALESCE(source_ref, '') = COALESCE(%s, '')
        LIMIT 1
        """,
        (pool_id, source_type, source_key, source_ref),
    )
    payload = _json(metadata or {})
    if existing:
        execute_write(
            """
            UPDATE monitor.stock_pool_sources
            SET signal_date = %s,
                score = %s,
                signal = %s,
                reason = %s,
                metadata = %s::jsonb,
                active = %s,
                updated_at = NOW()
            WHERE id = %s
            """,
            (signal_date, score, signal, reason, payload, active, _row_to_dict(existing).get("id")),
        )
        return
    execute_write(
        """
        INSERT INTO monitor.stock_pool_sources (
            pool_id, source_type, source_key, source_ref, signal_date,
            score, signal, reason, metadata, active
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
        """,
        (pool_id, source_type, source_key, source_ref, signal_date, score, signal, reason, payload, active),
    )


def record_event(
    pool_id: int,
    *,
    event_type: str,
    payload: Optional[dict[str, Any]] = None,
    actor_type: str = "system",
    actor_name: Optional[str] = None,
    source_page: Optional[str] = None,
) -> None:
    ensure_monitor_schema()
    execute_write(
        """
        INSERT INTO monitor.stock_pool_events (
            pool_id, event_type, actor_type, actor_name, source_page, payload
        ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
        """,
        (pool_id, event_type, actor_type, actor_name, source_page, _json(payload or {})),
    )


def sync_wave_watchlist_entry(code: Any, name: Any, market: Any, enabled: bool, note: Any = None) -> None:
    normalized = _normalize_code(code)
    if not normalized:
        return
    execute_write(
        """
        INSERT INTO wave_watchlist (code, name, market, note, is_active)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (code) DO UPDATE
        SET name = EXCLUDED.name,
            market = EXCLUDED.market,
            note = COALESCE(EXCLUDED.note, wave_watchlist.note),
            is_active = EXCLUDED.is_active
        """,
        (normalized, str(name or normalized), _infer_market(normalized, market), note, bool(enabled)),
    )


def add_monitor_stock(
    *,
    code: Any,
    name: Any = None,
    market: Any = "",
    industry: Any = None,
    source_type: str = "manual",
    source_key: Optional[str] = None,
    source_ref: Optional[str] = None,
    signal_date: Any = None,
    signal: Optional[str] = None,
    score: Any = None,
    reason: Optional[str] = None,
    source_page: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    row = upsert_pool_stock(
        code=code,
        name=name,
        market=market,
        industry=industry,
        tracking_status="watching",
        in_monitor_pool=True,
        latest_source_type=source_type,
        latest_source_key=source_key or source_ref or "monitor_add",
        latest_signal_type=signal,
        latest_signal_date=signal_date,
        is_active=True,
    )
    ensure_source(
        int(row["id"]),
        source_type=source_type,
        source_key=source_key,
        source_ref=source_ref,
        signal_date=signal_date,
        score=score,
        signal=signal,
        reason=reason,
        metadata=metadata,
        active=True,
    )
    record_event(
        int(row["id"]),
        event_type="add_to_monitor",
        payload={"source_type": source_type, "source_key": source_key, "source_ref": source_ref, **(metadata or {})},
        actor_type="api",
        actor_name="watchlist.add",
        source_page=source_page,
    )
    return row


def set_wave_pool_membership(
    *,
    code: Any,
    enabled: bool,
    name: Any = None,
    market: Any = "",
    note: Any = None,
    source_type: str = "manual",
    source_key: Optional[str] = None,
    source_page: Optional[str] = None,
) -> dict[str, Any]:
    existing = get_pool_row(code) or {}
    row = upsert_pool_stock(
        code=code,
        name=name or existing.get("name"),
        market=market or existing.get("market") or "",
        industry=existing.get("industry"),
        tracking_status="wave_pool" if enabled else ("watching" if existing.get("in_monitor_pool", True) else "archived"),
        in_wave_pool=enabled,
        in_monitor_pool=True if enabled else existing.get("in_monitor_pool", True),
        latest_source_type=source_type,
        latest_source_key=source_key or ("wave.enable" if enabled else "wave.disable"),
        is_active=True if enabled else existing.get("is_active", True),
    )
    sync_wave_watchlist_entry(row["code"], row["name"], row["market"], enabled, note=note)
    ensure_source(
        int(row["id"]),
        source_type="wave",
        source_key=source_key or ("enabled" if enabled else "disabled"),
        source_ref=row["code"],
        metadata={"enabled": enabled},
        active=enabled,
    )
    record_event(
        int(row["id"]),
        event_type="add_to_wave_pool" if enabled else "remove_from_wave_pool",
        payload={"enabled": enabled, "note": note},
        actor_type="api",
        actor_name="watchlist.wave",
        source_page=source_page,
    )
    return row


def remove_monitor_stock(code: Any, *, source_page: Optional[str] = None) -> Optional[dict[str, Any]]:
    existing = get_pool_row(code)
    if not existing:
        return None
    holding_like = str(existing.get("execution_status") or "flat") in {"holding", "pending_buy", "pending_sell"} or int(existing.get("position_qty") or 0) > 0
    row = upsert_pool_stock(
        code=existing["code"],
        name=existing.get("name"),
        market=existing.get("market"),
        industry=existing.get("industry"),
        tracking_status="holding" if holding_like else "archived",
        execution_status=existing.get("execution_status") or "flat",
        in_monitor_pool=False,
        in_wave_pool=False,
        is_active=True if holding_like else False,
        latest_source_type="manual_remove",
        latest_source_key="watchlist.remove",
    )
    sync_wave_watchlist_entry(row["code"], row["name"], row["market"], False)
    record_event(
        int(row["id"]),
        event_type="remove_from_monitor",
        payload={"holding_like": holding_like},
        actor_type="api",
        actor_name="watchlist.remove",
        source_page=source_page,
    )
    return row


def get_watchlist_items() -> list[dict[str, Any]]:
    ensure_monitor_schema()
    rows = execute_query(
        """
        SELECT code, name, market, industry, tracking_status, execution_status,
               in_wave_pool, in_monitor_pool, latest_source_type, latest_source_key,
               last_price, last_trade_date, position_qty, cost_price
        FROM monitor.stock_pool
        WHERE (in_monitor_pool = TRUE OR in_wave_pool = TRUE)
          AND (is_active = TRUE OR execution_status IN ('holding', 'pending_buy', 'pending_sell'))
        ORDER BY code
        """
    ) or []
    return [_row_to_dict(row) for row in rows]


def get_pool_rows_for_stock_monitor() -> list[dict[str, Any]]:
    ensure_monitor_schema()
    rows = execute_query(
        """
        SELECT *
        FROM monitor.stock_pool
        WHERE (in_monitor_pool = TRUE OR in_wave_pool = TRUE OR execution_status IN ('holding', 'pending_buy', 'pending_sell'))
          AND (is_active = TRUE OR execution_status IN ('holding', 'pending_buy', 'pending_sell'))
        ORDER BY
          CASE WHEN execution_status = 'holding' THEN 0 ELSE 1 END,
          code
        """
    ) or []
    return [_row_to_dict(row) for row in rows]


def bootstrap_from_legacy_wave_watchlist() -> int:
    ensure_monitor_schema()
    rows = execute_query(
        "SELECT code, name, market, note, is_active FROM monitor.wave_watchlist WHERE is_active = TRUE ORDER BY code"
    ) or []
    count = 0
    for row in rows:
        data = _row_to_dict(row)
        pool_row = upsert_pool_stock(
            code=data.get("code"),
            name=data.get("name"),
            market=data.get("market"),
            tracking_status="wave_pool",
            in_wave_pool=True,
            in_monitor_pool=True,
            latest_source_type="legacy_wave_watchlist",
            latest_source_key="bootstrap",
            is_active=True,
        )
        ensure_source(
            int(pool_row["id"]),
            source_type="legacy_wave_watchlist",
            source_key="bootstrap",
            source_ref=str(data.get("code") or ""),
            metadata={"note": data.get("note")},
            active=True,
        )
        count += 1
    return count


def sync_broker_positions(raw_positions: dict[str, Any], raw_balance: Optional[dict[str, Any]] = None) -> dict[str, Any]:
    ensure_monitor_schema()
    data = (raw_positions or {}).get("data", raw_positions or {})
    balance = (raw_balance or {}).get("data", raw_balance or {})
    account_id = str(balance.get("accID") or "")
    pos_list = data.get("posList") or []
    seen_codes: set[str] = set()
    for pos in pos_list:
        code = _normalize_code(pos.get("secCode"))
        if not code:
            continue
        qty = int(pos.get("count") or 0)
        avail_qty = int(pos.get("availCount") or 0)
        price_dec = int(pos.get("priceDec") or 2)
        cost_dec = int(pos.get("costPriceDec") or 2)
        current_price = float(pos.get("price") or 0) / (10 ** price_dec)
        cost_price = float(pos.get("costPrice") or pos.get("price") or 0) / (10 ** cost_dec)
        profit = float(pos.get("profit") or 0)
        profit_pct = float(pos.get("profitPct") or 0)
        market_value = current_price * qty
        seen_codes.add(code)
        execute_write(
            """
            INSERT INTO monitor.broker_position_snapshots (
                account_id, code, name, market, qty, avail_qty, cost_price,
                current_price, market_value, profit, profit_pct, raw_payload
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                account_id,
                code,
                pos.get("secName") or code,
                _infer_market(code),
                qty,
                avail_qty,
                cost_price,
                current_price,
                market_value,
                profit,
                profit_pct,
                _json(pos),
            ),
        )
        row = upsert_pool_stock(
            code=code,
            name=pos.get("secName") or code,
            market=_infer_market(code),
            tracking_status="focused",
            execution_status="holding" if qty > 0 else "flat",
            in_monitor_pool=True if qty > 0 else None,
            latest_source_type="broker_sync",
            latest_source_key="miaoxiang.positions",
            broker_account_status="synced",
            last_price=current_price,
            last_trade_date=date.today().isoformat(),
            position_qty=qty,
            cost_price=cost_price,
            is_active=True if qty > 0 else None,
        )
        ensure_source(
            int(row["id"]),
            source_type="broker_sync",
            source_key="miaoxiang.positions",
            source_ref=account_id,
            score=None,
            signal="holding" if qty > 0 else "flat",
            metadata={"qty": qty, "profit_pct": profit_pct},
            active=True,
        )

    if seen_codes:
        rows = execute_query(
            "SELECT code, in_monitor_pool, in_wave_pool FROM monitor.stock_pool WHERE execution_status = 'holding'"
        ) or []
        for row in rows:
            data_row = _row_to_dict(row)
            code = _normalize_code(data_row.get("code"))
            if code in seen_codes:
                continue
            keep_active = bool(data_row.get("in_monitor_pool") or data_row.get("in_wave_pool"))
            upsert_pool_stock(
                code=code,
                name=get_pool_row(code).get("name"),
                market=get_pool_row(code).get("market"),
                tracking_status="watching" if keep_active else "archived",
                execution_status="flat",
                position_qty=0,
                broker_account_status="synced",
                is_active=keep_active,
            )
    return {"ok": True, "count": len(pos_list), "account_id": account_id}


def _realtime_query_codes(codes: list[str]) -> list[str]:
    normalized: list[str] = []
    for code in codes:
        query_code = _format_query_code(code)
        if query_code:
            normalized.append(query_code)
    return list(dict.fromkeys(normalized))


def get_realtime_quote_rows(codes: Optional[list[str]] = None) -> list[dict[str, Any]]:
    ensure_monitor_schema()
    if codes:
        normalized = sorted({
            _normalize_code(code)
            for code in codes
            if _normalize_code(code).isdigit()
        })
        if not normalized:
            return []
        placeholders = ",".join(["%s"] * len(normalized))
        rows = execute_query(
            f"""
            SELECT *
            FROM monitor.realtime_quotes
            WHERE code IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            tuple(normalized),
        ) or []
    else:
        rows = execute_query(
            """
            SELECT *
            FROM monitor.realtime_quotes
            ORDER BY updated_at DESC
            LIMIT 500
            """
        ) or []
    return [_row_to_dict(row) for row in rows]


def get_realtime_quote_map(codes: Optional[list[str]] = None) -> dict[str, dict[str, Any]]:
    return {str(row.get("code") or ""): row for row in get_realtime_quote_rows(codes)}


def realtime_quotes_need_refresh(codes: list[str], ttl_seconds: int = 20) -> bool:
    ensure_monitor_schema()
    normalized = sorted({
        _normalize_code(code)
        for code in codes
        if _normalize_code(code).isdigit()
    })
    if not normalized:
        return False
    placeholders = ",".join(["%s"] * len(normalized))
    row = execute_one(
        f"""
        SELECT MAX(updated_at) AS latest_at
        FROM monitor.realtime_quotes
        WHERE code IN ({placeholders})
        """,
        tuple(normalized),
    )
    latest_at = _row_to_dict(row).get("latest_at") if row else None
    if not latest_at:
        return True
    try:
        age = datetime.now() - latest_at
        return age.total_seconds() > max(1, int(ttl_seconds or 20))
    except Exception:
        return True


def sync_realtime_quotes(
    codes: list[str],
    *,
    source_type: str = "miaoxiang",
    source_key: str = "api/ops/realtime/quotes",
) -> dict[str, Any]:
    ensure_monitor_schema()
    normalized_codes = _realtime_query_codes(codes)
    if not normalized_codes:
        return {"ok": True, "count": 0, "items": [], "source": "empty"}

    from api.hermes_native.services.miaoxiang_service import realtime_quote as mx_quote

    raw_items: list[dict[str, Any]] = []
    batch_size = 5  # 妙想自然语言查询每次最多返回5条
    for i in range(0, len(normalized_codes), batch_size):
        batch = normalized_codes[i : i + batch_size]
        if not batch:
            continue
        try:
            batch_items = mx_quote(batch)
            if isinstance(batch_items, list):
                raw_items.extend(batch_items)
        except Exception:
            continue

    # Merge raw items by code (妙想 may return multiple rows per stock)
    merged_raw: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        raw_code = str(item.get("code") or item.get("secCode") or item.get("symbol") or "").strip()
        norm_code = _normalize_code(raw_code)
        if not norm_code:
            continue
        if norm_code in merged_raw:
            # Merge: later items fill in missing fields from earlier items
            existing = merged_raw[norm_code]
            for k, v in item.items():
                if k not in existing or existing[k] in (None, "", 0):
                    existing[k] = v
        else:
            merged_raw[norm_code] = dict(item)

    normalized_items: list[dict[str, Any]] = []
    seen_codes: set[str] = set()
    for code, merged_item in merged_raw.items():
        normalized = _normalize_realtime_quote({**merged_item, "source_type": source_type, "source_key": source_key})
        code = normalized.get("code") or ""
        if not code or code in seen_codes:
            continue
        if normalized.get("price") is None or normalized.get("price") == 0:
            fallback = _eastmoney_quote_fallback(code)
            if fallback:
                for key in (
                    "name",
                    "market",
                    "price",
                    "change_pct",
                    "change",
                    "open",
                    "high",
                    "low",
                    "close",
                    "prev_close",
                    "volume",
                    "amount",
                ):
                    if fallback.get(key) not in (None, ""):
                        normalized[key] = fallback[key]
                normalized["source_type"] = fallback.get("source_type", normalized.get("source_type"))
                normalized["source_key"] = fallback.get("source_key", normalized.get("source_key"))
                normalized["raw_payload"] = {
                    "primary": normalized.get("raw_payload") or {},
                    "fallback": fallback.get("raw_payload") or {},
                }
        # Kline fallback: if price still None after eastmoney, try kline_daily
        if normalized.get("price") is None or normalized.get("price") == 0:
            try:
                kline_rows = execute_query(
                    """SELECT close, trade_date FROM public.kline_daily
                       WHERE code = %s ORDER BY trade_date DESC LIMIT 1""",
                    (code,),
                )
                if kline_rows and kline_rows[0].get("close") is not None:
                    krow = kline_rows[0]
                    kline_price = float(krow["close"])
                    kline_date = krow.get("trade_date")
                    normalized["price"] = kline_price
                    normalized["close"] = kline_price
                    if not normalized.get("name"):
                        normalized["name"] = code
                    if not normalized.get("market"):
                        normalized["market"] = _infer_market(code)
                    normalized["source_type"] = "kline"
                    normalized["source_key"] = f"{source_key}/kline"
                    if kline_date:
                        try:
                            from datetime import datetime as _dt, time as _dt_time
                            if isinstance(kline_date, str):
                                _ktd = _dt.strptime(kline_date[:10], "%Y-%m-%d")
                            else:
                                _ktd = _dt.combine(kline_date, _dt_time(15, 0))
                            normalized["_kline_updated_at"] = _ktd.replace(hour=15, minute=0)
                        except Exception:
                            pass
            except Exception:
                pass
        seen_codes.add(code)
        normalized_items.append(normalized)
        execute_write(
            """
            INSERT INTO monitor.realtime_quotes (
                code, name, market, price, change_pct, change_amount,
                open_price, high_price, low_price, close_price, prev_close,
                volume, amount, turnover_rate, pe, pb, market_cap,
                source_type, source_key, raw_payload, updated_at, created_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s,
                %s, %s, %s::jsonb, COALESCE(%s, NOW()), COALESCE((SELECT created_at FROM monitor.realtime_quotes WHERE code = %s), NOW())
            )
            ON CONFLICT (code) DO UPDATE SET
                name = EXCLUDED.name,
                market = EXCLUDED.market,
                price = EXCLUDED.price,
                change_pct = EXCLUDED.change_pct,
                change_amount = EXCLUDED.change_amount,
                open_price = EXCLUDED.open_price,
                high_price = EXCLUDED.high_price,
                low_price = EXCLUDED.low_price,
                close_price = EXCLUDED.close_price,
                prev_close = EXCLUDED.prev_close,
                volume = EXCLUDED.volume,
                amount = EXCLUDED.amount,
                turnover_rate = EXCLUDED.turnover_rate,
                pe = EXCLUDED.pe,
                pb = EXCLUDED.pb,
                market_cap = EXCLUDED.market_cap,
                source_type = EXCLUDED.source_type,
                source_key = EXCLUDED.source_key,
                raw_payload = EXCLUDED.raw_payload,
                updated_at = COALESCE(EXCLUDED.updated_at, NOW())
            """,
            (
                code,
                normalized.get("name"),
                normalized.get("market"),
                normalized.get("price"),
                normalized.get("change_pct"),
                normalized.get("change"),
                normalized.get("open"),
                normalized.get("high"),
                normalized.get("low"),
                normalized.get("close"),
                normalized.get("prev_close"),
                normalized.get("volume"),
                normalized.get("amount"),
                normalized.get("turnover_rate"),
                normalized.get("pe"),
                normalized.get("pb"),
                normalized.get("market_cap"),
                source_type,
                source_key,
                _json(normalized.get("raw_payload") or {}),
                normalized.get("_kline_updated_at"),
                code,
            ),
        )

    # Fill gaps: codes not returned by 妙想 → try eastmoney → try kline fallback
    missing_codes = [c for c in normalized_codes if c not in seen_codes]
    # Batch fetch kline data for all missing codes as fallback
    kline_fallback_map: dict[str, dict[str, Any]] = {}
    if missing_codes:
        try:
            placeholders = ",".join(["%s"] * len(missing_codes))
            kline_rows = execute_query(
                f"""
                SELECT code, close, trade_date
                FROM (
                    SELECT code, close, trade_date,
                           ROW_NUMBER() OVER (PARTITION BY code ORDER BY trade_date DESC) AS rn
                    FROM public.kline_daily
                    WHERE code IN ({placeholders})
                ) sub
                WHERE rn = 1
                """,
                tuple(missing_codes),
            )
            for row in kline_rows:
                c = str(row.get("code", "")).strip()
                if c and row.get("close") is not None:
                    kline_fallback_map[c] = {
                        "code": c,
                        "price": float(row["close"]),
                        "close": float(row["close"]),
                        "trade_date": row.get("trade_date"),
                        "name": c,
                        "market": _infer_market(c),
                    }
        except Exception:
            pass

    for code in missing_codes:
        try:
            fallback = _eastmoney_quote_fallback(code)
            if fallback and fallback.get("price") not in (None, 0):
                normalized = _normalize_realtime_quote({
                    **fallback,
                    "source_type": "eastmoney",
                    "source_key": f"{source_key}/fallback",
                })
                code = normalized.get("code") or ""
                if not code:
                    continue
                execute_write(
                    """
                    INSERT INTO monitor.realtime_quotes (
                        code, name, market, price, change_pct, change_amount,
                        open_price, high_price, low_price, close_price, prev_close,
                        volume, amount, turnover_rate, pe, pb, market_cap,
                        source_type, source_key, raw_payload, updated_at, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s::jsonb, NOW(), NOW()
                    )
                    ON CONFLICT (code) DO UPDATE SET
                        name = EXCLUDED.name,
                        market = EXCLUDED.market,
                        price = EXCLUDED.price,
                        change_pct = EXCLUDED.change_pct,
                        change_amount = EXCLUDED.change_amount,
                        open_price = EXCLUDED.open_price,
                        high_price = EXCLUDED.high_price,
                        low_price = EXCLUDED.low_price,
                        close_price = EXCLUDED.close_price,
                        prev_close = EXCLUDED.prev_close,
                        volume = EXCLUDED.volume,
                        amount = EXCLUDED.amount,
                        turnover_rate = EXCLUDED.turnover_rate,
                        pe = EXCLUDED.pe,
                        pb = EXCLUDED.pb,
                        market_cap = EXCLUDED.market_cap,
                        source_type = EXCLUDED.source_type,
                        source_key = EXCLUDED.source_key,
                        raw_payload = EXCLUDED.raw_payload,
                        updated_at = NOW()
                    """,
                    (
                        code,
                        normalized.get("name"),
                        normalized.get("market"),
                        normalized.get("price"),
                        normalized.get("change_pct"),
                        normalized.get("change"),
                        normalized.get("open"),
                        normalized.get("high"),
                        normalized.get("low"),
                        normalized.get("close"),
                        normalized.get("prev_close"),
                        normalized.get("volume"),
                        normalized.get("amount"),
                        normalized.get("turnover_rate"),
                        normalized.get("pe"),
                        normalized.get("pb"),
                        normalized.get("market_cap"),
                        "eastmoney",
                        f"{source_key}/fallback",
                        _json(normalized.get("raw_payload") or {}),
                    ),
                )
                continue
            # K-line fallback: use close price from kline_daily
            kline = kline_fallback_map.get(code)
            if kline and kline.get("price") not in (None, 0):
                trade_date = kline.get("trade_date")
                # Build updated_at from trade_date (收盘后以当日收盘时间为准)
                if trade_date:
                    try:
                        from datetime import datetime as _dt, time as _dt_time
                        if isinstance(trade_date, str):
                            td = _dt.strptime(trade_date[:10], "%Y-%m-%d")
                        else:
                            td = _dt.combine(trade_date, _dt_time(15, 0))
                        updated_at = td.replace(hour=15, minute=0)
                    except Exception:
                        updated_at = None
                else:
                    updated_at = None
                execute_write(
                    """
                    INSERT INTO monitor.realtime_quotes (
                        code, name, market, price, change_pct, change_amount,
                        open_price, high_price, low_price, close_price, prev_close,
                        volume, amount, turnover_rate, pe, pb, market_cap,
                        source_type, source_key, raw_payload, updated_at, created_at
                    ) VALUES (
                        %s, %s, %s, %s, NULL, NULL,
                        NULL, NULL, NULL, %s, NULL,
                        NULL, NULL, NULL, NULL, NULL, NULL,
                        'kline', %s, '{}'::jsonb, COALESCE(%s, NOW()), NOW()
                    )
                    ON CONFLICT (code) DO UPDATE SET
                        price = EXCLUDED.price,
                        close_price = EXCLUDED.close_price,
                        source_type = EXCLUDED.source_type,
                        source_key = EXCLUDED.source_key,
                        updated_at = COALESCE(EXCLUDED.updated_at, monitor.realtime_quotes.updated_at)
                    """,
                    (
                        code,
                        kline.get("name"),
                        kline.get("market"),
                        kline.get("price"),
                        kline.get("close"),
                        f"{source_key}/kline",
                        updated_at,
                    ),
                )
        except Exception:
            continue

    items_map = get_realtime_quote_map(normalized_codes)
    return {
        "ok": True,
        "count": len(items_map),
        "requested": len(normalized_codes),
        "source": "miaoxiang" if normalized_items else "cache",
        "items": list(items_map.values()),
        "items_map": items_map,
    }


def load_or_sync_realtime_quotes(
    codes: list[str],
    *,
    ttl_seconds: int = 20,
    force_refresh: bool = False,
    source_type: str = "miaoxiang",
    source_key: str = "api/ops/realtime/quotes",
) -> dict[str, Any]:
    ensure_monitor_schema()
    normalized_codes = [
        _normalize_code(code)
        for code in codes
        if _normalize_code(code).isdigit()
    ]
    normalized_codes = list(dict.fromkeys(normalized_codes))
    if not normalized_codes:
        return {"ok": True, "count": 0, "requested": 0, "source": "empty", "items": [], "items_map": {}}
    if force_refresh or realtime_quotes_need_refresh(normalized_codes, ttl_seconds=ttl_seconds):
        return sync_realtime_quotes(normalized_codes, source_type=source_type, source_key=source_key)
    items_map = get_realtime_quote_map(normalized_codes)
    return {
        "ok": True,
        "count": len(items_map),
        "requested": len(normalized_codes),
        "source": "cache",
        "items": list(items_map.values()),
        "items_map": items_map,
    }


def queue_trade_action(
    *,
    code: Any,
    name: Any = None,
    market: Any = "",
    action_type: str,
    qty: int = 0,
    price_hint: Any = None,
    request_source: str = "ui",
    payload: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ensure_monitor_schema()
    normalized = _normalize_code(code)
    if not normalized:
        raise ValueError("invalid code")
    existing = get_pool_row(normalized)
    pool_id = int(existing["id"]) if existing else None
    queue_row = execute_one(
        """
        INSERT INTO monitor.trade_action_queue (
            pool_id, code, name, action_type, qty, price_hint, request_source, status, broker_response, updated_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, 'pending', '{}'::jsonb, NOW())
        RETURNING *
        """,
        (
            pool_id,
            normalized,
            str(name or (existing or {}).get("name") or normalized),
            action_type,
            int(qty or 0),
            price_hint,
            request_source,
        ),
    )
    if pool_id:
        record_event(
            pool_id,
            event_type=action_type,
            payload=payload or {"qty": qty, "price_hint": price_hint},
            actor_type="api",
            actor_name="mock_trading",
            source_page=request_source,
        )
    return _row_to_dict(queue_row)


def update_trade_action_result(
    queue_id: int,
    *,
    status: str,
    broker_response: Optional[dict[str, Any]] = None,
    error_message: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    ensure_monitor_schema()
    row = execute_one(
        """
        UPDATE monitor.trade_action_queue
        SET status = %s,
            broker_response = %s::jsonb,
            error_message = %s,
            updated_at = NOW()
        WHERE id = %s
        RETURNING *
        """,
        (status, _json(broker_response or {}), error_message, queue_id),
    )
    return _row_to_dict(row) if row else None
