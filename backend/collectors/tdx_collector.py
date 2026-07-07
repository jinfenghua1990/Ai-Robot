"""
pytdx 数据采集器
- 动态服务器寻优 + 重试
- 板块资金流向采集
- 个股资金流向采集
- 涨停股识别
"""
import sys, os, time, threading
from datetime import datetime, timedelta
import logging
from concurrent.futures import ThreadPoolExecutor
import requests


logger = logging.getLogger(__name__)
# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow, StockFlow, LeaderLifecycle

try:
    from pytdx.hq import TdxHq_API
    try:
        from pytdx.util.best_ip import stock_ip
        TDX_SERVERS = [(s['ip'], s['port']) for s in stock_ip]
    except Exception:
        # best_ip 模块不可用时降级使用硬编码服务器列表
        TDX_SERVERS = [
            ('106.120.74.86', 7711),   # 北京行情主站1
            ('112.74.214.43', 7711),   # 深圳行情主站1
            ('221.231.141.60', 7711),  # 南京行情主站1
            ('101.227.73.20', 7711),   # 上海行情主站1
            ('101.227.77.254', 7711),  # 上海行情主站2
            ('14.17.75.71', 7711),     # 深圳行情主站2
            ('59.173.18.140', 7711),   # 武汉行情主站1
            ('180.153.39.51', 7711),   # 上海行情主站3
        ]
    PYTDX_AVAILABLE = True
except ImportError:
    PYTDX_AVAILABLE = False
    TDX_SERVERS = []

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

def call_tushare_mcp(api_name, params=None, fields=None):
    """调用 Tushare HTTP API"""
    from config import TUSHARE_TOKEN
    if not TUSHARE_TOKEN:
        logger.info('[tushare-api] No token configured')
        return None
    url = 'http://api.tushare.pro'
    payload = {
        'api_name': api_name,
        'token': TUSHARE_TOKEN,
        'params': params or {},
        'fields': ','.join(fields) if isinstance(fields, list) else (fields or '')
    }
    headers = {
        'Content-Type': 'application/json'
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        result = response.json()
        if result.get('code') != 0:
            logger.error(f'[tushare-api] API error code {result.get("code")}: {result.get("msg", "Unknown")}')
            return None
        if result.get('data') and result['data'].get('items'):
            data = result['data']
            columns = data.get('fields', [])
            items = data.get('items', [])
            return [dict(zip(columns, row)) for row in items]
        else:
            logger.info(f'[tushare-api] No data returned')
            return None
    except Exception as e:
        logger.error(f'[tushare-api] Request error: {e}')
        return None

_BEST_SERVER = None
_BEST_SERVER_TTL = 0
_thread_local = threading.local()


def get_thread_api():
    """获取线程隔离的TdxHq_API实例"""
    if not hasattr(_thread_local, 'api'):
        _thread_local.api = TdxHq_API()
    return _thread_local.api


def test_server(ip, port, timeout=3):
    """测试服务器延迟"""
    try:
        start = time.time()
        api = TdxHq_API()
        if api.connect(ip, port, time_out=timeout):
            api.disconnect()
            latency = (time.time() - start) * 1000
            return ip, port, latency
        return ip, port, float('inf')
    except Exception:
        logger.debug(f"test_server failed", exc_info=True)
        return ip, port, float('inf')


def get_best_server():
    """动态寻找最优服务器，5分钟缓存"""
    global _BEST_SERVER, _BEST_SERVER_TTL
    now = time.time()
    if _BEST_SERVER and now < _BEST_SERVER_TTL:
        return _BEST_SERVER
    if not TDX_SERVERS:
        return None
    logger.info(f'[tdx] Testing {len(TDX_SERVERS)} servers...')
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda s: test_server(s[0], s[1]), TDX_SERVERS))
    results = [r for r in results if r[2] < float('inf')]
    if not results:
        logger.info('[tdx] No server available')
        return None
    results.sort(key=lambda x: x[2])
    _BEST_SERVER = (results[0][0], results[0][1])
    _BEST_SERVER_TTL = now + 300
    logger.info(f'[tdx] Best server: {_BEST_SERVER[0]}:{_BEST_SERVER[1]} ({results[0][2]:.1f}ms)')
    return _BEST_SERVER


def connect_with_retry(max_retries=3):
    """带重试的连接"""
    if not PYTDX_AVAILABLE:
        return None, None
    server = get_best_server()
    candidates = []
    if server:
        candidates.append(server)
    candidates.extend(TDX_SERVERS[:10])
    for i, (ip, port) in enumerate(candidates[:max_retries]):
        try:
            api = get_thread_api()
            return api, (ip, port)
        except Exception as e:
            logger.debug(f'[tdx] TDX 连接失败 {ip}:{port} - {e}')
        time.sleep(0.5)
    return None, None


def get_sector_list():
    """获取板块列表"""
    # 使用 pytdx 获取板块列表
    # pytdx 的 get_security_list 或 get_block_info 可以获取板块
    # 返回格式: [{'name': 'AI', 'code': '...'}, ...]
    api, server = connect_with_retry()
    if not api:
        return []
    try:
        # 获取板块分类
        # market=0 深圳, market=1 上海
        # pytdx 板块接口
        blocks = []
        # 尝试获取概念板块
        for market in [0, 1]:
            result = api.get_security_list(market, 0)
            if result:
                for item in result[:50]:  # 限制数量
                    blocks.append({
                        'name': item.get('name', ''),
                        'code': item.get('code', ''),
                        'market': market
                    })
        api.disconnect()
        return blocks
    except Exception as e:
        logger.error(f'[tdx] get_sector_list error: {e}')
        return []


_moneyflow_cache = {}  # {date: (df, pro)}


def _get_stock_basic_from_tdx():
    """从通达信获取股票基础信息"""
    import pandas as pd
    api, server = connect_with_retry()
    if not api:
        return None
    try:
        stocks = []
        for market in [0, 1]:
            data = api.get_security_list(market, 0)
            if data:
                for item in data:
                    stocks.append({
                        'ts_code': f"{item['code']}.{'SZ' if market == 0 else 'SH'}",
                        'name': item.get('name', ''),
                        'industry': ''
                    })
        api.disconnect()
        if stocks:
            return pd.DataFrame(stocks)
        return None
    except Exception as e:
        logger.error(f'[tdx] _get_stock_basic_from_tdx error: {e}')
        return None


def _get_daily_from_tdx(trade_date):
    """从通达信获取日线行情数据"""
    import pandas as pd
    api, server = connect_with_retry()
    if not api:
        return None
    try:
        date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
        daily_data = []
        for market in [0, 1]:
            data = api.get_security_list(market, 0)
            if data:
                codes = [item['code'] for item in data[:1000]]
                for i in range(0, len(codes), 100):
                    batch = codes[i:i+100]
                    for code in batch:
                        try:
                            kline = api.get_security_bars(9, market, code, 0, 1)
                            if kline and len(kline) > 0:
                                bar = kline[0]
                                pct_change = ((bar['close'] - bar['pre_close']) / bar['pre_close'] * 100) if bar['pre_close'] else 0
                                daily_data.append({
                                    'ts_code': f"{code}.{'SZ' if market == 0 else 'SH'}",
                                    'close': bar['close'],
                                    'pre_close': bar['pre_close'],
                                    'pct_change': round(pct_change, 2),
                                    'vol': bar['vol'],
                                })
                        except Exception as e:
                            logger.debug(f'[tdx] 单股 K线拉取失败 market={market} code={code}: {e}')
        api.disconnect()
        if daily_data:
            return pd.DataFrame(daily_data)
        return None
    except Exception as e:
        logger.error(f'[tdx] _get_daily_from_tdx error: {e}')
        return None


def _get_moneyflow_data(trade_date):
    """获取资金流向数据
    - 资金流向：只能用 Tushare（pytdx不支持）
    - 日线行情：优先用 pytdx（实时、免费），降级用 Tushare
    - 股票基础信息：优先用 Tushare（有行业数据），降级用 pytdx
    """
    import pandas as pd
    if trade_date in _moneyflow_cache:
        return _moneyflow_cache[trade_date]
    date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
    
    try:
        mf_data = call_tushare_mcp(
            'moneyflow',
            params={'trade_date': date_str},
            fields=['ts_code', 'net_mf_amount', 'buy_elg_amount', 'sell_elg_amount', 
                    'buy_sm_amount', 'sell_sm_amount', 'buy_md_amount', 'sell_md_amount']
        )
        if mf_data:
            df = pd.DataFrame(mf_data)
            logger.info(f'[tushare] Got {len(df)} moneyflow records')
            
            daily_df = None
            if PYTDX_AVAILABLE:
                daily_df = _get_daily_from_tdx(trade_date)
                if daily_df is not None:
                    logger.info(f'[tdx] Got {len(daily_df)} daily records')
            
            if daily_df is None:
                daily_data = call_tushare_mcp(
                    'daily',
                    params={'trade_date': date_str},
                    fields=['ts_code', 'pct_chg', 'close']
                )
                if daily_data:
                    daily_df = pd.DataFrame(daily_data)
                    daily_df = daily_df.rename(columns={'pct_chg': 'pct_change'})
                    logger.info(f'[tushare] Got {len(daily_df)} daily records')
            
            if daily_df is not None:
                df = df.merge(daily_df[['ts_code', 'pct_change', 'close']], on='ts_code', how='left')
            
            stock_df = None
            stock_data = call_tushare_mcp(
                'stock_basic',
                params={'list_status': 'L'},
                fields=['ts_code', 'name', 'industry']
            )
            if stock_data:
                stock_df = pd.DataFrame(stock_data)
                logger.info(f'[tushare] Got {len(stock_df)} stock basic records')
            
            if stock_df is None and PYTDX_AVAILABLE:
                stock_df = _get_stock_basic_from_tdx()
                if stock_df is not None:
                    logger.info(f'[tdx] Got {len(stock_df)} stock basic records')
            
            if stock_df is not None:
                df = df.merge(stock_df[['ts_code', 'name', 'industry']], on='ts_code', how='left')
            
            result = (df, None)
            _moneyflow_cache[trade_date] = result
            return result
    except Exception as e:
        logger.error(f'[tushare] moneyflow error: {e}')
    
    if not TUSHARE_AVAILABLE:
        return None, None
    try:
        from config import TUSHARE_TOKEN
        if not TUSHARE_TOKEN:
            return None, None
        ts.set_token(TUSHARE_TOKEN)
        pro = ts.pro_api()
        df = pro.moneyflow(trade_date=date_str)
        if df is None or df.empty:
            logger.info(f'[tushare] moneyflow returned empty for {date_str}')
            return None, None
        
        daily_df = None
        if PYTDX_AVAILABLE:
            daily_df = _get_daily_from_tdx(trade_date)
        
        if daily_df is None:
            try:
                daily = pro.daily(trade_date=date_str)
                if daily is not None and not daily.empty:
                    daily_df = daily[['ts_code', 'pct_chg', 'close']].rename(columns={'pct_chg': 'pct_change'})
            except Exception as e:
                logger.warning(f'[tushare] daily merge warning: {e}')
        
        if daily_df is not None:
            df = df.merge(daily_df[['ts_code', 'pct_change', 'close']], on='ts_code', how='left')
        elif 'pct_chg' in df.columns:
            df = df.rename(columns={'pct_chg': 'pct_change'})
        
        stock_df = None
        try:
            stock_basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,name,industry')
            stock_df = stock_basic
        except Exception as e:
            logger.warning(f'[tushare] stock_basic 拉取失败，将降级到 pytdx: {e}')
        
        if stock_df is None and PYTDX_AVAILABLE:
            stock_df = _get_stock_basic_from_tdx()
        
        if stock_df is not None:
            df = df.merge(stock_df[['ts_code', 'name', 'industry']], on='ts_code', how='left')
        
        result = (df, pro)
        _moneyflow_cache[trade_date] = result
        return result
    except Exception as e:
        logger.error(f'[tushare] _get_moneyflow_data error: {e}')
        return None, None


def _em_fetch_all(fs, fid='f62', po='1', fields='f12,f14,f62,f3,f66,f72,f78,f84'):
    """分页获取东方财富全部数据（单页最多100条，带重试和间隔）"""
    url = 'http://push2.eastmoney.com/api/qt/clist/get'
    all_items = []
    pn = 1
    total = None
    consecutive_failures = 0
    while True:
        params = {
            'fid': fid, 'po': po, 'pz': '100', 'pn': str(pn),
            'fs': fs, 'fields': fields,
        }
        # 重试5次，指数退避
        data = None
        for attempt in range(5):
            try:
                resp = requests.get(url, params=params, timeout=15,
                                   headers={'User-Agent': 'Mozilla/5.0'})
                data = resp.json().get('data', {})
                break
            except Exception as e:
                if attempt < 4:
                    sleep_time = 0.5 * (2 ** attempt)  # 0.5s, 1s, 2s, 4s
                    time.sleep(sleep_time)
                else:
                    logger.error(f'[em] page {pn} failed after 5 retries: {e}')
                    consecutive_failures += 1
                    # 连续3页失败则放弃，单页失败跳过继续
                    if consecutive_failures >= 3:
                        logger.error(f'[em] {consecutive_failures} consecutive page failures, stopping')
                        return all_items, total
                    # 跳到下一页继续
                    pn += 1
                    time.sleep(1)
                    data = 'skip'  # sentinel
                    break
        if data is None:
            break
        if data == 'skip':
            continue
        if total is None:
            total = data.get('total', 0)
        items = data.get('diff', [])
        if isinstance(items, dict):
            items = list(items.values())
        if not items:
            break
        all_items.extend(items)
        if len(all_items) >= total or len(items) < 100:
            break
        consecutive_failures = 0  # 成功一页则重置连续失败计数
        pn += 1
        time.sleep(0.15)  # 请求间隔，避免被限流
    return all_items, total


def _sina_fetch_sectors(fenlei=0):
    """从新浪财经获取板块资金流向（分页）"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        'Referer': 'http://vip.stock.finance.sina.com.cn/',
    }
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'
    all_items = []
    for page in range(1, 10):
        params = {'page': page, 'num': 100, 'sort': 'netamount', 'asc': 0, 'fenlei': fenlei}
        resp = requests.get(url, params=params, timeout=10, headers=headers)
        data = resp.json()
        if not data:
            break
        all_items.extend(data)
        if len(data) < 100:
            break
    return all_items


def get_concept_sector_money_flow(trade_date):
    """
    获取概念板块资金流向数据（新浪财经 fenlei=1）
    返回格式与 get_sector_money_flow 一致
    """
    try:
        items = _sina_fetch_sectors(fenlei=1)  # 概念板块
        results = []
        for item in items:
            name = item.get('name', '')
            if not name:
                continue
            net_flow = float(item.get('netamount', 0) or 0) / 10000  # 元→万元
            in_amount = float(item.get('inamount', 0) or 0) / 10000
            out_amount = float(item.get('outamount', 0) or 0) / 10000
            rise_ratio = float(item.get('avg_changeratio', 0) or 0) * 100
            results.append({
                'sector': name,
                'net_flow': net_flow,
                'money_inflow': in_amount,
                'money_outflow': out_amount,
                'rise_ratio': rise_ratio,
                'avg_chg': rise_ratio,
            })
        logger.info(f'[sina] Got {len(results)} concept sector flows from 新浪财经')
        return results
    except Exception as e:
        logger.error(f'[sina] concept sector error: {e}')
        return []


def get_sector_money_flow(trade_date):
    """
    获取板块资金流向数据
    优先级：新浪财经 → 东方财富 → Tushare
    返回格式: [{'sector': '银行', 'money_inflow': 100000, 'money_outflow': 50000, 'net_flow': 50000, ...}, ...]
    """
    # === 1. 新浪财经（主数据源）===
    try:
        items = _sina_fetch_sectors(fenlei=0)  # 行业板块
        results = []
        for item in items:
            name = item.get('name', '')
            if not name:
                continue
            # netamount=主力净额(元), avg_changeratio=涨跌幅(小数), inamount=流入(元), outamount=流出(元)
            net_flow = float(item.get('netamount', 0) or 0) / 10000  # 元→万元
            in_amount = float(item.get('inamount', 0) or 0) / 10000
            out_amount = float(item.get('outamount', 0) or 0) / 10000
            rise_ratio = float(item.get('avg_changeratio', 0) or 0) * 100  # 小数→百分比
            results.append({
                'sector': name,
                'net_flow': net_flow,
                'money_inflow': in_amount,
                'money_outflow': out_amount,
                'rise_ratio': rise_ratio,
                'avg_chg': rise_ratio,  # 新浪avg_changeratio=板块平均涨幅，与rise_ratio同值
            })
        logger.info(f'[sina] Got {len(results)} sector flows from 新浪财经')
        if results:
            return results
        logger.info('[sina] 新浪返回空数据，尝试东方财富')
    except Exception as e:
        logger.error(f'[sina] error: {e}, 尝试东方财富')

    # === 2. 东方财富（降级）===
    try:
        items, total = _em_fetch_all('m:90 t:2')
        results = []
        for item in items:
            name = item.get('f14', '')
            if not name:
                continue
            if any(suffix in name for suffix in ['Ⅱ', 'Ⅲ', 'Ⅳ', 'Ⅴ']):
                continue
            net_flow = float(item.get('f62', 0) or 0) / 10000
            elg_flow = float(item.get('f66', 0) or 0) / 10000
            rise_ratio = float(item.get('f3', 0) or 0) / 100
            results.append({
                'sector': name,
                'net_flow': net_flow,
                'money_inflow': elg_flow if elg_flow > 0 else 0,
                'money_outflow': -elg_flow if elg_flow < 0 else 0,
                'rise_ratio': rise_ratio,
            })
        logger.info(f'[em] Got {len(results)} sector flows from 东方财富 (total raw: {total})')
        if results:
            return results
        logger.info('[em] 东方财富返回空数据，降级到 Tushare')
    except Exception as e:
        logger.error(f'[em] error: {e}, 降级到 Tushare')

    # === 3. Tushare（最终降级）===
    return _get_sector_money_flow_tushare(trade_date)


def _get_sector_money_flow_tushare(trade_date):
    """Tushare 降级方案"""
    df, _ = _get_moneyflow_data(trade_date)
    if df is None:
        return []
    try:
        if 'industry' not in df.columns:
            return []
        df_valid = df[df['industry'].notna() & (df['industry'] != '')]
        if df_valid.empty:
            return []
        agg_dict = {'net_mf_amount': 'sum', 'buy_elg_amount': 'sum', 'sell_elg_amount': 'sum'}
        if 'pct_change' in df_valid.columns:
            agg_dict['pct_change'] = 'mean'
        sector_group = df_valid.groupby('industry').agg(agg_dict).reset_index()
        results = []
        for _, row in sector_group.iterrows():
            results.append({
                'sector': row['industry'],
                'net_flow': float(row['net_mf_amount'] or 0),
                'money_inflow': float(row.get('buy_elg_amount', 0) or 0),
                'money_outflow': float(row.get('sell_elg_amount', 0) or 0),
                'rise_ratio': float(row.get('pct_change', 0) or 0) if 'pct_change' in row else 0.0,
                'avg_chg': float(row.get('pct_change', 0) or 0) if 'pct_change' in row else 0.0,  # 个股涨跌幅mean=板块平均涨幅
            })
        return results
    except Exception as e:
        logger.error(f'[tushare] fallback error: {e}')
        return []


def get_stock_money_flow(trade_date):
    """
    获取个股资金流向数据（东方财富 API，分页获取全量）
    返回格式: [{'ts_code': '000001.SZ', 'sector': '银行', 'net_inflow': 1000, ...}, ...]
    """
    try:
        items, total = _em_fetch_all('m:0 t:6,m:0 t:80,m:1 t:2,m:1 t:23', fields='f12,f14,f62,f3,f66,f84,f2')  # 沪深A股, f2=最新价

        # 从数据库最近的 StockFlow 记录获取股票→行业映射
        with get_db_session() as db:
            from sqlalchemy import func as sqlfunc
            latest_date = db.query(sqlfunc.max(StockFlow.trade_date)).scalar()
            stock_map = {}
            if latest_date:
                for sf in db.query(StockFlow).filter_by(trade_date=latest_date).all():
                    code = sf.ts_code.replace('.SZ', '').replace('.SH', '')
                    stock_map[code] = sf.sector or ''

        results = []
        for item in items:
            code = item.get('f12', '')
            name = item.get('f14', '')
            if not code:
                continue
            # 转换为 Tushare 格式代码
            if code.startswith('6') or code.startswith('688'):
                ts_code = f'{code}.SH'
            else:
                ts_code = f'{code}.SZ'
            industry = stock_map.get(code, '')
            # f62=主力净流入(元,=超大单+大单), f3=涨跌幅(需/100), f66=超大单, f84=小单, f2=最新价
            net_inflow = float(item.get('f62', 0) or 0) / 10000  # 元→万元
            main_flow = float(item.get('f62', 0) or 0) / 10000  # 主力净流入(同 f62)
            sm_flow = float(item.get('f84', 0) or 0) / 10000    # 小单净流入
            rise_ratio = float(item.get('f3', 0) or 0) / 100  # 涨跌幅 /100
            price = float(item.get('f2', 0) or 0) / 100  # 最新价 /100
            results.append({
                'ts_code': ts_code,
                'name': name,
                'sector': industry,
                'net_inflow': net_inflow,
                'main_force_inflow': main_flow,
                'retail_flow': sm_flow,
                'price_chg': rise_ratio,
                'price': price,
            })
        # 去重（EM API 分页偶有重复）
        seen = set()
        unique_results = []
        for r in results:
            if r['ts_code'] not in seen:
                seen.add(r['ts_code'])
                unique_results.append(r)
        results = unique_results

        logger.info(f'[em] Got {len(results)} stock flows from 东方财富 (total raw: {total})')
        if not results:
            logger.info('[em] 东方财富返回空数据，降级到 Tushare')
            return _get_stock_money_flow_tushare(trade_date)
        return results
    except Exception as e:
        logger.error(f'[em] get_stock_money_flow error: {e}, fallback to Tushare')
        return _get_stock_money_flow_tushare(trade_date)


def _get_stock_money_flow_tushare(trade_date):
    """Tushare 降级方案"""
    df, _ = _get_moneyflow_data(trade_date)
    if df is None:
        return []
    try:
        results = []
        for _, row in df.iterrows():
            net_mf = float(row.get('net_mf_amount', 0) or 0)
            # Tushare 主力净流入 = 超大单净流入（买入-卖出）
            elg_buy = float(row.get('buy_elg_amount', 0) or 0)
            elg_sell = float(row.get('sell_elg_amount', 0) or 0)
            main_flow = elg_buy - elg_sell  # 超大单净流入（万元）
            # 小单净流入
            sm_flow = float(row.get('buy_sm_amount', 0) or 0) - float(row.get('sell_sm_amount', 0) or 0)
            results.append({
                'ts_code': row['ts_code'],
                'name': row.get('name', '') or '',
                'sector': row.get('industry', '') or '',
                'net_inflow': net_mf,  # 所有资金净流入额（万元）
                'main_force_inflow': main_flow,  # 超大单净流入（万元）
                'retail_flow': sm_flow,  # 小单净流入（万元）
                'price_chg': float(row.get('pct_change', 0) or 0),
                'price': float(row.get('close', 0) or 0),
            })
        return results
    except Exception as e:
        logger.error(f'[tushare] fallback error: {e}')
        return []


def get_limit_up_stocks(trade_date):
    """
    获取涨停股列表
    优先使用 pytdx 获取涨幅数据判断，降级使用 Tushare
    """
    import pandas as pd
    date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
    
    # 优先使用 pytdx 获取涨幅判断涨停
    if PYTDX_AVAILABLE:
        logger.info('[tdx] Detecting limit-up stocks via pytdx')
        api, server = connect_with_retry()
        if api:
            try:
                limit_ups = []
                for market in [0, 1]:
                    data = api.get_security_list(market, 0)
                    if data:
                        codes = [item['code'] for item in data[:2000]]
                        for i in range(0, len(codes), 50):
                            batch = codes[i:i+50]
                            for code in batch:
                                try:
                                    kline = api.get_security_bars(9, market, code, 0, 1)
                                    if kline and len(kline) > 0:
                                        bar = kline[0]
                                        if bar['pre_close'] > 0:
                                            pct_change = (bar['close'] - bar['pre_close']) / bar['pre_close'] * 100
                                            if pct_change >= 9.8:
                                                limit_ups.append(ts_code)
                                except Exception as e:
                                    logger.debug(f'[tdx] 单股涨停判定失败 market={market} code={code}: {e}')
                api.disconnect()
                if limit_ups:
                    logger.info(f'[tdx] Found {len(limit_ups)} limit-up stocks')
                    return limit_ups
            except Exception as e:
                logger.error(f'[tdx] get_limit_up_stocks error: {e}')
    
    # 降级使用 Tushare limit_list_d 接口
    try:
        limit_data = call_tushare_mcp(
            'limit_list_d',
            params={'trade_date': date_str, 'limit_type': 'U'},
            fields=['ts_code']
        )
        if limit_data is not None:
            return [item['ts_code'] for item in limit_data]
    except Exception as e:
        logger.info(f'[tushare] limit_list_d 无权限或失败，降级到涨幅判断: {e}')
    
    # 最后降级使用涨幅判断
    logger.info('[tushare] limit_list_d no permission, using pct_change >= 9.8% instead')
    try:
        df, _ = _get_moneyflow_data(trade_date)
        if df is not None and not df.empty and 'pct_change' in df.columns:
            limit_ups = df[df['pct_change'] >= 9.8]['ts_code'].tolist()
            logger.info(f'[tushare] Found {len(limit_ups)} limit-up stocks via pct_change')
            return limit_ups
        else:
            logger.info('[tushare] pct_change not available')
    except Exception as e:
        logger.error(f'[tushare] get_limit_up_stocks error: {e}')

    # 最终降级：从已采集的 StockFlow 数据判断涨停
    try:
        from db.models import StockFlow
        from sqlalchemy import func
        with get_db_session() as db:
            stocks = db.query(StockFlow).filter(
                StockFlow.trade_date == trade_date,
                StockFlow.price_chg >= 9.0
            ).all()
            if stocks:
                limit_ups = [s.ts_code for s in stocks if s.price_chg and float(s.price_chg) >= 9.8]
                logger.info(f'[stockflow] Found {len(limit_ups)} limit-up stocks from StockFlow data')
                return limit_ups
            else:
                logger.info('[stockflow] No limit-up stocks found in StockFlow data')
    except Exception as e:
        logger.error(f'[stockflow] Error reading StockFlow: {e}')

    return []


def collect_daily_data(trade_date):
    """
    采集单日全量数据并写入数据库
    1. 板块资金流向 → sector_flow 表
    2. 个股资金流向 → stock_flow 表
    3. 涨停股识别 → leader_lifecycle 表（初始阶段）
    """
    logger.info(f'[collect] Starting collection for {trade_date}')

    # 1. 采集板块资金流向
    sector_flows = get_sector_money_flow(trade_date)
    logger.info(f'[collect] Got {len(sector_flows)} sector flows')

    try:
        with get_db_session() as db:
            # 批量查询已存在的板块记录，用字典做 O(1) 查找
            existing_sectors = {s.sector: s for s in db.query(SectorFlow).filter_by(trade_date=trade_date).all()}
            for sf in sector_flows:
                existing = existing_sectors.get(sf['sector'])
                if existing:
                    # 更新
                    existing.money_inflow = sf.get('money_inflow')
                    existing.money_outflow = sf.get('money_outflow')
                    existing.net_flow = sf.get('net_flow')
                    existing.rise_ratio = sf.get('rise_ratio')
                    existing.avg_chg = sf.get('avg_chg')
                else:
                    # 新增
                    record = SectorFlow(
                        trade_date=trade_date,
                        sector=sf['sector'],
                        money_inflow=sf.get('money_inflow'),
                        money_outflow=sf.get('money_outflow'),
                        net_flow=sf.get('net_flow'),
                        rise_ratio=sf.get('rise_ratio'),
                        avg_chg=sf.get('avg_chg'),
                    )
                    db.add(record)
            db.commit()
            logger.info(f'[collect] Sector flows saved')
    except Exception as e:
        db.rollback()
        logger.error(f'[collect] Sector flow error: {e}')

    # 2. 采集个股资金流向
    stock_flows = get_stock_money_flow(trade_date)
    logger.info(f'[collect] Got {len(stock_flows)} stock flows')

    try:
        with get_db_session() as db:
            # 批量查询已存在的个股记录，用字典做 O(1) 查找
            existing_stocks = {s.ts_code: s for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}
            for sf in stock_flows:
                existing = existing_stocks.get(sf['ts_code'])
                if existing:
                    existing.net_inflow = sf.get('net_inflow')
                    existing.main_force_inflow = sf.get('main_force_inflow')
                    existing.retail_flow = sf.get('retail_flow')
                    existing.price_chg = sf.get('price_chg')
                    existing.price = sf.get('price')
                    existing.sector = sf.get('sector')
                    existing.name = sf.get('name')
                else:
                    record = StockFlow(
                        trade_date=trade_date,
                        ts_code=sf['ts_code'],
                        name=sf.get('name'),
                        sector=sf.get('sector'),
                        net_inflow=sf.get('net_inflow'),
                        main_force_inflow=sf.get('main_force_inflow'),
                        retail_flow=sf.get('retail_flow'),
                        price_chg=sf.get('price_chg'),
                        price=sf.get('price'),
                    )
                    db.add(record)
            db.commit()
            logger.info(f'[collect] Stock flows saved')
    except Exception as e:
        db.rollback()
        logger.error(f'[collect] Stock flow error: {e}')

    # 3. 采集涨停股
    limit_ups = get_limit_up_stocks(trade_date)
    logger.info(f'[collect] Got {len(limit_ups)} limit-up stocks')

    try:
        with get_db_session() as db:
            # 批量查询涨停股的个股记录（用于获取板块/名称），只查一次
            stock_map = {s.ts_code: s for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}
            # 批量查询已存在的 LeaderLifecycle 记录
            existing_leaders = {l.ts_code: l for l in db.query(LeaderLifecycle).filter_by(trade_date=trade_date).all()}
            for ts_code in limit_ups:
                stock = stock_map.get(ts_code)
                sector = stock.sector if stock else None
                stock_name = stock.name if stock else None
                existing = existing_leaders.get(ts_code)
                if not existing:
                    record = LeaderLifecycle(
                        trade_date=trade_date,
                        ts_code=ts_code,
                        name=stock_name,
                        sector=sector,
                        stage='突破',  # 涨停股初始阶段为"突破"
                        strength=20,
                        consecutive_days=1,
                    )
                    db.add(record)
            db.commit()
            logger.info(f'[collect] Leader lifecycle saved')

            # 4. 按板块统计涨停数，更新 SectorFlow.limit_up_count
            sector_limit_counts = {}
            for ts_code in limit_ups:
                stock = stock_map.get(ts_code)
                if stock and stock.sector:
                    sector_limit_counts[stock.sector] = sector_limit_counts.get(stock.sector, 0) + 1

            # 批量查询已存在的板块记录
            existing_sectors = {s.sector: s for s in db.query(SectorFlow).filter_by(trade_date=trade_date).all()}
            for sector_name, count in sector_limit_counts.items():
                sf_record = existing_sectors.get(sector_name)
                if sf_record:
                    sf_record.limit_up_count = count
            db.commit()
            logger.info(f'[collect] Updated limit_up_count for {len(sector_limit_counts)} sectors')
    except Exception as e:
        db.rollback()
        logger.error(f'[collect] Leader lifecycle error: {e}')

    # 5. 采集概念板块资金流向
    try:
        from scripts import sync_concept_sectors
        sync_concept_sectors.sync()
    except Exception as e:
        logger.warning(f'[collect] Concept sector sync warning: {e}')

    concept_flows = get_concept_sector_money_flow(trade_date)
    if concept_flows:
        try:
            with get_db_session() as db:
                concept_map = {c.name: c.id for c in db.query(ConceptSector).all()}
                existing = {
                    (r.concept_sector_id): r
                    for r in db.query(ConceptSectorFlow).filter_by(trade_date=trade_date).all()
                }
                for cf in concept_flows:
                    name = cf['sector']
                    cid = concept_map.get(name)
                    if not cid:
                        # 如果概念板块定义表中没有，自动创建
                        new_c = ConceptSector(name=name, source='sina', stocks='', stock_count=0)
                        db.add(new_c)
                        db.flush()
                        cid = new_c.id
                        concept_map[name] = cid

                    record = existing.get(cid)
                    if record:
                        record.money_inflow = cf.get('money_inflow')
                        record.money_outflow = cf.get('money_outflow')
                        record.net_flow = cf.get('net_flow')
                        record.rise_ratio = cf.get('rise_ratio')
                        record.avg_chg = cf.get('avg_chg')
                    else:
                        db.add(ConceptSectorFlow(
                            trade_date=trade_date,
                            concept_sector_id=cid,
                            concept_name=name,
                            money_inflow=cf.get('money_inflow'),
                            money_outflow=cf.get('money_outflow'),
                            net_flow=cf.get('net_flow'),
                            rise_ratio=cf.get('rise_ratio'),
                            avg_chg=cf.get('avg_chg'),
                            limit_up_count=0,
                            heat_score=0,
                        ))
                db.commit()
                logger.info(f'[collect] Concept sector flows saved: {len(concept_flows)}')
        except Exception as e:
            db.rollback()
            logger.error(f'[collect] Concept sector flow error: {e}')

    logger.info(f'[collect] Collection complete for {trade_date}')


if __name__ == '__main__':
    # 测试
    today = datetime.now().strftime('%Y-%m-%d')
    logger.info(f'Testing pytdx availability: {PYTDX_AVAILABLE}')
    logger.info(f'Testing tushare availability: {TUSHARE_AVAILABLE}')
    if PYTDX_AVAILABLE:
        server = get_best_server()
        logger.info(f'Best server: {server}')