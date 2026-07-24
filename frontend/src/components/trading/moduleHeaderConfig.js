// 模块标题标准配置 — 所有卡片模块的「图标 + 名称 + 结论计算规则」集中于此
//
// 用法：
//   import { MODULE_HEADER_CONFIG, calcModuleConclusion, REALTIME_HEADER } from './moduleHeaderConfig';
//   const cfg = MODULE_HEADER_CONFIG.tech;
//   const conclusion = calcModuleConclusion('tech', { ind, kdjJ, macdVal, dif, dea, ma5, ma20, rsiVal });
//   <ModuleHeader icon={cfg.icon} name={cfg.name} conclusion={conclusion.label} conclusionColor={conclusion.color} title={conclusion.title} />
//
// 修改一处规则，所有模块自动生效。新增模块只需在此处加一个 key。

// === 颜色常量 ===
export const COLOR = {
  BULL: '#ef4444',        // 红=买入/看多
  BEAR: '#22c55e',        // 绿=卖出/看空
  CAUTION: '#f97316',     // 橙=谨慎/分歧
  ATTENTION: '#eab308',   // 黄=关注
  NEUTRAL: '#64748b',     // 灰=中性
  RISK: '#dc2626',        // 深红=高危
  STRONG: '#dc2626',      // 主升浪
  BOTTOM: '#3b82f6',      // 超卖低吸
};

// === 模块标题配置 ===
export const MODULE_HEADER_CONFIG = {
  tech: { icon: '📈', name: '个股技术指标' },
  org: { icon: '🏛️', name: '机构 / 游资' },
  flow: { icon: '💰', name: '资金流向' },
  sector: { icon: '🏭', name: '板块' },
  market: { icon: '🌐', name: '市场' },
  bs: { icon: '🎯', name: 'BS 区间' },
  ai: { icon: '🤖', name: 'AI 联动诊断' },
  rt: { icon: '🟢', name: '实时' }, // 右侧实时栏统一用这个
};

// === 各模块结论计算函数 ===
// 每个函数返回 { label, color, title }
// label 是核心操作建议（带方向），color 是 A 股惯例（红涨绿跌）

/**
 * 个股技术指标综合结论
 * 输入：{ kdjJ, macdVal, dif, dea, ma5, ma20, rsiVal }
 * 优先级：超买/超卖 > 金叉/死叉 > 多头/空头排列
 */
export function getTechConclusion(ind = {}) {
  const kdjJ = ind?.kdj_j;
  const macdVal = ind?.macd;
  const dif = ind?.dif, dea = ind?.dea;
  const ma5 = ind?.ma5, ma20 = ind?.ma20;
  const rsiVal = ind?.rsi;
  const isGoldenCross = dif != null && dea != null && dif > dea;
  const isDeathCross = dif != null && dea != null && dif < dea;
  const isMaBull = ma5 != null && ma20 != null && ma5 > ma20;
  const isMaBear = ma5 != null && ma20 != null && ma5 < ma20;
  const isOverbought = (kdjJ != null && kdjJ >= 80) || (rsiVal != null && rsiVal >= 70);
  const isOversold = (kdjJ != null && kdjJ <= 20) || (rsiVal != null && rsiVal <= 30);

  if (isOverbought && isGoldenCross && isMaBull) return { label: '超买·减仓', color: COLOR.CAUTION, title: 'KDJ/RSI 超买 + 金叉多头' };
  if (isOversold) return { label: '超卖·关注反弹', color: COLOR.BOTTOM, title: 'KDJ/RSI 超卖' };
  if (isGoldenCross && isMaBull && macdVal != null && macdVal > 0) return { label: '金叉多头·买入', color: COLOR.BULL, title: 'MACD 金叉 + MA 多头 + 红柱' };
  if (isGoldenCross && isMaBull) return { label: '多头·持有', color: COLOR.BULL, title: 'MACD 金叉 + MA 多头' };
  if (isDeathCross && isMaBear && macdVal != null && macdVal < 0) return { label: '死叉空头·减仓', color: COLOR.BEAR, title: 'MACD 死叉 + MA 空头 + 绿柱' };
  if (isDeathCross && isMaBear) return { label: '空头·谨慎', color: COLOR.BEAR, title: 'MACD 死叉 + MA 空头' };
  if (isMaBull) return { label: '偏多·持有', color: COLOR.BULL, title: 'MA5 > MA20 多头排列' };
  if (isMaBear) return { label: '偏空·观望', color: COLOR.BEAR, title: 'MA5 < MA20 空头排列' };
  return { label: '中性·观望', color: COLOR.NEUTRAL, title: '无显著趋势信号' };
}

/**
 * 机构 / 游资综合结论
 * 输入：{ instNet, yzNet }
 * 基于 4 档组合判断主力行为
 */
export function getOrgConclusion({ instNet, yzNet } = {}) {
  const instPositive = instNet != null && instNet > 0;
  const yzPositive = yzNet != null && yzNet > 0;
  const instNegative = instNet != null && instNet < 0;
  const yzNegative = yzNet != null && yzNet < 0;
  if (instPositive && yzPositive) return { label: '主力吸筹·跟进', color: COLOR.BULL, title: '机构净流入 + 游资净流入' };
  if (instNegative && yzNegative) return { label: '主力出逃·减仓', color: COLOR.BEAR, title: '机构净流出 + 游资净流出' };
  if (instPositive && yzNegative) return { label: '机构买·游资卖·分歧', color: COLOR.CAUTION, title: '机构净流入但游资净流出，分歧加剧' };
  if (instNegative && yzPositive) return { label: '机构卖·游资买·分歧', color: COLOR.CAUTION, title: '机构净流出但游资净流入，分歧加剧' };
  return { label: '无主力信号·观望', color: COLOR.NEUTRAL, title: '机构与游资均无显著动作' };
}

/**
 * 资金流向综合结论
 * 输入：{ hitTags, mainNet }
 * 基于 hitTags.capital + 主力净额方向
 */
export function getFlowConclusion({ hitTags = [], mainNet } = {}) {
  const isCapitalBurst = (hitTags || []).includes('capital');
  if (isCapitalBurst) return { label: '主力爆买·加仓', color: COLOR.STRONG, title: '主力资金爆买信号触发' };
  if (mainNet != null && mainNet > 0) return { label: '资金流入·持有', color: COLOR.BULL, title: '主力净流入' };
  if (mainNet != null && mainNet < 0) return { label: '资金流出·减仓', color: COLOR.BEAR, title: '主力净流出' };
  return { label: null, color: COLOR.NEUTRAL, title: '无主力资金数据' };
}

/**
 * 板块综合结论 — 直接使用已计算的 sectorEffect
 * 输入：sectorEffect 对象（{ label, color, icon }）+ 板块基础数据
 */
export function getSectorConclusion(sectorEffect, sector, limitUp, secAvgChg) {
  return {
    label: sectorEffect?.label || null,
    color: sectorEffect?.color || COLOR.NEUTRAL,
    title: `板块: ${sector || '--'} · 涨停 ${limitUp ?? 0} · 涨幅 ${secAvgChg != null ? secAvgChg.toFixed(2) + '%' : '--'}`,
  };
}

/**
 * 市场综合结论 — 精简为单行仓位建议
 * 输入：{ riskStage, riskScore, msState }
 * 输出：{ label, color, title, position, extra }
 *
 * 系统性风险 veto：高危强制清仓，与个股板块信号无关
 * 与板块微观判断形成宏观-微观双层：板块=个股战场，市场=系统性风险背景
 */
export function getMarketConclusion({ riskStage, riskScore, msState } = {}) {
  const positionMap = {
    '高危':   { label: '0-20%·果断清仓', color: COLOR.RISK, position: '0-20%' },
    '高风险': { label: '0-20%·果断清仓', color: COLOR.RISK, position: '0-20%' },
    '警戒':   { label: '20-40%·减仓防守', color: COLOR.BULL, position: '20-40%' },
    '中风险': { label: '40-60%·谨慎', color: COLOR.CAUTION, position: '40-60%' },
    '关注':   { label: '60-80%·持有', color: COLOR.ATTENTION, position: '60-80%' },
    '低风险': { label: '80-100%·可加仓', color: COLOR.BEAR, position: '80-100%' },
    '安全':   { label: '80-100%·可加仓', color: COLOR.BEAR, position: '80-100%' },
  };
  const posInfo = riskStage ? (positionMap[riskStage] || { label: riskStage, color: COLOR.NEUTRAL, position: '--' }) : null;
  const stateAbbrev = {
    'IMPULSE': '脉冲',
    'TREND': '趋势',
    'CHOPPY': '震荡',
    'PENDING': '待计算',
    'UNKNOWN': '未知',
  };
  const stateLabel = stateAbbrev[msState] || null;
  return {
    label: posInfo?.label || null,
    color: posInfo?.color || COLOR.NEUTRAL,
    position: posInfo?.position || '--',
    stateLabel,
    title: `市场状态: ${msState || '--'} · 风险等级: ${riskStage || '--'} · 风险评分: ${riskScore != null ? riskScore : '--'}`,
  };
}

/**
 * 实时栏标题 — 右侧实时栏的动态时间标签
 * 输入：rtDash（{ mode, snapshot_time }）
 * 输出：{ label, color, title }
 * mode: live=今天盘中；closed_today=今日已收盘；previous=回退到最近交易日
 */
export function getRealtimeHeader(rtDash) {
  if (!rtDash) return { label: '🟢 实时', color: COLOR.NEUTRAL, title: '' };
  const mode = rtDash.mode;
  const iso = rtDash.snapshot_time;
  let timeStr = '';
  let dateStr = '';
  if (iso) {
    const dt = new Date(iso);
    if (!Number.isNaN(dt.getTime())) {
      const hh = String(dt.getHours()).padStart(2, '0');
      const mm = String(dt.getMinutes()).padStart(2, '0');
      timeStr = `${hh}:${mm}`;
      const md = `${dt.getMonth() + 1}月${dt.getDate()}日`;
      dateStr = md;
    }
  }
  if (mode === 'live') return { label: `🟢 实时滚动 ${timeStr}`.trim(), color: COLOR.BEAR, title: `快照: ${iso || ''}` };
  if (mode === 'closed_today') return { label: `🟠 盘后定格 ${timeStr}`.trim(), color: COLOR.CAUTION, title: `快照: ${iso || ''}` };
  if (mode === 'previous') return { label: `上一交易日 ${dateStr} ${timeStr}`.trim(), color: COLOR.NEUTRAL, title: `快照: ${iso || ''}` };
  return { label: timeStr ? `🟢 ${timeStr}` : '🟢 实时', color: COLOR.NEUTRAL, title: `快照: ${iso || ''}` };
}

/**
 * 提取实时栏标签的纯净文本（去除前缀 emoji）
 * 配合 ModuleHeader 使用：右侧标题只显示时间部分，emoji 由 ModuleHeader 的 icon 提供
 */
export function stripRealtimePrefix(label = '') {
  return label.replace(/^🟢\s*/, '').replace(/^🟠\s*/, '').replace(/^上一交易日\s*/, '上一交易日 ');
}
