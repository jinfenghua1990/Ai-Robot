import ReactECharts from 'echarts-for-react';

export default function HeatmapChart({ data }) {
  if (!data || !data.values || data.values.length === 0) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  const sectorCount = data.sectors.length;
  const dateCount = data.dates.length;

  // 动态高度：每个板块行 36px + 顶部日期轴 60px + 底部色条 80px
  const chartHeight = Math.max(400, sectorCount * 36 + 140);

  // 计算每个板块的最大热度值，用于排名标注
  const sectorMaxHeat = {};
  data.values.forEach(v => {
    const idx = v[1];
    const name = data.sectors[idx];
    if (!sectorMaxHeat[name] || v[2] > sectorMaxHeat[name]) {
      sectorMaxHeat[name] = v[2];
    }
  });

  // 按热度排序的板块排名
  const rankedSectors = data.sectors
    .map((s, i) => ({ name: s, idx: i, maxHeat: sectorMaxHeat[s] || 0 }))
    .sort((a, b) => b.maxHeat - a.maxHeat);
  const rankMap = {};
  rankedSectors.forEach((s, i) => { rankMap[s.name] = i + 1; });

  // Y轴标签带排名前缀
  const yAxisData = data.sectors.map(s => `#${rankMap[s]} ${s}`);

  const option = {
    tooltip: {
      position: 'top',
      formatter: (params) => {
        const sector = data.sectors[params.value[1]];
        const date = data.dates[params.value[0]];
        const heat = params.value[2].toFixed(1);
        const rank = rankMap[sector];
        return `<div style="font-weight:600;font-size:13px;margin-bottom:4px">#${rank} ${sector}</div>` +
               `<div style="font-size:12px;color:#999">日期: ${date}</div>` +
               `<div style="font-size:12px;color:#999">热度: <span style="font-weight:600;color:${heat > 70 ? '#ef4444' : heat > 40 ? '#eab308' : '#22c55e'}">${heat}</span></div>`;
      },
      backgroundColor: 'rgba(30, 30, 30, 0.95)',
      borderColor: 'rgba(255, 255, 255, 0.1)',
      borderWidth: 1,
      padding: [8, 12],
      extraCssText: 'border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);',
    },
    grid: {
      height: `${sectorCount * 36}px`,
      top: 50,
      left: 160,
      right: 30,
      bottom: 80,
    },
    xAxis: {
      type: 'category',
      data: data.dates,
      splitArea: { show: true },
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 12,
        fontWeight: 500,
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'category',
      data: yAxisData,
      splitArea: { show: true },
      axisLabel: {
        color: 'var(--text-primary)',
        fontSize: 12,
        fontWeight: 600,
        width: 140,
        overflow: 'truncate',
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
      axisTick: { show: false },
      inverse: true,
    },
    visualMap: {
      min: 0,
      max: 100,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 10,
      textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
      inRange: {
        color: [
          '#1a3a2e', '#22c55e',
          '#1a3a1a', '#eab308',
          '#3a2a0a', '#f97316',
          '#3a0a0a', '#ef4444',
        ],
      },
    },
    series: [{
      type: 'heatmap',
      data: data.values,
      label: {
        show: true,
        formatter: (params) => {
          const v = params.value[2];
          // 只在热度>0时显示数值
          if (v < 0.1) return '';
          return v.toFixed(0);
        },
        color: '#fff',
        fontSize: 11,
        fontWeight: 600,
        textShadow: '0 1px 2px rgba(0,0,0,0.5)',
      },
      emphasis: {
        itemStyle: {
          shadowBlur: 15,
          shadowColor: 'rgba(0, 0, 0, 0.6)',
          borderColor: '#fff',
          borderWidth: 2,
        },
        label: {
          fontSize: 14,
          fontWeight: 700,
        },
      },
      itemStyle: {
        borderColor: 'rgba(0, 0, 0, 0.15)',
        borderWidth: 1,
        borderRadius: 3,
      },
    }],
  };

  return (
    <div>
      <ReactECharts
        option={option}
        style={{ height: `${chartHeight}px`, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
      <div className="flex items-center justify-between mt-2 px-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        <span>共 {sectorCount} 个板块 × {dateCount} 个交易日</span>
        <span>悬停查看详情 · 颜色越红热度越高</span>
      </div>
    </div>
  );
}
