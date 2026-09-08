import { useMemo } from 'react';
import ViewModeToggle from './ViewModeToggle';
import { useViewMode } from '../hooks/useViewMode';
import WatchlistTable from './watchlist/WatchlistTable';

/**
 * 统一的「表格 / 卡片」股票列表容器
 *
 * 目标：后续所有股票列表页面只改这一处标准，即可同步影响全部页面。
 * - 表格视图 = WatchlistTable（支持按 sector 分组）
 * - 卡片视图 = 由调用方传入 cardRenderer(items) 自由渲染
 * - 视图模式通过 viewModeKey 记忆到 localStorage
 *
 * 用法示例：
 *   <StockListContainer
 *     viewModeKey="watchlist"
 *     loading={loading}
 *     items={flatStocks}
 *     groupBy="sector"
 *     tableProps={{ selectedCode, onSelect, onRemove, onRefresh, ... }}
 *     cardRenderer={(items) => (
 *       <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
 *         {items.map(s => <StrategySignalCard key={s.secCode} signal={s} />)}
 *       </div>
 *     )}
 *     emptyText="暂无自选股"
 *     loadingText="加载自选股..."
 *   />
 */
export default function StockListContainer({
  // 视图模式控制（默认内部管理，也可外部控制）
  viewModeKey,
  defaultViewMode = 'card',
  viewMode: controlledView,
  onViewModeChange,

  // 数据状态
  loading = false,
  error = null,
  items = [],
  tableItems, // 表格视图专用数据（如卡片用原始 stock，表格用 signal）

  // 分组（表格视图下生效）
  groupBy = null, // 'sector' 或 (item) => key

  // 渲染
  cardRenderer,
  tableRenderer, // 自定义表格视图（优先级高于默认 WatchlistTable）
  tableProps = {},

  // 文案
  emptyText = '暂无数据',
  loadingText = '加载中...',
  errorText = '加载失败，请稍后重试',
  retryText = '重试',
  onRetry,

  // 布局
  className = '',
  contentClassName = 'rounded-xl border overflow-hidden',
  headerClassName = 'flex items-center justify-end gap-2 mb-2',
  emptyClassName = 'flex items-center justify-center h-64 text-sm',
  showToggle = true,
  toggleTitle = '切换股票列表阅读方式：表格（平铺） / 卡片（策略卡片）',
  headerExtra = null,
  // 卡片视图是否套用外层边框容器（卡片本身自带边框时传 false）
  wrapCard = true,
  cardClassName = 'p-3',
}) {
  const [internalView, setInternalView] = useViewMode(viewModeKey, defaultViewMode);
  const viewMode = controlledView ?? internalView;
  const setViewMode = onViewModeChange ?? setInternalView;

  const hasItems = Array.isArray(items) && items.length > 0;

  // 分组后的数据（仅用于传给 WatchlistTable，由表格内部分组渲染）
  const groupByProp = useMemo(() => {
    if (!groupBy) return null;
    return typeof groupBy === 'function' ? groupBy : (item) => item[groupBy];
  }, [groupBy]);

  // 统一外壳：状态区与表格视图始终套边框容器；卡片视图可选（卡片自带边框时关闭）
  const shell = (children, wrap = true) =>
    wrap ? (
      <div
        className={contentClassName}
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        {children}
      </div>
    ) : (
      children
    );

  const renderBody = () => {
    if (error) {
      return shell(
        <div className="flex flex-col items-center justify-center h-64 gap-3 text-sm">
          <span style={{ color: 'var(--text-muted)' }}>{errorText}</span>
          {onRetry && (
            <button
              onClick={onRetry}
              className="px-3 py-1 rounded-lg text-xs border"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              {retryText}
            </button>
          )}
        </div>
      );
    }

    if (loading) {
      return shell(
        <div className="flex items-center justify-center h-64 gap-2">
          <div
            className="w-5 h-5 border-2 rounded-full animate-spin"
            style={{ borderColor: 'var(--accent-blue, #6366f1)', borderTopColor: 'transparent' }}
          />
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{loadingText}</span>
        </div>
      );
    }

    if (!hasItems) {
      return shell(
        <div
          className={emptyClassName}
          style={{ color: 'var(--text-muted)' }}
        >
          {emptyText}
        </div>
      );
    }

    if (viewMode === 'table') {
      return shell(
        tableRenderer ? (
          tableRenderer()
        ) : (
          <WatchlistTable stocks={tableItems ?? items} groupBy={groupByProp} {...tableProps} />
        )
      );
    }

    return shell(
      <div className={cardClassName}>
        {cardRenderer?.(items) ?? (
          <div className="text-center text-sm" style={{ color: 'var(--text-muted)' }}>
            请提供 cardRenderer
          </div>
        )}
      </div>,
      wrapCard
    );
  };

  return (
    <div className={className}>
      {showToggle && (
        <div className={headerClassName}>
          {headerExtra}
          <ViewModeToggle value={viewMode} onChange={setViewMode} title={toggleTitle} />
        </div>
      )}
      {renderBody()}
    </div>
  );
}
