# Qlib Alpha158 本地映射

本目录把 Qlib 官方 `Alpha158DL` 中适合右侧交易研究的代表性因子登记为本地 `FactorDefinition`。来源代码位于 `research/external/qlib/qlib/contrib/data/loader.py`。

当前登记的 13 个候选覆盖动量、趋势、位置、波动和量价五类：ROC、MA gap、Slope/BETA、RSQR、RSV、STD、CORR、CNTD、SUMP、VMA、VSTD、WVMA。

这些因子全部位于 `backend/quant_vnext/alpha158_catalog.py`，状态固定为：

- `source=qlib_alpha158`
- `validity=research`
- `production=false`

因此它们不会进入 `default_registry().production()`，也不会改变当前实时评分、共振或交易状态。接口 `/api/vnext/research/alpha158` 仅用于查看研究候选。

## 采用规则

1. 只登记由当前及历史 K 线计算的表达式；拒绝 Alpha158 标签中的负向 `Ref` 未来数据。
2. 保留与右侧交易直接相关的趋势斜率、趋势线性度、位置、量价相关性和波动因子。
3. 暂不把板块、资金流、涨跌停和 ST 过滤伪装成 Alpha158 因子；这些继续由本地 A 股数据层单独负责。
4. 进入生产前必须通过滚动 IC、Rank IC、相关性、样本外收益和回撤检查，并由人工确认因子方向。

## 下一步

使用 `/api/vnext/research/alpha158` 检查目录，使用 `/api/vnext/research/alpha158/validate?days=20&limit=50&horizon=5` 运行真实历史验证；验证通过后逐个提升为生产因子，不做整批启用。

验证接口返回每个候选的 `ic`、`rank_ic`、`mean_forward_return` 和 `sample_count`。它只读数据库，不写生产信号，也不会改变当前总览和选股结果。

## 本地生产 V1 与研究候选的边界

当前生产引擎已经统一为 7 个因子组：

`market`、`sector`、`strength`、`trend`、`volume_price`、`position`、`risk`。

本地日线可真实计算的 33 个 V1 因子由 `backend/quant_vnext/registry.py` 注册，并由 `backend/quant_vnext/engine.py` 计算。Qlib Alpha158 的 13 个候选仍保留在独立研究目录，不会因为下载源码就自动进入生产。

市场环境现在有两个角色：

1. 作为 `market` 因子组参与综合评分。
2. 由 `MarketRegimeEngine` 输出 `STRONG`、`RANGE`、`WEAK`，动态调整趋势、强度、量价、位置和风险惩罚权重。

因此市场页面的数据不再只是展示；它会影响排序权重和 `NO_CHASE`/新开仓限制。
