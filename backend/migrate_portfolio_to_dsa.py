"""
将模拟盘/妙想持仓迁移到 DSA 持仓系统。
1. 创建"模拟盘迁移"账户
2. 根据共享持仓数据创建买仓交易
"""
import json
import sys
import urllib.request
from datetime import date

API_BASE = "http://127.0.0.1:8000/api/v1/portfolio"


def _req(method, path, body=None):
    url = f"{API_BASE}{path}"
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        print(f"  ❌ {method} {path}: {e.code} {e.reason}")
        print(f"     {e.read().decode()[:200]}")
        sys.exit(1)


def main():
    today = date.today().isoformat()

    # 1. 从共享持仓获取现有数据（妙想源）
    print("📥 读取现有共享持仓...")
    with urllib.request.urlopen(
        urllib.request.Request("http://127.0.0.1:9000/api/shared/portfolio"),
        timeout=10,
    ) as resp:
        shared = json.loads(resp.read().decode())

    positions = shared.get("positions", [])
    if not positions:
        print("  ⚠️  没有持仓需要迁移")
        return

    print(f"  发现 {len(positions)} 只持仓，总市值 {shared.get('total_market_value', 0):,.2f}")

    # 2. 创建账户
    print("\n📁 创建 DSA 账户: 模拟盘迁移...")
    account = _req("POST", "/accounts", {
        "name": "模拟盘迁移",
        "broker": "manual",
        "market": "cn",
        "base_currency": "CNY",
    })
    account_id = account["id"]
    print(f"  ✅ 账户创建成功: id={account_id}, name={account['name']}")

    # 3. 为每只持仓创建买仓交易
    total_cost = 0.0
    print(f"\n📝 创建买仓交易 ({len(positions)} 笔)...")
    for i, pos in enumerate(positions, 1):
        symbol = pos["symbol"]
        name = pos.get("name", "")
        qty = int(pos["quantity"])
        avg_cost = pos["avg_cost"]
        cost = qty * avg_cost
        total_cost += cost

        trade = _req("POST", "/trades", {
            "account_id": account_id,
            "symbol": symbol,
            "trade_date": today,
            "side": "buy",
            "quantity": qty,
            "price": round(avg_cost, 3),
            "fee": 0.0,
            "market": "cn",
            "currency": "CNY",
            "note": f"从模拟盘迁移 (成本 {avg_cost})",
        })
        trade_id = trade["id"]
        print(f"  [{i}/{len(positions)}] {name}({symbol}) {qty}股 @ {avg_cost} → trade_id={trade_id}")

    # 4. 验证快照
    print("\n📊 验证 DSA 持仓快照...")
    with urllib.request.urlopen(
        urllib.request.Request(
            f"http://127.0.0.1:8000/api/v1/portfolio/snapshot?include_realtime=true"
        ),
        timeout=10,
    ) as resp:
        snapshot = json.loads(resp.read().decode())

    accounts = snapshot.get("accounts", [])
    pos_count = sum(len(a.get("positions", [])) for a in accounts)
    mv = snapshot.get("total_market_value", 0)
    print(f"  ✅ DSA 账户数: {snapshot.get('account_count', 0)}")
    print(f"  ✅ 总持仓数: {pos_count}")
    print(f"  ✅ 总市值: {mv:,.2f}")
    print(f"  总投入成本: {total_cost:,.2f}")

    # 5. 验证共享接口是否也能拉到
    print("\n🔄 验证 /api/shared/portfolio 同步...")
    # 触发刷新
    req = urllib.request.Request(
        "http://127.0.0.1:9000/api/shared/portfolio/refresh",
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            refresh_result = json.loads(resp.read().decode())
            print(f"  ✅ 刷新结果: {refresh_result.get('message', 'ok')}")
    except Exception as e:
        print(f"  ⚠️  刷新失败 (共享缓存尚待改造): {e}")

    # 拉取最新共享数据
    with urllib.request.urlopen(
        urllib.request.Request("http://127.0.0.1:9000/api/shared/portfolio"),
        timeout=10,
    ) as resp:
        new_shared = json.loads(resp.read().decode())
    new_mv = new_shared.get("total_market_value", 0)
    new_count = new_shared.get("count", 0)
    print(f"  📊 共享持仓: {new_count} 只, 市值 {new_mv:,.2f}")
    sources = set(p.get("source", "?") for p in new_shared.get("positions", []))
    print(f"  📦 数据源: {sources}")

    print("\n🎉 迁移完成！")


if __name__ == "__main__":
    main()
