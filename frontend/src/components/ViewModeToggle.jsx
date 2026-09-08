/**
 * 通用「表格 / 卡片」视图切换
 *
 * - useViewMode(key, defaultView): 按页面 key 记忆偏好到 localStorage，刷新后保持。
 * - ViewModeToggle: 与策略中心 StrategyResultsTable 同款的分段控件（📋表格 / 🃏卡片）。
 *
 * 用法：
 *   const [viewMode, setViewMode] = useViewMode('watchlist', 'card');
 *   <ViewModeToggle value={viewMode} onChange={setViewMode} />
 *   渲染时：viewMode === 'table' ? <FlatTable/> : <CardGrid/>
 */

export default function ViewModeToggle({ value, onChange, title }) {
  const btn = (mode, label) => {
    const active = value === mode;
    return (
      <button
        type="button"
        onClick={() => onChange(mode)}
        className="px-2.5 py-1 text-xs font-medium transition-colors"
        style={{
          background: active ? 'var(--accent-blue)' : 'transparent',
          color: active ? '#fff' : 'var(--text-secondary)',
        }}
        title={title}
      >
        {label}
      </button>
    );
  };
  return (
    <div
      className="flex rounded-lg border overflow-hidden flex-shrink-0"
      style={{ borderColor: 'var(--border-color)' }}
    >
      {btn('table', '📋 表格')}
      {btn('card', '🃏 卡片')}
    </div>
  );
}
