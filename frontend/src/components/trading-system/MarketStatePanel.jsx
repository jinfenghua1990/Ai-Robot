/**
 * 市场状态面板 — 显示当前市场状态/情绪/总仓位建议
 */
export default function MarketStatePanel({ overview, summary, loading }) {
  if (loading && !overview) {
    return (
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>市场总览加载中...</div>
      </div>
    );
  }

  if (!overview) {
    return (
      <div className="rounded-lg border p-3 space-y-2"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 市场总览</h3>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无市场总览数据</div>
      </div>
    );
  }

  const { market_state, sentiment, total_position_suggestion, total_cap_pct } = overview;
  const sentimentColor = SENTIMENT_COLORS[sentiment] || '#9CA3AF';
  const stateColor = STATE_COLORS[market_state] || '#9CA3AF';
  const usagePct = total_cap_pct > 0 ? (total_position_suggestion / total_cap_pct) * 100 : 0;

  return (
    <div className="rounded-lg border p-3 space-y-2.5"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 市场总览</h3>
        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold"
          style={{ background: `${stateColor}22`, color: stateColor }}>
          {STATE_LABELS[market_state] || market_state}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>情绪温度</div>
          <div className="text-sm font-bold mt-0.5" style={{ color: sentimentColor }}>{sentiment}</div>
        </div>
        <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>可买股票</div>
          <div className="text-sm font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>
            {(summary?.strong_buy || 0) + (summary?.watch_buy || 0)} 只
          </div>
        </div>
      </div>

      {/* 总仓位进度条 */}
      <div>
        <div className="flex items-center justify-between text-[10px] mb-1">
          <span style={{ color: 'var(--text-muted)' }}>总仓位建议</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            <span className="font-bold" style={{ color: usagePct >= 100 ? '#ef4444' : 'var(--text-primary)' }}>
              {total_position_suggestion?.toFixed(1)}%
            </span>
            <span className="mx-1">/</span>
            <span>{total_cap_pct}%</span>
          </span>
        </div>
        <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-hover)' }}>
          <div
            className="h-full rounded-full transition-all"
            style={{
              width: `${Math.min(usagePct, 100)}%`,
              background: usagePct >= 100 ? '#ef4444' : usagePct >= 70 ? '#facc15' : '#22c55e',
            }}
          />
        </div>
      </div>
    </div>
  );
}

const SENTIMENT_COLORS = {
  '恐慌': '#22c55e',
  '谨慎': '#84cc16',
  '中性': '#a855f7',
  '乐观': '#f97316',
  '狂热': '#ef4444',
};

const STATE_COLORS = {
  'IMPULSE': '#ef4444',
  'TREND': '#f97316',
  'CHOPPY': '#a855f7',
  'PENDING': '#9CA3AF',
};

const STATE_LABELS = {
  'IMPULSE': '冲动',
  'TREND': '趋势',
  'CHOPPY': '震荡',
  'PENDING': '待定',
};
