import { useCallback, useEffect, useMemo, useState } from 'react';
import StockListContainer from '../StockListContainer';
import USWatchlistCard from './USWatchlistCard';
import USStockDetailDrawer from './USStockDetailDrawer';
import SinaLink from '../SinaLink';
import { usNameCN } from '../../utils/usStockNames';
import { usSectorCN } from '../../utils/usStockSectors';
import { apiFetch, formatApiError } from '../../utils/request';

const C = {
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  blue: 'var(--accent-blue)',
  amber: 'var(--accent-amber)',
};

const SORTS = [
  { key: 'score', label: '综合评分', desc: '技术综合分（高→低）' },
  { key: 'change_pct', label: '涨跌幅', desc: '当日涨跌幅' },
  { key: 'rsi', label: 'RSI', desc: '相对强弱（高→低）' },
  { key: 'ma50', label: 'MA50', desc: '50日均线（高→低）' },
];

const FACTOR_CN = { breakout: '突破', pullback: '回踩', overall: '综合' };

// usmart 卡片用动作色（与 USWatchlistCard.ACTION_COLORS 一致）
const ACTION_COLOR = {
  buy: '#ef4444', hold: '#f59e0b', reduce: '#f97316',
  sell: '#ef4444', stop: '#dc2626', scoop: '#22c55e', watch: '#94a3b8',
};

// 把扁平列表按板块分组（保持板块出现顺序）
function groupBySector(items) {
  const map = new Map();
  for (const it of items) {
    const sec = it.sector || usSectorCN(it.symbol) || '其他';
    if (!map.has(sec)) map.set(sec, []);
    map.get(sec).push(it);
  }
  return [...map.entries()];
}

/**
 * 单个股票池（universe）的成员视图：像 usmart 自选清单一样，卡片视图（按板块分组）+ 表格视图可切换。
 * 数据来源：/api/us-quant/universe/{code}/members + /api/us-quant/scanner?symbols= 算法评估。
 * 与 USWatchlistView 不同：股票池成员不可移除，故卡片不显示 × 按钮，且自带算法评分（七维因子 + 技术综合分）。
 */
export default function UniverseMembersView({ universeCode, market = 'US' }) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [sortKey, setSortKey] = useState('score');
  const [sortDir, setSortDir] = useState('desc');
  const [activeSector, setActiveSector] = useState('全部');
  const [lastUpdated, setLastUpdated] = useState(null);
  const [selectedStock, setSelectedStock] = useState(null);

  // 把单只候选折算成 usmart 卡片/表格共用的 indicators 结构
  const buildInd = (sym, c) => {
    const best = c?.best_factor_score ?? (Math.max(c?.breakout_score || 0, c?.pullback_score || 0) || null);
    const stateLabel = c?.state_label || '—';
    let action = 'watch';
    let actionLabel = '观察';
    if (stateLabel.includes('突破') && (c?.breakout_score || 0) >= 70) { action = 'buy'; actionLabel = '买入'; }
    else if (stateLabel.includes('回踩') && (c?.pullback_score || 0) >= 70) { action = 'scoop'; actionLabel = '低吸'; }
    else if (c?.rsi && c.rsi >= 70) { action = 'reduce'; actionLabel = '注意回调'; }
    const factorKey = c?.best_factor_key || (stateLabel.includes('突破') ? 'breakout' : stateLabel.includes('回踩') ? 'pullback' : null);
    return {
      score: best,
      factorKey,
      factorLabel: factorKey ? (FACTOR_CN[factorKey] || factorKey) : '—',
      stateLabel,
      action,
      actionLabel,
      actionColor: ACTION_COLOR[action] || C.muted,
      rsi: c?.rsi ?? null,
      ema20: c?.ema20 ?? null,
      ma50: c?.ma50 ?? null,
      stop_loss: c?.stop_loss ?? null,
      breakout_score: c?.breakout_score ?? null,
      pullback_score: c?.pullback_score ?? null,
    };
  };

  const load = useCallback(async () => {
    if (!universeCode) return;
    setLoading(true);
    setError(null);
    try {
      const mres = await apiFetch(`/api/us-quant/universe/${encodeURIComponent(universeCode)}/members`, {}, 10000, 0);
      if (!mres.ok) { setError(formatApiError(mres.error, '加载成员失败')); setLoading(false); return; }
      const members = mres.data?.members || [];
      let scores = {};
      if (members.length) {
        try {
          const sres = await apiFetch(`/api/us-quant/scanner?symbols=${encodeURIComponent(members.join(','))}`, {}, 60000, 0);
          if (sres.ok && sres.data?.candidates) {
            for (const cand of sres.data.candidates) if (cand.symbol) scores[cand.symbol] = cand;
          }
        } catch { /* 评分失败不阻断列表 */ }
      }
      const list = members.map((sym) => {
        const c = scores[sym] || {};
        const ind = buildInd(sym, c);
        return {
          symbol: sym,
          name: c.name || usNameCN(sym) || sym,
          sector: usSectorCN(sym) || '其他',
          price: c.price ?? null,
          change_pct: c.change_pct ?? null,
          indicators: ind,
        };
      });
      setItems(list);
      setLastUpdated(new Date());
    } catch {
      setError('网络错误');
    }
    setLoading(false);
  }, [universeCode]);

  useEffect(() => { load(); }, [load]);

  // 排序
  const sortedItems = useMemo(() => {
    const arr = [...items];
    const dir = sortDir === 'desc' ? -1 : 1;
    const getV = (it) => {
      const ind = it.indicators || {};
      switch (sortKey) {
        case 'score': return ind.score ?? -1;
        case 'change_pct': return it.change_pct ?? -999;
        case 'rsi': return ind.rsi ?? -1;
        case 'ma50': return ind.ma50 ?? -1;
        default: return 0;
      }
    };
    arr.sort((a, b) => (getV(a) - getV(b)) * dir);
    return arr;
  }, [items, sortKey, sortDir]);

  const sectorGroups = useMemo(() => groupBySector(sortedItems), [sortedItems]);
  const sectors = useMemo(() => ['全部', ...sectorGroups.map(([s]) => s)], [sectorGroups]);
  const filteredItems = useMemo(() => (
    activeSector === '全部' ? sortedItems
      : sortedItems.filter((it) => (it.sector || usSectorCN(it.symbol) || '其他') === activeSector)
  ), [sortedItems, activeSector]);

  

  // 卡片渲染：按板块分组，复用 usmart 卡片（股票池不可移除）
  const cardRenderer = useCallback((list) => (
    <div className="space-y-4">
      {groupBySector(list).map(([sector, group]) => {
        const upN = group.filter((s) => s.change_pct != null && s.change_pct > 0).length;
        const downN = group.filter((s) => s.change_pct != null && s.change_pct < 0).length;
        const avg = (() => {
          const vals = group.map((s) => s.change_pct).filter((v) => v != null);
          return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
        })();
        return (
          <div key={sector}>
            <div className="flex items-center gap-2 mb-2">
              <span className="text-xs font-semibold" style={{ color: C.secondary }}>{sector}</span>
              <span className="text-[11px]" style={{ color: C.muted }}>{group.length} 只</span>
              <span className="text-[10px]" style={{ color: C.up }}>{upN}↑</span>
              <span className="text-[10px]" style={{ color: C.down }}>{downN}↓</span>
              {avg != null && (
                <span className="text-[10px] font-semibold tabular-nums" style={{ color: avg >= 0 ? C.up : C.down }}>
                  均 {avg >= 0 ? '+' : ''}{avg.toFixed(2)}%
                </span>
              )}
              <span className="flex-1 h-px" style={{ background: C.borderLight }} />
            </div>
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
              {group.map((s) => (
                <USWatchlistCard key={s.symbol} stock={s} market={market} hideRemove onOpenDetail={setSelectedStock} />
              ))}
            </div>
          </div>
        );
      })}
    </div>
  ), [market]);

  // 表格渲染：保留原股票池的算法评分（评分 / 因子 / 状态 / 建议 / 行情）
  const tableRenderer = useCallback(() => (
    <div style={{ overflowX: 'auto' }}>
      <table className="w-full text-[12px]" style={{ borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ background: 'var(--bg-surface)' }}>
            <Th>代码</Th><Th>名称</Th><Th>板块</Th><Th align="right">最新价</Th><Th align="right">涨跌幅</Th>
            <Th align="center">评分</Th><Th>因子</Th><Th>状态</Th><Th>建议</Th><Th align="right">RSI</Th><Th align="right">MA50</Th><Th align="right">止损</Th><Th>行情</Th>
          </tr>
        </thead>
        <tbody>
          {filteredItems.map((s) => {
            const ind = s.indicators || {};
            const color = s.change_pct == null ? C.muted : s.change_pct >= 0 ? C.up : C.down;
            const scoreColor = ind.score == null ? C.muted : ind.score >= 70 ? C.up : ind.score >= 50 ? C.amber : C.muted;
            return (
              <tr key={s.symbol} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                <Td bold nowrap>{s.symbol}</Td>
                <Td nowrap>{s.name || '—'}</Td>
                <Td nowrap color={C.secondary}>{s.sector || '—'}</Td>
                <Td align="right" tabular>{s.price == null ? '—' : Number(s.price).toFixed(2)}</Td>
                <Td align="right" tabular color={color}>
                  {s.change_pct == null ? '—' : `${s.change_pct >= 0 ? '+' : ''}${s.change_pct.toFixed(2)}%`}
                </Td>
                <Td align="center">{ind.score != null ? <span className="font-bold" style={{ color: scoreColor }}>{Math.round(ind.score)}</span> : <span style={{ color: C.muted }}>—</span>}</Td>
                <Td nowrap color={C.secondary}>{ind.factorLabel || '—'}</Td>
                <Td nowrap color={C.muted}>{ind.stateLabel}</Td>
                <Td nowrap color={ind.actionColor} bold={ind.action !== 'watch'}>{ind.actionLabel}</Td>
                <Td align="right" tabular>{ind.rsi ?? '—'}</Td>
                <Td align="right" tabular>{ind.ma50 ?? '—'}</Td>
                <Td align="right" tabular color="#f97316">{ind.stop_loss ?? '—'}</Td>
                <Td nowrap><SinaLink market={market} code={s.symbol} size="xs" /></Td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  ), [filteredItems, market]);

  return (
    <div className="space-y-2">
      {(() => {
        const upN = filteredItems.filter((s) => s.change_pct != null && s.change_pct > 0).length;
        const downN = filteredItems.filter((s) => s.change_pct != null && s.change_pct < 0).length;
        const vals = filteredItems.map((s) => s.change_pct).filter((v) => v != null);
        const avg = vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null;
        const strongN = filteredItems.filter((s) => (s.indicators?.score ?? 0) >= 60).length;
        const weakN = filteredItems.filter((s) => (s.indicators?.score ?? 100) <= 30).length;
        return (
          <div
            className="flex items-center gap-3 px-3 py-1.5 rounded-lg text-[11px] flex-wrap"
            style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}
          >
            <span style={{ color: C.secondary }}>共 <b style={{ color: C.primary }}>{filteredItems.length}</b> 只</span>
            <span style={{ color: C.up }}>↑{upN}</span>
            <span style={{ color: C.down }}>↓{downN}</span>
            {avg != null && (
              <span className="font-semibold tabular-nums" style={{ color: avg >= 0 ? C.up : C.down }}>
                均 {avg >= 0 ? '+' : ''}{avg.toFixed(2)}%
              </span>
            )}
            <span className="h-3 w-px" style={{ background: C.borderLight }} />
            <span title="综合评分 ≥60" style={{ color: '#ef4444' }}>强势 {strongN}</span>
            <span title="综合评分 ≤30" style={{ color: '#22c55e' }}>弱势 {weakN}</span>
            {lastUpdated && (
              <span className="ml-auto" style={{ color: C.muted }}>
                更新 {lastUpdated.toLocaleTimeString('zh-CN', { hour12: false })}
              </span>
            )}
          </div>
        );
      })()}

      {/* 板块 tab 行 */}
      <div className="flex items-center gap-1 overflow-x-auto" style={{ scrollbarWidth: 'none' }}>
        {sectors.map((sec) => {
          const active = activeSector === sec;
          const count = sec === '全部'
            ? sortedItems.length
            : (sectorGroups.find(([s]) => s === sec)?.[1]?.length || 0);
          return (
            <button
              key={sec}
              onClick={() => setActiveSector(active ? '全部' : sec)}
              className="px-2 py-1 rounded-lg text-[11px] whitespace-nowrap flex-shrink-0"
              style={{
                background: active ? 'var(--bg-card)' : 'var(--bg-surface)',
                color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                border: active ? '1px solid var(--border-color)' : '1px solid transparent',
              }}
            >
              {sec} <span style={{ color: 'var(--text-muted)' }}>{count}</span>
            </button>
          );
        })}
      </div>

      <StockListContainer
        viewModeKey={`universe-members-${universeCode}`}
        defaultViewMode="card"
        showToggle
        toggleTitle="切换股票池阅读方式：卡片 / 表格"
        loading={loading}
        error={error}
        items={filteredItems}
        cardRenderer={cardRenderer}
        tableRenderer={tableRenderer}
        emptyText="该池暂无成员"
        loadingText="加载股票池成员..."
        headerExtra={
          <div className="flex items-center gap-2">
            <div className="relative" style={{ position: 'relative' }}>
              <select
                value={sortKey}
                onChange={(e) => setSortKey(e.target.value)}
                className="text-[11px] rounded px-1.5 py-1 cursor-pointer"
                style={{ background: 'transparent', border: `1px solid ${C.border}`, color: C.secondary }}
                title="排序字段"
              >
                {SORTS.map((s) => (
                  <option key={s.key} value={s.key}>{s.label}</option>
                ))}
              </select>
              <button
                onClick={() => setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))}
                className="text-[11px] ml-1 rounded px-1.5 py-1 cursor-pointer"
                style={{ background: 'transparent', border: `1px solid ${C.border}`, color: C.secondary }}
                title={sortDir === 'desc' ? '降序' : '升序'}
              >
                {sortDir === 'desc' ? '↓' : '↑'}
              </button>
            </div>
            <button
              onClick={load}
              style={{ background: 'transparent', border: `1px solid ${C.border}`, borderRadius: 6, padding: '3px 10px', fontSize: 11, cursor: 'pointer', color: C.secondary }}
            >↻ 重新评估</button>
          </div>
        }
      />

      {selectedStock && (
        <USStockDetailDrawer stock={selectedStock} market={market} onClose={() => setSelectedStock(null)} />
      )}
    </div>
  );
}

// ── 表格小工具 ──
function Th({ children, align }) {
  return (
    <th className="px-2 py-1.5 text-[11px] font-semibold" style={{ textAlign: align || 'left', color: C.muted, whiteSpace: 'nowrap' }}>
      {children}
    </th>
  );
}
function Td({ children, align, bold, color, nowrap, tabular }) {
  return (
    <td
      className="px-2 py-1.5"
      style={{
        textAlign: align || 'left',
        fontWeight: bold ? 700 : 400,
        color: color || C.primary,
        whiteSpace: nowrap ? 'nowrap' : 'normal',
        fontVariantNumeric: tabular ? 'tabular-nums' : undefined,
      }}
    >
      {children}
    </td>
  );
}
