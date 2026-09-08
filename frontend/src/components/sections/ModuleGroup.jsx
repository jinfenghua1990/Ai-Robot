function ModuleCell({ children }) {
  return <div className="min-w-0">{children}</div>;
}

function ModuleContentCell({ children, autoHeight }) {
  return (
    <div className="flex flex-col" style={{ minHeight: autoHeight ? undefined : '280px' }}>
      {children}
    </div>
  );
}

/**
 * 模块组：统一的通栏对比容器
 * 标题在通栏顶部，下方左右两栏按【标题行】【副标题行】【内容行】分别对齐，
 * 保证左右 chart 顶部/底部严格对齐。
 *
 * 用法：
 *   <ModuleGroup title="板块热度" badge="..." extra={...}>
 *     <ModuleGroup.Header left={...} right={...} />
 *     <ModuleGroup.SubHeader left={...} right={...} />
 *     <ModuleGroup.Content left={...} right={...} />
 *   </ModuleGroup>
 *
 * contentHeight: 内容行高度，默认 280px；列表类模块可传 'auto'。
 */
export function ModuleGroup({ title, badge, extra, children, contentHeight = '280px' }) {
  const slots = { header: { left: null, right: null }, subHeader: { left: null, right: null }, content: { left: null, right: null } };

  const arr = Array.isArray(children) ? children : [children];
  arr.forEach(child => {
    if (!child) return;
    if (child.type === ModuleGroupHeader) slots.header = { left: child.props.left, right: child.props.right };
    else if (child.type === ModuleGroupSubHeader) slots.subHeader = { left: child.props.left, right: child.props.right };
    else if (child.type === ModuleGroupContent) slots.content = { left: child.props.left, right: child.props.right };
  });

  const isAutoHeight = contentHeight === 'auto';
  const resolvedContentHeight = isAutoHeight ? 'auto' : contentHeight;

  return (
    <div className="rounded-xl border p-2.5"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      {/* 通栏标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
        <div className="flex items-center gap-2">
          <h2 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2>
          {badge && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-normal align-middle"
              style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>{badge}</span>
          )}
        </div>
        {extra && (
          <div className="flex items-center gap-2">{extra}</div>
        )}
      </div>

      {/* 左右两栏：标题行 / 副标题行 / 内容行 分别对齐 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2"
        style={{ gridTemplateRows: `auto auto ${resolvedContentHeight}` }}>
        <ModuleCell>{slots.header.left}</ModuleCell>
        <ModuleCell>{slots.header.right}</ModuleCell>
        {slots.subHeader.left || slots.subHeader.right ? (
          <>
            <ModuleCell>{slots.subHeader.left}</ModuleCell>
            <ModuleCell>{slots.subHeader.right}</ModuleCell>
          </>
        ) : null}
        <ModuleContentCell autoHeight={isAutoHeight}>{slots.content.left}</ModuleContentCell>
        <ModuleContentCell autoHeight={isAutoHeight}>{slots.content.right}</ModuleContentCell>
      </div>
    </div>
  );
}

function ModuleGroupHeader() { return null; }
function ModuleGroupSubHeader() { return null; }
function ModuleGroupContent() { return null; }

ModuleGroup.Header = ModuleGroupHeader;
ModuleGroup.SubHeader = ModuleGroupSubHeader;
ModuleGroup.Content = ModuleGroupContent;

export default ModuleGroup;
