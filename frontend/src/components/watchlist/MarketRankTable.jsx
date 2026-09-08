import { memo, useState, useCallback, useEffect } from 'react';
import { apiFetch } from '../../utils/request';

/** 金额格式化（模块级，避免每次渲染重建） */
function fmtMoney(v) {
  if (v == null) return '-';
  const a = Math.abs(v);
  if (a >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (a >= 1e4) return (v / 1e4).toFixed(0) + '万';
  return String(Math.round(v));
}

/**
 * 全市场资金流排行（东财批量排行榜，单次请求 50 条）
 * - 折叠面板：点击头部切换展开/收起
 * - 双 Tab：净流入 / 净流出
 * - 错误重试：东财接口偶发限流时提示重试
 */
function MarketRankTable({ defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const [tab, setTab] = useState('inflow');
  const [rank, setRank] = useState(null); // { inflow:{items,updated_at}, outflow:{...} }

  const loadRank = useCallback(async (type) => {
    const { ok, data } = await apiFetch(`/api/watchlist/market-capital-ranking?rtype=${type}&top=50`);
    if (ok) setRank(prev => ({ ...prev, [type]: data }));
  }, []);

  // 首次展开时拉取两个 Tab 数据
  useEffect(() => {
    if (!open) return;
    if (!rank?.inflow) loadRank('inflow');
    if (!rank?.outflow) loadRank('outflow');
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  const current = rank?.[tab];
  const items = current?.items || [];

  return (
    <div className="rounded-xl border mt-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between px-3 py-2">
        <button onClick={() => setOpen(o => !o)} className="flex items-center gap-2 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
          <span>{open ? '▾' : '▸'}</span>
          <span>🌐 全市场资金流</span>
          <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>主力净流入/流出 Top 50 · 共 5537 只 A 股</span>
        </button>
        {open && (
          <div className="flex items-center gap-1.5">
            <div className="flex rounded-lg overflow-hidden border" style={{ borderColor: 'var(--border-color)' }}>
              <button
                onClick={() => { setTab('inflow'); if (!rank?.inflow) loadRank('inflow'); }}
                className="px-2.5 py-1 text-[11px]"
                style={{ background: tab === 'inflow' ? 'rgba(239,68,68,0.15)' : 'transparent', color: tab === 'inflow' ? '#ef4444' : 'var(--text-secondary)' }}
              >🔥 净流入</button>
              <button
                onClick={() => { setTab('outflow'); if (!rank?.outflow) loadRank('outflow'); }}
                className="px-2.5 py-1 text-[11px]"
                style={{ background: tab === 'outflow' ? 'rgba(59,130,246,0.15)' : 'transparent', color: tab === 'outflow' ? 'var(--accent-blue)' : 'var(--text-secondary)' }}
              >💧 净流出</button>
            </div>
            <button onClick={() => loadRank(tab)} className="px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄</button>
          </div>
        )}
      </div>
      {open && (
        <div className="px-3 pb-3">
          {current?.updated_at && <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>更新于 {current.updated_at}</div>}
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr style={{ color: 'var(--text-muted)' }}>
                  <th className="text-left py-1 px-1 font-medium">#</th>
                  <th className="text-left py-1 px-1 font-medium">代码</th>
                  <th className="text-left py-1 px-1 font-medium">名称</th>
                  <th className="text-right py-1 px-1 font-medium">现价</th>
                  <th className="text-right py-1 px-1 font-medium">涨跌幅</th>
                  <th className="text-right py-1 px-1 font-medium">主力净流入</th>
                  <th className="text-right py-1 px-1 font-medium">占比</th>
                </tr>
              </thead>
              <tbody>
                {items.length === 0 && current?.error && (
                  <tr>
                    <td colSpan={7} className="text-center py-4" style={{ color: '#f59e0b' }}>
                      排行榜加载失败（东财接口偶发限流），<button onClick={() => loadRank(tab)} className="underline">点此重试</button>
                    </td>
                  </tr>
                )}
                {items.length === 0 && !current?.error && (
                  <tr><td colSpan={7} className="text-center py-4" style={{ color: 'var(--text-muted)' }}>加载中…</td></tr>
                )}
                {items.map((it, i) => {
                  const up = (it.main_net || 0) >= 0;
                  const pctUp = (it.pct || 0) >= 0;
                  return (
                    <tr key={it.code} style={{ borderTop: '1px solid var(--border-color)' }}>
                      <td className="py-1 px-1" style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                      <td className="py-1 px-1" style={{ color: 'var(--text-secondary)' }}>{it.code}</td>
                      <td className="py-1 px-1 font-medium" style={{ color: 'var(--text-primary)' }}>{it.name}</td>
                      <td className="py-1 px-1 text-right">{it.price != null ? it.price.toFixed(2) : '-'}</td>
                      <td className="py-1 px-1 text-right" style={{ color: pctUp ? '#ef4444' : 'var(--accent-green)' }}>
                        {it.pct != null ? (pctUp ? '+' : '') + it.pct.toFixed(2) + '%' : '-'}
                      </td>
                      <td className="py-1 px-1 text-right font-semibold" style={{ color: up ? '#ef4444' : 'var(--accent-green)' }}>
                        {up ? '+' : ''}{fmtMoney(it.main_net)}
                      </td>
                      <td className="py-1 px-1 text-right" style={{ color: up ? '#ef4444' : 'var(--accent-green)' }}>
                        {it.main_net_pct != null ? (up ? '+' : '') + it.main_net_pct.toFixed(2) + '%' : '-'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}

export default memo(MarketRankTable);
