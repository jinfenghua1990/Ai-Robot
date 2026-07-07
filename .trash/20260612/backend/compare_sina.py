"""新浪 vs Tushare 数据对比"""
import requests
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.connection import get_db
from db.models import SectorFlow
from datetime import datetime

# === 1. 获取新浪全量行业板块数据 ===
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Referer': 'http://vip.stock.finance.sina.com.cn/',
}
url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'

sina_all = []
for page in range(1, 5):
    params = {'page': page, 'num': 100, 'sort': 'netamount', 'asc': 0, 'fenlei': 0}
    resp = requests.get(url, params=params, timeout=10, headers=headers)
    data = resp.json()
    if not data:
        break
    sina_all.extend(data)
    if len(data) < 100:
        break

print(f'新浪行业板块: {len(sina_all)} 个')
sina_in = sum(float(it.get('netamount', 0) or 0) for it in sina_all if float(it.get('netamount', 0) or 0) > 0)
sina_out = sum(float(it.get('netamount', 0) or 0) for it in sina_all if float(it.get('netamount', 0) or 0) < 0)
print(f'新浪总流入: {sina_in/100000000:.2f}亿')
print(f'新浪总流出: {sina_out/100000000:.2f}亿')
print(f'新浪净额: {(sina_in+sina_out)/100000000:.2f}亿')

# === 2. 获取我们的 Tushare 数据 ===
print()
db = next(get_db())
today = datetime.now().date()
our_sectors = db.query(SectorFlow).filter(SectorFlow.trade_date == today).all()
print(f'我们的板块: {len(our_sectors)} 个')
our_in = sum(float(s.net_flow or 0) for s in our_sectors if float(s.net_flow or 0) > 0)
our_out = sum(float(s.net_flow or 0) for s in our_sectors if float(s.net_flow or 0) < 0)
print(f'我们的总流入: {our_in/10000:.2f}亿')
print(f'我们的总流出: {our_out/10000:.2f}亿')
print(f'我们的净额: {(our_in+our_out)/10000:.2f}亿')

# === 3. 逐板块对比（找共同板块）===
print()
print('=' * 60)
print('共同板块对比')
print('=' * 60)
sina_map = {it.get('name', ''): float(it.get('netamount', 0) or 0) for it in sina_all}
our_map = {s.sector: float(s.net_flow or 0) * 10000 for s in our_sectors}  # 万→元

# 找名称相近的板块
matched = []
for sina_name, sina_val in sina_map.items():
    for our_name, our_val in our_map.items():
        # 精确匹配或包含关系
        if sina_name == our_name or sina_name in our_name or our_name in sina_name:
            matched.append((sina_name, our_name, sina_val, our_val))
            break

print(f'匹配到 {len(matched)} 个板块')
print()
print(f'{"新浪名称":<12} {"我们的名称":<12} {"新浪(亿)":>10} {"我们(亿)":>10} {"差异":>10}')
for sina_name, our_name, sina_val, our_val in sorted(matched, key=lambda x: abs(x[2]-x[3]), reverse=True):
    sina_yi = sina_val / 100000000
    our_yi = our_val / 100000000
    diff = our_yi - sina_yi
    print(f'{sina_name:<12} {our_name:<12} {sina_yi:>10.2f} {our_yi:>10.2f} {diff:>+10.2f}')

# === 4. 检查 Tushare 数据是否有异常 ===
print()
print('=' * 60)
print('Tushare 数据异常检查（|净额| > 100亿的板块）')
print('=' * 60)
big = sorted(our_sectors, key=lambda s: abs(float(s.net_flow or 0)), reverse=True)[:15]
for s in big:
    nf = float(s.net_flow or 0)
    mi = float(s.money_inflow or 0)
    mo = float(s.money_outflow or 0)
    print(f'  {s.sector}: net_flow={nf/10000:.2f}亿, inflow={mi/10000:.2f}亿, outflow={mo/10000:.2f}亿, rise={float(s.rise_ratio or 0):.2f}%')

db.close()
