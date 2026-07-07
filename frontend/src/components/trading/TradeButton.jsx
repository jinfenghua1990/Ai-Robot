import { useState } from 'react';
import TradeModal from './TradeModal';
import { useTrading } from '../../context/TradingContext';

/**
 * 可复用的买卖按钮组件
 * 嵌入任何页面，点击弹出交易弹窗
 */
export default function TradeButton({ stockCode, stockName, type = 'buy', size = 'sm', positionCount = 0, className = '' }) {
  const [modalOpen, setModalOpen] = useState(false);
  const { executeTrade } = useTrading();

  if (!stockCode) return null;

  const isBuy = type === 'buy';

  const sizeClass = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-3 py-1.5 text-sm';

  return (
    <>
      <button
        onClick={(e) => { e.stopPropagation(); setModalOpen(true); }}
        className={`${sizeClass} rounded font-medium transition-all inline-flex items-center justify-center ${className}`}
        style={{
          background: isBuy ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
          color: isBuy ? '#ef4444' : '#22c55e',
          border: `1px solid ${isBuy ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)'}`,
        }}
      >
        {isBuy ? '买' : '卖'}
      </button>
      {modalOpen && (
        <TradeModal
          stockCode={stockCode}
          stockName={stockName}
          type={type}
          positionCount={positionCount}
          onClose={() => setModalOpen(false)}
          onConfirm={executeTrade}
        />
      )}
    </>
  );
}
