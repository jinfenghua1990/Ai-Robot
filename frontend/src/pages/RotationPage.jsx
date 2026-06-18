import { useState, useEffect } from 'react';
import SankeyChart from '../components/charts/SankeyChart';

export default function RotationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [lookbackDays, setLookbackDays] = useState(5);

  useEffect(() => {
    const today = new Date().toISOString().split('T')[0];
    setSelectedDate(today);
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetch(`/api/rotation?date=${selectedDate}&days=${lookbackDays}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedDate, lookbackDays]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>板块轮动图</h2>
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
          <select value={lookbackDays} onChange={(e) => setLookbackDays(Number(e.target.value))} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
            <option value={3}>近3天</option>
            <option value={5}>近5天</option>
            <option value={10}>近10天</option>
          </select>
        </div>
      </div>

      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <SankeyChart data={data} />
        )}
      </div>

      {data?.signals && data.signals.length > 0 && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>轮动信号</h3>
          <div className="space-y-2">
            {data.signals.map((signal, i) => (
              <div key={i} className="flex items-center gap-2 text-sm" style={{ color: 'var(--text-primary)' }}>
                <span className="w-2 h-2 rounded-full" style={{ background: signal.includes('流入') ? '#22c55e' : '#ef4444' }} />
                {signal}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
