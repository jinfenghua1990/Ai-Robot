import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

function pctStr(v) { if (v == null || isNaN(v)) return '—'; return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`; }
function pctColor(v) { if (v == null || isNaN(v)) return MUTED; return Number(v) > 0 ? UP : Number(v) < 0 ? DOWN : MUTED; }

export default function ThemeReviewPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [date, setDate] = useState('');

  useEffect(() => {
    setLoading(true);
    const params = date ? `?date=${date}` : '';
    Promise.all([apiFetch(`/api/themes${params}`), apiFetch(`/api/fundflow${params}`)])
      .then(([tRes, fRes]) => setData({ themes: tRes.ok ? tRes.data : null, fundflow: fRes.ok ? fRes.data : null }))
      .finally(() => setLoading(false));
  }, [date]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const { themes, fundflow } = data || {};
  const sections = themes?.sections || themes?.theme_sections || [];
  const sectors = fundflow?.sectors || fundflow?.top_sectors || [];
  const COLORS = { main: { bg: 'rgba(239,68,68,0.06)', border: 'rgba(239,68,68,0.15)', color: '#ef4444', label: '主线' }, watch: { bg: 'rgba(234,179,8,0.06)', border: 'rgba(234,179,8,0.15)', color: '#eab308', label: '观察' }, alive: { bg: 'rgba(34,197,94,0.06)', border: 'rgba(34,197,94,0.15)', color: '#22c55e', label: '活口' } };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>题材复盘</h2>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className="px-2 py-1 rounded border text-xs" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
      </div>
      {sections.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>题材战场</div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {sections.map((sec, si) => {
              const style = COLORS[sec.type] || COLORS.main;
              const items = sec.items || sec.themes || [];
              return (
                <div key={si} className="rounded-md p-2" style={{ background: style.bg, border: `1px solid ${style.border}` }}>
                  <div className="text-xs font-bold mb-1.5" style={{ color: style.color }}>{style.label} ({items.length})</div>
                  <div className="space-y-1.5">
                    {items.map((item, ii) => (
                      <div key={ii} className="rounded p-1.5" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-medium truncate" style={{ color: 'var(--text-primary)' }}>{item.name}</span>
                          <span className="text-xs font-mono ml-2" style={{ color: pctColor(item.change) }}>{pctStr(item.change)}</span>
                        </div>
                        {item.strength != null && (
                          <div className="flex items-center gap-1 mt-1">
                            <div className="flex-1 h-1 rounded-full" style={{ background: 'var(--bg-surface)' }}>
                              <div className="h-1 rounded-full" style={{ width: `${Math.min(100, Math.max(0, item.strength))}%`, background: style.color }} />
                            </div>
                            <span className="text-[9px] font-mono" style={{ color: style.color }}>{item.strength}%</span>
                          </div>
                        )}
                        {(item.leader || item.judgment) && <div className="text-[9px] mt-0.5" style={{ color: MUTED }}>{item.leader && <span>龙头: {item.leader}</span>}{item.judgment && <span className="ml-2">{item.judgment}</span>}</div>}
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
      {sectors.length > 0 && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>板块资金流向</div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
            {sectors.slice(0, 20).map((s, i) => (
              <div key={i} className="flex items-center justify-between text-xs p-1 rounded" style={{ background: 'var(--bg-hover)' }}>
                <span className="truncate" style={{ color: 'var(--text-primary)' }}>{s.name || s.sector}</span>
                <span className="font-mono ml-1" style={{ color: (s.inflow ?? s.net_inflow ?? 0) >= 0 ? UP : DOWN }}>{(s.inflow != null ? (s.inflow/1e8).toFixed(1) : s.net_inflow != null ? (s.net_inflow/1e8).toFixed(1) : '—')}亿</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
