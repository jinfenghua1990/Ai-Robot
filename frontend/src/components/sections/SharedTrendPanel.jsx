import { useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';

/**
 * 共享盘中趋势面板（通栏）
 * 由 PanoramaPage 的 selectedSector/selectedStock 驱动，合并原 StockFlowCompare 与 RealtimePanel 的重复趋势图。
 * trendType: { kind: 'stock'|'sector', name }
 * trendData: { points: [{ time, net_flow|main_force_inflow, price, rise_ratio }] }
 */
export default function SharedTrendPanel({ trendType, trendData, onClose }) {
  const option = useMemo(() => {
    if (!trendData?.points?.length) return null;
    const pts = trendData.points;
    const isStock = trendType?.kind === 'stock';
    return {
      tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', borderColor: 'rgba(255,255,255,0.15)', textStyle: { color: '#fff', fontSize: 12 } },
      grid: { left: 60, right: 60, top: 30, bottom: 30 },
      xAxis: { type: 'category', data: pts.map(p => p.time), axisLabel: { color: 'var(--text-muted)', fontSize: 10 }, axisLine: { lineStyle: { color: 'var(--border-color)' } } },
      yAxis: [
        { type: 'value', name: '净流入(万)', position: 'left', axisLabel: { color: 'var(--text-muted)', fontSize: 10, formatter: v => Math.abs(v) >= 10000 ? `${(v/10000).toFixed(1)}亿` : `${v.toFixed(0)}` }, splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } } },
        { type: 'value', name: isStock ? '价格' : '涨跌幅', position: 'right', axisLabel: { color: 'var(--text-muted)', fontSize: 10 }, splitLine: { show: false } },
      ],
      series: [
        { name: '净流入', type: 'line', data: pts.map(p => p.net_flow || p.main_force_inflow || 0), smooth: true, symbol: 'circle', symbolSize: 6, lineStyle: { color: '#ef4444', width: 2 }, itemStyle: { color: '#ef4444' }, areaStyle: { color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: 'rgba(239,68,68,0.3)' }, { offset: 1, color: 'rgba(239,68,68,0)' }] } } },
        { name: isStock ? '价格' : '涨跌幅', type: 'line', yAxisIndex: 1, data: pts.map(p => isStock ? (p.price || 0) : (p.rise_ratio || 0)), smooth: true, symbol: 'none', lineStyle: { color: '#38bdf8', width: 1.5, type: 'dashed' }, itemStyle: { color: '#38bdf8' } },
      ],
    };
  }, [trendData, trendType]);

  if (!option) return null;

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
          📈 盘中趋势：{trendType?.kind === 'stock' ? '个股' : '板块'} · {trendType?.name}
        </h3>
        <button onClick={onClose} className="text-xs" style={{ color: 'var(--text-muted)' }}>✕ 关闭</button>
      </div>
      <ReactECharts echarts={echarts} option={option} style={{ height: 240 }} />
    </div>
  );
}
