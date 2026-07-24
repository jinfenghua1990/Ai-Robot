/**
 * 港股/美股智能行情中心（独立模块）
 * 功能：指数卡片 | 市场概览 | 多维度筛选排序 | 技术信号 | 一键跟踪
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';
import { f2, stripCode } from '../utils/format';
import TrackButton from '../components/trading/TrackButton';

const fmtPct = (v, withSign = true) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  if (n === 0) return '0.00%';
  const sign = withSign && n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
};

const fmtNum = (v, digits = 2) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  return n.toFixed(digits);
};

const fmtVol = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  return n.toString();
};

const pctColor = (v) => {
  if (v == null || isNaN(Number(v))) return '#6b7280';
  return Number(v) > 0 ? UP_COLOR : Number(v) < 0 ? DOWN_COLOR : '#6b7280';
};

// 迷你sparkline
const Sparkline = ({ data, width = 70, height = 22 }) => {
  if (!data || data.length < 2) return <span style={{ color: '#9ca3af', fontSize: '10px' }}>—</span>;
  const closes = data.map(d => Number(d.c)).filter(c => !isNaN(c));
  if (closes.length < 2) return <span style={{ color: '#9ca3af', fontSize: '10px' }}>—</span>;
  const min = Math.min(...closes), max = Math.max(...closes), range = max - min || 1;
  const pts = closes.map((c, i) => `${(i/(closes.length-1))*width},${height-((c-min)/range)*height}`).join(' ');
  const up = closes[closes.length-1] >= closes[0];
  return <svg width={width} height={height}><polyline points={pts} fill="none" stroke={up?UP_COLOR:DOWN_COLOR} strokeWidth="1.2"/></svg>;
};

// 技术信号标签
const SignalBadge = ({ item }) => {
  const badges = [];
  const rsi = item.rsi;
  if (rsi != null) {
    if (rsi >= 70) badges.push({ text: 'RSI超买', color: DOWN_DARK, bg: 'rgba(34,197,94,0.1)' });
    else if (rsi <= 30) badges.push({ text: 'RSI超卖', color: UP_DARK, bg: 'rgba(239,68,68,0.1)' });
  }
  if (item.ma5 && item.ma20 && item.price) {
    if (item.price > item.ma5 && item.ma5 > item.ma20) badges.push({ text: '多头排列', color: UP_DARK, bg: 'rgba(239,68,68,0.1)' });
    else if (item.price < item.ma5 && item.ma5 < item.ma20) badges.push({ text: '空头排列', color: DOWN_DARK, bg: 'rgba(34,197,94,0.1)' });
  }
  if (item.change_pct != null) {
    if (item.change_pct >= 3) badges.push({ text: '强势', color: UP_COLOR, bg: 'rgba(239,68,68,0.12)' });
    else if (item.change_pct <= -3) badges.push({ text: '弱势', color: DOWN_COLOR, bg: 'rgba(34,197,94,0.12)' });
  }
  if (badges.length === 0) return <span style={{ color: 'var(--text-muted)', fontSize: '10px' }}>—</span>;
  return <div className="flex flex-wrap gap-0.5">{badges.map((b, i) => <span key={i} className="px-1 py-0.5 rounded text-[9px] font-medium" style={{ background: b.bg, color: b.color }}>{b.text}</span>)}</div>;
};

/** 表格骨架屏行 */
const SkeletonRow = () => (
  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
    <td className="px-1.5 py-1.5"><div className="h-4 w-24 animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1 py-1.5"><div className="h-5 w-16 mx-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-12 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-14 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-12 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-12 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-10 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-14 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-14 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-14 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-10 ml-auto animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-16 animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
    <td className="px-1.5 py-1.5"><div className="h-4 w-8 animate-pulse rounded" style={{ background: 'var(--bg-secondary)' }} /></td>
  </tr>
);

/** 搜索防抖 hook */
function useDebounce(value, delay = 300) {
  const [debounced, setDebounced] = useState(value);
  const timerRef = useRef(null);
  useEffect(() => {
    clearTimeout(timerRef.current);
    timerRef.current = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timerRef.current);
  }, [value, delay]);
  return debounced;
}

export default function GlobalMarketPage({ market: marketProp }) {
  const navigate = useNavigate();
  const isControlled = marketProp != null;
  const market = isControlled ? marketProp : 'HK';
  const [overview, setOverview] = useState(null);
  const [watchlist, setWatchlist] = useState(null);
  const [loading, setLoading] = useState(false);
  const [loadingWatchlist, setLoadingWatchlist] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');
  // 筛选/排序
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('change_pct');
  const [sortDir, setSortDir] = useState(-1);
  const [filterSignal, setFilterSignal] = useState('');

  const debouncedSearch = useDebounce(search, 300);

  const load = useCallback(async (mkt) => {
    setLoading(true);
    setLoadingWatchlist(true);
    setError('');
    try {
      // 先加载概览（指数 + 涨跌统计，较快）
      const ovRes = await apiFetch(`/api/global-market/overview/${mkt}`, {}, 15000, 0);
      if (ovRes.ok) { setOverview(ovRes.data); setUpdated(ovRes.data?.updated_at || ''); }
      else setError(ovRes.error || '加载失败');
      setLoading(false);

      // 再加载增强版选股（Yahoo Finance 1mo 数据，较慢，30s 超时，不重试）
      const wlRes = await apiFetch(`/api/global-market/watchlist-enhanced/${mkt}`, {}, 30000, 0);
      if (wlRes.ok) setWatchlist(wlRes.data);
      else setError(wlRes.error || '选股数据加载失败');
    } catch (e) { setError(String(e)); setLoading(false); }
    setLoadingWatchlist(false);
  }, []);

  useEffect(() => { load(market); }, [market, load]);

  const indices = overview?.indices || [];
  const stats = overview?.stats || {};
  const items = watchlist?.items || [];

  // 筛选 + 排序（使用防抖后的搜索词）
  const filtered = useMemo(() => {
    let list = [...items];
    if (debouncedSearch.trim()) {
      const q = debouncedSearch.trim().toLowerCase();
      list = list.filter(it => it.code?.toLowerCase().includes(q) || it.name?.toLowerCase().includes(q));
    }
    if (filterSignal === 'strong') list = list.filter(it => (it.change_pct || 0) >= 2);
    if (filterSignal === 'weak') list = list.filter(it => (it.change_pct || 0) <= -2);
    if (filterSignal === 'rsi_high') list = list.filter(it => it.rsi != null && it.rsi >= 70);
    if (filterSignal === 'rsi_low') list = list.filter(it => it.rsi != null && it.rsi <= 30);
    if (filterSignal === 'pullback') list = list.filter(it => it.ma20 && it.price && it.price <= it.ma20 * 1.02 && it.price >= it.ma20 * 0.98);
    list.sort((a, b) => {
      const va = Number(a[sortKey]) || 0, vb = Number(b[sortKey]) || 0;
      return (vb - va) * sortDir;
    });
    return list;
  }, [items, debouncedSearch, filterSignal, sortKey, sortDir]);

  const handleSort = (key) => {
    if (sortKey === key) setSortDir(d => -d);
    else { setSortKey(key); setSortDir(-1); }
  };

  const marketLabel = market === 'HK' ? '港股' : '美股';
  const marketIcon = market === 'HK' ? '🇭🇰' : '🇺🇸';

  // 排序箭头
  const sortArrow = (key) => {
    if (sortKey !== key) return <span className="ml-0.5 opacity-30">↕</span>;
    return <span className="ml-0.5">{sortDir > 0 ? '↑' : '↓'}</span>;
  };

  // 列定义：统一宽度
  const COLUMNS = [
    { key: null, label: '代码/名称', align: 'left', width: 'auto' },
    { key: null, label: '走势', align: 'center', width: '80px' },
    { key: 'price', label: '最新价', align: 'right', width: '72px' },
    { key: 'change_pct', label: '涨跌', align: 'right', width: '72px' },
    { key: 'ma5', label: 'MA5', align: 'right', width: '72px' },
    { key: 'ma20', label: 'MA20', align: 'right', width: '72px' },
    { key: 'rsi', label: 'RSI', align: 'right', width: '60px' },
    { key: 'change5d', label: '5日', align: 'right', width: '72px' },
    { key: 'change20d', label: '20日', align: 'right', width: '72px' },
    { key: 'deviation', label: '偏离度', align: 'right', width: '72px' },
    { key: 'volume', label: '成交量', align: 'right', width: '80px' },
    { key: null, label: '信号', align: 'left', width: 'auto' },
    { key: null, label: '跟踪', align: 'center', width: '56px' },
  ];

  return (
    <div className="p-4 overflow-auto" style={{ color: 'var(--text-primary)', background: 'var(--bg-primary)', minHeight: '100%' }}>
      {/* 标题 */}
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h1 className="text-lg font-bold">{marketIcon} {marketLabel}智能行情</h1>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>Yahoo Finance · 指数 + 技术筛选 + 一键跟踪</p>
        </div>
        <div className="flex items-center gap-2">
          {updated && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🕐 {updated}</span>}
          <button onClick={() => load(market)} className="px-3 py-1.5 rounded text-xs transition-all hover:opacity-80"
            style={{ background: 'var(--bg-card)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
            🔄 刷新
          </button>
        </div>
      </div>
      {error && (
        <div className="flex items-center justify-between p-2 mb-3 rounded text-xs" style={{ background: 'rgba(239,68,68,0.1)', color: DOWN_DARK }}>
          <span>⚠️ {error}</span>
          <button onClick={() => load(market)} className="ml-2 px-2 py-1 rounded text-[10px] font-medium"
            style={{ background: 'rgba(239,68,68,0.15)', color: DOWN_DARK }}>点此重试</button>
        </div>
      )}

      {/* 指数卡片 */}
      <div className="grid grid-cols-3 gap-2 mb-3">
        {loading ? [1,2,3].map(i => <div key={i} className="p-3 rounded animate-pulse" style={{ background: 'var(--bg-card)', height: 70 }} />)
          : indices.map(idx => (
          <div key={idx.code} className="p-3 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center justify-between mb-1"><span className="text-xs font-bold">{idx.name}</span><span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{idx.code}</span></div>
            <div className="text-lg font-bold" style={{ color: pctColor(idx.change_pct) }}>{fmtNum(idx.price)}</div>
            <div className="text-xs" style={{ color: pctColor(idx.change_pct) }}>{fmtPct(idx.change_pct)}</div>
          </div>
        ))}
      </div>

      {/* 搜索 + 筛选 */}
      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <input
          type="text" placeholder="搜索代码或名称..."
          value={search} onChange={e => setSearch(e.target.value)}
          className="w-40 px-2.5 py-1.5 text-xs rounded border"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
        />
        {[
          ['', '全部'], ['strong', '强势≥2%'], ['weak', '弱势≤-2%'],
          ['rsi_high', 'RSI超买'], ['rsi_low', 'RSI超卖'], ['pullback', '回踩MA20'],
        ].map(([k, label]) => (
          <button key={k} onClick={() => setFilterSignal(k)} className="px-2 py-1 rounded text-[10px] transition-all"
            style={{
              background: filterSignal === k ? 'var(--accent-blue)' : 'var(--bg-card)',
              color: filterSignal === k ? '#fff' : 'var(--text-muted)',
              border: `1px solid ${filterSignal === k ? 'var(--accent-blue)' : 'var(--border-color)'}`,
            }}
          >{label}</button>
        ))}
        <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>{filtered.length}/{items.length} 只</span>
      </div>

      {/* 涨跌统计 */}
      {stats.total > 0 && (
        <div className="grid grid-cols-3 gap-2 mb-3">
          {[{ label: '上涨', v: stats.up, c: UP_COLOR }, { label: '平盘', v: stats.flat, c: '#6b7280' }, { label: '下跌', v: stats.down, c: DOWN_COLOR }].map(s => (
            <div key={s.label} className="p-1.5 rounded text-center" style={{ background: `${s.c}10`, border: `1px solid ${s.c}30` }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.label}</div>
              <div className="text-base font-bold" style={{ color: s.c }}>{s.v}</div>
            </div>
          ))}
        </div>
      )}

      {/* 股票列表表格 */}
      <div className="rounded overflow-auto" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="p-2.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <h2 className="text-xs font-bold">📊 {marketLabel}选股看板 ({filtered.length})</h2>
          <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>点击列头排序 · 点击行跳转详情</span>
        </div>
        <table className="w-full text-xs" style={{ tableLayout: 'fixed' }}>
          <thead className="sticky top-0 z-20">
            <tr style={{ background: 'var(--bg-secondary)' }}>
              {COLUMNS.map(({ key, label, align, width }) => (
                <th key={label} className="px-1.5 py-1.5 whitespace-nowrap font-medium"
                  style={{
                    color: 'var(--text-muted)',
                    textAlign: align,
                    width,
                    cursor: key ? 'pointer' : 'default',
                    userSelect: 'none',
                  }}
                  onClick={() => key && handleSort(key)}>
                  {label}{key ? sortArrow(key) : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {loading && items.length === 0 ? (
              <>{Array.from({ length: 6 }).map((_, i) => <SkeletonRow key={i} />)}</>
            ) : filtered.length === 0 ? (
              <tr><td colSpan={COLUMNS.length} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>
                {debouncedSearch ? '未找到匹配的股票' : '暂无数据，请点击刷新'}
              </td></tr>
            ) : filtered.map(it => (
              <tr key={it.code} className="hover:opacity-80 cursor-pointer transition-colors"
                style={{ borderBottom: '1px solid var(--border-color)' }}
                onClick={() => navigate(`/stock/${it.code}`)}>
                <td className="px-1.5 py-1.5">
                  <div className="font-bold text-xs" style={{ color: 'var(--text-primary)' }}>{it.name}</div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{it.code}</div>
                </td>
                <td className="px-1 py-1.5">
                  <Sparkline data={it.sparkline} width={72} height={26} />
                </td>
                <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtNum(it.price)}</td>
                <td className="px-1.5 py-1.5 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>{fmtPct(it.change_pct)}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: it.price > it.ma5 ? UP_COLOR : it.price < it.ma5 ? DOWN_COLOR : 'var(--text-secondary)' }}>{fmtNum(it.ma5)}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtNum(it.ma20)}</td>
                <td className="px-1.5 py-1.5 text-right font-medium" style={{ color: it.rsi >= 70 ? DOWN_DARK : it.rsi <= 30 ? UP_DARK : 'var(--text-secondary)' }}>{fmtNum(it.rsi)}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change5d) }}>{fmtPct(it.change5d, false)}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.change20d) }}>{fmtPct(it.change20d, false)}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: pctColor(it.deviation) }}>{it.deviation != null ? `${(it.deviation > 0 ? '+' : '')}${fmtNum(it.deviation)}%` : '—'}</td>
                <td className="px-1.5 py-1.5 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtVol(it.volume)}</td>
                <td className="px-1.5 py-1.5"><SignalBadge item={it} /></td>
                <td className="px-1.5 py-1.5 text-center" onClick={e => e.stopPropagation()}>
                  <TrackButton stockCode={it.code} stockName={it.name} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="mt-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
        💡 数据: Yahoo Finance · 点击列头排序 · 点击行跳转详情 · "回踩MA20"筛选 = 股价在MA20±2%区间内
      </div>
    </div>
  );
}