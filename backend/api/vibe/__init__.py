"""Vibe-Research 能力聚合层

把 Vibe-Research 的数据源（A股 astock / 美港股 gstock / 资讯雷达 newsradar /
市场面板 market / 持仓 portfolio / 研报 myreports / AI chat）接入 AIROBOT，
统一以 /api/vibe/* 为前缀暴露，作为 AIROBOT 的二级数据源。

优先级策略：
- 实时行情/资金/龙虎榜/概念板块：优先走 AIROBOT 自有数据源（Tushare/同花顺/妙想/新浪），
  更及时、已与自选股体系打通。
- 财报/估值/研报/公告/新闻/互动易/解禁/大宗/股东户数：优先走 Vibe 数据源（astock 东财接口），
  覆盖度好、开箱即用、不做额外存储。
- 资讯雷达：独立走 Vibe newsradar 的 108 RSS 源。
- 美港股：走 gstock（东财域内源），作为 AIROBOT global_market 的补充。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Body, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from api.vibe import astock
from api.vibe import chat as chat_layer
from api.vibe import cli_runtime
from api.vibe import gstock
from api.vibe import market
from api.vibe import myreports as mr
from api.vibe import newsradar
from api.vibe import portfolio as pf
from collectors import data_source_registry as ds_registry

logger = logging.getLogger(__name__)
router = APIRouter()

# 启动持仓后台刷新（与 Vibe 原逻辑一致，本地缓存）
pf.start_scheduler(1800)

_CODE_RE = r"^\d{6}$"


def _validate(code: str) -> str:
    code = (code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    return code


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------
@router.get("/api/vibe/health")
def health():
    return {"ok": True, "service": "vibe-research-via-airobat", "version": "0.1.1"}


@router.get("/api/vibe/data-sources")
def data_sources():
    """返回 AIROBOT 聚合数据源注册表，含 Vibe-Research 数据源及优先级策略。"""
    return {
        "data": ds_registry.get_source_info(),
        "priority_note": (
            "实时行情/资金/龙虎榜/概念板块优先走 AIROBOT 自有源；"
            "财报/估值/研报/公告/新闻/互动易/解禁/大宗/股东户数/美港股/资讯雷达优先走 Vibe-Research。"
        ),
    }


# ---------------------------------------------------------------------------
# AI Chat（流式 NDJSON）
# ---------------------------------------------------------------------------
class LLMConfig(BaseModel):
    provider: str = ""
    baseURL: str = ""
    apiKey: str = ""
    model: str


class ChatReq(BaseModel):
    messages: list[dict]
    context: str = ""
    llm: LLMConfig


@router.post("/api/vibe/chat")
def chat(req: ChatReq):
    if not req.messages:
        raise HTTPException(400, "messages 不能为空")
    if not req.llm.model:
        raise HTTPException(400, "缺少模型配置")

    is_cli = req.llm.provider.startswith("cli-")
    if is_cli:
        kind = req.llm.provider[4:]
        if not cli_runtime.detect_cli(kind):
            raise HTTPException(400, f"未检测到「{kind}」对应的本机命令")
    elif not req.llm.apiKey or not req.llm.baseURL:
        raise HTTPException(400, "缺少 Base URL 或 API Key")

    cfg = req.llm.dict()

    def gen():
        try:
            events = (chat_layer.run_chat_cli_stream if is_cli else chat_layer.run_chat_stream)(
                cfg, req.messages, req.context
            )
            for ev in events:
                yield json.dumps(ev, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": f"对话失败：{e}"}, ensure_ascii=False) + "\n"

    return StreamingResponse(gen(), media_type="application/x-ndjson")


# ---------------------------------------------------------------------------
# 资讯雷达
# ---------------------------------------------------------------------------
@router.get("/api/vibe/radar")
def radar():
    try:
        return {"data": newsradar.get_radar(force=False)}
    except Exception as e:
        logger.exception("[vibe] radar error")
        raise HTTPException(502, f"资讯雷达异常：{e}") from e


@router.post("/api/vibe/radar/refresh")
def radar_refresh():
    try:
        return {"data": newsradar.fetch_radar()}
    except Exception as e:
        logger.exception("[vibe] radar refresh error")
        raise HTTPException(502, f"资讯雷达刷新失败：{e}") from e


# ---------------------------------------------------------------------------
# 市场总览 / 情绪 / 成交额 / 全球指数
# ---------------------------------------------------------------------------
@router.get("/api/vibe/market/overview")
def market_overview():
    try:
        return {"data": market.get_overview()}
    except Exception as e:
        logger.exception("[vibe] market overview error")
        raise HTTPException(502, f"市场总览异常：{e}") from e


@router.get("/api/vibe/market/emotion")
def market_emotion():
    try:
        return {"data": market.get_short_term_emotion()}
    except Exception as e:
        logger.exception("[vibe] market emotion error")
        raise HTTPException(502, f"短线情绪异常：{e}") from e


@router.get("/api/vibe/market/turnover-top")
def market_turnover_top():
    try:
        return {"data": market.get_turnover_top()}
    except Exception as e:
        logger.exception("[vibe] turnover top error")
        raise HTTPException(502, f"成交额榜异常：{e}") from e


@router.get("/api/vibe/global/indices")
def global_indices():
    try:
        return {"data": market.get_global_indices()}
    except Exception as e:
        logger.exception("[vibe] global indices error")
        raise HTTPException(502, f"全球指数异常：{e}") from e


@router.get("/api/vibe/global/stock")
def global_stock(symbol: str = Query(..., min_length=1, max_length=16)):
    try:
        data = gstock.us_hk_stock(symbol.strip())
        if not data:
            raise HTTPException(404, f"未找到美股/港股代码「{symbol}」")
        return {"data": data}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[vibe] global stock error")
        raise HTTPException(502, f"美港股查询异常：{e}") from e


# ---------------------------------------------------------------------------
# A股行情 / 指数 / 估值 / 财报 / 公告 / 新闻 / 研报
# ---------------------------------------------------------------------------
@router.get("/api/vibe/indices")
def indices():
    try:
        return {"data": astock.index_quote()}
    except Exception as e:
        logger.exception("[vibe] indices error")
        raise HTTPException(502, f"指数行情异常：{e}") from e


@router.get("/api/vibe/quote")
def quote(codes: str = Query(..., description="逗号分隔的 6 位代码")):
    lst = [c.strip() for c in codes.split(",") if c.strip()]
    if not lst or any(not c.isdigit() or len(c) != 6 for c in lst):
        raise HTTPException(400, "codes 必须是逗号分隔的 6 位数字")
    try:
        return {"data": astock.tencent_quote(lst)}
    except Exception as e:
        logger.exception("[vibe] quote error")
        raise HTTPException(502, f"行情源异常：{e}") from e


_PCT_CACHE: dict = {}
_ANN_CACHE: dict = {}
_FIN_CACHE: dict = {}
_DC_CACHE: dict = {}


def _cached_dc(endpoint: str, code: str, ttl: int, fetch):
    key = (endpoint, code)
    hit = _DC_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    data = fetch()
    _DC_CACHE[key] = (time.time(), data)
    return data


@router.get("/api/vibe/valuation/percentile")
def valuation_percentile(code: str = Query(...)):
    code = _validate(code)
    hit = _PCT_CACHE.get(code)
    if hit and time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.valuation_percentile(code)
        _PCT_CACHE[code] = (time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] valuation percentile error")
        raise HTTPException(502, f"估值分位异常：{e}") from e


@router.get("/api/vibe/announcements")
def announcements(code: str = Query(...)):
    code = _validate(code)
    hit = _ANN_CACHE.get(code)
    if hit and time.time() - hit[0] < 900:
        return {"data": hit[1]}
    try:
        data = astock.announcements(code)
        _ANN_CACHE[code] = (time.time(), data)
        return {"data": data}
    except Exception as e:
        logger.exception("[vibe] announcements error")
        raise HTTPException(502, f"公告源异常：{e}") from e


@router.get("/api/vibe/financials")
def financials(code: str = Query(...)):
    code = _validate(code)
    hit = _FIN_CACHE.get(code)
    if hit and time.time() - hit[0] < 1800:
        return {"data": hit[1]}
    try:
        data = astock.financials(code)
        _FIN_CACHE[code] = (time.time(), data)
        return {"data": data}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] financials error")
        raise HTTPException(502, f"财务摘要异常：{e}") from e


@router.get("/api/vibe/valuation")
def valuation(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": astock.full_valuation(code)}
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] valuation error")
        raise HTTPException(502, f"估值计算异常：{e}") from e


@router.get("/api/vibe/reports")
def reports(code: str = Query(...), pages: int = Query(2, ge=1, le=5)):
    code = _validate(code)
    try:
        rows = astock.eastmoney_reports(code, max_pages=pages)
        for r in rows:
            r["pdfUrl"] = astock.pdf_url(r.get("infoCode", "")) if r.get("infoCode") else None
        return {"data": rows}
    except Exception as e:
        logger.exception("[vibe] reports error")
        raise HTTPException(502, f"研报源异常：{e}") from e


@router.get("/api/vibe/news")
def news(code: str = Query(...), limit: int = Query(20, ge=1, le=50)):
    code = _validate(code)
    try:
        return {"data": astock.stock_news(code, limit=limit)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] news error")
        raise HTTPException(502, f"新闻源异常：{e}") from e


@router.get("/api/vibe/info")
def info(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": astock.individual_info(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] info error")
        raise HTTPException(502, f"基本面源异常：{e}") from e


@router.get("/api/vibe/disclosure")
def disclosure(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": astock.disclosure(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] disclosure error")
        raise HTTPException(502, f"公告源异常：{e}") from e


@router.get("/api/vibe/kline")
def kline(code: str = Query(...), category: int = Query(4), offset: int = Query(60, ge=1, le=800)):
    code = _validate(code)
    try:
        return {"data": astock.kline(code, category=category, offset=offset)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] kline error")
        raise HTTPException(502, f"K线源异常：{e}") from e


@router.get("/api/vibe/finance")
def finance(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": astock.finance(code)}
    except astock.DependencyMissing as e:
        raise HTTPException(501, str(e)) from e
    except Exception as e:
        logger.exception("[vibe] finance error")
        raise HTTPException(502, f"财务源异常：{e}") from e


# ---------------------------------------------------------------------------
# 资金面 / 筹码 / 信号（东财数据中心）
# ---------------------------------------------------------------------------
@router.get("/api/vibe/margin")
def margin(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("margin", code, 1800, lambda: astock.margin_trading(code))}
    except Exception as e:
        logger.exception("[vibe] margin error")
        raise HTTPException(502, f"融资融券异常：{e}") from e


@router.get("/api/vibe/block-trade")
def block_trade(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("block", code, 1800, lambda: astock.block_trade(code))}
    except Exception as e:
        logger.exception("[vibe] block trade error")
        raise HTTPException(502, f"大宗交易异常：{e}") from e


@router.get("/api/vibe/holders")
def holders(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("holders", code, 1800, lambda: astock.holder_num_change(code))}
    except Exception as e:
        logger.exception("[vibe] holders error")
        raise HTTPException(502, f"股东户数异常：{e}") from e


@router.get("/api/vibe/dividend")
def dividend(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("dividend", code, 1800, lambda: astock.dividend_history(code))}
    except Exception as e:
        logger.exception("[vibe] dividend error")
        raise HTTPException(502, f"分红送转异常：{e}") from e


@router.get("/api/vibe/fund-flow")
def fund_flow(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("fundflow", code, 900, lambda: astock.stock_fund_flow_120d(code))}
    except Exception as e:
        logger.exception("[vibe] fund flow error")
        raise HTTPException(502, f"资金流异常：{e}") from e


@router.get("/api/vibe/dragon-tiger")
def dragon_tiger(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("dt", code, 1800, lambda: astock.dragon_tiger_board(code))}
    except Exception as e:
        logger.exception("[vibe] dragon tiger error")
        raise HTTPException(502, f"龙虎榜异常：{e}") from e


@router.get("/api/vibe/lockup")
def lockup(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("lockup", code, 1800, lambda: astock.lockup_expiry(code))}
    except Exception as e:
        logger.exception("[vibe] lockup error")
        raise HTTPException(502, f"解禁日历异常：{e}") from e


@router.get("/api/vibe/blocks")
def blocks(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("blocks", code, 1800, lambda: astock.concept_blocks(code))}
    except Exception as e:
        logger.exception("[vibe] blocks error")
        raise HTTPException(502, f"板块归属异常：{e}") from e


@router.get("/api/vibe/hot-concepts")
def hot_concepts(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("hotcon", code, 900, lambda: astock.hot_concepts(code))}
    except Exception as e:
        logger.exception("[vibe] hot concepts error")
        raise HTTPException(502, f"热门概念异常：{e}") from e


@router.get("/api/vibe/investor-qa")
def investor_qa(code: str = Query(...)):
    code = _validate(code)
    try:
        return {"data": _cached_dc("irm", code, 900, lambda: astock.investor_qa(code))}
    except Exception as e:
        logger.exception("[vibe] investor qa error")
        raise HTTPException(502, f"互动易异常：{e}") from e


@router.get("/api/vibe/industry")
def industry(top: int = Query(20, ge=5, le=50)):
    key = ("industry", str(top))
    hit = _DC_CACHE.get(key)
    if hit and time.time() - hit[0] < 300:
        return {"data": hit[1]}
    try:
        data = astock.industry_comparison(top_n=top)
        _DC_CACHE[key] = (time.time(), data)
        return {"data": data}
    except Exception as e:
        logger.exception("[vibe] industry error")
        raise HTTPException(502, f"行业排名异常：{e}") from e


# ---------------------------------------------------------------------------
# 持仓 / 研报（本地缓存，不上传）
# ---------------------------------------------------------------------------
class HoldingIn(BaseModel):
    code: str
    shares: float
    cost: float


class CloseIn(BaseModel):
    code: str
    date: str
    price: float
    shares: float
    cost: float


@router.get("/api/vibe/portfolio")
def portfolio_get():
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:
        logger.exception("[vibe] portfolio error")
        raise HTTPException(502, f"持仓读取异常：{e}") from e


@router.post("/api/vibe/portfolio/holding")
def portfolio_add(h: HoldingIn):
    code = (h.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if h.shares <= 0:
        raise HTTPException(400, "数量必须大于 0")
    return {"data": pf.add_holding(code, h.shares, h.cost)}


@router.delete("/api/vibe/portfolio/holding")
def portfolio_remove(code: str = Query(...)):
    return {"data": pf.remove_holding(code.strip())}


@router.post("/api/vibe/portfolio/close")
def portfolio_close(c: CloseIn):
    code = (c.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "代码必须是 6 位数字")
    if c.price <= 0 or c.shares <= 0:
        raise HTTPException(400, "清仓价与股数必须大于 0")
    if not c.date:
        raise HTTPException(400, "请填清仓日期")
    from datetime import datetime
    try:
        datetime.strptime(c.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "清仓日期格式应为 YYYY-MM-DD") from None
    return {"data": pf.close_position(code, c.date, c.price, c.shares, c.cost)}


@router.delete("/api/vibe/portfolio/close")
def portfolio_close_remove(index: int = Query(...)):
    return {"data": pf.remove_closed(index)}


@router.post("/api/vibe/portfolio/refresh")
def portfolio_refresh():
    try:
        return {"data": pf.get_portfolio()}
    except Exception as e:
        logger.exception("[vibe] portfolio refresh error")
        raise HTTPException(502, f"刷新失败：{e}") from e


class ReportIn(BaseModel):
    name: str
    content_b64: str


@router.get("/api/vibe/myreports")
def myreports_list():
    return {"data": mr.list_reports()}


@router.post("/api/vibe/myreports")
def myreports_upload(r: ReportIn):
    try:
        return {"data": mr.save_report(r.name, r.content_b64)}
    except mr.ReportError as e:
        raise HTTPException(400, str(e)) from e


@router.get("/api/vibe/myreports/file/{rid}")
def myreports_file(rid: str):
    from fastapi.responses import FileResponse
    hit = mr.report_path(rid)
    if not hit:
        raise HTTPException(404, "研报不存在")
    path, name = hit
    return FileResponse(str(path), filename=name)


@router.delete("/api/vibe/myreports/{rid}")
def myreports_delete(rid: str):
    return {"data": {"ok": mr.delete_report(rid)}}
