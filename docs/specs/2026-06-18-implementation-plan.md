# AIROBOT 市场结构可视化系统 - 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个全自动数据采集的市场结构可视化系统，包含热力图、板块轮动、龙头生命周期、资金流路径和智能选股5个页面。

**Architecture:** FastAPI（端口9000，同时服务API和前端）+ React + Vite + ECharts + PostgreSQL。pytdx为主数据源，Tushare备选。全自动定时采集，用户只需打开浏览器查看数据。

**Tech Stack:** Python 3.12 / FastAPI / SQLAlchemy / pytdx / Tushare / React 18 / Vite 5 / ECharts 5 / PostgreSQL 16 / Tailwind CSS 3

---

## 文件结构

```
AIROBOT/
├── backend/
│   ├── main.py                      # FastAPI入口，端口9000，挂载前端
│   ├── config.py                    # 配置中心（数据库/采集/端口）
│   ├── db/
│   │   ├── __init__.py
│   │   ├── connection.py            # SQLAlchemy引擎+会话
│   │   └── models.py                # 3张核心表ORM模型
│   ├── collectors/
│   │   ├── __init__.py
│   │   ├── tdx_collector.py         # pytdx采集器（从hermes迁移优化）
│   │   ├── tushare_fallback.py      # Tushare备选源
│   │   └── scheduler.py             # 定时采集调度器
│   ├── analyzers/
│   │   ├── __init__.py
│   │   ├── heat_score.py            # 热度评分计算
│   │   ├── rotation.py              # 板块轮动分析
│   │   ├── lifecycle.py             # 龙头生命周期识别
│   │   └── money_flow.py            # 资金流路径分析
│   ├── strategies/
│   │   ├── __init__.py
│   │   ├── baihu_v26.py             # 白虎V2.6选股策略
│   │   └── qinglong.py              # 青龙MA10选股策略
│   ├── api/
│   │   ├── __init__.py
│   │   ├── heatmap.py               # GET /api/heatmap
│   │   ├── rotation.py              # GET /api/rotation
│   │   ├── lifecycle.py             # GET /api/lifecycle
│   │   ├── money_flow.py            # GET /api/money-flow
│   │   └── screener.py              # GET /api/screener + POST /api/backfill
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   │   ├── HeatmapPage.jsx
│   │   │   ├── RotationPage.jsx
│   │   │   ├── LifecyclePage.jsx
│   │   │   ├── MoneyFlowPage.jsx
│   │   │   └── ScreenerPage.jsx
│   │   ├── components/
│   │   │   ├── Layout.jsx           # 顶栏+左侧导航+内容区
│   │   │   └── charts/              # ECharts封装组件
│   │   ├── App.jsx
│   │   ├── main.jsx
│   │   └── index.css
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
├── docker-compose.yml
├── start.sh
├── .env
└── docs/specs/
    └── 2026-06-18-market-structure-dashboard-design.md
```

---

## Task 1: 项目初始化 + Docker环境

**Files:**
- Create: `AIROBOT/docker-compose.yml`
- Create: `AIROBOT/.env`
- Create: `AIROBOT/backend/requirements.txt`
- Create: `AIROBOT/start.sh`

- [ ] **Step 1: 创建项目目录结构**

```bash
cd /Users/gino/Projects/AIROBOT
mkdir -p backend/{db,collectors,analyzers,strategies,api}
mkdir -p frontend/src/{pages,components/charts}
```

- [ ] **Step 2: 创建 docker-compose.yml（PostgreSQL）**

```yaml
version: '3.8'
services:
  postgres:
    image: postgres:16-alpine
    container_name: airobot-db
    environment:
      POSTGRES_DB: airobot
      POSTGRES_USER: airobot
      POSTGRES_PASSWORD: airobot_dev_2026
    ports:
      - "5432:5432"
    volumes:
      - airobot_pgdata:/var/lib/postgresql/data
volumes:
  airobot_pgdata:
```

- [ ] **Step 3: 创建 .env**

```env
DATABASE_URL=postgresql+psycopg2://airobot:airobot_dev_2026@localhost:5432/airobot
TUSHARE_TOKEN=your_token_here
API_PORT=9000
```

- [ ] **Step 4: 创建 backend/requirements.txt**

```
fastapi==0.115.0
uvicorn[standard]==0.30.0
sqlalchemy==2.0.35
psycopg2-binary==2.9.9
pytdx==1.72
tushare==1.4.7
numpy==1.26.4
pandas==2.2.2
apscheduler==3.10.4
python-dotenv==1.0.1
pydantic==2.9.0
```

- [ ] **Step 5: 创建 start.sh 一键启动脚本**

```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "=== AIROBOT 启动 ==="
# 1. 启动PostgreSQL
docker compose up -d postgres
sleep 3
# 2. 安装后端依赖
cd backend && pip install -r requirements.txt -q
# 3. 初始化数据库
python -c "from db.connection import init_db; init_db()"
# 4. 构建前端
cd ../frontend && npm install && npm run build
# 5. 启动后端（服务API+前端）
cd ../backend && python -m uvicorn main:app --host 0.0.0.0 --port 9000
```

- [ ] **Step 6: 启动PostgreSQL并验证**

```bash
docker compose up -d postgres
docker exec airobot-db psql -U airobot -c "SELECT 1"
```
Expected: 返回 `1`

- [ ] **Step 7: Commit**

```bash
git init && git add -A && git commit -m "feat: init project structure + Docker"
```

---

## Task 2: 数据库连接 + ORM模型

**Files:**
- Create: `backend/db/__init__.py`
- Create: `backend/db/connection.py`
- Create: `backend/db/models.py`
- Create: `backend/config.py`

- [ ] **Step 1: 创建 config.py**

```python
import os
from dotenv import load_dotenv
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airobot:airobot_dev_2026@localhost:5432/airobot")
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
API_PORT = int(os.getenv("API_PORT", "9000"))
```

- [ ] **Step 2: 创建 db/connection.py**

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
from config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_size=10, max_overflow=20, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def init_db():
    Base.metadata.create_all(bind=engine)
```

- [ ] **Step 3: 创建 db/models.py（3张核心表）**

```python
from sqlalchemy import Column, Integer, String, Date, Numeric, DateTime, UniqueConstraint, func
from db.connection import Base

class SectorFlow(Base):
    __tablename__ = "sector_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    sector = Column(String(50), nullable=False, index=True)
    money_inflow = Column(Numeric(18, 2))
    money_outflow = Column(Numeric(18, 2))
    net_flow = Column(Numeric(18, 2))
    rise_ratio = Column(Numeric(6, 2))
    limit_up_count = Column(Integer, default=0)
    avg_chg = Column(Numeric(6, 2))
    leader_stock = Column(String(20))
    leader_strength = Column(Numeric(6, 2))
    heat_score = Column(Numeric(8, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "sector", name="uq_sector_date"),)

class StockFlow(Base):
    __tablename__ = "stock_flow"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    sector = Column(String(50), index=True)
    net_inflow = Column(Numeric(18, 2))
    main_force_inflow = Column(Numeric(18, 2))
    retail_flow = Column(Numeric(18, 2))
    price_chg = Column(Numeric(6, 2))
    volume_change = Column(Numeric(10, 2))
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_stock_date"),)

class LeaderLifecycle(Base):
    __tablename__ = "leader_lifecycle"
    id = Column(Integer, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, index=True)
    ts_code = Column(String(20), nullable=False, index=True)
    sector = Column(String(50))
    stage = Column(String(10), nullable=False)  # 启动/发酵/主升/分歧/退潮
    strength = Column(Numeric(6, 2))
    change_rate = Column(Numeric(6, 2))
    consecutive_days = Column(Integer, default=1)
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("trade_date", "ts_code", name="uq_leader_date"),)
```

- [ ] **Step 4: 创建 db/__init__.py**

```python
from .connection import engine, SessionLocal, Base, get_db, init_db
from .models import SectorFlow, StockFlow, LeaderLifecycle
```

- [ ] **Step 5: 初始化数据库并验证**

```bash
cd backend && python -c "from db.connection import init_db; init_db(); print('DB initialized')"
```
Expected: `DB initialized`

```bash
docker exec airobot-db psql -U airobot -c "\dt"
```
Expected: 显示3张表

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: database connection + 3 core tables"
```

---

## Task 3: pytdx数据采集器

**Files:**
- Create: `backend/collectors/__init__.py`
- Create: `backend/collectors/tdx_collector.py`
- Create: `backend/collectors/tushare_fallback.py`

- [ ] **Step 1: 创建 tdx_collector.py（从hermes迁移优化）**

核心函数：
- `get_best_server()` - 动态服务器寻优（从hermes迁移）
- `connect_with_retry(max_retries=3)` - 带重试的连接
- `get_sector_list()` - 获取板块列表
- `get_sector_money_flow(date)` - 获取板块资金流向
- `get_stock_money_flow(ts_code, date)` - 获取个股资金流向
- `get_limit_up_stocks(date)` - 获取涨停股
- `collect_daily_data(date)` - 采集指定日期全量数据并写入DB

```python
# 关键采集函数
def collect_daily_data(trade_date):
    """采集单日全量数据：板块资金流 + 个股资金流 + 涨停识别"""
    # 1. 获取板块列表
    sectors = get_sector_list()
    # 2. 遍历板块获取资金流向
    for sector in sectors:
        flow = get_sector_money_flow(sector, trade_date)
        # 写入 sector_flow 表
    # 3. 获取涨停股
    limit_ups = get_limit_up_stocks(trade_date)
    # 4. 遍历涨停股获取个股资金流向
    for stock in limit_ups:
        flow = get_stock_money_flow(stock, trade_date)
        # 写入 stock_flow 表
```

- [ ] **Step 2: 创建 tushare_fallback.py**

```python
# Tushare备选源，pytdx失败时自动切换
def get_sector_money_flow_tushare(date):
    """Tushare获取板块资金流向"""
    pro = ts.pro_api()
    df = pro.moneyflow_hsgt(trade_date=date.replace('-', ''))
    # 字段映射并返回

def get_stock_money_flow_tushare(ts_code, date):
    """Tushare获取个股资金流向"""
    pro = ts.pro_api()
    df = pro.moneyflow(ts_code=ts_code, trade_date=date.replace('-', ''))
    # 字段映射并返回
```

- [ ] **Step 3: 验证pytdx连接**

```bash
cd backend && python -c "
from collectors.tdx_collector import get_best_server
server = get_best_server()
print(f'Best server: {server}')
"
```
Expected: 输出最优服务器IP和端口

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: pytdx data collector + tushare fallback"
```

---

## Task 4: 分析器（热度评分 + 轮动 + 生命周期 + 资金流）

**Files:**
- Create: `backend/analyzers/__init__.py`
- Create: `backend/analyzers/heat_score.py`
- Create: `backend/analyzers/rotation.py`
- Create: `backend/analyzers/lifecycle.py`
- Create: `backend/analyzers/money_flow.py`

- [ ] **Step 1: 创建 heat_score.py**

```python
import numpy as np
from db.connection import get_db
from db.models import SectorFlow

def calculate_heat_scores(trade_date):
    """计算指定日期所有板块的热度评分"""
    db = next(get_db())
    sectors = db.query(SectorFlow).filter_by(trade_date=trade_date).all()
    if not sectors:
        return
    # 归一化
    net_flows = np.array([float(s.net_flow or 0) for s in sectors])
    limit_ups = np.array([float(s.limit_up_count or 0) for s in sectors])
    rises = np.array([float(s.rise_ratio or 0) for s in sectors])
    
    def normalize(arr):
        if arr.max() == arr.min():
            return np.ones_like(arr) * 0.5
        return (arr - arr.min()) / (arr.max() - arr.min())
    
    nf_norm = normalize(net_flows)
    lu_norm = normalize(limit_ups)
    rr_norm = normalize(rises)
    
    for i, sector in enumerate(sectors):
        sector.heat_score = nf_norm[i] * 0.4 + lu_norm[i] * 0.3 + rr_norm[i] * 0.3
    db.commit()
```

- [ ] **Step 2: 创建 rotation.py**

```python
def calculate_rotation(trade_date, lookback_days=5):
    """计算板块轮动：近N日资金流向变化"""
    # 对比当前与N日前各板块net_flow变化
    # 返回桑基图数据：source(流出板块) → target(流入板块), value(资金量)
```

- [ ] **Step 3: 创建 lifecycle.py**

```python
def identify_lifecycle_stage(ts_code, trade_date):
    """识别龙头股生命周期阶段"""
    # 基于连板天数 + 成交量 + 涨幅判断
    # 启动: 首板，成交量放大1.5x
    # 发酵: 2-3连板，主力净流入持续
    # 主升: 4+连板，涨幅加速
    # 分歧: 放量滞涨，主力流出
    # 退潮: 断板回落，跌幅>5%

def update_lifecycle(trade_date):
    """更新指定日期所有龙头股的生命周期"""
```

- [ ] **Step 4: 创建 money_flow.py**

```python
def calculate_money_flow_path(trade_date):
    """计算资金流路径：散户/机构/游资 → 板块 → 龙头股"""
    # 返回Graph数据：nodes(资金来源/板块/龙头), links(流向+资金量)
```

- [ ] **Step 5: 验证分析器**

```bash
cd backend && python -c "
from analyzers.heat_score import calculate_heat_scores
calculate_heat_scores('2026-06-18')
print('Heat scores calculated')
"
```

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "feat: analyzers (heat_score, rotation, lifecycle, money_flow)"
```

---

## Task 5: 内置策略（白虎V2.6 + 青龙）

**Files:**
- Create: `backend/strategies/__init__.py`
- Create: `backend/strategies/baihu_v26.py`
- Create: `backend/strategies/qinglong.py`

- [ ] **Step 1: 创建 baihu_v26.py（从下载文件迁移）**

```python
# 从 /Users/gino/Downloads/白虎V2.6选股策略_核心代码(1).py 迁移
# 核心函数：baihu_strategy_v26(kline, day_index=-1)
# 5个必过硬门槛 + 5维度评分系统
# 数据源改为从pytdx获取K线（替代新浪API）
```

- [ ] **Step 2: 创建 qinglong.py（从下载文件迁移）**

```python
# 从 /Users/gino/Downloads/青龙白虎双策略核心选股代码(1).py 迁移青龙部分
# 核心函数：qinglong_strategy(kline, day_index=-1)
# MA10主升浪回踩策略
```

- [ ] **Step 3: 验证策略运行**

```bash
cd backend && python -c "
from strategies.baihu_v26 import baihu_strategy_v26
from collectors.tdx_collector import get_kline
kline = get_kline('000001', '2026-03-01', '2026-06-18')
result = baihu_strategy_v26(kline)
print(f'Baihu result: {result}')
"
```

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: baihu v2.6 + qinglong strategies"
```

---

## Task 6: API层（5个API + 补采集）

**Files:**
- Create: `backend/api/__init__.py`
- Create: `backend/api/heatmap.py`
- Create: `backend/api/rotation.py`
- Create: `backend/api/lifecycle.py`
- Create: `backend/api/money_flow.py`
- Create: `backend/api/screener.py`
- Create: `backend/main.py`

- [ ] **Step 1: 创建5个API路由**

```python
# heatmap.py
@router.get("/api/heatmap")
async def get_heatmap(date: str = None, days: int = 5):
    """返回热力图数据：日期×板块的heat_score矩阵"""

# rotation.py
@router.get("/api/rotation")
async def get_rotation(date: str = None, days: int = 5):
    """返回桑基图数据：流出板块→流入板块"""

# lifecycle.py
@router.get("/api/lifecycle")
async def get_lifecycle(date: str = None, stage: str = None):
    """返回龙头生命周期数据"""

# money_flow.py
@router.get("/api/money-flow")
async def get_money_flow(date: str = None):
    """返回资金流路径图数据"""

# screener.py
@router.get("/api/screener")
async def screen_stocks(strategy: str = "baihu", date: str = None):
    """智能选股：白虎V2.6 / 青龙 / 热度综合"""

@router.post("/api/backfill")
async def backfill(date: str):
    """手动补采集指定日期数据"""
```

- [ ] **Step 2: 创建 main.py（FastAPI入口 + 前端挂载）**

```python
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from api import heatmap, rotation, lifecycle, money_flow, screener
from collectors.scheduler import start_scheduler

app = FastAPI(title="AIROBOT")
app.include_router(heatmap.router)
app.include_router(rotation.router)
app.include_router(lifecycle.router)
app.include_router(money_flow.router)
app.include_router(screener.router)

@app.get("/api/health")
async def health():
    return {"status": "ok"}

# 前端静态资源
app.mount("/assets", StaticFiles(directory="../frontend/dist/assets"), name="assets")

@app.get("/{full_path:path}")
async def serve_frontend(full_path: str):
    return FileResponse("../frontend/dist/index.html")

# 启动定时采集
@app.on_event("startup")
async def startup():
    start_scheduler()
```

- [ ] **Step 3: 验证API**

```bash
cd backend && python -m uvicorn main:app --port 9000 &
curl http://127.0.0.1:9000/api/health
```
Expected: `{"status":"ok"}`

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: API layer + main.py"
```

---

## Task 7: 定时采集调度器

**Files:**
- Create: `backend/collectors/scheduler.py`

- [ ] **Step 1: 创建 scheduler.py**

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from collectors.tdx_collector import collect_daily_data
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime

scheduler = AsyncIOScheduler()

def start_scheduler():
    # 盘中采集（9:30-15:00 每30分钟）
    scheduler.add_job(scheduled_collect, 'cron', hour='9-14', minute='0,30')
    # 收盘全量采集
    scheduler.add_job(scheduled_collect, 'cron', hour='15', minute='0')
    # 盘后分析
    scheduler.add_job(scheduled_analyze, 'cron', hour='15', minute='30')
    # 数据维护（每日凌晨清理30天前数据）
    scheduler.add_job(cleanup_old_data, 'cron', hour='6', minute='0')
    scheduler.start()

async def scheduled_collect():
    """定时采集任务"""
    today = datetime.now().strftime('%Y-%m-%d')
    collect_daily_data(today)

async def scheduled_analyze():
    """盘后分析任务"""
    today = datetime.now().strftime('%Y-%m-%d')
    calculate_heat_scores(today)
    update_lifecycle(today)
    calculate_rotation(today)
    calculate_money_flow_path(today)
```

- [ ] **Step 2: 验证调度器启动**

```bash
cd backend && python -c "
from collectors.scheduler import start_scheduler
import asyncio
async def test():
    start_scheduler()
    await asyncio.sleep(2)
    print('Scheduler started')
asyncio.run(test())
"
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: scheduler with auto-collect + analyze"
```

---

## Task 8: 前端初始化 + 布局

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.js`
- Create: `frontend/tailwind.config.js`
- Create: `frontend/index.html`
- Create: `frontend/src/main.jsx`
- Create: `frontend/src/App.jsx`
- Create: `frontend/src/index.css`
- Create: `frontend/src/components/Layout.jsx`

- [ ] **Step 1: 初始化Vite + React项目**

```bash
cd frontend && npm create vite@latest . -- --template react
npm install
npm install echarts echarts-for-react react-router-dom tailwindcss postcss autoprefixer
npx tailwindcss init -p
```

- [ ] **Step 2: 配置 vite.config.js（proxy到后端9000）**

```javascript
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      '/api': 'http://127.0.0.1:9000'
    }
  },
  build: {
    outDir: 'dist'
  }
})
```

- [ ] **Step 3: 创建 Layout.jsx（顶栏+左侧导航+内容区）**

```jsx
// 左侧导航5个页面入口
// 顶栏：标题 + 日期 + 刷新按钮 + 主题切换
// 内容区：根据路由渲染页面
```

- [ ] **Step 4: 创建 App.jsx（路由配置）**

```jsx
import { BrowserRouter, Routes, Route } from 'react-router-dom'
// 5个页面路由：/heatmap /rotation /lifecycle /money-flow /screener
```

- [ ] **Step 5: 创建 index.css（主题变量 + Tailwind）**

```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --bg-primary: #ffffff;
  --bg-card: #ffffff;
  --bg-surface: #f8fafc;
  --text-primary: #1a1a1a;
  --text-secondary: #64748b;
  --border-color: #e2e8f0;
}

[data-theme="dark"] {
  --bg-primary: #0f172a;
  --bg-card: #1e293b;
  --bg-surface: #1e293b;
  --text-primary: #f1f5f9;
  --text-secondary: #94a3b8;
  --border-color: #334155;
}
```

- [ ] **Step 6: 验证前端启动**

```bash
cd frontend && npm run dev
# 打开 http://localhost:5174 看到空白布局
```

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "feat: frontend init + layout"
```

---

## Task 9: 热力图页面（HeatmapPage）

**Files:**
- Create: `frontend/src/pages/HeatmapPage.jsx`
- Create: `frontend/src/components/charts/HeatmapChart.jsx`

- [ ] **Step 1: 创建 HeatmapChart.jsx（ECharts Heatmap封装）**

```jsx
import ReactECharts from 'echarts-for-react';

function HeatmapChart({ data }) {
  // data: { dates: [], sectors: [], values: [[x,y,val], ...] }
  const option = {
    tooltip: { position: 'top' },
    grid: { height: '50%', top: '10%' },
    xAxis: { type: 'category', data: data.dates },
    yAxis: { type: 'category', data: data.sectors },
    visualMap: {
      min: 0, max: 100,
      calculable: true,
      orient: 'horizontal', left: 'center', bottom: '15%',
      inRange: { color: ['#22c55e', '#eab308', '#f97316', '#ef4444'] }
    },
    series: [{
      type: 'heatmap',
      data: data.values,
      label: { show: true },
      emphasis: { itemStyle: { shadowBlur: 10 } }
    }]
  };
  return <ReactECharts option={option} style={{ height: '500px' }} />
}
```

- [ ] **Step 2: 创建 HeatmapPage.jsx**

```jsx
import { useState, useEffect } from 'react';
import HeatmapChart from '../components/charts/HeatmapChart';

export default function HeatmapPage() {
  const [data, setData] = useState(null);
  useEffect(() => {
    fetch('/api/heatmap?days=5')
      .then(r => r.json())
      .then(setData);
  }, []);
  // 日期选择 + 热力图 + Top5板块详情
}
```

- [ ] **Step 3: 验证页面渲染**

- [ ] **Step 4: Commit**

---

## Task 10: 板块轮动图页面（RotationPage）

**Files:**
- Create: `frontend/src/pages/RotationPage.jsx`
- Create: `frontend/src/components/charts/SankeyChart.jsx`

- [ ] **Step 1: 创建 SankeyChart.jsx（ECharts Sankey封装）**

```jsx
// 桑基图：左侧流出板块 → 右侧流入板块
// 线条粗细 = 资金量
```

- [ ] **Step 2: 创建 RotationPage.jsx**

```jsx
// 日期范围选择 + 桑基图 + 轮动信号
```

- [ ] **Step 3: Commit**

---

## Task 11: 龙头生命周期页面（LifecyclePage）

**Files:**
- Create: `frontend/src/pages/LifecyclePage.jsx`
- Create: `frontend/src/components/charts/LifecycleTimeline.jsx`

- [ ] **Step 1: 创建 LifecycleTimeline.jsx（自定义Timeline组件）**

```jsx
// 每行一个龙头股
// 5阶段进度条：启动→发酵→主升→分歧→退潮
// 颜色映射：蓝→黄→红→橙→灰
```

- [ ] **Step 2: 创建 LifecyclePage.jsx**

```jsx
// 阶段筛选 + 生命周期列表 + 强度排序
```

- [ ] **Step 3: Commit**

---

## Task 12: 资金流路径页面（MoneyFlowPage）

**Files:**
- Create: `frontend/src/pages/MoneyFlowPage.jsx`
- Create: `frontend/src/components/charts/FlowGraph.jsx`

- [ ] **Step 1: 创建 FlowGraph.jsx（ECharts Graph力导向图）**

```jsx
// 三层节点：资金来源(散户/机构/游资) → 板块 → 龙头股
// 线条粗细 = 资金量
// 颜色 = 资金类型
```

- [ ] **Step 2: 创建 MoneyFlowPage.jsx**

```jsx
// 日期选择 + 资金流图 + 主力净流入Top10
```

- [ ] **Step 3: Commit**

---

## Task 13: 智能选股页面（ScreenerPage）

**Files:**
- Create: `frontend/src/pages/ScreenerPage.jsx`

- [ ] **Step 1: 创建 ScreenerPage.jsx**

```jsx
// 策略选择：白虎V2.6 / 青龙 / 热度综合
// 选股结果表格：代码/名称/板块/阶段/主力流入/评分
// 选股逻辑展示
```

- [ ] **Step 2: Commit**

---

## Task 14: 一键启动 + 集成验证

**Files:**
- Modify: `start.sh`

- [ ] **Step 1: 完善start.sh**

```bash
#!/bin/bash
cd "$(dirname "$0")"
echo "=== AIROBOT 启动 ==="
# 1. PostgreSQL
docker compose up -d postgres
sleep 3
# 2. 后端依赖
cd backend && pip install -r requirements.txt -q
# 3. 数据库初始化
python -c "from db.connection import init_db; init_db()"
# 4. 前端构建
cd ../frontend && npm install && npm run build
# 5. 启动后端
cd ../backend && python -m uvicorn main:app --host 0.0.0.0 --port 9000
```

- [ ] **Step 2: 全链路验证**

```bash
./start.sh
# 打开 http://127.0.0.1:9000
# 验证5个页面都能正常加载
# 验证数据采集定时任务运行
```

- [ ] **Step 3: Commit**

```bash
git add -A && git commit -m "feat: one-click start + full integration"
```

---

## Self-Review

### Spec Coverage
- ✅ 3张核心表（sector_flow, stock_flow, leader_lifecycle）→ Task 2
- ✅ pytdx采集器 + Tushare备选 → Task 3
- ✅ 热度评分 → Task 4 (heat_score.py)
- ✅ 板块轮动 → Task 4 (rotation.py)
- ✅ 龙头生命周期 → Task 4 (lifecycle.py)
- ✅ 资金流路径 → Task 4 (money_flow.py)
- ✅ 白虎V2.6 + 青龙策略 → Task 5
- ✅ 5个API → Task 6
- ✅ 全自动采集调度 → Task 7
- ✅ 热力图页面 → Task 9
- ✅ 轮动图页面 → Task 10
- ✅ 生命周期页面 → Task 11
- ✅ 资金流页面 → Task 12
- ✅ 选股页面 → Task 13
- ✅ 一键启动 → Task 14
- ✅ 补采集机制 → Task 6 (screener.py POST /api/backfill)
- ✅ 单端口9000 → Task 6 (main.py)

### Placeholder Scan
- 部分Task中的代码为伪代码/框架代码，实际实现时需补充完整逻辑
- 这是有意为之：具体实现细节在执行时由subagent填充

### Type Consistency
- 表名一致：sector_flow, stock_flow, leader_lifecycle
- API路径一致：/api/heatmap, /api/rotation, /api/lifecycle, /api/money-flow, /api/screener
- 端口一致：9000（后端+前端），5432（PostgreSQL），5174（Vite dev）
