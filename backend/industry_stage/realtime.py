"""DB-first realtime collector for the independent industry-stage pool.

The scheduler is the only caller that reaches the external quote source.  API
handlers read the two ``industry_stage_realtime_*`` tables only.
"""

from datetime import date, datetime, time, timedelta
import logging
from urllib.request import Request, urlopen

from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.session import get_db_session
from industry_stage.market_clock import PHASE_TRADING, market_phase
from industry_stage.models import (
    IndustryStageRealtimeQuote,
    IndustryStageRealtimeState,
    IndustryStageRun,
    IndustryStageStockDaily,
)


logger = logging.getLogger(__name__)

SOURCE = "tencent_realtime"
MIN_READY_COVERAGE = 95.0
_USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
_market_day_cache: dict[date, bool] = {}
_retry_after: datetime | None = None


def _optional_float(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_ts_code(raw_code: str) -> str:
    raw = str(raw_code or "").strip().upper()
    if "." in raw:
        code, exchange = raw.split(".", 1)
        if len(code) == 6 and exchange in {"SH", "SZ", "BJ"}:
            return f"{code}.{exchange}"
        return ""
    if len(raw) != 6 or not raw.isdigit():
        return ""
    if raw.startswith("92") or raw[0] in {"4", "8"}:
        exchange = "BJ"
    elif raw[0] in {"5", "6", "9"}:
        exchange = "SH"
    else:
        exchange = "SZ"
    return f"{raw}.{exchange}"


def _provider_symbol(ts_code: str) -> str:
    normalized = _normalize_ts_code(ts_code)
    if not normalized:
        return ""
    code, exchange = normalized.split(".")
    return f"{exchange.lower()}{code}"


def _parse_quote_time(value) -> datetime | None:
    text = str(value or "").strip()
    if len(text) < 14 or not text[:14].isdigit():
        return None
    try:
        return datetime.strptime(text[:14], "%Y%m%d%H%M%S")
    except ValueError:
        return None


def parse_tencent_payload(data: str, symbol_to_ts: dict[str, str]) -> dict[str, dict]:
    """Parse Tencent's batch response without inferring exchanges from prefixes."""
    result = {}
    for line in str(data or "").split(";"):
        if '="' not in line:
            continue
        left, payload = line.split('="', 1)
        symbol = left.rsplit("_", 1)[-1].lower()
        ts_code = symbol_to_ts.get(symbol)
        if not ts_code:
            continue
        values = payload.rstrip('"').split("~")
        if len(values) < 50:
            continue
        price = _optional_float(values[3])
        quote_time = _parse_quote_time(values[30])
        if price is None or price <= 0 or quote_time is None:
            continue
        result[ts_code] = {
            "ts_code": ts_code,
            "name": str(values[1] or ""),
            "price": price,
            "previous_close": _optional_float(values[4]),
            "day_change_pct": _optional_float(values[32]),
            "amount_wan": _optional_float(values[37]),
            "turnover_rate": _optional_float(values[38]),
            "volume_ratio": _optional_float(values[49]),
            "quote_time": quote_time,
        }
    return result


def fetch_tencent_quotes(ts_codes: list[str], batch_size: int = 250) -> dict[str, dict]:
    """Fetch one batch quote per chunk; the caller persists results before serving."""
    normalized = [code for code in (_normalize_ts_code(item) for item in ts_codes) if code]
    quotes: dict[str, dict] = {}
    for start in range(0, len(normalized), batch_size):
        batch = normalized[start:start + batch_size]
        symbol_to_ts = {
            symbol: ts_code
            for ts_code in batch
            if (symbol := _provider_symbol(ts_code))
        }
        if not symbol_to_ts:
            continue
        request = Request(
            "https://qt.gtimg.cn/q=" + ",".join(symbol_to_ts),
            headers={"User-Agent": _USER_AGENT},
        )
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("gbk", errors="replace")
        quotes.update(parse_tencent_payload(payload, symbol_to_ts))
    return quotes


def _load_latest_pool() -> tuple[date | None, dict[str, str]]:
    with get_db_session() as db:
        run = db.query(IndustryStageRun).filter(
            IndustryStageRun.status == "READY",
        ).order_by(IndustryStageRun.trade_date.desc()).first()
        if run is None:
            return None, {}
        rows = db.query(
            IndustryStageStockDaily.ts_code,
            IndustryStageStockDaily.stock_name,
        ).filter(
            IndustryStageStockDaily.trade_date == run.trade_date,
        ).all()
    return run.trade_date, {str(row.ts_code): str(row.stock_name or "") for row in rows}


def _state_values(
    *,
    now: datetime,
    pool_trade_date: date | None,
    status: str,
    is_market_day: bool | None,
    expected_count: int,
    quote_count: int,
    snapshot_time: datetime | None,
    message: str,
) -> dict:
    coverage = round(quote_count / expected_count * 100, 2) if expected_count else 0
    return {
        "trade_date": now.date(),
        "pool_trade_date": pool_trade_date,
        "status": status,
        "is_market_day": is_market_day,
        "expected_count": expected_count,
        "quote_count": quote_count,
        "coverage": coverage,
        "snapshot_time": snapshot_time,
        "source": SOURCE,
        "message": message,
        "updated_at": now,
    }


def _upsert_state(db, values: dict, preserve_snapshot: bool = False) -> None:
    statement = pg_insert(IndustryStageRealtimeState.__table__).values(values)
    update_values = {
        "pool_trade_date": statement.excluded.pool_trade_date,
        "status": statement.excluded.status,
        "is_market_day": statement.excluded.is_market_day,
        "expected_count": statement.excluded.expected_count,
        "source": statement.excluded.source,
        "message": statement.excluded.message,
        "updated_at": statement.excluded.updated_at,
    }
    if not preserve_snapshot:
        update_values.update({
            "quote_count": statement.excluded.quote_count,
            "coverage": statement.excluded.coverage,
            "snapshot_time": statement.excluded.snapshot_time,
        })
    db.execute(statement.on_conflict_do_update(
        constraint="uq_industry_stage_realtime_state_date",
        set_=update_values,
    ))


def _save_state(values: dict, preserve_snapshot: bool = False) -> None:
    with get_db_session() as db:
        _upsert_state(db, values, preserve_snapshot=preserve_snapshot)
        db.commit()


def _quote_values(
    quotes: dict[str, dict],
    pool_names: dict[str, str],
    pool_trade_date: date,
    trade_date: date,
) -> list[dict]:
    values = []
    for ts_code, quote in quotes.items():
        if ts_code not in pool_names or quote["quote_time"].date() != trade_date:
            continue
        values.append({
            "trade_date": trade_date,
            "pool_trade_date": pool_trade_date,
            "ts_code": ts_code,
            "stock_name": quote.get("name") or pool_names[ts_code],
            "price": quote["price"],
            "previous_close": quote.get("previous_close"),
            "day_change_pct": quote.get("day_change_pct"),
            "amount_wan": quote.get("amount_wan"),
            "turnover_rate": quote.get("turnover_rate"),
            "volume_ratio": quote.get("volume_ratio"),
            "snapshot_time": quote["quote_time"],
            "source": SOURCE,
            "updated_at": datetime.now(),
        })
    return values


def collect_realtime_snapshot(now: datetime | None = None, fetcher=None) -> dict:
    """Collect the latest quote layer for the most recent READY stage pool."""
    global _retry_after
    current = now or datetime.now()
    if market_phase(current) != PHASE_TRADING:
        return {"status": "SKIPPED", "reason": "outside_session"}
    if _market_day_cache.get(current.date()) is False:
        return {"status": "CLOSED", "reason": "non_market_day"}
    if _retry_after and current < _retry_after:
        return {"status": "SKIPPED", "reason": "source_backoff"}

    pool_trade_date, pool_names = _load_latest_pool()
    expected_count = len(pool_names)
    if pool_trade_date is None or not pool_names:
        values = _state_values(
            now=current,
            pool_trade_date=pool_trade_date,
            status="MISSING",
            is_market_day=None,
            expected_count=0,
            quote_count=0,
            snapshot_time=None,
            message="没有可供盘中覆盖的 READY 阶段池",
        )
        _save_state(values)
        return values

    try:
        raw_quotes = (fetcher or fetch_tencent_quotes)(list(pool_names))
    except Exception as exc:
        _retry_after = current + timedelta(seconds=30)
        values = _state_values(
            now=current,
            pool_trade_date=pool_trade_date,
            status="FAILED",
            is_market_day=_market_day_cache.get(current.date()),
            expected_count=expected_count,
            quote_count=0,
            snapshot_time=None,
            message=f"实时行情源暂时不可用：{type(exc).__name__}",
        )
        _save_state(values, preserve_snapshot=True)
        logger.warning("[industry-stage] realtime quote source failed: %s", exc)
        return values

    if not raw_quotes:
        _retry_after = current + timedelta(seconds=30)
        values = _state_values(
            now=current,
            pool_trade_date=pool_trade_date,
            status="FAILED",
            is_market_day=_market_day_cache.get(current.date()),
            expected_count=expected_count,
            quote_count=0,
            snapshot_time=None,
            message="实时行情源未返回数据",
        )
        _save_state(values, preserve_snapshot=True)
        return values

    quote_rows = _quote_values(raw_quotes, pool_names, pool_trade_date, current.date())
    if not quote_rows:
        if current.time() >= time(9, 35):
            _market_day_cache[current.date()] = False
            status = "CLOSED"
            message = "行情源仍停留在上一交易日，今天按休市处理"
            is_market_day = False
        else:
            status = "WAITING"
            message = "集合竞价行情尚未形成，等待同日快照"
            is_market_day = None
        values = _state_values(
            now=current,
            pool_trade_date=pool_trade_date,
            status=status,
            is_market_day=is_market_day,
            expected_count=expected_count,
            quote_count=0,
            snapshot_time=None,
            message=message,
        )
        _save_state(values)
        return values

    _retry_after = None
    _market_day_cache[current.date()] = True
    quote_count = len(quote_rows)
    coverage = quote_count / expected_count * 100
    status = "READY" if coverage >= MIN_READY_COVERAGE else "PARTIAL"
    snapshot_time = max(row["snapshot_time"] for row in quote_rows)
    state = _state_values(
        now=current,
        pool_trade_date=pool_trade_date,
        status=status,
        is_market_day=True,
        expected_count=expected_count,
        quote_count=quote_count,
        snapshot_time=snapshot_time,
        message=f"盘中行情 {quote_count}/{expected_count}，阶段名单保持 {pool_trade_date.isoformat()} 快照",
    )

    with get_db_session() as db:
        for start in range(0, len(quote_rows), 250):
            statement = pg_insert(IndustryStageRealtimeQuote.__table__).values(
                quote_rows[start:start + 250],
            )
            db.execute(statement.on_conflict_do_update(
                constraint="uq_industry_stage_realtime_quote_date_code",
                set_={
                    "pool_trade_date": statement.excluded.pool_trade_date,
                    "stock_name": statement.excluded.stock_name,
                    "price": statement.excluded.price,
                    "previous_close": statement.excluded.previous_close,
                    "day_change_pct": statement.excluded.day_change_pct,
                    "amount_wan": statement.excluded.amount_wan,
                    "turnover_rate": statement.excluded.turnover_rate,
                    "volume_ratio": statement.excluded.volume_ratio,
                    "snapshot_time": statement.excluded.snapshot_time,
                    "source": statement.excluded.source,
                    "updated_at": statement.excluded.updated_at,
                },
            ))
        _upsert_state(db, state)
        db.commit()

    logger.debug("[industry-stage] realtime snapshot saved: %s", state)
    return state
