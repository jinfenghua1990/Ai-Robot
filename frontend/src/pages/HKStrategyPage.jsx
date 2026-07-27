import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, DOWN_DARK, UP_DARK } from '../utils/colors';

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

export default function HKStrategyPage() {
  const navigate = useNavigate();
  const [rules, setRules] = useState([]);
  const [enabledRules, setEnabledRules] = useState(new Set());
  const [signalType, setSignalType] = useState('B'); // B / S / ALL
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');
  const [sortKey, setSortKey] = useState('hits');
  const [sortDir, setSortDir] = useState(-1); // -1 desc, 1 asc
  const [collapsed, setCollapsed] = useState(false);
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

  // 执行扫描
  const runScan = useCallback(async () => {
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
  }, [enabledRules, signalType]);

  // 首次自动扫描
  useEffect(() => {
    if (rules.length > 0 && !results) runScan();
  }, [rules, results, runScan]);

  // 自动刷新（数据服务端缓存 5 分钟）
  useEffect(() => {
    if (!autoRefresh) return;
    timerRef.current = setInterval(() => runScan(), 5 * 60 * 1000);
    return () => clearInterval(timerRef.current);
  }, [autoRefresh, runScan]);

  const toggleRule = (key) => {
    setEnabledRules(prev => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  };

  const setPreset = (preset) => {
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
    let buy = 0, sell = 0;
    items.forEach(it => { if (it.signal === 'B') buy++; else if (it.signal === 'S') sell++; });
    const top = items.slice().sort((a, b) => (b.hits?.length || 0) - (a.hits?.length || 0))[0];
    return { total: items.length, buy, sell, top, scanned: results?.scanned || 0 };
  }, [results]);

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

  return (
    <div className="fade-in p-3" style={{ maxWidth: 1480, margin: '0 auto' }}>
      {/* 顶部标题 + 操作 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            <span className="mr-1">🇭🇰</span>港股策略扫描
          </h1>
          {updated && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· {updated}</span>}
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          {/* 信号类型切换 */}
          <div className="flex rounded-md overflow-hidden border" style={{ borderColor: 'var(--border-color)' }}>
            {[{ v: 'B', label: '买入', color: UP_COLOR }, { v: 'S', label: '卖出', color: DOWN_COLOR }, { v: 'ALL', label: '全部', color: 'var(--text-muted)' }].map(opt => (
              <button key={opt.v} onClick={() => setSignalType(opt.v)} className="px-2 py-1 text-[10px] font-medium transition-colors"
                style={{ background: signalType === opt.v ? `${opt.color}20` : 'transparent', color: signalType === opt.v ? opt.color : 'var(--text-muted)', fontWeight: signalType === opt.v ? 'bold' : 'normal' }}>
                {opt.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1 text-[10px] cursor-pointer select-none" style={{ color: 'var(--text-muted)' }}>
            <input type="checkbox" checked={autoRefresh} onChange={e => setAutoRefresh(e.target.checked)} style={{ accentColor: 'var(--accent-blue, #3b82f6)' }} />
            自动刷新
          </label>
          <button onClick={runScan} disabled={loading} className="px-3 py-1 rounded-md text-xs font-bold transition-colors"
            style={{ background: loading ? 'var(--bg-secondary)' : 'var(--accent-blue, #3b82f6)', color: loading ? 'var(--text-muted)' : '#fff', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.6 : 1 }}>
            {loading ? '⏳ 扫描中...' : '🔍 执行扫描'}
          </button>
        </div>
      </div>

      {/* 信号汇总 KPI */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        {[
          { label: '命中标的', value: summary.total, color: 'var(--text-primary)', sub: `扫描 ${summary.scanned} 只` },
          { label: '买入信号', value: summary.buy, color: UP_COLOR, sub: 'B' },
          { label: '卖出信号', value: summary.sell, color: DOWN_COLOR, sub: 'S' },
          { label: '最强信号', value: summary.top ? summary.top.name : '—', color: summary.top ? UP_COLOR : 'var(--text-muted)', sub: summary.top ? `命中 ${summary.top.hits?.length || 0} 条` : '暂无' },
        ].map(k => (
          <div key={k.label} className="rounded-md p-2.5" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{k.label}</div>
            <div className="text-base font-bold truncate" style={{ color: k.color }}>{k.value}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{k.sub}</div>
          </div>
        ))}
      </div>

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
                <button onClick={() => setEnabledRules(new Set(rules.map(r => r.key)))} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>全选</button>
                <button onClick={() => setEnabledRules(new Set())} className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>清空</button>
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

          {error && (
            <div className="p-3 text-center text-xs" style={{ color: 'var(--text-danger, #E24B4A)' }}>
              ❌ {error}
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
              {loading && filtered.length === 0 ? (
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

      <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
        💡 数据: Yahoo Finance · 策略规则基于技术指标（MA/RSI/涨跌幅/偏离度/成交量）· 扫描范围：港股自选 {summary.scanned} 只 · 服务端 5 分钟缓存
      </div>
    </div>
  );
}
