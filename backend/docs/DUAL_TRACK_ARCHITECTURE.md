# 双轨制数据中转层架构（盘后静态 + 盘中实时）

> 适用于 AIROBOT 项目所有"全聚合单页面"场景，包括 StockDetailPage、未来 SuperPanel 大屏等。

## 一、设计目标

1. **盘后静态数据**（游资底牌 / 板块热力 / 7 天生命周期 / 概念成分）→ 入库 PostgreSQL，前端打开页面时一次性读取
2. **盘中实时数据**（现价 / 大单主动率 / 千单频次 / 分时承接）→ 内存中转（Redis 或 in-process dict），3 秒/次轮询，前端定时器局部刷新
3. **单次聚合** → FastAPI `/api/v1/stock/super_panel` 一次性把两部分组装成 JSON 输出，前端只读不拼
4. **降级保护** → 中转层崩了时，前端自动降级只显示盘后静态部分，不卡不死

## 二、数据流（双轨制）

```
                       ┌───── 盘后 17:00 ─────┐
                       │                       │
[Tushare / AkShare] ──▶│  PostgreSQL 中转层   │──▶ 前端 (一次性加载)
                       │  (持久化历史)        │
                       └───────────────────────┘

                       ┌───── 盘中 09:30-15:00 ─────┐
                       │                                │
[iTick / mootdx] ──▶  │  In-Memory/Redis 中转层    │──▶ 前端 (3秒轮询)
                       │  (实时态,进程重启可丢)        │
                       └────────────────────────────────┘
```

## 三、表结构

### 3.1 盘后静态表（已有/扩展）

| 表名 | 用途 | 关键字段 |
|---|---|---|
| `stock_daily_kline` | 个股日 K 线（Tushare daily 同步） | ts_code, trade_date, open/high/low/close, pct_chg, volume, amount |
| `yuzi_seat_daily` | 游资席位每日龙虎榜 | trade_date, ts_code, seat_name, side, net_amount, turnover_rate |
| `yuzi_quant_signals` | 每日量化共振信号 | trade_date, ts_code, quant_score, boss_list, resonance_count |
| `yuzi_lifecycle_tracker` | 20 天生命周期跟踪 | trigger_date, ts_code, lifecycle_data(JSON), final_outcome, net_return_20d |
| `stock_flow` | 个股每日资金流（盘后聚合） | trade_date, ts_code, net_inflow, main_force_inflow, price_chg |
| `concept_sectors` / `concept_sector_flow` | 概念板块定义/资金流 | name, stocks, money_inflow, net_flow, heat_score |
| `sector_flow` | 行业板块资金流 | trade_date, sector, money_inflow, net_flow, limit_up_count |

### 3.2 盘中实时表（新增）

#### 3.2.1 `stock_realtime_tick`（个股分时 tick 流水）

```sql
CREATE TABLE stock_realtime_tick (
    id BIGSERIAL PRIMARY KEY,
    snapshot_time TIMESTAMP NOT NULL,           -- 精确到秒
    trade_date DATE NOT NULL,
    ts_code VARCHAR(20) NOT NULL,
    price NUMERIC(10, 4),
    volume BIGINT,                              -- 累计成交量(手)
    amount NUMERIC(20, 4),                      -- 累计成交额(元)
    bid_price_1 NUMERIC(10, 4),                 -- 五档盘口买一价
    bid_vol_1 BIGINT,
    ask_price_1 NUMERIC(10, 4),                 -- 五档盘口卖一价
    ask_vol_1 BIGINT,
    turnover_rate NUMERIC(6, 2),                -- 换手率%
    main_force_inflow NUMERIC(20, 4),           -- 主力净流入(元)
    source VARCHAR(20),                         -- itick / tdx / sina
    INDEX (trade_date, ts_code, snapshot_time)
);
```

**数据量评估**：5000 只股 × 240 分钟 × 60/3 = 2400 万条/日 → 启用 7 天 TTL 自动清理

#### 3.2.2 `stock_realtime_orderbook`（盘口快照）

```sql
CREATE TABLE stock_realtime_orderbook (
    id BIGSERIAL PRIMARY KEY,
    snapshot_time TIMESTAMP NOT NULL,
    trade_date DATE NOT NULL,
    ts_code VARCHAR(20) NOT NULL,
    bid_prices NUMERIC(10, 4)[5],               -- 买1~买5
    bid_vols BIGINT[5],
    ask_prices NUMERIC(10, 4)[5],               -- 卖1~卖5
    ask_vols BIGINT[5],
    source VARCHAR(20),
    INDEX (ts_code, trade_date, snapshot_time)
);
```

### 3.3 实时聚合缓存（进程内存 dict，非持久化）

```python
# collectors/realtime_aggregator.py
@dataclass
class RealtimeState:
    ts_code: str
    last_tick: dict
    last_3s_large_buy: int        # 近 3 秒大单买入笔数
    last_3s_large_sell: int       # 近 3 秒大单卖出笔数
    last_3s_active_ratio: float   # 主动买入比 = 买入笔数 / (买入+卖出)
    last_min_thousand_count: int  # 近 1 分钟千手单数
    support_eval: str             # 均线承接评价文本
    snapshot_time: datetime
```

进程级 dict `REALTIME_STATE: Dict[str, RealtimeState]`，3 秒调度器轮询时更新。FastAPI 路由直接读内存，零 DB 压力。

## 四、采集调度（双轨）

### 4.1 盘后调度（每日 17:00）

`scheduler.add_job(sync_daily_kline, 'cron', hour='17', minute='0')` 已有
`scheduler.add_job(sync_yuzi_signals, 'cron', hour='17', minute='30')` 已有
`scheduler.add_job(sync_concept_sector, 'cron', hour='18', minute='0')` 已有

### 4.2 盘中调度（09:30-15:00 每 3 秒）

```python
def _collect_realtime_aggregator():
    """盘中 3 秒轮询:拉取所有 watchlist 股票的 tick+盘口,更新内存聚合"""
    from collectors.realtime_aggregator import REALTIME_STATE, _large_order_detect
    codes = list(get_watchlist_codes())  # 100-500 只
    for code in codes:
        tick = itick_get_tick(code)     # ~50ms/只
        ob = tdx_get_orderbook(code)    # ~80ms/只
        if tick and ob:
            state = REALTIME_STATE.setdefault(code, RealtimeState(code))
            state.last_tick = tick
            _large_order_detect(state, tick, ob)  # 计算大单主动率
```

**频率控制**：批量请求 50 只/批 → 5 批 × 200ms = 1 秒即可覆盖 250 只股

## 五、聚合接口设计

### 5.1 `GET /api/v1/stock/super_panel`

**Query**: `?code={ts_code}`

**Response 格式**：

```json
{
  "ts_code": "001399.SZ",
  "stock_name": "惠科股份",
  "update_time": "2026-07-06 14:23:45",
  "source_health": {
    "static": "ok",            // 盘后静态数据状态
    "realtime": "live",        // 盘中实时数据状态: live/stale/closed
  },
  "post_market_base": {
    "quant_score": 91.5,
    "resonance_count": 5,
    "yesterday_bosses": [
      {"name": "东财拉萨团结一路", "action": "锁仓", "net_buy_mil": 8500},
      {"name": "炒股养家", "action": "新进", "net_buy_mil": 4200}
    ],
    "concept_sector": "OLED",
    "sector_hot_money_count": 4,
    "lifecycle_20d": [                              // 20 个交易日(≈1个月),覆盖完整中期波段
      {"date": "20260702", "stage": "首板涨停", "score": 91},
      {"date": "20260703", "stage": "分歧", "score": null},
      ...                                           // D1 ~ D20 共 20 项
    ]
  },
  "realtime_intraday": {
    "current_price": 38.12,
    "pct_chg": 0.5,
    "turnover_rate": 5.2,
    "large_order_active_ratio": 78.5,
    "thousand_order_count_per_min": 12,
    "support_level_eval": "🟢 均线处有万手托单，支撑极强"
  }
}
```

### 5.2 内部组装逻辑

```python
@router.get("/api/v1/stock/super_panel")
def super_panel(code: str):
    from collectors.realtime_aggregator import REALTIME_STATE
    ts_code = normalize_ts_code(code)
    
    # 1) 盘后静态（DB）
    base = _load_post_market_base(ts_code)        # 1 次 DB 查询
    
    # 2) 盘中实时（内存）
    rt = REALTIME_STATE.get(ts_code)              # 0 次 DB 查询
    realtime = _serialize_realtime(rt) if rt else _stale_realtime_placeholder(ts_code)
    
    # 3) 拼装
    return {
        "ts_code": ts_code,
        "update_time": datetime.now().isoformat(),
        "source_health": {"static": "ok", "realtime": "live" if rt else "stale"},
        "post_market_base": base,
        "realtime_intraday": realtime,
    }
```

## 六、前端策略

### 6.1 局部刷新模式

```jsx
function SuperPanel({ code }) {
  const { data, isLoading } = useSWR(`/api/v1/stock/super_panel?code=${code}`, fetcher, {
    refreshInterval: 0,           // 静态部分只拉 1 次
    revalidateOnFocus: false,
  });
  
  // 实时部分单独 3 秒拉
  const { data: rt } = useSWR(`/api/v1/stock/super_panel?code=${code}&section=realtime`, fetcher, {
    refreshInterval: 3000,
  });
  
  return (
    <>
      <StaticSection data={data?.post_market_base} />  {/* 静止 */}
      <RealtimeSection data={rt?.realtime_intraday} />  {/* 3 秒刷新 */}
    </>
  );
}
```

### 6.2 降级显示

```jsx
if (data?.source_health?.realtime === 'closed') {
  return <ClosedMarketNotice />;  // 收盘提示
}
if (data?.source_health?.realtime === 'stale') {
  return <StaleDataBadge time={data.update_time} />;  // 数据陈旧
}
```

## 七、性能与稳定性

| 维度 | 目标 | 实现 |
|---|---|---|
| 单页面加载 | < 500ms | super_panel 聚合后单次返回 |
| 实时刷新间隔 | 3 秒 | 内存 dict，零 DB 压力 |
| 大盘压力（500 只股） | 1 秒内 | 批量 50 只/批，5 批并行 |
| 容错 | 中转层崩不卡前端 | 静态部分从 DB 读，独立于实时聚合 |
| 历史回溯 | 7 天 tick 流水 | stock_realtime_tick 启用 7 天 TTL |

## 八、落地分阶段

| 阶段 | 任务 | 估时 |
|---|---|---|
| ✅ Phase 0 | 架构文档（本文件） | 已完成 |
| Phase 1 | 中转层基础设施：建表 + 大单检测逻辑 + 3 秒调度 | 1-2 天 |
| Phase 2 | 聚合 JSON 接口 `/api/v1/stock/super_panel` | 0.5 天 |
| Phase 3 | StockDetailPage 加"盘中"Tab，3 秒局部刷新 | 0.5 天 |
| Phase 4 | 全聚合 SuperPanel 大屏（独立路由 `/super-panel`） | 1 天（可选） |

## 九、关键文件清单

| 文件 | 作用 |
|---|---|
| `db/models.py` | 新增 `StockRealtimeTick`(20d TTL), `StockRealtimeOrderbook` |
| `collectors/realtime_aggregator.py` | 进程级 dict + 大单检测函数 |
| `collectors/scheduler.py` | 注册 3 秒轮询任务 |
| `api/super_panel/router.py` | `/api/v1/stock/super_panel` 聚合接口 |
| `frontend/src/pages/StockDetailPage.jsx` | 加"盘中"Tab |
| `frontend/src/components/RealtimePanel.jsx` | 大单主动率/千单频次图表 |
