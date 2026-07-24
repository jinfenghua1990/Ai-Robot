import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

function pctStr(v) { if (v == null || isNaN(v)) return '—'; return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`; }
function pctColor(v) { if (v == null || isNaN(v)) return MUTED; return Number(v) > 0 ? UP : Number(v) < 0 ? DOWN : MUTED; }

export default function StrategyPositionPage() {
  const [loading, setLoading] = useState(true);
  const [waveData, setWaveData] = useState(null);
  const [poolData, setPoolData] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [waveRes, poolRes] = await Promise.all([
      apiFetch('/api/ops/monitor/pool'),
      apiFetch('/api/ops/watchlist'),
    ]);
    if (waveRes.ok) setWaveData(waveRes.data);
    if (poolRes.ok) setPoolData(poolRes.data?.items || poolRes.data || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const rows = waveData?.rows || waveData || [];
  const poolItems = Array.isArray(rows) ? rows : [];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>波段信号</h2>
        <button onClick={loadData} className="px-2 py-1 rounded border text-xs hover:opacity-80" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
      </div>

      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>波段监控池 ({poolItems.length})</div>
        {poolItems.length === 0 ? (
          <div className="text-xs" style={{ color: MUTED }}>暂无波段信号数据</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>代码</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>名称</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>波段状态</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>备注</th>
                </tr>
              </thead>
              <tbody>
                {poolItems.map((item, i) => {
                  const status = item.wave_status || item.status || '';
                  const isB = status.includes('B') || status === 'B';
                  const isS = status.includes('S') || status === 'S';
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td className="py-1.5 px-2 font-mono" style={{ color: 'var(--text-primary)' }}>{item.code || item.ts_code || item.stock_code || '—'}</td>
                      <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{item.name || '—'}</td>
                      <td className="py-1.5 px-2 font-medium" style={{ color: isB ? UP : isS ? DOWN : 'var(--text-primary)' }}>{status || '—'}</td>
                      <td className="py-1.5 px-2" style={{ color: MUTED }}>{item.note || item.remark || item.status_note || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
