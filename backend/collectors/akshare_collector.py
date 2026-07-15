"""
AKShare 采集器 - 开源Python库，整合东财/新浪/同花顺等多源数据
无额度限制，实时行情基于新浪（可用），资金流向基于东财push2his（可能受限）
"""
import os
import logging
from utils.http_constants import clear_proxy_env
from utils.cache import BoundedDict

logger = logging.getLogger(__name__)

clear_proxy_env()

try:
    import akshare as ak
    AKSHARE_AVAILABLE = True
    AKSHARE_VERSION = ak.__version__
except ImportError:
    AKSHARE_AVAILABLE = False
    AKSHARE_VERSION = None

# 全市场实时行情缓存（避免每次都全量拉取）
_spot_cache = BoundedDict(maxsize=100)
_spot_cache_time = 0
_SPOT_CACHE_TTL = 60  # 60秒缓存


def akshare_batch_prices(ts_codes):
    """
    批量获取实时行情（基于新浪，无额度限制）
    ts_codes: ["600519.SH", "000001.SZ", ...]
    返回: {ts_code: {price, change_pct, open, high, low, prev_close, volume, amount}}
    """
    if not AKSHARE_AVAILABLE:
        return {}

    import time
    global _spot_cache, _spot_cache_time

    now = time.time()
    if now - _spot_cache_time > _SPOT_CACHE_TTL:
        # 缓存过期，重新拉取全市场行情
        try:
            df = ak.stock_zh_a_spot()
            _spot_cache = BoundedDict(maxsize=100)
            for _, row in df.iterrows():
                code = str(row['代码'])  # 如 bj920000, sh600519, sz000001
                # 标准化为 ts_code 格式
                if code.startswith('sh'):
                    tc = f"{code[2:]}.SH"
                elif code.startswith('sz'):
                    tc = f"{code[2:]}.SZ"
                elif code.startswith('bj'):
                    tc = f"{code[2:]}.BJ"
                else:
                    continue
                _spot_cache[tc] = {
                    'price': float(row.get('最新价', 0) or 0),
                    'change_pct': float(row.get('涨跌幅', 0) or 0),
                    'open': float(row.get('今开', 0) or 0),
                    'high': float(row.get('最高', 0) or 0),
                    'low': float(row.get('最低', 0) or 0),
                    'prev_close': float(row.get('昨收', 0) or 0),
                    'volume': float(row.get('成交量', 0) or 0),
                    'amount': float(row.get('成交额', 0) or 0),
                }
            _spot_cache_time = now
            print(f'[akshare] Cached {len(_spot_cache)} stocks from stock_zh_a_spot')
        except Exception as e:
            logger.warning(f'[akshare] stock_zh_a_spot error: {e}', exc_info=True)
            return {}

    # 从缓存中提取请求的股票
    result = {}
    for tc in ts_codes:
        if tc in _spot_cache:
            result[tc] = _spot_cache[tc]
    return result


def akshare_single_fund_flow(ts_code):
    """
    个股资金流向（基于东财push2his，可能受限）
    ts_code: "000001.SZ" 或 "600519.SH"
    返回: {main_net, super_net, big_net, mid_net, small_net} 单位：元，或None
    """
    if not AKSHARE_AVAILABLE:
        return None

    code = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
    market = 'sh' if ts_code.endswith('.SH') else 'sz'
    if ts_code.endswith('.BJ'):
        market = 'bj'

    try:
        df = ak.stock_individual_fund_flow(stock=code, market=market)
        if df is None or df.empty:
            return None
        # 取最后一条（当日）
        last = df.iloc[-1]
        return {
            'main_net': float(last.get('主力净流入-净额', 0) or 0),
            'super_net': float(last.get('超大单净流入-净额', 0) or 0),
            'big_net': float(last.get('大单净流入-净额', 0) or 0),
            'mid_net': float(last.get('中单净流入-净额', 0) or 0),
            'small_net': float(last.get('小单净流入-净额', 0) or 0),
        }
    except Exception as e:
        logger.warning(f'[akshare] fund_flow error for {ts_code}: {e}', exc_info=True)
        return None


def akshare_fund_flow_rank():
    """
    全市场资金流向排名（基于东财push2his，可能受限）
    返回: [{ts_code, name, main_net, ...}, ...] 或 None
    """
    if not AKSHARE_AVAILABLE:
        return None
    try:
        df = ak.stock_individual_fund_flow_rank(indicator='今日')
        if df is None or df.empty:
            return None
        result = []
        for _, row in df.iterrows():
            code = str(row.get('代码', ''))
            if not code:
                continue
            if code.startswith('6') or code.startswith('9'):
                tc = f"{code}.SH"
            elif code.startswith('8'):
                tc = f"{code}.BJ"
            else:
                tc = f"{code}.SZ"
            result.append({
                'ts_code': tc,
                'name': row.get('名称', ''),
                'main_net': float(row.get('今日主力净流入-净额', 0) or 0),
                'main_net_pct': float(row.get('今日主力净流入-净占比', 0) or 0),
                'super_net': float(row.get('今日超大单净流入-净额', 0) or 0),
                'big_net': float(row.get('今日大单净流入-净额', 0) or 0),
                'mid_net': float(row.get('今日中单净流入-净额', 0) or 0),
                'small_net': float(row.get('今日小单净流入-净额', 0) or 0),
            })
        return result
    except Exception as e:
        logger.warning(f'[akshare] fund_flow_rank error: {e}', exc_info=True)
        return None


if __name__ == '__main__':
    print(f'AKShare version: {AKSHARE_VERSION}')
    print(f'Available: {AKSHARE_AVAILABLE}')

    # 测试批量行情
    print('\n=== 批量行情 ===')
    prices = akshare_batch_prices(['000001.SZ', '600519.SH'])
    for tc, data in prices.items():
        print(f'{tc}: 价格={data["price"]}, 涨跌幅={data["change_pct"]}%')

    # 测试个股资金流向
    print('\n=== 个股资金流向 ===')
    flow = akshare_single_fund_flow('000001.SZ')
    if flow:
        print(f'主力净流入: {flow["main_net"]/10000:.2f}万')
    else:
        print('资金流向接口不可用（push2his可能受限）')
