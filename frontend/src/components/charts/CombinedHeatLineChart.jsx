import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle, getHeatColor } from '../../utils/chartConfig';
import { fmtFlow } from '../../utils/format';

/**
 * 盘后热度 + 实时净流入 双轴折线图
 * 左轴: 盘后热度值 (0-100, 红色实线)
 * 右轴: 实时净流入 (万元, 蓝色虚线)
 * X 轴: 板块名 (按盘后热度降序, Top 20)
 */
export default function CombinedHeatLineChart({
  heatData, rtSectors, selectedDate,
  selectedSector, onSectorClick,
}) {
  const combined = useMemo(() => {
    if (!heatData?.values || !heatData?.dates) return [];
    const dateIdx = heatData.dates.indexOf(selectedDate);
    const effectiveIdx = dateIdx >= 0 ? dateIdx : heatData.dates.length - 1;

    const rtMap = new Map();
    (rtSectors?.sectors || []).forEach(s => rtMap.set(s.sector, s));

    const heatMap = new Map();
    for (const v of heatData.values) {
      if (v[0] === effectiveIdx) heatMap.set(heatData.sectors[v[1]], v[2]);
    }

    return [...heatMap.entries()]
      .map(([name, heat]) => {
        const rt = rtMap.get(name);
        return {
          name,
          postHeat: heat,
          rtNetFlow: rt?.net_flow ?? null,
          rtRiseRatio: rt?.rise_ratio ?? null,
        };
      })
      .sort((a, b) => b.postHeat - a.postHeat)
      .slice(0, 20);
  }, [heatData, rtSectors, selectedDate]);

  const option = useMemo(() => {
    if (combined.length === 0) return null;

    const makeData = (key) => combined.map(s => {
      const isSelected = selectedSector && selectedSector === s.name;
      const dimmed = selectedSector && !isSelected;
      return {
        value: s[key],
        name: s.name,
        symbolSize: isSelected ? 14 : 6,
        itemStyle: {
          opacity: dimmed ? 0.35 : 1,
          borderColor: isSelected ? '#fff' : 'transparent',
          borderWidth: isSelected ? 2.5 : 0,
        },
      };
    });

    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
        formatter: (params) => {
          const d = combined[params[0].dataIndex];
          if (!d) return '';
          const hc = getHeatColor(d.postHeat);
          const fc = d.rtNetFlow > 0 ? '#ef4444' : d.rtNetFlow < 0 ? '#22c55e' : '#6b7280';
          let html = `<div style="font-weight:700;font-size:13px;margin-bottom:4px">${d.name}</div>`;
          html += `<div style="font-size:12px;color:#ccc">📊 盘后热度：<span style="font-weight:600;color:${hc}">${d.postHeat.toFixed(1)}</span></div>`;
          if (d.rtNetFlow != null) {
            html += `<div style="font-size:12px;color:#ccc">⚡ 实时净流入：<span style="font-weight:600;color:${fc}">${d.rtNetFlow > 0 ? '+' : ''}${fmtFlow(d.rtNetFlow)}</span></div>`;
            html += `<div style="font-size:12px;color:#ccc">实时涨跌：<span style="color:${d.rtRiseRatio > 0 ? '#ef4444' : '#22c55e'}">${d.rtRiseRatio > 0 ? '+' : ''}${d.rtRiseRatio.toFixed(2)}%</span></div>`;
          } else {
            html += `<div style="font-size:12px;color:#999">⚡ 暂无实时快照</div>`;
          }
          return html;
        },
      },
      legend: {
        data: ['盘后热度', '实时净流入'],
        top: 0,
        textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
        itemWidth: 16,
        itemHeight: 2,
      },
      grid: { left: 50, right: 70, top: 36, bottom: 85 },
      xAxis: {
        type: 'category',
        data: combined.map(s => s.name),
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 10,
          rotate: 38,
          interval: 0,
          formatter: (val) => val.length > 5 ? val.slice(0, 4) + '…' : val,
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '热度',
          min: 0,
          max: 100,
          position: 'left',
          nameTextStyle: { color: '#ef4444', fontSize: 10 },
          axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
          splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.25 } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: 'value',
          name: '净流入',
          position: 'right',
          min: (v) => Math.min(0, v.min),
          max: (v) => Math.max(0, v.max),
          nameTextStyle: { color: '#3b82f6', fontSize: 10 },
          axisLabel: {
            color: 'var(--text-muted)',
            fontSize: 10,
            formatter: (v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(1)}亿` : `${(v / 1000).toFixed(0)}k`,
          },
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      series: [
        {
          name: '盘后热度',
          type: 'line',
          data: makeData('postHeat'),
          yAxisIndex: 0,
          smooth: true,
          connectNulls: true,
          lineStyle: {
            color: '#ef4444',
            width: 2.5,
            opacity: selectedSector ? 0.45 : 1,
          },
          itemStyle: { color: '#ef4444' },
          emphasis: { focus: 'series', lineStyle: { width: 3, opacity: 1 } },
          z: 3,
        },
        {
          name: '实时净流入',
          type: 'line',
          data: makeData('rtNetFlow'),
          yAxisIndex: 1,
          smooth: true,
          connectNulls: true,
          lineStyle: {
            color: '#3b82f6',
            width: 2,
            type: 'dashed',
            opacity: selectedSector ? 0.45 : 1,
          },
          itemStyle: { color: '#3b82f6' },
          emphasis: { focus: 'series', lineStyle: { width: 3, opacity: 1 } },
          markLine: {
            symbol: 'none',
            silent: true,
            lineStyle: { color: '#6b7280', type: 'solid', opacity: 0.2, width: 1 },
            data: [{ yAxis: 0 }],
          },
          z: 2,
        },
      ],
    };
  }, [combined, selectedSector]);

  const onEvents = useMemo(() => onSectorClick ? {
    click: (params) => {
      if (params.componentType === 'series') onSectorClick(params.name);
    },
  } : undefined, [onSectorClick]);

  if (!option) {
    return (
      <div className="flex items-center justify-center h-80 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  return (
    <div>
      <ReactECharts
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: '420px', width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
      <div className="mt-1 px-2 text-[11px] flex items-center gap-3 flex-wrap" style={{ color: 'var(--text-muted)' }}>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 h-0.5 rounded" style={{ background: '#ef4444' }}></span>
          盘后热度 (左轴 0-100)
        </span>
        <span className="flex items-center gap-1">
          <span className="inline-block w-4 border-t-2 border-dashed" style={{ borderColor: '#3b82f6' }}></span>
          实时净流入 (右轴 万元)
        </span>
        {onSectorClick && <span>· 点击板块联动</span>}
      </div>
    </div>
  );
}
