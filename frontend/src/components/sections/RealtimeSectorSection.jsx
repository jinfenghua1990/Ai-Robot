import { useMemo } from 'react';
import SectorRealtimeTrendChart from '../charts/SectorRealtimeTrendChart';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 实时板块资金流向
 * mode='all'（默认）：实时资金流向走势(Top10流入+Top10流出) + 紧凑联动表格(Top20)
 * mode='bar'：仅实时资金流向走势
 * mode='table'：仅表格
 * 点击板块联动左栏盘后。rtSectors 由 PanoramaPage 单一轮询注入。
 */
export default function RealtimeSectorSection({ rtSectors, selectedSector, onSelectSector, autoRefresh, onToggleRefresh, mode = 'all', showHeader = true }) {
  const sectorList = useMemo(() => {
    const list = rtSectors?.sectors || [];
    return list.slice().sort((a, b) => b.net_flow - a.net_flow).slice(0, 20);
  }, [rtSectors]);

  const trendSectors = useMemo(() => {
    const list = (rtSectors?.sectors || []).slice().sort((a, b) => b.net_flow - a.net_flow);
    const topIn = list.filter(s => s.net_flow > 0).slice(0, 10);
    const topOut = list.filter(s => s.net_flow < 0).sort((a, b) => a.net_flow - b.net_flow).slice(0, 10);
    return [...topOut.reverse(), ...topIn].map(d => d.sector);
  }, [rtSectors]);

  const showBar = mode === 'all' || mode === 'bar';
  const showTable = mode === 'all' || mode === 'table';

  return (
    <div className="space-y-2 h-full flex flex-col">
      {/* 区块标题（可隐藏） */}
      {showHeader && (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <span className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>⚡ 实时板块动向</span>
            <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>盘中数据</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>快照: {rtSectors?.snapshot_time || '—'}</span>
            {onToggleRefresh && (
              <button onClick={onToggleRefresh} className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
                style={{ borderColor: autoRefresh ? '#22c55e' : 'var(--border-color)', color: autoRefresh ? '#22c55e' : 'var(--text-secondary)', background: autoRefresh ? 'rgba(34,197,94,0.1)' : 'transparent' }}>
                {autoRefresh ? '⏸ 暂停' : '▶ 刷新'}
              </button>
            )}
          </div>
        </div>
      )}

      {/* 实时板块资金流向走势 */}
      {showBar && (
        <div className="h-full flex flex-col">
          <SectorRealtimeTrendChart
            sectors={trendSectors}
            rtSectors={rtSectors}
            selectedSector={selectedSector}
            onSectorClick={onSelectSector}
          />
        </div>
      )}

      {/* 紧凑联动表格 Top20 */}
      {showTable && (
        <div>
          {showBar && <div className="flex items-center justify-between mb-1">
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>💱 板块资金流向 Top20 · 点击联动</span>
          </div>}
          <div className="grid grid-cols-12 gap-1 py-1 px-2 text-[10px] border-b mb-1"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
            <span className="col-span-1 text-center">#</span>
            <span className="col-span-4">板块名称</span>
            <span className="col-span-2 text-right">净流入</span>
            <span className="col-span-2 text-right">流入</span>
            <span className="col-span-2 text-right">流出</span>
            <span className="col-span-1 text-right">涨跌</span>
          </div>
          <div className="space-y-0.5 max-h-[420px] overflow-y-auto">
            {sectorList.length === 0 ? (
              <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据</div>
            ) : sectorList.map((s, i) => {
              const isInflow = s.net_flow > 0;
              const chg = s.rise_ratio ?? 0;
              const isSelected = selectedSector === s.sector;
              const dimmed = selectedSector && !isSelected;
              return (
                <div key={s.sector} className="grid grid-cols-12 gap-1 py-1 px-2 rounded cursor-pointer transition-colors"
                  style={{
                    background: isSelected ? 'rgba(99,102,241,0.15)' : (isInflow ? 'rgba(239,68,68,0.05)' : 'rgba(34,197,94,0.05)'),
                    opacity: dimmed ? 0.4 : 1,
                    border: isSelected ? '1px solid rgba(99,102,241,0.5)' : '1px solid transparent',
                  }}
                  onClick={() => onSelectSector?.(s.sector)}>
                  <span className="col-span-1 text-xs text-center" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="col-span-4 text-sm truncate" style={{ color: 'var(--text-primary)', fontWeight: isSelected ? 700 : 400 }}>{s.sector}</span>
                  <span className="col-span-2 text-xs text-right font-semibold" style={{ color: isInflow ? '#ef4444' : '#22c55e' }}>
                    {isInflow ? '+' : ''}{fmtFlow(s.net_flow)}
                  </span>
                  <span className="col-span-2 text-xs text-right" style={{ color: '#ef4444' }}>
                    +{fmtFlow(s.money_inflow)}
                  </span>
                  <span className="col-span-2 text-xs text-right" style={{ color: '#22c55e' }}>
                    -{fmtFlow(s.money_outflow)}
                  </span>
                  <span className="col-span-1 text-xs text-right" style={{ color: chg > 0 ? '#ef4444' : '#22c55e' }}>
                    {chg > 0 ? '+' : ''}{chg.toFixed(1)}%
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
