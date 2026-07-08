import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTrading } from '../context/TradingContext';
import TradeModal from '../components/trading/TradeModal';
import WatchlistItem from '../components/trading/WatchlistItem';
import ManualTradeBar from '../components/trading/ManualTradeBar';
import KLineChart from '../components/charts/KLineChart';
import GroupBar from '../components/watchlist/GroupBar';
import SortBar, { SORTS } from '../components/watchlist/SortBar';
import BatchBar from '../components/watchlist/BatchBar';
import FilterBar from '../components/watchlist/FilterBar';
import { BUY_COLOR } from '../utils/colors';
import { apiFetch } from '../utils/request';
import { TOAST_DURATION } from '../utils/constants';

export default function WatchlistPage() {
  const navigate = useNavigate();
  const { executeTrade, tradeResult, clearTradeResult } = useTrading();
  const [sellModal, setSellModal] = useState(null);
  const [signals, setSignals] = useState(null);
  const [syncStatus, setSyncStatus] = useState(null);
  const [busy, setBusy] = useState('');
  const [log, setLog] = useState([]);
  const [selectedCode, setSelectedCode] = useState(null);
  const [realtimeFlow, setRealtimeFlow] = useState(null);
  const [syncOpen, setSyncOpen] = useState(false);
  const [strategyPicks, setStrategyPicks] = useState({});  // code -> [strategy_name]
  const [picksDate, setPicksDate] = useState('');
  const syncRef = useRef(null);

  // === 分组/排序/批量/筛选状态（分组=归类，筛选=过滤，排序=排序，三者独立）===
  const [groups, setGroups] = useState([{ name: '默认', count: 0 }]);
  const [activeGroup, setActiveGroup] = useState('全部');
  const [sortKey, setSortKey] = useState('bs');
  const [sortDir, setSortDir] = useState('desc');
  const [filters, setFilters] = useState({ junk: false, buyOnly: false, heating: false, hit_yuzi: false, hit_strategy: false, hit_trend: false, hit_capital: false, hit_popularity: false, hit_support: false, hit_accumulation: false });
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);

  const addLog = (type, text) => setLog(l => [...l.slice(-4), { ts: new Date(), type, text }]);

  const loadWatchlist = useCallback(async () => {
    setSignals(null);
    const { ok, data } = await apiFetch('/api/watchlist');
    if (!ok) { setSignals({ signals: [], summary: {} }); return; }
    const sigs = data?.signals || [];
    setSignals({ ...data, signals: sigs });
    const cache = {};
    for (const sig of sigs) {
      if (sig.sectorTrend?.heat_series) cache[sig.secCode] = sig.sectorTrend.heat_series;
    }
    window.__wlSectorCache = cache;
    if (!selectedCode) {
      const first = sigs.find(x => x.quote);
      if (first) setSelectedCode(first.secCode);
    }
  }, [selectedCode]);

  const loadData = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/sync/status');
    if (ok) setSyncStatus(data);
  }, []);

  const loadGroups = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/watchlist/groups');
    if (ok && data.groups) setGroups(data.groups);
  }, []);

  const loadStrategyPicks = useCallback(async () => {
    try {
      const { ok, data } = await apiFetch('/api/bs-screener/strategy-picks');
      if (ok) {
        setStrategyPicks(data.code_to_strategies || {});
        setPicksDate(data.date || '');
      }
    } catch (e) { /* silent */ }
  }, []);

  useEffect(() => { Promise.all([loadGroups(), loadStrategyPicks()]).catch(() => {}); }, [loadGroups, loadStrategyPicks]);

  // 选中股票变化时，请求该股实时资金流（只 1 次请求，不做 N+1）
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

  useEffect(() => { Promise.all([loadWatchlist(), loadData()]).catch(() => {}); }, [loadWatchlist, loadData]);
  useEffect(() => { if (tradeResult) { const t = setTimeout(clearTradeResult, TOAST_DURATION); return () => clearTimeout(t); } }, [tradeResult, clearTradeResult]);

  // 点击外部关闭云端同步下拉
  useEffect(() => {
    const handler = (e) => { if (syncRef.current && !syncRef.current.contains(e.target)) setSyncOpen(false); };
    if (syncOpen) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [syncOpen]);

  const handleRemove = useCallback(async (code, name) => {
    // 1. 先本地立即移除（秒级响应，零卡顿）
    setSignals(prev => prev ? { ...prev, signals: prev.signals.filter(s => s.secCode !== code) } : prev);
    setSelectedCode(prev => prev === code ? null : prev);
    addLog('info', `已移除 ${name || code}（3秒后云端同步删除）`);
    // 2. 后台异步请求删除 + 静默拉取最新数据
    await apiFetch(`/api/watchlist/${code}`, { method: 'DELETE' });
    // 3. 3秒防抖：等云端同步触发后再拉取最新数据
    setTimeout(() => { loadWatchlist(); loadData(); }, 3000);
  }, [loadWatchlist, loadData]);

  const runOne = async (action, label) => {
    if (busy) { addLog('error', '有操作进行中，请稍候'); return; }
    setBusy(action);
    addLog('info', `${label}...`);
    try {
      const url = {
        pull_ths: '/api/sync/ths/pull', push_ths: '/api/sync/ths/push',
        pull_mx: '/api/sync/mx/pull', push_mx: '/api/sync/mx/push',
        pull_sina: '/api/sync/sina/pull', push_sina: '/api/sync/sina/push',
      }[action];
      const { ok, data, error } = await apiFetch(url, { method: 'POST' });
      if (!ok) {
        addLog('error', error || `${label}失败`);
      } else {
        const parts = [];
        if (data.added) parts.push(`新增${data.added}`);
        if (data.deleted) parts.push(`删除${data.deleted}`);
        if (data.pushed) parts.push(`推送${data.pushed}`);
        if (data.skipped) parts.push(`跳过${data.skipped}`);
        addLog('success', `${label}完成: ${parts.join(' ') || '无变化'}`);
      }
    } catch (e) { addLog('error', e.message); }
    setBusy(''); loadWatchlist(); loadData();
  };

  const ths = syncStatus?.platforms?.ths || {};
  const mx = syncStatus?.platforms?.mx || {};
  const sina = syncStatus?.platforms?.sina || {};
  const local = syncStatus?.platforms?.local || {};
  const totalCount = signals?.signals?.length || 0;
  const selected = useMemo(
    () => signals?.signals?.find(s => s.secCode === selectedCode),
    [signals, selectedCode]
  );
  const selectedSectorTrend = selected?.sectorTrend;

  // === 分组（归类）→ 筛选（过滤）→ 排序（排序）三步独立处理 ===
  const displaySignals = useMemo(() => {
    // 1. 分组：按 activeGroup 归类（"全部"= 不分组过滤，显示所有 80 只）
    let arr = activeGroup === '全部'
      ? (signals?.signals || [])
      : (signals?.signals || []).filter(s => (s.group || '默认') === activeGroup);
    // 2. 筛选：按 filters 过滤（独立于分组）
    if (filters.junk) arr = arr.filter(s => s.marketState?.market_state !== 'CHOPPY');
    if (filters.buyOnly) arr = arr.filter(s => s.bsSignal === 'B');
    if (filters.heating) arr = arr.filter(s => s.sectorTrend?.heat_trend === 'up');
    // 6 大命中标签过滤
    if (filters.hit_yuzi) arr = arr.filter(s => s.hitTags?.includes('yuzi'));
    if (filters.hit_strategy) arr = arr.filter(s => s.hitTags?.includes('strategy'));
    if (filters.hit_trend) arr = arr.filter(s => s.hitTags?.includes('trend'));
    if (filters.hit_capital) arr = arr.filter(s => s.hitTags?.includes('capital'));
    if (filters.hit_popularity) arr = arr.filter(s => s.hitTags?.includes('popularity'));
    if (filters.hit_support) arr = arr.filter(s => s.hitTags?.includes('support'));
    if (filters.hit_accumulation) arr = arr.filter(s => s.hitTags?.includes('accumulation'));
    // 3. 排序
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
    arr = [...arr].sort((a, b) => {
      const va = getVal(a), vb = getVal(b);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
    return arr;
  }, [signals, activeGroup, filters, sortKey, sortDir]);

  // 批量操作
  const onSelectAll = useCallback(() => {
    setSelectedIds(displaySignals.map(s => s.secCode));
  }, [displaySignals]);
  const onInvert = useCallback(() => {
    const sel = new Set(selectedIds);
    setSelectedIds(displaySignals.filter(s => !sel.has(s.secCode)).map(s => s.secCode));
  }, [displaySignals, selectedIds]);
  const onClearSel = useCallback(() => setSelectedIds([]), []);
  const onToggleCheck = useCallback((code) => {
    setSelectedIds(s => s.includes(code) ? s.filter(c => c !== code) : [...s, code]);
  }, []);
  const onBatchDelete = useCallback(async () => {
    const { ok } = await apiFetch('/api/watchlist/batch-delete', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stock_codes: selectedIds }),
    });
    if (ok) {
      addLog('success', `批量删除 ${selectedIds.length} 只`);
      setSelectedIds([]); setBatchMode(false);
      loadWatchlist(); loadGroups();
    } else { addLog('error', '批量删除失败'); }
  }, [selectedIds, loadWatchlist, loadGroups]);
  const onBatchMove = useCallback(async (target) => {
    const { ok } = await apiFetch('/api/watchlist/batch-move-group', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stock_codes: selectedIds, target_group: target }),
    });
    if (ok) {
      addLog('success', `已移动 ${selectedIds.length} 只到「${target}」`);
      setSelectedIds([]); setBatchMode(false);
      loadWatchlist(); loadGroups();
    } else { addLog('error', '批量移动失败'); }
  }, [selectedIds, loadWatchlist, loadGroups]);
  const onExport = useCallback(() => {
    window.open('/api/watchlist/export', '_blank');
  }, []);

  // 当切换分组时清空选中
  useEffect(() => { setSelectedIds([]); }, [activeGroup]);

  const platforms = [
    { key: 'ths', name: '同花顺', color: '#3b82f6', bg: 'rgba(59,130,246,0.1)', st: ths, pull: 'pull_ths', push: 'push_ths' },
    { key: 'mx', name: '妙想', color: '#eab308', bg: 'rgba(234,179,8,0.1)', st: mx, pull: 'pull_mx', push: 'push_mx' },
    { key: 'sina', name: '新浪', color: '#ef4444', bg: 'rgba(239,68,68,0.1)', st: sina, pull: 'pull_sina', push: 'push_sina' },
  ];

  // 状态卡：板块升温 | 可买 | 资金流入（资金流入用个股自身涨幅，不再重复板块flow）
  const statCards = [
    { key: 'heat', label: '板块升温', sub: '热度↑', count: signals?.summary?.sector_heating ?? 0, color: '#ef4444', top: signals?.summary?.sector_heating_top, valKey: 'heat', valFmt: v => `热度${v}` },
    { key: 'buy', label: '可买', sub: 'B信号', count: signals?.summary?.buy ?? 0, color: BUY_COLOR, top: signals?.summary?.buy_top, valKey: null, valFmt: () => null },
    { key: 'flow', label: '资金流入', sub: '净流入', count: signals?.summary?.inflow ?? 0, color: '#f97316', top: signals?.summary?.inflow_top, valKey: 'chg', valFmt: v => `${v >= 0 ? '+' : ''}${v}%` },
  ];

  // 7阶段趋势阶段状态栏（基于当日涨跌幅推断阶段）
  const STAGE_DEFS = [
    { key: '主升', color: '#dc2626', test: c => c >= 9.5 },
    { key: '加速', color: '#ef4444', test: c => c >= 5 && c < 9.5 },
    { key: '突破', color: '#f97316', test: c => c >= 1 && c < 5 },
    { key: '蓄势', color: '#eab308', test: c => c >= 0 && c < 1 },
    { key: '留意', color: '#3b82f6', test: c => c < 0 && c >= -3 },
    { key: '观望', color: '#64748b', test: c => c < -3 && c >= -5 },
    { key: '衰退', color: '#22c55e', test: c => c < -5 },
  ];
  const stageStats = useMemo(() => {
    const sigs = signals?.signals || [];
    const stats = {};
    STAGE_DEFS.forEach(s => stats[s.key] = 0);
    sigs.forEach(s => {
      const chg = s.quote?.changePct ?? 0;
      const stage = STAGE_DEFS.find(d => d.test(chg));
      if (stage) stats[stage.key]++;
    });
    return stats;
  }, [signals]);

  return (
    <div className="space-y-3">
      {tradeResult && (
        <div className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm shadow-lg" style={{ background: tradeResult.success ? 'rgba(34,197,94,0.9)' : 'rgba(239,68,68,0.9)', color: '#fff' }}>
          {tradeResult.success ? '✅ ' : '❌ '}{tradeResult.message}
        </div>
      )}

      {/* 标题栏：自选股 | 云端同步按钮 + 刷新按钮 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-primary)' }}>
          <span>自选股 <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>{totalCount}只</span></span>
          {/* 保留策略命中数（科创V7 + 创业V9） */}
          {Object.keys(strategyPicks).length > 0 && (
            <span className="text-xs flex items-center gap-1.5" style={{ color: 'var(--text-muted)' }}>
              <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.15)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}>
                📊 科创V7 {Object.values(strategyPicks).filter(arr => arr.includes('BS-科创-V7')).length}
              </span>
              <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(249,115,22,0.15)', color: '#f97316', border: '1px solid rgba(249,115,22,0.3)' }}>
                📊 创业V9 {Object.values(strategyPicks).filter(arr => arr.includes('BS-创业-V9')).length}
              </span>
              {picksDate && <span className="text-[10px]">({picksDate})</span>}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-2">
          {/* 云端同步下拉按钮 */}
          <div className="relative" ref={syncRef}>
            <button onClick={() => setSyncOpen(o => !o)}
              className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
              style={{ borderColor: 'rgba(168,85,247,0.4)', color: '#a855f7', background: syncOpen ? 'rgba(168,85,247,0.1)' : 'transparent' }}>
              🔗 云端同步 {syncOpen ? '▴' : '▾'}
            </button>
            {syncOpen && (
              <div className="absolute right-0 top-full mt-1 w-80 rounded-xl border p-2.5 z-40 shadow-xl"
                style={{ borderColor: 'rgba(168,85,247,0.3)', background: 'var(--bg-card)' }}>
                <div className="flex items-center justify-between mb-1.5">
                  <span className="text-xs font-bold" style={{ color: '#a855f7' }}>🔗 云端同步</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>本地 {local.count ?? 0} 只 · 增删自动同步</span>
                </div>
                <div className="space-y-1">
                  {platforms.map(p => {
                    const connected = p.st.connected !== false;
                    const count = p.st.count;
                    const disabled = !!busy || !connected;
                    return (
                      <div key={p.key} className="flex items-center gap-2 px-2 py-1 rounded-lg" style={{ background: p.bg }}>
                        <span className="text-xs font-bold w-12" style={{ color: p.color }}>{connected ? '●' : '○'} {p.name}</span>
                        <span className="text-[11px] flex-1" style={{ color: connected ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                          {connected ? `${count ?? 0}只` : (p.st.note || p.st.error || '未连接')}
                        </span>
                        <button onClick={() => runOne(p.pull, `${p.name}↓`)} disabled={disabled} className="px-1.5 py-0.5 rounded text-[10px] border disabled:opacity-40" style={{ borderColor: p.color, color: p.color }}>⬇</button>
                        <button onClick={() => runOne(p.push, `${p.name}↑`)} disabled={disabled} className="px-1.5 py-0.5 rounded text-[10px] border disabled:opacity-40" style={{ borderColor: p.color, color: p.color }}>⬆</button>
                      </div>
                    );
                  })}
                </div>
                {log.length > 0 && (
                  <div className="rounded p-1.5 text-[10px] space-y-0.5 mt-1.5 max-h-24 overflow-y-auto" style={{ background: 'rgba(0,0,0,0.2)', fontFamily: 'monospace' }}>
                    {log.map((l, i) => (
                      <div key={i} style={{ color: l.type === 'error' ? '#ef4444' : l.type === 'success' ? '#22c55e' : 'var(--text-muted)' }}>
                        {l.ts.toLocaleTimeString()} {l.text}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
          {/* 刷新 */}
          <button onClick={() => { loadWatchlist(); loadData(); }} className="px-2.5 py-1 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
        </div>
      </div>

      {/* 左右并排：左=合并状态模块(3卡)  右=K线图 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 左：合并状态模块（3 张状态卡竖排在一个容器内） */}
        <div className="rounded-xl border p-2.5 space-y-2" style={{ borderColor: 'rgba(99,102,241,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-[11px] font-bold flex items-center gap-2" style={{ color: 'var(--text-secondary)' }}>
            📊 池子状态 <span style={{ color: 'var(--text-muted)' }}>· 点击个股标签联动右侧K线</span>
          </div>
          {/* 7阶段趋势阶段状态栏 */}
          <div className="flex items-center gap-1 flex-wrap rounded-lg p-1.5" style={{ background: 'var(--bg-surface)' }}>
            {STAGE_DEFS.map(stage => {
              const count = stageStats[stage.key] || 0;
              const pct = totalCount > 0 ? Math.round(count / totalCount * 100) : 0;
              const active = filters.buyOnly && stage.key === '主升';
              return (
                <button
                  key={stage.key}
                  onClick={() => {/* 预留：点击筛选该阶段 */}}
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

      {/* === 手动买入 + 工具栏（分组/排序/批量）同一行横排 === */}
      <ManualTradeBar>
        <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>·</span>
        <GroupBar
          groups={groups}
          active={activeGroup}
          onChange={setActiveGroup}
          onRefresh={loadGroups}
          addLog={addLog}
        />
        <FilterBar
          activeFilters={filters}
          onToggle={(key, val) => setFilters(f => ({ ...f, [key]: val }))}
          addLog={addLog}
        />
        {/* 命中快捷筛选按钮：放在排序左边，先过滤再排序 */}
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
          addLog={addLog}
        />
        <BatchBar
          batchMode={batchMode}
          selectedIds={selectedIds}
          allStocks={displaySignals}
          groups={groups}
          activeGroup={activeGroup}
          onToggleBatch={() => setBatchMode(b => !b)}
          onSelectAll={onSelectAll}
          onInvert={onInvert}
          onClearSel={onClearSel}
          onBatchDelete={onBatchDelete}
          onBatchMove={onBatchMove}
          onExport={onExport}
          addLog={addLog}
        />
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {displaySignals.length} / {totalCount} 只{filters.junk && ' · 拒绝震荡'}{filters.buyOnly && ' · 仅可买'}{filters.heating && ' · 板块升温'}{filters.hit_trend && ' · 趋势命中'}{filters.hit_capital && ' · 资金命中'}
        </span>
      </ManualTradeBar>

      {/* 自选股列表（桌面端左右双卡片并排，移动端单列；memoized：点击切换只重渲染当前卡） */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-2">
        {signals ? (
          displaySignals.length > 0 ? displaySignals.map(sig => (
            <WatchlistItem
              key={sig.secCode}
              signal={sig}
              isSelected={selectedCode === sig.secCode}
              realtimeFlow={selectedCode === sig.secCode ? realtimeFlow : null}
              onSelect={setSelectedCode}
              onRemove={handleRemove}
              onSell={setSellModal}
              onRefresh={loadWatchlist}
              batchMode={batchMode}
              checked={selectedIds.includes(sig.secCode)}
              onToggleCheck={onToggleCheck}
              strategyTags={strategyPicks[sig.secCode] || []}
            />
          )) : (
            <div className="text-center py-8 col-span-2">
              <div className="text-3xl mb-2">⭐</div>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无自选股（靠云端下载拉取）</div>
            </div>
          )
        ) : [1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />)}
      </div>

      {sellModal && <TradeModal stockCode={sellModal.stockCode} stockName={sellModal.stockName} type="sell" positionCount={sellModal.positionCount || 0} onClose={() => setSellModal(null)} onConfirm={executeTrade} />}
    </div>
  );
}
