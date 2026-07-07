/**
 * 风控面板 — 总仓位/上限/高位股/警告
 */
export default function RiskPanel({ riskStatus, loading }) {
  if (loading && !riskStatus) {
    return (
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>风控状态加载中...</div>
      </div>
    );
  }

  if (!riskStatus) {
    return (
      <div className="rounded-lg border p-3 space-y-2"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🛡️ 风控状态</h3>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无风控数据</div>
      </div>
    );
  }

  const { total_position_pct, total_cap_pct, sentiment, single_risk_pct,
          high_position_stocks = [], warnings = [], config = {} } = riskStatus;

  const usagePct = total_cap_pct > 0 ? (total_position_pct / total_cap_pct) * 100 : 0;
  const isOverLimit = total_position_pct >= total_cap_pct;

  return (
    <div className="rounded-lg border p-3 space-y-2.5"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🛡️ 风控状态</h3>
        <span className="text-[10px] px-1.5 py-0.5 rounded"
          style={{
            background: isOverLimit ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)',
            color: isOverLimit ? '#ef4444' : '#22c55e',
          }}>
          {isOverLimit ? '超限' : '正常'}
        </span>
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总仓位 / 上限</div>
          <div className="text-xs font-bold mt-0.5" style={{ color: isOverLimit ? '#ef4444' : 'var(--text-primary)' }}>
            {total_position_pct?.toFixed(1)}% / {total_cap_pct}%
          </div>
        </div>
        <div className="rounded p-2" style={{ background: 'var(--bg-hover)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>单股风险</div>
          <div className="text-xs font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>
            {single_risk_pct}% 资金
          </div>
        </div>
      </div>

      {/* 仓位使用率进度条 */}
      <div>
        <div className="flex justify-between text-[10px] mb-1">
          <span style={{ color: 'var(--text-muted)' }}>仓位使用率</span>
          <span className="font-bold" style={{
            color: usagePct >= 100 ? '#ef4444' : usagePct >= 70 ? '#facc15' : '#22c55e'
          }}>
            {usagePct.toFixed(1)}%
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

      {/* 高位股 */}
      {high_position_stocks.length > 0 && (
        <div>
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>
            高位股 ({high_position_stocks.length} 只 · 单股上限 3%)
          </div>
          <div className="flex flex-wrap gap-1">
            {high_position_stocks.slice(0, 6).map(s => (
              <span key={s.code} className="text-[10px] px-1.5 py-0.5 rounded"
                style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>
                {s.name || s.code}
              </span>
            ))}
            {high_position_stocks.length > 6 && (
              <span className="text-[10px] px-1.5 py-0.5" style={{ color: 'var(--text-muted)' }}>
                +{high_position_stocks.length - 6}
              </span>
            )}
          </div>
        </div>
      )}

      {/* 警告 */}
      {warnings.length > 0 && (
        <div className="space-y-1">
          {warnings.map((w, i) => (
            <div key={i} className="text-[10px] px-2 py-1 rounded flex items-start gap-1"
              style={{ background: 'rgba(250,204,21,0.1)', color: '#a16207' }}>
              <span>⚠</span>
              <span>{w}</span>
            </div>
          ))}
        </div>
      )}

      {/* 风控配置 */}
      {config && Object.keys(config).length > 0 && (
        <div className="text-[10px] pt-1 border-t flex flex-wrap gap-x-3 gap-y-0.5"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
          <span>单股上限 {config.single_position_pct}%</span>
          <span>最大持仓 {config.max_positions} 只</span>
          <span>止损 {config.stop_loss_pct}%</span>
          <span>止盈 +{config.take_profit_pct}%</span>
        </div>
      )}
    </div>
  );
}
