"""回马枪 v1.1.5 当天实时筛选、快照持久化与结果读取。"""

from __future__ import annotations

from collections import defaultdict
import csv
from datetime import date, datetime, time, timedelta
import hashlib
import io
import json
import logging
from statistics import fmean
import threading
import uuid
from zoneinfo import ZoneInfo

from sqlalchemy import func

from db.models import HorsebackCandidate, HorsebackResult, HorsebackRun, StockDailyKline, StockFlow
from db.session import get_db_session

from . import STRATEGY_VERSION
from .config_store import TokenStore
from .ifind_client import build_daily_limit_up_query, collect_daily_limit_up_candidates, collect_realtime_quotes
from .scoring import (
    MIN_HISTORY_BARS,
    GateOptions,
    ScoreOptions,
    apply_realtime_entry_gate,
    evaluate_candidate,
    is_board_candidate,
)


logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})
ACTIVE_STATUSES = frozenset({"QUEUED", "COLLECTING", "SCORING", "QUOTING", "CANCEL_REQUESTED"})
DAILY_COVERAGE_RATIO_MIN = 0.95
MODE_LIVE = "live"
MODE_HISTORICAL_LIVE = "historical_live"
MODE_LEGACY_REPLAY = "replay"

DATA_CONTRACT = {
    "mode": "当天与历史截止日均按 v1.1.5 执行实时确认；历史扫描为历史结构 + 当前行情，不是历史回测",
    "candidate_source": "iFinD MCP search_stocks，逐交易日涨停池先落库",
    "candidate_limit": "涨停次数与整理日条件通过后全池读取本地日线；扫描上限仅限制形态达标后的实时行情确认数量",
    "kline_source": "stock_daily_kline / Tushare daily",
    "adjustment": "不复权（沿用 stock_daily_kline 当前口径）",
    "cutoff": "结构评分严格截止到所选日期；实时行情使用扫描或刷新时的当前快照，不写入历史日线",
    "realtime_source": "iFinD stock_highfreq_quotes，行情快照写入本次结果",
    "trading_calendar": "由 stock_daily_kline 实际交易日期推导",
    "missing_policy": "十日涨停池任一交易日缺失则扫描失败；盘后当日日线覆盖不足上一日 95% 时回退上一完整日；不足 63 根或关键字段缺失标为数据无效；无实时行情留在待触发/观察池",
    "execution_scope": "研究候选，不自动下单",
}

_SHANGHAI = ZoneInfo("Asia/Shanghai")
_active_lock = threading.Lock()
_cancel_events: dict[str, threading.Event] = {}


class ActiveRunError(RuntimeError):
    def __init__(self, run_id: str):
        self.run_id = run_id
        super().__init__(f"已有回马枪任务正在运行：{run_id}")


def _now_shanghai() -> datetime:
    return datetime.now(_SHANGHAI).replace(tzinfo=None)


def _today_shanghai() -> date:
    return _now_shanghai().date()


def _float(value):
    return float(value) if value is not None else None


def _date(value):
    if not value:
        return None
    return value if isinstance(value, date) else date.fromisoformat(str(value)[:10])


def _datetime(value):
    return value.isoformat() if value else None


def _loads(value: str | None, fallback):
    try:
        return json.loads(value) if value else fallback
    except json.JSONDecodeError:
        return fallback


def _apply_candidate_limit(candidates: list[dict], max_candidates: int) -> list[dict]:
    return candidates if max_candidates == 0 else candidates[:max_candidates]


def _select_structure_candidates(pool: list[dict], min_days: int, max_days: int) -> list[dict]:
    """保留全部符合整理日区间的候选；实时确认上限不在本阶段生效。"""

    chosen = []
    for item in pool:
        days = item["days_since_limit"]
        if days is not None and min_days <= days <= max_days:
            chosen.append(item)
        else:
            item["exclusion"] = "涨停后整理天数不在设定区间"
    return chosen


def _select_realtime_rows(rows: list[HorsebackResult], max_candidates: int) -> list[HorsebackResult]:
    """只为形态达标结果读取行情，并按结构分数应用实时确认上限。"""

    eligible = [row for row in rows if row.status != "INVALID" and bool(row.structure_eligible)]
    eligible.sort(key=lambda row: (-(row.score if row.score is not None else -1), row.ts_code))
    return _apply_candidate_limit(eligible, max_candidates)


def _run_mode(requested_end_date: date | None, today: date) -> str:
    return MODE_HISTORICAL_LIVE if requested_end_date and requested_end_date < today else MODE_LIVE


def _uses_realtime_confirmation(mode: str | None) -> bool:
    return (mode or MODE_LIVE) != MODE_LEGACY_REPLAY


def _has_required_daily_coverage(current_count: int, previous_count: int) -> bool:
    if current_count <= 0:
        return False
    return previous_count <= 0 or current_count >= previous_count * DAILY_COVERAGE_RATIO_MIN


def _daily_symbol_count(db, trade_date: date) -> int:
    return db.query(func.count(func.distinct(StockDailyKline.ts_code))).filter(
        StockDailyKline.trade_date == trade_date
    ).scalar() or 0


def _latest_completed_trade_date(db, now: datetime | None = None) -> date | None:
    current = now or _now_shanghai()
    latest = db.query(func.max(StockDailyKline.trade_date)).filter(
        StockDailyKline.trade_date <= current.date()
    ).scalar()
    if not latest:
        return None
    if current.weekday() < 5 and current.time() < time(15, 5) and latest == current.date():
        return db.query(func.max(StockDailyKline.trade_date)).filter(
            StockDailyKline.trade_date < current.date()
        ).scalar()
    if latest != current.date():
        return latest

    previous = db.query(func.max(StockDailyKline.trade_date)).filter(
        StockDailyKline.trade_date < latest
    ).scalar()
    if not previous:
        return latest
    latest_count = _daily_symbol_count(db, latest)
    previous_count = _daily_symbol_count(db, previous)
    if _has_required_daily_coverage(latest_count, previous_count):
        return latest
    logger.warning(
        "[horseback] 当日日线覆盖不足，回退上一完整交易日: %s=%d, %s=%d",
        latest.isoformat(), latest_count, previous.isoformat(), previous_count,
    )
    return previous


def _recent_trade_dates(db, target: date, count: int) -> list[date]:
    rows = db.query(StockDailyKline.trade_date).filter(
        StockDailyKline.trade_date <= target
    ).distinct().order_by(StockDailyKline.trade_date.desc()).limit(count).all()
    return sorted(row[0] for row in rows)


def _trading_days_between(trade_dates: list[date], latest_limit_date: date | None, as_of_date: date) -> int | None:
    if not latest_limit_date:
        return None
    index_by_date = {trade_date: index for index, trade_date in enumerate(trade_dates)}
    if latest_limit_date not in index_by_date or as_of_date not in index_by_date:
        return None
    return index_by_date[as_of_date] - index_by_date[latest_limit_date]


def _bars_by_symbol(db, symbols: list[str], target: date) -> dict[str, list[dict]]:
    if not symbols:
        return {}
    history_dates = _recent_trade_dates(db, target, 100)
    if not history_dates:
        return {}
    rows = db.query(StockDailyKline).filter(
        StockDailyKline.ts_code.in_(symbols),
        StockDailyKline.trade_date >= history_dates[0],
        StockDailyKline.trade_date <= target,
    ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()
    grouped = defaultdict(list)
    for row in rows:
        grouped[row.ts_code].append({
            "date": row.trade_date,
            "open": _float(row.open),
            "high": _float(row.high),
            "low": _float(row.low),
            "close": _float(row.close),
            "volume": _float(row.volume),
            "pct_chg": _float(row.pct_chg),
        })
    return {symbol: values[-80:] for symbol, values in grouped.items()}


def _latest_names(db, symbols: list[str], target: date) -> dict[str, str]:
    if not symbols:
        return {}
    rows = db.query(StockFlow.ts_code, StockFlow.name, StockFlow.trade_date).filter(
        StockFlow.ts_code.in_(symbols),
        StockFlow.trade_date <= target,
        StockFlow.trade_date >= target - timedelta(days=60),
    ).order_by(StockFlow.trade_date.desc()).all()
    names = {}
    for symbol, name, _ in rows:
        names.setdefault(symbol, name or "")
    return names


def _result_sort_key(item: dict):
    return (
        item["status"] != "SELECTED",
        item["status"] == "INVALID",
        item["status"] != "WATCHING",
        -(item["score"] or -1),
        item["ts_code"],
    )


def _run_dict(run: HorsebackRun, include_results: bool = False, db=None) -> dict:
    payload = {
        "id": run.id,
        "status": run.status,
        "source": run.source,
        "strategy_version": run.strategy_version,
        "mode": run.mode or MODE_LIVE,
        "requested_end_date": run.requested_end_date.isoformat() if run.requested_end_date else None,
        "as_of_date": run.as_of_date.isoformat() if run.as_of_date else None,
        "window_start": run.window_start.isoformat() if run.window_start else None,
        "window_end": run.window_end.isoformat() if run.window_end else None,
        "options": {
            "min_consolidation_days": run.min_consolidation_days,
            "max_consolidation_days": run.max_consolidation_days,
            "min_limit_count": run.min_limit_count,
            "max_limit_count": run.max_limit_count,
            "min_score": run.min_score,
            "max_candidates": run.max_candidates,
            "live_rise_pct_min": run.live_rise_pct_min,
            "live_volume_ratio_min": run.live_volume_ratio_min,
            "allow_gem": bool(run.allow_gem),
            "allow_star": bool(run.allow_star),
        },
        "progress": {
            "source_count": run.source_count or 0,
            "pool_count": run.pool_count or 0,
            "prefiltered_count": run.prefiltered_count or 0,
            "total": run.total_count or 0,
            "processed": run.processed_count or 0,
            "selected": run.selected_count or 0,
            "quote_total": run.quote_total or 0,
            "quote_processed": run.quote_processed or 0,
        },
        "realtime_at": _datetime(run.realtime_at),
        "message": run.message,
        "error": run.error,
        "cancel_requested": bool(run.cancel_requested),
        "started_at": _datetime(run.started_at),
        "completed_at": _datetime(run.completed_at),
        "created_at": _datetime(run.created_at),
        "updated_at": _datetime(run.updated_at),
        "data_contract": DATA_CONTRACT,
    }
    if include_results and db is not None:
        rows = db.query(HorsebackResult).filter(HorsebackResult.run_id == run.id).all()
        results = [_result_dict(row) for row in rows]
        results.sort(key=_result_sort_key)
        payload["results"] = results
        structure_eligible = sum(bool(row.structure_eligible) for row in rows)
        payload["progress"]["structure_eligible"] = structure_eligible
        payload["progress"]["quote_skipped"] = max(structure_eligible - (run.quote_total or 0), 0)
    return payload


def _result_dict(row: HorsebackResult) -> dict:
    return {
        "ts_code": row.ts_code,
        "code": row.ts_code.split(".")[0],
        "name": row.name or row.ts_code,
        "status": row.status,
        "score": row.score,
        "kline_count": row.kline_count,
        "limit_up_count": row.limit_up_count,
        "leader": bool(row.leader),
        "structure_eligible": row.structure_eligible,
        "last_limit_date": row.last_limit_date.isoformat() if row.last_limit_date else None,
        "days_since_limit": row.days_since_limit,
        "close": _float(row.close),
        "pct_chg": _float(row.pct_chg),
        "ma5": _float(row.ma5),
        "ma10": _float(row.ma10),
        "ma20": _float(row.ma20),
        "ma60": _float(row.ma60),
        "pullback_pct": _float(row.pullback_pct),
        "volume_ratio": _float(row.volume_ratio),
        "ma_convergence_pct": _float(row.ma_convergence_pct),
        "suggested_buy": _float(row.suggested_buy),
        "stop_loss": _float(row.stop_loss),
        "realtime_price": _float(row.realtime_price),
        "realtime_change_pct": _float(row.realtime_change_pct),
        "realtime_volume_ratio": _float(row.realtime_volume_ratio),
        "today_ma5": _float(row.today_ma5),
        "first_ma5_break": row.first_ma5_break,
        "realtime_gate": row.realtime_gate,
        "realtime_state": row.realtime_state,
        "realtime_at": _datetime(row.realtime_at),
        "components": _loads(row.components_json, []),
        "hard_failures": _loads(row.hard_failures_json, []),
    }


def get_run(run_id: str, include_results: bool = True) -> dict | None:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        return _run_dict(run, include_results, db) if run else None


def get_latest_run(include_results: bool = True) -> dict | None:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(
            HorsebackRun.strategy_version == STRATEGY_VERSION
        ).order_by(HorsebackRun.created_at.desc()).first()
        return _run_dict(run, include_results, db) if run else None


def get_today_run_attempt_count(requested_date: date | None = None) -> int:
    """返回当天 v1.1.5 已创建任务数，用于限制自动补扫次数。"""

    target_date = requested_date or _today_shanghai()
    with get_db_session() as db:
        return db.query(func.count(HorsebackRun.id)).filter(
            HorsebackRun.strategy_version == STRATEGY_VERSION,
            HorsebackRun.requested_end_date == target_date,
        ).scalar() or 0


def recover_orphaned_runs() -> int:
    """回收孤儿任务：进程崩溃/被杀导致 ACTIVE 状态滞留数据库的 run。

    当前进程的 _cancel_events 在 DB 行写入前就已登记（start_run /
    refresh_quotes 均先 reserve 再落库），因此 ACTIVE 状态却不在
    _cancel_events 中的 run 必然没有执行线程，可安全回收：
    - QUOTING 残留 = 扫描已完成、仅行情刷新被中断 → 恢复为 COMPLETED；
    - 其余（QUEUED/COLLECTING/SCORING）= 扫描本身被中断 → 标记 FAILED。
    不回收会永久阻塞后续定时扫描与刷新（最新任务一直是 ACTIVE）。
    """

    with _active_lock:
        live_ids = set(_cancel_events)
    recovered = 0
    with get_db_session() as db:
        runs = db.query(HorsebackRun).filter(
            HorsebackRun.status.in_(sorted(ACTIVE_STATUSES))
        ).all()
        for run in runs:
            if run.id in live_ids:
                continue
            if run.status == "QUOTING":
                run.status = "COMPLETED"
                run.message = (run.message or "扫描完成") + "（进程重启中断了行情刷新，已自动恢复）"
            else:
                run.status = "FAILED"
                run.error = "进程重启导致任务中断"
                run.message = "任务被进程重启中断，已自动回收"
            run.completed_at = _now_shanghai()
            run.updated_at = _now_shanghai()
            recovered += 1
        if recovered:
            db.commit()
            logger.warning("[horseback] 已回收孤儿任务 %d 个（进程重启残留）", recovered)
    return recovered


def _update_run(run_id: str, **values) -> None:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        if run:
            for key, value in values.items():
                setattr(run, key, value)
            db.commit()


def _cancelled(run_id: str, event: threading.Event) -> bool:
    if event.is_set():
        return True
    with get_db_session() as db:
        value = db.query(HorsebackRun.cancel_requested).filter(HorsebackRun.id == run_id).scalar()
        return bool(value)


def _reserve_run(run_id: str, cancel_event: threading.Event) -> None:
    with _active_lock:
        if _cancel_events:
            raise ActiveRunError(next(iter(_cancel_events)))
        _cancel_events[run_id] = cancel_event


def _release_run(run_id: str) -> None:
    with _active_lock:
        _cancel_events.pop(run_id, None)


def start_run(
    requested_end_date: date | None,
    min_consolidation_days: int,
    max_consolidation_days: int,
    min_limit_count: int,
    max_limit_count: int,
    min_score: int,
    max_candidates: int,
    live_rise_pct_min: float = 3.0,
    live_volume_ratio_min: float = 1.2,
    allow_gem: bool = False,
    allow_star: bool = False,
) -> dict:
    """创建实时任务；过去日期按 v1.1.5 使用历史结构与当前行情确认。"""

    TokenStore().load()
    today = _today_shanghai()
    if requested_end_date and requested_end_date > today:
        raise ValueError("筛选日期不能晚于今天")
    run_mode = _run_mode(requested_end_date, today)
    historical = run_mode == MODE_HISTORICAL_LIVE
    run_id = str(uuid.uuid4())
    cancel_event = threading.Event()
    _reserve_run(run_id, cancel_event)
    try:
        with get_db_session() as db:
            # 历史扫描以目标日收盘后视角取基准日线；实时模式取当前最近已完成日线。
            effective_now = datetime.combine(requested_end_date, time(16, 0)) if historical else None
            as_of = _latest_completed_trade_date(db, effective_now)
            if not as_of:
                raise ValueError("当前没有可用于结构评分的已完成 A 股日线")
            trade_dates = _recent_trade_dates(db, as_of, 10)
            if len(trade_dates) < 10:
                raise ValueError("候选池需要至少 10 个已完成交易日")
            run = HorsebackRun(
                id=run_id,
                status="QUEUED",
                source="ifind_mcp",
                strategy_version=STRATEGY_VERSION,
                mode=run_mode,
                requested_end_date=requested_end_date or today,
                as_of_date=as_of,
                window_start=trade_dates[0],
                window_end=trade_dates[-1],
                min_consolidation_days=min_consolidation_days,
                max_consolidation_days=max_consolidation_days,
                min_limit_count=min_limit_count,
                max_limit_count=max_limit_count,
                min_score=min_score,
                max_candidates=max_candidates,
                live_rise_pct_min=live_rise_pct_min,
                live_volume_ratio_min=live_volume_ratio_min,
                allow_gem=allow_gem,
                allow_star=allow_star,
                source_query="\n".join(build_daily_limit_up_query(item) for item in trade_dates),
                message="历史扫描已排队，完成结构评分后将读取当前实时行情" if historical else "当天实时任务已排队",
                created_at=_now_shanghai(),
                updated_at=_now_shanghai(),
            )
            db.add(run)
            db.commit()
            payload = _run_dict(run)
        thread = threading.Thread(
            target=_run_and_release,
            args=(run_id, cancel_event),
            name=f"horseback-{run_id[:8]}",
            daemon=True,
        )
        thread.start()
        return payload
    except Exception:
        _release_run(run_id)
        raise


def _run_and_release(run_id: str, cancel_event: threading.Event) -> None:
    try:
        _execute_run(run_id, cancel_event)
    finally:
        _release_run(run_id)


def request_cancel(run_id: str) -> dict | None:
    with _active_lock:
        event = _cancel_events.get(run_id)
        if event:
            event.set()
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        if not run:
            return None
        if run.status not in TERMINAL_STATUSES:
            run.cancel_requested = True
            run.message = "正在取消；当前 iFinD 请求完成后停止"
            run.status = "CANCEL_REQUESTED" if event else "CANCELLED"
            if not event:
                run.completed_at = _now_shanghai()
            db.commit()
        return _run_dict(run, True, db)


def _persist_structure_result(db, run_id: str, result: dict, item: dict) -> None:
    db.add(HorsebackResult(
        run_id=run_id,
        ts_code=result["ts_code"],
        name=result["name"],
        status=result["status"],
        score=result.get("score"),
        kline_count=result.get("kline_count", 0),
        limit_up_count=item.get("effective_count"),
        leader=(item.get("effective_count") or 0) >= 2,
        structure_eligible=bool(result.get("structure_eligible")),
        last_limit_date=_date(result.get("last_limit_date")),
        days_since_limit=result.get("days_since_limit"),
        close=result.get("close"),
        pct_chg=result.get("pct_chg"),
        ma5=result.get("ma5"),
        ma10=result.get("ma10"),
        ma20=result.get("ma20"),
        ma60=result.get("ma60"),
        pullback_pct=result.get("pullback_pct"),
        volume_ratio=result.get("volume_ratio"),
        ma_convergence_pct=result.get("ma_convergence_pct"),
        suggested_buy=result.get("suggested_buy"),
        stop_loss=result.get("stop_loss"),
        components_json=json.dumps(result.get("components", []), ensure_ascii=False),
        hard_failures_json=json.dumps(result.get("hard_failures", []), ensure_ascii=False),
    ))


def _execute_run(run_id: str, cancel_event: threading.Event) -> None:
    try:
        _update_run(run_id, status="COLLECTING", started_at=_now_shanghai(), message="正在生成近10日涨停池")
        with get_db_session() as db:
            run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).one()
            trade_dates = _recent_trade_dates(db, run.as_of_date, 10)
            allow_gem = bool(run.allow_gem)
            allow_star = bool(run.allow_star)
            run_mode = run.mode or MODE_LIVE
        token = TokenStore().load()
        board_filter = lambda symbol, name: is_board_candidate(symbol, name, allow_gem, allow_star)
        source_candidates, raw_payloads = collect_daily_limit_up_candidates(token, trade_dates, board_filter=board_filter)
        payload_hash = hashlib.sha256(
            json.dumps(raw_payloads, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()
        if _cancelled(run_id, cancel_event):
            _update_run(run_id, status="CANCELLED", message="任务已取消", completed_at=_now_shanghai())
            return

        with get_db_session() as db:
            run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).one()
            trade_dates = _recent_trade_dates(db, run.as_of_date, 40)
            symbols = [item["ts_code"] for item in source_candidates]
            names = _latest_names(db, symbols, run.as_of_date)
            prepared = []
            for item in source_candidates:
                symbol = item["ts_code"]
                name = item["name"] or names.get(symbol) or symbol
                latest_limit_date = _date(item.get("latest_limit_date"))
                effective_count = int(item.get("limit_up_count") or 0)
                days_since_limit = _trading_days_between(trade_dates, latest_limit_date, run.as_of_date)
                exclusion = None
                if not is_board_candidate(symbol, name, run.allow_gem, run.allow_star):
                    exclusion = "板块不在筛选范围（主板/创业板/科创板开关）或名称含 ST/退市标记"
                elif not run.min_limit_count <= effective_count <= run.max_limit_count:
                    exclusion = f"涨停次数 {effective_count} 不在 {run.min_limit_count}–{run.max_limit_count}"
                prepared.append({
                    **item,
                    "name": name,
                    "effective_count": effective_count,
                    "last_limit_date": latest_limit_date,
                    "days_since_limit": days_since_limit,
                    "exclusion": exclusion,
                })

            pool = [item for item in prepared if not item["exclusion"]]
            pool.sort(key=lambda item: (-item["effective_count"], item["ts_code"]))
            chosen = _select_structure_candidates(
                pool,
                run.min_consolidation_days,
                run.max_consolidation_days,
            )
            chosen_symbols = {item["ts_code"] for item in chosen}
            for item in prepared:
                db.add(HorsebackCandidate(
                    run_id=run_id,
                    ts_code=item["ts_code"],
                    name=item["name"],
                    source_rank=item["source_rank"],
                    source_limit_count=item.get("limit_up_count"),
                    observed_limit_count=item.get("limit_up_count"),
                    effective_limit_count=item["effective_count"],
                    last_limit_date=item["last_limit_date"],
                    admitted=item["ts_code"] in chosen_symbols,
                    exclusion_reason=item["exclusion"],
                    source_json=json.dumps(item.get("raw", []), ensure_ascii=False, default=str),
                ))
            run.source_payload_sha256 = payload_hash
            run.source_count = len(source_candidates)
            run.pool_count = len(pool)
            run.prefiltered_count = len(pool) - len(chosen)
            run.total_count = len(chosen)
            run.status = "SCORING"
            run.message = f"候选池已落库，正在全池读取日线结构 0/{len(chosen)}"
            db.commit()
            as_of_date = run.as_of_date
            score_options = ScoreOptions(
                min_score=run.min_score,
                min_consolidation_days=run.min_consolidation_days,
                max_consolidation_days=run.max_consolidation_days,
                allow_gem=bool(run.allow_gem),
                allow_star=bool(run.allow_star),
            )

        with get_db_session() as db:
            bars_map = _bars_by_symbol(db, [item["ts_code"] for item in chosen], as_of_date)
        for processed, item in enumerate(chosen, start=1):
            if _cancelled(run_id, cancel_event):
                _update_run(
                    run_id,
                    status="CANCELLED",
                    processed_count=processed - 1,
                    message=f"任务已取消，保留 {processed - 1} 条已完成结构结果",
                    completed_at=_now_shanghai(),
                )
                return
            result = evaluate_candidate(item["ts_code"], item["name"], bars_map.get(item["ts_code"], []), as_of_date, score_options)
            with get_db_session() as db:
                _persist_structure_result(db, run_id, result, item)
                run_row = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).one()
                run_row.processed_count = processed
                run_row.message = f"正在读取日线结构 {processed}/{len(chosen)}"
                db.commit()

        if _cancelled(run_id, cancel_event):
            _update_run(run_id, status="CANCELLED", message="任务已取消", completed_at=_now_shanghai())
            return
        if not _uses_realtime_confirmation(run_mode):
            # 兼容已生成的 v1.1.6 仅形态回放记录；新历史任务不再进入此模式。
            with get_db_session() as db:
                statuses = [
                    row[0] for row in
                    db.query(HorsebackResult.status).filter(HorsebackResult.run_id == run_id).all()
                ]
            selected = statuses.count("SELECTED")
            invalid = statuses.count("INVALID")
            _update_run(run_id, selected_count=selected)
            _complete_run(
                run_id,
                {"selected": selected, "observations": len(statuses) - selected - invalid},
                "历史回放扫描完成（仅形态评分，无实时门槛）",
            )
            return
        outcome = _refresh_realtime_quotes(run_id, cancel_event)
        if _cancelled(run_id, cancel_event):
            _update_run(run_id, status="CANCELLED", message="任务已取消", completed_at=_now_shanghai())
            return
        prefix = "历史扫描完成（历史结构 + 当前实时行情确认）" if run_mode == MODE_HISTORICAL_LIVE else "扫描完成"
        _complete_run(run_id, outcome, prefix)
    except Exception as exc:
        logger.exception("[horseback] run failed id=%s", run_id)
        _update_run(run_id, status="FAILED", error=str(exc), message="扫描失败", completed_at=_now_shanghai())


def _gate_context(
    row: HorsebackResult,
    bars: list[dict],
    as_of_date: date,
    snapshot_at: datetime,
) -> dict:
    """构造实时门槛基准。

    盘中任务的 ``as_of_date`` 是上一根已完成日线，直接以该日为基准。
    若收盘后新建任务，日线已包含当天收盘价；此时 MA5 上穿仍须以昨日为
    基准，不能把当天收盘价既当“上一日收盘”又当实时价。
    """

    valid_bars = [bar for bar in bars if all(bar.get(key) is not None for key in ("close", "volume"))]
    daily_bar_is_snapshot_day = bool(
        valid_bars
        and as_of_date == snapshot_at.date()
        and valid_bars[-1].get("date") == as_of_date
    )
    reference_bars = valid_bars[:-1] if daily_bar_is_snapshot_day else valid_bars
    reference_close = _float(row.close)
    reference_ma5 = _float(row.ma5)
    if reference_bars:
        reference_close = reference_bars[-1]["close"]
    if len(reference_bars) >= 5:
        reference_ma5 = fmean(bar["close"] for bar in reference_bars[-5:])
    structure_eligible = bool(row.structure_eligible) if row.structure_eligible is not None else row.status == "SELECTED"
    return {
        "status": "INVALID" if row.status == "INVALID" else ("SELECTED" if structure_eligible else "NOT_SELECTED"),
        "structure_eligible": structure_eligible,
        "close": reference_close,
        "ma5": reference_ma5,
        "suggested_buy": _float(row.suggested_buy),
        "stop_loss": _float(row.stop_loss),
        "last_four_closes": [bar["close"] for bar in reference_bars[-4:]],
        "avg_daily_volume5": fmean(bar["volume"] for bar in reference_bars[-5:]) if len(reference_bars) >= 5 else None,
    }


def _write_realtime_result(row: HorsebackResult, result: dict) -> None:
    row.status = result["status"]
    row.structure_eligible = bool(result.get("structure_eligible"))
    row.realtime_price = result.get("realtime_price")
    row.realtime_change_pct = result.get("realtime_change_pct")
    row.realtime_volume_ratio = result.get("realtime_volume_ratio")
    row.realtime_open = result.get("realtime_open")
    row.realtime_high = result.get("realtime_high")
    row.realtime_low = result.get("realtime_low")
    row.realtime_volume = result.get("realtime_volume")
    row.today_ma5 = result.get("today_ma5")
    row.first_ma5_break = result.get("first_ma5_break")
    row.realtime_gate = result.get("realtime_gate")
    row.realtime_state = result.get("realtime_state")
    row.realtime_at = result.get("realtime_at")


def _mark_realtime_not_requested(row: HorsebackResult, snapshot_at: datetime, max_candidates: int) -> None:
    """形态达标但超出实时确认上限时，保留为待触发并明确未请求原因。"""

    row.status = "WATCHING"
    row.realtime_price = None
    row.realtime_change_pct = None
    row.realtime_volume_ratio = None
    row.realtime_open = None
    row.realtime_high = None
    row.realtime_low = None
    row.realtime_volume = None
    row.today_ma5 = None
    row.first_ma5_break = False
    row.realtime_gate = f"形态达标 · 超过实时确认上限 {max_candidates}，未请求行情"
    row.realtime_state = "未请求实时行情"
    row.realtime_at = snapshot_at


def _quote_coverage(quote_symbols: list[str], quotes: dict[str, dict]) -> tuple[int, int]:
    requested = set(quote_symbols)
    processed = sum(symbol in quotes for symbol in requested)
    return processed, len(requested) - processed


def _refresh_realtime_quotes(run_id: str, cancel_event: threading.Event) -> dict:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).one()
        rows = db.query(HorsebackResult).filter(HorsebackResult.run_id == run_id).all()
        quote_rows = _select_realtime_rows(rows, run.max_candidates)
        quote_symbols = [row.ts_code for row in quote_rows]
        run.status = "QUOTING"
        run.quote_total = len(quote_symbols)
        run.quote_processed = 0
        run.message = "正在读取实时行情快照"
        db.commit()
    if _cancelled(run_id, cancel_event):
        return {"selected": 0, "observations": 0, "error": None}

    quote_error = None
    if quote_symbols:
        try:
            quotes, _ = collect_realtime_quotes(TokenStore().load(), quote_symbols)
        except Exception as exc:  # A missing snapshot must produce observation rows, not synthetic prices.
            logger.warning("[horseback] realtime quotes unavailable run=%s: %s", run_id, exc)
            quotes = {}
            quote_error = str(exc)
    else:
        quotes = {}

    snapshot_at = _now_shanghai()
    quote_processed, quote_missing = _quote_coverage(quote_symbols, quotes)
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).one()
        rows = db.query(HorsebackResult).filter(HorsebackResult.run_id == run_id).all()
        quote_rows = _select_realtime_rows(rows, run.max_candidates)
        quote_symbol_set = {row.ts_code for row in quote_rows}
        bars_map = _bars_by_symbol(db, list(quote_symbol_set), run.as_of_date)
        selected = 0
        watching = 0
        observations = 0
        gate_options = GateOptions(
            live_rise_pct_min=run.live_rise_pct_min if run.live_rise_pct_min is not None else 3.0,
            live_volume_ratio_min=run.live_volume_ratio_min if run.live_volume_ratio_min is not None else 1.2,
        )
        for row in rows:
            if row.status == "INVALID":
                continue
            if not bool(row.structure_eligible):
                row.status = "NOT_SELECTED"
            elif row.ts_code not in quote_symbol_set:
                _mark_realtime_not_requested(row, snapshot_at, run.max_candidates)
            else:
                context = _gate_context(row, bars_map.get(row.ts_code, []), run.as_of_date, snapshot_at)
                gated = apply_realtime_entry_gate(context, quotes.get(row.ts_code), snapshot_at, gate_options)
                _write_realtime_result(row, gated)
            if row.status == "SELECTED":
                selected += 1
            elif row.status == "WATCHING":
                watching += 1
            elif row.status != "INVALID":
                observations += 1
        run.selected_count = selected
        run.quote_processed = quote_processed
        run.realtime_at = snapshot_at
        run.error = quote_error
        if quote_error:
            run.message = "实时行情未返回，已保留观察池"
        elif quote_missing:
            run.message = f"实时行情部分缺失（已获取 {quote_processed}/{run.quote_total}），已保留观察池"
        else:
            run.message = "实时行情已刷新"
        db.commit()
    return {
        "selected": selected,
        "watching": watching,
        "observations": observations,
        "error": quote_error,
        "quote_missing": quote_missing,
    }


def _complete_run(run_id: str, outcome: dict, prefix: str) -> None:
    suffix = (
        f"：入选 {outcome['selected']} 只，待触发 {outcome.get('watching', 0)} 只，"
        f"观察池 {outcome['observations']} 只"
    )
    if outcome.get("error"):
        suffix += "（实时行情未返回）"
    elif outcome.get("quote_missing"):
        suffix += f"（{outcome['quote_missing']} 只实时行情缺失）"
    _update_run(run_id, status="COMPLETED", message=prefix + suffix, completed_at=_now_shanghai())


def refresh_quotes(run_id: str) -> dict | None:
    """异步刷新已有 v1.1.5 结果的实时行情快照。"""

    TokenStore().load()
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        if not run:
            return None
        if run.strategy_version != STRATEGY_VERSION:
            raise ValueError("仅支持刷新当前版本任务")
        if not _uses_realtime_confirmation(run.mode):
            raise ValueError("旧版仅形态回放任务不能刷新实时行情")
        if run.status in ACTIVE_STATUSES:
            raise ActiveRunError(run.id)
        if not db.query(HorsebackResult.id).filter(HorsebackResult.run_id == run_id).first():
            raise ValueError("当前任务没有可刷新的结果")
    cancel_event = threading.Event()
    _reserve_run(run_id, cancel_event)
    _update_run(run_id, status="QUOTING", cancel_requested=False, message="实时行情刷新已排队", error=None)
    thread = threading.Thread(
        target=_refresh_and_release,
        args=(run_id, cancel_event),
        name=f"horseback-quotes-{run_id[:8]}",
        daemon=True,
    )
    thread.start()
    return get_run(run_id)


def _refresh_and_release(run_id: str, cancel_event: threading.Event) -> None:
    try:
        outcome = _refresh_realtime_quotes(run_id, cancel_event)
        if _cancelled(run_id, cancel_event):
            _update_run(run_id, status="CANCELLED", message="实时行情刷新已取消", completed_at=_now_shanghai())
        else:
            _complete_run(run_id, outcome, "实时行情已刷新")
    except Exception as exc:
        logger.exception("[horseback] quote refresh failed id=%s", run_id)
        _update_run(run_id, status="FAILED", error=str(exc), message="实时行情刷新失败", completed_at=_now_shanghai())
    finally:
        _release_run(run_id)


def _realtime_snapshot(row: HorsebackResult) -> dict | None:
    if row.realtime_price is None or row.realtime_at is None:
        return None
    return {
        "price": _float(row.realtime_price),
        "change_pct": _float(row.realtime_change_pct),
        "open": _float(row.realtime_open),
        "high": _float(row.realtime_high),
        "low": _float(row.realtime_low),
        "volume": _float(row.realtime_volume),
        "at": _datetime(row.realtime_at),
        "state": row.realtime_state,
    }


def _bars_with_realtime_snapshot(bars: list[dict], realtime: dict | None) -> tuple[list[dict], bool]:
    output = [dict(item) for item in bars]
    if not output or not realtime or realtime.get("price") is None or not realtime.get("at"):
        return output, False
    snapshot_date = _date(realtime["at"])
    if not snapshot_date:
        return output, False
    price = realtime["price"]
    previous_close = output[-1].get("close")
    open_price = realtime.get("open") if realtime.get("open") is not None else previous_close
    high = realtime.get("high") if realtime.get("high") is not None else price
    low = realtime.get("low") if realtime.get("low") is not None else price
    if any(value is None for value in (open_price, high, low, price)):
        return output, False
    provisional = {
        "date": snapshot_date,
        "open": open_price,
        "high": max(high, open_price, price),
        "low": min(low, open_price, price),
        "close": price,
        "volume": realtime.get("volume"),
        "pct_chg": realtime.get("change_pct"),
        "provisional": True,
    }
    existing_index = next((index for index, bar in enumerate(output) if bar["date"] == snapshot_date), None)
    if existing_index is not None:
        output[existing_index] = {**output[existing_index], **provisional}
    elif snapshot_date > output[-1]["date"]:
        output.append(provisional)
    else:
        return output, False
    return output, True


def get_kline(run_id: str, symbol: str) -> dict | None:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        result = db.query(HorsebackResult).filter(
            HorsebackResult.run_id == run_id,
            HorsebackResult.ts_code == symbol,
        ).first()
        if not run or not result:
            return None
        raw_bars = _bars_by_symbol(db, [symbol], run.as_of_date).get(symbol, [])
        bars = [bar for bar in raw_bars if all(bar.get(key) is not None for key in ("open", "high", "low", "close"))]
        realtime = _realtime_snapshot(result)
        display_bars, realtime_bar_included = _bars_with_realtime_snapshot(bars, realtime)
        closes = []
        output = []
        for bar in display_bars:
            closes.append(bar["close"])
            output.append({
                **bar,
                "date": bar["date"].isoformat(),
                "ma5": round(fmean(closes[-5:]), 4) if len(closes) >= 5 else None,
                "ma10": round(fmean(closes[-10:]), 4) if len(closes) >= 10 else None,
                "ma20": round(fmean(closes[-20:]), 4) if len(closes) >= 20 else None,
                "ma60": round(fmean(closes[-60:]), 4) if len(closes) >= 60 else None,
            })
        return {
            "run_id": run_id,
            "ts_code": symbol,
            "name": result.name or symbol,
            "as_of_date": run.as_of_date.isoformat(),
            "source": DATA_CONTRACT["kline_source"],
            "adjustment": DATA_CONTRACT["adjustment"],
            "missing_bar_count": len(raw_bars) - len(bars),
            "realtime": realtime,
            "realtime_bar_included": realtime_bar_included,
            "bars": output,
        }


def export_csv(run_id: str) -> tuple[str, str] | None:
    with get_db_session() as db:
        run = db.query(HorsebackRun).filter(HorsebackRun.id == run_id).first()
        if not run:
            return None
        requested_end_date = run.requested_end_date
        results = [_result_dict(row) for row in db.query(HorsebackResult).filter(HorsebackResult.run_id == run_id).all()]
    results.sort(key=_result_sort_key)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "所属池", "评分", "代码", "名称", "龙头标记", "最近涨停日", "整理天数", "日线收盘",
        "实时价", "实时涨跌幅%", "实时量比", "首次站上MA5", "今日入选条件", "实时更新时间", "实时状态",
        "建议买入价", "建议止损价", "回撤%", "整理量比", "均线离散%", "结构理由", "风险",
    ])
    for item in results:
        safe_name = item["name"]
        if safe_name[:1] in ("=", "+", "-", "@"):
            safe_name = "'" + safe_name
        writer.writerow([
            "入选" if item["status"] == "SELECTED" else (
                "待触发" if item["status"] == "WATCHING" else ("数据无效" if item["status"] == "INVALID" else "观察池")
            ),
            item["score"], item["ts_code"], safe_name, "龙头候选" if item["leader"] else "",
            item["last_limit_date"], item["days_since_limit"], item["close"],
            item["realtime_price"], item["realtime_change_pct"], item["realtime_volume_ratio"],
            "是" if item["first_ma5_break"] else "否", item["realtime_gate"], item["realtime_at"], item["realtime_state"],
            item["suggested_buy"], item["stop_loss"], item["pullback_pct"], item["volume_ratio"], item["ma_convergence_pct"],
            "；".join(component["label"] for component in item["components"] if component.get("points")), "；".join(item["hard_failures"]),
        ])
    return output.getvalue(), f"回马枪选股_{requested_end_date.isoformat()}_{run_id[:8]}.csv"
