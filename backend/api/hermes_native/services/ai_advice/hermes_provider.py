"""Hermes AI 综合分析提供商 — LLM + robot-6 白虎策略视角"""

from api.hermes_native.services.ai_advice.base import BaseProvider, StockInfo, AnalysisReport, AnalysisSection


class HermesProvider(BaseProvider):
    key = "hermes"
    name = "Hermes AI"
    description = "AI 综合分析视角，融合市场情绪、风险量化、资金博弈与择时策略"
    version = "1.0.0"

    def analyze(self, stock: StockInfo) -> AnalysisReport:
        from api.hermes_native.services.ai_advice.llm_engine import generate_analysis

        result = generate_analysis(
            provider_key="hermes",
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
        raw_lines = [f"**{label} AI 综合分析报告** (Hermes AI)\n"]
        for s in sections:
            raw_lines.append(f"### {s.title}")
            raw_lines.append(s.content)
        raw_lines.append(f"\n*Hermes AI 分析仅供参考，不构成投资建议*")

        return AnalysisReport(
            provider_key=self.key,
            provider_name=self.name,
            summary=result.get("summary", ""),
            sections=sections,
            raw_text="\n".join(raw_lines),
        )
