import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import WatchlistItem from '../components/trading/WatchlistItem';
import KLineChart from '../components/charts/KLineChart';
import SortBar from '../components/watchlist/SortBar';
import FilterBar from '../components/watchlist/FilterBar';
import { BUY_COLOR } from '../utils/colors';

const SECTOR_ICONS = {
  'MLCC': '', 'CPO': '', 'PCB': '🟩', '存储芯片': '💾',
  '先进封装': '🔧', '光纤光缆': '🔆', 'AI PC': '🖥️', 'AI芯片': '🧠',
  'AI服务器': '🖧', 'OCS': '🔷', '培育钻石': '', '玻璃基板': '🔲',
  '陶瓷基板': '🏺', '高速链接': '⚡', '铜箔': '🟫', '树脂': '🍃',
  '电子布': '🧵', '液冷': '❄️', '六氟化钨': '⚗️', '碳酸铁锂': '🔋',
};

const STAGE_DEFS = [
  { key: '主升', color: '#dc2626', test: c => c >= 9.5 },
  { key: '加速', color: '#ef4444', test: c => c >= 5 && c < 9.5 },
  { key: '突破', color: '#f97316', test: c => c >= 1 && c < 5 },
  { key: '蓄势', color: '#eab308', test: c => c >= 0 && c < 1 },
  { key: '留意', color: '#3b82f6', test: c => c < 0 && c >= -3 },
  { key: '观望', color: '#64748b', test: c => c < -3 && c >= -5 },
  { key: '衰退', color: '#22c55e', test: c => c < -5 },
];

export default function FocusStocksPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState(null);
  const [strategyPicks, setStrategyPicks] = useState({});

  const [selectedCode, setSelectedCode] = useState(null);
  const [realtimeFlow, setRealtimeFlow] = useState(null);

  const [sortKey, setSortKey] = useState('bs');
  const [sortDir, setSortDir] = useState('desc');
  const [filters, setFilters] = useState({ junk: false, buyOnly: false, heating: false, hit_trend: false, hit_capital: false, hit_yuzi: false, hit_strategy: false, hit_popularity: false, hit_support: false, hit_accumulation: false });
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);

  const [collapsedSectors, setCollapsedSectors] = useState(new Set());

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2000);
  };

  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const [res, picksRes] = await Promise.all([
        apiFetch('/api/focus-stocks', {}, 30000),
        apiFetch('/api/bs-screener/strategy-picks'),
      ]);
      if (res.ok) setData(res.data);
      if (picksRes.ok && picksRes.data?.code_to_strategies) {
        setStrategyPicks(picksRes.data.code_to_strategies);
      }
    } catch (e) {
      showToast('数据加载失败', 'error');
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  // 选中股票变化时请求实时资金流
  useEffect(() => {
    if (!selectedCode) { setRealtimeFlow(null); return; }
    let active = true;
    const code = selectedCode;
    const suffix = code.startsWith('6') || code.startsWith('9') ? '.SH' : code.startsWith('8') || code.startsWith('4') ? '.BJ' : '.SZ';
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/realtime/stock-flow-detail?ts_code=${code}${suffix}`);
        if (active && ok) setRealtimeFlow(data);
        else if (active) setRealtimeFlow(null);
      } catch { if (active) setRealtimeFlow(null); }
    })();
    return () => { active = false; };
  }, [selectedCode]);

  // 展平所有股票
  const allStocks = useMemo(() => {
    if (!data?.sectors) return [];
    return data.sectors.flatMap(s => s.stocks);
  }, [data]);

  const totalCount = allStocks.length;

  const selected = useMemo(
    () => allStocks.find(s => s.secCode === selectedCode),
    [allStocks, selectedCode]
  );
  const selectedSectorTrend = selected?.sectorTrend;

  // 初始化选中
  useEffect(() => {
    if (!selectedCode && allStocks.length > 0) {
      const first = allStocks.find(x => x.quote);
      if (first) setSelectedCode(first.secCode);
    }
  }, [allStocks, selectedCode]);

  // 状态卡统计（前端计算）
  const statCards = useMemo(() => {
    const heating = allStocks.filter(s => s.sectorTrend?.heat_trend === 'up');
    const buy = allStocks.filter(s => s.bsSignal === 'B');
    const inflow = allStocks.filter(s => (s.moneyFlow?.main_net ?? 0) > 0);

    const heatingTop = heating
      .sort((a, b) => (b.sectorTrend?.latest_heat ?? 0) - (a.sectorTrend?.latest_heat ?? 0))
      .slice(0, 6)
      .map(s => ({ code: s.secCode, name: s.secName, heat: s.sectorTrend?.latest_heat ?? 0 }));
    const buyTop = buy
      .sort((a, b) => (b.buyPower?.score ?? 0) - (a.buyPower?.score ?? 0))
      .slice(0, 6)
      .map(s => ({ code: s.secCode, name: s.secName }));
    const inflowTop = inflow
      .sort((a, b) => (b.quote?.changePct ?? 0) - (a.quote?.changePct ?? 0))
      .slice(0, 6)
      .map(s => ({ code: s.secCode, name: s.secName, chg: s.quote?.changePct ?? 0 }));

    return [
      { key: 'heat', label: '板块升温', sub: '热度↑', count: heating.length, color: '#ef4444', top: heatingTop, valKey: 'heat', valFmt: v => `热度${v}` },
      { key: 'buy', label: '可买', sub: 'B信号', count: buy.length, color: BUY_COLOR, top: buyTop, valKey: null, valFmt: () => null },
      { key: 'flow', label: '资金流入', sub: '净流入', count: inflow.length, color: '#f97316', top: inflowTop, valKey: 'chg', valFmt: v => `${v >= 0 ? '+' : ''}${v}%` },
    ];
  }, [allStocks]);

  // 7阶段趋势统计
  const stageStats = useMemo(() => {
    const stats = {};
    STAGE_DEFS.forEach(s => stats[s.key] = 0);
    allStocks.forEach(s => {
      const chg = s.quote?.changePct ?? 0;
      const stage = STAGE_DEFS.find(d => d.test(chg));
      if (stage) stats[stage.key]++;
    });
    return stats;
  }, [allStocks]);

  // 排序+筛选函数（每个赛道内独立）
  const applySortFilter = useCallback((stocks) => {
    let arr = [...stocks];
    if (filters.junk) arr = arr.filter(s => s.marketState?.market_state !== 'CHOPPY');
    if (filters.buyOnly) arr = arr.filter(s => s.bsSignal === 'B');
    if (filters.heating) arr = arr.filter(s => s.sectorTrend?.heat_trend === 'up');
    if (filters.hit_trend) arr = arr.filter(s => s.hitTags?.includes('trend'));
    if (filters.hit_capital) arr = arr.filter(s => s.hitTags?.includes('capital'));
    if (filters.hit_yuzi) arr = arr.filter(s => s.hitTags?.includes('yuzi'));
    if (filters.hit_strategy) arr = arr.filter(s => s.hitTags?.includes('strategy'));
    if (filters.hit_popularity) arr = arr.filter(s => s.hitTags?.includes('popularity'));
    if (filters.hit_support) arr = arr.filter(s => s.hitTags?.includes('support'));
    if (filters.hit_accumulation) arr = arr.filter(s => s.hitTags?.includes('accumulation'));
    const dir = sortDir === 'desc' ? -1 : 1;
    const getVal = (s) => {
      switch (sortKey) {
        case 'bs': {
          const lastB = (s.techSignals || []).filter(t => t.type === 'B').sort((a, b) => (b.date || '').localeCompare(a.date || ''))[0];
          return lastB?.date || '0000-00-00';
        }
        case 'leader': return (s.bsSignal === 'B' ? 1 : 0) * 1000 + (s.quote?.changePct || 0);
        case 'buyPower': return s.buyPower?.score || 0;
        case 'changePct': return s.quote?.changePct ?? -9999;
        case 'heat': return s.sectorTrend?.latest_heat || 0;
        default: return 0;
      }
    };
    arr.sort((a, b) => {
      const va = getVal(a), vb = getVal(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
    return arr;
  }, [filters, sortKey, sortDir]);

  // 按平均涨跌幅排序赛道
  const sortedSectors = useMemo(() => {
    if (!data?.sectors) return [];
    return data.sectors.map(s => {
      const avgChg = s.stocks.reduce((sum, st) => sum + (st.quote?.changePct ?? 0), 0) / Math.max(s.stocks.length, 1);
      const upCount = s.stocks.filter(st => st.quote?.changePct > 0).length;
      return { ...s, avgChg, upCount };
    }).sort((a, b) => b.avgChg - a.avgChg);
  }, [data]);

  const toggleSector = (name) => {
    setCollapsedSectors(prev => {
      const n = new Set(prev);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });
  };

  const batchAdd = useCallback(async (sectorName) => {
    try {
      const res = await apiFetch('/api/focus-stocks/batch-add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sector: sectorName, group: '重点关注' }),
      });
      if (!res.ok) { showToast(res.data?.detail || '失败', 'error'); return; }
      const json = res.data;
      if (json?.success) showToast(`${sectorName}: +${json.added} 跳过${json.skipped}`);
      else showToast(json?.detail || '失败', 'error');
    } catch { showToast('批量添加失败', 'error'); }
  }, []);

  // 批量加入自选
  const onBatchAddToWatchlist = useCallback(async () => {
    const { ok, data: respData } = await apiFetch('/api/focus-stocks/batch-add-to-watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stock_codes: selectedIds }),
    });
    if (ok) {
      showToast(`已添加 ${respData.added} 只到自选股，跳过 ${respData.skipped} 只`);
      setSelectedIds([]); setBatchMode(false);
    } else { showToast('批量添加失败', 'error'); }
  }, [selectedIds]);

  const onToggleCheck = useCallback((code) => {
    setSelectedIds(s => s.includes(code) ? s.filter(c => c !== code) : [...s, code]);
  }, []);
  const onSelectAllSector = useCallback((stocks) => {
    const codes = stocks.map(s => s.secCode);
    setSelectedIds(prev => {
      const set = new Set(prev);
      codes.forEach(c => set.add(c));
      return [...set];
    });
  }, []);
  const onClearSel = useCallback(() => setSelectedIds([]), []);

  const fmtChg = (v) => {
    if (v == null) return '';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
  };

  const summary = data?.summary;

  return (
    <div className="space-y-3">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm shadow-lg"
          style={{ background: toast.type === 'error' ? 'rgba(239,68,68,0.92)' : toast.type === 'info' ? 'rgba(59,130,246,0.92)' : 'rgba(34,197,94,0.92)', color: '#fff' }}>
          {toast.msg}
        </div>
      )}

      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-primary)' }}>
          <span>重点关注 <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>{totalCount}只</span></span>
          {summary && (
            <span className="text-xs flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <span>{summary.total_sectors}赛道 · 涨{summary.up_count} 跌{summary.down_count}</span>
              {summary.limit_up_count > 0 && <span style={{ color: '#f97316' }}>涨停{summary.limit_up_count}</span>}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          <button onClick={() => loadData(true)} disabled={refreshing}
            className="px-2.5 py-1 rounded-lg border text-xs disabled:opacity-50"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            {refreshing ? '⏳' : '🔄 刷新'}
          </button>
          <button onClick={() => navigate('/watchlist')}
            className="px-2.5 py-1 rounded-lg border text-xs"
            style={{ borderColor: 'rgba(168,85,247,0.3)', color: '#a855f7' }}>
            ⭐自选股
          </button>
        </div>
      </div>

      {/* 左右并排：左=状态模块(3卡+7阶段)  右=K线图 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 左：状态模块 */}
        <div className="rounded-xl border p-2.5 space-y-2" style={{ borderColor: 'rgba(99,102,241,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-[11px] font-bold flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
            📊 池子状态 <span style={{ color: 'var(--text-muted)' }}>· 点击个股标签联动右侧K线</span>
          </div>
          {/* 7阶段趋势阶段状态栏 */}
          <div className="flex items-center gap-1 flex-wrap rounded-lg p-1.5" style={{ background: 'var(--bg-surface)' }}>
            {STAGE_DEFS.map(stage => {
              const count = stageStats[stage.key] || 0;
              const pct = totalCount > 0 ? Math.round(count / totalCount * 100) : 0;
              return (
                <button
                  key={stage.key}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] flex-shrink-0"
                  style={{ background: `${stage.color}15`, border: `1px solid ${stage.color}30`, color: stage.color }}
                  title={`${stage.key}阶段：涨跌幅区间`}
                >
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: stage.color }} />
                  <span className="font-bold">{stage.key}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{count}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{pct}%</span>
                </button>
              );
            })}
          </div>
          {statCards.map(card => {
            const pct = totalCount > 0 ? Math.round(card.count / totalCount * 100) : 0;
            return (
              <div key={card.key} className="rounded-lg border p-2" style={{ borderColor: `${card.color}25`, background: `${card.color}08` }}>
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xl font-bold leading-none" style={{ color: card.color }}>{card.count}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>·{pct}%</span>
                  <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{card.label}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{card.sub}</span>
                </div>
                <div className="flex flex-wrap gap-1">
                  {card.top && card.top.length > 0 ? card.top.map((s, i) => {
                    const val = card.valKey ? card.valFmt(s[card.valKey]) : null;
                    const active = selectedCode === s.code;
                    return (
                      <button key={i} onClick={() => setSelectedCode(s.code)}
                        className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1 transition-all"
                        style={{ background: active ? `${card.color}30` : `${card.color}12`, color: 'var(--text-secondary)', border: active ? `1px solid ${card.color}` : '1px solid transparent' }}>
                        <span className="truncate max-w-[60px]">{s.name}</span>
                        {val && <span style={{ color: card.color }}>{val}</span>}
                      </button>
                    );
                  }) : <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>—</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* 右：K线图（联动选中） */}
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(99,179,237,0.3)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-sm font-bold" style={{ color: '#60a5fa' }}>📈 K线 · 操盘线 · 板块趋势</span>
            {selected && (
              <span className="text-[10px] flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
                <span className="font-bold" style={{ color: '#22c55e' }}>{selected.secName}</span>
                <span>{selected.secCode}</span>
                {selected.quote && selected.quote.changePct != null && <span style={{ color: selected.quote.changePct >= 0 ? '#ef4444' : '#22c55e' }}>{selected.quote.changePct >= 0 ? '+' : ''}{selected.quote.changePct}%</span>}
                {selected.sector && <span style={{ color: 'var(--text-muted)' }}>{selected.sector}</span>}
                {selectedSectorTrend?.available && (
                  <span style={{ color: selectedSectorTrend.heat_trend === 'up' ? '#ef4444' : selectedSectorTrend.heat_trend === 'down' ? '#22c55e' : 'var(--text-muted)' }}>
                    {selectedSectorTrend.heat_trend === 'up' ? '🔥' : selectedSectorTrend.heat_trend === 'down' ? '❄' : '·'} {selectedSectorTrend.latest_heat}
                  </span>
                )}
              </span>
            )}
          </div>
          {selectedCode ? (
            <KLineChart code={selectedCode} height={260} />
          ) : (
            <div className="h-[260px] flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>点击左侧股票或状态卡标签查看K线</div>
          )}
        </div>
      </div>

      {/* 工具栏：排序/筛选/批量 */}
      <div className="flex items-center gap-2 flex-wrap rounded-xl border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <FilterBar
          activeFilters={filters}
          onToggle={(key, val) => setFilters(f => ({ ...f, [key]: val }))}
        />
        <button
          onClick={() => setFilters(f => ({ ...f, hit_trend: !f.hit_trend }))}
          className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1"
          style={{
            borderColor: filters.hit_trend ? 'rgba(59,130,246,0.5)' : 'var(--border-color)',
            background: filters.hit_trend ? 'rgba(59,130,246,0.12)' : 'var(--bg-hover)',
            color: filters.hit_trend ? '#3b82f6' : 'var(--text-secondary)',
          }}
          title="只显示多头排列/底部突破的股票"
        >
          📈 趋势
        </button>
        <button
          onClick={() => setFilters(f => ({ ...f, hit_capital: !f.hit_capital }))}
          className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1"
          style={{
            borderColor: filters.hit_capital ? 'rgba(239,68,68,0.5)' : 'var(--border-color)',
            background: filters.hit_capital ? 'rgba(239,68,68,0.12)' : 'var(--bg-hover)',
            color: filters.hit_capital ? '#ef4444' : 'var(--text-secondary)',
          }}
          title="只显示主力净流入创30天新高的股票"
        >
          💰 资金
        </button>
        <SortBar
          sortKey={sortKey}
          sortDir={sortDir}
          onChange={(k, d) => { if (d) setSortDir(d); else setSortKey(k); }}
        />
        {/* 批量模式 */}
        <button
          onClick={() => { setBatchMode(b => !b); if (batchMode) setSelectedIds([]); }}
          className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1"
          style={{
            borderColor: batchMode ? 'rgba(168,85,247,0.5)' : 'var(--border-color)',
            background: batchMode ? 'rgba(168,85,247,0.12)' : 'var(--bg-hover)',
            color: batchMode ? '#a855f7' : 'var(--text-secondary)',
          }}
        >
          {batchMode ? '✓ 批量' : '☑ 批量'}
        </button>
        {batchMode && (
          <>
            <button onClick={() => onSelectAllSector(allStocks)} className="px-1.5 py-1 rounded border text-[10px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>全选</button>
            <button onClick={onClearSel} className="px-1.5 py-1 rounded border text-[10px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>清空</button>
            <button
              onClick={onBatchAddToWatchlist}
              disabled={selectedIds.length === 0}
              className="px-2 py-1 rounded border text-[10px] disabled:opacity-40"
              style={{ borderColor: 'rgba(34,197,94,0.5)', color: '#22c55e' }}
            >
              ＋加入自选({selectedIds.length})
            </button>
          </>
        )}
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {totalCount} 只{filters.buyOnly && ' · 仅可买'}{filters.heating && ' · 板块升温'}{filters.hit_trend && ' · 趋势命中'}{filters.hit_capital && ' · 资金命中'}
        </span>
      </div>

      {/* 赛道分组列表 */}
      {loading ? (
        <div className="space-y-1.5">
          {[1,2,3,4,5,6,7,8].map(i => (
            <div key={i} className="h-16 rounded-lg animate-pulse" style={{ background: 'var(--bg-hover)' }} />
          ))}
        </div>
      ) : (
        <div className="space-y-2">
          {sortedSectors.map((sector) => {
            const expanded = !collapsedSectors.has(sector.sector);
            const displayStocks = applySortFilter(sector.stocks);
            if (displayStocks.length === 0 && (filters.buyOnly || filters.heating || filters.hit_trend || filters.hit_capital || filters.junk)) return null;
            return (
              <div key={sector.sector}
                className="rounded-xl border overflow-hidden"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                {/* 赛道头部 - 点击展开/收起 */}
                <div
                  className="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
                  style={{ borderBottom: expanded ? '1px solid var(--border-color)' : 'none' }}
                  onClick={() => toggleSector(sector.sector)}>
                  <span className="text-sm">{SECTOR_ICONS[sector.sector] || '📌'}</span>
                  <span className="text-xs font-bold" style={{ color: sector.color }}>{sector.sector}</span>
                  <span className="text-[10px] px-1 rounded" style={{
                    background: sector.avgChg >= 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: sector.avgChg >= 0 ? '#ef4444' : '#22c55e',
                  }}>
                    {sector.upCount}/{sector.stocks.length}↑
                  </span>
                  <span className="text-xs font-bold" style={{ color: sector.avgChg >= 0 ? '#ef4444' : '#22c55e' }}>
                    {fmtChg(sector.avgChg)}
                  </span>
                  <div className="ml-auto flex items-center gap-1.5">
                    {batchMode && displayStocks.length > 0 && (
                      <button
                        onClick={(e) => { e.stopPropagation(); onSelectAllSector(displayStocks); }}
                        className="text-[10px] px-1.5 py-0.5 rounded border"
                        style={{ borderColor: 'rgba(168,85,247,0.3)', color: '#a855f7' }}
                        title="选中本赛道全部"
                      >
                        ☑本赛道
                      </button>
                    )}
                    <button
                      onClick={(e) => { e.stopPropagation(); batchAdd(sector.sector); }}
                      className="text-[10px] px-1.5 py-0.5 rounded border"
                      style={{ borderColor: `${sector.color}40`, color: sector.color }}
                      title="整赛道加入自选股">
                      ＋整赛道
                    </button>
                    <span className="text-[10px] w-4 text-center" style={{ color: 'var(--text-muted)' }}>
                      {expanded ? '▾' : '▸'}
                    </span>
                  </div>
                </div>
                {/* 个股列表（双列 WatchlistItem，与自选页完全一致）*/}
                {expanded && (
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 px-3 py-2">
                    {displayStocks.length > 0 ? displayStocks.map(sig => (
                      <WatchlistItem
                        key={sig.secCode}
                        signal={sig}
                        isSelected={selectedCode === sig.secCode}
                        realtimeFlow={selectedCode === sig.secCode ? realtimeFlow : null}
                        onSelect={setSelectedCode}
                        onSell={null}
                        onRefresh={() => loadData(true)}
                        batchMode={batchMode}
                        checked={selectedIds.includes(sig.secCode)}
                        onToggleCheck={onToggleCheck}
                        strategyTags={strategyPicks[sig.secCode] || []}
                      />
                    )) : (
                      <div className="text-center py-4 col-span-2 text-xs" style={{ color: 'var(--text-muted)' }}>当前筛选条件下无股票</div>
                    )}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 底部 */}
      {data && (
        <div className="text-center text-[10px] py-0.5" style={{ color: 'var(--text-muted)' }}>
          {data.generated_at} · 点击个股卡片选中联动K线 · 点击赛道头收起/展开
        </div>
      )}
    </div>
  );
}
