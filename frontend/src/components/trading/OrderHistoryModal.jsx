import { useState } from 'react';
import { createPortal } from 'react-dom';

const STATUS_MAP = {
  1: '未报', 2: '已报', 3: '部成', 4: '已成',
  5: '部成待撤', 6: '已报待撤', 7: '部撤', 8: '已撤',
  9: '废单', 10: '撤单失败',
};

function formatTime(ts) {
  if (!ts) return '--';
  return new Date(ts * 1000).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

/**
 * 委托记录弹窗
 */
export default function OrderHistoryModal({ stockName, secCode, orders = [], onClose }) {
  const [filter, setFilter] = useState('all'); // all | buy | sell | filled

  const filtered = orders.filter(o => {
    if (filter === 'buy') return o.drt === 1;
    if (filter === 'sell') return o.drt === 2;
    if (filter === 'filled') return o.status === 4;
    return true;
  });

  const buyCount = orders.filter(o => o.drt === 1).length;
  const sellCount = orders.filter(o => o.drt === 2).length;
  const filledCount = orders.filter(o => o.status === 4).length;

  // 使用 Portal 渲染到 document.body，脱离父元素 stacking context
  return createPortal((
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.82)' }} onClick={onClose}>
      <div className="rounded-xl w-[calc(100vw-2rem)] max-w-2xl max-h-[85vh] flex flex-col"
        style={{
          background: 'var(--bg-card)',
          border: '2px solid #3b82f6',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.06), 0 12px 28px rgba(0,0,0,0.12), 0 30px 60px rgba(0,0,0,0.35)',
        }}
        onClick={e => e.stopPropagation()}>
        {/* 头部 */}
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <h3 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>📋 {stockName} 委托记录</h3>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
              {secCode} · 共 {orders.length} 笔 (买{buyCount} / 卖{sellCount} / 已成{filledCount})
            </div>
          </div>
          <button onClick={onClose} className="text-xl px-2" style={{ color: 'var(--text-muted)' }}>×</button>
        </div>

        {/* 筛选 */}
        <div className="flex gap-1 px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
          {[
            { key: 'all', label: '全部', count: orders.length },
            { key: 'buy', label: '买入', count: buyCount },
            { key: 'sell', label: '卖出', count: sellCount },
            { key: 'filled', label: '已成', count: filledCount },
          ].map(f => (
            <button key={f.key} onClick={() => setFilter(f.key)}
              className="px-3 py-1 rounded text-xs font-medium"
              style={{
                background: filter === f.key ? 'var(--accent-color, #3b82f6)' : 'var(--bg-surface)',
                color: filter === f.key ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${filter === f.key ? 'transparent' : 'var(--border-color)'}`,
              }}>
              {f.label} ({f.count})
            </button>
          ))}
        </div>

        {/* 记录列表 */}
        <div className="flex-1 overflow-y-auto p-3">
          {filtered.length === 0 ? (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-muted)' }}>暂无委托记录</div>
          ) : (
            <div className="space-y-1">
              {filtered.map(o => (
                <div key={o.id} className="flex items-center gap-3 py-2 px-3 rounded-lg text-sm" style={{ background: 'var(--bg-surface)' }}>
                  <span className="px-2 py-0.5 rounded font-medium text-xs" style={{
                    background: o.drt === 1 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: o.drt === 1 ? '#ef4444' : '#22c55e',
                  }}>
                    {o.drt === 1 ? '买入' : '卖出'}
                  </span>
                  <span style={{ color: 'var(--text-secondary)' }}>{o.price.toFixed(2)} 元</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{o.count} 股</span>
                  {o.tradeCount > 0 && <span style={{ color: 'var(--text-muted)' }}>已成 {o.tradeCount} 股</span>}
                  <span className="px-1.5 py-0.5 rounded text-xs" style={{
                    background: o.status === 4 ? 'rgba(34,197,94,0.1)' : o.status === 8 ? 'rgba(100,116,139,0.1)' : 'rgba(59,130,246,0.1)',
                    color: o.status === 4 ? '#22c55e' : o.status === 8 ? '#64748b' : '#3b82f6',
                  }}>
                    {STATUS_MAP[o.status] || '?'}
                  </span>
                  <span className="ml-auto text-xs" style={{ color: 'var(--text-muted)' }}>{formatTime(o.time)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  ), document.body);
}
