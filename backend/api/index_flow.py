"""
指数资金流向 API

数据源优先级：
1. 数据库 stock_flow 表（按指数成分股聚合，已有完整 T-1 数据）
2. 东方财富 push2his.eastmoney.com（仅当数据库无数据时降级使用）

覆盖主要 A 股指数：沪深300/上证50/上证综指/科创50/中证500/中证1000/创业板指/深证成指/中小板指

聚合方式：
- 宽基指数（沪深300/上证50/中证500/中证1000）：内置核心权重成分股列表
- 市场指数（上证综指/深证成指/创业板指/中小板指/科创50）：按代码前缀聚合
"""
import time
import json
import logging
import asyncio
import urllib.request
import urllib.parse
from datetime import datetime, date, timedelta
from typing import Optional
from fastapi import APIRouter, Query, HTTPException
from sqlalchemy import func, and_, or_

from db.session import get_db_session
from db.models import StockFlow

logger = logging.getLogger(__name__)
router = APIRouter()

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
except Exception as e:
    ak = None
    AKSHARE_AVAILABLE = False
    logger.warning(f'[index_flow] akshare 导入失败: {e}')

# ============================================================
# 宽基指数定义（保留用于 /api/index-flow/broad-rank）
# - members: 内置核心权重成分股（覆盖 50%+ 权重），按权重股精选
# - prefix: 当 members 为空时，按代码前缀聚合整个市场板块
# ============================================================

# 上证50 核心权重股（按权重排序前 40 只，覆盖 ~70% 权重）
_SSE50_MEMBERS = [
    '600519.SH', '601318.SH', '600036.SH', '601166.SH', '600276.SH',
    '601398.SH', '600900.SH', '601939.SH', '601857.SH', '600030.SH',
    '601628.SH', '600000.SH', '601288.SH', '601336.SH', '600016.SH',
    '601088.SH', '600690.SH', '601166.SH', '600028.SH', '601618.SH',
    '600048.SH', '600585.SH', '601888.SH', '600196.SH', '600887.SH',
    '601066.SH', '601601.SH', '600438.SH', '600406.SH', '601012.SH',
    '600089.SH', '601211.SH', '600009.SH', '601229.SH', '601981.SH',
    '600745.SH', '601800.SH', '600588.SH', '601138.SH', '600436.SH',
]

# 沪深300 核心权重股（按权重排序前 80 只，覆盖 ~50% 权重）
_CSI300_MEMBERS = _SSE50_MEMBERS + [
    '000651.SZ', '000333.SZ', '000858.SZ', '002594.SZ', '000568.SZ',
    '002415.SZ', '000063.SZ', '300750.SZ', '300059.SZ', '000725.SZ',
    '002475.SZ', '000338.SZ', '002271.SZ', '000002.SZ', '000538.SZ',
    '002352.SZ', '300760.SZ', '000625.SZ', '002230.SZ', '000596.SZ',
    '002304.SZ', '000876.SZ', '000708.SZ', '002241.SZ', '000999.SZ',
    '002736.SZ', '300015.SZ', '300124.SZ', '300498.SZ', '300142.SZ',
    '002128.SZ', '000100.SZ', '002508.SZ', '300274.SZ', '002120.SZ',
    '002470.SZ', '300308.SZ', '300661.SZ', '300316.SZ', '300285.SZ',
]

# 中证500 核心权重股（精选 60 只中盘股）
_CSI500_MEMBERS = [
    '600089.SH', '600118.SH', '600196.SH', '600199.SH', '600208.SH',
    '600260.SH', '600298.SH', '600372.SH', '600390.SH', '600426.SH',
    '600433.SH', '600436.SH', '600438.SH', '600487.SH', '600489.SH',
    '600507.SH', '600521.SH', '600549.SH', '600559.SH', '600580.SH',
    '600584.SH', '600586.SH', '600588.SH', '600600.SH', '600660.SH',
    '600674.SH', '600685.SH', '600699.SH', '600703.SH', '600707.SH',
    '600737.SH', '600745.SH', '600760.SH', '600776.SH', '600779.SH',
    '600801.SH', '600809.SH', '600837.SH', '600839.SH', '600867.SH',
    '000012.SZ', '000402.SZ', '000425.SZ', '000503.SZ', '000516.SZ',
    '000572.SZ', '000617.SZ', '000626.SZ', '000681.SZ', '000685.SZ',
    '000708.SZ', '000712.SZ', '000716.SZ', '000733.SZ', '000758.SZ',
    '000768.SZ', '000776.SZ', '000778.SZ', '000799.SZ', '000800.SZ',
]

# 中证1000 核心权重股（精选 80 只小盘股）
_CSI1000_MEMBERS = [
    '600179.SH', '600193.SH', '600222.SH', '600228.SH', '600243.SH',
    '600257.SH', '600282.SH', '600305.SH', '600309.SH', '600311.SH',
    '600313.SH', '600320.SH', '600345.SH', '600356.SH', '600363.SH',
    '600365.SH', '600378.SH', '600381.SH', '600382.SH', '600388.SH',
    '600391.SH', '600398.SH', '600416.SH', '600420.SH', '600429.SH',
    '600435.SH', '600444.SH', '600452.SH', '600455.SH', '600458.SH',
    '600460.SH', '600469.SH', '600477.SH', '600478.SH', '600482.SH',
    '600493.SH', '600495.SH', '600497.SH', '600498.SH', '600502.SH',
    '000009.SZ', '000014.SZ', '000017.SZ', '000019.SZ', '000020.SZ',
    '000021.SZ', '000028.SZ', '000031.SZ', '000034.SZ', '000038.SZ',
    '000045.SZ', '000048.SZ', '000049.SZ', '000050.SZ', '000055.SZ',
    '000056.SZ', '000058.SZ', '000059.SZ', '000061.SZ', '000062.SZ',
    '002001.SZ', '002003.SZ', '002006.SZ', '002008.SZ', '002010.SZ',
    '002013.SZ', '002016.SZ', '002019.SZ', '002021.SZ', '002023.SZ',
    '002025.SZ', '002026.SZ', '002028.SZ', '002030.SZ', '002031.SZ',
    '300001.SZ', '300002.SZ', '300003.SZ', '300004.SZ', '300005.SZ',
]

# 科创50 核心权重股
_STAR50_MEMBERS = [
    '688599.SH', '688111.SH', '688981.SH', '688256.SH', '688041.SH',
    '688235.SH', '688036.SH', '688169.SH', '688185.SH', '688112.SH',
    '688126.SH', '688200.SH', '688202.SH', '688223.SH', '688303.SH',
    '688315.SH', '688331.SH', '688333.SH', '688369.SH', '688396.SH',
    '688398.SH', '688433.SH', '688439.SH', '688466.SH', '688472.SH',
    '688498.SH', '688506.SH', '688521.SH', '688526.SH', '688528.SH',
    '688551.SH', '688565.SH', '688567.SH', '688568.SH', '688577.SH',
    '688585.SH', '688586.SH', '688590.SH', '688595.SH', '688596.SH',
]

# 上证红利核心成分股
_SSE_DIVIDEND_MEMBERS = [
    '601288.SH', '601398.SH', '601939.SH', '601328.SH', '600000.SH',
    '601166.SH', '600036.SH', '601006.SH', '600900.SH', '601088.SH',
    '601857.SH', '600028.SH', '601988.SH', '600019.SH', '601866.SH',
    '600372.SH', '600188.SH', '601225.SH', '600350.SH', '600012.SH',
]

# 创业板指核心权重股
_CHINEXT_MEMBERS = [
    '300750.SZ', '300059.SZ', '300760.SZ', '300015.SZ', '300124.SZ',
    '300498.SZ', '300142.SZ', '300274.SZ', '300316.SZ', '300285.SZ',
    '300661.SZ', '308308.SZ', '300308.SZ', '300012.SZ', '300003.SZ',
    '300015.SZ', '300024.SZ', '300033.SZ', '300054.SZ', '300088.SZ',
    '300122.SZ', '300133.SZ', '300168.SZ', '300182.SZ', '300212.SZ',
    '300223.SZ', '300251.SZ', '300257.SZ', '300296.SZ', '300347.SZ',
    '300357.SZ', '300383.SZ', '300418.SZ', '300433.SZ', '300458.SZ',
    '300476.SZ', '300496.SZ', '300502.SZ', '300529.SZ', '300554.SZ',
]

# 中小板指核心权重股
_SME_MEMBERS = [
    '002594.SZ', '002415.SZ', '002475.SZ', '002230.SZ', '002352.SZ',
    '002271.SZ', '002304.SZ', '002470.SZ', '002508.SZ', '002128.SZ',
    '002120.SZ', '002241.SZ', '002273.SZ', '002281.SZ', '002311.SZ',
    '002340.SZ', '002371.SZ', '002384.SZ', '002390.SZ', '002405.SZ',
    '002416.SZ', '002456.SZ', '002460.SZ', '002466.SZ', '002468.SZ',
    '002475.SZ', '002493.SZ', '002500.SZ', '002507.SZ', '002511.SZ',
    '002526.SZ', '002527.SZ', '002534.SZ', '002568.SZ', '002572.SZ',
    '002590.SZ', '002601.SZ', '002602.SZ', '002607.SZ', '002624.SZ',
]

# 深证50 核心权重股
_SZSE50_MEMBERS = [
    '000651.SZ', '000333.SZ', '000858.SZ', '002594.SZ', '000568.SZ',
    '002415.SZ', '000063.SZ', '300750.SZ', '300059.SZ', '000725.SZ',
    '002475.SZ', '000338.SZ', '002271.SZ', '000002.SZ', '000538.SZ',
    '002352.SZ', '300760.SZ', '000625.SZ', '002230.SZ', '000596.SZ',
    '002304.SZ', '000876.SZ', '000708.SZ', '002241.SZ', '000999.SZ',
    '002736.SZ', '300015.SZ', '300124.SZ', '300498.SZ', '300142.SZ',
    '002128.SZ', '000100.SZ', '002508.SZ', '300274.SZ', '002120.SZ',
    '002470.SZ', '300308.SZ', '300661.SZ', '300316.SZ', '300285.SZ',
    '000733.SZ', '000768.SZ', '000776.SZ', '000783.SZ', '000786.SZ',
]


# 宽基指数列表（secid 仅用于东方财富降级；DB 聚合不依赖 secid）
MAJOR_INDICES = [
    {'ts_code': '000001.SH', 'name': '上证指数',   'prefix': ['60', '688'], 'members': None},
    {'ts_code': '000016.SH', 'name': '上证50',    'prefix': None, 'members': _SSE50_MEMBERS, 'secid': '1.000016'},
    {'ts_code': '000300.SH', 'name': '沪深300',   'prefix': None, 'members': _CSI300_MEMBERS, 'secid': '1.000300'},
    {'ts_code': '000905.SH', 'name': '中证500',   'prefix': None, 'members': _CSI500_MEMBERS, 'secid': '1.000905'},
    {'ts_code': '000852.SH', 'name': '中证1000',  'prefix': None, 'members': _CSI1000_MEMBERS, 'secid': '1.000852'},
    {'ts_code': '000688.SH', 'name': '科创50',    'prefix': None, 'members': _STAR50_MEMBERS, 'secid': '1.000688'},
    {'ts_code': '000015.SH', 'name': '上证红利',  'prefix': None, 'members': _SSE_DIVIDEND_MEMBERS, 'secid': '1.000015'},
    {'ts_code': '399001.SZ', 'name': '深证成指',   'prefix': ['00'], 'members': None, 'secid': '0.399001'},
    {'ts_code': '399006.SZ', 'name': '创业板指',   'prefix': None, 'members': _CHINEXT_MEMBERS, 'secid': '0.399006'},
    {'ts_code': '399005.SZ', 'name': '中小板指',   'prefix': None, 'members': _SME_MEMBERS, 'secid': '0.399005'},
    {'ts_code': '399016.SZ', 'name': '深证50',    'prefix': None, 'members': _SZSE50_MEMBERS, 'secid': '0.399016'},
]

# 行业主题指数列表（按成分股聚合 stock_flow，匹配截图维度）
THEME_INDICES = [
    # 国证指数（CNI）
    {'ts_code': '980017.CNI', 'name': '国证芯片',        'type': 'cni', 'secid': '0.980017'},
    {'ts_code': '980022.CNI', 'name': '国证机器人产业',  'type': 'cni', 'secid': '0.980022'},
    {'ts_code': '980032.CNI', 'name': '国证新能源',      'type': 'cni', 'secid': '0.980032'},
    {'ts_code': '980030.CNI', 'name': '国证军工',        'type': 'cni', 'secid': '0.980030'},
    {'ts_code': '980048.CNI', 'name': '国证生物医药',    'type': 'cni', 'secid': '0.980048'},
    # 中证指数（CSI）
    {'ts_code': '399975.SZ',  'name': '中证证券公司',    'type': 'csi', 'secid': '0.399975'},
    {'ts_code': '931743.CSI', 'name': '半导体材料设备',  'type': 'csi', 'secid': '0.931743'},
    {'ts_code': '399967.SZ',  'name': '中证军工',        'type': 'csi', 'secid': '0.399967'},
    {'ts_code': '399997.SZ',  'name': '中证白酒',        'type': 'csi', 'secid': '0.399997'},
    {'ts_code': '399989.SZ',  'name': '中证医疗',        'type': 'csi', 'secid': '0.399989'},
    {'ts_code': '931151.CSI', 'name': '光伏产业',        'type': 'csi', 'secid': '0.931151'},
    {'ts_code': '930713.CSI', 'name': '人工智能',        'type': 'csi', 'secid': '0.930713'},
]

# 缓存
_rank_cache = {'data': None, 'ts': 0}
_broad_rank_cache = {'data': None, 'ts': 0}
_history_cache = {}  # ts_code -> {'data':..., 'ts':...}
_constituent_cache = {}  # ts_code -> {'members': [...], 'ts':...}
_RANK_CACHE_TTL = 300  # 5 分钟
_HISTORY_CACHE_TTL = 300
_CONSTITUENT_CACHE_TTL = 86400  # 成分股日频更新，缓存 1 天


# ============================================================
# 数据库聚合（主数据源）
# ============================================================

def _get_index_constituents(ts_code: str, index_type: str) -> list:
    """从 akshare 获取指数成分股列表，返回 [ts_code, ...]

    index_type: 'cni' 调用 index_detail_cni; 'csi' 调用 index_stock_cons_weight_csindex
    """
    if not AKSHARE_AVAILABLE or not ak:
        return []
    cache_key = f'{ts_code}:{index_type}'
    cached = _constituent_cache.get(cache_key)
    if cached and time.time() - cached['ts'] < _CONSTITUENT_CACHE_TTL:
        return cached['members']

    raw_code = ts_code.split('.')[0]
    members = []
    try:
        if index_type == 'cni':
            df = ak.index_detail_cni(symbol=raw_code)
            codes = df['样本代码'].astype(str).str.zfill(6).tolist()
        elif index_type == 'csi':
            df = ak.index_stock_cons_weight_csindex(symbol=raw_code)
            codes = df['成分券代码'].astype(str).str.zfill(6).tolist()
        else:
            codes = []
        for c in codes:
            if c.startswith('6') or c.startswith('8') or c.startswith('9'):
                members.append(f'{c}.SH')
            else:
                members.append(f'{c}.SZ')
    except Exception as e:
        logger.warning(f'[index_flow] 获取 {ts_code} 成分股失败: {e}')
        return []

    _constituent_cache[cache_key] = {'members': members, 'ts': time.time()}
    return members


def _build_member_filter(idx_def: dict):
    """根据指数定义构建成员过滤条件（SQLAlchemy expression）"""
    members = idx_def.get('members')
    # 行业主题指数：动态获取成分股
    if not members and idx_def.get('type') in ('cni', 'csi'):
        members = _get_index_constituents(idx_def['ts_code'], idx_def['type'])
    if members:
        return StockFlow.ts_code.in_(members)
    elif idx_def.get('prefix'):
        prefix = idx_def['prefix']
        if len(prefix) == 1:
            return StockFlow.ts_code.like(f'{prefix[0]}%')
        else:
            return or_(*[StockFlow.ts_code.like(f'{p}%') for p in prefix])
    return None


def _aggregate_index_from_db(idx_def: dict, db, latest_n_days: int = 12) -> dict:
    """从 stock_flow 表聚合单个指数最近 N 天的资金流向

    返回：{ts_code, name, dates: [...], main_net: [...], cumulative: [...],
           inflow_1d, inflow_3d, inflow_5d, inflow_10d, close, pct_change, member_count}
    """
    member_filter = _build_member_filter(idx_def)
    if member_filter is None:
        return None

    # 取最近 N 个交易日的数据，按 trade_date 聚合
    rows = db.query(
        StockFlow.trade_date,
        func.sum(StockFlow.main_force_inflow).label('main_net'),
        func.avg(StockFlow.price_chg).label('avg_chg'),
        func.avg(StockFlow.price).label('avg_close'),
        func.count('*').label('member_count'),
    ).filter(member_filter).group_by(
        StockFlow.trade_date
    ).order_by(
        StockFlow.trade_date.desc()
    ).limit(latest_n_days).all()

    if not rows:
        return None

    # rows 是倒序，反转为正序
    rows = list(reversed(rows))

    dates = [r.trade_date.strftime('%Y-%m-%d') if hasattr(r.trade_date, 'strftime') else str(r.trade_date) for r in rows]
    # main_force_inflow 字段在 DB 中单位是「万元」，统一转换为「元」与东方财富 API 一致
    _YI_TO_YUAN = 1e4
    main_nets = [float(r.main_net or 0) * _YI_TO_YUAN for r in rows]
    avg_chgs = [float(r.avg_chg or 0) for r in rows]
    avg_closes = [float(r.avg_close or 0) for r in rows]
    member_counts = [int(r.member_count or 0) for r in rows]

    # 累计净流入
    cumulative = []
    total = 0
    for v in main_nets:
        total += v
        cumulative.append(total)

    # 取最新日数据
    latest_row = rows[-1]
    latest_close = avg_closes[-1] if avg_closes else None
    latest_pct = avg_chgs[-1] if avg_chgs else None

    # 1/3/5/10 日累计主力净流入
    def _sum_last(n):
        return sum(main_nets[-n:]) if len(main_nets) >= n else sum(main_nets)

    return {
        'ts_code': idx_def['ts_code'],
        'name': idx_def['name'],
        'dates': dates,
        'main_net': main_nets,
        'cumulative': cumulative,
        'inflow_1d': _sum_last(1),
        'inflow_3d': _sum_last(3),
        'inflow_5d': _sum_last(5),
        'inflow_10d': _sum_last(10),
        'close': latest_close,
        'pct_change': latest_pct,
        'member_count': member_counts[-1] if member_counts else 0,
        'latest_date': dates[-1] if dates else None,
    }


# ============================================================
# 东方财富 API 降级（仅当数据库缺数据时使用）
# ============================================================

# 东方财富接口基础URL
_EM_FFLOW_URL = 'https://push2his.eastmoney.com/api/qt/stock/fflow/daykline/get'
_EM_QUOTE_URL = 'https://push2.eastmoney.com/api/qt/stock/get'

_EM_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Referer': 'https://quote.eastmoney.com/',
    'Accept': '*/*',
    'Accept-Language': 'zh-CN,zh;q=0.9',
}


def _urllib_get_json(url: str, params: dict) -> dict:
    full_url = url + '?' + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(full_url, headers=_EM_HEADERS)
            with urllib.request.urlopen(req, timeout=8) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            last_err = e
            time.sleep(0.8 * (attempt + 1))
    raise last_err


_EM_SEMAPHORE = asyncio.Semaphore(3)


async def _em_get_json(url: str, params: dict) -> dict:
    async with _EM_SEMAPHORE:
        return await asyncio.to_thread(_urllib_get_json, url, params)


async def _fetch_index_flow_history_em(secid: str, limit: int = 15) -> list:
    """东方财富：获取指数资金流向历史"""
    params = {
        'lmt': limit, 'klt': '101', 'secid': secid,
        'fields1': 'f1,f2,f3,f7',
        'fields2': 'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61,f62,f63,f64,f65',
        'ut': 'b2884a393a59ad64002292a3e90d46a5',
    }
    try:
        data = await _em_get_json(_EM_FFLOW_URL, params)
    except Exception as e:
        logger.warning(f'[index_flow] EM 获取 {secid} 历史失败: {e}')
        return []

    klines = data.get('data', {}).get('klines', []) if data.get('data') else []
    rows = []
    for k in klines:
        parts = k.split(',')
        if len(parts) < 6:
            continue
        try:
            rows.append({
                'date': parts[0],
                'main_net': float(parts[1]),
                'small_net': float(parts[2]),
                'medium_net': float(parts[3]),
                'large_net': float(parts[4]),
                'elg_net': float(parts[5]),
            })
        except (ValueError, IndexError):
            continue
    return rows


async def _fetch_index_quote_em(secid: str) -> dict:
    params = {
        'secid': secid,
        'fields': 'f43,f44,f45,f46,f47,f48,f57,f58,f170',
        'ut': 'b2884a393a59ad64002292a3e90d46a5',
    }
    try:
        data = await _em_get_json(_EM_QUOTE_URL, params)
    except Exception as e:
        logger.warning(f'[index_flow] EM 获取 {secid} 行情失败: {e}')
        return {}

    d = data.get('data', {}) or {}

    def _div100(v):
        if v is None:
            return None
        try:
            return float(v) / 100.0
        except (ValueError, TypeError):
            return None
    return {
        'close': _div100(d.get('f43')),
        'pct_change': _div100(d.get('f170')),
    }


def _aggregate_flow_em(history: list, days: int) -> float:
    if not history:
        return 0.0
    recent = history[-days:] if len(history) >= days else history
    return sum(r['main_net'] for r in recent)


# ============================================================
# API
# ============================================================

async def _build_rank_result(indices_list: list, cache: dict, source_label: str,
                              force: int = 0) -> dict:
    """通用排名构建：对给定指数列表按成分股聚合 stock_flow，缺数据时降级东方财富"""
    if not force and cache['data'] and time.time() - cache['ts'] < _RANK_CACHE_TTL:
        return cache['data']

    # 主数据源：数据库聚合
    db_results = []
    db_hit_count = 0
    with get_db_session() as db:
        for idx_def in indices_list:
            try:
                agg = _aggregate_index_from_db(idx_def, db, latest_n_days=12)
                if agg and agg.get('latest_date'):
                    db_results.append(agg)
                    db_hit_count += 1
                else:
                    db_results.append(None)
            except Exception as e:
                logger.warning(f'[index_flow] DB 聚合 {idx_def["ts_code"]} 失败: {e}')
                db_results.append(None)

    # 如果数据库全部命中，直接返回
    if db_hit_count == len(indices_list):
        result_indices = []
        latest_date = None
        for agg in db_results:
            if agg is None:
                continue
            if latest_date is None or agg['latest_date'] > latest_date:
                latest_date = agg['latest_date']
            result_indices.append({
                'ts_code': agg['ts_code'],
                'name': agg['name'],
                'close': agg.get('close'),
                'pct_change': agg.get('pct_change'),
                'inflow_1d': agg['inflow_1d'],
                'inflow_3d': agg['inflow_3d'],
                'inflow_5d': agg['inflow_5d'],
                'inflow_10d': agg['inflow_10d'],
                'abs_1d': abs(agg['inflow_1d']),
                'member_count': agg.get('member_count', 0),
                'source': 'db',
            })
        result_indices.sort(key=lambda x: x['inflow_5d'], reverse=True)
        result = {
            'date': latest_date,
            'indices': result_indices,
            'count': len(result_indices),
            'source': 'database',
            'index_type': source_label,
        }
        cache['data'] = result
        cache['ts'] = time.time()
        return result

    # 降级：对数据库未命中的指数调用东方财富
    logger.info(f'[index_flow] DB 命中 {db_hit_count}/{len(indices_list)}, 降级 EM 补充')
    em_indices_with_secid = [(i, idx) for i, idx in enumerate(indices_list)
                             if idx.get('secid') and db_results[i] is None]
    em_hist_results = []
    em_quote_results = []
    if em_indices_with_secid:
        tasks_hist = [_fetch_index_flow_history_em(idx['secid'], limit=15) for _, idx in em_indices_with_secid]
        tasks_quote = [_fetch_index_quote_em(idx['secid']) for _, idx in em_indices_with_secid]
        em_hist_results = await asyncio.gather(*tasks_hist, return_exceptions=True)
        em_quote_results = await asyncio.gather(*tasks_quote, return_exceptions=True)

    result_indices = []
    latest_date = None
    em_fail_count = 0

    # 处理 DB 命中的指数
    for agg in db_results:
        if agg is None:
            continue
        if latest_date is None or agg['latest_date'] > latest_date:
            latest_date = agg['latest_date']
        result_indices.append({
            'ts_code': agg['ts_code'],
            'name': agg['name'],
            'close': agg.get('close'),
            'pct_change': agg.get('pct_change'),
            'inflow_1d': agg['inflow_1d'],
            'inflow_3d': agg['inflow_3d'],
            'inflow_5d': agg['inflow_5d'],
            'inflow_10d': agg['inflow_10d'],
            'abs_1d': abs(agg['inflow_1d']),
            'member_count': agg.get('member_count', 0),
            'source': 'db',
        })

    # 处理 EM 补充的指数
    for j, (orig_i, idx_def) in enumerate(em_indices_with_secid):
        hist = em_hist_results[j] if not isinstance(em_hist_results[j], Exception) else []
        quote = em_quote_results[j] if not isinstance(em_quote_results[j], Exception) else {}
        if not hist:
            em_fail_count += 1
            continue
        if latest_date is None or hist[-1]['date'] > latest_date:
            latest_date = hist[-1]['date']
        result_indices.append({
            'ts_code': idx_def['ts_code'],
            'name': idx_def['name'],
            'close': quote.get('close'),
            'pct_change': quote.get('pct_change'),
            'inflow_1d': _aggregate_flow_em(hist, 1),
            'inflow_3d': _aggregate_flow_em(hist, 3),
            'inflow_5d': _aggregate_flow_em(hist, 5),
            'inflow_10d': _aggregate_flow_em(hist, 10),
            'abs_1d': abs(_aggregate_flow_em(hist, 1)),
            'member_count': 0,
            'source': 'eastmoney',
        })

    result_indices.sort(key=lambda x: x['inflow_5d'], reverse=True)
    result = {
        'date': latest_date,
        'indices': result_indices,
        'count': len(result_indices),
        'source': 'database+eastmoney' if em_indices_with_secid else 'database',
        'index_type': source_label,
    }

    # 全部失败时附加错误信息
    if not result_indices:
        result['error'] = 'data_source_unavailable'
        result['message'] = '数据库与东方财富数据源均不可用，请稍后重试'

    cache['data'] = result
    cache['ts'] = time.time()
    return result


@router.get('/api/index-flow/rank')
async def get_index_flow_rank(force: int = Query(0, description='1=跳过缓存强制刷新')):
    """获取行业主题指数的 1/3/5/10 日累计主力净流入排名（默认入口，匹配截图维度）"""
    return await _build_rank_result(THEME_INDICES, _rank_cache, 'theme', force=force)


@router.get('/api/index-flow/broad-rank')
async def get_index_flow_broad_rank(force: int = Query(0, description='1=跳过缓存强制刷新')):
    """获取宽基主要指数的 1/3/5/10 日累计主力净流入排名（兼容原逻辑）"""
    return await _build_rank_result(MAJOR_INDICES, _broad_rank_cache, 'broad', force=force)


@router.get('/api/index-flow/history')
async def get_index_flow_history(
    ts_code: str = Query(..., description='指数代码，如 000300.SH'),
    days: int = Query(20, description='返回最近 N 个交易日'),
    force: int = Query(0, description='1=跳过缓存'),
):
    """获取单个指数的资金流向历史趋势（用于详情图）"""
    if days < 1 or days > 60:
        raise HTTPException(status_code=400, detail='days must be between 1 and 60')

    _ALL_INDICES = MAJOR_INDICES + THEME_INDICES
    idx = next((x for x in _ALL_INDICES if x['ts_code'] == ts_code), None)
    if not idx:
        raise HTTPException(status_code=404, detail=f'不支持的指数代码: {ts_code}')

    # 缓存检查
    if not force and ts_code in _history_cache:
        cached = _history_cache[ts_code]
        if time.time() - cached['ts'] < _HISTORY_CACHE_TTL:
            return cached['data']

    # 优先：数据库聚合
    db_result = None
    try:
        with get_db_session() as db:
            agg = _aggregate_index_from_db(idx, db, latest_n_days=days)
            if agg and agg.get('dates'):
                db_result = {
                    'ts_code': ts_code,
                    'name': idx['name'],
                    'dates': agg['dates'],
                    'main_net': agg['main_net'],
                    'cumulative': agg['cumulative'],
                    'latest_date': agg['latest_date'],
                    'source': 'database',
                    'member_count': agg.get('member_count', 0),
                }
    except Exception as e:
        logger.warning(f'[index_flow] DB history {ts_code} 失败: {e}')

    if db_result:
        _history_cache[ts_code] = {'data': db_result, 'ts': time.time()}
        return db_result

    # 降级：东方财富
    if not idx.get('secid'):
        _history_cache[ts_code] = {
            'data': {'ts_code': ts_code, 'name': idx['name'], 'dates': [], 'main_net': [], 'cumulative': []},
            'ts': time.time(),
        }
        return _history_cache[ts_code]['data']

    history = await _fetch_index_flow_history_em(idx['secid'], limit=days)
    if not history:
        return {'ts_code': ts_code, 'name': idx['name'], 'dates': [], 'main_net': [], 'cumulative': []}

    cumulative = []
    total = 0
    for r in history:
        total += r['main_net']
        cumulative.append(total)

    result = {
        'ts_code': ts_code,
        'name': idx['name'],
        'dates': [r['date'] for r in history],
        'main_net': [r['main_net'] for r in history],
        'cumulative': cumulative,
        'latest_date': history[-1]['date'] if history else None,
        'source': 'eastmoney',
    }
    _history_cache[ts_code] = {'data': result, 'ts': time.time()}
    return result
