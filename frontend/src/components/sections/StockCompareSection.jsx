import { useState, useEffect, useMemo } from 'react';
import { apiFetch } from '../../utils/request';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 资金对比（盘后 vs 实时）· 折线 + Δ 徽章
 * 每只股票一张卡：上方红色盘后主力净流入线、下方蓝色实时主力净流入线（共享尺度），
 * Δ 徽章一眼显示实时相对盘后的加码/撤离。实时新增个股单独标注。
 * - postStockTop：来自 /api/money-flow 的盘后 sector→stock 链路 Top10
 * - rtStocks：PanoramaPage 单一轮询注入
 */
export default function StockCompareSection({ selectedDate, rtStocks, selectedStock, onSelectStock }) {
  const [moneyFlowData, setMoneyFlowData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!selectedDate) return;
    const controller = new AbortController();
    (async () => {
      const { ok, data } = await apiFetch(`/api/money-flow?date=${selectedDate}`, { signal: controller.signal });
      if (!ok) { setLoading(false); return; }
      setMoneyFlowData(data);
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate]);

  // 实时个股 Map（按 ts_code 索引）
  const realtimeMap = useMemo(() => {
    const m = new Map();
    (rtStocks?.stocks || []).forEach(s => m.set(s.ts_code, s));
    return m;
  }, [rtStocks]);

  // 盘后个股 Top10（仅 sector→stock 链路）
  const postStockTop = useMemo(() => {
    if (!moneyFlowData?.nodes || !moneyFlowData?.links) return [];
    const leaders = moneyFlowData.nodes.filter(n => n.category === 'leader');
    const leaderNames = new Set(leaders.map(n => n.name));
    const stockMap = new Map();
    moneyFlowData.links.forEach(l => {
      if (!leaderNames.has(l.target)) return;
      const ld = leaders.find(n => n.name === l.target);
      const prev = stockMap.get(l.target);
      if (prev) prev.value += l.value;
      else stockMap.set(l.target, {
        ts_code: l.target, name: ld?.label || l.target, value: l.value,
        price: ld?.price || 0, price_chg: ld?.price_chg || 0,
      });
    });
    return [...stockMap.values()].sort((a, b) => b.value - a.value).slice(0, 10);
  }, [moneyFlowData]);

  // 合并盘后 + 实时资金
  const compareList = useMemo(() => {
    return postStockTop.map(s => {
      const rt = realtimeMap.get(s.ts_code);
      return {
        ts_code: s.ts_code,
        name: s.name,
        sector: rt?.sector || '',
        postFlow: s.value,
        rtFlow: rt?.main_force_inflow ?? null,
        rtSources: rt?.sources_count ?? 0,
        price_chg: rt?.price_chg ?? s.price_chg ?? 0,
      };
    });
  }, [postStockTop, realtimeMap]);

  // 实时新增榜：实时 Top 中盘后未上榜
  const newcomers = useMemo(() => {
    const postCodes = new Set(postStockTop.map(s => s.ts_code));
    return (rtStocks?.stocks || [])
      .filter(s => !postCodes.has(s.ts_code))
      .sort((a, b) => (b.main_force_inflow || 0) - (a.main_force_inflow || 0))
      .slice(0, 5)
      .map(s => ({
        ts_code: s.ts_code,
        name: s.name,
        sector: s.sector || '',
        postFlow: null,
        rtFlow: s.main_force_inflow ?? 0,
        rtSources: s.sources_count ?? 0,
        price_chg: s.price_chg ?? 0,
      }));
  }, [rtStocks, postStockTop]);

  const dateLabel = selectedDate ? selectedDate.slice(5) : '';
  const allCards = [...compareList, ...newcomers];

  const renderCard = (item, idx, isNewcomer) => {
    const post = item.postFlow;
    const rt = item.rtFlow;
    const hasRt = rt != null;
    // Δ = 实时 − 盘后（仅两者都有时）
    const delta = hasRt && post != null ? rt - post : null;
    const deltaUp = delta != null && delta > 0;
    const deltaDown = delta != null && delta < 0;
    // 状态药丸
    let status = { text: '盘后上榜', color: '#a5b4fc', bg: 'rgba(99,102,241,0.15)' };
    if (isNewcomer) status = { text: '实时新增', color: '#f59e0b', bg: 'rgba(245,158,11,0.15)' };
    else if (deltaUp) status = { text: '实时加码', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' };
    else if (deltaDown) status = { text: '实时撤离', color: '#22c55e', bg: 'rgba(34,197,94,0.15)' };

    // 共享尺度（取两者绝对值最大）
    const maxAbs = Math.max(Math.abs(post || 0), Math.abs(rt || 0), 1);
    const postPct = post != null ? (Math.abs(post) / maxAbs) * 100 : 0;
    const rtPct = hasRt ? (Math.abs(rt) / maxAbs) * 100 : 0;
    const postPositive = (post || 0) >= 0;
    const rtPositive = (rt || 0) >= 0;

    const isSelected = selectedStock === item.ts_code;

    return (
      <div key={item.ts_code || idx}
        className="rounded-xl border p-2.5 cursor-pointer transition-all"
        style={{
          borderColor: isSelected ? 'rgba(56,189,248,0.6)' : 'var(--border-color)',
          background: 'var(--bg-card)',
          boxShadow: isSelected ? '0 0 0 1px rgba(56,189,248,0.4)' : 'none',
        }}
        onClick={() => onSelectStock?.(item.ts_code)}>
        {/* 头部 */}
        <div className="flex items-center justify-between gap-2 mb-2">
          <div className="flex items-center gap-1.5 min-w-0">
            <span className="text-xs font-bold flex-shrink-0" style={{ color: idx < 3 && !isNewcomer ? '#ef4444' : 'var(--text-muted)' }}>{idx + 1}</span>
            <span className="text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>{item.name}</span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{item.ts_code?.split('.')[0]}</span>
          </div>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold flex-shrink-0"
            style={{ background: status.bg, color: status.color }}>{status.text}</span>
        </div>

        {item.sector && (
          <div className="text-[10px] mb-2 truncate" style={{ color: 'var(--text-muted)' }}>📁 {item.sector}</div>
        )}

        {/* 盘后折线 */}
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[10px] w-8 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>📊盘后</span>
          <div className="flex-1 h-4 relative flex items-center" style={{ background: 'var(--bg-surface)', borderRadius: '4px' }}>
            {post != null ? (
              <>
                <div className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 rounded-full transition-all"
                  style={{ width: `${Math.max(postPct, 3)}%`, background: postPositive ? '#ef4444' : '#22c55e' }} />
                <div className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full transition-all border-2"
                  style={{ left: `calc(${Math.max(postPct, 3)}% - 5px)`, background: postPositive ? '#ef4444' : '#22c55e', borderColor: 'var(--bg-card)' }} />
              </>
            ) : (
              <div className="w-full text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>盘后未上榜</div>
            )}
          </div>
          <span className="text-[10px] w-16 text-right font-semibold tabular-nums flex-shrink-0"
            style={{ color: post != null ? (postPositive ? '#ef4444' : '#22c55e') : 'var(--text-muted)' }}>
            {post != null ? `${postPositive ? '+' : ''}${fmtFlow(post)}` : '—'}
          </span>
        </div>

        {/* 实时折线 */}
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[10px] w-8 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>⚡实时</span>
          <div className="flex-1 h-4 relative flex items-center" style={{ background: 'var(--bg-surface)', borderRadius: '4px' }}>
            {hasRt ? (
              <>
                <div className="absolute left-0 top-1/2 -translate-y-1/2 h-0.5 rounded-full transition-all"
                  style={{ width: `${Math.max(rtPct, 3)}%`, background: rtPositive ? '#3b82f6' : '#06b6d4' }} />
                <div className="absolute top-1/2 -translate-y-1/2 w-2.5 h-2.5 rounded-full transition-all border-2"
                  style={{ left: `calc(${Math.max(rtPct, 3)}% - 5px)`, background: rtPositive ? '#3b82f6' : '#06b6d4', borderColor: 'var(--bg-card)' }} />
              </>
            ) : (
              <div className="w-full text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>无实时快照</div>
            )}
          </div>
          <span className="text-[10px] w-16 text-right font-semibold tabular-nums flex-shrink-0"
            style={{ color: hasRt ? (rtPositive ? '#3b82f6' : '#06b6d4') : 'var(--text-muted)' }}>
            {hasRt ? `${rtPositive ? '+' : ''}${fmtFlow(rt)}` : '—'}
          </span>
        </div>

        {/* Δ 徽章 + 涨跌 */}
        <div className="flex items-center justify-between text-[10px] pt-1 border-t" style={{ borderColor: 'var(--border-color)' }}>
          <span style={{ color: 'var(--text-muted)' }}>
            涨跌 <span style={{ color: (item.price_chg || 0) > 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
              {(item.price_chg || 0) > 0 ? '+' : ''}{(item.price_chg || 0).toFixed(2)}%
            </span>
          </span>
          {delta != null ? (
            <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded font-bold"
              style={{ background: deltaUp ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)', color: deltaUp ? '#ef4444' : '#22c55e' }}>
              Δ {deltaUp ? '↑' : '↓'} {deltaUp ? '+' : ''}{fmtFlow(delta)}
            </span>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>{isNewcomer ? '盘后无数据' : '无实时对比'}</span>
          )}
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-2">
      {/* 区块标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2 pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>💰 资金对比 · 盘后 vs 实时</span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            红线=盘后 · 蓝线=实时 · Δ=实时−盘后{dateLabel ? ` · 盘后(${dateLabel})` : ''}
          </span>
        </div>
      </div>

      {/* 说明条 */}
      <div className="rounded-lg p-2 text-xs flex items-center gap-3 flex-wrap" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
        <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: '#ef4444' }} />盘后主力净流入</span>
        <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded-sm" style={{ background: '#3b82f6' }} />实时主力净流入</span>
        <span className="flex items-center gap-1"><span className="px-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>Δ↑实时加码</span></span>
        <span className="flex items-center gap-1"><span className="px-1 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>Δ↓实时撤离</span></span>
        <span className="flex items-center gap-1"><span className="px-1 rounded" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>实时新增</span></span>
      </div>

      {/* 对比卡片网格 */}
      {loading ? (
        <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>加载中...</div>
      ) : allCards.length === 0 ? (
        <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据</div>
      ) : (
        <>
          {compareList.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold mb-1.5 px-1" style={{ color: 'var(--text-muted)' }}>📈 盘后上榜个股 · 实时对比</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {compareList.map((item, i) => renderCard(item, i, false))}
              </div>
            </div>
          )}
          {newcomers.length > 0 && (
            <div>
              <div className="text-[11px] font-semibold mb-1.5 px-1 mt-2" style={{ color: '#f59e0b' }}>⚡ 实时新增（盘后未上榜）</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {newcomers.map((item, i) => renderCard(item, compareList.length + i, true))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
