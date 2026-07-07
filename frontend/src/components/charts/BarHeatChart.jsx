import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle, getHeatColor } from '../../utils/chartConfig';

// 变化模式颜色：红=升温，绿=降温，灰=持平
const getChangeColor = (trend) => {
  if (trend > 5) return '#dc2626';
  if (trend > 1) return '#f97316';
  if (trend < -5) return '#16a34a';
  if (trend < -1) return '#22c55e';
  return '#6b7280';
};

const HEAT_LEGEND = [
  { color: '#ef4444', label: '≥70 极热' },
  { color: '#f97316', label: '55-70 高热' },
  { color: '#eab308', label: '40-55 温热' },
  { color: '#22c55e', label: '25-40 低温' },
  { color: '#3b82f6', label: '<25 冰冷' },
];
const CHANGE_LEGEND = [
  { color: '#dc2626', label: '▲大幅升温' },
  { color: '#f97316', label: '▲小幅升温' },
  { color: '#6b7280', label: '●基本持平' },
  { color: '#22c55e', label: '▼小幅降温' },
  { color: '#16a34a', label: '▼大幅降温' },
];

/**
 * 板块热度/变化趋势横向柱状图
 * - viewMode='heat': 按热度降序的横向柱状图，柱长=热度(0-100)，颜色=热度等级
 * - viewMode='change': 发散型横向柱状图，零轴居中，升温红柱向右，降温绿柱向左
 * 接受 selectedSector/onSectorClick 实现左右联动高亮
 */
export default function BarHeatChart({ data, selectedDate, viewMode = 'heat', selectedSector, onSectorClick }) {

  // 提取当日 + 前一日板块热度，用 Map 一次遍历
  const { sorted, currentDate, prevDate } = useMemo(() => {
    if (!data || !data.values || data.values.length === 0) {
      return { sorted: [], currentDate: null, prevDate: null };
    }
    const dateIdx = data.dates.indexOf(selectedDate);
    const effectiveDateIdx = dateIdx >= 0 ? dateIdx : data.dates.length - 1;
    const curDate = data.dates[effectiveDateIdx];
    const prevDt = effectiveDateIdx > 0 ? data.dates[effectiveDateIdx - 1] : null;

    const curHeat = new Map();
    const prevHeat = new Map();
    for (const v of data.values) {
      if (v[0] === effectiveDateIdx) curHeat.set(data.sectors[v[1]], v[2]);
      else if (v[0] === effectiveDateIdx - 1) prevHeat.set(data.sectors[v[1]], v[2]);
    }

    const all = [...curHeat.entries()].map(([name, heat]) => {
      const prev = prevHeat.get(name) ?? null;
      return { name, heat, prev, trend: prev != null ? heat - prev : 0 };
    });

    const s = (viewMode === 'heat'
      ? all.sort((a, b) => b.heat - a.heat)
      : all.sort((a, b) => Math.abs(b.trend) - Math.abs(a.trend))
    ).slice(0, 20);

    return { sorted: s, currentDate: curDate, prevDate: prevDt };
  }, [data, selectedDate, viewMode]);

  const option = useMemo(() => {
    if (sorted.length === 0) return null;
    const isHeat = viewMode === 'heat';
    const sectorNames = sorted.map(s => s.name);

    const values = isHeat
      ? sorted.map(s => Math.max(s.heat, 0.5))
      : sorted.map(s => s.trend);

    // 选中态：匹配项全亮+边框，其余降透明度；无选择时全亮
    const dimmed = (name) => selectedSector && selectedSector !== name;

    const formatter = isHeat
      ? (params) => {
          const d = sorted[params.dataIndex];
          const trendText = d.trend > 1
            ? `<span style="color:#ef4444">▲ +${d.trend.toFixed(1)}</span>`
            : d.trend < -1
            ? `<span style="color:#22c55e">▼ ${d.trend.toFixed(1)}</span>`
            : '<span style="color:#999">● 持平</span>';
          return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${d.name}</div>` +
                 `<div style="font-size:12px;color:#ccc">热度：<span style="font-weight:600;color:${getHeatColor(d.heat)}">${d.heat.toFixed(1)}</span></div>` +
                 `<div style="font-size:12px;color:#ccc">前一天：${d.prev != null ? d.prev.toFixed(1) : '—'}</div>` +
                 `<div style="font-size:12px;color:#ccc">变化：${trendText}</div>`;
        }
      : (params) => {
          const d = sorted[params.dataIndex];
          const trendColor = d.trend > 0 ? '#ef4444' : d.trend < 0 ? '#22c55e' : '#999';
          const trendIcon = d.trend > 0 ? '▲' : d.trend < 0 ? '▼' : '●';
          return `<div style="font-weight:700;font-size:14px;margin-bottom:4px">${d.name}</div>` +
                 `<div style="font-size:12px;color:#ccc">变化：<span style="font-weight:600;color:${trendColor}">${trendIcon} ${d.trend > 0 ? '+' : ''}${d.trend.toFixed(1)}</span></div>` +
                 `<div style="font-size:12px;color:#ccc">当日热度：${d.heat.toFixed(1)}</div>` +
                 `<div style="font-size:12px;color:#ccc">前一天热度：${d.prev != null ? d.prev.toFixed(1) : '—'}</div>`;
        };

    if (isHeat) {
      // 热度值：横向柱状图，按热度降序
      return {
        tooltip: { ...tooltipStyle, formatter },
        grid: { left: 8, right: 40, top: 10, bottom: 28, containLabel: true },
        xAxis: {
          type: 'value',
          min: 0,
          max: 100,
          axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
          splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
        },
        yAxis: {
          type: 'category',
          inverse: true,
          data: sectorNames,
          axisLabel: {
            color: (value) => selectedSector && selectedSector !== value ? 'var(--text-muted)' : 'var(--text-primary)',
            fontSize: 11,
            fontWeight: (value) => selectedSector === value ? 700 : 400,
          },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        series: [{
          type: 'bar',
          data: values.map((v, i) => {
            const name = sorted[i].name;
            const baseColor = getHeatColor(sorted[i].heat);
            return {
              value: v,
              name,
              itemStyle: {
                color: baseColor,
                opacity: dimmed(name) ? 0.3 : 1,
                borderColor: selectedSector === name ? '#fff' : 'transparent',
                borderWidth: selectedSector === name ? 1.5 : 0,
                borderRadius: [0, 4, 4, 0],
              },
            };
          }),
          barWidth: '60%',
          label: {
            show: true,
            position: 'right',
            color: 'var(--text-muted)',
            fontSize: 10,
            formatter: (p) => p.value.toFixed(1),
          },
        }],
      };
    }

    // 变化趋势：发散型横向柱状图
    return {
      tooltip: { ...tooltipStyle, formatter },
      grid: { left: 8, right: 8, top: 10, bottom: 28, containLabel: true },
      xAxis: {
        type: 'value',
        axisLabel: {
          color: 'var(--text-muted)',
          fontSize: 10,
          formatter: (v) => (v > 0 ? '+' : '') + v.toFixed(0),
        },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
      },
      yAxis: {
        type: 'category',
        inverse: true,
        data: sectorNames,
        axisLabel: {
          color: (value) => selectedSector && selectedSector !== value ? 'var(--text-muted)' : 'var(--text-primary)',
          fontSize: 11,
          fontWeight: (value) => selectedSector === value ? 700 : 400,
        },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        type: 'bar',
        data: values.map((v, i) => {
          const name = sorted[i].name;
          const baseColor = getChangeColor(v);
          return {
            value: v,
            name,
            itemStyle: {
              color: baseColor,
              opacity: dimmed(name) ? 0.3 : 1,
              borderColor: selectedSector === name ? '#fff' : 'transparent',
              borderWidth: selectedSector === name ? 1.5 : 0,
              borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
            },
          };
        }),
        barWidth: '60%',
        label: {
          show: true,
          position: (p) => p.value >= 0 ? 'right' : 'left',
          color: 'var(--text-muted)',
          fontSize: 10,
          formatter: (p) => (p.value > 0 ? '+' : '') + p.value.toFixed(1),
        },
        markLine: {
          symbol: 'none',
          silent: true,
          lineStyle: { color: 'var(--border-color)', type: 'solid', opacity: 0.6 },
          data: [{ xAxis: 0 }],
        },
      }],
    };
  }, [sorted, viewMode, selectedSector]);

  const onEvents = useMemo(() => ({
    click: (params) => {
      if (onSectorClick && params.componentType === 'series') {
        onSectorClick(params.name);
      }
    },
  }), [onSectorClick]);

  if (!data || !data.values || data.values.length === 0 || !option) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  const legendItems = viewMode === 'heat' ? HEAT_LEGEND : CHANGE_LEGEND;

  return (
    <div>
      <div className="flex items-center justify-between mb-2 px-1">
        <div className="flex items-center gap-2 text-xs flex-wrap" style={{ color: 'var(--text-muted)' }}>
          {legendItems.map((item, i) => (
            <span key={i} className="flex items-center gap-1">
              <span className="inline-block w-2.5 h-2.5 rounded" style={{ background: item.color }}></span>
              {item.label}
            </span>
          ))}
        </div>
        <div className="text-xs flex-shrink-0 ml-2" style={{ color: 'var(--text-muted)' }}>
          {currentDate} {prevDate && <span>对比 {prevDate}</span>}
        </div>
      </div>
      <ReactECharts
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: '380px', width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
      <div className="mt-1.5 px-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        {viewMode === 'heat'
          ? `共 ${sorted.length} 个板块 · 柱长=热度值 · 颜色=热度等级${onSectorClick ? ' · 点击板块联动' : ''}`
          : `共 ${sorted.length} 个板块 · 柱长=变化量 · 红升绿降 · 按绝对值排序${onSectorClick ? ' · 点击板块联动' : ''}`}
      </div>
    </div>
  );
}
