"""Market-aware instrument discovery and tiered universe membership."""

from __future__ import annotations

import logging
import io
import json
import math
import re
import urllib.request
from datetime import datetime

from db.session import get_db_session
from .identity import normalize_market, normalize_symbol, provider_symbol
from .repository import MarketInstrument, MarketUniverseMembership

logger = logging.getLogger(__name__)


# Known display-name overrides for symbols discovered by the collectors.  This
# list is never used to fabricate universe membership when collection fails.
HK_REFERENCE_NAMES = [
    ("00005", "汇丰控股"), ("00011", "恒生银行"), ("00016", "新鸿基地产"),
    ("00027", "银河娱乐"), ("00066", "港铁公司"), ("00083", "信和置业"),
    ("00101", "恒隆地产"), ("00175", "吉利汽车"), ("00267", "中信股份"),
    ("00288", "万洲国际"), ("00316", "东方海外国际"), ("00386", "中国石油化工股份"),
    ("00388", "香港交易所"), ("00669", "创科实业"), ("00688", "中国海外发展"),
    ("00700", "腾讯控股"), ("00762", "中国联通"), ("00857", "中国石油股份"),
    ("00883", "中国海洋石油"), ("00939", "建设银行"), ("00941", "中国移动"),
    ("00960", "龙湖集团"), ("00981", "中芯国际"), ("00992", "联想集团"),
    ("01024", "快手-W"), ("01044", "恒安国际"), ("01088", "中国神华"),
    ("01109", "华润置地"), ("01171", "兖矿能源"), ("01177", "中国生物制药"),
    ("01211", "比亚迪股份"), ("01288", "农业银行"), ("01398", "工商银行"),
    ("01618", "中国中冶"), ("01658", "邮储银行"), ("01787", "山东黄金"),
    ("01810", "小米集团-W"), ("01876", "百威亚太"), ("01928", "金沙中国有限公司"),
    ("01929", "周大福"), ("01997", "九龙仓置业"), ("02007", "碧桂园"),
    ("02020", "安踏体育"), ("02015", "理想汽车-W"), ("02018", "瑞声科技"),
    ("02269", "药明生物"), ("02318", "中国平安"), ("02319", "蒙牛乳业"),
    ("02333", "长城汽车"), ("02359", "药明康德"), ("02382", "舜宇光学科技"),
    ("02388", "中银香港"), ("02601", "中国太保"), ("02628", "中国人寿"),
    ("02688", "新奥能源"), ("02727", "上海电气"), ("02899", "紫金矿业"),
    ("03323", "中国建材"), ("03690", "美团-W"), ("03692", "翰森制药"),
    ("03888", "金山软件"), ("03968", "招商银行"), ("03988", "中国银行"),
    ("06030", "中信证券"), ("06066", "中信建投证券"), ("06098", "碧桂园服务"),
    ("06160", "百济神州"), ("06618", "京东健康"), ("06690", "海尔智家"),
    ("06862", "海底捞"), ("06869", "长飞光纤光缆"),
    ("06881", "中国银河"), ("06886", "华泰证券"),
    ("09618", "京东集团-SW"), ("09626", "哔哩哔哩-W"), ("09633", "农夫山泉"),
    ("09698", "万国数据-SW"), ("09866", "蔚来-SW"), ("09868", "小鹏汽车-W"),
    ("09888", "百度集团-SW"), ("09896", "名创优品"), ("09961", "携程集团-S"),
    ("09988", "阿里巴巴-W"), ("09999", "网易-S"), ("09992", "泡泡玛特"),
    ("09987", "百胜中国"), ("09969", "诺诚健华"), ("09979", "绿城服务"),
    ("09991", "宝尊电商-W"), ("09995", "荣昌生物"), ("09997", "康基医疗"),
    ("01801", "信达生物"), ("02313", "申洲国际"),
    ("02331", "李宁"), ("02343", "太平洋航运"), ("02423", "贝壳-W"),
    ("02500", "启明医疗-B"), ("02607", "上海医药"), ("02869", "绿城服务"),
    ("03333", "中国恒大"), ("03800", "协鑫科技"), ("03900", "绿城中国"),
    ("06078", "海吉亚医疗"), ("06185", "康希诺生物"), ("06622", "兆科眼科-B"),
    ("06990", "科伦博泰生物-B"), ("09616", "东软教育"), ("09660", "地平线机器人-W"),
]

# HKEX's official listing file is authoritative for discovery, but its display
# names are English. Keep the Chinese names maintained by the app for known
# seed/core symbols so a remote refresh does not regress the Chinese UI.
# Newly discovered symbols keep the official name until a Chinese name source
# is added.
HK_NAME_OVERRIDES = dict(HK_REFERENCE_NAMES)


UNIVERSE_DEFINITIONS = {
    "US_CORE_A_300": {"market": "US", "limit": 300, "tier": "CORE", "label": "美股核心A池"},
    "US_CORE_B_500": {"market": "US", "limit": 500, "tier": "CORE_B", "label": "美股核心B池"},
    "US_RESEARCH_1000": {"market": "US", "limit": 1000, "tier": "RESEARCH", "label": "美股研究池"},
    "HK_CORE_100": {"market": "HK", "limit": 100, "tier": "CORE", "label": "港股核心池"},
    "HK_RESEARCH_500": {"market": "HK", "limit": 500, "tier": "RESEARCH", "label": "港股研究池"},
    "HK_WATCHLIST": {"market": "HK", "limit": None, "tier": "WATCH", "label": "盈立自选"},
}


def _hk_rows_from_akshare() -> list[dict]:
    try:
        import akshare as ak
        frame = ak.stock_hk_spot_em()
    except Exception as exc:
        logger.info("HK universe remote source unavailable: %s", exc)
        return []
    if frame is None or frame.empty:
        return []
    columns = {str(column): column for column in frame.columns}
    code_key = next((columns[key] for key in ("代码", "证券代码", "symbol") if key in columns), None)
    name_key = next((columns[key] for key in ("名称", "证券简称", "name") if key in columns), None)
    price_key = next((columns[key] for key in ("最新价", "现价", "price") if key in columns), None)
    turnover_key = next((columns[key] for key in ("成交额", "成交金额", "turnover") if key in columns), None)
    if code_key is None:
        return []
    rows = []
    for _, row in frame.iterrows():
        try:
            code = normalize_symbol("HK", str(row[code_key]))
        except ValueError:
            continue
        name = str(row[name_key]) if name_key is not None else code
        upper_name = name.upper()
        if any(token in upper_name for token in ("ETF", "基金", "权证", "牛熊", "CBBC")):
            continue
        def num(key):
            try:
                return float(row[key]) if key is not None and row[key] not in (None, "-") else None
            except (TypeError, ValueError):
                return None
        rows.append({"symbol": code, "name": name, "price": num(price_key), "turnover": num(turnover_key), "source": "akshare"})
    return rows


def _us_rows_from_db() -> list[dict]:
    from us_quant.repository import USInstrument
    with get_db_session() as db:
        rows = db.query(USInstrument).filter(USInstrument.is_active.is_(True)).all()
    result = []
    for row in rows:
        if row.is_etf or row.is_otc or row.is_leveraged or row.is_inverse:
            continue
        result.append({
            "symbol": row.symbol,
            "name": row.name or row.symbol,
            "exchange": row.exchange or "XNAS",
            "sector": row.sector or "",
            "industry": row.industry or "",
            "price": float(row.price) if row.price is not None else None,
            "market_cap": float(row.market_cap) if row.market_cap is not None else None,
            "turnover": float(row.avg_dollar_volume_20d) if row.avg_dollar_volume_20d is not None else None,
            "source": row.universe_source or "us_instruments",
        })
    return result


def _us_rows_from_remote() -> list[dict]:
    try:
        from us_quant.universe import fetch_research_universe_from_eastmoney
        rows = [dict(row, source="eastmoney") for row in fetch_research_universe_from_eastmoney()]
        if rows:
            return rows
    except Exception as exc:
        logger.warning("US universe remote refresh failed: %s", exc)
    return _us_rows_from_nasdaq()


def _us_rows_from_nasdaq() -> list[dict]:
    """Read common-stock candidates from Nasdaq's public screener.

    The screener is used only for instrument discovery.  It does not provide
    the production price history; every imported symbol still has to pass the
    real-history backfill and quality gate before scoring.
    """
    url = "https://api.nasdaq.com/api/screener/stocks?tableonly=true&limit=5000&offset=0"
    request = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json, text/plain, */*",
    })
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
        rows = json.loads(payload.decode("utf-8")).get("data", {}).get("table", {}).get("rows", [])
    except Exception as exc:
        logger.warning("Nasdaq universe refresh failed: %s", exc)
        return []

    excluded = ("ETF", "FUND", "TRUST", "NOTE", "WARRANT", "RIGHT", "UNIT", "PREFERRED", "DEBENTURE", "DEPOSITARY")

    def number(value):
        try:
            return float(str(value or "").replace("$", "").replace(",", "").strip())
        except (TypeError, ValueError):
            return None

    result = []
    seen = set()
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        name = str(row.get("name") or "").strip()
        price = number(row.get("lastsale"))
        market_cap = number(row.get("marketCap"))
        if (
            not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,7}", symbol)
            or symbol in seen
            or not name
            or not price or price <= 0
            or not market_cap or market_cap <= 0
            or any(token in name.upper() for token in excluded)
        ):
            continue
        seen.add(symbol)
        result.append({
            "symbol": symbol,
            "name": name,
            "price": price,
            "market_cap": market_cap,
            "exchange": "NASDAQ",
            "source": "nasdaq_screener",
        })
    logger.info("Nasdaq universe refresh: %s common-stock candidates", len(result))
    return result


def _hk_rows_from_hkex() -> list[dict]:
    """Read ordinary HKEX equity listings from the official XLSX list."""
    url = "https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx"
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
        import pandas as pd
        frame = pd.read_excel(io.BytesIO(content), sheet_name=0, header=2)
    except Exception as exc:
        logger.warning("HKEX universe refresh failed: %s", exc)
        return []

    excluded = ("ETF", "FUND", "TRUST", "WARRANT", "RIGHT", "PREF", "NOTE", "UNIT", "BOND")
    result = []
    seen = set()
    for _, row in frame.iterrows():
        category = str(row.get("Category") or "").strip().upper()
        sub_category = str(row.get("Sub-Category") or "").strip().upper()
        if category != "EQUITY" or "EQUITY SECURITIES" not in sub_category:
            continue
        raw_code = str(row.get("Stock Code") or "").split(".")[0].strip()
        name = str(row.get("Name of Securities") or "").strip()
        if not raw_code.isdigit() or not name or any(token in name.upper() for token in excluded):
            continue
        symbol = raw_code.zfill(5)
        if symbol in seen:
            continue
        seen.add(symbol)
        result.append({
            "symbol": symbol,
            "name": name,
            "exchange": "XHKG",
            "currency": str(row.get("Trading Currency") or "HKD").strip(),
            "source": "hkex",
        })
    logger.info("HKEX universe refresh: %s equity candidates", len(result))
    return result


def _save_instruments(market: str, rows: list[dict]) -> int:
    now = datetime.now()
    saved = 0
    with get_db_session() as db:
        for item in rows:
            try:
                symbol = normalize_symbol(market, item.get("symbol"))
            except ValueError:
                continue
            row = db.query(MarketInstrument).filter_by(market=market, symbol=symbol).first()
            if row is None:
                row = MarketInstrument(market=market, symbol=symbol, provider_symbol=provider_symbol(market, symbol), exchange=(item.get("exchange") or ("XHKG" if market == "HK" else "XNAS")))
                db.add(row)
            display_name = HK_NAME_OVERRIDES.get(symbol) if market == "HK" else None
            row.name = str(display_name or item.get("name") or symbol)[:128]
            row.sector = str(item.get("sector") or row.sector or "")[:128]
            row.industry = str(item.get("industry") or row.industry or "")[:128]
            row.price = item.get("price")
            row.market_cap = item.get("market_cap")
            row.avg_turnover_20d = item.get("turnover")
            row.currency = "HKD" if market == "HK" else "USD"
            row.security_type = "COMMON_STOCK"
            row.is_active = True
            row.is_etf = bool(item.get("is_etf", False))
            row.is_otc = bool(item.get("is_otc", False))
            row.is_leveraged = bool(item.get("is_leveraged", False))
            row.is_inverse = bool(item.get("is_inverse", False))
            row.source = item.get("source") or "unspecified_collector"
            row.data_updated_at = now
            saved += 1
        db.commit()
    return saved


def _score(row: dict) -> float:
    turnover = float(row.get("turnover") or 0)
    market_cap = float(row.get("market_cap") or 0)
    return math.log1p(max(turnover, 0)) * 0.7 + math.log1p(max(market_cap, 0)) * 0.3


def _active_rows(market: str) -> list[dict]:
    with get_db_session() as db:
        rows = db.query(MarketInstrument).filter(
            MarketInstrument.market == market,
            MarketInstrument.is_active.is_(True),
            MarketInstrument.is_etf.is_(False),
            MarketInstrument.is_otc.is_(False),
            MarketInstrument.is_leveraged.is_(False),
            MarketInstrument.is_inverse.is_(False),
        ).all()
    return [{
        "symbol": row.symbol,
        "name": row.name or row.symbol,
        "sector": row.sector or row.industry or "",
        "turnover": float(row.avg_turnover_20d or 0),
        "market_cap": float(row.market_cap or 0),
    } for row in rows]


def _save_memberships(market: str, universe_code: str, rows: list[dict], limit: int, tier: str) -> int:
    now = datetime.now()
    selected = sorted(rows, key=_score, reverse=True)[:limit]
    with get_db_session() as db:
        db.query(MarketUniverseMembership).filter(
            MarketUniverseMembership.market == market,
            MarketUniverseMembership.universe_code == universe_code,
            MarketUniverseMembership.effective_to.is_(None),
        ).update({"effective_to": now}, synchronize_session=False)
        for rank, item in enumerate(selected, start=1):
            db.add(MarketUniverseMembership(
                market=market,
                universe_code=universe_code,
                symbol=item["symbol"],
                tier=tier,
                rank=rank,
                universe_score=round(_score(item), 4),
                effective_from=now,
                inclusion_reason="按流动性与市值分层排名",
                source="market_universe",
                config_version="v1",
            ))
        db.commit()
    return len(selected)


def sync_market_universe(market: str, refresh_remote: bool = False) -> dict:
    market = normalize_market(market)
    if market == "US":
        rows = _us_rows_from_remote() if refresh_remote else _us_rows_from_db()
        if not rows:
            rows = _us_rows_from_remote()
        saved = _save_instruments("US", rows)
    elif market == "HK":
        rows = _hk_rows_from_akshare()
        if not rows and refresh_remote:
            rows = _hk_rows_from_hkex()
        if not rows:
            active = _active_rows("HK")
            return {
                "market": "HK",
                "status": "SOURCE_UNAVAILABLE",
                "instruments": 0,
                "active": len(active),
                "universes": {},
                "used_existing_database": bool(active),
                "updated_at": None,
            }
        saved = _save_instruments("HK", rows)
    else:
        raise ValueError("market universe only supports HK/US")

    active = _active_rows(market)
    counts = {}
    for code, definition in UNIVERSE_DEFINITIONS.items():
        if definition["market"] != market:
            continue
        # 自选池（盈立同步）不走评分重排，跳过避免覆盖
        if definition.get("tier") == "WATCH":
            counts[code] = None
            continue
        counts[code] = _save_memberships(market, code, active, definition["limit"], definition["tier"])
    return {"market": market, "status": "READY", "instruments": saved, "active": len(active), "universes": counts, "updated_at": datetime.now().isoformat()}


def universe_code(market: str, requested: str = "CORE") -> str:
    market = normalize_market(market)
    value = (requested or "CORE").upper()
    aliases = {
        ("US", "CORE"): "US_CORE_A_300",
        ("US", "CORE_A"): "US_CORE_A_300",
        ("US", "CORE_B"): "US_CORE_B_500",
        ("US", "RESEARCH"): "US_RESEARCH_1000",
        ("HK", "CORE"): "HK_CORE_100",
        ("HK", "RESEARCH"): "HK_RESEARCH_500",
    }
    return aliases.get((market, value), requested.upper())


def get_members(market: str, requested: str = "CORE") -> list[str]:
    market = normalize_market(market)
    code = universe_code(market, requested)
    with get_db_session() as db:
        rows = db.query(MarketUniverseMembership.symbol).filter(
            MarketUniverseMembership.market == market,
            MarketUniverseMembership.universe_code == code,
            MarketUniverseMembership.effective_to.is_(None),
        ).order_by(MarketUniverseMembership.rank.asc()).all()
    return [row[0] for row in rows]


def list_universes(market: str) -> list[dict]:
    market = normalize_market(market)
    result = []
    for code, definition in UNIVERSE_DEFINITIONS.items():
        if definition["market"] != market:
            continue
        members = get_members(market, code)
        result.append({"code": code, "label": definition["label"], "target": definition["limit"], "count": len(members), "tier": definition["tier"]})
    return result
