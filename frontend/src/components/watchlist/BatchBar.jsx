import { useState, useRef, useEffect } from 'react';

/**
 * 批量操作栏
 *  - 全选 / 反选
 *  - 批量删除
 *  - 批量移动分组
 *  - 导出 CSV
 *  - 退出批量模式
 */
export default function BatchBar({
  batchMode, selectedIds, allStocks, groups, activeGroup, onToggleBatch, onSelectAll, onInvert, onClearSel,
  onBatchDelete, onBatchMove, onExport, addLog,
}) {
  const [open, setOpen] = useState(false);
  const [moveOpen, setMoveOpen] = useState(false);
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) { setOpen(false); setMoveOpen(false); } };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  if (!batchMode) {
    return (
      <button
        onClick={onToggleBatch}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1.5 hover:opacity-80"
        style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      >
        ☑ 批量
      </button>
    );
  }

  const total = allStocks.length;
  const sel = selectedIds.length;
  const allSelected = total > 0 && sel === total;

  return (
    <div ref={ref} className="flex items-center gap-1 relative">
      {/* 全选/反选 */}
      <button
        onClick={() => allSelected ? onClearSel() : onSelectAll()}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1 hover:opacity-80"
        style={{ background: allSelected ? '#22c55e' : 'var(--bg-hover)', color: allSelected ? '#fff' : 'var(--text-primary)', border: '1px solid var(--border-color)' }}
        title={allSelected ? '取消全选' : '全选当前分组'}
      >
        {allSelected ? '☑' : '☐'} {allSelected ? `全选 ${sel}` : `全选 ${total}`}
      </button>
      <button onClick={onInvert} className="px-2 py-1 rounded text-[11px] hover:opacity-80" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
        反选
      </button>

      {/* 已选 N 只 */}
      <span className="text-[11px] px-2" style={{ color: 'var(--text-muted)' }}>
        已选 <b style={{ color: '#60a5fa' }}>{sel}</b> / {total}
      </span>

      {/* 批量操作下拉 */}
      <button
        onClick={() => setOpen(!open)}
        disabled={sel === 0}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1 hover:opacity-80"
        style={{ background: sel > 0 ? '#ef4444' : 'var(--bg-hover)', color: sel > 0 ? '#fff' : 'var(--text-muted)', border: '1px solid var(--border-color)', cursor: sel > 0 ? 'pointer' : 'not-allowed' }}
      >
        操作 ▾
      </button>
      {open && sel > 0 && (
        <div className="absolute right-0 top-full mt-1 z-30 rounded-lg shadow-2xl min-w-[180px] p-1"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <button
            onClick={() => { if (confirm(`确认删除 ${sel} 只自选股？`)) onBatchDelete(); setOpen(false); }}
            className="w-full text-left px-2 py-1 text-[11px] rounded hover:bg-white/10"
            style={{ color: '#ef4444' }}
          >
            🗑 删除 {sel} 只
          </button>
          <button
            onClick={() => { setMoveOpen(!moveOpen); }}
            className="w-full text-left px-2 py-1 text-[11px] rounded hover:bg-white/10"
            style={{ color: 'var(--text-primary)' }}
          >
            📂 移动到分组 ▸
          </button>
          {moveOpen && (
            <div className="ml-3 border-l pl-1" style={{ borderColor: 'var(--border-color)' }}>
              {groups.filter(g => g.name !== activeGroup).map(g => (
                <button
                  key={g.name}
                  onClick={() => { onBatchMove(g.name); setOpen(false); setMoveOpen(false); }}
                  className="w-full text-left px-2 py-1 text-[11px] rounded hover:bg-white/10"
                  style={{ color: 'var(--text-primary)' }}
                >
                  {g.name} <span style={{ color: 'var(--text-muted)' }}>({g.count})</span>
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* 导出按钮（独立） */}
      <button
        onClick={onExport}
        title="导出当前分组为 CSV"
        className="px-2 py-1 rounded text-[11px] hover:opacity-80"
        style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      >
        📥
      </button>

      {/* 退出批量 */}
      <button
        onClick={() => { onClearSel(); onToggleBatch(); }}
        title="退出批量"
        className="px-2 py-1 rounded text-[11px] hover:opacity-80"
        style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}
      >
        ✕
      </button>
    </div>
  );
}
