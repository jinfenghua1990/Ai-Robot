import { useState, useRef, useEffect } from 'react';

const SORTS = [
  { key: 'bs', label: 'B信号点', icon: '🔴', desc: '按最近B信号日期倒序' },
  { key: 'leader', label: '龙头强度', icon: '🔥', desc: '涨停+连板+涨幅综合' },
  { key: 'buyPower', label: '购买力评分', icon: '💰', desc: '100分制综合评估' },
  { key: 'changePct', label: '涨跌幅', icon: '📈', desc: '当日涨跌幅' },
  { key: 'heat', label: '板块热度', icon: '🌡', desc: '所属板块最新热度' },
];

/**
 * 排序下拉（仅负责排序，筛选请用 FilterBar）
 *  - 5 个排序键
 *  - asc / desc 切换
 */
export default function SortBar({ sortKey, sortDir, onChange, addLog }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const cur = SORTS.find(s => s.key === sortKey) || SORTS[0];

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1.5 hover:opacity-80"
        style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      >
        ↕ <span className="font-bold">{cur.icon} {cur.label}</span>
        <span style={{ color: 'var(--text-muted)' }}>{sortDir === 'desc' ? '↓' : '↑'}</span>
        <span style={{ color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 rounded-lg shadow-2xl min-w-[240px] p-2"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="text-[10px] mb-1 px-1" style={{ color: 'var(--text-muted)' }}>
            排序方式
          </div>
          {SORTS.map(s => (
            <div key={s.key} className="flex items-center gap-1 px-1 py-1 rounded hover:bg-white/5">
              <button
                onClick={() => { onChange(s.key); setOpen(false); }}
                className="flex-1 text-left text-[11px] px-1"
                style={{ color: s.key === sortKey ? '#60a5fa' : 'var(--text-primary)', fontWeight: s.key === sortKey ? 700 : 400 }}
              >
                {s.icon} {s.label} <span style={{ color: 'var(--text-muted)' }}>{s.desc}</span>
              </button>
              {s.key === sortKey && (
                <button
                  onClick={() => onChange(s.key, sortDir === 'desc' ? 'asc' : 'desc')}
                  className="px-1.5 py-0.5 text-[10px] rounded"
                  style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
                >
                  {sortDir === 'desc' ? '↓降序' : '↑升序'}
                </button>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export { SORTS };
