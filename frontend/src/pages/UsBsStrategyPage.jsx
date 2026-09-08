import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { apiFetch, formatApiError } from '../utils/request';
import { usNameCN } from '../utils/usStockNames';
import { usSectorCN } from '../utils/usStockSectors';
import { usBusinessCN } from '../utils/usBusinessDescriptions';
import { toFiniteNumber } from '../utils/format';

const C = {
  card: 'var(--bg-card)', surface: 'var(--bg-surface)', primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)', muted: 'var(--text-muted)', border: 'var(--border-color)',
  blue: 'var(--accent-blue)', up: 'var(--flow-up)', down: 'var(--flow-down)', amber: 'var(--accent-amber)',
};

const STATUS = {
  strong_buy: ['强B触发', C.up], holding: ['强B持有中', C.blue],
  sell: ['S退出', C.down], watch: ['观察', C.muted],
};

const CHECK_LABELS = {
  ma_cross: 'MA5/20 当日金叉', kdj_cross: 'KDJ 当日金叉',
  macd_double_positive: 'MACD 柱体与 DIF 双确认', above_ma60: '价格站上 MA60',
  rsi_range: 'RSI14 位于 45–70', liquidity: '价格与成交额达标',
};
const CHECK_SHORT = [
  ['ma_cross', 'MA5/20金叉'], ['kdj_cross', 'KDJ金叉'],
  ['macd_double_positive', 'MACD双确认'], ['above_ma60', '站上MA60'],
  ['rsi_range', 'RSI 45–70'], ['liquidity', '成交额达标'],
];

function Card({ children, style }) {
  return <section style={{ background: C.card, border: `1px solid ${C.border}`, borderRadius: 12, padding: 14, ...style }}>{children}</section>;
}

function Metric({ label, value, note, color }) {
  return <Card><div style={{ fontSize: 11, color: C.muted }}>{label}</div><div style={{ marginTop: 5, fontSize: 23, fontWeight: 800, color: color || C.primary }}>{value}</div>{note && <div style={{ marginTop: 3, fontSize: 10.5, color: C.muted }}>{note}</div>}</Card>;
}

function money(value) {
  const n = toFiniteNumber(value);
  if (n == null) return '—';
  if (n >= 1e9) return `$${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(2)}M`;
  return `$${n.toLocaleString()}`;
}

const fixed = (value, digits = 2) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : n.toFixed(digits);
};

export default function UsBsStrategyPage() {
  const [metadata, setMetadata] = useState(null);
  const [input, setInput] = useState('AAPL');
  const [result, setResult] = useState(null);
  const [dailyData, setDailyData] = useState(null);
  const [dailyLoading, setDailyLoading] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const evaluate = useCallback(async (rawSymbol) => {
    const symbol = String(rawSymbol || '').trim().toUpperCase();
    if (!symbol) return;
    setLoading(true); setError('');
    try {
      const response = await apiFetch(`/api/us-bs-strategy/evaluate?symbol=${encodeURIComponent(symbol)}`, {}, 30000, 0);
      if (response.ok && response.data?.ok) setResult(response.data);
      else setError(formatApiError(response.data?.error ?? response.error, '计算失败'));
    } catch (err) {
      setError(formatApiError(err, '网络错误'));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadDaily = useCallback(async () => {
    setDailyLoading(true);
    try {
      const response = await apiFetch('/api/us-bs-strategy/daily', {}, 30000, 0);
      if (response.ok && response.data?.ok) setDailyData(response.data);
    } finally {
      setDailyLoading(false);
    }
  }, []);

  useEffect(() => {
    apiFetch('/api/us-bs-strategy/metadata', {}, 15000, 0).then((response) => {
      if (response.ok && response.data?.ok) setMetadata(response.data.strategy);
    });
    evaluate('AAPL');
    loadDaily();
  }, [evaluate, loadDaily]);

  const strategy = result?.strategy || metadata;
  const validation = strategy?.validation || {};
  const [statusLabel, statusColor] = STATUS[result?.status] || STATUS.watch;

  return (
    <div style={{ minHeight: '100%', color: C.primary }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div>
          <Link to="/us-market?tab=factors" style={{ fontSize: 11, color: C.blue, textDecoration: 'none' }}>← 返回因子库</Link>
          <h1 style={{ margin: '6px 0 2px', fontSize: 22, fontWeight: 850 }}>强 B/S 策略因子</h1>
          <div style={{ fontSize: 12, color: C.secondary }}>独立二级页面 · {strategy?.version || 'strong-v1'} · 数据库盘后快照</div>
        </div>
        <Link to={`/us-stock-analysis${result?.symbol ? `?symbol=${result.symbol}` : ''}`} style={{ padding: '7px 11px', border: `1px solid ${C.border}`, borderRadius: 8, color: C.secondary, textDecoration: 'none', fontSize: 12 }}>打开个股分析 ↗</Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', gap: 8, marginBottom: 10 }}>
        <Metric label="历史胜率" value={`${((validation.win_rate || 0) * 100).toFixed(2)}%`} note={`${validation.samples || 0} 笔交易 · 已计交易摩擦`} color={C.up} />
        <Metric label="平均收益" value={`${((validation.avg_return || 0) * 100).toFixed(2)}%`} note="B 到 S 的完整交易" />
        <Metric label="时间留出胜率" value={`${((validation.time_holdout_win_rate || 0) * 100).toFixed(2)}%`} note="最后阶段未参与筛选" />
        <Metric label="退出规则" value="8% / 30日" note="先触发者执行" color={C.amber} />
      </div>

      <Card style={{ marginBottom: 10 }}>
        <form onSubmit={(event) => { event.preventDefault(); evaluate(input); }} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <input value={input} onChange={(event) => setInput(event.target.value.toUpperCase())} placeholder="输入美股代码"
            style={{ width: 180, padding: '7px 10px', borderRadius: 8, border: `1px solid ${C.border}`, background: C.surface, color: C.primary, fontSize: 12 }} />
          <button disabled={loading} style={{ padding: '7px 13px', border: 0, borderRadius: 8, background: C.blue, color: '#fff', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}>{loading ? '计算中…' : '从数据库评估'}</button>
          <span style={{ fontSize: 11, color: C.muted }}>仅读取 us_stock_daily 数据库 · 不现场拉取行情</span>
        </form>
        {error && <div style={{ marginTop: 8, color: C.down, fontSize: 12 }}>{error}</div>}
      </Card>

      <Card style={{ marginBottom: 10, padding: 0, overflow: 'hidden' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '11px 14px', borderBottom: `1px solid ${C.border}` }}>
          <div><b style={{ fontSize: 14 }}>盘后 B/S 选中列表</b><span style={{ marginLeft: 8, fontSize: 11, color: C.muted }}>{dailyData?.trade_date ? `最新交易日 ${dailyData.trade_date}` : '等待盘后快照'}</span><span style={{ marginLeft: 8, fontSize: 11, color: C.muted }}>· {dailyData?.count ?? 0} 只</span></div>
          <button onClick={loadDaily} disabled={dailyLoading} style={{ padding: '5px 9px', border: `1px solid ${C.border}`, borderRadius: 7, background: C.surface, color: C.secondary, fontSize: 11, cursor: 'pointer' }}>{dailyLoading ? '读取中…' : '刷新'}</button>
        </div>
        <div style={{ padding: '8px 14px', display: 'flex', gap: 14, flexWrap: 'wrap', borderBottom: `1px solid ${C.border}`, color: C.muted, fontSize: 10.5 }}>
          <span><b style={{ color: C.up }}>● B</b> 强 B 买入 · 持有中</span>
          <span><b style={{ color: C.down }}>● S</b> 卖出 · 当日退出</span>
          <span>来源：{dailyData?.source === 'database' ? '数据库快照' : '—'}</span>
        </div>
        {!dailyData?.items?.length ? <div style={{ padding: 22, textAlign: 'center', color: C.muted, fontSize: 12 }}>{dailyLoading ? '正在读取数据库盘后结果…' : '暂无盘后选中标的，等待美股收盘后计算'}</div> : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
              <thead><tr style={{ color: C.muted, textAlign: 'right', background: C.surface }}>
                <th style={{ textAlign: 'left', padding: '8px 14px' }}>股票</th><th style={{ padding: '8px' }}>信号</th><th style={{ padding: '8px' }}>状态值</th><th style={{ padding: '8px' }}>收盘价</th><th style={{ padding: '8px' }}>涨跌幅</th><th style={{ padding: '8px' }}>成交量</th><th style={{ padding: '8px', minWidth: 210 }}>条件</th><th style={{ textAlign: 'left', padding: '8px 14px' }}>行业</th><th style={{ padding: '8px 14px' }}>操作</th>
              </tr></thead>
              <tbody>{dailyData.items.map((item) => { const buy = item.side === 'B'; const color = buy ? C.up : C.down; return <tr key={item.symbol} style={{ borderTop: `1px solid ${C.border}` }}>
                <td style={{ padding: '8px 14px', maxWidth: 260 }}><div style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}><b style={{ whiteSpace: 'nowrap' }}>{usNameCN(item.symbol) || item.name || item.symbol}</b><span style={{ color: C.muted, whiteSpace: 'nowrap' }}>{item.symbol}</span></div><div title={item.name || ''} style={{ marginTop: 2, color: C.secondary, fontSize: 10, lineHeight: 1.25, overflowWrap: 'anywhere' }}>{usBusinessCN(item.symbol) || item.sector || usSectorCN(item.symbol) || '主营信息待补全'}</div></td>
                <td style={{ padding: 8, textAlign: 'right' }}><span title={buy ? '强 B 买入' : 'S 卖出'} style={{ padding: '2px 7px', borderRadius: 999, color, background: `${color}18`, fontWeight: 800 }}>{item.side} · {buy ? '强B持有' : '今日退出'}</span></td>
                <td style={{ padding: 8, textAlign: 'right', color, fontFamily: 'monospace' }}>{item.factor_value > 0 ? '+1' : '-1'}</td>
                <td style={{ padding: 8, textAlign: 'right', fontFamily: 'monospace' }}>{item.close == null ? '—' : `$${fixed(item.close, 2)}`}</td>
                <td style={{ padding: 8, textAlign: 'right', color: item.change_pct == null ? C.muted : item.change_pct >= 0 ? C.up : C.down, fontFamily: 'monospace' }}>{item.change_pct == null ? '—' : `${toFiniteNumber(item.change_pct) >= 0 ? '+' : ''}${fixed(item.change_pct, 2)}%`}</td>
                <td style={{ padding: 8, textAlign: 'right', color: C.secondary }}>{item.volume == null ? '—' : item.volume.toLocaleString()}</td>
                <td style={{ padding: 8 }}><div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(92px, 1fr))', gap: '2px 6px' }}>{CHECK_SHORT.map(([key, label]) => { const pass = item.checks?.[key]; return <span key={key} title={CHECK_LABELS[key]} style={{ color: pass ? C.up : C.muted, whiteSpace: 'nowrap', fontSize: 10 }}>{pass ? '✓' : '×'} {label} <span style={{ fontSize: 9 }}>{pass ? '通过' : '未触发'}</span></span>; })}</div></td>
                <td style={{ padding: '8px 14px', color: C.secondary }}>{item.sector || usSectorCN(item.symbol) || usBusinessCN(item.symbol) || '行业待补全 / N/A'}</td>
                <td style={{ padding: '8px 14px', textAlign: 'right' }}><Link target="_blank" rel="noreferrer" to={`/us-stock-analysis?symbol=${item.symbol}`} style={{ color: C.blue, textDecoration: 'none' }}>个股分析 ↗</Link></td>
              </tr>; })}</tbody>
            </table>
          </div>
        )}
      </Card>

      {result && <>
        <div style={{ display: 'grid', gridTemplateColumns: '1.15fr .85fr', gap: 10, marginBottom: 10 }}>
          <Card>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10 }}>
              <div><b style={{ fontSize: 17 }}>{result.symbol}</b><span style={{ marginLeft: 8, fontSize: 11, color: C.muted }}>{result.trade_date}</span></div>
              <span style={{ padding: '4px 9px', borderRadius: 999, background: `${statusColor}18`, color: statusColor, fontSize: 12, fontWeight: 800 }}>{statusLabel}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0,1fr))', gap: 8 }}>
              {[['收盘价', fixed(result.latest_values?.close, 2)], ['RSI14', fixed(result.latest_values?.rsi14, 2)], ['20日平均成交额', money(result.latest_values?.avg_dollar_volume_20d)]].map(([label, value]) => <div key={label} style={{ padding: 9, borderRadius: 8, background: C.surface }}><div style={{ fontSize: 10.5, color: C.muted }}>{label}</div><div style={{ marginTop: 4, fontSize: 15, fontWeight: 750 }}>{value || '—'}</div></div>)}
            </div>
            {result.entry && <div style={{ marginTop: 10, padding: 10, borderRadius: 8, background: `${C.blue}10`, fontSize: 11.5, color: C.secondary }}>入场 {result.entry.entry_date} · ${result.entry.entry_price} · 目标 ${result.entry.target_price} · 已持有 {result.entry.held_sessions} 日 · 当前 {result.entry.return_pct}%</div>}
          </Card>

          <Card>
            <div style={{ fontSize: 13, fontWeight: 800, marginBottom: 8 }}>今日条件</div>
            <div style={{ display: 'grid', gap: 6 }}>
              {Object.entries(CHECK_LABELS).map(([key, label]) => { const pass = Boolean(result.checks?.[key]); return <div key={key} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: 11.5 }}><span style={{ color: C.secondary }}>{label}</span><b style={{ color: pass ? C.up : C.muted }}>{pass ? '通过' : '未触发'}</b></div>; })}
            </div>
          </Card>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 800, marginBottom: 8 }}>强 B 入场规则</div>
            {(strategy?.entry_rules || []).map((rule, index) => <div key={rule} style={{ padding: '5px 0', borderBottom: `1px solid ${C.border}`, fontSize: 11.5, color: C.secondary }}>{index + 1}. {rule}</div>)}
          </Card>
          <Card>
            <div style={{ fontSize: 13, fontWeight: 800, marginBottom: 8 }}>最近 B/S 事件</div>
            {(result.signals || []).length === 0 ? <div style={{ color: C.muted, fontSize: 12 }}>近500根K线没有强 B/S 事件</div> : (result.signals || []).slice().reverse().map((signal) => <div key={`${signal.date}-${signal.side}`} style={{ display: 'grid', gridTemplateColumns: '78px 28px 1fr', gap: 8, padding: '6px 0', borderBottom: `1px solid ${C.border}`, fontSize: 11.5 }}><span style={{ color: C.muted }}>{signal.date}</span><b style={{ color: signal.side === 'B' ? C.up : C.down }}>{signal.side}</b><span style={{ color: C.secondary }}>{signal.reason}</span></div>)}
          </Card>
        </div>
      </>}
    </div>
  );
}
