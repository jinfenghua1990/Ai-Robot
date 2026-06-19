import ReactECharts from 'echarts-for-react';

const CATEGORY_STYLES = {
  source: { color: '#6366f1', size: 40 },
  sector: { color: '#3b82f6', size: 30 },
  leader: { color: '#ef4444', size: 25 },
};

export default function FlowGraph({ data }) {
  if (!data || !data.nodes || data.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无资金流数据
      </div>
    );
  }

  const nodes = data.nodes.map(n => ({
    name: n.name,
    symbolSize: CATEGORY_STYLES[n.category]?.size || 20,
    itemStyle: { color: CATEGORY_STYLES[n.category]?.color || '#94a3b8' },
    label: { show: true, formatter: n.label || n.name, color: 'var(--text-primary)', fontSize: 11 },
    category: n.category,
  }));

  const links = data.links.map(l => ({
    source: l.source,
    target: l.target,
    value: l.value,
    lineStyle: {
      width: Math.max(1, Math.min(10, l.value / 1000)),
      opacity: 0.6,
      curveness: 0.3,
    },
  }));

  const option = {
    tooltip: {
      formatter: (params) => {
        if (params.dataType === 'edge') {
          return `${params.data.source} → ${params.data.target}<br/>资金量: ${params.data.value.toFixed(2)}万`;
        }
        return params.data.name;
      },
    },
    series: [{
      type: 'graph',
      layout: 'force',
      data: nodes,
      links: links,
      roam: true,
      force: {
        repulsion: 200,
        edgeLength: [80, 200],
        gravity: 0.1,
      },
      emphasis: {
        focus: 'adjacency',
        lineStyle: { width: 4, opacity: 1 },
      },
      lineStyle: { color: 'var(--border-color)' },
    }],
  };

  return <ReactECharts option={option} style={{ height: '500px', width: '100%' }} />;
}
