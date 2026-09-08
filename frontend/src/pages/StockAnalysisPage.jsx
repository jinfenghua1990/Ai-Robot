import { useMemo, useState, useEffect, useCallback, useRef } from 'react';
import { useSearchParams } from 'react-router-dom';
import KLineChart from '../components/charts/KLineChart';
import IntradayPanel from '../components/trading/IntradayPanel';
import StockActionButtons from '../components/trading/StockActionButtons';
import { apiFetch, formatApiError } from '../utils/request';
import PriceLevelsCard from '../components/PriceLevelsCard';
import { useTrading } from '../context/tradingContextCore';
import { POLL_INTERVAL, isMarketOpenNow } from '../utils/constants';
import { fmtPct2, fmtAmount, toFiniteNumber } from '../utils/format';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import USStockAnalysis from '../components/us/USStockAnalysis';

const UP = UP_COLOR;
const DOWN = DOWN_COLOR;

const fmtFixed = (value, digits = 2) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : n.toFixed(digits);
};
const fmtScaled = (value, divisor, digits = 2) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : fmtFixed(n / divisor, digits);
};

const TABS = [
  { key: 'bs', label: 'B/S区间', id: 'sec-bs' },
  { key: 'tech', label: '技术', id: 'sec-tech' },
  { key: 'levels', label: '关键位', id: 'sec-levels' },
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



const DIM_LABELS = {
  trend_strength: '趋势强度', capital_momentum: '资金动能', sector_resonance: '板块共振',
  volume_health: '量能健康', volatility_health: '波动健康', relative_strength: '相对强度',
  drawdown_status: '回撤状态', institution_signal: '机构信号',
};

// 评分维度 → 左侧模块锚点映射（点击右侧评分项可跳转到左侧对应模块）
const DIM_TO_SECTION = {
  trend_strength: 'sec-tech',
  capital_momentum: 'sec-capital',
  sector_resonance: 'sec-capital',
  volume_health: 'sec-tech',
  volatility_health: 'sec-tech',
  relative_strength: 'sec-capital',
  drawdown_status: 'sec-bs',
  institution_signal: 'sec-f10',
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
  // 美股 ticker 以字母开头（如 AAPL），A 股为 6 位数字；美股走专用分析视图
  const isUS = /^[A-Za-z]/.test(code);
  const { positions } = useTrading();
  const [dash, setDash] = useState(null);
  const [dashboardError, setDashboardError] = useState('');
  const [backfilling, setBackfilling] = useState(false);
  const [quote, setQuote] = useState(null);
  const [peers, setPeers] = useState(null);
  const [bs, setBs] = useState(null); // bs-signals（技术指标回退）
  const [stockNews, setStockNews] = useState({ news: [], announcements: [] }); // 真实个股新闻/公告（东财）
  const [newsTab, setNewsTab] = useState('news');
  const [firstReady, setFirstReady] = useState(false); // 首次数据就绪后才退出全屏占位，切换个股时左侧栏不再被 loading 吞掉
  const [activeTab, setActiveTab] = useState('bs');
  // 左侧栏视图：watch=自选池 / pos=我的持仓（顶部通栏 tab 切换）
  const [leftTab, setLeftTab] = useState('watch');

  // 盘中实时（super_panel 实时段，5秒轮询）
  const [superPanel, setSuperPanel] = useState(null);   // 静态段（盘后底牌/F10）
  const [realtimeData, setRealtimeData] = useState(null);
  const [livePrice, setLivePrice] = useState(null); // 实时最新价（驱动蜡烛图当日K跳动）
  const [liveSeries, setLiveSeries] = useState(null); // 当日实时价序列（驱动蜡烛图实时价曲线）
  // 策略标签
  const [strategyData, setStrategyData] = useState(null);
  const [strategyLoading, setStrategyLoading] = useState(false);
  const [rescanning, setRescanning] = useState(false);
  // 自动交易（真实状态）
  const [autoGlobal, setAutoGlobal] = useState(null);
  const [stockAutoCfg, setStockAutoCfg] = useState(null);
  const [autoBusy, setAutoBusy] = useState(false);
  // AI 分析
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiStats, setAiStats] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiLoaded, setAiLoaded] = useState(false);
  const [priceLevelPlan, setPriceLevelPlan] = useState(null);
  const detailRef = useRef(null);
  const activeCodeRef = useRef(code);

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
    activeCodeRef.current = code;
    let cancelled = false;
    // 切换股票时重置新模块状态，避免旧数据串台
    setDash(null);
    setDashboardError('');
    setQuote(null);
    setBs(null);
    setStockAutoCfg(null);
    setSuperPanel(null);
    setRealtimeData(null);
    setLivePrice(null);
    setLiveSeries(null);
    setStrategyData(null);
    setStrategyLoading(true);
    setAiLoaded(false);
    setAiAnalysis(null);
    setAiStats(null);
    setPriceLevelPlan(null);
    setStockNews({ news: [], announcements: [] });
    // 首屏只等待仪表盘；报价、B/S 和资讯各自降级，不能因一项慢查询让整页白屏。
    // 每项只请求一次，避免慢接口的自动重试占满后端连接池。
    apiFetch(`/api/stock-dashboard/${base}?refresh=true`, {}, 8000, 0)
      .then((dRes) => {
        if (cancelled) return;
        if (dRes.ok) {
          if (dRes.data?.error) {
            setDashboardError(formatApiError(dRes.data.error, '数据库日度分析暂不可用'));
          } else {
            setDash(dRes.data);
          }
          const asOf = dRes.data?.data_as_of || dRes.data?.date;
          const asOfParam = asOf ? `&as_of=${encodeURIComponent(asOf)}` : '';
          apiFetch(`/api/trading/bs-signals?stockCode=${base}&datalen=60${asOfParam}`, {}, 8000, 0)
            .then((bsRes) => { if (!cancelled && bsRes.ok) setBs(bsRes.data); });
        }
      })
      .catch(() => { if (!cancelled) setDashboardError('数据库日度分析请求超时'); })
      .finally(() => { if (!cancelled) setFirstReady(true); });
    apiFetch(`/api/trading/quote?code=${base}`, {}, 3000, 0)
      .then((qRes) => { if (!cancelled && qRes.ok) setQuote(qRes.data); });
    apiFetch(`/api/stock/${base}/news?limit=8`, {}, 5000, 0)
      .then((nRes) => { if (!cancelled && nRes.ok) setStockNews(nRes.data || { news: [], announcements: [] }); });
    return () => { cancelled = true; };
  }, [code]);

  // 自选池只加载一次（与当前查看个股无关；若随 code 重拉会导致左侧列表重排/跳动）
  const watchlistLoaded = useRef(false);
  useEffect(() => {
    if (watchlistLoaded.current) return;
    watchlistLoaded.current = true;
    apiFetch('/api/watchlist').then(wRes => { if (wRes.ok) setPeers(wRes.data); }).catch(() => {});
  }, []);

  // 策略标签（/api/stock-strategies）+ 盘中每3分钟静默轮询，保证盘后/手动扫描结果即时反映
  useEffect(() => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    let cancelled = false;
    const loadStrategy = async (silent = false) => {
      try {
        const { ok, data } = await apiFetch(`/api/stock-strategies/${base}`);
        if (cancelled) return;
        if (ok) setStrategyData(data);
      } catch (e) { console.error('[strategy]', e); }
      finally { if (!silent && !cancelled) setStrategyLoading(false); }
    };
    setStrategyLoading(true);
    loadStrategy();
    const timer = setInterval(() => loadStrategy(true), 180000); // 每3分钟静默刷新
    return () => { cancelled = true; clearInterval(timer); };
  }, [code]);

  // 手动重新扫描（触发全市场策略扫描，立即基于最新行情重算）
  const handleRescan = async () => {
    const base = code.replace(/\D/g, '');
    if (!base || rescanning) return;
    setRescanning(true);
    try {
      await apiFetch('/api/strategy-scan/trigger', { method: 'POST' }, 180000);
      const { ok, data } = await apiFetch(`/api/stock-strategies/${base}`);
      if (ok) setStrategyData(data);
    } catch (e) { console.error('[rescan]', e); }
    finally { setRescanning(false); }
  };

  // 自动交易状态（全局总开关 + 本股配置）
  useEffect(() => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    let cancelled = false;
    (async () => {
      try {
        const [gRes, sRes] = await Promise.all([
          apiFetch('/api/auto-trade/global'),
          apiFetch(`/api/auto-trade/stocks/${base}/config`),
        ]);
        if (cancelled) return;
        if (gRes.ok) setAutoGlobal(gRes.data);
        if (sRes.ok) setStockAutoCfg(sRes.data);
      } catch (e) { console.error('[autotrade]', e); }
    })();
    return () => { cancelled = true; };
  }, [code]);

  // 自动交易状态派生
  const autoCfg = stockAutoCfg || {};
  const autoIsOn = !!(autoCfg.status && autoCfg.status !== 'OFF' && autoCfg.mode && autoCfg.mode !== 'off');
  const autoModeLabel = (m) => m === 'full_auto' ? '全自动' : m === 'risk_only' ? '风控托管' : (m && m !== 'off') ? m : '未设置';

  // 切换本股自动交易开关（开启失败时明确提示缺失配置）
  const toggleAutoTrade = async () => {
    const base = code.replace(/\D/g, '');
    if (!base || autoBusy) return;
    setAutoBusy(true);
    try {
      if (autoIsOn) {
        await apiFetch(`/api/auto-trade/stocks/${base}/disable`, { method: 'POST' }, 15000);
      } else {
        const res = await apiFetch(`/api/auto-trade/stocks/${base}/enable`, { method: 'POST' }, 15000);
        if (res.ok && res.data && res.data.ok === false) {
          window.alert(`开启自动交易失败，缺少以下配置：\n- ${(res.data.missing || []).join('\n- ')}\n\n请先补齐配置后再开启。`);
        } else if (!res.ok) {
          window.alert(`开启失败：${res.error || '未知错误'}`);
        }
      }
      const [gRes, sRes] = await Promise.all([
        apiFetch('/api/auto-trade/global'),
        apiFetch(`/api/auto-trade/stocks/${base}/config`),
      ]);
      if (gRes.ok) setAutoGlobal(gRes.data);
      if (sRes.ok) setStockAutoCfg(sRes.data);
    } catch (e) { console.error('[autotrade]', e); }
    finally { setAutoBusy(false); }
  };

  // 重新拉取本股仪表盘（精确特征 backfill 完成后刷新）
  const refreshDash = async () => {
    const base = code.replace(/\D/g, '');
    if (!base) return;
    try {
      const { ok, data } = await apiFetch(`/api/stock-dashboard/${base}?refresh=true`);
      if (ok && data && !data.error) setDash(data);
    } catch (e) { console.error('[dashboard] refresh', e); }
  };

  // 本股走 kline_fallback 时，后台补算精确特征（写 StockFeaturesDaily），稍后刷新落成精确
  const backfillPreciseFeatures = async () => {
    const base = code.replace(/\D/g, '');
    if (!base || backfilling) return;
    setBackfilling(true);
    try {
      const r = await apiFetch(`/api/market-state/refresh-codes?codes=${base}`, { method: 'POST' }, 30000);
      if (!r.ok || (r.data && r.data.success === false)) {
        window.alert(r.data?.message || '补算失败，请稍后再试');
        return;
      }
      // 等待后台对本股写库后，重新拉取精确特征
      setTimeout(() => { refreshDash(); setBackfilling(false); }, 2500);
    } catch (e) {
      console.error('[dashboard] backfill', e);
      window.alert('补算失败，请稍后再试');
      setBackfilling(false);
    }
  };

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
      if (ok && activeCodeRef.current.replace(/\D/g, '') === base) setRealtimeData(data);
    } catch { /* silent */ }
  }, [code]);

  useEffect(() => {
    fetchRealtime();
    const t = setInterval(() => { if (!document.hidden) fetchRealtime(); }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [fetchRealtime]);

  // 实时最新价（intraday 接口的 stockQuote.price，5秒轮询，驱动蜡烛图当日K跳动）
  const fetchLivePrice = useCallback(async () => {
    const base = code.replace(/\D/g, '');
    if (!base || !isMarketOpenNow()) return;
    try {
      const { ok, data } = await apiFetch(`/api/trading/intraday/${base}`);
      if (ok && activeCodeRef.current.replace(/\D/g, '') === base && data?.stockQuote?.price != null) {
        setLivePrice(data.stockQuote.price);
        if (Array.isArray(data.intraday) && data.intraday.length) {
          setLiveSeries(data.intraday.map(k => k.close));
        }
      }
    } catch { /* silent */ }
  }, [code]);

  useEffect(() => {
    if (!isMarketOpenNow()) {
      setLivePrice(null);
      setLiveSeries(null);
      return undefined;
    }
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
      if (activeCodeRef.current.replace(/\D/g, '') === base) {
        setAiAnalysis(a.ok ? a.data : null);
        setAiStats(s.ok ? s.data : null);
      }
    } catch { /* silent */ }
    if (activeCodeRef.current.replace(/\D/g, '') === base) {
      setAiLoading(false);
      setAiLoaded(true);
    }
  }, [code, aiLoaded]);

  useEffect(() => {
    if (activeTab === 'ai') loadAI();
  }, [activeTab, loadAI]);

  // tab 随滚动高亮（scroll-spy）
  useEffect(() => {
    if (!firstReady) return undefined;
    const scrollRoot = detailRef.current?.closest('main') || window;
    const onScroll = () => {
      const rootTop = scrollRoot === window ? 0 : scrollRoot.getBoundingClientRect().top;
      const current = TABS
        .map(t => ({ ...t, el: document.getElementById(t.id) }))
        .filter(t => t.el && !t.el.closest('.stock-analysis-context-scroll'))
        .map(t => ({ ...t, top: t.el.getBoundingClientRect().top }))
        .filter(t => t.top <= rootTop + 126)
        .sort((a, b) => b.top - a.top)[0];
      const key = current?.key;
      if (key) setActiveTab(prev => (prev === key ? prev : key));
    };
    scrollRoot.addEventListener('scroll', onScroll, { passive: true });
    onScroll();
    return () => scrollRoot.removeEventListener('scroll', onScroll);
  }, [firstReady]);

  const name = dash?.quote?.name || quote?.name || (dash?.sector_flow?.sector || code);
  const price = toFiniteNumber(quote?.price ?? dash?.quote?.price);
  const chg = toFiniteNumber(quote?.changePct ?? dash?.quote?.change);
  const up = chg == null ? null : chg >= 0;
  const chgColor = up == null ? 'var(--text-muted)' : up ? UP : DOWN;

  // 综合判断与 8 维评分只使用同一收盘日数据库明细；盘中快照仅在分时模块展示。
  const dayMainNet = dash?.institution_flow?.main_net ?? null;

  const dims = useMemo(() => {
    if (!dash) return [];
    return Object.keys(DIM_LABELS).map(k => ({ key: k, label: DIM_LABELS[k], v: toFiniteNumber(dash[k]) }));
  }, [dash]);
  const composite = toFiniteNumber(dash?.overall_score);

  // 技术指标：优先 dashboard，回退 bs-signals 实时计算
  const tech = useMemo(() => {
    const ind = bs?.indicators || {};
    const klines = bs?.klines || [];
    const last = arr => (Array.isArray(arr) && arr.length ? arr[arr.length - 1] : null);
    const macdDif = toFiniteNumber(dash?.technical_indicators?.macd?.dif ?? last(ind.dif));
    const macdDea = toFiniteNumber(dash?.technical_indicators?.macd?.dea ?? last(ind.dea));
    const macdHist = toFiniteNumber(dash?.technical_indicators?.macd?.macd ?? last(ind.macd));
    const kdjK = toFiniteNumber(dash?.technical_indicators?.kdj?.k ?? last(ind.kdj_k));
    const kdjD = toFiniteNumber(dash?.technical_indicators?.kdj?.d ?? last(ind.kdj_d));
    const kdjJ = toFiniteNumber(dash?.technical_indicators?.kdj?.j ?? last(ind.kdj_j));
    const rsi = toFiniteNumber(dash?.features?.rsi_14 ?? calcRSI(klines.map(k => k.close)));
    const volRatio = toFiniteNumber(dash?.features?.volume_ratio);
    const closeVsMa20 = toFiniteNumber(dash?.features?.close_vs_ma20);
    // MA20 斜率：优先后端 features（与自选列表一致），回退前端从 klines 算
    const storedMa20Slope = toFiniteNumber(dash?.features?.ma20_slope);
    // 数据库存的是小数变化率（0.02 = +2%）；前端展示、阈值和回退计算统一使用百分数。
    let ma20Slope = storedMa20Slope == null ? null : storedMa20Slope * 100;
    if (ma20Slope == null) {
      const closes = (bs?.klines || []).map(k => k?.close).filter(c => typeof c === 'number');
      if (closes.length >= 26) {
        const maAt = (i) => { if (i < 19) return null; let s = 0; for (let j = i - 19; j <= i; j++) s += closes[j]; return s / 20; };
        const mNow = maAt(closes.length - 1), mPrev = maAt(closes.length - 7);
        if (mNow != null && mPrev) ma20Slope = (mNow - mPrev) / mPrev * 100;
      }
    }
    const mCross = macdDif != null && macdDea != null ? (macdDif >= macdDea ? '多头' : '空头') : '';
    const kCross = kdjK != null && kdjD != null ? (kdjK >= kdjD ? '多头' : '空头') : '';
    return { macdDif, macdDea, macdHist, kdjK, kdjD, kdjJ, rsi, volRatio, closeVsMa20, ma20Slope, mCross, kCross };
  }, [dash, bs]);

  // 个股诊断结论（综合全页数据，纯前端合成，不新增接口）
  const verdict = useMemo(() => {
    if (!dash) return null;
    if (composite == null) {
      const missing = (dash?.missing_dimensions || []).map(key => DIM_LABELS[key] || key);
      return {
        state: '数据不足', stateColor: '#888780', stateBg: 'rgba(136,135,128,0.12)',
        score: null,
        summary: `8维综合评分未生成${missing.length ? `，缺少：${missing.join('、')}` : ''}；关键价位仍可独立提供防守与进攻参考。`,
        action: dash?.action_label, actionColor: dash?.action_color,
        techBull: false, techBear: false, fundIn: null,
      };
    }
    const score = composite;
    const techBull = tech.mCross === '多头' && tech.kCross === '多头';
    const techBear = tech.mCross === '空头' && tech.kCross === '空头';
    const fundIn = dayMainNet == null ? null : dayMainNet >= 0;
    // 状态阈值与后端综合分/建议同口径（55=观望带≥，40=减仓下限，<40=远离），避免“评分高却判断弱”的割裂。
    let state, stateColor, stateBg;
    if (score >= 55 && (techBull || fundIn)) { state = '偏强'; stateColor = UP; stateBg = 'rgba(216,80,74,0.12)'; }
    else if (score < 40 || (techBear && fundIn === false)) { state = '偏弱'; stateColor = DOWN; stateBg = 'rgba(59,154,46,0.12)'; }
    else { state = '震荡'; stateColor = '#888780'; stateBg = 'rgba(136,135,128,0.12)'; }
    const trendV = dims.find(d => d.key === 'trend_strength')?.v;
    const trendWord = trendV == null ? '趋势数据不足' : trendV >= 60 ? '趋势强' : trendV >= 40 ? '趋势中等' : '趋势弱';
    const fundWord = fundIn == null ? '资金数据不足' : fundIn ? '资金净流入' : '资金净流出';
    const rsiWord = tech.rsi == null ? '—' : tech.rsi >= 70 ? 'RSI超买' : tech.rsi <= 30 ? 'RSI超卖' : `RSI${fmtFixed(tech.rsi, 0)}`;
    const summary = `综合评分 ${score}｜${trendWord}｜${fundWord}｜MACD${tech.mCross}／KDJ${tech.kCross}｜${rsiWord}。操作建议：${dash?.action_label || '观望'}`;
    return { state, stateColor, stateBg, score, summary, action: dash?.action_label, actionColor: dash?.action_color, techBull, techBear, fundIn };
  }, [dash, tech, dayMainNet, composite, dims]);

  const cum = dash?.main_net_cumulative?.stock || {};
  const flow1d = toFiniteNumber(cum[1]);
  const flow3d = toFiniteNumber(cum[3]);
  const flow5d = toFiniteNumber(cum[5]);
  const priceLevelSignalContext = useMemo(() => ({
    overallState: verdict?.state,
    actionLabel: dash?.action_label,
    macd: tech.mCross,
    kdj: tech.kCross,
    kdjK: tech.kdjK,
    kdjJ: tech.kdjJ,
    closeVsMa20: tech.closeVsMa20,
    ma20Slope: tech.ma20Slope,
    rsi: tech.rsi,
    volumeRatio: tech.volRatio,
    flow1d,
    flow3d,
    flow5d,
  }), [dash?.action_label, flow1d, flow3d, flow5d, tech.closeVsMa20, tech.kCross, tech.kdjJ, tech.kdjK, tech.mCross, tech.ma20Slope, tech.rsi, tech.volRatio, verdict?.state]);
  const fundDetailItems = [
    { label: '10日', value: cum[10] },
    { label: '20日', value: cum[20] },
    { label: '散户净流入', value: dash?.institution_flow?.retail_net },
    { label: '超大单净流入', value: dash?.institution_flow?.super_large_net },
    { label: '大单净流入', value: dash?.institution_flow?.large_net },
  ];

  const related = useMemo(() => {
    // 优先：全市场同板块（后端读 stock_flow 聚合，纯库）。带板块且非当前股。
    if (dash?.sector_peers?.length) {
      return dash.sector_peers
        .filter(p => p.code !== code.replace(/\D/g, ''))
        .map(p => ({ name: p.name, code: p.code, chg: toFiniteNumber(p.chg) }))
        .slice(0, 8);
    }
    // 回退：自选池内同板块
    if (!peers) return [];
    const flat = [];
    if (Array.isArray(peers.groups)) peers.groups.forEach(g => (g.stocks || []).forEach(s => flat.push(s)));
    else if (Array.isArray(peers.signals)) peers.signals.forEach(s => flat.push(s));
    const me = flat.find(s => (s.secCode || s.stock_code) === code);
    const grp = me?.sector || me?.group || '';
    if (!grp) return [];
    return flat.filter(s => (s.sector || s.group) === grp && (s.secCode || s.stock_code) !== code)
      .map(s => ({ name: s.secName || s.stock_name || s.name, code: s.secCode || s.stock_code, chg: toFiniteNumber(s.quote?.changePct ?? s.change_pct ?? s.chg) }))
      .sort((a, b) => (b.chg ?? -1e9) - (a.chg ?? -1e9))
      .slice(0, 8);
  }, [peers, code, dash]);

  // 左侧自选池列表（来自 /api/watchlist，随 code 切换自动高亮）
  const watchRows = useMemo(() => {
    if (!Array.isArray(peers?.signals)) return [];
    const seen = new Set();
    return peers.signals
      .map(s => ({
        name: s.secName || s.stock_name || s.name || s.secCode,
        code: String(s.secCode || '').replace(/\D/g, ''),
        chg: toFiniteNumber(s.quote?.changePct ?? s.change_pct ?? s.chg),
        sector: s.sector || null,
      }))
      .filter(r => r.code && !seen.has(r.code) && seen.add(r.code));
  }, [peers]);

  // 左侧持仓列表（来自 /api/trading/positions，随 code 切换自动高亮；按代码去重兑底）
  const posRows = useMemo(() => {
    const list = positions?.positions || (Array.isArray(positions) ? positions : []);
    const sectorByCode = new Map();
    if (Array.isArray(peers?.signals)) {
      peers.signals.forEach(s => {
        const c = String(s.secCode || '').replace(/\D/g, '');
        if (c && !sectorByCode.has(c)) sectorByCode.set(c, s.sector || s.group || null);
      });
    }
    const seen = new Set();
    return list
      .map(p => {
        const code = String(p.secCode || '').replace(/\D/g, '');
        return {
          name: p.secName || p.name || String(p.secCode || ''),
          code,
          count: p.count,
          profit: p.profit,
          value: p.value,
          sector: p.sector || sectorByCode.get(code) || null,
        };
      })
      .filter(r => r.code && !seen.has(r.code) && seen.add(r.code));
  }, [positions, peers]);

  // 左侧「板块」视图：按行业板块(sector) 分组，组头显示板块整体涨跌（自选池内均值）；peers 只加载一次，切换个股不跳动
  const sectorGroups = useMemo(() => {
    if (!Array.isArray(peers?.signals)) return [];
    const map = new Map();
    peers.signals.forEach(s => {
      const key = s.sector || s.group;          // 优先行业板块，回退自选分组
      if (!key) return;
      const c = String(s.secCode || '').replace(/\D/g, '');
      if (!c) return;
      if (!map.has(key)) map.set(key, { name: key, rows: [], sum: 0, n: 0 });
      const chg = toFiniteNumber(s.quote?.changePct ?? s.change_pct ?? s.chg);
      map.get(key).rows.push({ name: s.secName || s.stock_name || s.name || s.secCode, code: c, chg });
      if (chg != null) { map.get(key).sum += chg; map.get(key).n += 1; }
    });
    return Array.from(map.values())
      .map(g => ({ ...g, avgChg: g.n ? g.sum / g.n : null }))
      .sort((a, b) => b.rows.length - a.rows.length);
  }, [peers]);
  // 当前股票所属板块（用于左栏板块视图高亮/滚动）
  const activeSectorIdx = useMemo(() => sectorGroups.findIndex(g => g.rows.some(r => r.code === code)), [sectorGroups, code]);

  // 进入板块视图时，自动滚动并高亮当前股票所属板块（必须放在 activeSectorIdx 声明之后，否则渲染期访问依赖数组触发 TDZ 报错）
  useEffect(() => {
    if (leftTab !== 'sector' || activeSectorIdx < 0) return;
    const t = setTimeout(() => {
      const el = document.getElementById(`sg-${activeSectorIdx}`);
      if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 60);
    return () => clearTimeout(t);
  }, [leftTab, activeSectorIdx]);

  const sector = dash?.sector_flow;
  const rotation = dash?.sector_rotation;
  const dailyChg = toFiniteNumber(dash?.quote?.change);
  const indexChg = toFiniteNumber(dash?.index_chg);
  const sectorChg = toFiniteNumber(sector?.avg_chg);
  // sector_flow.net_flow 后端已统一返回元；fmtAmount 接受元。
  const sectorNetFlow = toFiniteNumber(sector?.net_flow);
  const realtimeSourceStatus = realtimeData?.source_health?.realtime;
  const realtimeIsLive = realtimeSourceStatus === 'live' || realtimeSourceStatus === 'ready';
  const realtimeIsClosed = realtimeSourceStatus === 'closed' || realtimeSourceStatus === 'closed_snapshot';
  const executionAdvice = priceLevelPlan?.decision?.short || null;
  const midTermLabel = tech.closeVsMa20 == null ? '中期数据不足' : tech.closeVsMa20 >= 0 ? '中期强' : '中期弱';
  const sectorTrendLabel = sectorChg == null ? '板块数据不足' : sectorChg >= 0 ? '板块升温' : '板块走弱';
  const validDimensionCount = dims.filter(item => item.v != null).length;
  const contextCards = [
    {
      title: '综合判断',
      items: [
        { label: '状态', value: verdict?.state || '数据不足', color: verdict?.stateColor },
        { label: '评分', value: composite ?? '—', color: composite == null ? null : 'var(--accent-blue)' },
        { label: '建议', value: dash?.action_label || '数据不足', color: dash?.action_color },
      ],
    },
    {
      title: '执行状态',
      items: [
        ...(myPos ? [
          { label: '数量', value: `${myPos.count}股` },
          { label: '成本', value: fmtFixed(myPos.costPrice, 2) },
          { label: '市值', value: fmtAmount(myPos.value) },
          { label: '盈亏', value: fmtAmount(myPos.profit), color: myPos.profit == null ? null : myPos.profit >= 0 ? UP : DOWN },
        ] : [
          { label: '仓位', value: '空仓' },
        ]),
        { label: priceLevelPlan?.rrLabel || (myPos ? '持仓盈亏比' : '试仓盈亏比'), value: priceLevelPlan?.rr == null ? '—' : `1:${fmtFixed(priceLevelPlan.rr, 1)}` },
      ],
      note: executionAdvice,
    },
    {
      title: '趋势验证',
      items: [
        { label: 'MACD', value: tech.mCross || '—', color: tech.mCross ? (tech.mCross === '多头' ? UP : DOWN) : null },
        { label: 'KDJ', value: tech.kCross || '—', color: tech.kCross ? (tech.kCross === '多头' ? UP : DOWN) : null },
        {
          label: 'MA20',
          value: tech.closeVsMa20 == null ? '—' : tech.closeVsMa20 >= 0 ? '站上' : '跌破',
          color: tech.closeVsMa20 == null ? null : tech.closeVsMa20 >= 0 ? UP : DOWN,
        },
      ],
    },
    {
      title: '个股资金',
      items: [1, 3, 5].map(period => {
        const value = toFiniteNumber(cum[period]);
        return { label: `${period}日`, value: fmtAmount(value), color: value == null ? null : value >= 0 ? UP : DOWN };
      }),
    },
    {
      title: '强弱对比',
      items: [
        { label: '个股（收盘）', value: dailyChg != null ? fmtPct2(dailyChg) : '—', color: dailyChg == null ? null : dailyChg >= 0 ? UP : DOWN },
        { label: sector?.sector || '板块', value: sectorChg != null ? fmtPct2(sectorChg) : '—', color: sectorChg == null ? null : sectorChg >= 0 ? UP : DOWN },
        { label: '沪深300', value: indexChg != null ? fmtPct2(indexChg) : '—', color: indexChg == null ? null : indexChg >= 0 ? UP : DOWN },
      ],
    },
    {
      title: `板块资金 · ${sector?.sector || '—'}`,
      items: [
        { label: '7日净流(近7交易日)', value: fmtAmount(sectorNetFlow), color: sectorNetFlow == null ? null : sectorNetFlow >= 0 ? UP : DOWN },
        { label: '板块涨跌', value: sectorChg != null ? fmtPct2(sectorChg) : '—', color: sectorChg == null ? null : sectorChg >= 0 ? UP : DOWN },
        { label: '轮动(近10交易日)', value: rotation?.rotation_signal || '—', color: rotation?.rotation_color, wrap: true },
      ],
    },
    {
      title: '关键价位',
      items: [
        { label: myPos ? '清仓线' : '第二支撑', value: fmtFixed(myPos ? (priceLevelPlan?.s2 ?? priceLevelPlan?.s1) : priceLevelPlan?.s2, 2), color: (myPos ? (priceLevelPlan?.s2 ?? priceLevelPlan?.s1) : priceLevelPlan?.s2) == null ? null : DOWN },
        { label: myPos ? '第一防守' : '试仓失效', value: fmtFixed(priceLevelPlan?.s1, 2), color: priceLevelPlan?.s1 == null ? null : DOWN },
        { label: '现价', value: fmtFixed(price, 2), color: price == null ? null : chgColor },
        { label: '第一阻力', value: fmtFixed(priceLevelPlan?.r1, 2), color: priceLevelPlan?.r1 == null ? null : UP },
        { label: '突破确认', value: fmtFixed(priceLevelPlan?.r2, 2), color: priceLevelPlan?.r2 == null ? null : UP },
      ],
    },
  ];

  const scrollToSection = useCallback((sectionId) => {
    const el = document.getElementById(sectionId);
    if (!el) return;
    const tab = TABS.find(item => item.id === sectionId);
    if (tab) setActiveTab(tab.key);
    const scroller = el.closest('.stock-analysis-context-scroll');
    if (scroller) {
      const targetTop = el.getBoundingClientRect().top - scroller.getBoundingClientRect().top + scroller.scrollTop - 8;
      scroller.scrollTo({ top: targetTop, behavior: 'smooth' });
      return;
    }
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }, []);

  // 美股：走专用分析视图（复用 us-quant 接口），避免落入 A 股接口导致卡死/报错
  if (isUS) return <USStockAnalysis code={code} />;

  if (!firstReady) return <div className="p-6 text-sm" style={{ color: 'var(--text-muted)', background: 'var(--bg-surface)', minHeight: '100vh' }}>加载 {code} 真实分析数据…</div>;

  return (
    <div
      className="stock-analysis-page"
      style={{
        width: '100%',
        maxWidth: 'none',
        margin: 0,
        padding: '8px clamp(8px, 1vw, 16px) 16px',
        minHeight: '100vh',
        background: 'var(--bg-surface)',
      }}
    >
      {/* 全宽工作区：侧栏与详情共用内容宽度，不再套一层居中卡片 */}
      <div className="stock-analysis-layout flex items-start" style={{ background: 'transparent' }}>
      {/* ─── 左侧栏：自选池 / 我的持仓（顶部通栏 tab 切换） ─── */}
      {!embedded && (
        <div className="stock-analysis-sidebar custom-scroll" style={{ width: 'clamp(188px, 17vw, 240px)', flex: '0 0 clamp(188px, 17vw, 240px)', position: 'sticky', top: 0, maxHeight: 'calc(100vh - 48px)', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3, padding: '8px clamp(6px, 0.7vw, 12px) 10px', background: 'transparent', borderRight: '1px solid var(--border-color)' }}>
          <div>
            <div className="flex items-center justify-between px-1 py-0.5 mb-2">
              <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>{leftTab === 'pos' ? '💼 我的持仓' : leftTab === 'watch' ? '⭐ 自选池' : '🗂 板块'}</span>
              <span className="text-[10px] shrink-0 px-1.5 py-0.5 rounded" style={{ color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>{leftTab === 'sector' ? `${sectorGroups.reduce((a, g) => a + g.rows.length, 0)} 只` : (leftTab === 'pos' ? posRows : watchRows).length} 只</span>
            </div>
            {/* 视图切换：modern segmented control */}
            <div className="flex items-center rounded-lg p-0.5 mb-2" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
              {[
                { key: 'pos', label: '持仓' },
                { key: 'watch', label: '自选' },
                { key: 'sector', label: '板块' },
              ].map(t => (
                <button key={t.key} type="button" onClick={() => setLeftTab(t.key)}
                  className="flex-1 px-1 py-1 text-[10px] font-medium cursor-pointer rounded-md transition-all"
                  style={{ background: leftTab === t.key ? 'var(--bg-card)' : 'transparent', color: leftTab === t.key ? 'var(--accent-blue)' : 'var(--text-secondary)', border: leftTab === t.key ? '1px solid var(--border-color)' : '1px solid transparent', boxShadow: leftTab === t.key ? '0 1px 2px rgba(15,23,42,0.04)' : 'none', fontWeight: leftTab === t.key ? 600 : 400 }}>{t.label}</button>
              ))}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              {leftTab === 'sector' ? (
                sectorGroups.length === 0 ? (
                  <div className="px-1 py-2 text-xs text-center" style={{ color: 'var(--text-muted)' }}>自选池暂无板块分组信息</div>
                ) : sectorGroups.map((g, i) => (
                  <div key={g.name} id={`sg-${i}`} style={{ display: 'flex', flexDirection: 'column', gap: 2, padding: i === activeSectorIdx ? '3px 4px' : 0, borderRadius: 8, background: i === activeSectorIdx ? 'rgba(55,138,221,0.04)' : 'transparent', border: '1px solid transparent' }}>
                    <div className="px-1 pt-1.5 pb-0.5 text-[10px] font-semibold flex items-center justify-between" style={{ color: i === activeSectorIdx ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
                      <span>{g.name} · {g.rows.length}</span>
                      <span style={{ color: (g.avgChg || 0) >= 0 ? UP : DOWN }}>{g.avgChg != null ? fmtPct2(g.avgChg) : ''}</span>
                    </div>
                    {g.rows.map(r => {
                      const active = r.code === code;
                      return (
                        <button key={`${g.name}-${r.code}`} type="button" onClick={() => changeCode(r.code)}
                          title={`${r.sector || '其他'} · ${r.name} ${r.code}`}
                          className="w-full flex items-center gap-1.5 cursor-pointer rounded-md px-2 py-1.5 text-left"
                          style={{
                            border: '1px solid transparent',
                            borderLeft: active ? '3px solid var(--accent-blue)' : '3px solid transparent',
                            background: active ? 'rgba(55,138,221,0.06)' : 'transparent',
                            transition: 'background 0.15s ease',
                          }}
                          onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                          onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}>
                          <span className="truncate text-[10px]" style={{ width: 54, color: 'var(--text-muted)' }} title={r.sector || '其他'}>{r.sector || '其他'}</span>
                          <span className="flex-1 min-w-0 truncate text-xs" style={{ color: active ? 'var(--accent-blue)' : 'var(--text-primary)', fontWeight: active ? 700 : 500 }}>{r.name} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>{r.code}</span></span>
                          <span className="text-[10.5px] font-semibold tabular-nums w-12 text-right" style={{ color: r.chg == null ? 'var(--text-muted)' : r.chg >= 0 ? UP : DOWN }}>{r.chg != null ? fmtPct2(r.chg) : '—'}</span>
                        </button>
                      );
                    })}
                  </div>
                ))
              ) : (leftTab === 'pos' ? posRows : watchRows).map(r => {
                const active = r.code === code;
                return (
                  <button key={r.code} type="button" onClick={() => changeCode(r.code)}
                    title={`${r.sector || '其他'} · ${r.name} ${r.code}`}
                    className="w-full flex items-center gap-1.5 cursor-pointer rounded-md px-2 py-1.5 text-left"
                    style={{
                      border: '1px solid transparent',
                      borderLeft: active ? '3px solid var(--accent-blue)' : '3px solid transparent',
                      background: active ? 'rgba(55,138,221,0.06)' : 'transparent',
                      transition: 'background 0.15s ease',
                    }}
                    onMouseEnter={e => { if (!active) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                    onMouseLeave={e => { if (!active) e.currentTarget.style.background = 'transparent'; }}>
                    <span className="truncate text-[10px]" style={{ width: 54, color: 'var(--text-muted)' }} title={r.sector || '其他'}>{r.sector || '其他'}</span>
                    <span className="flex-1 min-w-0 truncate text-xs" style={{ color: active ? 'var(--accent-blue)' : 'var(--text-primary)', fontWeight: active ? 700 : 500 }}>{r.name} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>{r.code}</span></span>
                    {leftTab === 'pos' ? (
                      <span className="text-[10.5px] font-semibold tabular-nums w-14 text-right" style={{ color: r.profit == null ? 'var(--text-muted)' : r.profit >= 0 ? UP : DOWN }}>{r.profit != null ? `${r.profit >= 0 ? '+' : ''}${fmtAmount(r.profit)}` : '—'}</span>
                    ) : (
                      <span className="text-[10.5px] font-semibold tabular-nums w-12 text-right" style={{ color: r.chg == null ? 'var(--text-muted)' : r.chg >= 0 ? UP : DOWN }}>{r.chg != null ? fmtPct2(r.chg) : '—'}</span>
                    )}
                  </button>
                );
              })}
              {leftTab !== 'sector' && (leftTab === 'pos' ? posRows : watchRows).length === 0 && (
                <div className="px-1 py-2 text-xs text-center" style={{ color: 'var(--text-muted)' }}>{leftTab === 'pos' ? '暂无持仓' : '自选池为空，请先添加'}</div>
              )}
            </div>
          </div>
        </div>
      )}
      {/* ─── 右侧主区（个股分析详情） ─── */}
      <div ref={detailRef} className="stock-analysis-detail flex-1 min-w-0 p-2.5" style={{ background: 'transparent' }}>
      <div className="space-y-3">
      {/* 固定决策基准：下拉后仍保留个股、板块、大盘与关键价位对比 */}
      <div className="stock-analysis-sticky-dock sticky top-0 z-30 rounded-xl px-2.5 pt-2 pb-1.5"
        style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)', boxShadow: '0 6px 18px rgba(15,23,42,0.12)' }}>
        <div className="flex items-center justify-between gap-2 min-w-0">
          <div className="flex items-center gap-2 min-w-0 flex-wrap">
            <input value={code} onChange={(e) => changeCode(e.target.value)}
              placeholder="代码" className="w-[72px] px-2 py-1 rounded-lg text-xs font-bold outline-none"
              style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
            <span className="text-base font-bold whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>{name}</span>
            <div className="flex items-baseline gap-1.5 whitespace-nowrap">
              <span className="text-xl font-bold tabular-nums" style={{ color: chgColor }}>{fmtFixed(price, 2)}</span>
              <span className="text-xs font-semibold tabular-nums" style={{ color: chgColor }}>{chg != null ? `${fmtPct2(chg)} ${up ? '▲' : '▼'}` : '—'}</span>
            </div>
            {sector?.sector && (
              <button type="button" onClick={() => scrollToSection('sec-sector')}
                className="px-2 py-0.5 rounded-full text-[10px] font-medium cursor-pointer whitespace-nowrap"
                style={{ background: sectorChg == null ? 'rgba(136,135,128,0.1)' : sectorChg >= 0 ? 'rgba(216,80,74,0.1)' : 'rgba(59,154,46,0.1)', color: sectorChg == null ? 'var(--text-muted)' : sectorChg >= 0 ? UP : DOWN, border: `1px solid ${sectorChg == null ? 'var(--border-color)' : sectorChg >= 0 ? 'rgba(216,80,74,0.35)' : 'rgba(59,154,46,0.35)'}` }}>
                {sector.sector}{rotation?.rotation_signal ? ` · ${rotation.rotation_signal}` : ''}
              </button>
            )}
            <span className="text-[9px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
              行情 {String(quote?.dataAsOf || dash?.date || '—').replace('T', ' ').slice(0, 16)} · 评分/资金 {dash?.date || '—'} 收盘 · 关键位 {priceLevelPlan?.dataAsOf || (dashboardError ? '数据不足' : '加载中')}
            </span>
          </div>
          <StockActionButtons
            stockCode={code}
            stockName={name}
            positionCount={myPos?.count || 0}
            showAnalysis={false}
            showKline={false}
            showBuy
            showSell
            showWatch
            showTrack
            showSina
            showMore
            size="xs"
          />
        </div>

        <div className="mt-1 overflow-x-auto no-scrollbar rounded-lg">
          <div
            className="grid gap-0 w-full min-w-[1360px] overflow-hidden rounded-lg"
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border-color)',
              gridTemplateColumns: 'minmax(120px, .9fr) minmax(300px, 1.55fr) minmax(130px, .9fr) minmax(160px, 1fr) minmax(180px, 1.1fr) minmax(210px, 1.25fr) minmax(260px, 1.55fr)',
            }}
          >
            {contextCards.map((card, cardIndex) => (
              <div
                key={card.title}
                className="stock-analysis-context-card px-1.5 py-1 min-w-0 flex flex-col justify-center"
                style={{
                  background: 'var(--bg-card)',
                  borderRight: cardIndex < contextCards.length - 1 ? '1px solid var(--border-color)' : 'none',
                }}
              >
                <div className="text-[10px] leading-[1.2] font-semibold text-left truncate" style={{ color: 'var(--text-secondary)' }} title={card.title}>{card.title}</div>
                <div
                  className="grid gap-0.5 mt-0"
                  style={{
                    gridTemplateColumns: `repeat(${card.items.length}, max-content)`,
                    columnGap: 'clamp(8px, 1.2vw, 18px)',
                    justifyContent: 'start',
                  }}
                >
                  {card.items.map(item => (
                    <div key={`${card.title}-${item.label}`} className="min-w-0 text-left" title={`${item.label}：${item.value}`}>
                      <div className="text-[10px] leading-[1.2] truncate" style={{ color: 'var(--text-muted)' }}>{item.label}</div>
                      <div className={`text-[12px] font-bold tabular-nums leading-[1.25] ${item.wrap ? 'whitespace-normal break-words' : 'truncate'}`} style={{ color: item.color || 'var(--text-primary)' }}>{item.value}</div>
                    </div>
                  ))}
                </div>
                {card.note && (
                  <div
                    className={`mt-0 ${card.title === '执行状态' ? 'text-[9px]' : 'text-[10px]'} leading-[1.25] text-left`}
                    title={card.note}
                    style={{ color: 'var(--text-muted)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}
                  >
                    {card.note}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>

        <div className="flex items-center gap-0.5 mt-1 overflow-x-auto no-scrollbar" style={{ borderTop: '1px solid var(--border-light)' }}>
          {TABS.map(t => (
            <button key={t.key} type="button" onClick={() => scrollToSection(t.id)}
              className="px-2 py-1 text-[11px] font-medium cursor-pointer whitespace-nowrap"
              style={{ background: 'transparent', color: activeTab === t.key ? 'var(--accent-blue)' : 'var(--text-secondary)', border: 'none', borderBottom: activeTab === t.key ? '2px solid var(--accent-blue)' : '2px solid transparent', borderRadius: 0, fontWeight: activeTab === t.key ? 700 : 400 }}>{t.label}</button>
          ))}
        </div>
      </div>

      {/* 双栏终端布局：中线阅读优先，K线约占52%，右侧评分/技术/关键位约占48% */}
      <div className="grid grid-cols-1 lg:grid-cols-[minmax(0,1fr)_300px] xl:grid-cols-[minmax(0,56fr)_minmax(0,44fr)] 2xl:grid-cols-[minmax(0,52fr)_minmax(0,48fr)] gap-4 items-start">
        {/* 主区（左侧自适应） */}
        <div className="space-y-3 min-w-0">
          {/* K线/B-S + 实时曲线 */}
          <div id="sec-bs" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }} className="p-2.5 rounded-xl">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>K线 · B/S 区间 · 成交量 · MACD/KDJ</span></div>
              <span className="hidden 2xl:block text-[10px]" style={{ color: 'var(--text-muted)' }}>蓝带=B/S区间 · 红●买 绿●卖 · 紫线SuperTrend · MACD/KDJ同图对照</span>
            </div>
            <div className="h-[440px] xl:h-[480px] 2xl:h-[520px]">
              {code ? <KLineChart code={code} upColor={UP} downColor={DOWN} dataAsOf={dash?.data_as_of || dash?.date} /> : <div className="h-full flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>请输入股票代码</div>}
            </div>
          </div>

          {/* 资金面 */}
          <div id="sec-capital" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }} className="p-2.5 rounded-xl">
            <div className="flex items-center justify-between mb-1.5">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>个股资金明细</span><span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>10/20日累计 · 分单类型</span></div>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>红流入 · 绿流出</span>
            </div>
            {dash ? (
              <div className="grid grid-cols-2 md:grid-cols-3 2xl:grid-cols-5 gap-px overflow-hidden rounded-lg" style={{ background: 'var(--border-color)', border: '1px solid var(--border-color)' }}>
                {fundDetailItems.map(item => {
                  const value = toFiniteNumber(item.value);
                  return (
                    <div key={item.label} className="px-2 py-1.5 min-w-0" style={{ background: 'var(--bg-card)' }} title={`${item.label}：${fmtAmount(value)}`}>
                      <div className="text-[9px] truncate" style={{ color: 'var(--text-muted)' }}>{item.label}</div>
                      <div className="text-xs font-bold tabular-nums truncate" style={{ color: value == null ? 'var(--text-muted)' : value >= 0 ? UP : DOWN }}>{fmtAmount(value)}</div>
                    </div>
                  );
                })}
              </div>
            ) : <div className="text-xs py-3" style={{ color: 'var(--text-muted)' }}>该股票暂无分析特征数据（dashboard），资金维度暂不可用</div>}
          </div>

          {/* 板块明细：顶部保留强弱与资金摘要，此处只展开龙头、涨停和同板块标的 */}
          <div id="sec-sector" className="p-2.5 rounded-xl" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-1.5">
                <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>板块个股明细</span></div>
                {sector?.sector && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· {sector.sector}</span>}
              </div>
              <div className="flex items-center gap-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>涨停 <b style={{ color: 'var(--text-primary)' }}>{sector?.limit_up_count ?? '—'}</b></span>
                <span>龙头 <b style={{ color: 'var(--text-primary)' }}>{sector?.leader_stock || '—'}</b></span>
              </div>
            </div>
            {dash?.realtime?.sector_net != null && (
              <div className="text-[10px] mb-1.5" style={{ color: 'var(--text-muted)' }}>板块实时净流 {fmtScaled(dash.realtime.sector_net, 1e4, 0)}万 · 实时涨幅 {dash.realtime.sector_rise != null ? fmtPct2(dash.realtime.sector_rise) : '—'} · 模式 {dash.realtime.mode}</div>
            )}
            <div className="rounded-lg p-2" style={{ background: 'var(--bg-card)' }}>
                <div className="flex items-center justify-between mb-1">
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>同板块标的（按涨幅排序，龙头高亮）</div>
                  {related.length > 0 && <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{related.length} 只</div>}
                </div>
                {related.length === 0 ? (
                  <div className="py-2 text-[11px] text-center" style={{ color: 'var(--text-muted)' }}>当前自选池中无同板块标的</div>
                ) : (
                  <div className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-x-2 gap-y-1">
                    {related.map(r => {
                      const isLeader = sector?.leader_stock && r.name === sector.leader_stock;
                      const isMe = r.code === code;
                      return (
                        <button key={r.code} onClick={() => changeCode(r.code)} className="flex items-center justify-between gap-1 px-1.5 py-1 rounded hover:opacity-80" style={{ background: isMe ? 'var(--bg-card)' : 'transparent', border: isMe ? '1px solid rgba(55,138,221,0.35)' : '1px solid transparent' }}>
                          <span className="truncate flex items-center gap-1 text-[11px]" style={{ color: isMe ? 'var(--accent-blue)' : 'var(--text-primary)' }}>
                            {isLeader && <span className="text-[9px] px-1 rounded shrink-0" style={{ background: 'rgba(245,158,11,0.18)', color: '#f59e0b' }}>龙头</span>}
                            <span className="truncate">{r.name}</span>
                            <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{r.code}</span>
                          </span>
                          <span className="text-[11px] font-bold tabular-nums shrink-0" style={{ color: r.chg == null ? 'var(--text-muted)' : r.chg >= 0 ? UP : DOWN }}>{r.chg != null ? fmtPct2(r.chg) : '—'}</span>
                        </button>
                      );
                    })}
                  </div>
                )}
            </div>
          </div>

          {/* 盘中实时 */}
          <div id="sec-intraday" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }} className="rounded-xl p-2.5">
            <div className="flex items-center justify-between gap-2 mb-2">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>盘中分时</span><span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>5分钟 · 板块热度</span></div>
              <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>盘后 {dash?.date || '—'}</span>
                {realtimeSourceStatus && (
                  <span className="px-2 py-0.5 rounded" style={{ background: realtimeIsLive ? 'rgba(34,197,94,0.15)' : 'rgba(107,114,128,0.15)', color: realtimeIsLive ? '#22c55e' : '#6b7280' }}>
                    {realtimeIsLive ? '● 实时正常' : realtimeIsClosed ? '● 已收盘' : realtimeSourceStatus === 'price_only' ? '● 仅行情，资金待采集' : realtimeSourceStatus === 'stale' ? '● 实时快照已过期' : '● 实时流待采集'}
                  </span>
                )}
              </div>
            </div>
            {realtimeData?.realtime_intraday?.available ? (
              <IntradayLive data={realtimeData.realtime_intraday} />
            ) : (
              <div className="mb-2 rounded-lg px-2 py-1.5 text-[10px]" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>{realtimeData?.realtime_intraday?.message || '等待实时数据…'}</div>
            )}
            <div className="h-[520px] md:h-[300px] xl:h-[310px] 2xl:h-[320px] mt-2">
              {code ? <IntradayPanel code={code} /> : <div className="h-full flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>请输入股票代码</div>}
            </div>
          </div>

          {/* 策略信号 */}
          <div id="sec-strategy" className="p-2.5 rounded-xl" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>策略信号</span><span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>真实命中</span></div>
              <button
                onClick={handleRescan}
                disabled={rescanning}
                className="text-xs px-2 py-1 rounded font-medium transition-colors"
                style={{ border: '1px solid var(--border-color)', color: rescanning ? 'var(--text-muted)' : 'var(--text-primary)', background: 'var(--bg-card)', cursor: rescanning ? 'default' : 'pointer' }}
              >{rescanning ? '扫描中…' : '↻ 重新扫描'}</button>
            </div>
            <div className="mb-2.5 text-[10px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
              数据截至 {strategyData?.latest_trade_date || '—'}（交易日 15:30 后自动更新；也可点「重新扫描」立即基于最新行情重算）
            </div>
            {/* 自动交易配置面板（真实状态 + 可开关） */}
            <div className="mb-3 rounded-lg p-2" style={{ background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between mb-1.5">
                <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 自动交易配置</span>
                <div className="flex items-center gap-2">
                  {autoGlobal && (!autoGlobal.enabled || autoGlobal.paused) && (
                    <span className="text-[10px]" style={{ color: '#d97706' }}>{autoGlobal.paused ? `全局已暂停${autoGlobal.pause_reason ? `（${autoGlobal.pause_reason}）` : ''}` : '全局总开关关闭'}</span>
                  )}
                  <button
                    type="button"
                    onClick={toggleAutoTrade}
                    disabled={autoBusy}
                    className="px-2 py-0.5 rounded text-[10px] font-bold transition-colors"
                    style={{
                      border: '1px solid var(--border-color)',
                      background: autoIsOn ? 'rgba(34,197,94,0.15)' : 'rgba(148,163,184,0.12)',
                      color: autoIsOn ? '#22c55e' : 'var(--text-muted)',
                      cursor: autoBusy ? 'default' : 'pointer',
                    }}
                  >{autoBusy ? '处理中…' : (autoIsOn ? '● 已开启（点击关闭）' : '○ 已关闭（点击开启）')}</button>
                </div>
              </div>
              <div className="grid grid-cols-2 md:grid-cols-3 gap-x-3 gap-y-1 text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                <div><span style={{ color: 'var(--text-muted)' }}>执行模式：</span>{autoModeLabel(autoCfg.mode)}</div>
                <div><span style={{ color: 'var(--text-muted)' }}>运行环境：</span>{autoCfg.run_environment || 'paper'}{autoCfg.run_environment === 'live' ? '（实盘）' : '（模拟）'}</div>
                <div><span style={{ color: 'var(--text-muted)' }}>最大仓位：</span>{autoCfg.risk?.max_position_pct != null ? `${autoCfg.risk.max_position_pct}%` : '—'}</div>
                <div><span style={{ color: 'var(--text-muted)' }}>硬止损价：</span>{autoCfg.prices?.hard_stop_price ?? '—'}</div>
                <div><span style={{ color: 'var(--text-muted)' }}>最大滑点：</span>{autoCfg.risk?.max_slippage_pct != null ? `${autoCfg.risk.max_slippage_pct}%` : '—'}</div>
                <div><span style={{ color: 'var(--text-muted)' }}>单日最大交易：</span>{autoCfg.risk?.max_daily_orders != null ? `${autoCfg.risk.max_daily_orders}次` : '—'}</div>
                <div className="col-span-2 md:col-span-3"><span style={{ color: 'var(--text-muted)' }}>状态：</span>{autoCfg.status || 'OFF'}{autoCfg.status_reason ? `（${autoCfg.status_reason}）` : ''}</div>
              </div>
              <div className="mt-1.5 pt-1.5 text-[10px]" style={{ borderTop: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                开启需先配置交易模式/硬止损/仓位/最大亏损/滑点；全局总开关在「策略中心」管理。
              </div>
            </div>
            {strategyLoading ? (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>
            ) : !strategyData || (strategyData.today_count === 0 && (strategyData.history || []).length === 0) ? (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>近 10 天未命中任何策略</div>
            ) : (
              <div className="space-y-4">
                {strategyData.today_count > 0 && (
                  <div>
                    <div className="text-xs font-bold mb-1.5" style={{ color: 'var(--text-secondary)' }}>今日命中 {strategyData.today_count} 个策略</div>
                    <div className="space-y-2">
                      {(strategyData.today_strategies || []).map(s => {
                        const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
                        const d = s.detail || {};
                        return (
                          <div key={s.strategy_key} className="rounded-lg p-2.5" style={{ background: c.bg }}>
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
                              {d.change_pct != null && <div>当日涨幅: <strong style={{ color: d.change_pct >= 0 ? UP : DOWN }}>{fmtPct2(d.change_pct)}</strong></div>}
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
                        <div key={h.trade_date} className="flex items-center gap-2 rounded-lg px-2.5 py-1.5" style={{ background: 'var(--bg-card)' }}>
                          <span className="text-xs font-medium whitespace-nowrap" style={{ color: 'var(--text-muted)', minWidth: 80 }}>{h.trade_date}</span>
                          <div className="flex flex-wrap gap-1">
                            {(h.strategies || []).map(s => {
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
          <div id="sec-f10" className="p-2.5 rounded-xl" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }}>
            <div className="flex items-center gap-2 mb-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>盘后底牌 / F10</span></div>
            {superPanel?.post_market_base && (
              <div className="mb-2 rounded-lg px-2.5 py-1.5 text-xs" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
                <span className="font-bold" style={{ color: 'var(--text-primary)' }}>游资结论：</span>
                {(() => {
                  const pmb = superPanel.post_market_base;
                  const score = pmb.quant_score;
                  const bosses = pmb.yesterday_bosses || [];
                  if (score == null && bosses.length === 0) return '暂无明显游资信号';
                  const parts = [];
                  if (bosses.length > 0) parts.push(`有${bosses.length}位游资参与`);
                  if (score != null && score >= 80) parts.push('游资活跃度高');
                  else if (score != null && score >= 60) parts.push('游资有一定参与度');
                  parts.push('持续性仍需观察');
                  return parts.join('，');
                })()}
              </div>
            )}
            {superPanel?.post_market_base ? (
              <PostMarketBase data={superPanel.post_market_base} />
            ) : (
              <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无盘后底牌数据</div>
            )}
          </div>

          {/* 新闻 / 公告（真实个股级，东财） */}
          <div id="sec-news" className="p-2.5 rounded-xl" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>个股新闻 / 公告</span><span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>东财真实</span></div>
              <div className="flex items-center gap-1">
                <button type="button" onClick={() => setNewsTab('news')}
                  className="px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer"
                  style={{ background: 'transparent', color: newsTab === 'news' ? 'var(--accent-blue)' : 'var(--text-secondary)', border: 'none', borderBottom: newsTab === 'news' ? '2px solid var(--accent-blue)' : '2px solid transparent', borderRadius: 0, fontWeight: newsTab === 'news' ? 700 : 400 }}>新闻 {(stockNews?.news?.length ?? 0)}</button>
                <button type="button" onClick={() => setNewsTab('ann')}
                  className="px-2 py-0.5 rounded text-[11px] font-medium cursor-pointer"
                  style={{ background: 'transparent', color: newsTab === 'ann' ? 'var(--accent-blue)' : 'var(--text-secondary)', border: 'none', borderBottom: newsTab === 'ann' ? '2px solid var(--accent-blue)' : '2px solid transparent', borderRadius: 0, fontWeight: newsTab === 'ann' ? 700 : 400 }}>公告 {(stockNews?.announcements?.length ?? 0)}</button>
              </div>
            </div>
            {newsTab === 'news' ? (
              (stockNews?.news?.length ?? 0) === 0 ? (
                <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无该个股新闻</div>
              ) : (
                <div className="space-y-0">
                  {(stockNews?.news ?? []).map((n, i) => (
                    <a key={i} href={n.url || '#'} target="_blank" rel="noopener noreferrer"
                      className="block py-1.5 no-underline" style={{ borderBottom: i < (stockNews?.news?.length ?? 0) - 1 ? '1px solid var(--border-color)' : 'none' }}>
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
              (stockNews?.announcements?.length ?? 0) === 0 ? (
                <div className="py-3 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无该个股公告</div>
              ) : (
                <div className="space-y-0">
                  {(stockNews?.announcements ?? []).map((a, i) => (
                    <a key={i} href={a.url || '#'} target="_blank" rel="noopener noreferrer"
                      className="block py-1.5 no-underline" style={{ borderBottom: i < (stockNews?.announcements?.length ?? 0) - 1 ? '1px solid var(--border-color)' : 'none' }}>
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
          <div id="sec-ai" className="p-2.5 rounded-xl" style={{ scrollMarginTop: 126, background: 'var(--bg-surface)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2"><span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span><span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>AI 分析</span></div>
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

        {/* 右栏上下文：评分与技术指标保持相邻，窄屏时回归正常文档流 */}
        <div className="stock-analysis-context-scroll lg:sticky lg:self-start lg:max-h-[calc(100vh-188px)] lg:overflow-y-auto space-y-3 rounded-xl p-3" style={{ top: 126, background: 'var(--bg-surface)' }}>
          {/* 8维评分 */}
          <div className="rounded-xl p-2.5" style={{ background: 'transparent' }}>
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mb-2">
              <span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span>
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>综合评分</span>
              {dash?.metric_source === 'kline_fallback' && (
                <>
                  <span className="text-[9px] px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap" title="本股无 StockFeaturesDaily 精确入库，评分基于 K 线现场近似计算" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>近似</span>
                  <button
                    type="button"
                    disabled={backfilling}
                    onClick={backfillPreciseFeatures}
                    className="px-1.5 py-0.5 rounded-full text-[9px] font-medium whitespace-nowrap cursor-pointer disabled:opacity-50"
                    style={{ background: 'rgba(55,138,221,0.12)', color: 'var(--accent-blue)', border: '1px solid rgba(55,138,221,0.3)' }}
                  >
                    {backfilling ? '补算中…' : '补精确特征'}
                  </button>
                </>
              )}
              <span className="text-xl font-bold leading-none flex-shrink-0" style={{ color: 'var(--accent-blue)' }}>{composite ?? '—'}</span>
              <span className="text-[10px] whitespace-nowrap flex-shrink-0" style={{ color: 'var(--text-muted)' }}>综合评分 / 100</span>
              {verdict && (
                <span
                  className="min-w-0 flex-1 truncate text-[10px] font-medium"
                  style={{ color: 'var(--text-secondary)' }}
                  title={`${verdict.techBull ? '短线强' : verdict.techBear ? '短线弱' : '短线中性'}，${midTermLabel}，${sectorTrendLabel}`}
                >
                  {verdict.techBull ? '短线强' : verdict.techBear ? '短线弱' : '短线中性'} · {midTermLabel} · {sectorTrendLabel}
                </span>
              )}
              <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>{validDimensionCount}/8维可用</span>
            </div>
            {dash ? (
              <>
                {dims.map(d => (
                  <div key={d.key} className="mb-1.5 cursor-pointer hover:opacity-80" onClick={() => scrollToSection(DIM_TO_SECTION[d.key] || 'sec-tech')} title={`点击跳转到${d.label}对应模块`}>
                    <div className="flex justify-between text-[11px] mb-0.5" style={{ color: 'var(--text-secondary)' }}><span>{d.label}</span><span>{d.v == null ? '—' : Math.round(d.v)}</span></div>
                    <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--border-color)' }}>
                      <div className="h-full rounded-full" style={{ width: `${d.v ?? 0}%`, background: d.v == null ? 'var(--text-muted)' : d.v >= 60 ? UP : d.v >= 40 ? '#EF9F27' : DOWN }} />
                    </div>
                  </div>
                ))}
                {/* 风险等级（独立反向维，分数越高越危险） */}
                <div className="mb-1.5 mt-2.5 pt-2" title={dash?.risk?.status === 'PARTIAL' ? '噪声比暂无，风险仅按波动评估' : '风险等级为独立反向维度，分数越高越危险'} style={{ borderTop: '1px dashed var(--border-color)' }}>
                  <div className="flex justify-between items-center text-[11px] mb-0.5" style={{ color: 'var(--text-secondary)' }}>
                    <span>风险等级</span>
                    <span style={{ color: dash?.risk?.score == null ? 'var(--text-muted)' : dash?.risk?.score >= 70 ? '#ef4444' : dash?.risk?.score >= 50 ? '#f97316' : dash?.risk?.score >= 30 ? '#eab308' : '#22c55e' }}>
                      {dash?.risk?.level || '—'}
                      {dash?.risk?.status === 'PARTIAL' && <span className="text-[9px] ml-1" style={{ color: '#f59e0b' }}>近似</span>}
                    </span>
                  </div>
                  <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--border-color)' }}>
                    <div className="h-full rounded-full" style={{ width: `${dash?.risk?.score ?? 0}%`, background: dash?.risk?.score == null ? 'var(--text-muted)' : dash?.risk?.score >= 70 ? '#ef4444' : dash?.risk?.score >= 50 ? '#f97316' : dash?.risk?.score >= 30 ? '#eab308' : '#22c55e' }} />
                  </div>
                </div>
              </>
            ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>—</div>}
          </div>

          {/* 技术指标：紧接综合评分，针对右栏宽度使用紧凑卡片布局 */}
          <div id="sec-tech" className="rounded-xl p-2.5" style={{ scrollMarginTop: 126, background: 'transparent', borderTop: '1px solid var(--border-color)' }}>
            <div className="flex items-center gap-2 mb-2">
              <span className="w-1 h-4 rounded-full" style={{ background: 'var(--accent-blue)' }}></span>
              <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>个股技术指标</span>
              <span className="ml-auto px-2 py-1 rounded-md text-[9px] font-bold whitespace-nowrap" style={{
                color: verdict?.techBull ? UP : verdict?.techBear ? DOWN : 'var(--text-muted)',
                background: (verdict?.techBull ? UP : verdict?.techBear ? DOWN : '#888780') + '12',
              }}>
                {verdict?.techBull ? 'MACD/KDJ 同为多头 · 偏强' : verdict?.techBear ? 'MACD/KDJ 同为空头 · 偏弱' : 'MACD/KDJ 方向未一致'}
              </span>
            </div>

            <div className="grid grid-cols-2 xl:grid-cols-3 2xl:grid-cols-6 gap-2">
              <div className="rounded-lg p-2 min-w-0" style={{ background: 'var(--bg-card)' }}>
                <div className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>MACD</div>
                <div className="mt-1.5 grid grid-cols-3 gap-1 text-center">
                  {[['DIF', tech.macdDif], ['DEA', tech.macdDea], ['柱', tech.macdHist]].map(([label, value]) => (
                    <div key={label}><div className="text-[8px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="text-[11px] font-bold tabular-nums" style={{ color: label === '柱' && value != null ? (value >= 0 ? UP : DOWN) : 'var(--text-primary)' }}>{fmtFixed(value, 2)}</div></div>
                  ))}
                </div>
                <div className="mt-1 text-[9px] leading-tight" style={{ color: 'var(--text-muted)' }}>{tech.macdDif == null || tech.macdDea == null ? '数据不足' : tech.macdDif >= tech.macdDea ? 'DIF 高于 DEA，动能修复' : 'DIF 低于 DEA，动能偏弱'}</div>
              </div>

              <div className="rounded-lg p-2 min-w-0" style={{ background: 'var(--bg-card)' }}>
                <div className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>KDJ</div>
                <div className="mt-1.5 grid grid-cols-3 gap-1 text-center">
                  {[['K', tech.kdjK], ['D', tech.kdjD], ['J', tech.kdjJ]].map(([label, value]) => (
                    <div key={label}><div className="text-[8px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="text-[11px] font-bold tabular-nums" style={{ color: 'var(--text-primary)' }}>{fmtFixed(value, 1)}</div></div>
                  ))}
                </div>
                <div className="mt-1 text-[9px] leading-tight" style={{ color: 'var(--text-muted)' }}>{tech.kdjK == null || tech.kdjD == null ? '数据不足' : tech.kdjK >= tech.kdjD ? 'K 高于 D，短线偏强' : 'K 低于 D，短线偏弱'}</div>
              </div>

              {[
                { n: 'RSI(14)', v: fmtFixed(tech.rsi, 1), s: tech.rsi == null ? '数据不足' : tech.rsi >= 70 ? '超买' : tech.rsi <= 30 ? '超卖' : '中性', c: tech.rsi == null ? 'var(--text-muted)' : tech.rsi >= 70 ? UP : tech.rsi <= 30 ? DOWN : 'var(--text-muted)', ex: tech.rsi == null ? '暂无数据' : tech.rsi >= 70 ? '注意回调风险' : tech.rsi <= 30 ? '关注反弹机会' : '未进入极值区' },
                { n: '量比', v: fmtFixed(tech.volRatio, 2), s: tech.volRatio == null ? '数据不足' : tech.volRatio >= 1.5 ? '放量' : tech.volRatio >= 0.8 ? '正常' : tech.volRatio >= 0.5 ? '缩量' : '清淡', c: tech.volRatio == null ? 'var(--text-muted)' : tech.volRatio >= 1.5 ? UP : tech.volRatio >= 0.8 ? 'var(--text-secondary)' : DOWN, ex: tech.volRatio == null ? '暂无数据' : tech.volRatio >= 1.5 ? '资金参与度较高' : tech.volRatio >= 0.8 ? '量能正常' : tech.volRatio >= 0.5 ? '量能偏弱' : '交投清淡' },
                { n: '价 / MA20', v: tech.closeVsMa20 != null ? `${fmtFixed(tech.closeVsMa20 * 100, 1)}%` : '—', s: tech.closeVsMa20 == null ? '数据不足' : tech.closeVsMa20 >= 0 ? '站上' : '跌破', c: tech.closeVsMa20 == null ? 'var(--text-muted)' : tech.closeVsMa20 >= 0 ? UP : DOWN, ex: tech.closeVsMa20 == null ? '暂无数据' : tech.closeVsMa20 >= 0 ? '中期趋势偏强' : '中期趋势未修复', tip: '股价相对 20 日移动平均线的位置及偏离度' },
                { n: 'MA20 斜率', v: tech.ma20Slope != null ? `${tech.ma20Slope >= 0 ? '+' : ''}${fmtFixed(tech.ma20Slope, 1)}%` : '—', s: tech.ma20Slope == null ? '数据不足' : tech.ma20Slope > 0.5 ? '↑向上' : tech.ma20Slope < -0.5 ? '↓向下' : '→走平', c: tech.ma20Slope == null ? 'var(--text-muted)' : tech.ma20Slope > 0.5 ? UP : tech.ma20Slope < -0.5 ? DOWN : 'var(--text-muted)', ex: tech.ma20Slope == null ? '暂无数据' : '反映中期趋势方向', tip: '20 日移动平均线自身的斜率方向' },
              ].map(d => (
                <div key={d.n} title={d.tip} className="rounded-lg p-2 min-w-0" style={{ background: 'var(--bg-card)' }}>
                  <div className="flex items-center justify-between gap-1"><span className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{d.n}</span><span className="text-[9px] font-medium whitespace-nowrap" style={{ color: d.c }}>{d.s}</span></div>
                  <div className="text-sm font-bold tabular-nums mt-0.5" style={{ color: d.c === 'var(--text-muted)' ? 'var(--text-primary)' : d.c }}>{d.v}</div>
                  <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>{d.ex}</div>
                </div>
              ))}
            </div>
          </div>

          {/* 关键价位明细：核心五点固定在顶部，这里始终展开 11 类数据库价位 */}
          <div id="sec-levels" className="rounded-xl p-2.5" style={{ scrollMarginTop: 126, background: 'transparent', borderTop: '1px solid var(--border-color)' }}>
            <PriceLevelsCard
              market="a"
              symbol={code}
              dataAsOf={dash?.data_as_of || dash?.date}
              currentPrice={price}
              positionCount={myPos?.count || 0}
              signalContext={priceLevelSignalContext}
              onPlanChange={setPriceLevelPlan}
            />
          </div>

        </div>
      </div>

      <div className="text-[10px] text-right pt-2" style={{ color: 'var(--text-muted)', borderTop: '1px solid var(--border-color)' }}>数据日期 {dash?.date || '—'}</div>
      </div>
      </div>
    </div>
  </div>
  );
}

// 盘中实时数据展示（5秒刷新）
function IntradayLive({ data }) {
  const pct = toFiniteNumber(data.pct_chg);
  const isUp = pct == null ? null : pct >= 0;
  const pctColor = isUp === null ? 'var(--text-secondary)' : isUp ? UP : DOWN;
  const upstreamSource = data.upstream_source || data.upstreamSource;
  const isFallbackSnapshot = data.status === 'price_only' || data.data_quality === 'price_only' || upstreamSource === 'fallback';
  const normalizeSnapshotValue = value => {
    const number = toFiniteNumber(value);
    return isFallbackSnapshot && number === 0 ? null : number;
  };
  const activeRatio = normalizeSnapshotValue(data.large_order_active_ratio);
  const ratioColor = activeRatio == null ? 'var(--text-muted)' : activeRatio > 60 ? UP : activeRatio > 40 ? '#EF9F27' : DOWN;
  const mainForce = normalizeSnapshotValue(data.main_force_inflow);
  const turnover = normalizeSnapshotValue(data.turnover_rate);
  const volume = normalizeSnapshotValue(data.volume);
  const largeBuy = toFiniteNumber(data.large_buy_count_3s);
  const largeSell = toFiniteNumber(data.large_sell_count_3s);
  const thousandOrders = toFiniteNumber(data.thousand_order_count_per_min);
  const metrics = [
    { label: '现价 / 涨跌', value: `${fmtFixed(data.current_price, 2)}  ${pct != null ? fmtPct2(pct) : '—'}`, color: pctColor },
    { label: '换手率', value: turnover != null ? `${fmtFixed(turnover, 2)}%` : '—' },
    { label: '主力净流入', value: mainForce != null ? `${fmtScaled(mainForce, 10000, 0)}万` : '—', color: mainForce == null ? null : mainForce >= 0 ? UP : DOWN },
    { label: '成交量', value: volume != null ? `${fmtScaled(volume, 10000, 0)}万手` : '—' },
    { label: '大单主动买入比', value: activeRatio != null ? `${fmtFixed(activeRatio, 1)}%` : '—', color: ratioColor, ratio: activeRatio },
  ];
  return (
    <div>
      <div className="grid grid-cols-2 md:grid-cols-3 2xl:grid-cols-5 gap-px overflow-hidden rounded-lg" style={{ background: 'var(--border-color)', border: '1px solid var(--border-color)' }}>
        {metrics.map(metric => (
          <div key={metric.label} className="px-2 py-1.5 min-w-0" style={{ background: 'var(--bg-card)' }} title={`${metric.label}：${metric.value}`}>
            <div className="text-[9px] truncate" style={{ color: 'var(--text-muted)' }}>{metric.label}</div>
            <div className="text-xs font-bold tabular-nums truncate" style={{ color: metric.color || 'var(--text-primary)' }}>{metric.value}</div>
            {metric.ratio != null && (
              <div className="h-0.5 mt-1 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.2)' }}>
                <div className="h-full" style={{ width: `${Math.max(0, Math.min(100, metric.ratio))}%`, background: ratioColor }} />
              </div>
            )}
          </div>
        ))}
      </div>
      <div className="flex items-center flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[9px]" style={{ color: 'var(--text-muted)' }}>
        {data.last_close > 0 && <span>昨收 {fmtFixed(data.last_close, 2)}</span>}
        {(largeBuy != null || largeSell != null) && <span>近3秒 买{largeBuy ?? '—'} / 卖{largeSell ?? '—'}</span>}
        {thousandOrders != null && <span>千单/分 {thousandOrders}</span>}
        {data.bid_price_1 > 0 && <span><span style={{ color: UP }}>买一 {fmtFixed(data.bid_price_1, 2)}</span> · <span style={{ color: DOWN }}>卖一 {fmtFixed(data.ask_price_1, 2)}</span></span>}
        {data.snapshot_time && <span>快照 {data.snapshot_time.slice(5, 16).replace('T', ' ')}</span>}
        {data.source && <span>来源 数据库{isFallbackSnapshot ? ' · 降级快照' : ''}</span>}
        {data.support_level_eval && <span className="min-w-0 flex-1 truncate" title={data.support_level_eval}>{data.support_level_eval}</span>}
      </div>
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
        <span style={{ color: 'var(--text-muted)' }}>净买 {data.total_net_buy_wan ? `${fmtScaled(data.total_net_buy_wan, 10000, 2)}亿` : '—'}</span>
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
                    {b.net_buy_wan >= 0 ? '+' : ''}{fmtScaled(b.net_buy_wan, 10000, 2)}亿
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
