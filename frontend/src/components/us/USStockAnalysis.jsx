import { useEffect, useState, useMemo } from 'react';
import { apiFetch } from '../../utils/request';
import { usNameCN } from '../../utils/usStockNames';


// 配色与项目其他美股组件保持一致
const C = {
  card: 'var(--bg-card)',
  surface: 'var(--bg-surface)',
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  blue: 'var(--accent-blue)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  amber: 'var(--accent-amber)',
};

// 收盘价折线图（内联 SVG，无外部依赖）
function CloseLineChart({ closes }) {
  const W = 720, H = 200, PAD = 8;
  if (!closes || closes.length < 2) {
    return <div style={{ color: C.muted, fontSize: 13, padding: '24px 0', textAlign: 'center' }}>暂无足够历史数据绘制走势</div>;
  }
  const min = Math.min(...closes), max = Math.max(...closes);
  const span = max - min || 1;
  const stepX = (W - PAD * 2) / (closes.length - 1);
  const pts = closes.map((v, i) => {
    const x = PAD + i * stepX;
    const y = PAD + (1 - (v - min) / span) * (H - PAD * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const up = closes[closes.length - 1] >= closes[0];
  const color = up ? C.up : C.down;
  return (
    <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ display: 'block' }}>
      <polyline points={pts.join(' ')} fill="none" stroke={color} strokeWidth="1.6" />
      <text x={PAD} y={H - 2} fontSize="10" fill={C.muted}>{min.toFixed(2)}</text>
      <text x={W - PAD} y={H - 2} fontSize="10" fill={C.muted} textAnchor="end">{max.toFixed(2)}</text>
    </svg>
  );
}

function FactorTable({ values }) {
  if (!values || !Object.keys(values).length) {
    return <div style={{ color: C.muted, fontSize: 13 }}>暂无因子数据</div>;
  }
  const entries = Object.entries(values);
  return (
    <div style={{ maxHeight: 320, overflowY: 'auto', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 6 }}>
      {entries.map(([k, v]) => {
        const label = k.replace(/^value_/, '').replace(/_/g, ' ');
        const num = typeof v === 'number' ? v : parseFloat(v);
        const txt = Number.isFinite(num) ? (Math.abs(num) >= 1000 ? num.toFixed(0) : num.toFixed(4)) : String(v);
        // 0~1 区间因子画个迷你条
        const bar = Number.isFinite(num) && num >= 0 && num <= 1
          ? <span style={{ display: 'inline-block', width: 40, height: 5, borderRadius: 3, background: C.borderLight, marginLeft: 6, verticalAlign: 'middle', overflow: 'hidden' }}>
              <span style={{ display: 'block', width: `${Math.round(num * 100)}%`, height: '100%', background: C.blue }} />
            </span>
          : null;
        return (
          <div key={k} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: 12, padding: '4px 8px', borderRadius: 6, background: C.surface, border: `1px solid ${C.borderLight}` }}>
            <span style={{ color: C.secondary, textTransform: 'capitalize' }}>{label}</span>
            <span style={{ color: C.primary, fontVariantNumeric: 'tabular-nums', fontWeight: 600 }}>{txt}{bar}</span>
          </div>
        );
      })}
    </div>
  );
}

function SignalList({ signals }) {
  if (!signals || !signals.length) {
    return <div style={{ color: C.muted, fontSize: 13 }}>该股当前暂无有效信号</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {signals.map((s) => {
        const isBuy = /buy|long|做多/i.test(s.signal_type || '');
        const tagColor = isBuy ? C.up : /sell|short|做空/i.test(s.signal_type || '') ? C.down : C.amber;
        return (
          <div key={s.id} style={{ padding: '10px 12px', borderRadius: 10, background: C.surface, border: `1px solid ${C.borderLight}` }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontWeight: 700, color: C.primary }}>{s.strategy}</span>
              <span style={{ fontSize: 11, padding: '2px 8px', borderRadius: 999, color: tagColor, background: 'rgba(127,127,127,0.12)' }}>{s.signal_type}</span>
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, fontSize: 12, color: C.secondary }}>
              <span>评分 <b style={{ color: C.primary }}>{s.score != null ? s.score.toFixed(1) : '—'}</b></span>
              <span>计划入场 <b style={{ color: C.primary }}>{s.planned_entry != null ? s.planned_entry.toFixed(2) : '—'}</b></span>
              <span>计划止损 <b style={{ color: C.down }}>{s.planned_stop != null ? s.planned_stop.toFixed(2) : '—'}</b></span>
              <span>期望盈亏比 <b style={{ color: C.primary }}>{s.expected_rr != null ? s.expected_rr.toFixed(2) : '—'}</b></span>
              <span>状态 <b style={{ color: C.muted }}>{s.lifecycle_status}</b></span>
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default function USStockAnalysis({ code }) {
  const [klines, setKlines] = useState(null);
  const [factors, setFactors] = useState(null);
  const [signals, setSignals] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    const sym = encodeURIComponent(code);
    Promise.all([
      apiFetch(`/api/us-quant/klines?symbol=${sym}&days=120`, {}, 15000, 0),
      apiFetch(`/api/us-quant/factors/values?symbol=${sym}`, {}, 15000, 0),
      apiFetch('/api/us-quant/signals?status=ALL', {}, 15000, 0),
    ]).then(([kRes, fRes, sRes]) => {
      if (!alive) return;
      setKlines(kRes.ok && kRes.data ? (kRes.data.klines || []) : []);
      setFactors(fRes.ok && fRes.data ? (fRes.data.values || {}) : {});
      const all = (sRes.ok && sRes.data && (sRes.data.signals || sRes.data.candidates)) || [];
      setSignals(all.filter((x) => String(x.symbol || '').toUpperCase() === String(code).toUpperCase()));
      setLoading(false);
    }).catch(() => { if (alive) { setLoading(false); setKlines([]); setFactors({}); setSignals([]); } });
    return () => { alive = false; };
  }, [code]);

  const closes = useMemo(() => (klines || []).map((k) => k.close).filter((v) => v != null), [klines]);
  const first = closes[0], last = closes[closes.length - 1];
  const chgPct = first && last != null ? ((last - first) / first) * 100 : null;
  const up = chgPct != null && chgPct >= 0;
  const name = usNameCN(code);

  if (loading) {
    return <div style={{ padding: 24, color: C.muted, fontSize: 14 }}>加载 {code} 美股分析数据…</div>;
  }

  return (
    <div style={{ maxWidth: 1080, margin: '0 auto', padding: '16px 20px 32px', minHeight: '100vh', background: C.surface, color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, marginBottom: 4 }}>
        <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800 }}>{code}</h1>
        {name && <span style={{ fontSize: 14, color: C.secondary }}>{name}</span>}
        <span style={{ fontSize: 12, color: C.muted, marginLeft: 'auto' }}>美股 · US</span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 12, marginBottom: 16 }}>
        <span style={{ fontSize: 26, fontWeight: 800, color: up ? C.up : C.down }}>
          {last != null ? last.toFixed(2) : '—'}
        </span>
        {chgPct != null && (
          <span style={{ fontSize: 14, color: up ? C.up : C.down }}>
            {up ? '+' : ''}{chgPct.toFixed(2)}% <span style={{ color: C.muted, fontSize: 12 }}>(近 {closes.length} 交易日)</span>
          </span>
        )}
      </div>

      <Section title="价格走势（收盘价）" icon="📈">
        <CloseLineChart closes={closes} />
      </Section>

      <Section title={`因子评分（${factors ? Object.keys(factors).length : 0} 项）`} icon="🧮">
        <FactorTable values={factors} />
      </Section>

      <Section title={`当前信号（${signals ? signals.length : 0} 条）`} icon="🎯">
        <SignalList signals={signals} />
      </Section>

      <p style={{ color: C.muted, fontSize: 12, marginTop: 16 }}>
        数据来源：AIROBOT 美股量化系统（NeoData / 行情快照）。本页仅作分析展示，不构成投资建议。
      </p>
    </div>
  );
}

function Section({ title, icon, children }) {
  return (
    <section style={{ marginBottom: 16, padding: 14, borderRadius: 12, background: C.card, border: `1px solid ${C.borderLight}` }}>
      <div style={{ fontSize: 13, fontWeight: 700, marginBottom: 10, color: C.blue }}>{icon} {title}</div>
      {children}
    </section>
  );
}
