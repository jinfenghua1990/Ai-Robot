import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../utils/request';
import WatchlistResultsTable from '../components/WatchlistResultsTable';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';

const pct = (value) => value == null ? '—' : `${value >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`;

export default function MediumTermPage() {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    const { ok, data: result, error: message } = await apiFetch('/api/medium-term/overview');
    if (!ok) {
      setError(message || '中线策略快照读取失败');
      return;
    }
    setData(result);
  }, []);

  useEffect(() => { load(); }, [load]);

  if (!data) return <div className="flex h-64 items-center justify-center text-sm" style={{ color: MUTED }}>{error || '正在读取中线策略快照…'}</div>;
  if (data.status !== 'READY') return <div className="rounded-xl border p-5 text-sm" style={{ borderColor: 'var(--border-color)', color: MUTED }}>{data.message || '尚无中线策略快照'}</div>;

  const positions = data.target_positions || [];
  return (
    <div className="space-y-3 fade-in">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>中线趋势候选</h2>
          <p className="mt-1 text-xs" style={{ color: MUTED }}>数据日期 {data.data_as_of} · 规则 {data.rule_version} · 数据库快照</p>
        </div>
        <button type="button" onClick={load} className="rounded-lg border px-3 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新读取</button>
      </div>

      <div className="rounded-xl border px-4 py-3 text-sm" style={{ borderColor: 'rgba(59,130,246,0.3)', background: 'rgba(59,130,246,0.06)', color: 'var(--text-secondary)' }}>
        持有周期 20–60 个交易日 · 单行业最多 1 只 · 最多 5 只 · 仅纸面候选，不连接自动下单。
      </div>

      <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
        {[
          ['股票覆盖', data.coverage?.universe ?? 0],
          ['目标持仓', data.coverage?.selected ?? 0],
          ['目标现金', `${Number(data.cash_target_pct || 0).toFixed(0)}%`],
          ['每只目标仓位', positions[0]?.target_position_pct != null ? `${positions[0].target_position_pct}%` : '—'],
        ].map(([label, value]) => <div key={label} className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><div className="text-[11px]" style={{ color: MUTED }}>{label}</div><div className="mt-1 text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{value}</div></div>)}
      </div>

      <div className="overflow-x-auto rounded-xl border" style={{ borderColor: 'var(--border-color)' }}>
        <WatchlistResultsTable
          items={positions}
          viewModeKey="medium-term"
          defaultViewMode="table"
          loading={false}
          emptyText="暂无中线股票"
        />
      </div>
    </div>
  );
}
