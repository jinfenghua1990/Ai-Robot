import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { getSectorColorHex } from '../../utils/sectorColors';

// A股颜色习惯：红色=流入/上涨，绿色=流出/下跌
const COLOR_INFLOW = '#ef4444';   // 红色 - 流入
const COLOR_OUTFLOW = '#22c55e';  // 绿色 - 流出

export default function SankeyChart({ data, onNodeClick, selectedSector, height = '500px' }) {
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
  const nodeCategory = {}; // name → category 映射
  data.nodes.forEach(n => {
    nodeCategory[n.name] = n.category;
  });
  data.links.forEach(l => {
    outTotals[l.source] = (outTotals[l.source] || 0) + l.value;
    inTotals[l.target] = (inTotals[l.target] || 0) + l.value;
  });

  // 节点颜色：同一板块固定色相，流入/流出用同一色相的明暗区分
  const getNodeColor = (name) => {
    const category = nodeCategory[name];
    return getSectorColorHex(name, category === 'outflow' ? 'outflow' : 'inflow');
  };

  // 获取节点总额
  const getNodeTotal = (name) => {
    const category = nodeCategory[name];
    return category === 'outflow' ? (outTotals[name] || 0) : (inTotals[name] || 0);
  };

  const option = {
    tooltip: {
      ...tooltipStyle,
      trigger: 'item',
      formatter: (params) => {
        if (params.dataType === 'edge') {
          const pct = ((params.data.value / (outTotals[params.data.source] || 1)) * 100).toFixed(1);
          return `<div style="font-weight:600;font-size:13px">${params.data.source} → ${params.data.target}</div>` +
                 `<div style="font-size:12px;color:#ccc">资金量：<span style="font-weight:600;color:#fff">${params.data.value.toFixed(1)}万</span></div>` +
                 `<div style="font-size:12px;color:#ccc">占流出比：${pct}%</div>`;
        }
        const nodeName = params.data.name;
        const category = nodeCategory[nodeName];
        const total = getNodeTotal(nodeName);
        const type = category === 'outflow' ? '流出' : '流入';
        const color = getSectorColorHex(nodeName, category === 'outflow' ? 'outflow' : 'inflow');
        return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${nodeName}</div>` +
               `<div style="font-size:12px;color:#ccc">类型：<span style="color:${color}">${type}</span></div>` +
               `<div style="font-size:12px;color:#ccc">总${type}：<span style="font-weight:600;color:#fff">${total.toFixed(1)}万</span></div>`;
      },
    },
    series: [{
      type: 'sankey',
      data: data.nodes.map(n => {
        const isSelected = selectedSector && n.name === selectedSector;
        const dimmed = selectedSector && !isSelected;
        return {
          name: n.name,
          itemStyle: {
            color: getNodeColor(n.name),
            borderColor: isSelected ? '#fff' : 'rgba(0,0,0,0.2)',
            borderWidth: isSelected ? 2 : 0,
            opacity: dimmed ? 0.25 : 1,
          },
          value: getNodeTotal(n.name),
        };
      }),
      links: data.links.map(l => {
        const involved = selectedSector && (l.source === selectedSector || l.target === selectedSector);
        const dimmed = selectedSector && !involved;
        return {
          source: l.source,
          target: l.target,
          value: l.value,
          lineStyle: {
            color: 'gradient',
            curveness: 0.5,
            opacity: dimmed ? 0.05 : (involved ? 0.5 : 0.25),
          },
        };
      }),
      orient: 'horizontal',
      label: {
        color: 'var(--text-primary)',
        fontSize: 11,
        fontWeight: 500,
        formatter: (params) => {
          const name = params.data.name;
          const total = getNodeTotal(name);
          return `${name}\n${total.toFixed(0)}万`;
        },
      },
      lineStyle: { color: 'gradient', curveness: 0.5, opacity: 0.25 },
      emphasis: { focus: 'adjacency', lineStyle: { opacity: 0.7 } },
      nodeGap: 16,
      nodeWidth: 10,
      layoutIterations: 32,
    }],
  };

  const onChartClick = (params) => {
    if (params.dataType === 'node' && onNodeClick) {
      onNodeClick(params.data.name);
    }
  };

  const onEvents = { click: onChartClick };

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-1 px-1">
        <div className="flex items-center gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded" style={{background: COLOR_OUTFLOW}}></span>流出</span>
          <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded" style={{background: COLOR_INFLOW}}></span>流入</span>
        </div>
        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          悬停详情{onNodeClick ? ' · 点击钻取' : ''}
        </div>
      </div>
      <div className="flex-1 min-h-0">
        <ReactECharts echarts={echarts} option={option} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} onEvents={onEvents} />
      </div>
    </div>
  );
}
