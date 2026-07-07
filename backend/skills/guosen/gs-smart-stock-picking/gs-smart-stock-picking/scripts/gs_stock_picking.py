#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
国信证券智能选股接口调用脚本
用于根据各种财务指标和技术指标筛选符合条件的股票
"""

import os
import json
import urllib3
import ssl
import urllib.parse
import sys
import io

# 在文件开头添加，强制 stdout 使用 UTF-8
if sys.stdout.encoding != 'UTF-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

# 禁用 SSL 警告
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://dgzt.guosen.com.cn/skills/agent"


def smart_stock_picking(searchstring, searchtype, api_key):
    """
    调用国信证券智能选股接口

    Args:
        searchstring: 选股条件，例如："市盈率小于20的银行股"
        searchtype: 搜索类型，可选值：stock, fund, HK_stock, US_stock, NEEQ, index
        api_key: API密钥，用于身份验证

    Returns:
        接口返回的结果
    """
    # 创建 SSL 上下文，允许旧版重新协商
    ctx = ssl.create_default_context()
    ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT  # 关键：启用旧版 SSL 重新协商
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    # 构建 URL 和参数
    url = f"{BASE_URL}/mcp/smart_stock_picking"
    params = {
        "searchstring": searchstring,
        "searchtype": searchtype,
        "softName": "goldsun_skills",
        "skillName": "gs-smart-stock-picking",
        "apiKey": api_key
    }

    # 构建完整 URL（包含查询参数）
    full_url = f"{url}?{urllib.parse.urlencode(params)}"

    try:
        # 用 urllib3 的 PoolManager 直接发起请求
        http = urllib3.PoolManager(ssl_context=ctx)
        response = http.request('GET', full_url, timeout=30)

        # 检查响应状态
        if response.status >= 400:
            print(f"请求失败: HTTP {response.status}")
            return None

        # 解析 JSON 响应
        import json
        return json.loads(response.data.decode('utf-8'))

    except Exception as e:
        print(f"请求失败: {e}")
        return None


def print_result(result):
    """
    打印查询结果

    Args:
        result: 接口返回的结果
    """
    if not result:
        print("未获取到结果")
        return

    # 检查结果状态
    if "result" in result:
        results = result["result"]
        if isinstance(results, list) and len(results) > 0:
            code = results[0].get("code", -1)
            msg = results[0].get("msg", "未知错误")
            print(f"状态码: {code}")
            print(f"消息: {msg}")

            if code == 0 and "data" in result and result["data"]:
                # 处理返回的数据
                data = result["data"]
                if isinstance(data, list):
                    for i, obj in enumerate(data):
                        print(f"\n结果 #{i+1}:")
                        if "table" in obj:
                            table = obj["table"]
                            for key, values in table.items():
                                # 确保 key 是字符串并正常打印
                                print(f"{key}:")
                                for value in values:
                                    # 如果 value 是 bytes，解码；否则直接打印
                                    if isinstance(value, bytes):
                                        value = value.decode('utf-8')
                                    print(f"  - {value}")
                else:
                    print("返回数据格式异常")
            elif code != 0:
                print("查询失败")
        else:
            print("返回数据格式异常")
    else:
        print("返回数据格式异常")


def main():
    """
    主函数
    """
    import argparse

    parser = argparse.ArgumentParser(description="国信证券智能选股接口调用脚本")
    parser.add_argument("--searchstring", required=True, help="选股条件，例如：'市盈率小于20的银行股'")
    parser.add_argument("--searchtype", required=True, choices=["stock", "fund", "HK_stock", "US_stock", "NEEQ", "index"], help="搜索类型")
    parser.add_argument("--api-key", dest="api_key", required=True, help="API Key，用于身份验证")

    args = parser.parse_args()

    print(f"查询条件: {args.searchstring}")
    print(f"搜索类型: {args.searchtype}")
    print("正在查询...")

    result = smart_stock_picking(args.searchstring, args.searchtype, args.api_key)
    print_result(result)


if __name__ == "__main__":
    main()