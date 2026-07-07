import { useState, useEffect, useMemo, useCallback } from 'react';
import SectorPostTrendChart from '../charts/SectorPostTrendChart';
import SectorRealtimeTrendChart from '../charts/SectorRealtimeTrendChart';
import { apiFetch } from '../../utils/request';

/**
 * Top 10 板块资金流向对比
 * 左：盘后 Top 10 板块资金流向走势（日度时间轴折线）
 * 右：同一批板块实时资金流向走势（分钟时间轴折线）
 */
export default function SectorMoneyFlowCompareSection({
  selectedDate, rtSectors, selectedSector, onSelectSector,
}) {
  const [rotationData, setRotationData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedDate) return;
    const controller = new AbortController();
    setLoading(true);
    (async () => {
      const res = await apiFetch(`/api/rotation?date=${selectedDate}&days=1`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setRotationData(res.ok ? res.data : null);
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate]);

  // 盘后 Top 10 板块：按 |net_flow| 排序，取前 10
  const postTop10 = useMemo(() => {
    if (!rotationData?.signals) return [];
    const sectorFlows = [];
    rotationData.signals.forEach(signal => {
      const match = signal.match(/资金(流入|流出)[：:]\s*/);
      if (!match) return;
      const type = match[1];
      const sectors = signal.replace(/资金(流入|流出)[：:]\s*/, '').split('、').filter(Boolean);
      sectors.forEach(name => {
        // 从 rotationData 的 all_inflows/all_outflows 中找具体数值
        const inItem = rotationData.all_inflows?.find(s => s.sector === name);
        const outItem = rotationData.all_outflows?.find(s => s.sector === name);
        if (inItem) sectorFlows.push({ name, value: inItem.change, current: inItem.current, past: inItem.past });
        else if (outItem) sectorFlows.push({ name, value: outItem.change, current: outItem.current, past: outItem.past });
      });
    });
    return sectorFlows
      .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
      .slice(0, 10);
  }, [rotationData]);

  const sectorNames = useMemo(() => postTop10.map(s => s.name), [postTop10]);

  const handleSelect = useCallback((name) => {
    if (onSelectSector) onSelectSector(name);
  }, [onSelectSector]);

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between mb-2">
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
          Top 10 板块资金流向对比
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日` : ''} 盘后 vs 实时
            {rotationData?.actual_date && rotationData.actual_date !== selectedDate && (
              <span className="ml-1" style={{ color: '#eab308' }}>（盘后已回退 {rotationData.actual_date.slice(5).replace('-', '月')}日）</span>
            )}
          </span>
        </h2>
        <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 rounded" style={{ background: '#ef4444' }}></span>净流入</span>
          <span className="flex items-center gap-1"><span className="inline-block w-3 h-0.5 rounded" style={{ background: '#22c55e' }}></span>净流出</span>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-start">
        {/* 左：盘后 Top 10 资金流向走势 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
          <h3 className="text-sm font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
            📊 盘后 Top 10 资金流向走势
          </h3>
          {loading ? (
            <div className="h-64 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
          ) : (
            <SectorPostTrendChart
              sectors={sectorNames}
              selectedDate={selectedDate}
              days={5}
              selectedSector={selectedSector}
              onSectorClick={handleSelect}
            />
          )}
        </div>

        {/* 右：实时 Top 10 资金流向走势 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
          <h3 className="text-sm font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
            ⚡ 实时 Top 10 资金流向走势
            <span className="ml-2 text-xs font-normal" style={{ color: 'var(--text-muted)' }}>
              {rtSectors?.trade_date || selectedDate} 盘中
            </span>
          </h3>
          <SectorRealtimeTrendChart
            sectors={sectorNames}
            rtSectors={rtSectors}
            selectedSector={selectedSector}
            onSectorClick={handleSelect}
          />
        </div>
      </div>
    </div>
  );
}
