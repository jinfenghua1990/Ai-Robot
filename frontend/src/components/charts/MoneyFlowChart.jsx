import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { getSectorColorHex } from '../../utils/sectorColors';

/**
 * 资金流向累计走势图（参考行情终端风格）
 * - X 轴固定为交易时间 09:30-15:00
 * - 多条折线叠加，从 0 轴出发
 * - 净流入红色系，净流出绿色系
 * - 右侧显示最新值标签
 */
export default function MoneyFlowChart({ series, timeline, height = '100%', unit = 'wan', yAxisName }) {
  const chartHeight = typeof height === 'number' ? `${height}px` : height;

  const sortedSeries = useMemo(() => {
    // 按最终值排序：净流入大的在上，净流出大的在下
    return [...series].sort((a, b) => {
      const lastA = a.data[a.data.length - 1] || 0;
      const lastB = b.data[b.data.length - 1] || 0;
      return lastB - lastA;
    });
  }, [series]);

  const option = useMemo(() => {
    if (!timeline?.length || !sortedSeries?.length) return null;

    const echartsSeries = sortedSeries.map((s) => {
      const color = getSectorColorHex(s.name);
      const lastVal = s.data[s.data.length - 1] || 0;
      const isUp = lastVal >= 0;

      return {
        name: s.name,
        type: 'line',
        smooth: 0.35,
        symbol: 'none',
        connectNulls: true,
        lineStyle: {
          width: 2.5,
          color,
        },
        itemStyle: { color },
        data: s.data,
        emphasis: { focus: 'series', lineStyle: { width: 3.5 } },
        endLabel: {
          show: true,
          formatter: unit === 'yi'
            ? `{a} ${lastVal.toFixed(1)}亿`
            : (Math.abs(lastVal) >= 10000
              ? `{a} ${(lastVal / 10000).toFixed(1)}亿`
              : `{a} ${lastVal.toFixed(0)}万`),
          color,
          fontSize: 10,
          fontWeight: 500,
          offset: [5, 0],
        },
        markLine: lastVal >= 0 ? undefined : {
          silent: true,
          symbol: 'none',
          data: [{ yAxis: 0 }],
          lineStyle: { color: '#6b7280', type: 'dashed', opacity: 0.5 },
        },
      };
    });

    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
        formatter: (params) => {
          let html = `<div style="font-weight:700;margin-bottom:6px">${params[0].axisValue}</div>`;
          const sorted = [...params].filter(p => p.value != null).sort((a, b) => b.value - a.value);
          sorted.forEach(p => {
            const color = p.value > 0 ? '#ef4444' : p.value < 0 ? '#22c55e' : '#6b7280';
            html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;font-size:12px">`;
            html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>`;
            html += `<span style="flex:1">${p.seriesName}</span>`;
            const fmtVal = unit === 'yi'
              ? `${p.value > 0 ? '+' : ''}${p.value.toFixed(1)}亿`
              : (Math.abs(p.value) >= 10000 ? `${(p.value / 10000).toFixed(1)}亿` : `${p.value.toFixed(0)}万`);
            html += `<span style="font-weight:600;color:${color}">${fmtVal}</span>`;
            html += `</div>`;
          });
          return html;
        },
      },
      legend: { show: false },
      grid: { top: 10, left: 55, right: 110, bottom: 30 },
      xAxis: {
        type: 'category',
        data: timeline,
        boundaryGap: false,
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 10,
          interval: (i) => ['09:30', '10:30', '11:30', '13:00', '14:00', '15:00'].includes(timeline[i]),
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
        splitLine: {
          show: true,
          interval: (i) => ['11:30', '15:00'].includes(timeline[i]),
          lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.6 },
        },
      },
      yAxis: {
        type: 'value',
        name: yAxisName || (unit === 'yi' ? '净流入(亿)' : '净流入(万)'),
        nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 11,
          formatter: (v) => {
            if (unit === 'yi') return `${v > 0 ? '+' : ''}${v.toFixed(1)}`;
            return Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}亿` : `${(v / 1000).toFixed(0)}k`;
          },
        },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: echartsSeries,
    };
  }, [sortedSeries, timeline, unit]);

  if (!option) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无资金流向数据
      </div>
    );
  }

  return (
    <div className="h-full">
      <ReactECharts
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: chartHeight, width: '100%' }}
        opts={{ renderer: 'canvas' }}
      />
    </div>
  );
}
