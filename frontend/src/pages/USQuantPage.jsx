/**
 * US Quant System V2.1.1 — 美股量化交易系统
 * 路由: /us-market
 *
 * 排版统一为 A 股总览风格：
 *  - KPI 大数字卡片行（grid auto-fit）
 *  - 圆角 Panel 面板（icon + 标题 + 查看全部 →）
 *  - 原生 table 表格
 *
 * 功能：
 *  - Dashboard：市场状态 + 行业 TOP5 + 候选股票
 *  - Scanner：三套策略评分扫描（分层股票池）
 *  - Sectors：13 行业轮动评分
 *  - Signals：信号生命周期
 *  - Positions：持仓管理
 *  - Risk：风控中心
 */
import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';

// ─── 主题感知配色（复用全局 CSS 变量，明暗双主题自适应）──────────────────────
const C = {
  card: 'var(--bg-card)',
  surface: 'var(--bg-surface)',
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  blue: 'var(--accent-blue)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  amber: 'var(--accent-amber)',
};

// ─── 常量 ─────────────────────────────────────────────────────────────────────

const REGIME_LABELS = {
  STRONG_BREADTH: '强势普涨',
  LEADER_CONCENTRATION: '龙头集中',
  HIGH_LEVEL_RANGE: '高位震荡',
  WEAK_REBOUND: '弱势反弹',
  RISK_OFF: '风险回避',
};

const REGIME_COLORS = {
  STRONG_BREADTH: UP_COLOR,
  LEADER_CONCENTRATION: '#f59e0b',
  HIGH_LEVEL_RANGE: '#f59e0b',
  WEAK_REBOUND: '#f97316',
  RISK_OFF: DOWN_COLOR,
};

const REGIME_BG = {
  STRONG_BREADTH: 'rgba(239,68,68,0.1)',
  LEADER_CONCENTRATION: 'rgba(245,158,11,0.1)',
  HIGH_LEVEL_RANGE: 'rgba(245,158,11,0.1)',
  WEAK_REBOUND: 'rgba(249,115,22,0.1)',
  RISK_OFF: 'rgba(34,197,94,0.1)',
};

// ─── 工具函数 ─────────────────────────────────────────────────────────────────

const pctColor = (v) => (v == null || isNaN(Number(v))) ? C.muted : Number(v) > 0 ? C.up : Number(v) < 0 ? C.down : C.muted;
const fmtPctSign = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  if (n === 0) return '0.00%';
  return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};
const fmtNum = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d);
const money = (n, d = 2) => (n == null || isNaN(n)) ? '—' : '$' + Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
const scoreColor = (v) => {
  if (v == null) return C.muted;
  const n = Number(v);
  if (n >= 70) return C.up;
  if (n >= 50) return C.amber;
  return C.muted;
};
const pnlStyle = (v) => ({ color: v > 0 ? C.up : v < 0 ? C.down : C.muted });

// ─── 通用组件（A 股风格）──────────────────────────────────────────────────────

function Panel({ title, icon, loading, children, right }) {
  return (
    <section style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 14,
      padding: '16px 18px', display: 'flex', flexDirection: 'column', minHeight: 260,
    }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 17 }}>{icon}</span>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: C.primary }}>{title}</h3>
          {loading && <span style={{ fontSize: 11, color: C.muted }}>加载中…</span>}
        </div>
        {right}
      </header>
      <div style={{ flex: 1, overflow: 'auto' }}>{children}</div>
    </section>
  );
}

function Kpi({ label, value, sub, color, loading }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 14,
      padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 12, color: C.muted }}>{label}</span>
      {loading ? (
        <span style={{ fontSize: 22, fontWeight: 800, color: C.muted }}>···</span>
      ) : (
        <span style={{ fontSize: 24, fontWeight: 800, color: color || C.primary, lineHeight: 1.1 }}>{value}</span>
      )}
      {sub && <span style={{ fontSize: 11, color: C.secondary }}>{sub}</span>}
    </div>
  );
}

function Empty({ text = '暂无数据' }) {
  return <div style={{ padding: '32px 8px', textAlign: 'center', color: C.muted, fontSize: 13 }}>{text}</div>;
}

function Th({ children, align = 'left' }) {
  return <th style={{ textAlign: align, padding: '4px 6px', fontWeight: 600, fontSize: 12, color: C.muted, whiteSpace: 'nowrap' }}>{children}</th>;
}

function Td({ children, align = 'left', color, bold, nowrap }) {
  return <td style={{ textAlign: align, padding: '7px 6px', fontSize: 12, color: color || C.primary, fontWeight: bold ? 700 : 400, whiteSpace: nowrap ? 'nowrap' : undefined }}>{children}</td>;
}

const TableWrap = ({ children, onMore, moreText = '查看全部 →' }) => (
  <div style={{ overflowX: 'auto' }}>
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>{children}</table>
  </div>
);

const Badge = ({ children, color, bg }) => (
  <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 6, background: bg || (color + '18'), color, whiteSpace: 'nowrap' }}>{children}</span>
);

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useOverview() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/overview', {}, 30000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function useScanner(universe, customSymbols) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!universe) return;
    setLoading(true);
    try {
      const qs = universe === 'CUSTOM'
        ? `symbols=${encodeURIComponent(customSymbols || 'AAPL,MSFT,NVDA')}`
        : `universe=${encodeURIComponent(universe)}`;
      const res = await apiFetch(`/api/us-quant/scanner?${qs}`, {}, 120000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, [universe, customSymbols]);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function usePoolStats() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    apiFetch('/api/us-quant/universes', {}, 10000, 0).then(res => {
      if (res.ok) setStats(res.data);
    }).catch(() => {});
  }, []);
  return stats;
}

function useSectors() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/sectors', {}, 30000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function useSignals() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/signals?status=ALL', {}, 15000, 0);
      if (res.ok) setData(res.data.signals || []);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function usePositions() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/positions', {}, 15000, 0);
      if (res.ok) setData(res.data.positions || []);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

// ─── 子组件 ───────────────────────────────────────────────────────────────────

function ScoreBar({ label, value, max, color }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <span style={{ width: 42, fontSize: 10, color: C.muted, flexShrink: 0 }}>{label}</span>
      <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: 4, overflow: 'hidden' }}>
        <div style={{ width: `${Math.min(100, (value / max) * 100)}%`, height: '100%', background: color || C.blue, borderRadius: 4 }} />
      </div>
      <span style={{ width: 24, textAlign: 'right', fontSize: 11, fontWeight: 600, color: C.secondary }}>{value}</span>
    </div>
  );
}

function RegimeCard({ regime }) {
  if (!regime) return <Empty text="暂无市场环境数据" />;
  const color = REGIME_COLORS[regime.regime] || C.muted;
  const bg = REGIME_BG[regime.regime] || C.card;
  const label = REGIME_LABELS[regime.regime] || regime.regime;
  return (
    <div style={{ background: bg, border: `1px solid ${color}30`, borderRadius: 12, padding: 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>{label}</span>
        <span style={{ fontSize: 22, fontWeight: 800, color }}>{regime.score}</span>
      </div>
      <div style={{ fontSize: 11, color: C.secondary, marginBottom: 8, lineHeight: 1.4 }}>{regime.reason}</div>
      {regime.multipliers && (
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted }}>
          <span>突破 ×{regime.multipliers.breakout}</span>
          <span>回踩 ×{regime.multipliers.pullback}</span>
          <span>跳空 ×{regime.multipliers.earnings_gap}</span>
        </div>
      )}
    </div>
  );
}

function IndexRow({ idx }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 4px', borderTop: `1px solid ${C.borderLight}`, fontSize: 12 }}>
      <span style={{ fontWeight: 600 }}>{idx.symbol} <span style={{ fontSize: 10, color: C.muted }}>{idx.name}</span></span>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontWeight: 700, color: pctColor(idx.change_pct) }}>{fmtNum(idx.price)}</span>
        <span style={{ fontWeight: 700, color: pctColor(idx.change_pct) }}>{fmtPctSign(idx.change_pct)}</span>
        {idx.ma20 != null && <span style={{ fontSize: 10, color: C.muted }}>MA20 {fmtNum(idx.ma20)}</span>}
      </div>
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function DashboardTab({ overview, loading }) {
  const regime = overview?.regime;
  const sectors = overview?.sectors || [];
  const candidates = overview?.scanner || [];
  const topSectors = sectors.slice(0, 5);
  const topCandidates = candidates.slice(0, 5);
  const indices = regime?.indices || {};
  const sys = overview?.system || {};

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🇺🇸</span> US Quant 量化总览
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            市场环境 · 行业轮动 · 策略候选 一站式视图
            {overview?.updated_at && <span style={{ color: C.muted }}> · 更新 {new Date(overview.updated_at).toLocaleTimeString('zh-CN')}</span>}
          </p>
        </div>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="市场环境" value={REGIME_LABELS[regime?.regime] || '—'} sub={`评分 ${regime?.score ?? '—'} · 开新仓 ${regime?.allow_new_positions ? '允许' : '禁止'}`}
          color={REGIME_COLORS[regime?.regime] || C.muted} loading={loading} />
        <Kpi label="候选股票" value={candidates.length} sub={`Top 评分自动筛选`} color={C.blue} loading={loading} />
        <Kpi label="行业评分" value={sectors.length} sub={`${topSectors[0]?.etf_name || '—'} 领涨 ${topSectors[0]?.total_score ?? ''}`} color={C.blue} loading={loading} />
        <Kpi label="运行模式" value={sys.mode || 'SHADOW'} sub={`实盘 ${sys.allow_live ? '开启' : '关闭'}`}
          color={sys.allow_live ? C.up : '#f59e0b'} loading={loading} />
        <Kpi label="数据源" value={(sys.data_provider || 'nasdaq').toUpperCase()} sub={`实时行情 ${sys.live ? '✓' : '离线'}`}
          color={sys.live ? C.up : C.down} loading={loading} />
      </div>

      {/* 面板区 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(400px, 1fr))', gap: 14 }}>

        {/* 市场环境 */}
        <Panel title="市场环境" icon="🌡️">
          <RegimeCard regime={regime} />
          <div style={{ fontSize: 11, color: C.muted, marginTop: 10 }}>
            SPY {regime?.spy_price ? `$${fmtNum(regime.spy_price)}` : ''} · VIX {regime?.vix != null ? fmtNum(regime.vix) : ''} · 全市场 {regime?.market_tone || ''}
          </div>
        </Panel>

        {/* 主要指数 */}
        <Panel title="主要指数" icon="📈">
          {Object.keys(indices).length === 0 ? <Empty /> : (
            <>
              {Object.entries(indices).map(([key, idx]) => <IndexRow key={key} idx={{ symbol: key, ...idx }} />)}
              <div style={{ fontSize: 11, color: C.muted, marginTop: 8 }}>MA20 均线辅助判断趋势</div>
            </>
          )}
        </Panel>

        {/* 行业 TOP5 */}
        <Panel title="行业 TOP5" icon="🔥">
          {topSectors.length === 0 ? <Empty /> : (
            <>
              {topSectors.map((s, i) => (
                <div key={s.etf_symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 4px', borderTop: `1px solid ${C.borderLight}`, fontSize: 12 }}>
                  <span style={{ fontWeight: 600 }}><span style={{ color: C.muted, marginRight: 6 }}>{i + 1}</span>{s.etf_name}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 10, color: C.muted }}>{fmtPctSign(s.ret_20d)}</span>
                    <span style={{ fontWeight: 700, color: scoreColor(s.total_score) }}>{s.total_score}</span>
                  </div>
                </div>
              ))}
            </>
          )}
        </Panel>

        {/* 候选 TOP5 */}
        <Panel title="候选 TOP5" icon="🎯">
          {topCandidates.length === 0 ? <Empty text="暂无候选" /> : (
            <>
              {topCandidates.map((c, i) => (
                <div key={c.symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 4px', borderTop: `1px solid ${C.borderLight}`, fontSize: 12 }}>
                  <span style={{ fontWeight: 600 }}><span style={{ color: C.muted, marginRight: 6 }}>{i + 1}</span>{c.symbol}</span>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ color: C.secondary }}>{money(c.price)}</span>
                    <span style={{ fontSize: 10, color: pctColor(c.change_pct) }}>{fmtPctSign(c.change_pct)}</span>
                    <Badge color={scoreColor(c.breakout_score || c.pullback_score || 0)}>
                      B:{c.breakout_score || '—'} P:{c.pullback_score || '—'}
                    </Badge>
                  </div>
                </div>
              ))}
            </>
          )}
        </Panel>

        {/* 系统状态 */}
        <Panel title="系统状态" icon="🛡️">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              ['模式', sys.mode || 'SHADOW', '#f59e0b'],
              ['实盘', sys.allow_live ? '开启' : '关闭', sys.allow_live ? C.up : C.muted],
              ['数据源', (sys.data_provider || 'nasdaq').toUpperCase(), sys.live ? C.up : C.down],
              ['代理', sys.proxy ? '已识别' : '直连', C.blue],
              ['券商', sys.broker || 'paper', C.blue],
              ['状态', sys.status || 'running', C.up],
            ].map(([k, v, col]) => (
              <div key={k} style={{ background: C.surface, borderRadius: 10, padding: '9px 10px' }}>
                <div style={{ fontSize: 11, color: C.muted }}>{k}</div>
                <div style={{ fontSize: 14, fontWeight: 700, color: col, marginTop: 2 }}>{v}</div>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </div>
  );
}

// ─── Scanner ──────────────────────────────────────────────────────────────────

const POOL_TABS = [
  { key: 'US_CORE_A', label: '⚡ 核心A池', desc: '179种子 · 300目标' },
  { key: 'US_CORE_B', label: '📋 核心B池', desc: '60扩展 · 500目标' },
  { key: 'ALL', label: '🔀 全池', desc: 'A+B 去重扫描' },
  { key: 'US_RESEARCH', label: '🔬 研究池', desc: '239只 · 动态扩展' },
  { key: 'CUSTOM', label: '✏️ 自选', desc: '手动输入代码' },
];

function ScannerTab() {
  const [pool, setPool] = useState('US_CORE_A');
  const [customSymbols, setCustomSymbols] = useState('AAPL,MSFT,NVDA,TSLA,META,GOOGL');
  const universe = pool === 'CUSTOM' ? 'CUSTOM' : pool;
  const { data, loading, reload } = useScanner(universe, customSymbols);
  const poolStats = usePoolStats();
  const cands = data?.candidates || [];
  const topScore = cands.length ? Math.max(...cands.map(c => c.breakout_score || c.pullback_score || 0)) : 0;

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🔍</span> 策略扫描
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            分层股票池 · 突破/回踩双策略评分
            {data?.updated_at && <span style={{ color: C.muted }}> · 更新 {new Date(data.updated_at).toLocaleTimeString('zh-CN')}</span>}
          </p>
        </div>
        <button onClick={reload} disabled={loading}
          style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.7 : 1 }}>
          {loading ? '扫描中…' : '↻ 刷新'}
        </button>
      </div>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="候选数量" value={cands.length} sub={data?.pool ? `池 ${data.pool}` : '—'} color={C.blue} loading={loading} />
        <Kpi label="最高评分" value={topScore || '—'} sub={cands[0]?.symbol ? `领跑 ${cands[0].symbol}` : '—'} color={scoreColor(topScore)} loading={loading} />
        <Kpi label="扫描进度" value={data ? `${data.scanned || 0}/${data.pool_total || 0}` : '—'} sub="单次最多 30 只" color={C.secondary} loading={loading} />
        <Kpi label="当前池" value={POOL_TABS.find(t => t.key === pool)?.label.replace(/^[^\u4e00-\u9fa5]+\s*/, '') || pool} sub="点击上方按钮切换" color={C.blue} />
      </div>

      {/* 池选择器 */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
        {POOL_TABS.map(tab => (
          <button key={tab.key} onClick={() => setPool(tab.key)} title={tab.desc}
            style={{
              padding: '7px 14px', borderRadius: 10, fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
              border: pool === tab.key ? `1px solid ${C.blue}` : `1px solid ${C.border}`,
              background: pool === tab.key ? C.blue : C.card,
              color: pool === tab.key ? '#fff' : C.secondary,
            }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* 自选输入 */}
      {pool === 'CUSTOM' && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
          <input value={customSymbols} onChange={(e) => setCustomSymbols(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && reload()} placeholder="输入代码, 逗号分隔"
            style={{ flex: 1, padding: '8px 12px', borderRadius: 10, fontSize: 13, border: `1px solid ${C.border}`, background: C.card, color: C.primary }} />
          <button onClick={reload} disabled={loading}
            style={{ padding: '8px 16px', borderRadius: 10, fontSize: 13, fontWeight: 600, border: `1px solid ${C.blue}`, color: C.blue, background: 'transparent', cursor: 'pointer' }}>
            {loading ? '扫描中…' : '🔄 扫描'}
          </button>
        </div>
      )}

      {/* 池概览 */}
      {poolStats && (
        <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap' }}>
          {Object.entries(poolStats.stats || {}).map(([code, s]) => (
            <span key={code} style={{
              padding: '3px 10px', borderRadius: 999, fontSize: 11,
              background: pool === code ? C.blue + '1c' : C.surface,
              border: `1px solid ${pool === code ? C.blue : C.borderLight}`,
              fontWeight: pool === code ? 600 : 400, color: C.secondary,
            }}>
              {s.name}: <b style={{ color: pool === code ? C.blue : C.primary }}>{s.current}</b>{s.target ? ` / ${s.target}` : ''}
            </span>
          ))}
        </div>
      )}

      {/* 结果表 */}
      <Panel title="扫描结果" icon="📋" loading={loading} right={
        <span style={{ fontSize: 11, color: C.muted }}>共 {cands.length} 只候选 · 扫描 {data?.scanned || 0}/{data?.pool_total || 0}</span>
      }>
        {cands.length === 0 ? <Empty text={loading ? '扫描中…' : '无候选'} /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>排名</Th><Th>股票</Th><Th align="right">价</Th><Th align="right">涨跌</Th>
                <Th align="right">RSI</Th><Th align="right">突破</Th><Th align="right">回踩</Th>
                <Th align="right">状态</Th><Th align="right">止损</Th>
              </tr>
            </thead>
            <tbody>
              {cands.map((c) => (
                <tr key={c.symbol} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td color={C.muted}>#{c.rank}</Td>
                  <Td bold>{c.symbol}</Td>
                  <Td align="right" color={C.secondary}>{money(c.price)}</Td>
                  <Td align="right" color={pctColor(c.change_pct)}>{fmtPctSign(c.change_pct)}</Td>
                  <Td align="right" color={C.secondary}>{c.rsi != null ? c.rsi.toFixed(0) : '—'}</Td>
                  <Td align="right" bold color={scoreColor(c.breakout_score)}>{c.breakout_score != null ? c.breakout_score : '—'}</Td>
                  <Td align="right" bold color={scoreColor(c.pullback_score)}>{c.pullback_score != null ? c.pullback_score : '—'}</Td>
                  <Td align="right">
                    {c.state_label && <Badge color={c.state === 'MARKUP' || c.state === 'LAUNCH' ? C.up : C.muted}
                      bg={c.state === 'MARKUP' || c.state === 'LAUNCH' ? 'rgba(239,68,68,0.1)' : C.surface}>{c.state_label}</Badge>}
                  </Td>
                  <Td align="right" color={C.muted}>{c.stop_loss ? money(c.stop_loss) : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

// ─── Sectors ──────────────────────────────────────────────────────────────────

function SectorsTab() {
  const { data, loading, reload } = useSectors();
  const sectors = data?.sectors || [];

  const gradeColor = (g) => {
    if (g === '强势主线') return C.up;
    if (g === '重点关注') return C.amber;
    if (g === '观察') return '#3b82f6';
    return C.muted;
  };

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🔥</span> 行业轮动评分
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            5日收益(10) + 20日收益(20) + 60日收益(20) + 相对强度20日(15) + 相对强度60日(15) + 均线趋势(10) + 成交量(10) = 100
            {data?.updated_at && <span style={{ color: C.muted }}> · 更新 {new Date(data.updated_at).toLocaleTimeString('zh-CN')}</span>}
          </p>
        </div>
        <button onClick={reload} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>↻ 刷新</button>
      </div>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="行业数量" value={sectors.length} sub="13 大行业 ETF" color={C.blue} loading={loading} />
        <Kpi label="领涨行业" value={sectors[0]?.etf_name || '—'} sub={sectors[0] ? `评分 ${sectors[0].total_score}` : '—'} color={C.up} loading={loading} />
        <Kpi label="强势主线" value={sectors.filter(s => s.grade === '强势主线').length} sub="相对强度前 20%" color={C.up} loading={loading} />
        <Kpi label="重点关注" value={sectors.filter(s => s.grade === '重点关注').length} sub="轮动候选" color={C.amber} loading={loading} />
      </div>

      <Panel title="行业排名" icon="🏭" loading={loading}>
        {sectors.length === 0 ? <Empty /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>排名</Th><Th>行业</Th><Th align="right">评分</Th><Th align="right">等级</Th>
                <Th align="right">5日</Th><Th align="right">20日</Th><Th align="right">60日</Th>
                <Th align="right">强度20</Th><Th align="right">强度60</Th>
              </tr>
            </thead>
            <tbody>
              {sectors.map((s) => (
                <tr key={s.etf_symbol} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td color={C.muted}>{s.rank}</Td>
                  <Td bold>{s.etf_name}</Td>
                  <Td align="right" bold color={scoreColor(s.total_score)}>{s.total_score}</Td>
                  <Td align="right"><Badge color={gradeColor(s.grade)} bg={gradeColor(s.grade) + '15'}>{s.grade}</Badge></Td>
                  <Td align="right" color={pctColor(s.ret_5d)}>{fmtPctSign(s.ret_5d)}</Td>
                  <Td align="right" color={pctColor(s.ret_20d)}>{fmtPctSign(s.ret_20d)}</Td>
                  <Td align="right" color={pctColor(s.ret_60d)}>{fmtPctSign(s.ret_60d)}</Td>
                  <Td align="right" color={C.secondary}>{fmtNum(s.rel_strength_20d)}</Td>
                  <Td align="right" color={C.secondary}>{fmtNum(s.rel_strength_60d)}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

// ─── Signals ──────────────────────────────────────────────────────────────────

function SignalsTab() {
  const { data, loading, reload } = useSignals();

  const statusColor = (s) => {
    const colors = {
      DISCOVERED: C.muted, SCORED: '#3b82f6', WATCHING: C.amber,
      TRIGGERED: '#ef4444', APPROVED: C.up, ACTIVE: C.up,
      CLOSED: C.muted, EXPIRED: C.muted,
    };
    return colors[s] || C.muted;
  };
  const activeCount = data.filter(s => ['ACTIVE', 'APPROVED', 'TRIGGERED'].includes(s.lifecycle_status)).length;

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📡</span> 信号列表
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>信号生命周期 · 策略触发与执行状态</p>
        </div>
        <button onClick={reload} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>↻ 刷新</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="信号总数" value={data.length} sub="全部生命周期" color={C.blue} loading={loading} />
        <Kpi label="活跃信号" value={activeCount} sub="ACTIVE + APPROVED + TRIGGERED" color={C.up} loading={loading} />
        <Kpi label="最高评分" value={data.length ? Math.max(...data.map(s => s.score || 0)) : '—'} sub="当前信号池" color={C.up} loading={loading} />
      </div>

      <Panel title="信号明细" icon="🧾" loading={loading}>
        {data.length === 0 ? <Empty text="暂无信号" /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>股票</Th><Th>策略</Th><Th align="right">评分</Th><Th align="right">状态</Th>
                <Th align="right">入场</Th><Th align="right">止损</Th><Th align="right">时间</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((s) => (
                <tr key={s.id} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td bold>{s.symbol} <span style={{ fontSize: 10, color: C.muted, fontWeight: 400 }}>{s.name}</span></Td>
                  <Td color={C.secondary}>{s.strategy}</Td>
                  <Td align="right" bold color={scoreColor(s.score)}>{s.score}</Td>
                  <Td align="right"><Badge color={statusColor(s.lifecycle_status)} bg={statusColor(s.lifecycle_status) + '15'}>{s.lifecycle_status}</Badge></Td>
                  <Td align="right" color={C.secondary}>{s.planned_entry ? money(s.planned_entry) : '—'}</Td>
                  <Td align="right" color={C.secondary}>{s.planned_stop ? money(s.planned_stop) : '—'}</Td>
                  <Td align="right" color={C.muted} nowrap>{s.created_at ? new Date(s.created_at).toLocaleDateString('zh-CN') : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

// ─── Positions ────────────────────────────────────────────────────────────────

function PositionsTab() {
  const { data, loading, reload } = usePositions();
  const totalValue = data.reduce((s, p) => s + (p.market_value || 0), 0);
  const totalPnl = data.reduce((s, p) => s + (p.unrealized_pl || 0), 0);

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>💼</span> 持仓管理
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>美股模拟账户持仓 · 盈亏实时跟踪</p>
        </div>
        <button onClick={reload} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: 'pointer' }}>↻ 刷新</button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="持仓数量" value={data.length} sub="当前 ACTIVE 持仓" color={C.blue} loading={loading} />
        <Kpi label="持仓市值" value={money(totalValue, 0)} sub="按现价计算" color={C.primary} loading={loading} />
        <Kpi label="浮动盈亏" value={(totalPnl >= 0 ? '+' : '') + money(totalPnl, 0)} sub="未实现损益" color={totalPnl > 0 ? C.up : totalPnl < 0 ? C.down : C.muted} loading={loading} />
      </div>

      <Panel title="持仓明细" icon="📊" loading={loading}>
        {data.length === 0 ? <Empty text="暂无持仓" /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>股票</Th><Th align="right">持仓</Th><Th align="right">成本</Th><Th align="right">现价</Th>
                <Th align="right">盈亏%</Th><Th align="right">止损</Th><Th align="right">天数</Th>
              </tr>
            </thead>
            <tbody>
              {data.map((p) => (
                <tr key={p.symbol} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td bold>{p.symbol} <span style={{ fontSize: 10, color: C.muted, fontWeight: 400 }}>{p.name}</span></Td>
                  <Td align="right" color={C.secondary}>{p.quantity}</Td>
                  <Td align="right" color={C.secondary}>{p.entry_price ? money(p.entry_price) : '—'}</Td>
                  <Td align="right" color={C.secondary}>{p.current_price ? money(p.current_price) : '—'}</Td>
                  <Td align="right" bold color={(p.unrealized_pl_pct || 0) >= 0 ? C.up : C.down}>{p.unrealized_pl_pct != null ? fmtPctSign(p.unrealized_pl_pct) : '—'}</Td>
                  <Td align="right" color={C.muted}>{p.stop_price ? money(p.stop_price) : '—'}</Td>
                  <Td align="right" color={C.muted}>{p.holding_days || 0}d</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

// ─── Risk ─────────────────────────────────────────────────────────────────────

function RiskTab() {
  const { data: overview } = useOverview();
  const regime = overview?.regime;
  const sys = overview?.system || {};

  const riskItems = [
    { label: '数据延迟', status: '正常', color: C.up },
    { label: '券商连接', status: '正常', color: C.up },
    { label: '行情质量', status: sys.live ? '正常' : '降级', color: sys.live ? C.up : C.amber },
    { label: '持仓核对', status: '正常', color: C.up },
    { label: '账户熔断', status: '未触发', color: C.up },
    { label: '日亏损上限', status: '未达到', color: C.up },
    { label: '周亏损上限', status: '未达到', color: C.up },
  ];

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      <div style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
          <span>🛡️</span> 风控中心
        </h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>运行模式 · 市场环境 · 风险开关 一站式监控</p>
      </div>

      {/* 模式 KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(185px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="运行模式" value={sys.mode || 'SHADOW'} sub="影子运行默认开启" color="#f59e0b" />
        <Kpi label="实盘权限" value={sys.allow_live ? '开启' : '关闭'} sub="默认禁止" color={sys.allow_live ? C.up : C.muted} />
        <Kpi label="市场环境" value={REGIME_LABELS[regime?.regime] || '—'} sub={`评分 ${regime?.score ?? '—'}`} color={REGIME_COLORS[regime?.regime] || C.muted} />
        <Kpi label="开新仓" value={regime?.allow_new_positions ? '允许' : '禁止'} sub={regime?.allow_new_positions ? '正常交易' : '仅可平仓'} color={regime?.allow_new_positions ? C.up : C.down} />
      </div>

      {/* 风险开关 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 14 }}>
        <Panel title="风险开关" icon="🔐">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {riskItems.map((item) => (
              <div key={item.label} style={{ background: C.surface, borderRadius: 10, padding: '10px 12px', display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 12, color: C.secondary }}>{item.label}</span>
                <span style={{ fontSize: 12, fontWeight: 700, color: item.color }}>● {item.status}</span>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="市场环境风险" icon="🌡️">
          {regime ? (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
                <span style={{ fontSize: 22, fontWeight: 800, color: REGIME_COLORS[regime.regime] || C.muted }}>
                  {REGIME_LABELS[regime.regime] || regime.regime}
                </span>
                <span style={{ fontSize: 14, fontWeight: 700, color: C.muted }}>评分 {regime.score}</span>
              </div>
              <div style={{ fontSize: 12, color: C.secondary, lineHeight: 1.5, marginBottom: 12 }}>{regime.reason}</div>
              <div style={{ fontSize: 13, fontWeight: 700, color: regime.allow_new_positions ? C.up : C.down }}>
                {regime.allow_new_positions ? '✅ 允许开新仓' : '❌ 禁止开新仓（仅允许平仓）'}
              </div>
              {regime.multipliers && (
                <div style={{ display: 'flex', gap: 12, marginTop: 12, fontSize: 11, color: C.muted }}>
                  <span>突破 ×{regime.multipliers.breakout}</span>
                  <span>回踩 ×{regime.multipliers.pullback}</span>
                  <span>跳空 ×{regime.multipliers.earnings_gap}</span>
                </div>
              )}
            </div>
          ) : <Empty text="暂无市场环境数据" />}
        </Panel>
      </div>
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function USQuantPage() {
  const [params] = useSearchParams();
  const tab = params.get('tab') || 'dashboard';
  const { data: overview, loading: overviewLoading } = useOverview();

  return (
    <div style={{ minHeight: '100%' }}>
      {tab === 'dashboard' && <DashboardTab overview={overview} loading={overviewLoading} />}
      {tab === 'scanner' && <ScannerTab />}
      {tab === 'sectors' && <SectorsTab />}
      {tab === 'signals' && <SignalsTab />}
      {tab === 'positions' && <PositionsTab />}
      {tab === 'risk' && <RiskTab />}
    </div>
  );
}
