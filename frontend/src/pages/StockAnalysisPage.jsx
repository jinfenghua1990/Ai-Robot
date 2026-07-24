import { useMemo, useState, useEffect, useCallback } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import KLineChart from '../components/charts/KLineChart';
import IntradayPanel from '../components/trading/IntradayPanel';
import StockActionButtons from '../components/trading/StockActionButtons';
import { apiFetch } from '../utils/request';
import { useTrading } from '../context/TradingContext';
import { POLL_INTERVAL } from '../utils/constants';

const UP = '#D8504A';    // 涨=红（原型奶油蓝配色）
const DOWN = '#3B9A2E';  // 跌=绿

const TABS = [
  { key: 'overview', label: '诊断', id: 'sec-overview' },
  { key: 'bs', label: 'B/S区间', id: 'sec-bs' },
  { key: 'tech', label: '技术', id: 'sec-tech' },
  { key: 'capital', label: '资金', id: 'sec-capital' },
  { key: 'intraday', label: '盘中实时', id: 'sec-intraday' },
  { key: 'strategy', label: '策略', id: 'sec-strategy' },
  { key: 'f10', label: 'F10', id: 'sec-f10' },
  { key: 'news', label: '新闻', id: 'sec-news' },
  { key: 'ai', label: 'AI分析', id: 'sec-ai' },
];

// 策略标签颜色映射
const STRATEGY_TAG_COLORS = {
  baihu_v30: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: 'rgba(245,158,11,0.4)' },
  liangjia_report: { bg: 'rgba(234,179,8,0.15)', color: '#eab308', border: 'rgba(234,179,8,0.4)' },
  qinglong: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', border: 'rgba(239,68,68,0.4)' },
  macd_golden_cross: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', border: 'rgba(239,68,68,0.4)' },
  risk_exit: { bg: 'rgba(34,197,94,0.15)', color: '#22c55e', border: 'rgba(34,197,94,0.4)' },
  baihu_v26: { bg: 'rgba(234,179,8,0.08)', color: '#a3a3a3', border: 'rgba(234,179,8,0.2)' },
  zhushenglang: { bg: 'rgba(239,68,68,0.08)', color: '#a3a3a3', border: 'rgba(239,68,68,0.2)' },
  wave_band: { bg: 'rgba(59,130,246,0.08)', color: '#a3a3a3', border: 'rgba(59,130,246,0.2)' },
  volume_breakout: { bg: 'rgba(249,115,22,0.08)', color: '#a3a3a3', border: 'rgba(249,115,22,0.2)' },
};

function fmtMoney(y) {
  if (y == null || isNaN(y)) return '—';
  const a = Math.abs(y);
  if (a >= 1e8) return (y / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (y / 1e4).toFixed(0) + '万';
  return Math.round(y) + '元';
}

const DIM_LABELS = {
  trend_strength: '趋势强度', capital_momentum: '资金动能', sector_resonance: '板块共振',
  volume_health: '量能健康', volatility_health: '波动健康', relative_strength: '相对强度',
  drawdown_status: '回撤状态', institution_signal: '机构信号',
};

// 14 日 RSI
function calcRSI(closes, period = 14) {
  if (!closes || closes.length < period + 1) return null;
  let gains = 0, losses = 0;
  for (let i = closes.length - period; i < closes.length; i++) {
    const d = closes[i] - closes[i - 1];
    if (d >= 0) gains += d; else losses -= d;
  }
  const rs = gains / (losses || 1e-9);
  return 100 - 100 / (1 + rs);
}

export default function StockAnalysisPage({ embedded = false, initialCode } = {}) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [code, setCode] = useState(initialCode || searchParams.get('code') || '300164');
  const navigate = useNavigate();
  const { positions } = useTrading();
  const [dash, setDash] = useState(null);
  const [quote, setQuote] = useState(null);
  const [peers, setPeers] = useState(null);
  const [bs, setBs] = useState(null); // bs-signals（技术指标回退）
  const [stockNews, setStockNews] = useState({ news: [], announcements: [] }); // 真实个股新闻/公告（东财）
  const [newsTab, setNewsTab] = useState('news');
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState('overview');

  // 盘中实时（super_panel 实时段，5秒轮询）
  const [superPanel, setSuperPanel] = useState(null);   // 静态段（盘后底牌/F10）
  const [realtimeData, setRealtimeData] = useState(null);
  const [livePrice, setLivePrice] = useState(null); // 实时最新价（驱动蜡烛图当日K跳动）
  const [liveSeries, setLiveSeries] = useState(null); // 当日实时价序列（驱动蜡烛图实时价曲线）
  // 策略标签
  const [strategyData, setStrategyData] = useState(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  // AI 分析
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiStats, setAiStats] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiLoaded, setAiLoaded] = useState(false);

  const changeCode = (raw) => {
    const cc = String(raw).replace(/\D/g, '').slice(0, 6);
    if (!cc) return;
    setCode(cc);
    setSearchParams({ code: cc });
  };
  const myPos = useMemo(() => {
    const list = positions?.positions || (Array.isArray(positions) ? positions : []);
    return list.find(p => p.secCode === code) || null;
  }, [positions, code]);

  useEffect(() => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    let cancelled = false;
    setLoading(true);
    // 切换股票时重置新模块状态，避免旧数据串台
    setSuperPanel(null);
    setRealtimeData(null);
    setLivePrice(null);
    setLiveSeries(null);
    setStrategyData(null);
    setStrategyLoading(true);
    setAiLoaded(false);
    setAiAnalysis(null);
    setAiStats(null);
    setStockNews({ news: [], announcements: [] });
    Promise.all([
      apiFetch(`/api/stock-dashboard/${base}`),
      apiFetch(`/api/trading/quote?code=${base}`),
      apiFetch(`/api/watchlist`),
      apiFetch(`/api/trading/bs-signals?stockCode=${base}&datalen=60`),
      apiFetch(`/api/stock/${base}/news?limit=8`),
    ]).then(([dRes, qRes, wRes, bsRes, nRes]) => {
      if (cancelled) return;
      if (dRes.ok) setDash(dRes.data);
      if (qRes.ok) setQuote(qRes.data);
      if (wRes.ok) setPeers(wRes.data);
      if (bsRes.ok) setBs(bsRes.data);
      if (nRes.ok) setStockNews(nRes.data || { news: [], announcements: [] });
      setLoading(false);
    }).catch(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [code]);

  // 策略标签（/api/stock-strategies）
  useEffect(() => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    let cancelled = false;
    setStrategyLoading(true);
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/stock-strategies/${base}`);
        if (cancelled && !ok) return;
        if (ok) setStrategyData(data);
      } catch (e) { console.error('[strategy]', e); }
      if (!cancelled) setStrategyLoading(false);
    })();
    return () => { cancelled = true; };
  }, [code]);

  // F10 / 盘后底牌（super_panel 静态段，只拉 1 次）
  useEffect(() => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    let cancelled = false;
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/v1/stock/super_panel?code=${base}&section=static`);
        if (ok && !cancelled) setSuperPanel(data);
      } catch (e) { console.error('[super_panel]', e); }
    })();
    return () => { cancelled = true; };
  }, [code]);

  // 盘中实时（super_panel 实时段，5秒轮询，页面隐藏暂停）
  const fetchRealtime = useCallback(async () => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    try {
      const { ok, data } = await apiFetch(`/api/v1/stock/super_panel?code=${base}&section=realtime`);
      if (ok) setRealtimeData(data);
    } catch (e) { /* silent */ }
  }, [code]);

  useEffect(() => {
    fetchRealtime();
    const t = setInterval(() => { if (!document.hidden) fetchRealtime(); }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [fetchRealtime]);

  // 实时最新价（intraday 接口的 stockQuote.price，5秒轮询，驱动蜡烛图当日K跳动）
  const fetchLivePrice = useCallback(async () => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    try {
      const { ok, data } = await apiFetch(`/api/trading/intraday/${base}`);
      if (ok && data?.stockQuote?.price != null) {
        setLivePrice(data.stockQuote.price);
        if (Array.isArray(data.intraday) && data.intraday.length) {
          setLiveSeries(data.intraday.map(k => k.close));
        }
      }
    } catch (e) { /* silent */ }
  }, [code]);

  useEffect(() => {
    fetchLivePrice();
    const t = setInterval(() => { if (!document.hidden) fetchLivePrice(); }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [fetchLivePrice]);

  // AI 分析（懒加载：首次切到 AI 标签时拉取）
  const loadAI = useCallback(async () => {
    const base = code.replace(/\D/g, '');
    if (!base || aiLoaded) return;
    setAiLoading(true);
    try {
      const [a, s] = await Promise.all([
        apiFetch(`/api/ai/stock/${base}/analysis`),
        apiFetch(`/api/ai/stock/${base}/history`),
      ]);
      setAiAnalysis(a.ok ? a.data : null);
      setAiStats(s.ok ? s.data : null);
    } catch (e) { /* silent */ }
    setAiLoading(false);
    setAiLoaded(true);
  }, [code, aiLoaded]);

  useEffect(() => {
    if (activeTab === 'ai') loadAI();
  }, [activeTab, loadAI]);

  // tab 随滚动高亮（scroll-spy）
  useEffect(() => {
    const onScroll = () => {
      let current = TABS[0].id;
      for (const t of TABS) {
        const el = document.getElementById(t.id);
        if (el && el.getBoundingClientRect().top <= 80) current = t.id;
      }
      const key = TABS.find(t => t.id === current)?.key;
      if (key) setActiveTab(prev => (prev === key ? prev : key));
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => window.removeEventListener('scroll', onScroll);
  }, []);

  const name = dash?.quote?.name || quote?.name || (dash?.sector_flow?.sector || code);
  const price = quote?.price ?? dash?.quote?.price ?? null;
  const chg = quote?.changePct ?? dash?.quote?.change ?? null;
  const up = (chg ?? 0) >= 0;
  const chgColor = up ? UP : DOWN;

  const amplitude = useMemo(() => {
    if (!quote?.high || !quote?.low || !quote?.yesterdayClose) return null;
    return (quote.high - quote.low) / quote.yesterdayClose * 100;
  }, [quote]);

  const dayMainNet = dash?.realtime?.main_net ?? dash?.institution_flow?.main_net ?? null;

  const dims = useMemo(() => {
    if (!dash) return [];
    return Object.keys(DIM_LABELS).map(k => ({ key: k, label: DIM_LABELS[k], v: dash[k] ?? 0 }));
  }, [dash]);
  const composite = dims.length ? Math.round(dims.reduce((s, d) => s + d.v, 0) / dims.length) : null;

  // 技术指标：优先 dashboard，回退 bs-signals 实时计算
  const tech = useMemo(() => {
    const ind = bs?.indicators || {};
    const klines = bs?.klines || [];
    const last = arr => (Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null);
    const macdDif = dash?.technical_indicators?.macd?.dif ?? last(ind.dif);
    const macdDea = dash?.technical_indicators?.macd?.dea ?? last(ind.dea);
    const macdHist = dash?.technical_indicators?.macd?.macd ?? last(ind.macd);
    const kdjK = dash?.technical_indicators?.kdj?.k ?? last(ind.kdj_k);
    const kdjD = dash?.technical_indicators?.kdj?.d ?? last(ind.kdj_d);
    const kdjJ = dash?.technical_indicators?.kdj?.j ?? last(ind.kdj_j);
    const rsi = dash?.features?.rsi_14 ?? calcRSI(klines.map(k => k.close));
    const volRatio = dash?.features?.volume_ratio ?? null;
    const closeVsMa20 = dash?.features?.close_vs_ma20 ?? null;
    const mCross = macdDif != null && macdDea != null ? (macdDif >= macdDea ? '多头' : '空头') : '';
    const kCross = kdjK != null && kdjD != null ? (kdjK >= kdjD ? '多头' : '空头') : '';
    return { macdDif, macdDea, macdHist, kdjK, kdjD, kdjJ, rsi, volRatio, closeVsMa20, mCross, kCross };
  }, [dash, bs]);

  // 个股诊断结论（综合全页数据，纯前端合成，不新增接口）
  const verdict = useMemo(() => {
    if (!dash) return null;
    const score = composite ?? 0;
    const techBull = tech.mCross === '多头' && tech.kCross === '多头';
    const techBear = tech.mCross === '空头' && tech.kCross === '空头';
    const fundIn = (dayMainNet ?? 0) >= 0;
    let state, stateColor, stateBg;
    if (score >= 60 && (techBull || fundIn)) { state = '偏强'; stateColor = UP; stateBg = 'rgba(216,80,74,0.12)'; }
    else if (score < 40 || (techBear && !fundIn)) { state = '偏弱'; stateColor = DOWN; stateBg = 'rgba(59,154,46,0.12)'; }
    else { state = '震荡'; stateColor = '#888780'; stateBg = 'rgba(136,135,128,0.12)'; }
    const trendV = dims.find(d => d.key === 'trend_strength')?.v ?? 0;
    const trendWord = trendV >= 60 ? '趋势强' : trendV >= 40 ? '趋势中等' : '趋势弱';
    const fundWord = fundIn ? '资金净流入' : '资金净流出';
    const rsiWord = tech.rsi == null ? '—' : tech.rsi >= 70 ? 'RSI超买' : tech.rsi <= 30 ? 'RSI超卖' : `RSI${tech.rsi.toFixed(0)}`;
    const summary = `综合评分 ${score}｜${trendWord}｜${fundWord}｜MACD${tech.mCross}／KDJ${tech.kCross}｜${rsiWord}。操作建议：${dash?.action_label || '观望'}`;
    return { state, stateColor, stateBg, score, summary, action: dash?.action_label, actionColor: dash?.action_color, techBull, fundIn };
  }, [dash, tech, dayMainNet, composite, dims]);

  const cum = dash?.main_net_cumulative?.stock || {};
  const cumRows = [{ p: 1, v: cum[1] }, { p: 3, v: cum[3] }, { p: 5, v: cum[5] }, { p: 10, v: cum[10] }, { p: 20, v: cum[20] }];

  const related = useMemo(() => {
    if (!peers) return [];
    const flat = [];
    if (Array.isArray(peers.groups)) peers.groups.forEach(g => (g.stocks || []).forEach(s => flat.push(s)));
    else if (Array.isArray(peers.signals)) peers.signals.forEach(s => flat.push(s));
    const me = flat.find(s => (s.secCode || s.stock_code) === code);
    const grp = me?.group || me?.sector || '';
    if (!grp) return [];
    return flat.filter(s => (s.group || s.sector) === grp && (s.secCode || s.stock_code) !== code)
      .slice(0, 8)
      .map(s => ({ name: s.secName || s.stock_name || s.name, code: s.secCode || s.stock_code, chg: s.quote?.changePct ?? s.change_pct ?? s.chg ?? null }));
  }, [peers, code]);

  const sector = dash?.sector_flow;
  const rotation = dash?.sector_rotation;

  if (loading) return <div className="p-6 text-sm" style={{ color: '#888780', background: '#F1EFE8', minHeight: '100vh' }}>加载 {code} 真实分析数据…</div>;

  return (
    <div
      className="mx-auto"
      style={{
        maxWidth: 1120,
        margin: '0 auto',
        padding: '20px 24px 32px',
        background: '#F1EFE8',
        minHeight: '100vh',
        '--bg-card': '#ffffff',
        '--bg-surface': '#F7F6F2',
        '--border-color': '#D3D1C7',
        '--text-primary': '#2C2C2A',
        '--text-secondary': '#5F5E5A',
        '--text-muted': '#888780',
        '--accent-blue': '#185FA5',
      }}
    >
      <div className="space-y-3">
      {/* 顶部通栏 */}
      <div className={`rounded-xl p-2.5 flex items-center justify-between flex-wrap gap-2 ${embedded ? '' : 'sticky top-0 z-30'}`}
        style={{ background: '#E6F1FB', border: '1px solid #378ADD', boxShadow: embedded ? 'none' : '0 2px 12px rgba(0,0,0,0.06)' }}>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <input value={code} onChange={(e) => changeCode(e.target.value)}
              placeholder="代码" className="w-20 px-2 py-1 rounded-lg text-xs font-bold outline-none"
              style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
            <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{name}</span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{code}</span>
          </div>
          <div className="flex items-baseline gap-2">
            <span className="text-xl font-bold tabular-nums" style={{ color: chgColor }}>{price != null ? price.toFixed(2) : '—'}</span>
            <span className="text-sm font-semibold tabular-nums" style={{ color: chgColor }}>{chg != null ? `${up ? '+' : ''}${chg}% ${up ? '▲' : '▼'}` : ''}</span>
          </div>
          <div className="flex items-center gap-1.5">
            {TABS.map(t => (
              <button key={t.key} type="button" onClick={() => {
                setActiveTab(t.key);
                const el = document.getElementById(t.id);
                if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
              }}
                className="px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer"
                style={{ background: activeTab === t.key ? 'rgba(55,138,221,0.12)' : 'transparent', color: activeTab === t.key ? 'var(--accent-blue)' : 'var(--text-secondary)', border: `1px solid ${activeTab === t.key ? 'var(--accent-blue)' : 'var(--border-color)'}` }}>{t.label}</button>
            ))}
          </div>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <StockActionButtons
            stockCode={code}
            stockName={name}
            positionCount={myPos?.count || 0}
            showAnalysis={false}
            showKline
            showBuy
            showSell
            showWatch
            showTrack
            showSina
            showMore
            size="sm"
          />
          <div className="px-2.5 py-1 rounded-lg text-xs" style={{ background: dayMainNet != null && dayMainNet >= 0 ? 'rgba(216,80,74,0.1)' : 'rgba(59,154,46,0.1)', color: dayMainNet != null && dayMainNet >= 0 ? UP : DOWN, border: `1px solid ${dayMainNet != null && dayMainNet >= 0 ? 'rgba(216,80,74,0.35)' : 'rgba(59,154,46,0.35)'}` }}>
            主力净流入 {dayMainNet != null ? fmtMoney(dayMainNet) : '—'}
          </div>
        </div>
      </div>

      {/* KPI 条 */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
        {[
          { k: '现价', v: price != null ? price.toFixed(2) : '—', c: chgColor },
          { k: '涨跌幅', v: chg != null ? `${up ? '+' : ''}${chg}%` : '—', c: chgColor },
          { k: '振幅', v: amplitude != null ? `${amplitude.toFixed(2)}%` : '—' },
          { k: '量比', v: tech.volRatio != null ? tech.volRatio.toFixed(2) : '—', c: tech.volRatio > 1 ? UP : null },
          { k: '当日主力', v: fmtMoney(dayMainNet), c: dayMainNet != null && dayMainNet >= 0 ? UP : dayMainNet != null ? DOWN : null },
          { k: '操作建议', v: dash?.action_label || '—', c: dash?.action_color },
        ].map(x => (
          <div key={x.k} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{x.k}</div>
            <div className="text-base font-bold mt-0.5 tabular-nums truncate" style={{ color: x.c || 'var(--text-primary)' }}>{x.v}</div>
          </div>
        ))}
      </div>

      {/* 个股诊断结论带（专属页灵魂：综合全页数据） */}
      <div id="sec-overview" className="rounded-xl border p-3" style={{ scrollMarginTop: 64, borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-1.5 mb-2">
          <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🧭 个股诊断</span>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>综合评分·技术·资金·操作建议</span>
        </div>
        {verdict ? (
          <>
            <div className="flex items-center gap-4 flex-wrap">
              <div className="text-center">
                <div className="text-4xl font-bold leading-none" style={{ color: 'var(--accent-blue)' }}>{verdict.score}</div>
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>综合评分</div>
              </div>
              <span className="px-2.5 py-1 rounded-lg text-sm font-bold" style={{ background: verdict.stateBg, color: verdict.stateColor }}>{verdict.state}</span>
              {verdict.action && (
                <span className="px-2.5 py-1 rounded-lg text-sm font-bold" style={{ background: (verdict.actionColor || '#888780') + '20', color: verdict.actionColor || '#888780' }}>{verdict.action}</span>
              )}
              <div className="flex flex-wrap gap-1.5">
                <span className="px-2 py-0.5 rounded text-[11px] font-medium" style={{ background: 'var(--bg-surface)', color: tech.mCross === '多头' ? UP : tech.mCross === '空头' ? DOWN : 'var(--text-muted)', border: '1px solid var(--border-color)' }}>MACD {tech.mCross}</span>
                <span className="px-2 py-0.5 rounded text-[11px] font-medium" style={{ background: 'var(--bg-surface)', color: tech.kCross === '多头' ? UP : tech.kCross === '空头' ? DOWN : 'var(--text-muted)', border: '1px solid var(--border-color)' }}>KDJ {tech.kCross}</span>
                <span className="px-2 py-0.5 rounded text-[11px] font-medium" style={{ background: 'var(--bg-surface)', color: tech.rsi >= 70 ? UP : tech.rsi <= 30 ? DOWN : 'var(--text-muted)', border: '1px solid var(--border-color)' }}>RSI {tech.rsi != null ? tech.rsi.toFixed(0) : '—'}</span>
                <span className="px-2 py-0.5 rounded text-[11px] font-medium" style={{ background: 'var(--bg-surface)', color: verdict.fundIn ? UP : DOWN, border: '1px solid var(--border-color)' }}>{verdict.fundIn ? '资金流入' : '资金流出'}</span>
              </div>
            </div>
            <div className="mt-2 text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{verdict.summary}</div>
          </>
        ) : <div className="text-xs py-2" style={{ color: 'var(--text-muted)' }}>该股票暂无分析特征数据（dashboard），诊断暂不可用</div>}
      </div>

      {/* 双栏终端布局：主区分析 + 右栏上下文 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 items-start">
        {/* 主区（左侧 2 列） */}
        <div className="lg:col-span-2 space-y-3">
          {/* K线/B-S + 实时曲线 */}
          <div id="sec-bs" style={{ scrollMarginTop: 64, borderColor: 'var(--border-color)', background: 'var(--bg-card)' }} className="rounded-xl border p-2.5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📈 K线 · B/S 区间 · 成交量 · MACD/KDJ</span>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>蓝带=B/S区间 · 红●买 绿●卖 · 紫线 SuperTrend · 真实行情</span>
            </div>
            <div className="h-[460px]">
              {code ? <KLineChart code={code} upColor={UP} downColor={DOWN} livePrice={livePrice} liveSeries={liveSeries} /> : <div className="h-full flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>请输入股票代码</div>}
            </div>
          </div>

          {/* 技术指标 */}
          <div id="sec-tech" style={{ scrollMarginTop: 64, borderColor: 'var(--border-color)', background: 'var(--bg-card)' }} className="rounded-xl border p-2.5">
            <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>个股技术指标（真实）</div>

            {/* MACD × KDJ 共振结论条 */}
            <div className="flex items-center justify-between rounded-lg px-3 py-2 mb-2.5" style={{
              background: techBull ? UP + '12' : techBear ? DOWN + '12' : 'var(--bg-surface)',
              border: `1px solid ${techBull ? UP + '40' : techBear ? DOWN + '40' : 'var(--border-color)'}`,
            }}>
              <div className="flex items-center gap-1.5">
                <span className="text-base leading-none">{techBull ? '🔼' : techBear ? '🔽' : '➖'}</span>
                <span className="text-sm font-bold" style={{ color: techBull ? UP : techBear ? DOWN : 'var(--text-muted)' }}>{techBull ? '双金叉共振 · 看多' : techBear ? '双死叉共振 · 看空' : 'MACD/KDJ 未共振'}</span>
              </div>
              <span className="text-[10px] font-medium" style={{ color: 'var(--text-muted)' }}>MACD {tech.mCross} × KDJ {tech.kCross}</span>
            </div>

            {/* MACD + KDJ 双卡 */}
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              <div className="rounded-lg p-2.5" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>MACD</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{ color: tech.mCross === '多头' ? UP : tech.mCross === '空头' ? DOWN : 'var(--text-muted)', background: (tech.mCross === '多头' ? UP : tech.mCross === '空头' ? DOWN : '#888780') + '18', border: `1px solid ${(tech.mCross === '多头' ? UP : tech.mCross === '空头' ? DOWN : '#888780') + '40'}` }}>{tech.mCross || '—'}</span>
                </div>
                <div className="mt-1.5 grid grid-cols-3 gap-1 text-center">
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>DIF</div><div className="text-xs font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{tech.macdDif != null ? tech.macdDif.toFixed(2) : '—'}</div></div>
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>DEA</div><div className="text-xs font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{tech.macdDea != null ? tech.macdDea.toFixed(2) : '—'}</div></div>
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>MACD</div><div className="text-xs font-bold tabular-nums" style={{ color: tech.macdHist != null ? (tech.macdHist >= 0 ? UP : DOWN) : 'var(--text-primary)' }}>{tech.macdHist != null ? tech.macdHist.toFixed(2) : '—'}</div></div>
                </div>
              </div>
              <div className="rounded-lg p-2.5" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>KDJ</span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{ color: tech.kCross === '多头' ? UP : tech.kCross === '空头' ? DOWN : 'var(--text-muted)', background: (tech.kCross === '多头' ? UP : tech.kCross === '空头' ? DOWN : '#888780') + '18', border: `1px solid ${(tech.kCross === '多头' ? UP : tech.kCross === '空头' ? DOWN : '#888780') + '40'}` }}>{tech.kCross || '—'}</span>
                </div>
                <div className="mt-1.5 grid grid-cols-3 gap-1 text-center">
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>K</div><div className="text-xs font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{tech.kdjK != null ? tech.kdjK.toFixed(1) : '—'}</div></div>
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>D</div><div className="text-xs font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{tech.kdjD != null ? tech.kdjD.toFixed(1) : '—'}</div></div>
                  <div><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>J</div><div className="text-xs font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{tech.kdjJ != null ? tech.kdjJ.toFixed(1) : '—'}</div></div>
                </div>
              </div>
            </div>

            {/* 其余指标紧凑行 */}
            <div className="mt-2.5">
              {[
                { n: 'RSI(14)', v: tech.rsi != null ? tech.rsi.toFixed(1) : '—', s: tech.rsi >= 70 ? '超买' : tech.rsi <= 30 ? '超卖' : '中性', c: tech.rsi >= 70 ? UP : tech.rsi <= 30 ? DOWN : 'var(--text-muted)' },
                { n: '量比', v: tech.volRatio != null ? tech.volRatio.toFixed(2) : '—', s: tech.volRatio >= 1 ? '放量' : '缩量', c: tech.volRatio >= 1 ? UP : DOWN },
                { n: '价/MA20', v: tech.closeVsMa20 != null ? `${(tech.closeVsMa20 * 100).toFixed(1)}%` : '—', s: tech.closeVsMa20 >= 0 ? '站上' : '跌破', c: tech.closeVsMa20 >= 0 ? UP : DOWN },
              ].map(d => (
                <div key={d.n} className="flex items-center justify-between py-1.5" style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>{d.n}</span>
                  <span className="text-xs font-bold tabular-nums">{d.v}</span>
                  <span className="text-[11px] font-medium" style={{ color: d.c }}>{d.s}</span>
                </div>
              ))}
            </div>
          </div>

          {/* 资金面 */}
          <div id="sec-capital" style={{ scrollMarginTop: 64, borderColor: 'var(--border-color)', background: 'var(--bg-card)' }} className="rounded-xl border p-2.5">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>主力净流入累计（近 1/3/5/10/20 日）</span>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>红流入 · 绿流出 · 真实</span>
            </div>
            {dash ? (
              <>
                <div className="grid grid-cols-5 gap-2">
                  {cumRows.map(r => {
                    const v = r.v, pos = v != null && v >= 0;
                    return (
                      <div key={r.p} className="rounded-lg p-2 text-center" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{r.p}日</div>
                        <div className="text-sm font-bold mt-0.5 tabular-nums" style={{ color: v == null ? 'var(--text-muted)' : pos ? UP : DOWN }}>{fmtMoney(v)}</div>
                      </div>
                    );
                  })}
                </div>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
                  {[{ k: '主力净流入', v: dash?.institution_flow?.main_net }, { k: '散户净流入', v: dash?.institution_flow?.retail_net }, { k: '超大单净流入', v: dash?.institution_flow?.super_large_net }, { k: '大单净流入', v: dash?.institution_flow?.large_net }].map(x => (
                    <div key={x.k} className="rounded-lg p-2" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{x.k}</div>
                      <div className="text-sm font-bold mt-0.5 tabular-nums" style={{ color: x.v == null ? 'var(--text-muted)' : x.v >= 0 ? UP : DOWN }}>{fmtMoney(x.v)}</div>
                    </div>
                  ))}
                </div>
                {dash?.realtime?.sector_net != null && (
                  <div className="text-[10px] mt-1.5" style={{ color: 'var(--text-muted)' }}>板块实时：{(dash.realtime.sector_net / 1e4).toFixed(0)}万 · 板块涨幅 {dash.realtime.sector_rise != null ? `${dash.realtime.sector_rise}%` : '—'} · 模式 {dash.realtime.mode}</div>
                )}
              </>
            ) : <div className="text-xs py-3" style={{ color: 'var(--text-muted)' }}>该股票暂无分析特征数据（dashboard），资金维度暂不可用</div>}
          </div>

          {/* 盘中实时 */}
          <div id="sec-intraday" style={{ scrollMarginTop: 64 }} className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div className="md:col-span-2 rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 分时图（盘中实时）</span>
                {realtimeData?.source_health?.realtime && (
                  <span className="px-2 py-0.5 rounded text-[10px]" style={{ background: realtimeData.source_health.realtime === 'live' ? 'rgba(34,197,94,0.15)' : 'rgba(107,114,128,0.15)', color: realtimeData.source_health.realtime === 'live' ? '#22c55e' : '#6b7280' }}>
                    {realtimeData.source_health.realtime === 'live' ? '🟢 LIVE' : realtimeData.source_health.realtime === 'closed' ? '⚪ 已收盘' : '🟡 待采集'}
                  </span>
                )}
              </div>
              <div className="h-[420px]">
                {code ? <IntradayPanel code={code} /> : <div className="h-full flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>请输入股票代码</div>}
              </div>
            </div>
            <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>盘中实时数据</div>
              {realtimeData?.realtime_intraday?.available ? (
                <IntradayLive data={realtimeData.realtime_intraday} />
              ) : (
                <div className="text-center py-4 text-xs" style={{ color: 'var(--text-muted)' }}>{realtimeData?.realtime_intraday?.message || '等待实时数据…'}</div>
              )}
            </div>
          </div>

          {/* 策略信号 */}
          <div id="sec-strategy" style={{ scrollMarginTop: 64 }} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>策略信号（真实命中）</div>
            {strategyLoading ? (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>
            ) : !strategyData || (strategyData.today_count === 0 && (strategyData.history || []).length === 0) ? (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>近 10 天未命中任何策略</div>
            ) : (
              <div className="space-y-3">
                {strategyData.today_count > 0 && (
                  <div>
                    <div className="text-xs font-bold mb-1.5" style={{ color: 'var(--text-secondary)' }}>今日命中 {strategyData.today_count} 个策略</div>
                    <div className="space-y-2">
                      {strategyData.today_strategies.map(s => {
                        const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
                        const d = s.detail || {};
                        return (
                          <div key={s.strategy_key} className="rounded-lg border p-2.5" style={{ borderColor: c.border, background: c.bg }}>
                            <div className="flex items-center justify-between mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-bold" style={{ color: c.color }}>{s.icon} {s.strategy_name}</span>
                                <span className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ background: c.color, color: '#fff' }}>评分 {s.score}</span>
                              </div>
                              {s.exit_signal && (
                                <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>退出: {s.exit_signal}</span>
                              )}
                            </div>
                            <div className="grid grid-cols-3 gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
                              {d['20day_gain'] != null && <div>20日涨幅: <strong style={{ color: d['20day_gain'] >= 20 ? UP : 'var(--text-primary)' }}>{d['20day_gain']}%</strong></div>}
                              {d.deviation != null && <div>偏离MA: <strong>{d.deviation}%</strong></div>}
                              {d.rsi != null && <div>RSI: <strong style={{ color: d.rsi > 70 ? UP : d.rsi < 30 ? DOWN : 'var(--text-primary)' }}>{d.rsi}</strong></div>}
                              {d.change_pct != null && <div>当日涨幅: <strong style={{ color: d.change_pct >= 0 ? UP : DOWN }}>{d.change_pct >= 0 ? '+' : ''}{d.change_pct}%</strong></div>}
                              {d.vol_ratio != null && <div>量比: <strong>{d.vol_ratio}%</strong></div>}
                              {d.lower_shadow != null && <div>下影线: <strong>{d.lower_shadow}%</strong></div>}
                              {d.ma_spread != null && <div>MA排列强度: <strong>{d.ma_spread}%</strong></div>}
                              {d.bias_20 != null && <div>Bias: <strong>{d.bias_20}</strong></div>}
                              {d.main_force_days != null && <div>主力连续流入: <strong>{d.main_force_days}天</strong></div>}
                              {d.close != null && <div>收盘价: <strong>{d.close}</strong></div>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
                {strategyData.history?.length > 0 && (
                  <div>
                    <div className="text-xs font-bold mb-2" style={{ color: 'var(--text-secondary)' }}>近 10 天命中历史（{strategyData.history.length} 天）</div>
                    <div className="space-y-1.5">
                      {strategyData.history.map(h => (
                        <div key={h.trade_date} className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
                          <span className="text-xs font-medium whitespace-nowrap" style={{ color: 'var(--text-muted)', minWidth: 80 }}>{h.trade_date}</span>
                          <div className="flex flex-wrap gap-1">
                            {h.strategies.map(s => {
                              const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
                              return (
                                <span key={s.strategy_key} className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>{s.icon} {s.strategy_name} {s.score}</span>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* F10 / 盘后底牌 */}
          <div id="sec-f10" style={{ scrollMarginTop: 64 }} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>🎯 盘后底牌 / F10</div>
            {superPanel?.post_market_base ? (
              <PostMarketBase data={superPanel.post_market_base} />
            ) : (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无盘后底牌数据</div>
            )}
          </div>

          {/* 新闻 / 公告（真实个股级，东财） */}
          <div id="sec-news" style={{ scrollMarginTop: 64 }} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📰 个股新闻 / 公告（东财真实）</span>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => setNewsTab('news')}
                  className="px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer"
                  style={{ background: newsTab === 'news' ? 'rgba(55,138,221,0.12)' : 'transparent', color: newsTab === 'news' ? 'var(--accent-blue)' : 'var(--text-secondary)', border: `1px solid ${newsTab === 'news' ? 'var(--accent-blue)' : 'var(--border-color)'}` }}>新闻 {stockNews.news.length}</button>
                <button type="button" onClick={() => setNewsTab('ann')}
                  className="px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer"
                  style={{ background: newsTab === 'ann' ? 'rgba(55,138,221,0.12)' : 'transparent', color: newsTab === 'ann' ? 'var(--accent-blue)' : 'var(--text-secondary)', border: `1px solid ${newsTab === 'ann' ? 'var(--accent-blue)' : 'var(--border-color)'}` }}>公告 {stockNews.announcements.length}</button>
              </div>
            </div>
            {newsTab === 'news' ? (
              stockNews.news.length === 0 ? (
                <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无该个股新闻</div>
              ) : (
                <div className="space-y-0">
                  {stockNews.news.map((n, i) => (
                    <a key={i} href={n.url || '#'} target="_blank" rel="noopener noreferrer"
                      className="block py-1.5 no-underline" style={{ borderBottom: i < stockNews.news.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                      <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        <span className="tabular-nums">{(n.time || '').slice(5, 16)}</span>
                        <span>{n.source || ''}</span>
                      </div>
                      <div className="text-xs mt-0.5" style={{ color: 'var(--text-primary)' }}>{n.title}</div>
                    </a>
                  ))}
                </div>
              )
            ) : (
              stockNews.announcements.length === 0 ? (
                <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无该个股公告</div>
              ) : (
                <div className="space-y-0">
                  {stockNews.announcements.map((a, i) => (
                    <a key={i} href={a.url || '#'} target="_blank" rel="noopener noreferrer"
                      className="block py-1.5 no-underline" style={{ borderBottom: i < stockNews.announcements.length - 1 ? '1px solid var(--border-color)' : 'none' }}>
                      <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        <span className="tabular-nums">{a.date}</span>
                        {a.type && <span className="px-1 rounded" style={{ background: 'rgba(55,138,221,0.1)', color: 'var(--accent-blue)' }}>{a.type}</span>}
                      </div>
                      <div className="text-xs mt-0.5" style={{ color: 'var(--text-primary)' }}>{a.title}</div>
                    </a>
                  ))}
                </div>
              )
            )}
          </div>

          {/* AI 分析 */}
          <div id="sec-ai" style={{ scrollMarginTop: 64 }} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>AI 分析</span>
              <div className="flex items-center gap-1.5">
                <button type="button" onClick={async () => {
                  await apiFetch('/api/analysis/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stock_code: code, stock_name: name, source: 'tdx' }) });
                  alert('📊 通达信分析请求已提交！可到 📋研报中心 查看进度。');
                }} className="px-2 py-1 rounded text-[10px] font-medium" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}>📊 通达信分析</button>
                <button type="button" onClick={async () => {
                  await apiFetch('/api/analysis/request', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ stock_code: code, stock_name: name, source: 'ifind' }) });
                  alert('📈 同花顺分析请求已提交！可到 📋研报中心 查看进度。');
                }} className="px-2 py-1 rounded text-[10px] font-medium" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}>📈 同花顺分析</button>
              </div>
            </div>
            {aiLoading ? (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>
            ) : (
              <div className="space-y-2">
                <div className="text-xs p-2 rounded" style={{ background: 'rgba(55,138,221,0.06)', color: 'var(--text-secondary)' }}>
                  已沉淀 <b style={{ color: 'var(--accent-blue)' }}>{aiStats?.news_count ?? 0}</b> 条资讯搜索 + <b style={{ color: 'var(--accent-blue)' }}>{aiStats?.data_count ?? 0}</b> 条金融数据查询记录
                </div>
                {aiAnalysis ? (
                  typeof aiAnalysis === 'string' ? (
                    <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{aiAnalysis}</div>
                  ) : aiAnalysis.content ? (
                    <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{aiAnalysis.content}</div>
                  ) : (
                    <pre className="text-xs whitespace-pre-wrap" style={{ color: 'var(--text-muted)' }}>{JSON.stringify(aiAnalysis, null, 2)}</pre>
                  )
                ) : (
                  <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无 AI 分析结果</div>
                )}
              </div>
            )}
          </div>
        </div>

        {/* 右栏上下文（粘性） */}
        <div className="lg:col-span-1 space-y-3 lg:sticky lg:top-[64px] lg:self-start">
          {/* 8维评分 */}
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>综合评分（8维真实）</div>
            {dash ? (
              <>
                {dims.map(d => (
                  <div key={d.key} className="mb-1.5">
                    <div className="flex justify-between text-[11px] mb-0.5" style={{ color: 'var(--text-secondary)' }}><span>{d.label}</span><span>{Math.round(d.v)}</span></div>
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
                      <div className="h-full rounded-full" style={{ width: `${d.v}%`, background: d.v >= 60 ? UP : d.v >= 40 ? '#EF9F27' : DOWN }} />
                    </div>
                  </div>
                ))}
                <div className="text-center mt-2">
                  <div className="text-3xl font-bold" style={{ color: 'var(--accent-blue)' }}>{composite ?? '—'}</div>
                  <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>综合评分 / 100</div>
                </div>
              </>
            ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>—</div>}
          </div>

          {/* 板块关联 */}
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>板块关联</div>
            {sector ? (
              <div className="space-y-1.5 text-xs">
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>所属板块</span><span style={{ color: 'var(--text-primary)' }}>{sector.sector || '—'}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>板块净流入(7日)</span><span style={{ color: (sector.net_flow || 0) >= 0 ? UP : DOWN }}>{fmtMoney(sector.net_flow)}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>板块均涨</span><span style={{ color: (sector.avg_chg || 0) >= 0 ? UP : DOWN }}>{sector.avg_chg != null ? `${sector.avg_chg}%` : '—'}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>涨停数</span><span>{sector.limit_up_count ?? '—'}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>龙头股</span><span style={{ color: 'var(--text-primary)' }}>{sector.leader_stock || '—'}</span></div>
                {rotation?.rotation_signal && (
                  <div className="mt-1.5 rounded-lg p-1.5 text-center text-[11px] font-bold" style={{ background: `${rotation.rotation_color}18`, color: rotation.rotation_color, border: `1px solid ${rotation.rotation_color}40` }}>{rotation.rotation_icon} {rotation.rotation_signal}</div>
                )}
                {related.length > 0 && (
                  <div className="pt-1.5" style={{ borderTop: '1px solid var(--border-color)' }}>
                    <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>同板块标的</div>
                    {related.map(r => (
                      <button key={r.code} onClick={() => changeCode(r.code)}
                        className="w-full flex items-center justify-between py-0.5 cursor-pointer rounded hover:opacity-80"
                        style={{ background: 'transparent', border: 'none', textAlign: 'left', padding: '0' }}>
                        <span className="truncate max-w-[90px]" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                        <span className="text-[11px] font-bold tabular-nums" style={{ color: r.chg == null ? 'var(--text-muted)' : r.chg >= 0 ? UP : DOWN }}>{r.chg != null ? `${r.chg}%` : '—'}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>—</div>}
          </div>

          {/* 我的持仓 */}
          {myPos && (
            <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>我的持仓</div>
              <div className="space-y-1 text-xs">
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>数量</span><span style={{ color: 'var(--text-primary)' }}>{myPos.count} 股</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>持仓盈亏</span><span style={{ color: (myPos.profit || 0) >= 0 ? UP : DOWN }}>{fmtMoney(myPos.profit)}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>市值</span><span style={{ color: 'var(--text-primary)' }}>{fmtMoney(myPos.value)}</span></div>
                <div className="flex justify-between"><span style={{ color: 'var(--text-muted)' }}>成本</span><span style={{ color: 'var(--text-primary)' }}>{myPos.costPrice != null ? myPos.costPrice.toFixed(2) : '—'}</span></div>
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="text-[10px] text-right" style={{ color: 'var(--text-muted)' }}>个股分析（专属研究终端）· 行情/技术/资金/K线/策略/F10/AI/新闻公告 全部来自后端接口 · 数据日期 {dash?.date || '—'}</div>
      </div>
    </div>
  );
}

// 盘中实时数据展示（5秒刷新）
function IntradayLive({ data }) {
  const pct = data.pct_chg;
  const isUp = pct == null ? null : pct >= 0;
  const pctColor = isUp === null ? 'var(--text-secondary)' : isUp ? UP : DOWN;
  const activeRatio = data.large_order_active_ratio || 0;
  const ratioColor = activeRatio > 60 ? UP : activeRatio > 40 ? '#EF9F27' : DOWN;
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-bold" style={{ color: pctColor }}>
          {data.current_price?.toFixed(2) || '—'}
        </span>
        <span className="text-base font-semibold" style={{ color: pctColor }}>
          {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}
        </span>
        {data.last_close > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>昨收 {data.last_close.toFixed(2)}</span>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 text-xs">
        <Metric label="换手率" value={data.turnover_rate ? `${data.turnover_rate.toFixed(2)}%` : '—'} />
        <Metric label="主力净流入" value={data.main_force_inflow ? `${(data.main_force_inflow / 10000).toFixed(0)}万` : '—'} />
        <Metric label="成交量" value={data.volume ? `${(data.volume / 10000).toFixed(0)}万手` : '—'} />
      </div>
      <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>大单主动买入比</span>
          <span className="text-sm font-bold" style={{ color: ratioColor }}>{activeRatio.toFixed(1)}%</span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.2)' }}>
          <div className="h-full transition-all" style={{ width: `${activeRatio}%`, background: ratioColor }} />
        </div>
        <div className="flex items-center justify-between mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          <span>近3秒买 {data.large_buy_count_3s} / 卖 {data.large_sell_count_3s}</span>
          <span>千单/分 {data.thousand_order_count_per_min || 0}</span>
        </div>
      </div>
      {data.support_level_eval && (
        <div className="text-xs px-2 py-1.5 rounded" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
          {data.support_level_eval}
        </div>
      )}
      {data.bid_price_1 > 0 && (
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          <div className="px-2 py-1 rounded" style={{ background: 'rgba(216,80,74,0.08)' }}>
            <span style={{ color: UP }}>买一 {data.bid_price_1?.toFixed(2)}</span>
            <span className="ml-1" style={{ color: 'var(--text-muted)' }}>{data.bid_vol_1 || 0}手</span>
          </div>
          <div className="px-2 py-1 rounded" style={{ background: 'rgba(59,154,46,0.08)' }}>
            <span style={{ color: DOWN }}>卖一 {data.ask_price_1?.toFixed(2)}</span>
            <span className="ml-1" style={{ color: 'var(--text-muted)' }}>{data.ask_vol_1 || 0}手</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded p-1.5" style={{ background: 'var(--bg-surface)' }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

// 盘后静态底牌展示（F10）
function PostMarketBase({ data }) {
  const score = data.quant_score;
  const scoreColor = score == null ? '#6b7280' : score >= 80 ? UP : score >= 60 ? '#EF9F27' : DOWN;
  return (
    <div className="space-y-2 text-xs">
      <div className="flex items-center gap-3">
        <span className="px-2 py-1 rounded font-bold" style={{ background: `${scoreColor}20`, color: scoreColor }}>
          游资分 {score ?? '—'}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>共振 {data.resonance_count} 位</span>
        <span style={{ color: 'var(--text-muted)' }}>净买 {data.total_net_buy_wan ? `${(data.total_net_buy_wan / 10000).toFixed(2)}亿` : '—'}</span>
      </div>
      {data.concept_sector && (
        <div className="text-xs">
          板块: <span style={{ color: 'var(--accent-blue)' }}>{data.concept_sector}</span>
          {data.sector_hot_money_count > 0 && (
            <span className="ml-2" style={{ color: 'var(--text-muted)' }}>同板块共振 {data.sector_hot_money_count}</span>
          )}
        </div>
      )}
      {data.yesterday_bosses && data.yesterday_bosses.length > 0 && (
        <div>
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>游资名单</div>
          <div className="space-y-1">
            {data.yesterday_bosses.slice(0, 6).map((b, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span style={{ color: 'var(--text-primary)' }}>{b.name}</span>
                <span className="flex items-center gap-1.5">
                  <span
                    className="px-1 rounded text-[10px]"
                    style={{
                      background: b.action === '新进' ? 'rgba(216,80,74,0.15)' : b.action === '砸盘' ? 'rgba(59,154,46,0.15)' : 'rgba(107,114,128,0.15)',
                      color: b.action === '新进' ? UP : b.action === '砸盘' ? DOWN : '#6b7280',
                    }}
                  >
                    {b.action}
                  </span>
                  <span style={{ color: b.net_buy_wan >= 0 ? UP : DOWN }}>
                    {b.net_buy_wan >= 0 ? '+' : ''}{(b.net_buy_wan / 10000).toFixed(2)}亿
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
