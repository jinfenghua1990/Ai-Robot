/**
 * 格式化金额：保留2位小数，null返回'--'
 * @param {number} val - 金额
 * @returns {string} 格式化后的字符串
 */
export const formatMoney = (val) => {
  if (val == null) return '--';
  return val.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

/**
 * 安全保留2位小数（null/NaN→'0.00'）
 */
export const f2 = (v) => {
  const n = Number(v);
  return isNaN(n) ? '0.00' : n.toFixed(2);
};

/**
 * 涨跌色：正→红 #ef4444，负→绿 #22c55e，零/NaN→灰 #888
 */
export const colorForPct = (v) => {
  const n = Number(v);
  if (isNaN(n) || n === 0) return '#888';
  return n > 0 ? '#ef4444' : '#22c55e';
};

/**
 * 去掉股票代码的 .SH/.SZ/.BJ 后缀
 */
export const stripCode = (code) => String(code || '').split('.')[0];

/**
 * 格式化盈亏：带正负号 + 2位小数
 * @param {number} val - 盈亏金额
 * @returns {string} 带正负号的字符串
 */
export const formatProfit = (val) => {
  if (val == null) return '--';
  const sign = val >= 0 ? '+' : '';
  return sign + formatMoney(val);
};

/**
 * 格式化金额：万→亿（超过1亿显示亿）
 * @param {number} v - 金额（万元）
 * @returns {string} 格式化后的字符串
 */
export const fmtFlow = (v) => {
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 格式化涨跌幅
 * @param {number} v - 涨跌幅（%）
 * @returns {string} 带正负号的字符串
 */
export const fmtPct = (v) => {
  if (v > 0) return `+${v.toFixed(2)}%`;
  return `${v.toFixed(2)}%`;
};

/**
 * 格式化金额（元为输入单位）：超 1 亿显示"X.XX亿"，超 1 万显示"X.Xw"，否则保留 2 位小数
 * @param {number} v - 金额（元）
 * @returns {string} 格式化后的字符串
 */
export const formatWan = (v) => {
  if (v == null) return '-';
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(1) + 'w';
  return v.toFixed(2);
};

/**
 * 统一百分比格式化：+20.00% / -3.90%（2位小数，带正负号）
 * null/NaN → '—'
 */
export const fmtPct2 = (v) => {
  if (v == null || isNaN(v)) return '—';
  return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
};

/**
 * 统一金额格式化（输入为元）：3.34亿 / 30万 / —
 * null/NaN → '—'
 */
export const fmtAmount = (v) => {
  if (v == null || isNaN(v)) return '—';
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(0) + '万';
  return Math.round(v) + '元';
};

/**
 * 统一缺失值：始终返回 '—'
 */
export const fmtMissing = () => '—';

/**
 * 判断值是否为有效数据（非 null/undefined/NaN/空字符串）
 */
export const hasValue = (v) => v != null && v !== '' && !isNaN(v);

/**
 * 龙头数据 → SignalCard 兼容格式
 * 用于龙头趋势阶段/强度排行/周期V3页面，直接复用模拟盘的 SignalCard 组件
 */
export const leaderToSignal = (leader) => {
  const stage = leader.stage || '突破';
  const stageColors = {
    '观望': '#64748b',
    '留意': '#a78bfa',
    '蓄势': '#38bdf8',
    '突破': '#facc15',
    '加速': '#fb923c',
    '主升': '#ef4444',
    '分歧': '#f97316',
    '衰退': '#94a3b8',
  };
  const stageColor = stageColors[stage] || '#6b7280';
  const changeRate = leader.change_rate || 0;
  const days = leader.consecutive_days || 0;
  const strength = leader.strength || 0;

  const positiveFactors = [];
  const negativeFactors = [];
  const reasons = [];

  // 根据阶段生成看多/看空因素
  if (stage === '观望') {
    negativeFactors.push({ factor: '资金观望', detail: '主力资金未明显介入，处于观望状态', weight: -1 });
  } else if (stage === '留意') {
    positiveFactors.push({ factor: '资金留意', detail: '主力资金开始流入，值得跟踪', weight: 1 });
  } else if (stage === '蓄势') {
    positiveFactors.push({ factor: '主力蓄势', detail: '主力资金大幅流入，潜在突破信号', weight: 2 });
  } else if (stage === '突破') {
    positiveFactors.push({ factor: '突破阶段', detail: '首板涨停，资金开始关注', weight: 2 });
  } else if (stage === '加速') {
    positiveFactors.push({ factor: '加速阶段', detail: `${days}连板，市场共识形成`, weight: 3 });
  } else if (stage === '主升') {
    positiveFactors.push({ factor: '主升阶段', detail: `${days}连板，涨幅扩大`, weight: 2 });
    negativeFactors.push({ factor: '高位风险', detail: '连板高度较大，回调风险增加', weight: -1 });
  } else if (stage === '分歧') {
    negativeFactors.push({ factor: '分歧阶段', detail: '连板中断，多空分歧加大', weight: -2 });
  } else if (stage === '衰退') {
    negativeFactors.push({ factor: '衰退阶段', detail: '资金流出，行情进入尾声', weight: -2 });
  }

  // 涨跌因素
  if (changeRate > 0) {
    positiveFactors.push({ factor: '当日上涨', detail: `涨幅 ${changeRate.toFixed(2)}%`, weight: 1 });
  } else if (changeRate < 0) {
    negativeFactors.push({ factor: '当日下跌', detail: `跌幅 ${changeRate.toFixed(2)}%`, weight: -1 });
  }

  // 连板因素
  if (days >= 3) {
    positiveFactors.push({ factor: '连板强势', detail: `${days}连板`, weight: 1 });
  }

  reasons.push(`阶段：${stage}，强度：${strength.toFixed(0)}，连板：${days}天`);

  return {
    secCode: leader.ts_code,
    secName: leader.name || '',
    signal: stage,
    signalLabel: stage,
    signalColor: stageColor,
    riskLevel: (stage === '分歧' || stage === '衰退') ? 'high' : (stage === '主升' || stage === '蓄势' ? 'medium' : 'low'),
    score: Math.round(strength),
    reasons,
    positiveFactors,
    negativeFactors,
    sector: leader.sector || '未知',
    sectorTrend: { sector: leader.sector, available: false },
    position: {
      profitPct: changeRate,
      posPct: 0,
      dayProfit: 0,
      dayProfitPct: changeRate,
      count: days,
      price: 0,
      costPrice: 0,
      value: 0,
      profit: 0,
    },
  };
};
