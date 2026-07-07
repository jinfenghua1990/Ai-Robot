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
from typing import Dict, Any, Optional
import ssl
import warnings
warnings.filterwarnings('ignore')

DEFAULT_BASE_URL = "https://dgzt.guosen.com.cn/skills"
SOFT_NAME = "goldsun_skills"
TIMEOUT_SECONDS = 60
SKILL_NAME = "gs-economy-query"
GS_API_KEY = os.environ.get("GS_API_KEY", "")

if not GS_API_KEY:
    raise RuntimeError("缺少必要的凭证配置，请检查环境变量 GS_API_KEY")


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
    
    def process_response(result_data: Dict[str, Any]) -> Dict[str, Any]:
        """处理API响应数据"""
        if result_data.get("result") and result_data["result"][0].get("code") == 0:
            if result_data.get("data"):
                content_parts = []
                for item in result_data["data"]:
                    if item.get("type") == "STREAM_MESSAGE":
                        content_parts.append(item.get("content", ""))
                return {"content": "".join(content_parts)}
            else:
                return {"error": "No data in response"}
        else:
            error_msg = result_data.get("result", [{}])[0].get("msg", "Unknown error")
            return {"error": error_msg}
    
    try:
        query_string = urlencode(params)
        full_url = f"{url}?{query_string}"
        
        ssl_ctx = _create_ssl_context()
        if ssl_ctx:
            req = urllib_request.Request(full_url)
            with urllib_request.urlopen(req, context=ssl_ctx, timeout=TIMEOUT_SECONDS) as response:
                result_data = json.loads(response.read().decode("utf-8"))
                return process_response(result_data)
        else:
            req = urllib_request.Request(full_url)
            with urllib_request.urlopen(req, timeout=TIMEOUT_SECONDS) as response:
                result_data = json.loads(response.read().decode("utf-8"))
                return process_response(result_data)
    except urllib_error.HTTPError as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)
    except urllib_error.URLError as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)
    except Exception as e:
        full_url = f"{url}?{urlencode(params)}"
        return _curl_request(full_url)


def query_macro_data(query: str) -> Dict[str, Any]:
    """
    查询宏观经济数据

    Args:
        query: 自然语言查询文本

    Returns:
        包含查询结果的字典
    """
    url = f"{DEFAULT_BASE_URL}/agent/adapter/query"

    params = {
        "text": query,
        "softName": SOFT_NAME,
        "apiKey": GS_API_KEY
    }

    return _make_request(url, params)


def main():
    parser = argparse.ArgumentParser(description="国信宏观经济数据查询工具")
    parser.add_argument("query", type=str, nargs="?", help="自然语言查询文本")

    args = parser.parse_args()

    if not args.query:
        parser.print_help()
        sys.exit(1)

    result = query_macro_data(args.query)

    if "error" in result:
        print(f"错误: {result['error']}")
        sys.exit(1)
    else:
        print(result.get("content", ""))


if __name__ == "__main__":
    main()
