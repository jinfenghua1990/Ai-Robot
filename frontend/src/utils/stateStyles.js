/**
 * 市场状态样式映射（CHOPPY震荡 / TREND趋势 / IMPULSE主升 / PENDING待算）
 *
 * 统一抽取 SignalCard 和 WatchlistItem 中重复的 STATE_STYLE 定义。
 * 调用方传入 marketState 对象，返回对应的样式对象。
 */

export const STATE_STYLE = {
  CHOPPY:  { bg: 'rgba(100,116,139,0.15)', color: '#64748b', label: '震荡', icon: '〰️' },
  TREND:   { bg: 'rgba(59,130,246,0.15)',  color: '#3b82f6', label: '趋势', icon: '📈' },
  IMPULSE: { bg: 'rgba(239,68,68,0.15)',   color: '#ef4444', label: '主升', icon: '🚀' },
  PENDING: { bg: 'rgba(234,179,8,0.15)',   color: '#eab308', label: '待算', icon: '⏳' },
};

/**
 * 根据 market_state 字段返回样式对象
 * @param {string} state - marketState.market_state 的值
 * @returns {object} 样式对象 { bg, color, label, icon }
 */
export function getMarketStateStyle(state) {
  return STATE_STYLE[state] || STATE_STYLE.PENDING;
}
