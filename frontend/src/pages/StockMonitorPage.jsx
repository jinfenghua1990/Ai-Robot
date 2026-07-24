import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

function pctStr(v) { if (v == null || isNaN(v)) return '—'; return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`; }
function pctColor(v) { if (v == null || isNaN(v)) return MUTED; return Number(v) > 0 ? UP : Number(v) < 0 ? DOWN : MUTED; }

export default function StockMonitorPage() {
  const [loading, setLoading] = useState(true);
  const [pool, setPool] = useState([]);
  const [quotes, setQuotes] = useState({});
  const [watchlist, setWatchlist] = useState([]);

  const loadData = useCallback(async () => {
    setLoading(true);
    const [poolRes, quotesRes, wlRes] = await Promise.all([
      apiFetch('/api/ops/monitor/pool'),
      apiFetch('/api/ops/realtime/quotes'),
      apiFetch('/api/ops/watchlist'),
    ]);
    if (poolRes.ok) setPool(poolRes.data?.rows || poolRes.data || []);
    if (quotesRes.ok) {
      const q = quotesRes.data?.quotes || quotesRes.data || {};
      if (Array.isArray(q)) {
        const map = {};
        q.forEach(item => { map[item.code || item.ts_code] = item; });
        setQuotes(map);
      } else { setQuotes(q); }
    }
    if (wlRes.ok) setWatchlist(wlRes.data?.items || wlRes.data || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>选股持仓</h2>
        <button onClick={loadData} className="px-2 py-1 rounded border text-xs hover:opacity-80" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
      </div>

      {/* 监控池 */}
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>监控池 ({pool.length})</div>
        {pool.length === 0 ? (
          <div className="text-xs" style={{ color: MUTED }}>暂无监控标的</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>代码</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>名称</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>现价</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>涨跌幅</th>
                  <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>状态</th>
                </tr>
              </thead>
              <tbody>
                {pool.map((item, i) => {
                  const code = item.code || item.ts_code || item.stock_code || '';
                  const q = quotes[code] || {};
                  return (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td className="py-1.5 px-2 font-mono" style={{ color: 'var(--text-primary)' }}>{code}</td>
                      <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{item.name || q.name || '—'}</td>
                      <td className="py-1.5 px-2 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{q.price || q.close || '—'}</td>
                      <td className="py-1.5 px-2 text-right font-mono" style={{ color: pctColor(q.change_pct || q.pct_chg) }}>{pctStr(q.change_pct || q.pct_chg)}</td>
                      <td className="py-1.5 px-2 text-right" style={{ color: MUTED }}>{item.status || item.wave_status || '—'}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* 自选股 */}
      {watchlist.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>自选股 ({watchlist.length})</div>
          <div className="flex flex-wrap gap-1.5">
            {watchlist.map((item, i) => {
              const code = item.code || item.ts_code || item.stock_code || '';
              const q = quotes[code] || {};
              return (
                <div key={i} className="rounded px-2 py-1 text-xs" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>
                  <span style={{ color: 'var(--text-primary)' }}>{item.name || code}</span>
                  <span className="font-mono ml-1.5" style={{ color: pctColor(q.change_pct || q.pct_chg) }}>{pctStr(q.change_pct || q.pct_chg)}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
