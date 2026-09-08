"""9000 原生研究工作区：研究记录与本地笔记。

数据只落在 backend/.cache/research_workspace，不上传、不进入仓库。
它是研究记录能力的 9000 原生实现。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import case, func

from services.research import chat as chat_layer, cli_runtime, myreports
from db.models import (
    AIAnalysisCache, LeaderLifecycle, SectorFlow, StockDailyKline,
    StockDataQuery, StockF10, StockFlow, StockHolderNumber, StockNewsSearch,
)
from db.session import get_db_session

router = APIRouter(prefix="/api/research-workspace", tags=["research workspace"])
logger = logging.getLogger(__name__)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_DIR = os.path.join(_ROOT, ".cache", "research_workspace")
_FILE = os.path.join(_DIR, "notes.json")
_LOCK = threading.Lock()


class NoteIn(BaseModel):
    title: str = ""
    content: str = ""
    tags: list[str] = Field(default_factory=list)


class LLMConfig(BaseModel):
    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str = ""


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


class ReportIn(BaseModel):
    name: str
    content_b64: str


def _load() -> list[dict]:
    try:
        with open(_FILE, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, list) else []
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


def _save(items: list[dict]) -> None:
    os.makedirs(_DIR, exist_ok=True)
    tmp = _FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _FILE)


def _database_radar() -> dict:
    from api.stock_info import _search_error, _search_items

    with get_db_session() as db:
        searches = db.query(StockNewsSearch).order_by(
            StockNewsSearch.search_time.desc(), StockNewsSearch.id.desc()
        ).limit(1000).all()
    groups = {
        "news": {"key": "news", "name": "资讯", "accent": "#3b82f6", "items": []},
        "report": {"key": "report", "name": "研报", "accent": "#a855f7", "items": []},
        "notice": {"key": "notice", "name": "公告", "accent": "#f59e0b", "items": []},
    }
    seen = set()
    data_as_of = None
    for search in searches:
        items = _search_items(search.result_raw)
        if items and data_as_of is None:
            data_as_of = search.search_time
        for item in items:
            title = str(item.get("title") or "").strip()
            date_value = str(item.get("date") or "").strip()
            url = str(item.get("jumpUrl") or "").strip()
            identity = (title, date_value, url)
            if not title or identity in seen:
                continue
            seen.add(identity)
            info_type = str(item.get("informationType") or "").upper()
            key = "notice" if info_type == "NOTICE" else "report" if info_type == "REPORT" else "news"
            if len(groups[key]["items"]) >= 30:
                continue
            groups[key]["items"].append({
                "title": title,
                "summary": str(item.get("content") or item.get("showText") or "").strip()[:240],
                "time": date_value,
                "url": url,
                "stock_code": search.stock_code,
                "stock_name": search.stock_name,
            })
    latest_error = _search_error(searches[0].result_raw) if searches else None
    industries = []
    for group in groups.values():
        group["total"] = len(group["items"])
        industries.append(group)
    return {
        "industries": industries,
        "source": "database",
        "status": "STALE" if any(group["items"] for group in industries) and latest_error else
                  latest_error or "READY" if any(group["items"] for group in industries) else "MISSING",
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "collection_as_of": searches[0].search_time.isoformat() if searches else None,
    }


def _database_market_overview() -> dict:
    with get_db_session() as db:
        trade_date = db.query(func.max(StockFlow.trade_date)).scalar()
        if trade_date is None:
            return {"sentiment": {}, "sectors": [], "source": "database", "status": "MISSING"}
        stats = db.query(
            func.count(StockFlow.id),
            func.sum(case((StockFlow.price_chg > 0, 1), else_=0)),
            func.sum(case((StockFlow.price_chg < 0, 1), else_=0)),
            func.sum(case((StockFlow.price_chg >= 9.5, 1), else_=0)),
            func.sum(case((StockFlow.price_chg <= -9.5, 1), else_=0)),
        ).filter(StockFlow.trade_date == trade_date).one()
        sector_date = db.query(func.max(SectorFlow.trade_date)).scalar()
        sector_rows = db.query(SectorFlow).filter(
            SectorFlow.trade_date == sector_date
        ).order_by(SectorFlow.heat_score.desc().nullslast(), SectorFlow.avg_chg.desc()).limit(30).all() if sector_date else []
    total, up, down, zt, dt = (int(value or 0) for value in stats)
    ratio = up / total if total else 0
    breadth = "偏强" if ratio >= 0.6 else "偏弱" if ratio <= 0.4 else "中性"
    return {
        "sentiment": {"breadth": breadth, "up": up, "down": down, "zt": zt, "dt": dt, "total": total},
        "sectors": [{
            "name": row.sector,
            "change_pct": float(row.avg_chg) if row.avg_chg is not None else None,
            "heat_score": float(row.heat_score) if row.heat_score is not None else None,
            "net_flow": float(row.net_flow) if row.net_flow is not None else None,
        } for row in sector_rows],
        "source": "database", "status": "READY", "data_as_of": trade_date.isoformat(),
    }


def _database_emotion() -> dict:
    overview = _database_market_overview()
    with get_db_session() as db:
        trade_date = db.query(func.max(LeaderLifecycle.trade_date)).scalar()
        rows = db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date == trade_date).all() if trade_date else []
    return {
        "zt_count": overview.get("sentiment", {}).get("zt"),
        "dt_count": overview.get("sentiment", {}).get("dt"),
        "lianban_count": len(rows),
        "max_boards": max((int(row.consecutive_days or 0) for row in rows), default=0),
        "source": "database", "status": "READY" if rows else "MISSING",
        "data_as_of": trade_date.isoformat() if trade_date else None,
    }


def _database_turnover_top() -> dict:
    with get_db_session() as db:
        trade_date = db.query(func.max(StockDailyKline.trade_date)).scalar()
        rows = db.query(StockDailyKline).filter(
            StockDailyKline.trade_date == trade_date,
            StockDailyKline.amount.isnot(None),
        ).order_by(StockDailyKline.amount.desc()).limit(10).all() if trade_date else []
        codes = [row.ts_code for row in rows]
        names = {}
        for row in db.query(StockFlow).filter(StockFlow.ts_code.in_(codes)).order_by(StockFlow.trade_date.desc()).all() if codes else []:
            names.setdefault(row.ts_code, (row.name, row.sector))
    return {
        "stocks": [{
            "code": row.ts_code.split(".")[0],
            "name": (names.get(row.ts_code) or (row.ts_code.split(".")[0], None))[0],
            "industry": (names.get(row.ts_code) or (None, None))[1],
            "pct": float(row.pct_chg) if row.pct_chg is not None else None,
            "amount": float(row.amount) if row.amount is not None else None,
        } for row in rows],
        "source": "database", "status": "READY" if rows else "MISSING",
        "data_as_of": trade_date.isoformat() if trade_date else None,
    }


@router.get("/notes")
def list_notes():
    with _LOCK:
        return {"data": sorted(_load(), key=lambda item: item.get("updated_at", 0), reverse=True)}


@router.post("/notes")
def create_note(note: NoteIn):
    title = (note.title or "未命名记录").strip()[:120]
    content = (note.content or "").strip()
    if not content:
        raise HTTPException(400, "记录内容不能为空")
    now = int(time.time() * 1000)
    item = {
        "id": uuid.uuid4().hex,
        "title": title,
        "content": content,
        "tags": [str(tag).strip()[:30] for tag in (note.tags or []) if str(tag).strip()][:12],
        "created_at": now,
        "updated_at": now,
    }
    with _LOCK:
        items = _load()
        items.append(item)
        _save(items)
    return {"data": item}


@router.delete("/notes/{note_id}")
def delete_note(note_id: str):
    with _LOCK:
        items = _load()
        next_items = [item for item in items if item.get("id") != note_id]
        if len(next_items) == len(items):
            raise HTTPException(404, "记录不存在")
        _save(next_items)
    return {"data": {"ok": True}}


# 研究工作区统一数据入口。这里直接调用 services.research，前端与新路由
# 不依赖历史聚合层。
@router.get("/radar")
def research_radar():
    return {"data": _database_radar()}


@router.post("/radar/refresh")
def research_radar_refresh():
    return {"data": {**_database_radar(), "message": "页面只读取数据库；外部资讯由后台采集任务更新"}}


@router.get("/market/overview")
def research_market_overview():
    return {"data": _database_market_overview()}


@router.get("/market/emotion")
def research_market_emotion():
    return {"data": _database_emotion()}


@router.get("/market/turnover-top")
def research_market_turnover_top():
    return {"data": _database_turnover_top()}


@router.get("/global/indices")
def research_global_indices():
    from api.global_market import get_indices
    items = []
    for market_code in ("US", "HK"):
        payload = get_indices(market_code)
        for item in payload.get("indices") or []:
            items.append({**item, "key": f"{market_code}:{item.get('code')}", "market": market_code})
    return {"data": items, "source": "database", "status": "READY" if items else "MISSING"}


@router.get("/industry")
def research_industry(top: int = 20):
    payload = _database_market_overview()
    limit = max(5, min(int(top), 50))
    return {"data": {
        "sectors": payload.get("sectors", [])[:limit],
        "source": "database", "status": payload.get("status"),
        "data_as_of": payload.get("data_as_of"),
    }}


_RESEARCH_SECTIONS = {"core", "capital", "boards", "risk"}


def _validate_stock(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


@router.get("/stock-research")
def research_stock(code: str, section: str = "core"):
    code = _validate_stock(code)
    if section not in _RESEARCH_SECTIONS:
        raise HTTPException(400, f"section 必须是：{', '.join(sorted(_RESEARCH_SECTIONS))}")
    ts_candidates = [code, f"{code}.SH", f"{code}.SZ", f"{code}.BJ"]
    with get_db_session() as db:
        flow = db.query(StockFlow).filter(StockFlow.ts_code.in_(ts_candidates)).order_by(StockFlow.trade_date.desc()).first()
        f10 = db.query(StockF10).filter(StockF10.ts_code.in_(ts_candidates)).order_by(StockF10.fetched_at.desc()).first()
        data_query = db.query(StockDataQuery).filter(StockDataQuery.stock_code == code).order_by(StockDataQuery.query_time.desc()).first()
        analysis = db.query(AIAnalysisCache).filter(AIAnalysisCache.stock_code == code).order_by(AIAnalysisCache.created_at.desc()).first()
        holder = db.query(StockHolderNumber).filter(StockHolderNumber.ts_code.in_(ts_candidates)).order_by(StockHolderNumber.ann_date.desc()).first()

    def parsed(value):
        if not value:
            return None
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    common = {
        "name": flow.name if flow else None,
        "sector": flow.sector if flow else None,
        "trade_date": flow.trade_date.isoformat() if flow else None,
    }
    if section == "core":
        data = {
            "info": common,
            "financials": parsed(f10.financial_json) if f10 else None,
            "valuation": parsed(f10.rating_json) if f10 else None,
            "analysis": parsed(analysis.analysis_data) if analysis else None,
        }
    elif section == "capital":
        data = {
            "fund_flow": {
                "net_inflow": float(flow.net_inflow) if flow and flow.net_inflow is not None else None,
                "main_force_inflow": float(flow.main_force_inflow) if flow and flow.main_force_inflow is not None else None,
                "retail_flow": float(flow.retail_flow) if flow and flow.retail_flow is not None else None,
                "trade_date": flow.trade_date.isoformat() if flow else None,
            },
            "database_query": parsed(data_query.result_tables) if data_query else None,
        }
    elif section == "boards":
        data = {"blocks": {"sector": flow.sector if flow else None}, "hot_concepts": None, "investor_qa": None}
    else:
        data = {"holders": {
            "ann_date": holder.ann_date.isoformat(),
            "end_date": holder.end_date.isoformat() if holder.end_date else None,
            "holder_num": int(holder.holder_num or 0),
            "avg_shares": float(holder.avg_shares or 0),
        } if holder else None, "dividend": None, "lockup": None}
    available = any(value not in (None, {}, []) for value in data.values())
    return {
        "code": code, "section": section, "generated_at": datetime.now().isoformat(),
        "source": "database", "status": "READY" if available else "MISSING",
        "data": data, "errors": {} if available else {"database": "暂无已入库研究数据"},
    }


@router.get("/myreports")
def research_reports():
    return {"data": myreports.list_reports()}


@router.post("/myreports")
def research_report_upload(report: ReportIn):
    try:
        return {"data": myreports.save_report(report.name, report.content_b64)}
    except myreports.ReportError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/myreports/file/{rid}")
def research_report_file(rid: str):
    hit = myreports.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@router.delete("/myreports/{rid}")
def research_report_delete(rid: str):
    return {"data": {"ok": myreports.delete_report(rid)}}


@router.post("/chat")
def research_chat(req: ChatReq):
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置，请先在 AI 接入页填写")
    is_cli = req.llm.provider.startswith("cli-")
    if is_cli and not cli_runtime.detect_cli(req.llm.provider[4:]):
        raise HTTPException(400, f"未检测到「{req.llm.provider[4:]}」对应的本机命令")
    if not is_cli and (not req.llm.apiKey or not req.llm.baseURL):
        raise HTTPException(400, "缺少 Base URL 或 API Key，请先填写")

    cfg = req.llm.model_dump() if hasattr(req.llm, "model_dump") else req.llm.dict()

    def generate():
        try:
            stream_fn = chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream
            for event in stream_fn(cfg, req.messages, req.context):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except Exception as exc:
            yield json.dumps({"type": "error", "message": f"对话失败：{exc}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(generate(), media_type="application/x-ndjson")
