# AIROBOT 外部量化研究参考

这些仓库只作为研究、对照和测试参考，不会自动加入生产运行路径，也不会覆盖现有 `backend/quant_vnext`。

| 仓库 | 本地目录 | 用途 | 当前处理 |
|---|---|---|---|
| Microsoft Qlib | `qlib/` | Alpha158/Alpha360、因子研究、IC/Rank IC、组合回测 | 优先研究 |
| AKShare | `akshare/` | A 股行情、财务和公开数据接口 | 本地已有 Python 包，源码用于核对 |
| RiceQuant RQAlpha | `rqalpha/` | 日线回测、撮合、组合与交易状态验证 | 作为回测参考 |
| ZVT | `zvt/` | 数据—因子—信号—回测—可视化架构参考 | 只参考架构 |
| VeighNa VN.PY | `vnpy/` | 交易执行和实盘接口参考 | 当前网络下载不稳定，暂未完整落地 |

## 与本地系统的对应关系

- 本地已有 `backend/quant_vnext`：继续作为生产选股核心。
- 本地已有 `AKShare`、`Tushare`：继续作为数据源，不重复安装。
- Qlib：只吸收因子定义、研究流程和 Alpha158 思路，不直接替换本地数据库。
- RQAlpha：只用于独立回测校验，避免把回测假设混入实时选股。
- ZVT：参考模块边界，不整体迁移。
- VN.PY：等需要接入券商/模拟交易执行时再单独处理。

## 研究顺序

1. 先对照 Qlib Alpha158 因子定义。
2. 将因子接入本地 `factor_registry`，保留数据日期和有效性标记。
3. 用本地 A 股历史数据计算 IC、Rank IC、相关性和滚动收益。
4. 用独立回测验证交易成本、涨跌停、停牌和 T+1 约束。
5. 只有样本外有效的因子，才允许进入生产评分。

## 多市场扩展

| 仓库 | 本地目录 | 适用市场 | 当前处理 |
|---|---|---|---|
| Ashare | `Ashare/` | A 股备用行情 | 已下载并核对调用方式 |
| yfinance | `yfinance/` | 港股、美股及 Yahoo Finance 支持的代码 | 已下载，并成功读取 `0700.HK`、`AAPL` 日线 |
| vectorbt | `vectorbt/` | 多资产研究和组合回测 | 已下载，暂不进入生产 |
| WonderTrader | `wondertrader/` | A 股组合回测和交易参考 | 当前网络下 Git 克隆不完整，暂不导入 |

当前市场路由建议：

- A 股：继续使用 AKShare/Tushare/Qlib，Ashare 作为备用行情源。
- 港股、美股：使用 yfinance 进入统一 OHLCV 数据格式。
- 研究回测：将统一数据交给 vectorbt，并补充手续费、汇率、时区和交易日历规则。
- 实盘执行：与行情和研究模块分离，先纸面交易，再接入券商接口。

港美股生产接入已落在 `backend/market_quant/`，外部仓库仍只提供定义、测试和回测语义参考：

- `market_instruments` / `market_universe_memberships`：统一标的和每日股票池成员快照。
- `market_daily_bars`：只接收真实 OHLCV；合成数据不会进入统一生产层。
- `market_factor_values` / `market_resonance_snapshots`：七维因子、共振和交易状态快照。
- `market_research_records`：市场感知妙想研究原文与结构化结果。

仓库地址、固定 commit、许可证和生产禁用状态见 `research/external/manifest.json`。

已完成的最小读取验证：

```text
0700.HK: 5 daily bars, latest close 447.20
AAPL:    5 daily bars, latest close 339.75
```

Yahoo Finance 数据仅作为研究和展示数据源，不当作保证实时或保证完整的交易行情。

统一适配器位于 `research/market_sources/yahoo_adapter.py`，负责港股代码补全（例如 `700` → `0700.HK`）和 Yahoo 多层列名转换。当前已用真实数据验证 `0700.HK` 与 `AAPL`。
