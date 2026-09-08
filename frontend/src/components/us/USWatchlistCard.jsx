import { memo, useCallback } from 'react';
import SinaLink from '../SinaLink';
import { usNameCN } from '../../utils/usStockNames';
import { usSectorCN } from '../../utils/usStockSectors';
import { toFiniteNumber } from '../../utils/format';

// 与 USQuantPage 的 C 保持一致（涨红跌绿）
const C = {
  card: 'var(--bg-card)',
  surface: 'var(--bg-surface)',
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  blue: 'var(--accent-blue)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  amber: 'var(--accent-amber)',
};

const ACTION_COLORS = {
  buy: '#ef4444',
  hold: '#f59e0b',
  reduce: '#f97316',
  sell: '#ef4444',
  stop: '#dc2626',
  scoop: '#22c55e',
  watch: '#94a3b8',
  avoid: '#f97316',
  blocked: '#94a3b8',
};

const ACTION_ICONS = {
  buy: '▲ 买入',
  hold: '▶ 持有',
  reduce: '▼ 减仓',
  sell: '✕ 卖出',
  stop: '⛔ 止损',
  scoop: '△ 低吸',
  watch: '· 观望',
  avoid: '⚠ 回避',
  blocked: '· 阻断',
};

function actionText(action) {
  const fallback = ACTION_ICONS[action?.action] || '';
  const icon = fallback.split(' ')[0];
  return `${icon} ${action?.action_label || fallback.slice(icon.length).trim()}`.trim() || '—';
}

// 中文技术状态颜色（对应后端 StockState.label）
const STATE_COLORS = {
  '主升': '#ef4444',
  '发酵': '#f97316',
  '启动': '#f59e0b',
  '吸筹': '#22c55e',
  '跟随': '#38bdf8',
  '关注': '#a78bfa',
  '退潮': '#94a3b8',
};

function scoreColor(score) {
  if (score == null) return C.muted;
  if (score >= 80) return '#ef4444';
  if (score >= 60) return '#f97316';
  if (score >= 40) return C.secondary;
  return '#22c55e';
}

// 信号提醒配色（与表格"提醒"列一致）
function alertColor(level) {
  switch (level) {
    case 'buy': return '#ef4444';
    case 'sell': return '#22c55e';
    case 'warn': return '#f59e0b';
    default: return '#94a3b8';
  }
}

function Chip({ label, value, color, title }) {
  return (
    <span
      className="text-[10px] px-1.5 py-0.5 rounded font-mono whitespace-nowrap"
      style={{ background: C.surface, color: color || C.secondary, border: `1px solid ${C.borderLight}` }}
      title={title}
    >
      {label}{value}
    </span>
  );
}

function structColor(s) {
  if (s === '多头排列') return '#ef4444';
  if (s === '空头排列') return '#22c55e';
  return C.secondary;
}

function chgColor(v) {
  if (v == null) return C.muted;
  return v >= 0 ? '#ef4444' : '#22c55e';
}

function fmtBig(n) {
  const value = toFiniteNumber(n);
  if (value == null) return null;
  if (value >= 1e12) return (value / 1e12).toFixed(2) + '万亿';
  if (value >= 1e9) return (value / 1e9).toFixed(1) + 'B';
  if (value >= 1e6) return (value / 1e6).toFixed(0) + 'M';
  return value.toFixed(0);
}

const fmtUS = (value, digits = 2) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : n.toFixed(digits);
};

/**
 * 美股自选股卡片（像 A 股自选股卡片一样）
 * 展示：名称 / 代码 / 板块 / 最新价 / 涨跌幅 / 技术指标（评分/状态/RSI/MACD/KDJ/MA50/止损价）/ 市值 / 持仓 / 操作方向
 * 点击卡片打开详情抽屉（onOpenDetail）。
 */
function USWatchlistCard({ stock, market = 'US', onRemove, onOpenDetail, hideRemove = false, showSectorRotation = false }) {
  const { symbol, price, change_pct } = stock;
  const name = stock.name || usNameCN(symbol) || symbol;
  const sector = stock.sector || usSectorCN(symbol) || '其他';
  const ind = stock.indicators || null;
  const pos = stock.position || null;
  const sectorRotation = stock.sector_rotation || null;
  const opportunity = stock.opportunity || null;
  const action = stock.trade_action || ind;

  const changeColor = change_pct == null
    ? C.muted
    : change_pct >= 0 ? C.up : C.down;
  const changeValue = toFiniteNumber(change_pct);
  const changeText = changeValue == null
    ? '—'
    : `${changeValue >= 0 ? '+' : ''}${changeValue.toFixed(2)}%`;

  const kdjJ = ind?.kdj?.j;
  const kdjColor = kdjJ == null ? C.muted : kdjJ >= 80 ? '#ef4444' : kdjJ <= 20 ? '#22c55e' : C.secondary;
  const macdVal = ind?.macd?.dif;
  const macdColor = macdVal == null ? C.muted : macdVal >= 0 ? '#ef4444' : '#22c55e';
  const rsiColor = ind?.rsi == null ? C.muted : ind.rsi >= 70 ? '#ef4444' : ind.rsi <= 30 ? '#22c55e' : C.secondary;

  const handleRemove = useCallback((e) => {
    e.stopPropagation();
    onRemove?.(symbol);
  }, [onRemove, symbol]);

  const handleClick = useCallback(() => {
    onOpenDetail?.(stock);
  }, [onOpenDetail, stock]);

  const cap = fmtBig(stock.market_cap);

  return (
    <div
      onClick={handleClick}
      title="点击查看详情（全指标 + 操作方向）"
      className="rounded-lg border p-2.5 transition-all hover:shadow-sm relative cursor-pointer"
      style={{
        background: C.card,
        borderColor: C.border,
        color: C.primary,
      }}
    >
      {/* 移除按钮（自选清单才有，股票池不显示） */}
      {!hideRemove && (
        <button
          onClick={handleRemove}
          title="从自选清单移除"
          className="absolute top-1.5 right-1.5 w-5 h-5 flex items-center justify-center rounded-full text-xs"
          style={{ color: C.muted, border: `1px solid ${C.borderLight}` }}
        >
          ×
        </button>
      )}

      {/* 名称 + 板块 + 评分/状态 */}
      <div className="flex items-start justify-between gap-2 pr-5">
        <div className="min-w-0">
          <div className="font-bold text-sm truncate" style={{ color: C.primary }}>{name}</div>
          <div className="text-[11px] mt-0.5 flex items-center gap-1.5 flex-wrap">
            <span style={{ color: C.muted }}>{symbol}</span>
            {pos && (
              <span
                className="text-[9px] px-1 py-0.5 rounded font-semibold"
                style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}
                title={`持仓 ${pos.quantity} 股 · 成本 $${pos.cost_price ?? '—'} · 浮盈 ${toFiniteNumber(pos.hold_profit_pct) != null ? (Number(pos.hold_profit_pct) >= 0 ? '+' : '') + fmtUS(pos.hold_profit_pct, 1) + '%' : '—'}`}
              >
                持仓
              </span>
            )}
            {!(pos) && action?.action === 'buy' && (
              <span className="text-[9px] px-1 py-0.5 rounded font-semibold" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
                买入候选
              </span>
            )}
          </div>
        </div>
        <div className="flex items-center gap-1 flex-shrink-0">
          {ind?.score != null && (
            <span
              className="text-[11px] font-bold px-1.5 py-0.5 rounded"
              style={{ background: `${scoreColor(ind.score)}18`, color: scoreColor(ind.score) }}
              title={`综合评分 ${ind.score}`}
            >
              {ind.score}
            </span>
          )}
          {ind?.state_label && (
            <span
              className="text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap"
              style={{ background: C.surface, color: STATE_COLORS[ind.state_label] || C.secondary, border: `1px solid ${C.borderLight}` }}
            >
              {ind.state_label}
            </span>
          )}
          <span
            className="text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap"
            style={{ background: C.surface, color: C.secondary, border: `1px solid ${C.borderLight}` }}
          >
            {sector}
          </span>
        </div>
      </div>

      {/* 价格 + 涨跌幅 + 行情时间 */}
      <div className="flex items-baseline gap-2 mt-1.5">
        <span className="text-lg font-bold tabular-nums" style={{ color: C.primary }}>
          {price == null ? '—' : Number(price).toFixed(2)}
        </span>
        <span className="text-xs font-semibold tabular-nums" style={{ color: changeColor }}>
          {changeText}
        </span>
        {stock.quote_time && (
          <span className="text-[9px] ml-auto" style={{ color: C.muted }} title="新浪实时行情时间">
            {stock.quote_time.slice(5, 16)}
          </span>
        )}
      </div>

      {showSectorRotation && (
        <div className="mt-1 flex items-center gap-1.5 rounded px-2 py-1 text-[10px]" style={{ background: sectorRotation?.is_rising ? 'rgba(239,68,68,.08)' : 'rgba(245,158,11,.07)', border: `1px solid ${sectorRotation?.is_rising ? 'rgba(239,68,68,.25)' : 'rgba(245,158,11,.22)'}` }}>
          <b style={{ color: sectorRotation?.is_rising ? '#ef4444' : '#f59e0b' }}>板块上升度 {sectorRotation?.rise_score == null ? '—' : Number(sectorRotation.rise_score).toFixed(1)}</b>
          <span style={{ color: opportunity?.status === 'READY' ? '#ef4444' : opportunity?.status === 'RISK' ? '#22c55e' : C.muted }}>{opportunity?.label || '板块未通过'}</span>
          {sectorRotation && <span className="ml-auto" style={{ color: C.muted }}>20日 {toFiniteNumber(sectorRotation.ret_20d) == null ? '—' : `${Number(sectorRotation.ret_20d) >= 0 ? '+' : ''}${Number(sectorRotation.ret_20d).toFixed(1)}%`} · 广度 {toFiniteNumber(sectorRotation.breadth) == null ? '—' : `${Number(sectorRotation.breadth).toFixed(0)}%`}</span>}
        </div>
      )}

      {/* 操作方向徽章 + 理由 */}
      {action?.action && (
        <div className="mt-1 flex items-center gap-2">
          <span
            className="text-[11px] font-bold px-2 py-0.5 rounded"
            style={{
              background: `${ACTION_COLORS[action.action] || action.action_color}18`,
              color: ACTION_COLORS[action.action] || action.action_color,
              border: `1px solid ${ACTION_COLORS[action.action] || action.action_color}55`,
            }}
          >
            {actionText(action)}
          </span>
          {(action.action_reasons || []).length > 0 && (
            <span className="text-[10px] truncate" style={{ color: C.muted }} title={action.action_reasons.join('\n')}>
              {action.action_reasons[0]}
              {(action.action_reasons || []).length > 1 && <span style={{ color: C.blue }}> +{(action.action_reasons || []).length - 1}</span>}
            </span>
          )}
        </div>
      )}

      {ind?.data_status && ind.data_status !== 'CURRENT' && (
        <div className="mt-1 text-[10px]" style={{ color: '#f59e0b' }} title={ind.data_reason || ''}>
          数据状态：{ind.data_status === 'STALE' ? '过期' : ind.data_status === 'INSUFFICIENT' ? '样本不足' : '缺失'} · {ind.as_of || '无日期'}
        </div>
      )}

      {/* 具体买卖信号提醒（金叉/死叉/超买超卖/破位/放量） */}
      {(ind?.alerts || []).length > 0 && (
        <div className="flex items-center gap-1 flex-wrap mt-0.5">
          {ind.alerts.map((a, i) => (
            <span
              key={i}
              className="text-[9px] px-1.5 py-0.5 rounded font-semibold whitespace-nowrap"
              style={{
                background: `${alertColor(a.level)}14`,
                color: alertColor(a.level),
                border: `1px solid ${alertColor(a.level)}40`,
              }}
              title={`[${({ buy: '买入信号', sell: '卖出信号', warn: '风险提示', info: '观察' })[a.level] || '信号'}] ${a.text}`}
            >
              {({ buy: '▲', sell: '▼', warn: '⚠', info: '·' })[a.level]}{a.text}
            </span>
          ))}
        </div>
      )}

      {/* 技术指标行 */}
      {ind && (
        <div className="flex items-center gap-1 flex-wrap mt-1">
          <Chip label="RSI " value={ind.rsi ?? '—'} color={rsiColor} />
          <Chip label="MACD " value={toFiniteNumber(macdVal) == null ? '—' : `${Number(macdVal) >= 0 ? '+' : ''}${fmtUS(macdVal)}`} color={macdColor} />
          <Chip label="K " value={toFiniteNumber(kdjJ) == null ? '—' : fmtUS(kdjJ, 0)} color={kdjColor} />
          {ind.ema20 != null && <Chip label="EMA20 " value={fmtUS(ind.ema20)} />}
          {ind.ma50 != null && <Chip label="MA50 " value={fmtUS(ind.ma50)} />}
          {ind.ma200 != null && <Chip label="MA200 " value={fmtUS(ind.ma200)} />}
          {ind.stop_loss != null && (
            <Chip
              label="止损 "
              value={fmtUS(ind.stop_loss)}
              color="#f97316"
              title={ind.stop_dist != null ? `止损位（距现价 ${fmtUS(ind.stop_dist)}%）` : '止损位'}
            />
          )}
        </div>
      )}

      {/* 基本面行：市值 / PE */}
      {(stock.market_cap || stock.pe_ratio != null) && (
        <div className="flex items-center gap-1 flex-wrap mt-0.5">
          {cap && <Chip label="市值 " value={cap} color={C.muted} />}
          {stock.pe_ratio != null && (
            <Chip label="PE " value={fmtUS(stock.pe_ratio, 1)} color={C.muted} title="市盈率(TTM)" />
          )}
        </div>
      )}

      {/* 第二行：均线结构 / 52周位置 / 量比 / 动量 / 支撑阻力 */}
      {ind && (
        <div className="flex items-center gap-1 flex-wrap mt-1">
          {ind.ma_struct && (
            <Chip label="结构 " value={ind.ma_struct} color={structColor(ind.ma_struct)} title="EMA10/20/MA50/MA200 排列" />
          )}
          {ind.pct_from_high != null && (
            <Chip
              label="距52周高 "
              value={`${Number(ind.pct_from_high) >= 0 ? '+' : ''}${fmtUS(ind.pct_from_high, 1)}%`}
              color={chgColor(ind.pct_from_high)}
              title={`52周高 ${ind.high_52w} / 低 ${ind.low_52w}（距低点 ${ind.pct_from_low ?? '—'}%）`}
            />
          )}
          {ind.rel_vol != null && (
            <Chip label="量比 " value={fmtUS(ind.rel_vol, 1)} color={ind.rel_vol >= 1.5 ? '#f97316' : C.secondary} title="当日量 / 前5日均量" />
          )}
          {ind.chg_5d != null && (
            <Chip label="5日 " value={`${Number(ind.chg_5d) >= 0 ? '+' : ''}${fmtUS(ind.chg_5d, 1)}%`} color={chgColor(ind.chg_5d)} />
          )}
          {ind.chg_20d != null && (
            <Chip label="20日 " value={`${Number(ind.chg_20d) >= 0 ? '+' : ''}${fmtUS(ind.chg_20d, 1)}%`} color={chgColor(ind.chg_20d)} />
          )}
          {ind.support != null && (
            <Chip label="支撑 " value={fmtUS(ind.support)} color={C.secondary} title={`阻力 ${ind.resistance ?? '—'}`} />
          )}
          {ind.atr != null && (
            <Chip label="ATR " value={fmtUS(ind.atr)} color={C.muted} title="14日平均真实波幅" />
          )}
        </div>
      )}

      {/* 行情链接 */}
      <div className="mt-1">
        <SinaLink market={market} code={symbol} size="xs" />
      </div>
    </div>
  );
}

export default memo(USWatchlistCard);
