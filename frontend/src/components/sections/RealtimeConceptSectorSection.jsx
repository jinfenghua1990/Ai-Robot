import { useMemo } from 'react';
import ConceptRealtimeTrendChart from '../charts/ConceptRealtimeTrendChart';

/**
 * 实时概念板块资金流向 — 使用 RealtimeConceptSectorFlow 快照数据
 * 盘中每 15 分钟采集一次，展示分时累计走势
 */
export default function RealtimeConceptSectorSection({ rtConceptSectors, sectors, selectedSector, onSelectSector }) {
  // 只展示父组件选中的概念，按净流入降序
  const trendSectors = useMemo(() => {
    const selectedSet = new Set(sectors || []);
    const concepts = (rtConceptSectors?.sectors || []).filter(s => selectedSet.has(s.sector));
    return [...concepts].sort((a, b) => b.net_flow - a.net_flow).map(d => d.sector);
  }, [rtConceptSectors, sectors]);

  if (!rtConceptSectors?.trade_date) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无实时概念板块快照
      </div>
    );
  }

  if (trendSectors.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        请在右上方「筛选概念」中选择概念板块
      </div>
    );
  }

  // 判断当前快照是否在交易时段
  const snapshotTime = rtConceptSectors?.snapshot_time;
  const isTradingHours = useMemo(() => {
    if (!snapshotTime) return false;
    const t = snapshotTime.slice(11, 16);
    return (t >= '09:30' && t <= '11:30') || (t >= '13:00' && t <= '15:00');
  }, [snapshotTime]);

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-1 px-1 shrink-0">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          概念板块 · 快照: {snapshotTime || '—'}
          {!isTradingHours && (
            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.15)', color: '#eab308' }}>
              非交易时段 · 仅最新收盘快照
            </span>
          )}
        </span>
      </div>
      <div className="flex-1 min-h-0">
        <ConceptRealtimeTrendChart
          sectors={trendSectors}
          rtSectors={rtConceptSectors}
          selectedSector={selectedSector}
          onSectorClick={onSelectSector}
          height="100%"
          maxLines={500}
          trendApiPath="/api/realtime/concept-sector-trend"
          bulkTrendApiPath="/api/realtime/concept-sector-trends"
        />
      </div>
    </div>
  );
}
