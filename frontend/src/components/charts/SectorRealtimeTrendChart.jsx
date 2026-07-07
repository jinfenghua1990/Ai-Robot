import { useState, useEffect, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { apiFetch } from '../../utils/request';
import { fmtFlow } from '../../utils/format';
import { getSectorColorHex } from '../../utils/sectorColors';
import CategoryLineChart from './CategoryLineChart';

/**
 * Top 10 板块实时资金流向分钟走势图
 * X 轴：交易时间；Y 轴：净流入（万元）；每条线代表一个板块。
 */
export default function SectorRealtimeTrendChart({
  sectors, rtSectors, selectedSector, onSectorClick, height = '260px',
  trendApiPath = '/api/realtime/sector-trend',
}) {
  const [trends, setTrends] = useState([]);
  const [loading, setLoading] = useState(false);
  const cacheRef = useRef(new Map());

  const tradeDate = rtSectors?.trade_date;

  useEffect(() => {
    if (!tradeDate || !sectors?.length) {
      setTrends([]);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    (async () => {
      const results = await Promise.all(
        sectors.map(async (name) => {
          const cacheKey = `${tradeDate}_${name}`;
          if (cacheRef.current.has(cacheKey)) {
            return cacheRef.current.get(cacheKey);
          }
          const { ok, data } = await apiFetch(
            `${trendApiPath}?sector=${encodeURIComponent(name)}`,
            { signal: controller.signal }
          );
          if (!ok || !data?.points) return null;
          const item = { sector: name, points: data.points };
          cacheRef.current.set(cacheKey, item);
          return item;
        })
      );

      if (!controller.signal.aborted) {
        setTrends(results.filter(Boolean));
        setLoading(false);
      }
    })();

    return () => controller.abort();
  }, [tradeDate, sectors, trendApiPath]);

  const option = useMemo(() => {
    if (trends.length === 0) return null;

    const timesSet = new Set();
    trends.forEach(t => t.points.forEach(p => timesSet.add(p.time)));
    const times = [...timesSet].sort();

    const series = trends.map((t) => {
      const isSelected = selectedSector && selectedSector === t.sector;
      const dimmed = selectedSector && !isSelected;
      const color = getSectorColorHex(t.sector);
      const pointMap = new Map(t.points.map(p => [p.time, p.net_flow]));
      return {
        name: t.sector,
        type: 'line',
        smooth: true,
        symbol: 'circle',
        symbolSize: isSelected ? 10 : 4,
        connectNulls: true,
        lineStyle: { width: isSelected ? 4 : 2.5, color, opacity: dimmed ? 0.25 : 1 },
        itemStyle: { color, opacity: dimmed ? 0.25 : 1 },
        data: times.map(time => pointMap.get(time) ?? null),
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
        data: times,
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
  }, [trends, selectedSector]);

  const onEvents = useMemo(() => onSectorClick ? {
    click: (params) => {
      if (params.componentType === 'series') onSectorClick(params.seriesName);
    },
  } : undefined, [onSectorClick]);

  if (loading) {
    return <div className="h-64 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />;
  }

  if (!tradeDate) {
    return (
      <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无实时快照
      </div>
    );
  }

  if (!option) {
    // 非盘中时无分钟数据， fallback 用快照中的净流入展示 Top10 板块资金流向
    const snapshot = rtSectors?.sectors || [];
    const fallback = sectors
      .map(name => snapshot.find(s => s.sector === name))
      .filter(Boolean)
      .sort((a, b) => b.net_flow - a.net_flow);

    if (fallback.length === 0) {
      return (
        <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
          暂无资金流向数据
        </div>
      );
    }

    return (
      <CategoryLineChart
        categories={fallback.map(s => s.sector)}
        values={fallback.map(s => s.net_flow)}
        selectedItem={selectedSector}
        onItemClick={onSectorClick}
        color="#6366f1"
        valueFormatter={(v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(0)}亿` : `${v.toFixed(0)}万`}
        height={height}
      />
    );
  }

  const chartHeight = typeof height === 'number' ? `${height}px` : height;
  return (
    <div className="h-full">
      <ReactECharts
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: chartHeight, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
    </div>
  );
}
