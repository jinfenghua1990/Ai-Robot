import { useMemo } from 'react';
import StockListContainer from './StockListContainer';
import StrategySignalCard from './trading/StrategySignalCard';

/**
 * WatchlistResultsTable — 通用「自选式」结果表格
 *
 * 把任意策略/扫描产生的股票对象列表（rows）统一渲染成与 A股自选一致的
 * 卡片 + 18 列表格双视图：
 *  - 表格：复用 StockListContainer 默认 WatchlistTable（现价/成本·均线/MACD/KDJ·支撑压力·风险·建议·操作·自动交易）
 *  - 卡片：StrategySignalCard（或传入 cardComponent）
 *  - 字段缺失一律以 — 占位，保持逐列对齐；技术指标缺失时相关列显示 —。
 *
 * 用法：
 *   <WatchlistResultsTable
 *     items={data.stocks}
 *     viewModeKey="screener-some"
 *     loading={loading}
 *     tableProps={{ onRefresh, onAnalyze, ... }}
 *   />
 */
const toFinite = (v) => (v == null || isNaN(Number(v)) ? null : Number(v));

// 通用字段归一 → WatchlistTable 需要的 signal 结构（缺失字段以 undefined / 空对象占位）
const toWatchlistSignal = (r) => {
  const price = toFinite(r.close ?? r.latest_price ?? r.current_price);
  const changePct = toFinite(r.changePct ?? r.pct_chg ?? r.today_pct ?? r.change_pct);
  const score = toFinite(r.score ?? r.totalScore ?? r.composite_score);
  return {
    secCode: r.secCode ?? r.ts_code,
    secName: r.secName ?? r.name,
    code: r.secCode ?? r.ts_code,
    signalLabel: r.signalLabel ?? null,
    score,
    sector: r.sector ?? r.industry,
    latest_price: price,
    pct_chg: changePct,
    return_20d: toFinite(r.return_20d ?? r.chg_20d),
    // position：未持仓（策略候选），行内「数量/持仓盈亏/仓位」自然显示未持仓/—
    position: { price, dayProfitPct: changePct, avg_cost: null, count: 0, profitPct: null, posPct: null },
    quote: price != null ? { price, changePct } : null,
    moneyFlow: { main_net: toFinite(r.netInflow ?? r.mainNetIn), moneyFlow: r.moneyFlow },
    // 技术指标：策略对象提供的均线/MACD/KDJ/RSI 等尽量归于 indicators，缺失保持为空（表格显示 —）
    indicators: {
      ...(r.indicators || {}),
      ...(r.rsi != null ? { rsi: toFinite(r.rsi) } : {}),
      ...(r.ma5 != null ? { ma5: toFinite(r.ma5) } : {}),
      ...(r.ma10 != null ? { ma10: toFinite(r.ma10) } : {}),
      ...(r.ma20 != null ? { ma20: toFinite(r.ma20) } : {}),
      ...(r.ma60 != null ? { ma60: toFinite(r.ma60) } : {}),
      ...(r.ma60_slope_10d_pct != null ? { ma60_slope: toFinite(r.ma60_slope_10d_pct) } : {}),
      ...(r.dif != null || r.macd != null ? { macd: toFinite(r.macd ?? r.dif) } : {}),
      ...(r.kdj_k != null ? { kdj_k: toFinite(r.kdj_k) } : {}),
      ...(r.kdj_d != null ? { kdj_d: toFinite(r.kdj_d) } : {}),
      ...(r.kdj_j != null ? { kdj_j: toFinite(r.kdj_j) } : {}),
      ...(r.support != null ? { support: toFinite(r.support) } : {}),
      ...(r.resistance != null ? { resistance: toFinite(r.resistance) } : {}),
    },
    strategy: r.strategy ?? r.strategy_name,
    hitTags: r.strategy && r.strategy !== '手动' ? [String(r.strategy)] : [],
  };
};
export { toWatchlistSignal };

export default function WatchlistResultsTable({
  items = [],
  loading = false,
  error = null,
  viewModeKey = 'watchlist-results',
  defaultViewMode = 'card',
  groupBy = null,
  tableProps = {},
  cardComponent: Card = StrategySignalCard,
  cardProps = { mode: 'watchlist', showWatchBtn: true, showAnalysisButton: true },
  mapSignal = toWatchlistSignal,
  emptyText = '暂无结果',
  loadingText = '加载中...',
  onRetry,
}) {
  const effectiveItems = useMemo(() => (Array.isArray(items) ? items : []), [items]);
  // 卡片视图的 signal 用 memo 缓存，避免破坏 StrategySignalCard 的 memo
  const cards = useMemo(
    () => effectiveItems.map((r) => ({ key: (r.secCode ?? r.ts_code ?? r.secName ?? r.name ?? r.id), signal: mapSignal(r) })),
    [effectiveItems, mapSignal],
  );
  // 表格视图专用 signal 列表（与 WatchlistTable 对齐）
  const tableItems = useMemo(() => effectiveItems.map(mapSignal), [effectiveItems, mapSignal]);

  return (
    <StockListContainer
      viewModeKey={viewModeKey}
      defaultViewMode={defaultViewMode}
      loading={loading}
      error={error}
      items={effectiveItems}
      tableItems={tableItems}
      groupBy={groupBy}
      tableProps={tableProps}
      cardRenderer={(rows) => (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
          {rows.map((r) => {
            const key = (r.secCode ?? r.ts_code ?? r.secName ?? r.name ?? r.id);
            const cache = cards.find((c) => c.key === key);
            return <div key={key}><Card signal={cache?.signal || mapSignal(r)} {...cardProps} /></div>;
          })}
        </div>
      )}
      emptyText={emptyText}
      loadingText={loadingText}
      onRetry={onRetry}
    />
  );
}