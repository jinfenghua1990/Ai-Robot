import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { usNameCN, US_NAMES_CN } from '../utils/usStockNames';
import { usSectorCN } from '../utils/usStockSectors';
import { usTradingViewUrl } from '../utils/usStockExchange';
import PriceLevelsCard from '../components/PriceLevelsCard';

// ─── 全局框架色板（CSS 变量，随浅色/深色主题自动切换） ───────────────────────
const K = {
  panel: 'var(--bg-card)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  text: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  accent: 'var(--accent-blue)',
  gold: 'var(--accent-amber)',
  green: 'var(--accent-green)',
  hover: 'var(--bg-hover)',
};

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));
const fmtBig = (v) => {
  if (v == null) return '—';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return String(v);
};

function Panel({ title, extra, children, style, className = '' }) {
  return (
    <div className={className} style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '14px 16px', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: K.text }}>{title}</span>
        {extra && <span style={{ marginLeft: 'auto' }}>{extra}</span>}
      </div>
      {children}
    </div>
  );
}

/** 涨跌色（红涨绿跌，与全系统一致） */
function pctColor(v) {
  if (v == null) return K.muted;
  return v > 0 ? K.up : v < 0 ? K.down : K.muted;
}

/** 区间收益卡片 */
function RetCell({ label, value }) {
  return (
    <div style={{ background: K.hover, borderRadius: 8, padding: '8px 10px', textAlign: 'center' }}>
      <div style={{ fontSize: 11, color: K.muted }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: pctColor(value) }}>
        {value == null ? '—' : (value > 0 ? '+' : '') + fmt(value, 2) + '%'}
      </div>
    </div>
  );
}

/** 均线形态标签 */
function TrendBadge({ trend, signal }) {
  const map = {
    '多头排列': { c: K.up, t: '多头' },
    '空头排列': { c: K.down, t: '空头' },
    '均线纠缠': { c: K.gold, t: '纠缠' },
  };
  const m = map[trend];
  const color = m ? m.c : K.muted;
  return (
    <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center', fontSize: 12 }}>
      <span style={{ background: color, color: '#fff', borderRadius: 4, padding: '1px 6px', fontWeight: 600 }}>{m ? m.t : '—'}</span>
      {signal !== '—' && (
        <span style={{ color: signal === '金叉' ? K.up : K.down, fontWeight: 600 }}>{signal === '金叉' ? '⚡ 金叉' : '▼ 死叉'}</span>
      )}
    </span>
  );
}

/** 52周区间条 */
function RangeBar({ low, high, pos }) {
  const valid = low != null && high != null && high > low;
  if (!valid) return <div style={{ fontSize: 12, color: K.muted }}>—</div>;
  const p = Math.min(100, Math.max(0, pos ?? 0));
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
      <span style={{ color: K.muted, minWidth: 52, textAlign: 'right' }}>{fmt(low)}</span>
      <div style={{ flex: 1, height: 8, borderRadius: 4, background: K.hover, border: `1px solid ${K.borderLight}`, position: 'relative' }}>
        <div style={{ position: 'absolute', left: 0, top: 0, bottom: 0, width: `${p}%`, borderRadius: 4, background: 'var(--accent-blue)', opacity: 0.75 }} />
        <div style={{ position: 'absolute', top: -3, bottom: -3, width: 2, left: `${p}%`, background: K.text, borderRadius: 1 }} />
      </div>
      <span style={{ color: K.muted, minWidth: 52 }}>{fmt(high)}</span>
      <span style={{ color: K.accent, fontWeight: 600, minWidth: 44, textAlign: 'right' }}>{fmt(pos, 0)}%</span>
    </div>
  );
}

/** 走势图：收盘价 + MA20 + MA60 + 成交量副图 */
const CHART_TIMEFRAMES = [['intraday', '分时'], ['day', '日K'], ['week', '周K'], ['month', '月K']];
const MA_SERIES = [
  ['ma5', 'MA5', 'var(--accent-blue)'],
  ['ma10', 'MA10', '#a855f7'],
  ['ma20', 'MA20', 'var(--accent-amber)'],
  ['ma60', 'MA60', 'var(--accent-green)'],
];
const BOLL_SERIES = [
  ['upper', 'BOLL上', '#f97316'],
  ['mid', 'BOLL中', '#94a3b8'],
  ['lower', 'BOLL下', '#06b6d4'],
];

function spreadAxisLabels(items, minY, maxY, gap = 11) {
  const rows = [...items].sort((a, b) => a.y - b.y).map((item) => ({ ...item, labelY: item.y }));
  for (let i = 1; i < rows.length; i += 1) rows[i].labelY = Math.max(rows[i].labelY, rows[i - 1].labelY + gap);
  if (rows.at(-1)?.labelY > maxY) {
    rows[rows.length - 1].labelY = maxY;
    for (let i = rows.length - 2; i >= 0; i -= 1) rows[i].labelY = Math.min(rows[i].labelY, rows[i + 1].labelY - gap);
  }
  if (rows[0]?.labelY < minY) {
    rows[0].labelY = minY;
    for (let i = 1; i < rows.length; i += 1) rows[i].labelY = Math.max(rows[i].labelY, rows[i - 1].labelY + gap);
  }
  return rows;
}

function aggregateKline(rows, frame) {
  if (frame === 'day') return rows || [];
  const buckets = new Map();
  (rows || []).forEach((row) => {
    const d = new Date(`${row.d}T00:00:00Z`);
    const key = frame === 'week' ? `${row.d.slice(0, 4)}-${Math.floor((d.getTime() - Date.UTC(d.getUTCFullYear(), 0, 1)) / 604800000)}` : row.d.slice(0, 7);
    const prior = buckets.get(key);
    if (prior) { prior.h = Math.max(prior.h, row.h); prior.l = Math.min(prior.l, row.l); prior.c = row.c; prior.d = row.d; prior.v += row.v || 0; }
    else buckets.set(key, { ...row });
  });
  return [...buckets.values()];
}

function IntradayChart({ points }) {
  if (!points || points.length < 2) return <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: K.muted, fontSize: 13 }}>分时数据不足（当前非交易时段或数据源仅返回收盘点）</div>;
  const W = 640, H = 275, l = 12, r = 42, t = 16, b = 22, prices = points.map((p) => p.p);
  const low = Math.min(...prices), high = Math.max(...prices), pad = (high - low || high * 0.01 || 1) * 0.08;
  const X = (i) => l + i / (points.length - 1) * (W - l - r), Y = (v) => t + (1 - (v - (low - pad)) / (high - low + pad * 2)) * (H - t - b);
  const path = prices.map((p, i) => `${i ? 'L' : 'M'}${X(i).toFixed(1)},${Y(p).toFixed(1)}`).join('');
  return <div><div style={{ fontSize: 11, color: K.muted, marginBottom: 5 }}>当日分时 · {points.length} 个有效点</div><svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}><line x1={l} x2={W - r} y1={Y(prices[0])} y2={Y(prices[0])} stroke="var(--border-light)" strokeDasharray="3 3" /><path d={path} fill="none" stroke="var(--accent-blue)" strokeWidth="1.8" /><text x={W - r + 4} y={Y(high)} fontSize="9" fill="var(--text-muted)">{fmt(high)}</text><text x={W - r + 4} y={Y(low)} fontSize="9" fill="var(--text-muted)">{fmt(low)}</text><text x={l} y={H - 4} fontSize="9" fill="var(--text-muted)">{points[0].t}</text><text x={W - r} y={H - 4} textAnchor="end" fontSize="9" fill="var(--text-muted)">{points.at(-1).t}</text></svg></div>;
}

function Chart({ kline, indicators = {}, frame, intraday = [] }) {
  const [sub, setSub] = useState('macd');
  const W = 760, H = 310, L = 10, R = 100, TOP = 10, MAIN_H = 194, SUB_TOP = 224, SUB_H = 58;
  const { data, ind } = useMemo(() => {
    const allSource = aggregateKline(kline, frame);
    const displayLimit = frame === 'day' ? 90 : allSource.length;
    const start = Math.max(0, allSource.length - displayLimit);
    const source = allSource.slice(start);
    const cut = (v) => Array.isArray(v) ? v.slice(start) : [];
    return { data: source, ind: frame === 'day' ? { ...indicators, boll: Object.fromEntries(Object.entries(indicators.boll || {}).map(([k, v]) => [k, cut(v)])), macd: Object.fromEntries(Object.entries(indicators.macd || {}).map(([k, v]) => [k, cut(v)])), kdj: Object.fromEntries(Object.entries(indicators.kdj || {}).map(([k, v]) => [k, cut(v)])), ma5: cut(indicators.ma5), ma10: cut(indicators.ma10), ma20: cut(indicators.ma20), ma60: cut(indicators.ma60), rsi: cut(indicators.rsi), atr: cut(indicators.atr), obv: cut(indicators.obv), bs_signals: (indicators.bs_signals || []).filter((x) => x.i >= start).map((x) => ({ ...x, i: x.i - start })) } : { ma5: [], ma10: [], ma20: [], ma60: [], boll: { upper: [], mid: [], lower: [] }, macd: { hist: [], dif: [], dea: [] }, kdj: { k: [], d: [], j: [] }, rsi: [], atr: [], obv: [], bs_signals: [] } };
  }, [kline, indicators, frame]);
  if (frame === 'intraday') return <IntradayChart points={intraday} />;
  if (data.length < 2) return <div style={{ height: H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: K.muted, fontSize: 13 }}>日线数据不足，无法绘制技术图</div>;
  const X = (i) => L + i / (data.length - 1) * (W - L - R);
  const priceValues = data.flatMap((x) => [x.h, x.l]).concat(...[ind.ma5, ind.ma10, ind.ma20, ind.ma60, ind.boll.upper, ind.boll.lower].map((a) => a.filter((v) => v != null)));
  let lo = Math.min(...priceValues), hi = Math.max(...priceValues); const span = hi - lo || 1; lo -= span * 0.05; hi += span * 0.05;
  const PY = (v) => TOP + (1 - (v - lo) / (hi - lo)) * MAIN_H;
  const line = (arr, Y) => arr.reduce((p, v, i) => v == null ? p : `${p}${p && arr[i - 1] != null ? 'L' : 'M'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`, '');
  const subData = sub === 'macd' ? [ind.macd.hist, ind.macd.dif, ind.macd.dea] : sub === 'kdj' ? [ind.kdj.k, ind.kdj.d, ind.kdj.j] : [ind[sub] || []];
  const raw = subData.flat().filter((v) => v != null); const zeroBased = sub === 'macd'; const slo = zeroBased ? Math.min(0, ...raw) : Math.min(...raw, 0); const shi = Math.max(...raw, zeroBased ? 0 : 1); const SY = (v) => SUB_TOP + (1 - (v - slo) / (shi - slo || 1)) * SUB_H;
  const last = data.at(-1), first = data[0], change = (last.c / first.c - 1) * 100, step = (W - L - R) / (data.length - 1), candleW = Math.max(1.4, Math.min(8, step * 0.82));
  const frameLabel = frame === 'day' ? '日K' : frame === 'week' ? '周K' : '月K';
  const tickCount = Math.min(8, data.length);
  const tickIndices = Array.from({ length: tickCount }, (_, i) => Math.round(i * (data.length - 1) / Math.max(1, tickCount - 1)));
  const chartSeries = frame === 'day' ? [
    ...MA_SERIES.map(([key, label, seriesColor]) => ({ key, label, color: seriesColor, values: ind[key] || [], dashed: false, type: 'ma' })),
    ...BOLL_SERIES.map(([key, label, seriesColor]) => ({ key: `boll-${key}`, label, color: seriesColor, values: ind.boll?.[key] || [], dashed: true, type: 'boll' })),
  ] : [];
  const maAxisLabels = spreadAxisLabels(chartSeries.filter((item) => item.type === 'ma' && item.values.at(-1) != null).map((item) => ({ ...item, value: item.values.at(-1), y: PY(item.values.at(-1)) })), TOP + 5, TOP + MAIN_H - 5);
  const priceTicks = Array.from({ length: 5 }, (_, i) => ({ value: hi - (hi - lo) * i / 4, y: TOP + MAIN_H * i / 4 }));
  return <div>
    <div style={{ display: 'flex', alignItems: 'baseline', gap: 9, marginBottom: 4 }}><b style={{ fontSize: 20 }}>{fmt(last.c)}</b><b style={{ color: pctColor(change), fontSize: 13 }}>{change >= 0 ? '+' : ''}{fmt(change, 2)}%</b><span style={{ fontSize: 11, color: K.muted }}>{last.d} · {frameLabel}</span>{frame === 'day' && <span style={{ marginLeft: 'auto', fontSize: 10.5, color: K.muted, whiteSpace: 'nowrap' }}>纵轴：价格 · 横轴：日期</span>}</div>
    <div style={{ fontSize: 10.5, color: K.muted, marginBottom: 3 }}>{frameLabel} · {data.length} 根 · {data[0].d} — {last.d}</div>
    {frame === 'day' && <div style={{ display: 'flex', alignItems: 'center', gap: '4px 9px', flexWrap: 'wrap', margin: '4px 0 5px', fontSize: 9.5 }}>{chartSeries.map((item) => <span key={item.key} title={`${item.label} 最新 ${fmt(item.values.at(-1))}`} style={{ display: 'inline-flex', alignItems: 'center', gap: 3, color: K.secondary }}><span style={{ display: 'inline-block', width: 13, borderTop: `${item.dashed ? '1px dashed' : '2px solid'} ${item.color}` }} />{item.label} <b style={{ color: item.color }}>{fmt(item.values.at(-1))}</b></span>)}<span style={{ marginLeft: 'auto', color: K.muted }}><b style={{ color: '#d92d20' }}>● B买入</b>&nbsp;&nbsp;<b style={{ color: '#159447' }}>● S卖出</b></span></div>}
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
      {priceTicks.map((tick) => <g key={tick.value}><line x1={L} x2={W - R} y1={tick.y} y2={tick.y} stroke="var(--border-light)" strokeDasharray="3 3" /><text x={W - R - 4} y={tick.y + 3} fontSize="8.5" textAnchor="end" fill="var(--text-muted)">{fmt(tick.value)}</text></g>)}
      <line x1={W - R} x2={W - R} y1={TOP} y2={TOP + MAIN_H} stroke="var(--border-color)" />
      {data.map((k, i) => <g key={k.d}><line x1={X(i)} x2={X(i)} y1={PY(k.h)} y2={PY(k.l)} stroke={k.c >= k.o ? K.up : K.down} /><rect x={X(i) - candleW / 2} y={PY(Math.max(k.o, k.c))} width={candleW} height={Math.max(1, Math.abs(PY(k.o) - PY(k.c)))} fill={k.c >= k.o ? K.up : K.down} /></g>)}
      {chartSeries.map((item) => <path key={item.key} d={line(item.values, PY)} fill="none" stroke={item.color} strokeWidth={item.dashed ? .8 : 1.15} strokeDasharray={item.dashed ? '4 3' : undefined}><title>{item.label} · 最新 {fmt(item.values.at(-1))}</title></path>)}
      {ind.bs_signals.map((sig) => { const color = sig.side === 'B' ? '#d92d20' : '#159447'; const markerY = PY(sig.side === 'B' ? data[sig.i].l : data[sig.i].h) + (sig.side === 'B' ? 20 : -20); return <g key={`${sig.i}${sig.side}`}><line x1={X(sig.i)} x2={X(sig.i)} y1={PY(sig.side === 'B' ? data[sig.i].l : data[sig.i].h)} y2={markerY} stroke={color} strokeWidth="2.5" strokeDasharray="3 2" /><circle cx={X(sig.i)} cy={markerY} r="8.5" fill={color} stroke="#fff" strokeWidth="1.5" /><text x={X(sig.i)} y={markerY + 3.4} textAnchor="middle" fontSize="9" fontWeight="800" fill="#fff">{sig.side}</text><title>{sig.side === 'B' ? '强B买入' : '卖出'} · {sig.reason}</title></g>; })}
      {maAxisLabels.map((item) => <g key={`axis-${item.key}`}><circle cx={W - R} cy={item.y} r="2.2" fill={item.color} /><path d={`M${W - R},${item.y} L${W - R + 6},${item.y} L${W - R + 10},${item.labelY}`} fill="none" stroke={item.color} strokeWidth="1" /><text x={W - R + 13} y={item.labelY + 3} fontSize="8.5" fontWeight="700" fill={item.color}>{item.label} {fmt(item.value)}</text></g>)}
      {frame === 'day' && <line x1={L} x2={W - R} y1={SUB_TOP + SUB_H / 2} y2={SUB_TOP + SUB_H / 2} stroke="var(--border-light)" />}
      {frame === 'day' && sub === 'macd' && (ind.macd.hist || []).map((v, i) => v != null && <rect key={i} x={X(i) - candleW / 2} y={Math.min(SY(v), SY(0))} width={candleW} height={Math.max(1, Math.abs(SY(v) - SY(0)))} fill={v >= 0 ? K.up : K.down} opacity=".55" />)}
      {frame === 'day' && (sub === 'macd' ? [[ind.macd.dif, K.accent], [ind.macd.dea, 'var(--accent-amber)']] : sub === 'kdj' ? [[ind.kdj.k, K.accent], [ind.kdj.d, 'var(--accent-amber)'], [ind.kdj.j, 'var(--accent-purple)']] : [[ind[sub], K.accent]]).map(([a, c], i) => <path key={i} d={line(a || [], SY)} fill="none" stroke={c} strokeWidth="1.2" />)}
      {frame === 'day' && <><text x={W - R - 4} y={SUB_TOP + 8} fontSize="8" textAnchor="end" fill="var(--text-muted)">{Math.abs(shi) >= 1e6 ? fmtBig(shi) : fmt(shi, 1)}</text><text x={W - R - 4} y={SUB_TOP + SUB_H} fontSize="8" textAnchor="end" fill="var(--text-muted)">{Math.abs(slo) >= 1e6 ? fmtBig(slo) : fmt(slo, 1)}</text></>}
      {tickIndices.map((i) => <text key={i} x={X(i)} y={H - 3} fontSize="9" fill="var(--text-muted)" textAnchor={i === 0 ? 'start' : i === data.length - 1 ? 'end' : 'middle'}>{data[i].d.slice(5)}</text>)}
    </svg>
    {frame === 'day' ? <div style={{ display: 'flex', alignItems: 'center', gap: 5, flexWrap: 'wrap', marginTop: 4 }}><span style={{ fontSize: 10.5, color: K.muted, marginRight: 2 }}>副图</span>{[['macd', 'MACD'], ['kdj', 'KDJ'], ['rsi', 'RSI'], ['atr', 'ATR'], ['obv', 'OBV']].map(([key, label]) => <button key={key} onClick={() => setSub(key)} style={{ padding: '2px 7px', fontSize: 10.5, borderRadius: 5, cursor: 'pointer', border: `1px solid ${sub === key ? 'var(--accent-blue)' : K.border}`, color: sub === key ? '#fff' : K.secondary, background: sub === key ? 'var(--accent-blue)' : K.panel }}>{label}</button>)}<span style={{ marginLeft: 'auto', fontSize: 10.5, color: K.muted }}><b style={{ color: '#d92d20' }}>● 强B买入</b>&nbsp;&nbsp;<b style={{ color: '#159447' }}>● S卖出</b></span></div> : <div style={{ fontSize: 11, color: K.muted, marginTop: 4 }}>周/月K仅展示真实聚合价格，技术副图使用日K口径查看。</div>}
  </div>;
}

const RET_LABELS = [['1日', 'ret_1d'], ['5日', 'ret_5d'], ['20日', 'ret_20d'], ['60日', 'ret_60d'], ['120日', 'ret_120d'], ['250日', 'ret_250d']];

export default function UsStockAnalysisPage() {
  const [params, setParams] = useSearchParams();
  const [symbol, setSymbol] = useState((params.get('symbol') || 'AAPL').toUpperCase());
  const [input, setInput] = useState((params.get('symbol') || 'AAPL').toUpperCase());
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [chartFrame, setChartFrame] = useState('day');
  const [watchlist, setWatchlist] = useState([]);
  const [sectorMap, setSectorMap] = useState({});
  const [positions, setPositions] = useState([]);
  // 盘前策略：实时盘前/盘中数据 + 大盘风向
  const [pmData, setPmData] = useState(null);
  const [pmSort, setPmSort] = useState('move'); // move=异动 up=涨幅 down=跌幅 vol=量能
  const [pmCollapsed, setPmCollapsed] = useState(false);
  const [sidebarTab, setSidebarTab] = useState('watchlist');
  const [showWorkspace, setShowWorkspace] = useState(false);
  const timerRef = useRef(null);

  const load = useCallback(async (sym) => {
    if (!sym) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(`/api/us-stock-analysis/overview?symbol=${encodeURIComponent(sym)}&news_limit=10`);
      if (res?.ok && res.data?.ok) {
        setData(res.data);
      } else {
        setData(null);
        setError(res?.data?.error || res?.error || '加载失败');
      }
    } catch {
      setData(null);
      setError('网络请求失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load(symbol);
    // 60s 自动刷新
    timerRef.current = setInterval(() => load(symbol), 60000);
    return () => clearInterval(timerRef.current);
  }, [symbol, load]);

  // 侧栏：自选池 + 盈立持仓
  useEffect(() => {
    apiFetch('/api/us-stock-analysis/watchlist').then((res) => {
      if (res?.ok && res.data?.ok) {
        setWatchlist(res.data.symbols || []);
        // 后端库内行业（盈立同步自动补采）优先，静态映射表兜底
        setSectorMap(res.data.sectors || {});
      }
    }).catch(() => {});
    apiFetch('/api/usmart-sync/positions').then((res) => {
      const list = res?.ok && Array.isArray(res.data) ? res.data : (res?.data?.positions || []);
      setPositions(list);
    }).catch(() => {});
  }, []);

  // 盘前策略：30s 轮询刷新（盘前数据变化快）
  useEffect(() => {
    const loadPm = () => {
      apiFetch('/api/us-stock-analysis/premarket').then((res) => {
        if (res?.ok && res.data?.ok) setPmData(res.data);
      }).catch(() => {});
    };
    loadPm();
    const t = setInterval(loadPm, 30000);
    return () => clearInterval(t);
  }, []);

  const submit = () => {
    const s = input.trim().toUpperCase();
    if (!s) return;
    setSymbol(s);
    setParams({ symbol: s }, { replace: true });
  };

  const q = data?.quote || {};
  const s = data?.stats || {};
  const history = data?.history || {};
  const displayName = q.name || usNameCN(symbol) || symbol;
  const isDown = (q.change ?? 0) < 0;
  const trendText = s.trend || '趋势待确认';
  const signalText = s.signal && s.signal !== '—' ? s.signal : '暂无均线交叉';
  const supertrendText = s.supertrend?.direction || '待计算';
  const rangeText = q.pct_52w_pos == null ? '52周位置待计算' : `位于52周区间 ${fmt(q.pct_52w_pos, 0)}%`;

  return (
    <div className="us-stock-analysis-page" style={{ width: '100%', maxWidth: 'none', boxSizing: 'border-box', padding: 'clamp(8px, 1vw, 16px)', margin: 0 }}>
      {/* ─── 顶栏：只保留检索与阅读控制 ─── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: K.text }}>个股研究</h2>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <input
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && submit()}
            list="us-symbol-list"
            placeholder="输入美股代码，如 MSFT"
            style={{
              width: 200, padding: '6px 10px', borderRadius: 8, fontSize: 13,
              border: `1px solid ${K.border}`, background: K.panel, color: K.text, outline: 'none',
            }}
          />
          <datalist id="us-symbol-list">
            {Object.keys(US_NAMES_CN).slice(0, 200).map((k) => (
              <option key={k} value={k}>{US_NAMES_CN[k]}</option>
            ))}
          </datalist>
          <button onClick={submit} style={{
            padding: '6px 14px', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
            background: 'var(--accent-blue)', color: '#fff', border: 'none',
          }}>查询</button>
          <button onClick={() => load(symbol)} style={{
            padding: '6px 12px', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            background: K.panel, color: K.secondary, border: `1px solid ${K.border}`,
          }}>⟳ 刷新</button>
          <button onClick={() => setShowWorkspace(v => !v)} style={{
            padding: '6px 12px', borderRadius: 8, fontSize: 13, cursor: 'pointer',
            background: showWorkspace ? K.hover : K.panel, color: K.secondary,
            border: `1px solid ${showWorkspace ? 'var(--accent-blue)' : K.border}`,
          }}>{showWorkspace ? '收起盘前策略' : '盘前策略'}</button>
        </div>
        {error && <span style={{ fontSize: 12, color: 'var(--accent-red)' }}>⚠ {error}</span>}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: K.muted }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', display: 'inline-block', background: 'var(--accent-green)', boxShadow: '0 0 6px var(--accent-green)' }} />
          数据库 · 截至 {history.data_as_of || '—'}
        </span>
      </div>

      <div className="us-analysis-shell" style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, clamp(220px, 22vw, 360px)) minmax(0, 1fr)', gap: 'clamp(10px, 1vw, 16px)', alignItems: 'start' }}>
        {/* ─── 左侧栏：自选/持仓均可点击切换右侧个股分析 ─── */}
        <div className="us-analysis-sidebar" style={{ minWidth: 0, position: 'sticky', top: 70, display: 'flex', flexDirection: 'column', gap: 12 }}>
          <Panel title="股票列表" extra={<span style={{ fontSize: 11, color: K.muted }}>{sidebarTab === 'watchlist' ? `${watchlist.length} 只` : `${positions.length} 只`}</span>}>
            <div style={{ display: 'flex', gap: 4, paddingBottom: 6, marginBottom: 2, borderBottom: `1px solid ${K.border}` }}>
              {[['watchlist', '⭐ 自选'], ['positions', '📱 持仓']].map(([tab, label]) => (
                <button key={tab} onClick={() => setSidebarTab(tab)} style={{
                  flex: 1, padding: '4px 6px', borderRadius: 6, cursor: 'pointer', fontSize: 11.5, fontWeight: 600,
                  border: `1px solid ${sidebarTab === tab ? 'var(--accent-blue)' : 'transparent'}`,
                  background: sidebarTab === tab ? K.hover : 'transparent', color: sidebarTab === tab ? 'var(--accent-blue)' : K.secondary,
                }}>{label}</button>
              ))}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 0, maxHeight: 'calc(100vh - 174px)', overflowY: 'auto' }}>
              {sidebarTab === 'watchlist' && watchlist.map((sym) => {
                const active = sym === symbol;
                const sector = sectorMap[sym] || usSectorCN(sym);
                return (
                  <button key={sym} onClick={() => { setSymbol(sym); setInput(sym); setParams({ symbol: sym }, { replace: true }); }} style={{
                      width: '100%', display: 'flex', alignItems: 'center', gap: 5, textAlign: 'left', cursor: 'pointer', minWidth: 0,
                      border: `1px solid ${active ? 'var(--accent-blue)' : 'transparent'}`,
                      background: active ? K.hover : 'transparent', borderRadius: 6, padding: '3px 7px', fontSize: 12,
                    }}>
                      <span style={{ color: active ? 'var(--accent-blue)' : K.text, fontWeight: active ? 700 : 500, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {usNameCN(sym) || sym}
                      </span>
                      <span style={{ color: K.muted, fontSize: 10, flexShrink: 0 }}>{sym}</span>
                      {/* 行业板块徽标 */}
                      {sector && (
                        <span style={{ fontSize: 9, color: K.muted, background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 4, padding: '0 3px', flexShrink: 0 }}>{sector}</span>
                      )}
                  </button>
                );
              })}
              {sidebarTab === 'watchlist' && !watchlist.length && <span style={{ fontSize: 12, color: K.muted }}>自选池为空</span>}
              {sidebarTab === 'positions' && positions.map((p) => {
                const active = p.symbol === symbol;
                const profit = p.hold_profit_pct ?? p.hold_profit;
                return (
                  <button key={p.symbol} onClick={() => { setSymbol(p.symbol); setInput(p.symbol); setParams({ symbol: p.symbol }, { replace: true }); }} style={{
                    textAlign: 'left', cursor: 'pointer', border: `1px solid ${active ? 'var(--accent-blue)' : 'transparent'}`,
                    background: active ? K.hover : 'transparent', borderRadius: 6, padding: '4px 7px',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <span style={{ color: active ? 'var(--accent-blue)' : K.text, fontSize: 12, fontWeight: active ? 700 : 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{p.name || p.symbol}</span>
                      <span style={{ marginLeft: 'auto', fontSize: 10, color: K.muted }}>{p.symbol}</span>
                    </div>
                    <div style={{ display: 'flex', gap: 6, marginTop: 2, fontSize: 10.5 }}>
                      <span style={{ color: K.secondary }}>×{fmt(p.quantity, 0)}</span>
                      <span style={{ color: pctColor(profit) }}>{profit != null ? `${profit > 0 ? '+' : ''}${fmt(profit, 2)}%` : '—'}</span>
                    </div>
                  </button>
                );
              })}
              {sidebarTab === 'positions' && !positions.length && <span style={{ fontSize: 12, color: K.muted }}>无持仓数据</span>}
            </div>
          </Panel>
        </div>

        {/* ─── 主区（个股分析详情） ─── */}
        <div className="us-analysis-detail" style={{ minWidth: 0, display: 'grid', gridTemplateColumns: 'repeat(12, minmax(0, 1fr))', gap: 'clamp(10px, 1vw, 16px)' }}>
          {/* ─── 盘前策略面板（盘前选股一目了然） ─── */}
          <Panel style={{ gridColumn: 'span 12', display: showWorkspace ? undefined : 'none' }} title="📊 数据库收盘观察" extra={(
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              {pmData?.session && (
                <span style={{
                  fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 5,
                  background: pmData.session === '盘中' ? 'rgba(0,200,83,.12)' : pmData.session === '盘前' ? 'rgba(64,158,255,.12)' : pmData.session === '盘后' ? 'rgba(156,39,176,.12)' : 'rgba(128,128,128,.12)',
                  color: pmData.session === '盘中' ? '#00c853' : pmData.session === '盘前' ? '#409eff' : pmData.session === '盘后' ? '#9c27b0' : '#909399',
                  border: `1px solid ${pmData.session === '盘中' ? 'rgba(0,200,83,.3)' : pmData.session === '盘前' ? 'rgba(64,158,255,.3)' : pmData.session === '盘后' ? 'rgba(156,39,176,.3)' : 'rgba(128,128,128,.3)'}`,
                }}>{pmData.session}</span>
              )}
              {pmData?.us_time && <span style={{ fontSize: 11, color: K.muted }}>{pmData.us_time}</span>}
              <span style={{ fontSize: 11, color: K.muted }}>{pmData?.sgt_time?.slice(11, 16)} 更新</span>
              {[['move', '异动'], ['up', '涨幅'], ['down', '跌幅'], ['vol', '量能']].map(([k, l]) => (
                <button key={k} onClick={() => setPmSort(k)} style={{
                  fontSize: 11, padding: '2px 8px', borderRadius: 5, cursor: 'pointer',
                  border: `1px solid ${pmSort === k ? 'var(--accent-blue)' : K.border}`,
                  background: pmSort === k ? 'var(--accent-blue)' : K.panel,
                  color: pmSort === k ? '#fff' : K.secondary,
                }}>{l}</button>
              ))}
              <button onClick={() => setPmCollapsed(v => !v)} style={{ fontSize: 11, padding: '2px 8px', borderRadius: 5, cursor: 'pointer', border: `1px solid ${K.border}`, background: K.panel, color: K.secondary }}>{pmCollapsed ? '展开' : '收起'}</button>
            </div>
          )}>
            {pmData ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                {/* 大盘风向标 */}
                <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 2 }}>
                  {(pmData.market || []).map(m => (
                    <span key={m.symbol} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, background: K.hover, borderRadius: 7, padding: '4px 10px' }}>
                      <span style={{ color: K.text, fontWeight: 600 }}>{m.symbol}</span>
                      <span style={{ color: (m.chg_pct ?? 0) >= 0 ? K.up : K.down, fontWeight: 700 }}>
                        {(m.chg_pct ?? 0) > 0 ? '+' : ''}{(m.chg_pct ?? 0)?.toFixed?.(2) ?? m.chg_pct}%
                      </span>
                      <span style={{ color: K.muted }}>{fmt(m.price)}</span>
                    </span>
                  ))}
                </div>
                {/* 自选池盘前列表（点击行切换个股分析） */}
                {!pmCollapsed && (
                  <div style={{ display: 'flex', flexDirection: 'column', maxHeight: 340, overflowY: 'auto' }}>
                    <div style={{ display: 'flex', gap: 8, fontSize: 10.5, color: K.muted, padding: '3px 8px' }}>
                      <span style={{ width: 18 }}>#</span>
                      <span style={{ flex: 1.3 }}>名称</span>
                      <span style={{ width: 62, textAlign: 'right' }}>盘前涨跌</span>
                      <span style={{ width: 58, textAlign: 'right' }}>现价</span>
                      <span style={{ width: 64, textAlign: 'right' }}>盘前量</span>
                      <span style={{ width: 96, textAlign: 'right' }}>盘前区间</span>
                      <span style={{ width: 70 }}>信号</span>
                    </div>
                    {(pmSort === 'move' ? [...(pmData.stocks || [])].sort((a, b) => Math.abs(b.chg_pct ?? 0) - Math.abs(a.chg_pct ?? 0))
                      : pmSort === 'up' ? [...(pmData.stocks || [])].sort((a, b) => (b.chg_pct ?? 0) - (a.chg_pct ?? 0))
                      : pmSort === 'down' ? [...(pmData.stocks || [])].sort((a, b) => (a.chg_pct ?? 0) - (b.chg_pct ?? 0))
                      : [...(pmData.stocks || [])].sort((a, b) => (b.vol ?? 0) - (a.vol ?? 0)))
                    .map((st, i) => {
                      const pct = st.chg_pct ?? 0;
                      const vol = st.vol ?? 0;
                      const volMed = (() => {
                        const vols = (pmData.stocks || []).map(s => s.vol || 0).filter(v => v > 0).sort((a, b) => a - b);
                        return vols.length ? vols[Math.floor(vols.length / 2)] : 0;
                      })();
                      const hotVol = volMed > 0 && vol > volMed * 3;
                      const thin = vol > 0 && vol < 1000;
                      const pos = st.pos_in_range;
                      const signals = [
                        hotVol ? '放量' : null,
                        thin ? '清淡' : null,
                        pos != null && pos >= 90 ? '贴高' : null,
                        pos != null && pos <= 10 ? '贴低' : null,
                      ].filter(Boolean);
                      return (
                        <div key={st.symbol} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, borderRadius: 6, padding: '4px 8px', cursor: 'pointer' }} onClick={() => { setSymbol(st.symbol); setInput(st.symbol); setParams({ symbol: st.symbol }, { replace: true }); }} onMouseEnter={(e) => e.currentTarget.style.background = K.hover} onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                          <span style={{ width: 18, color: K.muted, fontSize: 10.5 }}>{i + 1}</span>
                          <span style={{ flex: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            <span style={{ color: K.text, fontWeight: 600 }}>{usNameCN(st.symbol) || st.name || st.symbol}</span>
                            <span style={{ color: K.muted, fontSize: 10.5, marginLeft: 5 }}>{st.symbol}</span>
                          </span>
                          <span style={{ width: 62, textAlign: 'right', fontSize: 13, fontWeight: 700, color: pct > 0 ? K.up : pct < 0 ? K.down : K.muted }}>
                            {pct > 0 ? '+' : ''}{fmt(pct, 2)}%
                          </span>
                          <span style={{ width: 58, textAlign: 'right', color: K.text, fontWeight: 600 }}>{fmt(st.price)}</span>
                          <span style={{ width: 64, textAlign: 'right', color: vol > 0 ? K.text : K.muted }}>{vol > 0 ? fmtBig(Math.round(vol)) : '—'}</span>
                          <span style={{ width: 96, textAlign: 'right', color: K.muted, fontSize: 11 }}>{st.low != null ? `${fmt(st.low)} — ${fmt(st.high)}` : '—'}</span>
                          <span style={{ width: 70, display: 'flex', gap: 3 }}>
                            {signals.map(sg => (
                              <span key={sg} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 4, border: '1px solid ' + K.borderLight, color: sg === '放量' ? 'var(--accent-blue)' : K.muted, background: K.hover }}>{sg}</span>
                            ))}
                          </span>
                        </div>
                      );
                    })}
                    {!pmData.stocks?.length && <span style={{ fontSize: 12, color: K.muted, padding: 6 }}>数据库暂无已落库行情</span>}
                  </div>
                )}
              </div>
            ) : (
              <span style={{ fontSize: 12, color: K.muted }}>加载盘前数据…</span>
            )}
          </Panel>

          {/* 报价卡：先让读者确认标的、价格和市场位置 */}
          <Panel style={{ gridColumn: 'span 12' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 22, fontWeight: 800, color: K.text }}>{displayName}</span>
              {q.english_name && <span style={{ fontSize: 12, color: K.muted }}>{q.english_name}</span>}
              <span style={{ fontSize: 12, color: K.muted, border: `1px solid ${K.borderLight}`, borderRadius: 4, padding: '0 6px' }}>{symbol}</span>
              {q.currency && <span style={{ fontSize: 12, color: K.muted }}>{q.currency}</span>}
              <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end' }}>
                <span style={{ fontSize: 10.5, color: K.muted }}>外部行情</span>
                <a href={usTradingViewUrl(symbol)} target="_blank" rel="noreferrer" title="在 TradingView 查看当前股票" style={{ fontSize: 11, color: 'var(--accent-blue)', textDecoration: 'none', border: `1px solid ${K.borderLight}`, borderRadius: 5, padding: '2px 7px' }}>TradingView ↗</a>
                <a href={`https://stock.finance.sina.com.cn/usstock/quotes/${symbol}.html`} target="_blank" rel="noreferrer" title="在新浪财经查看当前股票" style={{ fontSize: 11, color: 'var(--accent-blue)', textDecoration: 'none', border: `1px solid ${K.borderLight}`, borderRadius: 5, padding: '2px 7px' }}>新浪 ↗</a>
                <a href={`https://www.google.com/finance/quote/${symbol}:NASDAQ`} target="_blank" rel="noreferrer" title="在谷歌财经查看当前股票" style={{ fontSize: 11, color: 'var(--accent-blue)', textDecoration: 'none', border: `1px solid ${K.borderLight}`, borderRadius: 5, padding: '2px 7px' }}>谷歌 ↗</a>
                <span style={{ fontSize: 11, color: K.muted, marginLeft: 4 }}>{q.time}</span>
              </span>
            </div>
            <div style={{ display: 'flex', alignItems: 'baseline', gap: 14, margin: '10px 0 12px' }}>
              <span style={{ fontSize: 40, fontWeight: 800, color: isDown ? K.down : K.up, lineHeight: 1 }}>
                {fmt(q.price)}
              </span>
              <span style={{ fontSize: 17, fontWeight: 700, color: pctColor(q.change) }}>
                {q.change != null && (q.change > 0 ? '+' : '')}{fmt(q.change)}
              </span>
              <span style={{ fontSize: 15, fontWeight: 600, color: pctColor(q.chg_pct) }}>
                {q.chg_pct != null && (q.chg_pct > 0 ? '+' : '')}{fmt(q.chg_pct, 2)}%
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, fontSize: 12, marginBottom: 10 }}>
              {[['今开', fmt(q.open)], ['最高', fmt(q.high)], ['最低', fmt(q.low)], ['昨收', fmt(q.prev_close)],
                ['成交量', fmtBig(q.volume)], ['成交额', fmtBig(q.amount)], ['市盈率 PE', fmt(q.pe, 1)], ['每股收益 EPS', fmt(q.eps, 2)]].map(([k, v]) => (
                <div key={k} style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                  <div style={{ color: K.muted, fontSize: 11 }}>{k}</div>
                  <div style={{ color: K.text, fontWeight: 600, fontSize: 13 }}>{v}</div>
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: K.muted }}>
              <span style={{ whiteSpace: 'nowrap' }}>52周区间</span>
              <div style={{ flex: 1 }}><RangeBar low={q.low_52w} high={q.high_52w} pos={q.pct_52w_pos} /></div>
              {q.low_52w != null && <span style={{ whiteSpace: 'nowrap', fontSize: 11 }}>{fmt(q.low_52w)} — {fmt(q.high_52w)}</span>}
            </div>
          </Panel>

          {/* 读盘摘要：把分散在技术卡里的核心判断提前展示 */}
          <Panel title="读盘摘要" style={{ gridColumn: 'span 12' }} extra={<span style={{ fontSize: 11, color: K.muted }}>先结论，后证据</span>}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
              {[
                ['趋势结构', trendText, signalText, trendText === '多头排列' ? K.up : trendText === '空头排列' ? K.down : K.gold],
                ['趋势跟踪', supertrendText, s.supertrend?.line != null ? `关键线 ${fmt(s.supertrend.line)}` : '关键线待计算', supertrendText === '多头' ? K.up : supertrendText === '空头' ? K.down : K.muted],
                ['价格位置', rangeText, q.low_52w != null ? `${fmt(q.low_52w)} — ${fmt(q.high_52w)}` : '52周区间待计算', K.accent],
                ['风险轮廓', s.max_dd_1y != null ? `年内最大回撤 ${fmt(s.max_dd_1y, 1)}%` : '回撤待计算', s.vol_annual != null ? `年化波动 ${fmt(s.vol_annual, 1)}%` : '波动待计算', s.max_dd_1y != null && s.max_dd_1y < -20 ? K.down : K.secondary],
              ].map(([label, value, note, color]) => (
                <div key={label} style={{ borderLeft: `3px solid ${color}`, background: K.hover, borderRadius: 8, padding: '9px 11px' }}>
                  <div style={{ fontSize: 11, color: K.muted }}>{label}</div>
                  <div style={{ marginTop: 3, fontSize: 14, fontWeight: 700, color }}>{value}</div>
                  <div style={{ marginTop: 3, fontSize: 11, color: K.secondary }}>{note}</div>
                </div>
              ))}
            </div>
          </Panel>

          {/* 区间收益：只保留不同时间尺度的方向判断 */}
          <Panel title="区间收益" style={{ gridColumn: 'span 12' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6, 1fr)', gap: 8 }}>
              {RET_LABELS.map(([l, key]) => <RetCell key={key} label={l} value={s[key]} />)}
            </div>
          </Panel>

          {/* 走势图 */}
          <Panel className="us-analysis-chart-panel" title="价格走势" style={{ gridColumn: 'span 12' }} extra={(
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 10.5, color: history.status === 'READY' ? K.muted : K.down }}>
                数据库 {history.bars ?? 0} 根{history.data_as_of ? ` · 截至 ${history.data_as_of}` : ''}
              </span>
              {CHART_TIMEFRAMES.map(([key, label]) => (
                <button key={key} onClick={() => setChartFrame(key)} style={{
                  fontSize: 11, padding: '3px 9px', borderRadius: 6, cursor: 'pointer',
                  border: `1px solid ${chartFrame === key ? 'var(--accent-blue)' : K.border}`,
                  background: chartFrame === key ? 'var(--accent-blue)' : K.panel,
                  color: chartFrame === key ? '#fff' : K.secondary,
                }}>{label}</button>
              ))}
            </div>
          )}>
            {history.status && history.status !== 'READY' ? (
              <div style={{ height: 310, display: 'flex', alignItems: 'center', justifyContent: 'center', color: K.muted, fontSize: 13 }}>
                {history.message || '数据库日线不足，无法绘制技术图'}
              </div>
            ) : (
              <Chart kline={s.kline || []} indicators={s.chart_indicators || {}} frame={chartFrame} intraday={data?.intraday || []} />
            )}
          </Panel>

          {/* 技术指标 */}
          <Panel className="us-analysis-tech-panel" title="技术指标" style={{ gridColumn: 'span 12' }} extra={(
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontSize: 10.5, color: history.status === 'READY' ? K.muted : K.down }}>
                {history.source === 'database' ? '数据库' : '—'} · {history.bars ?? 0} 根
              </span>
              <TrendBadge trend={s.trend} signal={s.signal} />
            </span>
          )}>
            <div className="us-analysis-tech-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 6 }}>
              {[['MA5', s.ma5], ['MA10', s.ma10], ['MA20', s.ma20], ['MA60', s.ma60], ['MA120', s.ma120], ['MA250', s.ma250]].map(([k, v]) => {
                const price = s.last_close;
                const pos = v != null && price != null ? (price / v - 1) * 100 : null;
                return (
                  <div key={k} style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                    <div style={{ fontSize: 11, color: K.muted }}>{k}</div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: K.text }}>
                      {fmt(v)}{pos != null && <span style={{ fontSize: 10, color: pctColor(pos), marginLeft: 4 }}>{pos >= 0 ? '+' : ''}{fmt(pos, 1)}%</span>}
                    </div>
                  </div>
                );
              })}
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>年化波动率</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: K.text }}>{s.vol_annual != null ? fmt(s.vol_annual, 1) + '%' : '—'}</div>
              </div>
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>1年最大回撤</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: pctColor(s.max_dd_1y) }}>{s.max_dd_1y != null ? fmt(s.max_dd_1y, 1) + '%' : '—'}</div>
              </div>
              {/* Supertrend(10,3) 趋势跟踪（InStock 思路） */}
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>Supertrend(10,3)</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: K.text }}>
                  {s.supertrend ? (
                    <>
                      <span style={{ color: s.supertrend.direction === '多头' ? K.up : K.down }}>{s.supertrend.direction}</span>
                      <span style={{ fontSize: 10, color: K.muted, marginLeft: 4 }}>{fmt(s.supertrend.line)}{s.supertrend.flip ? ` · ${s.supertrend.flip}` : ''}</span>
                    </>
                  ) : '—'}
                </div>
              </div>
              {/* STOCHRSI */}
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>STOCHRSI(14,14,3,3)</div>
                <div style={{ fontSize: 13, fontWeight: 600, color: K.text }}>
                  {s.stochrsi ? (
                    <>
                      <span>K {fmt(s.stochrsi.k, 1)}</span>
                      <span style={{ marginLeft: 6 }}>D {fmt(s.stochrsi.d, 1)}</span>
                      <span style={{ fontSize: 10, marginLeft: 6, fontWeight: 600, color: s.stochrsi.state === '超买' ? K.up : s.stochrsi.state === '超卖' ? K.down : K.gold }}>{s.stochrsi.state}</span>
                      {s.stochrsi.cross && <span style={{ fontSize: 10, marginLeft: 4, color: s.stochrsi.cross === '金叉' ? K.up : K.down }}>⚡{s.stochrsi.cross}</span>}
                    </>
                  ) : '—'}
                </div>
              </div>
              {[['MACD(12,26,9)', s.macd?.dif != null ? `DIF ${fmt(s.macd.dif, 3)} · DEA ${fmt(s.macd.dea, 3)}` : '数据不足'], ['KDJ(9,3,3)', s.kdj?.k != null ? `K ${fmt(s.kdj.k, 1)} · D ${fmt(s.kdj.d, 1)}` : '数据不足'], ['RSI(14)', s.rsi14 != null ? fmt(s.rsi14, 1) : '数据不足'], ['BOLL(20,2)', s.boll?.mid != null ? `中 ${fmt(s.boll.mid)} · 上 ${fmt(s.boll.upper)}` : '数据不足'], ['ATR(14)', s.atr14 != null ? fmt(s.atr14, 2) : '数据不足'], ['OBV', s.obv != null ? fmt(s.obv, 0) : '数据不足'], ['ADX/DMI(14)', s.adx?.adx != null ? `ADX ${fmt(s.adx.adx, 1)} · +DI ${fmt(s.adx.plus_di, 1)}` : '数据不足']].map(([label, value]) => (
                <div key={label} style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                  <div style={{ fontSize: 11, color: K.muted }}>{label}</div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: K.text, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>{value}</div>
                </div>
              ))}
              {/* BIAS 乖离率 */}
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>乖离率 BIAS</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: K.text }}>
                  <span style={{ color: pctColor(s.bias6) }}>6日 {fmt(s.bias6, 1)}%</span>
                  <span style={{ marginLeft: 8, color: pctColor(s.bias12) }}>12日 {fmt(s.bias12, 1)}%</span>
                  <span style={{ marginLeft: 8, color: pctColor(s.bias24) }}>24日 {fmt(s.bias24, 1)}%</span>
                </div>
              </div>
              {/* 筹码分布（成交量加权估算） */}
              <div style={{ background: K.hover, borderRadius: 8, padding: '7px 10px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>筹码分布（近1年）</div>
                <div style={{ fontSize: 12, fontWeight: 600, color: K.text }}>
                  {s.chip_profile ? (
                    <>
                      <span>获利盘 <b style={{ color: pctColor(s.chip_profile.profit_ratio - 50) }}>{fmt(s.chip_profile.profit_ratio, 0)}%</b></span>
                      <span style={{ marginLeft: 8 }}>成本 {fmt(s.chip_profile.avg_cost)}</span>
                      <span style={{ marginLeft: 8, color: K.muted }}>集中度 {fmt(s.chip_profile.concentration, 0)}%</span>
                    </>
                  ) : '—'}
                </div>
                {s.chip_profile && (
                  <div style={{ fontSize: 10.5, color: K.muted, marginTop: 3 }}>
                    主峰 {fmt(s.chip_profile.poc)}（{s.chip_profile.dist_to_poc >= 0 ? '上方压力' : '下方支撑'}{fmt(Math.abs(s.chip_profile.dist_to_poc), 1)}%）
                  </div>
                )}
              </div>
            </div>
            {/* K线形态（最近1-3根） */}
            {Array.isArray(s.patterns) && s.patterns.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 11, color: K.muted }}>K线形态</span>
                {s.patterns.map((p, i) => (
                  <span key={i} style={{ fontSize: 11, fontWeight: 600, padding: '2px 8px', borderRadius: 6,
                    background: p.side === 'bullish' ? 'rgba(216,80,74,0.12)' : p.side === 'bearish' ? 'rgba(59,154,46,0.12)' : 'rgba(136,135,128,0.12)',
                    color: p.side === 'bullish' ? K.up : p.side === 'bearish' ? K.down : K.secondary }}>
                    {p.side === 'bullish' ? '▲ ' : p.side === 'bearish' ? '▼ ' : ''}{p.name}
                  </span>
                ))}
              </div>
            )}
          </Panel>

          {/* 关键价位 */}
          <Panel title="关键价位" style={{ gridColumn: 'span 12' }}>
            <PriceLevelsCard
              market="us"
              symbol={symbol}
              dataStatus={history.status}
              dataAsOf={history.data_as_of}
              historyBars={history.bars}
              minRequiredBars={history.min_required_bars || 30}
            />
          </Panel>

          {/* 个股新闻 */}
          <Panel title="个股新闻" style={{ gridColumn: 'span 12' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 8 }}>
              {(data?.news || []).map((n, i) => (
                <a key={i} href={n.url} target="_blank" rel="noreferrer" style={{ display: 'block', textDecoration: 'none', background: K.hover, borderRadius: 8, padding: '9px 12px' }}>
                  <div style={{ fontSize: 13, color: K.text, fontWeight: 500, lineHeight: 1.4 }}>{n.title}</div>
                  <div style={{ fontSize: 11, color: K.muted, marginTop: 4 }}>
                    {n.time} · {n.src}
                  </div>
                </a>
              ))}
              {!data?.news?.length && <div style={{ fontSize: 13, color: K.muted }}>{data?.news_status?.message || '暂无已入库相关新闻'}</div>}
            </div>
          </Panel>
        </div>
      </div>

      {loading && (
        <div style={{ position: 'fixed', top: 70, right: 16, background: K.panel, border: `1px solid ${K.border}`, borderRadius: 8, padding: '6px 12px', fontSize: 12, color: K.muted, zIndex: 50 }}>
          加载中…
        </div>
      )}
    </div>
  );
}
