import { useEffect, useState } from 'react';
import SinaLink from '../SinaLink';
import { apiFetch } from '../../utils/request';

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
  buy: '#ef4444', hold: '#f59e0b', reduce: '#f97316', sell: '#ef4444',
  stop: '#dc2626', scoop: '#22c55e', watch: '#94a3b8', avoid: '#f97316', blocked: '#94a3b8',
};
const ACTION_ICONS = {
  buy: '▲ 买入', hold: '▶ 持有', reduce: '▼ 减仓', sell: '✕ 卖出',
  stop: '⛔ 止损', scoop: '△ 低吸', watch: '· 观望',
  avoid: '⚠ 回避·等待修复', blocked: '· 数据阻断',
};

function actionText(action) {
  const fallback = ACTION_ICONS[action?.action] || '';
  const icon = fallback.split(' ')[0];
  return `${icon} ${action?.action_label || fallback.slice(icon.length).trim()}`.trim() || '—';
}

function fmtBig(n) {
  if (n == null) return '—';
  if (n >= 1e12) return (n / 1e12).toFixed(2) + ' 万亿';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + ' B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + ' M';
  return n.toFixed(0);
}

function Row({ label, value, color, sub }) {
  return (
    <div className="flex items-center justify-between py-1 text-[11px]">
      <span style={{ color: C.muted }}>{label}</span>
      <span className="flex items-center gap-1.5" style={{ color: color || C.primary }}>
        <span className="tabular-nums">{value}</span>
        {sub}
      </span>
    </div>
  );
}

// 迷你趋势图（最近 60 日收盘）
function Sparkline({ closes }) {
  if (!closes || closes.length < 2) return <div style={{ color: C.muted, fontSize: 11 }}>无趋势数据</div>;
  const w = 280, h = 56;
  const min = Math.min(...closes), max = Math.max(...closes);
  const range = max - min || 1;
  const pts = closes.map((v, i) => `${(i / (closes.length - 1)) * w},${h - ((v - min) / range) * (h - 8) - 4}`).join(' ');
  const last = closes[closes.length - 1];
  const first = closes[0];
  const up = last >= first;
  const col = up ? C.up : C.down;
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} className="w-full">
      <polyline points={pts} fill="none" stroke={col} strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={w} cy={h - ((last - min) / range) * (h - 8) - 4} r="2.5" fill={col} />
    </svg>
  );
}

/**
 * 美股自选详情抽屉：全指标 + 近60日趋势 + 操作方向与理由 + 持仓联动。
 * 右侧滑出，蒙层点击关闭，Esc 关闭。
 */
export default function USStockDetailDrawer({ stock, market = 'US', onClose }) {
  const [klines, setKlines] = useState(null);
  const ind = stock.indicators || null;
  const pos = stock.position || null;
  const action = stock.trade_action || ind;

  useEffect(() => {
    let alive = true;
    if (stock) {
      setKlines(null);
      apiFetch(`/api/us-quant/klines?symbol=${stock.symbol}&days=60${ind?.decision_date ? `&end_date=${ind.decision_date}` : ''}`, {}, 12000, 0)
        .then((res) => { if (alive && res.ok && res.data) setKlines(res.data.klines || res.data || []); })
        .catch(() => {});
    }
    return () => { alive = false; };
  }, [stock, ind?.decision_date]);

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', h);
    return () => document.removeEventListener('keydown', h);
  }, [onClose]);

  if (!stock) return null;

  const changeColor = stock.change_pct == null ? C.muted : stock.change_pct >= 0 ? C.up : C.down;
  const actionColor = ACTION_COLORS[action?.action] || action?.action_color || C.muted;
  const macdVal = ind?.macd?.dif;
  const avgColor = (v) => (v == null ? C.muted : v >= 0 ? C.up : C.down);
  const closes = (klines || []).map((k) => k.close).filter((v) => v != null);
  const priceAsOf = stock.quote_time
    ? `新浪实时 ${stock.quote_time}`
    : `${stock.price_source === 'decision_close' ? '决策日收盘' : '日线收盘'} ${stock.bar_as_of || ind?.as_of || '—'}`;

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      style={{ background: 'rgba(0,0,0,0.45)' }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="h-full w-full max-w-[380px] overflow-y-auto p-4 shadow-2xl"
        style={{ background: C.card, color: C.primary }}
      >
        {/* 头部 */}
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold text-base">{stock.name}</span>
              <span className="text-[11px]" style={{ color: C.muted }}>{stock.symbol}</span>
              {pos && (
                <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>
                  持仓 {pos.quantity} 股
                </span>
              )}
            </div>
            <div className="text-[11px] mt-0.5" style={{ color: C.muted }}>{stock.sector}</div>
          </div>
          <button onClick={onClose} className="text-sm w-6 h-6 rounded-full flex items-center justify-center" style={{ border: `1px solid ${C.border}`, color: C.muted }}>✕</button>
        </div>

        {/* 行情 */}
        <div className="flex items-baseline gap-2 mt-3">
          <span className="text-2xl font-bold tabular-nums">{stock.price == null ? '—' : Number(stock.price).toFixed(2)}</span>
          <span className="text-sm font-semibold tabular-nums" style={{ color: changeColor }}>
            {stock.change_pct == null ? '—' : `${stock.change_pct >= 0 ? '+' : ''}${stock.change_pct.toFixed(2)}%`}
          </span>
        </div>
        <div className="text-[10px] mt-0.5" style={{ color: C.muted }}>
          {priceAsOf}
        </div>

        {/* 操作方向 */}
        {action?.action && (
          <div className="mt-3 rounded-lg p-3" style={{ background: C.surface, border: `1px solid ${actionColor}55` }}>
            <div className="flex items-center gap-2">
              <span className="text-sm font-bold" style={{ color: actionColor }}>
                {actionText(action)}
              </span>
              {action.action_strength != null && (
                <span className="text-[10px]" style={{ color: C.muted }}>强度 {Number(action.action_strength).toFixed(1)}</span>
              )}
            </div>
            <div className="mt-1.5 space-y-1">
              {(action.action_reasons || []).map((r, i) => (
                <div key={i} className="text-[11px] flex items-start gap-1.5" style={{ color: C.secondary }}>
                  <span style={{ color: actionColor }}>·</span>{r}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* 持仓联动 */}
        {pos && (
          <div className="mt-3 rounded-lg p-3" style={{ background: 'rgba(34,197,94,0.06)', border: `1px solid ${C.borderLight}` }}>
            <Row label="持仓数量" value={`${pos.quantity} 股`} />
            <Row label="成本价" value={pos.cost_price != null ? '$' + pos.cost_price.toFixed(2) : '—'} />
            <Row label="市值" value={pos.market_value != null ? '$' + pos.market_value.toFixed(2) : '—'} />
            <Row
              label="浮动盈亏"
              value={pos.hold_profit == null ? '—' : `${pos.hold_profit >= 0 ? '+' : ''}$${pos.hold_profit.toFixed(2)}`}
              color={avgColor(pos.hold_profit)}
              sub={pos.hold_profit_pct != null ? <span style={{ color: avgColor(pos.hold_profit_pct) }}>({pos.hold_profit_pct >= 0 ? '+' : ''}{pos.hold_profit_pct.toFixed(1)}%)</span> : null}
            />
          </div>
        )}

        {/* 近60日趋势 */}
        <div className="mt-3 rounded-lg p-3" style={{ background: C.surface, border: `1px solid ${C.borderLight}` }}>
          <div className="text-[11px] font-semibold mb-1" style={{ color: C.secondary }}>近60日走势</div>
          <Sparkline closes={closes} />
        </div>

        {/* 基本面 */}
        <div className="mt-3 rounded-lg p-3" style={{ background: C.surface, border: `1px solid ${C.borderLight}` }}>
          <div className="text-[11px] font-semibold mb-1" style={{ color: C.secondary }}>基本面</div>
          <Row label="总市值" value={fmtBig(stock.market_cap)} />
          <Row label="市盈率(PE)" value={stock.pe_ratio != null ? stock.pe_ratio.toFixed(2) : '—'} />
        </div>

        {/* 技术明细 */}
        <div className="mt-3 rounded-lg p-3" style={{ background: C.surface, border: `1px solid ${C.borderLight}` }}>
          <div className="text-[11px] font-semibold mb-1" style={{ color: C.secondary }}>技术指标</div>
          <Row label="指标日期" value={ind?.as_of || '—'} color={ind?.data_status === 'CURRENT' ? C.up : '#f59e0b'} sub={<span className="text-[10px]" style={{ color: C.muted }}>{ind?.data_status || 'MISSING'}</span>} />
          <Row label="状态" value={ind?.state_label || '—'} />
          <Row
            label="RSI(14)"
            value={ind?.rsi == null ? '—' : Number(ind.rsi).toFixed(1)}
            color={ind?.rsi >= 70 ? C.up : ind?.rsi <= 30 ? C.down : C.primary}
          />
          <Row
            label="MACD(DIF/DEA)"
            value={macdVal == null || ind?.macd?.dea == null ? '—' : `${macdVal.toFixed(3)} / ${Number(ind.macd.dea).toFixed(3)}`}
            color={macdVal != null && macdVal >= 0 ? C.up : C.down}
            sub={ind?.macd?.status ? <span className="text-[10px]" style={{ color: C.muted }}>{ind.macd.status}</span> : null}
          />
          <Row label="MACD柱" value={ind?.macd?.macd == null && ind?.macd?.hist == null ? '—' : Number(ind.macd.macd ?? ind.macd.hist).toFixed(3)} />
          <Row
            label="KDJ(K/D/J)"
            value={ind?.kdj?.k == null || ind?.kdj?.d == null || ind?.kdj?.j == null ? '—' : `${Number(ind.kdj.k).toFixed(1)} / ${Number(ind.kdj.d).toFixed(1)} / ${Number(ind.kdj.j).toFixed(1)}`}
            color={ind?.kdj?.j >= 80 ? C.up : ind?.kdj?.j <= 20 ? C.down : C.primary}
            sub={ind?.kdj?.status ? <span className="text-[10px]" style={{ color: C.muted }}>{ind.kdj.status}</span> : null}
          />
          <Row label="均线结构" value={ind?.ma_struct || '—'} color={ind?.ma_struct === '多头排列' ? C.up : ind?.ma_struct === '空头排列' ? C.down : C.primary} />
          <Row label="EMA10" value={ind?.ema10 != null ? ind.ema10.toFixed(2) : '—'} />
          <Row label="EMA20" value={ind?.ema20 != null ? ind.ema20.toFixed(2) : '—'} />
          <Row label="MA5 / MA20" value={ind?.ma5 == null || ind?.ma20 == null ? '—' : `${ind.ma5.toFixed(2)} / ${ind.ma20.toFixed(2)}`} />
          <Row label="MA50" value={ind?.ma50 != null ? ind.ma50.toFixed(2) : '—'} />
          <Row label="MA60" value={ind?.ma60 != null ? ind.ma60.toFixed(2) : '—'} />
          <Row label="MA200" value={ind?.ma200 != null ? ind.ma200.toFixed(2) : '—'} />
          <Row label="MA20斜率" value={ind?.ma20_slope == null ? '—' : `${ind.ma20_slope >= 0 ? '+' : ''}${ind.ma20_slope.toFixed(2)}%`} />
          <Row label="支撑" value={ind?.support != null ? ind.support.toFixed(2) : '—'} />
          <Row label="阻力" value={ind?.resistance != null ? ind.resistance.toFixed(2) : '—'} />
          <Row label="ATR(14)" value={ind?.atr != null ? ind.atr.toFixed(2) : '—'} />
          <Row label="振幅" value={ind?.amplitude != null ? ind.amplitude.toFixed(2) + '%' : '—'} />
          <Row label="换手率" value={ind?.turnover == null ? '—' : `${Number(ind.turnover).toFixed(2)}%`} />
          <Row label="量比" value={ind?.rel_vol == null ? '—' : Number(ind.rel_vol).toFixed(2)} />
        </div>

        {/* 区间表现 */}
        <div className="mt-3 rounded-lg p-3" style={{ background: C.surface, border: `1px solid ${C.borderLight}` }}>
          <div className="text-[11px] font-semibold mb-1" style={{ color: C.secondary }}>区间表现</div>
          <Row
            label="距52周高"
            value={ind?.pct_from_high == null ? '—' : `${ind.pct_from_high >= 0 ? '+' : ''}${ind.pct_from_high.toFixed(1)}%`}
            color={avgColor(ind?.pct_from_high)}
          />
          <Row
            label="距52周低"
            value={ind?.pct_from_low == null ? '—' : `${ind.pct_from_low >= 0 ? '+' : ''}${ind.pct_from_low.toFixed(1)}%`}
            color={avgColor(ind?.pct_from_low)}
          />
          <Row label="52周高 / 低" value={ind?.high_52w == null || ind?.low_52w == null ? '—' : `${ind.high_52w.toFixed(2)} / ${ind.low_52w.toFixed(2)}`} />
          <Row label="5日" value={ind?.chg_5d == null ? '—' : `${avgSign(ind?.chg_5d)}${ind.chg_5d.toFixed(2)}%`} color={avgColor(ind?.chg_5d)} />
          <Row label="20日" value={ind?.chg_20d == null ? '—' : `${avgSign(ind?.chg_20d)}${ind.chg_20d.toFixed(2)}%`} color={avgColor(ind?.chg_20d)} />
          <Row label="60日" value={ind?.chg_60d == null ? '—' : `${avgSign(ind?.chg_60d)}${ind.chg_60d.toFixed(2)}%`} color={avgColor(ind?.chg_60d)} />
        </div>

        {/* 风险位 */}
        <div className="mt-3 rounded-lg p-3" style={{ background: 'rgba(249,115,22,0.05)', border: `1px solid ${C.borderLight}` }}>
          <Row
            label="止损价"
            value={ind?.stop_loss != null ? '$' + ind.stop_loss.toFixed(2) : '—'}
            color="#f97316"
            sub={ind?.stop_dist != null ? (
              <span className="text-[10px]" style={{ color: C.muted }}>距现价 {ind.stop_dist.toFixed(1)}%</span>
            ) : null}
          />
          <Row
            label="评分"
            value={ind?.score ?? '—'}
            color={ind?.score >= 60 ? C.up : ind?.score <= 40 ? C.down : C.primary}
            sub={ind?.state_label ? <span className="text-[10px]" style={{ color: C.muted }}>{ind.state_label}</span> : null}
          />
        </div>

        {/* 操作 */}
        <div className="mt-4 mb-2 flex items-center gap-2">
          <SinaLink market={market} code={stock.symbol} size="md" />
          <button onClick={onClose} className="ml-auto px-3 py-1 rounded text-[11px]" style={{ background: C.surface, border: `1px solid ${C.border}`, color: C.secondary }}>关闭</button>
        </div>
      </div>
    </div>
  );
}

function avgSign(v) { return v != null && v >= 0 ? '+' : ''; }
