import React from 'react';
import { scoreColor } from './SignalCardUtils';

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

// 游资阶段 → 犀利操作建议标签
export const LEADER_STAGE_MAP = {
  '主升': { label: '主升·加仓',     color: '#dc2626', icon: '🚀' },
  '加速': { label: '加速·追涨',     color: '#fb923c', icon: '🚀' },
  '突破': { label: '突破·跟进',     color: '#facc15', icon: '📈' },
  '启动': { label: '启动·试仓',     color: '#f59e0b', icon: '🔥' },
  '发酵': { label: '发酵·加仓',     color: '#ef4444', icon: '🔥' },
  '分歧': { label: '分歧·减仓',     color: '#22c55e', icon: '⚠️' },
  '蓄势': { label: '蓄势·潜伏',     color: '#3b82f6', icon: '⏳' },
  '留意': { label: '留意·小仓试错', color: '#a78bfa', icon: '👀' },
  '关注': { label: '关注·小仓试错', color: '#a78bfa', icon: '👀' },
  '吸筹': { label: '吸筹·分批建仓', color: '#ef4444', icon: '💰' },
  '跟随': { label: '跟随·轻仓',     color: '#64748b', icon: '👣' },
  '观望': { label: '空仓·不追',     color: '#64748b', icon: '🛑' },
  '衰退': { label: '衰退·清仓',     color: '#22c55e', icon: '🔻' },
  '退潮': { label: '退潮·离场',     color: '#22c55e', icon: '🔻' },
};

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
