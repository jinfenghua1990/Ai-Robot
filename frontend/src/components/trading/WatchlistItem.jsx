import { memo } from 'react';
import SignalCard from './SignalCard';

/**
 * 自选股列表项（memoized）
 * 关键优化：通过 React.memo 避免点击切换选中时 164 张卡片全部重渲染。
 * 只有 isSelected 变化的 2 张卡（旧选中→未选中、新选中→选中）会重渲染。
 *
 * onSelect/onSell 是 useState setter（React 保证引用稳定），onRemove 需在父层 useCallback。
 */
function WatchlistItem({ signal, isSelected, realtimeFlow, onSelect, onRemove, onSell, onRefresh, batchMode, checked, onToggleCheck, strategyTags = [] }) {
  const ms = signal.marketState || {};

  return (
    <div
      onClick={(e) => {
        // 如果点击的是按钮或弹窗，不触发选中
        if (e.target.closest('button') || e.target.closest('.fixed')) return;
        batchMode ? onToggleCheck?.(signal.secCode) : onSelect(signal.secCode);
      }}
      className="cursor-pointer rounded-lg transition-all relative"
      style={{
        outline: isSelected ? '2px solid #60a5fa' : (batchMode && checked ? '2px solid #f97316' : '2px solid transparent'),
        opacity: ms.market_state === 'CHOPPY' ? 0.7 : 1,
      }}
      title={ms.reasons?.join('、') || ''}
    >
      {/* 批量模式 checkbox */}
      {batchMode && (
        <div className="absolute top-1 left-1 z-10">
          <input
            type="checkbox"
            checked={!!checked}
            onChange={() => onToggleCheck?.(signal.secCode)}
            onClick={(e) => e.stopPropagation()}
            className="w-4 h-4 cursor-pointer"
          />
        </div>
      )}

      <SignalCard
        signal={signal}
        orders={[]}
        onSell={onSell}
        onRemove={onRemove}
        onRefresh={onRefresh}
        showWatchBtn={false}
        mode="watchlist"
        showMarketState
        showBuyPower
        showAnalysisButton
        showActionButton={!batchMode}
        strategyTags={strategyTags}
        realtimeFlow={realtimeFlow}
      />
    </div>
  );
}

export default memo(WatchlistItem);
