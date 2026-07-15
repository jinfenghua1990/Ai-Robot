"""AIROBOT Vibe-Research MCP Server —— 把 Vibe 数据工具暴露给 Claude Code 等 AI agent。

运行方式（stdio JSON-RPC，零第三方依赖）：
    python backend/mcp/vibe_mcp_server.py

挂进 Claude Code：
    claude mcp add airobat-vibe \
        -- /Users/gino/Projects/AIROBOT/backend/.venv/bin/python \
           /Users/gino/Projects/AIROBOT/backend/mcp/vibe_mcp_server.py

（根据实际虚拟环境路径调整 python 可执行文件位置；若用系统 Python 则直接写 python 路径。）

它通过调用本地 AIROBOT 后端的 /api/vibe/* HTTP 接口获取数据，因此启动前请确保：
    uvicorn main:app --host 127.0.0.1 --port 9000
已在运行。可通过环境变量 AIROBOT_API_URL 修改后端地址，例如：
    AIROBOT_API_URL=http://127.0.0.1:9000 python backend/mcp/vibe_mcp_server.py

合规：所有工具只返回客观公开数据，不输出任何买卖建议/评级/目标价。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger("vibe_mcp_server")
if not logger.handlers:
    # stdio JSON-RPC 进程不能输出到 stdout（会污染协议），只配 stderr。
    _h = logging.StreamHandler(sys.stderr)
    _h.setFormatter(logging.Formatter("[vibe_mcp] %(levelname)s %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.WARNING)

SERVER_INFO = {"name": "airobat-vibe", "version": "0.1.0"}
DEFAULT_PROTOCOL = "2024-11-05"
DEFAULT_API_URL = os.environ.get("AIROBOT_API_URL", "http://127.0.0.1:9000").rstrip("/")


def _api_get(path: str, params: dict[str, Any] | None = None) -> dict:
    """调用 AIROBOT /api/vibe/* GET 接口，返回 JSON data 字段。"""
    url = f"{DEFAULT_API_URL}{path}"
    if params:
        qs = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
        if qs:
            url = f"{url}?{qs}"
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("data") if isinstance(body, dict) and "data" in body else body
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception as parse_err:
            logger.debug("vibe_mcp: HTTP error body parse failed (%s) for %s", parse_err, path)
            detail = e.reason
        return {"error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        logger.warning("vibe_mcp: GET %s failed: %s", path, e)
        return {"error": f"请求失败：{e}"}


def _api_post(path: str, payload: dict | None = None) -> dict:
    """调用 AIROBOT /api/vibe/* POST 接口。"""
    url = f"{DEFAULT_API_URL}{path}"
    data = json.dumps(payload or {}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("data") if isinstance(body, dict) and "data" in body else body
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail", e.reason)
        except Exception as parse_err:
            logger.debug("vibe_mcp: HTTP error body parse failed (%s) for %s", parse_err, path)
            detail = e.reason
        return {"error": f"HTTP {e.code}: {detail}"}
    except Exception as e:
        logger.warning("vibe_mcp: POST %s failed: %s", path, e)
        return {"error": f"请求失败：{e}"}


def _call(name: str, args: dict) -> dict:
    """根据工具名分发到对应 /api/vibe 接口。"""
    code = str(args.get("code") or "").strip()
    symbol = str(args.get("symbol") or "").strip()

    if name == "query_vibe_radar":
        return _api_get("/api/vibe/radar")
    if name == "query_vibe_radar_refresh":
        return _api_post("/api/vibe/radar/refresh")

    if name == "query_vibe_market_overview":
        return _api_get("/api/vibe/market/overview")
    if name == "query_vibe_market_emotion":
        return _api_get("/api/vibe/market/emotion")
    if name == "query_vibe_turnover_top":
        return _api_get("/api/vibe/market/turnover-top")
    if name == "query_vibe_global_indices":
        return _api_get("/api/vibe/global/indices")
    if name == "query_vibe_global_stock":
        if not symbol:
            return {"error": "缺少 symbol 参数"}
        return _api_get("/api/vibe/global/stock", {"symbol": symbol})

    if name == "query_vibe_indices":
        return _api_get("/api/vibe/indices")
    if name == "query_vibe_quote":
        codes = args.get("codes")
        if isinstance(codes, list):
            codes = ",".join(str(c) for c in codes)
        if not codes:
            return {"error": "缺少 codes 参数"}
        return _api_get("/api/vibe/quote", {"codes": codes})

    if name == "query_vibe_valuation":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/valuation", {"code": code})
    if name == "query_vibe_valuation_percentile":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/valuation/percentile", {"code": code})
    if name == "query_vibe_financials":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/financials", {"code": code})
    if name == "query_vibe_finance":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/finance", {"code": code})
    if name == "query_vibe_reports":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        pages = args.get("pages", 2)
        return _api_get("/api/vibe/reports", {"code": code, "pages": pages})
    if name == "query_vibe_news":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        limit = args.get("limit", 20)
        return _api_get("/api/vibe/news", {"code": code, "limit": limit})
    if name == "query_vibe_announcements":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/announcements", {"code": code})
    if name == "query_vibe_disclosure":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/disclosure", {"code": code})
    if name == "query_vibe_info":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/info", {"code": code})
    if name == "query_vibe_kline":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        category = args.get("category", 4)
        offset = args.get("offset", 60)
        return _api_get("/api/vibe/kline", {"code": code, "category": category, "offset": offset})

    if name == "query_vibe_fund_flow":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/fund-flow", {"code": code})
    if name == "query_vibe_margin":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/margin", {"code": code})
    if name == "query_vibe_holders":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/holders", {"code": code})
    if name == "query_vibe_block_trade":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/block-trade", {"code": code})
    if name == "query_vibe_dividend":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/dividend", {"code": code})
    if name == "query_vibe_dragon_tiger":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/dragon-tiger", {"code": code})
    if name == "query_vibe_lockup":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/lockup", {"code": code})
    if name == "query_vibe_blocks":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/blocks", {"code": code})
    if name == "query_vibe_hot_concepts":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/hot-concepts", {"code": code})
    if name == "query_vibe_investor_qa":
        if not code or len(code) != 6 or not code.isdigit():
            return {"error": "code 必须是 6 位数字"}
        return _api_get("/api/vibe/investor-qa", {"code": code})
    if name == "query_vibe_industry":
        top = args.get("top", 20)
        return _api_get("/api/vibe/industry", {"top": top})

    return {"error": f"未知工具：{name}"}


# MCP Tools 定义（OpenAI function 风格参数转 MCP inputSchema）
MCP_TOOLS = [
    {
        "name": "query_vibe_radar",
        "description": "获取 Vibe-Research 资讯雷达：12+ 赛道公开 RSS 资讯聚合（宏观/政策/产业/公司）。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_radar_refresh",
        "description": "强制刷新 Vibe-Research 资讯雷达（重新抓取 RSS，耗时约 20-40 秒）。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_market_overview",
        "description": "获取 Vibe-Research 市场总览：市场情绪、板块资金流、大盘指数。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_market_emotion",
        "description": "获取 Vibe-Research 短线情绪：连板梯队、涨跌停家数、炸板率、封板率。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_turnover_top",
        "description": "获取 Vibe-Research 全市场成交额榜 Top20。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_global_indices",
        "description": "获取 Vibe-Research 全球指数快照：道指/标普500/纳斯达克/恒生/恒生科技。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_global_stock",
        "description": "查询美股/港股/韩股个股聚合数据。美股用字母代码如 AAPL/NVDA，港股用数字如 00700，韩股用 6 位数字加 .KS 如 005930.KS。",
        "inputSchema": {"type": "object", "properties": {"symbol": {"type": "string"}}, "required": ["symbol"]},
    },
    {
        "name": "query_vibe_indices",
        "description": "获取 A 股大盘指数实时行情：上证/深证成指/创业板指/沪深300。",
        "inputSchema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "query_vibe_quote",
        "description": "批量查询 A 股实时行情：现价/涨跌/PE/PB/市值/换手/涨跌停。",
        "inputSchema": {"type": "object", "properties": {"codes": {"type": "array", "items": {"type": "string"}, "description": "6 位股票代码列表"}}, "required": ["codes"]},
    },
    {
        "name": "query_vibe_valuation",
        "description": "查询单只 A 股完整估值：行情 + 机构一致预期 EPS + 前向 PE/PEG/PE 消化年数。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_valuation_percentile",
        "description": "查询单只 A 股 PE-TTM / PB 近 5 年历史分位。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_financials",
        "description": "查询单只 A 股财务关键指标（同花顺财务摘要，最新报告期）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_finance",
        "description": "查询单只 A 股季报财务快照（mootdx）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_reports",
        "description": "查询单只 A 股近期研报列表（标题/机构/评级/日期/PDF 链接）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}, "pages": {"type": "integer", "default": 2}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_news",
        "description": "查询单只 A 股近期新闻（标题/时间/来源）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}, "limit": {"type": "integer", "default": 20}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_announcements",
        "description": "查询单只 A 股近期公告（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_disclosure",
        "description": "查询单只 A 股巨潮公告列表。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_info",
        "description": "查询单只 A 股基本面：行业/股本/上市时间。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_kline",
        "description": "查询单只 A 股 K 线。category 4=日 5=周 6=月 11=60分钟。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}, "category": {"type": "integer", "default": 4}, "offset": {"type": "integer", "default": 60}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_fund_flow",
        "description": "查询单只 A 股 120 日主力净流入（东财 push2his）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_margin",
        "description": "查询单只 A 股融资融券明细（东财，日级）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_holders",
        "description": "查询单只 A 股股东户数变化（东财，季度级）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_block_trade",
        "description": "查询单只 A 股大宗交易（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_dividend",
        "description": "查询单只 A 股分红送转历史（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_dragon_tiger",
        "description": "查询单只 A 股近期龙虎榜记录 + 买卖席位 + 机构净买（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_lockup",
        "description": "查询单只 A 股限售解禁日历：历史解禁 + 未来 90 天待解禁（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_blocks",
        "description": "查询单只 A 股所属板块/概念归属（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_hot_concepts",
        "description": "查询单只 A 股当下被市场归到哪些热门概念（东财）。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_investor_qa",
        "description": "查询单只 A 股互动易问答（巨潮）：投资者提问 + 公司回复。",
        "inputSchema": {"type": "object", "properties": {"code": {"type": "string", "description": "6 位股票代码"}}, "required": ["code"]},
    },
    {
        "name": "query_vibe_industry",
        "description": "查询 A 股全行业涨跌幅排名（东财行业板块）。",
        "inputSchema": {"type": "object", "properties": {"top": {"type": "integer", "default": 20}}, "required": []},
    },
]


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _result(rid, result) -> None:
    _send({"jsonrpc": "2.0", "id": rid, "result": result})


def _error(rid, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}})


def _handle(msg: dict) -> None:
    method = msg.get("method")
    rid = msg.get("id")

    if method == "notifications/initialized":
        return

    if method == "initialize":
        params = msg.get("params") or {}
        proto = params.get("protocolVersion", DEFAULT_PROTOCOL)
        _result(rid, {
            "protocolVersion": proto,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        })
        return

    if method == "ping":
        _result(rid, {})
        return

    if method == "tools/list":
        _result(rid, {"tools": MCP_TOOLS})
        return

    if method == "tools/call":
        params = msg.get("params") or {}
        name = params.get("name", "")
        args = params.get("arguments") or {}
        data = _call(name, args)
        is_error = isinstance(data, dict) and "error" in data
        _result(rid, {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "isError": is_error,
        })
        return

    if rid is not None:
        _error(rid, -32601, f"未知方法：{method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        try:
            _handle(msg)
        except Exception as e:
            if msg.get("id") is not None:
                _error(msg["id"], -32603, f"内部错误：{e}")


if __name__ == "__main__":
    main()
