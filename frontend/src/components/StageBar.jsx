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

// ===== 趋势阶段（原"生命周期"，8段含分歧）=====
const LIFECYCLE_ORDER = ['观望', '留意', '蓄势', '突破', '加速', '主升', '分歧', '衰退'];
const LIFECYCLE_COLORS = {
  '观望': '#64748b',
  '留意': '#a78bfa',
  '蓄势': '#38bdf8',
  '突破': '#facc15',
  '加速': '#fb923c',
  '主升': '#ef4444',
  '分歧': '#f97316',
  '衰退': '#94a3b8',
};

// 旧名 → 新名映射（兼容后端旧数据）
const LEGACY_LIFECYCLE_MAP = {
  '跟随': '观望', '关注': '留意', '吸筹': '蓄势', '启动': '突破',
  '发酵': '加速', '退潮': '衰退',
};

// ===== 个股强度（原"质量状态"，7段）=====
const QUALITY_ORDER = ['劣质', '中性', '偏强', '强势', '极强', '核心', '淘汰'];
const QUALITY_COLORS = {
  '劣质': '#9CA3AF',
  '中性': '#64748B',
  '偏强': '#2563EB',
  '强势': '#16A34A',
  '极强': '#EA580C',
  '核心': '#DC2626',
  '淘汰': '#111827',
};

const LEGACY_QUALITY_MAP = {
  '杂毛': '劣质', '普通': '中性', '合格': '偏强', '优质': '强势', '强势': '极强',
};

// ===== 情绪温度（7段）=====
const SENTIMENT_ORDER = ['冰点', '恐慌', '谨慎', '中性', '乐观', '狂热', '过热'];
const SENTIMENT_COLORS = {
  '冰点': '#15803d', '恐慌': '#22c55e', '谨慎': '#86efac', '中性': '#94a3b8',
  '乐观': '#fb923c', '狂热': '#ef4444', '过热': '#dc2626',
};

// ===== 风险等级（7段）=====
const RISK_ORDER = ['极安', '安全', '低危', '中等', '高危', '极危', '崩盘'];
const RISK_COLORS = {
  '极安': '#15803d', '安全': '#22c55e', '低危': '#86efac', '中等': '#eab308',
  '高危': '#fb923c', '极危': '#ef4444', '崩盘': '#991b1b',
};

// ===== 资金动能（7段，板块资金面）=====
const MOMENTUM_ORDER = ['暴跌', '流出', '弱流', '平衡', '流入', '强入', '暴入'];
const MOMENTUM_COLORS = {
  '暴跌': '#15803d', '流出': '#22c55e', '弱流': '#86efac', '平衡': '#94a3b8',
  '流入': '#fb923c', '强入': '#ef4444', '暴入': '#dc2626',
};

// ===== 主力资金（7段，个股主力资金专项）=====
const MAIN_FORCE_ORDER = ['出逃', '减仓', '观望', '平衡', '建仓', '强仓', '锁仓'];
const MAIN_FORCE_COLORS = {
  '出逃': '#15803d', '减仓': '#22c55e', '观望': '#86efac', '平衡': '#94a3b8',
  '建仓': '#fb923c', '强仓': '#ef4444', '锁仓': '#dc2626',
};

// ===== 技术形态（7段）=====
const TECHNICAL_ORDER = ['破位', '弱势', '震荡', '偏多', '多头', '突破', '顶部'];
const TECHNICAL_COLORS = {
  '破位': '#ef4444', '弱势': '#fb923c', '震荡': '#94a3b8', '偏多': '#3b82f6',
  '多头': '#8b5cf6', '突破': '#facc15', '顶部': '#dc2626',
};

// ===== 板块共振（7段）=====
const SECTOR_ORDER = ['冷门', '跟随', '联动', '协同', '共振', '领涨', '极热'];
const SECTOR_COLORS = {
  '冷门': '#94a3b8', '跟随': '#60a5fa', '联动': '#22d3ee', '协同': '#22c55e',
  '共振': '#eab308', '领涨': '#fb923c', '极热': '#dc2626',
};

// variant → config 映射
const VARIANT_CONFIGS = {
  lifecycle: { order: LIFECYCLE_ORDER, colors: LIFECYCLE_COLORS, legacyMap: LEGACY_LIFECYCLE_MAP, defaultStage: '观望' },
  quality:   { order: QUALITY_ORDER,   colors: QUALITY_COLORS,   legacyMap: LEGACY_QUALITY_MAP,   defaultStage: '中性' },
  sentiment: { order: SENTIMENT_ORDER, colors: SENTIMENT_COLORS, legacyMap: {}, defaultStage: '中性' },
  risk:      { order: RISK_ORDER,      colors: RISK_COLORS,      legacyMap: {}, defaultStage: '中等' },
  momentum:  { order: MOMENTUM_ORDER,  colors: MOMENTUM_COLORS,  legacyMap: {}, defaultStage: '平衡' },
  mainForce: { order: MAIN_FORCE_ORDER, colors: MAIN_FORCE_COLORS, legacyMap: {}, defaultStage: '平衡' },
  technical: { order: TECHNICAL_ORDER, colors: TECHNICAL_COLORS, legacyMap: {}, defaultStage: '震荡' },
  sector:    { order: SECTOR_ORDER,    colors: SECTOR_COLORS,    legacyMap: {}, defaultStage: '跟随' },
};

// 所有 5 段指标元数据（供 IndicatorSettings 使用）
export const INDICATOR_META = {
  sentiment:    { label: '情绪温度', desc: '涨跌+板块热度+资金方向+量比' },
  momentum:     { label: '资金动能', desc: '板块净流入+3日主力+资金连续性' },
  mainForce:    { label: '主力资金', desc: '主力流向+持仓变化+大单特征+量价配合' },
  technical:    { label: '技术形态', desc: '新高新低+趋势一致性+均线位置+斜率' },
  sector:       { label: '板块共振', desc: '板块热度+热度趋势+上涨比+板块强度' },
  risk:         { label: '风险等级', desc: '噪声比+ATR+形态评分+仓位' },
};

// 根据主力净流入推断趋势阶段
export const inferStage = (value) => {
  if (value >= 10000) return '蓄势';
  if (value >= 1000) return '留意';
  return '观望';
};

// score(0-100) → 阶段名（支持 5 段和 7 段）
export const scoreToStage = (score, variant) => {
  const config = VARIANT_CONFIGS[variant];
  if (!config) return '';
  const order = config.order;
  if (order.length === 5) {
    if (score >= 80) return order[4];
    if (score >= 60) return order[3];
    if (score >= 40) return order[2];
    if (score >= 20) return order[1];
    return order[0];
  }
  // 7段：按 100/7 步长分界
  if (order.length === 7) {
    const step = 100 / 7;
    for (let i = 6; i >= 0; i--) {
      if (score >= step * i) return order[i];
    }
    return order[0];
  }
  return config.defaultStage || '';
};
// 兼容别名
export const scoreTo5Stage = scoreToStage;

export const stageOrder = LIFECYCLE_ORDER;
export const stageColors = LIFECYCLE_COLORS;
export const qualityOrder = QUALITY_ORDER;
export const qualityColors = QUALITY_COLORS;

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
            <div key={s} className="flex-1 text-center text-[8px] leading-tight" style={{
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
