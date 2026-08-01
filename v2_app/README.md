# Ai-Robot V2 右侧多因子决策系统

这是一个独立的新程序。原 Ai-Robot 继续作为 9000 端口运行；V2 使用 9001 端口，只读接入原 PostgreSQL 的真实日线、股票元数据和板块资金表，并在自己的 `v2_*` 表中保存因子、信号、验证和交易审计。

## 启动

在仓库根目录执行：

```bash
cd /Users/gino/Projects/AIROBOT
PYTHONPATH=. python3 -m uvicorn v2_app.main:app --host 0.0.0.0 --port 9001
```

浏览器分别打开：原系统 `http://本机IP:9000/`，新 V2 `http://本机IP:9001/`。

当前机器的 LaunchAgent 配置为：

- `~/Library/LaunchAgents/com.airobot.autostart.plist` → 原系统 `http://192.168.3.199:9000/`
- `v2_app/com.airobot.v2.plist` → 新 V2 `http://192.168.3.199:9001/`
- `v2_app/com.airobot.v2-9000.plist` → 已停止，不要再加载，避免覆盖原 9000。

旧数据库和旧页面均保留。本轮只修复了旧验证接口的启动语法，并扩大 `stock_daily_kline.pct_chg` 精度以容纳真实新股涨跌幅，没有改旧策略公式。

查看/停止/恢复新服务：

```bash
launchctl print gui/$(id -u)/com.airobot.v2
launchctl bootout gui/$(id -u)/com.airobot.v2
launchctl bootstrap gui/$(id -u) /Users/gino/Projects/AIROBOT/v2_app/com.airobot.v2.plist
```

如需临时停止 V2、保留原系统 9000：

```bash
launchctl bootout gui/$(id -u)/com.airobot.v2
launchctl bootstrap gui/$(id -u) /Users/gino/Library/LaunchAgents/com.airobot.autostart.plist
```

验证两个端口：

```bash
curl http://127.0.0.1:9000/api/health
curl http://127.0.0.1:9001/api/v2/health
```

全市场首次计算或持久化快照可能需要十秒左右；完成后会使用内存缓存，持久化结果写入独立的 `v2_*` 表。日常总览只计算当前参与研究评分的因子；候选 Alpha158 公式在因子验证任务中按需计算，避免候选库拖慢实时页面。

## 推荐使用顺序

1. **总览**：先看市场环境。`WEAK / 偏弱` 时，个股高分也只能 `NO_CHASE / 禁止追高`。
2. **选股中心**：筛选至少 4 个机会维度共振的股票，查看七维分数和失败原因。
3. **个股分析**：确认趋势、板块、强度、量价、位置和风险，而不是只看因子综合分。
4. **量化动作**：只有 `TRIGGERED / 已触发` 才进入买入预览；`READY` 仍是准备状态。
5. **持仓与交易**：每只持仓会结合 V2 信号、生命周期、风险闸门和止损/止盈线显示“继续持有”或“卖出复核”。点击“预览卖出”只生成解释，不会发订单。
6. **因子验证**：运行 IC、Rank IC、ICIR、分层收益、缺失率、异常值、市场状态和1/3/5/10/20日前瞻收益；短窗口只积累观察样本。
7. **系统状态**：查看候选/观察/生产/停用/淘汰状态、数据表来源、ST过滤和交易保护状态。

## 交易保护

V2 默认关闭外部下单：

- `V2_TRADING_ENABLED=false`
- 数据库 `v2_trade_config.enabled=false`
- 需要 `V2_ACTION_KEY`
- 请求必须明确 `confirm=true`

四项条件没有同时满足时，只能研究和预览。V2 不会因为一个形态标签或旧策略命中数自动买卖。

## 数据与验证

生产计算使用最近完成的 `stock_daily_kline`，读取 `stock_flow` 的中文名称/行业，并过滤名称以 `ST` 或 `*ST` 开头的股票。当前目录共189个因子：31个现有右侧公式和158个本地映射的 Qlib Alpha158 公式。补充历史后当前已有261个交易日；本次120日验证将其中74个因子放入观察状态、115个保留候选，仍没有因成本调整后收益不足而晋升生产。候选公式可在验证中心按需计算，但不会自动进入当前总分；正式生产还需要样本外稳定性、分层单调性、扣成本收益和覆盖率同时通过。

候选因子来源和映射记录见 `v2_app/alpha158.py`；公式只使用信号日及以前的 OHLCV，不使用未来数据。V2 的表结构在首次启动时自动创建：

因子状态和生产开关分开保存：`status` 表示候选/观察/生产/停用/淘汰生命周期，`allow_production` 才是是否允许进入生产评分的独立准入开关。每次验证还会写入 `future_function` 和 `price_basis`，让未来函数检查与价格口径成为可审计字段。

- `v2_factor_registry`
- `v2_factor_values`
- `v2_signal_snapshots`
- `v2_factor_validation`
- `v2_signal_outcomes`
- `v2_trade_config`
- `v2_trade_audit`

因子验证页的“保存全因子研究值”只把 189 个因子的原始值写入 `v2_factor_values`，不会因为候选因子数量增加就改变评分口径；正式评分仍由生命周期状态决定。
