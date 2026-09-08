"""
盘后综合日报生成器（本地库驱动）

- 数据源：本地 PostgreSQL (airobot)，全部为已落库的结构化数据
- 产出：自包含 HTML 报告（Chart.js CDN），落盘 reports/daily/<date>.html
- 可在 FastAPI 应用内（api/report.py）调用，也可独立 python 运行

报告结构：
  1. 盘面速览（涨跌家数 / 均价 / 主力净流入合计）
  2. 涨停 / 强势股榜（price_chg>=9，叠加龙头生命周期阶段）
  3. 板块轮动（行业 + 概念资金净流入 Top）
  4. 龙头生命周期活跃个股
  5. 个股研究摘要（当日新采集的妙想资讯 / AI 分析）
  6. 次日买卖参考清单（多信号交叉打分 Top N）
  7. 数据质量异常
"""
import os
import sys
import json
import logging
from datetime import datetime, date

# 允许独立运行：把 backend 根目录加入 sys.path（app 内 import 时本就在路径中，无害）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text

logger = logging.getLogger("daily_report")

REPORT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "daily")
ACTIVE_STAGES = ("主升", "加速", "启动")


def _fnum(v, nd=2):
    """None / NaN 安全转 float"""
    try:
        if v is None:
            return 0.0
        return round(float(v), nd)
    except (TypeError, ValueError):
        return 0.0


def _latest_trade_date(db):
    row = db.execute(text("SELECT max(trade_date) FROM stock_flow")).scalar()
    return row.strftime("%Y-%m-%d") if row else None


# ---------- 取数 ----------
def fetch_overview(db, d):
    sql = text("""
        SELECT
          sum(CASE WHEN price_chg > 0 THEN 1 ELSE 0 END) AS up,
          sum(CASE WHEN price_chg < 0 THEN 1 ELSE 0 END) AS dn,
          sum(CASE WHEN price_chg = 0 THEN 1 ELSE 0 END) AS eq,
          round(avg(price_chg)::numeric, 2) AS avg_chg,
          round(sum(main_force_inflow)::numeric / 1e8, 1) AS main_net_yi,
          count(*) AS total
        FROM stock_flow WHERE trade_date = :d
    """)
    r = db.execute(sql, {"d": d}).mappings().first()
    return dict(r) if r else {}


def fetch_limit_up(db, d, threshold=9.0, lim=30):
    sql = text("""
        SELECT sf.ts_code, sf.name, sf.sector, sf.price,
               sf.price_chg,
               round(sf.main_force_inflow::numeric / 1e8, 2) AS main_net_yi,
               ll.stage, ll.strength, ll.consecutive_days
        FROM stock_flow sf
        LEFT JOIN leader_lifecycle ll
          ON ll.ts_code = sf.ts_code AND ll.trade_date = :d
        WHERE sf.trade_date = :d AND sf.price_chg >= :th
        ORDER BY sf.price_chg DESC, sf.main_force_inflow DESC
        LIMIT :lim
    """)
    return [dict(r) for r in db.execute(sql, {"d": d, "th": threshold, "lim": lim}).mappings().all()]


def fetch_sector_flow(db, d, lim=15):
    sql = text("""
        SELECT sector,
               round(net_flow::numeric / 1e4, 1) AS net_flow_yi,
               round(avg_chg::numeric, 2) AS avg_chg,
               rise_ratio, limit_up_count, heat_score
        FROM sector_flow WHERE trade_date = :d
        ORDER BY net_flow DESC LIMIT :lim
    """)
    return [dict(r) for r in db.execute(sql, {"d": d, "lim": lim}).mappings().all()]


def fetch_concept_flow(db, d, lim=15):
    sql = text("""
        SELECT concept_name,
               round(net_flow::numeric / 1e4, 1) AS net_flow_yi,
               round(avg_chg::numeric, 2) AS avg_chg,
               rise_ratio, limit_up_count, heat_score
        FROM concept_sector_flow WHERE trade_date = :d
        ORDER BY net_flow DESC LIMIT :lim
    """)
    return [dict(r) for r in db.execute(sql, {"d": d, "lim": lim}).mappings().all()]


def fetch_leaders(db, d, lim=25):
    sql = text("""
        SELECT ts_code, name, sector, stage, strength, change_rate, consecutive_days
        FROM leader_lifecycle
        WHERE trade_date = :d AND stage IN ('加速', '主升', '启动')
        ORDER BY (CASE stage WHEN '主升' THEN 3 WHEN '加速' THEN 2 ELSE 1 END) DESC,
                 strength DESC
        LIMIT :lim
    """)
    return [dict(r) for r in db.execute(sql, {"d": d, "lim": lim}).mappings().all()]


def fetch_research(db, d, lim=14):
    """当日研究沉淀（AI 分析 + 妙想资讯），并关联龙头生命周期（连续活跃/阶段），
    便于日报直接呈现"连续强势 + 新增催化"的操作线索。"""
    sql = text("""
        WITH rs AS (
            SELECT stock_code, NULL AS stock_name, analysis_type AS typ, model,
                   left(analysis_data::text, 500) AS snippet, created_at, 'ai' AS src
            FROM ai_analysis_cache WHERE created_at::date = :d
            UNION ALL
            SELECT stock_code, stock_name, query_keyword AS typ, 'mx-search' AS model,
                   left(result_summary, 500) AS snippet, search_time AS created_at, 'news' AS src
            FROM stock_news_search WHERE search_time::date = :d
        )
        SELECT rs.stock_code, rs.stock_name, rs.typ, rs.model, rs.snippet, rs.created_at, rs.src,
               ll.stage, ll.consecutive_days, ll.strength
        FROM rs
        LEFT JOIN leader_lifecycle ll ON ll.ts_code = rs.stock_code AND ll.trade_date = :d
        ORDER BY rs.created_at DESC
    """)
    rows = [dict(r) for r in db.execute(sql, {"d": d}).mappings().all()]
    # 按 (stock_code, src) 去重，保留最新一条
    seen, dedup = set(), []
    for r in rows:
        key = (r.get("stock_code"), r.get("src"))
        if key in seen:
            continue
        seen.add(key)
        dedup.append(r)
    return dedup[:lim]


def fetch_nextday_plan(db, d, lim=20):
    """多信号交叉打分：龙头活跃 ∪ 当日强势(>=5%) ，综合价格/资金/阶段/研究"""
    sql = text("""
        WITH pool AS (
            SELECT ts_code, name FROM leader_lifecycle
            WHERE trade_date = :d AND stage IN ('加速', '主升', '启动')
            UNION
            SELECT ts_code, name FROM stock_flow
            WHERE trade_date = :d AND price_chg >= 5
        )
        SELECT p.ts_code, p.name,
               sf.price, sf.price_chg,
               round(sf.main_force_inflow::numeric / 1e8, 2) AS main_net_yi,
               ll.stage, ll.strength, ll.consecutive_days,
               (SELECT count(*) FROM ai_analysis_cache a WHERE a.stock_code = p.ts_code) AS has_ai,
               (SELECT count(*) FROM stock_news_search n WHERE n.stock_code = p.ts_code) AS has_news
        FROM pool p
        LEFT JOIN stock_flow sf ON sf.ts_code = p.ts_code AND sf.trade_date = :d
        LEFT JOIN leader_lifecycle ll ON ll.ts_code = p.ts_code AND ll.trade_date = :d
    """)
    rows = [dict(r) for r in db.execute(sql, {"d": d}).mappings().all()]
    scored = []
    for r in rows:
        pc = _fnum(r.get("price_chg"), 2)
        mn = _fnum(r.get("main_net_yi"), 2)
        stage = r.get("stage")
        strength = _fnum(r.get("strength"), 1)
        has_research = (int(r.get("has_ai") or 0) + int(r.get("has_news") or 0)) > 0
        stage_bonus = {"主升": 30, "加速": 22, "启动": 14}.get(stage, 0)
        research_bonus = 12 if has_research else 0
        # 价格贡献(封顶20) + 资金贡献(封顶25) + 阶段 + 研究
        score = min(pc, 20) + min(max(mn, 0) * 2, 25) + stage_bonus + research_bonus
        r["score"] = round(score, 1)
        r["has_research"] = has_research
        scored.append(r)
    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored[:lim]


def fetch_quality(db, d, lim=10):
    sql = text("""
        SELECT indicator, count(*) AS cnt,
               round(avg(quality_score)::numeric, 2) AS avg_q
        FROM data_quality_log
        WHERE trade_date = :d
        GROUP BY indicator
        ORDER BY cnt DESC
        LIMIT :lim
    """)
    return [dict(r) for r in db.execute(sql, {"d": d, "lim": lim}).mappings().all()]


# ---------- HTML ----------
def _build_html(d, data):
    ov = data["overview"]
    up, dn, eq = int(ov.get("up") or 0), int(ov.get("dn") or 0), int(ov.get("eq") or 0)
    avg_chg = _fnum(ov.get("avg_chg"), 2)
    main_net = _fnum(ov.get("main_net_yi"), 1)
    total = int(ov.get("total") or 0)

    # 情绪判定
    if up > dn * 1.5:
        mood, mood_color = "乐观", "#16a34a"
    elif up > dn:
        mood, mood_color = "偏多", "#65a30d"
    elif up * 1.5 < dn:
        mood, mood_color = "悲观", "#dc2626"
    else:
        mood, mood_color = "偏弱", "#d97706"

    gen_time = datetime.now().strftime("%Y-%m-%d %H:%M")

    # ---- 表格行 ----
    def limit_rows():
        out = []
        for r in data["limit_up"]:
            out.append(
                f"<tr><td>{r['ts_code']}</td><td>{r['name']}</td>"
                f"<td>{r.get('sector') or '-'}</td>"
                f"<td class='num up'>{_fnum(r['price_chg'])}%</td>"
                f"<td class='num'>{_fnum(r['price'])}</td>"
                f"<td class='num {'up' if _fnum(r['main_net_yi'])>0 else 'down'}'>{_fnum(r['main_net_yi'])}亿</td>"
                f"<td>{r.get('stage') or '-'}</td></tr>"
            )
        return "\n".join(out) if out else "<tr><td colspan='7'>暂无涨停/强势股</td></tr>"

    def leader_rows():
        out = []
        for r in data["leaders"]:
            out.append(
                f"<tr><td>{r['ts_code']}</td><td>{r['name']}</td>"
                f"<td>{r.get('sector') or '-'}</td>"
                f"<td><span class='badge'>{r['stage']}</span></td>"
                f"<td class='num'>{_fnum(r['strength'],1)}</td>"
                f"<td class='num'>{_fnum(r['change_rate'])}%</td>"
                f"<td class='num'>{int(r.get('consecutive_days') or 0)}天</td></tr>"
            )
        return "\n".join(out) if out else "<tr><td colspan='7'>暂无活跃龙头</td></tr>"

    def research_rows():
        out = []
        for r in data["research"]:
            typ = r.get("typ") or r.get("query_keyword") or "news"
            src = r.get("model") or "妙想"
            snippet = (r.get("snippet") or "").replace("\n", " ").strip()
            stage = r.get("stage")
            cd = int(r.get("consecutive_days") or 0)
            # 活跃标记：龙头阶段 / 连续 >=2 日 / 首板
            if stage:
                active = f"<span class='badge'>{stage}</span>"
            elif cd >= 2:
                active = f"<span class='badge'>{cd}日连</span>"
            elif cd == 1:
                active = "<span class='badge'>首板</span>"
            else:
                active = "-"
            # 新增催化标记
            catalyst = " 🔥" if r.get("src") == "news" and snippet else ""
            out.append(
                f"<tr><td>{r.get('stock_code')}</td><td>{r.get('stock_name') or r.get('stock_code') or '-'}</td>"
                f"<td><span class='tag'>{typ}</span></td>"
                f"<td>{src}{catalyst}</td>"
                f"<td>{active}</td>"
                f"<td class='snippet'>{snippet[:110]}{'…' if len(snippet)>110 else ''}</td></tr>"
            )
        return "\n".join(out) if out else "<tr><td colspan='6'>今日无新研究沉淀</td></tr>"

    def plan_rows():
        out = []
        for i, r in enumerate(data["plan"], 1):
            rs = "✓" if r.get("has_research") else "—"
            reason = []
            if _fnum(r.get("price_chg"), 2) >= 9:
                reason.append("涨停")
            elif _fnum(r.get("price_chg"), 2) >= 5:
                reason.append(f"强势+{_fnum(r['price_chg'])}%")
            if r.get("stage"):
                reason.append(f"龙头{r['stage']}")
            if _fnum(r.get("main_net_yi"), 2) > 0:
                reason.append(f"主力+{_fnum(r['main_net_yi'])}亿")
            if r.get("has_research"):
                reason.append("有研究催化")
            out.append(
                f"<tr><td>{i}</td><td>{r['ts_code']}</td><td>{r['name']}</td>"
                f"<td class='num'>{_fnum(r['score'],1)}</td>"
                f"<td>{' / '.join(reason) or '-'}</td>"
                f"<td class='num'>{rs}</td></tr>"
            )
        return "\n".join(out) if out else "<tr><td colspan='6'>暂无候选</td></tr>"

    def quality_rows():
        out = []
        for r in data["quality"]:
            out.append(
                f"<tr><td>{r['indicator']}</td>"
                f"<td class='num'>{int(r['cnt'])}</td>"
                f"<td class='num'>{_fnum(r['avg_q'],2)}</td></tr>"
            )
        return "\n".join(out) if out else "<tr><td colspan='3'>今日无质量异常</td></tr>"

    chart_data = json.dumps({
        "sector": [{"name": r["sector"], "v": _fnum(r["net_flow_yi"], 1)} for r in data["sector_flow"]],
        "concept": [{"name": r["concept_name"], "v": _fnum(r["net_flow_yi"], 1)} for r in data["concept_flow"]],
        "breadth": {"up": up, "dn": dn, "eq": eq},
    }, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>AIROBOT 盘后综合日报 - {d}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, "PingFang SC", "Microsoft YaHei", sans-serif;
         max-width: 1180px; margin: 0 auto; padding: 20px; background: #0f172a; color: #e2e8f0; }}
  h1 {{ font-size: 26px; margin: 0 0 4px; }}
  .sub {{ color: #94a3b8; font-size: 13px; margin-bottom: 18px; }}
  .cards {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 22px; }}
  .card {{ background: #1e293b; border-radius: 12px; padding: 14px; text-align: center; }}
  .card .k {{ font-size: 12px; color: #94a3b8; }}
  .card .v {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
  .up {{ color: #f87171; }} .down {{ color: #4ade80; }}
  .grid2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 18px; }}
  .panel {{ background: #1e293b; border-radius: 12px; padding: 16px; }}
  .panel h2 {{ font-size: 16px; margin: 0 0 10px; color: #cbd5e1; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th, td {{ padding: 7px 8px; text-align: left; border-bottom: 1px solid #334155; }}
  th {{ color: #94a3b8; font-weight: 600; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .badge {{ background: #3730a3; color: #c7d2fe; padding: 2px 8px; border-radius: 10px; font-size: 12px; }}
  .tag {{ background: #155e75; color: #a5f3fc; padding: 2px 8px; border-radius: 10px; font-size: 12px; }}
  .snippet {{ color: #94a3b8; max-width: 360px; }}
  .mood {{ display: inline-block; padding: 3px 12px; border-radius: 12px; color: #fff; font-weight: 600; }}
  .disc {{ color: #64748b; font-size: 12px; margin-top: 24px; padding-top: 14px;
          border-top: 1px solid #334155; line-height: 1.6; }}
  canvas {{ max-height: 300px; }}
  @media (max-width: 760px) {{ .cards{{grid-template-columns:repeat(2,1fr);}} .grid2{{grid-template-columns:1fr;}} }}
</style>
</head>
<body>
  <h1>📊 AIROBOT 盘后综合日报</h1>
  <div class="sub">交易日 <b>{d}</b> · 生成于 {gen_time} · 数据来源：本地 PostgreSQL（airobot）</div>

  <div class="cards">
    <div class="card"><div class="k">上涨家数</div><div class="v up">{up}</div></div>
    <div class="card"><div class="k">下跌家数</div><div class="v down">{dn}</div></div>
    <div class="card"><div class="k">平均涨跌幅</div><div class="v {'up' if avg_chg>=0 else 'down'}">{avg_chg}%</div></div>
    <div class="card"><div class="k">主力净流入(合计)</div><div class="v {'up' if main_net>=0 else 'down'}">{main_net}亿</div></div>
    <div class="card"><div class="k">市场情绪</div><div class="v"><span class="mood" style="background:{mood_color}">{mood}</span></div></div>
  </div>

  <div class="grid2">
    <div class="panel"><h2>🏭 行业板块资金净流入 Top15</h2><canvas id="sectorChart"></canvas></div>
    <div class="panel"><h2>💡 概念板块资金净流入 Top15 <span style="font-size:12px;color:#94a3b8">(数据截至 {data.get('concept_date', d)})</span></h2><canvas id="conceptChart"></canvas></div>
  </div>

  <div class="grid2">
    <div class="panel"><h2>🔥 涨停 / 强势股榜（涨≥9%）</h2>
      <table><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>涨幅</th><th>现价</th><th>主力净</th><th>龙头阶段</th></tr></thead>
      <tbody>{limit_rows()}</tbody></table></div>
    <div class="panel"><h2>🐉 龙头生命周期活跃</h2>
      <table><thead><tr><th>代码</th><th>名称</th><th>行业</th><th>阶段</th><th>强度</th><th>涨幅</th><th>连涨</th></tr></thead>
      <tbody>{leader_rows()}</tbody></table></div>
  </div>

  <div class="panel" style="margin-bottom:18px"><h2>📰 个股研究摘要（当日新采集）</h2>
      <table><thead><tr><th>代码</th><th>名称</th><th>类型</th><th>来源</th><th>活跃</th><th>摘要</th></tr></thead>
      <tbody>{research_rows()}</tbody></table></div>

  <div class="panel" style="margin-bottom:18px"><h2>🎯 次日买卖参考清单（多信号交叉打分 Top{len(data['plan'])}）</h2>
    <table><thead><tr><th>#</th><th>代码</th><th>名称</th><th>综合分</th><th>入选理由</th><th>研究</th></tr></thead>
    <tbody>{plan_rows()}</tbody></table></div>

  <div class="panel"><h2>⚠️ 数据质量异常（按指标）</h2>
    <table><thead><tr><th>指标</th><th>异常条数</th><th>平均质量分</th></tr></thead>
    <tbody>{quality_rows()}</tbody></table></div>

  <div class="disc">
    ⚠️ 本报告由 AIROBOT 基于本地数据库自动生成，仅供研究与复盘参考，<b>不构成任何投资建议或个股推荐</b>。
    "次日买卖参考"为量化信号交叉筛选结果，非收益预测；市场有风险，决策需谨慎。数据来源：本地 PostgreSQL（airobot）。
  </div>

<script>
  const D = {chart_data};
  const up = D.breadth.up, dn = D.breadth.dn, eq = D.breadth.eq;
  const netColor = v => v >= 0 ? '#f87171' : '#4ade80';
  new Chart(document.getElementById('sectorChart'), {{
    type: 'bar',
    data: {{ labels: D.sector.map(x=>x.name),
      datasets: [{{ label:'净流入(万元)', data: D.sector.map(x=>x.v),
        backgroundColor: D.sector.map(x=>netColor(x.v)) }}] }},
    options: {{ indexAxis:'y', plugins:{{legend:{{display:false}}}},
      scales:{{ x:{{ ticks:{{color:'#94a3b8'}}, grid:{{color:'#334155'}} }},
               y:{{ ticks:{{color:'#cbd5e1', font:{{size:11}}}}, grid:{{display:false}} }} }} }}
  }});
  new Chart(document.getElementById('conceptChart'), {{
    type: 'bar',
    data: {{ labels: D.concept.map(x=>x.name),
      datasets: [{{ label:'净流入(万元)', data: D.concept.map(x=>x.v),
        backgroundColor: D.concept.map(x=>netColor(x.v)) }}] }},
    options: {{ indexAxis:'y', plugins:{{legend:{{display:false}}}},
      scales:{{ x:{{ ticks:{{color:'#94a3b8'}}, grid:{{color:'#334155'}} }},
               y:{{ ticks:{{color:'#cbd5e1', font:{{size:11}}}}, grid:{{display:false}} }} }} }}
  }});
</script>
</body>
</html>"""
    return html


def generate_daily_report(date_str=None):
    """生成指定日期（默认最新交易日）的盘后日报，返回文件路径"""
    from db.session import get_db_session

    os.makedirs(REPORT_DIR, exist_ok=True)
    with get_db_session() as db:
        d = date_str or _latest_trade_date(db)
        if not d:
            raise RuntimeError("无法确定交易日期")
        # 概念板块数据可能滞后（采集器未更新到当日），回退到最新有数据日期
        concept_d = d
        try:
            if db.execute(text("SELECT 1 FROM concept_sector_flow WHERE trade_date=:d"), {"d": d}).first() is None:
                latest = db.execute(text("SELECT max(trade_date) FROM concept_sector_flow")).scalar()
                if latest:
                    concept_d = latest.strftime("%Y-%m-%d") if hasattr(latest, "strftime") else str(latest)
        except Exception:
            concept_d = d
        data = {
            "overview": fetch_overview(db, d),
            "limit_up": fetch_limit_up(db, d),
            "sector_flow": fetch_sector_flow(db, d),
            "concept_flow": fetch_concept_flow(db, concept_d),
            "concept_date": concept_d,
            "leaders": fetch_leaders(db, d),
            "research": fetch_research(db, d),
            "plan": fetch_nextday_plan(db, d),
            "quality": fetch_quality(db, d),
        }
    html = _build_html(d, data)
    path = os.path.join(REPORT_DIR, f"{d}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"[daily_report] 已生成 {d} 报告 -> {path}")
    return path


if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO)
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="YYYY-MM-DD，默认最新交易日")
    args = ap.parse_args()
    p = generate_daily_report(args.date)
    print("REPORT_PATH=" + p)
