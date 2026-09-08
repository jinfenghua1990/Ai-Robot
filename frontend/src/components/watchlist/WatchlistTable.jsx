import { memo, useCallback, useMemo, useState } from 'react';
import { UP_COLOR, DOWN_COLOR } from '../../utils/colors';
import { fmtPct2, fmtAmount, formatWan, toFiniteNumber } from '../../utils/format';
import StockActionButtons from '../trading/StockActionButtons';
import SinaLink from '../SinaLink';
import StockTableFrame, { STOCK_TABLE_SURFACE } from '../StockTableFrame';

/**
 * 自选股表格组件
 * 排版复用「A股持仓」完整 18 列富格式：固定列宽、横向滚动、首列固定、操作列固定、
 * 单元格分层展示（主指标 + 副指标）。缺失数据一律以 — 占位，保持逐列对齐。
 */
const UP_COLOR_CN = UP_COLOR;                 // 涨：红（中国市场约定）
const DOWN_COLOR_CN = DOWN_COLOR;             // 跌：绿

const EMPTY_TAGS = [];
const MUTED = 'var(--text-muted)';
// 可排序列：列头标签 → 排序键。排序值与下方每行单元格展示值保持同一来源（缺失数据排最后）。
const SORTABLE = {
  '当日盈亏 / 当日涨幅': 'dayPnl',
  '持仓盈亏 / 持仓收益率': 'profit',
  '仓位': 'posPct',
  '评分': 'score',
};
const sortValueOf = (signal, key) => {
  const position = signal.position || {};
  switch (key) {
    case 'score': return toFiniteNumber(signal.score);
    case 'dayPnl': return toFiniteNumber(position.dayProfit ?? signal.quote?.day_profit);
    case 'profit': return toFiniteNumber(position.profit);
    case 'posPct': return toFiniteNumber(position.posPct);
    default: return null;
  }
};
// dir: 1=升序(小→大)，-1=降序(大→小)；缺失值固定排最后，保持对齐。
const sortSignals = (list, key, dir) => {
  if (!key || !list?.length) return list;
  return [...list].sort((a, b) => {
    const va = sortValueOf(a, key);
    const vb = sortValueOf(b, key);
    const na = va == null;
    const nb = vb == null;
    if (na && nb) return 0;
    if (na) return 1;
    if (nb) return -1;
    return (va - vb) * dir;
  });
};
const TABLE_COLUMNS = [
  ['股票', 138, 'left', true],
  ['数量', 104, 'right', false],
  ['现价 / 成本价', 112, 'left', false],
  ['当日盈亏 / 当日涨幅', 126, 'left', false],
  ['持仓盈亏 / 持仓收益率', 136, 'left', false],
  ['仓位', 62, 'right', false],
  ['评分', 56, 'center', false],
  ['均线结构（MA5/20/60）', 190, 'left', false],
  ['RSI14', 56, 'center', false],
  ['MACD状态', 92, 'left', false],
  ['KDJ（K/D/J）', 104, 'left', false],
  ['换手率', 64, 'center', false],
  ['个股资金 / 板块', 148, 'left', false],
  ['支撑 / 压力位', 112, 'left', false],
  ['风险提示', 150, 'left', false],
  ['建议', 92, 'left', false],
  ['操作', 176, 'center', false],
  ['自动交易', 128, 'center', true],
];

const ACTION_COLOR = (a) => {
  const s = String(a || '');
  if (/卖出|减仓|退出|止损|止盈|清仓/.test(s)) return '#ef4444';
  if (/买入|加仓|开仓/.test(s)) return '#3b82f6';
  if (/观察|持有|继续/.test(s)) return '#f59e0b';
  return 'var(--text-muted)';
};

const num = (value, digits = 2) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : n.toFixed(digits);
};

const pct = (value, sign = true) => {
  if (value == null || isNaN(Number(value))) return '—';
  const n = Number(value);
  return `${sign && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

const fmtMoney = (value) => {
  if (value == null || isNaN(Number(value))) return '—';
  const a = Math.abs(Number(value));
  if (a >= 1e8) return `${(Number(value) / 1e8).toFixed(2)}亿`;
  if (a >= 1e4) return `${(Number(value) / 1e4).toFixed(1)}万`;
  return Number(value).toFixed(0);
};

const signedAmount = (value) => {
  const n = toFiniteNumber(value);
  return n == null ? '—' : `${n > 0 ? '+' : ''}${fmtAmount(n)}`;
};

function WatchlistTableRow({ signal, isSelected, onSelect, onRemove, onRefresh, onAnalyze, batchMode, checked, onToggleCheck, strategyTags = EMPTY_TAGS, realtimeFlow }) {
  const { secCode, secName, signalLabel, score, sector, sectorTrend, position = {}, quote, moneyFlow, indicators, hitTags } = signal;

  const rt = realtimeFlow || {};
  const changePct = toFiniteNumber(rt.price_chg != null ? rt.price_chg : quote?.changePct);
  const changeColor = changePct == null ? MUTED : changePct >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN;
  const price = toFiniteNumber(rt.price != null ? rt.price : quote?.price);
  const cost = toFiniteNumber(position?.costPrice);

  // 持仓
  const quantity = toFiniteNumber(position?.count);
  const marketValue = toFiniteNumber(position?.value ?? (price != null && quantity != null ? price * quantity : null));
  const profitPct = toFiniteNumber(position?.profitPct);
  const profit = toFiniteNumber(position?.profit);
  const dayPnl = toFiniteNumber(position?.dayProfit ?? quote?.day_profit);
  const posPct = toFiniteNumber(position?.posPct);
  const hasPos = (quantity ?? 0) > 0;

  // 技术指标（复用 A股持仓字段命名，缺失以 — 占位）
  const ind = indicators || {};
  const ma5Val = toFiniteNumber(ind.ma5);
  const ma20Val = toFiniteNumber(ind.ma20);
  const ma60Val = toFiniteNumber(ind.ma60);
  const ma20Slope = toFiniteNumber(ind.ma20_slope);
  const ma20Dist = (ma20Val != null && price != null) ? (price - ma20Val) / ma20Val * 100 : null;
  const maOrder = ma5Val != null && ma20Val != null
    ? (ma5Val >= ma20Val ? '短线多头' : '短线空头')
    : '—';
  const ma20Above = (ma20Val != null && price != null) ? price >= ma20Val : null;
  const rsi = toFiniteNumber(ind.rsi);
  const macdVal = toFiniteNumber(ind.macd);
  let macdTxt = '—';
  if (toFiniteNumber(ind.dif) != null && toFiniteNumber(ind.dea) != null) {
    macdTxt = toFiniteNumber(ind.dif) >= toFiniteNumber(ind.dea) ? (toFiniteNumber(ind.dif) >= 0 ? '零轴上金叉' : '零轴下金叉') : '死叉';
  } else if (macdVal != null) {
    macdTxt = macdVal >= 0 ? '多头' : '空头';
  }
  const kdjK = toFiniteNumber(ind.kdj_k != null ? ind.kdj_k : ind.kdj?.k);
  const kdjD = toFiniteNumber(ind.kdj_d != null ? ind.kdj_d : ind.kdj?.d);
  const kdjJ = toFiniteNumber(ind.kdj_j != null ? ind.kdj_j : ind.kdj?.j);
  const kdjState = kdjJ == null ? '—' : kdjJ >= 100 ? '超买' : kdjJ <= 0 ? '超卖' : (kdjK != null && kdjD != null && kdjK >= kdjD) ? '金叉偏强' : '死叉偏弱';
  const support = toFiniteNumber(ind.support);
  const resistance = toFiniteNumber(ind.resistance);

  // 风险提示（只在有真实信号时给出，避免臆造）
  const riskHints = [];
  if (rsi != null && rsi >= 70) riskHints.push({ text: 'RSI超买', tone: 'warn' });
  if (kdjState === '超买') riskHints.push({ text: 'KDJ超买', tone: 'warn' });
  if (ma20Above === false) riskHints.push({ text: '跌破MA20·止损观察', tone: 'danger' });
  if (support != null && price != null && price < support) riskHints.push({ text: '跌破支撑·止损关注', tone: 'danger' });
  if (/死叉/.test(macdTxt)) riskHints.push({ text: 'MACD死叉·收紧止损', tone: 'danger' });

  // 主力资金与板块（实时优先，单位一致：万元）
  const mainNet = toFiniteNumber(rt.main_force_inflow != null ? rt.main_force_inflow : moneyFlow?.main_net);
  const mainNetColor = mainNet == null ? MUTED : mainNet >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN;
  const sectorState = sectorTrend?.flow_direction === 'inflow' ? '资金流入' : sectorTrend?.flow_direction === 'outflow' ? '资金流出' : sectorTrend?.heat_trend === 'up' ? '板块升温' : sectorTrend?.heat_trend === 'down' ? '板块降温' : '板块中性';
  const sectorHeat = toFiniteNumber(sectorTrend?.latest_heat);
  const heatColor = sectorHeat == null ? MUTED : sectorHeat >= 60 ? '#ef4444' : sectorHeat >= 40 ? '#eab308' : '#3b82f6';

  // 换手率（实时）
  const turnover = toFiniteNumber(rt.turnover_rate != null ? rt.turnover_rate : ind.turnover_rate);

  // 建议（优先真实 signalLabel，命中的标签作为兜底）
  const action = signalLabel || (hitTags?.length ? hitTags[0] : '观察');

  const hitTagsStr = hitTags?.length ? hitTags.join(', ') : '';
  const strategyStr = strategyTags?.length ? strategyTags.join(', ') : '';

  const rowBackground = isSelected
    ? 'linear-gradient(rgba(59,130,246,0.12), rgba(59,130,246,0.12)), var(--bg-card)'
    : batchMode && checked
      ? 'linear-gradient(rgba(249,115,22,0.08), rgba(249,115,22,0.08)), var(--bg-card)'
      : hasPos && profitPct != null
        ? profitPct >= 0
          ? 'linear-gradient(rgba(239,68,68,0.04), rgba(239,68,68,0.04)), var(--bg-card)'
          : 'linear-gradient(rgba(34,197,94,0.04), rgba(34,197,94,0.04)), var(--bg-card)'
        : 'var(--bg-card)';
  const stockLeft = batchMode ? 32 : 0;

  const handleClick = useCallback((event) => {
    if (event.target.closest('button,a,input,select')) return;
    if (batchMode) onToggleCheck?.(secCode);
    else onSelect?.(secCode);
  }, [secCode, batchMode, onToggleCheck, onSelect]);

  return (
    <tr
      data-stock-code={secCode}
      onClick={handleClick}
      className="cursor-pointer transition-opacity hover:opacity-90"
      style={{
        background: rowBackground,
        borderTop: isSelected ? '1px solid rgba(59,130,246,0.5)' : '1px solid var(--border-color)',
      }}
    >
      {batchMode && (
        <td className="sticky left-0 z-[3] w-8 px-1 py-1 text-center" style={{ width: 32, minWidth: 32, background: rowBackground }}>
          <input type="checkbox" checked={!!checked} onChange={() => onToggleCheck?.(secCode)} onClick={(event) => event.stopPropagation()} className="h-3.5 w-3.5 cursor-pointer" />
        </td>
      )}

      {/* 股票（固定左） */}
      <td
        className="sticky z-[2] px-2 py-1 whitespace-nowrap"
        style={{
          left: stockLeft,
          width: 138,
          minWidth: 138,
          background: rowBackground,
          boxShadow: `${isSelected ? 'inset 3px 0 0 #3b82f6, ' : ''}1px 0 0 var(--border-color)`,
        }}
      >
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="font-bold" style={{ color: isSelected ? '#2563eb' : 'var(--text-primary)' }} title={secName}>{secName || '—'}</span>
          <span className="text-[9px]" style={{ color: MUTED }}>{secCode}</span>
          <SinaLink tsCode={secCode} size="xs" />
          {(profitPct ?? 0) < 0 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: DOWN_COLOR_CN }}>亏</span>}
        </div>
        <div className="mt-0.5 flex min-w-0 items-center gap-1 text-[9px]">
          {sector && <span className="max-w-[72px] truncate rounded px-1" style={{ background: `${heatColor}12`, color: heatColor }} title={sector}>{sector}</span>}
          {strategyStr && <span className="max-w-[86px] truncate rounded px-1" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }} title={strategyStr}>{strategyStr}</span>}
          {hitTagsStr && <span className="max-w-[86px] truncate rounded px-1" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title={hitTagsStr}>{hitTagsStr}</span>}
        </div>
      </td>

      {/* 数量 */}
      <td className="px-2 py-1 whitespace-nowrap text-right" style={{ color: 'var(--text-secondary)' }}>
        {hasPos ? <>
          <div>{quantity != null ? `${quantity}股` : '—'}</div>
          <div className="text-[10px]" style={{ color: MUTED }}>持仓金额 {marketValue != null ? formatWan(marketValue) : '—'}</div>
        </> : <span style={{ color: MUTED }}>未持仓</span>}
      </td>

      {/* 现价 / 成本价 */}
      <td className="px-2 py-1 whitespace-nowrap">
        <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>现价 {price != null ? num(price) : '—'}</div>
        <div style={{ color: MUTED }}>成本 {cost != null ? num(cost) : '—'}</div>
      </td>

      {/* 当日盈亏 / 当日涨幅 */}
      <td className="px-2 py-1 whitespace-nowrap">
        <div style={{ color: (dayPnl ?? 0) >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN, fontWeight: 600 }}>盈亏 {fmtMoney(dayPnl)}</div>
        <div style={{ color: changeColor }}>涨幅 {pct(changePct)}</div>
      </td>

      {/* 持仓盈亏 / 持仓收益率 */}
      <td className="px-2 py-1 whitespace-nowrap">
        {hasPos ? <>
          <div style={{ color: (profit ?? 0) >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN, fontWeight: 600 }}>盈亏 {fmtMoney(profit)}</div>
          <div style={{ color: profitPct == null ? MUTED : profitPct >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN }}>收益 {pct(profitPct)}</div>
        </> : <span style={{ color: MUTED }}>未持仓</span>}
      </td>

      {/* 仓位 */}
      <td className="px-2 py-1 text-right" style={{ color: 'var(--text-secondary)' }}>
        {posPct != null ? `${num(posPct, 1)}%` : '—'}
      </td>

      {/* 评分 */}
      <td className="px-2 py-1 text-center">
        {score != null ? (
          <span className="font-bold" style={{ color: score >= 70 ? UP_COLOR_CN : score >= 55 ? '#f59e0b' : 'var(--text-muted)' }}>{Math.round(score)}</span>
        ) : <span style={{ color: MUTED }}>—</span>}
      </td>

      {/* 均线结构（MA5/20/60） */}
      <td
        className="px-2 py-1 whitespace-nowrap cursor-help"
        title={'MA5、MA20、MA60 为对应交易日收盘价均线；现价偏离 MA20 的百分比不是收益率。'}
      >
        <div className="font-mono text-[10px]">
          <span style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>MA5 {num(ma5Val)}</span>
          <span style={{ color: 'var(--border-color)' }}> · </span>
          <span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>MA20 {num(ma20Val)}</span>
          <span style={{ color: 'var(--border-color)' }}> · </span>
          <span style={{ color: MUTED }}>MA60 {num(ma60Val)}</span>
        </div>
        <div style={{ color: ma20Above == null ? MUTED : ma20Above ? UP_COLOR_CN : DOWN_COLOR_CN, fontWeight: 600 }}>
          {maOrder} {ma20Above != null ? (ma20Above ? '· 现价高于 MA20' : '· 现价低于 MA20') : ''}
          {ma20Dist != null ? ` ${ma20Dist >= 0 ? '+' : ''}${num(ma20Dist, 1)}%` : ''}
        </div>
        <div className="text-[10px]" style={{ color: MUTED }}>
          {ma20Slope == null ? 'MA20斜率：—' : `MA20斜率：${ma20Slope >= 0 ? '+' : ''}${num(ma20Slope, 1)}%`}
        </div>
      </td>

      {/* RSI14 */}
      <td className="px-2 py-1 text-center" title="RSI14：14日相对强弱指标，通常 70 以上偏超买，30 以下偏超卖。" style={{ color: rsi == null ? MUTED : rsi >= 70 ? UP_COLOR_CN : rsi <= 30 ? DOWN_COLOR_CN : 'var(--text-secondary)' }}>
        {rsi != null ? num(rsi, 0) : '—'}
      </td>

      {/* MACD状态 */}
      <td className="px-2 py-1 whitespace-nowrap" title="MACD状态：金叉/死叉表示 DIF 与 DEA 的交叉，零轴上/下表示多空背景。" style={{ color: /金叉/.test(macdTxt) ? UP_COLOR_CN : /死叉/.test(macdTxt) ? DOWN_COLOR_CN : 'var(--text-muted)' }}>{macdTxt}</td>

      {/* KDJ（K/D/J） */}
      <td className="px-2 py-1 whitespace-nowrap" title="KDJ：K、D、J 为随机指标三条线；金叉偏强，死叉偏弱，J值极高/极低提示超买/超卖。">
        <div className="font-mono text-[10px]" style={{ color: 'var(--text-secondary)' }}>K {num(kdjK, 1)} / D {num(kdjD, 1)} / J {num(kdjJ, 1)}</div>
        <div style={{ color: /金叉|超买/.test(kdjState) ? UP_COLOR_CN : /死叉|超卖/.test(kdjState) ? DOWN_COLOR_CN : 'var(--text-muted)' }}>{kdjState}</div>
      </td>

      {/* 换手率 */}
      <td className="px-2 py-1 text-center" title="换手率：当日成交股数占流通股本的比例，用于衡量交易活跃度。" style={{ color: turnover == null ? MUTED : 'var(--text-secondary)' }}>
        {turnover != null ? `${num(turnover, 1)}%` : '—'}
      </td>

      {/* 个股资金 / 板块 */}
      <td className="px-2 py-1 whitespace-nowrap" title="个股资金为行情估算的主力净买入/净卖出；板块信息用于判断所属行业热度和资金方向。">
        <div style={{ color: mainNetColor }}>主力 {mainNet == null ? '—' : signedAmount(mainNet * 10000)}</div>
        <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{sector || '—'} · {sectorState}{sectorHeat != null ? ` ${num(sectorHeat, 1)}` : ''}</div>
      </td>

      {/* 支撑 / 压力位 */}
      <td className="px-2 py-1 whitespace-nowrap" title="支撑位：价格回落时可能获得承接的位置；压力位：价格上涨时可能遇到抛压的位置。" style={{ color: MUTED }}>
        {support != null ? `支撑 ${num(support)}` : '支撑 —'}{resistance != null ? ` · 压力 ${num(resistance)}` : ' · 压力 —'}
      </td>

      {/* 风险提示 */}
      <td className="px-2 py-1" title="技术风险提示仅供复核，不会自动改变持仓或触发交易。">
        {riskHints.length > 0 ? (
          <div className="flex flex-wrap gap-1">
            {riskHints.map((h) => <span key={h.text} className="px-1 py-0.5 rounded text-[9px] whitespace-nowrap" style={{ background: h.tone === 'danger' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.14)', color: h.tone === 'danger' ? '#ef4444' : '#d97706' }}>{h.text}</span>)}
          </div>
        ) : <span style={{ color: MUTED }}>暂无明显风险</span>}
      </td>

      {/* 建议 */}
      <td className="px-2 py-1 whitespace-nowrap font-medium" style={{ color: ACTION_COLOR(action) }}>{action}</td>

      {/* 操作 */}
      <td className="px-2 py-1 text-center" style={{ background: rowBackground, width: 176, maxWidth: 176, overflow: 'hidden' }}>
        {!batchMode && (
          <StockActionButtons
            stockCode={secCode}
            stockName={secName}
            signal={signal}
            positionCount={quantity || 0}
            showBuy
            showSell={false}
            showTrack={false}
            showWatch={false}
            showSina={false}
            showMore
            showAutoTrade={false}
            showKline
            showAnalysis
            onAnalyze={onAnalyze}
            layout="inline"
            size="xs"
            className="justify-center"
            onRefresh={onRefresh}
            onRemove={onRemove}
          />
        )}
      </td>

      {/* 自动交易（固定右，自选暂无自动交易引擎，占位为关闭） */}
      <td className="px-2 py-1 text-center sticky right-0 z-[2]" style={{ background: rowBackground }}>
        <span className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)', background: 'transparent' }}>关闭</span>
      </td>
    </tr>
  );
}

const MemoRow = memo(WatchlistTableRow);

export default function WatchlistTable({ stocks, groupBy, selectedCode, onSelect, onRemove, onRefresh, onAnalyze, batchMode, selectedIds, onToggleCheck, strategyPicks, realtimeFlow }) {
  const selectedIdSet = useMemo(() => new Set(selectedIds || []), [selectedIds]);
  // 列头排序状态：key=排序键，dir=1升序/-1降序；默认按评分降序（高分在前）
  const [sort, setSort] = useState({ key: null, dir: -1 });
  const toggleSort = useCallback((key) => {
    setSort((prev) => prev.key === key ? { key, dir: prev.dir === 1 ? -1 : 1 } : { key, dir: -1 });
  }, []);

  const groups = useMemo(() => {
    if (!groupBy || !stocks?.length) return null;
    const map = new Map();
    stocks.forEach((stock) => {
      const rawKey = typeof groupBy === 'function' ? groupBy(stock) : stock[groupBy];
      const key = rawKey || '未分类';
      if (!map.has(key)) map.set(key, []);
      map.get(key).push(stock);
    });
    return Array.from(map.entries()).map(([groupKey, items]) => ({
      groupKey,
      items,
      avgChg: items.reduce((sum, stock) => sum + (toFiniteNumber(stock.quote?.changePct) ?? 0), 0) / items.length,
    }));
  }, [stocks, groupBy]);

  const colSpan = batchMode ? TABLE_COLUMNS.length + 1 : TABLE_COLUMNS.length;
  const tableMinWidth = TABLE_COLUMNS.reduce((sum, [, width]) => sum + width, batchMode ? 32 : 0);
  const stockLeft = batchMode ? 32 : 0;

  const renderRows = (list) => {
    const sorted = sortSignals(list, sort.key, sort.dir);
    return sorted.map((signal) => (
      <MemoRow
        key={signal.secCode}
        signal={signal}
        isSelected={selectedCode === signal.secCode}
        onSelect={onSelect}
        onRemove={signal.poolSources?.includes('自选') ? onRemove : undefined}
        onRefresh={onRefresh}
        onAnalyze={onAnalyze}
        batchMode={batchMode}
        checked={selectedIdSet.has(signal.secCode)}
        onToggleCheck={onToggleCheck}
        strategyTags={strategyPicks?.[signal.secCode] || EMPTY_TAGS}
        realtimeFlow={realtimeFlow?.[signal.secCode] || null}
      />
    ));
  };

  return (
    <StockTableFrame minWidth={tableMinWidth} tableLayout="fixed">
        <thead>
          <tr style={{ background: STOCK_TABLE_SURFACE }}>
            {batchMode && <th className="sticky left-0 z-[4] w-8 px-1 py-1.5 text-center font-semibold" style={{ width: 32, minWidth: 32, color: MUTED, background: STOCK_TABLE_SURFACE }}>□</th>}
            {TABLE_COLUMNS.map(([label, width, align, sticky]) => {
              const sortKey = SORTABLE[label];
              const active = sort.key === sortKey;
              return (
                <th key={label} className="px-2 py-1.5 font-semibold whitespace-nowrap" style={{
                  color: MUTED,
                  width,
                  minWidth: width,
                  textAlign: align,
                  position: sticky ? 'sticky' : 'static',
                  left: sticky ? stockLeft : undefined,
                  right: sticky ? 0 : undefined,
                  zIndex: sticky ? 3 : 1,
                  background: STOCK_TABLE_SURFACE,
                  boxShadow: sticky ? '1px 0 0 var(--border-color)' : 'none',
                }}>
                  {sortKey ? (
                    <button
                      type="button"
                      tabIndex={-1}
                      onClick={(event) => { event.stopPropagation(); toggleSort(sortKey); }}
                      title={active ? (sort.dir === -1 ? '降序' : '升序') : `按「${label.replace(/ \/ .*/, '')}」排序`}
                      className="inline-flex items-center gap-1 whitespace-nowrap"
                      style={{
                        all: 'unset',
                        cursor: 'pointer',
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: 3,
                        color: active ? 'var(--accent-blue)' : 'inherit',
                        textAlign: 'left',
                      }}
                    >
                      {label}
                      <span className="font-mono" style={{ fontSize: 9, lineHeight: 1, color: active ? 'var(--accent-blue)' : 'var(--text-muted)', opacity: active ? 1 : 0.7 }}>{active ? (sort.dir === -1 ? '▼' : '▲') : '↕'}</span>
                    </button>
                  ) : label}
                </th>
              );
            })}
          </tr>
        </thead>
        {groups ? groups.map(({ groupKey, items, avgChg }) => (
          <tbody key={groupKey}>
            <tr style={{ background: STOCK_TABLE_SURFACE, borderTop: '1px solid var(--border-color)' }}>
              <td colSpan={colSpan} className="px-3 py-1">
                <div className="flex items-center gap-2">
                  <span className="h-3 w-1 rounded" style={{ background: '#6366f1' }} />
                  <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{groupKey}</span>
                  <span className="rounded px-1 text-[9px]" style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1' }}>{items.length}只</span>
                  <span className="font-mono text-[9px] font-bold" style={{ color: avgChg >= 0 ? UP_COLOR_CN : DOWN_COLOR_CN }}>均 {fmtPct2(avgChg)}</span>
                </div>
              </td>
            </tr>
            {renderRows(items)}
          </tbody>
        )) : <tbody>{renderRows(stocks || [])}</tbody>}
        <tfoot>
          <tr style={{ borderTop: '2px solid var(--border-color)', background: STOCK_TABLE_SURFACE }}>
            <td colSpan={colSpan} className="px-3 py-2">
              <div className="flex items-center gap-4">
                <span style={{ color: MUTED }}>合计 {stocks?.length || 0} 只</span>
                <span className="flex-1" />
                <span style={{ color: MUTED }}>点击整行选中 · 左右滑动查看更多 · 操作列固定 · 缺失数据以 — 占位</span>
              </div>
            </td>
          </tr>
        </tfoot>
    </StockTableFrame>
  );
}