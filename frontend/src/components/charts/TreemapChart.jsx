import ReactECharts from 'echarts-for-react';

export default function TreemapChart({ data, selectedDate }) {
  if (!data || !data.values || data.values.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  // 找到选中日期在 dates 数组中的索引
  const dateIdx = data.dates.indexOf(selectedDate);
  const effectiveDateIdx = dateIdx >= 0 ? dateIdx : data.dates.length - 1;
  const currentDate = data.dates[effectiveDateIdx];
  const prevDate = effectiveDateIdx > 0 ? data.dates[effectiveDateIdx - 1] : null;

  // 提取当日各板块的热度值
  const sectorHeat = {};
  data.values.forEach(v => {
    if (v[0] === effectiveDateIdx) {
      const sectorName = data.sectors[v[1]];
      sectorHeat[sectorName] = v[2];
    }
  });

  // 提取前一日热度用于趋势对比
  const prevSectorHeat = {};
  if (prevDate) {
    data.values.forEach(v => {
      if (v[0] === effectiveDateIdx - 1) {
        const sectorName = data.sectors[v[1]];
        prevSectorHeat[sectorName] = v[2];
      }
    });
  }

  // 构建 Treemap 数据，按热度排序
  const treemapData = Object.entries(sectorHeat)
    .map(([name, heat]) => {
      const prevHeat = prevSectorHeat[name];
      const trend = prevHeat != null ? heat - prevHeat : 0;
      const trendIcon = trend > 1 ? '▲' : trend < -1 ? '▼' : '●';
      const trendColor = trend > 1 ? '#ef4444' : trend < -1 ? '#22c55e' : '#999';
      return {
        name,
        value: Math.max(heat, 1),
        heat,
        trend,
        trendIcon,
        trendColor,
        prevHeat: prevHeat != null ? prevHeat.toFixed(1) : '—',
      };
    })
    .sort((a, b) => b.heat - a.heat);

  // 颜色映射函数
  const getHeatColor = (heat) => {
    if (heat >= 70) return '#dc2626';
    if (heat >= 55) return '#f97316';
    if (heat >= 40) return '#eab308';
    if (heat >= 25) return '#84cc16';
    return '#22c55e';
  };

  const option = {
    tooltip: {
      formatter: (params) => {
        const d = params.data;
        const trendText = d.trend > 0 ? `<span style="color:#ef4444">+${d.trend.toFixed(1)}</span>` 
                       : d.trend < 0 ? `<span style="color:#22c55e">${d.trend.toFixed(1)}</span>` 
                       : '<span style="color:#999">持平</span>';
        return `<div style="font-weight:700;font-size:14px;margin-bottom:6px">${d.name}</div>` +
               `<div style="font-size:12px;color:#ccc">热度: <span style="font-weight:600;color:${getHeatColor(d.heat)}">${d.heat.toFixed(1)}</span></div>` +
               `<div style="font-size:12px;color:#ccc">前日: ${d.prevHeat}</div>` +
               `<div style="font-size:12px;color:#ccc">变化: ${trendText}</div>`;
      },
      backgroundColor: 'rgba(20, 20, 20, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.15)',
      borderWidth: 1,
      padding: [10, 14],
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);',
    },
    series: [{
      type: 'treemap',
      data: treemapData.map(d => ({
        name: d.name,
        value: d.value,
        heat: d.heat,
        trend: d.trend,
        prevHeat: d.prevHeat,
        trendIcon: d.trendIcon,
        trendColor: d.trendColor,
        itemStyle: {
          color: getHeatColor(d.heat),
          borderColor: 'rgba(0, 0, 0, 0.2)',
          borderWidth: 2,
          gapWidth: 2,
        },
      })),
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      label: {
        show: true,
        formatter: (params) => {
          const d = params.data;
          const heat = d.heat.toFixed(0);
          // 大区块显示更多信息
          if (d.value >= 40) {
            return `{name|${d.name}}\n{heat|${heat}}\n{trend|${d.trendIcon}}`;
          }
          return `{name|${d.name}}\n{heat|${heat}}`;
        },
        rich: {
          name: { fontSize: 13, fontWeight: 600, color: '#fff', lineHeight: 20 },
          heat: { fontSize: 18, fontWeight: 700, color: '#fff', lineHeight: 24 },
          trend: { fontSize: 12, color: '#fff', lineHeight: 16 },
        },
        overflow: 'truncate',
      },
      upperLabel: { show: false },
      itemStyle: {
        borderColor: 'rgba(0, 0, 0, 0.2)',
        borderWidth: 2,
        gapWidth: 2,
      },
      emphasis: {
        itemStyle: {
          borderColor: '#fff',
          borderWidth: 3,
          shadowBlur: 20,
          shadowColor: 'rgba(0, 0, 0, 0.5)',
        },
        label: {
          fontSize: 15,
        },
      },
      levels: [{
        itemStyle: {
          borderColor: 'rgba(0, 0, 0, 0.2)',
          borderWidth: 2,
          gapWidth: 2,
        },
      }],
    }],
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#dc2646'}}></span>≥70 极热</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#f97316'}}></span>55-70 高热</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#eab308'}}></span>40-55 温热</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#22c55e'}}></span>≤40 低温</span>
        </div>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {currentDate} {prevDate && <span>vs {prevDate}</span>}
        </div>
      </div>
      <ReactECharts
        option={option}
        style={{ height: '520px', width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <div className="flex items-center justify-between mt-2 px-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>共 {treemapData.length} 个板块 · 面积=热度值 · 颜色=热度等级</span>
        <span>▲升温 ▼降温 ●持平 · 悬停查看详情</span>
      </div>
    </div>
  );
}
