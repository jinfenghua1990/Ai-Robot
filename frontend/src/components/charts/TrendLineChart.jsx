import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { getSectorColorHex } from '../../utils/sectorColors';

export default function TrendLineChart({ data, topSectors, selectedSector, onSectorClick, height = 240 }) {

  // 预构建索引 Map，避免循环内 find 的 O(n²) 查找
  const series = useMemo(() => {
    if (!data?.dates || !topSectors || topSectors.length === 0) return [];

    // key = `${dateIdx}_${sectorIdx}` → value
    const valueMap = new Map();
    for (const v of data.values) {
      valueMap.set(`${v[0]}_${v[1]}`, v[2]);
    }

    return topSectors.slice(0, 10).map((s, i) => {
      const sectorIdx = data.sectors.indexOf(s.sector);
      const trendData = data.dates.map((_, dateIdx) => {
        const val = valueMap.get(`${dateIdx}_${sectorIdx}`);
        return val != null ? parseFloat(val.toFixed(1)) : null;
      });
      const isSelected = selectedSector && selectedSector === s.sector;
      const dimmed = selectedSector && !isSelected;
      const color = getSectorColorHex(s.sector);
      return {
        name: s.sector,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: isSelected ? 10 : 6,
        connectNulls: true,
        lineStyle: { width: isSelected ? 4 : 2.5, color, opacity: dimmed ? 0.25 : 1 },
        itemStyle: { color, opacity: dimmed ? 0.25 : 1 },
        data: trendData,
        emphasis: {
          focus: 'series',
          lineStyle: { width: 4 },
          symbolSize: 10,
        },
      };
    });
  }, [data, topSectors, selectedSector]);

  const option = useMemo(() => {
    if (!data?.dates || !topSectors || topSectors.length === 0) return null;

    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
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
          fontSize: 10,
          rotate: 35,
          interval: 'auto',
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
  }, [data, topSectors, series]);

  if (!option) return null;

  const onEvents = onSectorClick ? {
    click: (params) => {
      if (params.componentType === 'series') onSectorClick(params.seriesName);
    },
  } : undefined;

  return (
    <div className="h-full">
      <ReactECharts
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: typeof height === 'number' ? `${height}px` : height, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
    </div>
  );
}
