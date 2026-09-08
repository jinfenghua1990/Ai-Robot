"""资金气象雷达 API
- GET /api/fund-weather  返回自选股按机构/游资双轨资金博弈划分的气象分组
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy import func
from sqlalchemy.orm import Session

from db.session import get_db_session
from db.models import StockDailyKline, YuziSeatDaily, YuziDict
from api.watchlist.core import get_watchlist
from api.watchlist._shared import normalize_stock_code, normalize_ts_code

router = APIRouter()
logger = logging.getLogger(__name__)


# === 天气配置 ===
WEATHER_CONFIG = {
    'insufficient': {
        'key': 'insufficient',
        'label': '数据不足',
        'emoji': '⚠️',
        'action': '等待数据补齐',
        'color': '#64748b',
        'bg': 'rgba(100,116,139,0.08)',
        'border': 'rgba(100,116,139,0.25)',
    },
    'storm': {
        'key': 'storm',
        'label': '雷暴风雨',
        'emoji': '⛈️',
        'action': '清仓 / 避险',
        'color': '#dc2626',
        'bg': 'rgba(220,38,38,0.08)',
        'border': 'rgba(220,38,38,0.25)',
    },
    'cloudy_to_sunny': {
        'key': 'cloudy_to_sunny',
        'label': '阴转多云',
        'emoji': '🌤️',
        'action': '减仓防守 / 锁定自选',
        'color': '#f97316',
        'bg': 'rgba(249,115,22,0.08)',
        'border': 'rgba(249,115,22,0.25)',
    },
    'typhoon': {
        'key': 'typhoon',
        'label': '龙卷风',
        'emoji': '🌪️',
        'action': '快进快出 / 严控止损',
        'color': '#eab308',
        'bg': 'rgba(234,179,8,0.08)',
        'border': 'rgba(234,179,8,0.25)',
    },
    'sunny': {
        'key': 'sunny',
        'label': '晴空万里',
        'emoji': '☀️',
        'action': '持股待涨 / 顺势加仓',
        'color': '#22c55e',
        'bg': 'rgba(34,197,94,0.08)',
        'border': 'rgba(34,197,94,0.25)',
    },
    'cloudy': {
        'key': 'cloudy',
        'label': '多云',
        'emoji': '☁️',
        'action': '观望 / 等待信号',
        'color': '#6b7280',
        'bg': 'rgba(107,114,128,0.08)',
        'border': 'rgba(107,114,128,0.25)',
    },
}


# === 天气判定规则 ===
# 阈值（万元）
INSTITUTION_THRESHOLD = 5000   # 机构爆买阈值
YUZI_THRESHOLD = 3000          # 游资爆买/砸盘阈值
RISE_THRESHOLD = 15.0          # 近5日涨幅阈值（台风）


def _is_breakdown(technical: Optional[dict]) -> bool:
    """技术形态是否破位"""
    if not technical:
        return False
    return technical.get('stage') == '破位'


def _is_bullish_technical(technical: Optional[dict]) -> bool:
    """技术形态是否偏多/多头/突破"""
    if not technical:
        return False
    return technical.get('stage') in ('偏多', '多头', '突破')


def _classify_weather(
    technical: Optional[dict],
    inst_net_5d: float,
    yuzi_net_5d: float,
    change_5d: Optional[float],
) -> str:
    """返回天气 key"""
    breakdown = _is_breakdown(technical)
    bullish = _is_bullish_technical(technical)

    # 暴风雨：技术破位 + 游资砸盘 + 机构不接盘
    if breakdown and yuzi_net_5d < -YUZI_THRESHOLD and inst_net_5d <= 0:
        return 'storm'

    # 阴转晴：技术破位 + 机构爆买 + 游资砸盘
    if breakdown and inst_net_5d > INSTITUTION_THRESHOLD and yuzi_net_5d < -YUZI_THRESHOLD:
        return 'cloudy_to_sunny'

    # 台风：暴涨 + 游资爆买 + 机构出货
    if change_5d is not None and change_5d > RISE_THRESHOLD and yuzi_net_5d > YUZI_THRESHOLD and inst_net_5d < -INSTITUTION_THRESHOLD:
        return 'typhoon'

    # 艳阳：技术多头 + 机构买入 + 游资买入
    if bullish and inst_net_5d > 0 and yuzi_net_5d > 0:
        return 'sunny'

    return 'cloudy'


def _missing_classification_inputs(
    technical: Optional[dict],
    change_5d: Optional[float],
    quote: Optional[dict],
) -> List[str]:
    missing = []
    if not technical:
        missing.append('technical')
    if change_5d is None:
        missing.append('change_5d')
    if not quote or quote.get('status') not in (None, 'READY'):
        missing.append('quote')
    return missing


def _fmt_wan(v: float) -> str:
    """格式化万元为 万/亿"""
    x = v or 0
    if abs(x) >= 10000:
        return f"{x / 10000:.2f}亿"
    return f"{x:.0f}万"


def _load_seat_flow_map(db: Session, stock_codes: List[str], days: int = 5) -> Dict[str, dict]:
    """批量查询近 N 日机构/游资净流入
    返回 {raw_code: {'inst_net': 万, 'yuzi_net': 万, 'inst_days': int, 'yuzi_days': int}}
    """
    if not stock_codes:
        return {}

    # 取最近 N 个交易日（从 YuziSeatDaily 的 trade_date 字符串 YYYYMMDD 中 distinct）
    recent_dates = db.query(YuziSeatDaily.trade_date).distinct()\
        .order_by(YuziSeatDaily.trade_date.desc()).limit(days).all()
    if not recent_dates:
        return {}

    date_list = [d[0] for d in recent_dates]

    # 一次批量拉取
    rows = db.query(
        YuziSeatDaily.ts_code,
        YuziSeatDaily.seat_name,
        YuziSeatDaily.yuzi_alias,
        YuziSeatDaily.net_amount,
        YuziDict.yuzi_group,
    ).outerjoin(
        YuziDict, YuziSeatDaily.seat_name == YuziDict.seat_name
    ).filter(
        YuziSeatDaily.trade_date.in_(date_list),
        YuziSeatDaily.ts_code.in_(stock_codes),
    ).all()

    result: Dict[str, dict] = {}
    for ts_code, seat_name, yuzi_alias, net_amount, yuzi_group in rows:
        code = ts_code.split('.')[0]
        if code not in result:
            result[code] = {'inst_net': 0.0, 'yuzi_net': 0.0, 'inst_days': set(), 'yuzi_days': set()}

        net = float(net_amount or 0)
        group = yuzi_group or ''

        # 机构识别：yuzi_group 为机构，或 seat_name 含机构专用
        if group == '机构' or '机构专用' in (seat_name or ''):
            result[code]['inst_net'] += net
            result[code]['inst_days'].add(ts_code + '@' + seat_name)
        # 游资识别：yuzi_group 属于游资类
        elif group in ('顶级游资', '实力游资', '假游资') or yuzi_alias:
            result[code]['yuzi_net'] += net
            result[code]['yuzi_days'].add(ts_code + '@' + seat_name)

    for code in result:
        result[code]['inst_net'] = round(result[code]['inst_net'], 2)
        result[code]['yuzi_net'] = round(result[code]['yuzi_net'], 2)
        result[code]['inst_days'] = len(result[code]['inst_days'])
        result[code]['yuzi_days'] = len(result[code]['yuzi_days'])

    return result


def _load_5d_change_map(db: Session, stock_codes: List[str]) -> Dict[str, float]:
    """从本地日 K 表计算 5 个交易日涨幅；不足 6 根 K 线的股票不返回。"""
    if not stock_codes:
        return {}
    recent_dates = db.query(StockDailyKline.trade_date).distinct()\
        .order_by(StockDailyKline.trade_date.desc()).limit(6).all()
    dates = [item[0] for item in recent_dates]
    if len(dates) < 6:
        return {}
    rows = db.query(
        StockDailyKline.ts_code,
        StockDailyKline.trade_date,
        StockDailyKline.close,
    ).filter(
        StockDailyKline.ts_code.in_(stock_codes),
        StockDailyKline.trade_date.in_(dates),
    ).order_by(StockDailyKline.ts_code, StockDailyKline.trade_date).all()
    grouped: Dict[str, list] = {}
    for ts_code, trade_date, close in rows:
        if close is not None:
            grouped.setdefault(ts_code, []).append((trade_date, float(close)))
    result: Dict[str, float] = {}
    for ts_code, bars in grouped.items():
        if len(bars) != 6 or bars[0][1] <= 0:
            continue
        result[ts_code.split('.')[0]] = round((bars[-1][1] / bars[0][1] - 1) * 100, 4)
    return result


@router.get("/api/fund-weather")
async def get_fund_weather():
    """资金气象雷达：按机构/游资双轨博弈把自选股分组

    返回:
    {
      "weather_groups": [
        {
          "weather": "storm",
          "label": "雷暴风雨",
          "emoji": "⛈️",
          "action": "清仓 / 避险",
          "color": "#dc2626",
          "count": 3,
          "stocks": [...]
        },
        ...
      ],
      "generated_at": "..."
    }
    """
    # 复用 watchlist 缓存数据
    try:
        watchlist_data = await get_watchlist()
    except Exception as e:
        logger.warning(f'[fund-weather] get_watchlist failed: {e}')
        watchlist_data = {'signals': []}

    signals = watchlist_data.get('signals') or []
    if not signals:
        return {
            'weather_groups': [],
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'data_as_of': watchlist_data.get('data_as_of'),
            'source': 'database',
            'status': 'MISSING',
            'message': '数据库中没有可分类的自选股数据',
            'coverage': {'total': 0},
        }

    # 批量查询近 5 日席位资金流
    raw_codes = [normalize_stock_code(s['secCode']) for s in signals if normalize_stock_code(s.get('secCode'))]
    ts_codes = [normalize_ts_code(code) for code in raw_codes]

    with get_db_session() as db:
        seat_map = _load_seat_flow_map(db, ts_codes, days=5)
        change_5d_map = _load_5d_change_map(db, ts_codes)
        latest_kline_date = db.query(func.max(StockDailyKline.trade_date)).scalar()
        latest_seat_date = db.query(func.max(YuziSeatDaily.trade_date)).scalar()

    # 按天气分组
    groups = {key: [] for key in WEATHER_CONFIG}
    for s in signals:
        code = normalize_stock_code(s.get('secCode', ''))
        seat = seat_map.get(code, {'inst_net': 0, 'yuzi_net': 0})
        technical = s.get('technical')
        change_5d = change_5d_map.get(code)
        quote = s.get('quote') or {}
        missing_inputs = _missing_classification_inputs(technical, change_5d, quote)

        weather_key = 'insufficient' if missing_inputs else _classify_weather(
            technical,
            seat.get('inst_net', 0),
            seat.get('yuzi_net', 0),
            change_5d,
        )

        cfg = WEATHER_CONFIG[weather_key]
        groups[weather_key].append({
            'code': code,
            'name': s.get('secName', ''),
            'sector': s.get('sector', ''),
            'technical_stage': technical.get('stage') if technical else '-',
            'change_pct': round(float(quote['changePct']), 2) if quote.get('changePct') is not None else None,
            'change_5d': round(change_5d, 2) if change_5d is not None else None,
            'change_5d_status': 'READY' if change_5d is not None else 'INSUFFICIENT_DATA',
            'price': round(float(quote['price']), 2) if quote.get('price') is not None else None,
            'inst_net_5d': seat.get('inst_net', 0),
            'yuzi_net_5d': seat.get('yuzi_net', 0),
            'inst_net_5d_fmt': _fmt_wan(seat.get('inst_net', 0)),
            'yuzi_net_5d_fmt': _fmt_wan(seat.get('yuzi_net', 0)),
            'action': cfg['action'],
            'weather': weather_key,
            'classification_status': 'INSUFFICIENT' if missing_inputs else 'READY',
            'missing_inputs': missing_inputs,
            'seat_observed': code in seat_map,
        })

    weather_groups = []
    for key in ['insufficient', 'storm', 'cloudy_to_sunny', 'typhoon', 'sunny', 'cloudy']:
        cfg = WEATHER_CONFIG[key]
        weather_groups.append({
            'weather': key,
            'label': cfg['label'],
            'emoji': cfg['emoji'],
            'action': cfg['action'],
            'color': cfg['color'],
            'bg': cfg['bg'],
            'border': cfg['border'],
            'count': len(groups[key]),
            'stocks': groups[key],
        })

    total = len(signals)
    technical_ready = sum(1 for s in signals if s.get('technical'))
    change_5d_ready = sum(1 for s in signals if s.get('secCode') in change_5d_map)
    quote_ready = sum(
        1 for s in signals
        if s.get('quote') and (s['quote'].get('status') in (None, 'READY'))
    )
    ready = sum(group['count'] for group in weather_groups if group['weather'] != 'insufficient')
    latest_kline = latest_kline_date.isoformat() if latest_kline_date else None
    latest_seat = str(latest_seat_date) if latest_seat_date else None
    status = 'READY' if ready == total and watchlist_data.get('status') == 'READY' else 'PARTIAL'

    return {
        'weather_groups': weather_groups,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'data_as_of': latest_kline or watchlist_data.get('data_as_of'),
        'source': 'database',
        'status': status,
        'message': None if status == 'READY' else f'{total - ready} 只股票缺少完整分类输入',
        'component_dates': {
            'watchlist': watchlist_data.get('data_as_of'),
            'daily_kline': latest_kline,
            'seat_flow': latest_seat,
        },
        'coverage': {
            'total': total,
            'classification_ready': ready,
            'quote_ready': quote_ready,
            'technical_ready': technical_ready,
            'change_5d_ready': change_5d_ready,
            'seat_observation_count': len(seat_map),
        },
    }
