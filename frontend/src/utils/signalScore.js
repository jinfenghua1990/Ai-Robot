/**
 * 7 维度信号命中评分（20天跟踪页 + 自选页统一标签体系）
 *
 * 7 个维度：涨跌幅 / 价格阶段 / 竞价溢价 / 振幅 / 主力净流入 / 散户净流入 / 承接力度
 * 每个维度判定为 看多(+1) / 看空(-1) / 中性(0)
 * 命中数 = 看多维度数 - 看空维度数，范围 -7 ~ +7
 *
 * 标签映射：
 *   6-7  → 强多（主升浪）
 *   3-5  → 偏多
 *   -2~2 → 中性
 *   -5~-3→ 偏空
 *   -7~-6→ 强空（退潮）
 */

// 单维度判定: 返回 1(看多) / -1(看空) / 0(中性)
const _scoreDimension = (dim, value, ctx = {}) => {
  switch (dim) {
    case 'pct_chg': {
      if (value == null) return 0;
      if (value > 0) return 1;
      if (value < 0) return -1;
      return 0;
    }
    case 'price_stage': {
      if (['连板', '晋级', '偏多'].includes(value)) return 1;
      if (['跌停A杀', '偏空', '砸盘'].includes(value)) return -1;
      return 0; // 震荡/分歧
    }
    case 'open_premium': {
      if (value == null) return 0;
      if (value >= 1) return 1;
      if (value <= -1) return -1;
      return 0;
    }
    case 'intra_amplitude': {
      // 振幅需要配合涨跌方向: 放量上涨=看多, 放量下跌=看空
      const pct = ctx.pct_chg || 0;
      if (value == null || value < 8) return 0; // 振幅<8% 不算信号
      if (pct > 0) return 1;
      if (pct < 0) return -1;
      return 0;
    }
    case 'main_force_inflow': {
      if (value == null || value === 0) return 0;
      return value > 0 ? 1 : -1;
    }
    case 'retail_flow': {
      // 散户净流入是反向信号: 散户大量流入=主力出货=看空; 散户流出=主力接盘=看多
      if (value == null || value === 0) return 0;
      return value > 0 ? -1 : 1;
    }
    case 'support_level': {
      if (value === '强') return 1;
      if (value === '弱') return -1;
      return 0;
    }
    default:
      return 0;
  }
};

/**
 * 计算 7 维度信号命中数
 * @param {Object} day - DayCell 数据（含 pct_chg/price_stage/open_premium/intra_amplitude/main_force_inflow/retail_flow/support_level）
 * @returns {Object} { score, bullCount, bearCount, neutralCount, label, color, details }
 */
export const computeSignalScore = (day) => {
  if (!day) return null;

  const pctChg = Number(day.pct_chg ?? day.win_rate_impact ?? 0);
  const ctx = { pct_chg: pctChg };

  const dims = [
    { key: 'pct_chg', label: '涨跌', value: pctChg },
    { key: 'price_stage', label: '阶段', value: day.price_stage || '震荡' },
    { key: 'open_premium', label: '竞价', value: Number(day.open_premium || 0) },
    { key: 'intra_amplitude', label: '振幅', value: Number(day.intra_amplitude || 0), ctx },
    { key: 'main_force_inflow', label: '主力', value: Number(day.main_force_inflow || 0) },
    { key: 'retail_flow', label: '散户', value: Number(day.retail_flow || 0) },
    { key: 'support_level', label: '承接', value: day.support_level || '中' },
  ];

  let bullCount = 0;
  let bearCount = 0;
  let neutralCount = 0;
  const details = [];

  dims.forEach(d => {
    const v = d.key === 'intra_amplitude'
      ? _scoreDimension(d.key, d.value, ctx)
      : _scoreDimension(d.key, d.value);
    if (v === 1) bullCount++;
    else if (v === -1) bearCount++;
    else neutralCount++;
    details.push({ label: d.label, value: v });
  });

  const score = bullCount - bearCount; // -7 ~ +7

  // 标签映射
  let label, color, bg;
  if (score >= 6) {
    label = '强多'; color = '#dc2626'; bg = 'rgba(220,38,38,0.2)';
  } else if (score >= 3) {
    label = '偏多'; color = '#ef4444'; bg = 'rgba(239,68,68,0.12)';
  } else if (score >= -2) {
    label = '中性'; color = '#6b7280'; bg = 'rgba(156,163,175,0.12)';
  } else if (score >= -5) {
    label = '偏空'; color = '#16a34a'; bg = 'rgba(22,163,74,0.12)';
  } else {
    label = '强空'; color = '#15803d'; bg = 'rgba(21,128,61,0.2)';
  }

  return {
    score,
    bullCount,
    bearCount,
    neutralCount,
    label,
    color,
    bg,
    details,
  };
};

/**
 * 命中数文字（用于 tooltip / 详情）
 * 例: "5/7看多" / "3/7看空" / "4多2空1中"
 */
export const fmtHitCount = (score) => {
  if (!score) return '—';
  return `${score.bullCount}多${score.bearCount}空${score.neutralCount}中`;
};

/**
 * 3 天趋势评分 — 基于最近 3 天 7 维得分的「平均强度 + 走势方向」
 *
 * 解决痛点: 单看最新一天会被"高位滞涨"骗(最新一天偏多但近3天持续走弱)
 *
 * 算法:
 *   avgScore   = 最近 3 天 7 维得分的平均 (-7~+7)
 *   trajectory = 最新一天 - 3 天前 (正=转强 / 负=转弱)
 *
 * 综合 12 种场景标签（强度 × 方向）:
 *   强势上行  - 平均强多 + 转强 (主升浪加速)
 *   高位滞涨  - 平均强多 + 转弱 (头部预警⚠)
 *   持续走强  - 平均偏多 + 转强 (启动)
 *   上涨乏力  - 平均偏多 + 转弱 (动力衰减)
 *   底部修复  - 平均震荡 + 转强 (有承接)
 *   横盘整理  - 平均震荡 + 平稳
 *   转弱信号  - 平均震荡 + 转弱 (预警)
 *   超跌反弹  - 平均偏弱 + 转强 (可能有买点)
 *   止跌迹象  - 平均弱势 + 转强
 *   持续走弱  - 平均偏弱 + 转弱 (退潮)
 *   继续杀跌  - 平均弱势 + 转弱 (主跌浪)
 *
 * @param {Object} lc - lifecycle_data (含 d1/d2/.../d20)
 * @returns {Object} { avgScore, trajectory, label, color, bg, dailyScores, lastScore, days }
 */
export const computeTrendSignalScore = (lc) => {
  if (!lc || typeof lc !== 'object') return null;

  const keys = Object.keys(lc)
    .filter(k => k.startsWith('d'))
    .map(k => parseInt(k.slice(1), 10))
    .filter(n => !isNaN(n));
  if (!keys.length) return null;

  const maxN = Math.max(...keys);

  // 取最近 3 天(允许缺失,过滤掉)
  const recentDays = [];
  for (let i = 0; i < 3; i++) {
    const d = lc[`d${maxN - i}`];
    if (d) recentDays.push(d);
  }
  if (!recentDays.length) return null;

  const dailyScores = recentDays.map(d => computeSignalScore(d)).filter(Boolean);
  if (!dailyScores.length) return null;

  const scores = dailyScores.map(s => s.score);
  const avgScore = scores.reduce((a, b) => a + b, 0) / scores.length;
  const trajectory = scores.length >= 2 ? (scores[0] - scores[scores.length - 1]) : 0;

  const strong = avgScore >= 4;      // 强多区
  const bull = avgScore >= 1.5;       // 偏多区
  const bear = avgScore <= -1.5;      // 偏空区
  const weak = avgScore <= -4;        // 强空区
  const rising = trajectory >= 2;     // 显著转强
  const falling = trajectory <= -2;   // 显著转弱

  let label, color, bg;
  if (strong && rising) {
    label = '强势上行'; color = '#dc2626'; bg = 'rgba(220,38,38,0.25)';
  } else if (strong && falling) {
    label = '高位滞涨'; color = '#f97316'; bg = 'rgba(249,115,22,0.18)';  // ⚠橙色预警
  } else if (strong) {
    label = '强势'; color = '#dc2626'; bg = 'rgba(220,38,38,0.2)';
  } else if (bull && rising) {
    label = '持续走强'; color = '#ef4444'; bg = 'rgba(239,68,68,0.15)';
  } else if (bull && falling) {
    label = '上涨乏力'; color = '#f97316'; bg = 'rgba(249,115,22,0.12)';
  } else if (bull) {
    label = '偏强'; color = '#ef4444'; bg = 'rgba(239,68,68,0.12)';
  } else if (bear && rising) {
    label = '超跌反弹'; color = '#3b82f6'; bg = 'rgba(59,130,246,0.15)';
  } else if (bear && falling) {
    label = '持续走弱'; color = '#15803d'; bg = 'rgba(21,128,61,0.2)';
  } else if (bear) {
    label = '偏弱'; color = '#16a34a'; bg = 'rgba(22,163,74,0.12)';
  } else if (weak && falling) {
    label = '继续杀跌'; color = '#15803d'; bg = 'rgba(21,128,61,0.28)';
  } else if (weak && rising) {
    label = '止跌迹象'; color = '#3b82f6'; bg = 'rgba(59,130,246,0.18)';
  } else if (weak) {
    label = '弱势'; color = '#15803d'; bg = 'rgba(21,128,61,0.2)';
  } else if (rising) {
    label = '底部修复'; color = '#3b82f6'; bg = 'rgba(59,130,246,0.12)';
  } else if (falling) {
    label = '转弱信号'; color = '#f97316'; bg = 'rgba(249,115,22,0.1)';
  } else {
    label = '横盘整理'; color = '#6b7280'; bg = 'rgba(156,163,175,0.12)';
  }

  return {
    avgScore: Number(avgScore.toFixed(1)),
    trajectory,
    label,
    color,
    bg,
    dailyScores: scores,
    lastScore: dailyScores[0],
    days: recentDays.length,
    maxN,
  };
};

/**
 * 3 天趋势 tooltip 文字
 * 例: "强势上行 (均+4.5 ↑+2) [+5,+4,+3]"
 */
export const fmtTrendTooltip = (trend) => {
  if (!trend) return '—';
  const arrow = trend.trajectory >= 2 ? '↑' : trend.trajectory <= -2 ? '↓' : '→';
  const scoresStr = trend.dailyScores.map(s => (s > 0 ? '+' : '') + s).join(',');
  return `${trend.label} (均${trend.avgScore > 0 ? '+' : ''}${trend.avgScore} ${arrow}${trend.trajectory > 0 ? '+' : ''}${trend.trajectory}) [${scoresStr}] · 最近${trend.days}天`;
};
