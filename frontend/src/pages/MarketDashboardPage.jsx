/**
 * 市场仪表盘（Koyfin 风格深色总览）
 * 布局：中央面板网格 + 右侧 My Watchlist
 * 数据：/api/market-dashboard/overview（60s 缓存）
 */
import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { apiFetch } from '../utils/request';
import { usNameCN } from '../utils/usStockNames';
import { usTradingViewUrl, usSinaUrl } from '../utils/usStockExchange';

// ─── 全局框架色板（CSS 变量，随浅色/深色主题自动切换） ───────────────────────
const K = {
  bg: 'var(--bg-primary)',
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
};

const fmtPct = (v, digits = 2, sign = true) => {
  if (v == null || isNaN(Number(v))) return '—';
  const n = Number(v);
  if (n === 0) return '0.00%';
  const s = sign && n > 0 ? '+' : '';
  return `${s}${n.toFixed(digits)}%`;
};

const fmtNum = (v, digits = 2) => {
  if (v == null || isNaN(Number(v))) return '—';
  return Number(v).toFixed(digits);
};

const pctColor = (v) => {
  if (v == null || isNaN(Number(v))) return K.muted;
  return Number(v) > 0 ? K.up : Number(v) < 0 ? K.down : K.muted;
};

// ─── 通用小组件 ──────────────────────────────────────────────────────────────

const Panel = ({ title, icon, right, children, style }) => (
  <div style={{
    background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10,
    display: 'flex', flexDirection: 'column', minWidth: 0, ...style,
  }}>
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '10px 12px 8px', borderBottom: `1px solid ${K.border}`,
    }}>
      <span style={{ fontSize: 13, fontWeight: 700, color: K.text }}>
        {icon ? <span style={{ marginRight: 6 }}>{icon}</span> : null}{title}
      </span>
      {right}
    </div>
    <div style={{ padding: '6px 12px 10px', flex: 1, minWidth: 0 }}>{children}</div>
  </div>
);

const Row = ({ children, hover, onClick, style }) => (
  <div
    onClick={onClick}
    style={{
      display: 'flex', alignItems: 'center', gap: 8, padding: '5px 6px', borderRadius: 6,
      fontSize: 12, cursor: onClick ? 'pointer' : 'default',
      borderBottom: `1px solid ${K.border}`,
      ...(hover ? { background: 'var(--bg-hover)' } : {}),
      ...style,
    }}
  >
    {children}
  </div>
);

const Th = ({ w, children, right }) => (
  <div style={{
    width: w, flexShrink: 0, fontSize: 10.5, color: K.muted, fontWeight: 600,
    textAlign: right ? 'right' : 'left', letterSpacing: 0.3,
  }}>
    {children}
  </div>
);

// 迷你涨跌条
const MiniBar = ({ v, max }) => {
  if (v == null || isNaN(Number(v))) return <span style={{ color: K.muted, fontSize: 11 }}>—</span>;
  const n = Number(v);
  const w = Math.min(Math.abs(n) / (max || 1), 1) * 46;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, justifyContent: 'flex-end' }}>
      <span style={{ width: 46, height: 4, borderRadius: 2, background: 'var(--border-color)', overflow: 'hidden', display: 'inline-block' }}>
        <span style={{
          display: 'block', height: '100%', width: w,
          background: n >= 0 ? K.up : K.down, opacity: 0.85,
        }} />
      </span>
      <span style={{ color: pctColor(n), fontSize: 11, minWidth: 44, textAlign: 'right' }}>{fmtPct(n)}</span>
    </span>
  );
};

// ─── 标准化表现多线图（SVG） ────────────────────────────────────────────────

const CHART_RANGES = [
  ['1周', 5], ['1月', 21], ['3月', 63], ['6月', 126], ['1年', 250],
];

function MultiLineChart({ series, range, onRange }) {
  const W = 860, H = 300, PAD = { l: 10, r: 70, t: 14, b: 20 };

  const data = useMemo(() => {
    const n = CHART_RANGES.find(([k]) => k === range)?.[1] || 250;
    const out = [];
    for (const s of series) {
      const closes = (s.closes || []).filter(c => c != null && !isNaN(c)).slice(-n);
      if (closes.length < 2) continue;
      const base = closes[0] || 1;
      out.push({ name: s.name, color: s.color, values: closes.map(c => (c / base) * 100), closes });
    }
    return out;
  }, [series, range]);

  const { paths, grid, labels } = useMemo(() => {
    if (data.length === 0) return { paths: [], grid: [], labels: [] };
    let min = Infinity, max = -Infinity;
    for (const d of data) {
      for (const v of d.values) { min = Math.min(min, v); max = Math.max(max, v); }
    }
    if (!isFinite(min) || !isFinite(max) || min === max) { min = 90; max = 110; }
    const pad = (max - min) * 0.12 || 1;
    min -= pad; max += pad;
    const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
    const X = (i) => PAD.l + (data[0].values.length > 1 ? (i / (data[0].values.length - 1)) * iw : 0);
    const Y = (v) => PAD.t + (1 - (v - min) / (max - min)) * ih;

    const paths = data.map(d => ({
      ...d,
      d: d.values.map((v, i) => `${i === 0 ? 'M' : 'L'}${X(i).toFixed(1)},${Y(v).toFixed(1)}`).join(' '),
      lastX: X(d.values.length - 1),
      lastY: Y(d.values[d.values.length - 1]),
      ret: (d.closes[d.closes.length - 1] / d.closes[0] - 1) * 100,
      maxV: Math.max(...d.values), minV: Math.min(...d.values),
    }));

    const grid = [];
    for (let i = 0; i <= 4; i++) {
      const v = min + ((max - min) / 4) * i;
      const y = Y(v);
      grid.push({ y, label: `${(v - 100).toFixed(1)}%` });
    }
    const labels = paths.map(p => ({ ...p, endLabel: fmtPct(p.ret, 1) }));
    return { paths, grid, labels };
  }, [data, PAD.b, PAD.l, PAD.r, PAD.t]);

  if (data.length === 0) {
    return <div style={{ height: H, display: 'flex', alignItems: 'center', justifyContent: 'center', color: K.muted, fontSize: 12 }}>暂无足够数据</div>;
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 4, marginBottom: 6, flexWrap: 'wrap' }}>
        {CHART_RANGES.map(([k]) => (
          <button
            key={k}
            onClick={() => onRange(k)}
            style={{
              padding: '2px 10px', borderRadius: 4, fontSize: 11, cursor: 'pointer',
              background: k === range ? K.accent : 'var(--bg-hover)', color: k === range ? '#fff' : K.secondary,
              border: `1px solid ${k === range ? K.accent : K.border}`,
            }}
          >
            {k}
          </button>
        ))}
        <span style={{ marginLeft: 'auto', fontSize: 10.5, color: K.muted, alignSelf: 'center' }}>
          起始基准 = 100
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', display: 'block' }}>
        {grid.map((g, i) => (
          <g key={i}>
            <line x1={PAD.l} x2={W - PAD.r} y1={g.y} y2={g.y} stroke="var(--border-color)" strokeWidth={i === 4 ? 1 : 0.6} />
            <text x={W - PAD.r + 6} y={g.y + 3.5} fill={K.muted} fontSize={10}>{g.label}</text>
          </g>
        ))}
        {paths.map((p) => (
          <g key={p.name}>
            <path d={p.d} fill="none" stroke={p.color} strokeWidth={1.6} strokeLinejoin="round" />
            <circle cx={p.lastX} cy={p.lastY} r={3} fill={p.color} />
            <text x={p.lastX + 7} y={p.lastY + 3.5} fill={p.color} fontSize={11} fontWeight={700}>
              {p.endLabel}
            </text>
          </g>
        ))}
      </svg>
      <div style={{ display: 'flex', gap: 14, marginTop: 6, flexWrap: 'wrap' }}>
        {labels.map(l => (
          <span key={l.name} style={{ fontSize: 11, color: K.secondary, display: 'inline-flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: l.color, display: 'inline-block' }} />
            {l.name}
          </span>
        ))}
      </div>
    </div>
  );
}

// ─── 页面主体 ────────────────────────────────────────────────────────────────

const SERIES_COLORS = ['var(--accent-blue)', 'var(--accent-amber)', '#8b5cf6', 'var(--accent-green)', '#f97316', '#ec4899'];

export default function MarketDashboardPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [range, setRange] = useState('1Y');
  const [selected, setSelected] = useState(['SPX', 'IXIC', 'DJI']);
  const timerRef = useRef(null);

  const load = useCallback(async () => {
    try {
      const res = await apiFetch('/api/market-dashboard/overview', {}, 60000, 0);
      setData(res?.data || null);
      setError('');
    } catch (e) {
      setError(e?.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 60000);
    return () => clearInterval(timerRef.current);
  }, [load]);

  const indices = useMemo(() => data?.indices || [], [data?.indices]);
  const currencies = useMemo(() => data?.currencies || [], [data?.currencies]);
  const news = useMemo(() => data?.news || [], [data?.news]);
  const sectors = useMemo(() => data?.sectors || [], [data?.sectors]);
  const globalReturns = useMemo(() => data?.global_returns || [], [data?.global_returns]);
  const globalIdx = useMemo(() => data?.global_indices || [], [data?.global_indices]);
  const watchlist = useMemo(() => data?.watchlist || [], [data?.watchlist]);
  const compare = useMemo(() => data?.compare || [], [data?.compare]);

  // 对比图 series（只画勾选的指数）
  const chartSeries = useMemo(() => {
    const colorMap = {};
    compare.forEach((c, i) => { colorMap[c.code] = SERIES_COLORS[i % SERIES_COLORS.length]; });
    return compare
      .filter(c => selected.includes(c.code))
      .map(c => ({ name: `${c.name} ${c.code}`, color: colorMap[c.code], closes: (c.klines || []).map(k => k.close) }));
  }, [compare, selected]);

  const toggleSelect = (code) => {
    setSelected(prev => prev.includes(code) ? prev.filter(x => x !== code) : [...prev, code]);
  };

  // 行业动量（因子面板用）
  const sectorMomentum = useMemo(() => {
    const ranked = [...sectors].sort((a, b) => (b.ret_20d ?? -999) - (a.ret_20d ?? -999));
    return { top: ranked.slice(0, 6), bottom: ranked.slice(-3).reverse() };
  }, [sectors]);

  // 全球回报表：global_indices 行 + global_returns 匹配历史回报
  const returnsMap = useMemo(() => {
    const m = {};
    for (const r of globalReturns) {
      // .INX → SPX / .DJI → DJI / .IXIC → IXIC / hkHSI → HSI
      let key = r.code.startsWith('.') ? r.code.slice(1) : r.code.replace(/^hk/, '');
      if (key === 'INX') key = 'SPX';
      m[key] = r;
    }
    return m;
  }, [globalReturns]);

  const globalRows = useMemo(() => {
    return globalIdx.map(g => {
      const key = g.code.split('.')[1] || g.code; // US.SPX → SPX, JP.N225 → N225
      const rr = returnsMap[key];
      return {
        code: g.code, name: g.name, price: g.price, change_pct: g.change_pct,
        ret_1y: rr?.ret_1y, ret_3y: rr?.ret_3y, ret_5y: rr?.ret_5y,
      };
    });
  }, [globalIdx, returnsMap]);

  const idxRet20 = useMemo(() => {
    const m = {};
    for (const i of indices) m[i.code] = i.ret_20d;
    return m;
  }, [indices]);

  return (
    <div style={{
      background: K.bg, color: K.text, minHeight: '100vh', padding: '14px 16px 30px',
    }}>
      {/* 顶栏 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        <h1 style={{ margin: 0, fontSize: 19, fontWeight: 800, letterSpacing: 0.3 }}>
          <span style={{ color: K.accent }}>◆</span> Market Dashboard
        </h1>
        <span style={{ fontSize: 12, color: K.muted }}>
          {data?.updated_at ? `更新于 ${data.updated_at}` : '加载中…'}
        </span>
        {error && <span style={{ fontSize: 12, color: 'var(--accent-red)' }}>⚠ {error}</span>}
        <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6 }}>
          <span style={{
            width: 8, height: 8, borderRadius: '50%', display: 'inline-block',
            background: loading ? K.gold : K.green, boxShadow: `0 0 6px ${loading ? K.gold : K.green}`,
          }} />
          <span style={{ fontSize: 11.5, color: K.secondary }}>{loading ? '同步中' : '实时'}</span>
          <button
            onClick={load}
            disabled={loading}
            style={{
              marginLeft: 10, padding: '4px 14px', borderRadius: 6, fontSize: 12, cursor: 'pointer',
              background: 'var(--bg-hover)', color: K.text, border: `1px solid ${K.border}`,
            }}
          >
            ↻ 刷新
          </button>
        </span>
      </div>

      <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
        {/* 中央主区 */}
        <div style={{ flex: 1, minWidth: 0, display: 'grid', gridTemplateColumns: 'repeat(12, 1fr)', gap: 12 }}>

          {/* 美股指数 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="U.S. Stock Market" icon="📈">
              <Row style={{ borderBottom: `1px solid ${K.borderLight}`, paddingBottom: 4 }}>
                <span style={{ width: 20 }} />
                <span style={{ flex: 1, fontSize: 10.5, color: K.muted, fontWeight: 600 }}>指数</span>
                <Th w={62} right>价格</Th>
                <Th w={60} right>涨跌</Th>
                <Th w={62} right>涨跌幅%</Th>
              </Row>
              {indices.map(i => (
                <Row key={i.code} onClick={() => toggleSelect(i.code)}>
                  <span style={{
                    width: 14, height: 14, borderRadius: 3, border: `1.5px solid ${K.borderLight}`,
                    display: 'inline-flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
                    background: selected.includes(i.code) ? K.accent : 'transparent',
                  }}>
                    {selected.includes(i.code) && <span style={{ color: '#fff', fontSize: 10, lineHeight: 1 }}>✓</span>}
                  </span>
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 12 }}>
                    {i.name}
                    <span style={{ color: K.muted, fontWeight: 400, fontSize: 10, marginLeft: 6 }}>
                      20D {fmtPct(i.ret_20d, 1)}
                    </span>
                  </span>
                  <span style={{ width: 62, textAlign: 'right', fontSize: 12 }}>{fmtNum(i.price)}</span>
                  <span style={{ width: 60, textAlign: 'right', fontSize: 12, color: pctColor(i.change) }}>{fmtNum(i.change)}</span>
                  <span style={{ width: 62, textAlign: 'right', fontSize: 12, fontWeight: 700, color: pctColor(i.change_pct) }}>
                    {fmtPct(i.change_pct)}
                  </span>
                </Row>
              ))}
              <div style={{ fontSize: 10.5, color: K.muted, marginTop: 8, lineHeight: 1.5 }}>
                勾选指数可切换下方对比图 · 20D = 20 交易日表现
              </div>
            </Panel>
          </div>

          {/* 市场要闻 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="Market News" icon="📰" right={<span style={{ fontSize: 10.5, color: K.muted }}>东方财富要闻</span>}>
              {news.length === 0 && <div style={{ color: K.muted, fontSize: 12, padding: 10 }}>暂无新闻</div>}
              {news.map((n, i) => (
                <Row key={i} hover style={{ alignItems: 'flex-start', padding: '7px 6px' }}>
                  <div style={{ minWidth: 0 }}>
                    <a
                      href={n.url} target="_blank" rel="noreferrer"
                      style={{ color: K.text, textDecoration: 'none', fontSize: 12, lineHeight: 1.45, display: 'block' }}
                    >
                      {n.title}
                    </a>
                    <div style={{ marginTop: 3, fontSize: 10.5, color: K.muted }}>
                      {n.media} · {n.time}
                    </div>
                  </div>
                </Row>
              ))}
            </Panel>
          </div>

          {/* 货币 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="Currencies" icon="💱" right={<span style={{ fontSize: 10.5, color: K.muted }}>新浪外汇</span>}>
              {currencies.map(c => (
                <Row key={c.code}>
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 12 }}>{c.pair}</span>
                  <span style={{ color: K.muted, fontSize: 10.5 }}>{c.name}</span>
                  <span style={{ width: 76, textAlign: 'right', fontSize: 12 }}>{fmtNum(c.price, 4)}</span>
                  <span style={{ width: 72, textAlign: 'right', fontSize: 12, fontWeight: 700, color: pctColor(c.change_pct) }}>
                    {fmtPct(c.change_pct)}
                  </span>
                </Row>
              ))}
              <div style={{ fontSize: 10.5, color: K.muted, marginTop: 8 }}>数据为新浪外汇参考报价，延迟约 1-2 分钟</div>
            </Panel>
          </div>

          {/* 标准化表现对比图 */}
          <div style={{ gridColumn: 'span 12', minWidth: 0 }}>
            <Panel
              title="Standardized Performance" icon="📊"
              right={<span style={{ fontSize: 10.5, color: K.muted }}>基准 = 100 · 新浪美股日K</span>}
            >
              <MultiLineChart series={chartSeries} range={range} onRange={setRange} />
            </Panel>
          </div>

          {/* 行业板块 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="U.S. Stock Market Sectors" icon="🏭">
              <Row style={{ borderBottom: `1px solid ${K.borderLight}`, paddingBottom: 4 }}>
                <span style={{ flex: 1, fontSize: 10.5, color: K.muted, fontWeight: 600 }}>板块</span>
                <Th w={54} right>当日</Th>
                <Th w={54} right>5D</Th>
                <Th w={62} right>20D</Th>
              </Row>
              {sectors.map(s => (
                <Row key={s.etf}>
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 12 }}>
                    {s.name}
                    <span style={{ color: K.muted, fontWeight: 400, fontSize: 10, marginLeft: 5 }}>{s.etf}</span>
                  </span>
                  <span style={{ width: 54, textAlign: 'right', fontSize: 11.5, color: pctColor(s.change_pct) }}>{fmtPct(s.change_pct)}</span>
                  <span style={{ width: 54, textAlign: 'right', fontSize: 11.5, color: pctColor(s.ret_5d) }}>{fmtPct(s.ret_5d)}</span>
                  <span style={{ width: 62, textAlign: 'right', fontSize: 11.5, fontWeight: 700, color: pctColor(s.ret_20d) }}>{fmtPct(s.ret_20d)}</span>
                </Row>
              ))}
            </Panel>
          </div>

          {/* 因子 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="Equity Factors" icon="🧮" right={<span style={{ fontSize: 10.5, color: K.muted }}>行业 20D 动量</span>}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginBottom: 10 }}>
                {[['标普500', 'SPX'], ['纳斯达克100', 'NDX'], ['罗素2000', 'RUT']].map(([label, code]) => (
                  <div key={code} style={{ background: 'var(--bg-hover)', borderRadius: 8, padding: '8px 9px' }}>
                    <div style={{ fontSize: 10, color: K.muted }}>{label}</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: pctColor(idxRet20[code]), marginTop: 2 }}>
                      {fmtPct(idxRet20[code], 1)}
                    </div>
                  </div>
                ))}
              </div>
              <div style={{ fontSize: 10.5, color: K.muted, marginBottom: 4 }}>动量 TOP 6</div>
              {sectorMomentum.top.map((s, i) => (
                <Row key={s.etf} style={{ padding: '4px 6px' }}>
                  <span style={{ width: 18, color: K.gold, fontSize: 10.5, fontWeight: 700 }}>#{i + 1}</span>
                  <span style={{ flex: 1, fontSize: 12 }}>{s.name}</span>
                  <MiniBar v={s.ret_20d} max={Math.max(...sectors.map(x => Math.abs(x.ret_20d || 0)), 1)} />
                </Row>
              ))}
              <div style={{ fontSize: 10.5, color: K.muted, margin: '6px 0 4px' }}>弱势板块</div>
              {sectorMomentum.bottom.map(s => (
                <Row key={s.etf} style={{ padding: '4px 6px' }}>
                  <span style={{ width: 18, color: K.down, fontSize: 10.5, fontWeight: 700 }}>▼</span>
                  <span style={{ flex: 1, fontSize: 12 }}>{s.name}</span>
                  <MiniBar v={s.ret_20d} max={Math.max(...sectors.map(x => Math.abs(x.ret_20d || 0)), 1)} />
                </Row>
              ))}
            </Panel>
          </div>

          {/* 全球回报 */}
          <div style={{ gridColumn: 'span 4', minWidth: 0 }}>
            <Panel title="Global Returns" icon="🌍" right={<span style={{ fontSize: 10.5, color: K.muted }}>区间回报 %</span>}>
              <Row style={{ borderBottom: `1px solid ${K.borderLight}`, paddingBottom: 4 }}>
                <span style={{ flex: 1, fontSize: 10.5, color: K.muted, fontWeight: 600 }}>市场</span>
                <Th w={52} right>当日</Th>
                <Th w={52} right>1Y</Th>
                <Th w={52} right>3Y</Th>
                <Th w={52} right>5Y</Th>
              </Row>
              {globalRows.map(g => (
                <Row key={g.code}>
                  <span style={{ flex: 1, fontWeight: 600, fontSize: 12 }}>{g.name}</span>
                  <span style={{ width: 52, textAlign: 'right', fontSize: 11.5, color: pctColor(g.change_pct) }}>{fmtPct(g.change_pct)}</span>
                  <span style={{ width: 52, textAlign: 'right', fontSize: 11.5, color: pctColor(g.ret_1y) }}>{fmtPct(g.ret_1y, 1)}</span>
                  <span style={{ width: 52, textAlign: 'right', fontSize: 11.5, color: pctColor(g.ret_3y) }}>{fmtPct(g.ret_3y, 1)}</span>
                  <span style={{ width: 52, textAlign: 'right', fontSize: 11.5, color: pctColor(g.ret_5y) }}>{fmtPct(g.ret_5y, 1)}</span>
                </Row>
              ))}
              <div style={{ fontSize: 10.5, color: K.muted, marginTop: 8, lineHeight: 1.5 }}>
                1Y/3Y/5Y 基于日K计算；日经/欧洲市场暂缺历史回报
              </div>
            </Panel>
          </div>
        </div>

        {/* 右侧 My Watchlist */}
        <div style={{
          width: 290, flexShrink: 0, background: K.panel, border: `1px solid ${K.border}`,
          borderRadius: 10, display: 'flex', flexDirection: 'column', maxHeight: 'calc(100vh - 110px)',
          position: 'sticky', top: 14,
        }}>
          <div style={{
            padding: '10px 12px 8px', borderBottom: `1px solid ${K.border}`,
            display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          }}>
            <span style={{ fontSize: 13, fontWeight: 700 }}>⭐ My Watchlist</span>
            <span style={{ fontSize: 10.5, color: K.muted }}>{watchlist.length} 只</span>
          </div>
          <div style={{ overflowY: 'auto', flex: 1, padding: '4px 8px 8px' }}>
            {watchlist.length === 0 && (
              <div style={{ color: K.muted, fontSize: 12, padding: 12 }}>自选为空（US_WATCHLIST）</div>
            )}
            {watchlist.map(w => (
              <a
                key={w.symbol}
                href={usTradingViewUrl(w.symbol)}
                target="_blank" rel="noreferrer"
                style={{ textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 8, padding: '5.5px 6px', borderRadius: 6, borderBottom: `1px solid ${K.border}` }}
                onMouseEnter={e => { e.currentTarget.style.background = 'var(--bg-hover)'; }}
                onMouseLeave={e => { e.currentTarget.style.background = 'transparent'; }}
              >
                <span style={{ flex: 1, minWidth: 0 }}>
                  <span style={{ display: 'block', fontSize: 12, fontWeight: 700, color: K.text }}>{w.symbol}</span>
                  <span style={{ display: 'block', fontSize: 10, color: K.muted, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {usNameCN(w.symbol) || w.name || '—'}
                  </span>
                </span>
                <span style={{ width: 62, textAlign: 'right', fontSize: 12, color: K.secondary }}>{fmtNum(w.price)}</span>
                <span style={{ width: 56, textAlign: 'right', fontSize: 11.5, fontWeight: 700, color: pctColor(w.change_pct) }}>
                  {fmtPct(w.change_pct)}
                </span>
                <span
                  title="新浪财经美股行情"
                  onClick={e => e.stopPropagation()}
                  style={{ fontSize: 11, color: 'var(--accent-blue)', cursor: 'pointer', textDecoration: 'none', padding: '0 4px', fontWeight: 700 }}
                >
                  <a
                    href={usSinaUrl(w.symbol)}
                    target="_blank" rel="noreferrer"
                    onClick={e => e.stopPropagation()}
                    style={{ color: 'inherit', textDecoration: 'none' }}
                  >新浪</a>
                </span>
              </a>
            ))}
          </div>
        </div>
      </div>

      {/* 页脚说明 */}
      <div style={{ marginTop: 14, fontSize: 10.5, color: K.muted, lineHeight: 1.6 }}>
        数据源：腾讯行情（美股/港股指数实时 · 自选行情）· 新浪财经（外汇 · 美股日K · 全球指数）· 东方财富（市场要闻）。
        指数与个股行情存在时区差异（美股为最近收盘价）；页面每 60 秒自动刷新。
      </div>
    </div>
  );
}
