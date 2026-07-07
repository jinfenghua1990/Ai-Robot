import { useMemo } from 'react';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 右栏 · 实时个股动向
 * 按 selectedSector 联动过滤；点击个股 → onSelectStock（驱动共享趋势面板）。
 * rtStocks 由 PanoramaPage 单一轮询注入。
 */
export default function RealtimeStockSection({ rtStocks, selectedSector, onSelectSector, selectedStock, onSelectStock }) {
  const stocks = useMemo(() => {
    const list = rtStocks?.stocks || [];
    const filtered = selectedSector ? list.filter(s => s.sector === selectedSector) : list;
    return filtered
      .slice()
      .sort((a, b) => (b.main_force_inflow || 0) - (a.main_force_inflow || 0))
      .slice(0, 20);
  }, [rtStocks, selectedSector]);

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📈 实时个股动向</h3>
        <div className="flex items-center gap-2 text-[10px]">
          {selectedSector ? (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded cursor-pointer"
              style={{ background: 'rgba(99,102,241,0.15)', color: '#a5b4fc' }}
              onClick={() => onSelectSector?.(null)}>
              筛选: {selectedSector} ✕
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>全部板块 · 按主力净流入排序</span>
          )}
          {rtStocks?.snapshot_time && (
            <span style={{ color: 'var(--text-muted)' }}>{rtStocks.snapshot_time.slice(11)}</span>
          )}
        </div>
      </div>

      <div className="grid grid-cols-12 gap-1 py-1 px-2 text-[10px] border-b mb-1"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
        <span className="col-span-1 text-center">#</span>
        <span className="col-span-4">个股</span>
        <span className="col-span-3">板块</span>
        <span className="col-span-2 text-right">主力净流入</span>
        <span className="col-span-2 text-right">涨跌幅</span>
      </div>
      <div className="space-y-0.5 max-h-[420px] overflow-y-auto">
        {stocks.length === 0 ? (
          <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>
            {selectedSector ? '该板块暂无实时个股快照' : '暂无数据'}
          </div>
        ) : stocks.map((s, i) => {
          const isInflow = (s.main_force_inflow || 0) > 0;
          const chg = s.price_chg ?? 0;
          const isSelected = selectedStock === s.ts_code;
          const dimmed = selectedStock && !isSelected;
          return (
            <div key={s.ts_code} className="grid grid-cols-12 gap-1 py-1 px-2 rounded cursor-pointer transition-colors"
              style={{
                background: isSelected ? 'rgba(56,189,248,0.15)' : (isInflow ? 'rgba(239,68,68,0.05)' : 'rgba(34,197,94,0.05)'),
                opacity: dimmed ? 0.4 : 1,
                border: isSelected ? '1px solid rgba(56,189,248,0.5)' : '1px solid transparent',
              }}
              onClick={() => onSelectStock?.(s.ts_code)}>
              <span className="col-span-1 text-xs text-center" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
              <span className="col-span-4 text-sm truncate" style={{ color: 'var(--text-primary)', fontWeight: isSelected ? 700 : 400 }}>
                {s.name}
                <span className="text-[10px] ml-1" style={{ color: 'var(--text-muted)' }}>{s.ts_code?.split('.')[0]}</span>
              </span>
              <span className="col-span-3 text-xs truncate" style={{ color: 'var(--text-muted)' }}>{s.sector || '—'}</span>
              <span className="col-span-2 text-xs text-right font-semibold" style={{ color: isInflow ? '#ef4444' : '#22c55e' }}>
                {isInflow ? '+' : ''}{fmtFlow(s.main_force_inflow)}
              </span>
              <span className="col-span-2 text-xs text-right" style={{ color: chg > 0 ? '#ef4444' : '#22c55e' }}>
                {chg > 0 ? '+' : ''}{chg.toFixed(2)}%
              </span>
            </div>
          );
        })}
      </div>
      <div className="mt-1.5 px-2 text-xs" style={{ color: 'var(--text-muted)' }}>
        共 {stocks.length} 只 · 点击个股查看盘中趋势
      </div>
    </div>
  );
}
