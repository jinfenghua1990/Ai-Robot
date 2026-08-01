/**
 * 港股研究中心 / 美股智能交易系统 —— 评分模型、状态体系、策略匹配、市场环境
 *
 * 数据来源说明（已接入真实数据源）：
 *  - 技术维度（价格 / MA5 / MA10 / MA20 / RSI / 区间涨跌 / 偏离度）来自后端真实行情接口（Yahoo，港股回退新浪）。
 *  - 基本面维度（PE / PB / 股息率 / 总市值 / 52周估值分位）来自腾讯 gtimg 实时接口，
 *    由后端 /api/global-market/fundamentals 提供，真实值覆盖下方估算。
 *  - ROE / 营收增速 / 利润增速 / 南向资金 / 主力资金流 / 每股收益超预期等维度，
 *    免费实时源暂不可靠，仍用「确定性估算」（按代码种子，稳定可复现）填充，页面标注「估算」。
 *
 * 模型权重严格遵循两份架构设计文档：
 *  - 港股：基本面30 / 资金25 / 估值20 / 趋势15 / 催化10 = 100
 *  - 美股：趋势30 / 基本面25 / 资金20 / 动量15 / 风险10 = 100
 */

import { apiFetch } from './request';

const clamp = (v, min = 0, max = 1) => Math.max(min, Math.min(max, v));
const round1 = (v) => Math.round(v * 10) / 10;

// ─── 确定性伪随机（按代码种子，保证刷新一致） ───────────────────────────────
function hashStr(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}
function makeRng(seed) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) | 0;
    let t = Math.imul(s ^ (s >>> 15), 1 | s);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * 估算基本面（稳定，按 market+code 种子）
 */
export function estimateFundamentals(market, code) {
  const r = makeRng(hashStr(`${market}:${code}`));
  const pick = (min, max) => min + r() * (max - min);
  return {
    pe: round1(pick(7, 48)),
    pb: round1(pick(0.5, 9)),
    roe: round1(pick(5, 34)), // %
    divYield: round1(pick(0, 7)), // %
    revGrowth: round1(pick(-8, 48)), // %
    earnGrowth: round1(pick(-18, 60)), // %
    grossMargin: round1(pick(18, 78)), // %
    // 港股：南向资金 20 日净流入（亿元，估算）
    southNet20d: round1(pick(-35, 70)),
    // 美股：机构/主力资金流（估算强度 -1..1）
    moneyFlow: round1(pick(-0.8, 0.9) * 10) / 10,
    institutionHold: round1(pick(18, 78)), // %
    cashFlowStable: r() > 0.3,
    vol20: round1(pick(12, 48)), // 年化波动率 %
    pePercentile: round1(pick(5, 95)), // 当前 PE 在历史的百分位
    pbPercentile: round1(pick(5, 95)),
    epsSurprise: round1(pick(-9, 20)), // %
    revSurprise: round1(pick(-7, 18)), // %
    guidance: r() > 0.4, // 是否上调指引
  };
}

// ─── 港股评分模型 ─────────────────────────────────────────────────────────────
export function hkScore(stock, f) {
  // 基本面 30
  let fundamental =
    clamp((f.roe - 5) / 25) * 12 +
    clamp((f.revGrowth + 5) / 40) * 9 +
    clamp((f.earnGrowth + 10) / 60) * 9;
  // 资金 25（南向 + 机构）
  let capital =
    clamp((f.southNet20d + 35) / 95) * 15 +
    clamp((f.institutionHold - 15) / 60) * 10;
  // 估值 20（低 PE 分位 + 低 PB 更优）
  let valuation =
    clamp((40 - f.pePercentile) / 40) * 12 +
    clamp((3.5 - f.pb) / 3) * 8;
  // 趋势 15（真实技术数据）
  let trend = 0;
  if (stock.price && stock.ma20) trend += clamp((stock.price - stock.ma20) / stock.ma20 / 0.1) * 7;
  if (stock.rsi != null) trend += clamp((stock.rsi - 40) / 40) * 4;
  if (stock.change20d != null) trend += clamp((stock.change20d + 10) / 30) * 4;
  // 催化 10
  let catalyst = (f.guidance ? 6 : 3) + clamp(f.epsSurprise / 10) * 4;

  const subs = {
    fundamental: round1(fundamental),
    capital: round1(capital),
    valuation: round1(valuation),
    trend: round1(trend),
    catalyst: round1(catalyst),
  };
  subs.total = round1(subs.fundamental + subs.capital + subs.valuation + subs.trend + subs.catalyst);
  return subs;
}

// ─── 美股评分模型 ─────────────────────────────────────────────────────────────
export function usScore(stock, f) {
  // 趋势 30（MA 排列 + 区间涨幅，真实技术数据）
  let trend = 0;
  if (stock.price && stock.ma20) trend += clamp((stock.price - stock.ma20) / stock.ma20 / 0.08) * 12;
  if (stock.ma5 && stock.ma20) trend += (stock.ma5 > stock.ma20 ? 6 : 0);
  if (stock.change20d != null) trend += clamp(stock.change20d / 25) * 12;
  // 基本面 25
  let fundamental =
    clamp((f.roe - 5) / 25) * 10 +
    clamp((f.revGrowth + 5) / 40) * 8 +
    clamp((f.earnGrowth + 10) / 60) * 7;
  // 资金 20
  let capital = clamp((f.moneyFlow + 0.8) / 1.7) * 10 + clamp((f.institutionHold - 15) / 60) * 10;
  // 动量 15
  let momentum = 0;
  if (stock.rsi != null) momentum += clamp((stock.rsi - 45) / 35) * 7;
  if (stock.change5d != null) momentum += clamp(stock.change5d / 10) * 8;
  // 风险 10（低波动 + 非极端 RSI 更优）
  let risk = clamp((35 - f.vol20) / 30) * 6 + (stock.rsi != null && stock.rsi < 78 ? 4 : 0);

  const subs = {
    trend: round1(trend),
    fundamental: round1(fundamental),
    capital: round1(capital),
    momentum: round1(momentum),
    risk: round1(risk),
  };
  subs.total = round1(subs.trend + subs.fundamental + subs.capital + subs.momentum + subs.risk);
  return subs;
}

// ─── 港股 7 维状态体系 ────────────────────────────────────────────────────────
export function hkStatus(score, stock, f) {
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
export function usStatus(score, stock, f) {
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
  if ((f.southNet20d ?? 0) > 20 && stock.price && stock.ma60 && stock.price > stock.ma60) {
    matched.push('南向资金流入');
  }
  // 价值修复：PE 低位 + ROE 优 + 利润恢复 + 资金流入
  if (f.pePercentile < 35 && f.roe >= 12 && f.earnGrowth > 0 && (f.southNet20d ?? 0) > 0) {
    matched.push('价值修复');
  }
  // 成长趋势：收入增长 + 利润增长 + 趋势突破
  if (f.revGrowth > 18 && f.earnGrowth > 18 && stock.price && stock.ma20 && stock.price > stock.ma20) {
    matched.push('成长趋势');
  }
  // 高股息：股息率>5% + 现金流稳定 + 低波动
  if (f.divYield > 5 && f.cashFlowStable && f.vol20 < 30) {
    matched.push('高股息');
  }
  return matched;
}

// ─── 美股 6 大交易策略 ────────────────────────────────────────────────────────
export function usStrategies(stock, f) {
  const matched = [];
  const price = stock.price, ma20 = stock.ma20, ma5 = stock.ma5;
  // 青龙趋势：MA20>MA50>MA200 + 站上均线 + 资金流入（MA50/200 用估算趋势强度代替）
  if (ma5 && ma20 && ma5 > ma20 && price && price > ma20 && f.moneyFlow > 0.2 && stock.change20d > 5) {
    matched.push('青龙趋势');
  }
  // 白虎突破：突破 60 日新高 + 量>150% + RSI 50-70（用 20 日涨幅近似新高）
  if (stock.change20d != null && stock.change20d > 12 && stock.rsi != null && stock.rsi >= 50 && stock.rsi <= 70) {
    matched.push('白虎突破');
  }
  // 回踩：上涨趋势 + 回调~10% + 缩量 + 均线支撑
  if (stock.change20d != null && stock.change20d > 5 && stock.change5d != null && stock.change5d < -3 && ma20 && price && price > ma20 * 0.95) {
    matched.push('回踩');
  }
  // 财报：EPS / Revenue 超预期 + 上调指引
  if (f.epsSurprise > 5 && f.revSurprise > 3 && f.guidance) {
    matched.push('财报');
  }
  // 低估反转：PE 较低 + ROE 优 + 基本面稳 + 资金流入
  if (f.pePercentile < 40 && f.roe >= 12 && f.moneyFlow > 0.1) {
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
  // 大盘趋势：从指数涨跌近似（恒正且强 → 高分）。真实需 MA200，这里用指数强度估算。
  const idxPct = (indices || []).map((i) => i.change_pct || 0);
  const avgIdx = idxPct.length ? idxPct.reduce((a, b) => a + b, 0) / idxPct.length : 0;
  const trend = clamp((avgIdx + 2) / 4) * 50; // -2%..+2% → 0..50
  // 市场宽度：上涨占比
  const total = stats?.total || 0;
  const breadth = total ? clamp(stats.up / total) * 30 : 0;
  // VIX 风险（估算，标注）：默认 15 左右为低风险。此处给固定估算值。
  const vix = 15.0;
  const vixScore = (vix < 20 ? 20 : vix < 30 ? 10 : 0);
  const totalScore = Math.round(trend + breadth + vixScore);
  let label = '中性';
  if (totalScore >= 80) label = '强势';
  else if (totalScore >= 60) label = '偏多';
  else if (totalScore < 40) label = '弱势';
  return {
    trend: Math.round(trend),
    breadth: Math.round(breadth),
    vix,
    vixScore,
    total: totalScore,
    label,
  };
}

// ─── 港股行业轮动（估算，稳定） ───────────────────────────────────────────────
const HK_SECTOR_DEFS = [
  ['科技', 88], ['互联网', 92], ['半导体', 81], ['创新药', 74],
  ['消费', 68], ['汽车', 71], ['金融', 63], ['能源', 55], ['地产', 48],
];
export function hkSectors() {
  return HK_SECTOR_DEFS.map(([name, heat], i) => {
    const f = estimateFundamentals('HK', `SECTOR${i}`);
    const valuation = Math.round(clamp((55 - f.pePercentile) / 55) * 100);
    const trend = Math.round(clamp((heat - 40) / 60) * 100);
    const capital = Math.round(clamp((f.southNet20d + 35) / 95) * 100);
    const score = Math.round(heat * 0.4 + capital * 0.25 + trend * 0.2 + valuation * 0.15);
    return { name, heatScore: heat, capitalFlow: Math.round(f.southNet20d), trendScore: trend, valuationScore: valuation, score };
  });
}

// ─── 美股行业轮动（估算，稳定） ───────────────────────────────────────────────
const US_SECTOR_DEFS = [
  ['科技 (XLK)', 90], ['半导体 (SMH)', 86], ['通信 (XLC)', 78],
  ['消费 (XLY)', 72], ['医疗 (XLV)', 64], ['金融 (XLF)', 60],
  ['能源 (XLE)', 55], ['工业 (XLI)', 58], ['材料 (XLB)', 50],
];
export function usSectors() {
  return US_SECTOR_DEFS.map(([name, momentum], i) => {
    const f = estimateFundamentals('US', `SECTOR${i}`);
    const gain = Math.round(clamp((momentum - 40) / 60) * 100); // 涨幅
    const capital = Math.round(clamp((f.moneyFlow + 0.8) / 1.7) * 100); // 资金
    const trend = Math.round(clamp((momentum - 40) / 60) * 100); // 趋势
    const strength = gain; // 强度
    const score = Math.round(gain * 0.3 + capital * 0.3 + trend * 0.2 + strength * 0.2);
    return { name, gainScore: gain, capitalFlow: capital, trendScore: trend, strengthScore: strength, score };
  });
}

export const hkStatusColor = (s) => {
  const m = {
    观察: '#6b7280', 低估: '#3b82f6', 资金流入: '#ef4444', 修复启动: '#f59e0b',
    成长加速: '#a855f7', 趋势主升: '#dc2626', 风险退潮: '#22c55e',
  };
  return m[s] || '#6b7280';
};
export const usStatusColor = (s) => {
  const m = {
    观察: '#6b7280', 筑底: '#3b82f6', 启动: '#f59e0b', 趋势: '#ef4444',
    主升: '#dc2626', 高位风险: '#f97316', 退潮: '#22c55e',
  };
  return m[s] || '#6b7280';
};

// ─── 真实数据接入 ─────────────────────────────────────────────────────────────
// 后端 /api/global-market/fundamentals/{market}（腾讯 gtimg）返回每只股票的 real 真实字段：
//   pe / pb / divYield / marketCap(亿元) / pePercentile(52周估值分位)
// 用真实值覆盖 estimateFundamentals 的对应估算，其余维度保留估算。
export async function fetchFundamentals(market) {
  try {
    const res = await apiFetch(`/api/global-market/fundamentals/${market}`, {}, 60000, 0);
    if (res && res.ok && res.data && res.data.items) return res.data.items;
  } catch (e) { /* 失败则回退估算 */ }
  return null;
}

// 港股通南向资金（后端 Eastmoney，尽力取真实，失败为 null）
export async function fetchSouthbound() {
  try {
    const res = await apiFetch(`/api/global-market/southbound`, {}, 40000, 0);
    if (res && res.ok && res.data) return res.data;
  } catch (e) { /* 失败则回退估算 */ }
  return null;
}

/**
 * 合并真实基本面到估算：返回 { f, real }
 *  - f：估算被打底，real 中的真实字段（pe/pb/divYield/marketCap/pePercentile）覆盖之
 *  - real：本次取到的真实字段对象（用于页面「实时」徽标）；null 表示全部为估算
 */
export function mergeFundamentals(market, code, realObj) {
  const est = estimateFundamentals(market, code);
  const real = realObj && realObj.real ? realObj.real : null;
  if (!real || !Object.keys(real).length) return { f: est, real: null };
  return { f: { ...est, ...real }, real };
}
