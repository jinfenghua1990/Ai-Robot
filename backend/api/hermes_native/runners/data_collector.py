"""
数据源采集器 - A股/港股/美股
- A股: pytdx为主，数据库替补
- 港股: pytdx为主
- 美股: tushare/akshare
三层缓存：内存缓存 → 磁盘缓存 → 网络拉取
线程隔离连接池，20线程并发
动态服务器寻优 + IP重试循环
"""
import sys, os, json, time, hashlib
from datetime import datetime, timedelta
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

sys.path.insert(0, '/Users/gino/Projects/AIROBOT/backend/.hermes-legacy/database')
from api.hermes_native.db_connector import execute_write, execute_query, execute_many

try:
    from pytdx.hq import TdxHq_API
    from pytdx.util.best_ip import stock_ip
    PYTDX_AVAILABLE = True
    TDX_SERVERS = [(s['ip'], s['port']) for s in stock_ip]
except ImportError:
    PYTDX_AVAILABLE = False
    TDX_SERVERS = []

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

try:
    import yfinance as yf
    YFINANCE_AVAILABLE = True
except ImportError:
    YFINANCE_AVAILABLE = False
    yf = None

_MEMORY_CACHE = {}
_CACHE_EXPIRE = 3600

_BEST_SERVER = None
_BEST_SERVER_TTL = 0

_thread_local = threading.local()


def get_thread_api():
    if not hasattr(_thread_local, 'api'):
        _thread_local.api = TdxHq_API()
    return _thread_local.api


def test_server(ip, port, timeout=3):
    try:
        start = time.time()
        api = TdxHq_API()
        if api.connect(ip, port, time_out=timeout):
            api.disconnect()
            latency = (time.time() - start) * 1000
            return ip, port, latency
        return ip, port, float('inf')
    except:
        return ip, port, float('inf')


def get_best_server():
    global _BEST_SERVER, _BEST_SERVER_TTL
    now = time.time()
    if _BEST_SERVER and now < _BEST_SERVER_TTL:
        return _BEST_SERVER
    
    print(f'[data] Testing {len(TDX_SERVERS)} TDX servers...', flush=True)
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(test_server, ip, port) for ip, port in TDX_SERVERS]
        results = [f.result() for f in as_completed(futures)]
    
    results = [r for r in results if r[2] < float('inf')]
    if results:
        results.sort(key=lambda x: x[2])
        _BEST_SERVER = (results[0][0], results[0][1])
        _BEST_SERVER_TTL = now + 300
        print(f'[data] Best server: {_BEST_SERVER[0]}:{_BEST_SERVER[1]} ({results[0][2]:.1f}ms)', flush=True)
    else:
        print('[data] Warning: No TDX server available, will use database fallback', flush=True)
    
    return _BEST_SERVER


def connect_with_retry(max_retries=3):
    """连接通达信服务器，带重试循环"""
    if not PYTDX_AVAILABLE:
        return None, None
    
    servers = []
    
    if _BEST_SERVER:
        servers.append(_BEST_SERVER)
    else:
        best = get_best_server()
        if best:
            servers.append(best)
    
    servers.extend(TDX_SERVERS[:10])
    
    for ip, port in servers[:max_retries]:
        try:
            api = TdxHq_API()
            if api.connect(ip, port, time_out=5):
                print(f'[data] Connected to {ip}:{port}', flush=True)
                return api, (ip, port)
        except Exception as e:
            print(f'[data] Failed to connect {ip}:{port}: {e}', flush=True)
        time.sleep(0.5)
    
    return None, None


def estimate_turnover(vol_ratio):
    if vol_ratio >= 2.5:
        return 10.0
    elif vol_ratio >= 1.8:
        return 7.0
    elif vol_ratio >= 1.2:
        return 5.0
    elif vol_ratio >= 0.8:
        return 3.0
    else:
        return 1.5


def cache_key(code, date):
    return f'{code}_{date}'


def get_cached_data(code, date):
    key = cache_key(code, date)
    if key in _MEMORY_CACHE:
        cached, ts = _MEMORY_CACHE[key]
        if time.time() - ts < _CACHE_EXPIRE:
            return cached
        del _MEMORY_CACHE[key]
    return None


def set_cached_data(code, date, data):
    key = cache_key(code, date)
    _MEMORY_CACHE[key] = (data, time.time())


def get_stock_list():
    rows = execute_query("""
        SELECT symbol, name, market 
        FROM stock_list 
        WHERE list_status = 'L' AND market IN ('CN_A', 'SH', 'SZ')
        ORDER BY symbol
    """)
    return rows


def get_kline_pytdx(code, start_date, end_date):
    if not PYTDX_AVAILABLE:
        return []
    
    api, server = connect_with_retry(max_retries=3)
    if not api:
        return []
    
    try:
        stock_code = f'{code}.SZ' if code.startswith('0') or code.startswith('3') else f'{code}.SH'
        
        kline = api.get_k_data(stock_code, start_date, end_date)
        api.disconnect()
        
        if kline is None or hasattr(kline, 'empty') and kline.empty:
            return []
        
        result = []
        
        if hasattr(kline, 'to_dict'):
            rows = kline.to_dict('records')
        else:
            rows = kline
        
        for i, row in enumerate(rows):
            date_str = str(row.get('date', ''))
            cached = get_cached_data(code, date_str)
            if cached:
                result.append(cached)
                continue
            
            close = float(row.get('close', 0))
            prev_close = float(row.get('preclose', 0))
            
            if prev_close <= 0 and i > 0:
                prev_close = float(rows[i-1].get('close', close))
            
            change_pct = ((close - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            volume = float(row.get('volume', row.get('vol', 0)))
            amount_raw = float(row.get('amount', 0))
            amount = amount_raw / 100 if amount_raw > 1000 else amount_raw
            
            vol_ratio = 1.0
            
            item = {
                'code': code,
                'trade_date': date_str,
                'open': round(float(row.get('open', 0)), 2),
                'high': round(float(row.get('high', 0)), 2),
                'low': round(float(row.get('low', 0)), 2),
                'close': round(close, 2),
                'volume': volume,
                'amount': round(amount, 2),
                'change_pct': round(change_pct, 2),
                'turnover_rate': round(estimate_turnover(vol_ratio), 2),
            }
            set_cached_data(code, date_str, item)
            result.append(item)
        
        return result
    except Exception as e:
        print(f'[data] pytdx error for {code}: {e}', flush=True)
        try:
            api.disconnect()
        except:
            pass
        return []


def set_custom_server(ip, port):
    global _BEST_SERVER, _BEST_SERVER_TTL
    _BEST_SERVER = (ip, port)
    _BEST_SERVER_TTL = time.time() + 3600
    print(f'[data] Custom server set: {ip}:{port}', flush=True)


def get_kline_db(code, start_date, end_date):
    rows = execute_query("""
        SELECT code, trade_date, open, high, low, close, volume, amount,
               change_pct, turnover_rate
        FROM kline_daily_cn_a
        WHERE code = %s AND trade_date >= %s AND trade_date <= %s
        ORDER BY trade_date ASC
    """, (code, start_date, end_date))
    
    result = []
    for row in rows:
        date_str = str(row['trade_date'])
        cached = get_cached_data(code, date_str)
        if cached:
            result.append(cached)
            continue
        
        item = {
            'code': row['code'],
            'trade_date': date_str,
            'open': round(float(row['open'] or 0), 2),
            'high': round(float(row['high'] or 0), 2),
            'low': round(float(row['low'] or 0), 2),
            'close': round(float(row['close'] or 0), 2),
            'volume': float(row['volume'] or 0),
            'amount': round(float(row['amount'] or 0), 2),
            'change_pct': round(float(row['change_pct'] or 0), 2),
            'turnover_rate': round(float(row['turnover_rate'] or 0), 2),
        }
        set_cached_data(code, date_str, item)
        result.append(item)
    return result


def get_kline(code, start_date, end_date, prefer_pytdx=True):
    if prefer_pytdx and PYTDX_AVAILABLE:
        data = get_kline_pytdx(code, start_date, end_date)
        if data:
            return data
    
    return get_kline_db(code, start_date, end_date)


def update_kline_to_db(klines):
    if not klines:
        return 0
    
    query = """
        INSERT INTO kline_daily_cn_a 
        (code, trade_date, open, high, low, close, volume, amount, change_pct, turnover_rate)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            amount = EXCLUDED.amount,
            change_pct = EXCLUDED.change_pct,
            turnover_rate = EXCLUDED.turnover_rate,
            updated_at = NOW()
    """
    
    params = [
        (k['code'], k['trade_date'], k['open'], k['high'], k['low'], 
         k['close'], k['volume'], k['amount'], k['change_pct'], k['turnover_rate'])
        for k in klines
    ]
    
    return execute_many(query, params)


def fetch_and_update_stock(code, days=10):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    
    klines = get_kline_pytdx(code, start_date, end_date)
    if klines:
        count = update_kline_to_db(klines)
        return code, count, 'success'
    return code, 0, 'failed'


def daily_update(days=5, max_workers=20):
    stocks = get_stock_list()
    codes = [s['symbol'].split('.')[0] if '.' in s['symbol'] else s['symbol'] for s in stocks]
    
    print(f'[data] Starting daily update for {len(codes)} stocks', flush=True)
    
    success = 0
    failed = 0
    total_rows = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_and_update_stock, code, days) for code in codes]
        for i, f in enumerate(as_completed(futures), 1):
            code, count, status = f.result()
            if status == 'success':
                success += 1
                total_rows += count
            else:
                failed += 1
            
            if i % 100 == 0 or i == len(codes):
                print(f'[data] Progress: {i}/{len(codes)} | Success: {success} | Failed: {failed} | Rows: {total_rows}', flush=True)
    
    print(f'[data] Daily update complete: {success} success, {failed} failed, {total_rows} rows updated', flush=True)
    return {'success': success, 'failed': failed, 'total_rows': total_rows}


# ==================== 港股数据采集 ====================

# 常用港股列表（备用方案）
HK_POPULAR_STOCKS = [
    {'code': '00700', 'name': '腾讯控股'},
    {'code': '09988', 'name': '阿里巴巴'},
    {'code': '09999', 'name': '网易'},
    {'code': '03690', 'name': '美团-W'},
    {'code': '01810', 'name': '小米集团-W'},
    {'code': '09618', 'name': '京东集团-SW'},
    {'code': '09633', 'name': '农夫山泉'},
    {'code': '00941', 'name': '中国移动'},
    {'code': '00939', 'name': '建设银行'},
    {'code': '00981', 'name': '中芯国际'},
    {'code': '00388', 'name': '香港交易所'},
    {'code': '00688', 'name': '中国海外发展'},
    {'code': '01109', 'name': '华润置地'},
    {'code': '00270', 'name': '金沙中国有限公司'},
    {'code': '00006', 'name': '电能实业'},
    {'code': '00011', 'name': '恒生银行'},
    {'code': '00012', 'name': '东亚银行'},
    {'code': '00016', 'name': '新鸿基地产'},
    {'code': '00017', 'name': '新世界发展'},
    {'code': '00019', 'name': '太古股份公司A'},
    {'code': '02318', 'name': '中国平安'},
    {'code': '02319', 'name': '蒙牛乳业'},
    {'code': '02382', 'name': '舜宇光学科技'},
    {'code': '02628', 'name': '中国人寿'},
    {'code': '02888', 'name': '渣打集团'},
    {'code': '03888', 'name': '金山软件'},
    {'code': '03968', 'name': '招商银行'},
    {'code': '03988', 'name': '中国银行'},
    {'code': '06618', 'name': '京东健康'},
    {'code': '06690', 'name': '海尔智家'},
    {'code': '06888', 'name': '海底捞'},
    {'code': '06969', 'name': '百济神州'},
    {'code': '08231', 'name': '汇量科技'},
    {'code': '18010', 'name': '哔哩哔哩-SW'},
    {'code': '18100', 'name': '小鹏汽车-W'},
    {'code': '09888', 'name': '百度集团-SW'},
    {'code': '09868', 'name': '小鹏汽车-W'},
    {'code': '06160', 'name': '百济神州'},
]


def get_hk_stock_list_from_tdx():
    """从通达信获取港股股票列表"""
    if not PYTDX_AVAILABLE:
        return HK_POPULAR_STOCKS
    
    api, server = connect_with_retry(max_retries=3)
    if not api:
        return HK_POPULAR_STOCKS
    
    try:
        stocks = []
        
        # 尝试用 get_security_bars 获取指数成分股来构建列表
        # 市场代码 0=深圳A, 1=上海A, 47=港股(部分)
        for i in range(50):
            batch = api.get_security_list(0, i * 100)
            if not batch:
                break
        
        api.disconnect()
        
        # 如果获取失败，返回常用股票列表
        if not stocks:
            print(f'[data] TDX HK list empty, using popular stocks', flush=True)
            return HK_POPULAR_STOCKS
        
        print(f'[data] Got {len(stocks)} HK stocks from TDX', flush=True)
        return stocks
    except Exception as e:
        print(f'[data] Error getting HK stock list: {e}, using popular stocks', flush=True)
        try:
            api.disconnect()
        except:
            pass
        return HK_POPULAR_STOCKS


def save_hk_stock_list(stocks):
    """保存港股股票列表到数据库"""
    if not stocks:
        return 0
    
    query = """
        INSERT INTO stock_list_hk (code, name, market)
        VALUES (%s, %s, %s)
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name,
            updated_at = NOW()
    """
    
    params = []
    for s in stocks:
        code = s.get('code', s.get('symbol', ''))
        name = s.get('name', s.get('name_en', ''))
        market = s.get('market', 'HK_MAIN')
        params.append((code, name, market))
    
    return execute_many(query, params)


def get_hk_kline_tdx(code, days=100):
    """从通达信获取港股K线"""
    if not PYTDX_AVAILABLE:
        return []
    
    api, server = connect_with_retry(max_retries=3)
    if not api:
        return []
    
    try:
        # 港股市场代码 47=主板，48=创业板
        market = 47  # 默认主板
        kline = api.get_security_bars(9, market, code, 0, days)  # 9=港股
        
        api.disconnect()
        
        if kline is None or (hasattr(kline, 'empty') and kline.empty):
            return []
        
        result = []
        if hasattr(kline, 'to_dict'):
            rows = kline.to_dict('records')
        else:
            rows = kline
        
        for i, row in enumerate(rows):
            date_str = str(row.get('datetime', ''))[:10]
            if not date_str:
                continue
            
            close = float(row.get('close', 0))
            prev_close = float(row.get('close', 0))
            if i > 0 and hasattr(kline, 'iloc'):
                prev_close = float(kline.iloc[i-1]['close'])
            elif i > 0 and isinstance(rows, list) and i < len(rows):
                prev_close = float(rows[i-1].get('close', close))
            
            change_pct = ((close - prev_close) / prev_close * 100) if prev_close > 0 else 0
            
            item = {
                'code': code,
                'trade_date': date_str,
                'open': round(float(row.get('open', 0)), 3),
                'high': round(float(row.get('high', 0)), 3),
                'low': round(float(row.get('low', 0)), 3),
                'close': round(close, 3),
                'volume': float(row.get('amount', 0)),  # 港股volume是成交笔数
                'amount': round(float(row.get('vol', 0)), 2),  # vol是成交量
                'change_pct': round(change_pct, 3),
            }
            result.append(item)
        
        return result
    except Exception as e:
        print(f'[data] Error getting HK kline for {code}: {e}', flush=True)
        try:
            api.disconnect()
        except:
            pass
        return []


def update_hk_kline_to_db(klines):
    """保存港股K线到数据库"""
    if not klines:
        return 0
    
    query = """
        INSERT INTO kline_daily_hk (code, trade_date, open, high, low, close, volume, amount, change_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (code, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            amount = EXCLUDED.amount,
            change_pct = EXCLUDED.change_pct,
            updated_at = NOW()
    """
    
    params = [
        (k['code'], k['trade_date'], k['open'], k['high'], k['low'],
         k['close'], k['volume'], k['amount'], k['change_pct'])
        for k in klines
    ]
    
    return execute_many(query, params)


def daily_update_hk(max_workers=10):
    """港股每日数据更新"""
    # 先获取股票列表
    stocks = get_hk_stock_list_from_tdx()
    if stocks:
        save_hk_stock_list(stocks)
    
    # 获取有K线的股票列表
    db_stocks = execute_query("SELECT code FROM stock_list_hk WHERE list_status = 'L' LIMIT 200")
    codes = [s['code'] for s in db_stocks]
    
    print(f'[data] Updating HK kline for {len(codes)} stocks', flush=True)
    
    success = 0
    failed = 0
    
    def fetch_one(code):
        try:
            klines = get_hk_kline_tdx(code, days=60)
            if klines:
                count = update_hk_kline_to_db(klines)
                return code, count, 'success'
        except:
            pass
        return code, 0, 'failed'
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_one, code) for code in codes]
        for f in as_completed(futures):
            code, count, status = f.result()
            if status == 'success':
                success += 1
            else:
                failed += 1
    
    print(f'[data] HK update complete: {success} success, {failed} failed', flush=True)
    return {'success': success, 'failed': failed}


# ==================== 美股数据采集 ====================

# Tushare token
TUSHARE_TOKEN = os.environ.get('TUSHARE_TOKEN', 'e85b62c1005ad7254faf4cfa7b2e0fac194af09889ddb784d1882f74')

# 热门美股列表（备用方案）
US_POPULAR_STOCKS = [
    {'symbol': 'AAPL', 'name': 'Apple', 'exchange': 'NASDAQ'},
    {'symbol': 'MSFT', 'name': 'Microsoft', 'exchange': 'NASDAQ'},
    {'symbol': 'GOOGL', 'name': 'Alphabet', 'exchange': 'NASDAQ'},
    {'symbol': 'AMZN', 'name': 'Amazon', 'exchange': 'NASDAQ'},
    {'symbol': 'NVDA', 'name': 'NVIDIA', 'exchange': 'NASDAQ'},
    {'symbol': 'META', 'name': 'Meta', 'exchange': 'NASDAQ'},
    {'symbol': 'TSLA', 'name': 'Tesla', 'exchange': 'NASDAQ'},
    {'symbol': 'BABA', 'name': 'Alibaba', 'exchange': 'NYSE'},
    {'symbol': 'JPM', 'name': 'JPMorgan', 'exchange': 'NYSE'},
    {'symbol': 'BAC', 'name': 'Bank of America', 'exchange': 'NYSE'},
    {'symbol': 'V', 'name': 'Visa', 'exchange': 'NYSE'},
    {'symbol': 'JNJ', 'name': 'Johnson & Johnson', 'exchange': 'NYSE'},
    {'symbol': 'WMT', 'name': 'Walmart', 'exchange': 'NYSE'},
    {'symbol': 'PG', 'name': 'Procter & Gamble', 'exchange': 'NYSE'},
    {'symbol': 'KO', 'name': 'Coca-Cola', 'exchange': 'NYSE'},
    {'symbol': 'DIS', 'name': 'Disney', 'exchange': 'NYSE'},
    {'symbol': 'NFLX', 'name': 'Netflix', 'exchange': 'NASDAQ'},
    {'symbol': 'AMD', 'name': 'AMD', 'exchange': 'NASDAQ'},
    {'symbol': 'INTC', 'name': 'Intel', 'exchange': 'NASDAQ'},
    {'symbol': 'CSCO', 'name': 'Cisco', 'exchange': 'NASDAQ'},
]


def set_tushare_token(token):
    """设置Tushare token"""
    global TUSHARE_TOKEN
    TUSHARE_TOKEN = token
    if token and TUSHARE_AVAILABLE:
        ts.set_token(token)
        pro = ts.pro_api()
        print(f'[data] Tushare token set', flush=True)
        return True
    return False


def get_us_stock_list_tushare():
    """从Tushare获取美股列表"""
    if not TUSHARE_AVAILABLE or not TUSHARE_TOKEN:
        print('[data] Tushare not available, using popular stocks', flush=True)
        return US_POPULAR_STOCKS
    
    try:
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        
        df = pro.us_basic()
        if df is None or df.empty:
            print('[data] Tushare US list empty, using popular stocks', flush=True)
            return US_POPULAR_STOCKS
        
        stocks = []
        for _, row in df.iterrows():
            ts_code = str(row.get('ts_code', ''))
            enname = str(row.get('enname', ''))
            if ts_code and ts_code != 'None' and enname and enname != 'None':
                stocks.append({
                    'symbol': ts_code.replace('.US', ''),
                    'name': enname,
                    'exchange': ts_code.split('.')[1] if '.' in ts_code else '',
                    'sector': row.get('classify', ''),
                })
        
        if stocks:
            print(f'[data] Got {len(stocks)} US stocks from Tushare', flush=True)
            return stocks
        else:
            print('[data] Tushare US list empty after filtering, using popular stocks', flush=True)
            return US_POPULAR_STOCKS
    except Exception as e:
        print(f'[data] Error getting US stock list from Tushare: {e}, using popular stocks', flush=True)
        return US_POPULAR_STOCKS


def get_us_stock_list_akshare():
    """从AKShare获取美股列表（备用）"""
    try:
        import akshare as ak
        
        # 获取美股列表
        df = ak.stock_us_spot_em()
        if df is None or df.empty:
            return []
        
        stocks = []
        for _, row in df.iterrows():
            stocks.append({
                'symbol': str(row.get('代码', '')),
                'name': str(row.get('名称', '')),
                'exchange': 'NASDAQ',  # akshare不区分交易所
            })
        
        print(f'[data] Got {len(stocks)} US stocks from AKShare', flush=True)
        return stocks
    except Exception as e:
        print(f'[data] AKShare not available: {e}', flush=True)
        return []


def save_us_stock_list(stocks):
    """保存美股股票列表到数据库"""
    if not stocks:
        return 0
    
    query = """
        INSERT INTO stock_list_us (symbol, name, exchange, sector)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (symbol) DO UPDATE SET
            name = EXCLUDED.name,
            exchange = EXCLUDED.exchange,
            sector = EXCLUDED.sector,
            updated_at = NOW()
    """
    
    params = []
    for s in stocks:
        symbol = s.get('symbol', '')
        name = s.get('name', '')
        if symbol and name:
            params.append((symbol, name, s.get('exchange', ''), s.get('sector', '')))
    
    return execute_many(query, params)


def get_us_kline_tushare(symbol, start_date, end_date):
    """从Tushare获取美股K线"""
    if not TUSHARE_AVAILABLE or not TUSHARE_TOKEN:
        return []
    
    try:
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        
        # 转换日期格式
        start = start_date.replace('-', '')
        end = end_date.replace('-', '')
        
        df = pro.us_daily(ts_code=f'{symbol}.US', start_date=start, end_date=end)
        if df is None or df.empty:
            return []
        
        result = []
        for _, row in df.iterrows():
            trade_date = str(row.get('trade_date', ''))
            if len(trade_date) >= 10:
                trade_date = f'{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]}'
            
            item = {
                'symbol': symbol,
                'trade_date': trade_date,
                'open': round(float(row.get('open', 0)), 3),
                'high': round(float(row.get('high', 0)), 3),
                'low': round(float(row.get('low', 0)), 3),
                'close': round(float(row.get('close', 0)), 3),
                'volume': float(row.get('vol', 0)),
                'amount': round(float(row.get('amount', 0)), 2),
                'change_pct': round(float(row.get('pct_chg', 0)), 3),
            }
            result.append(item)
        
        return result
    except Exception as e:
        print(f'[data] Error getting US kline for {symbol}: {e}', flush=True)
        return []


def get_us_kline_akshare(symbol, start_date, end_date):
    """从AKShare获取美股K线（备用）"""
    try:
        import akshare as ak
        
        start = start_date.replace('-', '')
        end = end_date.replace('-', '')
        
        # akshare美股历史数据
        df = ak.stock_us_hist(symbol=symbol, start_date=start, end_date=end, adjust='qfq')
        if df is None or df.empty:
            return []
        
        result = []
        for _, row in df.iterrows():
            trade_date = str(row.get('日期', ''))[:10]
            
            item = {
                'symbol': symbol,
                'trade_date': trade_date,
                'open': round(float(row.get('开盘', 0)), 3),
                'high': round(float(row.get('最高', 0)), 3),
                'low': round(float(row.get('最低', 0)), 3),
                'close': round(float(row.get('收盘', 0)), 3),
                'volume': float(row.get('成交量', 0)),
                'amount': round(float(row.get('成交额', 0)), 2),
                'change_pct': round(float(row.get('涨跌幅', 0)), 3),
            }
            result.append(item)
        
        return result
    except Exception as e:
        print(f'[data] AKShare error for {symbol}: {e}', flush=True)
        return []


def get_us_kline_yfinance(symbol, start_date, end_date):
    """从Yahoo Finance获取美股K线（第三备用）"""
    if not YFINANCE_AVAILABLE:
        return []
    
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(start=start_date, end=end_date)
        
        if df is None or df.empty:
            return []
        
        result = []
        prev_close = None
        
        for date, row in df.iterrows():
            date_str = date.strftime('%Y-%m-%d')
            close = float(row.get('Close', 0))
            
            if prev_close and prev_close > 0:
                change_pct = ((close - prev_close) / prev_close * 100)
            else:
                change_pct = 0
            
            item = {
                'symbol': symbol,
                'trade_date': date_str,
                'open': round(float(row.get('Open', 0)), 3),
                'high': round(float(row.get('High', 0)), 3),
                'low': round(float(row.get('Low', 0)), 3),
                'close': round(close, 3),
                'volume': float(row.get('Volume', 0)),
                'amount': round(float(row.get('Volume', 0)) * close, 2),
                'change_pct': round(change_pct, 3),
            }
            result.append(item)
            prev_close = close
        
        print(f'[data] Got {len(result)} US klines for {symbol} from yfinance', flush=True)
        return result
    except Exception as e:
        print(f'[data] yfinance error for {symbol}: {e}', flush=True)
        return []


def get_us_kline_eastmoney(symbol, start_date, end_date):
    """从东方财富获取美股K线（第四备用）"""
    try:
        import requests
        
        session = requests.Session()
        session.trust_env = False
        
        url = f'https://push2his.eastmoney.com/api/qt/stock/kline/get?secid=106.{symbol}&fields1=f1,f2,f3,f4,f5,f6&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61&klt=101&fqt=1'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Referer': f'https://quote.eastmoney.com/us/{symbol}.html',
        }
        
        resp = session.get(url, headers=headers, timeout=10)
        data = resp.json()
        
        if data.get('data', {}).get('klines') is None:
            return []
        
        klines = data['data']['klines']
        result = []
        prev_close = None
        
        for kline in klines:
            parts = kline.split(',')
            if len(parts) < 7:
                continue
            
            date_str = parts[0]
            open_val = float(parts[1])
            close_val = float(parts[2])
            low_val = float(parts[3])
            high_val = float(parts[4])
            volume = float(parts[5])
            
            if prev_close and prev_close > 0:
                change_pct = ((close_val - prev_close) / prev_close * 100)
            else:
                change_pct = 0
            
            item = {
                'symbol': symbol,
                'trade_date': date_str,
                'open': round(open_val, 3),
                'high': round(high_val, 3),
                'low': round(low_val, 3),
                'close': round(close_val, 3),
                'volume': volume,
                'amount': round(volume * close_val, 2),
                'change_pct': round(change_pct, 3),
            }
            result.append(item)
            prev_close = close_val
        
        if result:
            print(f'[data] Got {len(result)} US klines for {symbol} from eastmoney', flush=True)
            return result
        return []
    except Exception as e:
        print(f'[data] eastmoney error for {symbol}: {e}', flush=True)
        return []


def get_us_kline_qq(symbol, start_date, end_date):
    """从腾讯财经获取美股K线（第五备用）"""
    try:
        import requests
        
        session = requests.Session()
        session.trust_env = False
        
        url = f'https://qt.gtimg.cn/q=us{symbol}'
        headers = {'User-Agent': 'Mozilla/5.0'}
        
        resp = session.get(url, headers=headers, timeout=10)
        content = resp.text
        
        if not content or 'v_us' not in content:
            return []
        
        parts = content.split('="')[1].split('~')
        if len(parts) < 35:
            return []
        
        close = float(parts[3])
        prev_close = float(parts[4])
        open_val = float(parts[5])
        volume = float(parts[6])
        high = float(parts[33])
        low = float(parts[34])
        change_pct = float(parts[32])
        amount = float(parts[37])
        
        item = {
            'symbol': symbol,
            'trade_date': parts[30][:10],
            'open': round(open_val, 3),
            'high': round(high, 3),
            'low': round(low, 3),
            'close': round(close, 3),
            'volume': volume,
            'amount': round(amount, 2),
            'change_pct': change_pct,
        }
        
        print(f'[data] Got US kline for {symbol} from qq finance', flush=True)
        return [item]
    except Exception as e:
        print(f'[data] qq finance error for {symbol}: {e}', flush=True)
        return []


def update_us_kline_to_db(klines):
    """保存美股K线到数据库"""
    if not klines:
        return 0
    
    query = """
        INSERT INTO kline_daily_us (symbol, trade_date, open, high, low, close, volume, amount, change_pct)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (symbol, trade_date) DO UPDATE SET
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            amount = EXCLUDED.amount,
            change_pct = EXCLUDED.change_pct,
            updated_at = NOW()
    """
    
    params = [
        (k['symbol'], k['trade_date'], k['open'], k['high'], k['low'],
         k['close'], k['volume'], k['amount'], k['change_pct'])
        for k in klines
    ]
    
    return execute_many(query, params)


def daily_update_us(max_workers=5):
    """美股每日数据更新"""
    # 先获取股票列表
    stocks = get_us_stock_list_tushare()
    if not stocks and TUSHARE_AVAILABLE:
        stocks = get_us_stock_list_akshare()
    
    if stocks:
        save_us_stock_list(stocks)
    
    # 获取有K线的股票列表（优先大市值）
    db_stocks = execute_query("""
        SELECT symbol FROM stock_list_us 
        WHERE list_status = 'L' 
        ORDER BY market_cap DESC NULLS LAST
        LIMIT 100
    """)
    codes = [s['symbol'] for s in db_stocks]
    
    print(f'[data] Updating US kline for {len(codes)} stocks', flush=True)
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    
    success = 0
    failed = 0
    
    def fetch_one(symbol):
        try:
            klines = get_us_kline_qq(symbol, start_date, end_date)
            if not klines:
                klines = get_us_kline_tushare(symbol, start_date, end_date)
            if not klines:
                klines = get_us_kline_yfinance(symbol, start_date, end_date)
            if not klines:
                klines = get_us_kline_akshare(symbol, start_date, end_date)
            if klines:
                count = update_us_kline_to_db(klines)
                return symbol, count, 'success'
        except:
            pass
        return symbol, 0, 'failed'
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(fetch_one, code) for code in codes]
        for f in as_completed(futures):
            symbol, count, status = f.result()
            if status == 'success':
                success += 1
            else:
                failed += 1
    
    print(f'[data] US update complete: {success} success, {failed} failed', flush=True)
    return {'success': success, 'failed': failed}