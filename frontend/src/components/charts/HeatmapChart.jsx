import ReactECharts from 'echarts-for-react';

export default function HeatmapChart({ data }) {
  if (!data || !data.values || data.values.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  const option = {
    tooltip: {
      position: 'top',
      formatter: (params) => {
        const sector = data.sectors[params.value[1]];
        const date = data.dates[params.value[0]];
        return `${sector}<br/>${date}<br/>热度: ${params.value[2].toFixed(1)}`;
      },
    },
    grid: { height: '60%', top: '5%', left: '15%', right: '5%' },
    xAxis: {
      type: 'category',
      data: data.dates,
      splitArea: { show: true },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 11 },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    yAxis: {
      type: 'category',
      data: data.sectors,
      splitArea: { show: true },
      axisLabel: { color: 'var(--text-secondary)', fontSize: 11 },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '5%',
      textStyle: { color: 'var(--text-secondary)' },
      inRange: { color: ['#22c55e', '#eab308', '#f97316', '#ef4444'] },
    },
    series: [{
      type: 'heatmap',
      data: data.values,
      label: { show: false },
      emphasis: {
        itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' },
      },
    }],
  };

  return <ReactECharts option={option} style={{ height: '500px', width: '100%' }} />;
}
