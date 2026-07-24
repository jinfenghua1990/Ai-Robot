/**
 * 页面级加载状态（Lazy Load 时的 Suspense fallback）
 * 覆盖高度可调节
 */
export default function PageLoader({ height = '24rem' }) {
  return (
    <div className="flex items-center justify-center" style={{ height, background: 'var(--bg-primary)' }}>
      <div className="flex items-center gap-2">
        <div className="w-5 h-5 border-2 rounded-full animate-spin"
          style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</span>
      </div>
    </div>
  );
}
