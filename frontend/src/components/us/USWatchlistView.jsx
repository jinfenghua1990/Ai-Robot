import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import StockListContainer from '../StockListContainer';
import StockActionButtons from '../trading/StockActionButtons';
import SinaLink from '../SinaLink';
import USStockDetailDrawer from './USStockDetailDrawer';
import { useUSRealtimeStream } from '../../hooks/useUSRealtimeStream';
import { apiFetch, formatApiError } from '../../utils/request';
import { usNameCN } from '../../utils/usStockNames';
import { usSectorCN } from '../../utils/usStockSectors';

const C = {
  primary: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)',
  border: 'var(--border-color)', borderLight: 'var(--border-light)', blue: 'var(--accent-blue)',
  up: 'var(--flow-up)', down: 'var(--flow-down)',
};

const PAGE_SIZE = 30;
const SECTOR_HOT_KEY = 'us-sector-rotation-hot-sectors';
const SORTS = [
  ['sector_rise', '板块上升度'], ['score', '综合评分'], ['change_pct', '涨跌幅'],
  ['from_high', '距52周高'], ['chg_5d', '5日涨跌'], ['chg_20d', '20日涨跌'], ['rsi', 'RSI'],
];
const WATCH_FILTERS = [
  { key: 'all', label: '全部', test: () => true },
  { key: 'ready', label: '可行动', test: (item) => item.opportunity?.status === 'READY' },
  { key: 'stock_wait', label: '等待个股', test: (item) => item.opportunity?.status === 'STOCK_WAIT' },
  { key: 'closed', label: '板块未通过', test: (item) => ['SECTOR_CLOSED', 'SECTOR_UNQUALIFIED'].includes(item.opportunity?.status) },
  { key: 'data', label: '机会数据问题', test: (item) => ['DATA_STALE', 'DATA_INSUFFICIENT'].includes(item.opportunity?.status) },
  { key: 'risk', label: '持仓风险', test: (item) => ['RISK', 'AVOID'].includes(item.opportunity?.status) },
  { key: 'reference', label: 'ETF参考', test: (item) => item.opportunity?.status === 'REFERENCE' },
];
const MARKET_FILTERS = [
  { key: 'all', label: '全部候选', test: () => true },
  { key: 'core', label: '核心候选', test: (item) => item.core_gate?.valid === true },
  { key: 'strong', label: '强势候选', test: (item) => item.core_gate?.valid !== true },
];

const finite = (value) => value == null || Number.isNaN(Number(value)) ? null : Number(value);
const rounded = (value, digits = 2) => finite(value) == null ? null : Number(finite(value).toFixed(digits));
const num = (value, digits = 2) => finite(value) == null ? '—' : finite(value).toFixed(digits);
const pct = (value, digits = 1) => finite(value) == null ? '—' : `${finite(value) >= 0 ? '+' : ''}${finite(value).toFixed(digits)}%`;
const tone = (value) => finite(value) == null ? C.muted : finite(value) >= 0 ? C.up : C.down;
const money = (value) => {
  const amount = finite(value);
  if (amount == null) return '—';
  if (Math.abs(amount) >= 1e8) return `${(amount / 1e8).toFixed(2)}亿`;
  if (Math.abs(amount) >= 1e4) return `${(amount / 1e4).toFixed(1)}万`;
  return amount.toFixed(0);
};

const STATUS_META = {
  OPEN: ['机会门打开', '#ef4444'], CLOSED: ['未通过', '#f59e0b'],
  ETF_MISSING: ['ETF数据缺失', '#94a3b8'], DATA_INSUFFICIENT: ['数据不足', '#94a3b8'],
  SAMPLE_TOO_SMALL: ['样本不足', '#94a3b8'],
};
// 可排序列：列头标签 → 排序键。排序值与该表单元格展示值同源（缺失数据排最后）。
const SORTABLE = {
  '持仓盈亏 / 持仓收益率': 'profit',
  '评分': 'score',
};
const sortValueOf = (item, key) => {
  const pos = item.position || {};
  switch (key) {
    case 'score': return finite(item.candidate_score ?? item.indicators?.score);
    case 'profit': return finite(pos.hold_profit);
    default: return null;
  }
};
// dir: 1=升序(小→大)，-1=降序(大→小)；缺失值固定排最后。
const sortItems = (list, key, dir) => {
  if (!key || !list?.length) return list;
  return [...list].sort((a, b) => {
    const va = sortValueOf(a, key);
    const vb = sortValueOf(b, key);
    const na = va == null;
    const nb = vb == null;
    if (na && nb) return 0;
    if (na) return 1;
    if (nb) return -1;
    return (va - vb) * dir;
  });
};
const OPPORTUNITY_COLORS = {
  READY: '#ef4444', RISK: '#22c55e', AVOID: '#f97316', STOCK_WAIT: '#f59e0b',
  SECTOR_CLOSED: '#94a3b8', DATA_STALE: '#94a3b8', DATA_INSUFFICIENT: '#94a3b8',
  SECTOR_UNQUALIFIED: '#94a3b8', REFERENCE: '#3b82f6', MARKET_CORE: '#ef4444', MARKET_CANDIDATE: '#f59e0b',
};
const ACTION_ICONS = {
  buy: '▲ 买入', hold: '▶ 持有', scoop: '△ 低吸', watch: '· 观望',
  reduce: '▼ 减仓', sell: '✕ 卖出', stop: '⛔ 止损', avoid: '⚠ 回避', blocked: '· 阻断',
};

function ACTION_COLOR_WL(action_color, action) {
  if (action_color) return action_color;
  const s = String(action || '');
  if (/卖出|减仓|退出|止损|止盈|清仓|回避/.test(s)) return '#ef4444';
  if (/买入|加仓|开仓|低吸/.test(s)) return '#3b82f6';
  if (/观察|持有|继续|观望/.test(s)) return '#f59e0b';
  return 'var(--text-muted)';
}

function actionText(action) {
  const fallback = ACTION_ICONS[action?.action] || '';
  const icon = fallback.split(' ')[0];
  return `${icon} ${action?.action_label || fallback.slice(icon.length).trim()}`.trim() || '—';
}

function groupBySector(items) {
  const groups = new Map();
  for (const item of items) {
    const sector = item.sector || usSectorCN(item.symbol) || '其他';
    if (!groups.has(sector)) groups.set(sector, []);
    groups.get(sector).push(item);
  }
  return groups;
}

function gateReasonText(reasons = []) {
  const labels = {
    sample_too_small: '行业样本不足', data_coverage_low: '行情覆盖不足', rise_score_below_60: '上升度低于60',
    median_return_not_positive: '20日中位收益未转正', breadth_below_50: '上涨广度低于50%',
    ma20_breadth_below_50: '站上MA20不足50%', etf_data_missing: 'ETF同日数据缺失', etf_weak_veto: 'ETF弱势否决',
  };
  return reasons.map((reason) => labels[reason] || reason).join(' · ');
}

function macdText(indicators) {
  const macd = indicators?.macd || {};
  if (macd.status) return macd.status;
  if (finite(macd.dif) == null || finite(macd.dea) == null) return '—';
  return macd.dif >= macd.dea ? (macd.dif >= 0 ? '零轴上金叉' : '零轴下金叉') : '死叉';
}

function kdjText(indicators) {
  const kdj = indicators?.kdj || {};
  if (kdj.status) return kdj.status;
  if (finite(kdj.j) == null) return '—';
  return kdj.k >= kdj.d ? '金叉偏强' : '死叉偏弱';
}

function riskHints(item) {
  const ind = item.indicators || {};
  if (ind.data_status !== 'CURRENT') return [ind.data_reason || '技术数据不可用'];
  return [
    ind.rsi >= 75 && 'RSI超买', ind.rsi <= 30 && 'RSI超卖',
    ind.ma_struct === '空头排列' && '均线空头', macdText(ind).includes('死叉') && 'MACD死叉',
    ind.kdj?.j >= 100 && 'KDJ超买', ind.above_ma20 === false && '低于MA20',
  ].filter(Boolean);
}

function qualificationText(evidence) {
  if (!evidence) return '无有效强势证据';
  return `近1年 ${evidence.event_count} 次 · 最近 ${evidence.latest_trigger_date || '—'} · 单日最高 ${pct(evidence.max_single_day_pct)} · 两日最高 ${pct(evidence.max_two_day_pct)}`;
}

function candidateToDetail(stock, decisionDate, sectorContext = null) {
  const metrics = stock.metrics || {};
  const macdStatus = metrics.dif == null || metrics.dea == null ? '—' : metrics.dif >= metrics.dea ? '多头' : '空头';
  const kdjStatus = metrics.kdj_k == null || metrics.kdj_d == null ? '—' : metrics.kdj_k >= metrics.kdj_d ? '金叉偏强' : '死叉偏弱';
  const price = finite(metrics.last_price);
  const stopLoss = finite(metrics.support);
  return {
    symbol: stock.symbol,
    name: stock.name || stock.symbol,
    sector: stock.sector,
    market_candidate: true,
    is_watched: false,
    candidate_rank: stock.rank,
    candidate_score: rounded(stock.score, 1),
    qualification: stock.qualification || null,
    core_gate: stock.core_gate || null,
    sector_rotation: sectorContext || stock.sector_context || null,
    price,
    change_pct: metrics.day_change_pct,
    bar_as_of: decisionDate,
    price_source: 'decision_close',
    position: stock.position || null,
    opportunity: {
      status: stock.core_gate?.valid ? 'MARKET_CORE' : 'MARKET_CANDIDATE',
      label: stock.core_gate?.valid ? '核心候选' : '强势候选',
      sector_gate: (sectorContext || stock.sector_context)?.status === 'OPEN',
    },
    trade_action: {
      action: 'watch', action_label: stock.action || '研究候选', action_color: '#f59e0b',
      action_strength: rounded(stock.score, 1), action_reasons: [qualificationText(stock.qualification)],
    },
    indicators: {
      as_of: decisionDate, decision_date: decisionDate, data_status: 'CURRENT', score: rounded(stock.score, 1),
      rsi: rounded(metrics.rsi, 1), ema10: rounded(metrics.ema10), ema20: rounded(metrics.ema20),
      ma5: rounded(metrics.ma5), ma20: rounded(metrics.ma20), ma50: rounded(metrics.ma50), ma60: rounded(metrics.ma60),
      ma200: rounded(metrics.ma200), ma20_slope: rounded(metrics.ma20_slope),
      ma_struct: metrics.ma5 >= metrics.ma20 && metrics.ma20 >= metrics.ma60 ? '多头排列' : metrics.ma5 <= metrics.ma20 && metrics.ma20 <= metrics.ma60 ? '空头排列' : '均线交错',
      state_label: stock.core_gate?.valid ? '核心候选' : '强势证据候选',
      above_ma20: metrics.above_ma20,
      macd: { dif: rounded(metrics.dif, 4), dea: rounded(metrics.dea, 4), macd: rounded(metrics.macd, 4), status: macdStatus },
      kdj: { k: rounded(metrics.kdj_k, 2), d: rounded(metrics.kdj_d, 2), j: rounded(metrics.kdj_j, 2), status: kdjStatus },
      rel_vol: rounded(metrics.volume_ratio), turnover: rounded(metrics.turnover),
      chg_5d: rounded(metrics.ret_5d), chg_20d: rounded(metrics.ret_20d), chg_60d: rounded(metrics.ret_60d),
      support: rounded(metrics.support), resistance: rounded(metrics.resistance), atr: rounded(metrics.atr),
      amplitude: rounded(metrics.amplitude),
      pct_from_high: rounded(metrics.pct_from_high ?? metrics.drawdown), pct_from_low: rounded(metrics.pct_from_low),
      high_52w: rounded(metrics.high_52w), low_52w: rounded(metrics.low_52w), stop_loss: rounded(stopLoss),
      stop_dist: price && stopLoss ? rounded((price - stopLoss) / price * 100) : null,
    },
  };
}

function mergeMarketCandidate(stock, decisionDate, sectorContext, watchedItem) {
  const candidate = candidateToDetail(stock, decisionDate, sectorContext);
  if (!watchedItem) return candidate;
  return {
    ...candidate,
    ...watchedItem,
    name: watchedItem.name || candidate.name,
    sector: watchedItem.sector || candidate.sector,
    market_candidate: true,
    is_watched: true,
    candidate_rank: candidate.candidate_rank,
    candidate_score: candidate.candidate_score,
    qualification: candidate.qualification,
    core_gate: candidate.core_gate,
    sector_rotation: sectorContext || candidate.sector_rotation || watchedItem.sector_rotation,
    indicators: { ...candidate.indicators, ...(watchedItem.indicators || {}) },
  };
}

function PageControls({ page, pageCount, total, onChange }) {
  if (pageCount <= 1) return null;
  return (
    <div className="flex items-center justify-end gap-2 py-1 text-[11px]" style={{ color: C.muted }}>
      <span>共 {total} 只 · 每页 {PAGE_SIZE} 只</span>
      <button disabled={page <= 1} onClick={() => onChange(page - 1)} className="rounded border px-2 py-0.5 disabled:opacity-40" style={{ borderColor: C.border }}>上一页</button>
      <span>{page} / {pageCount}</span>
      <button disabled={page >= pageCount} onClick={() => onChange(page + 1)} className="rounded border px-2 py-0.5 disabled:opacity-40" style={{ borderColor: C.border }}>下一页</button>
    </div>
  );
}

export default function USWatchlistView({ market = 'US', refreshKey = 0, onChanged, showSectorRotation = false }) {
  const [items, setItems] = useState([]);
  const [marketCandidates, setMarketCandidates] = useState([]);
  const [sectorContexts, setSectorContexts] = useState([]);
  const [decisionDate, setDecisionDate] = useState(null);
  const [dataQuality, setDataQuality] = useState({});
  const [sectorFormula, setSectorFormula] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [marketError, setMarketError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [scope, setScope] = useState(showSectorRotation && market === 'US' ? 'market' : 'watched');
  const [activeSector, setActiveSector] = useState('全部');
  const [sectorPickerOpen, setSectorPickerOpen] = useState(false);
  const [sectorQuery, setSectorQuery] = useState('');
  const [hotSectors, setHotSectors] = useState([]);
  const hotSectorsRef = useRef([]);
  const hotMutationRef = useRef(0);
  const [sortKey, setSortKey] = useState(showSectorRotation ? 'sector_rise' : 'score');
  const [sortDir, setSortDir] = useState('desc');
  const [dirFilter, setDirFilter] = useState('all');
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [selectedStock, setSelectedStock] = useState(null);
  const [page, setPage] = useState(1);
  const [addOpen, setAddOpen] = useState(false);
  const [addSymbol, setAddSymbol] = useState('');
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState(null);
  const [candidateCache, setCandidateCache] = useState({});
  const [candidateLoading, setCandidateLoading] = useState(false);
  const [candidateAdding, setCandidateAdding] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setMarketError(null);
    try {
      const [response, opportunityResponse] = await Promise.all([
        apiFetch(`/api/us-quant/watchlist/detail?market=${market}`, {}, 20000, 0),
        showSectorRotation && market === 'US'
          ? apiFetch('/api/us-sector-rotation/opportunities', {}, 20000, 0)
          : Promise.resolve({ ok: true, data: { candidates: [] } }),
      ]);
      if (!response.ok || !response.data) throw new Error(formatApiError(response.error, '加载失败'));
      const payload = response.data;
      setItems((payload.members || []).map((item) => ({
        ...item,
        name: usNameCN(item.symbol) || item.name || item.symbol,
        sector: item.sector || usSectorCN(item.symbol) || '其他',
      })));
      setSectorContexts(payload.sector_contexts || []);
      setDecisionDate(payload.decision_date || payload.sector_context_date || null);
      setDataQuality(payload.data_quality || {});
      setSectorFormula(payload.sector_rise_formula || '');
      if (opportunityResponse.ok && opportunityResponse.data) {
        setMarketCandidates(opportunityResponse.data.candidates || []);
      } else {
        setMarketCandidates([]);
        setMarketError(formatApiError(opportunityResponse.error, '全市场机会加载失败'));
      }
      setCandidateCache({});
      setLastUpdated(new Date());
    } catch (reason) {
      setError(reason.message || '网络错误');
    } finally {
      setLoading(false);
    }
  }, [market, showSectorRotation]);

  useEffect(() => { load(); }, [load, refreshKey]);

  useEffect(() => {
    hotSectorsRef.current = hotSectors;
  }, [hotSectors]);

  useEffect(() => {
    if (!showSectorRotation || market !== 'US') return;
    let alive = true;
    const requestVersion = hotMutationRef.current;
    const migrate = async () => {
      let local;
      try { local = JSON.parse(localStorage.getItem(SECTOR_HOT_KEY) || '[]'); } catch { local = []; }
      const response = await apiFetch(`/api/us-quant/watchlist/sector-preferences?market=${market}`, {}, 10000, 0);
      if (!alive || !response.ok || requestVersion !== hotMutationRef.current) return;
      if ((response.data?.preference_count || 0) === 0 && local.length) {
        const saved = await apiFetch('/api/us-quant/watchlist/sector-preferences', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market, sectors: local }),
        }, 10000, 0);
        if (!alive || !saved.ok || requestVersion !== hotMutationRef.current) return;
        const next = Array.isArray(saved.data?.hot_sectors) ? saved.data.hot_sectors : local;
        hotSectorsRef.current = next;
        setHotSectors(next);
        localStorage.setItem(SECTOR_HOT_KEY, JSON.stringify(next));
      } else {
        const next = Array.isArray(response.data?.hot_sectors) ? response.data.hot_sectors : [];
        hotSectorsRef.current = next;
        setHotSectors(next);
        localStorage.setItem(SECTOR_HOT_KEY, JSON.stringify(next));
      }
    };
    migrate();
    return () => { alive = false; };
  }, [market, showSectorRotation]);

  useEffect(() => {
    if (!showSectorRotation || scope !== 'market' || activeSector === '全部' || candidateCache[activeSector]) return;
    let alive = true;
    setCandidateLoading(true);
    apiFetch(`/api/us-sector-rotation?sector=${encodeURIComponent(activeSector)}`, {}, 20000, 0)
      .then((response) => {
        if (!alive) return;
        setCandidateCache((old) => ({ ...old, [activeSector]: response.ok ? (response.data?.top_candidates || []) : [] }));
      })
      .finally(() => { if (alive) setCandidateLoading(false); });
    return () => { alive = false; };
  }, [activeSector, candidateCache, scope, showSectorRotation]);

  const { realtimeMap, streamStatus } = useUSRealtimeStream(market, autoRefresh && scope === 'watched');
  const mergedItems = useMemo(() => items.map((item) => {
    const realtime = realtimeMap[item.symbol];
    if (!realtime) return item;
    if (realtime.price === item.price && realtime.change_pct === item.change_pct && realtime.quote_time === item.quote_time) return item;
    return { ...item, price: realtime.price, change_pct: realtime.change_pct, quote_time: realtime.quote_time || item.quote_time };
  }), [items, realtimeMap]);
  const watchedItemBySymbol = useMemo(
    () => new Map(mergedItems.map((item) => [item.symbol, item])),
    [mergedItems],
  );
  const watchedSymbols = useMemo(() => new Set(items.map((item) => item.symbol)), [items]);
  const sectorContextByName = useMemo(
    () => new Map(sectorContexts.map((context) => [context.sector, context])),
    [sectorContexts],
  );
  const marketCandidateBySymbol = useMemo(
    () => new Map(marketCandidates.map((stock) => [stock.symbol, stock])),
    [marketCandidates],
  );
  const marketCandidateCountBySector = useMemo(() => {
    const counts = new Map();
    for (const stock of marketCandidates) counts.set(stock.sector, (counts.get(stock.sector) || 0) + 1);
    return counts;
  }, [marketCandidates]);
  const enrichedWatchedItems = useMemo(() => mergedItems.map((item) => {
    const stock = marketCandidateBySymbol.get(item.symbol);
    return stock ? mergeMarketCandidate(stock, decisionDate, stock.sector_context?.sector ? stock.sector_context : sectorContextByName.get(stock.sector), item) : item;
  }), [decisionDate, marketCandidateBySymbol, mergedItems, sectorContextByName]);
  const selectedCandidateRows = useMemo(
    () => activeSector === '全部' ? marketCandidates : candidateCache[activeSector] || [],
    [activeSector, candidateCache, marketCandidates],
  );
  const marketItems = useMemo(() => selectedCandidateRows.map((stock) => mergeMarketCandidate(
    stock,
    decisionDate,
    stock.sector_context?.sector ? stock.sector_context : sectorContextByName.get(stock.sector),
    watchedItemBySymbol.get(stock.symbol),
  )), [decisionDate, sectorContextByName, selectedCandidateRows, watchedItemBySymbol]);
  const scopeItems = scope === 'market' ? marketItems : enrichedWatchedItems;

  const sortedItems = useMemo(() => {
    const direction = sortDir === 'desc' ? -1 : 1;
    const value = (item) => {
      const ind = item.indicators || {};
      if (sortKey === 'sector_rise') return (item.sector_rotation?.status === 'OPEN' ? 1000 : 0) + (item.sector_rotation?.rise_score ?? -1);
      if (sortKey === 'score') return ind.score ?? -1;
      if (sortKey === 'change_pct') return item.change_pct ?? -999;
      if (sortKey === 'from_high') return ind.pct_from_high ?? -999;
      if (sortKey === 'chg_5d') return ind.chg_5d ?? -999;
      if (sortKey === 'chg_20d') return ind.chg_20d ?? -999;
      return ind.rsi ?? -1;
    };
    const opportunityOrder = { READY: 0, MARKET_CORE: 0, STOCK_WAIT: 1, MARKET_CANDIDATE: 1, RISK: 2, AVOID: 2, SECTOR_CLOSED: 3, SECTOR_UNQUALIFIED: 3, DATA_STALE: 4, DATA_INSUFFICIENT: 4, REFERENCE: 5 };
    return [...scopeItems].sort((left, right) => {
      const primary = (value(left) - value(right)) * direction;
      if (primary) return primary;
      const opportunityDiff = (opportunityOrder[left.opportunity?.status] ?? 9) - (opportunityOrder[right.opportunity?.status] ?? 9);
      if (opportunityDiff) return opportunityDiff;
      const candidateRankDiff = (left.candidate_rank || 999) - (right.candidate_rank || 999);
      if (candidateRankDiff) return candidateRankDiff;
      const scoreDiff = (right.candidate_score ?? right.indicators?.score ?? -1) - (left.candidate_score ?? left.indicators?.score ?? -1);
      if (scoreDiff) return scoreDiff;
      const triggerDiff = String(right.qualification?.latest_trigger_date || '').localeCompare(String(left.qualification?.latest_trigger_date || ''));
      return triggerDiff || String(left.symbol).localeCompare(String(right.symbol));
    });
  }, [scopeItems, sortDir, sortKey]);

  const watchedGroups = useMemo(() => groupBySector(enrichedWatchedItems), [enrichedWatchedItems]);
  const sectorSummaries = useMemo(() => {
    if (showSectorRotation && sectorContexts.length) {
      return sectorContexts.map((context) => ({ name: context.sector, context, group: watchedGroups.get(context.sector) || [] }));
    }
    return [...watchedGroups.entries()].map(([name, group]) => ({ name, group, context: group[0]?.sector_rotation || null }));
  }, [sectorContexts, showSectorRotation, watchedGroups]);
  const visibleSectors = useMemo(() => sectorSummaries.filter(
    (row) => row.context?.status === 'OPEN' || hotSectors.includes(row.name) || row.name === activeSector,
  ), [activeSector, hotSectors, sectorSummaries]);
  const searchedSectors = useMemo(() => {
    const query = sectorQuery.trim().toLowerCase();
    return sectorSummaries.filter((row) => !query || row.name.toLowerCase().includes(query) || String(row.context?.etf?.symbol || '').toLowerCase().includes(query));
  }, [sectorQuery, sectorSummaries]);

  const filterOptions = scope === 'market' ? MARKET_FILTERS : WATCH_FILTERS;
  const filteredItems = useMemo(() => {
    const filter = filterOptions.find((item) => item.key === dirFilter) || filterOptions[0];
    return sortedItems.filter((item) => (activeSector === '全部' || item.sector === activeSector) && filter.test(item));
  }, [activeSector, dirFilter, filterOptions, sortedItems]);
  const pageCount = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const pageItems = useMemo(() => filteredItems.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE), [filteredItems, page]);
  useEffect(() => { setPage(1); }, [activeSector, dirFilter, scope, sortDir, sortKey]);
  useEffect(() => { if (page > pageCount) setPage(pageCount); }, [page, pageCount]);

  const toggleHotSector = useCallback(async (sector) => {
    const current = hotSectorsRef.current;
    const wasHot = current.includes(sector);
    const optimistic = wasHot ? current.filter((item) => item !== sector) : [...current, sector];
    const requestVersion = ++hotMutationRef.current;
    hotSectorsRef.current = optimistic;
    setHotSectors(optimistic);
    localStorage.setItem(SECTOR_HOT_KEY, JSON.stringify(optimistic));
    const response = await apiFetch('/api/us-quant/watchlist/sector-preferences', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market, sector, is_hot: !wasHot }),
    }, 10000, 0);
    if (requestVersion !== hotMutationRef.current) return;
    if (!response.ok) {
      hotSectorsRef.current = current;
      setHotSectors(current);
      localStorage.setItem(SECTOR_HOT_KEY, JSON.stringify(current));
      return;
    }
    const persisted = Array.isArray(response.data?.hot_sectors) ? response.data.hot_sectors : optimistic;
    hotSectorsRef.current = persisted;
    setHotSectors(persisted);
    localStorage.setItem(SECTOR_HOT_KEY, JSON.stringify(persisted));
  }, [market]);

  const addWatch = useCallback(async (symbol) => {
    const response = await apiFetch('/api/us-quant/watchlist/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market, symbol }),
    }, 15000, 0);
    if (!response.ok || !response.data?.ok) throw new Error(formatApiError(response.data?.error ?? response.error, '添加失败'));
    await load();
    onChanged?.();
  }, [load, market, onChanged]);

  const handleAdd = useCallback(async () => {
    const symbol = addSymbol.trim();
    if (!symbol) return;
    setAdding(true);
    setAddError(null);
    try {
      await addWatch(symbol);
      setAddSymbol('');
      setAddOpen(false);
    } catch (reason) {
      setAddError(reason.message || '添加失败');
    } finally {
      setAdding(false);
    }
  }, [addSymbol, addWatch]);

  const handleCandidateAdd = useCallback(async (symbol) => {
    setCandidateAdding(symbol);
    setAddError(null);
    try { await addWatch(symbol); } catch (reason) { setAddError(reason.message || '添加失败'); } finally { setCandidateAdding(null); }
  }, [addWatch]);

  const handleRemove = useCallback(async (symbol) => {
    const previous = items;
    setItems((old) => old.filter((item) => item.symbol !== symbol));
    const response = await apiFetch('/api/us-quant/watchlist/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ market, symbol }),
    }, 15000, 0);
    if (!response.ok || !response.data?.ok) setItems(previous);
    else onChanged?.();
  }, [items, market, onChanged]);

  const selectSector = useCallback((sector) => {
    setScope('market');
    setDirFilter('all');
    setActiveSector((current) => current === sector ? '全部' : sector);
    setSectorPickerOpen(false);
  }, []);
  const selectScope = useCallback((nextScope) => {
    setScope(nextScope);
    setDirFilter('all');
    setActiveSector('全部');
    setSectorPickerOpen(false);
  }, []);

  const tableRenderer = useCallback(() => (
    <WatchlistHoldingTable
      items={pageItems} scope={scope}
      watchedSymbols={watchedSymbols} adding={candidateAdding}
      onOpen={setSelectedStock} onRemove={handleRemove} onAdd={handleCandidateAdd}
    />
  ), [candidateAdding, handleCandidateAdd, handleRemove, pageItems, scope, watchedSymbols]);

  const openSectorCount = sectorSummaries.filter((row) => row.context?.status === 'OPEN').length;
  const readyCount = items.filter((item) => item.opportunity?.status === 'READY').length;
  const coreCandidateCount = marketCandidates.filter((item) => item.core_gate?.valid).length;
  const dataIssueCount = (dataQuality.STALE || 0) + (dataQuality.INSUFFICIENT || 0) + (dataQuality.MISSING || 0) + (dataQuality.ERROR || 0);
  const opportunityDataIssueCount = items.filter((item) => ['DATA_STALE', 'DATA_INSUFFICIENT'].includes(item.opportunity?.status)).length;

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-1.5 rounded-lg border px-2 py-1 text-[10px]" style={{ borderColor: C.border, background: 'var(--bg-card)' }}>
        <span style={{ color: C.secondary }}>决策日 <b>{decisionDate || '按各股最新日线'}</b></span>
        <span style={{ color: C.up }}>全市场候选 <b>{marketCandidates.length}</b> · 核心 <b>{coreCandidateCount}</b></span>
        <span style={{ color: C.secondary }}>关注可行动 <b>{readyCount}</b></span>
        <span style={{ color: C.secondary }}>强势板块 <b>{openSectorCount}</b> / {sectorSummaries.length}</span>
        {dataIssueCount > 0 && <span title={`个股指标：过期 ${dataQuality.STALE || 0} · 不足 ${dataQuality.INSUFFICIENT || 0} · 缺失 ${dataQuality.MISSING || 0} · 错误 ${dataQuality.ERROR || 0}`} style={{ color: '#f59e0b' }}>指标待补 {dataIssueCount}</span>}
        {opportunityDataIssueCount > 0 && <button onClick={() => { selectScope('watched'); setDirFilter('data'); }} title="板块ETF或机会判断所需数据不足" style={{ color: '#f59e0b' }}>机会阻断 {opportunityDataIssueCount}</button>}
        <span className="ml-auto" title={scope === 'watched' ? '实时流只更新价格和涨跌幅，不重算日线技术结论' : '全市场候选来自已落库的决策日快照'} style={{ color: scope === 'watched' && streamStatus === 'open' ? '#22c55e' : C.muted }}>{scope === 'watched' ? (streamStatus === 'open' ? '● 实时价' : '○ 静态价') : '● 决策收盘'}{lastUpdated ? ` · ${lastUpdated.toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit' })}` : ''}</span>
      </div>

      {showSectorRotation && (
        <section className="relative space-y-1 rounded-lg border p-1.5" style={{ borderColor: C.border, background: 'var(--bg-card)' }}>
          <div className="flex flex-wrap items-center justify-between gap-1">
            <div><b className="text-xs">行业板块</b>{hotSectors.length > 0 && <span className="ml-2 rounded px-1 py-0.5 text-[9px]" style={{ color: '#f59e0b', background: 'rgba(245,158,11,.10)' }}>已收藏 {hotSectors.length}</span>}<span className="ml-2 text-[9px]" style={{ color: C.muted }}>默认显示强势与手动热门 · 点击查看行业候选</span></div>
            <div className="flex items-center gap-1"><button title={`${sectorFormula}；个股准入：近1年单日涨幅≥9%或连续两日复合涨幅≥16%；核心候选还要求近120日重复事件≥2次且站上MA60`} className="rounded px-1.5 py-0.5 text-[9px]" style={{ color: C.muted }}>规则</button><button onClick={() => setSectorPickerOpen((old) => !old)} className="rounded border px-1.5 py-0.5 text-[9px]" style={{ borderColor: C.border, color: C.secondary }}>查找行业 {sectorSummaries.length}</button></div>
          </div>
          <div className="grid grid-cols-2 gap-1 sm:grid-cols-4 xl:grid-cols-8">
            {visibleSectors.map(({ name, group, context }) => {
              const [statusLabel, statusColor] = STATUS_META[context?.status] || ['暂无板块数据', C.muted];
              const hot = hotSectors.includes(name);
              return <div key={name} className="relative">
                <button onClick={() => selectSector(name)} className="h-full w-full rounded-md p-1 pr-6 text-left" title={`${statusLabel} · ${gateReasonText(context?.gate_reasons)} · ETF相对SPY ${pct(context?.etf?.rel_strength_20d)}`} style={{ border: `1px solid ${activeSector === name ? C.blue : C.borderLight}`, background: activeSector === name ? 'rgba(59,130,246,.12)' : 'var(--bg-surface)' }}>
                  <div className="flex items-center justify-between gap-1"><span className="truncate text-[10px] font-bold">{context?.status === 'OPEN' ? '↑ ' : ''}{hot ? '🔥 ' : ''}{name}</span><span className="font-bold tabular-nums text-[10px]" style={{ color: statusColor }}>{num(context?.rise_score, 1)}</span></div>
                  <div className="truncate text-[8px]" style={{ color: statusColor }}>#{context?.rank || '—'} · 20日 {pct(context?.ret_20d)} · 广度 {pct(context?.breadth)}</div>
                  <div className="text-[8px]" style={{ color: C.muted }}>{context?.etf?.symbol || 'ETF—'} {context?.status === 'OPEN' ? '✓' : '—'} · {scope === 'market' ? `候选 ${name === activeSector && candidateCache[name] ? candidateCache[name].length : (marketCandidateCountBySector.get(name) || 0)}/10` : `关注 ${group.length}`}</div>
                </button>
                <button
                  type="button"
                  aria-label={hot ? `取消${name}热门` : `标记${name}热门`}
                  aria-pressed={hot}
                  onClick={(event) => { event.stopPropagation(); toggleHotSector(name); }}
                  title={hot ? '取消热门' : '标记热门'}
                  className="absolute right-0 top-0 z-10 h-5 w-5 rounded text-[11px]"
                  style={{ color: hot ? '#f59e0b' : C.muted }}
                >{hot ? '★' : '☆'}</button>
              </div>;
            })}
          </div>
          {visibleSectors.length === 0 && <div className="rounded border border-dashed py-2 text-center text-[10px]" style={{ borderColor: C.border, color: C.muted }}>当前没有强势或手动热门板块；可从“查找行业”中标记。</div>}
          {sectorPickerOpen && <div className="absolute right-2 top-7 z-30 w-[720px] max-w-[calc(100vw-240px)] rounded-lg border p-1.5 shadow-2xl" style={{ borderColor: C.border, background: 'var(--bg-card)' }}>
            <div className="mb-1.5 flex items-center gap-1.5"><input autoFocus value={sectorQuery} onChange={(event) => setSectorQuery(event.target.value)} placeholder="搜索行业或ETF" className="flex-1 rounded border px-2 py-1 text-[10px] outline-none" style={{ borderColor: C.border, background: 'var(--bg-surface)', color: C.primary }} /><span className="text-[9px]" style={{ color: C.muted }}>{searchedSectors.length}/{sectorSummaries.length}</span><button onClick={() => setSectorPickerOpen(false)} className="rounded px-1.5 py-0.5 text-[10px]" style={{ color: C.muted }}>关闭</button></div>
            <div className="grid max-h-[280px] grid-cols-2 gap-1 overflow-y-auto sm:grid-cols-3 xl:grid-cols-4">{searchedSectors.map(({ name, context }) => {
              const hot = hotSectors.includes(name);
              const statusColor = STATUS_META[context?.status]?.[1] || C.muted;
              return <div key={name} className="relative rounded border" style={{ borderColor: C.borderLight, background: 'var(--bg-surface)' }}><button onClick={() => selectSector(name)} className="w-full px-2 py-1 pr-7 text-left"><div className="truncate text-[10px] font-bold">{context?.status === 'OPEN' ? '↑ ' : ''}{name}</div><div className="text-[8px]" style={{ color: statusColor }}>#{context?.rank || '—'} · {num(context?.rise_score, 1)} · {context?.etf?.symbol || 'ETF—'}</div></button><button onClick={() => toggleHotSector(name)} aria-label={hot ? `取消${name}热门` : `标记${name}热门`} aria-pressed={hot} className="absolute right-1 top-1 text-[11px]" style={{ color: hot ? '#f59e0b' : C.muted }}>{hot ? '★' : '☆'}</button></div>;
            })}</div>
          </div>}
        </section>
      )}

      <div className="flex flex-wrap items-center gap-1 rounded-lg border px-1 py-0.5" style={{ borderColor: C.borderLight, background: 'var(--bg-card)' }}>
        {showSectorRotation && <><button onClick={() => selectScope('market')} className="rounded px-1.5 py-0.5 text-[10px] font-bold" style={{ border: `1px solid ${scope === 'market' ? C.blue : 'transparent'}`, background: scope === 'market' ? 'rgba(59,130,246,.10)' : 'transparent', color: scope === 'market' ? C.blue : C.muted }}>全市场机会 {marketCandidates.length}</button><button onClick={() => selectScope('watched')} className="rounded px-1.5 py-0.5 text-[10px] font-bold" style={{ border: `1px solid ${scope === 'watched' ? C.blue : 'transparent'}`, background: scope === 'watched' ? 'rgba(59,130,246,.10)' : 'transparent', color: scope === 'watched' ? C.blue : C.muted }}>我的关注 {items.length}</button><span className="mx-0.5 h-3 border-l" style={{ borderColor: C.border }} /></>}
        {activeSector !== '全部' && <button onClick={() => setActiveSector('全部')} className="rounded border px-1.5 py-0.5 text-[10px]" style={{ borderColor: C.border, color: C.blue }}>{activeSector} ×</button>}
        {filterOptions.map((filter) => {
          const active = dirFilter === filter.key;
          const count = filter.key === 'all' ? sortedItems.length : sortedItems.filter(filter.test).length;
          if (filter.key === 'all' && dirFilter === 'all') return null;
          if (count === 0 && !active && filter.key !== 'all') return null;
          return <button key={filter.key} onClick={() => setDirFilter(active ? 'all' : filter.key)} className="rounded px-1.5 py-0.5 text-[10px]" style={{ border: `1px solid ${active ? C.blue : 'transparent'}`, background: active ? 'rgba(59,130,246,.10)' : 'transparent', color: active ? C.blue : C.muted }}>{filter.label} <span style={{ opacity: .7 }}>{count}</span></button>;
        })}
        {!showSectorRotation && [...watchedGroups.keys()].map((sector) => <button key={sector} onClick={() => setActiveSector(activeSector === sector ? '全部' : sector)} className="rounded px-1.5 py-0.5 text-[10px]" style={{ color: activeSector === sector ? C.blue : C.muted }}>{sector} {watchedGroups.get(sector).length}</button>)}
        <span className="flex-1" />
        {scope === 'watched' ? <button onClick={() => setAutoRefresh((old) => !old)} className="rounded px-1 py-0.5 text-[9px]" title="切换实时价格流；技术指标仍固定使用决策日" style={{ color: autoRefresh && streamStatus === 'open' ? '#22c55e' : C.muted }}>{autoRefresh && streamStatus === 'open' ? '● 实时' : '○ 静态'}</button> : <span className="px-1 text-[9px]" style={{ color: C.muted }}>决策收盘</span>}
        <select value={sortKey} onChange={(event) => setSortKey(event.target.value)} className="rounded border px-1 py-0.5 text-[10px]" style={{ borderColor: C.border, background: 'transparent', color: C.secondary }}>{SORTS.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
        <button onClick={() => setSortDir((old) => old === 'desc' ? 'asc' : 'desc')} title="切换排序方向" className="rounded border px-1.5 py-0.5 text-[10px]" style={{ borderColor: C.border, color: C.secondary }}>{sortDir === 'desc' ? '↓' : '↑'}</button>
        <button onClick={load} title="刷新日线结论" className="rounded border px-1.5 py-0.5 text-[10px]" style={{ borderColor: C.border, color: C.secondary }}>↻</button>
        {!addOpen ? <button onClick={() => setAddOpen(true)} className="rounded border px-1.5 py-0.5 text-[10px]" style={{ borderColor: C.border, color: C.blue }}>＋{market === 'HK' ? '港股' : '美股'}</button> : <>
          <input autoFocus value={addSymbol} onChange={(event) => setAddSymbol(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter') handleAdd(); if (event.key === 'Escape') setAddOpen(false); }} placeholder="代码" className="w-20 rounded border px-1.5 py-0.5 text-[10px] outline-none" style={{ borderColor: C.border, background: 'var(--bg-surface)', color: C.primary }} />
          <button onClick={handleAdd} disabled={adding} className="rounded px-1.5 py-0.5 text-[10px]" style={{ background: C.blue, color: '#fff' }}>{adding ? '添加中' : '添加'}</button>
          <button onClick={() => { setAddOpen(false); setAddError(null); }} className="rounded px-1 py-0.5 text-[10px]" style={{ color: C.muted }}>取消</button>
        </>}
        {addError && <span className="text-[11px]" style={{ color: C.down }}>{addError}</span>}
      </div>

      <StockListContainer
        viewModeKey={showSectorRotation ? `us-watchlist-sector-${market}` : `us-watchlist-${market}`}
        viewMode="table" showToggle={false} loading={loading || (scope === 'market' && activeSector !== '全部' && candidateLoading)} error={scope === 'market' ? marketError || error : error}
        onRetry={load} items={pageItems} tableRenderer={tableRenderer}
        contentClassName="rounded-lg border overflow-hidden"
        emptyClassName="flex items-center justify-center py-5 text-[11px]"
        emptyText={scope === 'market' ? (activeSector === '全部' ? '当前强势板块暂无满足9%/两日16%门槛的候选' : `${activeSector} 暂无满足强势证据门槛的候选`) : '暂无重点关注，可从全市场机会或添加按钮加入'}
        loadingText={scope === 'market' ? '加载全市场机会快照...' : '加载重点关注...'}
      />
      <PageControls page={page} pageCount={pageCount} total={filteredItems.length} onChange={setPage} />

      {selectedStock && <USStockDetailDrawer stock={selectedStock} market={market} onClose={() => setSelectedStock(null)} />}
    </div>
  );
}

function WatchlistHoldingTable({ items, scope, watchedSymbols, adding, onOpen, onRemove, onAdd }) {
  const [sort, setSort] = useState({ key: null, dir: -1 });
  const toggleSort = useCallback((key) => {
    setSort((prev) => prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: -1 });
  }, []);
  const columns = [
    ['股票', 138, 'left', true], ['数量', 104, 'right', false], ['现价 / 成本价', 112, 'left', false],
    ['当日盈亏 / 当日涨幅', 126, 'left', false], ['持仓盈亏 / 持仓收益率', 136, 'left', false],
    ['仓位', 62, 'right', false], ['评分', 56, 'center', false],
    ['均线结构（MA5/20/60）', 190, 'left', false], ['RSI14', 56, 'center', false],
    ['MACD状态', 92, 'left', false], ['KDJ（K/D/J）', 104, 'left', false],
    ['换手率', 64, 'center', false], ['个股资金 / 板块', 148, 'left', false],
    ['支撑 / 压力位', 112, 'left', false], ['风险提示', 150, 'left', false],
    ['建议', 92, 'left', false], ['操作', 176, 'center', false], ['自动交易', 128, 'center', true],
  ];
  return <div className="overflow-x-auto no-scrollbar">
    <table className="w-full text-[9px]" style={{ borderCollapse: 'collapse', minWidth: 2200, tableLayout: 'fixed' }}>
      <thead><tr style={{ background: 'var(--bg-secondary)' }}>
        {columns.map(([label, width, align, sticky]) => {
          const sortKey = SORTABLE[label];
          const active = sort.key === sortKey;
          return <th key={label} className="px-1 py-1 font-semibold whitespace-nowrap" style={{ color: C.muted, width, minWidth: width, textAlign: align || 'left', position: sticky ? 'sticky' : 'static', left: sticky ? 0 : undefined, right: sticky ? 0 : undefined, zIndex: sticky ? 3 : 1, background: 'var(--bg-secondary)' }}>
            {sortKey ? <button type="button" tabIndex={-1} onClick={(e) => { e.stopPropagation(); toggleSort(sortKey); }} title={active ? (sort.dir === -1 ? '降序' : '升序') : `按「${label.replace(/ \/ .*/, '')}」排序`} className="inline-flex items-center gap-1 whitespace-nowrap" style={{ all: 'unset', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 3, color: active ? 'var(--accent-blue)' : 'inherit', textAlign: 'left' }}>{label}<span className="font-mono" style={{ fontSize: 9, lineHeight: 1, color: active ? 'var(--accent-blue)' : 'var(--text-muted)', opacity: active ? 1 : 0.7 }}>{active ? (sort.dir === -1 ? '▼' : '▲') : '↕'}</span></button> : label}
          </th>;
        })}
      </tr></thead>
      <tbody>{sortItems(items, sort.key, sort.dir).map((item) => {
        const ind = item.indicators || {};
        const pos = item.position;
        const action = item.trade_action || {};
        const opportunityColor = OPPORTUNITY_COLORS[item.opportunity?.status] || C.muted;
        const risks = riskHints(item);
        const watched = watchedSymbols.has(item.symbol);
        const hasPos = (pos?.quantity ?? 0) > 0;
        const marketValue = hasPos && finite(item.price) && finite(pos.quantity) ? finite(item.price) * finite(pos.quantity) : null;
        const rowBackground = pos?.hold_profit == null ? 'var(--bg-card)' : pos.hold_profit >= 0 ? 'rgba(239,68,68,.04)' : 'rgba(34,197,94,.04)';
        const ma20Val = finite(ind.ma20);
        const ma20Dist = ma20Val && finite(item.price) && ma20Val !== 0 ? (finite(item.price) - ma20Val) / ma20Val * 100 : null;
        const ma20Above = ma20Val && finite(item.price) ? finite(item.price) >= ma20Val : null;
        const actionColor = ACTION_COLOR_WL(action.action_color, action.action);
        return <tr key={item.symbol} onClick={(event) => { if (!event.target.closest('button,a,input,select')) onOpen(item); }} style={{ borderTop: `1px solid ${C.borderLight}`, background: rowBackground }}>
          {/* 股票（固定左） */}
          <td className="sticky left-0 z-[2] px-1 py-0.5 whitespace-nowrap" style={{ background: rowBackground }}>
            <button onClick={() => onOpen(item)} className="max-w-full text-left">
              <div className="flex items-center gap-1"><span className="truncate font-bold" style={{ color: C.primary }}>{item.name || item.symbol}</span><span className="truncate text-[8px]" style={{ color: C.muted }}>{item.symbol}</span>{(pos?.hold_profit ?? 0) < 0 && <span className="rounded px-0.5 text-[8px]" style={{ background: 'rgba(34,197,94,.12)', color: C.down }}>亏</span>}</div>
            </button>
            <div className="flex items-center gap-1 text-[8px]">
              <span className="truncate flex-1 min-w-0" style={{ color: C.muted }}>{item.sector || '其他'}<span className="ml-1 rounded px-0.5" style={{ color: opportunityColor, background: `${opportunityColor}16` }}>{item.opportunity?.label || '未判断'}</span></span>
              <SinaLink market="US" code={item.symbol} size="xs" />
            </div>
          </td>
          {/* 数量 */}
          <td className="px-1 py-0.5 whitespace-nowrap text-right" style={{ color: C.secondary }}>
            {hasPos ? <>{hasPos && pos.quantity != null ? <span>{finite(pos.quantity)}股</span> : <span>—</span>}<div className="text-[8px]" style={{ color: C.muted }}>持仓金额 {marketValue != null ? money(marketValue, 0) : '—'}</div></> : <span style={{ color: C.muted }}>未持仓</span>}
          </td>
          {/* 现价 / 成本价 */}
          <td className="px-1 py-0.5 whitespace-nowrap">
            <span style={{ color: C.primary, fontWeight: 600 }}>现价 {num(item.price)}</span>
            <div className="text-[9px]" style={{ color: C.muted }}>成本 {pos?.cost_price != null ? num(pos.cost_price) : '—'}</div>
          </td>
          {/* 当日盈亏 / 当日涨幅 */}
          <td className="px-1 py-0.5 whitespace-nowrap">
            <span style={{ color: C.muted }}>盈亏 —</span>
            <div className="text-[9px]" style={{ color: tone(item.change_pct) }}>涨幅 {pct(item.change_pct, 2)}</div>
          </td>
          {/* 持仓盈亏 / 持仓收益率 */}
          <td className="px-1 py-0.5 whitespace-nowrap">
            {hasPos ? (<>{pos.hold_profit != null ? <span style={{ color: tone(pos.hold_profit), fontWeight: 600 }}>盈亏 {money(pos.hold_profit)}</span> : <span style={{ color: C.muted }}>盈亏 —</span>}<div className="text-[9px]" style={{ color: tone(pos.hold_profit_pct) }}>收益 {pct(pos.hold_profit_pct, 1)}</div></>) : <span style={{ color: C.muted }}>未持仓</span>}
          </td>
          {/* 仓位 */}
          <td className="px-1 py-0.5 whitespace-nowrap text-right" style={{ color: C.muted }}>—</td>
          {/* 评分 */}
          <td className="px-1 py-0.5 text-center">
            {(item.candidate_score ?? ind.score) != null ? <span className="font-bold" style={{ color: (item.candidate_score ?? ind.score) >= 70 ? C.up : (item.candidate_score ?? ind.score) >= 50 ? '#f59e0b' : C.muted }}>{Math.round(item.candidate_score ?? ind.score)}</span> : <span style={{ color: C.muted }}>—</span>}
          </td>
          {/* 均线结构（MA5/20/60） */}
          <td className="px-1 py-0.5 whitespace-nowrap cursor-help" title="技术指标固定使用决策日收盘数据。">
            <div className="font-mono text-[9px]"><span style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>MA5 {num(ind.ma5)}</span><span style={{ color: 'var(--border-color)' }}> · </span><span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>MA20 {num(ind.ma20)}</span><span style={{ color: 'var(--border-color)' }}> · </span><span style={{ color: C.muted }}>MA60 {num(ind.ma60)}</span></div>
            <div style={{ color: ma20Above == null ? C.muted : ma20Above ? C.up : C.down, fontWeight: 600 }}>{ind.ma_struct || '—'} {ma20Above != null ? (ma20Above ? '· 现价高于 MA20' : '· 现价低于 MA20') : ''}{ma20Dist != null ? ` ${ma20Dist >= 0 ? '+' : ''}${num(ma20Dist, 1)}%` : ''}</div>
            <div className="text-[8px]" style={{ color: C.muted }}>MA20斜率：{finite(ind.ma20_slope) ? `${ind.ma20_slope >= 0 ? '+' : ''}${num(ind.ma20_slope, 1)}%` : '—'}</div>
          </td>
          {/* RSI14 */}
          <td className="px-1 py-0.5 text-center" style={{ color: finite(ind.rsi) ? (ind.rsi >= 70 ? C.up : ind.rsi <= 30 ? C.down : C.secondary) : C.muted }}>{finite(ind.rsi) ? num(ind.rsi, 0) : '—'}</td>
          {/* MACD状态 */}
          <td className="px-1 py-0.5 whitespace-nowrap" style={{ color: /金叉/.test(macdText(ind)) ? C.up : /死叉/.test(macdText(ind)) ? C.down : C.muted }}>{macdText(ind)}</td>
          {/* KDJ（K/D/J） */}
          <td className="px-1 py-0.5 whitespace-nowrap">
            <div className="font-mono text-[9px]" style={{ color: C.secondary }}>K {num(ind.kdj?.k, 1)} / D {num(ind.kdj?.d, 1)} / J {num(ind.kdj?.j, 1)}</div>
            <div style={{ color: /超买/.test(kdjText(ind)) ? C.up : /超卖/.test(kdjText(ind)) ? C.down : C.muted }}>{kdjText(ind)}</div>
          </td>
          {/* 换手率 */}
          <td className="px-1 py-0.5 text-center" style={{ color: ind.turnover == null ? C.muted : C.secondary }}>{ind.turnover == null ? '—' : `${num(ind.turnover, 1)}%`}</td>
          {/* 个股资金 / 板块 */}
          <td className="px-1 py-0.5 whitespace-nowrap">
            <div style={{ color: C.muted }}>主力 —</div>
            <div className="text-[8px]" style={{ color: C.secondary }}>{item.sector || '—'}</div>
          </td>
          {/* 支撑 / 压力位 */}
          <td className="px-1 py-0.5 whitespace-nowrap" style={{ color: C.muted }}>{finite(ind.support) ? `支撑 ${num(ind.support)}` : '支撑 —'}{finite(ind.resistance) ? ` · 压力 ${num(ind.resistance)}` : ' · 压力 —'}</td>
          {/* 风险提示 */}
          <td className="px-1 py-0.5">{risks?.length ? <div className="flex flex-wrap gap-1">{risks.map((h, i) => <span key={i} className="rounded px-1 py-0.5 text-[8px] whitespace-nowrap" style={{ background: /止损|风险|跌破|死叉/.test(h) ? 'rgba(239,68,68,.12)' : 'rgba(245,158,11,.14)', color: /止损|风险|跌破|死叉/.test(h) ? '#ef4444' : '#d97706' }}>{h}</span>)}</div> : <span style={{ color: C.muted }}>暂无明显风险</span>}</td>
          {/* 建议 */}
          <td className="px-1 py-0.5 whitespace-nowrap font-medium" style={{ color: actionColor }}>{actionText(action)}</td>
          {/* 操作 */}
          <td className="sticky right-0 z-[2] px-1 py-0.5 text-center" style={{ background: rowBackground, width: 176, maxWidth: 176, overflow: 'hidden' }}>{scope === 'market' ? <div className="flex flex-wrap items-center gap-1"><StockActionButtons stockCode={item.symbol} stockName={item.name} size="xs" showBuy={false} showSell={false} showTrack={false} showWatch={false} showMore={false} showKline={false} showSina={false} showAutoTrade={false} /><button onClick={() => onOpen(item)} className="rounded border px-1.5 py-0.5 text-[9px]" style={{ borderColor: C.border, color: C.blue }}>明细</button><button disabled={watched || adding === item.symbol} onClick={() => onAdd(item.symbol)} className="rounded border px-1.5 py-0.5 text-[9px] disabled:opacity-50" style={{ borderColor: watched ? C.border : 'rgba(239,68,68,.35)', color: watched ? C.muted : C.up }}>{watched ? '已关注' : adding === item.symbol ? '添加中' : '＋关注'}</button></div> : <div className="flex flex-wrap items-center gap-1"><StockActionButtons stockCode={item.symbol} stockName={item.name} positionCount={pos?.quantity || 0} size="xs" showSell={Boolean(pos)} showTrack={false} showWatch={false} showKline={false} showSina={false} showAutoTrade={false} /><button onClick={() => onOpen(item)} className="rounded border px-1.5 py-0.5 text-[9px]" style={{ borderColor: C.border, color: C.blue }}>明细</button><button onClick={() => onRemove(item.symbol)} className="rounded border px-1.5 py-0.5 text-[9px]" style={{ borderColor: 'rgba(239,68,68,.3)', color: '#ef4444' }}>剔除</button></div>}</td>
          {/* 自动交易（固定右，美股自选暂无自动交易引擎，占位为关闭） */}
          <td className="sticky right-0 z-[2] px-1 py-0.5 text-center" style={{ background: rowBackground }}><span className="rounded border px-1.5 py-0.5 text-[9px] whitespace-nowrap" style={{ borderColor: C.border, color: C.muted, background: 'transparent' }}>关闭</span></td>
        </tr>;
      })}</tbody>
    </table>
  </div>;
}
