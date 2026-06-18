const STAGES = [
  { key: '启动', color: '#3b82f6', icon: '🟦' },
  { key: '发酵', color: '#eab308', icon: '🟨' },
  { key: '主升', color: '#ef4444', icon: '🟥' },
  { key: '分歧', color: '#f97316', icon: '🟧' },
  { key: '退潮', color: '#64748b', icon: '⬜' },
];

export default function LifecycleTimeline({ leaders }) {
  if (!leaders || leaders.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无龙头数据
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {leaders.map((leader, idx) => {
        const currentStageIdx = STAGES.findIndex(s => s.key === leader.stage);
        return (
          <div key={idx} className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
            <div className="flex items-center justify-between mb-2">
              <div className="flex items-center gap-2">
                <span className="font-mono text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{leader.ts_code}</span>
                <span className="text-xs px-2 py-0.5 rounded" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>{leader.sector || '未知'}</span>
              </div>
              <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-secondary)' }}>
                <span>连板: {leader.consecutive_days}</span>
                <span style={{ color: leader.change_rate >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                  {leader.change_rate >= 0 ? '+' : ''}{leader.change_rate?.toFixed(2)}%
                </span>
                <span>强度: {leader.strength?.toFixed(0)}</span>
              </div>
            </div>
            {/* 生命周期进度条 */}
            <div className="flex items-center gap-1">
              {STAGES.map((stage, i) => {
                const isPassed = i < currentStageIdx;
                const isCurrent = i === currentStageIdx;
                return (
                  <div key={stage.key} className="flex-1 flex items-center gap-1">
                    <div
                      className="flex-1 h-6 rounded flex items-center justify-center text-xs font-medium transition-all"
                      style={{
                        background: isCurrent ? stage.color : isPassed ? stage.color + '40' : 'var(--bg-hover)',
                        color: isCurrent ? '#fff' : 'var(--text-muted)',
                        opacity: isPassed ? 0.5 : 1,
                      }}
                    >
                      {stage.key}
                    </div>
                    {i < STAGES.length - 1 && (
                      <div className="w-2 h-0.5" style={{ background: isPassed ? STAGES[i].color + '60' : 'var(--border-color)' }} />
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        );
      })}
    </div>
  );
}
