"""AIROBOT 公共工具函数
股票代码转换、交易日判断、日期格式等。
所有跨模块共享的纯函数都放这里。
"""
from datetime import datetime, date, timedelta
import re


def stock_code_to_sina(stock_code: str) -> str:
    """6位股票代码转新浪格式: 600519 -> sh600519, 000001 -> sz000001, 430047 -> bj430047"""
    if not stock_code:
        return ''
    code = stock_code.strip()
    if code.startswith(('sh', 'sz', 'bj')):
        return code
    if len(code) != 6:
        return ''
    if code[0] in ('6', '9'):
        return f'sh{code}'
    if code[0] in ('4', '8'):
        return f'bj{code}'
    return f'sz{code}'


def stock_code_to_ts_code(stock_code: str) -> str:
    """6位 → ts_code (600519 -> 600519.SH)"""
    if not stock_code or len(stock_code) != 6:
        return stock_code
    if stock_code[0] in ('6', '9'):
        return f'{stock_code}.SH'
    return f'{stock_code}.SZ'


def ts_code_to_stock_code(ts_code: str) -> str:
    """ts_code → 6位 (600519.SH -> 600519)"""
    if not ts_code:
        return ''
    return ts_code.split('.')[0]


def parse_ts_code(ts_code: str) -> tuple:
    """ts_code → (6位, 交易所)"""
    if not ts_code or '.' not in ts_code:
        return (ts_code, '')
    code, exchange = ts_code.split('.', 1)
    return (code, exchange)


def normalize_stock_code(stock_code: str) -> str:
    """任意格式 → 6位股票代码"""
    if not stock_code:
        return ''
    return ts_code_to_stock_code(stock_code)


def is_trading_day(d: date = None) -> bool:
    """判断是否为交易日（周一到周五，简化版，未考虑节假日）"""
    if d is None:
        d = date.today()
    return d.weekday() < 5


def trading_hours_window(now: datetime = None) -> tuple:
    """判断当前是否在 A 股交易时段
    Returns: (in_morning: bool, in_afternoon: bool)
    """
    if now is None:
        now = datetime.now()
    t = now.time()
    in_morning = (datetime.strptime('09:30', '%H:%M').time()
                  <= t <= datetime.strptime('11:30', '%H:%M').time())
    in_afternoon = (datetime.strptime('13:00', '%H:%M').time()
                    <= t <= datetime.strptime('15:00', '%H:%M').time())
    return (in_morning, in_afternoon)


def is_trading_time(now: datetime = None) -> bool:
    """当前是否在交易时段（含 9:25 集合竞价）"""
    if now is None:
        now = datetime.now()
    t = now.time()
    in_pre = (datetime.strptime('09:25', '%H:%M').time() <= t
              <= datetime.strptime('11:30', '%H:%M').time())
    in_post = (datetime.strptime('13:00', '%H:%M').time() <= t
               <= datetime.strptime('15:00', '%H:%M').time())
    return in_pre or in_post


def now_truncated(unit: str = 'minute') -> datetime:
    """返回当前时间，按分钟/小时截断（用于分钟级快照去重）"""
    now = datetime.now()
    if unit == 'minute':
        return now.replace(second=0, microsecond=0)
    if unit == 'hour':
        return now.replace(minute=0, second=0, microsecond=0)
    if unit == 'day':
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    return now


def format_date(d) -> str:
    """统一日期格式为 YYYY-MM-DD"""
    if isinstance(d, str):
        return d[:10]
    if isinstance(d, (date, datetime)):
        return d.strftime('%Y-%m-%d')
    return str(d)


def safe_div(a, b, default=0.0):
    """安全除法，b=0 时返回 default"""
    try:
        if b == 0:
            return default
        return a / b
    except (TypeError, ZeroDivisionError):
        return default


def clamp(value, min_val, max_val):
    """将 value 钳位到 [min_val, max_val]"""
    return max(min_val, min(max_val, value))


def round_pct(value, digits=2):
    """百分比四舍五入"""
    if value is None:
        return 0.0
    return round(float(value), digits)
