"""OpenClaw 技术分析提供商 — LLM 量化视角"""

from api.hermes_native.services.ai_advice.base import BaseProvider, StockInfo, AnalysisReport, AnalysisSection


class OpenClawProvider(BaseProvider):
    key = "openclaw"
    name = "OpenClaw"
    description = "技术面量化分析，侧重动量信号、量价关系、均线形态与支撑压力位"
    version = "1.0.0"

    def analyze(self, stock: StockInfo) -> AnalysisReport:
        from api.hermes_native.services.ai_advice.llm_engine import generate_analysis

        result = generate_analysis(
            provider_key="openclaw",
            code=stock.code,
            name=stock.name,
            price=stock.price,
            cost=stock.cost,
            profit_pct=stock.profit_pct,
            score=stock.score,
        )

        sections = [
            AnalysisSection(
                title=s.get("title", ""),
                content=s.get("content", ""),
                style=s.get("style", "default"),
            )
            for s in result.get("sections", [])
        ]

        label = f"{stock.name}({stock.code})" if stock.name else stock.code
        raw_lines = [f"**{label} 技术分析报告** (OpenClaw)\n"]
        for s in sections:
            raw_lines.append(f"### {s.title}")
            raw_lines.append(s.content)
        raw_lines.append(f"\n*OpenClaw 技术面分析仅供参考*")

        return AnalysisReport(
            provider_key=self.key,
            provider_name=self.name,
            summary=result.get("summary", ""),
            sections=sections,
            raw_text="\n".join(raw_lines),
        )
