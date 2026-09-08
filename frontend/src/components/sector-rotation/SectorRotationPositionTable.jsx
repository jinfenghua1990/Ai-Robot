import StockActionButtons from '../trading/StockActionButtons';

const UP = '#ef4444';
const DOWN = '#22c55e';
const MUTED = 'var(--text-muted)';

const finite = (value) => value == null || Number.isNaN(Number(value)) ? null : Number(value);
const num = (value, digits = 2) => finite(value) == null ? '—' : finite(value).toFixed(digits);
const pct = (value) => finite(value) == null ? '—' : `${finite(value) > 0 ? '+' : ''}${finite(value).toFixed(2)}%`;
const tone = (value) => finite(value) == null ? MUTED : finite(value) >= 0 ? UP : DOWN;
const money = (value) => {
  const amount = finite(value);
  if (amount == null) return '—';
  if (Math.abs(amount) >= 1e8) return `${(amount / 1e8).toFixed(2)}亿`;
  if (Math.abs(amount) >= 1e4) return `${(amount / 1e4).toFixed(1)}万`;
  return amount.toFixed(0);
};
const plainCode = (code) => String(code || '').split('.')[0];

const normalizePosition = (position) => ({
  quantity: finite(position?.quantity ?? position?.count),
  lastPrice: finite(position?.last_price ?? position?.price),
  avgCost: finite(position?.avg_cost ?? position?.costPrice),
  dayPnl: finite(position?.day_pnl ?? position?.dayProfit),
  unrealizedPnl: finite(position?.unrealized_pnl ?? position?.profit),
  profitPct: finite(position?.profit_ratio ?? position?.profitPct),
  positionPct: finite(position?.pos_pct ?? position?.posPct),
});

function triggerText(evidence) {
  if (!evidence) return '强势证据缺失';
  const type = evidence.trigger_type === 'both' ? '单日+两日' : evidence.trigger_type === 'single_day' ? '单日' : '两日';
  const single = evidence.max_single_day_pct == null ? '' : `单日最高 ${pct(evidence.max_single_day_pct)}`;
  const twoDay = evidence.max_two_day_pct == null ? '' : `两日最高 ${pct(evidence.max_two_day_pct)}`;
  return `${type} · ${[single, twoDay].filter(Boolean).join(' · ')} · 最近${evidence.days_since_trigger}个交易日前`;
}

function coreGateText(coreGate) {
  const labels = {
    strong_event_too_old: '强势触发超过120日',
    insufficient_repeat_events: '不同触发日不足2次',
    below_ma60: '当前未站上MA60',
  };
  return (coreGate?.reasons || []).map((reason) => labels[reason] || reason).join(' · ');
}

function scoreBreakdown(components) {
  if (!components) return '评分构成缺失';
  return `触发新近度 ${num(components.trigger_recency, 0)} · 事件强度 ${num(components.event_strength, 0)} · 20日动量 ${num(components.momentum_20d, 0)} · 流动性 ${num(components.liquidity, 0)}`;
}

function macdState(metrics) {
  if (finite(metrics.dif) == null || finite(metrics.dea) == null) return '—';
  if (metrics.dif >= metrics.dea) return metrics.dif >= 0 ? '零轴上金叉' : '零轴下金叉';
  return '死叉';
}

function kdjState(metrics) {
  if (finite(metrics.kdj_j) == null) return '—';
  if (metrics.kdj_j >= 100) return '超买';
  if (metrics.kdj_j <= 0) return '超卖';
  return metrics.kdj_k >= metrics.kdj_d ? '金叉偏强' : '死叉偏弱';
}

function autoStatus(config) {
  if (!config || config.mode === 'off') return { label: '关闭', color: MUTED };
  if (config.status === 'PAUSED') return { label: '已暂停', color: '#f97316' };
  if (config.status === 'MONITORING') return { label: '监控中', color: '#22c55e' };
  if (config.status === 'ERROR') return { label: '异常', color: '#ef4444' };
  return { label: config.status || config.mode, color: '#3b82f6' };
}

export default function SectorRotationPositionTable({ stocks, positions = [], autoStocks = {}, onOpen, onExclude, onOpenAuto }) {
  const positionMap = new Map(positions.map((position) => [plainCode(position.symbol ?? position.secCode ?? position.stockCode), position]));
  const hasCandidates = stocks.some((stock) => stock.core_gate?.valid === false);

  return <div className="overflow-x-auto no-scrollbar">
    <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth: 2038 }}>
      <thead>
        <tr style={{ background: 'var(--bg-secondary)' }}>
          {[
            ['股票', 130, 'left'], ['数量', 70, 'right'], ['现价 / 成本价', 112, 'left'], ['当日盈亏 / 当日涨幅', 126, 'left'],
            ['持仓盈亏 / 持仓收益率', 136, 'left'], ['仓位', 62, 'right'], ['评分', 56, 'center'], ['均线结构（MA5/20/60）', 190, 'left'],
            ['RSI14', 56, 'center'], ['MACD状态', 92, 'left'], ['KDJ（K/D/J）', 104, 'left'], ['换手率', 64, 'center'],
            ['个股资金 / 板块', 148, 'left'], ['支撑 / 压力位', 112, 'left'], ['风险提示', 150, 'left'], ['建议', 92, 'left'],
            ['操作', 210, 'center'], ['自动交易', 128, 'center'],
          ].map(([label, width, align], index) => <th key={label} className="px-2 py-1.5 font-semibold whitespace-nowrap"
            style={{ color: MUTED, width, minWidth: width, textAlign: align, position: index === 0 || index >= 16 ? 'sticky' : 'static', left: index === 0 ? 0 : undefined, right: index === 16 ? 128 : index === 17 ? 0 : undefined, zIndex: index === 0 || index >= 16 ? 2 : 1, background: 'var(--bg-secondary)' }}>{label}</th>)}
        </tr>
      </thead>
      <tbody>{stocks.map((stock) => {
        const metrics = stock.metrics || {};
        const holding = positionMap.get(plainCode(stock.ts_code));
        const position = normalizePosition(holding);
        const config = autoStocks[plainCode(stock.ts_code)] || autoStocks[stock.ts_code];
        const automatic = autoStatus(config);
        const currentPrice = position.lastPrice ?? finite(metrics.last_price);
        const cost = position.avgCost;
        const quantity = position.quantity;
        const dayPnl = position.dayPnl;
        const holdingPnl = position.unrealizedPnl ?? (cost != null && currentPrice != null && quantity != null ? (currentPrice - cost) * quantity : null);
        const holdingReturn = position.profitPct ?? (cost > 0 && currentPrice != null ? (currentPrice - cost) / cost * 100 : null);
        const positionPct = position.positionPct;
        const maOrder = metrics.ma5 != null && metrics.ma20 != null && metrics.ma60 != null
          ? metrics.ma5 >= metrics.ma20 && metrics.ma20 >= metrics.ma60 ? '多头排列'
            : metrics.ma5 <= metrics.ma20 && metrics.ma20 <= metrics.ma60 ? '空头排列' : '均线交错'
          : '—';
        const ma20Distance = metrics.ma20 && currentPrice ? (currentPrice - metrics.ma20) / metrics.ma20 * 100 : null;
        const macd = macdState(metrics);
        const kdj = kdjState(metrics);
        const risks = [
          metrics.rsi >= 70 && 'RSI超买',
          metrics.kdj_j >= 100 && 'KDJ超买',
          metrics.above_ma20 === false && '跌破MA20',
          metrics.support != null && currentPrice < metrics.support && '跌破支撑',
          macd === '死叉' && 'MACD死叉',
        ].filter(Boolean);
        const rowBackground = holdingPnl == null ? 'var(--bg-card)' : holdingPnl >= 0 ? 'rgba(239,68,68,0.04)' : 'rgba(34,197,94,0.04)';
        const sectorContext = stock.sector_context || {};
        const gateText = coreGateText(stock.core_gate);

        return <tr key={stock.ts_code} className="hover:opacity-90 transition-colors" style={{ borderTop: '1px solid var(--border-color)', background: rowBackground }}>
          <td className="px-2 py-1 whitespace-nowrap sticky left-0 z-[2]" style={{ background: rowBackground }}>
            <button onClick={() => onOpen(plainCode(stock.ts_code))} className="block text-left" title="打开个股分析"><div className="flex items-center gap-1.5"><span className="font-bold">{stock.name || '—'}</span><span className="text-[9px]" style={{ color: MUTED }}>{plainCode(stock.ts_code)}</span><span className="rounded px-1 text-[9px]" style={{ background: 'rgba(59,130,246,.1)', color: '#3b82f6' }}>#{stock.rank}</span></div></button>
            <div className="max-w-[300px] truncate text-[9px]" style={{ color: '#f59e0b' }} title={triggerText(stock.qualification)}>⚡ {triggerText(stock.qualification)}</div>
            {!!stock.theme_concepts?.length && <div className="max-w-[300px] truncate text-[9px]" style={{ color: '#60a5fa' }} title={stock.theme_concepts.join(' · ')}>题材：{stock.theme_concepts.join(' · ')}</div>}
            {stock.industry_sector && <div className="max-w-[300px] truncate text-[9px]" style={{ color: MUTED }}>行业：{stock.industry_sector}</div>}
            {gateText && <div className="max-w-[300px] truncate text-[9px]" style={{ color: DOWN }} title={gateText}>待补：{gateText}</div>}
          </td>
          <td className="px-2 py-1 text-right whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{quantity == null ? '—' : `${num(quantity, 0)}股`}</td>
          <td className="px-2 py-1 whitespace-nowrap"><div className="font-semibold">现价 {num(currentPrice)}</div><div style={{ color: MUTED }}>成本 {num(cost)}</div></td>
          <td className="px-2 py-1 whitespace-nowrap"><div style={{ color: tone(dayPnl), fontWeight: 600 }}>盈亏 {money(dayPnl)}</div><div style={{ color: tone(metrics.day_change_pct) }}>涨幅 {pct(metrics.day_change_pct)}</div></td>
          <td className="px-2 py-1 whitespace-nowrap"><div style={{ color: tone(holdingPnl), fontWeight: 600 }}>盈亏 {money(holdingPnl)}</div><div style={{ color: tone(holdingReturn) }}>收益 {pct(holdingReturn)}</div></td>
          <td className="px-2 py-1 text-right">{positionPct == null ? '—' : `${num(positionPct, 1)}%`}</td>
          <td className="px-2 py-1 text-center" title={scoreBreakdown(stock.score_components)}><span className="font-bold" style={{ color: stock.score >= 70 ? UP : stock.score >= 55 ? '#f59e0b' : MUTED }}>{num(stock.score, 0)}</span><div className="text-[9px]" style={{ color: MUTED }}>{num(stock.score_components?.trigger_recency, 0)}/{num(stock.score_components?.event_strength, 0)}/{num(stock.score_components?.momentum_20d, 0)}/{num(stock.score_components?.liquidity, 0)}</div></td>
          <td className="px-2 py-1 whitespace-nowrap" title="MA5、MA20、MA60为收盘价均线；偏离度不是持仓收益率。"><div className="font-mono text-[10px]"><span style={{ color: '#3b82f6', fontWeight: 700 }}>MA5 {num(metrics.ma5)}</span><span style={{ color: MUTED }}> · </span><span style={{ color: '#f59e0b', fontWeight: 700 }}>MA20 {num(metrics.ma20)}</span><span style={{ color: MUTED }}> · MA60 {num(metrics.ma60)}</span></div><div style={{ color: metrics.above_ma20 ? UP : DOWN, fontWeight: 600 }}>{maOrder} · 现价{metrics.above_ma20 ? '高于' : '低于'} MA20 {pct(ma20Distance)}</div><div className="text-[10px]" style={{ color: MUTED }}>MA20斜率：{pct(metrics.ma20_slope)}</div></td>
          <td className="px-2 py-1 text-center" style={{ color: metrics.rsi >= 70 ? UP : metrics.rsi <= 30 ? DOWN : 'var(--text-secondary)' }}>{num(metrics.rsi, 0)}</td>
          <td className="px-2 py-1 whitespace-nowrap" style={{ color: /金叉/.test(macd) ? UP : macd === '死叉' ? DOWN : MUTED }} title={`DIF ${num(metrics.dif, 4)} / DEA ${num(metrics.dea, 4)}`}>{macd}</td>
          <td className="px-2 py-1 whitespace-nowrap" title="KDJ：K/D/J为随机指标；金叉偏强、死叉偏弱。"><div className="font-mono text-[10px]">K {num(metrics.kdj_k, 1)} / D {num(metrics.kdj_d, 1)} / J {num(metrics.kdj_j, 1)}</div><div style={{ color: /金叉|超买/.test(kdj) ? UP : /死叉|超卖/.test(kdj) ? DOWN : MUTED }}>{kdj}</div></td>
          <td className="px-2 py-1 text-center" title="换手率为当日交易活跃度；量比为当日成交量相对近20日均量。"><div>{metrics.turnover == null ? '—' : `${num(metrics.turnover, 1)}%`}</div><div className="text-[9px]" style={{ color: MUTED }}>量比 {num(metrics.volume_ratio, 2)}</div></td>
          <td className="px-2 py-1 whitespace-nowrap"><div style={{ color: tone(metrics.main_net) }}>主力 {money(metrics.main_net)}</div><div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{stock.sector} · {sectorContext.net_flow == null ? '板块资金—' : `板块${sectorContext.net_flow >= 0 ? '流入' : '流出'} ${money(sectorContext.net_flow)}`}{sectorContext.heat_score != null ? ` · 热${num(sectorContext.heat_score, 0)}` : ''}</div></td>
          <td className="px-2 py-1 whitespace-nowrap" style={{ color: MUTED }}><div>支撑 {num(metrics.support)} · 压力 {num(metrics.resistance)}</div><div className="text-[9px]">ATR {num(metrics.atr)} · 距高 {pct(metrics.drawdown)}</div></td>
          <td className="px-2 py-1"><div>{risks.length ? <div className="flex flex-wrap gap-1">{risks.map((risk) => <span key={risk} className="px-1 py-0.5 rounded text-[9px] whitespace-nowrap" style={{ background: 'rgba(239,68,68,.12)', color: '#ef4444' }}>{risk}</span>)}</div> : <span style={{ color: MUTED }}>暂无明显风险</span>}</div><div className="mt-0.5 text-[9px]" style={{ color: MUTED }}>日波动 {pct(metrics.volatility)}</div></td>
          <td className="px-2 py-1 whitespace-nowrap font-medium" style={{ color: stock.action === '强势跟踪' ? UP : stock.action === '等待修复' ? DOWN : '#f59e0b' }}><div>{stock.action || '观察'}</div><div className="text-[9px]" style={{ color: MUTED }}>5/20/60日 {pct(metrics.ret_5d)} / {pct(metrics.ret_20d)} / {pct(metrics.ret_60d)}</div></td>
          <td className="px-2 py-1 text-center sticky z-[2]" style={{ background: rowBackground, width: 210, minWidth: 210, maxWidth: 210, right: 128, overflow: 'hidden' }}><StockActionButtons stockCode={plainCode(stock.ts_code)} stockName={stock.name} positionCount={quantity || 0} size="xs" showKline={false} showWatch={false} showTrack={false} showSina={false} showAutoTrade={false} onRemove={() => onExclude(stock.ts_code)} removeLabel="剔除" removeConfirmText={`确认从当前行业池剔除 ${stock.name}？`} /><span className="mx-1 inline-block h-3 align-middle" style={{ borderLeft: '1px solid var(--border-color)' }} /><button onClick={(event) => { event.stopPropagation(); onExclude(stock.ts_code); }} className="px-1.5 py-0 rounded text-[10px] h-5" style={{ background: 'rgba(239,68,68,.08)', color: '#ef4444', border: '1px solid rgba(239,68,68,.3)' }}>剔除</button></td>
          <td className="px-2 py-1 text-center sticky right-0 z-[2]" style={{ background: rowBackground }}><button onClick={() => onOpenAuto(plainCode(stock.ts_code))} className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap" style={{ borderColor: `${automatic.color}55`, color: automatic.color, background: `${automatic.color}10` }}>{automatic.label}</button></td>
        </tr>;
      })}</tbody>
      <tfoot><tr style={{ borderTop: '2px solid var(--border-color)', background: 'var(--bg-secondary)' }}><td colSpan={18} className="px-3 py-2"><div className="flex items-center gap-4 text-[11px]"><span style={{ color: MUTED }}>合计 {stocks.length} 只</span><span>{hasCandidates ? '全部满足一年强势资格，待补足当前有效性门槛' : '全部均满足强势资格与当前有效性门槛'}</span><span className="flex-1"/><span style={{ color: MUTED }}>点击股票名称查看详情 · 自动交易按钮进入个股策略配置</span></div></td></tr></tfoot>
    </table>
    {!stocks.length && <div className="py-12 text-center text-xs" style={{ color: MUTED }}>当前板块没有满足核心池门槛的股票</div>}
  </div>;
}
