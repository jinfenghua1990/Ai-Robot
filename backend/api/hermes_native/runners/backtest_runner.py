"""
白虎策略回测执行器
从数据库或 pytdx 实时数据源加载K线数据，按指定参数运行回测，返回指标结果
"""
import sys, json, os, math, time
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Optional, Union, Any, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, '/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database')
from api.hermes_native.db_connector import execute_query

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from api.hermes_native.runners.data_collector import get_kline, get_stock_list, estimate_turnover, PYTDX_AVAILABLE


def mean(arr):
    return sum(arr) / len(arr) if arr else 0.0

def stddev(arr):
    if len(arr) < 2:
        return 0.0
    m = mean(arr)
    return math.sqrt(sum((x - m) ** 2 for x in arr) / len(arr))


def calc_rsi(closes, period=14):
    if len(closes) < period + 1:
        return 50
    gains, losses = 0.0, 0.0
    for i in range(-period, 0):
        d = closes[i] - closes[i - 1]
        if d > 0:
            gains += d
        else:
            losses -= d
    avg_gain = gains / period
    avg_loss = losses / period
    if avg_loss == 0:
        return 100
    return 100 - (100 / (1 + avg_gain / avg_loss))


def calc_ma(prices, period):
    if len(prices) < period:
        return None
    return mean(prices[-period:])


def evaluate_signal(closes, opens, lows, highs, volumes, day_idx, params):
    """白虎策略信号评估（可调参版本）"""
    if day_idx < 25:
        return 0
    try:
        ma20_up_days = params.get('ma20_up_days', 4)
        min_20day_gain = params.get('min_20day_gain', 20)
        max_deviation = params.get('max_deviation', 8)
        min_lower_shadow = params.get('min_lower_shadow', 1.0)
        max_change_pct = params.get('max_change_pct', 6)
        max_vol_ratio = params.get('max_vol_ratio', 130)
        rsi_min = params.get('rsi_min', 25)
        rsi_max = params.get('rsi_max', 60)
        min_deviation = params.get('min_deviation', 0)

        # MA20连续N天向上
        ma20_slice = []
        for i in range(max(0, day_idx - ma20_up_days - 1), day_idx + 1):
            ma = calc_ma(closes[:i + 1], 20)
            if ma:
                ma20_slice.append(ma)
        if len(ma20_slice) < ma20_up_days:
            return 0
        if not all(ma20_slice[j] < ma20_slice[j + 1] for j in range(len(ma20_slice) - ma20_up_days, len(ma20_slice) - 1)):
            return 0

        if len(closes) < 21 or closes[-21] <= 0:
            return 0
        recent_20day_gain = (closes[-1] - closes[-21]) / closes[-21] * 100
        if recent_20day_gain < min_20day_gain:
            return 0

        close = closes[day_idx]
        open_p = opens[day_idx]
        low = lows[day_idx]
        volume = volumes[day_idx]
        prev_close = closes[day_idx - 1]

        ma20 = calc_ma(closes[:day_idx + 1], 20)
        if not ma20 or close <= ma20:
            return 0
        if low > ma20:
            return 0

        deviation = (close - ma20) / ma20 * 100
        if deviation >= max_deviation or deviation <= min_deviation:
            return 0

        if prev_close <= 0:
            return 0
        change_pct = (close - prev_close) / prev_close * 100
        lower_shadow = (min(close, open_p) - low) / prev_close * 100

        rsi = calc_rsi(closes[:day_idx + 1])

        recent_vols = volumes[max(0, day_idx - 5):day_idx]
        avg_vol = mean(recent_vols) if len(recent_vols) > 0 else 1
        vol_ratio = (volume / avg_vol * 100) if avg_vol > 0 else 100

        score = 0
        if lower_shadow > min_lower_shadow:
            score += 2
        if 0 <= change_pct <= max_change_pct:
            score += 2
        if vol_ratio < max_vol_ratio:
            score += 1
        if rsi_min <= rsi <= rsi_max:
            score += 1
        if min_deviation < deviation < max_deviation:
            score += 2

        return score if score >= 4 else 0
    except Exception:
        return 0


def run_backtest(kline_by_code, code_names, params, max_samples=50):
    """用指定参数运行回测，返回指标"""
    signals = []
    eligible = 0
    for code, kline in kline_by_code.items():
        if len(kline) < 31:  # 至少需要 31 日（day_idx 从 30 开始）
            continue
        eligible += 1
        closes = [k['close'] for k in kline]
        opens = [k['open'] for k in kline]
        lows = [k['low'] for k in kline]
        highs = [k['high'] for k in kline]
        volumes = [k['volume'] for k in kline]
        dates = [k['trade_date'] for k in kline]

        for day_idx in range(30, len(dates)):
            score = evaluate_signal(closes, opens, lows, highs, volumes, day_idx, params)
            if score > 0:
                signals.append({'code': code, 'date': dates[day_idx]})

    # 计算收益（5日后卖出）
    print(f'[bt] eligible stocks: {eligible}, signals found: {len(signals)}', flush=True)
    returns = []
    sample_stocks = []  # 保存样本信号股票详情
    for sig in signals:
        code = sig['code']
        date = sig['date']
        kline = kline_by_code.get(code, [])
        if not kline:
            continue
        try:
            buy_idx = next(i for i, k in enumerate(kline) if k['trade_date'] == date)
        except StopIteration:
            continue
        if buy_idx + 5 >= len(kline):
            continue
        buy_price = kline[buy_idx]['close']
        sell_price = kline[buy_idx + 5]['close']
        if buy_price > 0:
            ret = (sell_price - buy_price) / buy_price * 100
            returns.append(ret)

        # 收集样本信号股票（用于信号标签页展示）
        if len(sample_stocks) < max_samples:
            sample_stocks.append({
                'symbol': code,
                'name': code_names.get(code, ''),
                'trade_date': date,
                'close': round(buy_price, 2),
                'change_pct': round((kline[buy_idx]['close'] - kline[buy_idx]['open']) / kline[buy_idx]['open'] * 100, 2) if buy_idx < len(kline) else 0,
                'backtest_return': round(ret, 2),
            })

    if not returns:
        return {'signal_cnt': 0, 'trade_cnt': 0, 'win_rate': 0, 'avg_return': 0, 'sharpe': 0, 'max_drawdown': 0, 'sample_stocks': []}

    wins = len([r for r in returns if r > 0])
    win_rate = wins / len(returns) * 100
    avg_ret = mean(returns)
    std_ret = stddev(returns)
    sharpe = avg_ret / std_ret * math.sqrt(252) if std_ret > 0 else 0
    max_dd = min(returns) if returns else 0

    return {
        'signal_cnt': len(signals),
        'trade_cnt': len(returns),
        'win_rate': round(win_rate, 1),
        'avg_return': round(avg_ret, 2),
        'sharpe': round(sharpe, 2),
        'max_drawdown': round(max_dd, 2),
        'sample_stocks': sample_stocks,
    }


def load_market_data(stock_filters, days=180, use_pytdx=False):
    """
    从数据库加载K线数据，可选使用 pytdx 补充实时数据
    stock_filters: SQL LIKE 模式列表, e.g. ['300%', '688%']
    days: 回测天数
    use_pytdx: 是否使用 pytdx 补充数据（数据库数据不足时）
    returns: (kline_by_code, code_names, date_range)
    """
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # 构建过滤条件
    sym_like = ' OR '.join(f"symbol LIKE '{f.replace('%', '%%')}'" for f in stock_filters)
    code_like = ' OR '.join(f"code LIKE '{f.replace('%', '%%')}'" for f in stock_filters)

    stocks = execute_query(f"""
        SELECT symbol, name FROM stock_list
        WHERE list_status = 'L' AND market IN ('CN_A', 'SH', 'SZ')
        AND ({sym_like})
        ORDER BY symbol
    """)
    stock_list = [(s['symbol'], s['name']) for s in stocks]
    print(f'[bt] stock_list count: {len(stock_list)}', flush=True)

    rows = execute_query(f"""
        SELECT code, trade_date, open, high, low, close, volume
        FROM kline_daily_cn_a
        WHERE trade_date >= %s AND trade_date <= %s
        AND ({code_like})
        ORDER BY code, trade_date ASC
    """, (start_date, end_date))

    kline_by_code = defaultdict(list)
    code_names = {}
    for s, n in stock_list:
        # stock_list.symbol 格式为 "300750.SZ"，而 kline.code 为 "300750"
        code = s.split('.')[0] if '.' in s else s
        code_names[code] = n

    for r in rows:
        code = r['code']
        if code in code_names:
            kline_by_code[code].append({
                'trade_date': str(r['trade_date']),
                'open': float(r['open'] or 0),
                'high': float(r['high'] or 0),
                'low': float(r['low'] or 0),
                'close': float(r['close'] or 0),
                'volume': float(r['volume'] or 0),
            })

    print(f'[bt] kline rows: {len(rows)}, stocks with data: {len(kline_by_code)}', flush=True)

    # 如果启用 pytdx 且数据不足，补充实时数据
    if use_pytdx and PYTDX_AVAILABLE:
        print(f'[bt] pytdx available, supplementing missing data...', flush=True)
        missing_codes = [code for code in code_names if len(kline_by_code.get(code, [])) < 30]
        print(f'[bt] {len(missing_codes)} stocks need data supplement', flush=True)
        
        def fetch_one(code):
            try:
                data = get_kline(code, start_date, end_date, prefer_pytdx=True)
                return code, data
            except:
                return code, []
        
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(fetch_one, code) for code in missing_codes[:50]]
            for f in as_completed(futures):
                code, data = f.result()
                if data:
                    kline_by_code[code] = data
    
    print(f'[bt] final stocks with data: {len(kline_by_code)}', flush=True)
    return kline_by_code, code_names, (start_date, end_date)


# 策略 -> 股票过滤映射
STRATEGY_STOCK_FILTERS = {
    'baihu': ['300%', '688%'],       # 创业板+科创板
    'baihu-gem': ['300%'],            # 仅创业板
    'baihu-star': ['688%'],           # 仅科创板
    'wave': ['300%', '688%'],
}

# 扫描范围映射（前端选择 key → SQL LIKE 模式）
STOCK_FILTER_MAP = {
    'gem_star': ['300%', '688%'],   # 创业板+科创板
    'gem': ['300%'],                # 仅创业板
    'star': ['688%'],               # 仅科创板
    'all': ['%'],                   # 全A股
}

def decode_stock_filter(value: Union[str, list[str], None]) -> Optional[list[str]]:
    """解析扫描范围参数为 SQL LIKE 列表"""
    if value is None:
        return None
    if isinstance(value, list):
        return value
    return STOCK_FILTER_MAP.get(value)

# 默认参数
DEFAULT_PARAMS = {
    'ma20_up_days': 4,
    'min_20day_gain': 20,
    'max_deviation': 8,
    'min_lower_shadow': 1.0,
    'max_change_pct': 6,
    'max_vol_ratio': 130,
    'rsi_min': 25,
    'rsi_max': 60,
    'min_deviation': 0,
}


def execute_backtest(strategy_name: str, params: Optional[dict] = None, days: int = 180, stock_filters: Union[str, list[str], None] = None, max_samples: int = 50, use_pytdx: bool = False) -> dict:
    """
    执行回测主入口
    strategy_name: 策略名称（对应 STRATEGY_STOCK_FILTERS 的 key）
    params: 自定义参数，不传则用默认值
    days: 回测天数
    stock_filters: 扫描范围 key（如 'gem_star'）或 list，不传则用策略默认
    max_samples: 保存的样本信号数量上限，默认50
    use_pytdx: 是否使用 pytdx 补充实时数据
    returns: 包含指标的 dict
    """
    custom_filters = decode_stock_filter(stock_filters)
    filters = custom_filters or STRATEGY_STOCK_FILTERS.get(strategy_name, ['300%', '688%'])
    p = {**DEFAULT_PARAMS, **(params or {})}

    kline_by_code, code_names, (start, end) = load_market_data(filters, days, use_pytdx)
    result = run_backtest(kline_by_code, code_names, p, max_samples)

    # 记录使用的扫描范围 key（用于保存时生成标签）
    if isinstance(stock_filters, str) and stock_filters in STOCK_FILTER_MAP:
        result['stock_filter_key'] = stock_filters
    # else: 留给 save_result 用默认值

    # 添加元数据
    result['strategy'] = strategy_name
    result['params'] = p
    result['date_range'] = f"{start} ~ {end}"
    result['generated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    result['total_stocks'] = len(kline_by_code)

    return result


def save_result(strategy_name: str, result: dict):
    """保存回测结果到文件（与 get_backtest 兼容的格式）"""
    base = '/Users/gino/backtest_results'
    path_map = {
        'baihu': f'{base}/baihu/result.json',
        'baihu-gem': f'{base}/baihu-gem/result.json',
        'baihu-star': f'{base}/baihu-star/result.json',
        'wave': f'{base}/wave/result.json',
    }
    path = path_map.get(strategy_name)
    if not path:
        return

    # 记录扫描范围标签
    filter_labels = {'gem_star': '创业板+科创板', 'gem': '创业板', 'star': '科创板', 'all': '全A股'}
    used_key = result.get("stock_filter_key", "gem_star")
    filter_label = filter_labels.get(used_key, '创业板+科创板')

    saved = {
        "trade_date": datetime.now().strftime('%Y-%m-%d'),
        "generated_at": result.get("generated_at"),
        "strategy": result.get("strategy", strategy_name),
        "params": result.get("params"),
        "stock_filter_key": used_key,
        "stock_filter_label": filter_label,
        "data": {
            "stocks": result.get("sample_stocks", []),
            "total_signals": result.get("signal_cnt", 0),
            "win_rate": result.get("win_rate", 0),
            "avg_return": result.get("avg_return", 0),
            "max_drawdown": result.get("max_drawdown", 0),
            "sharpe": result.get("sharpe", 0),
            "date_range": result.get("date_range", ""),
            "total_stocks": result.get("total_stocks", 0),
        }
    }

    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(saved, f, ensure_ascii=False, indent=2)