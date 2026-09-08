"""研报中心 consumer：消费 analysis_requests 队列，生成报告落 PG

数据流：
  用户提交 request(pending)
    → analysis_consumer.process_pending() 轮询
    → 市场数据读 PG 已有盘后表（stock_features_daily / stock_daily_kline / stock_money_flow_detail）
    → F10(财务/评级/机构) 调 f10_provider 免费源拉取（Tushare 财务/机构 + 东方财富评级，结果缓存 PG；失败优雅降级为"—"）
    → 组装完整报告 dict → 写 analysis_reports + 改 request=completed + 写通知

这样：数据全部落 PG（多用户复用/可查询），且生成自动化（无需每次手动拉）。
"""
import json
import logging
from datetime import datetime, date
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

from sqlalchemy import select

from db.connection import SessionLocal
from db.models import (
    AnalysisRequest, AnalysisReport, StockFeaturesDaily,
    StockDailyKline, StockMoneyFlowDetail,
)
from services import f10_provider as f10

logger = logging.getLogger("analysis_consumer")


# ---------- 工具 ----------

def _to_ts_code(code: str) -> str:
    """纯数字代码 → tushare 风格 ts_code（002245 -> 002245.SZ）。"""
    c = code.strip()
    if "." in c:
        return c
    if c[0] in ("6", "9") or (c.startswith("688")):
        return f"{c}.SH"
    if c.startswith("8") or c.startswith("4"):
        return f"{c}.BJ"
    return f"{c}.SZ"


def _yuan_to_yi(v) -> Optional[float]:
    try:
        return float(v) / 1e8
    except (TypeError, ValueError):
        return None


def _fmt_yi(v, sign=True) -> str:
    x = _yuan_to_yi(v)
    if x is None:
        return "—"
    return (f"{x:+.2f}亿" if sign else f"{x:.2f}亿")


def _mmdd(d) -> str:
    if isinstance(d, (datetime, date)):
        return d.strftime("%m-%d")
    s = str(d)
    return f"{s[4:6]}-{s[6:8]}" if len(s) >= 8 else s


# ---------- 报告组装（来自 PG）----------

def build_report_from_pg(stock_code: str, stock_name: str = "", source: str = "tdx") -> Dict[str, Any]:
    code = stock_code.strip()
    ts_code = _to_ts_code(code)
    name = stock_name or code

    with SessionLocal() as db:
        feat = db.execute(
            select(StockFeaturesDaily).where(StockFeaturesDaily.stock_code == code)
            .order_by(StockFeaturesDaily.trade_date.desc()).limit(1)
        ).scalars().first()

        klines = db.execute(
            select(StockDailyKline).where(StockDailyKline.ts_code == ts_code)
            .order_by(StockDailyKline.trade_date.desc()).limit(60)
        ).scalars().all()
        klines = list(reversed(klines))  # 升序，便于区间计算

        flows = db.execute(
            select(StockMoneyFlowDetail).where(StockMoneyFlowDetail.ts_code == ts_code)
            .order_by(StockMoneyFlowDetail.trade_date.desc()).limit(15)
        ).scalars().all()
        flows = list(reversed(flows))  # 升序

    if not feat and not klines:
        raise ValueError(f"PG 中无 {code} 的市场数据（可能未纳入每日采集）")

    # --- 行情 ---
    last_k = klines[-1] if klines else None
    price = float(feat.close) if feat and feat.close is not None else (float(last_k.close) if last_k else 0)
    change_pct = float(last_k.pct_chg) if last_k and last_k.pct_chg is not None else 0.0
    high = float(last_k.high) if last_k else price
    low = float(last_k.low) if last_k else price
    vol = int(last_k.volume) if last_k and last_k.volume else 0
    amount = float(last_k.amount) if last_k and last_k.amount else 0.0
    quotes = {
        "price": round(price, 2),
        "change_pct": round(change_pct, 2),
        "high": round(high, 2),
        "low": round(low, 2),
        "volume": f"{vol/1e4:.0f}万手" if vol else "—",
        "amount": f"{amount/1e8:.2f}亿" if amount else "—",
        "turnover_rate": round(float(feat_high_turnover(flows)), 2) if flows else 0.0,
    }

    # --- K线区间 ---
    closes = [float(k.close) for k in klines if k.close is not None]
    highs = [float(k.high) for k in klines if k.high is not None]
    lows = [float(k.low) for k in klines if k.low is not None]
    period_label = f"{len(klines)}日" if klines else "—"
    kline_analysis = {
        "period": period_label,
        "change_pct": round((closes[-1] / closes[0] - 1) * 100, 2) if len(closes) >= 2 and closes[0] else 0.0,
        "high_60d": round(max(highs), 2) if highs else 0.0,
        "low_60d": round(min(lows), 2) if lows else 0.0,
        "ma_status": _ma_status(feat, price),
        "support": "—",
        "resistance": "—",
    }

    # --- 技术 ---
    technical = {
        "rsi": round(float(feat.rsi_14), 2) if feat and feat.rsi_14 is not None else "—",
        "macd": "—（PG 未存）",
        "kdj": "—（PG 未存）",
        "boll": "—",
        "ma5": round(float(feat.ma5), 2) if feat and feat.ma5 is not None else "—",
        "ma10": "—",
        "ma20": round(float(feat.ma20), 2) if feat and feat.ma20 is not None else "—",
        "ma60": round(float(feat.ma60), 2) if feat and feat.ma60 is not None else "—",
        "volume_ratio": round(float(feat.volume_ratio), 2) if feat and feat.volume_ratio is not None else "—",
        "summary": _tech_summary(feat, price),
    }

    # --- 资金流 ---
    money_flow = _build_money_flow(flows, klines)

    # --- 估值（基于 PG 行情 + 尝试 F10）---
    valuation = {
        "pe_ttm": "—", "pe_percentile_5y": "—", "pb": "—",
        "pb_percentile_5y": "—", "peg": "—",
        "industry_avg_pe": "—", "industry_avg_pb": "—",
        "assessment": "估值字段需 F10 财务数据；当前仅含 PG 盘后市场数据。",
    }
    financials = {
        "eps": "—", "bps": "—", "pe": "—", "pb": "—",
        "total_shares": "—", "market_cap": "—",
        "revenue": "—", "net_profit": "—", "roe": "—", "gross_margin": "—",
    }
    institutional = {
        "fund_count": "—", "fund_holding_ratio": "—",
        "fund_change_quarter": "—", "north_bound": "—", "north_bound_5d": "—",
    }
    target_price_val = None
    # --- F10 免费源 enrichment（Tushare 财务/机构 + 东方财富评级，缓存 PG；优雅降级）---
    if f10.is_configured():
        fin = f10.get_financials(code)
        if fin:
            financials["revenue"] = _as_str(fin.get("revenue"))
            financials["net_profit"] = _as_str(fin.get("net_profit"))
            financials["eps"] = _as_str(fin.get("eps"))
            financials["roe"] = _as_str(fin.get("roe"))
            financials["gross_margin"] = _as_str(fin.get("gross_margin"))
            # TTM PE / PB 直接用 Tushare daily_basic（免费且准确）
            pe = fin.get("pe_ttm")
            pb = fin.get("pb")
            if pe is not None:
                try:
                    financials["pe"] = f"{float(pe):.2f}"
                    valuation["pe_ttm"] = round(float(pe), 2)
                except Exception:
                    logger.debug("target_price format failed", exc_info=False)
            if pb is not None:
                try:
                    financials["pb"] = f"{float(pb):.2f}"
                except Exception:
                    logger.debug("PB format failed", exc_info=False)
            valuation["assessment"] = (
                f"TTM PE≈{valuation.get('pe_ttm')}，PB≈{financials.get('pb')}；"
                f"ROE {_as_str(fin.get('roe'))}，毛利率 {_as_str(fin.get('gross_margin'))}（数据来源 Tushare）。"
            )
        rat = f10.get_rating(code)
        if rat:
            tp = rat.get("target_price")
            if tp:
                try:
                    target_price_val = float(str(tp).replace(",", "").replace("元", "").strip())
                except Exception:
                    target_price_val = None
            if rat.get("rating_name"):
                valuation["assessment"] = (
                    f"券商评级「{rat.get('rating_name')}」，一致目标价 {_as_str(rat.get('target_price'))}；"
                    f"PE(TTM)≈{valuation.get('pe_ttm') if valuation.get('pe_ttm') != '—' else '—'}。"
                )
        inst = f10.get_institutional(code)
        if isinstance(inst, dict):
            institutional["fund_holding_ratio"] = _as_str(
                inst.get("持仓占实际流通A股比例") or inst.get("持仓比例")
            )
            institutional["fund_count"] = _as_str(inst.get("机构数量"))

    # --- 评级（透明规则）---
    rating, confidence, rating_note = _derive_rating(price, target_price_val, feat)
    if not f10.is_configured():
        rating_note = "免费 F10 源（Tushare/东方财富）未配置，评级为 PG 市场数据驱动的初步判断，仅供参考。"

    summary = {
        "rating": rating,
        "target_price": (f"{target_price_val:.2f}（券商一致预期）" if target_price_val else "—"),
        "confidence": confidence,
        "key_points": _key_points(price, change_pct, kline_analysis, money_flow, feat, rating_note),
    }

    report = {
        "stock_code": code,
        "stock_name": name,
        "source": source,
        "created_at": datetime.now().isoformat(),
        "report_type": "个股分析（PG盘后数据自动生成）",
        "summary": summary,
        "quotes": quotes,
        "kline_analysis": kline_analysis,
        "financials": financials,
        "sector": {"name": "—", "rank_in_sector": "—", "sector_change_pct": "—", "sector_heat": "—", "sector_main_net": "—"},
        "money_flow": money_flow,
        "technical": technical,
        "valuation": valuation,
        "institutional": institutional,
        "bull_case": _bull_case(feat, money_flow, target_price_val, price),
        "bear_case": _bear_case(feat, kline_analysis, target_price_val, price),
        "risk_factors": [
            "PG 盘后数据 T+1 延迟：盘中/当日实时变动不反映在此报告",
            "F10 财务/评级未补全时，估值与评级仅为初步判断",
            "概念/行业分类需结合 F10 补全，当前行业字段为占位",
            "市场有风险，本报告由数据自动生成，不构成投资建议",
        ],
        "disclaimer": "本报告基于 PostgreSQL 盘后数据自动生成（市场数据），F10 财务/机构来自 Tushare、评级/目标价来自东方财富公开接口并缓存入 PG；仅供参考，不构成个人投资建议",
    }
    return report


def feat_high_turnover(flows):
    return float(flows[-1].turnover_rate) if flows and flows[-1].turnover_rate is not None else 0.0


def _ma_status(feat, price):
    if not feat:
        return "—"
    parts = []
    for label, val in [("MA5", feat.ma5), ("MA20", feat.ma20), ("MA60", feat.ma60)]:
        if val is not None:
            parts.append(f"{label}={val:.2f}")
    if not parts:
        return "—"
    above = price > max([v for v in [feat.ma5, feat.ma20, feat.ma60] if v is not None])
    trend = "站上" if above else "低于"
    return f"现价{price:.2f}{trend}短期均线（{', '.join(parts)}）"


def _tech_summary(feat, price):
    if not feat:
        return "无技术特征数据"
    bits = []
    if feat.rsi_14 is not None:
        rsi = feat.rsi_14
        zone = "超买" if rsi > 70 else ("超卖" if rsi < 30 else "中位偏强" if rsi > 50 else "中位偏弱")
        bits.append(f"RSI(14)={rsi:.1f}（{zone}）")
    if feat.ma5 is not None and feat.ma20 is not None:
        bits.append("MA5/MA20 " + ("多头排列" if feat.ma5 > feat.ma20 else "空头排列"))
    if feat.volume_ratio is not None:
        bits.append(f"量比{feat.volume_ratio:.2f}")
    if feat.market_state:
        bits.append(f"状态={feat.market_state}")
    return "；".join(bits) if bits else "技术特征数据不足"


def _build_money_flow(flows, klines):
    # 日期 -> 涨跌幅（来自 kline）
    pct_map = {}
    for k in klines:
        d = k.trade_date
        key = d.strftime("%Y%m%d") if isinstance(d, (datetime, date)) else str(d)
        pct_map[key] = float(k.pct_chg) if k.pct_chg is not None else 0.0

    trend = []
    for f in flows[-10:]:
        d = f.trade_date
        ds = d.strftime("%Y%m%d") if isinstance(d, (datetime, date)) else str(d)
        chg = pct_map.get(ds, 0.0)
        main = _yuan_to_yi(f.main_net)
        status = "流入" if (main or 0) > 0 else "流出"
        trend.append({
            "date": _mmdd(d),
            "main_net": _fmt_yi(f.main_net),
            "change": f"{chg:+.2f}%",
            "status": status,
        })

    def sum_n(n):
        sub = flows[-n:] if n <= len(flows) else flows
        return sum(float(x.main_net) for x in sub if x.main_net is not None)

    period_stats = {
        "1日": _fmt_yi(sum_n(1)),
        "3日": _fmt_yi(sum_n(3)),
        "5日": _fmt_yi(sum_n(5)),
        "10日": _fmt_yi(sum_n(10)),
    }
    today = flows[-1] if flows else None
    today_main = _yuan_to_yi(today.main_net) if today else None
    return {
        "today": {
            "main_net": _fmt_yi(today.main_net) if today else "—",
            "super_large": _fmt_yi(today.super_large_net) if today else "—",
            "large": _fmt_yi(today.large_net) if today else "—",
            "medium": _fmt_yi(today.medium_net) if today else "—",
            "small": _fmt_yi(today.small_net) if today else "—",
            "main_ratio": "—",
            "status": "主力净流入" if (today_main or 0) > 0 else "主力净流出",
        },
        "trend": trend,
        "period_stats": period_stats,
    }


def _derive_rating(price, target_price_val, feat):
    if target_price_val is not None and price > 0:
        if target_price_val > price * 1.10:
            return "买入", "中", f"券商目标价{target_price_val:.2f}较现价{price:.2f}高>10%"
        if target_price_val < price * 0.95:
            return "卖出", "中", f"券商目标价{target_price_val:.2f}较现价{price:.2f}低>5%"
        return "持有", "中", f"券商目标价{target_price_val:.2f}与现价{price:.2f}接近"
    # 无 F10：基于 PG 趋势的初步判断
    if feat and feat.ma5 is not None and feat.ma20 is not None:
        if price > feat.ma20 and (feat.main_net_inflow_5d or 0) > 0:
            return "持有", "低", "站上MA20且5日主力净流入为正（初步）"
        if price < feat.ma20:
            return "持有", "低", "跌破MA20（初步，偏谨慎）"
    return "持有", "低", "市场数据驱动的初步判断"


def _as_str(v):
    if v is None:
        return "—"
    return str(v)


def _key_points(price, change_pct, kline, money_flow, feat, rating_note):
    pts = [
        f"现价{price:.2f}（{change_pct:+.2f}%），60日区间{float(kline.get('change_pct',0)):+.2f}%（低{float(kline.get('low_60d',0))}→高{float(kline.get('high_60d',0))}）",
    ]
    mf10 = money_flow.get("period_stats", {}).get("10日", "—")
    pts.append(f"近10日主力净流入：{mf10}（PG stock_money_flow_detail）")
    if feat and feat.rsi_14 is not None:
        pts.append(f"RSI(14)={feat.rsi_14:.1f}，{_tech_summary(feat, price)}")
    pts.append(rating_note)
    return pts


def _bull_case(feat, money_flow, target_price_val, price):
    cases = []
    mf10 = money_flow.get("period_stats", {}).get("10日", "—")
    if "亿" in str(mf10) and not str(mf10).startswith("-"):
        cases.append(f"资金面偏强：近10日主力净流入{mf10}")
    if feat and feat.ma5 is not None and feat.ma20 is not None and feat.ma5 > feat.ma20:
        cases.append("技术多头：MA5 站上 MA20，短期趋势向上")
    if target_price_val and price and target_price_val > price:
        cases.append(f"估值空间：券商一致目标价{target_price_val:.2f}高于现价{price:.2f}")
    if not cases:
        cases.append("PG 盘后市场数据完整，可结合 F10 补全后进一步判断")
    return cases


def _bear_case(feat, kline, target_price_val, price):
    cases = []
    mf10 = kline.get("change_pct", 0)
    if isinstance(mf10, (int, float)) and mf10 > 40:
        cases.append(f"短期涨幅大：60日已涨{mf10:.1f}%，追高回撤风险")
    if feat and feat.ma5 is not None and feat.ma20 is not None and feat.ma5 < feat.ma20:
        cases.append("技术偏弱：MA5 跌破 MA20")
    if not f10.is_configured():
        cases.append("F10 财务/评级未补全，估值安全边际无法评估")
    if not cases:
        cases.append("需 F10 补全以评估盈利质量与估值风险")
    return cases


# ---------- 队列消费 ----------

def process_request(rid: str) -> bool:
    """处理单个请求：生成报告→落库→改状态。返回是否成功。"""
    with SessionLocal() as db:
        req = db.get(AnalysisRequest, rid)
        if not req or req.status in ("completed", "processing"):
            return False
        req.status = "processing"
        req.updated_at = datetime.now()
        db.commit()
        try:
            report = build_report_from_pg(req.stock_code, req.stock_name, req.source)
            report["id"] = rid
            rep = AnalysisReport(
                id=rid,
                stock_code=req.stock_code,
                stock_name=req.stock_name,
                source=req.source,
                report_type=report.get("report_type", ""),
                rating=report.get("summary", {}).get("rating", ""),
                target_price=str(report.get("summary", {}).get("target_price", "")),
                confidence=report.get("summary", {}).get("confidence", ""),
                report_json=json.dumps(report, ensure_ascii=False),
            )
            db.merge(rep)
            # 通知
            from db.models import Notification
            notif = Notification(
                id=f"notif_{rid}",
                source=req.source,
                stock_code=req.stock_code,
                stock_name=req.stock_name,
                title=f"{req.stock_name}({req.stock_code}) 个股分析报告",
                read=False,
                created_at=datetime.now(),
            )
            db.merge(notif)
            req.status = "completed"
            req.updated_at = datetime.now()
            db.commit()
            logger.info("[analysis_consumer] 完成 %s %s", rid, req.stock_code)
            return True
        except Exception as e:
            db.rollback()
            req.status = "failed"
            req.error = str(e)[:500]
            req.updated_at = datetime.now()
            db.commit()
            logger.exception("[analysis_consumer] 失败 %s: %s", rid, e)
            return False


def process_pending(limit: int = 20) -> int:
    """轮询并处理 pending 请求，返回处理数量。"""
    with SessionLocal() as db:
        rows = db.execute(
            select(AnalysisRequest).where(AnalysisRequest.status == "pending")
            .order_by(AnalysisRequest.created_at.asc()).limit(limit)
        ).scalars().all()
        pending_ids = [r.id for r in rows]
    done = 0
    for rid in pending_ids:
        try:
            if process_request(rid):
                done += 1
        except Exception as e:
            logger.warning("[analysis_consumer] process %s error: %s", rid, e)
    return done
