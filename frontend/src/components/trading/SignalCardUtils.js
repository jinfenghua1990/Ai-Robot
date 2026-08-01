/* Auto-extracted from SignalCardV4.jsx - pure utility functions */
export const UP_COLOR = '#ef4444';
export const DOWN_COLOR = '#22c55e';
export const fmtWanYi = (v, fromYuan = false) => {
  const wan = fromYuan ? (v || 0) / 10000 : (v || 0);
  if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
  return `${wan.toFixed(fromYuan ? 2 : 0)}万`;
};

// 模块级常量与纯函数：避免每次 render 重建，降低 GC 压力

// 12 维评分维度键（原本定义在组件内部，每次 render 重建）
export const DIM_KEYS = ['trend_strength','capital_momentum','sector_resonance','relative_strength','volume_health','volatility_health','drawdown_status','institution_signal'];

// EMA 计算（纯函数）
export const calcEma = (arr, n) => {
  const k = 2 / (n + 1);
  let prev = arr[0];
  return arr.map((v, i) => (prev = i === 0 ? v : v * k + prev * (1 - k)));
};

// 实时 MACD：基于当日分时价格序列计算（参数 idPrices 显式传入）
export const calcIntradayMacd = (idPrices) => {
  if (idPrices.length < 26) return null;
  const e12 = calcEma(idPrices, 12);
  const e26 = calcEma(idPrices, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = calcEma(dif, 9);
  const n = dif.length;
  return { dif: dif[n - 1], dea: dea[n - 1], macd: 2 * (dif[n - 1] - dea[n - 1]) };
};

// 实时 KDJ：基于当日分时价格序列计算（参数 idPrices 显式传入）
export const calcIntradayKdj = (idPrices) => {
  const N = 9;
  if (idPrices.length < N) return null;
  let k = 50, d = 50;
  for (let i = N - 1; i < idPrices.length; i++) {
    const win = idPrices.slice(i - N + 1, i + 1);
    const hh = Math.max(...win), ll = Math.min(...win);
    const rsv = hh === ll ? 50 : ((idPrices[i] - ll) / (hh - ll)) * 100;
    k = (2 / 3) * k + (1 / 3) * rsv;
    d = (2 / 3) * d + (1 / 3) * k;
  }
  return { k, d, j: 3 * k - 2 * d };
};

// 评分颜色映射：70+深红 50+黄 30+橙 <30绿
export const scoreColor = (v) => (v == null ? 'var(--text-muted)' : v >= 70 ? '#ef4444' : v >= 50 ? '#eab308' : v >= 30 ? '#f97316' : '#22c55e');

// 即使当前是 13:18，右侧仍然显示 15:00，与交易软件一致。
export const TRADING_SESSIONS = [
  { start: 9 * 60 + 30, end: 11 * 60 + 30 },  // 9:30-11:30 = 120 分钟
  { start: 13 * 60, end: 15 * 60 },            // 13:00-15:00 = 120 分钟
];
export const TOTAL_TRADING_MINUTES = 240;
export const SESSION_LABELS = ['9:30', '11:30', '13:00', '15:00'];

export function timeStrToMinutes(t) {
  if (!t || typeof t !== 'string') return null;
  const m = t.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

// 将 HH:MM 转换为 X 轴位置（0-240 映射到 0-W）
export function minuteToX(minute, W) {
  let pos = 0;
  for (const s of TRADING_SESSIONS) {
    if (minute < s.start) break;          // 开盘前，留在起点
    if (minute <= s.end) {
      pos += (minute - s.start);
      return (pos / TOTAL_TRADING_MINUTES) * W;
    }
    pos += (s.end - s.start);              // 跳过午休
  }
  return W;                                // 收盘后，固定在最右
}
