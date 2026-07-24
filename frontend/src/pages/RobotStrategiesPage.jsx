import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

export default function RobotStrategiesPage() {
  const [loading, setLoading] = useState(true);
  const [strategies, setStrategies] = useState([]);
  const [catalog, setCatalog] = useState([]);
  const [history, setHistory] = useState([]);
  const [activeTab, setActiveTab] = useState('signals');

  const loadData = useCallback(async () => {
    setLoading(true);
    const [sRes, cRes, hRes] = await Promise.all([
      apiFetch('/api/ops/robot-strategies'),
      apiFetch('/api/ops/strategy-catalog'),
      apiFetch('/api/ops/robot-strategies-history'),
    ]);
    if (sRes.ok) setStrategies(sRes.data?.strategies || sRes.data || []);
    if (cRes.ok) setCatalog(cRes.data?.catalog || cRes.data || []);
    if (hRes.ok) setHistory(hRes.data?.history || hRes.data || []);
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const tabs = [
    { key: 'signals', label: '当前信号' },
    { key: 'history', label: '历史记录' },
    { key: 'catalog', label: '策略目录' },
  ];

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>策略信号</h2>
        <button onClick={loadData} className="px-2 py-1 rounded border text-xs hover:opacity-80" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
      </div>

      <div className="flex gap-1 border-b pb-0" style={{ borderColor: 'var(--border-color)' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => setActiveTab(t.key)}
            className="px-3 py-1.5 text-xs rounded-t transition-colors"
            style={{ background: activeTab === t.key ? 'var(--bg-hover)' : 'transparent', color: activeTab === t.key ? 'var(--accent-blue)' : MUTED, borderBottom: activeTab === t.key ? '2px solid var(--accent-blue)' : '2px solid transparent' }}>
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === 'signals' && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          {strategies.length === 0 ? (
            <div className="text-xs" style={{ color: MUTED }}>暂无策略信号</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>策略</th>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>标的</th>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>信号</th>
                    <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((s, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{s.strategy_name || s.strategy || s.name || '—'}</td>
                      <td className="py-1.5 px-2 font-mono" style={{ color: 'var(--text-primary)' }}>{s.stock_code || s.code || s.symbol || '—'}</td>
                      <td className="py-1.5 px-2" style={{ color: s.signal === 'B' || s.signal === 'BUY' ? UP : s.signal === 'S' || s.signal === 'SELL' ? DOWN : 'var(--text-primary)' }}>{s.signal || '—'}</td>
                      <td className="py-1.5 px-2 text-right" style={{ color: MUTED }}>{s.timestamp || s.date || s.time || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'history' && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          {history.length === 0 ? (
            <div className="text-xs" style={{ color: MUTED }}>暂无历史记录</div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>策略</th>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>标的</th>
                    <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>信号</th>
                    <th className="text-right py-1.5 px-2" style={{ color: MUTED }}>时间</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h, i) => (
                    <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                      <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{h.strategy_name || h.strategy || '—'}</td>
                      <td className="py-1.5 px-2 font-mono" style={{ color: 'var(--text-primary)' }}>{h.stock_code || h.code || '—'}</td>
                      <td className="py-1.5 px-2" style={{ color: h.signal === 'B' || h.signal === 'BUY' ? UP : h.signal === 'S' || h.signal === 'SELL' ? DOWN : 'var(--text-primary)' }}>{h.signal || '—'}</td>
                      <td className="py-1.5 px-2 text-right" style={{ color: MUTED }}>{h.timestamp || h.date || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {activeTab === 'catalog' && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          {catalog.length === 0 ? (
            <div className="text-xs" style={{ color: MUTED }}>暂无策略目录</div>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {catalog.map((c, i) => (
                <div key={i} className="rounded p-2" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>
                  <div className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{c.name || c.key || c.id}</div>
                  <div className="text-[10px] mt-0.5" style={{ color: MUTED }}>{c.description || c.desc || ''}</div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
