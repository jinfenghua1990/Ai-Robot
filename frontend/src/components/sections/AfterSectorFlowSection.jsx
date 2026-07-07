import { useState, useEffect, useMemo } from 'react';
import { apiFetch } from '../../utils/request';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 盘后板块动向
 * 展示指定交易日板块资金流向排名（按 net_flow 降序）。
 */
export default function AfterSectorFlowSection({ selectedDate, selectedSector, onSelectSector }) {
  const [rankData, setRankData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!selectedDate) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    (async () => {
      const { ok, data } = await apiFetch(`/api/sector-flow-rank?date=${selectedDate}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      if (ok) setRankData(data);
      else setError(data?.detail || '加载失败');
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate]);

  const topList = useMemo(() => (rankData?.sectors || []).slice(0, 20), [rankData]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        加载中...
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: '#ef4444' }}>
        加载失败：{error}
      </div>
    );
  }

  if (topList.length === 0) {
    return (
      <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
        暂无盘后板块动向数据
      </div>
    );
  }

  const actualDate = rankData?.actual_date;
  const isFallback = actualDate && actualDate !== selectedDate;

  return (
    <div className="h-full flex flex-col">
      <div className="flex items-center justify-between mb-1 px-1">
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          {isFallback ? `数据日期 ${actualDate}` : `盘后数据`}
        </span>
        {isFallback && (
          <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            已回退
          </span>
        )}
      </div>
      <div className="grid grid-cols-12 gap-1 py-1 px-2 text-[10px] border-b mb-1"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
        <span className="col-span-1 text-center">#</span>
        <span className="col-span-4">板块名称</span>
        <span className="col-span-2 text-right">净流入</span>
        <span className="col-span-2 text-right">流入</span>
        <span className="col-span-2 text-right">流出</span>
        <span className="col-span-1 text-right">涨跌</span>
      </div>
      <div className="space-y-0.5 overflow-y-auto flex-1">
        {topList.map((s, i) => {
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
              onClick={() => onSelectSector?.(s.sector)}
              title={`龙头: ${s.leader_stock || '—'} | 涨停: ${s.limit_up_count ?? 0} | 热度: ${(s.heat_score ?? 0).toFixed(1)}`}>
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
  );
}
