import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

export default function DataCenterSchedulePage() {
  const [loading, setLoading] = useState(true);
  const [scheduleData, setScheduleData] = useState(null);

  useEffect(() => {
    apiFetch('/api/data-center/schedule').then(res => {
      if (res.ok) setScheduleData(res.data);
    }).finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const jobs = scheduleData?.jobs || scheduleData || [];

  return (
    <div className="space-y-3">
      <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>定时采集</h2>
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>定时任务 ({Array.isArray(jobs) ? jobs.length : 0})</div>
        {(!jobs || jobs.length === 0) ? (
          <div className="text-xs" style={{ color: MUTED }}>暂无定时任务数据</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>任务名称</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>状态</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>上次运行</th>
                  <th className="text-left py-1.5 px-2" style={{ color: MUTED }}>下次运行</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="py-1.5 px-2" style={{ color: 'var(--text-primary)' }}>{job.name || job.label || job.id || job.plist || '—'}</td>
                    <td className="py-1.5 px-2">
                      <span className="inline-flex items-center gap-1">
                        <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ background: job.status === 'running' || job.status === 'active' ? DOWN : MUTED }} />
                        <span style={{ color: job.status === 'running' || job.status === 'active' ? DOWN : MUTED }}>{job.status || '—'}</span>
                      </span>
                    </td>
                    <td className="py-1.5 px-2" style={{ color: MUTED }}>{job.last_run || job.last_run_time || '—'}</td>
                    <td className="py-1.5 px-2" style={{ color: MUTED }}>{job.next_run || job.next_run_time || job.schedule || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
