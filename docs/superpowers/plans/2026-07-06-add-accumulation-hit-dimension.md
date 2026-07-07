# 新增「吸筹」命中维度 + 全标签展示实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 基于股东户数/户均持股数据新增第 7 个命中标签「吸筹」，并在自选股卡片中固定展示全部 7 个命中标签，未命中时显示「无命中」。

**Architecture:** 后端新增 `stock_holder_number` 表存储每期股东户数与户均持股，新增采集脚本从 Tushare `stk_holdernumber` 接口每日增量拉取；在 `watchlist/core.py` 的批量命中计算中加入 `_hit_accumulation` 规则（默认逻辑：最近两期股东户数连续减少且户均持股增加）。前端 `HitTagBar` 改为固定渲染 7 个标签位，未命中标签置灰显示为「无命中」。

**Tech Stack:** Python/SQLAlchemy/Tushare, React/Tailwind。

---

## 文件结构

- 创建：`backend/db/models.py` 中新增 `StockHolderNumber` 模型
- 创建：`backend/collectors/holder_number_collector.py` 采集脚本
- 修改：`backend/api/watchlist/core.py` 增加 `_hit_accumulation` 与 `accumulation` 命中计算
- 修改：`frontend/src/components/trading/HitTagBar.jsx` 固定展示 7 个标签
- 修改：`frontend/src/components/watchlist/FilterBar.jsx` 增加「吸筹命中」筛选
- 修改：`frontend/src/pages/WatchlistPage.jsx` 增加 `hit_accumulation` 过滤器状态

---

## Task 1: 新增股东户数模型

**Files:**
- Modify: `backend/db/models.py`

- [ ] **Step 1: 在 models.py 中追加 StockHolderNumber 表**

在文件末尾（其他模型之后）新增：

```python
class StockHolderNumber(Base):
    """股东户数与户均持股（用于筹码集中度/主力吸筹判断）

    数据源：Tushare stk_holdernumber
    - ann_date: 公告日期
    - holder_num: 股东户数（户）
    - avg_shares: 户均持股（股）
    """
    __tablename__ = "stock_holder_number"
    id = Column(Integer, primary_key=True, autoincrement=True)
    ts_code = Column(String(20), nullable=False, index=True)
    name = Column(String(20))
    ann_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=True, index=True)
    holder_num = Column(BigInteger, default=0)
    avg_shares = Column(Numeric(16, 2), default=0)
    source = Column(String(20), default='tushare')
    created_at = Column(DateTime, server_default=func.now())
    __table_args__ = (UniqueConstraint("ts_code", "ann_date", name="uq_holder_ts_date"),)
```

- [ ] **Step 2: 执行数据库迁移创建表**

运行：

```bash
cd /Users/gino/Projects/AIROBOT/backend
PYTHONPATH=/Users/gino/Projects/AIROBOT/backend python3 -c "
from db.connection import Base, engine
from db.models import StockHolderNumber
Base.metadata.create_all(engine)
print('stock_holder_number created')
"
```

Expected: `stock_holder_number created`

- [ ] **Step 3: Commit**

```bash
git add backend/db/models.py
git commit -m "feat(db): add stock_holder_number model for chip concentration"
```

---

## Task 2: 股东户数采集脚本

**Files:**
- Create: `backend/collectors/holder_number_collector.py`

- [ ] **Step 1: 创建采集脚本**

```python
"""股东户数/户均持股采集（Tushare stk_holdernumber）"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import SessionLocal
from db.models import StockHolderNumber
from sqlalchemy.dialects.postgresql import insert as pg_insert
import tushare as ts


def fetch_holder_number(ts_code: str = None, start_date: str = None, end_date: str = None, token: str = None):
    """从 Tushare 拉取股东户数数据"""
    if token is None:
        token = os.getenv('TUSHARE_TOKEN')
    if not token:
        raise RuntimeError('TUSHARE_TOKEN not set')
    pro = ts.pro_api(token)
    params = {}
    if ts_code:
        params['ts_code'] = ts_code
    if start_date:
        params['start_date'] = start_date
    if end_date:
        params['end_date'] = end_date
    df = pro.stk_holdernumber(**params)
    if df is None or df.empty:
        return []
    df = df.where(df.notna(), None)
    rows = []
    for _, r in df.iterrows():
        rows.append({
            'ts_code': r.get('ts_code'),
            'name': r.get('name'),
            'ann_date': _parse_date(r.get('ann_date')),
            'end_date': _parse_date(r.get('end_date')),
            'holder_num': int(r.get('holder_num') or 0),
            'avg_shares': float(r.get('avg_shares') or 0),
        })
    return rows


def _parse_date(v):
    if not v:
        return None
    if isinstance(v, str):
        return datetime.strptime(v, '%Y%m%d').date()
    return v


def save_rows(rows):
    if not rows:
        return 0
    db = SessionLocal()
    try:
        for row in rows:
            stmt = pg_insert(StockHolderNumber).values(**row)
            stmt = stmt.on_conflict_do_update(
                index_elements=['ts_code', 'ann_date'],
                set_={
                    'name': stmt.excluded.name,
                    'end_date': stmt.excluded.end_date,
                    'holder_num': stmt.excluded.holder_num,
                    'avg_shares': stmt.excluded.avg_shares,
                }
            )
            db.execute(stmt)
        db.commit()
        return len(rows)
    finally:
        db.close()


def run_full_refresh():
    """全量：拉最近 5 年数据"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=365 * 5)).strftime('%Y%m%d')
    rows = fetch_holder_number(start_date=start, end_date=end)
    return save_rows(rows)


def run_daily():
    """增量：拉最近 90 天，覆盖最新一期"""
    end = datetime.now().strftime('%Y%m%d')
    start = (datetime.now() - timedelta(days=90)).strftime('%Y%m%d')
    rows = fetch_holder_number(start_date=start, end_date=end)
    return save_rows(rows)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--full', action='store_true', help='full refresh')
    args = parser.parse_args()
    count = run_full_refresh() if args.full else run_daily()
    print(f'saved {count} rows')
```

- [ ] **Step 2: 测试采集脚本**

运行：

```bash
cd /Users/gino/Projects/AIROBOT/backend
PYTHONPATH=/Users/gino/Projects/AIROBOT/backend TUSHARE_TOKEN=$TUSHARE_TOKEN python3 collectors/holder_number_collector.py
```

Expected: `saved N rows`（N > 0）

- [ ] **Step 3: Commit**

```bash
git add backend/collectors/holder_number_collector.py
git commit -m "feat(collector): add stock_holder_number collector from tushare"
```

---

## Task 3: 后端新增吸筹命中规则

**Files:**
- Modify: `backend/api/watchlist/core.py`

- [ ] **Step 1: 导入 StockHolderNumber 并新增 _hit_accumulation 函数**

在 `_hit_support` 函数之后、`_gen_action_hint` 之前插入：

```python
def _hit_accumulation(db, ts_codes: list) -> set:
    """🧲 吸筹命中：最近两期股东户数连续减少 + 户均持股增加"""
    from db.models import StockHolderNumber
    if not ts_codes:
        return set()
    # 取每只股最近两期（按公告日期倒序）
    from sqlalchemy import Row, func
    sub = db.query(
        StockHolderNumber.ts_code,
        func.max(StockHolderNumber.ann_date).label('latest_date')
    ).filter(StockHolderNumber.ts_code.in_(ts_codes)).group_by(StockHolderNumber.ts_code).subquery()
    latest_rows = db.query(StockHolderNumber).join(
        sub,
        (StockHolderNumber.ts_code == sub.c.ts_code) &
        (StockHolderNumber.ann_date == sub.c.latest_date)
    ).all()
    if not latest_rows:
        return set()
    prev_dates = db.query(
        StockHolderNumber.ts_code,
        func.max(StockHolderNumber.ann_date).label('prev_date')
    ).filter(
        StockHolderNumber.ts_code.in_(ts_codes),
        StockHolderNumber.ann_date < sub.c.latest_date
    ).group_by(StockHolderNumber.ts_code).subquery()
    prev_rows = db.query(StockHolderNumber).join(
        prev_dates,
        (StockHolderNumber.ts_code == prev_dates.c.ts_code) &
        (StockHolderNumber.ann_date == prev_dates.c.prev_date)
    ).all()
    prev_map = {r.ts_code: r for r in prev_rows}
    hit = set()
    for cur in latest_rows:
        prev = prev_map.get(cur.ts_code)
        if not prev:
            continue
        if (cur.holder_num or 0) > 0 and (prev.holder_num or 0) > 0 \
                and cur.holder_num < prev.holder_num \
                and (cur.avg_shares or 0) > (prev.avg_shares or 0):
            hit.add(cur.ts_code)
    return hit
```

- [ ] **Step 2: 在 _batch_hit_tags 中加入 accumulation 计算**

在循环列表中追加：

```python
        ('accumulation', _hit_accumulation, (db, ts_codes)),
```

并在后续 `tags.append('accumulation')` 逻辑中加入：

```python
        if ts in sets.get('accumulation', set()):
            tags.append('accumulation')
```

- [ ] **Step 3: 在 _gen_action_hint 中加入 accumulation 文案**

在 `if 'support' in s:` 之前插入：

```python
    if 'accumulation' in s:
        return '股东户数减少筹码集中，主力吸筹待拉升'
```

- [ ] **Step 4: Commit**

```bash
git add backend/api/watchlist/core.py
git commit -m "feat(watchlist): add accumulation hit based on holder number reduction"
```

---

## Task 4: 前端固定展示 7 个命中标签

**Files:**
- Modify: `frontend/src/components/trading/HitTagBar.jsx`

- [ ] **Step 1: 修改 HitTagBar 固定渲染 7 个标签位**

```jsx
/**
 * 7 大命中雷达标签栏（固定展示全部维度，未命中显示「无命中」）
 */

export const HIT_TAG_CONFIG = [
  { key: 'yuzi', icon: '🎯', label: '游资', color: '#a855f7', action: '游资共振净买入，关注次日溢价' },
  { key: 'strategy', icon: '🤖', label: '策略', color: '#3b82f6', action: '量化策略命中，按模式死磕' },
  { key: 'trend', icon: '📈', label: '趋势', color: '#22c55e', action: '多头排列，回踩均线低吸' },
  { key: 'capital', icon: '💰', label: '资金', color: '#ef4444', action: '主力爆买创30天新高，防踏空' },
  { key: 'popularity', icon: '🔥', label: '人气', color: '#f97316', action: '板块爆发人气龙头，打板' },
  { key: 'support', icon: '🛡️', label: '承接', color: '#eab308', action: '昨日上榜今日V反，深水低吸' },
  { key: 'accumulation', icon: '🧲', label: '吸筹', color: '#06b6d4', action: '股东户数减少筹码集中，主力吸筹待拉升' },
];

const TAG_MAP = Object.fromEntries(HIT_TAG_CONFIG.map(t => [t.key, t]));

export default function HitTagBar({ tags = [] }) {
  const hitSet = new Set(tags || []);

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1">
      {HIT_TAG_CONFIG.map(cfg => {
        const hit = hitSet.has(cfg.key);
        return (
          <span
            key={cfg.key}
            className="inline-flex items-center gap-0.5 px-2 py-1 rounded text-[11px] font-bold whitespace-nowrap"
            style={{
              background: hit ? `${cfg.color}1a` : 'rgba(107,114,128,0.08)',
              color: hit ? cfg.color : 'var(--text-muted)',
              border: `1px solid ${hit ? `${cfg.color}55` : 'rgba(107,114,128,0.2)'}`,
            }}
            title={hit ? cfg.action : '未命中'}
          >
            <span>{cfg.icon}</span>
            <span>{hit ? cfg.label : '无'}</span>
          </span>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/components/trading/HitTagBar.jsx
git commit -m "feat(ui): show all 7 hit tags with inactive '无' state"
```

---

## Task 5: 前端筛选器增加吸筹命中

**Files:**
- Modify: `frontend/src/components/watchlist/FilterBar.jsx`
- Modify: `frontend/src/pages/WatchlistPage.jsx`

- [ ] **Step 1: 在 FilterBar 的 FILTERS 数组中新增 accumulation**

```jsx
  { key: 'hit_accumulation', label: '吸筹命中', icon: '🧲', desc: '股东户数减少筹码集中' },
```

- [ ] **Step 2: 在 WatchlistPage 的 filters 初始状态中加入 hit_accumulation**

```jsx
const [filters, setFilters] = useState({
  junk: false, buyOnly: false, heating: false,
  hit_yuzi: false, hit_strategy: false, hit_trend: false,
  hit_capital: false, hit_popularity: false, hit_support: false,
  hit_accumulation: false,
});
```

- [ ] **Step 3: 在 displaySignals 的筛选逻辑中加入 accumulation**

```jsx
if (filters.hit_accumulation) arr = arr.filter(s => s.hitTags?.includes('accumulation'));
```

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/watchlist/FilterBar.jsx frontend/src/pages/WatchlistPage.jsx
git commit -m "feat(watchlist): add accumulation filter"
```

---

## Task 6: 构建并验证

- [ ] **Step 1: 重新构建前端**

```bash
cd /Users/gino/Projects/AIROBOT/frontend
npm run build
```

Expected: build success

- [ ] **Step 2: 重新启动 9000 静态服务**

```bash
pkill -f "http.server 9000"
cd /Users/gino/Projects/AIROBOT/frontend/dist
python3 -m http.server 9000 &
```

- [ ] **Step 3: 浏览器验证**

访问 `http://127.0.0.1:9000/watchlist`，检查：
- 每张卡片顶部出现 7 个标签位：游资/策略/趋势/资金/人气/承接/吸筹
- 未命中的显示为灰色「无」
- 命中的显示彩色标签名
- 筛选下拉中出现「吸筹命中」

- [ ] **Step 4: Commit build artifacts（若项目习惯提交 dist）**

```bash
git add frontend/dist
# 或仅提交源码，视项目习惯
git commit -m "chore: rebuild frontend with accumulation hit"
```

---

## Spec Coverage Check

- 新增吸筹维度命中 → Task 1, 2, 3
- 固定展示 7 个标签、未命中显示「无」 → Task 4
- 前端筛选联动 → Task 5
- 部署验证 → Task 6

## Placeholder Scan

无 TBD/TODO/"implement later"。所有步骤包含完整代码与命令。

## Type Consistency

- 命中标签 key：`accumulation`
- 过滤器 key：`hit_accumulation`
- 前端 HIT_TAG_CONFIG key：`accumulation`
- 后端 sets key：`accumulation`
