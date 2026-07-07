/**
 * 通栏对比行容器
 * 一个通栏标题 + 左右两栏（盘后 vs 实时）。
 * 子组件保持各自样式，容器只提供外框 + 标题 + grid 布局。
 * lg 以下自动堆叠为单列。
 */
export default function CompareRow({
  title, badge, legend, extra,
  children,
}) {
  const [left, right] = Array.isArray(children) ? children : [children, null];

  return (
    <div className="rounded-xl border p-3"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      {/* 通栏标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-3">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2>
          {badge && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-normal align-middle"
              style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>{badge}</span>
          )}
        </div>
        {legend && (
          <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>{legend}</div>
        )}
        {extra}
      </div>

      {/* 左右两栏 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
        {left}
        {right}
      </div>
    </div>
  );
}
