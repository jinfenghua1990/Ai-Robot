import { useState } from 'react';

/**
 * ⑤ 历史统计模块
 * - 统计卡片（寿命/切换/活跃/总数）
 * - 板块龙头统计 TOP
 * - 历史记录（折叠表格）
 */
export default function LifecycleHistoryStats({ stats, history = [] }) {
  const [historyOpen, setHistoryOpen] = useState(false);

  if (!stats && history.length === 0) {
    return (
      <div className="rounded-lg border p-4 text-center" style={{ borderColor: 'var(--border-color)' }}>
        <span className="text-sm" style={{ color: 'var(--text-muted)' }}>暂无历史数据（首次运行后开始记录）</span>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
        <span>📈</span> 历史统计
        {stats?.date_range && (
          <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>
            {stats.date_range.start} ~ {stats.date_range.end}
          </span>
        )}
      </h3>

      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard label="龙头平均寿命" value={stats.avg_life_days} unit="天" color="#3b82f6" />
          <StatCard label="切换次数" value={stats.switch_count} unit="次" color="#f97316" />
          <StatCard label="活跃板块数" value={stats.active_sectors} unit="个" color="#22c55e" />
          <StatCard label="总记录数" value={stats.total_records} unit="条" color="#a855f7" />
        </div>
      )}

      {stats?.sector_breakdown?.length > 0 && (
        <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
          <div className="px-3 py-2 text-xs font-bold border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
            板块龙头统计 TOP{stats.sector_breakdown.length}
          </div>
          <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
            {stats.sector_breakdown.map((s, idx) => (
              <div key={s.sector} className="flex items-center gap-3 px-3 py-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
                <span className="font-bold flex-shrink-0" style={{ color: idx < 3 ? '#f97316' : 'var(--text-muted)' }}>#{idx + 1}</span>
                <span className="font-medium flex-shrink-0" style={{ color: 'var(--text-primary)', minWidth: 80 }}>{s.sector}</span>
                <span className="text-xs">记录<b style={{ color: 'var(--text-primary)' }}>{s.record_count}</b></span>
                <span className="text-xs">龙头<b style={{ color: 'var(--text-primary)' }}>{s.leader_count}</b>只</span>
                <span className="text-xs">均分<b style={{ color: '#3b82f6' }}>{s.avg_score.toFixed(1)}</b></span>
                <span className="text-xs truncate" style={{ color: 'var(--text-muted)' }}>{s.leaders.join('、')}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {history.length > 0 && (
        <div>
          <button
            onClick={() => setHistoryOpen(!historyOpen)}
            className="w-full flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-medium transition-colors hover:opacity-80"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          >
            <span className="flex items-center gap-2">
              <span>📋</span> 历史记录
              <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>（{history.length}条）</span>
            </span>
            <span style={{ color: 'var(--text-muted)' }}>{historyOpen ? '▲ 收起' : '▼ 展开'}</span>
          </button>
          {historyOpen && (
            <div className="mt-2 rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
              <table className="w-full text-sm">
                <thead>
                  <tr style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
                    <th className="px-3 py-2 text-left">日期</th>
                    <th className="px-3 py-2 text-left">板块</th>
                    <th className="px-3 py-2 text-left">龙头</th>
                    <th className="px-3 py-2 text-right">龙头分</th>
                    <th className="px-3 py-2 text-right">板块分</th>
                    <th className="px-3 py-2 text-center">阶段</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((h) => (
                    <tr key={`${h.date}-${h.leader_code}`} style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
                      <td className="px-3 py-2 text-xs">{h.date}</td>
                      <td className="px-3 py-2 text-xs">{h.sector}</td>
                      <td className="px-3 py-2">
                        <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{h.leader_name}</span>
                        <span className="ml-1 text-xs" style={{ color: 'var(--text-muted)' }}>{h.leader_code}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-bold" style={{ color: h.leader_score >= 5 ? '#ef4444' : '#facc15' }}>{h.leader_score}</td>
                      <td className="px-3 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{h.sector_score}</td>
                      <td className="px-3 py-2 text-center text-xs">{h.stage}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value, unit, color }) {
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: color + '30', background: 'var(--bg-card)' }}>
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="flex items-baseline gap-1 mt-1">
        <span className="text-2xl font-bold" style={{ color }}>{value}</span>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{unit}</span>
      </div>
    </div>
  );
}
