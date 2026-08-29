"""iFinD MCP 客户端与选股结果解析。"""

from __future__ import annotations

import csv
from datetime import date
import io
import ipaddress
import json
import logging
import re
import socket
import time
from urllib.parse import urljoin, urlparse

import httpx

from .scoring import is_main_board_candidate, normalize_symbol


logger = logging.getLogger(__name__)

DEFAULT_ENDPOINT = "https://api-mcp.51ifind.com:8643/ds-mcp-servers/hexin-ifind-ds-stock-mcp"
MCP_PROTOCOL_VERSION = "2025-06-18"
_CODE_KEYS = ("股票代码", "证券代码", "代码", "ts_code", "thscode", "symbol", "code")
_NAME_KEYS = ("股票简称", "证券简称", "简称", "股票名称", "证券名称", "name")
_COUNT_KEYS = ("区间涨停次数", "涨停次数", "涨停天数", "limit_up_count", "limitcount")
_PRICE_KEYS = ("最新价", "现价", "price")
_CHANGE_KEYS = ("涨跌幅", "change_pct", "change")
_OPEN_KEYS = ("开盘价", "open")
_HIGH_KEYS = ("最高价", "high")
_LOW_KEYS = ("最低价", "low")
_VOLUME_KEYS = ("成交量", "volume", "vol")
_TIME_KEYS = ("时间", "time", "更新时间", "datetime")


class MCPClientError(RuntimeError):
    pass


def _lookup(row: dict, keys: tuple[str, ...]):
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        if key.lower() in lowered:
            return lowered[key.lower()]
    return None


def _count(value) -> int | None:
    if value is None or str(value).strip() in {"", "--", "—", "-"}:
        return None
    match = re.search(r"\d+", str(value))
    return int(match.group()) if match else None


def _number(value) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "").replace("%", ""))
    except (TypeError, ValueError):
        return None


def _lookup_contains(row: dict, keys: tuple[str, ...]):
    exact = _lookup(row, keys)
    if exact is not None:
        return exact
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        target = key.lower()
        for header, value in lowered.items():
            if target in header:
                return value
    return None


def _structured_rows(value):
    if isinstance(value, dict):
        if _lookup(value, _CODE_KEYS) is not None:
            yield value
        columns = value.get("columns") or value.get("headers")
        data = value.get("data")
        if isinstance(columns, list) and isinstance(data, list):
            for item in data:
                if isinstance(item, (list, tuple)) and len(item) == len(columns):
                    yield dict(zip(columns, item))
        for nested in value.values():
            yield from _structured_rows(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _structured_rows(item)


def _table_rows(text: str) -> list[dict]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for index, line in enumerate(lines):
        if "|" not in line or not any(key in line for key in _CODE_KEYS[:3]):
            continue
        headers = [cell.strip() for cell in line.strip("|").split("|")]
        start = index + 1
        if start < len(lines) and re.fullmatch(r"\|?[\s:|-]+\|?", lines[start]):
            start += 1
        rows = []
        for current in lines[start:]:
            if "|" not in current:
                break
            cells = [cell.strip() for cell in current.strip("|").split("|")]
            if len(cells) == len(headers):
                rows.append(dict(zip(headers, cells)))
        if rows:
            return rows

    for delimiter in (",", "\t"):
        try:
            reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
            rows = [dict(row) for row in reader if row]
            if rows and _lookup(rows[0], _CODE_KEYS) is not None:
                return rows
        except csv.Error:
            continue
    return []


def _payload_rows(payload):
    if isinstance(payload, str):
        text = payload.strip()
        try:
            decoded = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            decoded = None
        if decoded is not None:
            yield from _structured_rows(decoded)
        yield from _table_rows(text)
        return
    yield from _structured_rows(payload)
    if isinstance(payload, dict):
        for block in payload.get("content") or []:
            if isinstance(block, dict) and block.get("type") == "text":
                yield from _payload_rows(block.get("text", ""))


def _candidate_rows(payload):
    """剥开 iFinD 的多层 JSON 包装（content[].text → data → Markdown 表格）。"""

    if isinstance(payload, str):
        yield from _payload_rows(payload)
        return
    for node in _walk_payload(payload):
        if isinstance(node, str) and node.strip():
            yield from _payload_rows(node)
        elif isinstance(node, dict):
            yield from _structured_rows(node)


def parse_candidates(payload) -> list[dict]:
    """解析 JSON/Markdown/CSV，并只保留非 ST 的 A 股主板股票。"""

    candidates = []
    seen = set()
    source_rank = 0
    for row in _candidate_rows(payload):
        source_rank += 1
        raw_code = _lookup(row, _CODE_KEYS)
        name = str(_lookup(row, _NAME_KEYS) or "").strip()
        symbol = normalize_symbol(raw_code)
        if not symbol or symbol in seen or not is_main_board_candidate(symbol, name):
            continue
        seen.add(symbol)
        candidates.append({
            "ts_code": symbol,
            "name": name,
            "limit_up_count": _count(_lookup(row, _COUNT_KEYS)),
            "source_rank": source_rank,
            "raw": row,
        })
    return candidates


def _json_from_response(response: httpx.Response):
    if not response.content:
        return None
    content_type = response.headers.get("content-type", "")
    if "text/event-stream" in content_type:
        events = []
        for line in response.text.splitlines():
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data and data != "[DONE]":
                try:
                    events.append(json.loads(data))
                except json.JSONDecodeError:
                    continue
        return events[-1] if events else None
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise MCPClientError("iFinD MCP 返回了无法解析的响应") from exc


def _safe_public_https(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MCPClientError("iFinD 导出链接不是有效 HTTPS 地址")
    if parsed.hostname.lower() == "localhost":
        raise MCPClientError("拒绝访问本机导出链接")
    try:
        literal = ipaddress.ip_address(parsed.hostname)
        addresses = [literal]
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(item[4][0]) for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
        except (OSError, socket.gaierror) as exc:
            raise MCPClientError("iFinD 导出链接域名无法解析") from exc
    if any(address.is_private or address.is_loopback or address.is_link_local or address.is_reserved for address in addresses):
        raise MCPClientError("拒绝访问非公网导出地址")


class IfindMCPClient:
    def __init__(self, token: str, endpoint: str = DEFAULT_ENDPOINT, timeout: float = 60.0):
        self.endpoint = endpoint
        self._next_id = 0
        self._session_id = None
        self._last_tool_request_at = 0.0
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json, text/event-stream",
                "Content-Type": "application/json",
                "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
                "User-Agent": "AIROBOT-Horseback/1.1.5",
            },
        )
        # CSV 可能托管在第三方对象存储；必须使用不带 Authorization 的独立客户端，
        # 避免把 iFinD MCP 密钥发送给导出链接域名。
        self._download_client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=15.0),
            headers={"User-Agent": "AIROBOT-Horseback/1.1.5"},
        )

    def close(self):
        self._client.close()
        self._download_client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def _post(self, payload: dict, expect_response: bool = True):
        headers = {"Mcp-Session-Id": self._session_id} if self._session_id else None
        try:
            response = self._client.post(self.endpoint, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise MCPClientError("无法连接 iFinD MCP 服务") from exc
        if response.status_code in (401, 403):
            raise MCPClientError("iFinD 密钥无效、已过期或没有该 MCP 权限")
        if response.status_code >= 400:
            raise MCPClientError(f"iFinD MCP 请求失败（HTTP {response.status_code}）")
        self._session_id = response.headers.get("mcp-session-id") or self._session_id
        return _json_from_response(response) if expect_response else None

    def _request(self, method: str, params: dict):
        self._next_id += 1
        payload = {"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params}
        response = self._post(payload)
        if not isinstance(response, dict):
            raise MCPClientError("iFinD MCP 未返回 JSON-RPC 结果")
        if response.get("error"):
            message = response["error"].get("message") if isinstance(response["error"], dict) else None
            raise MCPClientError(f"iFinD MCP 调用失败：{message or '未知错误'}")
        return response.get("result")

    def initialize(self):
        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "AIROBOT Horseback Screener", "version": "1.1.5"},
        })
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, expect_response=False)
        return result

    def call_tool(self, name: str, arguments: dict):
        elapsed = time.monotonic() - self._last_tool_request_at
        if self._last_tool_request_at and elapsed < 0.5:
            time.sleep(0.5 - elapsed)
        self._last_tool_request_at = time.monotonic()
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def fetch_export(self, url: str) -> str:
        current = url
        for _ in range(4):
            _safe_public_https(current)
            try:
                response = self._download_client.get(
                    current,
                    headers={"Accept": "text/csv,text/plain,application/octet-stream"},
                    follow_redirects=False,
                )
            except httpx.HTTPError as exc:
                raise MCPClientError("iFinD CSV 下载失败") from exc
            if response.status_code in (301, 302, 303, 307, 308):
                location = response.headers.get("location")
                if not location:
                    raise MCPClientError("iFinD CSV 重定向缺少地址")
                current = urljoin(current, location)
                continue
            if response.status_code >= 400:
                raise MCPClientError(f"iFinD CSV 下载失败（HTTP {response.status_code}）")
            for encoding in ("utf-8-sig", "gb18030"):
                try:
                    return response.content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            raise MCPClientError("iFinD CSV 编码无法识别")
        raise MCPClientError("iFinD CSV 重定向次数过多")


def build_limit_up_query(start_date: date, end_date: date) -> str:
    return (
        f"筛选 {start_date.isoformat()} 至 {end_date.isoformat()} 期间 A 股涨停股票，"
        "仅保留沪深主板，排除 ST、*ST、退市、创业板、科创板和北交所；"
        "返回股票代码、股票简称、区间涨停次数，按最近涨停日期倒序。"
    )


def build_daily_limit_up_query(trade_date: date) -> str:
    return f"{trade_date.year}年{trade_date.month}月{trade_date.day}日A股涨停股票"


def _payload_text(value) -> str:
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return ""


def _candidates_from_result(client: IfindMCPClient, result) -> list[dict]:
    candidates = parse_candidates(result)
    if candidates:
        return candidates
    for url in re.findall(r"https://[^\s<>\]\[\"']+", _payload_text(result)):
        if ".csv" not in url.lower():
            continue
        candidates = parse_candidates(client.fetch_export(url.rstrip(".,)")))
        if candidates:
            return candidates
    return []


def collect_daily_limit_up_candidates(token: str, trade_dates: list[date], attempts_per_day: int = 3) -> tuple[list[dict], list[dict]]:
    """按交易日读取涨停池，保留最近涨停日期与十日出现次数。

    iFinD MCP 单日查询偶发返回空或失败时原地重试。十日窗口必须完整，
    任何交易日仍缺失都会拒绝本次扫描，避免把少计的涨停次数当成有效结果。
    """

    if not trade_dates:
        raise ValueError("涨停池需要至少一个交易日")
    aggregate: dict[str, dict] = {}
    raw_payloads = []
    missing_dates: list[date] = []
    source_rank = 0
    with IfindMCPClient(token) as client:
        client.initialize()
        for trade_date in sorted(trade_dates):
            rows: list[dict] = []
            last_error: Exception | None = None
            attempt_count = max(1, attempts_per_day)
            for attempt in range(attempt_count):
                try:
                    result = client.call_tool("search_stocks", {"query": build_daily_limit_up_query(trade_date)})
                    rows = _candidates_from_result(client, result)
                    raw_payloads.append({"trade_date": trade_date.isoformat(), "result": result})
                    if rows:
                        break
                    last_error = MCPClientError(f"iFinD 返回空的 {trade_date.isoformat()} 涨停池")
                except MCPClientError as exc:
                    if "密钥" in str(exc):
                        raise
                    last_error = exc
                if attempt < attempt_count - 1:
                    time.sleep(3)
            if not rows:
                missing_dates.append(trade_date)
                logger.warning("[horseback] 涨停池 %s 重试 %d 次后仍失败：%s", trade_date.isoformat(), attempt_count, last_error)
                continue
            for row in rows:
                source_rank += 1
                symbol = row["ts_code"]
                count = max(1, row.get("limit_up_count") or 1)
                current = aggregate.get(symbol)
                if not current:
                    aggregate[symbol] = {
                        **row,
                        "source_rank": source_rank,
                        "limit_up_count": count,
                        "latest_limit_date": trade_date,
                        "raw": [{"trade_date": trade_date.isoformat(), "row": row["raw"]}],
                    }
                    continue
                current["limit_up_count"] += count
                current["latest_limit_date"] = max(current["latest_limit_date"], trade_date)
                current["raw"].append({"trade_date": trade_date.isoformat(), "row": row["raw"]})
                if not current.get("name") and row.get("name"):
                    current["name"] = row["name"]
    candidates = sorted(aggregate.values(), key=lambda item: (-item["limit_up_count"], item["ts_code"]))
    if missing_dates:
        missing = "、".join(item.isoformat() for item in missing_dates)
        raise MCPClientError(f"iFinD 涨停池不完整，缺失交易日：{missing}")
    if not candidates:
        raise MCPClientError("iFinD 没有返回可解析的沪深主板候选股")
    return candidates, raw_payloads


def _walk_payload(value):
    stack = [value]
    seen = set()
    while stack:
        current = stack.pop()
        marker = id(current)
        if isinstance(current, (dict, list)):
            if marker in seen:
                continue
            seen.add(marker)
        yield current
        if isinstance(current, dict):
            stack.extend(current.values())
        elif isinstance(current, list):
            stack.extend(current)
        elif isinstance(current, str):
            text = current.strip()
            if text[:1] in "[{":
                try:
                    stack.append(json.loads(text))
                except json.JSONDecodeError:
                    pass


def _table_rows_from_payload(payload):
    for node in _walk_payload(payload):
        if isinstance(node, dict):
            headers = node.get("headers") or node.get("columns")
            data = node.get("data")
            if isinstance(headers, list) and isinstance(data, list):
                for row in data:
                    if isinstance(row, (list, tuple)) and len(row) == len(headers):
                        yield dict(zip(headers, row))
        elif isinstance(node, list) and node and isinstance(node[0], (list, tuple)):
            headers = [str(value).strip() for value in node[0]]
            if not any(any(key.lower() in header.lower() for key in _CODE_KEYS) for header in headers):
                continue
            for row in node[1:]:
                if isinstance(row, (list, tuple)) and len(row) == len(headers):
                    yield dict(zip(headers, row))


def parse_realtime_quotes(payload) -> dict[str, dict]:
    """兼容 iFinD MCP 的嵌套 JSON、Markdown/表格响应，输出标准化行情快照。"""

    rows = list(_payload_rows(payload)) + list(_table_rows_from_payload(payload))
    quotes = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = normalize_symbol(_lookup_contains(row, _CODE_KEYS))
        price = _number(_lookup_contains(row, _PRICE_KEYS))
        if not symbol or price is None:
            continue
        quotes[symbol] = {
            "price": price,
            "change_pct": _number(_lookup_contains(row, _CHANGE_KEYS)),
            "open": _number(_lookup_contains(row, _OPEN_KEYS)),
            "high": _number(_lookup_contains(row, _HIGH_KEYS)),
            "low": _number(_lookup_contains(row, _LOW_KEYS)),
            "volume": _number(_lookup_contains(row, _VOLUME_KEYS)),
            "at": str(_lookup_contains(row, _TIME_KEYS) or "").strip(),
        }
    return quotes


def collect_realtime_quotes(token: str, symbols: list[str], batch_size: int = 10) -> tuple[dict[str, dict], list[object]]:
    """分批采集并标准化实时行情；调用节奏由客户端限制为每秒最多两次。"""

    unique_symbols = list(dict.fromkeys(symbols))
    if not unique_symbols:
        return {}, []
    quotes: dict[str, dict] = {}
    raw_payloads = []
    with IfindMCPClient(token) as client:
        client.initialize()
        for offset in range(0, len(unique_symbols), batch_size):
            batch = unique_symbols[offset:offset + batch_size]
            result = client.call_tool("stock_highfreq_quotes", {
                "symbols": ",".join(batch),
                "indicators": "最新价,涨跌幅,开盘价,最高价,最低价,成交量",
                "data_mode": "real_time",
            })
            raw_payloads.append(result)
            quotes.update(parse_realtime_quotes(result))
    return quotes, raw_payloads


def collect_limit_up_candidates(token: str, start_date: date, end_date: date) -> tuple[list[dict], object]:
    query = build_limit_up_query(start_date, end_date)
    with IfindMCPClient(token) as client:
        client.initialize()
        result = client.call_tool("search_stocks", {"query": query})
        candidates = parse_candidates(result)
        if not candidates:
            text = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            urls = re.findall(r"https://[^\s<>\]\[\"']+", text)
            for url in urls:
                if ".csv" not in url.lower():
                    continue
                candidates = parse_candidates(client.fetch_export(url.rstrip(".,)")))
                if candidates:
                    break
        if not candidates:
            raise MCPClientError("iFinD 没有返回可解析的沪深主板候选股")
        return candidates, result
