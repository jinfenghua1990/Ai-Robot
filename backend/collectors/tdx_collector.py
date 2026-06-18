"""
pytdx 数据采集器
- 动态服务器寻优 + 重试
- 板块资金流向采集
- 个股资金流向采集
- 涨停股识别
"""
import sys, os, time, threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from db.connection import get_db
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
    except:
        return ip, port, float('inf')


def get_best_server():
    """动态寻找最优服务器，5分钟缓存"""
    global _BEST_SERVER, _BEST_SERVER_TTL
    now = time.time()
    if _BEST_SERVER and now < _BEST_SERVER_TTL:
        return _BEST_SERVER
    if not TDX_SERVERS:
        return None
    print(f'[tdx] Testing {len(TDX_SERVERS)} servers...')
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = list(executor.map(lambda s: test_server(s[0], s[1]), TDX_SERVERS))
    results = [r for r in results if r[2] < float('inf')]
    if not results:
        print('[tdx] No server available')
        return None
    results.sort(key=lambda x: x[2])
    _BEST_SERVER = (results[0][0], results[0][1])
    _BEST_SERVER_TTL = now + 300
    print(f'[tdx] Best server: {_BEST_SERVER[0]}:{_BEST_SERVER[1]} ({results[0][2]:.1f}ms)')
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
            if api.connect(ip, port, time_out=5):
                return api, (ip, port)
        except:
            pass
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
        print(f'[tdx] get_sector_list error: {e}')
        return []


def get_sector_money_flow(trade_date):
    """
    获取板块资金流向数据
    使用 Tushare 的 moneyflow_hsgt 或东方财富API
    返回格式: [{'sector': 'AI', 'money_inflow': 100000, 'money_outflow': 50000, 'net_flow': 50000, ...}, ...]
    """
    # 优先使用 Tushare 获取板块资金流向
    if TUSHARE_AVAILABLE:
        try:
            from config import TUSHARE_TOKEN
            if TUSHARE_TOKEN:
                ts.set_token(TUSHARE_TOKEN)
                pro = ts.pro_api()
                # 获取个股资金流向，按板块汇总
                date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
                df = pro.moneyflow(trade_date=date_str)
                if df is not None and not df.empty:
                    # 按行业汇总
                    results = []
                    # 获取个股所属行业
                    stock_basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,industry')
                    if stock_basic is not None:
                        df = df.merge(stock_basic[['ts_code', 'industry']], on='ts_code', how='left')
                        sector_group = df.groupby('industry').agg({
                            'net_mf_amount': 'sum',
                            'buy_elg_amount': 'sum',
                            'sell_elg_amount': 'sum',
                        }).reset_index()
                        for _, row in sector_group.iterrows():
                            if row['industry']:
                                results.append({
                                    'sector': row['industry'],
                                    'net_flow': float(row['net_mf_amount'] or 0) / 10000,  # 转为万元
                                    'money_inflow': float(row.get('buy_elg_amount', 0) or 0) / 10000,
                                    'money_outflow': float(row.get('sell_elg_amount', 0) or 0) / 10000,
                                })
                    return results
        except Exception as e:
            print(f'[tushare] get_sector_money_flow error: {e}')
    return []


def get_stock_money_flow(trade_date):
    """
    获取个股资金流向数据
    返回格式: [{'ts_code': '000001.SZ', 'sector': '银行', 'net_inflow': 1000, 'main_force_inflow': 500, ...}, ...]
    """
    if TUSHARE_AVAILABLE:
        try:
            from config import TUSHARE_TOKEN
            if TUSHARE_TOKEN:
                ts.set_token(TUSHARE_TOKEN)
                pro = ts.pro_api()
                date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
                df = pro.moneyflow(trade_date=date_str)
                if df is not None and not df.empty:
                    stock_basic = pro.stock_basic(exchange='', list_status='L', fields='ts_code,industry')
                    if stock_basic is not None:
                        df = df.merge(stock_basic[['ts_code', 'industry']], on='ts_code', how='left')
                    results = []
                    for _, row in df.iterrows():
                        results.append({
                            'ts_code': row['ts_code'],
                            'sector': row.get('industry', ''),
                            'net_inflow': float(row.get('net_mf_amount', 0) or 0) / 10000,
                            'main_force_inflow': float(row.get('buy_elg_amount', 0) or 0) / 10000,
                            'retail_flow': float(row.get('buy_sm_amount', 0) or 0) / 10000 - float(row.get('sell_sm_amount', 0) or 0) / 10000,
                            'price_chg': float(row.get('pct_change', 0) or 0),
                        })
                    return results
        except Exception as e:
            print(f'[tushare] get_stock_money_flow error: {e}')
    return []


def get_limit_up_stocks(trade_date):
    """获取涨停股列表"""
    if TUSHARE_AVAILABLE:
        try:
            from config import TUSHARE_TOKEN
            if TUSHARE_TOKEN:
                ts.set_token(TUSHARE_TOKEN)
                pro = ts.pro_api()
                date_str = trade_date.replace('-', '') if isinstance(trade_date, str) else trade_date.strftime('%Y%m%d')
                # 获取当日涨停股
                df = pro.limit_list_d(trade_date=date_str, limit_type='U')
                if df is not None and not df.empty:
                    return df['ts_code'].tolist()
        except Exception as e:
            print(f'[tushare] get_limit_up_stocks error: {e}')
    return []


def collect_daily_data(trade_date):
    """
    采集单日全量数据并写入数据库
    1. 板块资金流向 → sector_flow 表
    2. 个股资金流向 → stock_flow 表
    3. 涨停股识别 → leader_lifecycle 表（初始阶段）
    """
    print(f'[collect] Starting collection for {trade_date}')

    # 1. 采集板块资金流向
    sector_flows = get_sector_money_flow(trade_date)
    print(f'[collect] Got {len(sector_flows)} sector flows')

    db = next(get_db())
    try:
        for sf in sector_flows:
            # 检查是否已存在
            existing = db.query(SectorFlow).filter_by(trade_date=trade_date, sector=sf['sector']).first()
            if existing:
                # 更新
                existing.money_inflow = sf.get('money_inflow')
                existing.money_outflow = sf.get('money_outflow')
                existing.net_flow = sf.get('net_flow')
            else:
                # 新增
                record = SectorFlow(
                    trade_date=trade_date,
                    sector=sf['sector'],
                    money_inflow=sf.get('money_inflow'),
                    money_outflow=sf.get('money_outflow'),
                    net_flow=sf.get('net_flow'),
                )
                db.add(record)
        db.commit()
        print(f'[collect] Sector flows saved')
    except Exception as e:
        db.rollback()
        print(f'[collect] Sector flow error: {e}')
    finally:
        db.close()

    # 2. 采集个股资金流向
    stock_flows = get_stock_money_flow(trade_date)
    print(f'[collect] Got {len(stock_flows)} stock flows')

    db = next(get_db())
    try:
        for sf in stock_flows:
            existing = db.query(StockFlow).filter_by(trade_date=trade_date, ts_code=sf['ts_code']).first()
            if existing:
                existing.net_inflow = sf.get('net_inflow')
                existing.main_force_inflow = sf.get('main_force_inflow')
                existing.retail_flow = sf.get('retail_flow')
                existing.price_chg = sf.get('price_chg')
                existing.sector = sf.get('sector')
            else:
                record = StockFlow(
                    trade_date=trade_date,
                    ts_code=sf['ts_code'],
                    sector=sf.get('sector'),
                    net_inflow=sf.get('net_inflow'),
                    main_force_inflow=sf.get('main_force_inflow'),
                    retail_flow=sf.get('retail_flow'),
                    price_chg=sf.get('price_chg'),
                )
                db.add(record)
        db.commit()
        print(f'[collect] Stock flows saved')
    except Exception as e:
        db.rollback()
        print(f'[collect] Stock flow error: {e}')
    finally:
        db.close()

    # 3. 采集涨停股
    limit_ups = get_limit_up_stocks(trade_date)
    print(f'[collect] Got {len(limit_ups)} limit-up stocks')

    db = next(get_db())
    try:
        for ts_code in limit_ups:
            # 查找个股的板块信息
            stock = db.query(StockFlow).filter_by(trade_date=trade_date, ts_code=ts_code).first()
            sector = stock.sector if stock else None
            existing = db.query(LeaderLifecycle).filter_by(trade_date=trade_date, ts_code=ts_code).first()
            if not existing:
                record = LeaderLifecycle(
                    trade_date=trade_date,
                    ts_code=ts_code,
                    sector=sector,
                    stage='启动',  # 涨停股初始阶段为"启动"
                    strength=20,
                    consecutive_days=1,
                )
                db.add(record)
        db.commit()
        print(f'[collect] Leader lifecycle saved')
    except Exception as e:
        db.rollback()
        print(f'[collect] Leader lifecycle error: {e}')
    finally:
        db.close()

    print(f'[collect] Collection complete for {trade_date}')


if __name__ == '__main__':
    # 测试
    today = datetime.now().strftime('%Y-%m-%d')
    print(f'Testing pytdx availability: {PYTDX_AVAILABLE}')
    print(f'Testing tushare availability: {TUSHARE_AVAILABLE}')
    if PYTDX_AVAILABLE:
        server = get_best_server()
        print(f'Best server: {server}')
