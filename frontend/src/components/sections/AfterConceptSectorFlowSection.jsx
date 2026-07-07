import { useState, useEffect, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { apiFetch } from '../../utils/request';
import { getSectorColorHex } from '../../utils/sectorColors';
import ChartLabelLayer from '../charts/ChartLabelLayer';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 盘后概念板块动向 — 已选概念板块 20 日净流入趋势折线图
 * 与板块热度左栏一致的视觉语言。
 * sectors: 父组件传入的已选概念列表（与实时右侧同维度）
 * 右侧板块名称+数值用外部 HTML 标签层渲染，强制最小间距，永不重叠
 */
export default function AfterConceptSectorFlowSection({ selectedDate, sectors, selectedSector, onSelectSector }) {
  const [rankData, setRankData] = useState(null);
  const [trendData, setTrendData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const chartRef = useRef(null);

  // 1. 拉取排名数据（用于回显 actual_date）
  useEffect(() => {
    if (!selectedDate) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setTrendData(null);
    (async () => {
      const { ok, data } = await apiFetch(`/api/concept-sector-flow-rank?date=${selectedDate}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (ok) setRankData(data);
      else setError(data?.detail || '加载失败');
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate]);

  // 用父组件传入的 sectors，不再自动取 Top10
  const topSectors = useMemo(() => (sectors || []).slice(0, 30), [sectors]);

  // 2. 拉取已选概念的 20 日趋势
  useEffect(() => {
    if (!selectedDate || topSectors.length === 0) {
      setTrendData(null);
      return;
    }
    const controller = new AbortController();
    (async () => {
      const names = topSectors.join(',');
      const { ok, data } = await apiFetch(
        `/api/concept-sector-flow-trend?date=${selectedDate}&days=20&sectors=${encodeURIComponent(names)}`,
        { signal: controller.signal }
      );
      if (controller.signal.aborted) return;
      if (ok) setTrendData(data);
    })();
    return () => controller.abort();
  }, [selectedDate, topSectors]);

  // 每条线元数据：按最终值从高到低排序，计算颜色/标签文本（供 option 和外部标签共用）
  const lineMeta = useMemo(() => {
    if (!trendData?.dates || !trendData?.series || trendData.series.length === 0) return [];
    const withLast = trendData.series.map(s => {
      const lastValid = [...s.values].reverse().find(v => v != null && !isNaN(v)) ?? 0;
      return { ...s, lastValue: lastValid };
    });
    return [...withLast].sort((a, b) => b.lastValue - a.lastValue);
  }, [trendData]);

  const option = useMemo(() => {
    if (lineMeta.length === 0 || !trendData?.dates) return null;

    const series = lineMeta.map((s) => {
      const isSelected = selectedSector && selectedSector === s.sector;
      const dimmed = selectedSector && !isSelected;
      const color = getSectorColorHex(s.sector);
      return {
        name: s.sector,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: isSelected ? 10 : 5,
        connectNulls: true,
        lineStyle: { width: isSelected ? 4 : 2.5, color, opacity: dimmed ? 0.25 : 1 },
        itemStyle: { color, opacity: dimmed ? 0.25 : 1 },
        data: s.values,
        emphasis: { focus: 'series', lineStyle: { width: 4 }, symbolSize: 10 },
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
            html += `<span style="font-weight:600;color:${color}">${p.value > 0 ? '+' : ''}${fmtFlow(p.value)}</span>`;
            html += `</div>`;
          });
          return html;
        },
      },
      legend: { show: false },
      grid: { top: 10, left: 55, right: 160, bottom: 30 },
      xAxis: {
        type: 'category',
        data: trendData.dates,
        boundaryGap: false,
        axisLabel: { color: 'var(--text-secondary)', fontSize: 10, rotate: 35, interval: 'auto', formatter: (v) => v.slice(5) },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: '净流入（万元）',
        nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
        axisLabel: {
          color: 'var(--text-secondary)', fontSize: 11,
          formatter: (v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(0)}亿` : `${(v / 1000).toFixed(0)}k`,
        },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series,
    };
  }, [lineMeta, trendData, selectedSector]);

  // 外部标签 items（ChartLabelLayer 用，强制不重叠）
  const labelItems = useMemo(() => lineMeta.map(s => {
    const isSelected = selectedSector && selectedSector === s.sector;
    const dimmed = selectedSector && !isSelected;
    const color = getSectorColorHex(s.sector);
    const isPositive = s.lastValue >= 0;
    const valueText = Math.abs(s.lastValue) >= 10000
      ? `${(s.lastValue / 10000).toFixed(1)}亿`
      : `${s.lastValue.toFixed(0)}万`;
    return {
      key: s.sector,
      label: s.sector,
      value: s.lastValue,
      valueText,
      color,
      isPositive,
      isSelected,
      dimmed,
      onClick: onSelectSector ? () => onSelectSector(s.sector) : undefined,
    };
  }), [lineMeta, selectedSector, onSelectSector]);

  const onEvents = useMemo(() => onSelectSector ? {
    click: (params) => {
      if (params.componentType === 'series') onSelectSector(params.seriesName);
    },
  } : undefined, [onSelectSector]);

  if (loading) {
    return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>;
  }
  if (error) {
    return <div className="flex items-center justify-center h-full text-sm" style={{ color: '#ef4444' }}>加载失败：{error}</div>;
  }
  if (topSectors.length === 0) {
    return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>请在右上方「筛选概念」中选择概念板块</div>;
  }
  if (!option) {
    return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无盘后概念板块趋势数据</div>;
  }

  const actualDate = rankData?.actual_date;
  const isFallback = actualDate && actualDate !== selectedDate;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-1 px-1 shrink-0">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {isFallback ? `数据日期 ${actualDate}` : '盘后数据'}
        </span>
        {isFallback && (
          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>已回退</span>
        )}
      </div>
      <div className="flex-1 min-h-0 relative">
        <ReactECharts
          ref={chartRef}
          echarts={echarts}
          option={option}
          notMerge={true}
          style={{ height: '100%', width: '100%' }}
          opts={{ renderer: 'canvas' }}
          onEvents={onEvents}
        />
        <ChartLabelLayer chartRef={chartRef} items={labelItems} width={160} />
      </div>
    </div>
  );
}
