"""共享 HTTP 常量：请求头、代理清除等"""

import os

# 新浪财经请求头（统一 User-Agent + Referer）
SINA_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Referer": "https://finance.sina.com.cn",
}

# 新浪财经请求头（精简版，用于行情等简单接口）
SINA_HEADERS_SHORT = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}


def clear_proxy_env():
    """清除代理环境变量，避免本地请求走代理"""
    for _k in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'all_proxy', 'ALL_PROXY']:
        os.environ.pop(_k, None)
    os.environ.setdefault('no_proxy', '*')
