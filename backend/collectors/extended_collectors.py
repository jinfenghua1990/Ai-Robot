"""
扩展数据源采集器 - 7个新数据源统一采集
包含: efinance / qstock / adata / mootdx / 同花顺 / 网易财经 / 巨潮资讯
每个数据源都实现: 批量行情 + 资金流向（如支持）
所有函数都有try-except保护，出错不影响其他数据源
"""
import logging
import os, time, json, traceback
from datetime import datetime
import requests
from utils.http_constants import clear_proxy_env


clear_proxy_env()
logger = logging.getLogger(__name__)

# 出错率统计（内存中，定期持久化）
_error_stats = {}  # {source: {'total': 0, 'errors': 0, 'last_error': ''}}


def _record_call(source, success, error=''):
    """记录数据源调用统计"""
    if source not in _error_stats:
        _error_stats[source] = {'total': 0, 'errors': 0, 'last_error': '', 'last_success': None}
    _error_stats[source]['total'] += 1
    if success:
        _error_stats[source]['last_success'] = datetime.now().isoformat()
    else:
        _error_stats[source]['errors'] += 1
        _error_stats[source]['last_error'] = error[:200]


def get_error_stats():
    """获取出错率统计"""
    result = {}
    for src, stats in _error_stats.items():
        total = stats['total']
        errors = stats['errors']
        result[src] = {
            'total_calls': total,
            'errors': errors,
            'error_rate': round(errors / total * 100, 1) if total > 0 else 0,
            'last_error': stats['last_error'],
            'last_success': stats['last_success'],
        }
    return result


def _ts_to_code(ts_code):
    """ts_code(000001.SZ) → 6位代码"""
    return ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')


# ============================================================
# 1. efinance - 基于东财的开源库
# ============================================================
def efinance_batch_quotes(ts_codes):
    """efinance批量行情（逐个获取，限制20只）"""
    try:
        import efinance as ef
        result = {}
        for tc in ts_codes[:20]:
            try:
                code = _ts_to_code(tc)
                s = ef.stock.get_quote_snapshot(code)
                if s is not None and '最新价' in s.index:
                    result[tc] = {
                        'price': float(s.get('最新价', 0) or 0),
                        'price_chg': float(s.get('涨跌幅', 0) or 0),
                    }
            except Exception:
                logger.debug(f"efinance_batch_quotes item failed", exc_info=True)
                continue
        _record_call('efinance', True)
        return result
    except Exception as e:
        _record_call('efinance', False, str(e))
        return {}


def efinance_fund_flow(ts_code):
    """efinance资金流向"""
    try:
        import efinance as ef
        code = _ts_to_code(ts_code)
        df = ef.stock.get_today_bill(code)
        if df is None or df.empty:
            _record_call('efinance', False, 'no fund flow data')
            return None
        latest = df.iloc[-1]
        result = {
            'main_force_inflow': float(latest.get('主力净流入-净额', 0) or 0) / 10000,
        }
        _record_call('efinance', True)
        return result
    except Exception as e:
        _record_call('efinance', False, str(e))
        return None


# ============================================================
# 2. qstock - 整合多源的开源库
# ============================================================
def qstock_batch_quotes(ts_codes):
    """qstock批量行情"""
    try:
        import qstock as qs
        codes = [_ts_to_code(c) for c in ts_codes[:50]]  # 限制50只
        df = qs.realtime_data(codes)
        if df is None or df.empty:
            _record_call('qstock', False, 'empty data')
            return {}
        result = {}
        for _, row in df.iterrows():
            code = str(row.get('代码', ''))
            ts_code = None
            for tc in ts_codes:
                if _ts_to_code(tc) == code:
                    ts_code = tc
                    break
            if ts_code:
                result[ts_code] = {
                    'price': float(row.get('最新价', 0) or 0),
                    'price_chg': float(row.get('涨跌幅', 0) or 0),
                }
        _record_call('qstock', True)
        return result
    except Exception as e:
        _record_call('qstock', False, str(e))
        return {}


def qstock_fund_flow(ts_code):
    """qstock资金流向"""
    try:
        import qstock as qs
        code = _ts_to_code(ts_code)
        df = qs.data_fund_flow(code)
        if df is None or df.empty:
            _record_call('qstock', False, 'no fund flow data')
            return None
        latest = df.iloc[-1]
        result = {
            'main_force_inflow': float(latest.get('主力净流入-净额', 0) or 0) / 10000,
        }
        _record_call('qstock', True)
        return result
    except Exception as e:
        _record_call('qstock', False, str(e))
        return None


# ============================================================
# 3. adata - 聚合多源数据
# ============================================================
def adata_batch_quotes(ts_codes):
    """adata批量行情"""
    try:
        import adata
        codes = [_ts_to_code(c) for c in ts_codes[:50]]
        result = {}
        for code in codes:
            try:
                df = adata.stock.market.get_market(stock_code=code, k_type=1)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    ts_code = None
                    for tc in ts_codes:
                        if _ts_to_code(tc) == code:
                            ts_code = tc
                            break
                    if ts_code:
                        result[ts_code] = {
                            'price': float(latest.get('close', 0) or 0),
                            'price_chg': float(latest.get('pct_chg', 0) or 0),
                        }
            except Exception:
                logger.debug(f"adata_batch_quotes item failed", exc_info=True)
                continue
        _record_call('adata', True)
        return result
    except Exception as e:
        _record_call('adata', False, str(e))
        return {}


# ============================================================
# 4. mootdx - 通达信TCP增强版（pytdx降级）
# ============================================================
_mootdx_reader = None
_mootdx_use_pytdx = None  # None=未检测, True=用pytdx, False=不可用

def _get_mootdx_reader():
    """获取mootdx Reader实例（单例），优先mootdx，降级pytdx"""
    global _mootdx_reader, _mootdx_use_pytdx
    if _mootdx_reader is not None:
        return _mootdx_reader
    # 尝试mootdx
    try:
        from mootdx.reader import Reader
        _mootdx_reader = Reader.factory(market='std', tdxdir=None)
        return _mootdx_reader
    except Exception as e:
        logger.debug(f'[extended] mootdx 不可用，降级到 pytdx: {e}')
    # 降级：用pytdx TCP（已在tdx_collector中可用）
    try:
        from pytdx.hq import TdxHq_API
        _mootdx_use_pytdx = True
        _mootdx_reader = 'pytdx'  # 标记使用pytdx
        return _mootdx_reader
    except Exception:
        logger.debug(f"_get_mootdx_reader fallback", exc_info=True)
        _mootdx_reader = False
        return None


def mootdx_batch_quotes(ts_codes):
    """mootdx批量行情（优先mootdx，降级pytdx TCP）"""
    try:
        reader = _get_mootdx_reader()
        if not reader:
            _record_call('mootdx', False, 'no mootdx or pytdx available')
            return {}

        # pytdx TCP降级模式
        if _mootdx_use_pytdx:
            from collectors.tdx_collector import connect_with_retry
            api, server = connect_with_retry()
            if not api:
                _record_call('mootdx', False, 'pytdx connect failed')
                return {}
            result = {}
            for ts_code in ts_codes[:30]:
                try:
                    code = _ts_to_code(ts_code)
                    market = 0 if ts_code.endswith('.SZ') else 1  # 0=深圳, 1=上海
                    quotes = api.get_security_quotes([(market, code)])
                    if quotes:
                        q = quotes[0]
                        price = float(q.get('price', 0) or q.get('last_close', 0) or 0)
                        pre_close = float(q.get('last_close', 0) or 0)
                        pct_chg = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0
                        result[ts_code] = {
                            'price': price,
                            'price_chg': round(pct_chg, 2),
                        }
                except Exception:
                    logger.debug(f"function item failed", exc_info=True)
                    continue
                api.disconnect()
            if result:
                _record_call('mootdx', True)
            else:
                _record_call('mootdx', False, 'pytdx no data')
            return result

        # mootdx原生模式
        result = {}
        for ts_code in ts_codes[:30]:
            try:
                code = _ts_to_code(ts_code)
                market = 'sz' if ts_code.endswith('.SZ') else 'sh'
                df = reader.minute(symbol=f'{market}{code}')
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    result[ts_code] = {
                        'price': float(latest.get('price', 0) or 0),
                    }
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        _record_call('mootdx', True)
        return result
    except Exception as e:
        _record_call('mootdx', False, str(e))
        return {}


# ============================================================
# 5. 同花顺 - HTTP API
# ============================================================
def ths_fund_flow_rank():
    """同花顺资金流向排名（批量）"""
    try:
        url = 'https://data.10jqka.com.cn/funds/zijin/field/zdf/order/desc/page/1/ajax/1/free/1/'
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)',
            'Referer': 'https://data.10jqka.com.cn/',
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            _record_call('ths', False, f'HTTP {resp.status_code}')
            return {}
        # 解析HTML表格
        import pandas as pd
        tables = pd.read_html(resp.text)
        if not tables:
            _record_call('ths', False, 'no tables')
            return {}
        df = tables[0]
        result = {}
        for _, row in df.iterrows():
            try:
                code = str(row.get('代码', '')).zfill(6)
                if code.startswith('6'):
                    ts_code = f'{code}.SH'
                elif code.startswith(('0', '3')):
                    ts_code = f'{code}.SZ'
                else:
                    continue
                main_flow = float(row.get('主力净流入-净额', 0) or 0)
                result[ts_code] = {
                    'main_force_inflow': main_flow / 10000,  # 元→万元
                }
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        _record_call('ths', True)
        return result
    except Exception as e:
        _record_call('ths', False, str(e))
        return {}


# ============================================================
# 6. 网易财经 - HTTP API
# ============================================================
def netease_batch_quotes(ts_codes):
    """网易财经批量行情"""
    try:
        result = {}
        codes = []
        for tc in ts_codes[:50]:
            code = _ts_to_code(tc)
            if tc.endswith('.SH'):
                codes.append(f'0{code}')
            else:
                codes.append(f'1{code}')
        url = f'https://api.money.126.net/data/feed/{",".join(codes)}'
        headers = {'User-Agent': 'Mozilla/5.0'}
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            _record_call('netease', False, f'HTTP {resp.status_code}')
            return {}
        text = resp.text
        prefix_str = '_ntes_quote_callback('
        if text.startswith(prefix_str):
            text = text[len(prefix_str):-2]
        data = json.loads(text)
        for tc in ts_codes:
            code = _ts_to_code(tc)
            prefix = '0' if tc.endswith('.SH') else '1'
            key = f'{prefix}{code}'
            if key in data:
                d = data[key]
                result[tc] = {
                    'price': float(d.get('price', 0) or 0),
                    'price_chg': float(d.get('percent', 0) or 0),
                }
        _record_call('netease', True)
        return result
    except Exception as e:
        _record_call('netease', False, str(e))
        return {}


# ============================================================
# 7. 巨潮资讯 - 公告/财报
# ============================================================
def cninfo_latest_announcements(ts_code, page=1):
    """巨潮资讯最新公告"""
    try:
        code = _ts_to_code(ts_code)
        url = 'http://www.cninfo.com.cn/new/hisAnnouncement/query'
        data = {
            'stock': f'{code},',
            'tabName': 'fulltext',
            'pageSize': 5,
            'pageNum': page,
            'column': 'szse' if ts_code.endswith('.SZ') else 'sse',
            'category': '',
            'plate': '',
            'searchkey': '',
            'secid': '',
            'sortName': '',
            'sortType': '',
            'isHLtitle': 'true',
        }
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        resp = requests.post(url, data=data, headers=headers, timeout=10)
        if resp.status_code != 200:
            _record_call('cninfo', False, f'HTTP {resp.status_code}')
            return []
        result_data = resp.json()
        announcements = result_data.get('announcements', [])
        result = []
        for ann in announcements[:5]:
            result.append({
                'title': ann.get('announcementTitle', ''),
                'time': ann.get('announcementTime', ''),
                'type': ann.get('announcementTypeName', ''),
                'url': f'http://www.cninfo.com.cn/{ann.get("adjunctUrl", "")}',
            })
        _record_call('cninfo', True)
        return result
    except Exception as e:
        _record_call('cninfo', False, str(e))
        return []


# ============================================================
# 8. baostock - 免费开源证券数据（无token，无额度限制）
# ============================================================
def baostock_daily_kline(ts_code, days=5):
    """baostock日K线数据"""
    try:
        import baostock as bs
        from datetime import datetime, timedelta
        # ts_code(000001.SZ) → baostock格式(sz.000001)
        code = ts_code.replace('.SH', '').replace('.SZ', '').replace('.BJ', '')
        if ts_code.endswith('.SH'):
            bs_code = f'sh.{code}'
        else:
            bs_code = f'sz.{code}'

        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=days*2)).strftime('%Y-%m-%d')

        lg = bs.login()
        if lg.error_code != '0':
            _record_call('baostock', False, f'login: {lg.error_msg}')
            return None

        rs = bs.query_history_k_data_plus(
            bs_code, 'date,code,open,high,low,close,preclose,volume,amount,pctChg,turn',
            start_date=start_date, end_date=end_date, frequency='d'
        )
        rows = []
        while (rs.error_code == '0') and rs.next():
            rows.append(rs.get_row_data())

        if not rows:
            _record_call('baostock', False, 'no data')
            return None

        latest = rows[-1]
        result = {
            'date': latest[0],
            'close': float(latest[4]) if latest[4] else 0,
            'pct_chg': float(latest[9]) if latest[9] else 0,
            'turn': float(latest[10]) if latest[10] else 0,
        }
        _record_call('baostock', True)
        return result
    except Exception as e:
        _record_call('baostock', False, str(e))
        return None


def baostock_batch_quotes(ts_codes):
    """baostock批量行情（取最新日K收盘价，限制20只）"""
    try:
        import baostock as bs
        result = {}
        for tc in ts_codes[:20]:
            try:
                r = baostock_daily_kline(tc, days=3)
                if r:
                    result[tc] = {
                        'price': r['close'],
                        'price_chg': r['pct_chg'],
                    }
            except Exception:
                logger.debug(f"baostock_batch_quotes item failed", exc_info=True)
                continue
        if result:
            _record_call('baostock', True)
        else:
            _record_call('baostock', False, 'no data for all codes')
        return result
    except Exception as e:
        _record_call('baostock', False, str(e))
        return {}


# ============================================================
# 9. sina_quote - 新浪行情API (hq.sinajs.cn，无额度限制)
# ============================================================
def sina_quote_batch(ts_codes):
    """新浪行情API批量实时行情"""
    try:
        # ts_code(000001.SZ) → sz000001
        codes = []
        for tc in ts_codes[:50]:
            code = _ts_to_code(tc)
            if tc.endswith('.SH'):
                codes.append(f'sh{code}')
            elif tc.endswith('.BJ'):
                codes.append(f'bj{code}')
            else:
                codes.append(f'sz{code}')

        url = f'https://hq.sinajs.cn/list={",".join(codes)}'
        headers = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            _record_call('sina_quote', False, f'HTTP {resp.status_code}')
            return {}

        result = {}
        for line in resp.text.strip().split('\n'):
            try:
                if '=' not in line or '"' not in line:
                    continue
                # var hq_str_sz000001="平安银行,10.680,..."
                code_part = line.split('=')[0].split('_')[-1].strip()
                content = line.split('"')[1]
                fields = content.split(',')
                if len(fields) < 4:
                    continue
                # 反向匹配 ts_code
                ts_code = None
                for tc in ts_codes:
                    raw = _ts_to_code(tc)
                    if code_part.endswith(raw):
                        ts_code = tc
                        break
                if not ts_code:
                    continue
                name = fields[0]
                pre_close = float(fields[2]) if fields[2] else 0
                price = float(fields[3]) if fields[3] else 0
                pct_chg = ((price - pre_close) / pre_close * 100) if pre_close > 0 else 0
                result[ts_code] = {
                    'price': price,
                    'price_chg': round(pct_chg, 2),
                    'name': name,
                }
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        _record_call('sina_quote', True)
        return result
    except Exception as e:
        _record_call('sina_quote', False, str(e))
        return {}


# 9b. sina_orderbook - 新浪五档盘口（hq.sinajs.cn，无额度限制）
# ============================================================
def sina_orderbook_batch(ts_codes):
    """新浪行情API批量五档盘口
    返回: {ts_code: {'name','price','pre_close','bid_prices':[b1..b5],'bid_vols':[v1..v5],'ask_prices':[a1..a5],'ask_vols':[v1..v5]}}
    买卖量单位统一为"手"（原始股数/100）
    """
    try:
        codes = []
        for tc in ts_codes[:50]:
            code = _ts_to_code(tc)
            if tc.endswith('.SH'):
                codes.append(f'sh{code}')
            elif tc.endswith('.BJ'):
                codes.append(f'bj{code}')
            else:
                codes.append(f'sz{code}')

        url = f'https://hq.sinajs.cn/list={",".join(codes)}'
        headers = {
            'Referer': 'https://finance.sina.com.cn',
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
        }
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            _record_call('sina_orderbook', False, f'HTTP {resp.status_code}')
            return {}

        result = {}
        for line in resp.text.strip().split('\n'):
            try:
                if '=' not in line or '"' not in line:
                    continue
                code_part = line.split('=')[0].split('_')[-1].strip()
                content = line.split('"')[1]
                fields = content.split(',')
                if len(fields) < 30:
                    continue
                ts_code = None
                for tc in ts_codes:
                    raw = _ts_to_code(tc)
                    if code_part.endswith(raw):
                        ts_code = tc
                        break
                if not ts_code:
                    continue

                def _f(idx, int_val=False):
                    v = fields[idx] if idx < len(fields) else ''
                    if not v:
                        return 0
                    try:
                        return int(float(v) / 100) if int_val else float(v)
                    except (ValueError, TypeError):
                        return 0

                result[ts_code] = {
                    'name': fields[0],
                    'price': _f(3),
                    'pre_close': _f(2),
                    'bid_prices': [_f(i) for i in [11, 13, 15, 17, 19]],
                    'bid_vols': [_f(i, True) for i in [10, 12, 14, 16, 18]],
                    'ask_prices': [_f(i) for i in [21, 23, 25, 27, 29]],
                    'ask_vols': [_f(i, True) for i in [20, 22, 24, 26, 28]],
                }
            except Exception:
                logger.debug("sina_orderbook item failed", exc_info=True)
                continue
        _record_call('sina_orderbook', True)
        return result
    except Exception as e:
        _record_call('sina_orderbook', False, str(e))
        return {}


# ============================================================
# 10. tencent_kline - 腾讯K线API (web.ifzq.gtimg.cn，无额度限制)
# ============================================================
def tencent_kline_batch(ts_codes, ktype='day'):
    """腾讯K线批量获取（前复权日K，限制30只）"""
    try:
        result = {}
        for tc in ts_codes[:30]:
            try:
                code = _ts_to_code(tc)
                if tc.endswith('.SH'):
                    symbol = f'sh{code}'
                elif tc.endswith('.BJ'):
                    symbol = f'bj{code}'
                else:
                    symbol = f'sz{code}'
                url = f'https://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={symbol},{ktype},,,5,qfq'
                resp = requests.get(url, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
                if resp.status_code != 200:
                    continue
                data = resp.json()
                kdata = data.get('data', {}).get(symbol, {})
                # 优先取 qfqday/day
                klines = kdata.get('qfqday') or kdata.get('day') or []
                if not klines:
                    continue
                latest = klines[-1]
                # [date, open, close, high, low, volume]
                if len(latest) >= 5:
                    close = float(latest[2]) if latest[2] else 0
                    pre_close = float(klines[-2][2]) if len(klines) >= 2 and klines[-2][2] else 0
                    pct_chg = ((close - pre_close) / pre_close * 100) if pre_close > 0 else 0
                    result[tc] = {
                        'price': close,
                        'price_chg': round(pct_chg, 2),
                    }
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        if result:
            _record_call('tencent_kline', True)
        else:
            _record_call('tencent_kline', False, 'no data')
        return result
    except Exception as e:
        _record_call('tencent_kline', False, str(e))
        return {}


# ============================================================
# 11. iTick - 实时行情API (itick.org，HTTP+WebSocket)
# ============================================================
_itick_available = None

def _check_itick():
    """检查iTick token是否配置"""
    global _itick_available
    if _itick_available is not None:
        return _itick_available
    try:
        from config import ITICK_TOKEN
        _itick_available = bool(ITICK_TOKEN)
    except Exception:
        logger.debug(f"_check_itick fallback", exc_info=True)
        _itick_available = False
    return _itick_available


def itick_batch_quotes(ts_codes):
    """iTick批量实时行情（A股，逐个请求，5次/秒限流）"""
    if not _check_itick():
        _record_call('itick', False, 'no token')
        return {}
    try:
        from config import ITICK_TOKEN, ITICK_BASE_URL
        result = {}
        headers = {
            'accept': 'application/json',
            'token': ITICK_TOKEN,
        }
        for tc in ts_codes[:30]:
            try:
                code = _ts_to_code(tc)
                if tc.endswith('.SH'):
                    region = 'SH'
                elif tc.endswith('.BJ'):
                    region = 'BJ'
                else:
                    region = 'SZ'
                url = f'{ITICK_BASE_URL}/stock/quote'
                params = {'region': region, 'code': code}
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                if resp.status_code != 200:
                    continue
                data = resp.json().get('data', {})
                if not data:
                    continue
                # data.ld=最新价, data.p=昨收, data.ch=涨跌额, data.chp=涨跌幅%
                price = float(data.get('ld', 0) or 0)
                pre_close = float(data.get('p', 0) or 0)
                pct_chg = float(str(data.get('chp', 0) or '0').replace('%', ''))
                if not pct_chg and pre_close > 0 and price > 0:
                    pct_chg = (price - pre_close) / pre_close * 100
                if price > 0:
                    result[tc] = {
                        'price': price,
                        'price_chg': round(pct_chg, 2),
                    }
                time.sleep(0.2)  # 5次/秒限流
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        if result:
            _record_call('itick', True)
        else:
            _record_call('itick', False, 'no data')
        return result
    except Exception as e:
        _record_call('itick', False, str(e))
        return {}


# ============================================================
# 12. jqdata - 聚宽 JoinQuant (jqdatasdk)
# ============================================================
_jq_logged_in = False
_jq_login_failed = False

def _jq_login():
    """聚宽登录（单例）"""
    global _jq_logged_in, _jq_login_failed
    if _jq_logged_in:
        return True
    if _jq_login_failed:
        return False
    try:
        from config import JQDATA_ACCOUNT, JQDATA_PASSWORD
        if not JQDATA_ACCOUNT or not JQDATA_PASSWORD:
            _jq_login_failed = True
            return False
        import jqdatasdk as jq
        jq.auth(JQDATA_ACCOUNT, JQDATA_PASSWORD)
        _jq_logged_in = True
        return True
    except Exception as e:
        _jq_login_failed = True
        _record_call('jqdata', False, f'login failed: {e}')
        return False


def jqdata_batch_quotes(ts_codes):
    """聚宽批量行情（日K线，限制30只）"""
    if not _jq_login():
        return {}
    try:
        import jqdatasdk as jq
        from datetime import datetime, timedelta
        result = {}
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')

        for tc in ts_codes[:30]:
            try:
                # ts_code(000001.SZ) → jq格式(000001.XSHE)
                code = _ts_to_code(tc)
                if tc.endswith('.SH'):
                    jq_code = f'{code}.XSHG'
                elif tc.endswith('.BJ'):
                    jq_code = f'{code}.XBJE'
                else:
                    jq_code = f'{code}.XSHE'

                df = jq.get_price(jq_code, start_date=start_date, end_date=end_date,
                                    frequency='daily', fields=['close', 'pre_close', 'high', 'low'],
                                    count=5)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    close = float(latest.get('close', 0) or 0)
                    pre_close = float(latest.get('pre_close', 0) or 0)
                    pct_chg = ((close - pre_close) / pre_close * 100) if pre_close > 0 else 0
                    result[tc] = {
                        'price': close,
                        'price_chg': round(pct_chg, 2),
                    }
            except Exception:
                logger.debug(f"function item failed", exc_info=True)
                continue
        if result:
            _record_call('jqdata', True)
        else:
            _record_call('jqdata', False, 'no data')
        return result
    except Exception as e:
        _record_call('jqdata', False, str(e))
        return {}


def jqdata_fund_flow(ts_code):
    """聚宽资金流向（大单统计，需高级权限）"""
    if not _jq_login():
        return None
    try:
        import jqdatasdk as jq
        from datetime import datetime
        code = _ts_to_code(ts_code)
        if ts_code.endswith('.SH'):
            jq_code = f'{code}.XSHG'
        elif ts_code.endswith('.BJ'):
            jq_code = f'{code}.XBJE'
        else:
            jq_code = f'{code}.XSHE'

        today = datetime.now().strftime('%Y-%m-%d')
        df = jq.get_money_flow(jq_code, end_date=today, fields=['sec_code', 'change_pct', 'net_amount_main'],
                               count=1)
        if df is not None and not df.empty:
            latest = df.iloc[0]
            main_net = float(latest.get('net_amount_main', 0) or 0)
            _record_call('jqdata', True)
            return {'main_force_inflow': main_net}
        _record_call('jqdata', False, 'no fund flow data')
        return None
    except Exception as e:
        _record_call('jqdata', False, str(e))
        return None


# ============================================================
# 统一接口：按数据源名调用
# ============================================================
def fetch_batch_quotes(source_name, ts_codes):
    """统一批量行情接口"""
    handlers = {
        'efinance': efinance_batch_quotes,
        'qstock': qstock_batch_quotes,
        'adata': adata_batch_quotes,
        'mootdx': mootdx_batch_quotes,
        'netease': netease_batch_quotes,
        'baostock': baostock_batch_quotes,
        'sina_quote': sina_quote_batch,
        'tencent_kline': tencent_kline_batch,
        'itick': itick_batch_quotes,
        'jqdata': jqdata_batch_quotes,
    }
    handler = handlers.get(source_name)
    if handler:
        return handler(ts_codes)
    return {}


def fetch_fund_flow(source_name, ts_code):
    """统一资金流向接口"""
    handlers = {
        'efinance': efinance_fund_flow,
        'qstock': qstock_fund_flow,
        'ths': lambda tc: ths_fund_flow_rank().get(tc),
        'jqdata': jqdata_fund_flow,
    }
    handler = handlers.get(source_name)
    if handler:
        return handler(ts_code)
    return None


if __name__ == '__main__':
    # 测试各数据源
    test_codes = ['000001.SZ', '600519.SH', '002475.SZ']

    print('=== efinance ===')
    r = efinance_batch_quotes(test_codes)
    print(f'  行情: {r}')

    print('\n=== qstock ===')
    r = qstock_batch_quotes(test_codes)
    print(f'  行情: {r}')

    print('\n=== netease ===')
    r = netease_batch_quotes(test_codes)
    print(f'  行情: {r}')

    print('\n=== adata ===')
    r = adata_batch_quotes(test_codes)
    print(f'  行情: {r}')

    print('\n=== mootdx ===')
    r = mootdx_batch_quotes(test_codes)
    print(f'  行情: {r}')

    print('\n=== 同花顺资金流向排名 ===')
    r = ths_fund_flow_rank()
    print(f'  获取 {len(r)} 只股票资金流向')

    print('\n=== 出错率统计 ===')
    stats = get_error_stats()
    for src, s in stats.items():
        print(f'  {src}: 调用{s["total_calls"]}次, 错误{s["errors"]}次, 出错率{s["error_rate"]}%')