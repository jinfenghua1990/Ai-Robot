import React from 'react';
import { UP_COLOR, DOWN_COLOR } from '../../utils/colors';
import { TRADING_SESSIONS, TOTAL_TRADING_MINUTES, SESSION_LABELS, timeStrToMinutes, minuteToX, scoreColor } from './SignalCardUtils';

export function IntradaySparkline({ data, showPriceLabel = true }) {
  if (!data || data.length < 2) return null;
  const W = 240, H = 38, padY = 5;
  const prices = data.map((d) => d.price).filter((v) => v != null);
  if (prices.length < 2) return null;
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min || 1;
  const last = data[data.length - 1];
  const up = (last.pct_chg ?? 0) >= 0;
  const stroke = up ? '#ef4444' : '#22c55e'; // 红涨绿跌
  // X 轴：按实际时间映射到固定交易时段位置
  const x = (d) => {
    const m = timeStrToMinutes(d.t);
    return m == null ? 0 : minuteToX(m, W);
  };
  const y = (p) => padY + (1 - (p - min) / span) * (H - 2 * padY);
  const pts = data.map((d) => (d.price == null ? null : `${x(d).toFixed(1)},${y(d.price).toFixed(1)}`)).filter(Boolean);
  const line = pts.join(' ');
  // 面积从首个点开始（不是从 X=0 开始），让折线与面积对齐
  const firstX = pts.length > 0 ? pts[0].split(',')[0] : '0';
  const area = `${firstX},${H} ${line} ${W},${H}`;
  // 当前价格点位置（用于在 SVG 内部右上角标注价格涨幅）
  const lastX = pts.length > 0 ? parseFloat(pts[pts.length - 1].split(',')[0]) : W;
  const priceLabelX = lastX > W * 0.6 ? Math.max(2, lastX - 2) : Math.min(W - 50, lastX + 4);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: 'block' }}>
        {/* 午休分割线（11:30/13:00 之间为空白） */}
        <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--border-color)" strokeWidth={0.5} strokeDasharray="2,2" opacity={0.4} />
        <polygon points={area} fill={stroke} opacity={0.08} />
        <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.2} strokeLinejoin="round" />
      </svg>
      {/* 时间标签行：9:30 / 11:30 / 13:00 / 15:00，避免居中涨幅文字挤在中间 */}
      <div style={{ position: 'relative', width: '100%', height: '12px', fontSize: '9px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
        {/* 9:30 → 0%（左对齐） */}
        <span style={{ position: 'absolute', left: '0%', transform: 'translateX(0)' }}>9:30</span>
        {/* 11:30 → 50%（右对齐，标签右边贴着午休点） */}
        <span style={{ position: 'absolute', left: '50%', transform: 'translateX(-100%)', paddingRight: '2px' }}>11:30</span>
        {/* 13:00 → 50%（左对齐，标签左边贴着午休点） */}
        <span style={{ position: 'absolute', left: '50%', transform: 'translateX(0)', paddingLeft: '2px' }}>13:00</span>
        {/* 15:00 → 100%（右对齐） */}
        <span style={{ position: 'absolute', left: '100%', transform: 'translateX(-100%)' }}>15:00</span>
      </div>
      {/* 涨幅独立行：右下角显示价格 + 涨幅，与时间标签分离避免重叠（默认显示，外面已经在「当日」位置展示过时可关闭） */}
      {showPriceLabel && (
        <div style={{ position: 'relative', width: '100%', height: '11px', fontSize: '9px', whiteSpace: 'nowrap' }}>
          <span className="font-bold" style={{ position: 'absolute', right: '0%', color: stroke }}>
            {last.price?.toFixed(2)} {up ? '↑' : '↓'}{Math.abs(last.pct_chg ?? 0).toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}

// BS 区间日 K 迷你走势：收盘价折线 + B 起点 / S 终点（带竖虚线+标签）+ 起止日期 + 区间盈亏%
// 颜色遵循 A 股惯例：红涨绿跌（project_memory 硬约束）
// klines: [{date, open, close, high, low, volume}, ...]
// bsInt: {state, start_date, start_price, end_date, end_price, hold_days, pnl_pct}
export function BSRangeSparkline({ klines, bsInt }) {
  if (!klines || klines.length < 1) return null;
  // viewBox 与实际像素 1:1，避免 preserveAspectRatio="none" 拉伸导致文字扭曲
  const W = 240, H = 48, padY = 10, padX = 8;
  const closes = klines.map((k) => k.close).filter((v) => v != null);
  if (closes.length < 1) return null;
  const sp = bsInt?.start_price;
  const ep = bsInt?.end_price;
  // y 轴范围：纳入 B 起点 / S 终点价格 + 10% padding，确保标记在可视区内
  const allVals = [...closes];
  if (sp != null) allVals.push(sp);
  if (ep != null) allVals.push(ep);
  const rawMin = Math.min(...allVals), rawMax = Math.max(...allVals);
  const rawSpan = (rawMax - rawMin) || Math.abs(rawMin) * 0.02 || 1;
  const min = rawMin - rawSpan * 0.15;
  const max = rawMax + rawSpan * 0.15;
  const span = max - min || 1;
  const n = klines.length;
  const isSingle = n === 1;
  // x 轴：按日期均匀分布在整个图宽
  const x = (i) => (n <= 1 ? W * 0.5 : padX + (i / (n - 1)) * (W - 2 * padX));
  const y = (p) => padY + (1 - (p - min) / span) * (H - 2 * padY);
  const last = klines[n - 1];
  const first = klines[0];
  const up = (last.close ?? 0) >= (first.close ?? 0);
  const stroke = up ? '#ef4444' : '#22c55e';
  const pts = klines.map((d, i) => (d.close == null ? null : `${x(i).toFixed(1)},${y(d.close).toFixed(1)}`)).filter(Boolean);
  const line = pts.join(' ');
  const area = `${padX},${H} ${line} ${W - padX},${H}`;
  const sd = bsInt?.start_date || '';
  const ed = bsInt?.end_date || '今';
  const pnl = bsInt?.pnl_pct;
  const pnlColor = pnl == null ? '#94a3b8' : pnl >= 0 ? '#ef4444' : '#22c55e';
  const isHolding = bsInt?.state === 'holding';
  const epColor = isHolding ? '#ef4444' : '#f97316';
  const epLabel = isHolding ? '现' : 'S';
  // B 点位置：在 60 天 klines 中找到 B 点日期对应的索引
  // 单点时强制左右分开（B 在左 1/4，现价在右 3/4）
  const bIdx = isSingle ? -1 : klines.findIndex(k => (k.date || '').slice(0, 10) === (sd || '').slice(0, 10));
  const bx = isSingle ? W * 0.25 : (bIdx >= 0 ? x(bIdx) : padX);
  const ex = isSingle ? W * 0.75 : W - padX;
  // 标签 y 位置：B 标签固定在上方，现价标签固定在下方，避免重叠
  const bLabelY = Math.max(11, y(sp) - 5);
  const eLabelY = Math.min(H - 3, y(ep) + 11);
  // 标签锚点：B 标签向右展开（text-anchor=start），现价标签向左展开（text-anchor=end）
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
        {/* 区间面积 + 折线 */}
        {!isSingle && (
          <>
            <polygon points={area} fill={stroke} opacity={0.08} />
            <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.4} strokeLinejoin="round" />
          </>
        )}
        {/* 单点 / sp=ep 时用虚线连接 B→现价，明确显示是同一价还是有变动 */}
        {isSingle && sp != null && ep != null && (
          <line x1={bx} y1={y(sp)} x2={ex} y2={y(ep)} stroke={stroke} strokeWidth={1.6} strokeDasharray="3,2" />
        )}
        {/* B 起点竖虚线 + 圆点 + 标签（蓝色，固定在上方） */}
        {sp != null && (
          <g>
            <line x1={bx} y1={0} x2={bx} y2={H} stroke="#3b82f6" strokeWidth={1} strokeDasharray="3,2" opacity={0.7} />
            <circle cx={bx} cy={y(sp)} r={3.5} fill="#3b82f6" stroke="#fff" strokeWidth={1} />
            <text x={bx + 5} y={bLabelY} fontSize={9} fill="#3b82f6" fontWeight={700}>B {sp.toFixed(2)}</text>
          </g>
        )}
        {/* S 终点 / 当前价 竖虚线 + 圆点 + 标签（红/橙，固定在下方） */}
        {ep != null && (
          <g>
            <line x1={ex} y1={0} x2={ex} y2={H} stroke={epColor} strokeWidth={1} strokeDasharray="3,2" opacity={0.7} />
            <circle cx={ex} cy={y(ep)} r={3.5} fill={epColor} stroke="#fff" strokeWidth={1} />
            <text x={ex - 5} y={eLabelY} fontSize={9} fill={epColor} fontWeight={700} textAnchor="end">{epLabel} {ep.toFixed(2)}</text>
          </g>
        )}
      </svg>
      {/* 日期标签行：绝对定位精准对齐到 B 点 / S 点（当前价）的 X 位置 */}
      <div style={{ position: 'relative', width: '100%', height: '13px', fontSize: '9px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
        {/* B 起点日期：对齐到 bx 位置（百分比），bx 靠近左边界时切换为右对齐避免溢出 */}
        <span style={{ position: 'absolute', left: `${(bx / W) * 100}%`, transform: (bx / W) < 0.25 ? 'translateX(0)' : 'translateX(-50%)' }}>{sd}</span>
        {/* S 终点 / 当前价日期：对齐到 ex 位置（百分比，右对齐避免溢出） */}
        <span style={{ position: 'absolute', left: `${(ex / W) * 100}%`, transform: 'translateX(-100%)' }}>{ed}</span>
        {/* 区间盈亏：左上角显示，避免和日期/线条重叠 */}
        <span className="font-bold" style={{ position: 'absolute', left: '0%', top: '0', color: pnlColor, background: 'var(--bg-card)', paddingRight: '4px' }}>
          区间 {pnl == null ? '--' : `${pnl >= 0 ? '+' : ''}${pnl}%`}
        </span>
      </div>
    </div>
  );
}
