"""资金气象雷达 API
- GET /api/fund-weather  返回自选股按机构/游资双轨资金博弈划分的气象分组
"""
import logging
from datetime import datetime
from typing import Dict, List, Optional

from fastapi import APIRouter
from sqlalchemy.orm import Session

from db.session import get_db_session
from db.models import YuziSeatDaily, YuziDict
from api.watchlist.core import get_watchlist

router = APIRouter()
logger = logging.getLogger(__name__)


# === 天气配置 ===
WEATHER_CONFIG = {
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
    change_5d: float,
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
    if change_5d > RISE_THRESHOLD and yuzi_net_5d > YUZI_THRESHOLD and inst_net_5d < -INSTITUTION_THRESHOLD:
        return 'typhoon'

    # 艳阳：技术多头 + 机构买入 + 游资买入
    if bullish and inst_net_5d > 0 and yuzi_net_5d > 0:
        return 'sunny'

    return 'cloudy'


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
        return {'weather_groups': [], 'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

    # 批量查询近 5 日席位资金流
    raw_codes = [s['secCode'] for s in signals if s.get('secCode')]
    ts_codes = [f"{c}.SH" if c[0] in ('6', '9') else f"{c}.SZ" for c in raw_codes if len(c) == 6]

    with get_db_session() as db:
        seat_map = _load_seat_flow_map(db, ts_codes, days=5)

    # 计算近 5 日涨幅（从 signal.quote 没有历史，用 changePct 近似当日，或用 moneyFlow inflow_5d 相关）
    # MVP：先使用当日涨幅作为 proxy，后续可从 StockDailyKline 取 5 日涨幅
    def _estimate_5d_change(s):
        quote = s.get('quote') or {}
        # 如果有近5日累计主力净流入方向与涨幅同向，用当日涨幅 proxy
        return float(quote.get('changePct') or 0)

    # 按天气分组
    groups = {key: [] for key in WEATHER_CONFIG}
    for s in signals:
        code = s.get('secCode', '')
        ts_code = f"{code}.SH" if code and code[0] in ('6', '9') else f"{code}.SZ"
        seat = seat_map.get(code, {'inst_net': 0, 'yuzi_net': 0})
        technical = s.get('technical')
        change_5d = _estimate_5d_change(s)

        weather_key = _classify_weather(
            technical,
            seat.get('inst_net', 0),
            seat.get('yuzi_net', 0),
            change_5d,
        )

        quote = s.get('quote') or {}
        cfg = WEATHER_CONFIG[weather_key]
        groups[weather_key].append({
            'code': code,
            'name': s.get('secName', ''),
            'sector': s.get('sector', ''),
            'technical_stage': technical.get('stage') if technical else '-',
            'change_pct': round(float(quote.get('changePct') or 0), 2),
            'price': round(float(quote.get('price') or 0), 2),
            'inst_net_5d': seat.get('inst_net', 0),
            'yuzi_net_5d': seat.get('yuzi_net', 0),
            'inst_net_5d_fmt': _fmt_wan(seat.get('inst_net', 0)),
            'yuzi_net_5d_fmt': _fmt_wan(seat.get('yuzi_net', 0)),
            'action': cfg['action'],
            'weather': weather_key,
        })

    weather_groups = []
    for key in ['storm', 'cloudy_to_sunny', 'typhoon', 'sunny', 'cloudy']:
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

    return {
        'weather_groups': weather_groups,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
