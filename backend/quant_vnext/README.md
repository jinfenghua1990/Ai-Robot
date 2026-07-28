# quant_vnext

全新、独立的 A 股右侧多因子选股核心。该目录不依赖旧版 `strategies/`、`analyzers/` 或 `services/strategy_runner.py`。

## 当前闭环

```text
历史 K 线
  -> 日期门禁
  -> Factor Engine
  -> 横截面百分位标准化
  -> 维度评分
  -> 独立证据共振
  -> 生命周期
  -> 交易状态
  -> SignalSnapshot
```

## 运行测试

```bash
cd /Users/gino/Projects/AIROBOT/backend
python3 -m pytest -q quant_vnext/tests
python3 -m compileall -q quant_vnext
```

## 使用方式

```python
from datetime import date
from quant_vnext.contracts import MarketContext
from quant_vnext.pipeline import QuantPipeline

pipeline = QuantPipeline()
snapshots = pipeline.run(history, date(2026, 3, 21), MarketContext(
    trade_date=date(2026, 3, 21),
    breadth=0.55,
))
```

## 设计约束

- 所有因子必须先注册，不能在策略函数中临时创造评分。
- 因子缺失输出 `valid=False`，不再用 50 分伪装成中性数据。
- `risk` 分数越高代表风险越可接受；风险不足时交易状态为 `INVALID`。
- 共振至少 4 个维度，同时要求趋势确认、强度/板块确认和风险确认。
- 生命周期和交易状态分离；`主升` 不自动等于可以买入。
- 因子值、验证结果、共振快照和信号结果使用独立表结构。

## 尚未接入旧 9000 API

当前版本已增加只读路由 `GET /api/vnext/snapshots`，但当前正在运行的 9000 进程需要重启后才会加载该路由。它只读取 `stock_daily_kline`，不会写入旧表，也不会替换旧选股入口。

```bash
curl 'http://localhost:9000/api/vnext/snapshots?limit=20'
```

下一步是接入离线数据库写入、历史滚动验证和前端独立页面，最后才切换前端入口。
