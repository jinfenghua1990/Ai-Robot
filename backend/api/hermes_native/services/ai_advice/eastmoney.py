"""东方财富妙想 AI 分析提供商"""

from api.hermes_native.services.ai_advice.base import BaseProvider, StockInfo, AnalysisReport, AnalysisSection


class EastMoneyProvider(BaseProvider):
    key = "eastmoney"
    name = "东方财富妙想"
    description = "基于东方财富权威数据库，综合行情、财务、资讯进行量化+基本面分析"
    version = "1.0.0"

    def analyze(self, stock: StockInfo) -> AnalysisReport:
        sections: list[AnalysisSection] = []
        label = f"{stock.name}({stock.code})" if stock.name else stock.code

        # 1. 行情数据
        quote_parts: list[str] = []
        try:
            from api.hermes_native.services.miaoxiang_service import query as mx_query, _parse_tables
            quote_result = mx_query(f"{label} 最新价 涨跌幅 换手率 量比 市盈率 市净率")
            quote_tables = _parse_tables(quote_result)
            if quote_tables:
                q = quote_tables[0]
                for field, cn in [
                    ("最新价", "最新价"), ("收盘价", "收盘价"), ("涨跌幅", "涨跌幅"),
                    ("换手率", "换手率"), ("量比", "量比"), ("市盈率", "市盈率"), ("市净率", "市净率"),
                ]:
                    if val := q.get(field, ""):
                        quote_parts.append(f"  {cn}: {val}")
        except Exception:
            pass

        if quote_parts:
            sections.append(AnalysisSection(
                title="行情数据",
                content="\n".join(quote_parts),
                style="default",
            ))

        # 2. 持仓评估
        if stock.price > 0 and stock.cost > 0:
            pct = stock.profit_pct
            status = "持有观察"
            style = "default"
            if pct > 10:
                status = "盈利良好，可考虑部分止盈"
                style = "positive"
            elif pct > 0:
                status = "小幅盈利，持有观察"
                style = "default"
            elif pct > -5:
                status = "小幅浮亏，耐心持有"
                style = "default"
            elif pct > -15:
                status = "明显浮亏，关注止损信号"
                style = "warning"
            else:
                status = "大幅亏损，严格止损纪律"
                style = "negative"

            sections.append(AnalysisSection(
                title="持仓评估",
                content=f"  当前价: {stock.price:.2f}元\n"
                        f"  成本价: {stock.cost:.2f}元\n"
                        f"  盈亏: {pct:+.2f}%\n"
                        f"  状态: {status}",
                style=style,
            ))

        # 3. 策略信号
        if stock.score > 0:
            score = stock.score
            if score >= 8:
                level, adv, style = "强信号", "该股被多个策略选中，信号质量高", "positive"
            elif score >= 6:
                level, adv, style = "中等信号", "信号可信度一般，需结合技术面判断", "default"
            elif score >= 3:
                level, adv, style = "弱信号", "策略信号偏弱，谨慎参与", "warning"
            else:
                level, adv, style = "极弱", "暂无明确策略信号", "negative"

            sections.append(AnalysisSection(
                title="策略信号",
                content=f"  综合评分: {score:.1f} ({level})\n"
                        f"  建议: {adv}",
                style=style,
            ))

        # 4. 最新资讯
        news_items: list[str] = []
        try:
            from api.hermes_native.services.miaoxiang_service import query as mx_query, _parse_tables
            news_result = mx_query(f"{label} 最新公告 新闻 3条")
            news_tables = _parse_tables(news_result)
            for i, n in enumerate(news_tables[:3], 1):
                title = n.get("entityName", n.get("标题", ""))
                if title and "(" not in title:
                    news_items.append(f"  {i}. {title}")
        except Exception:
            pass

        if news_items:
            sections.append(AnalysisSection(
                title="最新资讯",
                content="\n".join(news_items),
                style="highlight",
            ))

        # 5. 综合建议
        summary_parts: list[str] = []
        risk_flags: list[str] = []
        if stock.profit_pct < -10:
            risk_flags.append("浮亏超10%")
        if stock.score > 7:
            summary_parts.append("信号较强，可持有观察等待催化剂")
        elif stock.score > 4:
            summary_parts.append("信号中性，建议结合大盘环境和技术形态综合判断")
        else:
            summary_parts.append("信号偏弱，若无明确催化剂建议控制仓位")
        if risk_flags:
            summary_parts.append(f"⚠ 风险: {'、'.join(risk_flags)}")

        summary = "；".join(summary_parts) if summary_parts else "暂无明确信号"

        # 生成原始文本（兼容旧格式）
        raw_lines = [f"**{label} AI分析报告** (东方财富妙想)\n"]
        for s in sections:
            raw_lines.append(f"### {s.title}")
            raw_lines.append(s.content)
        raw_lines.append(f"\n### 综合建议\n{summary}\n*以上分析仅供参考，不构成投资建议*")

        return AnalysisReport(
            provider_key=self.key,
            provider_name=self.name,
            summary=summary,
            sections=sections,
            raw_text="\n".join(raw_lines),
        )