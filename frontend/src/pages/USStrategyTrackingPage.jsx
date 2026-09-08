import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../utils/request';
import { simplifyUSName, usNameCN } from '../utils/usStockNames';

const fmt = (value, digits = 1) => value == null ? '—' : `${Number(value) > 0 ? '+' : ''}${Number(value).toFixed(digits)}%`;
const money = (value) => value == null ? '—' : `$${Number(value).toFixed(2)}`;
const color = (value) => Number(value) > 0 ? 'var(--flow-up)' : Number(value) < 0 ? 'var(--flow-down)' : 'var(--text-muted)';
const strategyLabel = (value) => ({
  daily_decision: '每日决策',
  strategy_us_bs_strong: 'B/S 强势',
}[value] || value || '策略命中');

function stockDisplay(row) {
  const symbol = String(row.symbol || '').toUpperCase();
  const chinese = usNameCN(symbol);
  const shortEnglish = simplifyUSName(row.name).replace(/[,.\s]+$/, '');
  const short = chinese || (shortEnglish && shortEnglish.length <= 18 ? shortEnglish : symbol);
  const ticker = short.toUpperCase() === symbol ? '' : symbol;
  return { short, ticker, fullName: row.name || symbol };
}

function SummaryCard({ label, value, tone = 'var(--text-primary)' }) {
  return <div className="strategy-track-summary-card">
    <span>{label}</span>
    <strong style={{ color: tone }}>{value}</strong>
  </div>;
}

export default function USStrategyTrackingPage() {
  const [data, setData] = useState({ rows: [], summary: {} });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    const res = await apiFetch('/api/us-strategy-track/list?status=all', {}, 15000, 0);
    if (res.ok) setData(res.data || { rows: [], summary: {} });
    else setError(String(res.error || '跟踪数据加载失败'));
    setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);

  const run = async (path) => {
    setBusy(true);
    setMsg('');
    const res = await apiFetch(path, { method: 'POST' }, 30000, 0);
    setMsg(res.ok
      ? (path.endsWith('/pool') ? `已加入 ${res.data?.added || 0} 只今日策略命中股票` : `已更新 ${res.data?.updated || 0} 条日线记录`)
      : String(res.error || '操作失败'));
    await load();
    setBusy(false);
  };

  const summary = data.summary || {};
  const rows = data.rows || [];
  const successTone = summary.win_rate == null ? 'var(--text-muted)' : summary.win_rate >= 50 ? 'var(--flow-up)' : 'var(--flow-down)';
  const returnTone = summary.avg_return_pct == null ? 'var(--text-muted)' : color(summary.avg_return_pct);

  return <main className="strategy-tracking-page" style={{ color: 'var(--text-primary)' }}>
    <header className="strategy-track-header">
      <div>
        <div className="strategy-track-title-row"><span className="strategy-track-mark">30D</span><h1>每日策略跟踪</h1><span className="strategy-track-subtitle">D1–D30 逐日观察</span></div>
        <p>策略命中后固定入选价，连续跟踪 30 个交易日；胜率只统计已完成样本。</p>
      </div>
      <div className="strategy-track-actions">
        <button disabled={busy} onClick={() => run('/api/us-strategy-track/pool')} className="strategy-track-primary">{busy ? '处理中…' : '加入今日命中'}</button>
        <button disabled={busy} onClick={() => run('/api/us-strategy-track/daily-update')} className="strategy-track-secondary">更新日线</button>
      </div>
    </header>

    {msg && <div className="strategy-track-message">{msg}</div>}
    {error && <div className="strategy-track-error">{error}</div>}

    <div className="strategy-track-summary">
      <SummaryCard label="总样本" value={summary.total ?? 0} />
      <SummaryCard label="进行中" value={summary.active ?? 0} tone="var(--accent-blue)" />
      <SummaryCard label="已完成" value={summary.completed ?? 0} />
      <SummaryCard label="完成样本胜率" value={summary.win_rate == null ? '—' : `${summary.win_rate}%`} tone={successTone} />
      <SummaryCard label="完成样本平均收益" value={summary.avg_return_pct == null ? '—' : fmt(summary.avg_return_pct)} tone={returnTone} />
    </div>

    <div className="strategy-track-note">统计口径：完成样本 = 已走完 D30；未完成的 {summary.active ?? 0} 条只展示过程，不计入胜率。</div>

    <section className="strategy-track-table-shell">
      <div className="strategy-track-table-head">
        <div><strong>30 日逐日跟踪</strong><span>单元格为累计收益 · 悬停查看收盘价和当日收益</span></div>
        <span>{rows.length} 条样本</span>
      </div>
      <div className="strategy-track-table-scroll">
        <table className="strategy-track-table">
          <thead><tr>
            <th className="strategy-track-stock-col sticky left-0 z-[3]">股票</th>
            <th className="strategy-track-strategy-col">来源</th>
            <th className="strategy-track-entry-col">入选日 / 入选价</th>
            <th className="strategy-track-progress-col">进度 / 最新</th>
            <th className="strategy-track-return-col">累计收益</th>
            {Array.from({ length: 30 }, (_, index) => <th key={index} className="strategy-track-day-col">D{index + 1}</th>)}
            <th className="strategy-track-status-col sticky right-0 z-[3]">状态</th>
          </tr></thead>
          <tbody>
            {rows.map((row) => {
              const daily = new Map((row.daily || []).map((item) => [item.day_n, item]));
              const progress = Math.min(30, row.daily?.length || 0);
              const progressLabel = progress ? `D${progress}/30` : '待首日';
              const stock = stockDisplay(row);
              return <tr key={row.id}>
                <td className="strategy-track-stock-col sticky left-0 z-[2]" style={{ background: 'var(--bg-card)' }} title={stock.fullName}>
                  <div className="strategy-track-stock-name"><b>{stock.short}</b>{stock.ticker && <span>{stock.ticker}</span>}</div>
                  <div className="strategy-track-stock-meta">{row.pool_date} · {row.status === 'active' ? '跟踪中' : '已完成'}</div>
                </td>
                <td className="strategy-track-strategy-col"><span className="strategy-track-source">{strategyLabel(row.strategy)}</span></td>
                <td className="strategy-track-entry-col"><div className="strategy-track-cell-stack"><b>{row.pool_date}</b><span>{money(row.entry_price)}</span></div></td>
                <td className="strategy-track-progress-col" title={progress ? `已归档 ${progress} 个交易日` : '入选后尚未归档首个交易日线'}><div className="strategy-track-cell-stack"><b>{progressLabel}</b><div className="strategy-track-progress"><i style={{ width: `${progress / 30 * 100}%` }} /></div><span>{money(row.latest_price)}</span></div></td>
                <td className="strategy-track-return-col" style={{ color: color(row.latest_return_pct) }}>{fmt(row.latest_return_pct)}</td>
                {Array.from({ length: 30 }, (_, index) => {
                  const item = daily.get(index + 1);
                  return <td key={index} className="strategy-track-day-col" title={item ? `D${index + 1} · ${item.trade_date} · 收盘 ${money(item.close)} · 当日 ${fmt(item.daily_return_pct)}` : `D${index + 1} 尚未跟踪`} style={{ color: item ? color(item.cum_return_pct) : 'var(--text-muted)', background: item ? 'var(--bg-hover)' : undefined }}>{item ? fmt(item.cum_return_pct) : '—'}</td>;
                })}
                <td className="strategy-track-status-col sticky right-0 z-[2]" style={{ background: 'var(--bg-card)' }}><span className={row.status === 'active' ? 'strategy-track-active' : 'strategy-track-complete'}>{row.status === 'active' ? '● 进行中' : '✓ 已完成'}</span></td>
              </tr>;
            })}
          </tbody>
        </table>
        {loading && <div className="strategy-track-empty">正在读取 30 日跟踪快照…</div>}
        {!loading && !error && !rows.length && <div className="strategy-track-empty">暂无跟踪样本；盘后运行“加入今日命中”后开始记录。</div>}
      </div>
    </section>
  </main>;
}
