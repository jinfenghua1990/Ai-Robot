/**
 * ① 板块状态总览（主升/轮动/下降）
 * 展示板块分数卡 + 净流入 + 涨停数
 */
export default function LifecycleSectorOverview({ sectorFilter }) {
  const { strong = [], rotation = [], down = [] } = sectorFilter || {};

  const renderSectorCard = (s, color, bg) => (
    <div
      key={s.sector}
      className="rounded-lg p-2.5 border"
      style={{ borderColor: color + '30', background: bg }}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
        <span className="text-xs px-1.5 py-0.5 rounded font-bold" style={{ background: color + '20', color }}>{s.score}分</span>
      </div>
      <div className="flex items-center gap-3 mt-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
        <span>热度<b style={{ color, marginLeft: 2 }}>{s.heat?.toFixed(0)}</b></span>
        <span>净流入<b style={{ color: s.net_flow > 0 ? '#ef4444' : '#22c55e', marginLeft: 2 }}>{(s.net_flow / 10000).toFixed(0)}万</b></span>
        {s.limit_up_count > 0 && <span>涨停<b style={{ color: 'var(--text-primary)', marginLeft: 2 }}>{s.limit_up_count}</b></span>}
      </div>
    </div>
  );

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <span>🔥</span> 主升板块
          <span className="text-xs font-normal px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>可交易 {strong.length}</span>
        </h3>
        {strong.length > 0 ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {strong.map((s) => renderSectorCard(s, '#ef4444', 'rgba(239,68,68,0.05)'))}
          </div>
        ) : (
          <div className="text-xs px-3 py-2 rounded border" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>暂无主升板块</div>
        )}
      </div>

      {rotation.length > 0 && (
        <div>
          <h3 className="text-sm font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <span>⚡</span> 轮动板块
            <span className="text-xs font-normal px-1.5 py-0.5 rounded" style={{ background: 'rgba(250,204,21,0.1)', color: '#facc15' }}>轻仓 {rotation.length}</span>
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {rotation.map((s) => renderSectorCard(s, '#facc15', 'rgba(250,204,21,0.05)'))}
          </div>
        </div>
      )}

      {down.length > 0 && (
        <details>
          <summary className="text-sm font-bold cursor-pointer flex items-center gap-2 mb-2" style={{ color: 'var(--text-muted)' }}>
            <span>⛔</span> 下降板块
            <span className="text-xs font-normal px-1.5 py-0.5 rounded" style={{ background: 'rgba(148,163,184,0.1)', color: 'var(--text-muted)' }}>禁止交易 {down.length}</span>
          </summary>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-2">
            {down.map((s) => renderSectorCard(s, '#94a3b8', 'rgba(148,163,184,0.05)'))}
          </div>
        </details>
      )}
    </div>
  );
}
