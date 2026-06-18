# AIROBOT 市场结构可视化系统 - 设计文档

## 概述

将现有"策略选股工具"升级为"交易级市场指挥舱"，核心是**全自动数据采集 + 可视化市场结构分析**。用户只需打开浏览器查看数据，判断方向。

## 核心目的

> 全自动获取程序给我数据，我来判断方向，给我一个全面的分析的股票系统

## 项目位置

`/Users/gino/Projects/AIROBOT/`（全新独立项目，不影响现有 hermes-cockpit）

## 技术栈

- **后端**：FastAPI + SQLAlchemy + pytdx（主数据源）+ Tushare（备选）
- **前端**：React + Vite + ECharts
- **数据库**：PostgreSQL
- **端口**：单一端口 `9000`（FastAPI 同时服务 API 和前端）

## 架构

```
AIROBOT/
├── backend/
│   ├── main.py                 # FastAPI 入口，端口 9000
│   ├── config.py               # 配置中心
│   ├── db/
│   │   ├── connection.py       # SQLAlchemy 引擎
│   │   └── models.py           # 3 张核心表
│   ├── collectors/
│   │   ├── tdx_collector.py    # pytdx 数据采集（从 hermes 迁移优化）
│   │   ├── tushare_fallback.py # Tushare 备选
│   │   └── scheduler.py        # 定时任务（盘中实时 + 盘后全量）
│   ├── analyzers/
│   │   ├── heat_score.py      # 热度评分
│   │   ├── rotation.py        # 轮动分析
│   │   ├── lifecycle.py       # 龙头生命周期识别
│   │   └── money_flow.py      # 资金流路径
│   ├── strategies/
│   │   ├── baihu_v26.py       # 白虎V2.6 强势回调选股
│   │   └── qinglong.py        # 青龙 MA10 主升浪回踩
│   └── api/
│       ├── heatmap.py         # 热力图数据
│       ├── rotation.py        # 轮动桑基图数据
│       ├── lifecycle.py       # 生命周期数据
│       ├── money_flow.py      # 资金流数据
│       └── screener.py        # 智能选股
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HeatmapPage.jsx       # 主线热力图
│   │   │   ├── RotationPage.jsx      # 板块轮动桑基图
│   │   │   ├── LifecyclePage.jsx     # 龙头生命周期
│   │   │   ├── MoneyFlowPage.jsx     # 资金流路径
│   │   │   └── ScreenerPage.jsx     # 智能选股
│   │   ├── components/
│   │   ├── App.jsx
│   │   └── index.css
│   ├── package.json
│   └── vite.config.js
├── docker-compose.yml         # PostgreSQL
├── start.sh                   # 一键启动脚本
└── .env
```

## 数据模型

### 表1：sector_flow（板块流动核心表）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| trade_date | DATE | 交易日期 |
| sector | VARCHAR(50) | 板块名称 |
| money_inflow | DECIMAL(18,2) | 资金流入 |
| money_outflow | DECIMAL(18,2) | 资金流出 |
| net_flow | DECIMAL(18,2) | 净流入 |
| rise_ratio | DECIMAL(6,2) | 板块涨幅% |
| limit_up_count | INT | 涨停数 |
| avg_chg | DECIMAL(6,2) | 平均涨幅 |
| leader_stock | VARCHAR(20) | 龙头股代码 |
| leader_strength | DECIMAL(6,2) | 龙头强度 |
| heat_score | DECIMAL(8,2) | 热度评分（计算字段） |
| created_at | TIMESTAMP | |

约束：UNIQUE(trade_date, sector)

### 表2：stock_flow（个股资金路径）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| trade_date | DATE | 交易日期 |
| ts_code | VARCHAR(20) | 股票代码 |
| sector | VARCHAR(50) | 所属板块 |
| net_inflow | DECIMAL(18,2) | 净流入 |
| main_force_inflow | DECIMAL(18,2) | 主力流入 |
| retail_flow | DECIMAL(18,2) | 散户流向 |
| price_chg | DECIMAL(6,2) | 涨跌幅 |
| volume_change | DECIMAL(10,2) | 成交量变化% |
| created_at | TIMESTAMP | |

约束：UNIQUE(trade_date, ts_code)

### 表3：leader_lifecycle（龙头生命周期）

| 字段 | 类型 | 说明 |
|---|---|---|
| id | SERIAL PK | |
| trade_date | DATE | 交易日期 |
| ts_code | VARCHAR(20) | 股票代码 |
| sector | VARCHAR(50) | 所属板块 |
| stage | VARCHAR(10) | 启动/发酵/主升/分歧/退潮 |
| strength | DECIMAL(6,2) | 强度评分 |
| change_rate | DECIMAL(6,2) | 涨跌幅 |
| consecutive_days | INT | 连板天数 |
| created_at | TIMESTAMP | |

约束：UNIQUE(trade_date, ts_code)

### 热度评分公式

```
heat_score = (
    net_flow_normalized * 0.4 +
    limit_up_count_normalized * 0.3 +
    rise_ratio_normalized * 0.3
)
```

### 生命周期阶段识别

| 阶段 | 判断条件 | 强度参考 |
|---|---|---|
| 启动 | 首板，成交量放大1.5x | 20 |
| 发酵 | 2-3连板，主力净流入持续 | 40 |
| 主升 | 4+连板，涨幅加速 | 80 |
| 分歧 | 放量滞涨，主力流出 | 60 |
| 退潮 | 断板回落，跌幅>5% | 20 |

## 前端页面

### 页面1：主线热力图（HeatmapPage）

- ECharts Heatmap 组件
- 横轴：日期（最近5天）
- 纵轴：板块
- 颜色：heat_score 映射（红=热 → 绿=冷）
- 点击板块展开个股列表

### 页面2：板块轮动图（RotationPage）

- ECharts Sankey 桑基图
- 左侧：资金流出板块
- 右侧：资金流入板块
- 线条粗细 = 资金量
- 底部：自动识别轮动信号

### 页面3：龙头生命周期（LifecyclePage）

- 自定义 Timeline + 折线
- 每行一个龙头股的生命周期阶段
- 颜色：阶段映射（启动=蓝、发酵=黄、主升=红、分歧=橙、退潮=灰）
- 阶段筛选：全部/启动/发酵/主升/分歧/退潮

### 页面4：资金流路径（MoneyFlowPage）

- ECharts Graph 力导向图
- 三层：资金来源(散户/机构/游资) → 板块 → 龙头股
- 线条粗细 = 资金量
- 颜色 = 资金类型（蓝=机构、红=游资、灰=散户）
- 底部：主力净流入 Top10 个股

### 页面5：智能选股（ScreenerPage）

- 基于前4个模块数据自动筛选
- 内置策略：白虎V2.6（MA20回踩）、青龙（MA10主升浪回踩）
- 选股逻辑：板块热度Top5 + 生命周期启动/发酵 + 主力净流入>1000万 + 连板>=2
- 预留策略接入点，后续可扩展更多策略

## 数据采集计划

### 自动采集调度

| 时间 | 动作 |
|---|---|
| 09:15 | 盘前准备（连接 pytdx 最优服务器） |
| 09:30 | 开盘采集（板块资金流向快照） |
| 10:30 | 盘中采集①（更新热力图数据） |
| 11:30 | 午间采集（更新轮动数据） |
| 13:00 | 下午开盘（继续采集） |
| 14:00 | 盘中采集②（更新生命周期） |
| 14:30 | 尾盘采集（更新资金路径） |
| 15:00 | 收盘采集（全量数据落盘） |
| 15:30 | 盘后分析（计算热度评分 + 生命周期阶段） |
| 06:00(每日) | 数据维护（清理30天前数据 + 备份） |

### 补采集机制

1. **失败重试**：每次采集失败自动重试3次，间隔递增（5s/10s/15s）
2. **下轮补采**：下一轮自动检测并补采缺失时段数据
3. **数据源切换**：pytdx 连续失败时自动切换 Tushare
4. **手动补采**：API `POST /api/backfill?date=YYYY-MM-DD`
5. **缺口检测**：每次采集前检查数据库缺失时段，优先补采

## 内置策略

### 白虎V2.6（强势回调选股）

来源：`/Users/gino/Downloads/白虎V2.6选股策略_核心代码(1).py`

核心逻辑：
1. MA20 连续4天向上
2. 近20日累计涨幅 > 20%
3. 收盘价 > MA20（不破位）
4. 最低价 ≤ MA20（真回踩）
5. 偏离 MA20 < 8%
6. 5维度评分（下影线/涨幅/量比/RSI/偏离度），≥4分入选

### 青龙（MA10主升浪回踩）

来源：`/Users/gino/Downloads/青龙白虎双策略核心选股代码(1).py`

核心逻辑：MA10 主升浪回踩策略

## 部署方式

- 一键启动：`./start.sh`
- 自动启动 PostgreSQL + 后端 + 前端构建
- 单端口访问：`http://127.0.0.1:9000`
