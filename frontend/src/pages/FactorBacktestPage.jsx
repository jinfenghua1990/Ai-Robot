/**
 * 因子回测评估页 —— 移植自 tickflow-stock-panel 的 backtest/factor.py
 * 功能：IC/IR 分析 + 分层回测净值 + 多空组合
 * market="a"（A股）/ "us"（美股）
 */
import { useCallback, useEffect, useState } from 'react';
import { apiFetch, formatApiError } from '../utils/request';

const MARKET_LABEL = { a: 'A股', us: '美股' };

// ── 通用 SVG 折线（多序列）──
function LineChart({ series, height = 160, width = 620 }) {
  const K = {
    up: 'var(--flow-up)', down: 'var(--flow-down)', blue: 'var(--accent-blue)',
    secondary: 'var(--text-secondary)', border: 'var(--border-light)', muted: 'var(--text-muted)',
  };
  // series: [{ name, color, data: [{date, value}] }]
  const all = series.flatMap((s) => s.data.map((d) => d.value)).filter((v) => v != null);
  if (all.length === 0) return <div style={{ fontSize: 11, color: K.muted, padding: 8 }}>暂无数据</div>;
  const min = Math.min(...all, 0), max = Math.max(...all);
  const pad = (max - min) * 0.08 || 1;
  const yMin = min - pad, yMax = max + pad;
  
  const idx = (i, len) => (len === 1 ? width / 2 : 8 + (i * (width - 16)) / (len - 1));
  const y = (v) => height - 14 - ((v - yMin) / (yMax - yMin || 1)) * (height - 28);
  return (
    <svg width="100%" viewBox={`0 0 ${width} ${height}`} style={{ display: 'block' }}>
      {/* 基准线 1.0 */}
      <line x1={8} x2={width - 8} y1={y(1)} y2={y(1)} stroke={K.border} strokeDasharray="4 3" strokeWidth="1" />
      <text x={width - 12} y={y(1) - 3} fontSize="9" fill={K.muted} textAnchor="end">1.0</text>
      {series.map((s) => (
        <g key={s.name}>
          <polyline
            points={s.data.map((d, i) => `${idx(i, s.data.length)},${y(d.value)}`).join(' ')}
            fill="none" stroke={s.color} strokeWidth={1.5} strokeLinejoin="round"
          />
        </g>
      ))}
    </svg>
  );
}

const fmtPct = (v) => (v == null ? '—' : `${v >= 0 ? '+' : ''}${(v * 100).toFixed(2)}%`);

export default function FactorBacktestPage({ market = 'a' }) {
  const [factors, setFactors] = useState([]);
  const [factor, setFactor] = useState('momentum_20d');
  const [start, setStart] = useState('');
  const [end, setEnd] = useState('');
  const [rebalance, setRebalance] = useState('monthly');
  const [nGroups, setNGroups] = useState(5);
  const [symbols, setSymbols] = useState('');
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const K = {
    panel: 'var(--bg-card)', border: 'var(--border-color)', borderLight: 'var(--border-light)',
    text: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)',
    up: 'var(--flow-up)', down: 'var(--flow-down)', blue: 'var(--accent-blue)',
    hover: 'var(--bg-hover)', red: 'var(--accent-red)',
  };

  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch('/api/factor-backtest/factors', {}, 15000);
        if (res?.ok && res.data?.ok && res.data.data?.length) {
          setFactors(res.data.data);
          setFactor(res.data.data[0].id);
        }
      } catch {}
    })();
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError('');
    setResult(null);
    try {
      const qs = new URLSearchParams({
        market, factor, rebalance, n_groups: String(nGroups),
        start, end, symbols,
      });
      const res = await apiFetch(`/api/factor-backtest/run?${qs}`, {}, 120000);
      if (res?.ok && res.data?.ok && res.data.data) {
        setResult(res.data.data);
      } else {
        setError(formatApiError(res.data?.error ?? res?.error, '回测失败'));
      }
    } catch (e) {
      setError(formatApiError(e, '回测失败'));
    } finally {
      setLoading(false);
    }
  }, [market, factor, start, end, rebalance, nGroups, symbols]);

  // 因子分组
  const groups = [];
  for (const f of factors) {
    let g = groups.find((x) => x.name === f.group);
    if (!g) { g = { name: f.group, items: [] }; groups.push(g); }
    g.items.push(f);
  }

  // 净值系列（分层）
  const navSeries = (result?.group_nav || []).length
    ? result.group_nav[0] && Object.keys(result.group_nav[0])
        .filter((k) => k.startsWith('Q'))
        .map((k) => ({
          name: k,
          color: k === `Q${result.group_nav[0] ? nGroups : 5}` ? K.up : K.secondary,
          data: result.group_nav.map((e) => ({ date: e.date, value: e[k] })),
        }))
    : [];
  const lsSeries = result?.long_short_nav?.length
    ? [{ name: '多空', color: K.blue, data: result.long_short_nav }]
    : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 1280, margin: '0 auto', padding: 12 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: K.text }}>
        因子回测评估 · {MARKET_LABEL[market]}
        <span style={{ fontSize: 11, fontWeight: 400, color: K.muted, marginLeft: 8 }}>
          移植自 tickflow-stock-panel 的 IC/IR + 分层 + 多空评估
        </span>
      </div>

      {/* 参数面板 */}
      <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12, display: 'flex', flexWrap: 'wrap', gap: 14, alignItems: 'center' }}>
        <div>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>因子</div>
          <select value={factor} onChange={(e) => setFactor(e.target.value)}
            style={{ background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }}>
            {groups.map((g) => (
              <optgroup key={g.name} label={g.name}>
                {g.items.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
              </optgroup>
            ))}
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>开始日期</div>
          <input type="date" value={start} onChange={(e) => setStart(e.target.value)}
            style={{ background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>结束日期</div>
          <input type="date" value={end} onChange={(e) => setEnd(e.target.value)}
            style={{ background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }} />
        </div>
        <div>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>调仓频率</div>
          <select value={rebalance} onChange={(e) => setRebalance(e.target.value)}
            style={{ background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }}>
            <option value="daily">每日</option>
            <option value="weekly">每周</option>
            <option value="monthly">每月</option>
          </select>
        </div>
        <div>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>分组数</div>
          <input type="number" min={2} max={10} value={nGroups}
            onChange={(e) => setNGroups(Math.max(2, Math.min(10, parseInt(e.target.value) || 5)))}
            style={{ width: 56, background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }} />
        </div>
        <div style={{ minWidth: 220 }}>
          <div style={{ fontSize: 11, color: K.muted, marginBottom: 4 }}>指定代码（逗号分隔，留空=候选池）</div>
          <input type="text" value={symbols} onChange={(e) => setSymbols(e.target.value)} placeholder="如 600519,000001"
            style={{ width: '100%', background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }} />
        </div>
        <button onClick={run} disabled={loading}
          style={{ padding: '8px 18px', borderRadius: 8, fontSize: 13, cursor: 'pointer', background: K.blue, color: '#fff', border: 'none', marginTop: 14 }}>
          {loading ? '回测中…' : '▶ 运行回测'}
        </button>
      </div>

      {error && <div style={{ fontSize: 12, color: K.red }}>{error}</div>}

      {result && (
        <>
          {/* IC / IR 指标卡 */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
            {[
              { label: 'Rank IC 均值', value: result.ic_mean == null ? '—' : result.ic_mean.toFixed(4), color: result.ic_mean >= 0 ? K.up : K.down },
              { label: 'IC 标准差', value: result.ic_std == null ? '—' : result.ic_std.toFixed(4), color: K.secondary },
              { label: 'IR（IC/σ）', value: result.ir == null ? '—' : result.ir.toFixed(4), color: (result.ir ?? 0) >= 0 ? K.up : K.down },
              { label: 'IC 胜率', value: result.ic_win_rate == null ? '—' : `${(result.ic_win_rate * 100).toFixed(1)}%`, color: K.secondary },
              { label: '样本日期数', value: result.n_dates ?? '—', color: K.secondary },
              { label: '样本股票数', value: result.n_symbols ?? '—', color: K.secondary },
              { label: '多空总收益', value: fmtPct(result.long_short_stats?.total_return), color: (result.long_short_stats?.total_return ?? 0) >= 0 ? K.up : K.down },
              { label: '多空回撤', value: fmtPct(result.long_short_stats?.max_drawdown), color: K.down },
            ].map((c) => (
              <div key={c.label} style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '10px 12px' }}>
                <div style={{ fontSize: 11, color: K.muted }}>{c.label}</div>
                <div style={{ fontSize: 17, fontWeight: 700, color: c.color }}>{c.value}</div>
              </div>
            ))}
          </div>

          {/* 分层净值 */}
          <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 4 }}>
              分层净值曲线
              <span style={{ fontSize: 11, fontWeight: 400, color: K.muted, marginLeft: 8 }}>
                {result.start} ~ {result.end} · {result.rebalance} 调仓 · Q1=最低组 Q{nGroups}=最高组（红色）
              </span>
            </div>
            <LineChart series={navSeries} height={200} />
          </div>

          {/* 多空 + 组统计 */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 4 }}>
                多空组合（多 {result.long_short_stats?.top_group} 空 {result.long_short_stats?.bottom_group}）
              </div>
              <LineChart series={lsSeries} height={150} />
            </div>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 4 }}>分组统计</div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
                <thead>
                  <tr style={{ color: K.muted, textAlign: 'left' }}>
                    {['组', '总收益', '年化', '最大回撤', '夏普', '胜率'].map((h) => <th key={h} style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}` }}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {(result.group_stats || []).map((s) => (
                    <tr key={s.group} style={{ color: K.text }}>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}` }}>{s.label}</td>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}`, color: s.total_return >= 0 ? K.up : K.down }}>{fmtPct(s.total_return)}</td>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}` }}>{fmtPct(s.annual_return)}</td>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}`, color: K.down }}>{fmtPct(s.max_drawdown)}</td>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}` }}>{s.sharpe}</td>
                      <td style={{ padding: '4px 6px', borderBottom: `1px solid ${K.borderLight}` }}>{`${(s.win_rate * 100).toFixed(0)}%`}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
          <div style={{ fontSize: 11, color: K.muted }}>
            耗时 {result.elapsed_ms}ms · IC 序列 {result.ic_series?.length || 0} 期（各调仓日截面 Spearman）
          </div>
        </>
      )}
    </div>
  );
}
