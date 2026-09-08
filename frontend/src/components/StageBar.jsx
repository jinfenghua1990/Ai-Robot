/**
 * 等宽分段状态条（支持 8 种 variant，7 段统一标准）
 *
 * variant:
 *   'lifecycle' (8段): 观望 → 留意 → 蓄势 → 突破 → 加速 → 主升 → 分歧 → 衰退
 *   'quality'   (7段): 劣质 → 中性 → 偏强 → 强势 → 极强 → 核心 → 淘汰
 *   'sentiment' (7段): 冰点 → 恐慌 → 谨慎 → 中性 → 乐观 → 狂热 → 过热
 *   'risk'      (7段): 极安 → 安全 → 低危 → 中等 → 高危 → 极危 → 崩盘
 *   'momentum'  (7段): 暴跌 → 流出 → 弱流 → 平衡 → 流入 → 强入 → 暴入
 *   'mainForce' (7段): 出逃 → 减仓 → 观望 → 平衡 → 建仓 → 强仓 → 锁仓
 *   'technical' (7段): 破位 → 弱势 → 震荡 → 偏多 → 多头 → 突破 → 顶部
 *   'sector'    (7段): 冷门 → 跟随 → 联动 → 协同 → 共振 → 领涨 → 极热
 *
 * 7段一致性标准：所有 7 段指标统一使用 100/7 等比分界
 */

import { VARIANT_CONFIGS, inferStage } from '../utils/stageConfig';

export default function StageBar({
  stage,
  value,
  compact = false,
  showLabels = false,
  variant = 'lifecycle',
}) {
  const config = VARIANT_CONFIGS[variant] || VARIANT_CONFIGS.lifecycle;
  const { order, colors, legacyMap, defaultStage } = config;

  // 兼容旧名称
  let mappedStage = stage ? (legacyMap[stage] || stage) : null;
  const finalStage = mappedStage || (variant === 'lifecycle' ? inferStage(value || 0) : defaultStage);
  const currentIdx = order.indexOf(finalStage);
  const isUnknown = currentIdx === -1;

  return (
    <div className="flex-1 flex flex-col gap-0.5 min-w-0 w-full">
      <div className="flex-1 flex items-center gap-1 min-w-0">
        <div className="flex-1 flex h-2 rounded-full overflow-hidden gap-px" style={{ background: 'var(--bg-hover)' }}>
          {order.map((s, i) => (
            <div key={s} className="flex-1 transition-all" style={{
              background: !isUnknown && i <= currentIdx ? colors[s] : 'transparent',
              opacity: !isUnknown && i === currentIdx ? 1 : !isUnknown && i < currentIdx ? 0.5 : 1,
            }} title={s} />
          ))}
        </div>
        <span
          className={`flex-shrink-0 text-right font-bold whitespace-nowrap ${compact ? 'text-[10px] w-7' : 'text-xs w-9'}`}
          style={{ color: isUnknown ? '#9CA3AF' : (colors[finalStage] || '#9CA3AF') }}
        >
          {finalStage}
        </span>
      </div>
      {showLabels && (
        <div className="flex gap-px">
          {order.map((s, i) => (
            <div key={s} className="flex-1 text-center text-[10px] leading-tight" style={{
              color: i === currentIdx ? colors[s] : 'var(--text-muted)',
              fontWeight: i === currentIdx ? 700 : 400,
            }}>
              {s}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
