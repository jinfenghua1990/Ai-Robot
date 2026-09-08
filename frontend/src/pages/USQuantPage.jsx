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
import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom';
import { apiFetch, formatApiError } from '../utils/request';
import { toFiniteNumber } from '../utils/format';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import { usNameCN, simplifyUSName } from '../utils/usStockNames';
import { openStockAnalysis } from '../utils/openStockAnalysis';
import FactorBacktestPage from './FactorBacktestPage';
import StrategyScanPage from './StrategyScanPage';
import USStrategyTrackingPage from './USStrategyTrackingPage';

import SinaLink from '../components/SinaLink';
import USWatchlistView from '../components/us/USWatchlistView';
import UniverseMembersView from '../components/us/UniverseMembersView';

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

function PositionDetailRow({ label, value, color }) {
  return (
    <div className="flex items-center justify-between py-1 text-[11px]" style={{ borderBottom: `1px solid ${C.borderLight}` }}>
      <span style={{ color: C.muted }}>{label}</span>
      <span className="font-medium" style={{ color: color || C.primary }}>{formatApiError(value, '—')}</span>
    </div>
  );
}

function PositionDetailSection({ title, icon, children }) {
  return (
    <section className="rounded-lg border p-3" style={{ borderColor: C.border }}>
      <div className="text-[11px] font-bold mb-2" style={{ color: C.blue }}>{icon} {title}</div>
      {children}
    </section>
  );
}

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


// ─── 通用组件（A 股风格）──────────────────────────────────────────────────────

function Panel({ title, icon, loading, children, right }) {
  return (
    <section style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
      padding: '10px 12px', display: 'flex', flexDirection: 'column', minHeight: 0,
    }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 17 }}>{icon}</span>
          <h3 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: C.primary }}>{title}</h3>
          {loading && <span style={{ fontSize: 11, color: C.muted }}>加载中…</span>}
        </div>
        {right}
      </header>
      <div style={{ flex: 1, overflow: 'auto' }}>{children}</div>
    </section>
  );
}

function Kpi({ label, value, sub, color, loading, compact = false }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: compact ? 10 : 12,
      padding: compact ? '8px 10px' : '10px 12px', display: 'flex', flexDirection: 'column', gap: compact ? 2 : 3,
    }}>
      <span style={{ fontSize: compact ? 11 : 12, color: C.muted }}>{label}</span>
      {loading ? (
        <span style={{ fontSize: compact ? 20 : 22, fontWeight: 800, color: C.muted }}>···</span>
      ) : (
        <span style={{ fontSize: compact ? 19 : 21, fontWeight: 800, color: color || C.primary, lineHeight: 1.1 }}>{value}</span>
      )}
      {sub && <span style={{ fontSize: compact ? 10 : 11, color: C.secondary }}>{sub}</span>}
    </div>
  );
}

function Empty({ text = '暂无数据' }) {
  return <div style={{ padding: '32px 8px', textAlign: 'center', color: C.muted, fontSize: 13 }}>{text}</div>;
}

function Th({ children, align = 'left' }) {
  return <th style={{ textAlign: align, padding: '4px 5px', fontWeight: 600, fontSize: 11, color: C.muted, whiteSpace: 'nowrap' }}>{children}</th>;
}

// 表头排序按钮：点击切换排序状态（激活列高亮显 ◀ 提示箭头）
function SortThBtn({ k, sort, toggle, label }) {
  const active = sort.key === k;
  return <button type="button" tabIndex={-1} onClick={(e) => { e.stopPropagation(); toggle(k); }} title={active ? (sort.dir === -1 ? '降序' : '升序') : `按「${label.replace(/ \/ .*/, '')}」排序`} style={{ all: 'unset', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 3, color: active ? C.blue : 'inherit', textAlign: 'left' }}>{label}<span className="font-mono" style={{ fontSize: 9, lineHeight: 1, color: active ? C.blue : C.muted, opacity: active ? 1 : 0.7 }}>{active ? (sort.dir === -1 ? '▼' : '▲') : '↕'}</span></button>;
}

function Td({ children, align = 'left', color, bold, nowrap }) {
  return <td style={{ textAlign: align, padding: '5px 5px', fontSize: 11, color: color || C.primary, fontWeight: bold ? 700 : 400, whiteSpace: nowrap ? 'nowrap' : undefined }}>{children}</td>;
}

const TableWrap = ({ children }) => (
  <div style={{ overflowX: 'auto' }}>
    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>{children}</table>
  </div>
);

const Badge = ({ children, color, bg }) => (
  <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 6, background: bg || (color + '18'), color, whiteSpace: 'nowrap' }}>{children}</span>
);

// ─── Hooks ────────────────────────────────────────────────────────────────────

function useOverview(enabled = true) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/overview', {}, 30000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, [enabled]);
  useEffect(() => { if (enabled) load(); }, [enabled, load]);
  return { data, loading, reload: load };
}

function useScanner(universe, customSymbols, enabled = true) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!enabled || !universe) return;
    setLoading(true);
    try {
      const qs = universe === 'CUSTOM'
        ? `symbols=${encodeURIComponent(customSymbols || 'AAPL,MSFT,NVDA')}`
        : `universe=${encodeURIComponent(universe)}`;
      const res = await apiFetch(`/api/us-quant/scanner?${qs}`, {}, 120000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, [enabled, universe, customSymbols]);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function usePoolStats() {
  const [stats, setStats] = useState(null);
  useEffect(() => {
    apiFetch('/api/market-quant/US/universes', {}, 10000, 0).then(res => {
      if (res.ok) {
        const aliases = {
          US_CORE_A_300: 'US_CORE_A',
          US_CORE_B_500: 'US_CORE_B',
          US_RESEARCH_1000: 'US_RESEARCH',
        };
        const mapped = Object.fromEntries((res.data.universes || []).map(item => [
          aliases[item.code] || item.code,
          { name: item.label, current: item.count, target: item.target },
        ]));
        setStats({ stats: mapped });
      }
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

function useScanSnapshot(enabled = true) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!enabled) return;
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/scan-results', {}, 15000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, [enabled]);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

// ─── 子组件 ───────────────────────────────────────────────────────────────────



function RegimeCard({ regime }) {
  const color = REGIME_COLORS[regime?.regime] || C.muted;
  const bg = REGIME_BG[regime?.regime] || C.card;
  const label = REGIME_LABELS[regime?.regime] || '—';
  return (
    <div style={{ background: bg, border: `1px solid ${color}30`, borderRadius: 10, padding: 10 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 700, color }}>{label}</span>
        <span style={{ fontSize: 22, fontWeight: 800, color }}>{regime?.score != null ? regime.score : '—'}</span>
      </div>
      <div style={{ fontSize: 11, color: C.secondary, marginBottom: 8, lineHeight: 1.4 }}>{regime?.reason || '暂无市场环境数据（等待定时任务采集）'}</div>
      {regime?.multipliers ? (
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted }}>
          <span>突破 ×{regime.multipliers.breakout}</span>
          <span>回踩 ×{regime.multipliers.pullback}</span>
          <span>跳空 ×{regime.multipliers.earnings_gap}</span>
        </div>
      ) : (
        <div style={{ display: 'flex', gap: 10, fontSize: 10, color: C.muted }}>
          <span>突破 ×—</span>
          <span>回踩 ×—</span>
          <span>跳空 ×—</span>
        </div>
      )}
    </div>
  );
}

// ─── Dashboard ────────────────────────────────────────────────────────────────

function DecisionStockRow({ item, kind, onOpen }) {
  const isBuy = kind === 'buy';
  const accent = isBuy ? C.up : C.amber;
  const shortName = usNameCN(item.symbol) || simplifyUSName(item.name) || item.name || '';
  return (
    <div style={{ padding: '9px 0', borderTop: `1px solid ${C.borderLight}`, display: 'flex', alignItems: 'center', gap: 8 }}>
      <div style={{ minWidth: 0, flex: 1 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span style={{ fontSize: 13, fontWeight: 800, color: C.primary }}>{item.symbol}</span>
          <Badge color={accent} bg={accent + '18'}>{isBuy ? '可买入' : '待触发'}</Badge>
          {item.lifecycle && <span style={{ fontSize: 10, color: C.secondary }}>{item.lifecycle}</span>}
        </div>
        {shortName && <div style={{ fontSize: 10, color: C.muted, marginTop: 2, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{shortName}</div>}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 5, fontSize: 10, color: C.secondary }}>
          <span>因子 {item.factor_score != null ? fmtNum(item.factor_score) : '—'}</span>
          <span>趋势 {item.trend_score != null ? fmtNum(item.trend_score) : '—'}</span>
          <span>位置 {item.position_score != null ? fmtNum(item.position_score) : '—'}</span>
          <span>共振 {item.resonance_count || 0} 维</span>
        </div>
      </div>
      <div style={{ textAlign: 'right', flexShrink: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 700, color: C.primary }}>{money(item.price)}</div>
        <button onClick={() => onOpen(item.symbol)} style={{ marginTop: 5, border: `1px solid ${accent}55`, color: accent, background: 'transparent', borderRadius: 6, padding: '3px 7px', fontSize: 10, fontWeight: 600, cursor: 'pointer' }}>看个股 →</button>
      </div>
    </div>
  );
}

function DashboardTab({ overview, loading, reload }) {
  const navigate = useNavigate();
  const regime = overview?.regime;
  const sectors = overview?.sectors || [];
  const topSectors = sectors.slice(0, 5);
  const decision = overview?.decision;
  const buyable = decision?.buyable || [];
  const watch = decision?.watch || [];
  const counts = decision?.counts || {};
  const quality = decision?.data_quality || overview?.data_quality;
  const isReady = decision?.available === true;
  const allowNewPositions = decision?.market_gate?.allow_new_positions;
  const completedAt = decision?.completed_at || overview?.scan?.completed_at || overview?.updated_at;
  const openStock = (symbol) => openStockAnalysis(symbol, 'us');
  const qualityGood = quality?.status === 'VALID';

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🎯</span> 今日盘后决策
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            策略与因子在盘后自动计算；这里只显示可执行和待关注结果
          </p>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <button onClick={() => navigate('/us-market?tab=tracking')} style={{ background: C.card, border: `1px solid ${C.border}`, color: C.secondary, borderRadius: 8, padding: '6px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>重点关注</button>
          <button onClick={() => navigate('/us-market?tab=scanner')} style={{ background: C.card, border: `1px solid ${C.border}`, color: C.secondary, borderRadius: 8, padding: '6px 10px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>策略研究</button>
          <button onClick={reload} disabled={loading} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 10px', fontSize: 12, fontWeight: 600, cursor: loading ? 'wait' : 'pointer', opacity: loading ? 0.7 : 1 }}>{loading ? '读取中…' : '↻ 刷新结果'}</button>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', padding: '7px 10px', marginBottom: 10, borderRadius: 9, background: isReady && qualityGood ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.08)', border: `1px solid ${isReady && qualityGood ? C.up : C.amber}40` }}>
        <span style={{ fontSize: 11, fontWeight: 700, color: isReady && qualityGood ? C.up : C.amber }}>{isReady && qualityGood ? '✓ 盘后任务已完成' : '⏳ 等待盘后决策结果'}</span>
        {decision?.trade_date && <span style={{ fontSize: 11, color: C.secondary }}>交易日 {decision.trade_date}</span>}
        {completedAt && <span style={{ fontSize: 11, color: C.muted }}>更新 {new Date(completedAt).toLocaleString('zh-CN')}</span>}
        {quality?.message && <span style={{ fontSize: 11, color: C.muted }}>{quality.message}</span>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: 8, marginBottom: 10 }}>
        <Kpi label="今日可买入" value={counts.buyable ?? 0} sub="已满足交易状态 TRIGGERED" color={C.up} loading={loading} />
        <Kpi label="关注候选" value={counts.watch ?? 0} sub="因子已确认，等待下一步触发" color={C.amber} loading={loading} />
        <Kpi label="市场许可" value={allowNewPositions === true ? '允许开仓' : allowNewPositions === false ? '暂缓开仓' : '待判定'} sub={decision?.market_gate?.label || REGIME_LABELS[regime?.regime] || '等待市场状态'} color={allowNewPositions === true ? C.up : C.amber} loading={loading} />
        <Kpi label="历史覆盖" value={decision?.valid_count != null ? `${decision.valid_count}/${decision.pool_total || '—'}` : '—'} sub={qualityGood ? '真实历史日线已覆盖' : '等待数据质量达标'} color={qualityGood ? C.blue : C.amber} loading={loading} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 10 }}>
        <Panel title="今日可买入" icon="✅" loading={loading} right={<span style={{ fontSize: 11, color: C.up }}>{counts.buyable ?? 0} 只</span>}>
          {buyable.length === 0 ? <Empty text={isReady ? '本轮没有满足全部交易条件的股票，不建议强行开仓' : '等待盘后统一快照'} /> : buyable.map(item => <DecisionStockRow key={item.symbol} item={item} kind="buy" onOpen={openStock} />)}
        </Panel>
        <Panel title="关注候选" icon="👀" loading={loading} right={<span style={{ fontSize: 11, color: C.amber }}>{counts.watch ?? 0} 只</span>}>
          {watch.length === 0 ? <Empty text={isReady ? '暂无已通过因子确认、等待触发的股票' : '等待盘后统一快照'} /> : watch.map(item => <DecisionStockRow key={item.symbol} item={item} kind="watch" onOpen={openStock} />)}
        </Panel>
      </div>

      {isReady && (
        <div style={{ marginTop: 10, padding: '8px 10px', borderRadius: 9, background: C.surface, border: `1px solid ${C.borderLight}`, fontSize: 11, color: C.secondary, lineHeight: 1.5 }}>
          可买入＝因子共振、风控通过且已触发；关注候选＝已通过因子与风控，但尚待交易触发。{counts.risk_blocked ? `本轮有 ${counts.risk_blocked} 只高分股票被风控排除，不在这里作为候选展示。` : ''}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 10, marginTop: 10 }}>
        <Panel title="市场条件（辅助判断）" icon="🌡️">
          <RegimeCard regime={regime} />
        </Panel>
        <Panel title="强势行业（辅助筛选）" icon="🔥" right={<button onClick={() => navigate('/us-market?tab=sectors')} style={{ border: 'none', background: 'transparent', color: C.blue, fontSize: 11, cursor: 'pointer' }}>查看全部 →</button>}>
          {topSectors.length === 0 ? <Empty text="暂无行业数据" /> : topSectors.slice(0, 3).map((s, i) => (
            <div key={s.etf_symbol} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '7px 2px', borderTop: `1px solid ${C.borderLight}`, fontSize: 11 }}>
              <span style={{ fontWeight: 600 }}><span style={{ color: C.muted, marginRight: 6 }}>{i + 1}</span>{s.etf_name}</span>
              <span style={{ color: scoreColor(s.total_score), fontWeight: 700 }}>{s.total_score}</span>
            </div>
          ))}
        </Panel>
      </div>
    </div>
  );
}

function TrackingTab() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const view = params.get('view') === 'history' ? 'history' : 'watchlist';
  const switchView = (nextView) => navigate(nextView === 'history' ? '/us-market?tab=tracking&view=history' : '/us-market?tab=tracking');

  return (
    <div className="us-tracking-page" style={{ color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 1 }}>
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 800 }}>{view === 'history' ? '🧾 历史信号记录' : '👀 重点关注 · 全市场行业机会'}</h1>
        <span title={view === 'history' ? '查看已经记录的策略信号、评分、入场和止损信息' : '先判断板块是否上升，再研究板块内个股；板块机会门未打开时不优先参与'} style={{ fontSize: 12, color: C.secondary }}>{view === 'history' ? '历史策略信号与入场/止损记录' : '板块优先 · 个股确认'}</span>
      </div>
      <div role="tablist" aria-label="行业机会内容" style={{ display: 'flex', gap: 1, marginBottom: 4, borderBottom: `1px solid ${C.border}` }}>
        {[['watchlist', '行业机会与关注'], ['history', '历史信号记录']].map(([key, label]) => {
          const active = view === key;
          return <button key={key} role="tab" aria-selected={active} onClick={() => switchView(key)} style={{ border: 'none', borderBottom: active ? `2px solid ${C.blue}` : '2px solid transparent', background: 'transparent', color: active ? C.blue : C.secondary, padding: '4px 9px', fontSize: 12, fontWeight: active ? 700 : 500, cursor: 'pointer' }}>{label}</button>;
        })}
      </div>
      {view === 'watchlist' ? <USWatchlistView market="US" showSectorRotation /> : <SignalsTab embedded />}
    </div>
  );
}

// ─── Scanner ──────────────────────────────────────────────────────────────────
// 参考 A 股 StrategyCenterPage 风格：分组 Tab 栏 + 卡片布局 + 状态指示

const SCANNER_GROUPS = [
  {
    key: 'core',
    label: '核心池',
    color: '#ef4444',
    tabs: [
      { key: 'US_CORE_A', label: '核心A池', icon: '⚡', desc: '179种子 · 300目标' },
      { key: 'US_CORE_B', label: '核心B池', icon: '📋', desc: '60扩展 · 500目标' },
    ],
  },
  {
    key: 'full',
    label: '全量池',
    color: '#3b82f6',
    tabs: [
      { key: 'ALL', label: '全池', icon: '🔀', desc: 'A+B 去重扫描' },
      { key: 'US_RESEARCH', label: '研究池', icon: '🔬', desc: '239只 · 动态扩展' },
    ],
  },
  {
    key: 'custom',
    label: '自定义',
    color: '#a855f7',
    tabs: [
      { key: 'CUSTOM', label: '自选', icon: '✏️', desc: '手动输入代码' },
    ],
  },
];

function QuantScannerPanel() {
  const [pool, setPool] = useState('US_CORE_A');
  const [customSymbols, setCustomSymbols] = useState('AAPL,MSFT,NVDA,TSLA,META,GOOGL');
  const universe = pool === 'CUSTOM' ? 'CUSTOM' : pool;
  const useSnapshot = pool === 'US_CORE_A';
  const liveScan = useScanner(universe, customSymbols, !useSnapshot);
  const snapshotScan = useScanSnapshot(useSnapshot);
  const data = useSnapshot ? snapshotScan.data : liveScan.data;
  const loading = useSnapshot ? snapshotScan.loading : liveScan.loading;
  const reload = useSnapshot ? snapshotScan.reload : liveScan.reload;
  const poolStats = usePoolStats();
  const cands = data?.candidates || [];
  const topScore = cands.length ? Math.max(...cands.map(c => c.factor_score ?? c.breakout_score ?? c.pullback_score ?? 0)) : 0;

  // 池描述动态化：name: 当前/target，实时统计优先，硬编码 desc 兜底
  const scannerGroups = useMemo(
    () => SCANNER_GROUPS.map(g => ({
      ...g,
      tabs: g.tabs.map(t => {
        const st = poolStats?.stats?.[t.key];
        const desc = st
          ? `${st.name ? st.name + '：' : ''}${st.current} 只${st.target ? ` / 目标 ${st.target}` : ''}`
          : t.desc;
        return { ...t, desc };
      }),
    })),
    [poolStats]);

  // 当前分组高亮色
  const activeGroup = SCANNER_GROUPS.find(g => g.tabs.some(t => t.key === pool));
  const groupColor = activeGroup?.color || C.blue;

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🔍</span> 策略扫描
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            盘后统一七维因子评分 · 独立维度共振
            {data?.updated_at && <span style={{ color: C.muted }}> · 更新 {new Date(data.updated_at).toLocaleTimeString('zh-CN')}</span>}
            {useSnapshot && data?.trade_date && <span style={{ color: C.muted }}> · 盘后快照 {data.trade_date}</span>}
          </p>
        </div>
        <button onClick={reload} disabled={loading}
          style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.7 : 1 }}>
            {loading ? '读取中…' : useSnapshot ? '↻ 刷新快照' : '↻ 刷新扫描'}
        </button>
      </div>

      {data?.data_quality && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
          marginBottom: 14, borderRadius: 8, flexWrap: 'wrap',
          background: data.data_quality.status === 'VALID' ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.08)',
          border: `1px solid ${(data.data_quality.status === 'VALID' ? C.up : C.amber)}55`,
        }}>
          <span style={{ fontSize: 11, fontWeight: 700, color: data.data_quality.status === 'VALID' ? C.up : C.amber }}>
            {data.data_quality.status === 'VALID' ? '✓ 统一因子快照' : '⏳ 统一因子快照尚未具备评分条件'}
          </span>
          <span style={{ fontSize: 11, color: C.secondary }}>{data.data_quality.message || '页面只读取最近一次盘后结果'}</span>
        </div>
      )}

      {/* KPI 卡片行 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginBottom: 10 }}>
        <Kpi label="候选数量" value={cands.length} sub={data?.pool ? `池 ${data.pool}` : '—'} color={C.blue} loading={loading} />
        <Kpi label="最高评分" value={topScore || '—'} sub={cands[0]?.symbol ? `领跑 ${cands[0].symbol}` : '—'} color={scoreColor(topScore)} loading={loading} />
        <Kpi label="扫描进度" value={data ? `${data.scanned || 0}/${data.pool_total || 0}` : '—'} sub="最近一次盘后快照" color={C.secondary} loading={loading} />
        <Kpi label="当前池" value={SCANNER_GROUPS.flatMap(g => g.tabs).find(t => t.key === pool)?.label.replace(/^[^\u4e00-\u9fa5]+\s*/, '') || pool} sub="点击下方按钮切换" color={C.blue} />
      </div>

      {/* 分组 Tab 栏（参考 A 股 StrategyCenterPage 风格：单行Tab + 分组色 + 下划线指示器） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 14, flexWrap: 'wrap' }}>
        {scannerGroups.map((group, gi) => {
          const showDivider = gi > 0;
          return (
            <div key={group.key} style={{ display: 'flex', alignItems: 'center' }}>
              {showDivider && <span style={{ margin: '0 4px', fontSize: 13, color: C.border }}>|</span>}
              {group.tabs.map((tab) => {
                const isActive = pool === tab.key;
                return (
                  <button key={tab.key} onClick={() => setPool(tab.key)} title={tab.desc}
                    style={{
                      position: 'relative',
                      padding: '7px 12px', fontSize: 12, fontWeight: isActive ? 700 : 500, cursor: 'pointer',
                      background: 'transparent',
                      color: isActive ? group.color : C.secondary,
                      border: 'none',
                      transition: 'all 0.15s ease',
                    }}>
                    <span style={{ fontSize: 13, marginRight: 4 }}>{tab.icon}</span>
                    {tab.label}
                    {isActive && (
                      <span style={{
                        position: 'absolute', left: 6, right: 6, bottom: 0, height: 2.5,
                        background: group.color, borderRadius: '2px 2px 0 0',
                      }} />
                    )}
                  </button>
                );
              })}
            </div>
          );
        })}
      </div>

      {/* 扫描状态摘要（参考 A 股 StrategyHealthBar 风格） */}
      {useSnapshot && !loading && !data?.scan_run && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
          marginBottom: 14, borderRadius: 8, flexWrap: 'wrap',
          background: 'rgba(245,158,11,0.08)', border: `1px solid ${C.amber}55`,
        }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: C.amber }}>⏳ 等待首次盘后扫描</span>
          <span style={{ fontSize: 11, color: C.secondary }}>美股收盘后自动扫描，完成后本页直接读取最近成功快照</span>
        </div>
      )}
      {data?.scan_run && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '6px 12px',
          marginBottom: 14, borderRadius: 8, flexWrap: 'wrap',
          background: C.card, border: `1px solid ${C.border}`,
        }}>
          <span style={{ fontSize: 11, fontWeight: 600, color: C.secondary }}>
            📊 扫描状态
          </span>
          <span style={{ fontSize: 11, color: loading ? '#f59e0b' : '#22c55e' }}>
            {loading ? '⏳ 读取中…' : '✓ 盘后扫描完成'}
          </span>
          <span style={{ fontSize: 11, color: C.muted }}>
            候选 {cands.length} 只 · 扫描 {data.scanned || 0}/{data.pool_total || 0}
          </span>
          {data.updated_at && (
            <span style={{ fontSize: 10, color: C.muted, marginLeft: 'auto' }}>
              更新 {new Date(data.updated_at).toLocaleTimeString('zh-CN')}
            </span>
          )}
        </div>
      )}

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
              background: pool === code ? groupColor + '1c' : C.surface,
              border: `1px solid ${pool === code ? groupColor : C.borderLight}`,
              fontWeight: pool === code ? 600 : 400, color: C.secondary,
            }}>
              {s.name}: <b style={{ color: pool === code ? groupColor : C.primary }}>{s.current}</b>{s.target ? ` / ${s.target}` : ''}
            </span>
          ))}
        </div>
      )}

      {/* 扫描结果卡片（参考 A 股 Panel 风格） */}
      <Panel title="扫描结果" icon="📋" loading={loading} right={
        <span style={{ fontSize: 11, color: C.muted }}>共 {cands.length} 只候选 · 扫描 {data?.scanned || 0}/{data?.pool_total || 0}</span>
      }>
        {cands.length === 0 ? <Empty text={loading ? '读取快照中…' : useSnapshot && !data?.scan_run ? '等待首次盘后扫描' : '最近一次盘后扫描无候选'} /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>排名</Th><Th>股票</Th><Th align="right">价</Th><Th align="right">因子分</Th>
                <Th align="right">趋势</Th><Th align="right">位置</Th><Th align="right">共振</Th>
                <Th align="right">状态</Th><Th align="right">质量</Th>
              </tr>
            </thead>
            <tbody>
              {cands.map((c) => (
                <tr key={c.symbol} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td color={C.muted}>#{c.rank}</Td>
                  <Td bold><span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>{c.symbol}<SinaLink market="US" code={c.symbol} size="xs" /></span>
                    {usNameCN(c.symbol) && <span className="block text-[9px]" style={{ color: C.muted }}>{usNameCN(c.symbol)}</span>}</Td>
                  <Td align="right" color={C.secondary}>{money(c.price)}</Td>
                  <Td align="right" bold color={scoreColor(c.factor_score)}>{c.factor_score != null ? c.factor_score : '—'}</Td>
                  <Td align="right" color={scoreColor(c.breakout_score)}>{c.breakout_score != null ? c.breakout_score : '—'}</Td>
                  <Td align="right" color={scoreColor(c.pullback_score)}>{c.pullback_score != null ? c.pullback_score : '—'}</Td>
                  <Td align="right" color={c.resonance_count >= 4 ? C.up : C.muted}>{c.resonance_count != null ? `${c.resonance_count}/6` : '—'}</Td>
                  <Td align="right">
                    {c.state_label && <Badge color={c.state === 'MARKUP' || c.state === 'LAUNCH' ? C.up : C.muted}
                      bg={c.state === 'MARKUP' || c.state === 'LAUNCH' ? 'rgba(239,68,68,0.1)' : C.surface}>{c.state_label}</Badge>}
                  </Td>
                  <Td align="right" color={c.data_quality === 'VALID' ? C.up : C.amber}>{c.data_quality === 'VALID' ? '真实' : (c.data_quality || '—')}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

function ScannerTab() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const view = params.get('view') === 'tsp' ? 'tsp' : 'quant';

  const switchView = (nextView) => {
    navigate(nextView === 'tsp' ? '/us-market?tab=scanner&view=tsp' : '/us-market?tab=scanner');
  };

  return (
    <div style={{ color: C.primary }}>
      <div role="tablist" aria-label="策略扫描模式" style={{ display: 'flex', gap: 4, marginBottom: 12, borderBottom: `1px solid ${C.border}` }}>
        {[
          ['quant', '量化策略扫描'],
          ['tsp', '传统策略（TSP）'],
        ].map(([key, label]) => {
          const active = view === key;
          return (
            <button key={key} role="tab" aria-selected={active} onClick={() => switchView(key)}
              style={{ border: 'none', borderBottom: active ? `2px solid ${C.blue}` : '2px solid transparent', background: 'transparent', color: active ? C.blue : C.secondary, padding: '7px 12px', fontSize: 12, fontWeight: active ? 700 : 500, cursor: 'pointer' }}>
              {label}
            </button>
          );
        })}
      </div>
      {view === 'tsp' ? <StrategyScanPage market="us" /> : <QuantScannerPanel />}
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
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🔥</span> 行业轮动评分
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            5日收益(10) + 20日收益(20) + 60日收益(20) + 相对强度20日(15) + 相对强度60日(15) + 均线趋势(10) + 成交量(10) = 100
            {data?.updated_at && <span style={{ color: C.muted }}> · 更新 {new Date(data.updated_at).toLocaleTimeString('zh-CN')}</span>}
          </p>
        </div>
        <button onClick={reload} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>↻ 刷新</button>
      </div>

      {/* KPI */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginBottom: 10 }}>
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

function SignalsTab({ embedded = false }) {
  const { data, loading, reload } = useSignals();

  const statusLabel = {
    DISCOVERED: '已发现', SCORED: '已评分', WATCHING: '观察中',
    TRIGGERED: '已触发', APPROVED: '已批准', ACTIVE: '活跃',
    CLOSED: '已关闭', EXPIRED: '已过期',
  };

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
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      {!embedded && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
              <span>📡</span> 历史信号记录
            </h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>历史策略信号与生命周期记录，不作为今日买入依据</p>
          </div>
          <button onClick={reload} style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>↻ 刷新</button>
        </div>
      )}

      {embedded && <div style={{ display: 'flex', justifyContent: 'flex-end', marginBottom: 8 }}><button onClick={reload} style={{ background: C.card, border: `1px solid ${C.border}`, color: C.secondary, borderRadius: 8, padding: '5px 9px', fontSize: 11, cursor: 'pointer' }}>↻ 刷新记录</button></div>}

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginBottom: 10 }}>
        <Kpi label="信号总数" value={data.length} sub="全部生命周期" color={C.blue} loading={loading} />
        <Kpi label="活跃信号" value={activeCount} sub="活跃 + 已批准 + 已触发" color={C.up} loading={loading} />
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
                  <Td bold><span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>{s.symbol} <span style={{ fontSize: 10, color: C.muted, fontWeight: 400 }}>{usNameCN(s.symbol) || simplifyUSName(s.name)}</span><SinaLink market="US" code={s.symbol} size="xs" /></span></Td>
                  <Td color={C.secondary}>{s.strategy}</Td>
                  <Td align="right" bold color={scoreColor(s.score)}>{s.score}</Td>
                  <Td align="right"><Badge color={statusColor(s.lifecycle_status)} bg={statusColor(s.lifecycle_status) + '15'}>{statusLabel[s.lifecycle_status] || s.lifecycle_status || '未知'}</Badge></Td>
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

const positionValue = (p) => {
  if (p.market_value != null) return Number(p.market_value) || 0;
  return (Number(p.current_price) || 0) * (Number(p.quantity) || 0);
};

const positionCost = (p) => {
  if (p.cost_basis != null) return Number(p.cost_basis) || 0;
  return (Number(p.entry_price) || 0) * (Number(p.quantity) || 0);
};

// 从 scanner 信号 + 持仓数据构建表格行
function buildUSRow(pos, sig) {
  const s = sig || {};
  const price = pos.current_price ?? s.price ?? null;
  // 均线结构
  let maStruct = '—';
  const { ema10, ema20, ma50 } = s;
  if (ema10 && ema20 && ma50) {
    if (ema10 > ema20 && ema20 > ma50) maStruct = '多头排列';
    else if (ema10 < ema20 && ema20 < ma50) maStruct = '空头排列';
    else maStruct = '均线纠缠';
  } else if (ema20 && price != null) {
    maStruct = price >= ema20 ? '价>EMA20' : '价<EMA20';
  }
  // MACD
  const macd = s.macd || {};
  let macdTxt = '—';
  if (macd.dif != null && macd.dea != null) {
    macdTxt = macd.dif >= macd.dea ? (macd.dif >= 0 ? '零轴上金叉' : '零轴下金叉') : '死叉';
  }
  // KDJ
  const kdj = s.kdj || {};
  const kdjTxt = kdj.status || '—';
  // 评分
  const score = s.best_factor_score ?? (Math.max(s.breakout_score || 0, s.pullback_score || 0) || null);
  // 状态
  const stateLabel = s.state_label || '—';
  // 因子
  const factorKey = s.best_factor_key || null;
  // 止损
  const stopLoss = s.stop_loss ?? pos.stop_price ?? null;
  // 建议
  let action = '观察';
  if (stateLabel.includes('突破') && (s.breakout_score || 0) >= 70) action = '持有·突破';
  else if (stateLabel.includes('回踩') && (s.pullback_score || 0) >= 70) action = '持有·回踩';
  else if (s.rsi && s.rsi >= 70) action = '注意回调';
  else if (stopLoss && price && price <= stopLoss) action = '止损预警';
  // K/D/J 数值（若美股信号提供）
  const kdjK = toFiniteNumber(kdj.k);
  const kdjD = toFiniteNumber(kdj.d);
  const kdjJ = toFiniteNumber(kdj.j);
  // 板块
  const sector = pos.sector ?? s.sector ?? null;
  // 现价相对 EMA20 的偏离
  const ema20Dist = (ema20 != null && price != null) ? (price - ema20) / ema20 * 100 : null;
  const ema20Above = (ema20 != null && price != null) ? price >= ema20 : null;
  // 风险提示（只在有真实信号时给出）
  const riskHints = [];
  if (s.rsi != null && s.rsi >= 70) riskHints.push({ text: 'RSI超买', tone: 'warn' });
  if (kdjJ != null && kdjJ >= 100) riskHints.push({ text: 'KDJ超买', tone: 'warn' });
  if (ema20Above === false) riskHints.push({ text: '跌破EMA20·止损观察', tone: 'danger' });
  if (/死叉/.test(macdTxt)) riskHints.push({ text: 'MACD死叉·收紧止损', tone: 'danger' });
  if (stopLoss && price && price <= stopLoss) riskHints.push({ text: '触及止损·风控关注', tone: 'danger' });
  return {
    ...pos, maStruct, rsi: s.rsi ?? null, macdTxt, kdjTxt, kdjK, kdjD, kdjJ, score, stateLabel, factorKey, stopLoss,
    action, ema10: toFiniteNumber(ema10), ema20: toFiniteNumber(ema20), ma50: toFiniteNumber(ma50),
    ema20Dist, ema20Above, sector, riskHints, signal: s,
  };
}

// ─── 统一持仓行（盈立真实持仓 18 列技术指标模板）────

const f1 = (v) => (v == null || isNaN(v)) ? '—' : Number(v).toFixed(1);

function PosRow({ r, onSelect, onEdit, onClose, onDelete }) {
  const changePct = (r.current_price != null && r.pre_close) ? (r.current_price - r.pre_close) / r.pre_close * 100 : null;
  const pctText = changePct != null ? fmtPctSign(changePct) : (r.unrealized_pl_pct != null ? fmtPctSign(r.unrealized_pl_pct) : '—');
  const costPrice = r.cost_price ?? r.entry_price;
  const plAmt = r.unrealized_pl ?? r.hold_profit ?? 0;
  const plPct = r.unrealized_pl_pct ?? r.hold_profit_pct;
  const marketValue = r.market_value ?? positionValue(r);
  // 均线结构（美股信号提供 EMA10/EMA20/MA50 数值）
  const maHtml = (
    <div className="font-mono text-[10px]">
      <span style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>E10 {r.ema10 != null ? money(r.ema10) : '—'}</span>
      <span style={{ color: 'var(--border-color)' }}> · </span>
      <span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>E20 {r.ema20 != null ? money(r.ema20) : '—'}</span>
      <span style={{ color: 'var(--border-color)' }}> · </span>
      <span style={{ color: C.muted }}>M50 {r.ma50 != null ? money(r.ma50) : '—'}</span>
    </div>
  );
  return (
    <tr key={r.symbol} onClick={onSelect} className="cursor-pointer" style={{ borderTop: `1px solid ${C.borderLight}` }}>
      {/* 股票（固定左） */}
      <Td bold nowrap>
        <span style={{ color: C.primary }}>{usNameCN(r.symbol) || r.name || r.symbol}</span>
        <span className="block text-[9px]" style={{ color: C.muted }}>{r.symbol}</span>
        <span className="block mt-0.5"><SinaLink market="US" code={r.symbol} size="xs" /></span>
      </Td>
      {/* 数量 */}
      <Td align="right" color={C.secondary} nowrap>
        <span>{r.quantity ?? '—'}</span>
        <span className="block text-[9px]" style={{ color: C.muted }}>持仓金额 {marketValue != null ? money(marketValue, 0) : '—'}</span>
      </Td>
      {/* 现价 / 成本价 */}
      <Td align="left" nowrap>
        <span style={{ color: C.primary, fontWeight: 600 }}>现价 {r.current_price != null ? money(r.current_price) : '—'}</span>
        <span className="block text-[10px]" style={{ color: C.muted }}>成本 {costPrice != null ? money(costPrice) : '—'}</span>
      </Td>
      {/* 当日盈亏 / 当日涨幅 */}
      <Td align="left" nowrap>
        <span style={{ color: (r.today_profit ?? 0) >= 0 ? C.up : C.down, fontWeight: 600 }}>
          {r.today_profit != null ? `${r.today_profit >= 0 ? '+' : ''}${money(r.today_profit, 0)}` : '—'}
        </span>
        <span className="block text-[10px]" style={{ color: pctColor(changePct) }}>涨幅 {pctText}</span>
      </Td>
      {/* 持仓盈亏 / 持仓收益率 */}
      <Td align="left" nowrap>
        <span className="font-bold" style={{ color: plAmt >= 0 ? C.up : C.down }}>{`${plAmt >= 0 ? '+' : ''}${money(plAmt, 0)}`}</span>
        <span className="block text-[10px]" style={{ color: pctColor(plPct) }}>收益 {fmtPctSign(plPct)}</span>
      </Td>
      {/* 仓位 */}
      <Td align="right" color={C.muted} nowrap>—</Td>
      {/* 评分 */}
      <Td align="center">{r.score != null ? <span className="font-bold" style={{ color: r.score >= 70 ? C.up : r.score >= 50 ? C.amber : C.muted }}>{Math.round(r.score)}</span> : <span style={{ color: C.muted }}>—</span>}</Td>
      {/* 均线结构（MA5/20/60） */}
      <Td align="left" nowrap title="美股信号提供 EMA10/EMA20/MA50 数值；排列与现价相对 EMA20 位置由两者比较得出。">
        {maHtml}
        <span style={{ color: r.ema20Above == null ? C.muted : r.ema20Above ? C.up : C.down, fontWeight: 600 }}>
          {r.maStruct} {r.ema20Above != null ? (r.ema20Above ? '· 现价高于 E20' : '· 现价低于 E20') : ''}
          {r.ema20Dist != null ? ` ${r.ema20Dist >= 0 ? '+' : ''}${f1(r.ema20Dist)}%` : ''}
        </span>
      </Td>
      {/* RSI14 */}
      <Td align="center" style={{ color: r.rsi == null ? C.muted : r.rsi >= 70 ? C.up : r.rsi <= 30 ? C.down : C.secondary }}>{r.rsi != null ? r.rsi.toFixed(0) : '—'}</Td>
      {/* MACD状态 */}
      <Td align="left" nowrap style={{ color: /金叉/.test(r.macdTxt) ? C.up : /死叉/.test(r.macdTxt) ? C.down : C.muted }}>{r.macdTxt}</Td>
      {/* KDJ（K/D/J） */}
      <Td align="left" nowrap>
        <div className="font-mono text-[10px]" style={{ color: C.secondary }}>K {f1(r.kdjK)} / D {f1(r.kdjD)} / J {f1(r.kdjJ)}</div>
        <span style={{ color: /超买/.test(r.kdjTxt) ? C.up : /超卖/.test(r.kdjTxt) ? C.down : C.muted }}>{r.kdjTxt}</span>
      </Td>
      {/* 换手率 */}
      <Td align="center" color={C.muted} nowrap>—</Td>
      {/* 个股资金 / 板块 */}
      <Td align="left" nowrap>
        <span style={{ color: C.muted }}>主力 —</span>
        <span className="block text-[10px]" style={{ color: C.secondary }}>{r.sector || '—'}</span>
      </Td>
      {/* 支撑 / 压力位 */}
      <Td align="left" color={C.muted} nowrap>支撑 — · 压力 —</Td>
      {/* 风险提示 */}
      <Td align="left">
        {r.riskHints?.length ? (
          <div className="flex flex-wrap gap-1">
            {r.riskHints.map((h) => <span key={h.text} className="px-1 py-0.5 rounded text-[9px] whitespace-nowrap" style={{ background: h.tone === 'danger' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.14)', color: h.tone === 'danger' ? '#ef4444' : '#d97706' }}>{h.text}</span>)}
          </div>
        ) : <span style={{ color: C.muted }}>暂无明显风险</span>}
      </Td>
      {/* 建议 */}
      <Td align="left" nowrap style={{ color: ACTION_COLOR_US(r.action), fontWeight: 600 }}>{r.action}</Td>
      {/* 操作 */}
      <Td align="center" nowrap>
        <div className="flex items-center justify-center gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); onSelect(); }}
            className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
            style={{ borderColor: C.blue, color: C.blue, background: 'transparent' }}
          >详情</button>
          <button
            onClick={(e) => { e.stopPropagation(); onEdit?.(); }}
            className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
            style={{ borderColor: C.amber, color: C.amber, background: 'transparent' }}
          >编辑</button>
          <button
            onClick={(e) => { e.stopPropagation(); onClose?.(); }}
            className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
            style={{ borderColor: 'var(--flow-down)', color: 'var(--flow-down)', background: 'transparent' }}
          >平仓</button>
          <button
            onClick={(e) => { e.stopPropagation(); onDelete?.(); }}
            className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
            style={{ borderColor: C.border, color: C.muted, background: 'transparent' }}
          >删除</button>
        </div>
      </Td>
      {/* 自动交易（固定右，美股持仓暂无自动交易引擎，占位为关闭） */}
      <Td align="center" nowrap>
        <span className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap" style={{ borderColor: C.border, color: C.muted, background: 'transparent' }}>关闭</span>
      </Td>
    </tr>
  );
}

function HistoryPosRow({ row, onSelect }) {
  const pnl = Number(row.hold_profit) || 0;
  const pnlPct = row.hold_profit_pct;
  const closedAt = row.closed_at || row.synced_at;
  return (
    <tr key={row.symbol} onClick={onSelect} className="cursor-pointer" style={{ borderTop: '1px solid ' + C.borderLight }}>
      <Td bold nowrap>
        <span style={{ color: C.primary }}>{usNameCN(row.symbol) || row.name || row.symbol}</span>
        <span className="block text-[9px]" style={{ color: C.muted }}>{row.symbol}</span>
        <span className="block mt-0.5"><SinaLink market="US" code={row.symbol} size="xs" /></span>
      </Td>
      <Td align="right" color={C.secondary} nowrap>{row.quantity ?? '—'}</Td>
      <Td align="right" color={C.secondary} nowrap>{row.cost_price != null ? money(row.cost_price) : '—'}</Td>
      <Td align="right" color={C.secondary} nowrap>{row.last_price != null ? money(row.last_price) : '—'}</Td>
      <Td align="right" nowrap>
        <span className="font-bold" style={{ color: pnl >= 0 ? C.up : C.down }}>{(pnl >= 0 ? '+' : '') + money(pnl, 2)}</span>
        <span className="block text-[10px]" style={{ color: pctColor(pnlPct) }}>{fmtPctSign(pnlPct)}</span>
      </Td>
      <Td nowrap><Badge color={row.exchange_type === 52 ? C.amber : C.blue}>{row.exchange_type === 52 ? '碎股' : '整股'}</Badge></Td>
      <Td nowrap><Badge color={C.muted} bg={C.muted + '15'}>已关闭</Badge></Td>
      <Td align="right" color={C.muted} nowrap>{closedAt ? new Date(closedAt).toLocaleString('zh-CN') : '—'}</Td>
    </tr>
  );
}

const ACTION_COLOR_US = (a) => {
  const s = String(a || '');
  if (/止损|预警/.test(s)) return '#ef4444';
  if (/回调/.test(s)) return '#f59e0b';
  if (/持有|突破|回踩/.test(s)) return '#22c55e';
  return 'var(--text-muted)';
};

function PositionDetail({ position, onClose }) {
  if (!position) return null;
  const value = positionValue(position);
  const cost = positionCost(position);
  const pnl = Number(position.unrealized_pl) || 0;
  const targets = Array.isArray(position.target_prices) ? position.target_prices.join(' / ') : position.target_prices;
  const sig = position.signal || {};
  const macd = sig.macd || {};
  const kdj = sig.kdj || {};
  const hasTech = !!sig.symbol;
  return (
    <div className="fixed inset-0 z-50 flex justify-end" style={{ background: 'rgba(0,0,0,0.32)' }} onClick={onClose}>
      <aside className="h-full w-[440px] max-w-[94vw] flex flex-col shadow-2xl" style={{ background: C.card, borderLeft: `1px solid ${C.border}` }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b shrink-0" style={{ borderColor: C.border }}>
          <div>
            <div className="text-sm font-bold" style={{ color: C.primary }}>{usNameCN(position.symbol) || position.name || position.symbol}</div>
            <div className="text-[10px]" style={{ color: C.muted }}>{position.symbol} · 美股持仓</div>
          </div>
          <button onClick={onClose} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: C.border, color: C.secondary }}>✕ 关闭</button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          <PositionDetailSection title="持仓信息" icon="📦">
            <PositionDetailRow label="持仓数量" value={`${position.quantity ?? 0} 股`} />
            <PositionDetailRow label="持仓市值" value={money(value, 2)} />
            <PositionDetailRow label="持仓成本" value={money(cost, 2)} />
            <PositionDetailRow label="成本价" value={position.entry_price != null ? money(position.entry_price) : '—'} />
            <PositionDetailRow label="当前价格" value={position.current_price != null ? money(position.current_price) : '—'} />
            <PositionDetailRow label="当前盈亏" value={`${pnl >= 0 ? '+' : ''}${money(pnl, 2)}`} color={pnl >= 0 ? C.up : C.down} />
            <PositionDetailRow label="盈亏比例" value={fmtPctSign(position.unrealized_pl_pct)} color={(position.unrealized_pl_pct ?? 0) >= 0 ? C.up : C.down} />
          </PositionDetailSection>

          {hasTech && (
            <PositionDetailSection title="技术指标" icon="📊">
              <PositionDetailRow label="EMA10 / EMA20" value={[sig.ema10, sig.ema20].map(v => v != null ? money(v) : '—').join(' / ')} />
              <PositionDetailRow label="MA50" value={sig.ma50 != null ? money(sig.ma50) : '—'} />
              <PositionDetailRow label="RSI14" value={sig.rsi != null ? sig.rsi.toFixed(1) : '—'} color={sig.rsi >= 70 ? C.up : sig.rsi <= 30 ? C.down : C.secondary} />
              <PositionDetailRow label="MACD DIF/DEA" value={`${macd.dif != null ? macd.dif : '—'} / ${macd.dea != null ? macd.dea : '—'}`} color={macd.status === '多头' ? C.up : macd.status === '空头' ? C.down : C.muted} />
              <PositionDetailRow label="MACD 状态" value={macd.status || '—'} color={macd.status === '多头' ? C.up : macd.status === '空头' ? C.down : C.muted} />
              <PositionDetailRow label="KDJ 状态" value={kdj.status || '—'} color={/超买/.test(kdj.status) ? C.up : /超卖/.test(kdj.status) ? C.down : C.secondary} />
              <PositionDetailRow label="均线乖离率" value={sig.ma_bias != null ? sig.ma_bias.toFixed(2) + '%' : '—'} color={Math.abs(sig.ma_bias || 0) > 10 ? C.amber : C.secondary} />
              <PositionDetailRow label="7状态" value={sig.state_label || '—'} />
            </PositionDetailSection>
          )}

          {hasTech && (sig.best_factor_key || sig.breakout_score || sig.pullback_score) && (
            <PositionDetailSection title="因子评分" icon="🧮">
              <PositionDetailRow label="最佳因子" value={sig.best_factor_key || '—'} />
              <PositionDetailRow label="因子评分" value={sig.best_factor_score != null ? Math.round(sig.best_factor_score) : '—'} color={sig.best_factor_score >= 70 ? C.up : sig.best_factor_score >= 50 ? C.amber : C.muted} />
              <PositionDetailRow label="突破评分" value={sig.breakout_score != null ? sig.breakout_score.toFixed(1) : '—'} color={sig.breakout_score >= 70 ? C.up : C.muted} />
              <PositionDetailRow label="回踩评分" value={sig.pullback_score != null ? sig.pullback_score.toFixed(1) : '—'} color={sig.pullback_score >= 70 ? C.up : C.muted} />
            </PositionDetailSection>
          )}

          <PositionDetailSection title="交易计划" icon="🎯">
            <PositionDetailRow label="策略" value={position.strategy || '—'} />
            <PositionDetailRow label="行业" value={position.sector || '—'} />
            <PositionDetailRow label="风险组" value={position.risk_group || '—'} />
            <PositionDetailRow label="止损价" value={position.stop_price != null ? money(position.stop_price) : '—'} color={C.down} />
            {hasTech && <PositionDetailRow label="扫描止损" value={sig.stop_loss != null ? money(sig.stop_loss) : '—'} color={C.down} />}
            <PositionDetailRow label="目标价" value={targets || '—'} color={C.up} />
            <PositionDetailRow label="持有天数" value={`${position.holding_days ?? 0} 天`} />
            <PositionDetailRow label="建仓日期" value={position.entry_date || '—'} />
          </PositionDetailSection>

          <PositionDetailSection title="数据状态" icon="🛡️">
            <PositionDetailRow label="状态" value={{ ACTIVE: '活跃', CLOSED: '已关闭', PENDING: '待确认' }[position.status] || position.status || '活跃'} color={C.up} />
            <PositionDetailRow label="更新时间" value={position.updated_at ? new Date(position.updated_at).toLocaleString('zh-CN') : '—'} />
          </PositionDetailSection>
        </div>
        <div className="p-3 border-t shrink-0" style={{ borderColor: C.border }}>
          <a target="_blank" rel="noreferrer" href={`/stock-analysis?code=${encodeURIComponent(position.symbol)}`} className="block w-full rounded-lg py-2 text-center text-xs font-medium no-underline" style={{ background: C.blue, color: '#fff' }}>
            🔍 打开个股分析
          </a>
        </div>
      </aside>
    </div>
  );
}

// 内置持仓新增/编辑弹窗（脱离盈立后手动管理）
function PositionEditModal({ modal, onClose, onSubmit }) {
  const isAdd = modal.mode === 'add';
  const [form, setForm] = useState({
    symbol: modal.symbol || '',
    name: modal.name || '',
    quantity: modal.quantity ?? '',
    cost_price: modal.cost_price ?? '',
  });
  const [busy, setBusy] = useState(false);
  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));
  const submit = async () => {
    const symbol = String(form.symbol || '').trim().toUpperCase();
    const quantity = Number(form.quantity);
    const cost_price = Number(form.cost_price);
    if (!symbol) return window.alert('请输入股票代码');
    if (!Number.isFinite(quantity) || quantity <= 0) return window.alert('请输入正确的持仓数量');
    if (!Number.isFinite(cost_price) || cost_price <= 0) return window.alert('请输入正确的成本价');
    setBusy(true);
    try { await onSubmit({ symbol, name: form.name?.trim() || null, quantity, cost_price }); }
    finally { setBusy(false); }
  };
  const inputStyle = { width: '100%', padding: '6px 8px', fontSize: 12, borderRadius: 6, border: `1px solid ${C.border}`, background: C.surface, color: C.primary, outline: 'none', boxSizing: 'border-box' };
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.42)' }} onClick={busy ? undefined : onClose}>
      <div className="w-[360px] max-w-full rounded-xl border shadow-2xl" style={{ background: C.card, borderColor: C.border }} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: C.border }}>
          <div className="text-sm font-bold" style={{ color: C.primary }}>{isAdd ? '➕ 新增持仓' : `✏️ 编辑持仓 ${modal.symbol}`}</div>
          <button onClick={onClose} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: C.border, color: C.secondary }}>✕</button>
        </div>
        <div className="p-4 space-y-3">
          <div>
            <div className="text-[10px] mb-1" style={{ color: C.muted }}>股票代码（美股，如 NVDA）</div>
            <input value={form.symbol} disabled={!isAdd} onChange={(e) => set('symbol', e.target.value)} placeholder="NVDA" style={{ ...inputStyle, textTransform: 'uppercase', opacity: isAdd ? 1 : 0.6 }} />
          </div>
          <div>
            <div className="text-[10px] mb-1" style={{ color: C.muted }}>名称（留空自动获取）</div>
            <input value={form.name || ''} onChange={(e) => set('name', e.target.value)} placeholder="英伟达" style={inputStyle} />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <div className="text-[10px] mb-1" style={{ color: C.muted }}>持仓数量（股）</div>
              <input type="number" min="0" step="any" value={form.quantity} onChange={(e) => set('quantity', e.target.value)} placeholder="100" style={inputStyle} />
            </div>
            <div>
              <div className="text-[10px] mb-1" style={{ color: C.muted }}>成本价（USD）</div>
              <input type="number" min="0" step="any" value={form.cost_price} onChange={(e) => set('cost_price', e.target.value)} placeholder="120.50" style={inputStyle} />
            </div>
          </div>
        </div>
        <div className="flex justify-end gap-2 px-4 py-3 border-t" style={{ borderColor: C.border }}>
          <button onClick={onClose} className="px-3 py-1.5 rounded-lg border text-xs" style={{ borderColor: C.border, color: C.secondary, background: 'transparent' }}>取消</button>
          <button onClick={submit} disabled={busy} className="px-3 py-1.5 rounded-lg text-xs font-semibold disabled:opacity-50" style={{ background: C.blue, color: '#fff', border: 'none' }}>{busy ? '保存中…' : '保存'}</button>
        </div>
      </div>
    </div>
  );
}

function PositionsTab() {
  const { data: realData, loading: realLoading, reload: reloadReal } = useRealPositions();
  const [signals, setSignals] = useState({});
  const [sigLoading, setSigLoading] = useState(false);
  const [selected, setSelected] = useState(null);
  const [visible, setVisible] = useState(true);
  const [syncMsg, setSyncMsg] = useState('');
  const timerRef = useRef(null);
  // 信号回验
  const [valData, setValData] = useState(null);
  const [valHorizon, setValHorizon] = useState(5);
  // 持仓表列头排序：key=排序键，dir=1升序/-1降序
  const [sort, setSort] = useState({ key: null, dir: -1 });
  const toggleSort = useCallback((key) => {
    setSort((prev) => prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: -1 });
  }, []);

  useEffect(() => {
    let on = true;
    setValData(null);
    apiFetch(`/api/us-quant/signals/validation?horizon=${valHorizon}`, {}, 20000, 0)
      .then((res) => { if (on && res.ok) setValData(res.data); })
      .catch(() => {});
    return () => { on = false; };
  }, [valHorizon]);

  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  // 拉取 scanner 信号（技术指标）
  const loadSignals = useCallback(async (syms) => {
    if (!syms || !syms.length) return;
    setSigLoading(true);
    try {
      const res = await apiFetch(`/api/us-quant/scanner?symbols=${encodeURIComponent(syms.join(','))}`, {}, 60000, 0);
      if (res.ok && res.data?.candidates) {
        const map = {};
        for (const c of res.data.candidates) { if (c.symbol) map[c.symbol] = c; }
        setSignals(map);
      }
    } catch {}
    setSigLoading(false);
  }, []);

  // 自动刷新 30s
  useEffect(() => {
    const interval = visible ? 30000 : 60000;
    timerRef.current = setInterval(() => { reloadReal(); }, interval);
    return () => clearInterval(timerRef.current);
  }, [reloadReal, visible]);

  // 内置持仓操作（新增 / 编辑 / 平仓 / 删除）——已脱离盈立客户端
  const [editModal, setEditModal] = useState(null);
  const submitEdit = async (form) => {
    const isAdd = editModal?.mode === 'add';
    const url = isAdd ? '/api/us-positions' : `/api/us-positions/${encodeURIComponent(editModal.symbol)}`;
    try {
      const res = await apiFetch(url, {
        method: isAdd ? 'POST' : 'PATCH',
        body: JSON.stringify(isAdd ? form : { quantity: form.quantity, cost_price: form.cost_price, name: form.name }),
      }, 30000, 0);
      if (res.ok && res.data?.ok) {
        setEditModal(null);
        setSyncMsg(`✅ ${form.symbol} ${isAdd ? '已新增' : '已更新'}`);
        reloadReal();
      } else {
        setSyncMsg('❌ ' + formatApiError(res.data?.error ?? res.error, '操作失败'));
      }
    } catch { setSyncMsg('❌ 网络错误'); }
  };
  const handleClosePos = async (r) => {
    if (!window.confirm(`确认平仓 ${r.symbol}？将按最新行情快照盈亏并移入历史持仓`)) return;
    try {
      const res = await apiFetch(`/api/us-positions/${encodeURIComponent(r.symbol)}/close`, { method: 'POST' }, 30000, 0);
      if (res.ok && res.data?.ok) { setSyncMsg(`✅ ${r.symbol} 已平仓`); reloadReal(); }
      else setSyncMsg('❌ ' + formatApiError(res.data?.error ?? res.error, '平仓失败'));
    } catch { setSyncMsg('❌ 网络错误'); }
  };
  const handleDeletePos = async (r) => {
    if (!window.confirm(`确认删除 ${r.symbol} 的持仓记录？该操作不可恢复`)) return;
    try {
      const res = await apiFetch(`/api/us-positions/${encodeURIComponent(r.symbol)}`, { method: 'DELETE' }, 15000, 0);
      if (res.ok && res.data?.ok) { setSyncMsg(`✅ ${r.symbol} 已删除`); reloadReal(); }
      else setSyncMsg('❌ ' + formatApiError(res.data?.error ?? res.error, '删除失败'));
    } catch { setSyncMsg('❌ 网络错误'); }
  };

  const realPositions = useMemo(() => realData.positions || [], [realData.positions]);
  const historyPositions = useMemo(() => realData.history || [], [realData.history]);
  // 内置持仓为唯一持仓数据源（已脱离盈立 CDP 同步）
  const totalValue = realPositions.reduce((s, p) => s + (p.market_value || 0), 0);
  const totalCost = realPositions.reduce((s, p) => s + (p.cost_price || 0) * (p.quantity || 0), 0);
  const totalPnl = realPositions.reduce((s, p) => s + (p.hold_profit || 0), 0);
  const lossCount = realPositions.filter((p) => (p.hold_profit || 0) < 0).length;
  const realSyncedAt = realPositions[0]?.synced_at || realData?.last_status?.synced_at || null;

  // 盈立持仓归一化 + scanner 技术指标
  const realRows = useMemo(() => realPositions.map((p) => buildUSRow({
    ...p,
    current_price: p.last_price,
    entry_price: p.cost_price,
    unrealized_pl: p.hold_profit,
    unrealized_pl_pct: p.hold_profit_pct,
  }, signals[p.symbol])), [realPositions, signals]);
  // 盈亏/评分（盈立真实持仓 + scanner 技术指标）排序辅助：评分 / 持仓盈亏 / 当日盈亏（缺失值排最后）
  const sortedRows = useMemo(() => {
    if (!sort.key || !realRows?.length) return realRows;
    return [...realRows].sort((a, b) => {
      const usSortVal = (r) => {
        switch (sort.key) {
          case 'score': return toFiniteNumber(r.score);
          case 'profit': return toFiniteNumber(r.unrealized_pl ?? r.hold_profit);
          case 'dayPnl': return toFiniteNumber(r.today_profit);
          default: return null;
        }
      };
      const va = usSortVal(a);
      const vb = usSortVal(b);
      const na = va == null;
      const nb = vb == null;
      if (na && nb) return 0;
      if (na) return 1;
      if (nb) return -1;
      return (va - vb) * sort.dir;
    });
  }, [realRows, sort]);
  // 今日盈亏（盈立真实持仓：当日已实现 + 浮动）
  const todayPnl = realPositions.reduce((s, p) => s + (p.today_profit || 0), 0);
  const historyPnl = historyPositions.reduce((s, p) => s + (Number(p.hold_profit) || 0), 0);
  // 拉取信号：盈立真实持仓符号去重
  const signalSyms = useMemo(() => {
    const set = new Set();
    realPositions.forEach(p => p.symbol && set.add(p.symbol));
    return [...set];
  }, [realPositions]);

  useEffect(() => {
    if (signalSyms.length) loadSignals(signalSyms);
  }, [signalSyms, loadSignals]);

  return (
    <div className="space-y-3" style={{ color: C.primary }}>
      {/* Sticky 顶栏 */}
      <div className="sticky top-0 z-20 rounded-xl p-2.5 space-y-2" style={{ background: C.card, borderBottom: `2px solid ${C.border}`, boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h1 className="text-lg font-bold flex items-center gap-2 m-0"><span>💼</span> 美股持仓管理
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: C.blue }}>{realPositions.length} 只</span>
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.08)', color: C.down }}>亏损 {lossCount}</span>
            {sigLoading && <span className="text-[10px]" style={{ color: C.muted }}>指标加载中…</span>}
          </h1>
          <div className="flex items-center gap-2">
            <button onClick={reloadReal} disabled={realLoading} className="px-2.5 py-1 rounded-lg border text-xs disabled:opacity-50" style={{ borderColor: C.blue, color: C.blue, background: 'transparent' }}>{realLoading ? '⏳' : '🔄'} 刷新</button>
          </div>
        </div>
        <div className="text-[10px]" style={{ color: C.muted }}>美股真实持仓 · 内置持仓管理（已脱离盈立客户端）· 30秒自动刷新</div>
      </div>

      {/* KPI 卡片（市值/成本/浮动盈亏/今日盈亏/数量） */}
      <div className="grid grid-cols-2 lg:grid-cols-5 gap-2">
        <Kpi label="持仓市值" value={money(totalValue, 0)} sub="按现价计算" color={C.primary} loading={realLoading} />
        <Kpi label="持仓成本" value={money(totalCost, 0)} sub="当前活跃持仓" color={C.blue} loading={realLoading} />
        <Kpi label="浮动盈亏" value={`${totalPnl >= 0 ? '+' : ''}${money(totalPnl, 0)}`} sub={totalCost > 0 ? `收益率 ${((totalPnl / totalCost) * 100).toFixed(2)}%` : '未实现损益'} color={totalPnl > 0 ? C.up : totalPnl < 0 ? C.down : C.muted} loading={realLoading} />
        <Kpi label="今日盈亏" value={`${todayPnl >= 0 ? '+' : ''}${money(todayPnl, 0)}`} sub="当日盈亏" color={todayPnl >= 0 ? C.up : todayPnl < 0 ? C.down : C.muted} loading={realLoading} />
        <Kpi label="持仓数量" value={realPositions.length} sub={`亏损 ${lossCount} 只`} color={C.blue} loading={realLoading} />
      </div>

      {/* 信号回验：历史信号 N 日后实际收益统计（衡量判断对错） */}
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: C.border, background: C.card }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: C.border }}>
          <div className="text-xs font-bold flex items-center gap-2" style={{ color: C.primary }}><span>📈</span> 信号回验
            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.08)', color: C.blue }}>历史命中率 · 样本自动积累</span>
          </div>
          <div className="flex items-center gap-1">
            {[3, 5, 10].map((h) => (
              <button key={h} onClick={() => setValHorizon(h)} className="px-2 py-0.5 rounded text-[10px] border" style={{ borderColor: valHorizon === h ? C.blue : C.border, color: valHorizon === h ? C.blue : C.muted, background: valHorizon === h ? 'rgba(59,130,246,0.08)' : 'transparent' }}>{h}日</button>
            ))}
          </div>
        </div>
        {!valData ? <div className="space-y-2 p-3">{[1, 2].map((i) => <div key={i} className="h-7 rounded animate-pulse" style={{ background: C.surface }} />)}</div> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth: 760 }}>
              <thead>
                <tr style={{ background: C.surface }}>
                  <Th>信号</Th><Th align="center">方向</Th><Th align="center">命中率</Th><Th align="center">样本</Th><Th align="right">上涨占比</Th><Th align="right">下跌占比</Th><Th align="right">平均收益</Th><Th align="right">最大亏损</Th>
                </tr>
              </thead>
              <tbody>
                {valData.baseline && (
                  <tr style={{ borderTop: `1px solid ${C.borderLight}`, background: 'rgba(107,114,128,0.05)' }}>
                    <Td bold>全样本基准</Td><Td align="center">—</Td>
                    <Td align="center" style={{ color: C.secondary }}>{(valData.baseline.up_ratio * 100).toFixed(0)}%</Td>
                    <Td align="center" color={C.secondary}>{valData.baseline.count}</Td>
                    <Td align="right" color={C.secondary}>{(valData.baseline.up_ratio * 100).toFixed(1)}%</Td>
                    <Td align="right" color={C.secondary}>{(valData.baseline.down_ratio * 100).toFixed(1)}%</Td>
                    <Td align="right" style={{ color: pctColor(valData.baseline.mean_ret * 100) }}>{(valData.baseline.mean_ret * 100).toFixed(2)}%</Td>
                    <Td align="right" color={C.down}>{(valData.baseline.max_loss * 100).toFixed(2)}%</Td>
                  </tr>
                )}
                {valData.signals.map((s) => {
                  const hit = s.direction === '看多' ? s.up_ratio : s.direction === '看空' ? s.down_ratio : null;
                  return (
                  <tr key={s.key} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                    <Td bold nowrap>{s.label}</Td>
                    <Td align="center"><Badge color={s.direction === '看多' ? C.up : s.direction === '看空' ? C.down : C.muted}>{s.direction}</Badge></Td>
                    <Td align="center" style={{ color: hit == null ? C.muted : hit >= 0.6 ? C.up : hit <= 0.4 ? C.down : C.secondary }}>{hit != null ? `${(hit * 100).toFixed(0)}%` : '—'}</Td>
                    <Td align="center" color={s.count > 0 && s.count < 30 ? C.amber : C.secondary}>{s.count}{s.count > 0 && s.count < 30 ? '*' : ''}</Td>
                    <Td align="right" color={C.secondary}>{s.up_ratio != null ? `${(s.up_ratio * 100).toFixed(1)}%` : '—'}</Td>
                    <Td align="right" color={C.secondary}>{s.down_ratio != null ? `${(s.down_ratio * 100).toFixed(1)}%` : '—'}</Td>
                    <Td align="right" style={{ color: s.mean_ret != null ? pctColor(s.mean_ret * 100) : C.muted }}>{s.mean_ret != null ? `${(s.mean_ret * 100).toFixed(2)}%` : '—'}</Td>
                    <Td align="right" color={C.down}>{s.max_loss != null ? `${(s.max_loss * 100).toFixed(2)}%` : '—'}</Td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
        <div className="px-3 py-1.5 border-t text-[10px]" style={{ borderColor: C.border, color: C.muted }}>{valData?.note || '…'}</div>
      </div>

      {/* 盈立真实持仓（主视图，以盈立为准） */}
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: C.border, background: C.card }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: C.border }}>
          <div className="text-xs font-bold flex items-center gap-2" style={{ color: C.primary }}><span>💼</span> 美股持仓（内置管理）<span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.08)', color: C.up }}>{realPositions.length} 只</span></div>
          <div className="flex items-center gap-2">
            {realSyncedAt && <span className="text-[10px]" style={{ color: C.muted }}>更新于 {new Date(realSyncedAt).toLocaleString('zh-CN')}</span>}
            {syncMsg && <span className="text-[10px]" style={{ color: syncMsg.startsWith('✅') ? C.up : C.down }}>{syncMsg}</span>}
            <button onClick={() => setEditModal({ mode: 'add', symbol: '', name: '', quantity: '', cost_price: '' })} className="px-2 py-1 rounded-lg border text-[10px] font-semibold" style={{ borderColor: C.blue, color: '#fff', background: C.blue }}>➕ 新增持仓</button>
          </div>
        </div>
        {realData?.last_status?.error && !realData?.last_status?.ok && (
          <div className="px-3 py-2 text-[11px] border-b" style={{ borderColor: `${C.down}55`, background: `${C.down}0d`, color: C.down }}>⚠️ 上次同步未成功：{formatApiError(realData.last_status.error, '同步失败')}</div>
        )}
        {realLoading ? <div className="space-y-2 p-3">{[1, 2].map((i) => <div key={i} className="h-8 rounded animate-pulse" style={{ background: C.surface }} />)}</div> : realPositions.length === 0 ? <Empty text="暂无持仓（点击「新增持仓」手动录入）" /> : (
          <div style={{ overflowX: 'auto' }}>
            <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth: 2100 }}>
            <thead>
          <tr style={{ background: C.surface }}>
            <Th>股票</Th><Th align="right">数量</Th><Th align="left">现价 / 成本价</Th>
            <Th align="left"><SortThBtn k="dayPnl" sort={sort} toggle={toggleSort} label="当日盈亏 / 当日涨幅" /></Th>
            <Th align="left"><SortThBtn k="profit" sort={sort} toggle={toggleSort} label="持仓盈亏 / 持仓收益率" /></Th>
            <Th align="right">仓位</Th>
            <Th align="center"><SortThBtn k="score" sort={sort} toggle={toggleSort} label="评分" /></Th>
            <Th>均线结构（MA5/20/60）</Th><Th align="center">RSI14</Th><Th>MACD状态</Th><Th>KDJ（K/D/J）</Th><Th align="center">换手率</Th><Th>个股资金 / 板块</Th><Th>支撑 / 压力位</Th><Th>风险提示</Th><Th>建议</Th><Th align="center">操作</Th><Th align="center">自动交易</Th>
          </tr>
        </thead>
        <tbody>
          {sortedRows.map((r) => (
            <PosRow key={r.symbol} r={r} onSelect={() => setSelected(r)}
              onEdit={() => setEditModal({ mode: 'edit', symbol: r.symbol, name: r.name, quantity: r.quantity, cost_price: r.cost_price })}
              onClose={() => handleClosePos(r)}
              onDelete={() => handleDeletePos(r)} />
          ))}
        </tbody>
            </table>
          </div>
        )}
        <div className="px-3 py-1.5 border-t text-[10px]" style={{ borderColor: C.border, color: C.muted }}>数据来源：内置持仓管理 → us_real_positions · 现价/市值/盈亏由腾讯实时行情自动刷新（15 秒节流）</div>
      </div>

      {/* 已关闭的历史持仓：来自 us_real_positions 的 CLOSED 记录 */}
      <div className="rounded-xl border overflow-hidden" style={{ borderColor: C.border, background: C.card }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: C.border }}>
          <div className="text-xs font-bold flex items-center gap-2" style={{ color: C.primary }}>
            <span>🗂️</span> 历史持仓
            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(100,116,139,0.12)', color: C.muted }}>{historyPositions.length} 条</span>
          </div>
          <div className="flex items-center gap-3 text-[10px]" style={{ color: C.muted }}>
            <span>已关闭记录</span>
            <span>记录盈亏 {(historyPnl >= 0 ? '+' : '') + money(historyPnl, 0)}</span>
          </div>
        </div>
        {historyPositions.length === 0 ? (
          <Empty text="暂无历史持仓记录（清仓后同步才会归档）" />
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth: 980 }}>
              <thead>
                <tr style={{ background: C.surface }}>
                  <Th>股票</Th><Th align="right">记录数量</Th><Th align="right">成本价</Th><Th align="right">关闭前价格</Th><Th align="right">记录盈亏</Th><Th>类型</Th><Th>状态</Th><Th align="right">关闭时间</Th>
                </tr>
              </thead>
              <tbody>
                {historyPositions.map((row) => (
                  <HistoryPosRow
                    key={row.symbol + '-' + (row.closed_at || row.synced_at || 'history')}
                    row={row}
                    onSelect={() => setSelected({
                      ...row,
                      status: 'CLOSED',
                      current_price: row.last_price,
                      entry_price: row.cost_price,
                      unrealized_pl: row.hold_profit,
                      unrealized_pl_pct: row.hold_profit_pct,
                    })}
                  />
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="px-3 py-1.5 border-t text-[10px]" style={{ borderColor: C.border, color: C.muted }}>
          历史数据来自数据库已关闭记录；“记录盈亏”是平仓时按最新行情快照的持仓盈亏，不等同于券商已结算流水。
        </div>
      </div>

      {selected && <PositionDetail position={selected} onClose={() => setSelected(null)} />}
      {editModal && <PositionEditModal modal={editModal} onClose={() => setEditModal(null)} onSubmit={submitEdit} />}
    </div>
  );
}

// ─── 因子库（V2.3）────────────────────────────────────────────────────────────

function useFactors() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/factors', {}, 15000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function FactorLibraryPanel() {
  const { data, loading } = useFactors();
  const { data: strategies, loading: strategiesLoading } = useStrategies();
  const [symbol, setSymbol] = useState('AAPL');
  const [values, setValues] = useState(null);
  const [calcLoading, setCalcLoading] = useState(false);
  const [activeCat, setActiveCat] = useState('');

  const cats = (data?.categories || {});
  const items = activeCat ? (data?.factors || []).filter(f => f.category === activeCat) : (data?.factors || []);

  const calcValues = async () => {
    setCalcLoading(true);
    setValues(null);
    try {
      const res = await apiFetch(`/api/us-quant/factors/values?symbol=${encodeURIComponent(symbol.trim().toUpperCase())}`, {}, 30000, 0);
      if (res.ok) setValues(res.data);
      else alert('计算失败: ' + formatApiError(res.data?.error ?? res.error, '请求失败'));
    } catch { alert('网络错误'); }
    setCalcLoading(false);
  };

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🧮</span> 因子库
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>Qlib Alpha158/360 · WorldQuant 101 · TA-Lib 共 {data?.count || 0} 个因子</p>
        </div>
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10 }}>
        <input value={symbol} onChange={(e) => setSymbol(e.target.value)}
          placeholder="输入美股代码如 AAPL"
          style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: '6px 10px', fontSize: 12, color: C.primary, width: 160 }} />
        <button onClick={calcValues} disabled={calcLoading}
          style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer' }}>
          {calcLoading ? '⏳ 计算中…' : '🧪 计算因子值'}
        </button>
        {values && (
          <span style={{ fontSize: 12, color: C.muted }}>
            {values.symbol} · {values.count} 个因子值（6个月K线）
          </span>
        )}
      </div>

      <div style={{ marginTop: 14, marginBottom: 10 }}>
        <h2 style={{ margin: 0, fontSize: 15, fontWeight: 800 }}>🎯 因子策略</h2>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: C.secondary }}>由多个因子组合形成的可执行策略，共 {strategies.length} 个</p>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 10 }}>
        {strategies.map((s) => (
          <div key={s.key} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: '10px 12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
              <span style={{ fontSize: 18 }}>{s.icon}</span>
              <span style={{ fontSize: 13, fontWeight: 700, color: C.primary }}>{s.name}</span>
              <Badge color={C.blue} bg={C.blue + '15'}>{s.key}</Badge>
            </div>
            <div style={{ fontSize: 12, color: C.secondary, lineHeight: 1.5 }}>{s.description}</div>
            <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>模块：{s.module} · 函数：{s.func}</div>
          </div>
        ))}
        {!strategiesLoading && strategies.length === 0 && <Empty text="暂无策略" />}
      </div>

      {values && (
        <Panel title={`${values.symbol} 因子值明细`} icon="📊">
          <TableWrap>
            <thead><tr><Th>因子</Th><Th>名称</Th><Th align="right">当前值</Th></tr></thead>
            <tbody>
              {Object.entries(values.values || {}).filter(([, v]) => v !== 0 && v != null).slice(0, 120).map(([k, v]) => (
                <tr key={k} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td bold nowrap>{k}</Td>
                  <Td color={C.muted}>{'—'}</Td>
                  <Td align="right" color={Number(v) > 0 ? C.up : Number(v) < 0 ? C.down : C.muted}>{typeof v === 'number' ? v.toFixed(4) : v}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        </Panel>
      )}

      <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 10 }}>
        <button onClick={() => setActiveCat('')}
          style={{ background: activeCat === '' ? C.blue : C.card, color: activeCat === '' ? '#fff' : C.secondary, border: `1px solid ${activeCat === '' ? C.blue : C.border}`, borderRadius: 8, padding: '4px 10px', fontSize: 11, cursor: 'pointer' }}>
          全部 {data?.count || 0}
        </button>
        {Object.entries(cats).map(([cat, n]) => (
          <button key={cat} onClick={() => setActiveCat(cat)}
            style={{ background: activeCat === cat ? C.blue : C.card, color: activeCat === cat ? '#fff' : C.secondary, border: `1px solid ${activeCat === cat ? C.blue : C.border}`, borderRadius: 8, padding: '4px 10px', fontSize: 11, cursor: 'pointer' }}>
            {cat} {n}
          </button>
        ))}
      </div>

      <Panel title={activeCat || '全部因子'} icon="🗂️" loading={loading}>
        {items.length === 0 ? <Empty text="暂无因子" /> : (
          <TableWrap>
            <thead><tr><Th>因子 KEY</Th><Th>名称</Th><Th>类别</Th><Th>输入</Th></tr></thead>
            <tbody>
              {items.map((f) => (
                <tr key={f.key} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td bold nowrap>{f.key}</Td>
                  <Td color={C.secondary}>{f.name}</Td>
                  <Td><Badge color={C.blue} bg={C.blue + '15'}>{f.category}</Badge></Td>
                  <Td color={C.muted} nowrap>{(f.params || []).join(' + ')}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
    </div>
  );
}

function FactorsTab() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const view = params.get('view') === 'pool' ? 'pool' : 'factors';

  const switchView = (nextView) => {
    navigate(nextView === 'pool' ? '/us-market?tab=factors&view=pool' : '/us-market?tab=factors');
  };

  return (
    <div style={{ color: C.primary }}>
      <div role="tablist" aria-label="因子与股票池" style={{ display: 'flex', gap: 4, marginBottom: 12, borderBottom: `1px solid ${C.border}` }}>
        {[
          ['factors', '因子库'],
          ['pool', '股票池管理'],
        ].map(([key, label]) => {
          const active = view === key;
          return (
            <button key={key} role="tab" aria-selected={active} onClick={() => switchView(key)}
              style={{ border: 'none', borderBottom: active ? `2px solid ${C.blue}` : '2px solid transparent', background: 'transparent', color: active ? C.blue : C.secondary, padding: '7px 12px', fontSize: 12, fontWeight: active ? 700 : 500, cursor: 'pointer' }}>
              {label}
            </button>
          );
        })}
      </div>
      {view === 'pool' ? <UniversesTab /> : <FactorLibraryPanel />}
    </div>
  );
}

// ─── 回测中心（V2.3）─────────────────────────────────────────────────────────

function useBacktestResults() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/backtest/results?limit=50', {}, 15000, 0);
      if (res.ok) setData(res.data.results || []);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function BacktestTab() {
  const { data: results, loading, reload } = useBacktestResults();
  const [params] = useSearchParams();
  const [mode, setMode] = useState(params.get('mode') === 'factor' ? 'factor' : 'strategy');
  const [pool, setPool] = useState('US_WATCHLIST');
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState('');

  const runBacktest = async () => {
    setRunning(true); setMsg('');
    try {
      const res = await apiFetch(`/api/us-quant/backtest?pool_source=${encodeURIComponent(pool)}`, { method: 'POST' }, 300000, 0);
      if (res.ok && res.data.status === 'ok') {
        setMsg(`✅ 回测完成，共 ${res.data.count} 只股票`);
        reload();
      } else {
        setMsg('❌ ' + formatApiError(res.data?.error ?? res.error, '回测失败'));
      }
    } catch (e) { setMsg('❌ 网络错误: ' + (e?.message || '')); }
    setRunning(false);
  };

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>⏪</span> 回测中心
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>按股票池批量回测 · 胜率 / 盈亏比 / 回撤 / Sharpe</p>
        </div>
        <button onClick={reload} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: '6px 12px', fontSize: 12, cursor: 'pointer', color: C.secondary }}>↻ 刷新</button>
      </div>

      <div style={{ display: 'flex', gap: 4, marginBottom: 12, borderBottom: `1px solid ${C.border}` }}>
        {[
          ['strategy', '📋 策略组合回测'],
          ['factor', '🧮 因子研究回测'],
        ].map(([key, label]) => (
          <button key={key} onClick={() => setMode(key)} style={{ border: 'none', borderBottom: mode === key ? `2px solid ${C.blue}` : '2px solid transparent', background: 'transparent', color: mode === key ? C.blue : C.secondary, padding: '7px 12px', fontSize: 12, fontWeight: mode === key ? 700 : 500, cursor: 'pointer' }}>{label}</button>
        ))}
      </div>

      {mode === 'factor' ? <FactorBacktestPage market="us" /> : (
      <>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <select value={pool} onChange={(e) => setPool(e.target.value)}
          style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: '6px 10px', fontSize: 12, color: C.primary }}>
          <option value="US_WATCHLIST">盈立美股自选池（US_WATCHLIST）</option>
          <option value="CORE_A_300">核心A池 (CORE_A_300)</option>
          <option value="CORE_B_500">核心B池 (CORE_B_500)</option>
          <option value="SEED_CORE_179">种子池 (SEED_CORE_179)</option>
        </select>
        <button onClick={runBacktest} disabled={running}
          style={{ background: running ? C.muted : C.up, color: '#fff', border: 'none', borderRadius: 8, padding: '6px 14px', fontSize: 12, fontWeight: 600, cursor: running ? 'wait' : 'pointer' }}>
          {running ? '⏳ 回测中（每只股票约数秒）…' : '▶ 开始回测'}
        </button>
        {msg && <span style={{ fontSize: 12, color: msg.startsWith('✅') ? C.up : C.down }}>{msg}</span>}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8, marginBottom: 10 }}>
        <Kpi label="回测记录" value={results.length} sub="最近 50 条" color={C.blue} loading={loading} />
        <Kpi label="平均胜率" value={results.length ? (results.reduce((s, r) => s + (Number(r.win_rate) || 0), 0) / results.length).toFixed(1) + '%' : '—'} sub="全部记录" color={C.up} loading={loading} />
        <Kpi label="平均盈亏比" value={results.length ? (results.reduce((s, r) => s + (Number(r.profit_factor) || 0), 0) / results.length).toFixed(2) : '—'} sub="profit factor" color={C.amber} loading={loading} />
        <Kpi label="平均回撤" value={results.length ? (results.reduce((s, r) => s + (Number(r.max_drawdown_pct) || 0), 0) / results.length).toFixed(1) + '%' : '—'} sub="max drawdown" color={C.down} loading={loading} />
      </div>

      <Panel title="最近回测结果" icon="📋" loading={loading}>
        {results.length === 0 ? <Empty text="暂无回测记录，点击开始回测" /> : (
          <TableWrap>
            <thead>
              <tr>
                <Th>股票</Th><Th>策略</Th><Th align="right">交易数</Th><Th align="right">胜率</Th>
                <Th align="right">盈亏比</Th><Th align="right">收益%</Th><Th align="right">最大回撤%</Th><Th align="right">Sharpe</Th><Th>时间</Th>
              </tr>
            </thead>
            <tbody>
              {results.map((r, i) => (
                <tr key={i} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                  <Td bold nowrap>{r.symbol}</Td>
                  <Td color={C.secondary}>{r.strategy}</Td>
                  <Td align="right">{r.total_trades}</Td>
                  <Td align="right" bold color={(Number(r.win_rate) || 0) >= 50 ? C.up : C.down}>{r.win_rate != null ? r.win_rate + '%' : '—'}</Td>
                  <Td align="right" color={(Number(r.profit_factor) || 0) >= 1 ? C.up : C.down}>{r.profit_factor != null ? Number(r.profit_factor).toFixed(2) : '—'}</Td>
                  <Td align="right" bold color={(Number(r.total_pnl_pct) || 0) >= 0 ? C.up : C.down}>{r.total_pnl_pct != null ? Number(r.total_pnl_pct).toFixed(2) + '%' : '—'}</Td>
                  <Td align="right" color={C.down}>{r.max_drawdown_pct != null ? Number(r.max_drawdown_pct).toFixed(1) + '%' : '—'}</Td>
                  <Td align="right" color={(Number(r.sharpe_ratio) || 0) >= 0 ? C.up : C.down}>{r.sharpe_ratio != null ? Number(r.sharpe_ratio).toFixed(2) : '—'}</Td>
                  <Td color={C.muted} nowrap>{r.run_at ? r.run_at.slice(0, 10) : '—'}</Td>
                </tr>
              ))}
            </tbody>
          </TableWrap>
        )}
      </Panel>
      </>
      )}
    </div>
  );
}

// ─── 策略注册（V2.3）─────────────────────────────────────────────────────────

function useStrategies() {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/strategies', {}, 10000, 0);
      if (res.ok) setData(res.data.strategies || []);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

// ─── 盈立自选同步（V2.3）─────────────────────────────────────────────────────

function UsmartTab() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [msg, setMsg] = useState('');

  const loadStatus = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/usmart-sync/status', {}, 10000, 0);
      if (res.ok) setStatus(res.data);
    } catch {}
    setLoading(false);
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  const doSync = async () => {
    setSyncing(true); setMsg('');
    try {
      const res = await apiFetch('/api/usmart-sync/sync?markets=US,HK', { method: 'POST' }, 120000, 0);
      if (res.ok && res.data.ok) {
        setMsg('✅ 同步完成');
        loadStatus();
      } else {
        setMsg('❌ ' + formatApiError(res.data?.error ?? res.error, '同步失败'));
        loadStatus();
      }
    } catch { setMsg('❌ 网络错误'); }
    setSyncing(false);
  };

  const loginColor = {
    logged_in: C.up,
    relogin_ok: C.up,
    need_sms: C.amber,
    login_page: C.down,
    no_credentials: C.down,
    failed: C.down,
    disabled: C.amber,
    unknown: C.muted,
  };
  const loginLabel = {
    logged_in: '盈立在线',
    relogin_ok: '自动重登成功',
    need_sms: '需要短信验证',
    login_page: '需要登录',
    no_credentials: '未找到记住的账号',
    failed: '自动登录失败',
    disabled: '自动重登已关闭',
    unknown: '未检测到登录态',
  };
  const positionStatus = status?.positions_status;
  const clientLogin = status?.client_login === 'logged_in' || status?.client_login === 'relogin_ok'
    ? status.client_login
    : positionStatus?.login === 'need_sms'
      ? 'need_sms'
      : status?.client_login || status?.login;
  const syncHint = status?.error || positionStatus?.error;

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 17, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 6 }}>
            <span>⭐</span> 盈立自选同步
          </h1>
          <p style={{ margin: '2px 0 0', fontSize: 11.5, color: C.secondary }}>从盈立（uSMART）客户端读取自选股并同步到股票池</p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginLeft: 'auto' }}>
          <button onClick={doSync} disabled={syncing}
            style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 7, padding: '6px 11px', fontSize: 11.5, fontWeight: 600, cursor: syncing ? 'wait' : 'pointer', opacity: syncing ? 0.75 : 1 }}>
            {syncing ? '⏳ 同步中…' : '🔄 立即同步美股 + 港股'}
          </button>
          <button onClick={loadStatus} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 7, padding: '5px 9px', fontSize: 11, cursor: 'pointer', color: C.secondary }}>↻ 刷新状态</button>
          {msg && <span style={{ fontSize: 11, color: msg.startsWith('✅') ? C.up : C.down }}>{msg}</span>}
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(145px, 1fr))', gap: 6, marginBottom: 8 }}>
        <Kpi compact label="美股自选" value={status?.US?.count ?? '—'} sub="美股自选池（US_WATCHLIST）" color={C.blue} loading={loading} />
        <Kpi compact label="港股自选" value={status?.HK?.count ?? '—'} sub="港股自选池（HK_WATCHLIST）" color={C.amber} loading={loading} />
        <Kpi compact label="客户端登录态" value={loginLabel[clientLogin] || clientLogin || '—'} sub={syncHint ? formatApiError(syncHint, '同步失败') : status?.cdp_available === false ? (status?.cdp_reason || '未发现盈立调试通道（9222）') : '自动同步依赖盈立客户端保持登录'} color={loginColor[clientLogin] || C.muted} loading={loading} />
        <Kpi compact label="上次同步" value={status?.synced_at ? status.synced_at.slice(0, 16).replace('T', ' ') : '—'} sub={status?.source || 'cdp'} color={C.secondary} loading={loading} />
      </div>

      <div style={{ fontSize: 10.5, color: C.muted, lineHeight: 1.4, marginBottom: 6 }}>
        说明：通过 CDP 调试通道读取盈立客户端（需保持客户端开启）；<br />
        若手机端登录导致电脑端掉线，同步时自动重新登录（USMART_AUTO_RELOGIN=0 可关闭自动重登）。{' '}
        <a href="/hk-market?tab=watchlist" style={{ color: C.blue, textDecoration: 'none' }}>查看港股自选清单 →</a>
      </div>

      <div style={{ marginTop: 8, fontSize: 11, color: C.secondary }}>同步完成后，请到「重点关注」查看和管理美股自选。</div>
    </div>
  );
}

// ─── 美股持仓（内置管理，已脱离盈立客户端）────────────────────────────────

function useRealPositions() {
  const [data, setData] = useState({ positions: [], history: [], last_status: null });
  const [loading, setLoading] = useState(false);
  const normalize = (value) => {
    if (!value || typeof value !== 'object') return null;
    const item = { ...value };
    item.symbol = formatApiError(value.symbol, '');
    item.name = formatApiError(value.name, '');
    item.status = formatApiError(value.status, '');
    ['quantity', 'cost_price', 'last_price', 'pre_close', 'market_value', 'hold_profit', 'hold_profit_pct', 'today_profit', 'exchange_type'].forEach((key) => {
      if (item[key] != null) {
        const n = Number(item[key]);
        item[key] = Number.isFinite(n) ? n : null;
      }
    });
    return item;
  };
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-positions?include_history=true&refresh=1', {}, 30000, 0);
      if (res.ok) {
        const payload = res.data && typeof res.data === 'object' ? res.data : {};
        setData({
          ...payload,
          positions: Array.isArray(payload.positions) ? payload.positions.map(normalize).filter(Boolean) : [],
          history: Array.isArray(payload.history) ? payload.history.map(normalize).filter(Boolean) : [],
        });
      }
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

// ─── 股票池管理（V2.3）───────────────────────────────────────────────────────

function useUniverses() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch('/api/us-quant/universes', {}, 10000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

function UniversesTab() {
  const { data, loading, reload } = useUniverses();
  const [selCode, setSelCode] = useState('');
  const unis = data?.universes || [];

  // 进入页面默认选中第一个池
  useEffect(() => {
    if (!selCode && unis.length) setSelCode(unis[0].code);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unis]);

  return (
    <div style={{ padding: 0, maxWidth: 'none', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>🗂️</span> 股票池管理
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>池 Tab 切换 · 点击查看成员，卡片/表格双视图 + 算法自动评估每只股票</p>
        </div>
        <button onClick={reload} style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 8, padding: '6px 12px', fontSize: 12, cursor: 'pointer', color: C.secondary }}>↻ 刷新</button>
      </div>

      {/* 池 Tab 栏（点击切换，自动评估成员） */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 0, borderBottom: `1px solid ${C.border}`, marginBottom: 14, flexWrap: 'wrap' }}>
        {unis.map((u) => {
          const isActive = selCode === u.code;
          return (
            <button key={u.code} onClick={() => setSelCode(u.code)} title={`${u.name} · ${u.description}`}
              style={{ position: 'relative', padding: '7px 12px', fontSize: 12, fontWeight: isActive ? 700 : 500, cursor: 'pointer', background: 'transparent', color: isActive ? C.blue : C.secondary, border: 'none', transition: 'all 0.15s ease' }}>
              <span style={{ fontSize: 13 }}>{u.code}</span>
              <span className="ml-1 text-[10px]" style={{ color: isActive ? C.blue : C.muted }}>{u.count}/{u.target || '∞'}</span>
              {isActive && (
                <span style={{ position: 'absolute', left: 6, right: 6, bottom: 0, height: 2.5, background: C.blue, borderRadius: '2px 2px 0 0' }} />
              )}
            </button>
          );
        })}
        {!loading && unis.length === 0 && <Empty text="暂无股票池" />}
      </div>

      {/* 选中池的成员：像 usmart 自选清单一样，卡片（按板块分组）/ 表格双视图 */}
      {selCode && (
        <div style={{ marginTop: 4 }}>
          <UniverseMembersView
            key={selCode}
            universeCode={selCode}
            market="US"
            onChanged={reload}
          />
        </div>
      )}
    </div>
  );
}

// ─── 主页面 ───────────────────────────────────────────────────────────────────

export default function USQuantPage({ forcedTab = null } = {}) {
  const [params] = useSearchParams();
  const tab = forcedTab || params.get('tab') || 'dashboard';
  const overviewEnabled = tab === 'dashboard';
  const { data: overview, loading: overviewLoading, reload: reloadOverview } = useOverview(overviewEnabled);

  return (
    <div style={{ minHeight: '100%' }}>
      {tab === 'dashboard' && <DashboardTab overview={overview} loading={overviewLoading} reload={reloadOverview} />}
      {tab === 'scanner' && <ScannerTab />}
      {tab === 'sectors' && <Navigate to="/us-market?tab=tracking" replace />}
      {tab === 'tracking' && <TrackingTab />}
      {tab === 'strategy-tracking' && <USStrategyTrackingPage />}
      {tab === 'signals' && <Navigate to="/us-market?tab=tracking&view=history" replace />}
      {tab === 'positions' && <PositionsTab />}
      {(tab === 'risk' || tab === 'system' || tab === 'health') && <Navigate to="/quality?section=risk" replace />}
      {tab === 'factors' && <FactorsTab />}
      {tab === 'backtest' && <BacktestTab />}
      {/* 旧策略库链接保留兼容，统一跳转到因子库 */}
      {tab === 'strategies' && <Navigate to="/us-market?tab=factors" replace />}
      {tab === 'usmart' && <UsmartTab />}
      {tab === 'universes' && <Navigate to="/us-market?tab=factors&view=pool" replace />}
    </div>
  );
}
