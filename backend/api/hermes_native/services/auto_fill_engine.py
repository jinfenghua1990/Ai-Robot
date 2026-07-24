from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Optional, Union

from api.hermes_native.db_connector import execute_query

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT_DIR / "backend"
REPORT_DIR = BACKEND_ROOT / "reports"
STATE_PATH = REPORT_DIR / "auto_fill_state.json"
SCRIPT_PATH = BACKEND_ROOT / "scripts" / "robot1_auto_refill.py"
WATCH_INTERVAL_SECONDS = 600
WATCH_MIN_INTERVAL_SECONDS = 120
WATCH_JOB_PROFILES: dict[str, dict[str, Any]] = {
    "core_refresh": {
        "label": "核心快补",
        "base_seconds": 180,
        "backoff": 1.35,
        "cap_seconds": 900,
    },
    "north_money_refresh": {
        "label": "北向资金守护",
        "base_seconds": 180,
        "backoff": 1.25,
        "cap_seconds": 900,
    },
    "margin_refresh": {
        "label": "融资融券守护",
        "base_seconds": 1200,
        "backoff": 1.4,
        "cap_seconds": 3600,
    },
    "hk_refresh": {
        "label": "港股日线守护",
        "base_seconds": 1500,
        "backoff": 1.45,
        "cap_seconds": 5400,
    },
    "youzi_refresh": {
        "label": "游资补齐",
        "base_seconds": 300,
        "backoff": 1.45,
        "cap_seconds": 1200,
    },
}


CORE_TABLES = {
    "kline_daily": "SELECT MAX(trade_date) AS latest FROM kline_daily WHERE market IN ('SH', 'SZ', 'BJ')",
    "index_data": "SELECT MAX(trade_date) AS latest FROM index_data WHERE market = 'CN_A'",
    "market_sentiment_daily": "SELECT MAX(trade_date) AS latest FROM market_sentiment_daily WHERE market = 'CN_A'",
    "limit_up_pool_daily": "SELECT MAX(trade_date) AS latest FROM limit_up_pool_daily WHERE market = 'CN_A'",
    "industry_board_daily": "SELECT MAX(trade_date) AS latest FROM industry_board_daily",
    "concept_board_daily": "SELECT MAX(trade_date) AS latest FROM concept_board_daily",
    "leader_stock_daily": "SELECT MAX(trade_date) AS latest FROM leader_stock_daily WHERE market = 'CN_A'",
}

NORTH_MONEY_TABLES = {
    "north_money_flow": "SELECT MAX(trade_date) AS latest FROM north_money_flow",
}

MARGIN_TABLES = {
    "margin_data": "SELECT MAX(trade_date) AS latest FROM margin_data",
}

HK_TABLES = {
    "hk_daily_kline": "SELECT MAX(trade_date) AS latest FROM kline_daily WHERE market = 'HK'",
}

YOUZI_TABLES = {
    "youzi_lhb_daily": "SELECT MAX(trade_date) AS latest FROM youzi_lhb_daily",
    "youzi_seat_daily": "SELECT MAX(trade_date) AS latest FROM youzi_seat_daily",
}

JOB_DEFINITIONS: dict[str, dict[str, Any]] = {
    "core_refresh": {
        "tables": CORE_TABLES,
        "reason": "核心盘后数据存在缺口或滞后，优先补齐 K线 / 指数 / 情绪 / 涨停 / 板块 / 龙头。",
    },
    "north_money_refresh": {
        "tables": NORTH_MONEY_TABLES,
        "reason": "北向资金数据存在缺口，进入北向资金独立守护链路。",
    },
    "margin_refresh": {
        "tables": MARGIN_TABLES,
        "reason": "融资融券数据存在缺口，进入融资融券独立守护链路。",
    },
    "hk_refresh": {
        "tables": HK_TABLES,
        "reason": "港股收盘数据存在缺口，进入港股日线独立守护链路。",
    },
    "youzi_refresh": {
        "tables": YOUZI_TABLES,
        "reason": "龙虎榜 / 席位数据存在缺口，进入游资链路自动补齐。",
    },
}


def _ensure_dirs() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def _normalize_date(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip()
    if not text:
        return None
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return text


def _parse_date(value: Any) -> Optional[datetime]:
    if value in (None, "", []):
        return None
    text = str(value).strip().replace("T", " ").replace("Z", "")
    if not text:
        return None
    for fmt in (
        "%Y/%m/%d %H:%M:%S.%f",
        "%Y/%m/%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            if fmt == "%Y-%m-%d":
                candidate = text[:10]
            elif fmt == "%Y/%m/%d %H:%M:%S":
                candidate = text[:19]
            else:
                candidate = text[:26]
            return datetime.strptime(candidate, fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        payload = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return _normalize_loaded_state(payload) if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _pid_alive(pid: Any) -> bool:
    try:
        pid_int = int(pid)
    except Exception:
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
        return True
    except Exception:
        return False


def _normalize_loaded_state(payload: dict[str, Any]) -> dict[str, Any]:
    """把历史遗留的假 running 状态修正掉。"""
    if not isinstance(payload, dict):
        return {}
    state = dict(payload)
    if state.get("mode") == "watch" and state.get("status") == "running" and not _pid_alive(state.get("pid")):
        state["status"] = "stale"
        state["pid"] = None
        state["stale_at"] = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
        try:
            _save_state(state)
        except Exception:
            pass
    return state


def _save_state(payload: dict[str, Any]) -> None:
    _ensure_dirs()
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def get_watch_job_interval_seconds(job_name: str, attempt: int = 0) -> int:
    profile = WATCH_JOB_PROFILES.get(job_name, {})
    base_seconds = int(profile.get("base_seconds", WATCH_INTERVAL_SECONDS))
    backoff = float(profile.get("backoff", 1.0))
    cap_seconds = int(profile.get("cap_seconds", WATCH_INTERVAL_SECONDS))
    attempt = max(0, int(attempt or 0))
    sleep_seconds = int(round(base_seconds * (backoff**attempt)))
    return max(WATCH_MIN_INTERVAL_SECONDS, min(sleep_seconds, cap_seconds))


def get_watch_interval_seconds(job_names: list[str], attempts: Optional[dict[str, int]] = None) -> int:
    attempts = attempts or {}
    intervals = [
        get_watch_job_interval_seconds(job_name, attempts.get(job_name, 0))
        for job_name in job_names
        if job_name in WATCH_JOB_PROFILES
    ]
    if not intervals:
        return WATCH_INTERVAL_SECONDS
    return max(WATCH_MIN_INTERVAL_SECONDS, min(intervals))


def _run_result_text(run_result: dict[str, Any]) -> str:
    stdout = str(run_result.get("stdout") or "")
    stderr = str(run_result.get("stderr") or "")
    return "\n".join(part for part in (stdout, stderr) if part)


def get_next_retry_at(
    job_name: str,
    now: datetime,
    attempt: int = 0,
    run_results: Optional[list[dict[str, Any]]] = None,
) -> datetime:
    run_results = run_results or []
    base_wait = timedelta(seconds=get_watch_job_interval_seconds(job_name, attempt))
    next_due = now + base_wait

    combined_text = "\n".join(_run_result_text(result) for result in run_results).strip()
    lowered = combined_text.lower()

    if job_name == "hk_refresh" and combined_text:
        if "频率超限" in combined_text or "10次/天" in combined_text or "rate limit" in lowered:
            next_reset = (now + timedelta(days=1)).replace(hour=0, minute=15, second=0, microsecond=0)
            if next_reset <= now:
                next_reset += timedelta(days=1)
            return next_reset

        if "No data returned from Tushare" in combined_text or "No HK data fetched" in combined_text:
            return max(next_due, now + timedelta(hours=3))

        if re.search(r"(Union[429, too]many Union[requests, 频次超限])", combined_text, re.IGNORECASE):
            next_reset = (now + timedelta(days=1)).replace(hour=0, minute=15, second=0, microsecond=0)
            if next_reset <= now:
                next_reset += timedelta(days=1)
            return next_reset

    if job_name == "margin_refresh" and combined_text:
        if "No data returned from Tushare" in combined_text or "margin_detail 无数据" in combined_text:
            return max(next_due, now + timedelta(hours=2))

    if job_name == "north_money_refresh" and combined_text:
        if "No data returned from Tushare" in combined_text or "moneyflow_hsgt 无数据" in combined_text:
            return max(next_due, now + timedelta(minutes=45))

    return next_due


def _latest_trade_date(sql: str) -> Optional[str]:
    try:
        rows = execute_query(sql)
    except Exception:
        return None
    if not rows:
        return None
    row = rows[0]
    return _normalize_date(row.get("latest"))


def _table_snapshots() -> dict[str, Optional[str]]:
    snapshots: dict[str, Optional[str]] = {}
    for table, sql in {
        **CORE_TABLES,
        **NORTH_MONEY_TABLES,
        **MARGIN_TABLES,
        **HK_TABLES,
        **YOUZI_TABLES,
    }.items():
        snapshots[table] = _latest_trade_date(sql)
    return snapshots


def _needs_refresh(latest: Optional[str], requested_date: str) -> bool:
    latest_dt = _parse_date(latest)
    request_dt = _parse_date(requested_date)
    if latest_dt is None or request_dt is None:
        return latest_dt is None
    return latest_dt < request_dt


def build_auto_fill_plan(review_date: str) -> dict[str, Any]:
    snapshots = _table_snapshots()
    jobs: list[dict[str, Any]] = []

    for job_name, spec in JOB_DEFINITIONS.items():
        tables = spec.get("tables", {})
        if any(_needs_refresh(snapshots.get(table), review_date) for table in tables):
            jobs.append(
                {
                    "job": job_name,
                    "reason": spec.get("reason"),
                    "watch_interval_seconds": get_watch_job_interval_seconds(job_name),
                    "watch_profile": WATCH_JOB_PROFILES.get(job_name, {}),
                    "tables": list(tables.keys()),
                }
            )

    watch_interval_seconds = get_watch_interval_seconds([job.get("job") for job in jobs if job.get("job") in WATCH_JOB_PROFILES])

    cooldown_minutes = 30
    state = _load_state()
    last_date = state.get("review_date")
    last_launched_at = _parse_date(state.get("launched_at"))
    now = datetime.now()
    cooldown_active = (
        last_date == review_date
        and last_launched_at is not None
        and now - last_launched_at < timedelta(minutes=cooldown_minutes)
    )

    return {
        "review_date": review_date,
        "jobs": jobs,
        "snapshots": snapshots,
        "cooldown": cooldown_active,
        "cooldown_minutes": cooldown_minutes,
        "watch_interval_seconds": watch_interval_seconds,
        "state": state,
    }


def request_auto_fill(review_date: str) -> dict[str, Any]:
    plan = build_auto_fill_plan(review_date)
    jobs = plan.get("jobs", [])
    job_names = [job.get("job") for job in jobs if job.get("job") in WATCH_JOB_PROFILES]
    watch_interval_seconds = get_watch_interval_seconds(job_names)
    state = _load_state()
    watch_disabled = os.environ.get("HERMES_DISABLE_AUTO_FILL_WATCH", "").strip().lower() in {"1", "true", "yes"}
    same_date_active = (
        state.get("review_date") == review_date
        and state.get("mode") == "watch"
        and _pid_alive(state.get("pid"))
    )

    if not jobs:
        return {
            "requested": False,
            "launched": False,
            "review_date": review_date,
            "jobs": [],
            "reason": "already_fresh",
            "snapshots": plan.get("snapshots", {}),
            "watching": same_date_active,
            "interval_seconds": None,
        }

    if same_date_active:
        return {
            "requested": True,
            "launched": False,
            "review_date": review_date,
            "jobs": jobs,
            "reason": "watcher_active",
            "snapshots": plan.get("snapshots", {}),
            "watching": True,
            "pid": state.get("pid"),
            "launched_at": state.get("launched_at"),
            "interval_seconds": state.get("interval_seconds") or watch_interval_seconds,
        }

    if watch_disabled:
        return {
            "requested": True,
            "launched": False,
            "review_date": review_date,
            "jobs": jobs,
            "reason": "watch_disabled",
            "snapshots": plan.get("snapshots", {}),
            "watching": False,
            "interval_seconds": watch_interval_seconds,
        }

    _ensure_dirs()
    cmd = [
        sys.executable,
        str(SCRIPT_PATH),
        "--watch",
        "--interval",
        str(watch_interval_seconds),
        "--date",
        review_date,
    ]

    launched_at = datetime.now().strftime("%Y/%m/%d %H:%M:%S")
    _save_state(
        {
            "review_date": review_date,
            "launched_at": launched_at,
            "jobs": jobs,
            "job_names": job_names,
            "cmd": cmd,
            "mode": "watch",
            "interval_seconds": watch_interval_seconds,
            "watch_profile": {
                job_name: get_watch_job_interval_seconds(job_name)
                for job_name in job_names
            },
        }
    )

    log_path = REPORT_DIR / f"auto_fill_{review_date.replace('-', '')}.log"
    log_file = log_path.open("a", encoding="utf-8")
    proc = None
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=str(BACKEND_ROOT),
            stdout=log_file,
            stderr=subprocess.STDOUT,
            env={**os.environ, "PYTHONUTF8": "1"},
            start_new_session=True,
        )
    finally:
        log_file.close()

    if proc is not None:
        state_payload = _load_state()
        state_payload.update(
            {
                "pid": proc.pid,
                "mode": "watch",
                "status": "running",
                "launched_at": launched_at,
                "review_date": review_date,
                "interval_seconds": watch_interval_seconds,
            }
        )
        _save_state(state_payload)

    return {
        "requested": True,
        "launched": True,
        "review_date": review_date,
        "jobs": jobs,
        "reason": "background_auto_fill_watch_started",
        "snapshots": plan.get("snapshots", {}),
        "watching": True,
        "launched_at": launched_at,
        "interval_seconds": watch_interval_seconds,
        "pid": proc.pid if proc else None,
        "log_path": str(log_path),
        "cmd": cmd,
    }
