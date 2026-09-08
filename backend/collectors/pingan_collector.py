"""
平安证券数据采集器
调用平安证券6个技能的API，将数据存入数据库

技能列表:
1. pa-market-query  - 行情查询（个股/板块/资金流向/K线）
2. pa-research-report - 研报检索
3. pa-news-search     - 资讯检索
4. pa-guyouquan-query - 股友圈社区查询
5. pa-etf-filter      - 场内ETF筛选
6. pa-mutual-fund-filter - 场外基金榜单

注意：各技能脚本的 get_data.py 模块名冲突，本采集器使用直接 HTTP 请求调用 API。
"""
import sys
import os
import json
import logging
import uuid
import requests
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.session import get_db_session
from db.models import (
    PingAnStockQuote, PingAnSectorQuote, PingAnSectorStocks,
    PingAnFundFlow, PingAnKline, PingAnResearchReport,
    PingAnNews, PingAnGuYouQuan, PingAnEtfScreen, PingAnFundRank, StockDailyKline,
)

logger = logging.getLogger(__name__)

# ---- 获取 API Key ----
try:
    from config import PINGAN_SKILL_APIKEY
except Exception:
    PINGAN_SKILL_APIKEY = os.environ.get('PINGAN_SKILL_APIKEY', '')
PINGAN_AVAILABLE = bool(PINGAN_SKILL_APIKEY)

# ---- 行情查询 API 配置 ----
MARKET_AVAILABLE = False
if PINGAN_AVAILABLE:
    MARKET_AVAILABLE = True

MARKET_BASE_URL = "https://ai.stock.pingan.com"
MARKET_SKILL_PREFIX = "restapi/hangqing"
MARKET_SKILL_ID = "market-query"
MARKET_API_PATHS = {
    "quote": "adapter/hangQing/stockDynamic",
    "sector": "adapter/hangQing/blockDynamic",
    "sector_stocks": "adapter/hangQing/constituentDynamic",
    "fundflow": "adapter/hangQing/capitalFlow",
    "kline": "adapter/hangQing/klineData",
}

ETF_BASE_URL = "https://ai.stock.pingan.com"
ETF_API_PATH = "restapi/jinku/omm/v2/http/mop/vault/query"
ETF_SKILL_ID = "etf-filter"


def _is_limit_error(exc: Exception) -> bool:
    message = str(exc)
    return "频率超限" in message or "次数已达上限" in message or "超过限制" in message


def _market_call_api(options: str, payload: dict) -> dict:
    """调用行情查询 API"""
    path = MARKET_API_PATHS.get(options)
    if not path:
        raise RuntimeError(f"未知行情接口: {options}")

    url = f"{MARKET_BASE_URL}/{MARKET_SKILL_PREFIX}/{path}"
    headers = {
        "X-API-Key": PINGAN_SKILL_APIKEY,
        "Content-Type": "application/json",
        "X-Skill-ID": MARKET_SKILL_ID,
        "X-Request-ID": str(uuid.uuid4()),
        "channelId": "c_lite_adapgaty_a_skill",
        "requestId": str(uuid.uuid4()),
    }
    response = requests.post(url, json=payload, headers=headers, timeout=60)

    if response.status_code == 401:
        raise RuntimeError("缺少 API Key。")
    if response.status_code == 403:
        raise RuntimeError("API Key 无效或没有权限。")
    if response.status_code == 429:
        body = response.json()
        error_code = body.get("error_code")
        if error_code == "RATE_LIMIT_EXCEEDED":
            raise RuntimeError("接口调用频率超限。")
        if error_code == "DAILY_QUOTA_EXCEEDED":
            raise RuntimeError("今日调用次数已达上限。")
        raise RuntimeError("请求超过限制。")
    if response.status_code == 503:
        raise RuntimeError("服务暂时不可用，请稍后重试。")

    response.raise_for_status()
    body = response.json()
    if body.get("code") != 0:
        raise RuntimeError(body.get("error_message", "接口调用失败。"))
    return body.get("data", {})


def _etf_call_api(payload: dict):
    """调用平安场内 ETF 筛选；字段单位按 pa-etf-filter skill 原始定义保留。"""
    if not PINGAN_AVAILABLE:
        raise RuntimeError("缺少 API Key。")
    body = dict(payload)
    body["key"] = "ETF_FILTER"
    response = requests.post(
        f"{ETF_BASE_URL}/{ETF_API_PATH}",
        json=body,
        headers={
            "X-API-Key": PINGAN_SKILL_APIKEY,
            "Content-Type": "application/json",
            "X-Skill-ID": ETF_SKILL_ID,
            "X-Request-ID": str(uuid.uuid4()),
        },
        timeout=60,
    )
    if response.status_code == 401:
        raise RuntimeError("缺少 API Key。")
    if response.status_code == 403:
        raise RuntimeError("API Key 无效或没有权限。")
    if response.status_code == 429:
        error_code = (response.json() or {}).get("error_code")
        if error_code == "DAILY_QUOTA_EXCEEDED":
            raise RuntimeError("今日调用次数已达上限。")
        raise RuntimeError("接口调用频率超限。")
    if response.status_code == 503:
        raise RuntimeError("服务暂时不可用，请稍后重试。")
    response.raise_for_status()
    result = response.json()
    return result.get("rows", []) or result


def _optional_float(value, multiplier=1.0):
    if value in (None, ""):
        return None
    text = str(value).strip().replace(',', '')
    if text.lower() in ('null', 'none', 'nan', 'n/a', '--'):
        return None
    if text.endswith('%'):
        # 带百分号的数据已经是百分点，不能再按 ETF 小数口径乘 100。
        return float(text[:-1])
    return float(text) * multiplier


def _pingan_code_to_ts_code(code: str) -> str:
    """将平安市场代码转换为统一日K表使用的 ts_code。"""
    raw = str(code or '').strip().upper()
    if raw.startswith('SH') and len(raw) == 8:
        return f'{raw[2:]}.SH'
    if raw.startswith('SZ') and len(raw) == 8:
        return f'{raw[2:]}.SZ'
    return raw


def _watchlist_code_to_pingan_code(code: str) -> str:
    """A股代码映射；5 开头场内 ETF 属沪市，不能按普通深市规则处理。"""
    raw = str(code or '').strip()
    return f"{'SH' if raw.startswith(('5', '6', '9')) else 'SZ'}{raw}"


def pingan_collect_industry_etfs(trade_date=None):
    """缓存流动性靠前的行业主题 ETF，供 A 股行业轮动页盘后读取。"""
    target = trade_date or date.today()
    rows = _etf_call_api({
        "wheres": [{"field": "fundType1", "type": 5, "value": "行业主题"}],
        "fields": "code,etfName,fundType1,fundType2,indexName,scope,turnVolume20,dayRise20,oneYearRise,pe,pb",
        "orderBy": "turnVolume20",
        "orderType": "D",
        "pageSize": 100,
    })
    if not isinstance(rows, list):
        raise RuntimeError("ETF 筛选返回格式异常")

    with get_db_session() as db:
        db.query(PingAnEtfScreen).filter(PingAnEtfScreen.trade_date == target).delete()
        for item in rows:
            code = str(item.get("code") or "").strip()
            if not code:
                continue
            db.add(PingAnEtfScreen(
                trade_date=target,
                etf_code=code,
                etf_name=item.get("etfName"),
                etf_type=item.get("fundType2") or item.get("fundType1"),
                fund_size=_optional_float(item.get("scope")),
                pe=_optional_float(item.get("pe")),
                pb=_optional_float(item.get("pb")),
                tracking_index=item.get("indexName"),
                return_20d_pct=_optional_float(item.get("dayRise20"), 100),
                return_1y_pct=_optional_float(item.get("oneYearRise"), 100),
                amount_20d=_optional_float(item.get("turnVolume20")),
                source="pingan_etf_filter",
            ))
        db.commit()
    logger.info('[pingan] collected %d industry ETFs for %s', len(rows), target)
    try:
        from api.sector_rotation import invalidate_cache
        invalidate_cache(target, persisted=True)
    except Exception as exc:
        logger.warning('[pingan] sector rotation cache invalidation skipped: %s', exc)
    return len(rows)


# ============================================================
# 1. 行情查询 - 个股/ETF/股指实时行情
# ============================================================

def pingan_collect_quotes(codes, batch_size=5):
    """
    批量采集个股实时行情并存入数据库
    codes: ["SH600519", "SZ000001", ...] 最多5个
    """
    if not MARKET_AVAILABLE:
        logger.warning('[pingan] market-query not available')
        return 0
    count = 0
    now = datetime.now()
    trade_date = now.date()
    snapshot_time = now

    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        try:
            result = _market_call_api('quote', {"codes": batch})
            items = result.get('items', []) if isinstance(result, dict) else result
            if not items:
                continue

            with get_db_session() as db:
                for item in items:
                    rec = PingAnStockQuote(
                        trade_date=trade_date,
                        code=item.get('code', ''),
                        name=item.get('name', ''),
                        price=float(item.get('price', 0) or 0),
                        change=_optional_float(item.get('change')) or 0,
                        change_pct=_optional_float(item.get('change_pct')) or 0,
                        open=float(item.get('open', 0) or 0),
                        high=float(item.get('high', 0) or 0),
                        low=float(item.get('low', 0) or 0),
                        prev_close=float(item.get('prev_close', 0) or 0),
                        volume=int(item.get('volume', 0) or 0),
                        amount=float(item.get('amount', 0) or 0),
                        turnover_pct=_optional_float(item.get('turnover_pct')),
                        pe_ttm=float(item.get('pe_ttm', 0) or 0) if item.get('pe_ttm') else None,
                        pb=float(item.get('pb', 0) or 0) if item.get('pb') else None,
                        market_cap=float(item.get('market_cap', 0) or 0) if item.get('market_cap') else None,
                        circ_market_cap=float(item.get('circ_market_cap', 0) or 0) if item.get('circ_market_cap') else None,
                        snapshot_time=snapshot_time,
                    )
                    db.add(rec)
                    count += 1
                db.commit()
        except Exception as e:
            if _is_limit_error(e):
                logger.warning('[pingan] quote collection stopped: %s', e)
                break
            logger.error('[pingan] collect quotes error: %s', e, exc_info=True)
    logger.info('[pingan] collected %d quotes', count)
    return count


# ============================================================
# 2. 行情查询 - 板块实时行情
# ============================================================

def pingan_collect_sectors(sector_codes):
    """采集板块实时行情"""
    if not MARKET_AVAILABLE:
        return 0
    count = 0
    now = datetime.now()
    trade_date = now.date()
    snapshot_time = now

    for sc in sector_codes:
        try:
            result = _market_call_api('sector', {"sector_code": sc})
            if isinstance(result, dict):
                items = result.get('items', [result])
            else:
                items = result if isinstance(result, list) else [result]

            with get_db_session() as db:
                for item in items if isinstance(items, list) else [items]:
                    if not item or not item.get('sector_code'):
                        continue
                    rec = PingAnSectorQuote(
                        trade_date=trade_date,
                        sector_code=item.get('sector_code', ''),
                        sector_name=item.get('sector_name', ''),
                        change_pct=_optional_float(item.get('change_pct')) or 0,
                        leading_stock_code=item.get('leading_stock_code', ''),
                        leading_stock_name=item.get('leading_stock_name', ''),
                        leading_stock_change_pct=_optional_float(item.get('leading_stock_change_pct')),
                        amount=float(item.get('amount', 0) or 0) if item.get('amount') else None,
                        stock_count=int(item.get('stock_count', 0) or 0) if item.get('stock_count') else None,
                        up_count=int(item.get('up_count', 0) or 0) if item.get('up_count') else None,
                        down_count=int(item.get('down_count', 0) or 0) if item.get('down_count') else None,
                        flat_count=int(item.get('flat_count', 0) or 0) if item.get('flat_count') else None,
                        snapshot_time=snapshot_time,
                    )
                    db.add(rec)
                    count += 1
                db.commit()
        except Exception as e:
            if _is_limit_error(e):
                logger.warning('[pingan] sector collection stopped: %s', e)
                break
            logger.error('[pingan] collect sector error %s: %s', sc, e)
    logger.info('[pingan] collected %d sector quotes', count)
    return count


# ============================================================
# 3. 行情查询 - 主力资金流向
# ============================================================

def pingan_collect_fundflow(codes):
    """采集主力资金流向"""
    if not MARKET_AVAILABLE:
        return 0
    count = 0
    now = datetime.now()
    trade_date = now.date()
    snapshot_time = now

    for i in range(0, len(codes), 5):
        batch = codes[i:i + 5]
        try:
            result = _market_call_api('fundflow', {"codes": batch})
            items = result.get('items', []) if isinstance(result, dict) else result
            if not items:
                continue

            with get_db_session() as db:
                for item in items:
                    rec = PingAnFundFlow(
                        trade_date=trade_date,
                        code=item.get('code', ''),
                        name=item.get('name', ''),
                        main_net_inflow=float(item.get('main_net_inflow', 0) or 0),
                        main_net_inflow_pct=_optional_float(item.get('main_net_inflow_pct')),
                        super_large_net_inflow=float(item.get('super_large_net_inflow', 0) or 0) if item.get('super_large_net_inflow') else None,
                        large_net_inflow=float(item.get('large_net_inflow', 0) or 0) if item.get('large_net_inflow') else None,
                        amount=float(item.get('amount', 0) or 0) if item.get('amount') else None,
                        snapshot_time=snapshot_time,
                    )
                    db.add(rec)
                    count += 1
                db.commit()
        except Exception as e:
            if _is_limit_error(e):
                logger.warning('[pingan] fundflow collection stopped: %s', e)
                break
            logger.error('[pingan] collect fundflow error: %s', e)
    logger.info('[pingan] collected %d fundflow records', count)
    return count


# ============================================================
# 4. 行情查询 - 历史K线
# ============================================================

def pingan_collect_kline(code, last_n=180):
    """采集历史K线，并写入平安归档与统一 stock_daily_kline。"""
    if not MARKET_AVAILABLE:
        return 0
    count = 0
    try:
        result = _market_call_api('kline', {"code": code, "last_n": last_n})
        items = result.get('items', []) if isinstance(result, dict) else result
        if not items:
            return 0

        ts_code = _pingan_code_to_ts_code(code)
        with get_db_session() as db:
            standard_rows = []
            for item in items:
                name = item.get('name', '')
                bars = item.get('bars', [])
                for bar in bars:
                    trade_date_str = bar.get('date', '')
                    if not trade_date_str:
                        continue
                    try:
                        td = datetime.strptime(trade_date_str, '%Y-%m-%d').date()
                    except ValueError:
                        continue

                    open_price = _optional_float(bar.get('open'))
                    high_price = _optional_float(bar.get('high'))
                    low_price = _optional_float(bar.get('low'))
                    close_price = _optional_float(bar.get('close'))
                    if close_price is None:
                        continue
                    change_pct = _optional_float(bar.get('change_pct'))
                    volume = int(_optional_float(bar.get('volume')) or 0)
                    amount = _optional_float(bar.get('amount'))
                    standard_rows.append({
                        'ts_code': ts_code,
                        'trade_date': td,
                        'open': open_price,
                        'high': high_price,
                        'low': low_price,
                        'close': close_price,
                        'volume': volume,
                        'amount': amount,
                        'pct_chg': change_pct,
                    })

                    existing = db.query(PingAnKline).filter(
                        PingAnKline.code == code,
                        PingAnKline.trade_date == td
                    ).first()
                    if existing:
                        continue

                    rec = PingAnKline(
                        code=code,
                        name=name,
                        trade_date=td,
                        open=open_price,
                        high=high_price,
                        low=low_price,
                        close=close_price,
                        change_pct=change_pct,
                        volume=volume,
                        amount=amount,
                    )
                    db.add(rec)
                    count += 1

            if standard_rows:
                from sqlalchemy.dialects.postgresql import insert as pg_insert
                stmt = pg_insert(StockDailyKline.__table__).values(standard_rows)
                stmt = stmt.on_conflict_do_update(
                    index_elements=['ts_code', 'trade_date'],
                    set_={
                        'open': stmt.excluded.open,
                        'high': stmt.excluded.high,
                        'low': stmt.excluded.low,
                        'close': stmt.excluded.close,
                        'volume': stmt.excluded.volume,
                        'amount': stmt.excluded.amount,
                        'pct_chg': stmt.excluded.pct_chg,
                    },
                )
                db.execute(stmt)
                db.commit()
    except Exception as e:
        logger.error('[pingan] collect kline error for %s: %s', code, e)
    logger.info('[pingan] collected %d kline records for %s', count, code)
    return count


# ============================================================
# 5. 定时采集：采集自选股行情 + 资金流向
# ============================================================

def pingan_scheduled_collect():
    """
    定时采集主函数 - 由 APScheduler 调用
    采集内容：
    1. 自选股实时行情
    2. 自选股资金流向
    3. 15:00 后缓存行业主题 ETF（每日一次）
    """
    if not MARKET_AVAILABLE:
        logger.warning('[pingan] market-query not available, skipping scheduled collection')
        return

    logger.info('[pingan] starting scheduled collection')

    try:
        now = datetime.now()
        if now.hour >= 15:
            with get_db_session() as db:
                etf_exists = db.query(PingAnEtfScreen.id).filter(
                    PingAnEtfScreen.trade_date == now.date()
                ).first()
            if not etf_exists:
                try:
                    pingan_collect_industry_etfs(now.date())
                except Exception as exc:
                    logger.warning('[pingan] industry ETF collection skipped: %s', exc)

        from db.models import Watchlist
        with get_db_session() as db:
            watchlist = db.query(Watchlist).all()

        codes = []
        for w in watchlist:
            code = w.stock_code
            if len(code) == 6:
                pingan_code = _watchlist_code_to_pingan_code(code)
                codes.append(pingan_code)

        if codes:
            logger.info('[pingan] collecting quotes for %d stocks', len(codes))
            pingan_collect_quotes(codes)

            logger.info('[pingan] collecting fundflow for %d stocks', len(codes))
            pingan_collect_fundflow(codes)

        if now.hour >= 15:
            try:
                from collectors.sync_daily_kline import sync_watchlist_etf_klines
                sync_watchlist_etf_klines(now.strftime('%Y%m%d'))
            except Exception as exc:
                logger.warning('[pingan] ETF kline collection skipped: %s', exc)
        else:
            logger.info('[pingan] no watchlist stocks; quote/fundflow collection skipped')

        logger.info('[pingan] scheduled collection completed')

    except Exception as e:
        logger.error('[pingan] scheduled collection error: %s', e, exc_info=True)


# ============================================================
# 测试入口
# ============================================================

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    print('=== 平安证券数据采集器测试 ===')
    print(f'PINGAN_AVAILABLE: {PINGAN_AVAILABLE}')
    print(f'MARKET_AVAILABLE: {MARKET_AVAILABLE}')

    if MARKET_AVAILABLE:
        print('\n--- 测试行情查询 ---')
        c = pingan_collect_quotes(['SH600519', 'SZ000001'])
        print(f'  quotes: {c}')

        print('\n--- 测试资金流向 ---')
        c = pingan_collect_fundflow(['SH600519'])
        print(f'  fundflow: {c}')

        print('\n--- 测试K线采集 ---')
        c = pingan_collect_kline('SH600519', last_n=5)
        print(f'  kline: {c}')
