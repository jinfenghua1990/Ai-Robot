import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import WatchlistResultsTable, { toWatchlistSignal } from '../components/WatchlistResultsTable';

/**
 * 横盘蓄势策略页（A股 · 盘后圈股）
 *
 * 数据流：每日盘后 worker 自动扫描 → horizontal_signal 表 → 本页展示。
 * 逻辑：板块上涨 + 个股横盘蓄势 + 突破/回踩买点。
 * 展示：大盘过滤 / 状态统计 / 筛选 / 股票列表 / 单股详情（评分+量价+箱体+历史跟踪）。
 * 说明：评分高 ≠ 立刻买入，必须同时出现买点信号（A/B/C）。
 */

// ===== 状态与信号元信息 =====
const STATE_META = {
  '横盘观察': { color: '#6b7280', bg: 'rgba(107,114,128,0.12)' },
  '接近突破': { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  '突破启动': { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  '回踩确认': { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  '突破失败': { color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
};

const GRADE_META = {
  '核心候选': { color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  '重点观察': { color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  '普通观察': { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
};

const SIGNAL_META = {
  A: { label: '接近突破', color: '#3b82f6', bg: 'rgba(59,130,246,0.12)' },
  B: { label: '突破启动', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  C: { label: '回踩确认', color: '#ef4444', bg: 'rgba(239,68,68,0.12)' },
  D: { label: '突破失败', color: '#64748b', bg: 'rgba(100,116,139,0.12)' },
};

const ALL_STATES = ['横盘观察', '接近突破', '突破启动', '回踩确认', '突破失败'];

// 横盘策略结果 → 18列自选信号（统一由 WatchlistResultsTable 渲染）
// 横盘扫描不计算技术指标，均线/MACD/KDJ/支撑压力列按缺失显示 —；
// 状态与买点信号映射到「建议」列保留关键信息。
const toHorizontalSignal = (r) => {
  const base = toWatchlistSignal(r);
  const sc = r.signal_code;
  base.signalLabel = sc
    ? `${sc}·${(SIGNAL_META[sc]?.label || '')}${r.state ? ' / ' + r.state : ''}`
    : (r.state || null);
  base.strategy = '横盘蓄势';
  return base;
};

function scoreColor(score) {
  if (score >= 85) return '#ef4444';
  if (score >= 75) return '#f59e0b';
  if (score >= 65) return '#3b82f6';
  return '#6b7280';
}



// ===== 策略胜率/盈亏比卡片 =====
function PerformanceCard({ perf, loading }) {
  if (loading) {
    return (
      <div className="rounded-md p-3 flex items-center justify-center text-xs" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
        胜率统计加载中...
      </div>
    );
  }
  if (!perf) return null;
  const holds = ['5', '10', '20'];
  const label = { 5: '5日', 10: '10日', 20: '20日' };
  return (
    <div className="rounded-md p-3" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="text-xs font-bold mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-primary)' }}>
        📊 信号后走势（A/B/C 买点胜率）· 滚动评估
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        {holds.map((h) => {
          const d = perf[h];
          if (!d || !d.n) {
            return (
              <div key={h} className="rounded p-2" style={{ background: 'var(--bg-sub)', border: '1px solid var(--border-color)' }}>
                <div className="font-bold" style={{ color: 'var(--text-primary)' }}>{label[h]}</div>
                <div style={{ color: 'var(--text-muted)' }}>样本不足</div>
              </div>
            );
          }
          const wr = d.win_rate ?? 0;
          const ok = wr >= 50;
          return (
            <div key={h} className="rounded p-2" style={{ background: 'var(--bg-sub)', border: '1px solid var(--border-color)' }}>
              <div className="flex items-center justify-between">
                <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{label[h]}</span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{d.n} 例</span>
              </div>
              <div className="mt-1 flex items-baseline gap-1">
                <span className="text-base font-bold" style={{ color: ok ? UP_COLOR : '#f59e0b' }}>{wr.toFixed(0)}%</span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>胜率</span>
              </div>
              <div className="mt-0.5 flex flex-wrap gap-x-2 gap-y-0.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>均收 <b style={{ color: d.avg_ret >= 0 ? UP_COLOR : DOWN_COLOR }}>{d.avg_ret >= 0 ? '＋' : ''}{d.avg_ret}%</b></span>
                {d.profit_loss_ratio != null && (
                  <span>盈亏比 <b style={{ color: 'var(--text-primary)' }}>{d.profit_loss_ratio}</b></span>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===== 大盘环境卡片 =====
function MarketCard({ market, loading }) {
  if (loading) {
    return (
      <div className="rounded-md p-3 flex items-center justify-center text-xs" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
        大盘环境加载中...
      </div>
    );
  }
  if (!market) return null;
  const m = market;
  const ok = m.ok;
  const conds = m.details || {};
  const condList = Object.entries(conds).map(([k, v]) => ({ label: k, pass: !!v }));

  return (
    <div className="rounded-md p-3" style={{ background: 'var(--bg-card)', border: `1px solid ${ok ? 'rgba(239,68,68,0.4)' : 'var(--border-color)'}` }}>
      <div className="flex items-center justify-between mb-2">
        <div className="text-xs font-bold flex items-center gap-1.5" style={{ color: 'var(--text-primary)' }}>
          🌐 大盘环境（盘后过滤）
        </div>
        <span
          className="text-[10px] font-bold px-2 py-0.5 rounded-full"
          style={{
            color: ok ? UP_COLOR : '#6b7280',
            background: ok ? 'rgba(239,68,68,0.12)' : 'rgba(107,114,128,0.12)',
            border: `1px solid ${ok ? 'rgba(239,68,68,0.35)' : 'rgba(107,114,128,0.3)'}`,
          }}
        >
          {ok ? '✅ 允许交易' : '⛔ 仅观察池'}
        </span>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 text-xs">
        <Metric label="大盘评分" value={`${m.score} / 10`} highlight={m.score >= 7 ? UP_COLOR : undefined} />
        <Metric label="等权指数" value={m.index_close != null ? Number(m.index_close).toFixed(2) : '—'} sub={m.trade_date ? `交易日 ${m.trade_date}` : undefined} />
        <Metric label="指数 MA20" value={m.index_ma20 != null ? Number(m.index_ma20).toFixed(2) : '—'} />
        <Metric label="MA20 五日斜率" value={m.ma20_slope5 != null ? `${Number(m.ma20_slope5).toFixed(2)}%` : '—'} highlight={m.ma20_slope5 >= 0 ? UP_COLOR : DOWN_COLOR} />
        <Metric label="全市场上涨占比" value={m.up_ratio != null ? `${Number(m.up_ratio).toFixed(1)}%` : '—'} highlight={m.up_ratio >= 40 ? UP_COLOR : DOWN_COLOR} />
      </div>

      <div className="flex flex-wrap items-center gap-1.5 mt-2.5">
        {condList.map((c) => (
          <span key={c.label} className="text-[10px] px-1.5 py-0.5 rounded"
            style={{
              color: c.pass ? UP_COLOR : DOWN_COLOR,
              background: c.pass ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)',
            }}>
            {c.pass ? '✓' : '✗'} {c.label}
          </span>
        ))}
        <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>
          大盘不满足时：不产生买入信号，横盘股仍进入观察池
        </span>
      </div>
    </div>
  );
}

function Metric({ label, value, sub, highlight }) {
  return (
    <div className="rounded px-2 py-1.5" style={{ background: 'var(--bg-secondary)' }}>
      <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-bold" style={{ color: highlight || 'var(--text-primary)' }}>{value}</div>
      {sub && <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
  );
}

// ===== 统计条 =====
function StatsBar({ stats, marketOk }) {
  if (!stats) return null;
  const stateItems = ALL_STATES.map((s) => ({
    state: s,
    n: stats.states?.[s] || 0,
    ...(STATE_META[s] || {}),
  }));
  const signalItems = ['A', 'B', 'C', 'D'].map((c) => ({
    code: c,
    n: stats.signals?.[c] || 0,
    ...(SIGNAL_META[c] || {}),
  }));
  return (
    <div className="rounded-md p-3" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        <div className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📊 扫描统计</div>
        <StatChip label="箱体命中" value={stateItems.reduce((s, i) => s + i.n, 0)} color="var(--text-primary)" />
        {stateItems.map((i) => (
          <StatChip key={i.state} label={i.state} value={i.n} color={i.color} />
        ))}
        <span className="mx-1 w-px h-4 self-center" style={{ background: 'var(--border-color)' }} />
        {signalItems.map((i) => (
          <StatChip key={i.code} label={`信号${i.code} ${SIGNAL_META[i.code].label}`} value={i.n} color={i.color} />
        ))}
        <span className="mx-1 w-px h-4 self-center" style={{ background: 'var(--border-color)' }} />
        <StatChip label="可交易（大盘+板块+信号）" value={stats.tradable || 0} color={marketOk ? UP_COLOR : '#6b7280'} />
      </div>
      <div className="text-[9px] mt-1.5" style={{ color: 'var(--text-muted)' }}>
        评分 &gt; 65 分才入库展示 · 最高买点 = 回踩确认（信号C），其次放量突破（信号B）、接近突破（信号A）
      </div>
    </div>
  );
}

function StatChip({ label, value, color }) {
  return (
    <div className="flex items-center gap-1 text-xs">
      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="font-bold" style={{ color }}>{value}</span>
    </div>
  );
}

// ===== 筛选栏 =====
function FilterBar({ filters, setFilters, sectors, onRefresh, onScan, scanning, refreshing }) {
  const update = (patch) => setFilters((f) => ({ ...f, ...patch }));
  const inputCls = {
    background: 'var(--bg-secondary)',
    border: '1px solid var(--border-color)',
    color: 'var(--text-primary)',
    outline: 'none',
    borderRadius: 6,
    padding: '3px 8px',
    fontSize: 12,
  };
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-md p-2" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <select value={filters.state} onChange={(e) => update({ state: e.target.value })} style={inputCls}>
        <option value="">全部状态</option>
        {ALL_STATES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <select value={filters.grade} onChange={(e) => update({ grade: e.target.value })} style={inputCls}>
        <option value="">全部等级</option>
        <option value="核心候选">核心候选</option>
        <option value="重点观察">重点观察</option>
        <option value="普通观察">普通观察</option>
      </select>
      <input
        type="number" min={0} max={100} placeholder="最低评分"
        value={filters.minScore || ''}
        onChange={(e) => update({ minScore: e.target.value })}
        style={{ ...inputCls, width: 80 }}
      />
      <select value={filters.sector} onChange={(e) => update({ sector: e.target.value })} style={{ ...inputCls, maxWidth: 140 }}>
        <option value="">全部板块</option>
        {(sectors || []).map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
      <select value={filters.sort} onChange={(e) => update({ sort: e.target.value })} style={inputCls}>
        <option value="score">按评分</option>
        <option value="amplitude">按振幅</option>
      </select>
      <label className="flex items-center gap-1 text-xs cursor-pointer select-none" style={{ color: 'var(--text-secondary)' }}>
        <input type="checkbox" checked={filters.onlySignal} onChange={(e) => update({ onlySignal: e.target.checked })} />
        仅看信号
      </label>
      <label className="flex items-center gap-1 text-xs cursor-pointer select-none" style={{ color: 'var(--text-secondary)' }}>
        <input type="checkbox" checked={filters.onlyTradable} onChange={(e) => update({ onlyTradable: e.target.checked })} />
        仅可交易
      </label>
      <span className="flex-1" />
      <button
        onClick={onRefresh} disabled={refreshing}
        className="px-2.5 py-1 rounded-md text-xs border flex items-center gap-1"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', cursor: refreshing ? 'wait' : 'pointer', opacity: refreshing ? 0.6 : 1 }}
      >
        {refreshing ? '⏳' : '🔄'} 刷新
      </button>
      <button
        onClick={onScan} disabled={scanning}
        className="px-2.5 py-1 rounded-md text-xs font-medium flex items-center gap-1"
        style={{
          background: 'rgba(239,68,68,0.12)', color: UP_COLOR,
          border: '1px solid rgba(239,68,68,0.35)',
          cursor: scanning ? 'wait' : 'pointer', opacity: scanning ? 0.6 : 1,
        }}
      >
        {scanning ? '⏳' : '▶️'} 重新扫描
      </button>
    </div>
  );
}



// ===== 详情弹窗 =====
function ScoreBar({ label, score, max }) {
  const pct = Math.min(100, (score / max) * 100);
  return (
    <div className="flex items-center gap-2 text-[10px]">
      <span className="w-16 shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-secondary)' }}>
        <div className="h-full rounded-full" style={{ width: `${pct}%`, background: score >= max * 0.6 ? UP_COLOR : score >= max * 0.4 ? '#f59e0b' : '#6b7280' }} />
      </div>
      <span className="w-8 text-right font-medium" style={{ color: 'var(--text-primary)' }}>{Number(score).toFixed(1)}</span>
    </div>
  );
}

function Kv({ label, value, color, unit }) {
  return (
    <div className="flex items-center justify-between text-[10px] py-0.5" style={{ borderBottom: '1px dashed var(--border-color)' }}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="font-medium" style={{ color: color || 'var(--text-primary)' }}>
        {value != null ? value : '—'}{unit || ''}
      </span>
    </div>
  );
}

function DetailModal({ item, onClose }) {
  const [detail, setDetail] = useState(null);
  const [history, setHistory] = useState(null);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState('score'); // score | vp | box | history

  useEffect(() => {
    if (!item) return;
    setLoading(true);
    setDetail(null);
    setHistory(null);
    (async () => {
      try {
        const q = `?code=${item.ts_code}`;
        const [d, h] = await Promise.all([
          apiFetch(`/api/a-horizontal/detail${q}`),
          apiFetch(`/api/a-horizontal/history${q}&limit=20`),
        ]);
        if (d.ok) setDetail(d.data.item);
        if (h.ok) setHistory(h.data.items);
      } catch { /* silent */ }
      setLoading(false);
    })();
  }, [item]);

  if (!item) return null;
  const data = detail || item;
  const scoreDetail = data.score_detail || {};
  const sm = STATE_META[data.state] || STATE_META['横盘观察'];
  const gm = GRADE_META[data.grade];

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.5)' }} onClick={onClose}>
      <div
        className="rounded-lg w-full max-w-2xl max-h-[88vh] overflow-auto"
        style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* 头部 */}
        <div className="sticky top-0 z-10 px-4 py-2.5 flex items-center justify-between border-b" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{data.name || data.ts_code}</span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{data.ts_code}</span>
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ color: sm.color, background: sm.bg }}>{data.state}</span>
            {gm && <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ color: gm.color, background: gm.bg }}>{data.grade}</span>}
            <span className="text-sm font-bold" style={{ color: scoreColor(data.score) }}>{data.score != null ? Number(data.score).toFixed(1) : '—'}分</span>
          </div>
          <button onClick={onClose} className="px-1.5 text-sm" style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        {loading && (
          <div className="py-14 text-center text-xs" style={{ color: 'var(--text-muted)' }}>
            <div className="w-5 h-5 border-2 rounded-full animate-spin mx-auto mb-2" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
            详情加载中...
          </div>
        )}

        {!loading && (
          <>
            {/* 信号详情条 */}
            <div className="px-4 py-2 flex items-center gap-2 text-[11px]" style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)' }}>
              <span style={{ color: 'var(--text-muted)' }}>信号：</span>
              {data.signal_code ? (
                <span className="px-1.5 py-0.5 rounded font-medium" style={{ color: SIGNAL_META[data.signal_code]?.color, background: SIGNAL_META[data.signal_code]?.bg }}>
                  {data.signal_code} · {SIGNAL_META[data.signal_code]?.label}
                </span>
              ) : <span style={{ color: 'var(--text-muted)' }}>尚未触发</span>}
              <span style={{ color: 'var(--text-secondary)' }}>{data.signal_detail || '—'}</span>
              {data.tradable && (
                <span className="ml-auto px-1.5 py-0.5 rounded text-[10px] font-bold" style={{ color: UP_COLOR, background: 'rgba(239,68,68,0.12)' }}>✓ 可交易</span>
              )}
            </div>

            {/* Tab 切换 */}
            <div className="px-4 pt-2 flex items-center gap-1">
              {[
                ['score', '评分明细'], ['vp', '量价结构'], ['box', '箱体参数'], ['history', '历史跟踪'],
              ].map(([k, label]) => (
                <button
                  key={k}
                  onClick={() => setTab(k)}
                  className="px-2 py-1 rounded-t text-[11px] font-medium"
                  style={{
                    color: tab === k ? 'var(--accent-blue)' : 'var(--text-muted)',
                    borderBottom: tab === k ? '2px solid var(--accent-blue)' : '2px solid transparent',
                  }}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="px-4 py-3">
              {tab === 'score' && (
                <div className="space-y-1.5">
                  {Object.entries(scoreDetail).map(([k, v]) => (
                    <ScoreBar key={k} label={k} score={Number(v) || 0} max={20} />
                  ))}
                  <div className="flex items-center justify-between pt-1 text-[10px]">
                    <span style={{ color: 'var(--text-muted)' }}>风险回报比（盈亏比）</span>
                    <span className="font-bold" style={{ color: (data.risk_reward || 0) >= 2 ? UP_COLOR : '#f59e0b' }}>
                      {data.risk_reward != null ? Number(data.risk_reward).toFixed(2) : '—'}
                    </span>
                  </div>
                  <div className="pt-1.5 text-[9px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                    💡 评分代表股票质量，不代表立即买入：必须同时出现买点信号（A 接近突破 / B 放量突破 / C 回踩确认）才考虑入场。
                  </div>
                </div>
              )}

              {tab === 'vp' && (
                <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
                  <Kv label="阳线均量 / 阴线均量" value={data.up_dn_vol_ratio != null ? Number(data.up_dn_vol_ratio).toFixed(2) : '—'} color={(data.up_dn_vol_ratio || 0) >= 1.15 ? UP_COLOR : undefined} />
                  <Kv label="近5日均量 / 20日均量" value={data.vol_ratio_5_20 != null ? Number(data.vol_ratio_5_20).toFixed(2) : '—'} color={(data.vol_ratio_5_20 || 0) >= 0.8 && (data.vol_ratio_5_20 || 0) <= 1.5 ? UP_COLOR : undefined} />
                  <Kv label="价格重心变化" value={data.price_gravity != null ? `${Number(data.price_gravity).toFixed(1)}%` : '—'} color={(data.price_gravity || 0) > 0 ? UP_COLOR : DOWN_COLOR} />
                  <Kv label="20日均成交额" value={data.amount_20 != null ? `${(Number(data.amount_20) / 100000).toFixed(2)}亿` : '—'} />
                  <Kv label="换手/波动（ATR比）" value={data.atr_ratio != null ? `${Number(data.atr_ratio).toFixed(2)}%` : '—'} color={(data.atr_ratio || 99) <= 4 ? UP_COLOR : '#f59e0b'} />
                  <Kv label="判断" value="存在横盘换手与承接特征" color="var(--text-secondary)" />
                </div>
              )}

              {tab === 'box' && (
                <div className="grid grid-cols-2 gap-x-6 gap-y-0.5">
                  <Kv label="箱体区间" value={data.box_high != null ? `${Number(data.box_low).toFixed(2)} — ${Number(data.box_high).toFixed(2)}` : '—'} />
                  <Kv label="箱体振幅" value={data.amplitude != null ? `${Number(data.amplitude).toFixed(2)}%` : '—'} color={(data.amplitude || 99) <= 15 ? UP_COLOR : '#f59e0b'} />
                  <Kv label="横盘天数" value={data.box_days != null ? `${data.box_days} 日` : '—'} />
                  <Kv label="距箱体上沿" value={data.dist_to_break != null ? `${Number(data.dist_to_break).toFixed(1)}%` : '—'} color={(data.dist_to_break || 99) <= 3 ? '#3b82f6' : 'var(--text-primary)'} />
                  <Kv label="收盘位于箱体位置" value={data.close_pos_in_box != null ? `${Number(data.close_pos_in_box).toFixed(0)}%` : '—'} color={(data.close_pos_in_box || 0) >= 70 ? UP_COLOR : undefined} />
                  <Kv label="MA20 漂移" value={data.ma20_drift != null ? `${Number(data.ma20_drift).toFixed(2)}%` : '—'} color={(data.ma20_drift || 99) <= 8 ? UP_COLOR : '#f59e0b'} />
                  <Kv label="失效参考位" value={data.box_low != null ? `跌破 ${Number(data.box_low).toFixed(2)} 失效` : '—'} color={DOWN_COLOR} />
                  <Kv label="板块" value={data.sector || '—'} />
                  <Kv label="板块强度排名" value={data.sector_rank_pct != null ? `行业前 ${Number(data.sector_rank_pct).toFixed(1)}%` : '—'} color={(data.sector_rank_pct || 99) <= 30 ? UP_COLOR : '#f59e0b'} />
                  <Kv label="板块趋势" value={data.sector_ok ? '板块强（>MA20且向上）' : '板块弱'} color={data.sector_ok ? UP_COLOR : DOWN_COLOR} />
                  <Kv label="大盘环境" value={data.market_ok ? '允许交易' : '仅观察'} color={data.market_ok ? UP_COLOR : '#6b7280'} />
                </div>
              )}

              {tab === 'history' && (
                <div>
                  {!history || !history.length ? (
                    <div className="py-6 text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>暂无历史信号记录</div>
                  ) : (
                    <table className="w-full text-[10px]">
                      <thead>
                        <tr style={{ color: 'var(--text-muted)' }}>
                          <th className="text-left py-1">日期</th>
                          <th>状态</th>
                          <th>信号</th>
                          <th>评分</th>
                          <th>收盘</th>
                          <th>距突破</th>
                        </tr>
                      </thead>
                      <tbody>
                        {history.map((h) => (
                          <tr key={h.trade_date} style={{ borderTop: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
                            <td className="py-1">{h.trade_date}</td>
                            <td className="text-center">
                              <span className="px-1 rounded" style={{ color: STATE_META[h.state]?.color, background: STATE_META[h.state]?.bg }}>
                                {h.state}
                              </span>
                            </td>
                            <td className="text-center">{h.signal_code || '—'}</td>
                            <td className="text-center" style={{ color: h.score != null ? scoreColor(h.score) : undefined }}>{h.score != null ? Number(h.score).toFixed(1) : '—'}</td>
                            <td className="text-center">{h.close != null ? Number(h.close).toFixed(2) : '—'}</td>
                            <td className="text-center">{h.dist_to_break != null ? `${Number(h.dist_to_break).toFixed(1)}%` : '—'}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ===== 主页面 =====
export default function AHorizontalPage() {
  const [market, setMarket] = useState(null);
  const [scanData, setScanData] = useState(null);
  const [items, setItems] = useState([]);
  const [sectors, setSectors] = useState([]);
  const [performance, setPerformance] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);
  const [tradeDate, setTradeDate] = useState('');
  const [filters, setFilters] = useState({
    state: '', grade: '', minScore: '', sector: '',
    sort: 'score', order: 'desc', onlySignal: false, onlyTradable: false,
  });
  const pollRef = useRef(null);

  const loadAll = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    try {
      const q = new URLSearchParams();
      if (filters.state) q.set('state', filters.state);
      if (filters.grade) q.set('grade', filters.grade);
      if (filters.minScore) q.set('min_score', filters.minScore);
      if (filters.sector) q.set('sector', filters.sector);
      if (filters.sort) q.set('sort', filters.sort);
      q.set('order', filters.order);
      if (filters.onlySignal) q.set('only_signal', 'true');
      if (filters.onlyTradable) q.set('only_tradable', 'true');
      q.set('limit', '200');

      const [scanR, mktR, perfR] = await Promise.all([
        apiFetch(`/api/a-horizontal/scan?${q.toString()}`),
        apiFetch('/api/a-horizontal/market'),
        apiFetch('/api/a-horizontal/performance'),
      ]);
      if (scanR.ok) {
        setScanData(scanR.data);
        setItems(scanR.data.items || []);
        setTradeDate(scanR.data.trade_date || '');
      } else {
        setError(scanR.error || '扫描数据加载失败');
      }
      if (mktR.ok) setMarket(mktR.data.market);
      if (perfR.ok) setPerformance(perfR.data.summary || null);
    } catch (e) {
      setError(e.message || '网络错误');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [filters]);

  // 板块列表（从全量数据提取）
  useEffect(() => {
    if (!scanData?.items) return;
    const set = new Set();
    scanData.items.forEach((it) => { if (it.sector) set.add(it.sector); });
    setSectors([...set].sort());
  }, [scanData]);

  useEffect(() => { loadAll(); }, [loadAll]);

  useEffect(() => () => { if (pollRef.current) clearInterval(pollRef.current); }, []);

  const handleRefresh = useCallback(() => {
    setRefreshing(true);
    loadAll(true);
  }, [loadAll]);

  const handleScan = useCallback(async () => {
    if (scanning) return;
    if (!window.confirm('将对全市场重新执行一次横盘扫描（约 1-2 分钟），确认继续？')) return;
    setScanning(true);
    try {
      const { ok, error: err } = await apiFetch('/api/a-horizontal/run', { method: 'POST' });
      if (!ok) { alert('触发失败：' + err); setScanning(false); return; }
      // 轮询扫描状态接口，直到 running 变为 false（扫描完成）
      const t0 = Date.now();
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = setInterval(async () => {
        try {
          const { ok: ok2, data } = await apiFetch('/api/a-horizontal/run/status');
          if (ok2 && !data.running && data.last_done) {
            clearInterval(pollRef.current);
            pollRef.current = null;
            setScanning(false);
            loadAll(true);
          }
        } catch { /* ignore */ }
        if (Date.now() - t0 > 5 * 60 * 1000) {
          clearInterval(pollRef.current);
          pollRef.current = null;
          setScanning(false);
        }
      }, 5000);
    } catch (e) {
      alert('触发失败：' + e.message);
      setScanning(false);
    }
  }, [scanning, loadAll]);

  const totalBoxed = useMemo(
    () => (scanData?.stats ? Object.values(scanData.stats.states || {}).reduce((s, n) => s + n, 0) : 0),
    [scanData]
  );

  return (
    <div className="space-y-2">
      {/* 标题行 */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            📦 横盘蓄势 · 盘后圈股
          </h1>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            板块上涨 + 个股横盘蓄势 + 突破/回踩买点 · 每日盘后自动扫描{tradeDate && ` · 最新交易日 ${tradeDate}`} · 共 {totalBoxed} 只命中
          </div>
        </div>
      </div>

      <MarketCard market={market} loading={loading && !market} />
      <PerformanceCard perf={performance} loading={loading && !performance} />
      <StatsBar stats={scanData?.stats} marketOk={market?.ok} />

      <FilterBar
        filters={filters} setFilters={setFilters}
        sectors={sectors}
        onRefresh={handleRefresh} onScan={handleScan}
        scanning={scanning} refreshing={refreshing}
      />

      <WatchlistResultsTable
        items={items}
        viewModeKey="a-horizontal"
        defaultViewMode="table"
        loading={loading}
        error={error}
        emptyText="当前筛选条件下暂无结果"
        mapSignal={toHorizontalSignal}
        tableProps={{ onSelect: (code) => {
          const it = items.find((i) => i.ts_code === code);
          if (it) setSelected(it);
        } }}
      />

      {/* 底部说明 */}
      <div className="text-[9px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
        说明：① 评分 ≥85 核心候选 / 75-84 重点观察 / 65-74 普通观察，低于 65 分不展示；② 评分高不代表立刻买入，必须同时出现买点信号（A 接近突破 / B 放量突破 / C 回踩确认）；③ 信号 D 突破失败自动移出交易池；④ 首版为盘后圈股 + 人工次日交易，不自动下单。
      </div>

      {selected && <DetailModal item={selected} onClose={() => setSelected(null)} />}
    </div>
  );
}
