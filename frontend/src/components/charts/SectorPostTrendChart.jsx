import { useState, useEffect, useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { fmtFlow } from '../../utils/format';
import { apiFetch } from '../../utils/request';
import { getSectorColorHex } from '../../utils/sectorColors';

/**
 * 盘后 Top N 板块资金流向日度走势
 * X 轴：交易日；Y 轴：净流入（万元）；每条线代表一个板块。
 */
export default function SectorPostTrendChart({
  sectors,
  selectedDate,
  days = 5,
  selectedSector,
  onSectorClick,
}) {
  const [trendData, setTrendData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedDate || !sectors?.length) {
      setTrendData(null);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    (async () => {
      const { ok, data } = await apiFetch(
        `/api/sector-flow-trend?date=${selectedDate}&days=${days}&sectors=${encodeURIComponent(sectors.join(','))}`,
        { signal: controller.signal }
      );
      if (!controller.signal.aborted) {
        setTrendData(ok ? data : null);
        setLoading(false);
      }
    })();

    return () => controller.abort();
  }, [selectedDate, days, sectors]);

  const option = useMemo(() => {
    if (!trendData?.dates?.length || !trendData?.series?.length) return null;

    const series = trendData.series.map((s) => {
      const isSelected = selectedSector && selectedSector === s.sector;
      const dimmed = selectedSector && !isSelected;
      const color = getSectorColorHex(s.sector);
      return {
        name: s.sector,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: isSelected ? 10 : 4,
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
      legend: {
        type: 'scroll',
        top: 0,
        textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
        pageTextStyle: { color: 'var(--text-muted)' },
        pageItemSize: 12,
      },
      grid: { top: 40, left: 55, right: 30, bottom: 30 },
      xAxis: {
        type: 'category',
        data: trendData.dates,
        boundaryGap: false,
        axisLabel: { color: 'var(--text-secondary)', fontSize: 11 },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        name: '净流入（万元）',
        nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 11,
          formatter: (v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(0)}亿` : `${(v / 1000).toFixed(0)}k`,
        },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series,
    };
  }, [trendData, selectedSector]);

  const onEvents = useMemo(() => onSectorClick ? {
    click: (params) => {
      if (params.componentType === 'series') onSectorClick(params.seriesName);
    },
  } : undefined, [onSectorClick]);

  if (loading) {
    return <div className="h-64 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />;
  }

  if (!option) {
    return (
      <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无盘后资金流向走势数据
      </div>
    );
  }

  const actualDate = trendData?.actual_date;
  const isFallback = actualDate && actualDate !== selectedDate;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-1">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {isFallback ? `数据日期 ${actualDate}` : '盘后数据'}
        </span>
        {isFallback && (
          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            已回退
          </span>
        )}
      </div>
      <div className="flex-1 min-h-0">
        <ReactECharts
          echarts={echarts}
          option={option}
          notMerge={true}
          style={{ height: '240px', width: '100%' }}
          opts={{ renderer: 'canvas' }}
          onEvents={onEvents}
        />
      </div>
    </div>
  );
}
