import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

function pctStr(v) { if (v == null || isNaN(v)) return '—'; return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`; }
function pctColor(v) { if (v == null || isNaN(v)) return MUTED; return Number(v) > 0 ? UP : Number(v) < 0 ? DOWN : MUTED; }

export default function MockTradingPage() {
  const [loading, setLoading] = useState(true);
  const [balance, setBalance] = useState(null);
  const [positions, setPositions] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [bRes, pRes] = await Promise.all([
      apiFetch('/api/mock-trading/balance'),
      apiFetch('/api/mock-trading/positions'),
    ]);
    if (bRes.ok) setBalance(bRes.data);
    if (pRes.ok) setPositions(pRes.data?.positions || pRes.data || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>模拟交易</h2>
        <button onClick={loadData} className="px-2 py-1 rounded border text-xs hover:opacity-80" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
      </div>

      {/* 账户总览 */}
      {balance && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>账户总览</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: MUTED }}>总资产</div>
              <div className="text-sm font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{balance.total_equity != null ? Number(balance.total_equity).toLocaleString() : '—'}</div>
            </div>
            <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: MUTED }}>持仓市值</div>
              <div className="text-sm font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{balance.total_market_value != null ? Number(balance.total_market_value).toLocaleString() : '—'}</div>
            </div>
            <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: MUTED }}>可用资金</div>
              <div className="text-sm font-bold font-mono" style={{ color: 'var(--text-primary)' }}>{balance.total_cash != null ? Number(balance.total_cash).toLocaleString() : '—'}</div>
            </div>
            <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: MUTED }}>浮动盈亏</div>
              <div className="text-sm font-bold font-mono" style={{ color: (balance.unrealized_pnl ?? 0) >= 0 ? UP : DOWN }}>{balance.unrealized_pnl != null ? `${balance.unrealized_pnl >= 0 ? '+' : ''}${Number(balance.unrealized_pnl).toLocaleString()}` : '—'}</div>
            </div>
          </div>
        </div>
      )}

      {/* 持仓明细 */}
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>持仓明细 ({positions.length})</div>
        {positions.length === 0 ? (
          <div className="text-xs" style={{ color: MUTED }}>暂无持仓</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>代码</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>名称</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>持仓</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>成本</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>现价</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>盈亏</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((p, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-1.5 px-2 font-mono" style={{ color: 'var(--text-primary)' }}>{p.code || p.stock_code || p.symbol || '—'}</td>
                    <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{p.name || p.stock_name || '—'}</td>
                    <td className="py-1.5 px-2 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{p.volume || p.quantity || p.shares || '—'}</td>
                    <td className="py-1.5 px-2 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{p.cost_price || p.avg_cost || '—'}</td>
                    <td className="py-1.5 px-2 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{p.current_price || p.price || '—'}</td>
                    <td className="py-1.5 px-2 text-right font-mono" style={{ color: pctColor(p.unrealized_pnl || p.pnl) }}>{pctStr(p.unrealized_pnl_pct || p.pnl_pct)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
