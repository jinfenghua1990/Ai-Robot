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
import { useWatchlistRealtimeStream } from '../hooks/useWatchlistRealtimeStream';

export default function WatchlistPage() {
  const navigate = useNavigate();
  const { executeTrade, tradeResult, clearTradeResult } = useTrading();
  const [sellModal, setSellModal] = useState(null);
  const [signals, setSignals] = useState(null);
  const [syncStatus, setSyncStatus] = useState(null);
  const [busy, setBusy] = useState('');
  const [log, setLog] = useState([]);
  const [selectedCode, setSelectedCode] = useState(null);
  const [realtimeMap, setRealtimeMap] = useState({}); // secCode -> 实时资金流摘要/明细
  const [syncOpen, setSyncOpen] = useState(false);
  const [strategyPicks, setStrategyPicks] = useState({});  // code -> [strategy_name]
  const [picksDate, setPicksDate] = useState('');
  const syncRef = useRef(null);
  const initialSelectedRef = useRef(false);

  // === 分组/排序/批量/筛选状态（分组=归类，筛选=过滤，排序=排序，三者独立）===
  const [groups, setGroups] = useState([{ name: '默认', count: 0 }]);
  const [activeGroup, setActiveGroup] = useState('全部');
  const [sortKey, setSortKey] = useState('bs');
  const [sortDir, setSortDir] = useState('desc');
  const [filters, setFilters] = useState({ junk: false, buyOnly: false, heating: false, hit_yuzi: false, hit_strategy: false, hit_trend: false, hit_capital: false, hit_popularity: false, hit_support: false, hit_accumulation: false });
  const [batchMode, setBatchMode] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [collapsedSectors, setCollapsedSectors] = useState(new Set());
  const toggleSector = (name) => {
    setCollapsedSectors(prev => {
      const n = new Set(prev);
      if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });
  };
  // 手动触发采集进度
  const [collect, setCollect] = useState({ running: false, done: 0, total: 0, started_at: null, finished_at: null, last_error: null });
  // 全市场资金流排行
  const [marketOpen, setMarketOpen] = useState(false);
  const [marketTab, setMarketTab] = useState('inflow');
  const [marketRank, setMarketRank] = useState(null); // { inflow:{items,updated_at}, outflow:{...} }
  const collectTimer = useRef(null);

  const addLog = (type, text) => setLog(l => [...l.slice(-4), { ts: new Date(), type, text }]);

  const toTsCode = useCallback((code) => {
    if (!code) return '';
    if (code.includes('.')) return code;
    return code.startsWith('6') || code.startsWith('9') ? `${code}.SH`
      : code.startsWith('8') || code.startsWith('4') ? `${code}.BJ`
      : `${code}.SZ`;
  }, []);

  const loadRealtimeBatch = useCallback(async (sigs) => {
    // 兼容旧调用：实际由 SSE hook 接管实时数据
    if (!sigs || sigs.length === 0) return;
  }, []);

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
    if (!initialSelectedRef.current) {
      initialSelectedRef.current = true;
      const first = sigs.find(x => x.quote);
      if (first) setSelectedCode(first.secCode);
    }
  }, []);

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

  // === 手动触发全量自选股采集（带进度轮询）===
  const triggerCollect = useCallback(async () => {
    if (collect.running) return;
    const res = await apiFetch('/api/watchlist/realtime-flow/trigger', { method: 'POST' });
    if (!res.ok) { addLog('error', '触发采集失败'); return; }
    setCollect({ running: true, done: 0, total: res.data?.total || 0, started_at: res.data?.started_at || null, finished_at: null, last_error: null });
    if (collectTimer.current) clearInterval(collectTimer.current);
    collectTimer.current = setInterval(async () => {
      const s = await apiFetch('/api/watchlist/realtime-flow/trigger/status');
      if (s.ok) {
        setCollect(s.data);
        if (!s.data.running) {
          clearInterval(collectTimer.current);
          collectTimer.current = null;
          addLog('success', `采集完成：${s.data.done}/${s.data.total} 只`);
          loadWatchlist(); loadData();
          setTimeout(() => setCollect(c => ({ ...c, finished_at: null })), 6000);
        }
      }
    }, 1500);
  }, [collect.running, loadWatchlist, loadData, addLog]);

  // 组件卸载时清理轮询定时器
  useEffect(() => () => { if (collectTimer.current) clearInterval(collectTimer.current); }, []);

  // === 全市场资金流排行 ===
  const loadMarketRank = useCallback(async (type) => {
    const { ok, data } = await apiFetch(`/api/watchlist/market-capital-ranking?rtype=${type}&top=50`);
    if (ok) setMarketRank(prev => ({ ...prev, [type]: data }));
  }, []);

  const toggleMarket = (open) => {
    setMarketOpen(open);
    if (open) {
      if (!marketRank?.inflow) loadMarketRank('inflow');
      if (!marketRank?.outflow) loadMarketRank('outflow');
    }
  };

  // === 实时数据：SSE 推送（5s 自动刷新），selectedCode 变化时拉分时点明细补全 ===
  const { realtimeMap: sseRealtimeMap, streamStatus } = useWatchlistRealtimeStream();

  // 合并 SSE 实时数据到 realtimeMap
  useEffect(() => {
    if (!sseRealtimeMap || Object.keys(sseRealtimeMap).length === 0) return;
    setRealtimeMap(prev => {
      const next = { ...prev };
      for (const [code, item] of Object.entries(sseRealtimeMap)) {
        const existing = prev[code];
        if (existing && existing.intraday_points && existing.intraday_points.length > 0) {
          next[code] = { ...existing, ...item, intraday_points: existing.intraday_points };
        } else {
          next[code] = item;
        }
      }
      return next;
    });
  }, [sseRealtimeMap]);

  // 选中股票变化时，请求该股实时资金流明细（分时点），并合并到 realtimeMap
  useEffect(() => {
    if (!selectedCode) return;
    let active = true;
    const tsCode = toTsCode(selectedCode);
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/realtime/stock-flow-detail?ts_code=${tsCode}`);
        if (active && ok) {
          setRealtimeMap(prev => ({ ...prev, [selectedCode]: data }));
        }
      } catch { /* silent */ }
    })();
    return () => { active = false; };
  }, [selectedCode, toTsCode]);

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

  // 按板块分组（同重点关注排版）
  const SECTOR_ICONS = {
    'MLCC': '', 'CPO': '', 'PCB': '🟩', '存储芯片': '💾', '先进封装': '🔧',
    '光纤光缆': '🔆', 'AI PC': '🖥️', 'AI芯片': '🧠', 'AI服务器': '🖧', 'OCS': '🔷',
    '培育钻石': '', '玻璃基板': '🔲', '陶瓷基板': '🏺', '高速链接': '⚡', '铜箔': '🟫',
    '树脂': '🍃', '电子布': '🧵', '液冷': '❄️', '六氟化钨': '⚗️', '碳酸铁锂': '🔋',
  };
  const SECTOR_COLORS = [
    '#6366f1','#a855f7','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6',
    '#06b6d4','#3b82f6','#8b5cf6','#d946ef','#64748b','#84cc16','#10b981','#0ea5e9',
  ];
  const groupedSectors = useMemo(() => {
    const map = {};
    for (const sig of displaySignals) {
      const sec = sig.sector || sig.sectorTrend?.sector || '其他';
      if (!map[sec]) map[sec] = [];
      map[sec].push(sig);
    }
    return Object.entries(map).map(([sector, stocks], i) => {
      const avgChg = stocks.reduce((sum, s) => sum + (s.quote?.changePct ?? 0), 0) / Math.max(stocks.length, 1);
      const upCount = stocks.filter(s => (s.quote?.changePct ?? 0) > 0).length;
      return { sector, stocks, avgChg, upCount, color: SECTOR_COLORS[i % SECTOR_COLORS.length] };
    }).sort((a, b) => b.avgChg - a.avgChg);
  }, [displaySignals]);

  const fmtChg = (v) => { if (v == null) return ''; const sign = v >= 0 ? '+' : ''; return `${sign}${v.toFixed(2)}%`; };
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
    { key: 'ths', name: '同花顺', color: 'var(--accent-blue)', bg: 'rgba(59,130,246,0.1)', st: ths, pull: 'pull_ths', push: 'push_ths' },
    { key: 'mx', name: '妙想', color: 'var(--accent-amber)', bg: 'rgba(234,179,8,0.1)', st: mx, pull: 'pull_mx', push: 'push_mx' },
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
    { key: '蓄势', color: 'var(--accent-amber)', test: c => c >= 0 && c < 1 },
    { key: '留意', color: 'var(--accent-blue)', test: c => c < 0 && c >= -3 },
    { key: '观望', color: 'var(--text-muted)', test: c => c < -3 && c >= -5 },
    { key: '衰退', color: 'var(--accent-green)', test: c => c < -5 },
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

      {/* ===== 悬浮置顶栏：标题 + 所有操作按钮（滚动时固定）===== */}
      <div className="sticky top-0 z-30 rounded-xl p-2.5 space-y-2"
        style={{
          background: 'var(--bg-card)',
          borderBottom: '2px solid var(--border-color)',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }}>

        {/* Row 1: 标题（左）| 主操作按钮组（右）*/}
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-xl font-bold flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-primary)' }}>
            <span>自选股 <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--accent-green)' }}>{totalCount}只</span></span>
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

          {/* 右侧操作按钮组：手动买入 / 同步 / 采集 / 刷新 —— 同一维度整齐排列 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* 手动买入入口 */}
            <ManualTradeBar>
              <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>·</span>
            </ManualTradeBar>
            {/* 分隔线 */}
            <span className="w-px h-4 bg-gray-300 dark:bg-gray-600" />
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
                        <div key={i} style={{ color: l.type === 'error' ? '#ef4444' : l.type === 'success' ? 'var(--accent-green)' : 'var(--text-muted)' }}>
                          {l.ts.toLocaleTimeString()} {l.text}
                        </div>
                      ))}
                    </div>
                  )}
              </div>
            )}
          </div>
          {/* 刷新 + 立即采集 + 实时连接状态 */}
          <div className="flex items-center gap-1.5">
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: streamStatus === 'open' ? 'var(--accent-green)' : streamStatus === 'fallback' ? '#facc15' : 'var(--text-muted)',
                boxShadow: streamStatus === 'open' ? '0 0 4px #22c55e' : 'none',
              }}
              title={streamStatus === 'open' ? '实时推送已连接' : streamStatus === 'fallback' ? '推送中断,使用轮询' : '连接中'}
            />
            {collect.running && (
              <span className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1" style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent-blue)' }}>
                <span className="inline-block w-2 h-2 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
                {collect.total > 0
                  ? `采集中 ${collect.done}/${collect.total} · 约剩 ${Math.max(0, Math.round((collect.total - collect.done) * 0.7))}s`
                  : '采集中…'}
              </span>
            )}
            {!collect.running && collect.finished_at && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: 'var(--accent-green)' }}>✅ 采集完成</span>
            )}
            <button
              onClick={triggerCollect}
              disabled={collect.running}
              className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1 disabled:opacity-50"
              style={{ borderColor: 'rgba(59,130,246,0.4)', color: 'var(--accent-blue)', background: collect.running ? 'rgba(59,130,246,0.06)' : 'transparent' }}
              title="立即触发一次全量自选股实时资金流采集（约 60-90 秒）"
            >
              ⚡ 立即采集
            </button>
            <button onClick={() => { loadWatchlist(); loadData(); }} className="px-2.5 py-1 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
          </div>{/* /右侧操作按钮组 */}
        </div>{/* /Row 1: 标题 | 操作按钮 */}

        {/* Row 2: 分组 · 筛选 · 趋势/资金快捷 · 排序 · 批量 · 计数 */}
        <div className="flex items-center gap-1.5 flex-wrap">
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
          {/* 命中快捷筛选按钮 */}
          <button
            onClick={() => setFilters(f => ({ ...f, hit_trend: !f.hit_trend }))}
            className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1"
            style={{
              borderColor: filters.hit_trend ? 'rgba(59,130,246,0.5)' : 'var(--border-color)',
              background: filters.hit_trend ? 'rgba(59,130,246,0.12)' : 'var(--bg-hover)',
              color: filters.hit_trend ? 'var(--accent-blue)' : 'var(--text-secondary)',
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
        </div>{/* /Row 2: 筛选工具栏 */}
      </div>{/* /sticky 悬浮置顶栏 */}

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
                <span className="font-bold" style={{ color: 'var(--accent-green)' }}>{selected.secName}</span>
                <span>{selected.secCode}</span>
                {selected.quote && selected.quote.changePct != null && <span style={{ color: selected.quote.changePct >= 0 ? '#ef4444' : 'var(--accent-green)' }}>{selected.quote.changePct >= 0 ? '+' : ''}{selected.quote.changePct}%</span>}
                {selected.sector && <span style={{ color: 'var(--text-muted)' }}>{selected.sector}</span>}
                {selectedSectorTrend?.available && (
                  <span style={{ color: selectedSectorTrend.heat_trend === 'up' ? '#ef4444' : selectedSectorTrend.heat_trend === 'down' ? 'var(--accent-green)' : 'var(--text-muted)' }}>
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

      {/* 自选股列表 — 按板块分组排版（同重点关注） */}
      {signals ? (
        displaySignals.length > 0 ? (
          <div className="space-y-2">
            {groupedSectors.map((sec) => {
              const expanded = !collapsedSectors.has(sec.sector);
              if (sec.stocks.length === 0) return null;
              return (
                <div key={sec.sector} className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                  {/* 板块头部 */}
                  <div className="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
                    style={{ borderBottom: expanded ? '1px solid var(--border-color)' : 'none' }}
                    onClick={() => toggleSector(sec.sector)}>
                    <span className="text-sm">{SECTOR_ICONS[sec.sector] || '📌'}</span>
                    <span className="text-xs font-bold" style={{ color: sec.color }}>{sec.sector}</span>
                    <span className="text-[10px] px-1 rounded" style={{
                      background: sec.avgChg >= 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                      color: sec.avgChg >= 0 ? '#ef4444' : '#22c55e',
                    }}>
                      {sec.upCount}/{sec.stocks.length}↑
                    </span>
                    <span className="text-xs font-bold" style={{ color: sec.avgChg >= 0 ? '#ef4444' : '#22c55e' }}>
                      {fmtChg(sec.avgChg)}
                    </span>
                    <span className="ml-auto text-[10px] w-4 text-center" style={{ color: 'var(--text-muted)' }}>
                      {expanded ? '▾' : '▸'}
                    </span>
                  </div>
                  {expanded && (
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 px-3 py-2">
                      {sec.stocks.map(sig => (
                        <WatchlistItem
                          key={sig.secCode}
                          signal={sig}
                          isSelected={selectedCode === sig.secCode}
                          realtimeFlow={realtimeMap[sig.secCode] || null}
                          onSelect={setSelectedCode}
                          onRemove={handleRemove}
                          onSell={setSellModal}
                          onRefresh={loadWatchlist}
                          batchMode={batchMode}
                          checked={selectedIds.includes(sig.secCode)}
                          onToggleCheck={onToggleCheck}
                          strategyTags={strategyPicks[sig.secCode] || []}
                        />
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ) : (
          <div className="text-center py-8">
            <div className="text-3xl mb-2">⭐</div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无自选股（靠云端下载拉取）</div>
          </div>
        )
      ) : [1,2,3,4].map(i => <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />)}

      {/* 全市场资金流排行（东财批量排行榜，单次请求） */}
      <div className="rounded-xl border mt-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center justify-between px-3 py-2">
          <button onClick={() => toggleMarket(!marketOpen)} className="flex items-center gap-2 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            <span>{marketOpen ? '▾' : '▸'}</span>
            <span>🌐 全市场资金流</span>
            <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>主力净流入/流出 Top 50 · 共 5537 只 A 股</span>
          </button>
          {marketOpen && (
            <div className="flex items-center gap-1.5">
              <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: 'var(--border-color)' }}>
                <button onClick={() => { setMarketTab('inflow'); loadMarketRank('inflow'); }} className="px-2.5 py-1 text-[11px]" style={{ background: marketTab === 'inflow' ? 'rgba(239,68,68,0.15)' : 'transparent', color: marketTab === 'inflow' ? '#ef4444' : 'var(--text-secondary)' }}>🔥 净流入</button>
                <button onClick={() => { setMarketTab('outflow'); loadMarketRank('outflow'); }} className="px-2.5 py-1 text-[11px]" style={{ background: marketTab === 'outflow' ? 'rgba(59,130,246,0.15)' : 'transparent', color: marketTab === 'outflow' ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>💧 净流出</button>
              </div>
              <button onClick={() => loadMarketRank(marketTab)} className="px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄</button>
            </div>
          )}
        </div>
        {marketOpen && (() => {
          const rank = marketRank?.[marketTab];
          const items = rank?.items || [];
          const fmtMoney = (v) => {
            if (v == null) return '-';
            const a = Math.abs(v);
            if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
            if (a >= 1e4) return (v / 1e4).toFixed(0) + '万';
            return String(Math.round(v));
          };
          return (
            <div className="px-3 pb-3">
              {rank?.updated_at && <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>更新于 {rank.updated_at}</div>}
              <div className="overflow-x-auto">
                <table className="w-full text-[11px]">
                  <thead>
                    <tr style={{ color: 'var(--text-muted)' }}>
                      <th className="text-left py-1 px-1 font-medium">#</th>
                      <th className="text-left py-1 px-1 font-medium">代码</th>
                      <th className="text-left py-1 px-1 font-medium">名称</th>
                      <th className="text-right py-1 px-1 font-medium">现价</th>
                      <th className="text-right py-1 px-1 font-medium">涨跌幅</th>
                      <th className="text-right py-1 px-1 font-medium">主力净流入</th>
                      <th className="text-right py-1 px-1 font-medium">占比</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.length === 0 && rank?.error && (
                      <tr><td colSpan={7} className="text-center py-4" style={{ color: '#f59e0b' }}>排行榜加载失败（东财接口偶发限流），<button onClick={() => loadMarketRank(marketTab)} className="underline">点此重试</button></td></tr>
                    )}
                    {items.length === 0 && !rank?.error && (
                      <tr><td colSpan={7} className="text-center py-4" style={{ color: 'var(--text-muted)' }}>加载中…</td></tr>
                    )}
                    {items.map((it, i) => {
                      const up = (it.main_net || 0) >= 0;
                      const pctUp = (it.pct || 0) >= 0;
                      return (
                        <tr key={it.code} style={{ borderTop: '1px solid var(--border-color)' }}>
                          <td className="py-1 px-1" style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                          <td className="py-1 px-1" style={{ color: 'var(--text-secondary)' }}>{it.code}</td>
                          <td className="py-1 px-1 font-medium" style={{ color: 'var(--text-primary)' }}>{it.name}</td>
                          <td className="py-1 px-1 text-right">{it.price != null ? it.price.toFixed(2) : '-'}</td>
                          <td className="py-1 px-1 text-right" style={{ color: pctUp ? '#ef4444' : 'var(--accent-green)' }}>{it.pct != null ? (pctUp ? '+' : '') + it.pct.toFixed(2) + '%' : '-'}</td>
                          <td className="py-1 px-1 text-right font-semibold" style={{ color: up ? '#ef4444' : 'var(--accent-green)' }}>{up ? '+' : ''}{fmtMoney(it.main_net)}</td>
                          <td className="py-1 px-1 text-right" style={{ color: up ? '#ef4444' : 'var(--accent-green)' }}>{it.main_net_pct != null ? (up ? '+' : '') + it.main_net_pct.toFixed(2) + '%' : '-'}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </div>
          );
        })()}
      </div>

      {sellModal && <TradeModal stockCode={sellModal.stockCode} stockName={sellModal.stockName} type="sell" positionCount={sellModal.positionCount || 0} onClose={() => setSellModal(null)} onConfirm={executeTrade} />}
      </div>
    </div>
  );
}
