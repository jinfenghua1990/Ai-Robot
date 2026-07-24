"""国信证券 AI 分析提供商 — LLM 投研视角"""

from api.hermes_native.services.ai_advice.base import BaseProvider, StockInfo, AnalysisReport, AnalysisSection


class GuoxinProvider(BaseProvider):
    key = "guoxin"
    name = "国信证券"
    description = "国信证券专业投研视角，侧重基本面估值与行业对比分析"
    version = "1.0.0"

    def analyze(self, stock: StockInfo) -> AnalysisReport:
        from api.hermes_native.services.ai_advice.llm_engine import generate_analysis

        result = generate_analysis(
            provider_key="guoxin",
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
        raw_lines = [f"**{label} 投研分析报告** (国信证券)\n"]
        for s in sections:
            raw_lines.append(f"### {s.title}")
            raw_lines.append(s.content)
        raw_lines.append(f"\n*以上分析仅供参考，不构成投资建议*")

        return AnalysisReport(
            provider_key=self.key,
            provider_name=self.name,
            summary=result.get("summary", ""),
            sections=sections,
            raw_text="\n".join(raw_lines),
        )
