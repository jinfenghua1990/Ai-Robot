import { useMemo } from 'react';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(1)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 实时板块资金流向排名（替代桑基图）
 * 左右分栏：Top 8 净流入 + Top 8 净流出，与盘后格式对齐方便对比。
 */
export default function RealtimeSankeyChart({ rtSectors, selectedSector, onNodeClick }) {
  const { inflows, outflows, snapshotTime } = useMemo(() => {
    const list = rtSectors?.sectors || [];
    const sorted = list.slice().sort((a, b) => b.net_flow - a.net_flow);
    return {
      inflows: sorted.filter(s => s.net_flow > 0).slice(0, 8),
      outflows: sorted.filter(s => s.net_flow < 0).sort((a, b) => a.net_flow - b.net_flow).slice(0, 8),
      snapshotTime: rtSectors?.snapshot_time,
    };
  }, [rtSectors]);

  if (!rtSectors?.trade_date) {
    return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>;
  }

  // 统计
  const totalIn = inflows.reduce((s, x) => s + x.net_flow, 0);
  const totalOut = outflows.reduce((s, x) => s + Math.abs(x.net_flow), 0);

  return (
    <div className="h-full flex flex-col gap-1.5 overflow-hidden">
      {/* 统计摘要 */}
      <div className="grid grid-cols-3 gap-1.5 shrink-0">
        <div className="rounded px-2 py-1 border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>Top8 流入</div>
          <div className="text-xs font-bold text-red-500">{fmtFlow(totalIn)}</div>
        </div>
        <div className="rounded px-2 py-1 border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>Top8 流出</div>
          <div className="text-xs font-bold text-green-500">{fmtFlow(totalOut)}</div>
        </div>
        <div className="rounded px-2 py-1 border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>快照时间</div>
          <div className="text-[10px] font-bold" style={{ color: 'var(--text-secondary)' }}>
            {snapshotTime ? snapshotTime.slice(11, 19) : '—'}
          </div>
        </div>
      </div>

      {/* 排名列表 */}
      <div className="flex-1 min-h-0 grid grid-cols-2 gap-2 overflow-hidden">
        {/* 净流入 */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="text-[10px] font-semibold text-red-500 px-1 shrink-0">▼ 净流入 Top 8</div>
          <div className="flex-1 overflow-y-auto">
            {inflows.map((s, i) => {
              const isSel = selectedSector === s.sector;
              return (
                <div
                  key={s.sector}
                  onClick={() => onNodeClick?.(s.sector)}
                  className="flex items-center px-2 py-1 rounded cursor-pointer text-xs transition-colors"
                  style={{
                    background: isSel ? 'var(--bg-hover)' : 'transparent',
                    borderLeft: isSel ? '2px solid #ef4444' : '2px solid transparent',
                  }}
                  onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                  onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span className="w-4 text-center font-mono text-[10px]" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="flex-1 truncate mx-1.5" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                  {s.rise_ratio != null && (
                    <span className="text-[10px] mr-1.5 font-mono" style={{ color: s.rise_ratio >= 0 ? '#ef4444' : '#22c55e' }}>
                      {s.rise_ratio >= 0 ? '+' : ''}{s.rise_ratio.toFixed(2)}%
                    </span>
                  )}
                  <span className="font-mono text-[11px] font-semibold text-red-500 w-14 text-right">
                    {fmtFlow(s.net_flow)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        {/* 净流出 */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="text-[10px] font-semibold text-green-500 px-1 shrink-0">▲ 净流出 Top 8</div>
          <div className="flex-1 overflow-y-auto">
            {outflows.map((s, i) => {
              const isSel = selectedSector === s.sector;
              return (
                <div
                  key={s.sector}
                  onClick={() => onNodeClick?.(s.sector)}
                  className="flex items-center px-2 py-1 rounded cursor-pointer text-xs transition-colors"
                  style={{
                    background: isSel ? 'var(--bg-hover)' : 'transparent',
                    borderLeft: isSel ? '2px solid #22c55e' : '2px solid transparent',
                  }}
                  onMouseEnter={e => { if (!isSel) e.currentTarget.style.background = 'var(--bg-hover)'; }}
                  onMouseLeave={e => { if (!isSel) e.currentTarget.style.background = 'transparent'; }}
                >
                  <span className="w-4 text-center font-mono text-[10px]" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="flex-1 truncate mx-1.5" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                  {s.rise_ratio != null && (
                    <span className="text-[10px] mr-1.5 font-mono" style={{ color: s.rise_ratio >= 0 ? '#ef4444' : '#22c55e' }}>
                      {s.rise_ratio >= 0 ? '+' : ''}{s.rise_ratio.toFixed(2)}%
                    </span>
                  )}
                  <span className="font-mono text-[11px] font-semibold text-green-500 w-14 text-right">
                    {fmtFlow(s.net_flow)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 底部说明 */}
      <div className="text-[9px] shrink-0 px-1" style={{ color: 'var(--text-muted)' }}>
        当日累计净流入 · 含涨跌幅参考 · 点击钻取分时走势
      </div>
    </div>
  );
}
