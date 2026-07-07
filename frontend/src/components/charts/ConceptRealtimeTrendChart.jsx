import { useState, useEffect, useMemo, useRef } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { apiFetch } from '../../utils/request';
import { fmtFlow } from '../../utils/format';
import { getSectorColorHex } from '../../utils/sectorColors';
import ChartLabelLayer from './ChartLabelLayer';

/**
 * 概念板块实时资金流向累计走势图（仿行情终端风格）
 * - 所有折线从 09:30 的 0 轴出发
 * - 净流入区域红色系，净流出区域绿色系
 * - 右侧板块名称+数值用外部 HTML 标签层渲染，强制最小间距，永不重叠
 * - 按最终值排序：净流入在上，净流出在下
 */
export default function ConceptRealtimeTrendChart({
  sectors, rtSectors, selectedSector, onSectorClick, height = '260px', maxLines = 30,
  trendApiPath = '/api/realtime/concept-sector-trend',
  bulkTrendApiPath,
}) {
  const [trends, setTrends] = useState([]);
  const [loading, setLoading] = useState(false);
  const cacheRef = useRef(new Map());
  const chartRef = useRef(null);

  const tradeDate = rtSectors?.trade_date;

  // 生成固定交易时间轴（09:30-11:30, 13:00-15:00）
  const timeAxis = useMemo(() => {
    const times = [];
    for (let h = 9; h <= 11; h++) {
      for (let m = 30; m < 60; m += 5) times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
    }
    times.push('12:00'); // dummy noon separator
    for (let h = 13; h < 15; h++) {
      for (let m = 0; m < 60; m += 5) times.push(`${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`);
    }
    times.push('15:00');
    return times;
  }, []);

  useEffect(() => {
    if (!tradeDate || !sectors?.length) {
      setTrends([]);
      return;
    }

    const controller = new AbortController();
    setLoading(true);

    (async () => {
      const limitedSectors = sectors.slice(0, maxLines);

      if (bulkTrendApiPath && limitedSectors.length > 1) {
        const namesKey = limitedSectors.join(',');
        const cacheKey = `${tradeDate}_bulk_${namesKey}`;
        let results = [];
        if (cacheRef.current.has(cacheKey)) {
          results = cacheRef.current.get(cacheKey);
        } else {
          const { ok, data } = await apiFetch(
            bulkTrendApiPath,
            {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ sectors: limitedSectors }),
              signal: controller.signal,
            }
          );
          if (ok && data?.trends) {
            results = data.trends
              .filter(t => Array.isArray(t.points))
              .map(t => ({ sector: t.sector, points: t.points }));
            cacheRef.current.set(cacheKey, results);
          }
        }
        if (!controller.signal.aborted) {
          setTrends(results);
          setLoading(false);
        }
        return;
      }

      const results = await Promise.all(
        limitedSectors.map(async (name) => {
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
  }, [tradeDate, sectors, trendApiPath, bulkTrendApiPath, maxLines]);

  // 每条线的元数据：排序、颜色、data、最终值、标签文本（供 option 和外部标签共用）
  const lineMeta = useMemo(() => {
    if (trends.length === 0) return [];
    const withLast = trends.map(t => {
      const last = t.points.length > 0 ? t.points[t.points.length - 1].net_flow : 0;
      return { ...t, lastValue: last };
    });
    const sorted = [...withLast].sort((a, b) => b.lastValue - a.lastValue);
    const manyLines = sorted.length > 20;
    return sorted.map((t, idx) => {
      const isSelected = selectedSector && selectedSector === t.sector;
      const dimmed = selectedSector && !isSelected;
      const isPositive = t.lastValue >= 0;
      const color = getSectorColorHex(t.sector);
      const pointMap = new Map(t.points.map(p => [p.time, p.net_flow]));
      const hasTradingTime = t.points.some(p => timeAxis.includes(p.time));
      let data;
      if (!hasTradingTime && t.points.length > 0) {
        const lastPoint = t.points[t.points.length - 1];
        data = timeAxis.map((time) => {
          if (time === '09:30') return 0;
          if (time === '15:00') return lastPoint.net_flow;
          return null;
        });
      } else {
        data = timeAxis.map((time) => {
          if (time === '09:30') return 0;
          return pointMap.get(time) ?? null;
        });
      }
      const lastValid = data[data.length - 1] ?? t.lastValue;
      const valueText = Math.abs(lastValid) >= 10000
        ? `${(lastValid / 10000).toFixed(1)}亿`
        : `${lastValid.toFixed(0)}万`;
      return { t, idx, isSelected, dimmed, isPositive, color, manyLines, data, lastValid, valueText };
    });
  }, [trends, selectedSector, timeAxis]);

  const option = useMemo(() => {
    if (lineMeta.length === 0) return null;
    const series = lineMeta.map(m => ({
      name: m.t.sector,
      type: 'line',
      smooth: 0.35,
      symbol: 'none',
      connectNulls: true,
      lineStyle: {
        width: m.isSelected ? 3.5 : (m.manyLines ? 1.5 : 2.5),
        color: m.color,
        opacity: m.dimmed ? 0.2 : (m.manyLines ? 0.7 : 1),
      },
      itemStyle: { color: m.color, opacity: m.dimmed ? 0.2 : (m.manyLines ? 0.7 : 1) },
      data: m.data,
      emphasis: { focus: 'series', lineStyle: { width: 3.5, opacity: 1 } },
    }));

    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
        formatter: (params) => {
          let html = `<div style="font-weight:700;margin-bottom:6px">${params[0].axisValue}</div>`;
          const sortedParams = [...params].filter(p => p.value != null).sort((a, b) => b.value - a.value);
          sortedParams.forEach(p => {
            const valueColor = p.value > 0 ? '#ef4444' : p.value < 0 ? '#22c55e' : '#6b7280';
            html += `<div style="display:flex;align-items:center;gap:6px;margin:2px 0;font-size:12px">`;
            html += `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${p.color}"></span>`;
            html += `<span style="flex:1">${p.seriesName}</span>`;
            html += `<span style="font-weight:600;color:${valueColor}">${p.value > 0 ? '+' : ''}${fmtFlow(p.value)}</span>`;
            html += `</div>`;
          });
          return html;
        },
      },
      legend: { show: false },
      grid: { top: 10, left: 55, right: 160, bottom: 30 },
      xAxis: {
        type: 'category',
        data: timeAxis,
        boundaryGap: false,
        axisLabel: {
          color: 'var(--text-secondary)',
          fontSize: 10,
          interval: (i) => ['09:30', '10:30', '11:30', '13:00', '14:00', '15:00'].includes(timeAxis[i]),
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
        splitLine: {
          show: true,
          interval: (i) => ['11:30', '15:00'].includes(timeAxis[i]),
          lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.6 },
        },
      },
      yAxis: {
        type: 'value',
        name: '净流入',
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
  }, [lineMeta, timeAxis]);

  // 外部标签 items（ChartLabelLayer 用，强制不重叠）
  const labelItems = useMemo(() => lineMeta.map(m => ({
    key: m.t.sector,
    label: m.t.sector,
    value: m.lastValid,
    valueText: m.valueText,
    color: m.color,
    isPositive: m.isPositive,
    isSelected: m.isSelected,
    dimmed: m.dimmed,
    onClick: onSectorClick ? () => onSectorClick(m.t.sector) : undefined,
  })), [lineMeta, onSectorClick]);

  const onEvents = useMemo(() => onSectorClick ? {
    click: (params) => {
      if (params.componentType === 'series') onSectorClick(params.seriesName);
    },
  } : undefined, [onSectorClick]);

  if (loading) {
    return <div className="h-full rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />;
  }

  if (!tradeDate || !option) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无实时资金流向数据
      </div>
    );
  }

  const chartHeight = typeof height === 'number' ? `${height}px` : height;
  return (
    <div className="h-full relative">
      <ReactECharts
        ref={chartRef}
        echarts={echarts}
        option={option}
        notMerge={true}
        style={{ height: chartHeight, width: '100%' }}
        opts={{ renderer: 'canvas' }}
        onEvents={onEvents}
      />
      <ChartLabelLayer chartRef={chartRef} items={labelItems} width={160} />
    </div>
  );
}
