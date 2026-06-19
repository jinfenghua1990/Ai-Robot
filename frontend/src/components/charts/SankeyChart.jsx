import ReactECharts from 'echarts-for-react';

export default function SankeyChart({ data }) {
  if (!data || !data.nodes || data.nodes.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无轮动数据
      </div>
    );
  }

  // 计算各节点总流入/流出
  const inTotals = {};
  const outTotals = {};
  data.links.forEach(l => {
    outTotals[l.source] = (outTotals[l.source] || 0) + l.value;
    inTotals[l.target] = (inTotals[l.target] || 0) + l.value;
  });

  // 节点颜色：流出=蓝色系，流入=红色系
  const getNodeColor = (name, category) => {
    if (category === 'outflow') {
      const val = outTotals[name] || 0;
      if (val > 300) return '#1e40af';
      if (val > 150) return '#3b82f6';
      return '#60a5fa';
    } else {
      const val = inTotals[name] || 0;
      if (val > 300) return '#b91c1c';
      if (val > 150) return '#ef4444';
      return '#f87171';
    }
  };

  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (params) => {
        if (params.dataType === 'edge') {
          const pct = ((params.data.value / (outTotals[params.data.source] || 1)) * 100).toFixed(1);
          return `<div style="font-weight:600;font-size:13px">${params.data.source} → ${params.data.target}</div>` +
                 `<div style="font-size:12px;color:#ccc">资金量: <span style="font-weight:600;color:#fff">${params.data.value.toFixed(1)}万</span></div>` +
                 `<div style="font-size:12px;color:#ccc">占流出比: ${pct}%</div>`;
        }
        const node = params.data;
        const total = node.category === 'outflow'
          ? outTotals[node.name] || 0
          : inTotals[node.name] || 0;
        const type = node.category === 'outflow' ? '流出' : '流入';
        const color = node.category === 'outflow' ? '#60a5fa' : '#f87171';
        return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${node.name}</div>` +
               `<div style="font-size:12px;color:#ccc">类型: <span style="color:${color}">${type}</span></div>` +
               `<div style="font-size:12px;color:#ccc">总${type}: <span style="font-weight:600;color:#fff">${total.toFixed(1)}万</span></div>`;
      },
      backgroundColor: 'rgba(20, 20, 20, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      borderWidth: 1,
      padding: [10, 14],
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
    },
    series: [{
      type: 'sankey',
      data: data.nodes.map(n => ({
        name: n.name,
        itemStyle: { color: getNodeColor(n.name, n.category), borderColor: 'rgba(0,0,0,0.2)' },
        value: n.category === 'outflow' ? (outTotals[n.name] || 0) : (inTotals[n.name] || 0),
      })),
      links: data.links.map(l => ({
        source: l.source,
        target: l.target,
        value: l.value,
        lineStyle: {
          color: 'gradient',
          curveness: 0.5,
          opacity: 0.5,
        },
      })),
      orient: 'horizontal',
      label: {
        color: 'var(--text-primary)',
        fontSize: 12,
        fontWeight: 600,
        formatter: (params) => {
          const node = params.data;
          const total = node.category === 'outflow'
            ? outTotals[node.name] || 0
            : inTotals[node.name] || 0;
          return `${node.name}\n${total.toFixed(0)}万`;
        },
      },
      lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.5 },
      emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.9 } },
      nodeGap: 12,
      nodeWidth: 20,
      layoutIterations: 32,
    }],
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#3b82f6'}}></span>资金流出板块</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#ef4444'}}></span>资金流入板块</span>
        </div>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          连线粗细=资金量 · 悬停查看详情
        </div>
      </div>
      <ReactECharts option={option} style={{ height: '500px', width: '100%' }} opts={{ renderer: 'canvas' }} />
    </div>
  );
}
