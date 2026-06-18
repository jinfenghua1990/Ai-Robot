import { useState, useEffect } from 'react';
import LifecycleTimeline from '../components/charts/LifecycleTimeline';

const STAGES = ['全部', '启动', '发酵', '主升', '分歧', '退潮'];
const STAGE_COLORS = {
  '启动': '#3b82f6', '发酵': '#eab308', '主升': '#ef4444',
  '分歧': '#f97316', '退潮': '#64748b',
};

export default function LifecyclePage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [stageFilter, setStageFilter] = useState('全部');

  useEffect(() => {
    const today = new Date().toISOString().split('T')[0];
    setSelectedDate(today);
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    const stageParam = stageFilter !== '全部' ? `&stage=${stageFilter}` : '';
    fetch(`/api/lifecycle?date=${selectedDate}${stageParam}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedDate, stageFilter]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  // 统计各阶段数量
  const stageCounts = data?.leaders
    ? STAGES.slice(1).map(s => ({
        stage: s,
        count: data.leaders.filter(l => l.stage === s).length,
        color: STAGE_COLORS[s],
      }))
    : [];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>龙头生命周期</h2>
        <div className="flex items-center gap-3">
          <button onClick={() => changeDate(-1)} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>前一天</button>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            className="px-3 py-1.5 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
          <button onClick={() => changeDate(1)} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>后一天</button>
        </div>
      </div>

      {/* 阶段统计卡片 */}
      {stageCounts.length > 0 && (
        <div className="grid grid-cols-5 gap-3">
          {stageCounts.map(s => (
            <button
              key={s.stage}
              onClick={() => setStageFilter(stageFilter === s.stage ? '全部' : s.stage)}
              className="rounded-lg border p-3 text-center transition-all"
              style={{
                borderColor: stageFilter === s.stage ? s.color : 'var(--border-color)',
                background: stageFilter === s.stage ? s.color + '20' : 'var(--bg-card)',
              }}
            >
              <div className="text-2xl font-bold" style={{ color: s.color }}>{s.count}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{s.stage}</div>
            </button>
          ))}
        </div>
      )}

      {/* 筛选标签 */}
      <div className="flex items-center gap-2">
        {STAGES.map(s => (
          <button
            key={s}
            onClick={() => setStageFilter(s)}
            className="px-3 py-1 rounded-full text-xs border transition-all"
            style={{
              borderColor: stageFilter === s ? 'var(--accent-blue)' : 'var(--border-color)',
              background: stageFilter === s ? 'var(--accent-blue)' : 'transparent',
              color: stageFilter === s ? '#fff' : 'var(--text-secondary)',
            }}
          >
            {s}
          </button>
        ))}
      </div>

      {/* 生命周期列表 */}
      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <LifecycleTimeline leaders={data?.leaders || []} />
        )}
      </div>
    </div>
  );
}
