# -*- coding: utf-8 -*-
"""美股行业采集服务（stockanalysis.com）

数据流：
  盈立自选同步(sync_us_stocks) → 对 sector 为空的标的并发补采
    stockanalysis.com/stocks/{SYM}/ 静态页 → 行业 slug → 中文 → USInstrument.sector

为什么用 stockanalysis.com：
  - 国内源（东财/新浪）无稳定美股行业字段，东财接口对本机 IP 限流
  - stockanalysis.com 行业信息为静态 HTML，无需 token，单次请求约 2s
  - 行业信息长期稳定，采集后落库缓存，不重复请求
"""
from __future__ import annotations

import json
import html
import logging
import re
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Optional

from db.session import get_db_session
from us_quant.repository import USInstrument

logger = logging.getLogger(__name__)

# ─── 配置 ──────────────────────────────────────────────────────────────────

SA_TIMEOUT = 10            # 单只请求超时（秒）
SA_WORKERS = 2             # 并发数（stockanalysis 对并发敏感，实测并发>2 易触发 429）
SA_BATCH_DELAY = 0.6       # 并发请求间最小间隔（秒）
SA_RETRY_DELAYS = [3, 10]  # 429 限流退避重试间隔（秒）
SA_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"}

# 行业页返回形如：Industry</span> <a href="/stocks/industry/{slug}">Name</a>
_SA_RE = re.compile(r'Industry</span>.*?href="/stocks/industry/([^"/]+)/?"[^>]*>([^<]+)</a>',
                    re.DOTALL)
# 兜底：任意 industry 链接
_SA_RE2 = re.compile(r'href="/stocks/industry/([^"/]+)/?"[^>]*>([^<]+)</a>')

# stockanalysis.com 行业 slug → 中文（抓取 /stocks/industry/ 全量整理）
US_SLUG_CN: Dict[str, str] = {
    "advertising-agencies": "广告营销",
    "aerospace-and-defense": "航空航天军工",
    "agricultural-inputs": "农业化工",
    "airlines": "航空",
    "airports-and-air-services": "机场航空服务",
    "aluminum": "铝业",
    "apparel-manufacturing": "服装制造",
    "apparel-retail": "服装零售",
    "asset-management": "资产管理",
    "auto-and-truck-dealerships": "汽车经销",
    "auto-manufacturers": "汽车制造",
    "auto-parts": "汽车零部件",
    "banks-diversified": "银行",
    "banks-regional": "区域银行",
    "beverages-brewers": "啤酒饮料",
    "beverages-non-alcoholic": "非酒精饮料",
    "beverages-wineries-and-distilleries": "酒类",
    "biotechnology": "生物科技",
    "broadcasting": "广播电视",
    "building-materials": "建材",
    "building-products-and-equipment": "建筑产品",
    "business-equipment-and-supplies": "办公设备用品",
    "capital-markets": "资本市场",
    "chemicals": "化工",
    "coking-coal": "焦煤",
    "communication-equipment": "通信设备",
    "computer-hardware": "电脑硬件",
    "confectioners": "糖果零食",
    "conglomerates": "综合集团",
    "consulting-services": "咨询服务",
    "consumer-electronics": "消费电子",
    "copper": "铜业",
    "credit-services": "信贷服务",
    "department-stores": "百货零售",
    "diagnostics-and-research": "医疗诊断",
    "discount-stores": "折扣零售",
    "drug-manufacturers-general": "制药",
    "drug-manufacturers-specialty-and-generic": "制药",
    "education-and-training-services": "教育培训",
    "electrical-equipment-and-parts": "电气设备",
    "electronic-components": "电子元器件",
    "electronic-gaming-and-multimedia": "电子游戏",
    "electronics-and-computer-distribution": "电子分销",
    "engineering-and-construction": "工程建筑",
    "entertainment": "娱乐传媒",
    "farm-and-heavy-construction-machinery": "工程机械",
    "farm-products": "农产品",
    "financial-conglomerates": "金融集团",
    "financial-data-and-stock-exchanges": "金融数据服务",
    "food-distribution": "食品分销",
    "footwear-and-accessories": "鞋服配饰",
    "furnishings-fixtures-and-appliances": "家具家电",
    "gambling": "博彩",
    "gold": "黄金矿业",
    "grocery-stores": "超市零售",
    "health-information-services": "医疗信息化",
    "healthcare-plans": "医疗保险",
    "home-improvement-retail": "家居建材零售",
    "household-and-personal-products": "日用消费品",
    "industrial-distribution": "工业分销",
    "information-technology-services": "IT服务",
    "infrastructure-operations": "基础设施运营",
    "insurance-diversified": "保险",
    "insurance-life": "寿险",
    "insurance-property-and-casualty": "财产险",
    "insurance-reinsurance": "再保险",
    "insurance-specialty": "专业保险",
    "insurance-brokers": "保险经纪",
    "integrated-freight-and-logistics": "物流货运",
    "internet-content-and-information": "互联网内容",
    "internet-retail": "电商零售",
    "leisure": "休闲服务",
    "lodging": "酒店住宿",
    "lumber-and-wood-production": "木材加工",
    "luxury-goods": "奢侈品",
    "marine-shipping": "海运",
    "medical-care-facilities": "医疗护理设施",
    "medical-devices": "医疗器械",
    "medical-distribution": "医药分销",
    "medical-instruments-and-supplies": "医疗耗材",
    "metal-fabrication": "金属加工",
    "mortgage-finance": "抵押贷款",
    "oil-gas-drilling": "油气钻探",
    "oil-gas-equipment-and-services": "油服",
    "oil-gas-e-and-p": "油气勘探开发",
    "oil-gas-integrated": "综合石油",
    "oil-gas-midstream": "油气中游",
    "oil-gas-refining-and-marketing": "炼油",
    "other-industrial-metals-and-mining": "工业金属",
    "other-precious-metals-and-mining": "贵金属矿业",
    "packaged-foods": "包装食品",
    "packaging-and-containers": "包装",
    "paper-and-paper-products": "造纸",
    "personal-services": "个人服务",
    "pharmaceutical-retailers": "药品零售",
    "pollution-and-treatment-controls": "环保设备",
    "publishing": "出版",
    "reit-diversified": "REIT",
    "reit-healthcare-facilities": "医疗REIT",
    "reit-hotel-and-motel": "酒店REIT",
    "reit-industrial": "工业REIT",
    "reit-mortgage": "抵押REIT",
    "reit-office": "写字楼REIT",
    "reit-residential": "住宅REIT",
    "reit-retail": "商业REIT",
    "reit-specialty": "专项REIT",
    "railroads": "铁路运输",
    "real-estate-development": "房地产开发",
    "real-estate-diversified": "房地产综合",
    "real-estate-services": "房地产服务",
    "recreational-vehicles": "休闲车",
    "rental-and-leasing-services": "租赁服务",
    "residential-construction": "住宅建筑",
    "resorts-and-casinos": "度假村赌场",
    "restaurants": "餐饮",
    "scientific-and-technical-instruments": "科学仪器",
    "security-and-protection-services": "安防服务",
    "semiconductors": "半导体",
    "semiconductor-equipment-and-materials": "半导体设备",
    "shell-companies": "壳公司",
    "silver": "白银矿业",
    "software-infrastructure": "软件服务",
    "software-application": "应用软件",
    "solar": "光伏",
    "specialty-business-services": "商业服务",
    "specialty-chemicals": "精细化工",
    "specialty-industrial-machinery": "专用机械",
    "specialty-retail": "专业零售",
    "staffing-and-employment-services": "人力资源",
    "steel": "钢铁",
    "telecom-services": "电信服务",
    "telecommunication-services": "电信服务",
    "textile-manufacturing": "纺织制造",
    "thermal-coal": "动力煤",
    "tobacco": "烟草",
    "tools-and-accessories": "工具五金",
    "travel-services": "旅游服务",
    "trucking": "卡车运输",
    "utilities-diversified": "综合公用事业",
    "utilities-independent-power-producers": "独立发电",
    "utilities-regulated-electric": "电力公用事业",
    "utilities-regulated-gas": "燃气公用事业",
    "utilities-regulated-water": "水务公用事业",
    "utilities-renewable": "新能源公用事业",
    "uranium": "铀矿",
    "waste-management": "废物处理",
}

# 人工修正：stockanalysis 分类与常见认知有偏差的代码（采集时优先采用）
US_SECTOR_OVERRIDE: Dict[str, str] = {
    "CBRS": "半导体",     # Cerebras Systems：AI 芯片公司（站点归为软件）
    "WDC": "存储",       # 西部数据：硬盘/存储（站点归为电脑硬件）
    "SNDK": "存储",      # 闪迪：闪存（站点归为电脑硬件）
}


# ETF/基金/杠杆类（无行业页的代码直接归类，避免空跑）
US_ETF_CN: Dict[str, str] = {
    "NVDS": "杠杆ETF",
    "SKHY": "半导体",
    "SKHYV": "半导体",
    "SOXX": "半导体ETF",
    "SMH": "半导体ETF",
    "XLC": "通信ETF",
    "XLI": "工业ETF",
    "XLK": "科技ETF",
    "XLRE": "地产ETF",
    "XLP": "消费ETF",
    "XLF": "金融ETF",
    "XLU": "公用事业ETF",
    "XLE": "能源ETF",
    "XLY": "消费ETF",
    "XLV": "医疗ETF",
    "XLB": "材料ETF",
    "RSP": "标普等权ETF",
    "TLT": "长期国债ETF",
    "HYG": "高收益债ETF",
    "SPY": "标普500ETF",
    "IVV": "标普500ETF",
    "SHV": "国债ETF",
    "QQQ": "纳指ETF",
    "DIA": "道指ETF",
    "IWM": "罗素2000ETF",
    "VOO": "标普500ETF",
    "VTI": "全市场ETF",
    "ARKK": "创新ETF",
    "TQQQ": "纳指杠杆ETF",
    "SQQQ": "纳指反向ETF",
    "VIXY": "波动率ETF",
    "GLD": "黄金ETF",
    "SLV": "白银ETF",
    "IAU": "黄金ETF",
    "GDX": "黄金矿业ETF",
}


def _http_get(url: str, timeout: float = SA_TIMEOUT) -> Optional[str]:
    """urllib 直连抓取（本机 requests 走坏代理，必须 urllib）

    429 限流时抛 RateLimitedError，由调用方退避重试
    """
    try:
        req = urllib.request.Request(url, headers=SA_UA)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RateLimitedError()
        return None
    except Exception:
        return None


class RateLimitedError(Exception):
    """上游限流（HTTP 429），应减速重试"""



def parse_sa_sector(html: str) -> Optional[tuple]:
    """从 stockanalysis 个股页 HTML 解析 (slug, 英文行业名)"""
    m = _SA_RE.search(html)
    if m:
        return m.group(1).rstrip("/"), m.group(2).strip()
    m2 = _SA_RE2.search(html)
    if m2:
        return m2.group(1).rstrip("/"), m2.group(2).strip()
    return None


def fetch_us_sector_cn(symbol: str) -> Optional[str]:
    """抓取单只美股行业中文名（失败返回 None）

    - 已知 ETF/基金代码直接返回映射（无个股页）
    - 未知 slug 时返回英文行业名（有数据总比空好）
    - 429 限流时抛 RateLimitedError（批量采集内退避重试）
    """
    sym = (symbol or "").strip().upper()
    if not sym:
        return None
    if sym in US_SECTOR_OVERRIDE:
        return US_SECTOR_OVERRIDE[sym]
    if sym in US_ETF_CN:
        return US_ETF_CN[sym]
    html_text = _http_get(f"https://stockanalysis.com/stocks/{sym}/")
    if not html_text:
        return None
    parsed = parse_sa_sector(html_text)
    if not parsed:
        return None
    slug, name = parsed
    return US_SLUG_CN.get(slug, html.unescape(name))


def fetch_sectors_batch(symbols: List[str], workers: int = SA_WORKERS) -> Dict[str, str]:
    """并发批量采集行业，返回 {SYM: 中文行业}（失败的不在结果里）

    限流感知：429 退避重试 2 次；每请求间带最小间隔，避免触发上游限流
    """
    out: Dict[str, str] = {}
    seen: set = set()
    todo = []
    for s in symbols:
        s = (s or "").strip().upper()
        if s and s not in seen:
            seen.add(s)
            todo.append(s)
    if not todo:
        return out

    def _one(sym: str) -> Optional[str]:
        for delay in SA_RETRY_DELAYS:
            try:
                return fetch_us_sector_cn(sym)
            except RateLimitedError:
                time.sleep(delay)
        return None

    with ThreadPoolExecutor(max_workers=min(workers, len(todo))) as pool:
        futures = {}
        for s in todo:
            time.sleep(SA_BATCH_DELAY)
            futures[pool.submit(_one, s)] = s
        for fut in as_completed(futures):
            sym = futures[fut]
            try:
                sector = fut.result()
            except Exception as exc:
                logger.warning("[us-sector] %s 采集异常: %s", sym, exc)
                continue
            if sector:
                out[sym] = sector
    return out


def fill_missing_sectors(codes: Optional[List[str]] = None,
                         workers: int = SA_WORKERS) -> dict:
    """补采 sector 为空的标的并落库（幂等，可重复调用）

    Args:
        codes: 指定优先补采的代码（如刚同步的自选）；None 时补采全库空缺
    返回: {"checked": n, "filled": n, "failed": n, "skipped": n, "sectors": {...}}
    """
    now = datetime.now()
    checked = filled = failed = skipped = 0
    sectors: Dict[str, str] = {}

    with get_db_session() as db:
        q = db.query(USInstrument.symbol).filter(
            (USInstrument.sector.is_(None))
            | (USInstrument.sector == "")
        )
        if codes:
            clean = [c.strip().upper() for c in codes if c and c.strip()]
            if clean:
                q = q.filter(USInstrument.symbol.in_(clean))
        missing = [r[0] for r in q.all()]
    checked = len(missing)
    if not missing:
        return {"checked": 0, "filled": 0, "failed": 0, "skipped": 0,
                "sectors": {}, "message": "无缺失行业"}

    sectors = fetch_sectors_batch(missing, workers=workers)
    if sectors:
        with get_db_session() as db:
            for sym, sector in sectors.items():
                inst = db.query(USInstrument).filter(USInstrument.symbol == sym).first()
                if inst:
                    inst.sector = sector
                    inst.updated_at = now
                    filled += 1
            db.commit()
    failed = checked - len(sectors)
    skipped = 0
    logger.info("[us-sector] 补采完成: 检查 %d, 写入 %d, 失败 %d",
                checked, filled, failed)
    return {"checked": checked, "filled": filled, "failed": failed,
            "skipped": skipped, "sectors": sectors}


def backfill_sectors_async(codes: Optional[List[str]] = None):
    """后台线程补采（供同步流程调用，不阻塞）"""
    def _run():
        try:
            fill_missing_sectors(codes)
        except Exception as exc:
            logger.warning("[us-sector] 后台补采异常: %s", exc)
    t = threading.Thread(target=_run, name="us-sector-backfill", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    import sys
    codes = sys.argv[1:] or None
    result = fill_missing_sectors(codes)
    print(json.dumps(result, ensure_ascii=False, indent=2))
