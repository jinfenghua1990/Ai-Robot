/**
 * 当日交易信号列表 — 支持 STRONG_BUY / WATCH_BUY / FORBID 切换
 */
import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';

const TABS = [
  { key: 'STRONG_BUY', label: '强买', color: '#ef4444' },
  { key: 'WATCH_BUY', label: '观察买', color: '#f97316' },
  { key: 'FORBID', label: '禁止', color: '#22c55e' },
];

export default function DailySignalList({ signals, summary, loading }) {
  const [tab, setTab] = useState('STRONG_BUY');
  const navigate = useNavigate();

  const filtered = useMemo(() => {
    if (!signals) return [];
    return signals.filter(s => s.signal_4 === tab);
  }, [signals, tab]);

  return (
    <div className="rounded-lg border p-3 space-y-2 flex flex-col"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', minHeight: 320 }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚡ 当日信号</h3>
        {summary && (
          <div className="text-[10px] flex gap-2" style={{ color: 'var(--text-muted)' }}>
            <span style={{ color: '#ef4444' }}>强买{summary.strong_buy}</span>
            <span style={{ color: '#f97316' }}>观察{summary.watch_buy}</span>
            <span style={{ color: '#22c55e' }}>禁{summary.forbid}</span>
          </div>
        )}
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-1 p-0.5 rounded-md" style={{ background: 'var(--bg-hover)' }}>
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className="flex-1 px-2 py-1 rounded text-[11px] font-medium transition-all"
            style={{
              background: tab === t.key ? 'var(--bg-card)' : 'transparent',
              color: tab === t.key ? t.color : 'var(--text-muted)',
              boxShadow: tab === t.key ? '0 1px 2px rgba(0,0,0,0.05)' : 'none',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 信号列表 */}
      <div className="flex-1 overflow-auto space-y-1.5" style={{ maxHeight: 280 }}>
        {loading && !signals ? (
          <div className="text-[11px] text-center py-4" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : filtered.length === 0 ? (
          <div className="text-[11px] text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无{tab === 'STRONG_BUY' ? '强买' : tab === 'WATCH_BUY' ? '观察买' : '禁止'}信号</div>
        ) : filtered.slice(0, 50).map(s => (
          <div
            key={s.ts_code}
            onClick={() => navigate(`/stock/${s.ts_code.split('.')[0]}`)}
            className="rounded-md border p-2 cursor-pointer hover:shadow-sm transition-all"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1.5 min-w-0">
                <span className="text-xs font-bold truncate" style={{ color: 'var(--text-primary)' }}>
                  {s.name}
                </span>
                <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
                  {s.ts_code.split('.')[0]}
                </span>
              </div>
              <span
                className="text-[10px] px-1.5 py-0.5 rounded font-bold flex-shrink-0"
                style={{ background: `${s.signal_color}22`, color: s.signal_color }}
              >
                {s.signal_label}
              </span>
            </div>

            <div className="flex items-center justify-between mt-1 text-[10px]">
              <span style={{ color: 'var(--text-muted)' }}>{s.sector}</span>
              <span style={{ color: 'var(--text-secondary)' }}>
                评分 <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{s.final_score?.toFixed(1)}</span>
              </span>
            </div>

            {s.signal_4 !== 'FORBID' && (
              <div className="flex items-center justify-between mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>仓位<span className="font-bold ml-0.5" style={{ color: 'var(--text-primary)' }}>{s.position_pct?.toFixed(1)}%</span></span>
                <span>止损<span className="font-bold ml-0.5" style={{ color: '#22c55e' }}>{s.stop_loss_pct?.toFixed(1)}%</span></span>
                <span>止盈<span className="font-bold ml-0.5" style={{ color: '#ef4444' }}>{s.take_profit_pct?.toFixed(1)}%</span></span>
              </div>
            )}

            {s.is_high_position && (
              <div className="mt-1 text-[10px] px-1.5 py-0.5 rounded inline-block"
                style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>
                ⚠ 高位股
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
