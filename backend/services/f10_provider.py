"""研报中心 F10 免费数据源（替代付费通达信 Hub）+ PG 缓存

设计原则：
- 财务(营收/净利/ROE/毛利率/eps) 与 机构持仓(机构数/占流通比) 走 Tushare
  复用 collectors.tdx_collector.call_tushare_mcp（已含 TUSHARE_TOKEN + 全局令牌桶限流）。
- 评级/目标价 走东方财富公开 API（无需 token）。
- 三者按 ts_code 整包缓存进 PG `stock_f10` 表，TTL = 1 天（日频变化）。
  多用户复用、断网/限流时直接读缓存，无需每次外网拉取。
- 任何网络/解析异常都吞掉并返回 None，绝不中断主报告生成（F10 只是锦上添花）。

对外暴露与旧 tdx_hub_client 完全一致的接口签名：
  get_financials(code) / get_rating(code) / get_institutional(code) / is_configured()
这样 analysis_consumer 几乎不用改动即可切换数据源。
"""
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

import httpx

from db.connection import SessionLocal
from db.models import StockF10

logger = logging.getLogger("f10_provider")

# 缓存有效期（小时）。财务/机构日频变化，1 天足够。
CACHE_TTL_HOURS = 24

# 东方财富 datacenter 盈利预测接口（含目标价/一致EPS），公开无需鉴权
_EM_RATING_URL = (
    "https://datacenter.eastmoney.com/securities/api/data/v1/get"
    "?reportName=RPT_WEB_RESPREDICT&columns=ALL"
    "&filter=(SECUCODE%3D%22{secucode}%22)"
    "&client=PC&source=WEB&p=1"
)
_EM_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Referer": "https://data.eastmoney.com/",
}


# ---------- 工具 ----------

def _to_ts_code(code: str) -> str:
    """纯数字代码 -> tushare 风格 ts_code（002245 -> 002245.SZ）。"""
    c = (code or "").strip()
    if not c:
        return c
    if "." in c:
        return c
    if c[0] in ("6", "9") or c.startswith("688"):
        return f"{c}.SH"
    if c.startswith("8") or c.startswith("4"):
        return f"{c}.BJ"
    return f"{c}.SZ"


def is_configured() -> bool:
    """只要 Tushare token 在（财务/机构可用）即视为可用；东方财富无需 token。"""
    try:
        from config import TUSHARE_TOKEN
        if TUSHARE_TOKEN:
            return True
    except Exception as e:
        logger.debug("[f10_provider] is_configured failed: %s", e)
    return False


# ---------- PG 缓存 ----------

def _cache_get(ts_code: str) -> Optional[Dict[str, Any]]:
    try:
        with SessionLocal() as db:
            row = db.get(StockF10, ts_code)
            if row and row.fetched_at:
                if datetime.now() - row.fetched_at < timedelta(hours=CACHE_TTL_HOURS):
                    return {
                        "financials": json.loads(row.financial_json) if row.financial_json else None,
                        "institution": json.loads(row.institution_json) if row.institution_json else None,
                        "rating": json.loads(row.rating_json) if row.rating_json else None,
                    }
    except Exception as e:
        logger.warning("[f10_provider] cache_get %s error: %s", ts_code, e)
    return None


def _cache_set(ts_code: str, financials, institution, rating) -> None:
    try:
        with SessionLocal() as db:
            row = db.get(StockF10, ts_code)
            if not row:
                row = StockF10(ts_code=ts_code)
            row.financial_json = json.dumps(financials, ensure_ascii=False) if financials else None
            row.institution_json = json.dumps(institution, ensure_ascii=False) if institution else None
            row.rating_json = json.dumps(rating, ensure_ascii=False) if rating else None
            row.fetched_at = datetime.now()
            db.merge(row)
            db.commit()
    except Exception as e:
        logger.warning("[f10_provider] cache_set %s error: %s", ts_code, e)


# ---------- 免费源拉取 ----------

def _fetch_financials(ts_code: str) -> Optional[Dict[str, Any]]:
    """Tushare 财务：fina_indicator 取 ROE/毛利率/eps/bps，income 取营收/净利，合并为最新期。"""
    from collectors.tdx_collector import call_tushare_mcp
    out: Dict[str, Any] = {}
    fi = call_tushare_mcp(
        "fina_indicator",
        params={"ts_code": ts_code},
        fields=["ts_code", "ann_date", "end_date", "roe", "grossprofit_margin", "eps", "bps"],
    )
    if fi:
        r = fi[0]
        if r.get("roe") is not None:
            out["roe"] = r["roe"]
        if r.get("grossprofit_margin") is not None:
            out["gross_margin"] = r["grossprofit_margin"]
        if r.get("eps") is not None:
            out["eps"] = r["eps"]
        if r.get("bps") is not None:
            out["bps"] = r["bps"]
        if r.get("end_date"):
            out["period"] = str(r["end_date"])
    inc = call_tushare_mcp(
        "income",
        params={"ts_code": ts_code},
        fields=["ts_code", "ann_date", "end_date", "revenue", "n_income"],
    )
    if inc:
        r = inc[0]
        if r.get("revenue") is not None:
            out["revenue"] = r["revenue"]
        if r.get("n_income") is not None:
            out["net_profit"] = r["n_income"]
        if "period" not in out and r.get("end_date"):
            out["period"] = str(r["end_date"])
    # TTM PE / PB 来自 daily_basic（免费且准确，避免用单季 EPS 误算）
    db = call_tushare_mcp(
        "daily_basic",
        params={"ts_code": ts_code},
        fields=["ts_code", "trade_date", "pe_ttm", "pb"],
    )
    if db:
        db.sort(key=lambda x: str(x.get("trade_date") or ""), reverse=True)
        r = db[0]
        if r.get("pe_ttm") is not None:
            out["pe_ttm"] = r["pe_ttm"]
        if r.get("pb") is not None:
            out["pb"] = r["pb"]
    return out or None


_INST_KEYWORDS = ("基金", "资管", "保险", "社保", "QFII", "信托", "证券", "银行", "私募", "养老")


def _fetch_institution(ts_code: str) -> Optional[Dict[str, Any]]:
    """Tushare top10_floatholders：仅取最新报告期，统计机构数 + 机构合计占流通股比例。"""
    from collectors.tdx_collector import call_tushare_mcp
    rows = call_tushare_mcp(
        "top10_floatholders",
        params={"ts_code": ts_code},
        fields=["ts_code", "ann_date", "holder_name", "hold_ratio"],
    )
    if not rows:
        return None
    # 只保留最新报告期（避免跨期累加导致占比 >100%）
    rows.sort(key=lambda x: str(x.get("ann_date") or ""), reverse=True)
    latest = rows[0].get("ann_date")
    period_rows = [r for r in rows if r.get("ann_date") == latest]
    inst_rows = [x for x in period_rows if any(k in (x.get("holder_name") or "") for k in _INST_KEYWORDS)]
    out: Dict[str, Any] = {}
    if inst_rows:
        out["机构数量"] = len(inst_rows)
        try:
            ratio = sum(float(x.get("hold_ratio") or 0) for x in inst_rows)
            out["持仓占实际流通A股比例"] = round(ratio, 4)
        except Exception as e:
            logger.debug("[f10_provider] hold_ratio sum failed: %s", e)
    if latest:
        out["period"] = str(latest)
    return out or None


def _fetch_rating(ts_code: str) -> Optional[Dict[str, Any]]:
    """东方财富公开盈利预测接口（RPT_WEB_RESPREDICT）：券商一致目标价 / EPS / 评级分布。

    字段证实可用（2026-07-14 验证）：
    - DEC_AIMPRICEMAX/DEC_AIMPRICEMIN → 最高/最低目标价（取均值）
    - EPS1/2/3/4 → 各财年一致预测（YEAR_MARK: A=actual, E=estimate）
    - RATING_BUY_NUM/ADD_NUM/NEUTRAL_NUM/REDUCE_NUM/SALE_NUM → 评级分布
    - RATING_ORG_NUM → 覆盖机构数
    """
    secucode = ts_code
    url = _EM_RATING_URL.format(secucode=secucode)
    try:
        resp = httpx.get(url, headers=_EM_HEADERS, timeout=12)
        if resp.status_code != 200:
            logger.warning("[f10_provider] 东财评级 %s -> HTTP %s", ts_code, resp.status_code)
            return None
        data = resp.json()
        if not data.get("success"):
            logger.warning("[f10_provider] 东财评级 %s 接口失败: %s", ts_code, data.get("message"))
            return None
        items = (data.get("result") or {}).get("data") or []
        if not items:
            return None
        row = items[0]
        out: Dict[str, Any] = {}
        # 目标价（最高/最低取均值）
        tp_max = row.get("DEC_AIMPRICEMAX")
        tp_min = row.get("DEC_AIMPRICEMIN")
        if tp_max is not None or tp_min is not None:
            try:
                vals = [float(v) for v in (tp_max, tp_min) if v is not None]
                if vals:
                    out["target_price"] = round(sum(vals) / len(vals), 2)
            except Exception:
                logger.debug("f10: target price avg failed", exc_info=False)
        # 一致 EPS（优先取 A=actual 已确认的财年，否则取最新的 E=estimate）
        for i in range(1, 5):
            eps = row.get(f"EPS{i}")
            mrk = row.get(f"YEAR_MARK{i}")
            if eps is not None and mrk == "A":
                out["eps"] = float(eps)
                yr = row.get(f"YEAR{i}")
                if yr:
                    out["eps_year"] = int(yr)
                break
        else:
            for i in range(1, 5):
                eps = row.get(f"EPS{i}")
                if eps is not None:
                    out["eps"] = float(eps)
                    break
        # 评级分布 & 综合信号
        buy = row.get("RATING_BUY_NUM") or 0
        add = row.get("RATING_ADD_NUM") or 0
        neutral = row.get("RATING_NEUTRAL_NUM") or 0
        reduce = row.get("RATING_REDUCE_NUM") or 0
        sale = row.get("RATING_SALE_NUM") or 0
        total = buy + add + neutral + reduce + sale
        out["org_count"] = total
        out["rating_buy"] = buy
        out["rating_add"] = add
        out["rating_neutral"] = neutral
        if total > 0:
            out["buy_add_ratio"] = round((buy + add) / total, 4)
        if out:
            return out
    except Exception as e:
        logger.warning("[f10_provider] 东财评级 %s exception: %s", ts_code, e)
    return None


# ---------- 对外接口（与旧 tdx_hub_client 签名一致）----------

def fetch_f10(code: str) -> Dict[str, Any]:
    """拉取（或读缓存）F10 整包：{financials, institution, rating}。"""
    ts_code = _to_ts_code(code)
    cached = _cache_get(ts_code)
    if cached:
        return cached
    financials = _fetch_financials(ts_code)
    institution = _fetch_institution(ts_code)
    rating = _fetch_rating(ts_code)
    _cache_set(ts_code, financials, institution, rating)
    return {"financials": financials, "institution": institution, "rating": rating}


def get_financials(code: str) -> Optional[Dict[str, Any]]:
    return fetch_f10(code).get("financials")


def get_institutional(code: str) -> Optional[Dict[str, Any]]:
    return fetch_f10(code).get("institution")


def get_rating(code: str) -> Optional[Dict[str, Any]]:
    """返回 {target_price, rating_name, eps?}；eps 优先用财务包里的。"""
    bundle = fetch_f10(code)
    rating = bundle.get("rating") or {}
    fin = bundle.get("financials") or {}
    out = dict(rating)
    if "eps" not in out and fin.get("eps") is not None:
        out["eps"] = fin["eps"]
    return out or None
