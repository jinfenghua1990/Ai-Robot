import { useState } from 'react';
import ReactECharts from 'echarts-for-react';

export default function PolarChart({ data, selectedDate }) {
  const [viewMode, setViewMode] = useState('heat'); // 'heat' | 'change'

  if (!data || !data.values || data.values.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  const dateIdx = data.dates.indexOf(selectedDate);
  const effectiveDateIdx = dateIdx >= 0 ? dateIdx : data.dates.length - 1;
  const currentDate = data.dates[effectiveDateIdx];
  const prevDate = effectiveDateIdx > 0 ? data.dates[effectiveDateIdx - 1] : null;

  // 提取当日各板块热度
  const sectorHeat = {};
  data.values.forEach(v => {
    if (v[0] === effectiveDateIdx) {
      const name = data.sectors[v[1]];
      sectorHeat[name] = v[2];
    }
  });

  const prevSectorHeat = {};
  if (prevDate) {
    data.values.forEach(v => {
      if (v[0] === effectiveDateIdx - 1) {
        const name = data.sectors[v[1]];
        prevSectorHeat[name] = v[2];
      }
    });
  }

  const allSectors = Object.entries(sectorHeat)
    .map(([name, heat]) => {
      const prev = prevSectorHeat[name];
      const trend = prev != null ? heat - prev : 0;
      return { name, heat, prev, trend };
    });

  // 热度模式：按热度排序
  // 变化模式：按变化绝对值排序（最大变化在前）
  // 只显示 Top 20，避免过多板块导致视觉混乱
  const sorted = (viewMode === 'heat'
    ? [...allSectors].sort((a, b) => b.heat - a.heat)
    : [...allSectors].sort((a, b) => Math.abs(b.trend) - Math.abs(a.trend))
  ).slice(0, 20);

  const sectorNames = sorted.map(s => s.name);

  // 热度模式颜色
  const getHeatColor = (heat) => {
    if (heat >= 70) return '#dc2626';
    if (heat >= 55) return '#f97316';
    if (heat >= 40) return '#eab308';
    if (heat >= 25) return '#84cc16';
    return '#22c55e';
  };

  // 变化模式：红=升温，绿=降温，灰=持平
  const getChangeColor = (trend) => {
    if (trend > 5) return '#dc2626';
    if (trend > 1) return '#f97316';
    if (trend < -5) return '#16a34a';
    if (trend < -1) return '#22c55e';
    return '#6b7280';
  };

  let option;

  if (viewMode === 'heat') {
    // 热度值模式
    const heatValues = sorted.map(s => Math.max(s.heat, 0.5));
    const itemColors = sorted.map(s => getHeatColor(s.heat));

    option = {
      tooltip: {
        formatter: (params) => {
          const d = sorted[params.dataIndex];
          const trendText = d.trend > 1
            ? `<span style="color:#ef4444">▲ +${d.trend.toFixed(1)}</span>`
            : d.trend < -1
            ? `<span style="color:#22c55e">▼ ${d.trend.toFixed(1)}</span>`
            : '<span style="color:#999">● 持平</span>';
          return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${d.name}</div>` +
                 `<div style="font-size:12px;color:#ccc">热度: <span style="font-weight:600;color:${getHeatColor(d.heat)}">${d.heat.toFixed(1)}</span></div>` +
                 `<div style="font-size:12px;color:#ccc">前日: ${d.prev != null ? d.prev.toFixed(1) : '—'}</div>` +
                 `<div style="font-size:12px;color:#ccc">变化: ${trendText}</div>`;
        },
        backgroundColor: 'rgba(20, 20, 20, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.15)',
        borderWidth: 1,
        padding: [10, 14],
        extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
      },
      polar: { center: ['50%', '52%'], radius: '78%' },
      angleAxis: {
        type: 'category',
        data: sectorNames,
        startAngle: 90,
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 11,
          formatter: (val) => val.length > 4 ? val.slice(0, 4) + '..' : val,
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        splitLine: { show: false },
      },
      radiusAxis: {
        min: 0, max: 100,
        axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
      },
      series: [{
        type: 'bar',
        data: heatValues.map((v, i) => ({
          value: v,
          itemStyle: { color: itemColors[i], borderRadius: [4, 4, 0, 0] },
        })),
        coordinateSystem: 'polar',
        barWidth: '90%',
        emphasis: {
          itemStyle: { shadowBlur: 20, shadowColor: 'rgba(0,0,0,0.5)', borderColor: '#fff', borderWidth: 2 },
        },
      }],
    };
  } else {
    // 变化趋势模式
    const changeValues = sorted.map(s => s.trend);
    const itemColors = sorted.map(s => getChangeColor(s.trend));

    option = {
      tooltip: {
        formatter: (params) => {
          const d = sorted[params.dataIndex];
          const trendColor = d.trend > 0 ? '#ef4444' : d.trend < 0 ? '#22c55e' : '#999';
          const trendIcon = d.trend > 0 ? '▲' : d.trend < 0 ? '▼' : '●';
          return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${d.name}</div>` +
                 `<div style="font-size:12px;color:#ccc">变化: <span style="font-weight:600;color:${trendColor}">${trendIcon} ${d.trend > 0 ? '+' : ''}${d.trend.toFixed(1)}</span></div>` +
                 `<div style="font-size:12px;color:#ccc">当日热度: ${d.heat.toFixed(1)}</div>` +
                 `<div style="font-size:12px;color:#ccc">前日热度: ${d.prev != null ? d.prev.toFixed(1) : '—'}</div>`;
        },
        backgroundColor: 'rgba(20, 20, 20, 0.95)',
        borderColor: 'rgba(255, 255, 255, 0.15)',
        borderWidth: 1,
        padding: [10, 14],
        extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
      },
      polar: { center: ['50%', '52%'], radius: '78%' },
      angleAxis: {
        type: 'category',
        data: sectorNames,
        startAngle: 90,
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 11,
          formatter: (val) => val.length > 4 ? val.slice(0, 4) + '..' : val,
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        splitLine: { show: false },
      },
      radiusAxis: {
        axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
        axisLine: { show: false },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
      },
      series: [{
        type: 'bar',
        data: changeValues.map((v, i) => ({
          value: v,
          itemStyle: { color: itemColors[i], borderRadius: v >= 0 ? [4, 4, 0, 0] : [0, 0, 4, 4] },
        })),
        coordinateSystem: 'polar',
        barWidth: '90%',
        emphasis: {
          itemStyle: { shadowBlur: 20, shadowColor: 'rgba(0,0,0,0.5)', borderColor: '#fff', borderWidth: 2 },
        },
      }],
    };
  }

  const legendItems = viewMode === 'heat'
    ? [
        { color: '#dc2626', label: '≥70 极热' },
        { color: '#f97316', label: '55-70 高热' },
        { color: '#eab308', label: '40-55 温热' },
        { color: '#22c55e', label: '≤40 低温' },
      ]
    : [
        { color: '#dc2626', label: '▲大幅升温' },
        { color: '#f97316', label: '▲小幅升温' },
        { color: '#6b7280', label: '●基本持平' },
        { color: '#22c55e', label: '▼小幅降温' },
        { color: '#16a34a', label: '▼大幅降温' },
      ];

  return (
    <div>
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          {legendItems.map((item, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="inline-block w-3 h-3 rounded" style={{ background: item.color }}></span>
              {item.label}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-2">
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {currentDate} {prevDate && <span>vs {prevDate}</span>}
          </div>
          {/* 模式切换 */}
          <button
            onClick={() => setViewMode(viewMode === 'heat' ? 'change' : 'heat')}
            className="px-3 py-1 rounded-lg text-xs font-medium transition-all"
            style={{
              background: 'var(--accent-color, #3b82f6)',
              color: '#fff',
              border: 'none',
              cursor: 'pointer',
            }}
          >
            {viewMode === 'heat' ? '🔄 切换到变化趋势' : '🔄 切换到热度值'}
          </button>
        </div>
      </div>
      <ReactECharts
        option={option}
        style={{ height: '520px', width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <div className="flex items-center justify-between mt-2 px-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>
          共 {sorted.length} 个板块 ·{' '}
          {viewMode === 'heat'
            ? '扇形长度=热度值 · 颜色=热度等级'
            : '扇形长度=变化量 · 红=升温 绿=降温 · 按|变化量|排序'}
        </span>
        <span>悬停查看详情</span>
      </div>
    </div>
  );
}
