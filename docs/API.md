# AIROBOT API 文档

**后端地址**：`http://localhost:9000`
**端点数**：131 个
**生成时间**：2026-07-03

---

## 1. 健康检查

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/health` | 健康检查 |

---

## 2. 自选股 Watchlist (16 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/watchlist/` | 列出自选股 |
| GET | `/api/watchlist/sync/status` | 同步状态 |
| GET | `/api/watchlist/groups` | 分组列表 |
| POST | `/api/watchlist/add` | 添加 |
| POST | `/api/watchlist/remove` | 删除 |
| POST | `/api/watchlist/quality` | 更新质量状态 |
| POST | `/api/watchlist/group/add` | 加分组 |
| POST | `/api/watchlist/group/rename` | 改分组 |
| POST | `/api/watchlist/group/delete` | 删分组 |
| POST | `/api/watchlist/sync/pull` | 从云端拉取 |
| POST | `/api/watchlist/sync/push` | 推到云端 |
| POST | `/api/watchlist/sync/clear` | 清空 |
| ... | | |

---

## 3. 模拟盘 Trading (14 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/trading/signals` | 模拟盘信号列表 |
| GET | `/api/trading/balance` | 账户余额 |
| GET | `/api/trading/positions` | 持仓 |
| GET | `/api/trading/orders` | 委托 |
| GET | `/api/trading/history/{date}` | 某日历史 |
| POST | `/api/trading/buy` | 买入 |
| POST | `/api/trading/sell` | 卖出 |
| POST | `/api/trading/cancel/{id}` | 撤单 |
| GET | `/api/trading/bs-signals` | BS 信号 |
| ... | | |

---

## 4. 妙想 MX (7 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/mx/balance` | 妙想账户余额 |
| GET | `/api/mx/positions` | 妙想持仓 |
| GET | `/api/mx/orders` | 妙想委托 |
| POST | `/api/mx/buy` | 妙想买入 |
| POST | `/api/mx/sell` | 妙想卖出 |
| GET | `/api/mx/skills` | 可用 skill 列表 |
| ... | | |

---

## 5. 妙想模拟盘自动化 Mx-Trading (7 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/mx-trading/balance` | 自动化账户余额 |
| GET | `/api/mx-trading/positions` | 自动化持仓 |
| GET | `/api/mx-trading/logs` | 自动化日志 |
| GET | `/api/mx-trading/config` | 自动化配置 |
| POST | `/api/mx-trading/config` | 更新配置 |
| POST | `/api/mx-trading/run` | 手动执行 |
| ... | | |

---

## 6. 自动交易 Auto-Trade (5 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/auto-trade/config` | 配置 |
| POST | `/api/auto-trade/config` | 更新配置 |
| GET | `/api/auto-trade/logs` | 日志 |
| POST | `/api/auto-trade/run` | 手动执行 |
| POST | `/api/auto-trade/cycle` | 单次循环 |

---

## 7. BS 策略 Bs-Screener (10 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/bs-screener/strategies` | 策略列表 |
| GET | `/api/bs-screener/today` | 今日扫描 |
| GET | `/api/bs-screener/strategy-picks` | **保留策略今日命中** |
| GET | `/api/bs-screener/backtest` | 回测列表 |
| POST | `/api/bs-screener/backtest/run` | 运行回测 |
| POST | `/api/bs-screener/scan/run` | 手动扫描 |
| ... | | |

---

## 8. 生命周期 Lifecycle (4 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/lifecycle/` | V1 生命周期 |
| GET | `/api/lifecycle-v2/` | V2 |
| GET | `/api/lifecycle-v3/` | V3 |
| GET | `/api/lifecycle-v4/` | V4 |

---

## 9. 龙头体系 Leader (4 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/leader/system` | 龙头系统 |
| GET | `/api/leader/history` | 龙头历史 |
| GET | `/api/leader/lifecycle` | 龙头生命周期 |
| GET | `/api/leader/stage` | 阶段判定 |

---

## 10. 重点关注 Focus-Stocks (4 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/focus-stocks/` | 列表 |
| POST | `/api/focus-stocks/add` | 添加 |
| POST | `/api/focus-stocks/remove` | 删除 |
| POST | `/api/focus-stocks/refresh` | 刷新 |

---

## 11. AI 分析 (3 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/ai/{review_id}` | 获取分析 |
| POST | `/api/ai/analyze` | 触发分析 |
| GET | `/api/ai/cache` | 缓存列表 |

---

## 12. 板块/概念/资金流 (10 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/concept-sector-flow-rank` | 概念板块资金流排行 |
| GET | `/api/concept-sector-flow-trend` | 概念板块趋势 |
| GET | `/api/concept-sector-hot` | 概念板块热度 |
| GET | `/api/sector-flow-rank` | 板块资金流排行 |
| GET | `/api/sector-flow-trend` | 板块趋势 |
| GET | `/api/heatmap` | 热力图 |
| GET | `/api/rotation` | 轮动 |
| GET | `/api/money-flow` | 资金流 |
| GET | `/api/panorama` | 全景 |
| GET | `/api/market-state` | 市场状态 |

---

## 13. 同步 Sync (11 endpoints)

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/sync/mx/pull` | 妙想拉取 |
| POST | `/api/sync/mx/push` | 妙想推送 |
| POST | `/api/sync/mx/mirror` | 妙想镜像 |
| POST | `/api/sync/ths/pull` | 同花顺拉取 |
| POST | `/api/sync/ths/push` | 同花顺推送 |
| POST | `/api/sync/ths/mirror` | 同花顺镜像 |
| POST | `/api/sync/sina/pull` | 新浪拉取 |
| POST | `/api/sync/sina/push` | 新浪推送 |
| POST | `/api/sync/sina/mirror` | 新浪镜像 |
| GET | `/api/sync/status` | 同步状态 |
| POST | `/api/sync/all` | 全部同步 |

---

## 14. 数据查询/研究 (5 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/stock/research` | 个股研究 |
| GET | `/api/stock/strategies` | 个股策略 |
| GET | `/api/strategy-health` | 策略健康度 |
| POST | `/api/strategy-scan` | 触发扫描 |
| GET | `/api/screener` | 智能选股 |

---

## 15. 投资组合 / 实时 (4 endpoints)

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/portfolio/` | 投资组合 |
| GET | `/api/realtime/quote` | 实时行情 |
| GET | `/api/realtime/snapshot` | 实时快照 |
| GET | `/api/realtime/refresh` | 手动刷新 |

---

## 16. 数据回填/白虎/杂项 (10 endpoints)

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/backfill/` | 数据回填 |
| POST | `/api/baihu-screen` | 白虎V3.0 选股 |
| POST | `/api/stock-strategies` | 个股多策略 |
| GET | `/api/misc/config` | 配置查询 |
| POST | `/api/misc/config` | 配置更新 |
| ... | | |

---

## 17. 关键响应格式

### 17.1 自选股 signal

```json
{
  "secCode": "600519",
  "secName": "贵州茅台",
  "sector": "白酒",
  "signal": "B",
  "signalLabel": "B点",
  "signalColor": "#22c55e",
  "riskLevel": "低",
  "score": 85,
  "reasons": ["MA20 上行", "MACD 金叉"],
  "positiveFactors": [...],
  "negativeFactors": [...],
  "sectorTrend": {...},
  "position": {...},
  "marketState": {...},
  "buyPower": {...},
  "qualityStatus": "优质",
  "quote": {...},
  "bsSignal": {...}
}
```

### 17.2 持仓 position

```json
{
  "code": "600519",
  "name": "贵州茅台",
  "count": 100,
  "available": 100,
  "cost": 1500.00,
  "price": 1680.00,
  "marketValue": 168000.00,
  "profit": 18000.00,
  "profitPct": 12.00
}
```

### 17.3 策略命中 picks

```json
{
  "date": "2026-07-02",
  "picks": [
    {
      "code": "688698",
      "name": "伟创电气",
      "sector": "电气设备",
      "strategy": "BS-科创-V7",
      "dimension": "star",
      "signal": "B",
      "reasons": [...]
    }
  ],
  "code_to_strategies": {"688698": ["BS-科创-V7"]},
  "summary": {"BS-科创-V7": 27, "BS-创业-V9": 23}
}
```

---

## 18. 错误码

| 状态码 | 含义 |
|---|---|
| 200 | 成功 |
| 400 | 参数错误 |
| 401 | 未授权 |
| 404 | 不存在 |
| 500 | 服务器错误 |
| 502 | 上游数据源错误 |

---

## 19. 调用规范

- 全部使用 GET/POST，PUT/DELETE 几乎不用
- Query 参数：snake_case 或 camelCase（混合，建议前端用前端规范）
- 时间：YYYY-MM-DD 字符串
- 股票代码：6位字符串（无后缀）或 ts_code（带后缀）
- 错误响应：FastAPI 标准 `{"detail": "..."}`
