from __future__ import annotations

import json
import threading
import time as time_module
from datetime import datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Optional, Union

from ._utils import safe_dict, safe_list
from .main_central_hub import MainCentralHub

PayloadProvider = Callable[[], Optional[Mapping[str, Any]]]


def _now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value in (None, "", []):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ").replace("Z", "")
    if not text:
        return None
    for fmt in ("%Y/%m/%d %H:%M:%S.%f", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d"):
        try:
            if fmt == "%Y-%m-%d":
                return datetime.strptime(text[:10], fmt)
            if fmt == "%Y/%m/%d %H:%M:%S":
                return datetime.strptime(text[:19], fmt)
            return datetime.strptime(text[:26], fmt)
        except Exception:
            continue
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


class HermesCronScheduler:
    """
    Hermes 盘中高频流控总线。

    说明：
    - 不在 import 时自动启动。
    - 通过 payload_provider 注入 Robot-1 的真实抓取结果。
    - 每次触发后调用 MainCentralHub.receive_and_transit 完成写缓存和落盘。
    """

    def __init__(
        self,
        hub_instance: MainCentralHub,
        payload_provider: Optional[PayloadProvider] = None,
        *,
        api_config: Optional[Mapping[str, Any]] = None,
        interval_seconds: int = 600,
        poll_seconds: int = 30,
        state_path: Union[Path, Optional[str]]= None,
    ) -> None:
        self.hub = hub_instance
        self.payload_provider = payload_provider
        self.api_config = safe_dict(api_config)
        self.interval_seconds = max(60, int(interval_seconds or 600))
        self.poll_seconds = max(5, int(poll_seconds or 30))
        self.retry_interval_seconds = max(60, self.interval_seconds // 3)
        self.report_dir = Path(state_path).parent if state_path else Path(__file__).resolve().parents[1] / "reports"
        self.report_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = Path(state_path) if state_path else self.report_dir / "cron_scheduler_state.json"

        self.is_running = False
        self.thread: threading.Optional[Thread] = None
        self._state = self._load_state()
        self.last_success_at = _parse_datetime(self._state.get("last_success_at"))
        self.last_run_at = self.last_success_at
        self.last_result: Optional[dict[str, Any]] = None
        self.auto_run_start = dt_time(16, 0)
        self.auto_run_end = dt_time(18, 0)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {}
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _save_state(self, extra: Optional[Mapping[str, Any]] = None) -> None:
        payload = {
            "updated_at": _now_str(),
            "is_running": self.is_running,
            "last_run_at": self.last_run_at.strftime("%Y/%m/%d %H:%M:%S") if self.last_run_at else None,
            "last_success_at": self.last_success_at.strftime("%Y/%m/%d %H:%M:%S") if self.last_success_at else None,
            "last_status": self._state.get("last_status"),
            "last_error": self._state.get("last_error"),
            "run_count": int(self._state.get("run_count", 0) or 0),
            "skip_count": int(self._state.get("skip_count", 0) or 0),
        }
        if extra:
            payload.update(dict(extra))
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        self._state = payload

    def _is_trading_day(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        return now.weekday() <= 4

    def _is_trading_time(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        if not self._is_trading_day(now):
            return False

        clock = now.time()
        morning_start = dt_time(9, 30)
        morning_end = dt_time(11, 30)
        afternoon_start = dt_time(13, 0)
        afternoon_end = dt_time(15, 0)
        post_close_start = self.auto_run_start
        post_close_end = self.auto_run_end
        return (
            (morning_start <= clock <= morning_end)
            or (afternoon_start <= clock <= afternoon_end)
            or (post_close_start <= clock <= post_close_end)
        )

    def _is_auto_run_time(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        if not self._is_trading_day(now):
            return False
        return self.auto_run_start <= now.time() <= self.auto_run_end

    def _due_to_run(self, now: Optional[datetime] = None) -> bool:
        now = now or datetime.now()
        if not self._is_auto_run_time(now):
            return False
        if self.last_success_at and self.last_success_at.date() == now.date():
            return False
        if self.last_run_at is None:
            return True
        last_status = str(self._state.get("last_status") or "")
        if last_status in {"ERROR", "NO_PAYLOAD"}:
            if self.last_run_at.date() < now.date():
                return True
            return (now - self.last_run_at).total_seconds() >= self.retry_interval_seconds
        if self.last_run_at.date() < now.date():
            return True
        return False

    def _extract_payload(self, payload: Optional[Mapping[str, Any]]) -> dict[str, Any]:
        payload = safe_dict(payload)
        if not payload:
            return {}

        if any(key in payload for key in ("today_sectors", "history_map", "market_metrics", "upstream_context")):
            return {
                "today_sectors": payload.get("today_sectors"),
                "history_map": payload.get("history_map"),
                "market_metrics": payload.get("market_metrics"),
                "api_config": payload.get("api_config") or self.api_config,
                "upstream_context": payload.get("upstream_context"),
            }

        if "payload" in payload and isinstance(payload.get("payload"), dict):
            nested = safe_dict(payload.get("payload"))
            return self._extract_payload(nested)

        return {}

    def run_once(
        self,
        *,
        now: Optional[datetime] = None,
        payload: Optional[Mapping[str, Any]] = None,
        enforce_time_window: bool = False,
    ) -> dict[str, Any]:
        now = now or datetime.now()
        state_updates: dict[str, Any] = {"last_attempt_at": now.strftime("%Y/%m/%d %H:%M:%S")}

        if enforce_time_window and not self._is_auto_run_time(now):
            skip_count = int(self._state.get("skip_count", 0) or 0) + 1
            state_updates.update(
                {
                    "last_status": "SKIPPED",
                    "last_error": "outside_trading_session",
                    "skip_count": skip_count,
                }
            )
            self._save_state(state_updates)
            return {
                "status": "SKIPPED",
                "reason": "outside_trading_session",
                "message": "当前不在 A 股交易时段，跳过本轮调度。",
                "now": now.strftime("%Y/%m/%d %H:%M:%S"),
            }

        if payload is None and self.payload_provider is not None:
            try:
                payload = self.payload_provider()
            except Exception as exc:
                self.last_run_at = now
                state_updates.update(
                    {
                        "last_run_at": now.strftime("%Y/%m/%d %H:%M:%S"),
                        "last_status": "ERROR",
                        "last_error": str(exc),
                    }
                )
                self._save_state(state_updates)
                return {
                    "status": "ERROR",
                    "reason": "payload_provider_failed",
                    "error": str(exc),
                    "now": now.strftime("%Y/%m/%d %H:%M:%S"),
                }

        normalized = self._extract_payload(payload)
        if not normalized:
            state_updates.update(
                {
                    "last_status": "NO_PAYLOAD",
                    "last_error": "payload_missing",
                }
            )
            self._save_state(state_updates)
            return {
                "status": "NO_PAYLOAD",
                "reason": "payload_missing",
                "message": "未获得 Robot-1 传入数据，本轮不写入中转站。",
                "now": now.strftime("%Y/%m/%d %H:%M:%S"),
            }

        try:
            package = self.hub.receive_and_transit(
                today_sectors=normalized.get("today_sectors"),
                history_map=normalized.get("history_map"),
                market_metrics=normalized.get("market_metrics"),
                api_config=normalized.get("api_config") or self.api_config,
                upstream_context=normalized.get("upstream_context"),
            )
        except Exception as exc:
            self.last_run_at = now
            state_updates.update(
                {
                    "last_run_at": now.strftime("%Y/%m/%d %H:%M:%S"),
                    "last_status": "ERROR",
                    "last_error": str(exc),
                }
            )
            self._save_state(state_updates)
            return {
                "status": "ERROR",
                "reason": "hub_receive_failed",
                "error": str(exc),
                "now": now.strftime("%Y/%m/%d %H:%M:%S"),
            }

        self.last_run_at = now
        self.last_success_at = now
        self.last_result = package
        run_count = int(self._state.get("run_count", 0) or 0) + 1
        state_updates.update(
            {
                "last_run_at": now.strftime("%Y/%m/%d %H:%M:%S"),
                "last_success_at": now.strftime("%Y/%m/%d %H:%M:%S"),
                "last_status": "OK",
                "last_error": None,
                "run_count": run_count,
                "last_package_date": package.get("date"),
            }
        )
        self._save_state(state_updates)
        return {
            "status": "OK",
            "now": now.strftime("%Y/%m/%d %H:%M:%S"),
            "package": package,
        }

    def run_forever(self) -> None:
        self.is_running = True
        self._save_state({"is_running": True})
        while self.is_running:
            now = datetime.now()
            try:
                if self._due_to_run(now):
                    self.run_once(now=now, enforce_time_window=True)
            except Exception as exc:
                self._state["last_status"] = "ERROR"
                self._state["last_error"] = str(exc)
                self._save_state()
            time_module.sleep(self.poll_seconds)

    def start(self) -> None:
        if self.is_running:
            return
        self.is_running = True
        self.thread = threading.Thread(target=self.run_forever, name="hermes-cron-scheduler", daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self.is_running = False
        self._save_state({"is_running": False})
        thread = self.thread
        if thread and thread.is_alive():
            thread.join(timeout=5)

    def status(self) -> dict[str, Any]:
        snapshot = self._load_state()
        snapshot.update(
            {
                "is_running": self.is_running,
                "last_run_at": self.last_run_at.strftime("%Y/%m/%d %H:%M:%S") if self.last_run_at else None,
                "last_success_at": self.last_success_at.strftime("%Y/%m/%d %H:%M:%S") if self.last_success_at else None,
                "last_result_status": self.last_result.get("status") if self.last_result else None,
            }
        )
        return snapshot


__all__ = ["HermesCronScheduler"]
