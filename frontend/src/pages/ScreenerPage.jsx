import { useState, useEffect } from 'react';

const STRATEGIES = [
  { key: 'heat', label: '热度综合', desc: '板块热度Top5 + 启动/发酵阶段 + 主力净流入' },
  { key: 'baihu', label: '白虎V2.6', desc: 'MA20强势回调，5维度评分≥4分入选' },
  { key: 'qinglong', label: '青龙', desc: 'MA10主升浪回踩策略' },
];

const STAGE_COLORS = {
  '启动': '#3b82f6', '发酵': '#eab308', '主升': '#ef4444',
  '分歧': '#f97316', '退潮': '#64748b',
};

export default function ScreenerPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [strategy, setStrategy] = useState('heat');
  const [backfilling, setBackfilling] = useState(false);

  useEffect(() => {
    fetch('/api/latest-date')
      .then(r => r.json())
      .then(d => { if (d.date) setSelectedDate(d.date); else setSelectedDate(new Date().toISOString().split('T')[0]); })
      .catch(() => setSelectedDate(new Date().toISOString().split('T')[0]));
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetch(`/api/screener?strategy=${strategy}&date=${selectedDate}`)
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, [selectedDate, strategy]);

  const changeDate = (offset) => {
    const d = new Date(selectedDate);
    d.setDate(d.getDate() + offset);
    setSelectedDate(d.toISOString().split('T')[0]);
  };

  const handleBackfill = async () => {
    setBackfilling(true);
    try {
      const res = await fetch(`/api/backfill?date=${selectedDate}`, { method: 'POST' });
      const result = await res.json();
      alert(result.message || '补采集完成');
      // 重新加载数据
      setLoading(true);
      fetch(`/api/screener?strategy=${strategy}&date=${selectedDate}`)
        .then(r => r.json())
        .then(d => { setData(d); setLoading(false); });
    } catch (e) {
      alert('补采集失败: ' + e.message);
    }
    setBackfilling(false);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>智能选股</h2>
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
          <button
            onClick={handleBackfill}
            disabled={backfilling}
            className="px-3 py-1.5 rounded-lg text-sm border transition-all"
            style={{
              borderColor: 'var(--accent-blue)',
              color: '#fff',
              background: 'var(--accent-blue)',
              opacity: backfilling ? 0.6 : 1,
            }}
          >
            {backfilling ? '采集中...' : '手动采集'}
          </button>
        </div>
      </div>

      {/* 策略选择 */}
      <div className="grid grid-cols-3 gap-3">
        {STRATEGIES.map(s => (
          <button
            key={s.key}
            onClick={() => setStrategy(s.key)}
            className="rounded-lg border p-4 text-left transition-all"
            style={{
              borderColor: strategy === s.key ? 'var(--accent-blue)' : 'var(--border-color)',
              background: strategy === s.key ? 'var(--accent-blue)' + '15' : 'var(--bg-card)',
            }}
          >
            <div className="font-medium text-sm mb-1" style={{ color: strategy === s.key ? 'var(--accent-blue)' : 'var(--text-primary)' }}>
              {s.label}
            </div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.desc}</div>
          </button>
        ))}
      </div>

      {/* 热门板块 */}
      {data?.top_sectors && data.top_sectors.length > 0 && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>热门板块 Top 5</h3>
          <div className="flex gap-3">
            {data.top_sectors.map((s, i) => (
              <div key={i} className="flex-1 rounded-lg p-3 text-center" style={{ background: 'var(--bg-surface)' }}>
                <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>#{i + 1}</div>
                <div className="text-sm font-medium mb-1" style={{ color: 'var(--text-primary)' }}>{s.name}</div>
                <div className="text-xs" style={{ color: 'var(--accent-amber)' }}>热度 {s.heat_score?.toFixed(1)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 选股结果 */}
      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>选股结果</h3>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {data?.stocks?.length || 0} 只
          </span>
        </div>

        {loading ? (
          <div className="flex items-center justify-center h-48 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : data?.stocks && data.stocks.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b" style={{ borderColor: 'var(--border-color)' }}>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>代码</th>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>名称</th>
                  <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>板块</th>
                  <th className="text-center py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>阶段</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>连板</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>主力流入(万)</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>涨跌幅</th>
                  <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>强度</th>
                  {data?.strategy !== 'heat' && (
                    <>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>评分</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>偏离%</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>RSI</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>20日涨幅%</th>
                    </>
                  )}
                </tr>
              </thead>
              <tbody>
                {data.stocks.map((stock, i) => (
                  <tr key={i} className="border-b hover:bg-opacity-50 transition-colors" style={{ borderColor: 'var(--border-light)' }}>
                    <td className="py-2 px-3 font-mono" style={{ color: 'var(--text-primary)' }}>{stock.ts_code}</td>
                    <td className="py-2 px-3" style={{ color: 'var(--text-secondary)' }}>{stock.name || '-'}</td>
                    <td className="py-2 px-3" style={{ color: 'var(--text-secondary)' }}>{stock.sector || '-'}</td>
                    <td className="py-2 px-3 text-center">
                      <span className="inline-block px-2 py-0.5 rounded text-xs font-medium" style={{
                        background: (STAGE_COLORS[stock.stage] || '#94a3b8') + '20',
                        color: STAGE_COLORS[stock.stage] || '#94a3b8',
                      }}>
                        {stock.stage || '-'}
                      </span>
                    </td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{stock.consecutive_days || 1}</td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--accent-red)' }}>
                      +{stock.main_force_inflow?.toFixed(2) || '0.00'}
                    </td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: stock.price_chg >= 0 ? 'var(--accent-green)' : 'var(--accent-red)' }}>
                      {stock.price_chg >= 0 ? '+' : ''}{stock.price_chg?.toFixed(2) || '0.00'}%
                    </td>
                    <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{stock.strength?.toFixed(0) || 0}</td>
                    {data?.strategy !== 'heat' && (
                      <>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-primary)' }}>{stock.score ?? '-'}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{stock.deviation != null ? stock.deviation.toFixed(2) : '-'}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{stock.rsi != null ? stock.rsi.toFixed(1) : '-'}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{stock['20day_gain'] != null ? stock['20day_gain'].toFixed(2) : '-'}</td>
                      </>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="flex items-center justify-center h-48 text-sm" style={{ color: 'var(--text-muted)' }}>
            暂无选股结果，请尝试手动采集数据
          </div>
        )}
      </div>
    </div>
  );
}
