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
from concurrent.futures import ThreadPoolExecutor, as_completed

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field

from services.research import astock, chat as chat_layer, cli_runtime, gstock, market, myreports, newsradar

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
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as exc:
        logger.exception("research radar error")
        raise HTTPException(502, f"资讯雷达异常：{exc}") from exc


@router.post("/radar/refresh")
def research_radar_refresh():
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as exc:
        logger.exception("research radar refresh error")
        raise HTTPException(502, f"资讯雷达刷新失败：{exc}") from exc


@router.get("/market/overview")
def research_market_overview():
    try:
        return {"data": market.get_overview()}
    except Exception as exc:
        logger.exception("research market overview error")
        raise HTTPException(502, f"市场总览异常：{exc}") from exc


@router.get("/market/emotion")
def research_market_emotion():
    try:
        return {"data": market.get_short_term_emotion()}
    except Exception as exc:
        logger.exception("research market emotion error")
        raise HTTPException(502, f"短线情绪异常：{exc}") from exc


@router.get("/market/turnover-top")
def research_market_turnover_top():
    try:
        return {"data": market.get_turnover_top()}
    except Exception as exc:
        logger.exception("research turnover top error")
        raise HTTPException(502, f"成交额榜异常：{exc}") from exc


@router.get("/global/indices")
def research_global_indices():
    try:
        return {"data": market.get_global_indices()}
    except Exception as exc:
        logger.exception("research global indices error")
        raise HTTPException(502, f"全球指数异常：{exc}") from exc


@router.get("/industry")
def research_industry(top: int = 20):
    try:
        return {"data": astock.industry_comparison(top_n=max(5, min(int(top), 50)))}
    except Exception as exc:
        logger.exception("research industry error")
        raise HTTPException(502, f"行业排名异常：{exc}") from exc


_RESEARCH_GROUPS = {
    "core": {
        "info": lambda code: astock.individual_info(code),
        "financials": lambda code: astock.financials(code),
        "valuation": lambda code: astock.full_valuation(code),
        "valuation_percentile": lambda code: astock.valuation_percentile(code),
    },
    "capital": {
        "fund_flow": lambda code: astock.stock_fund_flow_120d(code),
        "margin": lambda code: astock.margin_trading(code),
        "block_trade": lambda code: astock.block_trade(code),
        "dragon_tiger": lambda code: astock.dragon_tiger_board(code),
    },
    "boards": {
        "blocks": lambda code: astock.concept_blocks(code),
        "hot_concepts": lambda code: astock.hot_concepts(code),
        "investor_qa": lambda code: astock.investor_qa(code),
    },
    "risk": {
        "holders": lambda code: astock.holder_num_change(code),
        "dividend": lambda code: astock.dividend_history(code),
        "lockup": lambda code: astock.lockup_expiry(code),
    },
}
_STOCK_RESEARCH_CACHE: dict[tuple[str, str], tuple[float, dict]] = {}


def _validate_stock(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


@router.get("/stock-research")
def research_stock(code: str, section: str = "core"):
    code = _validate_stock(code)
    if section not in _RESEARCH_GROUPS:
        raise HTTPException(400, f"section 必须是：{', '.join(_RESEARCH_GROUPS)}")
    cache_key = (code, section)
    hit = _STOCK_RESEARCH_CACHE.get(cache_key)
    if hit and time.time() - hit[0] < 600:
        return hit[1]
    group = _RESEARCH_GROUPS[section]
    data: dict = {}
    errors: dict = {}
    with ThreadPoolExecutor(max_workers=min(4, len(group))) as pool:
        futures = {pool.submit(fetch, code): name for name, fetch in group.items()}
        for future in as_completed(futures):
            name = futures[future]
            try:
                data[name] = future.result()
            except Exception as exc:
                logger.warning("research stock %s/%s failed: %s", code, name, exc)
                data[name] = None
                errors[name] = str(exc) or "数据源暂不可用"
    result = {
        "code": code,
        "section": section,
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": "9000 研究数据服务",
        "data": data,
        "errors": errors,
    }
    _STOCK_RESEARCH_CACHE[cache_key] = (time.time(), result)
    return result


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
