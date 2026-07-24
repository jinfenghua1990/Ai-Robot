import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

const MARKET_LABELS = { a_share: 'A股数据', hk: '港股数据', us: '美股数据' };

export default function DataCenterMarketPage({ market = 'a_share' }) {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);

  useEffect(() => {
    setLoading(true);
    const endpoint = market === 'hk' ? '/api/global-market/indices/hk' : market === 'us' ? '/api/global-market/indices/us' : '/api/main-hub/context';
    apiFetch(endpoint).then(res => {
      if (res.ok) setData(res.data);
    }).finally(() => setLoading(false));
  }, [market]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const indices = data?.indices || [];
  const title = MARKET_LABELS[market] || '市场数据';

  return (
    <div className="space-y-3">
      <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2>
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>指数概览</div>
        {indices.length === 0 ? (
          <div className="text-xs" style={{ color: MUTED }}>暂无数据</div>
        ) : (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {indices.map((idx, i) => (
              <div key={i} className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
                <div className="text-xs" style={{ color: MUTED }}>{idx.name || idx.code}</div>
                <div className="text-base font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{idx.price ?? '—'}</div>
                <div className="text-xs font-mono" style={{ color: (idx.change_pct ?? 0) >= 0 ? UP : DOWN }}>
                  {idx.change_pct != null ? `${idx.change_pct >= 0 ? '+' : ''}${Number(idx.change_pct).toFixed(2)}%` : '—'}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
      {data && (
        <details className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <summary className="text-xs cursor-pointer" style={{ color: MUTED }}>原始数据</summary>
          <pre className="text-[10px] mt-2 whitespace-pre-wrap overflow-auto max-h-96" style={{ color: 'var(--text-secondary)' }}>{JSON.stringify(data, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
