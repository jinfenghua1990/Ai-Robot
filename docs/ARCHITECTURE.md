# AIROBOT 架构文档

**版本**：2026-07-03
**状态**：基线（基于代码体检）

---

## 1. 系统概述

AIROBOT 是一个**A股量化分析 + 模拟盘 + 自动化交易**平台。

- 数据：新浪 / 东方财富 / 同花顺 / TDX / 雪球 / 妙想
- 行情：日内分钟级 + 日级 + 历史K线（最长 800+ 交易日）
- 分析：BS策略（SuperTrend）、生命周期、市场状态、板块热力
- 交易：妙想模拟盘对接（mx-moni skill）+ 自动化引擎

**部署环境**：
- 后端：macOS + Python 3.9 + uvicorn（LaunchAgent 管理）
- DB：PostgreSQL 16
- 前端：macOS + Vite 5 dev server（默认 :5173）/ 生产 build 静态文件
- 反向代理：未使用，端口直连

---

## 2. 系统分层

```
┌─────────────────────────────────────────────────────────────┐
│  Frontend (React 18 + Vite 5)                                │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐           │
│  │ Watchlist   │ │ Trading     │ │ BS-Screener │           │
│  │ Panorama    │ │ Strategy Ctr│ │ Quality     │           │
│  │ LifecycleV4 │ │ StockDetail │ │ Mx-Trading  │           │
│  │ ConceptFlow │ │ Screener    │ │ Focus       │           │
│  └─────────────┘ └─────────────┘ └─────────────┘           │
└──────────────────────────┬──────────────────────────────────┘
                           │ REST API (FastAPI :9000)
┌──────────────────────────▼──────────────────────────────────┐
│  Backend (Python 3.9 + FastAPI + SQLAlchemy 2)               │
│  ┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐                │
│  │  api/  │ │  svc/  │ │analyz/ │ │ collet/│                │
│  │ 33文件 │ │ 6 文件 │ │13 文件 │ │ 8 文件 │                │
│  └───┬────┘ └───┬────┘ └───┬────┘ └────────┘                │
│      └──────────┴──────────┴─────→  db/models.py            │
└──────────────────────────┬──────────────────────────────────┘
                           │ psycopg2 / SQLAlchemy
┌──────────────────────────▼──────────────────────────────────┐
│  PostgreSQL 16 (localhost:5432, db=airobot)                  │
│  32 表 / ≈1.3M 行 / ≈320MB                                  │
└──────────────────────────┬──────────────────────────────────┘
                           │ 多源数据采集
┌──────────────────────────▼──────────────────────────────────┐
│  External Data Sources                                       │
│  新浪 / 东方财富 / 同花顺 / TDX / 雪球 / 妙想                │
└─────────────────────────────────────────────────────────────┘
```

---

## 3. 后端模块

### 3.1 目录结构

```
backend/
├── main.py              # 入口（220 行），挂载 33 个 API router
├── config.py            # 配置（DB / MX_APIKEY / 数据源 URL）
├── api/                 # 33 个 endpoint 文件
│   ├── watchlist.py     # 自选股管理
│   ├── trading.py       # 模拟盘交易
│   ├── bs_screener.py   # BS 策略扫描
│   ├── bs_signals.py    # BS 单股信号
│   ├── bs_backtest.py   # BS 回测
│   ├── auto_trading.py  # 自动化交易配置
│   ├── mx_trading.py    # 妙想模拟盘对接
│   ├── strategy_center.py  # 策略中心
│   ├── quality.py       # 质量评分
│   ├── leader_system.py # 龙头体系
│   ├── lifecycle*.py    # 生命周期 V1/V2/V3/V4
│   ├── concept_sector.py # 概念板块
│   ├── sector_engine.py # 板块引擎
│   ├── panorama.py      # 全景
│   └── ... (其他)
├── services/            # 业务服务（核心业务流）
│   ├── auto_trade_engine.py    # 自动化交易引擎
│   ├── bs_strategy_runner.py   # BS 策略预计算
│   ├── signal_builder.py       # 信号组装
│   ├── watchlist_signal_runner.py  # 自选股日信号
│   ├── leader_history_service.py    # 龙头历史
│   └── strategy_runner.py     # 策略执行
├── analyzers/           # 纯分析（无 FastAPI 依赖）
│   ├── strategy_engine.py    # 策略引擎
│   ├── sector_engine.py      # 板块引擎
│   ├── leader_engine.py      # 龙头引擎
│   ├── lifecycle*.py         # 生命周期
│   ├── market_state.py       # 市场状态
│   ├── buy_power.py          # 购买力评分
│   ├── cross_validator.py    # 多源交叉验证
│   └── ...
├── collectors/          # 数据采集
│   ├── realtime_collector.py
│   ├── tdx_collector.py
│   ├── extended_collectors.py
│   ├── astock_collector.py
│   ├── money_flow_middleman.py
│   └── scheduler.py      # 调度器
├── db/                  # 数据库
│   ├── models.py        # 32 个 ORM 模型
│   ├── connection.py    # 引擎 + SessionLocal
│   └── concept_descriptions.py
├── strategies/          # 策略代码（白虎/青龙）
├── scripts/             # 一次性脚本（数据回填等）
├── skills/              # 妙想 skill 包（gomoku）
└── ...
```

### 3.2 API 端点分组（131 个 endpoint）

| 分组 | 数量 | 前缀 |
|---|---|---|
| 自选股 / 分组 / 同步 | ~25 | `/api/watchlist/*` |
| 模拟盘 / 交易 | ~12 | `/api/trading/*` |
| 妙想模拟盘 / 自动化 | ~15 | `/api/mx-trading/*` |
| BS 策略 / 扫描 / 回测 | ~12 | `/api/bs-screener/*` |
| 生命周期 V1-V4 | ~16 | `/api/lifecycle*` |
| 龙头体系 | ~10 | `/api/leader/*` |
| 质量评分 | ~6 | `/api/quality/*` |
| 板块 / 概念 | ~12 | `/api/concept-sector/*` |
| 数据源同步 | ~12 | `/api/sync/*` |
| 行情 / 实时 | ~6 | `/api/realtime/*` |
| 全景 / 自选股日信号 | ~5 | `/api/panorama/*` |

详见 `docs/API.md`（待写）。

### 3.3 关键业务流程

#### 3.3.1 自动化交易（auto_trade）
```
scheduler 每 5 分钟（9:25-11:30, 13:00-15:00）
  ↓
auto_trade_engine.run_cycle()
  ├─ get_today_signals() ← watchlist_signal_daily
  ├─ filter_quality(quality_status >= 优质)
  ├─ filter_vote(vote_score >= min_vote_score)
  ├─ get_positions() ← 妙想 API
  ├─ decide_sell() → 卖出现有（先卖后买）
  ├─ decide_buy()  → 按 score 排序买入
  ├─ check_risk(single_position_pct, max_positions, max_buy_count)
  └─ place_order() → 妙想 API
        ↓
auto_trade_log 记录决策 + 成交
```

#### 3.3.2 BS 策略扫描
```
scheduler 盘后（16:30-17:00）
  ↓
bs_strategy_runner.precompute_bs_strategies(today)
  ├─ 遍历 bs_backtest_results（保留 2 个：BS-科创-V7, BS-创业-V9）
  ├─ _execute_bs_scan_core(dimension=chinext/star)
  │    ├─ 候选股票池（StockFlow 按主力净流入排序）
  │    ├─ 计算指标（MA/RSI/MACD/KDJ/SuperTrend）
  │    ├─ 过滤（板块 + 技术）
  │    └─ 生成 signals（B/S）
  └─ 存入 bs_daily_scan
        ↓
前端 /api/bs-screener/today?backtest_id=X
        ↓
SignalCard 显示徽章（保留策略命中）
```

#### 3.3.3 自选股日信号
```
scheduler 盘后（17:00-19:00）
  ↓
watchlist_signal_runner.run()
  ├─ 取 watchlist 所有股票
  ├─ 取 stock_flow + sector_flow 当日数据
  ├─ 计算市场状态 (market_state.py)
  ├─ 计算购买力评分 (buy_power.py)
  ├─ 计算生命周期阶段
  └─ 存 watchlist_signal_daily
        ↓
/api/watchlist 读取预计算结果
```

---

## 4. 数据库分层

### 4.1 存储分层

| 层级 | 表 | 保留期 | 清理策略 |
|---|---|---|---|
| **实时数据** | realtime_stock_flow, realtime_money_flow_snapshot, realtime_concept_sector_flow | 30 天 | 定时清理 |
| **日级数据** | stock_flow, sector_flow, concept_sector_flow, watchlist_signal_daily, leader_lifecycle | 6 个月 | 定期归档 |
| **配置** | watchlist, auto_trade_config, bs_backtest_results, bs_strategies | 永久 | 人工管理 |
| **历史** | leader_history, auto_trade_log, strategy_run_log, data_quality_log | 1 年 | 定期清理 |
| **业务** | sim_account, sim_position, sim_order, sim_position_snapshot | 永久 | 永久保留 |

### 4.2 关键表关系

详见 [ER_DIAGRAM.md](./ER_DIAGRAM.md)

---

## 5. 部署架构

### 5.1 启动方式

```bash
# 后端（LaunchAgent 自动启动，plist 路径）
~/Library/LaunchAgents/com.airobot.autostart.plist
# 命令：cd /Users/gino/Projects/AIROBOT/backend
#      /Library/Developer/.../python -m uvicorn main:app --host 0.0.0.0 --port 9000 ...

# 前端（dev 模式）
cd /Users/gino/Projects/AIROBOT/frontend
npm run dev  # 默认 :5173
# 或 build 后用任何静态服务器
npm run build  # dist/

# DB（本地 PostgreSQL）
brew services start postgresql@16
# 启动后清理 postmaster.pid 锁（如进程已死）
```

### 5.2 关键约束（来自 AGENTS.md）

- ✅ Backend 必须通过 LaunchAgent（不用 run.sh 避免端口冲突）
- ✅ PostgreSQL@16 启动前清理 postmaster.pid 锁
- ✅ /mx-tools → /watchlist 重定向（/mx-tools 已废弃）
- ✅ 股票详情走独立路由 `/stock/:code`（不用 modal）
- ✅ Stock 信息搜索记录（包括空结果）必须入库
- ✅ 妙想/同花顺/新浪 mirror=true pull → 全局删除本地多余股票
- ✅ 妙想/同花顺/新浪 mirror=true push → 删除云端多余
- ✅ 每日自动 pull + update stock_features_daily
- ✅ Bearish 用绿色 / Bullish 用红色（包含图表、按钮、标签）
- ✅ WCAG 2.1 AA 颜色对比度
- ✅ 2×2 模块化布局（参考 Watchlist）
- ✅ 全响应式（桌面/平板/手机）
- ✅ 全数据可视化用 line chart（不用 bar）
- ✅ 概念板块图用 getSectorColorHex 保持跨页面一致
- ✅ 生命周期数据从 LeaderLifecycle 表取；非龙头股显示"未入选"（不编造）

---

## 6. 编码规范

### 6.1 Python

- 函数/方法：`snake_case`
- 类名：`PascalCase`
- 常量：`UPPER_SNAKE_CASE`
- 私有：前缀 `_`（如 `_get_quote`）
- 异步：使用 `async def`，CPU 密集用线程池
- 错误处理：必须 `log.exception()`，禁止 `except: pass`（除非有明确理由）
- DB Session：FastAPI Depends `get_db`，不跨层共享

### 6.2 JavaScript/React

- 组件：`PascalCase`（文件同名）
- 函数：`camelCase`
- 常量：`UPPER_SNAKE_CASE`
- 样式：Tailwind className 优先，复杂内联用 `style={}`
- 颜色：使用 `utils/colors.js` 常量（`UP_COLOR/DOWN_COLOR/BULLISH_COLOR`），禁止硬编码
- 状态：< 5 个 useState / 组件；> 5 抽 hook
- 列表：必须指定 `key={id || code}`，禁止用 index

### 6.3 命名一致性

| 场景 | 命名 | 示例 |
|---|---|---|
| 股票代码（6位） | `code` | `'600519'` |
| 股票代码（带后缀） | `ts_code` | `'600519.SH'` |
| 股票名称 | `name` | `'贵州茅台'` |
| 板块名称 | `sector` | `'白酒'` |
| 信号类型 | `signal` | `'B' / 'S' / 'WATCH'` |
| 交易方向 | `action` | `'buy' / 'sell'` |
| 状态 | `status` | `'pending' / 'filled'` |

---

## 7. 监控 & 告警（待补）

- 自动化交易失败告警（飞书 / 邮件）
- DB 空间告警
- 后端进程存活（LaunchAgent KeepAlive）
- 数据采集失败重试

---

## 8. 已知技术债

详见 [audit/SUMMARY.md](./audit/SUMMARY.md) 第 4 节"修复优先级清单"

按 P0 / P1 / P2 排序。
