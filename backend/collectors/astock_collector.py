"""
a-stock-data 采集器（免费开源数据源）
提取 SKILL.md 中的关键函数，作为第6个数据源用于交叉验证
- 腾讯财经：批量实时行情（PE/PB/市值/换手率/涨跌停），不封IP
- 东财push2：分钟级个股资金流向（主力/超大单/大单/中单/小单）
- mootdx：K线+五档盘口（TCP协议，不封IP）
"""
import logging
import threading
import urllib.request
import requests
import time

logger = logging.getLogger(__name__)
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"

# 东财请求间隔（社区实测防封阈值）。实时采集会并发调用这里，故需用同一把锁
# 串行化预约，避免多线程在同一时刻绕过间隔并触发上游断连。
_EM_LAST_CALL = 0.0
_EM_REQUEST_LOCK = threading.Lock()
_EM_FAILURE_UNTIL = 0.0
_EM_FAILURE_LOGGED_AT = 0.0
_EM_MIN_INTERVAL_SECONDS = 1.2
_EM_FAILURE_COOLDOWN_SECONDS = 60.0
_SINA_FUND_FLOW_FAILURE_UNTIL = 0.0
_SINA_FUND_FLOW_FAILURE_LOGGED_AT = 0.0
_SINA_FUND_FLOW_LOCK = threading.Lock()
_SINA_FUND_FLOW_FAILURE_COOLDOWN_SECONDS = 60.0


class _EastmoneyTemporarilyUnavailable(Exception):
    """Eastmoney push2 is in a short cooldown after a transport failure."""


def _record_em_failure(operation, code, exc):
    """Open a short circuit breaker and rate-limit noisy upstream failures."""
    global _EM_FAILURE_UNTIL, _EM_FAILURE_LOGGED_AT
    now = time.monotonic()
    with _EM_REQUEST_LOCK:
        _EM_FAILURE_UNTIL = max(_EM_FAILURE_UNTIL, now + _EM_FAILURE_COOLDOWN_SECONDS)
        should_log = now - _EM_FAILURE_LOGGED_AT >= _EM_FAILURE_COOLDOWN_SECONDS
        if should_log:
            _EM_FAILURE_LOGGED_AT = now
    if should_log:
        logger.warning(
            "[em-push2] %s unavailable for %s; fallback source will be used (%s)",
            operation, code, type(exc).__name__,
        )

def _em_get(url, params=None, headers=None, timeout=10):
    """东财请求带限流（≥1.2秒间隔）"""
    global _EM_LAST_CALL
    with _EM_REQUEST_LOCK:
        now = time.monotonic()
        if now < _EM_FAILURE_UNTIL:
            raise _EastmoneyTemporarilyUnavailable()
        elapsed = now - _EM_LAST_CALL
        if elapsed < _EM_MIN_INTERVAL_SECONDS:
            time.sleep(_EM_MIN_INTERVAL_SECONDS - elapsed)
        _EM_LAST_CALL = time.monotonic()
    h = {"User-Agent": UA, "Referer": "https://quote.eastmoney.com/"}
    if headers:
        h.update(headers)
    return requests.get(url, params=params, headers=h, timeout=timeout)


def tencent_quote(codes):
    """
    腾讯财经批量实时行情（不封IP）
    codes: ["688017", "300476", "002463"] 或指数 ["000001"]
    返回: {code: {name, price, change_pct, pe_ttm, pb, mcap_yi, ...}}
    """
    prefixed = []
    for c in codes:
        if c.startswith(("6", "9")):
            prefixed.append(f"sh{c}")
        elif c.startswith("8"):
            prefixed.append(f"bj{c}")
        else:
            prefixed.append(f"sz{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", UA)
    try:
        resp = urllib.request.urlopen(req, timeout=10)
        data = resp.read().decode("gbk")
    except Exception as e:
        logger.warning(f"[tencent] quote error: {e}", exc_info=True)
        return {}

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        try:
            result[code] = {
                "name":         vals[1],
                "price":        float(vals[3]) if vals[3] else 0,
                "last_close":   float(vals[4]) if vals[4] else 0,
                "open":         float(vals[5]) if vals[5] else 0,
                "change_amt":   float(vals[31]) if vals[31] else 0,
                "change_pct":   float(vals[32]) if vals[32] else 0,
                "high":         float(vals[33]) if vals[33] else 0,
                "low":          float(vals[34]) if vals[34] else 0,
                "amount_wan":   float(vals[37]) if vals[37] else 0,
                "turnover_pct": float(vals[38]) if vals[38] else 0,
                "pe_ttm":       float(vals[39]) if vals[39] else 0,
                "amplitude_pct":float(vals[43]) if vals[43] else 0,
                "mcap_yi":      float(vals[44]) if vals[44] else 0,
                "float_mcap_yi":float(vals[45]) if vals[45] else 0,
                "pb":           float(vals[46]) if vals[46] else 0,
                "limit_up":     float(vals[47]) if vals[47] else 0,
                "limit_down":   float(vals[48]) if vals[48] else 0,
                "vol_ratio":    float(vals[49]) if vals[49] else 0,
            }
        except (ValueError, IndexError):
            continue
    return result


def eastmoney_fund_flow_minute(code):
    """
    东财push2 个股资金流向（分钟级，当日盘中）
    code: 6位股票代码
    返回: [{time, main_net, small_net, mid_net, large_net, super_net}, ...] 单位：元
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 1,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    try:
        r = _em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except _EastmoneyTemporarilyUnavailable:
        return []
    except Exception as exc:
        _record_em_failure("minute fund flow", code, exc)
        return []

    rows = []
    for line in d.get("data", {}).get("klines", []):
        parts = line.split(",")
        if len(parts) >= 6:
            try:
                rows.append({
                    "time": parts[0],
                    "main_net": float(parts[1]),    # 主力净流入（元）
                    "small_net": float(parts[2]),   # 小单净流入（元）
                    "mid_net": float(parts[3]),     # 中单净流入（元）
                    "large_net": float(parts[4]),   # 大单净流入（元）
                    "super_net": float(parts[5]),   # 超大单净流入（元）
                })
            except (ValueError, IndexError):
                continue
    return rows


def eastmoney_fund_flow_daily(code):
    """
    东财push2 个股资金流向（日级，当日累计）
    code: 6位股票代码
    返回: {main_net, small_net, mid_net, large_net, super_net} 单位：元
    """
    secid = f"1.{code}" if code.startswith("6") else f"0.{code}"
    url = "https://push2.eastmoney.com/api/qt/stock/fflow/kline/get"
    params = {
        "secid": secid, "klt": 101,
        "fields1": "f1,f2,f3,f7",
        "fields2": "f51,f52,f53,f54,f55,f56,f57",
    }
    headers = {"Referer": "https://quote.eastmoney.com/", "Origin": "https://quote.eastmoney.com"}
    try:
        r = _em_get(url, params=params, headers=headers, timeout=10)
        d = r.json()
    except _EastmoneyTemporarilyUnavailable:
        return None
    except Exception as exc:
        _record_em_failure("daily fund flow", code, exc)
        return None

    klines = d.get("data", {}).get("klines", [])
    if not klines:
        return None
    # 取最后一条（当日）
    parts = klines[-1].split(",")
    if len(parts) >= 6:
        try:
            return {
                "main_net": float(parts[1]),
                "small_net": float(parts[2]),
                "mid_net": float(parts[3]),
                "large_net": float(parts[4]),
            }
        except (ValueError, IndexError):
            pass
    return None


def batch_realtime_quotes(ts_codes):
    """
    批量获取实时行情（腾讯财经，用于交叉验证价格/涨跌幅）
    ts_codes: ["600519.SH", "000001.SZ", ...]
    返回: {ts_code: {price, change_pct, pe_ttm, pb, mcap_yi, ...}}
    """
    codes = [tc.replace(".SH", "").replace(".SZ", "").replace(".BJ", "") for tc in ts_codes]
    raw = tencent_quote(codes)
    result = {}
    for code, q in raw.items():
        # 还原 ts_code
        if code.startswith(("6", "9")):
            tc = f"{code}.SH"
        elif code.startswith("8"):
            tc = f"{code}.BJ"
        else:
            tc = f"{code}.SZ"
        result[tc] = q
    return result


def sina_stock_fund_flow(code):
    """
    新浪财经个股资金流向（当日累计）
    code: 6位股票代码
    返回: {main_net, super_net, big_net, mid_net, small_net} 单位：元
    """
    global _SINA_FUND_FLOW_FAILURE_UNTIL, _SINA_FUND_FLOW_FAILURE_LOGGED_AT
    now = time.monotonic()
    with _SINA_FUND_FLOW_LOCK:
        if now < _SINA_FUND_FLOW_FAILURE_UNTIL:
            return None

    if code.startswith(("6", "9")):
        prefix = "sh"
    elif code.startswith("8"):
        prefix = "bj"
    else:
        prefix = "sz"
    url = f"https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_zjlrqs"
    params = {
        "stock_code": f"{prefix}{code}",
        "page": "1",
        "num": "1",
        "sort": "opendate",
        "asc": "0",
    }
    headers = {"User-Agent": UA, "Referer": "https://vip.stock.finance.sina.com.cn/"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        r.raise_for_status()
        data = r.json()
        if not data or len(data) == 0:
            return None
        d = data[0]
        return {
            "main_net": float(d.get("netamount", 0)),       # 主力净流入（元）
            "super_net": float(d.get("r0_net", 0)),          # 超大单净流入（元）
            "big_net": float(d.get("r1_net", 0)),            # 大单净流入（元）
            "mid_net": float(d.get("r2_net", 0)),            # 中单净流入（元）
            "small_net": float(d.get("r3_net", 0)),          # 小单净流入（元）
        }
    except (requests.RequestException, ValueError) as e:
        # 新浪偶尔返回 HTML 验证页。采集任务会继续尝试其他已配置来源，
        # 本轮不再为每只股票重复发请求或打印堆栈，下一分钟自动恢复尝试。
        with _SINA_FUND_FLOW_LOCK:
            _SINA_FUND_FLOW_FAILURE_UNTIL = max(
                _SINA_FUND_FLOW_FAILURE_UNTIL,
                time.monotonic() + _SINA_FUND_FLOW_FAILURE_COOLDOWN_SECONDS,
            )
            should_log = time.monotonic() - _SINA_FUND_FLOW_FAILURE_LOGGED_AT >= _SINA_FUND_FLOW_FAILURE_COOLDOWN_SECONDS
            if should_log:
                _SINA_FUND_FLOW_FAILURE_LOGGED_AT = time.monotonic()
        if should_log:
            logger.warning("[sina] stock fund_flow unavailable; pause retries for 60 seconds (%s)", type(e).__name__)
        return None


def tdx_realtime_price(ts_codes):
    """
    通达信实时行情（pytdx，TCP协议不封IP，无额度限制）
    ts_codes: ["600519.SH", "000001.SZ", ...]
    返回: {ts_code: {price, last_close, change_pct}}
    """
    try:
        from collectors.tdx_collector import connect_with_retry, PYTDX_AVAILABLE
        if not PYTDX_AVAILABLE:
            return {}
        api, server = connect_with_retry()
        if not api:
            return {}
        result = {}
        for tc in ts_codes:
            code = tc.replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
            market = 1 if tc.endswith(".SH") else 0
            try:
                quotes = api.get_security_quotes([(market, code)])
                if quotes and len(quotes) > 0:
                    q = quotes[0]
                    price = q.get("price", 0)
                    last_close = q.get("last_close", 0)
                    change_pct = ((price - last_close) / last_close * 100) if last_close else 0
                    result[tc] = {
                        "price": price,
                        "last_close": last_close,
                    }
            except Exception as e:
                logger.debug(f'[astock] 单股实时行情拉取失败 code={tc}: {e}')
        api.disconnect()
        return result
    except Exception as e:
        logger.warning(f"[tdx] realtime price error: {e}", exc_info=True)
        return {}


if __name__ == '__main__':
    print('=== 腾讯财经批量行情 ===')
    quotes = batch_realtime_quotes(['600519.SH', '000001.SZ', '002475.SZ'])
    for tc, q in quotes.items():
        print(f"  {q['name']}({tc}): {q['price']}元 涨跌{q['change_pct']}% PE={q['pe_ttm']} PB={q['pb']} 市值={q['mcap_yi']}亿")

    print('\n=== 东财push2 资金流向（日级）===')
    flow = eastmoney_fund_flow_daily('600519')
    if flow:
        print(f"  贵州茅台: 主力净流入={flow['main_net']/1e4:.0f}万 超大单={flow['super_net']/1e4:.0f}万")
