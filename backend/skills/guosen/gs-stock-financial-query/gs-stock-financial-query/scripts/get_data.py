
import argparse
import json
import os
import sys
import uuid
import subprocess
from pathlib import Path
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import urlencode
from typing import Dict, Any, Optional, List
import ssl

GS_API_KEY = os.environ.get("GS_API_KEY", "")

if not GS_API_KEY:
    raise RuntimeError("缺少必要的凭证配置，请检查环境变量 GS_API_KEY")

DEFAULT_BASE_URL = "https://dgzt.guosen.com.cn/skills"
SOFT_NAME = "goldsun_skills"
TIMEOUT_SECONDS = 15
SKILL_NAME = "gs-stock-financial-query"

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
    params["skillName"] = SKILL_NAME
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


REPORT_TYPE_MAP = {
   "Q0": "最新",
    "Q4": "年报",
    "Q2": "半年报",
    "Q3": "三季报",
    "Q1": "一季报",
}


def query_a_stock_balance_sheet(code: str, market: str, report_type: str = "Q0", report_year: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询A股资产负债表
    
    Args:
        code: 证券代码，如 600000, 000001
        market: 证券市场，SH-上海，SZ-深圳
        report_type: 财报类型 Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报
        report_year: 财报年份，如 2024
        count: 财报数量
    
    Returns:
        包含资产负债表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/gsf10/financial/balanceSheet/1.0"
    params = {
        "code": code,
        "market": market,
        "reportType": report_type,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def query_a_stock_income_statement(code: str, market: str, report_type: str = "Q0", report_year: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询A股利润表
    
    Args:
        code: 证券代码
        market: 证券市场，SH-上海，SZ-深圳
        report_type: 财报类型 Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报
        report_year: 财报年份
        count: 财报数量
    
    Returns:
        包含利润表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/gsf10/financial/incomeStatement/1.0"
    params = {
        "code": code,
        "market": market,
        "reportType": report_type,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def query_a_stock_cash_flow_statement(code: str, market: str, report_type: str = "Q0", report_year: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询A股现金流量表
    
    Args:
        code: 证券代码
        market: 证券市场，SH-上海，SZ-深圳
        report_type: 财报类型 Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报
        report_year: 财报年份
        count: 财报数量
    
    Returns:
        包含现金流量表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/gsf10/financial/cashFlowStatement/1.0"
    params = {
        "code": code,
        "market": market,
        "reportType": report_type,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def query_hk_stock_balance_sheet(code: str, report_year: str = None, report_type: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询港股资产负债表
    
    Args:
        code: 证券代码，如 02020
        report_year: 报告日期，如 2021-06-30
        report_type: 报告类型 Q1-一季报，Q2-中报，Q3-三季报，Q4-年报
        count: 查询期数，默认为1
    
    Returns:
        包含资产负债表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/hkf10/financial/balanceSheet/1.0"
    params = {
        "code": code,
        "market": "HK",
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if report_type:
        params["reportType"] = report_type
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def query_hk_stock_income_statement(code: str, report_year: str = None, report_type: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询港股利润表
    
    Args:
        code: 证券代码
        report_year: 报告日期
        report_type: 报告类型 Q1-一季报，Q2-中报，Q3-三季报，Q4-年报
        count: 查询期数，默认为1
    
    Returns:
        包含利润表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/hkf10/financial/incomeStatement/1.0"
    params = {
        "code": code,
        "market": "HK",
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if report_type:
        params["reportType"] = report_type
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def query_hk_stock_cash_flow_statement(code: str, report_year: str = None, report_type: str = None, count: int = 1) -> Dict[str, Any]:
    """
    查询港股现金流量表
    
    Args:
        code: 证券代码
        report_year: 报告日期
        report_type: 报告类型 Q1-一季报，Q2-中报，Q3-三季报，Q4-年报
        count: 查询期数，默认为1
    
    Returns:
        包含现金流量表数据的字典
    """
    url = f"{DEFAULT_BASE_URL}/gsnews/hkf10/financial/cashFlowStatement/1.0"
    params = {
        "code": code,
        "market": "HK",
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }
    
    if report_year:
        params["reportYear"] = report_year
    if report_type:
        params["reportType"] = report_type
    if count:
        params["count"] = str(count)
    
    return _make_request(url, params)


def main():
    parser = argparse.ArgumentParser(description="国信财务数据查询工具")
    parser.add_argument("action", 
                        choices=["a_balance", "a_income", "a_cashflow", "hk_balance", "hk_income", "hk_cashflow"], 
                        help="查询动作")
    parser.add_argument("--code", type=str, required=True, help="证券代码")
    parser.add_argument("--market", type=str, help="证券市场(SH/SZ)")
    parser.add_argument("--report_type", type=str, default="Q0", help="财报类型")
    parser.add_argument("--report_year", type=str, help="财报年份")
    parser.add_argument("--count", type=int, default=1, help="财报数量")
    
    args = parser.parse_args()
    
    result = None
    
    if args.action == "a_balance":
        if not args.market:
            print("错误: --market 参数必填")
            sys.exit(1)
        result = query_a_stock_balance_sheet(args.code, args.market, args.report_type, args.report_year, args.count)
        
    elif args.action == "a_income":
        if not args.market:
            print("错误: --market 参数必填")
            sys.exit(1)
        result = query_a_stock_income_statement(args.code, args.market, args.report_type, args.report_year, args.count)
        
    elif args.action == "a_cashflow":
        if not args.market:
            print("错误: --market 参数必填")
            sys.exit(1)
        result = query_a_stock_cash_flow_statement(args.code, args.market, args.report_type, args.report_year, args.count)
        
    elif args.action == "hk_balance":
        result = query_hk_stock_balance_sheet(args.code, args.report_year, args.report_type, args.count)
        
    elif args.action == "hk_income":
        result = query_hk_stock_income_statement(args.code, args.report_year, args.report_type, args.count)
        
    elif args.action == "hk_cashflow":
        result = query_hk_stock_cash_flow_statement(args.code, args.report_year, args.report_type, args.count)
    
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
