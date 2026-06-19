import { useState, useEffect } from 'react';
import TreemapChart from '../components/charts/TreemapChart';
import TrendLineChart from '../components/charts/TrendLineChart';

export default function HeatmapPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [days, setDays] = useState(5);
  const [viewDate, setViewDate] = useState('');

  useEffect(() => {
    fetch('/api/latest-date')
      .then(r => r.json())
      .then(d => {
        const date = d.date || new Date().toISOString().split('T')[0];
        setSelectedDate(date);
        setViewDate(date);
      })
      .catch(() => {
        const today = new Date().toISOString().split('T')[0];
        setSelectedDate(today);
        setViewDate(today);
      });
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetch(`/api/heatmap?date=${selectedDate}&days=${days}`)
      .then(r => r.json())
      .then(d => {
        // API返回日期为倒序(新→旧)，反转为正序(旧→新)方便导航
        const reversed = {
          ...d,
          dates: [...d.dates].reverse(),
          values: d.values.map(v => [d.dates.length - 1 - v[0], v[1], v[2]]),
        };
        setData(reversed);
        if (reversed.dates && reversed.dates.length > 0) {
          setViewDate(reversed.dates[reversed.dates.length - 1]);
        }
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }, [selectedDate, days]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  const changeViewDate = (offset) => {
    if (!data?.dates) return;
    const idx = data.dates.indexOf(viewDate);
    const newIdx = Math.max(0, Math.min(data.dates.length - 1, idx + offset));
    setViewDate(data.dates[newIdx]);
  };

  const topSectors = data?.values && viewDate
    ? (() => {
        const dateIdx = data.dates.indexOf(viewDate);
        return [...new Set(data.values.filter(v => v[0] === dateIdx).map(v => data.sectors[v[1]]))]
          .map(sector => {
            const val = data.values.find(v => v[0] === dateIdx && data.sectors[v[1]] === sector);
            return { sector, heat: val ? val[2] : 0 };
          })
          .sort((a, b) => b.heat - a.heat);
      })()
    : [];

  const viewDateIdx = data?.dates ? data.dates.indexOf(viewDate) : -1;
  const canGoBack = viewDateIdx > 0;
  const canGoForward = data?.dates ? viewDateIdx < data.dates.length - 1 : false;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>主线热力图</h2>
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
          <select value={days} onChange={(e) => setDays(Number(e.target.value))} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
            <option value={3}>3天</option>
            <option value={5}>5天</option>
            <option value={10}>10天</option>
            <option value={20}>20天</option>
          </select>
        </div>
      </div>

      {data?.dates && data.dates.length > 1 && (
        <div className="flex items-center justify-center gap-4">
          <button
            onClick={() => changeViewDate(-1)}
            disabled={!canGoBack}
            className="px-3 py-1 rounded-lg border text-sm disabled:opacity-30"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            ← 前日
          </button>
          <div className="flex items-center gap-2">
            {data.dates.map((d, i) => (
              <button
                key={d}
                onClick={() => setViewDate(d)}
                className="px-3 py-1 rounded-lg text-xs font-medium transition-all"
                style={{
                  background: d === viewDate ? 'var(--accent-color, #3b82f6)' : 'var(--bg-surface)',
                  color: d === viewDate ? '#fff' : 'var(--text-muted)',
                  border: `1px solid ${d === viewDate ? 'transparent' : 'var(--border-color)'}`,
                }}
              >
                {d.slice(5)}
              </button>
            ))}
          </div>
          <button
            onClick={() => changeViewDate(1)}
            disabled={!canGoForward}
            className="px-3 py-1 rounded-lg border text-sm disabled:opacity-30"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            后日 →
          </button>
        </div>
      )}

      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <TreemapChart data={data} selectedDate={viewDate} />
        )}
      </div>

      {topSectors.length > 0 && !loading && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
            Top 10 板块热度趋势 <span className="text-xs ml-1" style={{ color: 'var(--text-muted)' }}>({data.dates[0].slice(5)} → {data.dates[data.dates.length-1].slice(5)})</span>
          </h3>
          <TrendLineChart data={data} topSectors={topSectors} />
        </div>
      )}

      {topSectors.length > 0 && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>
            热度 Top 10 板块 <span className="text-xs ml-1" style={{ color: 'var(--text-muted)' }}>({viewDate})</span>
          </h3>
          <div className="grid grid-cols-2 gap-x-6 gap-y-2">
            {topSectors.slice(0, 10).map((s, i) => (
              <div key={s.sector} className="flex items-center gap-3">
                <span className="text-xs w-6 font-bold" style={{ color: i < 3 ? '#ef4444' : 'var(--text-muted)' }}>{i + 1}</span>
                <span className="text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                <div className="w-24 h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
                  <div className="h-full rounded-full transition-all" style={{ width: `${s.heat}%`, background: s.heat > 70 ? '#dc2626' : s.heat > 55 ? '#f97316' : s.heat > 40 ? '#eab308' : '#22c55e' }} />
                </div>
                <span className="text-xs w-10 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{s.heat.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
