import ReactECharts from 'echarts-for-react';

export default function SankeyChart({ data }) {
  if (!data || !data.nodes || data.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无轮动数据
      </div>
    );
  }

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}<br/>资金量: ${params.data.value.toFixed(2)}万`;
        }
        return params.data.name;
      },
    },
    series: [{
      type: 'sankey',
      data: data.nodes.map(n => ({ name: n.name, itemStyle: { color: n.category === 'outflow' ? '#ef4444' : '#22c55e' } })),
      links: data.links,
      orient: 'horizontal',
      label: {
        color: 'var(--text-primary)',
        fontSize: 12,
      },
      lineStyle: {
        color: 'gradient',
        curveness: 0.5,
        opacity: 0.6,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { opacity: 0.9 },
      },
    }],
  };

  return <ReactECharts option={option} style={{ height: '500px', width: '100%' }} />;
}
