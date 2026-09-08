# AIROBOT 9000 端口全面架构审计报告 v2

> 2026-07-10 | 涵盖：数据库、调度器、前端、进程资源四维深度分析

---

## 1. 数据库层

### 1.1 表规模 TOP 10

| 表 | 行数 | 大小 | 列数 | 索引 | 问题 |
|----|------|------|------|------|------|
| `realtime_stock_flow` | 157万 | **434 MB** | 19 | 8 | 日均34万行写入，无清理策略 |
| `stock_flow` | 60万 | **142 MB** | 15 | 7 | 慢查询重灾区(见下) |
| `stock_realtime_tick` | 21万 | 55 MB | 14 | 3 | 每5秒写入，无清理 |
| `stock_adj_factor` | 131万 | 126 MB | 5 | **1(仅主键)** | 🔴 131万行无任何业务索引 |
| `leader_lifecycle` | — | 98 MB | — | — | 批量更新942ms |
| `stock_margin_data` | 14万 | 21 MB | 12 | **1(仅主键)** | 🔴 融资融券表无索引 |
| `stock_money_flow_detail` | 2.6万 | 14 MB | 22 | 4 | 正常 |
| `ai_analysis_cache` | 239 | — | 7 | — | INSERT 慢(374ms) |

**总容量: 944 MB | 50 张表 | 日均写入 ~55万行**

### 1.2 慢查询分析

| 查询 | 耗时 | 问题 |
|------|------|------|
| `SELECT sector FROM stock_flow WHERE ts_code LIKE '%005247.SZ%'` | **2970ms** | `LIKE '%code%'` 无法用B-tree，602K全表扫描 |
| `UPDATE leader_lifecycle SET change_rate=...` | 942ms | 批量更新无优化 |
| 板块聚合 `sum(main_force_inflow)` | 640ms | 无板块预聚合表 |
| `INSERT stock_news_search` | 331ms | 写IO瓶颈 |

**3个致命慢查询，全在 `stock_flow` 表上做 `LIKE '%xxx%'` 扫描**。

### 1.3 资金流四表并存

| 表 | 内容 | 是否冗余 |
|----|------|---------|
| `realtime_stock_flow` | 盘中1分钟级全市场资金流(多源验证) | ✅ 主力表 |
| `stock_money_flow_realtime` | 盘中资金流(emdatah5单源) | ❌ 与前者重复90% |
| `stock_flow` | 盘后汇总资金流(每日一行) | ✅ EOD归档 |
| `stock_money_flow_detail` | 盘后4档资金流(特大/大/小/散) | ✅ 独立维度 |

👉 **`stock_money_flow_realtime` 是唯一冗余表，应废弃**。

---

## 2. 调度器层

### 2.1 盘中并发任务（9:00-11:30, 13:00-15:00）

```
同一时刻最多 8 个任务并发：

每 1 分钟 ── realtime_snapshot       全市场5500只batch+多源验证  ⚡高负载
每 2 分钟 ── emdatah5_fund_flow       114只自选股逐股请求        ⚡中负载
每 5 秒   ── realtime_aggregator      全市场Tick+盘口采集         ⚡高负载
每 5 分钟 ── money_flow_concept       概念板块资金流
每 5 分钟 ── money_flow_industry      行业板块资金流
每 5 分钟 ── watchlist_sync           自选股同步
每 5 分钟 ── auto_trade              自动交易
每10 分钟 ── refresh_caches           缓存刷新
```

**问题**：
- `realtime_snapshot`(每分钟) 已经**包含**了 `emdatah5_fund_flow` 的功能——都从东财拿数据，都是资金流
- `realtime_snapshot` 在每1分钟跑，`emdatah5` 在每2分钟跑。部分分钟它们同时触发达 3-4 个CPU密集任务

### 2.2 任务重叠

| 重叠对 | 说明 |
|--------|------|
| **emdatah5 ↔ realtime_snapshot** | 都在拉东财资金流，emdatah5可以废弃 |
| **realtime_aggregator 5s ↔ realtime_snapshot 1m** | 都在拉实时数据，一个冲量一个冲价 |
| **auto_trade 多时段** | 9-14每5分 + 11:00-30密集 + 13-14每5分 → 3个同名任务 |

---

## 3. 前端层

### 3.1 构建产物

| 前端 | 大小 | 文件数 |
|------|------|--------|
| 主前端 | 2.2 MB | ~80 JS chunks |
| DSA前端 | 5.3 MB | 独立SPA |
| Hermes前端 | 1.2 MB | 纯静态(后端已停) |
| Vibe前端 | 684 KB | 独立SPA |
| **合计** | **9.4 MB** | **4套独立构建** |

### 3.2 最大Chunk

- `echarts-vendor`：**1.06 MB** — 只用在大盘热力图/概念板块
- `charts-vendor`：171 KB — 重复的 Chart.js（DSA里也有）
- `react-vendor`：165 KB — 主前端一份、DSA一份、Vibe一份（重复3次）

👉 **3个前端各自打包react/chart.js，浏览器加载DSA页面时重复下载 ~400KB**

---

## 4. 进程与资源层

### 4.1 运行中进程

| 进程 | 端口 | 内存(RSS) | CPU% | 用途 |
|------|------|-----------|------|------|
| 主后端 uvicorn | 9000 | 23.5 MB | 1.0% | FastAPI + 所有API |
| DSA 后端 | 8000 | 9.3 MB | 0% | AI分析子进程 |
| LiteLLM 网关 | 8001 | 8.7 MB | 0.3% | LLM代理 |
| Node/Vite | — | 25.6 MB | 0.9% | 前端dev server |
| Hermes Agent | — | 13.6 MB | 0.1% | 闲置的hermes子进程 |

**总非必要开销：DSA(9MB) + Hermes Agent(14MB) + LiteLLM(9MB) = ~32MB 可回收**

### 4.2 冗余子进程识别

- **Hermes Agent (PID 66538, 13.6MB)**：位于 `.hermes/hermes-agent/venv/bin/python`，独立运行。根据代码注释"后端API已停用"，**应完全关闭**。
- **LiteLLM**(PID 70322, 8.7MB)：被DSA使用，**如果DSA合并入主后端可以省掉**。

---

## 5. 顶层优化路线图

### 第1批：立刻做（周三前，1-2天）

| # | 优化 | 改动量 | 效果 |
|---|------|--------|------|
| 1 | **废弃 `stock_money_flow_realtime`** | 改5处：删除 emdatah5 cron、改 SSE读源、改 core.py 三个API、删表 | 省 5MB 表 + 每2分钟的冗余任务 |
| 2 | **`stock_flow` 加 `ts_code` 函数索引** | 1行SQL: `CREATE INDEX ON stock_flow(ts_code varchar_pattern_ops)` | `LIKE '%xxx.SZ%'` 从 2970ms → ~5ms |
| 3 | **`stock_adj_factor` 加索引** | 1行SQL: `CREATE INDEX ON stock_adj_factor(trade_date, ts_code)` | 131万行查询从全表扫描 → 索引查找 |
| 4 | **妙想 API 加 30s TTL缓存** | `trading.py` 加 `cachetools.TTLCache` | 消除交易模块挂死 |
| 5 | **DB清理策略：30天快照** | scheduler 加一个 `DELETE` cron | 每月释放 ~400MB |

### 第2批：本周做（周四前）

| # | 优化 | 改动量 | 效果 |
|---|------|--------|------|
| 6 | **删除 Hermes 前端 + 关闭 Hermes Agent** | 删目录、删路由、kill进程 | 省 15MB 内存 + 1.2MB 磁盘 |
| 7 | **emdatah5 `batch_save_realtime` 废弃** | 删除函数+import、移除cron | 省每2分钟114次HTTP请求 |
| 8 | **Vibe 数据加 N分钟 TTL缓存** | 在 `api/vibe/__init__.py` 加 `lru_cache` 装饰器 | 省90%重复请求 |
| 9 | **stock_flow 概念板块聚合预计算** | 新增 `concept_aggregation_cache` 表 + 定时任务 | 板块页加载从 640ms → 5ms |

### 第3批：以后做

| # | 优化 | 改动量 | 效果 |
|---|------|--------|------|
| 10 | DSA 合并入主后端 | 移植路由+依赖 | 省 9MB进程 + 消除死锁风险 |
| 11 | 三前端统一构建 | DSA+Vibe页面移入主前端 | 省 ~400KB重复下载 |
| 12 | 合并 LiteLLM | LLM 能力集成进主后端 | 省 9MB进程 |
