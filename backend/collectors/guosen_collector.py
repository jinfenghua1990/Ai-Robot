"""
国信证券数据采集器
复用 gs-stock-market-query skill 的脚本，封装为统一接口
- 实时行情（批量，最多10个一批）
- 资金流向（单个股票）
- 涨幅排名（全市场Top N）
- 关联板块
"""
import sys, os
import threading
from datetime import date
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging

# 把国信 skill 脚本加入 path
_SKILL_SCRIPT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    'skills', 'guosen', 'gs-stock-market-query', 'gs-stock-market-query', 'scripts'
)
sys.path.insert(0, _SKILL_SCRIPT_DIR)

from config import GS_API_KEY
os.environ['GS_API_KEY'] = GS_API_KEY  # skill 脚本从环境变量读取
logger = logging.getLogger(__name__)
_GUOSEN_FUND_FLOW_QUOTA_EXHAUSTED_DATE = None
_GUOSEN_FUND_FLOW_LOCK = threading.Lock()

try:
    from get_data import (
        query_single_hq, query_comb_hq, query_fund_flow,
        query_multi_hq, query_related_comb_hq, query_past_hq
    )
    GUOSEN_AVAILABLE = True
except Exception as e:
    logger.warning(f'[guosen] skill import failed: {e}')
    GUOSEN_AVAILABLE = False


def _set_code_from_ts_code(ts_code):
    """从 ts_code (如 600519.SH / 000001.SZ) 推导 setCode"""
    if ts_code.endswith('.SH'):
        return 1
    if ts_code.endswith('.SZ'):
        return 0
    if ts_code.endswith('.BJ'):
        return 2
    return 0


def _first_mapping(value):
    """兼容国信接口把结果包成对象或列表的两种响应形态。"""
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        return next((item for item in value if isinstance(item, dict)), None)
    return None


def _extract_fund_flow_payload(response):
    """返回含资金流字段的记录；上游无有效记录时返回 None。"""
    if not isinstance(response, dict):
        return None

    result = response.get('result')
    if isinstance(result, dict):
        code = result.get('code')
        if code not in (None, 0, '0'):
            return None
        candidates = (response.get('object'), response.get('data'), result.get('object'), result.get('data'), result)
    else:
        candidates = (response.get('object'), response.get('data'), result)

    for candidate in candidates:
        payload = _first_mapping(candidate)
        if payload and any(key in payload for key in ('mainNetInflow', 'netInflow')):
            return payload
    return None


def _fund_flow_quota_exhausted(response) -> bool:
    """国信返回 197006 时表示当天额度耗尽，不能继续逐股重试。"""
    if not isinstance(response, dict):
        return False
    result = _first_mapping(response.get('result'))
    if not result:
        return False
    return str(result.get('code', '')) == '197006' or '超过日限额' in str(result.get('msg', ''))


def guosen_batch_realtime_quotes(ts_codes, batch_size=10):
    """
    批量查询实时行情（国信单次最多10个）
    返回: {ts_code: {price, price_chg, name, ...}, ...}
    """
    if not GUOSEN_AVAILABLE:
        return {}
    results = {}
    for i in range(0, len(ts_codes), batch_size):
        batch = ts_codes[i:i + batch_size]
        codes = [tc.replace('.SH', '').replace('.SZ', '').replace('.BJ', '') for tc in batch]
        set_codes = [_set_code_from_ts_code(tc) for tc in batch]
        try:
            resp = query_comb_hq(codes, set_codes)
            if resp.get('result', {}).get('code') == 0:
                data = resp.get('data') or resp.get('object') or []
                if isinstance(data, dict):
                    data = list(data.values())
                for item in data:
                    code = item.get('code', '')
                    set_code = str(item.get('setCode', ''))
                    market = item.get('market', '')
                    ts_code = f"{code}.{market}" if market else f"{code}.{'SH' if set_code == '1' else 'SZ'}"
                    results[ts_code] = {
                        'name': item.get('name', ''),
                        'price': float(item.get('now', 0) or 0),
                        'price_chg': float(item.get('priceChangePct', 0) or 0),
                        'amount': item.get('amount', ''),
                        'vol': item.get('vol', ''),
                        'open': float(item.get('open', 0) or 0),
                        'max': float(item.get('max', 0) or 0),
                        'min': float(item.get('min', 0) or 0),
                        'close': float(item.get('close', 0) or 0),  # 昨收
                    }
        except Exception as e:
            logger.warning(f'[guosen] batch quotes error: {e}', exc_info=True)
    return results


def guosen_single_fund_flow(ts_code, period=1):
    """
    查询单个股票资金流向
    period: 周期（日），1=今日
    返回: {net_inflow, main_force_inflow, ...} 单位：万元
    """
    if not GUOSEN_AVAILABLE:
        return None
    global _GUOSEN_FUND_FLOW_QUOTA_EXHAUSTED_DATE
    # 该接口有日额度。锁覆盖请求和额度标记，避免并发任务在收到 197006 前重复穿透。
    with _GUOSEN_FUND_FLOW_LOCK:
        today = date.today()
        if _GUOSEN_FUND_FLOW_QUOTA_EXHAUSTED_DATE == today:
            return None
        code = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        set_code = _set_code_from_ts_code(ts_code)
        try:
            resp = query_fund_flow(code, set_code=set_code, period=period)
            if _fund_flow_quota_exhausted(resp):
                _GUOSEN_FUND_FLOW_QUOTA_EXHAUSTED_DATE = today
                logger.warning('[guosen] fund-flow daily quota exhausted; skip further requests until tomorrow')
                return None
            obj = _extract_fund_flow_payload(resp)
            if obj is not None:
                # mainNetInflow 单位是元，转万元
                main_inflow = float(obj.get('mainNetInflow', 0) or 0) / 10000
                net_inflow = float(obj.get('netInflow', 0) or 0)  # 已经是万元
                return {
                    'ts_code': ts_code,
                    'main_force_inflow': main_inflow,
                    'net_inflow': net_inflow,
                    'source': 'guosen',
                }
        except Exception as e:
            logger.warning(f'[guosen] fund_flow error for {ts_code}: {e}', exc_info=True)
    return None


def guosen_top_gainers(set_domain=6, want_num=80, sort_type=1):
    """
    查询涨幅排名
    set_domain: 6=沪深A股, 14=创业板, 11005=沪深ETF
    sort_type: 1=涨幅, 2=跌幅
    返回: [{ts_code, name, price, price_chg, amount, ...}, ...]
    """
    if not GUOSEN_AVAILABLE:
        return []
    try:
        resp = query_multi_hq(set_domain=set_domain, want_num=want_num, sort_type=sort_type)
        if resp.get('result', {}).get('code') == 0:
            data = resp.get('data', [])
            results = []
            for item in data:
                code = item.get('code', '')
                market = item.get('market', '')
                ts_code = f"{code}.{market}" if market else f"{code}.{'SH' if item.get('setCode') == '1' else 'SZ'}"
                results.append({
                    'ts_code': ts_code,
                    'name': item.get('name', ''),
                    'price': float(item.get('now', 0) or 0),
                    'price_chg': float(item.get('priceChangePct', 0) or 0),
                    'amount': item.get('amount', ''),
                    'vol': item.get('vol', ''),
                    'open': float(item.get('open', 0) or 0),
                    'max': float(item.get('max', 0) or 0),
                    'min': float(item.get('min', 0) or 0),
                })
            return results
    except Exception as e:
        logger.warning(f'[guosen] top_gainers error: {e}', exc_info=True)
    return []


def guosen_related_sectors(ts_code):
    """查询个股关联板块"""
    if not GUOSEN_AVAILABLE:
        return []
    code = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
    set_code = _set_code_from_ts_code(ts_code)
    try:
        resp = query_related_comb_hq(code, set_code=set_code)
        if resp.get('result', {}).get('code') == 0:
            return resp.get('data', []) or resp.get('object', []) or []
    except Exception as e:
        logger.warning(f'[guosen] related_sectors error: {e}', exc_info=True)
    return []


if __name__ == '__main__':
    # 测试
    print('=== 国信证券采集器测试 ===')
    print(f'Available: {GUOSEN_AVAILABLE}')
    if GUOSEN_AVAILABLE:
        print('\n--- 贵州茅台实时行情 ---')
        r = guosen_batch_realtime_quotes(['600519.SH'])
        print(r)

        print('\n--- 贵州茅台资金流向 ---')
        r = guosen_single_fund_flow('600519.SH', period=1)
        print(r)

        print('\n--- 沪深A股涨幅前5 ---')
        r = guosen_top_gainers(set_domain=6, want_num=5)
        print(f'Got {len(r)} stocks')
        for s in r[:3]:
            print(f"  {s['name']} {s['ts_code']} +{s['price_chg']}%")
