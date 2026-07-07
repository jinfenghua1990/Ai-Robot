import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';

/**
 * 分类折线图：X 轴为分类（如板块名），Y 轴为数值，单条折线连接各点。
 * 统一参考 Top 10 板块热度趋势的视觉样式。
 */
export default function CategoryLineChart({
  categories = [],
  values = [],
  selectedItem = null,
  onItemClick,
  color = '#3b82f6',
  positiveColor = '#ef4444',
  negativeColor = '#22c55e',
  zeroColor = '#6b7280',
  height = 240,
  yAxisName = '',
  xAxisName = '',
  valueFormatter = (v) => String(v),
  tooltipFormatter,
  horizontal = false,
}) {
  const option = useMemo(() => {
    if (!categories.length || !values.length) return null;

    const categoryAxis = {
      type: 'category',
      data: categories,
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 10,
        interval: 0,
        formatter: (val) => val.length > 5 ? val.slice(0, 4) + '…' : val,
      },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
      axisTick: { show: false },
    };

    const valueAxis = {
      type: 'value',
      nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
      axisLabel: {
        color: 'var(--text-secondary)',
        fontSize: 10,
        formatter: valueFormatter,
      },
      splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
      axisLine: { show: false },
      axisTick: { show: false },
    };

    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
        formatter: tooltipFormatter || ((params) => {
          const p = params[0];
          return `<div style="font-weight:700;font-size:13px;margin-bottom:2px">${p.name}</div>` +
                 `<div style="font-size:12px;color:#ccc">数值：<span style="color:${p.color};font-weight:600">${valueFormatter(p.value)}</span></div>`;
        }),
      },
      grid: {
        top: 40,
        left: horizontal ? 70 : 50,
        right: 20,
        bottom: 45,
      },
      xAxis: horizontal
        ? { ...valueAxis, name: xAxisName }
        : { ...categoryAxis, boundaryGap: false, axisLabel: { ...categoryAxis.axisLabel, rotate: 35 } },
      yAxis: horizontal
        ? { ...categoryAxis }
        : { ...valueAxis, name: yAxisName },
      series: [{
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: (value, params) => selectedItem === params.name ? 12 : 8,
        lineStyle: { width: 3, color },
        itemStyle: {
          color: (params) => {
            const v = params.value;
            return v > 0 ? positiveColor : v < 0 ? negativeColor : zeroColor;
          },
          opacity: (params) => selectedItem && selectedItem !== params.name ? 0.3 : 1,
          borderColor: (params) => selectedItem === params.name ? '#fff' : 'transparent',
          borderWidth: (params) => selectedItem === params.name ? 2 : 0,
        },
        emphasis: {
          focus: 'series',
          symbolSize: 12,
          lineStyle: { width: 4 },
        },
        data: values,
        markLine: {
          silent: true,
          symbol: 'none',
          lineStyle: { color: 'var(--text-muted)', type: 'dashed', width: 1 },
          data: [horizontal ? { xAxis: 0 } : { yAxis: 0 }],
          label: { show: false },
        },
      }],
    };
  }, [categories, values, selectedItem, color, positiveColor, negativeColor, zeroColor, yAxisName, xAxisName, valueFormatter, tooltipFormatter, horizontal]);

  const onEvents = useMemo(() => onItemClick ? {
    click: (params) => {
      if (params.componentType === 'series') onItemClick(params.name);
    },
  } : undefined, [onItemClick]);

  if (!option) {
    return (
      <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  return (
    <div className="h-full">
      <ReactECharts
        echarts={echarts}
        option={option}
        style={{ height: typeof height === 'number' ? `${height}px` : height, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
    </div>
  );
}
