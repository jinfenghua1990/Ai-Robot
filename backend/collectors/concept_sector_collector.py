"""
概念板块实时资金流向采集（新浪财经）
- 直接拿概念板块维度资金流，不再依赖成分股实时快照的覆盖完整性
- 返回结构与 get_sector_money_flow 一致，便于复用写入逻辑
"""
import os
import sys
import requests
from utils.http_constants import SINA_HEADERS

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# SINA_HEADERS imported from utils.http_constants


def get_concept_sector_money_flow_realtime(pages=10, per_page=100):
    """
    从新浪财经获取概念板块实时资金流向（当日累计主力净流入）。
    返回: [{'sector': '算力', 'net_flow': 158600.0, 'money_inflow': ..., 'money_outflow': ..., 'rise_ratio': ...}, ...]
    net_flow 单位：万元
    """
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'
    items = []
    for page in range(1, pages + 1):
        try:
            resp = requests.get(url, params={
                'page': page, 'num': per_page, 'sort': 'netamount', 'asc': 0, 'fenlei': 1
            }, timeout=15, headers=SINA_HEADERS)
            data = resp.json()
            if not data:
                break
            seen = set()
            for item in data:
                name = item.get('name', '').strip()
                netamount = float(item.get('netamount', 0) or 0) / 10000  # 元 -> 万元
                avg_chg = float(item.get('avgchangeratio', 0) or 0)
                if not name or name in seen:
                    continue
                seen.add(name)
                items.append({
                    'sector': name,
                    'net_flow': netamount,
                    'money_inflow': max(netamount, 0),
                    'money_outflow': max(-netamount, 0),
                    'rise_ratio': avg_chg,
                    'source': 'sina',
                })
            if len(data) < per_page:
                break
        except Exception as e:
            logger.warning(f'[concept_sector_collector] sina page {page} error: {e}', exc_info=True)
            break

    print(f'[concept_sector_collector] fetched {len(items)} concept sectors from sina')
    return items


if __name__ == '__main__':
    # 本地测试
    results = get_concept_sector_money_flow_realtime(pages=2)
    for r in results[:10]:
        print(r)
