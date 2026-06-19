import { useState, useEffect } from 'react';
import HeatmapChart from '../components/charts/HeatmapChart';

export default function HeatmapPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [days, setDays] = useState(5);
  const [topN, setTopN] = useState(30);

  useEffect(() => {
    fetch('/api/latest-date')
      .then(r => r.json())
      .then(d => { if (d.date) setSelectedDate(d.date); else setSelectedDate(new Date().toISOString().split('T')[0]); })
      .catch(() => setSelectedDate(new Date().toISOString().split('T')[0]));
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetch(`/api/heatmap?date=${selectedDate}&days=${days}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedDate, days]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  // 按热度排序的板块列表
  const topSectors = data?.values
    ? [...new Set(data.values.map(v => data.sectors[v[1]]))]
        .map(sector => {
          const vals = data.values.filter(v => data.sectors[v[1]] === sector);
          const maxHeat = Math.max(...vals.map(v => v[2]));
          return { sector, heat: maxHeat };
        })
        .sort((a, b) => b.heat - a.heat)
    : [];

  // 筛选 Top N 板块的热力图数据
  const filteredData = data && topSectors.length > 0
    ? (() => {
        const topSectorNames = new Set(topSectors.slice(0, topN).map(s => s.sector));
        const filteredSectors = topSectors.slice(0, topN).map(s => s.sector);
        const sectorIndexMap = new Map(filteredSectors.map((s, i) => [s, i]));
        const filteredValues = data.values
          .filter(v => topSectorNames.has(data.sectors[v[1]]))
          .map(v => [v[0], sectorIndexMap.get(data.sectors[v[1]]), v[2]]);
        return { ...data, sectors: filteredSectors, values: filteredValues };
      })()
    : data;

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
          <select value={topN} onChange={(e) => setTopN(Number(e.target.value))} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
            <option value={20}>Top 20</option>
            <option value={30}>Top 30</option>
            <option value={50}>Top 50</option>
            <option value={9999}>全部</option>
          </select>
        </div>
      </div>

      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <HeatmapChart data={filteredData} />
        )}
      </div>

      {topSectors.length > 0 && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>热度 Top 10 板块</h3>
          <div className="space-y-2">
            {topSectors.slice(0, 10).map((s, i) => (
              <div key={s.sector} className="flex items-center gap-3">
                <span className="text-xs w-6" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                <span className="text-sm flex-1" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                <div className="w-32 h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-surface)' }}>
                  <div className="h-full rounded-full" style={{ width: `${s.heat}%`, background: s.heat > 70 ? '#ef4444' : s.heat > 40 ? '#eab308' : '#22c55e' }} />
                </div>
                <span className="text-xs w-10 text-right" style={{ color: 'var(--text-secondary)' }}>{s.heat.toFixed(1)}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
