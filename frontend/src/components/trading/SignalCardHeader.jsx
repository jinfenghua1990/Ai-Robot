import 'react';


// 维度评分 pill：内嵌在各分组标题行，显示该维度的盘后 / 实时评分（带颜色）
export function DimPill({ label, afterVal, rtVal, rtAvail }) {
  const c = (v) => v == null ? null : v >= 70 ? '#ef4444' : v >= 50 ? '#eab308' : v >= 30 ? '#f97316' : '#22c55e';
  const showAfter = afterVal != null;
  const showRt = rtAvail && rtVal != null;
  if (!showAfter && !showRt) return null;
  return (
    <span className="text-[9px] inline-flex items-center gap-0.5 px-1 py-0.5 rounded font-bold whitespace-nowrap"
          style={{ background: 'rgba(148,163,184,0.06)', border: '1px solid rgba(148,163,184,0.18)' }}
          title={`${label}：盘后 ${showAfter ? afterVal : '无数据'} · 实时 ${showRt ? rtVal : '无数据'}`}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      {showAfter && <span className="tabular-nums" style={{ color: c(afterVal) }}>{afterVal}</span>}
      {showRt && <span className="tabular-nums" style={{ color: c(rtVal) }}>/{rtVal}</span>}
    </span>
  );
}

// 统一的模块标题行组件：左侧色块标题 + 右侧结论标签 + 可选辅助数据
export function ModuleHeader({ icon, name, conclusion, conclusionColor = '#64748b', extra = null, title = '', onClick = null }) {
  return (
    <div className="flex items-center justify-between gap-1 mb-0.5 min-h-[18px]">
      <span
        className={onClick ? "text-[11px] font-bold tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap flex-shrink-0 cursor-pointer hover:opacity-80" : "text-[11px] font-bold tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap flex-shrink-0"}
        style={{
          background: 'rgba(59,130,246,0.12)',
          color: 'var(--accent-blue, #3b82f6)',
          border: '1px solid rgba(59,130,246,0.35)',
        }}
        title={onClick ? `${title || ''}（点击查看详情）` : title}
        onClick={onClick || undefined}
      >
        {icon} {name}
      </span>
      <div className="flex items-center gap-1.5 flex-shrink-0 min-w-0">
        {conclusion && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap"
            style={{
              background: `${conclusionColor}1a`,
              color: conclusionColor,
              border: `1px solid ${conclusionColor}40`,
            }}
            title={title}
          >
            {conclusion}
          </span>
        )}
        {extra}
      </div>
    </div>
  );
}
