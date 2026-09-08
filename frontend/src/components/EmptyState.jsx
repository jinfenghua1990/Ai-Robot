/**
 * 空数据占位组件
 * 统一全站"暂无数据"、"空空如也"等场景
 */
export default function EmptyState({ icon = '📭', text = '暂无数据', subText }) {
  return (
    <div className="flex flex-col items-center justify-center py-12 gap-2">
      <span className="text-3xl opacity-30">{icon}</span>
      <span className="text-sm" style={{ color: 'var(--text-muted)' }}>{text}</span>
      {subText && <span className="text-xs" style={{ color: 'var(--text-muted)', opacity: 0.6 }}>{subText}</span>}
    </div>
  );
}
