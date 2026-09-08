import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, DOWN_DARK, UP_DARK } from '../utils/colors';
import SinaLink from '../components/SinaLink';

/**
 * 港股策略扫描页面（优化版）
 * - 左侧：规则按「类别」分组 + 一键预设组合 + 命中分布
 * - 右侧：信号汇总 KPI + 命中标的（强度徽章 + 迷你走势 + 排序 + 跳转）
 */

// 规则类别（用于左侧分组展示）
const RULE_CATEGORIES = [
  { key: 'revert', label: '回踩 / 反转', members: ['deviation_revert'] },
  { key: 'rsi', label: '超买超卖 (RSI)', members: ['rsi_oversold', 'rsi_overbought'] },
  { key: 'align', label: '均线排列', members: ['bull_align', 'bear_align'] },
  { key: 'momentum', label: '区间动量', members: ['5d_pullback', '5d_breakout', '20d_uptrend', '20d_downtrend'] },
  { key: 'vol', label: '成交量', members: ['volume_active'] },
];

// 一键预设组合（rules=null 表示全部启用）
const PRESETS = [
  { key: 'all', label: '全部规则', rules: null },
  { key: 'rebound', label: '超跌反弹', rules: ['rsi_oversold', '5d_pullback', 'deviation_revert'] },
  { key: 'momentum', label: '动量突破', rules: ['5d_breakout', '20d_uptrend', 'bull_align'] },
  { key: 'trend', label: '趋势跟踪', rules: ['bull_align', '20d_uptrend', 'deviation_revert'] },
];

// 迷你走势图
function Sparkline({ points, color }) {
  if (!points || points.length < 2) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const vals = points.map(p => (typeof p === 'object' ? p.c : p)).filter(v => v != null).map(Number);
  if (vals.length < 2) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const min = Math.min(...vals), max = Math.max(...vals);
  const span = max - min || 1;
  const w = 64, h = 20, pad = 2;
  const step = (w - pad * 2) / (vals.length - 1);
  const coords = vals.map((v, i) => {
    const x = pad + i * step;
    const y = pad + (h - pad * 2) * (1 - (v - min) / span);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline points={coords} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
}

function strengthBadge(hits) {
  if (hits >= 3) return { label: '强', color: UP_COLOR };
  if (hits === 2) return { label: '中', color: '#f59e0b' };
  return { label: '弱', color: 'var(--text-muted)' };
}

const DIMENSION_LABELS = {
  market: '市场',
  sector: '板块',
  strength: '强度',
  trend: '趋势',
  volume_price: '量价',
  position: '位置',
  risk: '风险',
};

const TRADING_STATE_LABELS = {
  WATCH: '观察',
  READY: '准备',
  TRIGGERED: '已触发',
  HOLD: '持有',
  NO_CHASE: '禁止追高',
  INVALID: '失效',
};

function dimensionScore(dimensions, key) {
  const dimension = dimensions?.[key];
  if (!dimension?.valid || dimension.score == null) return '—';
  return Number(dimension.score).toFixed(0);
}

function UnifiedSnapshotTable({ items, loading, scanned, error, onRetry, navigate }) {
  const rows = [...(items || [])].sort((a, b) => (b.factor_score ?? -Infinity) - (a.factor_score ?? -Infinity));

  return (
    <div className="rounded-md overflow-auto" style={{ minHeight: 'calc(100vh - 240px)', background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="p-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
        <div>
          <h2 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
            📊 统一七维因子结果 ({rows.length})
            <span className="ml-1 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>/ 有效历史 {scanned || 0} 只</span>
          </h2>
          <div className="text-[9px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            按因子综合得分排序 · 风险只作否决闸门 · 旧 RSI/均线规则仅作为研究对照
          </div>
        </div>
        <span className="text-[9px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>点击行查看个股分析</span>
      </div>

      {error && (
        <div className="p-3 text-center text-xs" style={{ color: 'var(--text-danger, #E24B4A)' }}>
          ❌ {error}
          <button onClick={onRetry} className="ml-2 underline">重试</button>
        </div>
      )}

      <table className="w-full text-xs" style={{ minWidth: 920, tableLayout: 'fixed' }}>
        <thead>
          <tr style={{ background: 'var(--bg-secondary)', borderBottom: '1px solid var(--border-color)' }}>
            {[
              ['股票', '22%'], ['因子综合得分', '10%'], ['市场/板块/强度', '16%'],
              ['趋势/量价', '14%'], ['位置/风险', '14%'], ['共振', '8%'],
              ['交易状态', '11%'], ['失败维度', 'auto'], ['质量', '8%'],
            ].map(([label, width]) => (
              <th key={label} className="px-1.5 py-1.5 whitespace-nowrap font-medium" style={{ color: 'var(--text-muted)', textAlign: label === '股票' || label === '失败维度' ? 'left' : 'center', width }}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && rows.length === 0 ? Array.from({ length: 6 }).map((_, i) => (
            <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
              {Array.from({ length: 9 }).map((__, j) => (
                <td key={j} className="px-1.5 py-2"><div className="h-4 animate-pulse rounded" style={{ background: 'var(--bg-secondary)', width: `${55 + (j * 11) % 38}px` }} /></td>
              ))}
            </tr>
          )) : rows.length === 0 ? (
            <tr><td colSpan={9} className="text-center py-8 px-4" style={{ color: 'var(--text-muted)' }}>
              {error ? '' : '暂无可用的统一因子结果；请先完成港股历史数据补采并运行盘后扫描。'}
            </td></tr>
          ) : rows.map((item, index) => {
            const dimensions = item.dimension_scores || item.dimensions || {};
            const state = item.trading_state || 'WATCH';
            const stateColor = state === 'TRIGGERED' || state === 'READY' ? UP_COLOR : state === 'INVALID' ? DOWN_COLOR : state === 'NO_CHASE' ? '#f59e0b' : 'var(--text-secondary)';
            const quality = item.data_quality || 'UNKNOWN';
            const qualityColor = quality === 'VALID' ? UP_COLOR : quality === 'INSUFFICIENT' ? '#f59e0b' : DOWN_COLOR;
            const failed = item.failed_dimensions || [];
            return (
              <tr key={item.code || item.symbol || index} className="hover:opacity-80 cursor-pointer transition-colors" style={{ borderBottom: '1px solid var(--border-color)' }} onClick={() => navigate(`/stock/${item.code || item.symbol}`)}>
                <td className="px-1.5 py-1.5">
                  <div className="font-bold text-xs" style={{ color: 'var(--text-primary)' }}>{item.name || item.code || item.symbol}
                    <SinaLink market="HK" code={item.code || item.symbol} size="xs" />
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{item.code || item.symbol} · {item.currency || 'HKD'}</div>
                </td>
                <td className="px-1.5 py-1.5 text-center">
                  <div className="font-bold text-sm" style={{ color: item.factor_score == null ? 'var(--text-muted)' : UP_COLOR }}>{item.factor_score == null ? '—' : Number(item.factor_score).toFixed(1)}</div>
                  <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{item.lifecycle || '—'}</div>
                </td>
                <td className="px-1.5 py-1.5 text-center" title={['market', 'sector', 'strength'].map(k => `${DIMENSION_LABELS[k]}: ${dimensionScore(dimensions, k)}`).join(' · ')}>
                  <span style={{ color: dimensions.market?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'market')}</span>
                  <span className="mx-0.5" style={{ color: 'var(--border-color)' }}>/</span>
                  <span style={{ color: dimensions.sector?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'sector')}</span>
                  <span className="mx-0.5" style={{ color: 'var(--border-color)' }}>/</span>
                  <span style={{ color: dimensions.strength?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'strength')}</span>
                </td>
                <td className="px-1.5 py-1.5 text-center" title={['trend', 'volume_price'].map(k => `${DIMENSION_LABELS[k]}: ${dimensionScore(dimensions, k)}`).join(' · ')}>
                  <span className="font-medium" style={{ color: dimensions.trend?.valid ? UP_COLOR : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'trend')}</span>
                  <span className="mx-0.5" style={{ color: 'var(--border-color)' }}>/</span>
                  <span style={{ color: dimensions.volume_price?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'volume_price')}</span>
                </td>
                <td className="px-1.5 py-1.5 text-center" title={['position', 'risk'].map(k => `${DIMENSION_LABELS[k]}: ${dimensionScore(dimensions, k)}`).join(' · ')}>
                  <span style={{ color: dimensions.position?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'position')}</span>
                  <span className="mx-0.5" style={{ color: 'var(--border-color)' }}>/</span>
                  <span style={{ color: dimensions.risk?.valid ? 'var(--text-secondary)' : 'var(--text-muted)' }}>{dimensionScore(dimensions, 'risk')}</span>
                </td>
                <td className="px-1.5 py-1.5 text-center">
                  <span className="inline-flex items-center justify-center px-1.5 py-0.5 rounded text-[10px] font-bold" style={{ background: `${UP_COLOR}18`, color: UP_COLOR }}>{item.resonance_count ?? 0}/6</span>
                </td>
                <td className="px-1.5 py-1.5 text-center">
                  <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: `${stateColor}18`, color: stateColor }}>{TRADING_STATE_LABELS[state] || state}</span>
                </td>
                <td className="px-1.5 py-1.5 text-[10px]" style={{ color: failed.length ? '#f59e0b' : 'var(--text-muted)' }}>{failed.length ? failed.map(k => DIMENSION_LABELS[k] || k).join('、') : '—'}</td>
                <td className="px-1.5 py-1.5 text-center"><span style={{ color: qualityColor }}>{quality === 'VALID' ? '真实' : quality === 'INSUFFICIENT' ? '不足' : quality}</span></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function HKStrategyPage({ snapshot = null, snapshotReady = false, snapshotLoading = false, snapshotError = '', onRefresh }) {
  const navigate = useNavigate();
  const [manualMode, setManualMode] = useState(false);
  const snapshotMode = snapshotReady && Boolean(snapshot?.factor_snapshot || snapshot?.source === 'market_scan_snapshot') && !manualMode;
  const [rules, setRules] = useState([]);
  const [enabledRules, setEnabledRules] = useState(new Set());
  const [signalType, setSignalType] = useState('B'); // B / S / ALL
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');
  const [sortKey, setSortKey] = useState('hits');
  const [sortDir, setSortDir] = useState(-1); // -1 desc, 1 asc
  const [collapsed] = useState(false);
  const [autoRefresh, setAutoRefresh] = useState(false);
  const timerRef = useRef(null);

  // 加载策略规则
  const loadRules = useCallback(async () => {
    const res = await apiFetch('/api/hk-strategy/rules', {}, 10000, 0);
    if (res.ok) {
      setRules(res.data.rules || []);
      setEnabledRules(new Set((res.data.rules || []).map(r => r.key)));
    }
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);

  // 默认读取港股盘后快照；只有用户修改规则后，才回到手动实时扫描。
  useEffect(() => {
    if (!snapshotMode || !snapshot?.strategy) return;
    const allItems = snapshot.strategy.items || [];
    // 生产快照已经由七维因子引擎决定交易状态，不再用旧 B/S 过滤器隐藏 NO_CHASE/观察结果。
    setResults({ ...snapshot.strategy, items: allItems });
    setUpdated(snapshot.updated_at || '');
    setError(snapshotError || '');
  }, [snapshot, snapshotError, snapshotMode]);

  // 执行扫描
  const runScan = useCallback(async () => {
    if (snapshotMode) {
      if (onRefresh) await onRefresh();
      return;
    }
    setLoading(true);
    setError('');
    try {
      const body = { market: 'HK', rules: Array.from(enabledRules), signal_type: signalType };
      const res = await apiFetch('/api/hk-strategy/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }, 45000, 0);
      if (res.ok) {
        setResults(res.data);
        setUpdated(res.data.updated_at || '');
      } else {
        setError(res.error || '扫描失败');
      }
    } catch (e) {
      setError(String(e));
    }
    setLoading(false);
  }, [enabledRules, onRefresh, signalType, snapshotMode]);

  // 首次自动扫描
  useEffect(() => {
    if (!snapshotMode && !snapshotLoading && rules.length > 0 && !results) runScan();
  }, [rules, results, runScan, snapshotLoading, snapshotMode]);

  // 自动刷新（数据服务端缓存 5 分钟）
  useEffect(() => {
    if (!autoRefresh) return;
    timerRef.current = setInterval(() => runScan(), 5 * 60 * 1000);
    return () => clearInterval(timerRef.current);
  }, [autoRefresh, runScan]);

  const toggleRule = (key) => {
    setManualMode(true);
    setEnabledRules(prev => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  };

  const setPreset = (preset) => {
    setManualMode(true);
    if (preset.rules === null) setEnabledRules(new Set(rules.map(r => r.key)));
    else setEnabledRules(new Set(preset.rules));
  };

  // 规则命中分布（基于扫描结果聚合）
  const ruleDist = useMemo(() => {
    const m = {};
    (results?.items || []).forEach(it => (it.hits || []).forEach(h => { m[h.key] = (m[h.key] || 0) + 1; }));
    return m;
  }, [results]);

  // 信号汇总
  const summary = useMemo(() => {
    const items = results?.items || [];
    if (snapshotMode) {
      const buy = items.filter(it => ['READY', 'TRIGGERED'].includes(it.trading_state)).length;
      const blocked = items.filter(it => ['NO_CHASE', 'INVALID'].includes(it.trading_state)).length;
      const top = items.slice().sort((a, b) => (b.factor_score ?? -Infinity) - (a.factor_score ?? -Infinity))[0];
      return { total: items.length, buy, sell: blocked, top, scanned: results?.scanned || snapshot?.factor_snapshot?.valid_count || 0 };
    }
    let buy = 0, sell = 0;
    items.forEach(it => { if (it.signal === 'B') buy++; else if (it.signal === 'S') sell++; });
    const top = items.slice().sort((a, b) => (b.hits?.length || 0) - (a.hits?.length || 0))[0];
    return { total: items.length, buy, sell, top, scanned: results?.scanned || 0 };
  }, [results, snapshot, snapshotMode]);

  const filtered = useMemo(() => {
    if (!results?.items) return [];
    const items = [...results.items];
    items.sort((a, b) => {
      let av, bv;
      if (sortKey === 'hits') { av = a.hits?.length || 0; bv = b.hits?.length || 0; }
      else if (sortKey === 'strength') { av = a.hits?.length || 0; bv = b.hits?.length || 0; }
      else if (sortKey === 'change_pct') { av = a.change_pct ?? -999; bv = b.change_pct ?? -999; }
      else if (sortKey === 'deviation') { av = a.deviation ?? -999; bv = b.deviation ?? -999; }
      else if (sortKey === 'rsi') { av = a.rsi ?? 0; bv = b.rsi ?? 0; }
      else if (sortKey === 'change5d') { av = a.change5d ?? -999; bv = b.change5d ?? -999; }
      else if (sortKey === 'change20d') { av = a.change20d ?? -999; bv = b.change20d ?? -999; }
      else if (sortKey === 'price') { av = a.price ?? 0; bv = b.price ?? 0; }
      else { av = 0; bv = 0; }
      return (av - bv) * sortDir;
    });
    return items;
  }, [results, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => d * -1);
    else { setSortKey(key); setSortDir(-1); }
  };
  const sortArrow = (key) => {
    if (sortKey !== key) return <span className="ml-0.5 opacity-30">↕</span>;
    return <span className="ml-0.5">{sortDir > 0 ? '↑' : '↓'}</span>;
  };

  const pctColor = (v) => v == null ? 'var(--text-muted)' : v >= 0 ? UP_COLOR : DOWN_COLOR;
  const fmtNum = (v, d = 2) => v == null ? '—' : Number(v).toFixed(d);
  const fmtPct = (v, sign = true) => v == null ? '—' : `${v >= 0 && sign ? '+' : ''}${Number(v).toFixed(2)}%`;
  const ruleName = (key) => rules.find(r => r.key === key)?.name || key;

  const COLUMNS = [
    { key: null, label: '代码/名称', align: 'left', width: 'auto' },
    { key: 'strength', label: '强度', align: 'center', width: '52px' },
    { key: 'hits', label: '命中', align: 'center', width: '52px' },
    { key: 'price', label: '最新价', align: 'right', width: '72px' },
    { key: 'change_pct', label: '当日%', align: 'right', width: '68px' },
    { key: 'deviation', label: '偏离MA20', align: 'right', width: '72px' },
    { key: 'rsi', label: 'RSI', align: 'right', width: '56px' },
    { key: 'change5d', label: '5日%', align: 'right', width: '68px' },
    { key: 'change20d', label: '20日%', align: 'right', width: '68px' },
    { key: null, label: '走势', align: 'center', width: '72px' },
    { key: null, label: '命中规则', align: 'left', width: 'auto' },
  ];

  const maxRuleHit = Math.max(1, ...Object.values(ruleDist));
  const viewLoading = snapshotMode ? snapshotLoading : loading;
  const snapshotQuality = snapshot?.factor_snapshot?.data_quality || snapshot?.data_quality;

  return (
    <div className="fade-in p-3" style={{ maxWidth: 1480, margin: '0 auto' }}>
      {/* 顶部标题 + 操作 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            <span className="mr-1">🇭🇰</span>港股策略扫描
          </h1>
          {updated && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· {updated}</span>}
          {snapshotMode && snapshot?.data_trade_date && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 数据日 {snapshot.data_trade_date}</span>}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* 信号类型切换 */}
          {!snapshotMode && (
            <div className="flex rounded-md overflow-hidden border" style={{ borderColor: 'var(--border-color)' }}>
              {[{ v: 'B', label: '买入', color: UP_COLOR }, { v: 'S', label: '卖出', color: DOWN_COLOR }, { v: 'ALL', label: '全部', color: 'var(--text-muted)' }].map(opt => (
                <button key={opt.v} onClick={() => setSignalType(opt.v)} className="px-2 py-1 text-[10px] font-medium transition-colors"
                  style={{ background: signalType === opt.v ? `${opt.color}20` : 'transparent', color: signalType === opt.v ? opt.color : 'var(--text-muted)', fontWeight: signalType === opt.v ? 'bold' : 'normal' }}>
                  {opt.label}
                </button>
              ))}
            </div>
          )}
          <label className="flex items-center gap-1 text-[10px] cursor-pointer select-none" style={{ color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} style={{ accentColor: 'var(--accent-blue, #3b82f6)' }} />
            自动刷新
          </label>
          <button onClick={runScan} disabled={viewLoading} className="px-3 py-1 rounded-md text-xs font-bold transition-colors"
            style={{ background: viewLoading ? 'var(--bg-secondary)' : 'var(--accent-blue, #3b82f6)', color: viewLoading ? 'var(--text-muted)' : '#fff', cursor: viewLoading ? 'default' : 'pointer', opacity: viewLoading ? 0.6 : 1 }}>
            {viewLoading ? '⏳ 读取中...' : snapshotMode ? '🔄 刷新快照' : '🔍 执行扫描'}
          </button>
        </div>
      </div>

      {snapshotMode && snapshotQuality && (
        <div className="mb-3 px-2.5 py-1.5 rounded text-[10px] flex items-center gap-2 flex-wrap" style={{
          background: snapshotQuality.status === 'VALID' ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.10)',
          border: `1px solid ${snapshotQuality.status === 'VALID' ? UP_COLOR : '#f59e0b'}55`,
          color: snapshotQuality.status === 'VALID' ? UP_COLOR : '#f59e0b',
        }}>
          <b>{snapshotQuality.status === 'VALID' ? '✓ 统一因子快照' : '⏳ 统一因子快照尚未具备评分条件'}</b>
          <span style={{ color: 'var(--text-secondary)' }}>{snapshotQuality.message || '页面只读取最近一次盘后结果'}</span>
          {snapshot?.factor_snapshot?.valid_count != null && <span style={{ color: 'var(--text-muted)' }}>有效历史 {snapshot.factor_snapshot.valid_count} 只</span>}
          {snapshot?.factor_snapshot?.pool_total != null && <span style={{ color: 'var(--text-muted)' }}>核心池 {snapshot.factor_snapshot.pool_total} 只 · 未达标 {Math.max(0, snapshot.factor_snapshot.pool_total - (snapshot.factor_snapshot.valid_count || 0))} 只</span>}
        </div>
      )}

      {/* 信号汇总 KPI */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        {[
          { label: snapshotMode ? '有效候选' : '命中标的', value: summary.total, color: 'var(--text-primary)', sub: `扫描 ${summary.scanned} 只` },
          { label: snapshotMode ? '已触发/准备' : '买入信号', value: summary.buy, color: UP_COLOR, sub: snapshotMode ? '准备 / 已触发' : 'B' },
          { label: snapshotMode ? '禁止追高/失效' : '卖出信号', value: summary.sell, color: snapshotMode ? '#f59e0b' : DOWN_COLOR, sub: snapshotMode ? '禁止追高 / 失效' : 'S' },
          { label: snapshotMode ? '最高因子分' : '最强信号', value: summary.top ? (snapshotMode ? Number(summary.top.factor_score).toFixed(1) : summary.top.name) : '—', color: summary.top ? UP_COLOR : 'var(--text-muted)', sub: summary.top ? (snapshotMode ? summary.top.name : `命中 ${summary.top.hits?.length || 0} 条`) : '暂无' },
        ].map(k => (
          <div key={k.label} className="rounded-md p-2.5" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{k.label}</div>
            <div className="text-base font-bold truncate" style={{ color: k.color }}>{k.value}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{k.sub}</div>
          </div>
        ))}
      </div>

      {snapshotMode ? (
        <UnifiedSnapshotTable
          items={results?.items || []}
          loading={viewLoading}
          scanned={summary.scanned}
          error={error || snapshotError}
          onRetry={runScan}
          navigate={navigate}
        />
      ) : (
      <div className="flex gap-3" style={{ minHeight: 'calc(100vh - 240px)' }}>
        {/* 左侧：规则面板 */}
        <div className="flex-shrink-0" style={{ width: collapsed ? 0 : 250, transition: 'width 0.2s', overflow: 'hidden' }}>
          <div className="rounded-md p-2.5 h-full overflow-auto" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            {/* 预设组合 */}
            <div className="mb-3">
              <div className="text-[10px] font-bold mb-1.5" style={{ color: 'var(--text-muted)' }}>⚡ 一键策略组合</div>
              <div className="flex flex-wrap gap-1">
                {PRESETS.map(p => (
                  <button key={p.key} onClick={() => setPreset(p)} className="px-2 py-1 rounded text-[10px] font-medium transition-colors"
                    style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
                    {p.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📋 策略规则 ({rules.length})</span>
              <div className="flex gap-1">
                <button onClick={() => { setManualMode(true); setEnabledRules(new Set(rules.map(r => r.key))); }} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>全选</button>
                <button onClick={() => { setManualMode(true); setEnabledRules(new Set()); }} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>清空</button>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              {RULE_CATEGORIES.map(cat => {
                const catRules = rules.filter(r => cat.members.includes(r.key));
                if (!catRules.length) return null;
                const enabledInCat = catRules.filter(r => enabledRules.has(r.key)).length;
                return (
                  <div key={cat.key}>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[10px] font-semibold" style={{ color: 'var(--text-secondary)' }}>{cat.label}</span>
                      <button onClick={() => setEnabledRules(prev => {
                        const n = new Set(prev);
                        if (enabledInCat === catRules.length) catRules.forEach(r => n.delete(r.key));
                        else catRules.forEach(r => n.add(r.key));
                        return n;
                      })} className="text-[8px] px-1 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>
                        {enabledInCat === catRules.length ? '全不选' : '全选'}
                      </button>
                    </div>
                    <div className="flex flex-col gap-1">
                      {catRules.map(r => {
                        const enabled = enabledRules.has(r.key);
                        const isBuy = r.signal === 'B';
                        const hitCount = ruleDist[r.key] || 0;
                        return (
                          <label key={r.key} className="flex items-start gap-1.5 p-1.5 rounded cursor-pointer transition-colors"
                            style={{ background: enabled ? `${isBuy ? UP_COLOR : DOWN_COLOR}08` : 'transparent' }}>
                            <input type="checkbox" checked={enabled} onChange={() => toggleRule(r.key)} className="mt-0.5 cursor-pointer" style={{ accentColor: isBuy ? UP_COLOR : DOWN_COLOR }} />
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center gap-1">
                                <span className="text-[11px] font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                                <span className="text-[8px] px-1 rounded font-bold" style={{ background: `${isBuy ? UP_COLOR : DOWN_COLOR}20`, color: isBuy ? UP_COLOR : DOWN_COLOR }}>{isBuy ? 'B' : 'S'}</span>
                              </div>
                              <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>{r.desc}</div>
                              {hitCount > 0 && (
                                <div className="mt-1 flex items-center gap-1">
                                  <div className="flex-1 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-secondary)' }}>
                                    <div className="h-full rounded-full" style={{ width: `${(hitCount / maxRuleHit) * 100}%`, background: isBuy ? UP_COLOR : DOWN_COLOR }} />
                                  </div>
                                  <span className="text-[8px]" style={{ color: isBuy ? UP_COLOR : DOWN_COLOR }}>{hitCount}</span>
                                </div>
                              )}
                            </div>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* 右侧：扫描结果 */}
        <div className="flex-1 min-w-0 rounded-md overflow-auto" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="p-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
            <h2 className="text-xs font-bold">
              📊 命中股票 ({filtered.length})
              {results && <span className="ml-1 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>/ 扫描 {results.scanned || 0}</span>}
            </h2>
            <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>点击列头排序 · 点击行跳转详情</span>
          </div>

          {(error || (snapshotMode && snapshotError)) && (
            <div className="p-3 text-center text-xs" style={{ color: 'var(--text-danger, #E24B4A)' }}>
              ❌ {error || snapshotError}
              <button onClick={runScan} className="ml-2 underline">重试</button>
            </div>
          )}

          <table className="w-full text-xs" style={{ tableLayout: 'fixed' }}>
            <thead className="sticky top-0 z-20">
              <tr style={{ background: 'var(--bg-secondary)' }}>
                {COLUMNS.map(({ key, label, align, width }) => (
                  <th key={label} className="px-1.5 py-1.5 whitespace-nowrap font-medium"
                    style={{ color: 'var(--text-muted)', textAlign: align, width, cursor: key ? 'pointer' : 'default', userSelect: 'none' }}
                    onClick={() => key && handleSort(key)}>
                    {label}{key ? sortArrow(key) : ''}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {viewLoading && filtered.length === 0 ? (
                Array.from({ length: 6 }).map((_, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    {COLUMNS.map((_, j) => (
                      <td key={j} className="px-1.5 py-1.5">
                        <div className="h-4 animate-pulse rounded" style={{ background: 'var(--bg-secondary)', width: `${60 + (j * 7) % 30}px` }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : filtered.length === 0 ? (
                <tr><td colSpan={COLUMNS.length} className="text-center py-8 px-4" style={{ color: 'var(--text-muted)' }}>
                  {error ? '' : (
                    <div>
                      <div className="text-sm mb-1">📭 当前无标的命中选中规则</div>
                      <div className="text-[10px] leading-relaxed">
                        可尝试：切换为「全部」信号 · 放宽规则（勾选更多 / 用预设组合）· 点「执行扫描」重试<br />
                        <span style={{ color: 'var(--text-muted)' }}>注：港股行情数据源为 Yahoo Finance，若其限流/不可达，扫描将无技术数据（已扫描 {summary.scanned} 只）</span>
                      </div>
                    </div>
                  )}
                </td></tr>
              ) : filtered.map(it => {
                const strength = strengthBadge(it.hits?.length || 0);
                const sparkColor = (it.change_pct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR;
                return (
                  <tr key={it.code} className="hover:opacity-80 cursor-pointer transition-colors" style={{ borderBottom: '1px solid var(--border-color)' }}
                    onClick={() => navigate(`/stock/${it.code}`)}>
                    <td className="px-1.5 py-1.5">
                      <div className="font-bold text-xs" style={{ color: 'var(--text-primary)' }}>{it.name}</div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{it.code}</div>
                    </td>
                    <td className="px-1.5 py-1.5 text-center">
                      <span className="inline-block px-1.5 py-0.5 rounded text-[9px] font-bold" style={{ background: `${strength.color}18`, color: strength.color }}>{strength.label}</span>
                    </td>
                    <td className="px-1.5 py-1.5 text-center">
                      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold"
                        style={{ background: it.signal === 'B' ? `${UP_COLOR}20` : it.signal === 'S' ? `${DOWN_COLOR}20` : 'var(--bg-secondary)', color: it.signal === 'B' ? UP_COLOR : it.signal === 'S' ? DOWN_COLOR : 'var(--text-muted)' }}>
                        {it.hits?.length || 0}
                      </span>
                    </td>
                    <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtNum(it.price)}</td>
                    <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtPct(it.change_pct)}</td>
                    <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.deviation) }}>{it.deviation != null ? `${it.deviation > 0 ? '+' : ''}${fmtNum(it.deviation)}%` : '—'}</td>
                    <td className="px-1.5 py-1.5 text-right font-medium" style={{ color: it.rsi >= 70 ? DOWN_DARK : it.rsi <= 30 ? UP_DARK : 'var(--text-secondary)' }}>{fmtNum(it.rsi, 0)}</td>
                    <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change5d) }}>{fmtPct(it.change5d, false)}</td>
                    <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change20d) }}>{fmtPct(it.change20d, false)}</td>
                    <td className="px-1.5 py-1.5 text-center"><Sparkline points={it.sparkline} color={sparkColor} /></td>
                    <td className="px-1.5 py-1.5">
                      <div className="flex flex-wrap gap-0.5">
                        {it.hits?.map((h, i) => {
                          const isBuy = h.signal === 'B';
                          return (
                            <span key={i} className="px-1 py-0.5 rounded text-[9px] font-medium"
                              style={{ background: `${isBuy ? UP_COLOR : DOWN_COLOR}15`, color: isBuy ? UP_COLOR : DOWN_COLOR }} title={ruleName(h.key)}>
                              {h.name}
                            </span>
                          );
                        })}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
      )}

      <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
        💡 数据: {snapshotMode ? '港股盘后统一因子快照（真实历史日线）' : 'Yahoo Finance'} · {snapshotMode ? '七维评分与独立维度共振；旧 RSI/均线规则仅研究对照' : '策略规则基于技术指标（MA/RSI/涨跌幅/偏离度/成交量）'} · 扫描范围：港股 {summary.scanned} 只
      </div>
    </div>
  );
}
