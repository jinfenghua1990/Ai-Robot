import ReactECharts from 'echarts-for-react';

export default function PolarChart({ data, selectedDate }) {
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

  // 按热度排序
  const sorted = Object.entries(sectorHeat)
    .map(([name, heat]) => {
      const prev = prevSectorHeat[name];
      const trend = prev != null ? heat - prev : 0;
      return { name, heat, prev, trend };
    })
    .sort((a, b) => b.heat - a.heat);

  const sectorNames = sorted.map(s => s.name);
  const heatValues = sorted.map(s => Math.max(s.heat, 0.5));

  // 颜色映射
  const getHeatColor = (heat) => {
    if (heat >= 70) return '#dc2626';
    if (heat >= 55) return '#f97316';
    if (heat >= 40) return '#eab308';
    if (heat >= 25) return '#84cc16';
    return '#22c55e';
  };

  const itemColors = sorted.map(s => getHeatColor(s.heat));

  const option = {
    tooltip: {
      formatter: (params) => {
        const idx = params.dataIndex;
        const d = sorted[idx];
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
    polar: {
      center: ['50%', '52%'],
      radius: '78%',
    },
    angleAxis: {
      type: 'category',
      data: sectorNames,
      startAngle: 90,
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 11,
        formatter: (val) => {
          // 长名称截断
          return val.length > 4 ? val.slice(0, 4) + '..' : val;
        },
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
      splitLine: { show: false },
    },
    radiusAxis: {
      min: 0,
      max: 100,
      axisLabel: {
        color: 'var(--text-muted)',
        fontSize: 10,
      },
      axisLine: { show: false },
      splitLine: {
        lineStyle: {
          color: 'var(--border-color)',
          type: 'dashed',
          opacity: 0.3,
        },
      },
    },
    series: [{
      type: 'bar',
      data: heatValues.map((v, i) => ({
        value: v,
        itemStyle: {
          color: itemColors[i],
          borderRadius: [4, 4, 0, 0],
        },
      })),
      coordinateSystem: 'polar',
      barWidth: '90%',
      emphasis: {
        itemStyle: {
          shadowBlur: 20,
          shadowColor: 'rgba(0, 0, 0, 0.5)',
          borderColor: '#fff',
          borderWidth: 2,
        },
      },
    }],
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-3 px-1">
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-3 rounded" style={{background:'#dc2626'}}></span>≥70 极热</span>
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
        <span>共 {sorted.length} 个板块 · 扇形长度=热度值 · 颜色=热度等级</span>
        <span>▲升温 ▼降温 ●持平 · 悬停查看详情</span>
      </div>
    </div>
  );
}
