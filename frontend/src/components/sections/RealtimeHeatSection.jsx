import { useMemo } from 'react';
import SectorRealtimeTrendChart from '../charts/SectorRealtimeTrendChart';

/**
 * 实时板块热度
 * 与实时板块动向一致：按净流入取 Top 10，展示当天分钟级资金流向走势。
 */
export default function RealtimeHeatSection({ rtSectors, selectedSector, onSelectSector }) {
  const topSectors = useMemo(() => {
    const sectors = rtSectors?.sectors || [];
    return sectors
      .slice()
      .sort((a, b) => b.net_flow - a.net_flow)
      .slice(0, 10)
      .map(s => s.sector);
  }, [rtSectors]);

  if (!rtSectors?.trade_date) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无实时快照
      </div>
    );
  }

  if (topSectors.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无实时板块热度数据
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <SectorRealtimeTrendChart
        sectors={topSectors}
        rtSectors={rtSectors}
        selectedSector={selectedSector}
        onSelectSector={onSelectSector}
        height="100%"
      />
    </div>
  );
}
