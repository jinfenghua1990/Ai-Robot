# AIROBOT 运维手册

**目标**：开发/部署/故障排查一体化参考

---

## 1. 启动 / 停止

### 1.1 后端

**方式 A：LaunchAgent（推荐，AGENTS.md 强制）**

```bash
# 查看状态
launchctl list | grep airobot

# 启动
launchctl start com.airobot.autostart

# 停止
launchctl stop com.airobot.autostart

# 重新加载配置（修改 plist 后）
launchctl unload ~/Library/LaunchAgents/com.airobot.autostart.plist
launchctl load ~/Library/LaunchAgents/com.airobot.autostart.plist
```

**方式 B：手动（开发用）**

```bash
cd /Users/gino/Projects/AIROBOT/backend
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/Resources/Python.app/Contents/MacOS/Python -m uvicorn main:app --host 0.0.0.0 --port 9000 --limit-concurrency 200
```

### 1.2 前端

```bash
cd /Users/gino/Projects/AIROBOT/frontend

# dev 模式
npm run dev  # http://localhost:5173

# 生产 build
npm run build  # dist/ 目录

# 预览生产
npm run preview
```

### 1.3 数据库

```bash
# 启动
brew services start postgresql@16

# 启动前清理死锁（如有）
# 提示：若报 "lock file postmaster.pid already exists" 先杀进程
pg_ctl -D /opt/homebrew/var/postgresql@16 stop -m fast

# 启动
pg_ctl -D /opt/homebrew/var/postgresql@16 start

# 连接
psql -U airobot -d airobot
```

---

## 2. 关键路径

```
~/Projects/AIROBOT/
├── backend/                # 后端
│   ├── main.py            # 入口
│   ├── config.py          # 配置（DB / MX_APIKEY）
│   ├── api/               # 33 个 endpoint
│   ├── services/          # 业务服务
│   ├── analyzers/         # 纯分析
│   ├── collectors/        # 数据采集
│   ├── strategies/        # 策略代码
│   └── db/                # 模型
├── frontend/              # 前端
│   ├── src/pages/         # 14 个页面
│   ├── src/components/    # 通用组件
│   └── src/lib/           # 工具
├── docs/                  # 文档
│   ├── ARCHITECTURE.md
│   ├── API.md
│   ├── ER_DIAGRAM.md
│   └── audit/SUMMARY.md
├── start.sh               # 启动脚本
└── stop.sh                # 停止脚本
```

---

## 3. 配置管理

### 3.1 环境变量（backend/config.py）

| 变量 | 说明 | 默认 |
|---|---|---|
| `DATABASE_URL` | PostgreSQL 连接串 | `postgresql+psycopg2://airobot:...` |
| `MX_APIKEY` | 妙想 API Key（自选股+数据查询） | - |
| `MX_TRADING_APIKEY` | 妙想模拟盘 API Key（20w 账户） | - |
| `MX_API_URL` | 妙想基础 URL | `https://mcp.miaoxiang.com` |

**永久生效**：写入 `~/Library/LaunchAgents/com.airobot.autostart.plist` 的 `EnvironmentVariables`。

### 3.2 .env 文件

`backend/.env` 加载顺序：
1. 系统 env
2. plist EnvironmentVariables
3. `backend/.env`（不推荐，仅本地用）

---

## 4. 数据采集调度

后端启动后自动注册以下定时任务（`collectors/scheduler.py`）：

| 任务 | 时间 | 频率 | 目标表 |
|---|---|---|---|
| 实时快照采集 | 9:30-11:30, 13:00-15:00 | 每 15 分钟 | realtime_*_flow |
| 收盘归档 | 15:05 | 每天 | sector_flow / stock_flow |
| 盘后分析 | 15:30 | 每天 | watchlist_signal_daily |
| 概念板块同步 | 9:00 / 15:05 | 每天 | concept_sectors |
| BS 策略预计算 | 15:30 | 每天 | bs_daily_scan |
| 自动化交易 | 9:25-11:30, 13:00-15:00 | 每 5 分钟 | auto_trade_log |
| 数据维护（清理） | 02:00 | 每天 | （删除 180天前数据） |

---

## 5. 监控 & 告警

### 5.1 进程存活

```bash
# 后端进程
ps aux | grep "uvicorn main:app" | grep -v grep

# LaunchAgent
launchctl list | grep airobot
```

### 5.2 健康检查

```bash
curl http://localhost:9000/api/health
# 期望: {"status":"ok","service":"AIROBOT"}
```

### 5.3 关键指标（每日巡检）

```sql
-- 1. 当日数据量
SELECT count(*) FROM stock_flow WHERE trade_date = CURRENT_DATE;
SELECT count(*) FROM watchlist_signal_daily WHERE trade_date = CURRENT_DATE;

-- 2. BS 策略命中
SELECT strategy_name, hit_count FROM bs_daily_scan
WHERE trade_date = CURRENT_DATE ORDER BY hit_count DESC;

-- 3. 自动化交易
SELECT * FROM auto_trade_log WHERE trade_date = CURRENT_DATE;

-- 4. 数据质量
SELECT count(*) FROM data_quality_log WHERE ts > NOW() - INTERVAL '1 day';
```

---

## 6. 常见故障排查

### 6.1 后端起不来

**症状**：`curl /api/health` 超时或连接拒绝

**排查**：
```bash
# 1. 进程是否在跑
ps aux | grep "uvicorn main:app" | grep -v grep

# 2. 看启动日志
tail -100 /tmp/airobot_backend.log

# 3. 常见错误：
#    - "Address already in use" → 端口被占，pkill 旧进程
#    - "no module X" → pip install 缺失依赖
#    - "database connection failed" → 检查 PostgreSQL 是否启动
```

### 6.2 数据没更新

**排查**：
```sql
-- 1. 检查实时采集是否在跑
SELECT * FROM realtime_stock_flow
WHERE trade_date = CURRENT_DATE ORDER BY snapshot_time DESC LIMIT 10;

-- 2. 检查数据源状态
SELECT * FROM data_source_reliability ORDER BY source;

-- 3. 手动触发一次采集
curl -X POST http://localhost:9000/api/realtime/refresh
```

### 6.3 妙想 API 401/403

**原因**：`MX_APIKEY` 失效或未配置

**修复**：
1. 登录妙想控制台获取新 key
2. 更新 `backend/.env`、plist
3. 重启后端

### 6.4 自动化交易没执行

**排查**：
```sql
-- 1. 是否启用
SELECT enabled, max_buy_count, min_vote_score FROM auto_trade_config WHERE id=1;

-- 2. 当日决策日志
SELECT * FROM auto_trade_log WHERE trade_date = CURRENT_DATE ORDER BY created_at DESC;

-- 3. 是否在交易时段（盘后才执行）
```

### 6.5 前端白屏 / 404

**排查**：
```bash
# 1. dev 模式
cd frontend && npm run dev

# 2. 检查后端
curl http://localhost:9000/api/health

# 3. 检查 API 代理
# vite.config.js 中是否配了 '/api' -> 'http://localhost:9000'
```

### 6.6 DB 锁冲突

**症状**：`Lock wait timeout exceeded`

**修复**：
```sql
-- 找锁
SELECT * FROM pg_stat_activity WHERE state='active';
-- 杀进程
SELECT pg_terminate_backend(pid);
```

---

## 7. 数据备份与恢复

### 7.1 备份

```bash
# 完整备份
pg_dump airobot > /tmp/airobot_$(date +%Y%m%d).sql

# 仅 schema
pg_dump -s airobot > /tmp/airobot_schema.sql

# 仅数据
pg_dump -a airobot > /tmp/airobot_data.sql

# 单表
pg_dump -t stock_flow airobot > /tmp/stock_flow.sql
```

### 7.2 恢复

```bash
psql -U airobot -d airobot < /tmp/airobot_20260703.sql
```

### 7.3 定时备份（crontab）

```cron
0 2 * * * pg_dump airobot > /tmp/airobot_$(date +\%Y\%m\%d).sql
```

---

## 8. 性能调优

### 8.1 后端

- 并发：`--limit-concurrency 200`
- keepalive：`--timeout-keep-alive 15`
- 不开 access log（用 nginx 单独记录）

### 8.2 DB

- 关键查询加索引（见 ER_DIAGRAM.md 第 6 节）
- 大表定期清理（auto_trade_log 1年 / sector_flow 6月）
- `VACUUM ANALYZE` 每周一次

### 8.3 前端

- 路由级 code splitting（`React.lazy`）
- echarts 按需引入（不要全部 import）
- 大列表用 `React.memo` 减少重渲染

---

## 9. 部署清单

部署到新机器时：

- [ ] 安装 PostgreSQL 16
- [ ] 初始化 DB：`psql -U postgres -c "CREATE DATABASE airobot;"`
- [ ] 跑 schema：`psql -U airobot -d airobot < schema.sql`
- [ ] 装 Python 依赖：`pip install -r requirements.txt`
- [ ] 装 LaunchAgent
- [ ] 配置 `MX_APIKEY`（plist EnvironmentVariables）
- [ ] 验证：`curl localhost:9000/api/health`
- [ ] 装前端依赖：`cd frontend && npm install && npm run build`
- [ ] 部署静态文件到 nginx
- [ ] 配置 nginx 反代 `/api` → 后端 9000

---

## 10. 紧急联系方式

无（项目私有）

故障时检查顺序：
1. 进程是否在跑
2. 日志（`/tmp/airobot_backend.log`）
3. DB 连接
4. 数据源（妙想/新浪/东财）
