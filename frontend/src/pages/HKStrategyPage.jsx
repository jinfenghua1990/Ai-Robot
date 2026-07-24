import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, DOWN_DARK, UP_DARK } from '../utils/colors';

/**
 * 港股策略扫描页面
 * - 左侧：策略规则列表（可勾选启用/禁用）
 * - 右侧：命中股票列表（可排序、跳转详情）
 */
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
  const [collapsed, setCollapsed] = useState(false); // 移动端折叠规则面板

  // 加载策略规则
  const loadRules = useCallback(async () => {
    const res = await apiFetch('/api/hk-strategy/rules', {}, 10000, 0);
    if (res.ok) {
      setRules(res.data.rules || []);
      // 默认全选
      setEnabledRules(new Set((res.data.rules || []).map(r => r.key)));
    }
  }, []);

  useEffect(() => { loadRules(); }, [loadRules]);

  // 执行扫描
  const runScan = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const body = {
        market: 'HK',
        rules: Array.from(enabledRules),
        signal_type: signalType,
      };
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

  // 自动首次扫描
  useEffect(() => {
    if (rules.length > 0 && !results) runScan();
  }, [rules, results, runScan]);

  const toggleRule = (key) => {
    setEnabledRules(prev => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key); else n.add(key);
      return n;
    });
  };

  const filtered = useMemo(() => {
    if (!results?.items) return [];
    const items = [...results.items];
    items.sort((a, b) => {
      let av, bv;
      if (sortKey === 'hits') { av = a.hits?.length || 0; bv = b.hits?.length || 0; }
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

  const COLUMNS = [
    { key: null, label: '代码/名称', align: 'left', width: 'auto' },
    { key: 'hits', label: '命中', align: 'center', width: '60px' },
    { key: 'price', label: '最新价', align: 'right', width: '72px' },
    { key: 'change_pct', label: '当日%', align: 'right', width: '68px' },
    { key: 'deviation', label: '偏离MA20', align: 'right', width: '72px' },
    { key: 'rsi', label: 'RSI', align: 'right', width: '56px' },
    { key: 'change5d', label: '5日%', align: 'right', width: '68px' },
    { key: 'change20d', label: '20日%', align: 'right', width: '68px' },
    { key: null, label: '命中规则', align: 'left', width: 'auto' },
  ];

  return (
    <div className="fade-in p-3" style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 顶部标题 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <h1 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            <span className="mr-1">🇭🇰</span>港股策略扫描
          </h1>
          {updated && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· {updated}</span>}
        </div>
        <div className="flex items-center gap-2">
          {/* 信号类型切换 */}
          <div className="flex rounded-md overflow-hidden border" style={{ borderColor: 'var(--border-color)' }}>
            {[
              { v: 'B', label: '买入', color: UP_COLOR },
              { v: 'S', label: '卖出', color: DOWN_COLOR },
              { v: 'ALL', label: '全部', color: 'var(--text-muted)' },
            ].map(opt => (
              <button key={opt.v} onClick={() => setSignalType(opt.v)}
                className="px-2 py-1 text-[10px] font-medium transition-colors"
                style={{
                  background: signalType === opt.v ? `${opt.color}20` : 'transparent',
                  color: signalType === opt.v ? opt.color : 'var(--text-muted)',
                  fontWeight: signalType === opt.v ? 'bold' : 'normal',
                }}>
                {opt.label}
              </button>
            ))}
          </div>
          <button onClick={runScan} disabled={loading}
            className="px-3 py-1 rounded-md text-xs font-bold transition-colors"
            style={{
              background: loading ? 'var(--bg-secondary)' : 'var(--accent-blue, #3b82f6)',
              color: loading ? 'var(--text-muted)' : '#fff',
              cursor: loading ? 'default' : 'pointer',
              opacity: loading ? 0.6 : 1,
            }}>
            {loading ? '⏳ 扫描中...' : '🔍 执行扫描'}
          </button>
        </div>
      </div>

      {/* 主体：左右布局 */}
      <div className="flex gap-3" style={{ minHeight: 'calc(100vh - 140px)' }}>
        {/* 左侧：策略规则面板 */}
        <div className="flex-shrink-0" style={{ width: collapsed ? 0 : 240, transition: 'width 0.2s', overflow: 'hidden' }}>
          <div className="rounded-md p-2.5 h-full overflow-auto" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📋 策略规则 ({rules.length})</span>
              <div className="flex gap-1">
                <button onClick={() => setEnabledRules(new Set(rules.map(r => r.key)))}
                  className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>全选</button>
                <button onClick={() => setEnabledRules(new Set())}
                  className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>清空</button>
              </div>
            </div>
            <div className="flex flex-col gap-1">
              {rules.map(r => {
                const enabled = enabledRules.has(r.key);
                const isBuy = r.signal === 'B';
                return (
                  <label key={r.key} className="flex items-start gap-1.5 p-1.5 rounded cursor-pointer transition-colors"
                    style={{ background: enabled ? `${isBuy ? UP_COLOR : DOWN_COLOR}08` : 'transparent' }}>
                    <input type="checkbox" checked={enabled} onChange={() => toggleRule(r.key)}
                      className="mt-0.5 cursor-pointer" style={{ accentColor: isBuy ? UP_COLOR : DOWN_COLOR }} />
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-1">
                        <span className="text-[11px] font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                        <span className="text-[8px] px-1 rounded font-bold"
                          style={{ background: `${isBuy ? UP_COLOR : DOWN_COLOR}20`, color: isBuy ? UP_COLOR : DOWN_COLOR }}>
                          {isBuy ? 'B' : 'S'}
                        </span>
                      </div>
                      <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>{r.desc}</div>
                    </div>
                  </label>
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
                <tr><td colSpan={COLUMNS.length} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
                  {error ? '' : '无命中股票，可调整规则或信号类型后重新扫描'}
                </td></tr>
              ) : filtered.map(it => (
                <tr key={it.code} className="hover:opacity-80 cursor-pointer transition-colors"
                  style={{ borderBottom: '1px solid var(--border-color)' }}
                  onClick={() => navigate(`/stock/${it.code}`)}>
                  <td className="px-1.5 py-1.5">
                    <div className="font-bold text-xs" style={{ color: 'var(--text-primary)' }}>{it.name}</div>
                    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{it.code}</div>
                  </td>
                  <td className="px-1.5 py-1.5 text-center">
                    <span className="inline-flex items-center justify-center w-6 h-6 rounded-full text-[10px] font-bold"
                      style={{
                        background: it.signal === 'B' ? `${UP_COLOR}20` : it.signal === 'S' ? `${DOWN_COLOR}20` : 'var(--bg-secondary)',
                        color: it.signal === 'B' ? UP_COLOR : it.signal === 'S' ? DOWN_COLOR : 'var(--text-muted)',
                      }}>
                      {it.hits?.length || 0}
                    </span>
                  </td>
                  <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtNum(it.price)}</td>
                  <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtPct(it.change_pct)}</td>
                  <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.deviation) }}>{it.deviation != null ? `${it.deviation > 0 ? '+' : ''}${fmtNum(it.deviation)}%` : '—'}</td>
                  <td className="px-1.5 py-1.5 text-right font-medium" style={{ color: it.rsi >= 70 ? DOWN_DARK : it.rsi <= 30 ? UP_DARK : 'var(--text-secondary)' }}>{fmtNum(it.rsi, 0)}</td>
                  <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change5d) }}>{fmtPct(it.change5d, false)}</td>
                  <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change20d) }}>{fmtPct(it.change20d, false)}</td>
                  <td className="px-1.5 py-1.5">
                    <div className="flex flex-wrap gap-0.5">
                      {it.hits?.map((h, i) => {
                        const isBuy = h.signal === 'B';
                        return (
                          <span key={i} className="px-1 py-0.5 rounded text-[9px] font-medium"
                            style={{ background: `${isBuy ? UP_COLOR : DOWN_COLOR}15`, color: isBuy ? UP_COLOR : DOWN_COLOR }}
                            title={rules.find(r => r.key === h.key)?.desc}>
                            {h.name}
                          </span>
                        );
                      })}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
        💡 数据: Yahoo Finance · 策略规则基于技术指标（MA/RSI/涨跌幅/偏离度）· 首次加载较慢，5 分钟内重复扫描走缓存
      </div>
    </div>
  );
}
