import { useState, useEffect } from 'react';
import ReactECharts from 'echarts-for-react';
import SankeyChart from '../components/charts/SankeyChart';

export default function RotationPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedDate, setSelectedDate] = useState('');
  const [lookbackDays, setLookbackDays] = useState(5);

  useEffect(() => {
    fetch('/api/latest-date')
      .then(r => r.json())
      .then(d => { if (d.date) setSelectedDate(d.date); else setSelectedDate(new Date().toISOString().split('T')[0]); })
      .catch(() => setSelectedDate(new Date().toISOString().split('T')[0]));
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

  // 计算汇总数据
  const inTotals = {};
  const outTotals = {};
  if (data?.links) {
    data.links.forEach(l => {
      outTotals[l.source] = (outTotals[l.source] || 0) + l.value;
      inTotals[l.target] = (inTotals[l.target] || 0) + l.value;
    });
  }
  const totalInflow = Object.values(inTotals).reduce((a, b) => a + b, 0);
  const totalOutflow = Object.values(outTotals).reduce((a, b) => a + b, 0);
  const netFlow = totalInflow - totalOutflow;
  const topInflow = Object.entries(inTotals).sort((a, b) => b[1] - a[1])[0];
  const topOutflow = Object.entries(outTotals).sort((a, b) => b[1] - a[1])[0];

  // 流入流出对比柱状图
  const inflowSorted = Object.entries(inTotals).sort((a, b) => b[1] - a[1]).slice(0, 10);
  const outflowSorted = Object.entries(outTotals).sort((a, b) => b[1] - a[1]).slice(0, 10);

  const barOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      backgroundColor: 'rgba(20, 20, 20, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      borderWidth: 1,
      padding: [10, 14],
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        let html = '';
        params.forEach(p => {
          html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">`;
          html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>`;
          html += `<span>${p.name}</span>`;
          html += `<span style="font-weight:600;margin-left:auto">${p.value.toFixed(1)}万</span>`;
          html += `</div>`;
        });
        return html;
      },
    },
    grid: { left: 80, right: 80, top: 10, bottom: 10 },
    xAxis: { type: 'value', axisLabel: { color: 'var(--text-muted)', fontSize: 10 }, splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } } },
    yAxis: [
      {
        type: 'category',
        inverse: true,
        data: outflowSorted.map(s => s[0]),
        axisLabel: { color: '#60a5fa', fontSize: 11, fontWeight: 600 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      {
        type: 'category',
        data: inflowSorted.map(s => s[0]),
        axisLabel: { color: '#f87171', fontSize: 11, fontWeight: 600 },
        axisLine: { show: false },
        axisTick: { show: false },
      },
    ],
    series: [
      {
        name: '流出',
        type: 'bar',
        data: outflowSorted.map(s => s[1]),
        itemStyle: { color: '#3b82f6', borderRadius: [0, 4, 4, 0] },
        barWidth: '40%',
      },
      {
        name: '流入',
        type: 'bar',
        yAxisIndex: 1,
        data: inflowSorted.map(s => s[1]),
        itemStyle: { color: '#ef4444', borderRadius: [4, 0, 0, 4] },
        barWidth: '40%',
      },
    ],
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>板块轮动图</h2>
        <div className="flex items-center gap-3">
          <button onClick={() => changeDate(-1)} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>前一天</button>
          <input type="date" value={selectedDate} onChange={(e) => setSelectedDate(e.target.value)} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
          <button onClick={() => changeDate(1)} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>后一天</button>
          <select value={lookbackDays} onChange={(e) => setLookbackDays(Number(e.target.value))} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
            <option value={3}>近3天</option>
            <option value={5}>近5天</option>
            <option value={10}>近10天</option>
          </select>
        </div>
      </div>

      {/* 汇总卡片 */}
      {!loading && data && (
        <div className="grid grid-cols-4 gap-3">
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>总流入</div>
            <div className="text-lg font-bold" style={{ color: '#ef4444' }}>{totalInflow.toFixed(0)}万</div>
          </div>
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>总流出</div>
            <div className="text-lg font-bold" style={{ color: '#3b82f6' }}>{totalOutflow.toFixed(0)}万</div>
          </div>
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>净轮动</div>
            <div className="text-lg font-bold" style={{ color: netFlow > 0 ? '#ef4444' : '#3b82f6' }}>{netFlow > 0 ? '+' : ''}{netFlow.toFixed(0)}万</div>
          </div>
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>最强流入</div>
            <div className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{topInflow ? topInflow[0] : '—'}</div>
            <div className="text-xs" style={{ color: '#ef4444' }}>{topInflow ? `${topInflow[1].toFixed(0)}万` : ''}</div>
          </div>
        </div>
      )}

      {/* Sankey 图 */}
      <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : (
          <SankeyChart data={data} />
        )}
      </div>

      {/* 流入流出对比图 */}
      {!loading && data && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>
            流入 vs 流出 Top 10 对比
          </h3>
          <div className="flex items-center gap-3 mb-2 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#3b82f6'}}></span>流出板块（左）</span>
            <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#ef4444'}}></span>流入板块（右）</span>
          </div>
          <ReactECharts option={barOption} style={{ height: '320px', width: '100%' }} opts={{ renderer: 'canvas' }} />
        </div>
      )}

      {/* 轮动信号 */}
      {data?.signals && data.signals.length > 0 && (
        <div className="grid grid-cols-2 gap-3">
          {data.signals.map((signal, i) => {
            const isInflow = signal.includes('流入');
            return (
              <div key={i} className="rounded-xl border p-4" style={{ borderColor: isInflow ? 'rgba(239,68,68,0.3)' : 'rgba(59,130,246,0.3)', background: 'var(--bg-card)' }}>
                <div className="flex items-center gap-2 mb-2">
                  <span className="text-lg">{isInflow ? '🔥' : '❄️'}</span>
                  <span className="text-sm font-medium" style={{ color: isInflow ? '#ef4444' : '#3b82f6' }}>
                    {isInflow ? '资金流入板块' : '资金流出板块'}
                  </span>
                </div>
                <div className="text-sm" style={{ color: 'var(--text-primary)' }}>
                  {signal.replace(/资金(流入|流出):\s*/, '').split(', ').map((sector, j) => (
                    <span key={j} className="inline-block px-2 py-1 rounded mr-1 mb-1 text-xs font-medium"
                      style={{ background: isInflow ? 'rgba(239,68,68,0.15)' : 'rgba(59,130,246,0.15)', color: isInflow ? '#f87171' : '#60a5fa' }}>
                      {sector}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
