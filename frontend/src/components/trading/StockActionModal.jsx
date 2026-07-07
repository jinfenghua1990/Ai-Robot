import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useNavigate } from 'react-router-dom';
import TradeModal from './TradeModal';
import OrderHistoryModal from './OrderHistoryModal';
import { useTrading } from '../../context/TradingContext';
import { apiFetch } from '../../utils/request';

/**
 * 个股操作弹窗（居中 + 遮罩）
 * 操作：买入/卖出/委托记录/移除/移动分组/加备注/置顶/个股详情
 *
 * 注意：禁止使用 transform: scale 或父级 opacity<1 做入场动画。
 * transform 会创建合成层导致 macOS Retina 屏文字/图表模糊；
 * 父级 opacity<1 会让所有子元素的子像素抗锯齿失效。
 */
export default function StockActionModal({ signal, onClose, onRemove, onRefresh }) {
  const navigate = useNavigate();
  const { executeTrade } = useTrading();

  // 子弹窗状态
  const [tradeType, setTradeType] = useState(null);       // 'buy' | 'sell' | null
  const [orderOpen, setOrderOpen] = useState(false);
  const [orders, setOrders] = useState([]);
  // 移除二次确认
  const [confirmRemove, setConfirmRemove] = useState(false);
  // 移动分组
  const [groupOpen, setGroupOpen] = useState(false);
  const [groups, setGroups] = useState([]);
  // 加备注
  const [noteOpen, setNoteOpen] = useState(false);
  const [noteText, setNoteText] = useState(signal.note || '');
  // 置顶反馈
  const [pinned, setPinned] = useState(false);
  // 错误/提示
  const [tip, setTip] = useState('');

  const code = signal?.secCode || '';
  const name = signal?.secName || code;

  // 点击遮罩关闭
  const handleOverlayClick = (e) => {
    if (e.target === e.currentTarget) onClose();
  };

  const showTip = (msg) => { setTip(msg); setTimeout(() => setTip(''), 2000); };

  // 打开委托记录
  const openOrders = async () => {
    try {
      const { ok, data } = await apiFetch('/api/trading/orders');
      if (!ok) { setOrders([]); setOrderOpen(true); return; }
      const all = data.orders || data || [];
      const mine = Array.isArray(all) ? all.filter(o => (o.secCode || o.stockCode || '').replace(/\.\w+$/, '') === code) : [];
      setOrders(mine);
      setOrderOpen(true);
    } catch {
      setOrders([]);
      setOrderOpen(true);
    }
  };

  // 移动分组
  const openMoveGroup = async () => {
    try {
      const { ok, data } = await apiFetch('/api/watchlist/groups');
      if (!ok) { setGroups([{ name: '默认', count: 0 }]); setGroupOpen(true); return; }
      setGroups(data.groups || [{ name: '默认', count: 0 }]);
      setGroupOpen(true);
    } catch {
      setGroups([{ name: '默认', count: 0 }]);
      setGroupOpen(true);
    }
  };
  const doMoveGroup = async (target) => {
    try {
      const { ok } = await apiFetch(`/api/watchlist/${code}/move-group`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_group: target }),
      });
      if (ok) { showTip(`已移动到「${target}」`); onRefresh?.(); setTimeout(onClose, 800); }
      else showTip('移动失败');
    } catch { showTip('移动失败'); }
  };

  // 加备注
  const saveNote = async () => {
    try {
      const { ok } = await apiFetch(`/api/watchlist/${code}/note`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ note: noteText }),
      });
      if (ok) { showTip('备注已保存'); onRefresh?.(); setNoteOpen(false); }
      else showTip('保存失败');
    } catch { showTip('保存失败'); }
  };

  // 置顶
  const doPin = async () => {
    try {
      const { ok } = await apiFetch(`/api/watchlist/${code}/pin`, { method: 'POST' });
      if (ok) { setPinned(true); showTip('已置顶'); onRefresh?.(); }
      else showTip('置顶失败');
    } catch { showTip('置顶失败'); }
  };

  // 确认移除
  const confirmRemoveAction = () => {
    onRemove?.(code, name);
    onClose();
  };

  // 个股详情
  const goDetail = () => { navigate(`/stock/${code}`); onClose(); };

  const actions = [
    { key: 'buy', label: '买入', icon: '💰', color: '#ef4444', onClick: () => setTradeType('buy') },
    { key: 'sell', label: '卖出', icon: '📤', color: '#22c55e', onClick: () => setTradeType('sell') },
    { key: 'orders', label: '委托记录', icon: '📋', color: '#3b82f6', onClick: openOrders },
    { key: 'move', label: '移动分组', icon: '📁', color: '#eab308', onClick: openMoveGroup },
    { key: 'note', label: '加备注', icon: '📝', color: '#06b6d4', onClick: () => setNoteOpen(true) },
    { key: 'pin', label: pinned ? '已置顶' : '置顶', icon: '📌', color: '#f97316', onClick: doPin },
    { key: 'remove', label: '移除', icon: '✕', color: '#6b7280', onClick: () => setConfirmRemove(true) },
  ];

  // 使用 Portal 渲染到 document.body，脱离父元素 stacking context
  // （WatchlistItem 对劣质股设置 opacity:0.55，会创建 stacking context 导致弹窗遮罩被降透明度）
  return createPortal((
    <div
      onClick={handleOverlayClick}
      className="fixed inset-0 z-50 flex items-center justify-center px-4"
      style={{ background: 'rgba(0,0,0,0.82)' }}
    >
      <div
        className="w-[calc(100vw-2rem)] max-w-md max-h-[90vh] overflow-y-auto rounded-xl"
        style={{
          background: 'var(--bg-card)',
          border: '2px solid #3b82f6',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.06), 0 12px 28px rgba(0,0,0,0.12), 0 30px 60px rgba(0,0,0,0.35)',
        }}
      >
        {/* 头部 */}
        <div className="flex items-center justify-between px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex items-baseline gap-2">
            <span className="font-bold text-base" style={{ color: 'var(--text-primary)' }}>{name}</span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{code}</span>
            {signal?.quote && (
              <span className="text-xs" style={{ color: signal.quote.changePct >= 0 ? '#ef4444' : '#22c55e' }}>
                {signal.quote.changePct >= 0 ? '+' : ''}{signal.quote.changePct}%
              </span>
            )}
          </div>
          <button onClick={onClose} className="text-lg leading-none px-2 py-0.5 rounded" style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        {/* 操作按钮网格 */}
        <div className="p-4 grid grid-cols-4 gap-2">
          {actions.map(a => (
            <button
              key={a.key}
              onClick={a.onClick}
              className="flex flex-col items-center gap-1 py-2.5 px-1 rounded-lg border transition-all hover:scale-105"
              style={{ borderColor: `${a.color}30`, background: `${a.color}08`, color: a.color }}
            >
              <span className="text-lg">{a.icon}</span>
              <span className="text-[11px] font-medium">{a.label}</span>
            </button>
          ))}
        </div>

        {/* 提示 */}
        {tip && (
          <div className="px-4 pb-2 text-center text-xs" style={{ color: '#22c55e' }}>{tip}</div>
        )}

        {/* 移除二次确认 */}
        {confirmRemove && (
          <div className="px-4 pb-3">
            <div className="rounded-lg p-3 text-center" style={{ background: 'rgba(239,68,68,0.08)' }}>
              <div className="text-sm mb-2" style={{ color: 'var(--text-primary)' }}>确认从自选股移除 {name}？</div>
              <div className="flex gap-2 justify-center">
                <button onClick={confirmRemoveAction} className="px-3 py-1 rounded text-xs font-bold" style={{ background: '#ef4444', color: '#fff' }}>确认移除</button>
                <button onClick={() => setConfirmRemove(false)} className="px-3 py-1 rounded text-xs" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>取消</button>
              </div>
            </div>
          </div>
        )}

        {/* 移动分组下拉 */}
        {groupOpen && (
          <div className="px-4 pb-3">
            <div className="text-xs mb-1.5" style={{ color: 'var(--text-muted)' }}>选择目标分组：</div>
            <div className="flex flex-wrap gap-1.5">
              {groups.map(g => (
                <button key={g.name} onClick={() => doMoveGroup(g.name)}
                  className="px-2.5 py-1 rounded text-xs border"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
                  📁 {g.name} ({g.count ?? 0})
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 加备注 */}
        {noteOpen && (
          <div className="px-4 pb-3">
            <div className="text-xs mb-1.5" style={{ color: 'var(--text-muted)' }}>编辑备注（关注理由）：</div>
            <div className="flex gap-1.5">
              <input
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                placeholder="如：突破压力位 / 龙头回调"
                className="flex-1 px-2.5 py-1.5 rounded text-sm outline-none"
                style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}
              />
              <button onClick={saveNote} className="px-3 py-1 rounded text-xs font-bold" style={{ background: '#3b82f6', color: '#fff' }}>保存</button>
            </div>
          </div>
        )}
      </div>

      {/* 买入/卖出弹窗 */}
      {tradeType && (
        <TradeModal
          stockCode={code}
          stockName={name}
          type={tradeType}
          positionCount={0}
          onClose={() => setTradeType(null)}
          onConfirm={executeTrade}
        />
      )}

      {/* 委托记录弹窗 */}
      {orderOpen && (
        <OrderHistoryModal
          stockName={name}
          secCode={code}
          orders={orders}
          onClose={() => setOrderOpen(false)}
        />
      )}
    </div>
  ), document.body);
}
