"""
LLM 分析引擎 — 通过 DeepSeek API 为不同提供商生成差异化分析报告
"""

from __future__ import annotations

import json
import os
from typing import Any

import requests

# LLM Gateway 配置
_LLM_BASE_URL = "http://127.0.0.1:8001/v1"
_LLM_MODEL = "auto"


def _api_key() -> str:
    return os.getenv(
        "LLM_API_KEY",
        "88ba6601ea2dbec56fc0ca38a86bfa6f",
    )


def call_llm(system_prompt: str, user_prompt: str, *, max_tokens: int = 2000, temperature: float = 0.7) -> str:
    """调用 DeepSeek chat completions API"""
    headers = {
        "Authorization": f"Bearer {_api_key()}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": os.getenv("LLM_MODEL", _LLM_MODEL),
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }
    resp = requests.post(
        f"{os.getenv('LLM_BASE_URL', _LLM_BASE_URL)}/chat/completions",
        headers=headers,
        json=payload,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _fetch_stock_data(label: str) -> dict[str, str]:
    """从妙想 API 采集个股基础数据，作为 LLM 分析上下文"""
    context: dict[str, str] = {}
    try:
        from api.hermes_native.services.miaoxiang_service import query as mx_query, _parse_tables

        # 行情快照
        q = mx_query(f"{label} 最新价 涨跌幅 换手率 量比 市盈率 市净率 总市值 成交额")
        tables = _parse_tables(q)
        if tables:
            parts = []
            for k, v in tables[0].items():
                if k not in ("code", "name") and v:
                    parts.append(f"{k}: {v}")
            context["行情"] = "；".join(parts)

        # 资金流向
        f = mx_query(f"{label} 主力资金净流入 超大单 大单 散户")
        ft = _parse_tables(f)
        if ft:
            parts = []
            for k, v in ft[0].items():
                if k not in ("code", "name") and v:
                    parts.append(f"{k}: {v}")
            context["资金流向"] = "；".join(parts)

        # 新闻/公告
        n = mx_query(f"{label} 最新公告 新闻 3条")
        nt = _parse_tables(n)
        news_items = []
        for item in nt[:3]:
            title = item.get("entityName", item.get("标题", ""))
            if title and "(" not in title:
                news_items.append(title)
        if news_items:
            context["近期资讯"] = "；".join(news_items)

    except Exception:
        pass
    return context


def generate_analysis(
    provider_key: str,
    code: str,
    name: str = "",
    price: float = 0,
    cost: float = 0,
    profit_pct: float = 0,
    score: float = 0,
) -> dict[str, Any]:
    """
    为指定提供商生成 LLM 分析。
    返回 {"summary": str, "sections": [{"title", "content", "style"}]}
    """
    label = f"{name}({code})" if name else code

    # 采集数据上下文
    data_ctx = _fetch_stock_data(label)
    data_text = "\n".join(f"- {k}: {v}" for k, v in data_ctx.items()) if data_ctx else "暂无实时数据"

    # 持仓信息
    holding_text = ""
    if price > 0 and cost > 0:
        holding_text = f"\n持仓信息: 当前价 {price}元, 成本价 {cost}元, 盈亏 {profit_pct:+.2f}%"

    # 策略信号
    signal_text = ""
    if score > 0:
        signal_text = f"\n策略综合评分: {score}/10"

    base_info = f"股票: {label}\n\n实时数据:\n{data_text}{holding_text}{signal_text}"

    # 各提供商的差异化 prompt
    prompts = _get_prompts(provider_key, name or code)

    try:
        raw = call_llm(
            system_prompt=prompts["system"],
            user_prompt=f"{base_info}\n\n{prompts['user']}",
            max_tokens=prompts.get("max_tokens", 1500),
            temperature=prompts.get("temperature", 0.7),
        )
    except Exception as exc:
        return {
            "summary": f"{prompts['display_name']} 分析暂时不可用",
            "sections": [{"title": "错误", "content": str(exc), "style": "negative"}],
        }

    # 解析 LLM 返回的 JSON 结构
    sections = _parse_llm_response(raw, prompts["display_name"])
    summary = sections[0]["content"][:80] if sections else "分析完成"

    return {"summary": summary, "sections": sections, "raw_text": raw}


def _get_prompts(provider_key: str, stock_label: str) -> dict[str, Any]:
    """返回各提供商的差异化 prompt"""

    if provider_key == "guoxin":
        return {
            "display_name": "国信证券",
            "system": (
                "你是国信证券研究所的资深分析师。你的分析风格：\n"
                "- 侧重基本面估值：PE/PB/DCF模型、盈利预测、目标价区间\n"
                "- 行业对比：同行业对标分析、市场份额、竞争格局\n"
                "- 研报风格：引用数据和逻辑推导，语言专业严谨\n"
                "- 关注机构持仓变化、研报评级、一致预期\n"
                "- 语气：机构投研报告风格，客观理性"
            ),
            "user": (
                f"请对 {stock_label} 出具一份国信证券风格的投研分析报告。\n"
                "严格按以下JSON格式输出（不要其他内容）：\n"
                '{"sections": ['
                '{"title": "估值分析", "content": "...", "style": "default"},'
                '{"title": "行业对标", "content": "...", "style": "default"},'
                '{"title": "机构观点", "content": "...", "style": "highlight"},'
                '{"title": "投资建议", "content": "...", "style": "positive或warning或negative"}'
                ']}\n'
                "style 可选: default, positive, warning, negative, highlight"
            ),
            "max_tokens": 1500,
            "temperature": 0.5,
        }

    elif provider_key == "openclaw":
        return {
            "display_name": "OpenClaw",
            "system": (
                "你是 OpenClaw 量化技术分析引擎。你的分析风格：\n"
                "- 纯技术面视角：均线系统(MA5/10/20/60)、MACD、RSI、布林带\n"
                "- 量价关系：放量/缩量形态、量价背离检测、换手率分析\n"
                "- 动量信号：趋势强度、突破确认、支撑压力位\n"
                "- 资金博弈：主力净流入、大单动向、筹码分布\n"
                "- 语气：量化系统输出风格，数据驱动，结论明确"
            ),
            "user": (
                f"请对 {stock_label} 进行 OpenClaw 技术面量化分析。\n"
                "严格按以下JSON格式输出（不要其他内容）：\n"
                '{"sections": ['
                '{"title": "技术面快照", "content": "...", "style": "default"},'
                '{"title": "量价分析", "content": "...", "style": "highlight"},'
                '{"title": "动量评估", "content": "...", "style": "positive或warning或negative"},'
                '{"title": "关键位", "content": "...", "style": "default"},'
                '{"title": "操作信号", "content": "...", "style": "positive或warning或negative"}'
                ']}\n'
                "style 可选: default, positive, warning, negative, highlight"
            ),
            "max_tokens": 1500,
            "temperature": 0.3,
        }

    elif provider_key == "hermes":
        return {
            "display_name": "Hermes AI",
            "system": (
                "你是 Hermes AI 智能投研助手（robot-6 白虎策略核心）。你的分析风格：\n"
                "- 综合视角：融合技术面+基本面+情绪面+资金面四维分析\n"
                "- 市场情绪：板块联动、题材热度、涨停生态\n"
                "- 风险量化：波动率评估、回撤风险、止损位计算\n"
                "- 择时策略：结合大盘环境和个股阶段给出仓位建议\n"
                "- 语气：AI助手风格，通俗易懂，重点突出，有明确操作建议"
            ),
            "user": (
                f"请对 {stock_label} 进行 Hermes AI 综合投研分析。\n"
                "严格按以下JSON格式输出（不要其他内容）：\n"
                '{"sections": ['
                '{"title": "多维画像", "content": "...", "style": "default"},'
                '{"title": "情绪与板块", "content": "...", "style": "highlight"},'
                '{"title": "风险评估", "content": "...", "style": "warning或negative或default"},'
                '{"title": "资金博弈", "content": "...", "style": "highlight"},'
                '{"title": "Hermes择时", "content": "...", "style": "positive或warning或negative"}'
                ']}\n'
                "style 可选: default, positive, warning, negative, highlight"
            ),
            "max_tokens": 1800,
            "temperature": 0.7,
        }

    else:
        # 通用 fallback
        return {
            "display_name": provider_key,
            "system": "你是一个专业的股票分析师，请给出全面的个股分析。",
            "user": f"请分析 {stock_label}，用JSON格式输出 sections 数组。",
            "max_tokens": 1200,
            "temperature": 0.7,
        }


def _parse_llm_response(raw: str, provider_name: str) -> list[dict]:
    """解析 LLM 返回的 JSON 结构"""
    # 尝试直接解析
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "sections" in data:
            return data["sections"]
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 块
    import re
    json_match = re.search(r'\{[^{}]*"sections"\s*:\s*\[.*?\]\s*\}', raw, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group())
            if "sections" in data:
                return data["sections"]
        except json.JSONDecodeError:
            pass

    # Fallback: 把原始文本作为单 section 返回
    return [{"title": f"{provider_name} 分析", "content": raw, "style": "default"}]
