/**
 * 回测摘要 — 最近一次组合回测的关键指标 + 历史 5 次对比折线
 */
import { useMemo } from 'react';
import { UP_COLOR, DOWN_COLOR } from '../../utils/colors';

export default function BacktestSummary({ backtest, loading }) {
  if (loading && !backtest) {
    return (
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>回测数据加载中...</div>
      </div>
    );
  }

  if (!backtest || !backtest.latest_run) {
    return (
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>📈 回测表现</h3>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {backtest?.message || '暂无回测数据'}
        </div>
      </div>
    );
  }

  const { latest_run, history = [] } = backtest;

  // 历史 5 次胜率/收益折线图（SVG）
  const sparkline = useMemo(() => buildSparkline(history), [history]);

  return (
    <div className="rounded-lg border p-3 space-y-2"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📈 回测表现</h3>
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{latest_run.run_at}</span>
      </div>

      <div className="grid grid-cols-4 gap-1.5">
        <Stat label="胜率" value={`${latest_run.win_rate?.toFixed(1)}%`} color={latest_run.win_rate >= 50 ? UP_COLOR : DOWN_COLOR} />
        <Stat label="总收益" value={`${latest_run.total_profit_pct?.toFixed(2)}%`} color={latest_run.total_profit_pct >= 0 ? UP_COLOR : DOWN_COLOR} />
        <Stat label="最大回撤" value={`${latest_run.max_drawdown_pct?.toFixed(2)}%`} color={DOWN_COLOR} />
        <Stat label="盈亏比" value={latest_run.profit_factor?.toFixed(2)} color={latest_run.profit_factor >= 1 ? UP_COLOR : DOWN_COLOR} />
      </div>

      {/* 历史趋势折线 */}
      {sparkline && (
        <div>
          <div className="flex items-center justify-between text-[10px] mb-1">
            <span style={{ color: 'var(--text-muted)' }}>近 {history.length} 次回测胜率趋势</span>
            <div className="flex gap-2">
              <span style={{ color: '#ef4444' }}>●胜率</span>
              <span style={{ color: '#3b82f6' }}>●收益</span>
            </div>
          </div>
          <svg width="100%" height="48" style={{ overflow: 'visible' }}>
            {sparkline.win.line && <path d={sparkline.win.line} fill="none" stroke="#ef4444" strokeWidth="1.5" strokeLinejoin="round" />}
            {sparkline.win.area && <path d={sparkline.win.area} fill="rgba(239,68,68,0.12)" />}
            {sparkline.win.dots.map((d, i) => (
              <circle key={`w${i}`} cx={d.x} cy={d.y} r="2" fill="#ef4444" />
            ))}
            {sparkline.profit.line && <path d={sparkline.profit.line} fill="none" stroke="#3b82f6" strokeWidth="1.5" strokeLinejoin="round" />}
            {sparkline.profit.dots.map((d, i) => (
              <circle key={`p${i}`} cx={d.x} cy={d.y} r="2" fill="#3b82f6" />
            ))}
          </svg>
        </div>
      )}

      <div className="grid grid-cols-3 gap-2 text-[10px] pt-1 border-t"
        style={{ borderColor: 'var(--border-color)' }}>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>个股数</div>
          <div className="font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{latest_run.stock_count}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>总交易</div>
          <div className="font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{latest_run.total_trades}</div>
        </div>
        <div>
          <div style={{ color: 'var(--text-muted)' }}>持仓天数</div>
          <div className="font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{latest_run.avg_hold_days?.toFixed(1)}</div>
        </div>
      </div>
    </div>
  );
}

function Stat({ label, value, color }) {
  return (
    <div className="rounded p-1.5" style={{ background: 'var(--bg-hover)' }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-xs font-bold mt-0.5" style={{ color }}>{value}</div>
    </div>
  );
}

/**
 * 构建 SVG 折线图（胜率 + 收益双线）
 */
function buildSparkline(history) {
  if (!history || history.length < 2) return null;

  const W = 280, H = 48, PAD = 4;
  const wins = history.map(h => h.win_rate || 0).reverse();   // 老到新
  const profits = history.map(h => h.total_profit_pct || 0).reverse();

  const buildLine = (data, min, max) => {
    const range = Math.max(max - min, 1);
    const stepX = (W - PAD * 2) / (data.length - 1);
    const pts = data.map((v, i) => ({
      x: PAD + i * stepX,
      y: H - PAD - ((v - min) / range) * (H - PAD * 2),
    }));
    const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
    const area = `${line} L${pts[pts.length - 1].x.toFixed(1)},${H} L${pts[0].x.toFixed(1)},${H} Z`;
    return { line, area, dots: pts };
  };

  const all = [...wins, ...profits];
  const min = Math.min(...all);
  const max = Math.max(...all);

  return {
    win: buildLine(wins, min, max),
    profit: buildLine(profits, min, max),
  };
}
