import { useState, useRef, useEffect, useMemo } from 'react';

const STORAGE_KEY = 'panorama_concept_filter_selected';

/** 默认热门概念（首次使用时勾选） */
const DEFAULT_SELECTED = [
  '算力', '共封装光学CPO', '液冷', '人形机器人', '机器人概念',
  'AI应用', '核聚变', '商业航天', '低空经济', '固态电池',
  '铜缆高速连接', '车路云', '存储芯片', 'PCB概念', '人工智能',
];

export function loadSelectedConcepts() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr)) return arr;
    }
  } catch (e) { /* silent */ }
  return DEFAULT_SELECTED;
}

export function saveSelectedConcepts(arr) {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(arr)); } catch {}
}

/**
 * 概念板块多选筛选器
 * - 紧凑按钮「📋 筛选 (N) ▼」
 * - 下拉：搜索 + 复选框列表 + 全选/清空 + 概念中文释义
 * - 选中状态由父组件管理（localStorage 持久化）
 */
export default function ConceptSectorFilter({ allSectors, selected, onChange, descriptions = {} }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState('');
  const ref = useRef(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return allSectors;
    return allSectors.filter(s => {
      const nameMatch = s.toLowerCase().includes(q);
      const descMatch = (descriptions[s] || '').toLowerCase().includes(q);
      return nameMatch || descMatch;
    });
  }, [allSectors, query, descriptions]);

  const selectedSet = useMemo(() => new Set(selected), [selected]);

  const toggle = (name) => {
    if (selectedSet.has(name)) onChange(selected.filter(s => s !== name));
    else onChange([...selected, name]);
  };

  const selectAll = () => onChange([...allSectors]);
  const clearAll = () => onChange([]);

  return (
    <div className="relative inline-block" ref={ref}>
      <button
        onClick={() => setOpen(o => !o)}
        className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border text-xs font-medium transition-colors"
        style={{
          borderColor: 'var(--border-color)',
          background: open ? 'var(--bg-hover)' : 'var(--bg-card)',
          color: 'var(--text-primary)',
        }}
      >
        <span>📋</span>
        <span>筛选概念</span>
        <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold"
          style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>
          {selected.length}
        </span>
        <span style={{ fontSize: 9, opacity: 0.6 }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 rounded-xl border shadow-2xl"
          style={{
            borderColor: 'var(--border-color)',
            background: 'var(--bg-card)',
            width: 340,
            maxHeight: 420,
          }}>
          {/* 搜索框 + 操作按钮 */}
          <div className="flex items-center gap-2 p-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="搜索概念板块..."
              className="flex-1 px-2 py-1 rounded text-xs outline-none"
              style={{
                background: 'var(--bg-hover)',
                color: 'var(--text-primary)',
                border: '1px solid var(--border-color)',
              }}
              autoFocus
            />
            <button onClick={selectAll} className="px-2 py-1 rounded text-[10px] whitespace-nowrap"
              style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>全选</button>
            <button onClick={clearAll} className="px-2 py-1 rounded text-[10px] whitespace-nowrap"
              style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>清空</button>
          </div>

          {/* 复选框列表 */}
          <div className="overflow-y-auto p-1" style={{ maxHeight: 360 }}>
            {filtered.length === 0 && (
              <div className="text-center text-xs py-4" style={{ color: 'var(--text-muted)' }}>无匹配概念</div>
            )}
            {filtered.map(name => {
              const checked = selectedSet.has(name);
              const desc = descriptions[name];
              return (
                <label key={name}
                  className="flex items-start gap-2 px-2 py-1.5 rounded cursor-pointer text-xs transition-colors hover:bg-opacity-50"
                  style={{ background: checked ? 'rgba(34,197,94,0.08)' : 'transparent' }}
                  onMouseEnter={e => { if (!checked) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                  onMouseLeave={e => { if (!checked) e.currentTarget.style.background = 'transparent'; }}
                >
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => toggle(name)}
                    className="accent-green-500 mt-0.5"
                    style={{ width: 14, height: 14, flexShrink: 0 }}
                  />
                  <div className="flex flex-col min-w-0 flex-1">
                    <span style={{ color: checked ? '#22c55e' : 'var(--text-primary)', fontWeight: checked ? 600 : 400 }}>
                      {name}
                    </span>
                    {desc && (
                      <span
                        className="mt-0.5 leading-tight overflow-hidden"
                        style={{
                          color: 'var(--text-muted)',
                          fontSize: 10,
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          wordBreak: 'break-all',
                        }}
                        title={desc}
                      >
                        {desc}
                      </span>
                    )}
                  </div>
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
