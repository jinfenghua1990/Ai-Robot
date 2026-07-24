/**
 * StrategySignalCard — 策略中心专用卡片
 *
 * 设计理念：为快速扫描决策而生，不是 V4 的翻版。
 * 信息层级：股票名 > BS 区间 > 技术指标 > 板块 > 操作
 *
 * 兼容接口：signal / prefetchedDash / awaitParentPrefetch / showWatchBtn / showAnalysisButton
 * 可作为 StrategyResultsTable 的 cardComponent 使用
 */
import { useState, useRef, useEffect, useMemo, memo } from 'react';
import StockActionButtons from './StockActionButtons';
import { apiFetch } from '../../utils/request';

// ===== 工具函数 =====

const calcEma = (arr, n) => {
  const k = 2 / (n + 1);
  let prev = arr[0];
  return arr.map((v, i) => (prev = i === 0 ? v : v * k + prev * (1 - k)));
};

const calcIntradayMacd = (idPrices) => {
  if (idPrices.length < 26) return null;
  const e12 = calcEma(idPrices, 12);
  const e26 = calcEma(idPrices, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = calcEma(dif, 9);
  const n = dif.length;
  return { dif: dif[n - 1], dea: dea[n - 1], macd: 2 * (dif[n - 1] - dea[n - 1]) };
};

const calcIntradayKdj = (idPrices) => {
  const N = 9;
  if (idPrices.length < N) return null;
  let k = 50, d = 50;
  for (let i = N - 1; i < idPrices.length; i++) {
    const win = idPrices.slice(i - N + 1, i + 1);
    const hh = Math.max(...win), ll = Math.min(...win);
    const rsv = hh === ll ? 50 : ((idPrices[i] - ll) / (hh - ll)) * 100;
    k = (2 / 3) * k + (1 / 3) * rsv;
    d = (2 / 3) * d + (1 / 3) * k;
  }
  return { k, d, j: 3 * k - 2 * d };
};

const fmtYuan = (v) => {
  const abs = Math.abs(v || 0);
  if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
  if (abs >= 1e4) return `${(v / 1e4).toFixed(2)}万`;
  return `${(v || 0).toFixed(0)}`;
};

const fmtWanYi = (v, fromYuan = false) => {
  const wan = fromYuan ? (v || 0) / 10000 : (v || 0);
  if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
  return `${wan.toFixed(fromYuan ? 2 : 0)}万`;
};

// ===== 分时图交易时段 =====

const TRADING_SESSIONS = [
  { start: 9 * 60 + 30, end: 11 * 60 + 30 },
  { start: 13 * 60, end: 15 * 60 },
];
const TOTAL_TRADING_MINUTES = 240;

function timeStrToMinutes(t) {
  if (!t || typeof t !== 'string') return null;
  const m = t.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

function minuteToX(minute, W) {
  let pos = 0;
  for (const s of TRADING_SESSIONS) {
    if (minute < s.start) break;
    if (minute <= s.end) {
      pos += (minute - s.start);
      return (pos / TOTAL_TRADING_MINUTES) * W;
    }
    pos += (s.end - s.start);
  }
  return W;
}

// ===== 子组件：迷你分时图 =====

function MiniSpark({ data, width = 48, height = 16, className = '' }) {
  if (!data || data.length < 2) return null;
  const W = 240, H = height, pad = 4;
  const prices = data.map((d) => d.price).filter((v) => v != null);
  if (prices.length < 2) return null;
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min || 1;
  const up = (data[data.length - 1].pct_chg ?? 0) >= 0;
  const stroke = up ? '#ef4444' : '#22c55e';
  const x = (d) => { const m = timeStrToMinutes(d.t); return m == null ? 0 : minuteToX(m, W); };
  const y = (p) => pad + (1 - (p - min) / span) * (H - 2 * pad);
  const pts = data.map((d) => (d.price == null ? null : `${x(d).toFixed(1)},${y(d.price).toFixed(1)}`)).filter(Boolean);
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width={width} height={H} preserveAspectRatio="none" className={className} style={{ display: 'block', flexShrink: 0 }}>
      <polyline points={pts.join(' ')} fill="none" stroke={stroke} strokeWidth={1.5} strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ===== 主组件 =====

function StrategySignalCardInner({
  signal,
  showWatchBtn = true,
  showBuyBtn,
  showAnalysisButton = false,
  onAnalyze,
  showActionButton = true,
  onRefresh,
  onRemove,
  prefetchedDash = null,
  awaitParentPrefetch = false,
}) {
  const code = signal?.secCode;
  const [dash, setDash] = useState(prefetchedDash);
  const [loading, setLoading] = useState(prefetchedDash ? false : true);
  const dashRef = useRef(dash);
  useEffect(() => { dashRef.current = dash; }, [dash]);

  useEffect(() => {
    if (prefetchedDash && prefetchedDash !== dashRef.current) {
      setDash(prefetchedDash);
      setLoading(false);
    }
  }, [prefetchedDash]);

  const rootRef = useRef(null);
  const visibleRef = useRef(false);

  // 数据加载（IntersectionObserver + 自动刷新）
  useEffect(() => {
    if (!code) return;
    let active = true;
    let timer = null;

    if (prefetchedDash) {
      setLoading(false);
      if (prefetchedDash?.realtime?.mode === 'live') {
        timer = setTimeout(async () => {
          if (!active) return;
          try {
            const { ok, data } = await apiFetch(`/api/stock-dashboard/${code}`);
            if (active && ok && data && !data.error) setDash(data);
          } catch { /* keep last */ }
        }, 60000);
      }
      return () => { active = false; if (timer) clearTimeout(timer); };
    }

    if (awaitParentPrefetch) {
      setLoading(true);
      return () => { active = false; };
    }

    setLoading(true);
    const load = async () => {
      try {
        const { ok, data } = await apiFetch(`/api/stock-dashboard/${code}`);
        if (!active) return;
        if (ok && data && !data.error) setDash(data);
      } catch { /* ignore */ }
    };

    const schedule = () => {
      if (timer) { clearTimeout(timer); timer = null; }
      // 仅在「可见」且「盘中实时(live)」时轮询；不可见或盘后(非live)一律停轮询，避免 100+ 张卡后台狂打后端
      if (!visibleRef.current) return;
      if (dashRef.current?.realtime?.mode !== 'live') return;
      timer = setTimeout(async () => { if (active) { await load(); schedule(); } }, 30000);
    };

    let io = null;
    const start = () => { load().finally(() => { if (active) setLoading(false); }); schedule(); };
    if (typeof IntersectionObserver !== 'undefined' && rootRef.current) {
      io = new IntersectionObserver((entries) => {
        const vis = entries.some((e) => e.isIntersecting);
        if (vis === visibleRef.current) return;
        visibleRef.current = vis;
        if (vis) { if (active) start(); } else { schedule(); }
      }, { threshold: 0.01 });
      io.observe(rootRef.current);
    } else { start(); }

    return () => { active = false; if (timer) clearTimeout(timer); if (io) io.disconnect(); };
  }, [code, prefetchedDash]);

  if (!signal || !signal.secCode) return null;

  // ===== 数据派生 =====
  const { secCode, secName } = signal;
  const rtDash = dash?.realtime;
  const bsInt = dash?.bs_interval || signal?.bsInterval;
  const sfDash = dash?.sector_flow;
  const ind = signal?.indicators;

  // 实时价格
  const idArr = rtDash?.intraday || [];
  const lastPt = idArr.length ? idArr[idArr.length - 1] : null;
  const curPrice = lastPt?.price ?? signal?.quote?.price ?? null;
  const dayPct = lastPt?.pct_chg ?? signal?.quote?.pct_chg ?? null;
  const priceColor = dayPct == null ? 'var(--text-muted)' : dayPct >= 0 ? '#ef4444' : '#22c55e';

  // 分时技术指标
  const idPrices = idArr.map((d) => d?.price).filter((v) => typeof v === 'number' && !Number.isNaN(v));
  const rtKdj = useMemo(() => calcIntradayKdj(idPrices), [idPrices]);
  const rtMacd = useMemo(() => calcIntradayMacd(idPrices), [idPrices]);

  // 5分钟涨跌 / 振幅
  const rt5MinChg = useMemo(() => {
    const n = idArr.length;
    if (n < 2) return null;
    const last = idArr[n - 1]?.price;
    const prev = idArr[Math.max(0, n - 6)]?.price;
    if (last == null || prev == null || !prev) return null;
    return (last - prev) / prev * 100;
  }, [idArr]);
  const rtAmplitude = useMemo(() => {
    const prices = idArr.map((d) => d?.price).filter((v) => v != null && v > 0);
    if (prices.length < 2) return null;
    return (Math.max(...prices) - Math.min(...prices)) / Math.min(...prices) * 100;
  }, [idArr]);

  // ===== 公共样式 =====
  const rowH = "flex items-center gap-1.5 text-[10px] tabular-nums min-h-[18px]";
  const labelW = "w-10 flex-shrink-0 text-[10px]";
  const muted = { color: 'var(--text-muted)' };
  const empty = <div className={rowH} style={{ visibility: 'hidden' }}>&nbsp;</div>;

  // 颜色工具
  const redGreen = (v) => v == null ? 'var(--text-muted)' : v >= 0 ? '#ef4444' : '#22c55e';

  return (
    <div ref={rootRef} className="rounded-lg overflow-hidden border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>

      {/* ===== 1. 头部：股票名 + 现价 + 迷你分时线 ===== */}
      <div className="flex items-center justify-between px-2.5 py-2">
        <div className="flex items-baseline gap-2 min-w-0">
          <span className="text-sm font-bold truncate" style={{ color: 'var(--text-primary)' }}>
            {secName}
          </span>
          <span className="text-[10px] font-mono flex-shrink-0" style={{ color: 'var(--text-muted)' }}>
            {secCode}
          </span>
          {loading && (
            <span className="inline-block w-2.5 h-2.5 border rounded-full animate-spin flex-shrink-0"
              style={{ borderColor: 'var(--text-muted)', borderTopColor: 'transparent' }} />
          )}
        </div>
        <div className="flex items-center gap-2 flex-shrink-0">
          {idArr.length >= 2 && (
            <MiniSpark data={idArr} width={48} height={16} />
          )}
          {curPrice != null && (
            <div className="flex items-baseline gap-1.5">
              <span className="text-sm font-bold font-mono" style={{ color: priceColor }}>
                {curPrice.toFixed(2)}
              </span>
              {dayPct != null && (
                <span className="text-[11px] font-bold font-mono" style={{ color: priceColor }}>
                  {dayPct >= 0 ? '+' : ''}{dayPct.toFixed(2)}%
                </span>
              )}
            </div>
          )}
        </div>
      </div>

      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)', opacity: 0.5 }} />

      {/* ===== 2. BS 区间（纯文字档案，无 K 线图）===== */}
      {bsInt && bsInt.state !== 'unknown' && (
        <>
          <div className="px-2.5 py-1.5">
            {/* 模块标题行 */}
            <div className="flex items-center justify-between mb-1">
              <span className="text-[10px] font-bold px-1.5 py-0 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', borderLeft: '2px solid #3b82f6' }}>
                BS 区间
              </span>
            </div>
            {/* 状态 + B/S 路径 + 盈亏 */}
            <div className="flex items-center gap-2">
              {/* 状态标签：明确标注 B 持仓 / S 平仓 */}
              {(() => {
                const isHolding = bsInt.state === 'holding';
                const c = isHolding ? '#ef4444' : '#f97316';
                return (
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-bold flex-shrink-0 inline-flex items-center gap-1"
                    style={{ background: `${c}14`, color: c, border: `1px solid ${c}30` }}>
                    <span className={`inline-block w-1.5 h-1.5 rounded-full ${isHolding ? 'animate-pulse' : ''}`} style={{ background: c }} />
                    {isHolding ? 'B 持仓中' : 'S 已平仓'}
                  </span>
                );
              })()}

              {/* B → S/今 路径 */}
              {(() => {
                const isHolding = bsInt.state === 'holding';
                const sd = bsInt.start_date || '';
                const ed = bsInt.end_date || (isHolding ? '今' : '');
                const sp = bsInt.start_price || 0;
                const ep = bsInt.end_price || 0;
                const stateColor = isHolding ? '#ef4444' : '#f97316';
                return (
                  <span className="text-[10px] font-mono truncate" style={{ color: 'var(--text-secondary)' }}>
                    <span style={muted}>B</span> {sd} <span style={{ color: stateColor }}>{sp.toFixed(2)}</span>
                    <span style={muted}> → </span>
                    <span style={muted}>{isHolding ? '今' : 'S'}</span> {ed} <span style={{ color: stateColor }}>{ep.toFixed(2)}</span>
                  </span>
                );
              })()}

              {/* 持有天数 + 盈亏 */}
              {(() => {
                const hd = bsInt.hold_days || 0;
                const pnl = bsInt.pnl_pct;
                const pnlColor = pnl == null ? '#94a3b8' : pnl >= 0 ? '#ef4444' : '#22c55e';
                return (
                  <div className="ml-auto flex items-center gap-2 flex-shrink-0">
                    <span className="text-[10px]" style={muted}>{hd}天</span>
                    <span className="text-[11px] font-bold font-mono px-1.5 py-0.5 rounded" style={{ background: `${pnlColor}12`, color: pnlColor }}>
                      {pnl == null ? '--' : `${pnl >= 0 ? '+' : ''}${pnl}%`}
                    </span>
                  </div>
                );
              })()}
            </div>
          </div>
          <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)', opacity: 0.5 }} />
        </>
      )}

      {/* ===== 3. 技术指标：左盘后 4 行 | 右实时 4 行 ===== */}
      {(ind?.kdj_k || ind?.macd) && (
        <>
          <div className="px-2.5 py-1.5">
            <div className="flex items-stretch">
              {/* 左：盘后 */}
              <div className="flex-1 min-w-0 pr-2 flex flex-col gap-0.5">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[10px] font-bold px-1.5 py-0 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', borderLeft: '2px solid #3b82f6' }}>
                    技术指标
                  </span>
                  {(() => {
                    const j = ind?.kdj_j, m = ind?.macd, ma5 = ind?.ma5, ma20 = ind?.ma20, r = ind?.rsi;
                    const tags = [];
                    if (j != null && j >= 80) tags.push({ t: '超买', c: '#ef4444' });
                    if (j != null && j <= 20) tags.push({ t: '超卖', c: '#22c55e' });
                    if (m != null && m >= 0 && ind?.dif > ind?.dea) tags.push({ t: '金叉', c: '#ef4444' });
                    if (m != null && m < 0 && ind?.dif < ind?.dea) tags.push({ t: '死叉', c: '#22c55e' });
                    if (ma5 != null && ma20 != null && ma5 > ma20) tags.push({ t: '多头', c: '#ef4444' });
                    if (ma5 != null && ma20 != null && ma5 < ma20) tags.push({ t: '空头', c: '#22c55e' });
                    if (r != null && r >= 70) tags.push({ t: '超买', c: '#ef4444' });
                    if (r != null && r <= 30) tags.push({ t: '超卖', c: '#22c55e' });
                    return tags.length > 0 ? (
                      <span className="text-[9px] px-1 py-0 rounded font-bold" style={{ background: `${tags[0].c}14`, color: tags[0].c }}>
                        {tags[0].t}
                      </span>
                    ) : null;
                  })()}
                </div>

                {/* KDJ */}
                {ind?.kdj_j != null ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>KDJ</span>
                    <span className="font-mono" style={{ color: ind.kdj_j >= 80 ? '#ef4444' : ind.kdj_j <= 20 ? '#22c55e' : 'var(--text-primary)' }}>
                      K{ind.kdj_k?.toFixed(1)} D{ind.kdj_d?.toFixed(1)} J{ind.kdj_j.toFixed(1)}
                    </span>
                  </div>
                ) : empty}

                {/* MACD */}
                {ind?.macd != null ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>MACD</span>
                    <span className="font-mono" style={{ color: ind.macd >= 0 ? '#ef4444' : '#22c55e' }}>
                      {ind.macd.toFixed(3)} DIF{ind.dif?.toFixed(3)} DEA{ind.dea?.toFixed(3)}
                    </span>
                  </div>
                ) : empty}

                {/* MA */}
                {(ind?.ma5 != null && ind?.ma20 != null) ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>MA</span>
                    <span className="font-mono" style={{ color: ind.ma5 >= ind.ma20 ? '#ef4444' : '#22c55e' }}>
                      MA5 {ind.ma5.toFixed(2)} / MA20 {ind.ma20.toFixed(2)}
                    </span>
                  </div>
                ) : empty}

                {/* RSI */}
                {ind?.rsi != null ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>RSI</span>
                    <span className="font-mono" style={{ color: ind.rsi >= 70 ? '#ef4444' : ind.rsi <= 30 ? '#22c55e' : 'var(--text-primary)' }}>
                      {ind.rsi.toFixed(1)}
                    </span>
                  </div>
                ) : empty}
              </div>

              {/* 分隔线 */}
              <div className="shrink-0" style={{ width: '1px', backgroundColor: 'var(--border-color)', margin: '4px 0' }} />

              {/* 右：实时 */}
              <div className="flex-1 min-w-0 pl-2 flex flex-col gap-0.5">
                <div className="flex items-center justify-between mb-0.5">
                  <span className="text-[10px] font-bold px-1.5 py-0 rounded" style={{ background: 'rgba(34,197,94,0.08)', color: '#22c55e', borderLeft: '2px solid #22c55e' }}>
                    实时
                  </span>
                  {rtDash?.snapshot_time && (
                    <span className="text-[9px]" style={muted}>{rtDash.snapshot_time.slice(-8)}</span>
                  )}
                </div>

                {/* 分KDJ */}
                {rtKdj ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>分KDJ</span>
                    <span className="font-mono" style={{ color: rtKdj.j >= 80 ? '#ef4444' : rtKdj.j <= 20 ? '#22c55e' : 'var(--text-primary)' }}>
                      K{rtKdj.k.toFixed(1)} D{rtKdj.d.toFixed(1)} J{rtKdj.j.toFixed(1)}
                    </span>
                  </div>
                ) : empty}

                {/* 分MACD */}
                {rtMacd ? (
                  <div className={rowH}>
                    <span className={labelW} style={muted}>分MACD</span>
                    <span className="font-mono" style={{ color: rtMacd.macd >= 0 ? '#ef4444' : '#22c55e' }}>
                      {rtMacd.macd.toFixed(3)} DIF{rtMacd.dif.toFixed(3)}
                    </span>
                    {rtMacd.dif > rtMacd.dea && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>金叉</span>}
                    {rtMacd.dif < rtMacd.dea && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>死叉</span>}
                  </div>
                ) : empty}

                {/* 支撑/阻力 */}
                {(() => {
                  const pctSup = (ind?.support != null && curPrice) ? (curPrice - ind.support) / ind.support * 100 : null;
                  const pctRes = (ind?.resistance != null && curPrice) ? (curPrice - ind.resistance) / ind.resistance * 100 : null;
                  if (pctSup == null && pctRes == null) return empty;
                  return (
                    <div className={rowH}>
                      <span className={labelW} style={muted}>撑/阻</span>
                      {pctSup != null && (
                        <span className="font-mono font-bold" style={{ color: pctSup >= 0 ? '#ef4444' : '#22c55e' }}>
                          撑{pctSup >= 0 ? '+' : ''}{pctSup.toFixed(2)}%
                        </span>
                      )}
                      {pctSup != null && pctRes != null && <span style={muted}>/</span>}
                      {pctRes != null && (
                        <span className="font-mono font-bold" style={{ color: pctRes >= 0 ? '#ef4444' : '#22c55e' }}>
                          阻{pctRes >= 0 ? '+' : ''}{pctRes.toFixed(2)}%
                        </span>
                      )}
                    </div>
                  );
                })()}

                {/* 5分钟 / 振幅 */}
                <div className={rowH}>
                  <span className={labelW} style={muted}>5分钟</span>
                  {rt5MinChg == null ? (
                    <span className="text-[10px] italic" style={muted}>无数据</span>
                  ) : (
                    <>
                      <span className="font-mono font-bold" style={{ color: rt5MinChg >= 0 ? '#ef4444' : '#22c55e' }}>
                        {rt5MinChg >= 0 ? '+' : ''}{rt5MinChg.toFixed(2)}%
                      </span>
                      <span className="text-[9px]" style={muted}>振幅</span>
                      <span className="font-mono" style={{ color: rtAmplitude != null && rtAmplitude >= 3 ? '#f59e0b' : 'var(--text-primary)' }}>
                        {rtAmplitude != null ? `${rtAmplitude.toFixed(2)}%` : '--'}
                      </span>
                    </>
                  )}
                </div>
              </div>
            </div>
          </div>
          <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)', opacity: 0.5 }} />
        </>
      )}

      {/* ===== 4. 板块行 ===== */}
      {(signal.sector || sfDash) && (
        <>
          <div className="px-2.5 py-1">
            <div className="flex items-center gap-2 text-[10px]">
              <span className="font-bold px-1.5 py-0 rounded flex-shrink-0" style={{ background: 'rgba(168,85,247,0.08)', color: '#a855f7', borderLeft: '2px solid #a855f7' }}>
                板块
              </span>
              <span className="font-bold truncate" style={{ color: 'var(--text-secondary)' }}>
                {signal.sector || '--'}
              </span>
              {sfDash?.avg_chg != null && (
                <span className="font-bold font-mono flex-shrink-0" style={{ color: redGreen(sfDash.avg_chg) }}>
                  {sfDash.avg_chg >= 0 ? '+' : ''}{sfDash.avg_chg.toFixed(2)}%
                </span>
              )}
              {sfDash?.limit_up_count > 0 && (
                <span className="text-[9px] px-1 rounded flex-shrink-0" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>
                  {sfDash.limit_up_count}涨停
                </span>
              )}
              {/* 板块资金 */}
              {(() => {
                const v = rtDash?.sector_net ?? sfDash?.net_flow ?? signal?.sectorTrend?.total_net_flow ?? null;
                if (v == null) return null;
                return (
                  <span className="ml-auto font-mono flex-shrink-0" style={{ color: redGreen(v) }}>
                    {v >= 0 ? '净流入 ' : '净流出 '}{fmtYuan(Math.abs(v))}
                  </span>
                );
              })()}
            </div>
          </div>
          <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)', opacity: 0.5 }} />
        </>
      )}

      {/* ===== 5. 操作按钮（2 列分隔网格，靠右）===== */}
      <div className="px-2.5 py-1.5 flex justify-end">
        <StockActionButtons
          stockCode={secCode}
          stockName={secName}
          signal={signal}
          positionCount={signal?.position?.count || 0}
          showBuy={showBuyBtn ?? showWatchBtn}
          showSell={(signal?.position?.count || 0) > 0}
          showTrack={showBuyBtn ?? showWatchBtn}
          showWatch={showWatchBtn}
          showMore={showActionButton}
          showKline={showAnalysisButton}
          showAnalysis={showAnalysisButton}
          onAnalyze={onAnalyze}
          layout="grid"
          size="sm"
          onRefresh={onRefresh}
          onRemove={onRemove}
        />
      </div>
    </div>
  );
}

export default memo(StrategySignalCardInner);