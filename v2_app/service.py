from __future__ import annotations

import threading
import time
from datetime import date

from .data import MarketData
from .engine import V2Engine, serialize_market, serialize_signal
from .repository import active_factor_names, get_config, load_signal_snapshot, save_run, sync_factor_reviews
from .validation import persist_validation, run_validation


class V2Service:
    def __init__(self):
        self.data = MarketData()
        self.engine = V2Engine()
        self._lock = threading.RLock()
        self._snapshot_cache: dict[date, tuple[float, dict]] = {}
        self._persisted_snapshot_cache: dict[date, tuple[float, list[dict]]] = {}
        self._validation_cache: tuple[float, dict] | None = None

    def snapshot(self, requested_date: date | None = None, persist: bool = False) -> dict:
        target = self.data.resolve_date(requested_date)
        if not target:
            return {"trade_date": None, "universe_count": 0, "market": None, "signals": [], "all_signals": []}
        with self._lock:
            cached = self._snapshot_cache.get(target)
            if cached and time.time() - cached[0] < 180:
                result = cached[1]
            else:
                universe = self.data.load_universe(target)
                history = self.data.load_history([item["ts_code"] for item in universe], target)
                universe = [item for item in universe if item["ts_code"] in history]
                market = self.data.market_context(target, universe, history)
                active_names, score_mode, status_summary = active_factor_names()
                result = self.engine.run(
                    history,
                    market,
                    self.data.load_sector_flow(target),
                    display_limit=None,
                    active_factor_names=active_names or None,
                    score_mode=score_mode,
                )
                # History is intentionally not retained in the web cache; it
                # is only needed during the calculation and validation loads
                # it independently.  This keeps the new service memory-safe
                # with a 5,000+ stock universe.
                result["universe"] = universe
                result["filtered_st_count"] = getattr(self.data, "last_filtered_st_count", 0)
                result["factor_status_summary"] = status_summary
                result["factor_catalog_count"] = sum(status_summary.values())
                result["production_factor_count"] = status_summary.get("production", 0)
                self._snapshot_cache[target] = (time.time(), result)
            if persist:
                save_run(result)
            return result

    def dashboard(self) -> dict:
        target = self.data.resolve_date()
        signals = self._persisted_signals(target) if target else []
        if signals:
            return self._dashboard_from_signals(target, signals, persisted=True)
        return {
            "trade_date": target, "universe_count": 0, "market": None,
            "state_counts": {}, "lifecycle_counts": {}, "triggered": 0,
            "resonance_eligible": 0, "st_filtered_count": 0,
            "score_mode": "NOT_COMPUTED", "production_ready": False,
            "factor_status_summary": {}, "snapshot_mode": "not_computed",
            "data_sources": {"daily_bars": "stock_daily_kline（未计算快照）"},
            "message": "当前没有已保存的 V2 快照；请执行明确的刷新计算动作。",
        }
        result = self.snapshot()
        signals = result.get("all_signals", [])
        state_counts = {}
        lifecycle_counts = {}
        for item in signals:
            state_counts[item.trading_state] = state_counts.get(item.trading_state, 0) + 1
            lifecycle_counts[item.lifecycle] = lifecycle_counts.get(item.lifecycle, 0) + 1
        return {
            "trade_date": result.get("trade_date"),
            "universe_count": result.get("universe_count", 0),
            "market": serialize_market(result.get("market")),
            "state_counts": state_counts,
            "lifecycle_counts": lifecycle_counts,
            "triggered": sum(1 for item in signals if item.trading_state == "TRIGGERED"),
            "resonance_eligible": sum(1 for item in signals if item.resonance_eligible),
            "st_filtered_count": result.get("filtered_st_count", 0),
            "score_mode": result.get("score_mode", "RESEARCH"),
            "production_ready": result.get("production_ready", False),
            "factor_status_summary": result.get("factor_status_summary", {}),
            "data_sources": {
                "daily_bars": "stock_daily_kline",
                "stock_metadata": "stock_flow",
                "sector_flow": "sector_flow（如有同日数据）",
                "market_proxy": result.get("market").source if result.get("market") else None,
            },
        }

    def _persisted_signals(self, target: date | None) -> list[dict]:
        if not target:
            return []
        cached = self._persisted_snapshot_cache.get(target)
        if cached and time.time() - cached[0] < 300:
            return cached[1]
        signals = load_signal_snapshot(target)
        # A partial historical write must never masquerade as today's full market scan.
        if len(signals) < 1000:
            return []
        self._persisted_snapshot_cache[target] = (time.time(), signals)
        return signals

    def _dashboard_from_signals(self, target: date, signals: list[dict], persisted: bool = False) -> dict:
        state_counts, lifecycle_counts = {}, {}
        for item in signals:
            state = item.get("trading_state", "WATCH") if isinstance(item, dict) else item.trading_state
            lifecycle = item.get("lifecycle", "关注") if isinstance(item, dict) else item.lifecycle
            eligible = item.get("resonance_eligible", False) if isinstance(item, dict) else item.resonance_eligible
            state_counts[state] = state_counts.get(state, 0) + 1
            lifecycle_counts[lifecycle] = lifecycle_counts.get(lifecycle, 0) + 1
        market_state = next((item.get("market_state") for item in signals if item.get("market_state")), "RANGE")
        return {
            "trade_date": target, "universe_count": len(signals),
            "market": {"trade_date": target.isoformat(), "breadth": None, "limit_up": "—", "limit_down": "—", "market_return_20d": None, "sentiment": "已保存快照", "state": market_state, "source": "v2_signal_snapshots"},
            "state_counts": state_counts, "lifecycle_counts": lifecycle_counts,
            "triggered": state_counts.get("TRIGGERED", 0),
            "resonance_eligible": sum(1 for item in signals if item.get("resonance_eligible")),
            "st_filtered_count": 0, "score_mode": signals[0].get("score_mode", "RESEARCH"),
            "production_ready": signals[0].get("production_ready", False),
            "factor_status_summary": {}, "data_sources": {"daily_bars": "v2_signal_snapshots（已保存快照）"},
            "snapshot_mode": "persisted" if persisted else "live",
        }

    def persist_research_snapshot(self, requested_date: date | None = None) -> dict:
        """Persist all catalog factor values without adding candidates to score.

        The normal daily snapshot only stores factors currently enabled in
        the research score.  This explicit research action evaluates the
        full catalog (including candidate Alpha158 formulas), keeps scoring
        on the active lifecycle set, and stores the raw candidate values for
        audit/research in ``v2_factor_values``.
        """
        target = self.data.resolve_date(requested_date)
        if not target:
            return {"trade_date": None, "universe_count": 0, "factor_values": 0, "snapshots": 0}
        with self._lock:
            universe = self.data.load_universe(target)
            history = self.data.load_history([item["ts_code"] for item in universe], target)
            universe = [item for item in universe if item["ts_code"] in history]
            market = self.data.market_context(target, universe, history)
            active_names, score_mode, status_summary = active_factor_names()
            result = self.engine.run(
                history,
                market,
                self.data.load_sector_flow(target),
                display_limit=None,
                active_factor_names=active_names or None,
                score_mode=score_mode,
                include_candidate_factors=True,
            )
            result["universe"] = universe
            result["filtered_st_count"] = getattr(self.data, "last_filtered_st_count", 0)
            result["factor_status_summary"] = status_summary
            result["factor_catalog_count"] = sum(status_summary.values())
            result["production_factor_count"] = status_summary.get("production", 0)
            saved = save_run(result)
            return {
                "trade_date": target,
                "universe_count": len(universe),
                "factor_catalog_count": result["factor_catalog_count"],
                "score_mode": score_mode,
                "production_ready": score_mode == "PRODUCTION",
                "factor_values": saved["factors"],
                "snapshots": saved["snapshots"],
                "message": "全因子研究值已写入 v2_factor_values；候选因子仍不参与评分",
            }

    def candidates(self, requested_date: date | None = None, limit: int = 50, state: str | None = None) -> dict:
        target = self.data.resolve_date(requested_date)
        persisted = self._persisted_signals(target)
        if persisted:
            signals = [item for item in persisted if not state or item.get("trading_state") == state]
            dashboard = self._dashboard_from_signals(target, persisted, persisted=True)
            return {"trade_date": target, "universe_count": len(persisted), "market": dashboard["market"], "score_mode": dashboard["score_mode"], "production_ready": dashboard["production_ready"], "factor_status_summary": {}, "signals": signals[:max(1, min(limit, 500))]}
        return {
            "trade_date": target, "universe_count": 0, "market": None,
            "score_mode": "NOT_COMPUTED", "production_ready": False,
            "factor_status_summary": {}, "signals": [],
            "message": "当前没有已保存的 V2 快照；请执行明确的刷新计算动作。",
        }
        result = self.snapshot(requested_date)
        signals = result.get("all_signals", [])
        if state:
            signals = [item for item in signals if item.trading_state == state]
        return {
            "trade_date": result.get("trade_date"),
            "universe_count": result.get("universe_count", 0),
            "market": serialize_market(result.get("market")),
            "score_mode": result.get("score_mode", "RESEARCH"),
            "production_ready": result.get("production_ready", False),
            "factor_status_summary": result.get("factor_status_summary", {}),
            "signals": [serialize_signal(item) for item in signals[:max(1, min(limit, 500))]],
        }

    def enrich_account(self, account: dict) -> dict:
        """Attach V2 hold/exit review to an account without placing orders.

        A weak market or ``NO_CHASE`` signal is not treated as a sell signal
        for an existing position.  Only an invalid/退潮 signal or explicit
        stop-loss/take-profit threshold produces ``SELL_REVIEW``.
        """
        result = dict(account or {})
        positions = [dict(item) for item in result.get("positions", [])]
        try:
            snapshot = self.snapshot()
            signals = {item.code.split(".")[0]: item for item in snapshot.get("all_signals", [])}
            cfg = get_config()
        except Exception as exc:
            result["positions"] = positions
            result["v2_signal_status"] = "unavailable"
            result["v2_signal_error"] = str(exc)
            result["v2_summary"] = "V2 信号暂时不可用，当前只显示账户数据"
            return result

        stop_loss = float(cfg.get("stop_loss_pct", -6) or -6)
        take_profit = float(cfg.get("take_profit_pct", 15) or 15)
        summary = {"HOLD": 0, "SELL_REVIEW": 0, "NO_SIGNAL": 0}
        for position in positions:
            plain_code = str(position.get("code") or "").upper().split(".")[0]
            signal = signals.get(plain_code)
            review = {
                "decision": "NO_SIGNAL",
                "decision_label": "暂无V2信号",
                "source_state": None,
                "factor_score": None,
                "resonance_count": None,
                "lifecycle": None,
                "risk_score": None,
                "signal_date": None,
                "reason": "未进入 V2 生产股票池，不能用旧策略结果替代；先保留人工复核。",
            }
            if signal is not None:
                risk = signal.dimensions.get("risk")
                risk_score = risk.score if risk and risk.valid else None
                last_price = float(position.get("last_price") or 0)
                avg_cost = float(position.get("avg_cost") or 0)
                profit_pct = ((last_price / avg_cost) - 1) * 100 if avg_cost > 0 and last_price > 0 else None
                sell_reasons = []
                if signal.lifecycle == "退潮":
                    sell_reasons.append("生命周期进入退潮")
                if signal.trading_state == "INVALID" or risk_score is not None and risk_score < 40:
                    sell_reasons.append("风险闸门失效")
                if profit_pct is not None and profit_pct <= stop_loss:
                    sell_reasons.append(f"浮亏{profit_pct:.1f}%达到止损线{stop_loss:.1f}%")
                if profit_pct is not None and profit_pct >= take_profit:
                    sell_reasons.append(f"浮盈{profit_pct:.1f}%达到止盈线{take_profit:.1f}%")
                decision = "SELL_REVIEW" if sell_reasons else "HOLD"
                review = {
                    "decision": decision,
                    "decision_label": "卖出复核" if decision == "SELL_REVIEW" else "继续持有",
                    "source_state": signal.trading_state,
                    "factor_score": signal.factor_score,
                    "resonance_count": signal.resonance_count,
                    "lifecycle": signal.lifecycle,
                    "risk_score": risk_score,
                    "signal_date": signal.trade_date.isoformat(),
                    "reason": "；".join(sell_reasons) if sell_reasons else f"V2状态为{signal.trading_state}，弱市禁止追买不等于卖出；继续观察止损/退潮条件。",
                }
            position["v2"] = review
            summary[review["decision"]] = summary.get(review["decision"], 0) + 1

        result["positions"] = positions
        result["v2_signal_status"] = "ok"
        result["v2_signal_date"] = snapshot.get("trade_date")
        result["v2_summary"] = f"继续持有 {summary['HOLD']} 只，卖出复核 {summary['SELL_REVIEW']} 只，暂无V2信号 {summary['NO_SIGNAL']} 只"
        result["v2_thresholds"] = {"stop_loss_pct": stop_loss, "take_profit_pct": take_profit}
        return result

    def stock(self, code: str, requested_date: date | None = None) -> dict | None:
        target = self.data.resolve_date(requested_date)
        persisted = self._persisted_signals(target)
        if persisted:
            plain = code.strip().upper().split(".", 1)[0]
            return next((item for item in persisted if item["code"] == code or item["code"].split(".")[0] == plain), None)
        result = self.snapshot(requested_date)
        item = next((signal for signal in result.get("all_signals", []) if signal.code == code or signal.code.split(".")[0] == code), None)
        return serialize_signal(item) if item else None

    def validation(self, days: int = 20, limit: int = 300, persist: bool = False) -> dict:
        with self._lock:
            if self._validation_cache and time.time() - self._validation_cache[0] < 900 and not persist:
                return self._validation_cache[1]
            result = run_validation(self.data, self.engine, days=days, limit=limit)
            self._validation_cache = (time.time(), result)
            if persist:
                result["saved_rows"] = persist_validation(result)
                result["lifecycle_updated"] = sync_factor_reviews(result)
                self._snapshot_cache.clear()
            return result
