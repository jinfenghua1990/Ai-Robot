import { useState, useRef, useEffect } from 'react';

/**
 * 筛选栏（独立于分组和排序）
 * 专注：按条件过滤股票列表，不负责归类或排序
 *
 * 当前筛选条件：
 *  - 拒绝震荡：隐藏 CHOPPY 状态股票（只留 TREND/IMPULSE）
 *  - 信号过滤：按 B/S 信号筛选
 *  - 板块升温：所属板块热度上升
 */
const FILTERS = [
  { key: 'junk', label: '拒绝震荡', icon: '〰️', desc: '隐藏CHOPPY状态，只留趋势/主升' },
  { key: 'buyOnly', label: '仅可买', icon: '🔴', desc: '只显示B信号股票' },
  { key: 'heating', label: '板块升温', icon: '🔥', desc: '所属板块热度上升' },
  { key: 'hit_yuzi', label: '游资命中', icon: '🎯', desc: '2+游资共振净买入' },
  { key: 'hit_strategy', label: '策略命中', icon: '🤖', desc: '量化策略今日命中' },
  { key: 'hit_trend', label: '趋势命中', icon: '📈', desc: '多头排列/底部突破' },
  { key: 'hit_capital', label: '资金命中', icon: '💰', desc: '主力净流入创30天新高' },
  { key: 'hit_popularity', label: '人气命中', icon: '🔥', desc: '板块爆发涨停≥5' },
  { key: 'hit_support', label: '承接命中', icon: '🛡️', desc: '昨日上榜今日V反' },
  { key: 'hit_accumulation', label: '吸筹命中', icon: '🧲', desc: '股东户数减少筹码集中' },
];

export default function FilterBar({ activeFilters, onToggle, addLog }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const activeCount = FILTERS.filter(f => activeFilters[f.key]).length;

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1.5 hover:opacity-80"
        style={{
          background: activeCount > 0 ? 'rgba(59,130,246,0.12)' : 'var(--bg-hover)',
          border: `1px solid ${activeCount > 0 ? '#3b82f6' : 'var(--border-color)'}`,
          color: activeCount > 0 ? '#3b82f6' : 'var(--text-primary)',
        }}
      >
        <span>🔍</span>
        <span className="font-bold">筛选</span>
        {activeCount > 0 && (
          <span className="px-1 rounded text-[10px]" style={{ background: '#3b82f6', color: '#fff' }}>
            {activeCount}
          </span>
        )}
        <span style={{ color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 rounded-lg shadow-2xl min-w-[260px] p-2"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="text-[10px] mb-1 px-1" style={{ color: 'var(--text-muted)' }}>
            筛选条件（独立于分组和排序）
          </div>
          {FILTERS.map(f => (
            <label
              key={f.key}
              className="flex items-center gap-1.5 px-1 py-1.5 rounded cursor-pointer hover:bg-white/5"
              style={{ color: activeFilters[f.key] ? '#3b82f6' : 'var(--text-primary)' }}
            >
              <input
                type="checkbox"
                checked={!!activeFilters[f.key]}
                onChange={(e) => onToggle(f.key, e.target.checked)}
              />
              <span className="text-[12px]">{f.icon}</span>
              <span className="text-[11px] font-bold">{f.label}</span>
              <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>{f.desc}</span>
            </label>
          ))}
          {activeCount > 0 && (
            <button
              onClick={() => FILTERS.forEach(f => onToggle(f.key, false))}
              className="mt-1 w-full text-[10px] py-1 rounded hover:opacity-80"
              style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}
            >
              清除全部筛选
            </button>
          )}
        </div>
      )}
    </div>
  );
}
