import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { useTrading } from '../context/TradingContext';
import TradeModal from '../components/trading/TradeModal';
import WatchlistItem from '../components/trading/WatchlistItem';
import ManualTradeBar from '../components/trading/ManualTradeBar';
import GroupBar from '../components/watchlist/GroupBar';
import SortBar from '../components/watchlist/SortBar';
import BatchBar from '../components/watchlist/BatchBar';
import FilterBar from '../components/watchlist/FilterBar';
import MarketRankTable from '../components/watchlist/MarketRankTable';
import { BUY_COLOR } from '../utils/colors';
import { apiFetch } from '../utils/request';
import { TOAST_DURATION } from '../utils/constants';
import { useWatchlistRealtimeStream } from '../hooks/useWatchlistRealtimeStream';

// === 模块级常量（避免每次渲染重建，提升 useMemo 引用稳定性） ===
// 稳定空数组引用，避免 strategyPicks[code] || [] 每次新建导致 WatchlistItem memo 失效
const EMPTY_ARR = [];
// 板块图标映射
const SECTOR_ICONS = {
  'MLCC': '', 'CPO': '', 'PCB': '🟩', '存储芯片': '💾', '先进封装': '🔧',
  '光纤光缆': '🔆', 'AI PC': '🖥️', 'AI芯片': '🧠', 'AI服务器': '🖧', 'OCS': '🔷',
  '培育钻石': '', '玻璃基板': '🔲', '陶瓷基板': '🏺', '高速链接': '⚡', '铜箔': '🟫',
  '树脂': '🍃', '电子布': '🧵', '液冷': '❄️', '六氟化钨': '⚗️', '碳酸铁锂': '🔋',
};
// 板块配色（按出现顺序循环分配）
const SECTOR_COLORS = [
  '#6366f1','#a855f7','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6',
  '#06b6d4','#3b82f6','#8b5cf6','#d946ef','#64748b','#84cc16','#10b981','#0ea5e9',
];
// 7阶段趋势定义（基于当日涨跌幅推断阶段）
const STAGE_DEFS = [
  { key: '主升', color: '#dc2626', test: c => c >= 9.5 },
  { key: '加速', color: '#ef4444', test: c => c >= 5 && c < 9.5 },
  { key: '突破', color: '#f97316', test: c => c >= 1 && c < 5 },
  { key: '蓄势', color: 'var(--accent-amber)', test: c => c >= 0 && c < 1 },
  { key: '留意', color: 'var(--accent-blue)', test: c => c < 0 && c >= -3 },
  { key: '观望', color: 'var(--text-muted)', test: c => c < -3 && c >= -5 },
  { key: '衰退', color: 'var(--accent-green)', test: c => c < -5 },
];

export default function WatchlistPage() {
  const { executeTrade, tradeResult, clearTradeResult } = useTrading();
  const [sellModal, setSellModal] = useState(null);
  const [signals, setSignals] = useState(null);
  const [focusSignals, setFocusSignals] = useState([]);
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
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [poolView, setPoolView] = useState(() => searchParams.get('pool') || 'all');
  const openAnalysis = useCallback((c) => navigate(`/stock-analysis?code=${c}`), [navigate]);

  // === 分组/排序/批量/筛选状态（分组=归类，筛选=过滤，排序=排序，三者独立）===
  const [groups, setGroups] = useState([{ name: '默认', count: 0 }]);
  const [activeGroup, setActiveGroup] = useState('全部');
  const [sortKey, setSortKey] = useState('bs');
  const [sortDir, setSortDir] = useState('desc');
  const [filters, setFilters] = useState({ junk: false, buyOnly: false, heating: false, hit_yuzi: false, hit_strategy: false, hit_trend: false, hit_capital: false, hit_popularity: false, hit_support: false, hit_accumulation: false, stage: null });
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
  const collectTimer = useRef(null);
  const finishTimerRef = useRef(null);    // 采集完成 6s 后清空 finished_at 的 setTimeout
  const removeTimerRef = useRef(null);   // 删除自选股后 3s 重新拉取的 setTimeout

  const addLog = useCallback((type, text) => setLog(l => [...l.slice(-4), { ts: new Date(), type, text }]), []);

  const toTsCode = useCallback((code) => {
    if (!code) return '';
    if (code.includes('.')) return code;
    return code.startsWith('6') || code.startsWith('9') ? `${code}.SH`
      : code.startsWith('8') || code.startsWith('4') ? `${code}.BJ`
      : `${code}.SZ`;
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

  const loadFocusStocks = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/focus-stocks');
    if (!ok || !data?.sectors) return;
    const flattened = data.sectors.flatMap((sector) =>
      (sector.stocks || []).map((stock) => ({
        ...stock,
        poolSources: ['重点关注'],
        group: stock.group || '重点关注',
        focusSector: sector.sector || '',
      }))
    );
    setFocusSignals(flattened);
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
          if (finishTimerRef.current) clearTimeout(finishTimerRef.current);
          finishTimerRef.current = setTimeout(() => setCollect(c => ({ ...c, finished_at: null })), 6000);
        }
      }
    }, 1500);
  }, [collect.running, loadWatchlist, loadData, addLog]);

  // 组件卸载时清理所有定时器（轮询 + finish + remove）
  useEffect(() => () => {
    if (collectTimer.current) clearInterval(collectTimer.current);
    if (finishTimerRef.current) clearTimeout(finishTimerRef.current);
    if (removeTimerRef.current) clearTimeout(removeTimerRef.current);
  }, []);

  // === 实时数据：SSE 推送（5s 自动刷新），selectedCode 变化时拉分时点明细补全 ===
  const { realtimeMap: sseRealtimeMap, streamStatus } = useWatchlistRealtimeStream();

  // 合并 SSE 实时数据到 realtimeMap（仅对变化的 code 替换引用，保留已有 intraday_points）
  useEffect(() => {
    if (!sseRealtimeMap || Object.keys(sseRealtimeMap).length === 0) return;
    setRealtimeMap(prev => {
      let next = prev;
      let dirty = false;
      for (const [code, item] of Object.entries(sseRealtimeMap)) {
        const existing = prev[code];
        // 保留已有 intraday_points（selectedCode 拉取的分时明细）
        const merged = existing?.intraday_points?.length
          ? { ...existing, ...item, intraday_points: existing.intraday_points }
          : item;
        if (merged !== existing) {
          if (!dirty) { next = { ...prev }; dirty = true; }
          next[code] = merged;
        }
      }
      return dirty ? next : prev;
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

  useEffect(() => { Promise.all([loadWatchlist(), loadFocusStocks(), loadData()]).catch(() => {}); }, [loadWatchlist, loadFocusStocks, loadData]);
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
    // 3. 3秒防抖：等云端同步触发后再拉取最新数据（保存 timer 以便卸载时清理）
    if (removeTimerRef.current) clearTimeout(removeTimerRef.current);
    removeTimerRef.current = setTimeout(() => {
      removeTimerRef.current = null;
      loadWatchlist(); loadData();
    }, 3000);
  }, [loadWatchlist, loadData]);

  // 同步模式：incremental=增量(只加不删) / mirror=镜像(完全覆盖)
  const [syncMode, setSyncMode] = useState('incremental');

  const runOne = async (action, label) => {
    if (busy) { addLog('error', '有操作进行中，请稍候'); return; }
    setBusy(action);
    addLog('info', `${label}...`);
    try {
      const urlMap = {
        pull_ths: '/api/sync/ths/pull', push_ths: '/api/sync/ths/push',
        pull_mx: '/api/sync/mx/pull', push_mx: '/api/sync/mx/push',
      };
      // 增量模式只加不删（mirror=false）；镜像模式完全覆盖（mirror=true）
      const url = `${urlMap[action]}?mirror=${syncMode === 'mirror'}`;
      // 同步可能涉及逐股推送 100+ 股票，单次请求耗时较长，用 5 分钟超时
      const { ok, data, error } = await apiFetch(url, { method: 'POST' }, 300000, 0);
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
  const local = syncStatus?.platforms?.local || {};
  // 合并股票池：自选数据优先，重点关注只补充自选中没有的标的。
  // 重叠标的只保留一张卡，并保留两个来源标签。
  const poolSignals = useMemo(() => {
    const merged = new Map();
    for (const signal of (signals?.signals || [])) {
      merged.set(signal.secCode, { ...signal, poolSources: ['自选'] });
    }
    for (const focus of focusSignals) {
      const current = merged.get(focus.secCode);
      if (current) {
        merged.set(focus.secCode, {
          ...current,
          poolSources: ['自选', '重点关注'],
          focusSector: focus.focusSector || '',
        });
      } else {
        merged.set(focus.secCode, focus);
      }
    }
    return Array.from(merged.values());
  }, [signals, focusSignals]);

  const totalCount = poolSignals.length;
  const sourceCounts = useMemo(() => ({
    all: poolSignals.length,
    watchlist: poolSignals.filter(s => s.poolSources?.includes('自选')).length,
    focus: poolSignals.filter(s => s.poolSources?.includes('重点关注')).length,
    both: poolSignals.filter(s => s.poolSources?.length === 2).length,
  }), [poolSignals]);

  // === 分组（归类）→ 筛选（过滤）→ 排序（排序）三步独立处理 ===
  const displaySignals = useMemo(() => {
    // 1. 分组：按 activeGroup 归类（"全部"= 不分组过滤，显示所有 80 只）
    let arr = poolView === 'all'
      ? poolSignals
      : poolSignals.filter(s => s.poolSources?.includes(poolView === 'watchlist' ? '自选' : '重点关注') && (poolView !== 'both' || s.poolSources?.length === 2));
    if (activeGroup !== '全部') arr = arr.filter(s => (s.group || '默认') === activeGroup);
    // 2. 筛选：按 filters 过滤（独立于分组）
    if (filters.junk) arr = arr.filter(s => s.marketState?.market_state !== 'CHOPPY');
    if (filters.buyOnly) arr = arr.filter(s => s.bsSignal === 'B');
    if (filters.heating) arr = arr.filter(s => s.sectorTrend?.heat_trend === 'up');
    // 6 大命中标签过滤
    if (filters.hit_yuzi) arr = arr.filter(s => s.hitTags?.includes('yuzi'));
    // 策略筛选改用 strategyPicks（顶部 📊 BS-XXX / 🔥 游资龙头 数据源）
    if (filters.hit_strategy) arr = arr.filter(s => !!strategyPicks[s.secCode]);
    if (filters.hit_trend) arr = arr.filter(s => s.hitTags?.includes('trend'));
    if (filters.hit_capital) arr = arr.filter(s => s.hitTags?.includes('capital'));
    if (filters.hit_popularity) arr = arr.filter(s => s.hitTags?.includes('popularity'));
    if (filters.hit_support) arr = arr.filter(s => s.hitTags?.includes('support'));
    if (filters.hit_accumulation) arr = arr.filter(s => s.hitTags?.includes('accumulation'));
    // 阶段筛选：按当日涨跌幅区间过滤
    if (filters.stage) {
      const stageDef = STAGE_DEFS.find(d => d.key === filters.stage);
      if (stageDef) arr = arr.filter(s => stageDef.test(s.quote?.changePct ?? 0));
    }
    // 3. 排序
    const dir = sortDir === 'desc' ? -1 : 1;
    const getVal = (s) => {
      switch (sortKey) {
        case 'bs': {
          const lastB = (s.techSignals || []).filter(t => t.type === 'B').sort((a, b) => (b.date || '').localeCompare(a.date || ''))[0];
          return lastB?.date || '0000-00-00';
        }
        case 'leader': return (s.bsSignal === 'B' ? 1 : 0) * 1000 + (s.quote?.changePct || 0);
        case 'overall': return s.overallScore ?? -1;   // 8维综合评分（替代原 buyPower）
        case 'trend': return s.trendStrength ?? s.technical?.score ?? -1;  // 趋势强度单维
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
  }, [poolSignals, poolView, activeGroup, filters, sortKey, sortDir]);

  // 按板块分组（同重点关注排版）
  const groupedSectors = useMemo(() => {
    const map = {};
    for (const sig of displaySignals) {
      const sec = sig.sector || sig.sectorTrend?.sector || '其他';
      if (!map[sec]) map[sec] = [];
      map[sec].push(sig);
    }
    return Object.entries(map).map(([sector, stocks], i) => {
      const changes = stocks.map(s => s.quote?.changePct ?? 0);
      const avgChg = changes.reduce((a, b) => a + b, 0) / Math.max(stocks.length, 1);
      const upCount = changes.filter(v => v > 0).length;
      const downCount = changes.filter(v => v < 0).length;
      const flatCount = stocks.length - upCount - downCount;
      // 龙头股（涨幅最高）和落后股（跌幅最大）
      const topStock = stocks.reduce((best, s) => {
        const v = s.quote?.changePct ?? -9999;
        return v > (best?.quote?.changePct ?? -9999) ? s : best;
      }, stocks[0]);
      const bottomStock = stocks.reduce((worst, s) => {
        const v = s.quote?.changePct ?? 9999;
        return v < (worst?.quote?.changePct ?? 9999) ? s : worst;
      }, stocks[0]);
      // 7阶段分布（按 STAGE_DEFS 推断）
      const stageDist = {};
      STAGE_DEFS.forEach(d => stageDist[d.key] = 0);
      stocks.forEach(s => {
        const chg = s.quote?.changePct ?? 0;
        const stage = STAGE_DEFS.find(d => d.test(chg));
        if (stage) stageDist[stage.key]++;
      });
      // B 信号数 / 主力净流入合计（buyPower.score 累加）
      const bCount = stocks.filter(s => s.bsSignal === 'B').length;
      return {
        sector, stocks, avgChg, upCount, downCount, flatCount, topStock, bottomStock, stageDist, bCount,
        color: SECTOR_COLORS[i % SECTOR_COLORS.length],
      };
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

  // 选中集合的 Set 视图：渲染 80+ 卡片时 O(1) 查询，避免每张卡都跑 includes()
  const selectedIdSet = useMemo(() => new Set(selectedIds), [selectedIds]);

  const platforms = [
    { key: 'ths', name: '同花顺', color: 'var(--accent-blue)', bg: 'rgba(59,130,246,0.1)', st: ths, pull: 'pull_ths', push: 'push_ths' },
    { key: 'mx', name: '妙想', color: 'var(--accent-amber)', bg: 'rgba(234,179,8,0.1)', st: mx, pull: 'pull_mx', push: 'push_mx' },
  ];

  // 策略命中数（避免在 header 中重复计算 Object.values().filter().length）
  const strategyCounts = useMemo(() => {
    const arr = Object.values(strategyPicks);
    return {
      kechuangV7: arr.filter(a => a.includes('BS-科创-V7')).length,
      chuoyeV9: arr.filter(a => a.includes('BS-创业-V9')).length,
    };
  }, [strategyPicks]);

  // 状态卡：板块升温 | 可买 | 资金流入（资金流入用个股自身涨幅，不再重复板块flow）
  const statCards = [
    { key: 'heat', label: '板块升温', sub: '热度↑', count: signals?.summary?.sector_heating ?? 0, color: '#ef4444', top: signals?.summary?.sector_heating_top, valKey: 'heat', valFmt: v => `热度${v}` },
    { key: 'buy', label: '可买', sub: 'B信号', count: signals?.summary?.buy ?? 0, color: BUY_COLOR, top: signals?.summary?.buy_top, valKey: null, valFmt: () => null },
    { key: 'flow', label: '资金流入', sub: '净流入', count: signals?.summary?.inflow ?? 0, color: '#ef4444', top: signals?.summary?.inflow_top, valKey: 'chg', valFmt: v => `${v >= 0 ? '+' : ''}${v}%` },
  ];

  // 7阶段趋势阶段状态栏（基于当日涨跌幅推断阶段）
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

      {/* ===== 悬浮置顶栏：紧凑单行，标题、搜索、筛选、操作全部排满 ===== */}
      <div className="sticky top-0 z-30 rounded-xl p-2 space-y-1.5"
        style={{
          background: 'var(--bg-card)',
          borderBottom: '2px solid var(--border-color)',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }}>

        <div className="flex items-center justify-between gap-2 flex-wrap">
          {/* 左侧：标题 + 数量 + 策略命中 */}
          <div className="flex items-center gap-2 flex-wrap">
            <h2 className="text-base font-bold flex items-center gap-1.5" style={{ color: 'var(--text-primary)' }}>
              <span>自选与重点关注 <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--accent-green)' }}>{totalCount}只</span></span>
            </h2>
            {/* 保留策略命中数（科创V7 + 创业V9） */}
            {Object.keys(strategyPicks).length > 0 && (
              <span className="text-xs flex items-center gap-1" style={{ color: 'var(--text-muted)' }}>
                <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.15)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}>
                  科创V7 {strategyCounts.kechuangV7}
                </span>
                <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(249,115,22,0.15)', color: '#f97316', border: '1px solid rgba(249,115,22,0.3)' }}>
                  创业V9 {strategyCounts.chuoyeV9}
                </span>
                {picksDate && <span className="text-[10px]">({picksDate})</span>}
              </span>
            )}
          </div>

          <div className="flex items-center gap-1 rounded-lg p-0.5" style={{ background: 'var(--bg-surface)' }}>
            {[
              ['all', '全部', sourceCounts.all],
              ['watchlist', '自选', sourceCounts.watchlist],
              ['focus', '重点关注', sourceCounts.focus],
              ['both', '交集', sourceCounts.both],
            ].map(([key, label, count]) => (
              <button
                key={key}
                onClick={() => { setPoolView(key); setSelectedIds([]); }}
                className="px-2 py-1 rounded-md text-[11px] whitespace-nowrap"
                style={{
                  background: poolView === key ? 'var(--bg-card)' : 'transparent',
                  color: poolView === key ? 'var(--text-primary)' : 'var(--text-muted)',
                  boxShadow: poolView === key ? '0 1px 3px rgba(0,0,0,0.12)' : 'none',
                }}
              >
                {label} {count}
              </button>
            ))}
          </div>

          {/* 右侧：搜索 + 筛选 + 操作按钮，填满不留大片空白 */}
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* 手动买入入口（紧凑） */}
            <ManualTradeBar compact showLabel={false} />

            {/* 筛选器 */}
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

            {/* 分隔线 */}
            <span className="w-px h-3 bg-gray-300 dark:bg-gray-600 mx-1" />

            {/* 实时连接状态 */}
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{
                background: streamStatus === 'open' ? 'var(--accent-green)' : streamStatus === 'fallback' ? '#facc15' : 'var(--text-muted)',
                boxShadow: streamStatus === 'open' ? '0 0 4px #22c55e' : 'none',
              }}
              title={streamStatus === 'open' ? '实时推送已连接' : streamStatus === 'fallback' ? '推送中断,使用轮询' : '连接中'}
            />

            {/* 云端同步下拉按钮 */}
            <div className="relative" ref={syncRef}>
              <button onClick={() => setSyncOpen(o => !o)}
                className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1"
                style={{ borderColor: 'rgba(168,85,247,0.4)', color: '#a855f7', background: syncOpen ? 'rgba(168,85,247,0.1)' : 'transparent' }}>
                🔗 同步 {syncOpen ? '▴' : '▾'}
              </button>
              {syncOpen && (
                <div className="absolute right-0 top-full mt-1 w-80 rounded-xl border p-2.5 z-40 shadow-xl"
                  style={{ borderColor: 'rgba(168,85,247,0.3)', background: 'var(--bg-card)' }}>
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-xs font-bold" style={{ color: '#a855f7' }}>🔗 云端同步</span>
                    <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>本地 {local.count ?? 0} 只 · 增删自动同步</span>
                  </div>
                  <div className="flex items-center gap-1 mb-2">
                    <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>模式</span>
                    <div className="flex rounded-lg overflow-hidden border text-[10px]" style={{ borderColor: 'rgba(168,85,247,0.3)' }}>
                      <button onClick={() => setSyncMode('incremental')}
                        className="px-2 py-0.5"
                        style={{ background: syncMode === 'incremental' ? '#a855f7' : 'transparent', color: syncMode === 'incremental' ? '#fff' : 'var(--text-muted)' }}>
                        增量(只加)
                      </button>
                      <button onClick={() => setSyncMode('mirror')}
                        className="px-2 py-0.5"
                        style={{ background: syncMode === 'mirror' ? '#a855f7' : 'transparent', color: syncMode === 'mirror' ? '#fff' : 'var(--text-muted)' }}>
                        镜像(覆盖)
                      </button>
                    </div>
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

            {collect.running && (
              <span className="text-[10px] px-1.5 py-0.5 rounded flex items-center gap-1" style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent-blue)' }}>
                <span className="inline-block w-2 h-2 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
                {collect.total > 0
                  ? `${collect.done}/${collect.total}`
                  : '采集中…'}
              </span>
            )}
            {!collect.running && collect.finished_at && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: 'var(--accent-green)' }} title="✅ 采集完成">✅</span>
            )}
            <button
              onClick={triggerCollect}
              disabled={collect.running}
              className="px-2 py-1 rounded-lg border text-[11px] flex items-center gap-1 disabled:opacity-50"
              style={{ borderColor: 'rgba(59,130,246,0.4)', color: 'var(--accent-blue)', background: collect.running ? 'rgba(59,130,246,0.06)' : 'transparent' }}
              title="立即触发一次全量自选股实时资金流采集（约 60-90 秒）"
            >
              ⚡ 采集
            </button>
            <button onClick={() => { loadWatchlist(); loadFocusStocks(); loadData(); }} className="px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>

            {/* 计数 */}
            <span className="text-[10px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
              {displaySignals.length}/{totalCount}只
            </span>
          </div>{/* /右侧 */}
        </div>{/* /主工具行 */}
      </div>{/* /sticky 悬浮置顶栏 */}

      {/* 池子状态模块（概览） — 紧凑单行布局，横向铺满不留空白 */}
      <div className="rounded-xl border p-2 space-y-1.5" style={{ borderColor: 'rgba(99,102,241,0.3)', background: 'var(--bg-card)' }}>
        {/* 标题 + 7阶段趋势条 同一行，flex-wrap 自适应 */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-[11px] font-bold flex items-center gap-1.5 flex-shrink-0" style={{ color: 'var(--text-secondary)' }}>
            📊 池子状态
          </span>
          <div className="flex items-center gap-1 flex-wrap">
            {STAGE_DEFS.map(stage => {
              const count = stageStats[stage.key] || 0;
              const pct = totalCount > 0 ? Math.round(count / totalCount * 100) : 0;
              const active = filters.stage === stage.key;
              return (
                <button
                  key={stage.key}
                  onClick={() => setFilters(f => ({ ...f, stage: f.stage === stage.key ? null : stage.key }))}
                  className="flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] flex-shrink-0 transition-all"
                  style={{
                    background: active ? `${stage.color}40` : `${stage.color}15`,
                    border: active ? `1px solid ${stage.color}` : `1px solid ${stage.color}30`,
                    color: stage.color,
                    boxShadow: active ? `0 0 0 2px ${stage.color}25` : 'none',
                  }}
                  title={`${stage.key}阶段：涨跌幅区间（点击筛选）`}
                >
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: stage.color }} />
                  <span className="font-bold">{stage.key}</span>
                  <span style={{ color: 'var(--text-muted)' }}>{count}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{pct}%</span>
                </button>
              );
            })}
          </div>
        </div>
        {/* 3 张状态卡：横向三列网格（窄屏自动竖排），铺满宽度 */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-1.5">
          {statCards.map(card => {
            const pct = totalCount > 0 ? Math.round(card.count / totalCount * 100) : 0;
            return (
              <div key={card.key} className="rounded-lg border p-1.5 flex flex-col" style={{ borderColor: `${card.color}25`, background: `${card.color}08` }}>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-lg font-bold leading-none" style={{ color: card.color }}>{card.count}</span>
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>·{pct}%</span>
                  <span className="text-[11px] font-medium" style={{ color: 'var(--text-primary)' }}>{card.label}</span>
                  <span className="text-[9px] ml-auto" style={{ color: 'var(--text-muted)' }}>{card.sub}</span>
                </div>
                <div className="flex flex-wrap gap-1 content-start">
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
                    <>
                    {/* 板块汇总统计条：分隔头部与子组件（个股卡片），展示板块整体画像 */}
                    <div className="flex items-center gap-3 px-3 py-1 flex-wrap text-[10px]"
                      style={{ background: 'var(--bg-surface)', borderBottom: '1px solid var(--border-color)' }}>
                      {/* 板块色标识 + 名称 */}
                      <span className="flex items-center gap-1.5 flex-shrink-0">
                        <span className="inline-block w-1 h-3 rounded-full" style={{ background: sec.color }} />
                        <span className="font-bold" style={{ color: sec.color }}>{sec.sector}</span>
                        <span style={{ color: 'var(--text-muted)' }}>{sec.stocks.length}只</span>
                      </span>
                      {/* 上涨/平/下跌分布 */}
                      <span className="flex items-center gap-1.5 flex-shrink-0">
                        <span style={{ color: '#ef4444' }}>↑{sec.upCount}</span>
                        {sec.flatCount > 0 && <span style={{ color: 'var(--text-muted)' }}>平{sec.flatCount}</span>}
                        <span style={{ color: 'var(--accent-green)' }}>↓{sec.downCount}</span>
                      </span>
                      {/* 平均涨跌幅 */}
                      <span className="flex-shrink-0" style={{ color: sec.avgChg >= 0 ? '#ef4444' : 'var(--accent-green)', fontWeight: 600 }}>
                        均{fmtChg(sec.avgChg)}
                      </span>
                      {/* B 信号数 */}
                      {sec.bCount > 0 && (
                        <span className="flex-shrink-0 px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: 'var(--accent-green)' }}>
                          B{sec.bCount}
                        </span>
                      )}
                      {/* 7阶段分布（仅显示有命中的阶段，紧凑） */}
                      <span className="flex items-center gap-1 flex-wrap">
                        {STAGE_DEFS.map(st => {
                          const n = sec.stageDist[st.key] || 0;
                          if (n === 0) return null;
                          return (
                            <span key={st.key} className="flex items-center gap-0.5 px-1 rounded"
                              style={{ background: `${st.color}15`, color: st.color }}>
                              {st.key}{n}
                            </span>
                          );
                        })}
                      </span>
                      {/* 龙头 / 落后股 */}
                      {sec.topStock && (sec.topStock.quote?.changePct != null) && (
                        <span className="flex items-center gap-1 ml-auto flex-shrink-0">
                          <span style={{ color: 'var(--text-muted)' }}>领涨</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedCode(sec.topStock.secCode); }}
                            className="font-bold hover:underline" style={{ color: 'var(--text-primary)' }}>
                            {sec.topStock.secName}
                          </button>
                          <span style={{ color: sec.topStock.quote.changePct >= 0 ? '#ef4444' : 'var(--accent-green)' }}>
                            {fmtChg(sec.topStock.quote.changePct)}
                          </span>
                        </span>
                      )}
                      {sec.bottomStock && sec.bottomStock !== sec.topStock && (sec.bottomStock.quote?.changePct != null) && (
                        <span className="flex items-center gap-1 flex-shrink-0">
                          <span style={{ color: 'var(--text-muted)' }}>领跌</span>
                          <button
                            onClick={(e) => { e.stopPropagation(); setSelectedCode(sec.bottomStock.secCode); }}
                            className="font-bold hover:underline" style={{ color: 'var(--text-primary)' }}>
                            {sec.bottomStock.secName}
                          </button>
                          <span style={{ color: sec.bottomStock.quote.changePct >= 0 ? '#ef4444' : 'var(--accent-green)' }}>
                            {fmtChg(sec.bottomStock.quote.changePct)}
                          </span>
                        </span>
                      )}
                    </div>
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 px-3 py-2">
                      {sec.stocks.map(sig => (
                        <WatchlistItem
                          key={sig.secCode}
                          signal={sig}
                          isSelected={selectedCode === sig.secCode}
                          realtimeFlow={realtimeMap[sig.secCode] || null}
                          onSelect={setSelectedCode}
                          onRemove={sig.poolSources?.includes('自选') ? handleRemove : undefined}
                          onSell={setSellModal}
                          onRefresh={loadWatchlist}
                          batchMode={batchMode}
                          checked={selectedIdSet.has(sig.secCode)}
                          onToggleCheck={onToggleCheck}
                          strategyTags={strategyPicks[sig.secCode] || EMPTY_ARR}
                          onAnalyze={openAnalysis}
                        />
                      ))}
                    </div>
                    </>
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

      {/* 全市场资金流排行（已抽取为独立组件，自管理 open/tab/数据状态） */}
      <MarketRankTable defaultOpen={false} />

      {sellModal && <TradeModal stockCode={sellModal.stockCode} stockName={sellModal.stockName} type="sell" positionCount={sellModal.positionCount || 0} onClose={() => setSellModal(null)} onConfirm={executeTrade} />}
    </div>
  );
}
