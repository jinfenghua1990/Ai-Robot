import { useMemo } from 'react';
import TrendLineChart from '../components/charts/TrendLineChart';

/**
 * 盘后 · 板块热度 Chart 组件
 * 数据/视角日期由父组件 ModuleGroup 注入，本组件只负责渲染 Top 10 热度趋势折线。
 */
export default function AfterHeatmapSection({
  data,
  viewDate,
  selectedSector, onSelectSector,
}) {
  const topSectors = useMemo(() => {
    if (!data || !viewDate) return [];
    const dateIdx = data.dates.indexOf(viewDate);
    if (dateIdx === -1) return [];
    const sectors = [];
    data.values.forEach(v => {
      if (v[0] === dateIdx) {
        const sector = data.sectors[v[1]];
        sectors.push({ sector, heat: v[2] });
      }
    });
    return sectors.sort((a, b) => b.heat - a.heat).slice(0, 10);
  }, [data, viewDate]);

  if (!data) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        加载中...
      </div>
    );
  }

  if (topSectors.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无数据
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="flex-1 min-h-0" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <TrendLineChart data={data} topSectors={topSectors}
          selectedSector={selectedSector} onSectorClick={onSelectSector} height="100%" />
      </div>
    </div>
  );
}
