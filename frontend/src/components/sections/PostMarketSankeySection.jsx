import { useState, useEffect, useMemo } from 'react';
import { apiFetch } from '../../utils/request';

const fmtYi = (v) => {
  if (v == null || isNaN(v)) return '—';
  return `${v > 0 ? '+' : ''}${(v / 10000).toFixed(1)}亿`;
};

/**
 * 盘后板块资金轮动 — 排名列表视图（替代桑基图）
 * 展示：统计摘要 + 轮动信号 + 流入/流出排名(含5日变化、连续天数)
 */
export default function PostMarketSankeySection({ selectedDate, selectedSector, onSelectSector }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!selectedDate) return;
    const ctrl = new AbortController();
    setLoading(true);
    setError(null);
    (async () => {
      const res = await apiFetch(`/api/rotation?date=${selectedDate}&days=5`, { signal: ctrl.signal });
      if (ctrl.signal.aborted) return;
      if (res.ok) setData(res.data);
      else setError(res.data?.detail || '加载失败');
      setLoading(false);
    })();
    return () => ctrl.abort();
  }, [selectedDate]);

  const inflows = useMemo(() => (data?.all_inflows || []).slice(0, 15), [data]);
  const outflows = useMemo(() => (data?.all_outflows || []).slice(0, 15), [data]);
  const streaks = data?.streaks || {};

  if (loading) return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>;
  if (error) return <div className="flex items-center justify-center h-full text-sm" style={{ color: '#ef4444' }}>{error}</div>;
  if (!data?.all_inflows?.length && !data?.all_outflows?.length) return <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无轮动数据</div>;

  const netFlow = data.net_flow || 0;
  const totalIn = data.total_inflow || 0;
  const totalOut = data.total_outflow || 0;

  // 找最强加速（change最大的）
  const strongest = inflows[0];
  // 找最大减速（change最负的）
  const weakest = outflows[0];

  return (
    <div className="h-full flex flex-col gap-1.5 overflow-hidden">
      {/* 统计摘要 */}
      <div className="grid grid-cols-4 gap-1.5 shrink-0">
        <MiniStat label="总流入" value={`${(totalIn / 10000).toFixed(0)}亿`} color="#ef4444" />
        <MiniStat label="总流出" value={`${(totalOut / 10000).toFixed(0)}亿`} color="#22c55e" />
        <MiniStat label="净轮动" value={`${(netFlow / 10000).toFixed(0)}亿`} color={netFlow >= 0 ? '#ef4444' : '#22c55e'} />
        <MiniStat label="数据日期" value={data.actual_date?.slice(5) || '—'} color="var(--text-secondary)" small />
      </div>

      {/* 轮动信号 */}
      {data.signals?.length > 0 && (
        <div className="shrink-0 px-2 py-1 rounded text-[10px] leading-relaxed" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
          {data.signals.map((s) => (
            <div key={s} className="truncate">{s}</div>
          ))}
        </div>
      )}

      {/* 排名列表 */}
      <div className="flex-1 min-h-0 grid grid-cols-2 gap-2 overflow-hidden">
        {/* 流入排名 */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="text-[10px] font-semibold text-red-500 px-1 shrink-0">▼ 资金流入加速</div>
          <div className="flex-1 overflow-y-auto">
            {inflows.map((s, i) => {
              const streak = streaks[s.sector] || 0;
              const isSel = selectedSector === s.sector;
              return (
                <div
                  key={s.sector}
                  onClick={() => onSelectSector?.(s.sector)}
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
                  {streak >= 2 && (
                    <span className="px-1 py-0.5 rounded text-[10px] font-bold mr-1" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
                      {streak}连
                    </span>
                  )}
                  <span className="font-mono text-[11px] font-semibold text-red-500 w-14 text-right">
                    {fmtYi(s.change)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
        {/* 流出排名 */}
        <div className="flex flex-col min-h-0 overflow-hidden">
          <div className="text-[10px] font-semibold text-green-500 px-1 shrink-0">▲ 资金流出加速</div>
          <div className="flex-1 overflow-y-auto">
            {outflows.map((s, i) => {
              const streak = streaks[s.sector] || 0;
              const isSel = selectedSector === s.sector;
              return (
                <div
                  key={s.sector}
                  onClick={() => onSelectSector?.(s.sector)}
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
                  {streak >= 2 && (
                    <span className="px-1 py-0.5 rounded text-[10px] font-bold mr-1" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>
                      {streak}连
                    </span>
                  )}
                  <span className="font-mono text-[11px] font-semibold text-green-500 w-14 text-right">
                    {fmtYi(s.change)}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* 底部说明 */}
      <div className="text-[10px] shrink-0 px-1" style={{ color: 'var(--text-muted)' }}>
        5日变化量 · 红色=资金加速流入 · 绿色=资金加速流出 · N连=连续N天同向 · 点击钻取
      </div>
    </div>
  );
}

function MiniStat({ label, value, color, small }) {
  return (
    <div className="rounded px-2 py-1 border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className={`${small ? 'text-[10px]' : 'text-xs'} font-bold`} style={{ color }}>{value}</div>
    </div>
  );
}
