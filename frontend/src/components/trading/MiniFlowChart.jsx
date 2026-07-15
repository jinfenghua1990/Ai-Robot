/**
 * 轻量级分时资金趋势图（纯 SVG，无外部依赖）
 * 双线：价格（蓝）+ 主力净流入（红/绿）
 * 用于 SignalCard 展开区域
 */
export default function MiniFlowChart({ points = [], height = 60 }) {
  if (!points || points.length < 2) {
    return <div className="text-[10px] text-center py-2" style={{ color: 'var(--text-muted)' }}>数据不足</div>;
  }

  const W = 320;
  const H = height;
  const PAD_X = 2;
  const PAD_Y = 8;
  const labelW = 30;
  const chartW = W - labelW - PAD_X * 2;
  const chartH = H - PAD_Y * 2;

  const prices = points.map(p => p.price);
  const flows = points.map(p => p.main_force_inflow || 0);

  const pMax = Math.max(...prices);
  const pMin = Math.min(...prices);
  const pRange = Math.max(pMax - pMin, 0.01);

  const fMax = Math.max(...flows, 0);
  const fMin = Math.min(...flows, 0);
  const fRange = Math.max(fMax - fMin, 1);

  const stepX = chartW / (points.length - 1);

  // 价格线（蓝色）
  const pricePts = prices.map((v, i) => ({
    x: PAD_X + labelW + i * stepX,
    y: PAD_Y + chartH - ((v - pMin) / pRange) * chartH,
  }));
  const priceLine = pricePts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');

  // 资金流向线（红/绿，0 轴分界）
  const zeroY = PAD_Y + chartH - ((0 - fMin) / fRange) * chartH;
  const flowPts = flows.map((v, i) => ({
    x: PAD_X + labelW + i * stepX,
    y: PAD_Y + chartH - ((v - fMin) / fRange) * chartH,
  }));
  const flowLine = flowPts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
  const flowArea = `${flowLine} L${flowPts[flowPts.length - 1].x.toFixed(1)},${zeroY.toFixed(1)} L${flowPts[0].x.toFixed(1)},${zeroY.toFixed(1)} Z`;

  const lastPrice = prices[prices.length - 1];
  const lastFlow = flows[flows.length - 1];
  const flowColor = lastFlow >= 0 ? '#ef4444' : '#22c55e';

  return (
    <div className="w-full">
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" style={{ maxHeight: H }}>
        <defs>
          <linearGradient id="flowGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={flowColor} stopOpacity="0.3" />
            <stop offset="100%" stopColor={flowColor} stopOpacity="0" />
          </linearGradient>
        </defs>
        {/* 0 轴虚线 */}
        <line
          x1={PAD_X + labelW} y1={zeroY} x2={W - PAD_X} y2={zeroY}
          stroke="var(--border-color)" strokeWidth="0.5" strokeDasharray="2,2"
        />
        {/* 资金流向面积 */}
        <path d={flowArea} fill="url(#flowGrad)" />
        {/* 资金流向线 */}
        <path d={flowLine} fill="none" stroke={flowColor} strokeWidth="1.2" strokeLinejoin="round" />
        {/* 价格线 */}
        <path d={priceLine} fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinejoin="round" />
        {/* 最新点 */}
        <circle cx={pricePts[pricePts.length - 1].x} cy={pricePts[pricePts.length - 1].y} r="2" fill="#3b82f6" />
        <circle cx={flowPts[flowPts.length - 1].x} cy={flowPts[flowPts.length - 1].y} r="2" fill={flowColor} />
      </svg>
      <div className="flex items-center justify-between text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
        <span>📊 价格 <span style={{ color: '#3b82f6' }}>{lastPrice.toFixed(2)}</span></span>
        <span>💰 主力 <span style={{ color: flowColor }}>{(lastFlow / 10000).toFixed(1)}万</span></span>
        <span>{points[0].time} - {points[points.length - 1].time}</span>
      </div>
    </div>
  );
}
