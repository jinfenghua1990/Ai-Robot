import { useState } from 'react';
import { createPortal } from 'react-dom';
import KLineChart from '../charts/KLineChart';
import IntradayPanel from './IntradayPanel';
import SinaLink from '../SinaLink';
import { todayLabel } from '../../utils/formatTime';

/**
 * K线图弹窗组件（2×3网格布局）
 *
 * ┌─────────────────────────────────────────────┐
 * │ 头部：K线图 · 美迪凯 688079  [✕]            │
 * ├─────────────────────────────────────────────┤
 * │ 信息区（跨满宽度，在2×3网格上方）            │
 * │ - 行1：股票名 代码 K线天数 日期 信号 交易   │
 * │ - 行2：图例                                  │
 * │ - 行3-4：指标说明（4条规则，2列×2行）         │
 * ├─────────────────────────────────────────────┤
 * │ 2×3 图表网格（左右对齐，禁止上下堆叠）       │
 * │ ┌───────────┬───────────┐                   │
 * │ │ K线主图    │ 当日分时   │  flex 1          │
 * │ ├───────────┼───────────┤                   │
 * │ │ 成交量    │ 板块当天   │  flex 0.6        │
 * │ ├───────────┼───────────┤                   │
 * │ │ MACD+KDJ  │ 板块7天    │  flex 0.8        │
 * │ └───────────┴───────────┘                   │
 * └─────────────────────────────────────────────┘
 */
export default function KLineModal({ stockCode, stockName, onClose }) {
  const [summary, setSummary] = useState(null);

  if (!stockCode) return null;

  const today = todayLabel();
  const latest = summary?.latestSignal;
  const klineCount = summary?.klineCount || 60;
  const techCount = summary?.techSignalCount ?? 0;
  const tradeCount = summary?.tradeRecordCount ?? 0;

  // 使用 Portal 渲染到 document.body，脱离父元素 stacking context（劣质股 opacity:0.55）
  return createPortal((
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-2 sm:p-3"
      style={{ background: 'rgba(0,0,0,0.82)' }}
      onClick={onClose}
    >
      <div
        className="rounded-xl w-[calc(100vw-1rem)] sm:w-[calc(100vw-1.5rem)] max-w-7xl flex flex-col"
        style={{
          background: 'var(--bg-card)',
          border: '2px solid #3b82f6',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.06), 0 12px 28px rgba(0,0,0,0.12), 0 30px 60px rgba(0,0,0,0.35)',
          height: 'min(90vh, 900px)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 固定头部 */}
        <div className="flex items-center justify-between px-3 py-2 border-b flex-shrink-0" style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex items-center gap-2">
            <h3 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
              K线图 · {stockName} <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>{stockCode}</span>
            </h3>
            <SinaLink tsCode={stockCode} />
          </div>
          <button onClick={onClose} className="text-lg px-2 hover:opacity-70" style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        {/* 信息区（跨满宽度，在2×3网格上方） */}
        <div className="px-2 py-1.5 border-b flex-shrink-0 space-y-0.5" style={{ borderColor: 'var(--border-color)' }}>
          {/* 第1行：基础信息 */}
          <div className="flex items-center gap-1.5 text-[10px] flex-wrap" style={{ color: 'var(--text-muted)' }}>
            <span style={{ color: 'var(--text-primary)', fontWeight: 700, fontSize: '12px' }}>{stockName}</span>
            <span>{stockCode}</span>
            <span>· {klineCount}天K线</span>
            <span className="px-1 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>{today} 实时</span>
            <span>技术信号 <b style={{ color: 'var(--text-primary)' }}>{techCount}</b></span>
            <span>交易 <b style={{ color: 'var(--text-primary)' }}>{tradeCount}</b></span>
            {latest && (
              <span style={{ color: latest.type === 'B' ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                最新: {latest.type === 'B' ? '🔴B买入' : '🟢S卖出'} {latest.date} {latest.reasons?.join('; ')}
              </span>
            )}
          </div>

          {/* 第2行：图例 */}
          <div className="flex items-center gap-2 text-[10px] flex-wrap" style={{ color: 'var(--text-muted)' }}>
            <span className="flex items-center gap-0.5"><span style={{ display: 'inline-block', width: 7, height: 8, background: '#ef4444' }}></span>K线(红涨绿跌)</span>
            <span className="flex items-center gap-0.5"><span style={{ display: 'inline-block', width: 10, height: 2, background: '#eab308' }}></span>MA5</span>
            <span className="flex items-center gap-0.5"><span style={{ display: 'inline-block', width: 10, height: 2, background: '#3b82f6' }}></span>MA20</span>
            <span className="flex items-center gap-0.5"><span style={{ display: 'inline-block', width: 10, height: 2, background: '#a855f7' }}></span>SuperTrend操盘线</span>
            <span style={{ color: '#ef4444', fontWeight: 'bold' }}>B</span>买入(SuperTrend多头)
            <span style={{ color: '#22c55e', fontWeight: 'bold' }}>S</span>卖出(SuperTrend空头)
            <span className="flex items-center gap-0.5"><span style={{ display: 'inline-block', width: 7, height: 8, background: 'rgba(239,68,68,0.95)' }}></span>倍量柱</span>
          </div>

          {/* 第3-4行：指标说明（4条规则，2列×2行网格） */}
          <div className="rounded p-1.5 text-[10px] grid grid-cols-2 gap-x-3 gap-y-0.5" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-color)', color: 'var(--text-muted)', lineHeight: 1.35 }}>
            <div><span style={{ color: '#a855f7', fontWeight: 600 }}>SuperTrend操盘线：</span>紫线在K线<b style={{color:'#ef4444'}}>下方</b>＝多头持股，收盘跌破紫线→<b style={{color:'#22c55e'}}>S卖出</b>；紫线在K线<b style={{color:'#22c55e'}}>上方</b>＝空头持币，收盘突破紫线→<b style={{color:'#ef4444'}}>B买入</b>。线的位置由ATR波动幅度动态调整，震荡市自动加宽通道避免频繁触发。</div>
            <div><span style={{ color: '#f43f5e', fontWeight: 600 }}>KDJ指标：</span><span style={{ color: '#fbbf24' }}>K</span>/<span style={{ color: '#22d3ee' }}>D</span>/<span style={{ color: '#f43f5e' }}>J</span>三线，J&gt;100为超买区(易回调)，J&lt;0为超卖区(易反弹)；K上穿D为<b style={{color:'#ef4444'}}>金叉(买入)</b>，K下穿D为<b style={{color:'#22c55e'}}>死叉(卖出)</b>。</div>
            <div><span style={{ color: '#ffffff', fontWeight: 600 }}>MACD指标：</span>红柱=多头动能，绿柱=空头动能；DIF上穿DEA为<b style={{color:'#ef4444'}}>金叉(买入)</b>，DIF下穿DEA为<b style={{color:'#22c55e'}}>死叉(卖出)</b>。</div>
            <div><span style={{ color: '#ef4444', fontWeight: 600 }}>成交量信号：</span><span style={{ color: '#ef4444' }}>红色文字</span>为买入相关信号：倍量(量≥5日均量1.5倍且阳线)、地量(20日最低量)、量价齐升(连续3日放量上涨)、缩量调(上涨后量缩洗盘)、背离反包(量价背离+次日反包立马冲)；<span style={{ color: '#22c55e' }}>绿色文字</span>为风险提示：放量跌(放量且阴线，注意风险)。★ 量价背离次日反包立马冲：前一日创20日新低但缩量，次日阳线反包前一日实体→立马冲看涨。</div>
          </div>
        </div>

        {/* 2×3 图表网格（左右对齐，禁止上下堆叠） */}
        <div className="flex-1 grid gap-1.5 overflow-hidden p-1.5" style={{ gridTemplateColumns: '1fr 1fr', minHeight: 0 }}>
          {/* 左列：K线主图 / 成交量 / MACD+KDJ */}
          <div className="overflow-hidden" style={{ minWidth: 0 }}>
            <KLineChart stockCode={stockCode} stockName={stockName} onSummary={setSummary} />
          </div>
          {/* 右列：当日分时 / 板块当天 / 板块7天 */}
          <div className="overflow-hidden" style={{ minWidth: 0 }}>
            <IntradayPanel code={stockCode} />
          </div>
        </div>
      </div>
    </div>
  ), document.body);
}
