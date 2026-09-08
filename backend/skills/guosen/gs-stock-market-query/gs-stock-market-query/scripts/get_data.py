import argparse
import json
import os
import sys
import uuid
import subprocess
import re
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode
from typing import Dict, Any, Optional, List
import ssl
import warnings
warnings.filterwarnings('ignore')

GS_API_KEY = os.environ.get("GS_API_KEY", "")

if not GS_API_KEY:
    raise RuntimeError("缺少必要的凭证配置，请检查环境变量 GS_API_KEY")

DEFAULT_BASE_URL = "https://dgzt.guosen.com.cn/skills"
SOFT_NAME = "goldsun_skills"
SKILL_NAME = "gs-stock-market-query"
TIMEOUT_SECONDS = 15


def _create_ssl_context():
    """创建SSL上下文，允许不安全的 renegotiation 以兼容旧服务器"""
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            ctx.set_ciphers('ALL:@SECLEVEL=0')
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        except Exception:
            pass
        return ctx
    except Exception as e:
        pass
    
    try:
        ctx = ssl._create_unverified_context()
        try:
            ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
            ctx.set_ciphers('ALL:@SECLEVEL=0')
        except Exception:
            pass
        return ctx
    except Exception:
        pass
    
    return None


def _curl_request(url: str) -> Dict[str, Any]:
    """使用curl发送请求，当requests/urllib失败时的备用方案"""
    try:
        result = subprocess.run(
            ["curl", "-s", "-k", url],
            capture_output=True,
            text=True,
            timeout=30,
            encoding='utf-8',
            errors='ignore'
        )
        if result.returncode == 0 and result.stdout:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                return {"error": "Invalid JSON response", "raw": result.stdout[:500]}
        else:
            return {"error": f"curl failed: {result.stderr}"}
    except Exception as e:
        return {"error": str(e)}


def _make_request(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """发送请求，支持 urllib 和 curl 备用"""
    params["skillName"] = SKILL_NAME 
    try:
        query_string = urlencode(params)
        full_url = f"{url}?{query_string}"
        
        ssl_ctx = _create_ssl_context()
        if ssl_ctx:
            req = urllib_request.Request(full_url)
            with urllib_request.urlopen(req, context=ssl_ctx, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
        else:
            req = urllib_request.Request(full_url)
            with urllib_request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                return json.loads(response.read().decode("utf-8"))
    except urllib_error.HTTPError as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)
    except urllib_error.URLError as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)
    except Exception as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)


SET_CODE_MAP = {
    "深圳": 0,
    "上海": 1,
    "北交所": 2,
    "港股": -1,
    "美股": 74,
}

SET_DOMAIN_MAP = {
    "上证A股": 0,
    "深证A股": 2,
    "北交所": 14515,
    "沪深A股": 6,
    "创业板": 14,
    "沪深ETF基金": 11005,
}


def query_single_hq(code: str, set_code: int = 0, target: int = 0) -> Dict[str, Any]:
    """
    查询单个证券实时行情
    
    Args:
        code: 证券代码，如 600519, 000001
        set_code: 证券市场代码 0-深圳, 1-上海, 2-北交所, -1-港股, 74-美股
        target: 站点信息 0-沪深京(默认), 3-港股美股
    
    Returns:
        包含行情数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryHQInfo/1.0"
    params = {
        "code": code,
        "setCode": set_code,
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    return _make_request(url, params)


def query_comb_hq(codes: List[str], set_codes: List[int], target: int = 0) -> Dict[str, Any]:
    """
    查询多个证券实时行情
    
    Args:
        codes: 证券代码列表
        set_codes: 证券市场代码列表
        target: 站点信息 0-沪深京(默认), 3-港股美股
    
    Returns:
        包含行情数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryCombHQ/1.0"
    params = {
        "code": ",".join(codes),
        "setCode": ",".join(str(sc) for sc in set_codes),
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    return _make_request(url, params)


def query_fund_flow(code: str, set_code: int, period: int = 60) -> Dict[str, Any]:
    """
    查询资金流向
    
    Args:
        code: 证券代码
        set_code: 证券市场代码 0-深圳, 1-上海
        period: 周期，单位为日，最多60日
    
    Returns:
        包含资金流向数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryFundFlow/1.0"
    params = {
        "code": code,
        "setCode": str(set_code),
        "period": str(period),
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    return _make_request(url, params)


def query_multi_hq(set_domain: int, want_num: int, sort_type: int = 1, target: int = 0) -> Dict[str, Any]:
    """
    查询涨幅排名
    
    Args:
        set_domain: 查询类型 0-上证A股, 2-深证A股, 6-沪深A股, 14-创业板, 14515-北交所, 11005-沪深ETF
        want_num: 返回数量，最多80
        sort_type: 1-涨幅(默认), 2-跌幅
        target: 0-沪深(默认), 3-港股美股
    
    Returns:
        包含涨幅排名数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryMultiHQ/1.0"
    params = {
        "setDomain": set_domain,
        "wantNum": want_num,
        "sortType": sort_type,
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    return _make_request(url, params)


def query_related_comb_hq(code: str, set_code: int, target: int = 0) -> Dict[str, Any]:
    """
    查询个股关联板块
    
    Args:
        code: 证券代码
        set_code: 证券市场代码 0-深圳, 1-上海, 2-北交所, 74-美股
        target: 站点信息 0-沪深京(默认), 3-港股美股
    
    Returns:
        包含关联板块数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryRelatedCombHQ/1.0"
    params = {
        "code": code,
        "setCode": set_code,
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    return _make_request(url, params)


def query_past_hq(code: str, set_code: int, want_nums: int, target: int = 0, mas: str = None) -> Dict[str, Any]:
    """
    查询近n个交易日日行情
    
    Args:
        code: 证券代码
        set_code: 证券市场代码 0-深圳, 1-上海, 2-北交所, -1-港股, 74-美股
        want_nums: 近n个交易日
        target: 站点信息 0-沪深京(默认), 3-港股美股
        mas: 要计算的MA周期，多个以逗号分隔
    
    Returns:
        包含历史行情数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/market/agentbot/queryPastHQInfo/1.0"
    params = {
        "code": code,
        "setCode": str(set_code),
        "wantNums": str(want_nums),
        "target": target,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if mas:
        params["mas"] = mas
    
    return _make_request(url, params)


def main():
    parser = argparse.ArgumentParser(description="国信股市行情查询工具")
    parser.add_argument("action", choices=["single_hq", "comb_hq", "fund_flow", "multi_hq", "related_comb", "past_hq"], 
                        help="查询动作")
    parser.add_argument("--code", type=str, help="证券代码")
    parser.add_argument("--codes", type=str, help="证券代码列表(逗号分隔)")
    parser.add_argument("--set_code", type=int, default=0, help="证券市场代码")
    parser.add_argument("--set_codes", type=str, help="证券市场代码列表(逗号分隔)")
    parser.add_argument("--set_domain", type=int, default=6, help="查询类型")
    parser.add_argument("--target", type=int, default=0, help="站点信息")
    parser.add_argument("--period", type=int, default=60, help="周期")
    parser.add_argument("--want_num", type=int, default=10, help="返回数量")
    parser.add_argument("--sort_type", type=int, default=1, help="排序类型")
    parser.add_argument("--want_nums", type=int, default=20, help="近n个交易日")
    parser.add_argument("--mas", type=str, help="MA周期(逗号分隔)")
    
    args = parser.parse_args()
    
    result = None
    
    if args.action == "single_hq":
        if not args.code:
            print("错误: --code 参数必填")
            sys.exit(1)
        result = query_single_hq(args.code, args.set_code, args.target)
        
    elif args.action == "comb_hq":
        if not args.codes or not args.set_codes:
            print("错误: --codes 和 --set_codes 参数必填")
            sys.exit(1)
        codes = args.codes.split(",")
        set_codes = [int(sc) for sc in args.set_codes.split(",")]
        result = query_comb_hq(codes, set_codes, args.target)
        
    elif args.action == "fund_flow":
        if not args.code:
            print("错误: --code 参数必填")
            sys.exit(1)
        result = query_fund_flow(args.code, args.set_code, args.period)
        
    elif args.action == "multi_hq":
        result = query_multi_hq(args.set_domain, args.want_num, args.sort_type, args.target)
        
    elif args.action == "related_comb":
        if not args.code:
            print("错误: --code 参数必填")
            sys.exit(1)
        result = query_related_comb_hq(args.code, args.set_code, args.target)
        
    elif args.action == "past_hq":
        if not args.code:
            print("错误: --code 参数必填")
            sys.exit(1)
        result = query_past_hq(args.code, args.set_code, args.want_nums, args.target, args.mas)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
