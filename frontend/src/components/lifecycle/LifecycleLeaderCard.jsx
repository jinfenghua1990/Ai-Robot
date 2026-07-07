import SignalCard from '../trading/SignalCard';

/**
 * ② 主龙卡（保留主龙特殊样式，叠加切换预警和评分明细）
 */
export default function LifecycleLeaderCard({ leader, switchWarning }) {
  if (!leader) {
    return (
      <div className="rounded-lg border border-dashed p-3 text-center flex items-center justify-center gap-2" style={{ borderColor: 'var(--border-color)' }}>
        <div className="text-base">🔍</div>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          <span style={{ color: 'var(--text-secondary)' }}>暂无主龙</span>
          <span className="ml-1.5">· 当前可交易板块内无评分≥5的龙头候选</span>
        </div>
      </div>
    );
  }

  const leaderScore = leader.leaderScore ?? leader.score ?? 0;
  const secName = leader.secName || leader.name || '';
  const secCode = leader.secCode || leader.ts_code || '';
  const sector = leader.sector || '';
  const sectorStateLabel = leader.sectorStateLabel || leader.sector_state_label || '';
  const sectorScore = leader.sectorScore ?? leader.sector_score;
  const changeRate = leader.quote?.changePct ?? leader.change_rate ?? 0;
  const consecutiveDays = leader.position?.count ?? leader.consecutive_days ?? 0;
  const stage = leader.signalLabel !== '留意' ? leader.signalLabel : (leader.stage || '留意');
  const details = leader.details || {};

  const scoreColor = leaderScore >= 7 ? '#ef4444' : leaderScore >= 5 ? '#f97316' : '#facc15';

  return (
    <div className="rounded-lg border-2 p-3" style={{ borderColor: scoreColor + '60', background: 'var(--bg-card)' }}>
      <div className="flex items-center gap-3">
        <div className="flex-shrink-0 w-14 h-14 rounded-lg flex flex-col items-center justify-center font-bold" style={{ background: scoreColor + '15', border: `2px solid ${scoreColor}` }}>
          <span className="text-[10px]" style={{ color: scoreColor }}>主龙</span>
          <span className="text-xl" style={{ color: scoreColor }}>{leaderScore}</span>
        </div>

        <div className="flex-1">
          <div className="flex items-center gap-1.5">
            <span className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{secName}</span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{secCode}</span>
            {sectorStateLabel && (
              <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: scoreColor + '15', color: scoreColor }}>
                {sectorStateLabel}板块
              </span>
            )}
          </div>
          <div className="flex items-center gap-2 mt-0.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <span>板块: <b style={{ color: 'var(--text-primary)' }}>{sector}</b></span>
            {sectorScore != null && <span>板块评分: <b style={{ color: scoreColor }}>{sectorScore}</b></span>}
            <span>涨幅: <b style={{ color: changeRate > 0 ? '#ef4444' : '#22c55e' }}>{changeRate > 0 ? '+' : ''}{changeRate?.toFixed(2)}%</b></span>
            <span>连板: <b style={{ color: 'var(--text-primary)' }}>{consecutiveDays}</b></span>
            <span>阶段: <b style={{ color: 'var(--text-primary)' }}>{stage}</b></span>
          </div>
        </div>
      </div>

      <div className="mt-2">
        <SignalCard
          signal={leader}
          orders={[]}
          showWatchBtn
          mode="watchlist"
          showMarketState
          showBuyPower
          showAnalysisButton
        />
      </div>

      {switchWarning && (
        <div className="mt-3 px-3 py-2 rounded-lg flex items-center gap-2 text-sm" style={{ background: 'rgba(250,204,21,0.08)', border: '1px solid rgba(250,204,21,0.2)' }}>
          <span style={{ color: '#facc15' }}>⚠️</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            切换预警: 候选 <b style={{ color: '#facc15' }}>{switchWarning.new_candidate}</b> 评分接近（差{switchWarning.score_diff}分）
          </span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{switchWarning.reason}</span>
        </div>
      )}

      {Object.keys(details).length > 0 && (
        <div className="mt-2 flex items-center gap-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>
          <span>评分明细:</span>
          {Object.entries(details).map(([k, v]) => (
            <span key={k} className="px-1.5 py-0.5 rounded" style={{ background: v > 0 ? 'rgba(34,197,94,0.08)' : 'rgba(148,163,184,0.05)', color: v > 0 ? '#22c55e' : 'var(--text-muted)' }}>
              {k}:{v}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
