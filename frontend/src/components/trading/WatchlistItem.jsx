import { memo, useCallback, useMemo } from 'react';
import SignalCard from './SignalCardV4';
import CardSafetyBoundary from '../CardSafetyBoundary';

/**
 * 自选股列表项（memoized）
 * 关键优化：通过 React.memo 避免点击切换选中时 164 张卡片全部重渲染。
 * 只有 isSelected 变化的 2 张卡（旧选中→未选中、新选中→选中）会重渲染。
 *
 * onSelect/onSell 是 useState setter（React 保证引用稳定），onRemove 需在父层 useCallback。
 *
 * 模块级空数组常量：避免每次 render 新建 [] 击穿下游 SignalCardV4 的 memo。
 * （默认参数 orders=[] 和 strategyTags=[] 每次都创建新引用，是 memo 杀手）
 */
const EMPTY_ORDERS = [];
const EMPTY_TAGS = [];

function WatchlistItem({ signal, isSelected, realtimeFlow, onSelect, onRemove, onSell, onRefresh, batchMode, checked, onToggleCheck, onAnalyze, strategyTags = EMPTY_TAGS }) {
  const handleClick = useCallback((e) => {
    // 如果点击的是按钮或弹窗，不触发选中
    if (e.target.closest('button') || e.target.closest('.fixed')) return;
    batchMode ? onToggleCheck?.(signal.secCode) : onSelect(signal.secCode);
  }, [batchMode, onToggleCheck, onSelect, signal.secCode]);

  const containerStyle = useMemo(() => ({
    outline: isSelected ? '2px solid #60a5fa' : (batchMode && checked ? '2px solid #f97316' : '2px solid transparent'),
    opacity: 1,
  }), [isSelected, batchMode, checked]);

  return (
    <div
      onClick={handleClick}
      className="cursor-pointer rounded-lg transition-all relative"
      style={containerStyle}
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

      <CardSafetyBoundary>
        <SignalCard
          signal={signal}
          orders={EMPTY_ORDERS}
          onSell={onSell}
          onRemove={onRemove}
          onRefresh={onRefresh}
          onAnalyze={onAnalyze}
          showWatchBtn={!signal.poolSources?.includes('自选')}
          // 自选页现在是持仓状态管理页，不在这里把未持仓标的当成买入信号。
          showBuyBtn={false}
          mode="watchlist"
          showAnalysisButton
          showActionButton={!batchMode}
          strategyTags={strategyTags}
          realtimeFlow={realtimeFlow}
          showRealtimeDetail={isSelected}
        />
      </CardSafetyBoundary>
    </div>
  );
}

export default memo(WatchlistItem);
