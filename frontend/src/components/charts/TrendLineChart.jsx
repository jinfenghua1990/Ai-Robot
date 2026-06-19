import ReactECharts from 'echarts-for-react';

export default function TrendLineChart({ data, topSectors }) {
  if (!data?.dates || !topSectors || topSectors.length === 0) {
    return null;
  }

  // 颜色池
  const colors = [
    '#ef4444', '#f97316', '#eab308', '#84cc16', '#22c55e',
    '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899', '#f43f5e',
  ];

  // 为每个 Top10 板块构建一条趋势线
  const series = topSectors.slice(0, 10).map((s, i) => {
    const sectorIdx = data.sectors.indexOf(s.sector);
    const trendData = data.dates.map((_, dateIdx) => {
      const val = data.values.find(v => v[0] === dateIdx && v[1] === sectorIdx);
      return val ? parseFloat(val[2].toFixed(1)) : null;
    });
    return {
      name: s.sector,
      type: 'line',
      smooth: true,
      symbol: 'circle',
      symbolSize: 6,
      lineStyle: { width: 2.5, color: colors[i] },
      itemStyle: { color: colors[i] },
      data: trendData,
      emphasis: {
        focus: 'series',
        lineStyle: { width: 4 },
        symbolSize: 10,
      },
    };
  });

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(20, 20, 20, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      borderWidth: 1,
      padding: [10, 14],
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        let html = `<div style="font-weight:700;margin-bottom:6px">${params[0].axisValue}</div>`;
        const sorted = [...params].sort((a, b) => b.value - a.value);
        sorted.forEach(p => {
          if (p.value == null) return;
          const heat = p.value;
          const color = heat > 70 ? '#ef4444' : heat > 55 ? '#f97316' : heat > 40 ? '#eab308' : '#22c55e';
          html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">`;
          html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>`;
          html += `<span style="flex:1">${p.seriesName}</span>`;
          html += `<span style="font-weight:600;color:${color}">${heat.toFixed(1)}</span>`;
          html += `</div>`;
        });
        return html;
      },
    },
    legend: {
      type: 'scroll',
      top: 0,
      textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
      pageTextStyle: { color: 'var(--text-muted)' },
      pageItemSize: 12,
    },
    grid: {
      top: 40,
      left: 40,
      right: 20,
      bottom: 30,
    },
    xAxis: {
      type: 'category',
      data: data.dates,
      boundaryGap: false,
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 11,
        formatter: (val) => val.slice(5),
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value',
      min: 0,
      max: 100,
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 11,
      },
      splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    series,
  };

  return (
    <div>
      <ReactECharts
        option={option}
        style={{ height: '300px', width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
