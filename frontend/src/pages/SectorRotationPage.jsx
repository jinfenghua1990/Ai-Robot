import { useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import SectorRotationPositionTable from '../components/sector-rotation/SectorRotationPositionTable';

const HOT_KEY = 'sector-rotation-hot-sectors';
const THEME_HOT_KEY = 'sector-rotation-hot-themes';
const EXCLUDE_KEY = 'sector-rotation-excluded-stocks';
const n = (v) => v == null ? null : Number(v);
const pct = (v) => n(v) == null ? '—' : `${n(v) >= 0 ? '+' : ''}${n(v).toFixed(2)}%`;
const color = (v) => n(v) == null ? 'var(--text-muted)' : n(v) >= 0 ? '#ef4444' : '#22c55e';
const money = (v) => {
  const value = n(v);
  if (value == null) return '—';
  if (Math.abs(value) >= 1e8) return `${(value / 1e8).toFixed(1)}亿`;
  if (Math.abs(value) >= 1e4) return `${(value / 1e4).toFixed(1)}万`;
  return value.toFixed(0);
};

export default function SectorRotationPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [sector, setSector] = useState('');
  const [hot, setHot] = useState(() => { try { return JSON.parse(localStorage.getItem(HOT_KEY) || '[]'); } catch { return []; } });
  const [themeData, setThemeData] = useState(null);
  const [themeDetail, setThemeDetail] = useState(null);
  const [themeHot, setThemeHot] = useState(() => { try { return JSON.parse(localStorage.getItem(THEME_HOT_KEY) || '[]'); } catch { return []; } });
  const [showAll, setShowAll] = useState(false);
  const [query, setQuery] = useState('');
  const [sort, setSort] = useState('rank');
  const [poolView, setPoolView] = useState('core');
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailKind, setDetailKind] = useState('industry');
  const [error, setError] = useState('');
  const [portfolio, setPortfolio] = useState({ positions: [] });
  const [autoStocks, setAutoStocks] = useState({});
  const [excluded, setExcluded] = useState(() => { try { return JSON.parse(localStorage.getItem(EXCLUDE_KEY) || '[]'); } catch { return []; } });
  const requestRef = useRef(null);
  const themeRequestRef = useRef(null);

  useEffect(() => {
    apiFetch('/api/sector-rotation/themes', {}, 30000, 0).then((r) => {
      if (r.ok) setThemeData(r.data);
    });
  }, []);
  useEffect(() => {
    requestRef.current?.abort();
    const controller = new AbortController();
    requestRef.current = controller;
    apiFetch(`/api/sector-rotation${sector ? `?sector=${encodeURIComponent(sector)}` : ''}`, { signal: controller.signal }, 30000, 0).then((r) => {
      if (r.ok) { setData(r.data); setError(''); } else setError(r.error || '加载失败');
    });
    return () => controller.abort();
  }, [sector]);
  useEffect(() => {
    Promise.all([apiFetch('/api/shared/portfolio'), apiFetch('/api/auto-trade/stocks')]).then(([p, a]) => {
      if (p.ok) setPortfolio(p.data || { positions: [] });
      if (a.ok) setAutoStocks(a.data?.items || {});
    });
  }, []);
  const toggleHot = (name) => setHot((old) => { const next = old.includes(name) ? old.filter(x => x !== name) : [...old, name]; localStorage.setItem(HOT_KEY, JSON.stringify(next)); return next; });
  const toggleThemeHot = (name) => setThemeHot((old) => { const next = old.includes(name) ? old.filter(x => x !== name) : [...old, name]; localStorage.setItem(THEME_HOT_KEY, JSON.stringify(next)); return next; });
  const selected = data?.sectors?.find(x => x.sector === data.selected);
  const recommendedRows = useMemo(() => (data?.sectors || []).filter(x => (x.metrics?.score ?? 0) >= 60).slice(0, 6), [data]);
  const recommendedNames = useMemo(() => new Set(recommendedRows.map(x => x.sector)), [recommendedRows]);
  const sectorRows = useMemo(() => {
    const rows = data?.sectors || [];
    if (showAll) return rows;
    const merged = [...recommendedRows, ...rows.filter(x => hot.includes(x.sector) && !recommendedNames.has(x.sector))];
    return merged;
  }, [data, hot, recommendedNames, recommendedRows, showAll]);
  const recommendedThemes = useMemo(() => (themeData?.theme_groups || []).filter(x => x.recommended).slice(0, 6), [themeData]);
  const recommendedThemeNames = useMemo(() => new Set(recommendedThemes.map(x => x.theme)), [recommendedThemes]);
  const themeRows = useMemo(() => {
    const rows = themeData?.theme_groups || [];
    return [...recommendedThemes, ...rows.filter(x => themeHot.includes(x.theme) && !recommendedThemeNames.has(x.theme))];
  }, [recommendedThemeNames, recommendedThemes, themeData, themeHot]);
  const stocks = useMemo(() => {
    const source = poolView === 'candidate' ? data?.candidate_stocks : data?.stocks;
    let rows = (source || []).filter(x => !excluded.includes(x.ts_code) && `${x.name || ''}${x.ts_code}`.toLowerCase().includes(query.toLowerCase()));
    if (sort === 'ret20') rows = [...rows].sort((a, b) => (b.metrics.ret_20d || -999) - (a.metrics.ret_20d || -999));
    if (sort === 'ret60') rows = [...rows].sort((a, b) => (b.metrics.ret_60d || -999) - (a.metrics.ret_60d || -999));
    if (sort === 'score') rows = [...rows].sort((a, b) => (b.score || -999) - (a.score || -999));
    return rows;
  }, [data, excluded, poolView, query, sort]);
  const excludeStock = (code) => setExcluded((old) => { const next = old.includes(code) ? old : [...old, code]; localStorage.setItem(EXCLUDE_KEY, JSON.stringify(next)); return next; });
  const restoreExcluded = () => { localStorage.removeItem(EXCLUDE_KEY); setExcluded([]); };
  const openSector = (name) => { setDetailKind('industry'); setSector(name); setDetailOpen(true); };
  const openTheme = async (name, concept = '') => {
    themeRequestRef.current?.abort();
    const controller = new AbortController();
    themeRequestRef.current = controller;
    setDetailKind('theme');
    setThemeDetail(null);
    setDetailOpen(true);
    const params = new URLSearchParams({ theme: name });
    if (concept) params.set('concept', concept);
    const result = await apiFetch(`/api/sector-rotation/themes?${params}`, { signal: controller.signal }, 30000, 0);
    if (result.ok) setThemeDetail(result.data);
  };
  const activeTheme = themeDetail?.theme_groups?.find(x => x.theme === themeDetail.selected_theme);
  const themeStocks = useMemo(() => {
    let rows = [...(themeDetail?.stocks || []), ...(themeDetail?.candidate_stocks || [])]
      .filter(x => !excluded.includes(x.ts_code) && `${x.name || ''}${x.ts_code}`.toLowerCase().includes(query.toLowerCase()));
    if (sort === 'ret20') rows = rows.sort((a, b) => (b.metrics.ret_20d || -999) - (a.metrics.ret_20d || -999));
    if (sort === 'ret60') rows = rows.sort((a, b) => (b.metrics.ret_60d || -999) - (a.metrics.ret_60d || -999));
    if (sort === 'score') rows = rows.sort((a, b) => (b.score || -999) - (a.score || -999));
    return rows;
  }, [excluded, query, sort, themeDetail]);
  return <div className="space-y-3" style={{ color: 'var(--text-primary)' }}>
    <div className="rounded-xl p-2.5 space-y-2" style={{ background: 'var(--bg-card)', borderBottom: '2px solid var(--border-color)', boxShadow: '0 2px 12px rgba(0,0,0,.06)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2"><h2 className="text-lg font-bold flex items-center gap-2">行业轮动池 <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,.1)', color: '#3b82f6' }}>{hot.length}个热门</span><span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,.1)', color: '#22c55e' }}>{data?.selected || '未选择板块'}</span></h2><div className="flex items-center gap-1.5"><span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>盘后缓存 · {data?.trade_date || '—'}</span><button onClick={() => setShowAll(x => !x)} className="rounded px-2 py-1 text-[11px]" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>{showAll ? '收起未标记板块' : `展开全部板块（${data?.sectors?.length || 0}）`}</button></div></div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">{[
        ['当前行业', data?.selected || '—', '#3b82f6'],
        ['行业强度', selected?.metrics?.score ?? '—', '#f59e0b'],
        ['核心池 / 资格库', `${data?.stock_count ?? 0}/${selected?.qualified_stock_count ?? 0}`, '#22c55e'],
        ['20日表现', pct(selected?.metrics?.ret_20d), color(selected?.metrics?.ret_20d)],
      ].map(([label, value, c]) => <div key={label} className="rounded-lg px-2.5 py-2" style={{ background: 'var(--bg-hover)' }}><div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="text-lg font-bold mt-0.5" style={{ color: c }}>{value}</div></div>)}</div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-2.5 py-1.5 text-[10px]" style={{ background: 'rgba(59,130,246,.06)', color: 'var(--text-secondary)' }}>
        <b style={{ color: '#3b82f6' }}>入池硬门槛</b>
        <span>近 {data?.pool_rule?.lookback_trade_days || 250} 个完成交易日：单日涨幅 ≥ {data?.pool_rule?.single_day_pct_gte || 9}% 或连续两日复合涨幅 ≥ {data?.pool_rule?.two_day_compound_pct_gte || 16}%</span>
        <span>核心池再要求：最近 {data?.pool_rule?.core_requires_days_since_trigger_lte || 120} 日内触发、至少 {data?.pool_rule?.core_requires_distinct_event_dates_gte || 2} 个不同触发日、站上 MA60</span>
        <span style={{ color: 'var(--text-muted)' }}>剔除 ST、上市前 {data?.pool_rule?.ignored_initial_trading_bars || 20} 日和异常复权涨跌；日线 {data?.data_as_of?.daily_kline || '—'} · 个股资金 {data?.data_as_of?.stock_money_flow || '—'} · 板块资金 {data?.data_as_of?.sector_flow || '—'}</span>
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg px-2.5 py-1.5 text-[10px]" style={{ background: selected?.etf ? 'rgba(168,85,247,.07)' : 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
        <b style={{ color: '#a855f7' }}>ETF 参考</b>
        {selected?.etf ? <><span className="font-semibold">{selected.etf.name}（{selected.etf.code}）</span><span>跟踪 {selected.etf.tracking_index || '—'}</span><span style={{ color: color(selected.etf.return_20d_pct) }}>20日 {pct(selected.etf.return_20d_pct)}</span><span style={{ color: color(selected.etf.return_1y_pct) }}>近一年 {pct(selected.etf.return_1y_pct)}</span><span>规模 {money(selected.etf.fund_size)} · 20日成交 {money(selected.etf.amount_20d)}</span><span style={{ color: 'var(--text-muted)' }}>{selected.etf_note} · {selected.etf.as_of}</span></> : <span style={{ color: 'var(--text-muted)' }}>{selected?.etf_note || 'ETF 数据尚未缓存，当前先以强势资格股等权聚合作为板块参考'}</span>}
      </div>
    </div>
    {error && <div className="rounded p-2 text-xs" style={{ background: 'rgba(239,68,68,.1)', color: '#ef4444' }}>{error}</div>}
    <section className="rounded-lg border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-2 py-2" style={{ borderColor: 'var(--border-color)' }}><div><b className="text-xs">交易主题</b><span className="ml-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>一级行业之上，按概念成分与强势资格股交叉识别</span></div><div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>系统推荐 {recommendedThemes.length} · 手动收藏 {themeHot.length} · 主题数据 {themeData?.data_as_of?.concept_flow || '—'}</div></div>
      <div className="grid grid-cols-2 gap-1.5 p-2 sm:grid-cols-3 lg:grid-cols-6">{themeRows.map(x => <div key={x.theme} className="flex items-start gap-1 rounded px-2 py-1.5" style={{ background: x.recommended ? 'rgba(239,68,68,.06)' : 'var(--bg-hover)', border: `1px solid ${x.recommended ? 'rgba(239,68,68,.2)' : 'transparent'}` }}><button onClick={() => openTheme(x.theme)} className="min-w-0 flex-1 text-left" title={x.metrics?.basis}><div className="flex items-center gap-1 truncate text-[11px] font-bold"><span>{themeHot.includes(x.theme) ? '🔥' : x.recommended ? '⚡' : ''}</span>{x.theme}<span className="text-[9px]" style={{ color: '#f59e0b' }}>{x.metrics?.score ?? '—'}</span></div><div className="truncate text-[9px]" style={{ color: color(x.metrics?.avg_chg_pct) }}>领涨 {pct(x.metrics?.avg_chg_pct)} · {x.leading_concept || '—'}</div><div className="truncate text-[9px]" style={{ color: 'var(--text-muted)' }}>资格股 {x.stock_count} · 核心 {x.core_stock_count} · {x.subtheme_count}个子方向</div></button><button onClick={() => toggleThemeHot(x.theme)} className="text-[10px]" title={themeHot.includes(x.theme) ? '取消收藏' : '加入收藏'}>{themeHot.includes(x.theme) ? '★' : '☆'}</button></div>)}</div>
      {!themeRows.length && <div className="py-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>正在读取交易主题…</div>}
    </section>
    <section className="rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <div className="flex items-center gap-2 overflow-x-auto border-b px-2 py-2" style={{ borderColor: 'var(--border-color)' }}><button onClick={() => setSector('')} className="shrink-0 rounded px-2 py-1 text-[11px]" style={{ background: !sector ? 'rgba(59,130,246,.14)' : 'var(--bg-hover)', color: !sector ? '#60a5fa' : 'var(--text-secondary)' }}>推荐与收藏 {sectorRows.length}</button>{sectorRows.map(x => <button key={x.sector} onClick={() => openSector(x.sector)} className="shrink-0 rounded px-2 py-1 text-[11px]" style={{ background: x.sector === data?.selected ? 'rgba(59,130,246,.18)' : 'var(--bg-hover)', color: x.sector === data?.selected ? '#60a5fa' : 'var(--text-secondary)' }}>{hot.includes(x.sector) && '🔥 '}{x.sector} <span className="opacity-60">{x.metrics.score ?? '—'}</span></button>)}</div>
      <div className="p-2"><div className="mb-2 flex items-center justify-between"><div className="text-xs font-bold">板块列表 <span className="ml-1 font-normal" style={{ color: 'var(--text-muted)' }}>点击板块弹出个股明细</span></div><span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>系统推荐 {recommendedRows.length} · 手动收藏 {hot.length} · 重复板块合并显示</span></div><div className="grid grid-cols-2 gap-1.5 sm:grid-cols-4 lg:grid-cols-6">{sectorRows.map(x => <div key={x.sector} className="flex items-center gap-1 rounded px-2 py-1.5" style={{ background: x.sector === data?.selected ? 'rgba(59,130,246,.14)' : 'var(--bg-hover)', border: `1px solid ${x.sector === data?.selected ? '#3b82f6' : 'transparent'}` }}><button onClick={() => openSector(x.sector)} className="min-w-0 flex-1 text-left"><div className="truncate text-[11px] font-bold">{hot.includes(x.sector) && '🔥 '}{x.sector}</div><div className="text-[9px]" style={{ color: color(x.metrics.ret_20d) }}>20日 {pct(x.metrics.ret_20d)} · {x.stock_count}只 · {recommendedNames.has(x.sector) ? '系统推荐' : '手动收藏'}</div></button><button onClick={() => toggleHot(x.sector)} className="text-[10px]" title={hot.includes(x.sector) ? '取消收藏' : '加入收藏'}>{hot.includes(x.sector) ? '★' : '☆'}</button></div>)}</div>{!showAll && !sectorRows.length && <div className="py-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>当前没有达到推荐强度门槛的板块，请展开全部板块查看</div>}</div>
    </section>
    <section className="overflow-hidden rounded-xl border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
      <div className="flex flex-wrap items-center justify-between gap-2 border-b px-2 py-2" style={{ borderColor: 'var(--border-color)' }}><div><b className="text-sm">{data?.selected || '请选择板块'}</b><span className="ml-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>{selected ? `核心池 ${data.stock_count || 0} / 强势资格库 ${selected.qualified_stock_count || 0} / 行业全量 ${selected.universe_stock_count || 0}` : '从上方板块进入'}</span></div><div className="flex items-center gap-1"><button onClick={() => setPoolView('core')} className="rounded px-1.5 py-1 text-[10px]" style={{ background: poolView === 'core' ? 'rgba(34,197,94,.12)' : 'var(--bg-hover)', color: poolView === 'core' ? '#22c55e' : 'var(--text-muted)', border: '1px solid var(--border-color)' }}>核心池 {data?.stock_count || 0}</button><button onClick={() => setPoolView('candidate')} className="rounded px-1.5 py-1 text-[10px]" style={{ background: poolView === 'candidate' ? 'rgba(245,158,11,.12)' : 'var(--bg-hover)', color: poolView === 'candidate' ? '#f59e0b' : 'var(--text-muted)', border: '1px solid var(--border-color)' }}>待补池 {data?.candidate_count || 0}</button><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索名称/代码" className="w-32 rounded px-2 py-1 text-[11px]" style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }} /><select value={sort} onChange={e => setSort(e.target.value)} className="rounded px-1 py-1 text-[11px]" style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }}><option value="rank">行业排名</option><option value="score">综合分</option><option value="ret20">20日收益</option><option value="ret60">60日收益</option></select>{excluded.length > 0 && <button onClick={restoreExcluded} className="rounded border px-1.5 py-1 text-[10px]" style={{ borderColor: 'var(--border-color)' }}>恢复剔除 {excluded.length}</button>}</div></div>
      <SectorRotationPositionTable stocks={stocks} positions={portfolio?.positions || []} autoStocks={autoStocks} onOpen={(code) => navigate(`/stock-analysis?code=${code}`)} onExclude={excludeStock} onOpenAuto={(code) => navigate(`/stock-analysis?code=${code}#sec-strategy`)} />
    </section>
    {detailOpen && <div className="fixed inset-0 z-50 flex items-start justify-center overflow-auto p-4" style={{ background: 'rgba(2,6,23,.68)' }} onClick={() => setDetailOpen(false)}>
      <div className="mt-6 w-full max-w-[1500px] rounded-xl border shadow-2xl" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }} onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-color)' }}><div><b className="text-sm">{detailKind === 'theme' ? `${themeDetail?.selected_theme || '交易主题'}${themeDetail?.selected_concept ? ` / ${themeDetail.selected_concept}` : ''}` : (data?.selected || sector || '板块')} · 个股明细</b><span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>{detailKind === 'theme' ? (themeDetail ? `核心 ${themeDetail.stock_count || 0} · 待补 ${themeDetail.candidate_count || 0}` : '正在加载主题数据…') : (data?.selected === sector ? `核心池 ${data?.stock_count || 0} · 资格库 ${selected?.qualified_stock_count || 0}` : '正在加载板块数据…')}</span></div><button onClick={() => setDetailOpen(false)} className="rounded px-2 py-1 text-xs" style={{ background: 'var(--bg-hover)' }}>关闭</button></div>
        {detailKind === 'theme' ? themeDetail ? <>
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-3 py-2 text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }} title={activeTheme?.metrics?.basis}><span>主题热度 <b style={{ color: '#f59e0b' }}>{activeTheme?.metrics?.heat_score ?? '—'}</b></span><span>领涨子方向均值 <b style={{ color: color(activeTheme?.metrics?.avg_chg_pct) }}>{pct(activeTheme?.metrics?.avg_chg_pct)}</b></span><span>20日 <b style={{ color: color(activeTheme?.metrics?.ret_20d) }}>{pct(activeTheme?.metrics?.ret_20d)}</b></span><span>领涨方向涨停 {activeTheme?.metrics?.limit_up_count ?? 0}</span><span>主题 {themeDetail.data_as_of?.concept_flow || '—'} · 个股技术 {themeDetail.data_as_of?.daily_kline || '—'}</span><span className="ml-auto">行业是稳定归类，主题是当日交易驱动</span></div>
          <div className="flex flex-wrap items-center gap-1 border-b px-3 py-2" style={{ borderColor: 'var(--border-color)' }}><button onClick={() => openTheme(activeTheme?.theme || themeDetail.selected_theme)} className="rounded px-2 py-1 text-[10px]" style={{ background: !themeDetail.selected_concept ? 'rgba(59,130,246,.14)' : 'var(--bg-hover)', color: !themeDetail.selected_concept ? '#60a5fa' : 'var(--text-secondary)' }}>全部子方向</button>{(activeTheme?.concepts || []).map(concept => <button key={concept.name} onClick={() => openTheme(activeTheme.theme, concept.name)} className="rounded px-2 py-1 text-[10px]" style={{ background: themeDetail.selected_concept === concept.name ? 'rgba(59,130,246,.14)' : 'var(--bg-hover)', color: themeDetail.selected_concept === concept.name ? '#60a5fa' : 'var(--text-secondary)' }}>{concept.name} <span className="opacity-60">{pct(concept.avg_chg_pct)} · {concept.qualified_stock_count}</span></button>)}</div>
          <div className="flex items-center justify-end gap-1 border-b px-3 py-1.5" style={{ borderColor: 'var(--border-color)' }}><input value={query} onChange={e => setQuery(e.target.value)} placeholder="搜索主题内股票" className="w-36 rounded px-2 py-1 text-[11px]" style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }} /><select value={sort} onChange={e => setSort(e.target.value)} className="rounded px-1 py-1 text-[11px]" style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)' }}><option value="rank">主题排名</option><option value="score">综合分</option><option value="ret20">20日收益</option><option value="ret60">60日收益</option></select></div>
          <SectorRotationPositionTable stocks={themeStocks} positions={portfolio?.positions || []} autoStocks={autoStocks} onOpen={(code) => navigate(`/stock-analysis?code=${code}`)} onExclude={excludeStock} onOpenAuto={(code) => navigate(`/stock-analysis?code=${code}#sec-strategy`)} />
        </> : <div className="p-8 text-center text-xs" style={{ color: 'var(--text-muted)' }}>正在加载对应主题和子方向…</div> : data?.selected === sector ? <><div className="flex flex-wrap gap-x-4 gap-y-1 border-b px-3 py-2 text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}><span>强度 <b style={{ color: '#f59e0b' }}>{selected?.metrics?.score ?? '—'}</b></span><span>20日 <b style={{ color: color(selected?.metrics?.ret_20d) }}>{pct(selected?.metrics?.ret_20d)}</b></span><span>60日 <b style={{ color: color(selected?.metrics?.ret_60d) }}>{pct(selected?.metrics?.ret_60d)}</b></span><span>核心池 {data?.stock_count || 0}</span><span>资格库 {selected?.qualified_stock_count || 0}</span><span>ETF {selected?.etf?.name || '—'}</span></div><SectorRotationPositionTable stocks={stocks} positions={portfolio?.positions || []} autoStocks={autoStocks} onOpen={(code) => navigate(`/stock-analysis?code=${code}`)} onExclude={excludeStock} onOpenAuto={(code) => navigate(`/stock-analysis?code=${code}#sec-strategy`)} /></> : <div className="p-8 text-center text-xs" style={{ color: 'var(--text-muted)' }}>正在加载对应板块明细…</div>}
      </div>
    </div>}
  </div>;
}
