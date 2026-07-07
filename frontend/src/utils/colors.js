/**
 * 语义色常量（A股惯例：红涨绿跌）
 *
 * 统一使用此文件常量，避免硬编码 #ef4444 / #22c55e 导致颜色颠倒。
 *
 * 业务语义：
 *   - 涨/盈利/流入/买入/看多/升温/加仓 → 红色系
 *   - 跌/亏损/流出/卖出/看空/降温/清仓 → 绿色系
 */

// 涨跌色（核心）
export const UP_COLOR   = '#ef4444';  // 涨/上涨
export const DOWN_COLOR = '#22c55e';  // 跌/下跌

// 买卖色（与涨跌色一致：买=红，卖=绿）
export const BUY_COLOR  = '#ef4444';  // 买入
export const SELL_COLOR = '#22c55e';  // 卖出

// 资金流向色（流入=红，流出=绿）
export const INFLOW_COLOR  = '#ef4444';  // 资金流入
export const OUTFLOW_COLOR = '#22c55e';  // 资金流出

// BS 信号色（B=买入=红，S=卖出=绿）
export const B_SIGNAL_COLOR = '#ef4444';  // B 点（买入信号）
export const S_SIGNAL_COLOR = '#22c55e';  // S 点（卖出信号）

// 看多/看空色（看多=红，看空=绿）
export const BULLISH_COLOR = '#ef4444';  // 看多
export const BEARISH_COLOR = '#22c55e';  // 看空

// 持仓动作色（加仓=红，清仓=绿）
export const ADD_COLOR     = '#ef4444';  // 加仓（强买）
export const REDUCE_COLOR  = '#84cc16';  // 减仓（弱卖，浅绿）
export const CLEAR_COLOR    = '#22c55e';  // 清仓（强卖）

// 深浅变体（用于 hover / 边框 / 背景）
export const UP_DARK   = '#dc2626';
export const UP_LIGHT  = '#f87171';
export const DOWN_DARK = '#16a34a';
export const DOWN_LIGHT = '#4ade80';

// 背景半透明（用于 tag / badge 背景）
export const upBg   = (alpha = 0.1) => `rgba(239,68,68,${alpha})`;
export const downBg = (alpha = 0.1) => `rgba(34,197,94,${alpha})`;
export const buyBg  = (alpha = 0.1) => `rgba(239,68,68,${alpha})`;
export const sellBg = (alpha = 0.1) => `rgba(34,197,94,${alpha})`;

// 工具函数：根据涨跌返回颜色
export const changeColor = (change) => (change > 0 ? UP_COLOR : change < 0 ? DOWN_COLOR : '#6b7280');
export const flowColor   = (flow)    => (flow > 0 ? INFLOW_COLOR : flow < 0 ? OUTFLOW_COLOR : '#6b7280');

// 评分色：score≥3 加仓（红），≤-5 清仓（绿），中间档灰/橙
export const scoreColor = (score) => {
  if (score <= -5) return DOWN_DARK;   // 清仓：深绿
  if (score <= -2) return REDUCE_COLOR; // 减仓：浅绿
  if (score >= 3)  return UP_COLOR;    // 加仓：红
  return '#6b7280';                     // 观望：灰
};
