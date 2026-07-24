from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Optional, Optional, Union

from ._utils import as_text, clamp, safe_dict, safe_list, to_float, to_int, unique_by_name

SnapshotResolver = Callable[[str, Mapping[str, Any], Mapping[str, Any]], Optional[list[Any]]]


def _now_str() -> str:
    return datetime.now().strftime("%Y/%m/%d %H:%M:%S")


def _normalize_date_like(value: Any) -> Optional[str]:
    if value in (None, "", []):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    text = str(value).strip().replace("T", " ").replace("Z", "")
    if not text:
        return None
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    if len(text) == 8 and text.isdigit():
        return f"{text[:4]}-{text[4:6]}-{text[6:8]}"
    match = re.search(r"(\d{4})[-/]?(\d{2})[-/]?(\d{2})", text)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return None


def _parse_datetime(value: Any, fallback: Optional[Path] = None) -> datetime:
    if isinstance(value, datetime):
        return value
    if value not in (None, "", []):
        text = str(value).strip().replace("T", " ").replace("Z", "")
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
            pass
    if fallback and fallback.exists():
        try:
            return datetime.fromtimestamp(fallback.stat().st_mtime)
        except Exception:
            pass
    return datetime.min


def _clean_pool(values: Any) -> list[str]:
    if values in (None, "", []):
        return []
    result: list[str] = []
    if isinstance(values, str):
        candidate = values.strip()
        return [candidate] if candidate else []
    if isinstance(values, dict):
        name = as_text(values.get("name") or values.get("stock_name") or values.get("symbol") or values.get("code"), default="")
        code = as_text(values.get("code") or values.get("ts_code") or values.get("ticker"), default="")
        if name and code and code not in name:
            return [f"{name}({code})"]
        if name:
            return [name]
        if code:
            return [code]
        return []
    if isinstance(values, Iterable):
        for item in values:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    result.append(text)
            elif isinstance(item, Mapping):
                name = as_text(item.get("name") or item.get("stock_name") or item.get("symbol") or item.get("code"), default="")
                code = as_text(item.get("code") or item.get("ts_code") or item.get("ticker"), default="")
                if name and code and code not in name:
                    result.append(f"{name}({code})")
                elif name:
                    result.append(name)
                elif code:
                    result.append(code)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in result:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


class Robot3SniperStrategy:
    """
    Hermes 题材狙击策略引擎。

    目标：
    - 扫描历史落盘快照
    - 找出连续 3 天热度 >= 70 且排名持续改善的概念 / 行业
    - 输出次日开仓候选池
    """

    def __init__(
        self,
        report_dir: Union[Path, Optional[str]]= None,
        history_dirs: Optional[Iterable[Union[Path, str]]] = None,
        minimum_persistence_days: int = 3,
        component_resolver: Optional[SnapshotResolver] = None,
    ) -> None:
        self.report_dir = Path(report_dir or Path(__file__).resolve().parents[1] / "reports")
        self.report_dir.mkdir(parents=True, exist_ok=True)
        default_history_dirs = [
            self.report_dir,
            Path.cwd() / "storage" / "market_context",
            Path(__file__).resolve().parents[1] / "reports",
        ]
        selected_dirs = list(history_dirs or default_history_dirs)
        self.history_dirs = []
        for directory in selected_dirs:
            directory = Path(directory)
            if directory not in self.history_dirs:
                self.history_dirs.append(directory)
        self.minimum_persistence_days = max(3, int(minimum_persistence_days or 3))
        self.component_resolver = component_resolver
        self.latest_report_path = self.report_dir / "robot3_sniper_latest.json"

    def _load_json(self, path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def _extract_context(self, snapshot: Mapping[str, Any]) -> dict[str, Any]:
        snapshot = safe_dict(snapshot)
        if "market_context" in snapshot and isinstance(snapshot.get("market_context"), dict):
            return safe_dict(snapshot.get("market_context"))
        return snapshot

    def _extract_snapshot_date(self, snapshot: Mapping[str, Any], path: Path) -> str:
        snapshot = safe_dict(snapshot)
        market_context = safe_dict(snapshot.get("market_context"))
        meta = safe_dict(snapshot.get("meta"))
        candidates = [
            snapshot.get("date"),
            snapshot.get("resolved_date"),
            meta.get("resolved_date"),
            meta.get("created_at"),
            market_context.get("date"),
            market_context.get("updated_at"),
        ]
        for candidate in candidates:
            normalized = _normalize_date_like(candidate)
            if normalized:
                return normalized
        stem = path.stem
        match = re.search(r"(\d{4})(\d{2})(\d{2})", stem)
        if match:
            return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
        return ""

    def _extract_snapshot_created_at(self, snapshot: Mapping[str, Any], path: Path) -> datetime:
        snapshot = safe_dict(snapshot)
        market_context = safe_dict(snapshot.get("market_context"))
        meta = safe_dict(snapshot.get("meta"))
        for candidate in (
            meta.get("created_at"),
            snapshot.get("updated_at"),
            market_context.get("updated_at"),
            snapshot.get("created_at"),
        ):
            parsed = _parse_datetime(candidate)
            if parsed != datetime.min:
                return parsed
        return _parse_datetime(None, fallback=path)

    def _discover_snapshot_files(self) -> list[dict[str, Any]]:
        latest_by_date: dict[str, dict[str, Any]] = {}
        for directory in self.history_dirs:
            if not directory.exists():
                continue
            if directory.resolve() == self.report_dir.resolve():
                patterns = ("main_central_hub_*.json", "main_central_hub_latest.json")
            else:
                patterns = ("*.json",)
            for pattern in patterns:
                for path in directory.glob(pattern):
                    if path.is_dir():
                        continue
                    if path.name.startswith(("robot3_sniper_", "cron_scheduler_", "auto_fill_")):
                        continue
                    payload = self._load_json(path)
                    if not payload:
                        continue
                    snapshot_date = self._extract_snapshot_date(payload, path)
                    if not snapshot_date:
                        continue
                    created_at = self._extract_snapshot_created_at(payload, path)
                    current = latest_by_date.get(snapshot_date)
                    if current is None or created_at > current["created_at"]:
                        latest_by_date[snapshot_date] = {
                            "date": snapshot_date,
                            "created_at": created_at,
                            "path": path,
                            "payload": payload,
                        }
        return sorted(latest_by_date.values(), key=lambda item: (item["date"], item["created_at"]), reverse=True)

    def _source_priority(self, source: str) -> int:
        order = {
            "concept_dimensions": 4,
            "theme_dimensions": 3,
            "industry_dimensions": 3,
            "sector_matrix": 2,
        }
        return order.get(source, 1)

    def _score_from_dimension(self, item: Mapping[str, Any]) -> float:
        direct = to_float(item.get("score"), None)
        if direct is not None:
            return clamp(direct, 0.0, 100.0)
        direct = to_float(item.get("strength"), None)
        if direct is not None:
            return clamp(direct, 0.0, 100.0)
        direct = to_float(item.get("hot"), None)
        if direct is not None:
            return clamp(direct, 0.0, 100.0)

        score = 48.0
        latest_rank = to_int(item.get("latest_rank"), None)
        if latest_rank is not None:
            score += clamp(28.0 - latest_rank * 1.8, -18.0, 24.0)

        latest_amount = to_float(item.get("latest_amount_yi") or item.get("latest"), None)
        if latest_amount is not None and latest_amount > 0:
            score += clamp(math.log10(latest_amount + 1.0) * 4.0, 0.0, 16.0)

        delta = to_float(item.get("delta"), None)
        if delta is not None:
            score += clamp(delta / max(abs(latest_amount or delta or 1.0), 1.0) * 120.0, -10.0, 10.0)

        for window_key in ("3", "5"):
            window = safe_dict(item.get("rank_windows")).get(window_key) if isinstance(item.get("rank_windows"), dict) else None
            if isinstance(window, dict) and window.get("trend") == "up":
                score += 10.0 if window_key == "3" else 5.0
            window = safe_dict(item.get("ratio_windows")).get(window_key) if isinstance(item.get("ratio_windows"), dict) else None
            if isinstance(window, dict) and window.get("trend") == "up":
                score += 6.0 if window_key == "3" else 3.0

        state = as_text(item.get("state"), default="")
        if state in {"mainline", "main"}:
            score += 6.0
        elif state == "watch":
            score += 3.0

        if as_text(item.get("category"), default="") in {"主题", "概念"}:
            score += 2.0

        return clamp(score, 0.0, 100.0)

    def _normalize_component_pool(self, item: Mapping[str, Any], latest_context: Mapping[str, Any]) -> list[str]:
        pool_fields = ("components", "constituents", "component_stocks", "members", "stocks", "pool")
        for field in pool_fields:
            values = item.get(field)
            cleaned = _clean_pool(values)
            if cleaned:
                return cleaned[:3]

        candidate_name = as_text(item.get("name"), default="")
        leaders: list[str] = []
        for context in (latest_context,):
            sector_matrix = safe_dict(context.get("sector_matrix"))
            for group in ("mainline", "watch", "alive"):
                for row in safe_list(sector_matrix.get(group)):
                    if as_text(row.get("name"), default="") != candidate_name:
                        continue
                    leader = as_text(row.get("leader"), default="")
                    if leader and leader not in leaders:
                        leaders.append(leader)
        leader = as_text(item.get("leader"), default="")
        if leader and leader not in leaders:
            leaders.append(leader)
        return leaders[:3]

    def _extract_candidates_from_context(self, context: Mapping[str, Any]) -> list[dict[str, Any]]:
        context = safe_dict(context)
        rotation = safe_dict(context.get("rotation"))
        sector_matrix = safe_dict(context.get("sector_matrix"))
        result: dict[str, dict[str, Any]] = {}

        def add_candidate(raw: Mapping[str, Any], source: str, category: str, source_rank: Optional[int] = None) -> None:
            name = as_text(raw.get("name") or raw.get("board_name") or raw.get("sector_name"), default="")
            if not name:
                return
            candidate = {
                "name": name,
                "category": as_text(raw.get("category"), default=category),
                "source": source,
                "leader": as_text(raw.get("leader"), default="数据暂缺"),
                "state": as_text(raw.get("state"), default=category),
                "score": round(self._score_from_dimension(raw), 2),
                "rank": to_int(raw.get("latest_rank") or raw.get("rank"), source_rank),
                "latest_amount_yi": to_float(raw.get("latest_amount_yi") or raw.get("latest"), None),
                "delta": to_float(raw.get("delta"), None),
                "rank_windows": deepcopy(safe_dict(raw.get("rank_windows"))),
                "ratio_windows": deepcopy(safe_dict(raw.get("ratio_windows"))),
                "series_rank": safe_list(raw.get("series_rank")),
                "series_ratio_pct": safe_list(raw.get("series_ratio_pct")),
                "series": safe_list(raw.get("series")),
                "components": _clean_pool(raw.get("components") or raw.get("constituents") or raw.get("members") or raw.get("stocks") or raw.get("pool")),
                "source_priority": self._source_priority(source),
                "raw": deepcopy(dict(raw)),
            }
            existing = result.get(name)
            if existing is None or candidate["score"] > existing["score"] or (
                candidate["score"] == existing["score"] and candidate["source_priority"] > existing["source_priority"]
            ):
                result[name] = candidate

        for source in ("concept_dimensions", "theme_dimensions", "industry_dimensions"):
            dims = [item for item in safe_list(safe_dict(rotation.get(source)).get("dimensions")) if isinstance(item, dict)]
            for index, item in enumerate(sorted(dims, key=lambda row: self._score_from_dimension(row), reverse=True), start=1):
                add_candidate(item, source, "board", index)

        for group in ("mainline", "watch", "alive"):
            rows = [item for item in safe_list(sector_matrix.get(group)) if isinstance(item, dict)]
            for index, item in enumerate(sorted(rows, key=lambda row: to_float(row.get("score") or row.get("strength"), 0.0) or 0.0, reverse=True), start=1):
                raw = {
                    "name": item.get("name"),
                    "category": group,
                    "leader": item.get("leader"),
                    "state": item.get("state") or group,
                    "score": item.get("score") or item.get("strength"),
                    "rank": index,
                    "components": item.get("components"),
                }
                add_candidate(raw, "sector_matrix", group, index)

        ordered = sorted(result.values(), key=lambda item: (item["score"], -item["source_priority"]), reverse=True)
        for index, item in enumerate(ordered, start=1):
            if item.get("rank") in (None, 0):
                item["rank"] = index
        return ordered

    def _collect_history(self) -> list[dict[str, Any]]:
        snapshots = self._discover_snapshot_files()
        if len(snapshots) > self.minimum_persistence_days:
            snapshots = snapshots[: max(self.minimum_persistence_days, 10)]
        return snapshots

    def _persistence_candidates(self, snapshots: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(snapshots) < self.minimum_persistence_days:
            return []

        ordered = sorted(snapshots, key=lambda item: item["date"])
        history: dict[str, list[dict[str, Any]]] = defaultdict(list)
        latest_context = self._extract_context(ordered[-1]["payload"])

        for snapshot in ordered:
            context = self._extract_context(snapshot["payload"])
            candidates = self._extract_candidates_from_context(context)
            for candidate in candidates:
                history[candidate["name"]].append(
                    {
                        "date": snapshot["date"],
                        "score": candidate["score"],
                        "rank": int(candidate.get("rank") or 0),
                        "leader": candidate.get("leader"),
                        "source": candidate.get("source"),
                        "category": candidate.get("category"),
                        "components": candidate.get("components", []),
                        "context": context,
                    }
                )

        verified: list[dict[str, Any]] = []
        for name, records in history.items():
            if len(records) < self.minimum_persistence_days:
                continue
            recent = records[-self.minimum_persistence_days :]
            scores = [round(to_float(record.get("score"), 0.0) or 0.0, 2) for record in recent]
            ranks = [int(record.get("rank") or 0) for record in recent]
            if not all(score >= 70.0 for score in scores):
                continue
            if not all(ranks[index + 1] <= ranks[index] for index in range(len(ranks) - 1)):
                continue
            if ranks[-1] >= ranks[0]:
                continue
            if scores[-1] < scores[0]:
                continue

            latest_record = recent[-1]
            components = self._normalize_component_pool(
                {
                    "name": name,
                    "leader": latest_record.get("leader"),
                    "components": latest_record.get("components"),
                },
                latest_context,
            )
            verified.append(
                {
                    "concept_name": name,
                    "category": latest_record.get("category"),
                    "source": latest_record.get("source"),
                    "persistence_days": len(recent),
                    "score_trend": scores,
                    "rank_trend": ranks,
                    "rank_gain": ranks[0] - ranks[-1],
                    "score_gain": round(scores[-1] - scores[0], 2),
                    "evidence": [
                        {
                            "date": record.get("date"),
                            "score": record.get("score"),
                            "rank": record.get("rank"),
                            "leader": record.get("leader"),
                        }
                        for record in recent
                    ],
                    "recommended_pool": components,
                    "execution_trigger": "次日早盘 09:30-09:35 观察量比，若开盘爆量大于 1.5，结合仓位通行证分批执行。",
                    "reason": "满足连续 3 天综合热度 >= 70 且排名逐日改善，具备资金持续性。",
                    "latest_context": latest_context,
                }
            )
        verified.sort(key=lambda item: (item["score_trend"][-1], item["rank_gain"]), reverse=True)
        return verified

    def _write_report(self, payload: Mapping[str, Any], *, label: str = "latest") -> Path:
        self.report_dir.mkdir(parents=True, exist_ok=True)
        latest_path = self.report_dir / f"robot3_sniper_{label}.json"
        latest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        if label == "latest":
            self.latest_report_path = latest_path
        return latest_path

    def generate_sniper_signals(self) -> dict[str, Any]:
        snapshots = self._collect_history()
        verified = self._persistence_candidates(snapshots)
        generated_at = _now_str()

        if not verified:
            result = {
                "status": "SHORT_POSITION" if snapshots else "HOLD",
                "execution_date": date.today().isoformat(),
                "strategy_name": "Hermes-Persistence-Sniper (题材狙击一号)",
                "reason": (
                    "历史记忆库不足，无法计算 Persistence 持续性特征。"
                    if len(snapshots) < self.minimum_persistence_days
                    else "市场无任何板块满足持续性霸榜条件，多为一日游题材，保持防守/轻仓。"
                ),
                "radar_results": [],
                "history_dates": [item["date"] for item in snapshots[: self.minimum_persistence_days]],
                "generated_at": generated_at,
            }
            self._write_report(result)
            return result

        radar_results = []
        for item in verified:
            radar_results.append(
                {
                    "target_concept": item["concept_name"],
                    "category": item.get("category"),
                    "persistence_days": item["persistence_days"],
                    "score_trend": item["score_trend"],
                    "rank_trend": item["rank_trend"],
                    "rank_gain": item["rank_gain"],
                    "recommended_pool": item["recommended_pool"][:3],
                    "execution_trigger": item["execution_trigger"],
                    "reason": item["reason"],
                    "evidence": item["evidence"],
                }
            )

        result = {
            "status": "ATTACK",
            "execution_date": date.today().isoformat(),
            "strategy_name": "Hermes-Persistence-Sniper (题材狙击一号)",
            "radar_results": radar_results,
            "history_dates": [item["date"] for item in snapshots[: self.minimum_persistence_days]],
            "generated_at": generated_at,
        }
        self._write_report(result)
        return result

    def load_latest_report(self) -> dict[str, Any]:
        path = self.latest_report_path
        if not path.exists():
            return {}
        return self._load_json(path)


__all__ = ["Robot3SniperStrategy"]
