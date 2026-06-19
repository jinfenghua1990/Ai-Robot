import { useState, useEffect } from 'react';
import FlowGraph from '../components/charts/FlowGraph';

export default function MoneyFlowPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');

  useEffect(() => {
    fetch('/api/latest-date')
      .then(r => r.json())
      .then(d => { if (d.date) setSelectedDate(d.date); else setSelectedDate(new Date().toISOString().split('T')[0]); })
      .catch(() => setSelectedDate(new Date().toISOString().split('T')[0]));
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetch(`/api/money-flow?date=${selectedDate}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedDate]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>资金流路径</h2>
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

      {/* 图例 */}
      <div className="flex items-center gap-4 text-xs" style={{ color: 'var(--text-secondary)' }}>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full" style={{ background: '#6366f1' }} />资金来源</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full" style={{ background: '#3b82f6' }} />板块</span>
        <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded-full" style={{ background: '#ef4444' }} />龙头股</span>
      </div>

      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <FlowGraph data={data} />
        )}
      </div>

      {/* 主力净流入Top10 */}
      {data?.top10 && data.top10.length > 0 && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>主力净流入 Top 10</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border-color)' }}>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>代码</th>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>名称</th>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>板块</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>主力流入(万)</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>涨跌幅</th>
                </tr>
              </thead>
              <tbody>
                {data.top10.map((stock, i) => (
                  <tr key={i} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                    <td className="py-2 px-3 font-mono" style={{ color: 'var(--text-primary)' }}>{stock.ts_code}</td>
                    <td className="py-2 px-3" style={{ color: 'var(--text-secondary)' }}>{stock.name || '-'}</td>
                    <td className="py-2 px-3" style={{ color: 'var(--text-secondary)' }}>{stock.sector || '-'}</td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--accent-red)' }}>+{stock.main_force_inflow?.toFixed(2)}</td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: stock.price_chg >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {stock.price_chg >= 0 ? '+' : ''}{stock.price_chg?.toFixed(2)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
