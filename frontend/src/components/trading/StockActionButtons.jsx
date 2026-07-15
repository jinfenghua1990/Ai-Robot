import { useState } from 'react';
import TradeModal from './TradeModal';
import StockActionModal from './StockActionModal';
import { useTrading } from '../../context/TradingContext';
import { apiFetch } from '../../utils/request';

/**
 * 可复用的股票操作按钮组：买 / 卖 / 自选 / 重点 / 操作
 * 嵌入任意股票列表/卡片/表格中
 */
export default function StockActionButtons({
  stockCode,
  stockName,
  signal = null,
  positionCount = 0,
  showBuy = true,
  showSell = true,
  showWatch = true,
  showFocus = true,
  showMore = true,
  size = 'sm',
  className = '',
  onRefresh,
  onRemove,
}) {
  const { executeTrade } = useTrading();
  const [tradeType, setTradeType] = useState(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [watchAdded, setWatchAdded] = useState(false);
  const [focusAdded, setFocusAdded] = useState(false);

  if (!stockCode) return null;

  const sizeClass = size === 'xs'
    ? 'px-1.5 py-0 text-[10px] h-5'
    : size === 'md'
    ? 'px-2.5 py-1 text-xs h-7'
    : 'px-2 py-0.5 text-xs h-6';

  const handleWatch = async (e) => {
    e?.stopPropagation?.();
    if (watchAdded) return;
    const { ok } = await apiFetch('/api/watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stockCode, stockName }),
    });
    if (ok) setWatchAdded(true);
  };

  const handleFocus = async (e) => {
    e?.stopPropagation?.();
    if (focusAdded) return;
    const res = await apiFetch('/api/watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stockCode, stockName, group: '重点关注' }),
    });
    if (res.ok) {
      setFocusAdded(true);
    } else if (res.status === 400) {
      const moveRes = await apiFetch(`/api/watchlist/${stockCode}/move-group`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_group: '重点关注' }),
      });
      if (moveRes.ok) setFocusAdded(true);
    }
  };

  const fullSignal = signal || { secCode: stockCode, secName: stockName };

  return (
    <>
      <div className={`inline-flex items-center gap-1 flex-wrap ${className}`}>
        {showBuy && (
          <button
            onClick={(e) => { e.stopPropagation(); setTradeType('buy'); }}
            className={`${sizeClass} rounded font-medium inline-flex items-center justify-center`}
            style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}
            title="买入"
          >
            买
          </button>
        )}
        {showSell && (
          <button
            onClick={(e) => { e.stopPropagation(); setTradeType('sell'); }}
            className={`${sizeClass} rounded font-medium inline-flex items-center justify-center`}
            style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}
            title="卖出"
          >
            卖
          </button>
        )}
        {showWatch && (
          <button
            onClick={handleWatch}
            className={`${sizeClass} rounded font-medium inline-flex items-center justify-center`}
            style={watchAdded
              ? { background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
              : { background: 'rgba(234,179,8,0.1)', color: '#eab308', border: '1px solid rgba(234,179,8,0.3)' }
            }
            title="加入自选股"
          >
            {watchAdded ? '✓已加' : '自选'}
          </button>
        )}
        {showFocus && (
          <button
            onClick={handleFocus}
            className={`${sizeClass} rounded font-medium inline-flex items-center justify-center`}
            style={focusAdded
              ? { background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
              : { background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }
            }
            title="加入重点关注"
          >
            {focusAdded ? '✓已关注' : '重点'}
          </button>
        )}
        {showMore && (
          <button
            onClick={(e) => { e.stopPropagation(); setMoreOpen(true); }}
            className={`${sizeClass} rounded font-medium inline-flex items-center justify-center`}
            style={{ background: 'rgba(107,114,128,0.1)', color: '#6b7280', border: '1px solid rgba(107,114,128,0.3)' }}
            title="更多操作"
          >
            操作
          </button>
        )}
      </div>

      {tradeType && (
        <TradeModal
          stockCode={stockCode}
          stockName={stockName}
          type={tradeType}
          positionCount={positionCount}
          onClose={() => setTradeType(null)}
          onConfirm={executeTrade}
        />
      )}

      {moreOpen && (
        <StockActionModal
          signal={fullSignal}
          onClose={() => setMoreOpen(false)}
          onRemove={onRemove}
          onRefresh={onRefresh}
        />
      )}
    </>
  );
}
