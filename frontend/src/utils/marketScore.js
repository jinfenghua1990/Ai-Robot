/**
 * 港股研究中心 / 美股智能交易系统 —— 评分模型、状态体系、策略匹配、市场环境
 *
 * 页面只消费后端已经入库的数据。缺失的基本面、资金或行业字段保持为空，
 * 不用代码种子、固定值或其他合成数据填补。
 *
 * 模型权重严格遵循两份架构设计文档：
 *  - 港股：基本面30 / 资金25 / 估值20 / 趋势15 / 催化10 = 100
 *  - 美股：趋势30 / 基本面25 / 资金20 / 动量15 / 风险10 = 100
 */

import { apiFetch } from './request';

const clamp = (v, min = 0, max = 1) => Math.max(min, Math.min(max, v));
const round1 = (v) => Math.round(v * 10) / 10;

/** 返回显式缺失值，保留旧导出名仅为兼容现有调用方。 */
export function estimateFundamentals() {
  return {
    pe: null, pb: null, roe: null, divYield: null,
    revGrowth: null, earnGrowth: null, grossMargin: null,
    southNet20d: null, moneyFlow: null, institutionHold: null,
    cashFlowStable: null, vol20: null, pePercentile: null,
    pbPercentile: null, epsSurprise: null, revSurprise: null,
    guidance: null,
  };
}

// ─── 港股评分模型 ─────────────────────────────────────────────────────────────
export function hkScore(stock, f) {
  const finite = (...values) => values.every((value) => value != null && value !== '' && Number.isFinite(Number(value)));
  // 基本面 30
  let fundamental = finite(f.roe, f.revGrowth, f.earnGrowth) ?
    clamp((f.roe - 5) / 25) * 12 +
    clamp((f.revGrowth + 5) / 40) * 9 +
    clamp((f.earnGrowth + 10) / 60) * 9 : null;
  // 资金 25（南向 + 机构）
  let capital = finite(f.southNet20d, f.institutionHold) ?
    clamp((f.southNet20d + 35) / 95) * 15 +
    clamp((f.institutionHold - 15) / 60) * 10 : null;
  // 估值 20（低 PE 分位 + 低 PB 更优）
  let valuation = finite(f.pePercentile, f.pb) ?
    clamp((40 - f.pePercentile) / 40) * 12 +
    clamp((3.5 - f.pb) / 3) * 8 : null;
  // 趋势 15（真实技术数据）
  let trend = 0;
  if (stock.price && stock.ma20) trend += clamp((stock.price - stock.ma20) / stock.ma20 / 0.1) * 7;
  if (stock.rsi != null) trend += clamp((stock.rsi - 40) / 40) * 4;
  if (stock.change20d != null) trend += clamp((stock.change20d + 10) / 30) * 4;
  // 催化 10
  let catalyst = typeof f.guidance === 'boolean' && finite(f.epsSurprise)
    ? (f.guidance ? 6 : 3) + clamp(f.epsSurprise / 10) * 4
    : null;

  const subs = {
    fundamental: fundamental == null ? null : round1(fundamental),
    capital: capital == null ? null : round1(capital),
    valuation: valuation == null ? null : round1(valuation),
    trend: stock.price != null ? round1(trend) : null,
    catalyst: catalyst == null ? null : round1(catalyst),
  };
  const complete = Object.values(subs).every((value) => value != null);
  subs.total = complete ? round1(Object.values(subs).reduce((sum, value) => sum + value, 0)) : null;
  return subs;
}

// ─── 美股评分模型 ─────────────────────────────────────────────────────────────
export function usScore(stock, f) {
  const finite = (...values) => values.every((value) => value != null && value !== '' && Number.isFinite(Number(value)));
  // 趋势 30（MA 排列 + 区间涨幅，真实技术数据）
  let trend = 0;
  if (stock.price && stock.ma20) trend += clamp((stock.price - stock.ma20) / stock.ma20 / 0.08) * 12;
  if (stock.ma5 && stock.ma20) trend += (stock.ma5 > stock.ma20 ? 6 : 0);
  if (stock.change20d != null) trend += clamp(stock.change20d / 25) * 12;
  // 基本面 25
  const fundamental = finite(f.roe, f.revGrowth, f.earnGrowth) ?
    clamp((f.roe - 5) / 25) * 10 +
    clamp((f.revGrowth + 5) / 40) * 8 +
    clamp((f.earnGrowth + 10) / 60) * 7 : null;
  // 资金 20
  const capital = finite(f.moneyFlow, f.institutionHold)
    ? clamp((f.moneyFlow + 0.8) / 1.7) * 10 + clamp((f.institutionHold - 15) / 60) * 10
    : null;
  // 动量 15
  let momentum = 0;
  if (stock.rsi != null) momentum += clamp((stock.rsi - 45) / 35) * 7;
  if (stock.change5d != null) momentum += clamp(stock.change5d / 10) * 8;
  // 风险 10（低波动 + 非极端 RSI 更优）
  const risk = finite(f.vol20) && stock.rsi != null
    ? clamp((35 - f.vol20) / 30) * 6 + (stock.rsi < 78 ? 4 : 0)
    : null;

  const subs = {
    trend: stock.price != null && stock.ma20 != null ? round1(trend) : null,
    fundamental: fundamental == null ? null : round1(fundamental),
    capital: capital == null ? null : round1(capital),
    momentum: stock.rsi != null && stock.change5d != null ? round1(momentum) : null,
    risk: risk == null ? null : round1(risk),
  };
  const complete = Object.values(subs).every((value) => value != null);
  subs.total = complete ? round1(Object.values(subs).reduce((sum, value) => sum + value, 0)) : null;
  return subs;
}

// ─── 港股 7 维状态体系 ────────────────────────────────────────────────────────
export function hkStatus(score, stock, f) {
  if (score.total == null) return '数据不足';
  const upTrend = stock.price && stock.ma20 && stock.price > stock.ma20 && stock.change20d != null && stock.change20d > 0;
  const strong = score.total >= 70;
  if ((f.southNet20d ?? 0) < -10 && stock.price && stock.ma20 && stock.price < stock.ma20) return '风险退潮';
  if (f.pePercentile < 30 && f.roe >= 12) return '低估';
  if ((f.southNet20d ?? 0) > 25) return '资金流入';
  if (f.pePercentile < 45 && f.earnGrowth > 5 && (f.southNet20d ?? 0) > 0) return '修复启动';
  if (f.revGrowth > 20 && f.earnGrowth > 20 && (f.southNet20d ?? 0) > 10) return '成长加速';
  if (upTrend && strong && stock.price && stock.ma60 && stock.price > stock.ma60) return '趋势主升';
  return '观察';
}

// ─── 美股 7 维状态体系 ────────────────────────────────────────────────────────
export function usStatus(score, stock) {
  if (score.total == null) return '数据不足';
  const price = stock.price;
  const ma20 = stock.ma20;
  const ch20 = stock.change20d;
  if (price && ma20 && price < ma20 && ch20 != null && ch20 < -8) return '退潮';
  if (stock.rsi != null && stock.rsi > 78) return '高位风险';
  if (price && ma20 && price > ma20 && stock.ma5 && stock.ma5 > ma20 && ch20 != null && ch20 > 12) return '主升';
  if (price && ma20 && price > ma20 && ch20 != null && ch20 > 3) return '趋势';
  if (price && ma20 && price > ma20 && ch20 != null && ch20 > 0) return '启动';
  if (price && ma20 && price < ma20 && ch20 != null && ch20 > -3) return '筑底';
  return '观察';
}

// ─── 港股 4 大选股策略 ────────────────────────────────────────────────────────
export function hkStrategies(stock, f) {
  const matched = [];
  // 南向资金流入：20日净流入 + 站上 MA60 + 量能提升
  if (f.southNet20d != null && f.southNet20d > 20 && stock.price && stock.ma60 && stock.price > stock.ma60) {
    matched.push('南向资金流入');
  }
  // 价值修复：PE 低位 + ROE 优 + 利润恢复 + 资金流入
  if (f.pePercentile != null && f.roe != null && f.earnGrowth != null && f.southNet20d != null && f.pePercentile < 35 && f.roe >= 12 && f.earnGrowth > 0 && f.southNet20d > 0) {
    matched.push('价值修复');
  }
  // 成长趋势：收入增长 + 利润增长 + 趋势突破
  if (f.revGrowth != null && f.earnGrowth != null && f.revGrowth > 18 && f.earnGrowth > 18 && stock.price && stock.ma20 && stock.price > stock.ma20) {
    matched.push('成长趋势');
  }
  // 高股息：股息率>5% + 现金流稳定 + 低波动
  if (f.divYield != null && f.vol20 != null && f.divYield > 5 && f.cashFlowStable === true && f.vol20 < 30) {
    matched.push('高股息');
  }
  return matched;
}

// ─── 美股 6 大交易策略 ────────────────────────────────────────────────────────
export function usStrategies(stock, f) {
  const matched = [];
  const price = stock.price, ma20 = stock.ma20, ma50 = stock.ma50, ma200 = stock.ma200;
  const finite = (...values) => values.every((value) => value != null && value !== '' && Number.isFinite(Number(value)));
  // 青龙趋势：只在实际均线和资金数据齐全时匹配。
  if (finite(price, ma20, ma50, ma200, f.moneyFlow)
      && price > ma20 && ma20 > ma50 && ma50 > ma200 && f.moneyFlow > 0.2) {
    matched.push('青龙趋势');
  }
  // 白虎突破：不用涨幅代替新高和量比。
  if (finite(price, stock.high60, stock.volumeRatio, stock.rsi)
      && price >= stock.high60 && stock.volumeRatio >= 1.5 && stock.rsi >= 50 && stock.rsi <= 70) {
    matched.push('白虎突破');
  }
  // 回踩：上涨趋势 + 回调~10% + 缩量 + 均线支撑
  if (stock.change20d != null && stock.change20d > 5 && stock.change5d != null && stock.change5d < -3 && ma20 && price && price > ma20 * 0.95) {
    matched.push('回踩');
  }
  // 财报：EPS / Revenue 超预期 + 上调指引
  if (finite(f.epsSurprise, f.revSurprise) && f.epsSurprise > 5 && f.revSurprise > 3 && f.guidance === true) {
    matched.push('财报');
  }
  // 低估反转：PE 较低 + ROE 优 + 基本面稳 + 资金流入
  if (finite(f.pePercentile, f.roe, f.moneyFlow) && f.pePercentile < 40 && f.roe >= 12 && f.moneyFlow > 0.1) {
    matched.push('低估反转');
  }
  // ETF 轮动：仅对主流 ETF 标的生效
  if (['QQQ', 'SMH', 'XLK', 'XLE', 'XLV', 'SPY'].includes(stock.code)) {
    matched.push('ETF轮动');
  }
  return matched;
}

// ─── 美股市场环境评分（0-100） ────────────────────────────────────────────────
export function usMarketEnv(indices, stats) {
  // 大盘趋势是对已入库指数涨跌的派生分项，不代替 MA200。
  const idxPct = (indices || []).map((i) => i.change_pct || 0);
  const avgIdx = idxPct.length ? idxPct.reduce((a, b) => a + b, 0) / idxPct.length : 0;
  const trend = clamp((avgIdx + 2) / 4) * 50; // -2%..+2% → 0..50
  // 市场宽度：上涨占比
  const total = stats?.total || 0;
  const breadth = total ? clamp(stats.up / total) * 30 : 0;
  // 没有已入库 VIX 时不补固定值，也不生成不完整的总分。
  const vix = null;
  const vixScore = null;
  const totalScore = null;
  const label = '数据不足';
  return {
    trend: Math.round(trend),
    breadth: Math.round(breadth),
    vix,
    vixScore,
    total: totalScore,
    label,
  };
}

// ─── 行业轮动：由数据库快照接口提供，缺失时返回空 ───────────────────────────
export function hkSectors() {
  return [];
}

export function usSectors() {
  return [];
}

export const hkStatusColor = (s) => {
  const m = {
    观察: '#6b7280', 低估: '#3b82f6', 资金流入: '#ef4444', 修复启动: '#f59e0b',
    成长加速: '#a855f7', 趋势主升: '#dc2626', 风险退潮: '#22c55e', 数据不足: '#6b7280',
  };
  return m[s] || '#6b7280';
};
export const usStatusColor = (s) => {
  const m = {
    观察: '#6b7280', 筑底: '#3b82f6', 启动: '#f59e0b', 趋势: '#ef4444',
    主升: '#dc2626', 高位风险: '#f97316', 退潮: '#22c55e', 数据不足: '#6b7280',
  };
  return m[s] || '#6b7280';
};

// ─── 真实数据接入 ─────────────────────────────────────────────────────────────
// 后端 /api/global-market/fundamentals/{market} 返回已入库的基本面快照：
//   pe / pb / divYield / marketCap(亿元) / pePercentile(52周估值分位)
export async function fetchFundamentals(market) {
  try {
    const res = await apiFetch(`/api/global-market/fundamentals/${market}`, {}, 60000, 0);
    if (res && res.ok && res.data && res.data.items) return res.data;
  } catch { /* 数据库查询失败时保持缺失 */ }
  return null;
}

// 港股通南向资金（后端数据库快照，缺失时为 null）
export async function fetchSouthbound() {
  try {
    const res = await apiFetch(`/api/global-market/southbound`, {}, 40000, 0);
    if (res && res.ok && res.data) return res.data;
  } catch { /* 数据库查询失败时保持缺失 */ }
  return null;
}

/**
 * 合并数据库基本面快照：返回 { f, real }。
 * 未入库的字段保持 null，不用估算值打底。
 */
export function mergeFundamentals(market, code, realObj) {
  const est = estimateFundamentals();
  const real = realObj && realObj.real ? realObj.real : null;
  if (!real || !Object.keys(real).length) return { f: est, real: null };
  return { f: { ...est, ...real }, real };
}
