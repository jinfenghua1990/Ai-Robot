import { useState, useRef, useEffect } from 'react';
import { apiFetch } from '../../utils/request';

/**
 * 分组管理下拉
 *  - 列出所有分组（带股票数）+ 切换当前激活分组
 *  - 新建 / 重命名 / 删除 / 强制清空
 */
export default function GroupBar({ groups, active, onChange, onRefresh, addLog }) {
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // {oldName, newName}
  const [confirming, setConfirming] = useState(null); // 待删除的分组名
  const ref = useRef(null);

  useEffect(() => {
    const h = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', h);
    return () => document.removeEventListener('mousedown', h);
  }, []);

  const create = async (name) => {
    if (!name) return;
    const { ok, error } = await apiFetch('/api/watchlist/groups', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name }) });
    if (ok) { addLog?.('success', `分组「${name}」已创建`); onRefresh(); }
    else { addLog?.('error', error || '创建失败'); }
  };

  const rename = async (oldName, newName) => {
    if (!newName || oldName === newName) return;
    const { ok, error } = await apiFetch('/api/watchlist/groups/rename', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ old_name: oldName, new_name: newName }) });
    if (ok) { addLog?.('success', `已重命名为「${newName}」`); onChange(newName); onRefresh(); }
    else { addLog?.('error', error || '重命名失败'); }
  };

  const remove = async (name, force = false) => {
    const { ok, error } = await apiFetch(`/api/watchlist/groups/${encodeURIComponent(name)}${force ? '?force=true' : ''}`, { method: 'DELETE' });
    if (ok) { addLog?.('success', `已删除分组「${name}」`); if (active === name) onChange('全部'); onRefresh(); }
    else { addLog?.('error', error || '删除失败'); }
  };

  const activeGroup = groups.find(g => g.name === active);
  const totalCount = groups.reduce((s, g) => s + g.count, 0);
  // "全部"模式时 count 显示总股数；否则显示当前分组股数
  const displayCount = active === '全部' ? totalCount : (activeGroup?.count || 0);

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className="px-2 py-1 rounded text-[11px] flex items-center gap-1.5 hover:opacity-80"
        style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      >
        📂 <span className="font-bold">{active || '全部'}</span>
        <span style={{ color: 'var(--text-muted)' }}>({displayCount})</span>
        <span style={{ color: 'var(--text-muted)' }}>{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-30 rounded-lg shadow-2xl min-w-[260px] p-2"
          style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>

          {/* 分组列表 */}
          <div className="text-[10px] mb-1 px-1" style={{ color: 'var(--text-muted)' }}>
            共 {groups.length} 个分组 / {totalCount} 只股
          </div>
          <div className="max-h-[200px] overflow-y-auto">
            {/* "全部"虚拟项 — 默认显示所有股票，不按分组过滤 */}
            <div className="flex items-center gap-1 px-1 py-1 rounded hover:bg-white/5">
              <button
                onClick={() => { onChange('全部'); setOpen(false); }}
                className="flex-1 text-left text-[11px] px-1"
                style={{ color: '全部' === active ? '#60a5fa' : 'var(--text-primary)', fontWeight: '全部' === active ? 700 : 400 }}
              >
                {'全部' === active && '● '}全部 <span style={{ color: 'var(--text-muted)' }}>({totalCount})</span>
              </button>
            </div>
            {groups.map(g => (
              <div key={g.name} className="flex items-center gap-1 px-1 py-1 rounded hover:bg-white/5 group">
                {editing?.oldName === g.name ? (
                  <input
                    autoFocus
                    defaultValue={g.name}
                    onBlur={(e) => { rename(g.name, e.target.value.trim()); setEditing(null); }}
                    onKeyDown={(e) => { if (e.key === 'Enter') { rename(g.name, e.target.value.trim()); setEditing(null); } if (e.key === 'Escape') setEditing(null); }}
                    className="flex-1 px-1 text-[11px] rounded"
                    style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
                  />
                ) : (
                  <button
                    onClick={() => { onChange(g.name); setOpen(false); }}
                    className="flex-1 text-left text-[11px] px-1"
                    style={{ color: g.name === active ? '#60a5fa' : 'var(--text-primary)', fontWeight: g.name === active ? 700 : 400 }}
                  >
                    {g.name === active && '● '}{g.name} <span style={{ color: 'var(--text-muted)' }}>({g.count})</span>
                  </button>
                )}
                {g.name !== '默认' && editing?.oldName !== g.name && (
                  <div className="hidden group-hover:flex items-center gap-0.5">
                    <button onClick={() => setEditing({ oldName: g.name, newName: g.name })} title="重命名" className="px-1 text-[10px] hover:opacity-70" style={{ color: 'var(--text-muted)' }}>✎</button>
                    <button onClick={() => setConfirming(g.name)} title="删除" className="px-1 text-[10px] hover:opacity-70" style={{ color: '#ef4444' }}>🗑</button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* 新建分组 */}
          <NewGroupInput onCreate={(n) => { create(n); }} />

          {/* 删除确认 */}
          {confirming && (
            <div className="mt-2 p-2 rounded text-[11px]" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid #ef4444' }}>
              <div style={{ color: '#ef4444' }}>删除分组「{confirming}」？</div>
              <div className="flex gap-1 mt-1">
                <button onClick={() => { remove(confirming, true); setConfirming(null); }} className="px-2 py-0.5 rounded text-[10px]" style={{ background: '#ef4444', color: '#fff' }}>移到默认组</button>
                <button onClick={() => setConfirming(null)} className="px-2 py-0.5 rounded text-[10px]" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>取消</button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function NewGroupInput({ onCreate }) {
  const [show, setShow] = useState(false);
  const [val, setVal] = useState('');
  if (!show) return (
    <button onClick={() => setShow(true)} className="mt-2 w-full text-[11px] py-1 rounded hover:opacity-80" style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
      + 新建分组
    </button>
  );
  return (
    <div className="mt-2 flex gap-1">
      <input
        autoFocus
        value={val}
        onChange={e => setVal(e.target.value)}
        onKeyDown={e => { if (e.key === 'Enter') { onCreate(val.trim()); setVal(''); setShow(false); } if (e.key === 'Escape') { setShow(false); setVal(''); } }}
        placeholder="新分组名"
        maxLength={20}
        className="flex-1 px-2 py-0.5 text-[11px] rounded"
        style={{ background: 'var(--bg-input)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
      />
      <button onClick={() => { onCreate(val.trim()); setVal(''); setShow(false); }} className="px-2 py-0.5 text-[10px] rounded" style={{ background: '#22c55e', color: '#fff' }}>✓</button>
    </div>
  );
}
