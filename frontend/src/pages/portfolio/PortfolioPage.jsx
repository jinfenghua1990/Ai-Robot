import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../../utils/request';
import { formatWan } from '../../utils/format';

const UP_COLOR = '#ef4444';    // 涨：红（中国市场约定）
const DOWN_COLOR = '#22c55e';  // 跌：绿
const MODE_TEXT = { off: '关闭', risk_only: '风控托管', full_auto: '全自动' };
const STATUS_TEXT = {
  OFF: '关闭', VALIDATING: '开启检查', MONITORING: '监控中', SIGNAL_READY: '信号就绪',
  ORDER_PENDING: '准备下单', ORDER_WORKING: '订单处理中', PARTIAL_FILLED: '部分成交',
  HOLDING: '持有中', PAUSED: '已暂停', ERROR: '异常', COMPLETED: '本轮完成', LOCKED: '当日不可卖',
};
const ACTION_COLOR = (a) => {
  const s = String(a || '');
  if (/卖出|减仓|退出|止损|止盈|清仓/.test(s)) return '#ef4444';
  if (/买入|加仓|开仓/.test(s)) return '#3b82f6';
  if (/观察|持有|继续/.test(s)) return '#f59e0b';
  return 'var(--text-muted)';
};

function timeAgo(iso) {
  if (!iso) return '';
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 5) return '刚刚';
  if (sec < 60) return `${sec}秒前`;
  return `${Math.floor(sec / 60)}分钟前`;
}

const num = (v, d = 2) => (v == null || isNaN(Number(v)) ? '—' : Number(v).toFixed(d));
const pct = (v, sign = true) => {
  if (v == null || isNaN(Number(v))) return '—';
  const n = Number(v);
  return `${sign && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};
const fmtMoney = (v) => {
  if (v == null || isNaN(Number(v))) return '—';
  const a = Math.abs(Number(v));
  if (a >= 1e8) return `${(Number(v) / 1e8).toFixed(2)}亿`;
  if (a >= 1e4) return `${(Number(v) / 1e4).toFixed(1)}万`;
  return Number(v).toFixed(0);
};

/** 持仓 + 自选信号 + 自动交易配置 → 表格行 */
function buildRow(holding, sig, cfg, global) {
  const q = sig?.quote || {};
  const ind = sig?.indicators || {};
  const pos = sig?.position || {};
  const mf = sig?.moneyFlow || {};
  const price = q.price ?? holding.last_price ?? pos.price ?? 0;
  const cost = pos.costPrice ?? holding.avg_cost ?? 0;
  const changePct = q.changePct ?? holding.day_pnl_pct ?? pos.dayProfitPct ?? null;
  const profitPct = pos.profitPct ?? (cost > 0 ? ((price - cost) / cost) * 100 : 0);
  const score = sig?.overallScore ?? null;
  // 均线结构
  let maStruct = '—';
  if (ind.ma5 && ind.ma20) {
    const bull = ind.ma5 >= ind.ma20;
    const above = price >= ind.ma20;
    maStruct = `${above ? '价>MA20' : '价<MA20'}·${bull ? '多头' : '空头'}`;
  } else if (ind.ma20) {
    maStruct = price >= ind.ma20 ? '价>MA20' : '价<MA20';
  }
  // MACD
  let macdTxt = '—';
  if (ind.dif != null && ind.dea != null) {
    macdTxt = ind.dif >= ind.dea ? (ind.dif >= 0 ? '零轴上金叉' : '零轴下金叉') : '死叉';
  } else if (ind.macd != null) {
    macdTxt = ind.macd >= 0 ? '多头' : '空头';
  }
  const mode = cfg?.mode || 'off';
  const status = cfg?.status || 'OFF';
  const globalPaused = global?.paused || false;
  const globalOff = !global?.enabled;
  let atStatus = MODE_TEXT[mode] || '关闭';
  let atColor = 'var(--text-muted)';
  let atHint = '';
  if (mode !== 'off') {
    if (globalPaused) { atStatus = '已暂停'; atColor = '#f97316'; atHint = '全局暂停中'; }
    else if (globalOff) { atStatus = '总开关关闭'; atColor = '#f59e0b'; atHint = '未执行'; }
    else if (status === 'PAUSED') { atStatus = '已暂停'; atColor = '#f97316'; atHint = cfg.paused_reason || ''; }
    else if (status === 'MONITORING') { atStatus = `${MODE_TEXT[mode]}·监控中`; atColor = '#22c55e'; }
    else { atStatus = `${MODE_TEXT[mode]}·${STATUS_TEXT[status] || status}`; atColor = status === 'ERROR' ? '#ef4444' : '#3b82f6'; }
  }
  return {
    code: holding.symbol, name: q.name || holding.name || holding.symbol,
    price, changePct, cost, profitPct,
    posPct: pos.posPct ?? holding.pos_pct ?? null,
    score,
    maStruct, rsi: ind.rsi ?? null, macdTxt,
    volRatio: mf.turnover_rate ?? null,
    mainNet: mf.main_net ?? null,
    support: ind.support ?? null, resistance: ind.resistance ?? null,
    action: sig?.holdingState?.action || sig?.actionLabel || sig?.signalLabel || '观察',
    mode, status, atStatus, atColor, atHint,
    sig, cfg,
  };
}

export default function PortfolioPage() {
  const navigate = useNavigate();
  const [portfolio, setPortfolio] = useState(null);
  const [wlSignals, setWlSignals] = useState({});
  const [autoGlobal, setAutoGlobal] = useState(null);
  const [autoStocks, setAutoStocks] = useState({});
  const [notes, setNotes] = useState({});
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [visible, setVisible] = useState(true);
  const timerRef = useRef(null);

  // 抽屉状态：detail / config / audit / null
  const [drawer, setDrawer] = useState(null);
  const [drawerCode, setDrawerCode] = useState(null);
  const [auditItems, setAuditItems] = useState([]);

  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  const loadWatchlistSignals = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/watchlist');
    if (ok && data) {
      const map = {};
      for (const s of (data.signals || [])) if (s.secCode) map[s.secCode] = s;
      setWlSignals(map);
    }
  }, []);

  const loadNotes = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/shared/stock-notes');
    if (ok && data) setNotes(data);
  }, []);

  const loadAutoTrade = useCallback(async () => {
    const [g, s] = await Promise.all([
      apiFetch('/api/auto-trade/global'),
      apiFetch('/api/auto-trade/stocks'),
    ]);
    if (g.ok && g.data) setAutoGlobal(g.data);
    if (s.ok && s.data) setAutoStocks(s.data.items || {});
  }, []);

  const loadData = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/shared/portfolio');
    if (ok && data) { setPortfolio(data); setLastSync(new Date().toISOString()); }
    await Promise.all([loadWatchlistSignals(), loadNotes(), loadAutoTrade()]);
    setLoading(false);
  }, [loadWatchlistSignals, loadNotes, loadAutoTrade]);

  useEffect(() => {
    loadData();
    const interval = visible ? 30000 : 60000;
    timerRef.current = setInterval(loadData, interval);
    return () => clearInterval(timerRef.current);
  }, [loadData, visible]);

  const handleSync = async () => {
    setSyncing(true);
    await apiFetch('/api/shared/portfolio/refresh', { method: 'POST' });
    await loadData();
    setSyncing(false);
  };

  // ─── 账户级操作 ───
  const updateGlobal = async (patch) => {
    const { ok } = await apiFetch('/api/auto-trade/global', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    });
    if (ok) await loadAutoTrade();
  };
  const pauseGlobal = async () => {
    await apiFetch('/api/auto-trade/global/pause', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: '人工一键暂停' }),
    });
    await loadAutoTrade();
  };
  const resumeGlobal = async () => {
    await apiFetch('/api/auto-trade/global/resume', { method: 'POST' });
    await loadAutoTrade();
  };

  // ─── 审计 ───
  const openAudit = async (code = null) => {
    const qs = code ? `?code=${code}` : '';
    const { ok, data } = await apiFetch(`/api/auto-trade/audit${qs}`);
    if (ok && data) setAuditItems(data.items || []);
    setDrawerCode(code);
    setDrawer('audit');
  };

  const openDetail = (code) => { setDrawerCode(code); setDrawer('detail'); };
  const openConfig = (code) => { setDrawerCode(code); setDrawer('config'); };

  // ─── 个股操作（由配置抽屉调用） ───
  const saveStockConfig = async (code, patch) => {
    const { ok } = await apiFetch(`/api/auto-trade/stocks/${code}/config`, {
      method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(patch),
    });
    if (ok) await loadAutoTrade();
    return ok;
  };
  const enableStock = async (code, operator = 'user') => {
    const res = await apiFetch(`/api/auto-trade/stocks/${code}/enable`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ operator }),
    });
    if (res.ok && res.data?.ok) { await loadAutoTrade(); return { ok: true }; }
    return { ok: false, missing: res.data?.missing || [], message: res.data?.message };
  };
  const disableStock = async (code) => {
    await apiFetch(`/api/auto-trade/stocks/${code}/disable`, { method: 'POST' });
    await loadAutoTrade();
  };
  const pauseStock = async (code, reason) => {
    await apiFetch(`/api/auto-trade/stocks/${code}/pause`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason }),
    });
    await loadAutoTrade();
  };
  const resumeStock = async (code) => {
    await apiFetch(`/api/auto-trade/stocks/${code}/resume`, { method: 'POST' });
    await loadAutoTrade();
  };

  const positions = portfolio?.positions ?? [];
  const totalMv = portfolio?.total_market_value ?? 0;
  const totalPnl = portfolio?.total_unrealized_pnl ?? 0;
  const totalAssets = portfolio?.total_assets ?? (totalMv + (portfolio?.available_cash ?? 0));
  const availableCash = portfolio?.available_cash ?? 0;
  const totalCost = portfolio?.total_cost ?? 0;
  const totalDayPnl = portfolio?.total_day_pnl ?? 0;

  const rows = useMemo(() => positions
    .map((p) => buildRow(p, wlSignals[p.symbol], autoStocks[p.symbol], autoGlobal))
    .sort((a, b) => {
      // 风险优先置顶：已开启自动交易 > 亏损幅度 > 盈亏
      const riskA = a.mode !== 'off' ? 1 : 0;
      const riskB = b.mode !== 'off' ? 1 : 0;
      if (riskA !== riskB) return riskB - riskA;
      return (a.profitPct ?? 0) - (b.profitPct ?? 0);
    }), [positions, wlSignals, autoStocks, autoGlobal]);

  const g = autoGlobal || { enabled: false, run_environment: 'paper', paused: false, today_orders: 0, today_pnl: 0 };
  const riskCount = rows.filter((r) => r.mode !== 'off').length;
  const lossCount = rows.filter((r) => (r.profitPct ?? 0) < 0).length;

  return (
    <div className="space-y-3">

      {/* ===== Sticky 顶栏 ===== */}
      <div className="sticky top-0 z-30 rounded-xl p-2.5 space-y-2"
        style={{ background: 'var(--bg-card)', borderBottom: '2px solid var(--border-color)', boxShadow: '0 2px 12px rgba(0,0,0,0.06)' }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <span>我的持仓</span>
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--accent-green)' }}>{positions.length}只</span>
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.08)', color: '#ef4444' }}>亏损{lossCount}</span>
          </h2>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>同步于 {timeAgo(lastSync)}</span>
            <button onClick={handleSync} disabled={syncing}
              className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1 disabled:opacity-50"
              style={{ borderColor: syncing ? 'var(--border-color)' : 'rgba(59,130,246,0.4)', color: 'var(--accent-blue)', background: syncing ? 'rgba(59,130,246,0.06)' : 'transparent' }}>
              {syncing ? '⏳' : '🔄'} 同步
            </button>
          </div>
        </div>
      </div>

      {/* ===== 账户自动交易控制栏 ===== */}
      <div className="rounded-xl border p-2.5 space-y-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-1.5">
            <span className="text-[11px] font-medium" style={{ color: 'var(--text-secondary)' }}>自动交易总开关</span>
            <button onClick={() => updateGlobal({ enabled: !g.enabled })}
              className="w-9 h-5 rounded-full transition-colors relative"
              style={{ background: g.enabled ? '#22c55e' : 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>
              <span className="absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all" style={{ left: g.enabled ? '20px' : '2px', background: '#fff' }} />
            </button>
            <span className="text-xs font-bold" style={{ color: g.enabled ? '#22c55e' : 'var(--text-muted)' }}>{g.enabled ? '已开启' : '关闭'}</span>
          </div>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: g.run_environment === 'live' ? 'rgba(239,68,68,0.1)' : 'rgba(59,130,246,0.1)', color: g.run_environment === 'live' ? '#ef4444' : '#3b82f6' }}>
            {g.run_environment === 'live' ? '实盘' : '模拟'}
          </span>
          <div className="flex items-center gap-3 text-[11px]" style={{ color: 'var(--text-muted)' }}>
            <span>今日自动订单 <b style={{ color: 'var(--text-primary)' }}>{g.today_orders ?? 0}</b></span>
            <span>今日自动盈亏 <b style={{ color: (g.today_pnl ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>{fmtMoney(g.today_pnl)}</b></span>
            <span>自动交易持仓 <b style={{ color: 'var(--text-primary)' }}>{riskCount}</b> 只</span>
          </div>
          <div className="flex-1" />
          <button onClick={() => openAudit()} className="px-2 py-1 rounded-lg border text-[11px]"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'transparent' }}>📋 操作记录</button>
          {g.paused ? (
            <button onClick={resumeGlobal} className="px-2 py-1 rounded-lg border text-[11px]"
              style={{ borderColor: 'rgba(34,197,94,0.4)', color: '#22c55e', background: 'rgba(34,197,94,0.06)' }}>▶ 恢复</button>
          ) : (
            <button onClick={pauseGlobal} className="px-2 py-1 rounded-lg border text-[11px]"
              style={{ borderColor: 'rgba(239,68,68,0.4)', color: '#ef4444', background: 'rgba(239,68,68,0.06)' }}>⏸ 一键暂停全部</button>
          )}
        </div>
        {g.paused && (
          <div className="flex items-center gap-2 px-2 py-1.5 rounded-lg text-[11px]"
            style={{ background: 'rgba(249,115,22,0.08)', color: '#f97316' }}>
            <span>⚠️ 自动交易已全局暂停：{g.pause_reason || '未知原因'}</span>
            <span style={{ color: 'var(--text-muted)' }}>暂停于 {g.paused_at || ''} · 恢复需人工确认</span>
          </div>
        )}
      </div>

      {/* ===== 总览卡片 ===== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {[
          { label: '总资产', value: formatWan(totalAssets), color: 'var(--text-primary)', sub: `持仓 ${formatWan(totalMv)} · 可用 ${formatWan(availableCash)}` },
          { label: '可用资金', value: formatWan(availableCash), color: '#3b82f6', sub: totalAssets > 0 ? `仓位 ${((totalMv / totalAssets) * 100).toFixed(1)}%` : '—' },
          { label: '总盈亏', value: formatWan(totalPnl), color: totalPnl >= 0 ? UP_COLOR : DOWN_COLOR, sub: totalCost > 0 ? `收益率 ${((totalPnl / totalCost) * 100).toFixed(2)}%` : (totalPnl >= 0 ? '盈利中' : '亏损中') },
          { label: '当日盈亏', value: formatWan(totalDayPnl), color: totalDayPnl >= 0 ? UP_COLOR : DOWN_COLOR, sub: totalDayPnl >= 0 ? '今日盈利' : '今日亏损' },
        ].map((c, i) => (
          <div key={i} className="rounded-xl border p-2.5" style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
            <div className="text-[10px] flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
              {c.label}
              <span className="text-[9px]">{c.sub}</span>
            </div>
            <div className="text-xl font-bold mt-0.5" style={{ color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* ===== 持仓技术指标表格 ===== */}
      {loading ? (
        <div className="space-y-2">
          {[1, 2, 3, 4].map(i => <div key={i} className="h-12 rounded animate-pulse" style={{ background: 'var(--bg-hover)' }} />)}
        </div>
      ) : rows.length === 0 ? (
        <div className="text-center py-12 rounded-xl border" style={{ borderColor: 'var(--border-color)' }}>
          <div className="text-3xl mb-2">💼</div>
          <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>暂无持仓数据</div>
          <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>在妙想模拟盘交易后自动同步</div>
        </div>
      ) : (
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="overflow-x-auto no-scrollbar">
            <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth: 1080 }}>
              <thead>
                <tr style={{ background: 'var(--bg-secondary)' }}>
                  {[
                    { k: '股票', w: 130, sticky: 'left' },
                    { k: '现价/涨幅', w: 96 },
                    { k: '成本/盈亏', w: 100 },
                    { k: '仓位', w: 62 },
                    { k: '评分', w: 56 },
                    { k: '均线结构', w: 100 },
                    { k: 'RSI', w: 50 },
                    { k: 'MACD', w: 86 },
                    { k: '量比', w: 56 },
                    { k: '资金', w: 74 },
                    { k: '关键位', w: 96 },
                    { k: '建议', w: 92 },
                    { k: '自动交易', w: 128, sticky: 'right' },
                  ].map((c) => (
                    <th key={c.k} className="px-2 py-1.5 font-semibold text-left whitespace-nowrap"
                      style={{
                        color: 'var(--text-muted)', width: c.w, position: c.sticky ? 'sticky' : 'static',
                        left: c.sticky === 'left' ? 0 : undefined, right: c.sticky === 'right' ? 0 : undefined,
                        zIndex: c.sticky ? 2 : 1, background: 'var(--bg-secondary)',
                      }}>{c.k}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.code} onClick={() => openDetail(r.code)}
                    className="cursor-pointer hover:opacity-90 transition-colors"
                    style={{ borderTop: '1px solid var(--border-color)', background: 'var(--bg-card)' }}>
                    {/* 股票（固定左） */}
                    <td className="px-2 py-1 whitespace-nowrap sticky left-0 z-[2]" style={{ background: 'var(--bg-card)' }}>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                        <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{r.code}</span>
                        {(r.profitPct ?? 0) < 0 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: DOWN_COLOR }}>亏</span>}
                      </div>
                    </td>
                    {/* 现价/涨幅 */}
                    <td className="px-2 py-1 whitespace-nowrap">
                      <div style={{ color: 'var(--text-primary)' }}>{num(r.price)}</div>
                      <div style={{ color: (r.changePct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>{pct(r.changePct)}</div>
                    </td>
                    {/* 成本/盈亏 */}
                    <td className="px-2 py-1 whitespace-nowrap">
                      <div style={{ color: 'var(--text-muted)' }}>{num(r.cost)}</div>
                      <div style={{ color: (r.profitPct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>{pct(r.profitPct)}</div>
                    </td>
                    {/* 仓位 */}
                    <td className="px-2 py-1 text-right" style={{ color: 'var(--text-secondary)' }}>
                      {r.posPct != null ? `${r.posPct.toFixed(1)}%` : '—'}
                    </td>
                    {/* 评分 */}
                    <td className="px-2 py-1 text-center">
                      {r.score != null ? (
                        <span className="font-bold" style={{ color: r.score >= 70 ? UP_COLOR : r.score >= 55 ? '#f59e0b' : 'var(--text-muted)' }}>{Math.round(r.score)}</span>
                      ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    {/* 均线结构 */}
                    <td className="px-2 py-1 whitespace-nowrap" style={{ color: /多头/.test(r.maStruct) ? UP_COLOR : 'var(--text-secondary)' }}>{r.maStruct}</td>
                    {/* RSI */}
                    <td className="px-2 py-1 text-center" style={{ color: r.rsi == null ? 'var(--text-muted)' : r.rsi >= 70 ? UP_COLOR : r.rsi <= 30 ? DOWN_COLOR : 'var(--text-secondary)' }}>
                      {r.rsi != null ? r.rsi.toFixed(0) : '—'}
                    </td>
                    {/* MACD */}
                    <td className="px-2 py-1 whitespace-nowrap" style={{ color: /金叉/.test(r.macdTxt) ? UP_COLOR : /死叉/.test(r.macdTxt) ? DOWN_COLOR : 'var(--text-muted)' }}>{r.macdTxt}</td>
                    {/* 量比 */}
                    <td className="px-2 py-1 text-center" style={{ color: r.volRatio == null ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
                      {r.volRatio != null ? r.volRatio.toFixed(1) : '—'}
                    </td>
                    {/* 资金 */}
                    <td className="px-2 py-1 text-right whitespace-nowrap" style={{ color: (r.mainNet ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>
                      {fmtMoney(r.mainNet)}
                    </td>
                    {/* 关键位 */}
                    <td className="px-2 py-1 whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
                      {r.support != null ? `支${num(r.support)}` : ''}{r.resistance != null ? ` 突${num(r.resistance)}` : ''}
                    </td>
                    {/* 建议 */}
                    <td className="px-2 py-1 whitespace-nowrap font-medium" style={{ color: ACTION_COLOR(r.action) }}>{r.action}</td>
                    {/* 自动交易（固定右） */}
                    <td className="px-2 py-1 sticky right-0 z-[2]" style={{ background: 'var(--bg-card)' }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); openConfig(r.code); }}
                        className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
                        style={{ borderColor: `${r.atColor}55`, color: r.atColor, background: `${r.atColor}10` }}>
                        {r.atStatus}{r.atHint ? `·${r.atHint}` : ''}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex items-center gap-3 px-3 py-1.5 text-[10px] flex-wrap" style={{ borderTop: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
            <span>点击行查看详情 · 点击「自动交易」配置个股</span>
            <span className="flex-1" />
            <span>默认不交易 · 风险指令优先 · 关键位决定动作 · 技术指标负责确认</span>
          </div>
        </div>
      )}

      {/* ===== 右侧抽屉 ===== */}
      {drawer && (
        <Drawer code={drawerCode} mode={drawer}
          wlSignal={drawerCode ? wlSignals[drawerCode] : null}
          cfg={drawerCode ? autoStocks[drawerCode] : null}
          global={g}
          notes={drawerCode ? notes[drawerCode] : null}
          auditItems={drawer && drawer === 'audit' ? auditItems : []}
          onClose={() => setDrawer(null)}
          onOpenConfig={openConfig}
          onOpenDetail={openDetail}
          onSave={saveStockConfig}
          onEnable={enableStock}
          onDisable={disableStock}
          onPause={pauseStock}
          onResume={resumeStock}
          onRefreshAudit={openAudit}
          navigate={navigate} />
      )}
    </div>
  );
}

/* ================= 右侧抽屉 ================= */
function Drawer({ code, mode, wlSignal, cfg, global, notes, auditItems, onClose, onOpenConfig, onOpenDetail, onSave, onEnable, onDisable, onPause, onResume, onRefreshAudit, navigate }) {
  // Esc 关闭抽屉
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);
  const sig = wlSignal || {};
  const q = sig.quote || {};
  const ind = sig.indicators || {};
  const pos = sig.position || {};
  const mf = sig.moneyFlow || {};

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.4)' }} onClick={onClose}>
      <div className="w-[600px] max-w-[94vw] h-[86vh] flex flex-col rounded-xl overflow-hidden"
        style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', boxShadow: '0 12px 48px rgba(0,0,0,0.25)' }}
        onClick={(e) => e.stopPropagation()}>

        {mode === 'audit' ? (
          <AuditPanel items={auditItems} code={code} onClose={onClose} onRefresh={() => onRefreshAudit(code)} />
        ) : mode === 'config' ? (
          <ConfigPanel code={code} cfg={cfg} global={global}
            onClose={onClose}
            onSave={onSave} onEnable={onEnable} onDisable={onDisable}
            onPause={onPause} onResume={onResume} />
        ) : (
          <DetailPanel code={code} sig={sig} q={q} ind={ind} pos={pos} mf={mf}
            cfg={cfg} global={global} notes={notes}
            onClose={onClose} onOpenConfig={() => onOpenConfig(code)} onOpenDetail={onOpenDetail} navigate={navigate} />
        )}
      </div>
    </div>
  );
}

/* ===== 详情面板 ===== */
function DetailPanel({ code, sig, q, ind, pos, mf, cfg, global, notes, onClose, onOpenConfig, navigate }) {
  const [audit, setAudit] = useState([]);
  useEffect(() => {
    apiFetch(`/api/auto-trade/audit?code=${code}`).then(({ ok, data }) => { if (ok) setAudit(data.items || []); });
  }, [code]);

  const price = q.price ?? pos.price ?? 0;
  const cost = pos.costPrice ?? 0;
  const profitPct = pos.profitPct ?? (cost > 0 ? ((price - cost) / cost) * 100 : 0);
  const reasons = (sig.reasons || []).slice(0, 3);
  const mode = cfg?.mode || 'off';
  const p = cfg?.prices || {};
  const rk = cfg?.risk || {};
  const header = (
    <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--border-color)' }}>
      <div>
        <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{q.name || code}</span>
        <span className="ml-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>{code}</span>
      </div>
      <button onClick={onClose} className="px-2 py-0.5 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>✕ 关闭</button>
    </div>
  );

  const Section = ({ title, children }) => (
    <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
      <div className="text-[11px] font-bold mb-1.5" style={{ color: 'var(--accent-blue)' }}>{title}</div>
      {children}
    </div>
  );
  const Row = ({ k, v, c }) => (
    <div className="flex items-center justify-between py-0.5 text-[11px]">
      <span style={{ color: 'var(--text-muted)' }}>{k}</span>
      <span className="font-medium" style={{ color: c || 'var(--text-primary)' }}>{v}</span>
    </div>
  );

  return (
    <>
      {header}
      <div className="flex-1 overflow-y-auto">
        <Section title="📦 持仓信息">
          <Row k="持仓数量" v={`${num(pos.count, 0)} 股`} />
          <Row k="可卖数量" v="—（需券商确认）" />
          <Row k="持仓成本" v={num(cost)} />
          <Row k="当前价格" v={num(price)} />
          <Row k="当前盈亏" v={fmtMoney(pos.profit)} c={(pos.profit ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR} />
          <Row k="盈亏比例" v={pct(profitPct)} c={profitPct >= 0 ? UP_COLOR : DOWN_COLOR} />
          <Row k="当前仓位" v={pos.posPct != null ? `${pos.posPct.toFixed(1)}%` : '—'} />
        </Section>

        <Section title="📊 技术指标">
          <Row k="MA5 / MA20" v={[ind.ma5, ind.ma20].map((v) => v != null ? num(v) : '—').join(' / ')} />
          <Row k="RSI14" v={ind.rsi != null ? num(ind.rsi) : '—'} />
          <Row k="MACD DIF/DEA" v={`${ind.dif != null ? num(ind.dif) : '—'} / ${ind.dea != null ? num(ind.dea) : '—'}`} />
          <Row k="量比/换手" v={mf.turnover_rate != null ? `${num(mf.turnover_rate)}%` : '—'} />
          <Row k="今日主力净流入" v={fmtMoney(mf.main_net)} c={(mf.main_net ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR} />
          <Row k="支撑 / 突破位" v={`${ind.support != null ? num(ind.support) : '—'} / ${ind.resistance != null ? num(ind.resistance) : '—'}`} />
          <Row k="综合评分" v={sig.overallScore != null ? Math.round(sig.overallScore) : '—'} />
        </Section>

        <Section title="🎯 自动交易计划">
          <Row k="模式" v={MODE_TEXT[mode] || '关闭'} />
          <Row k="状态" v={cfg ? `${STATUS_TEXT[cfg.status] || cfg.status}${cfg.status_reason ? '·' + cfg.status_reason : ''}` : '未开启'} c={cfg?.status === 'MONITORING' ? '#22c55e' : 'var(--text-secondary)'} />
          <Row k="防守位" v={p.support_price != null ? num(p.support_price) : '—'} />
          <Row k="确认破位线" v={p.breakdown_price != null ? num(p.breakdown_price) : '—'} />
          <Row k="硬止损价" v={p.hard_stop_price != null ? num(p.hard_stop_price) : '—'} />
          <Row k="第一/第二止盈" v={`${p.take_profit_1 != null ? num(p.take_profit_1) : '—'} / ${p.take_profit_2 != null ? num(p.take_profit_2) : '—'}`} />
          <Row k="移动止损" v={p.trailing_stop_type === 'off' ? '关闭' : `${p.trailing_stop_type}${p.trailing_stop_value ? '(' + p.trailing_stop_value + ')' : ''}`} />
          <Row k="单票最大仓位" v={rk.max_position_pct != null ? `${rk.max_position_pct}%` : '—'} />
          {global && !global.enabled && mode !== 'off' && (
            <div className="mt-1.5 px-2 py-1 rounded text-[10px]" style={{ background: 'rgba(245,158,11,0.1)', color: '#f59e0b' }}>⚠️ 账户总开关关闭，该股自动交易未执行</div>
          )}
        </Section>

        <Section title="💡 触发依据">
          {reasons.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>暂无信号依据</div>
          ) : reasons.map((r, i) => (
            <div key={i} className="py-0.5 text-[11px]" style={{ color: /空头|跌破|流出|亏损/.test(r) ? '#ef4444' : /金叉|流入|盈利|突破/.test(r) ? '#22c55e' : 'var(--text-secondary)' }}>{r}</div>
          ))}
        </Section>

        {notes?.note && (
          <Section title="📝 备注">
            <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{notes.note}</div>
          </Section>
        )}

        <Section title="📋 操作记录（最近）">
          {audit.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>暂无操作记录</div>
          ) : audit.slice(0, 6).map((a, i) => (
            <div key={i} className="flex items-center justify-between py-0.5 text-[10px]">
              <span style={{ color: 'var(--text-secondary)' }}>{a.event_type} {a.reason ? '·' + a.reason : ''}</span>
              <span style={{ color: 'var(--text-muted)' }}>{a.event_time}</span>
            </div>
          ))}
        </Section>
      </div>

      <div className="p-3 border-t shrink-0 flex gap-2" style={{ borderColor: 'var(--border-color)' }}>
        <button onClick={() => navigate(`/stock-analysis?code=${code}`)}
          className="flex-1 px-2 py-1.5 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔍 个股分析</button>
        <button onClick={onOpenConfig}
          className="flex-1 px-2 py-1.5 rounded-lg text-xs font-medium"
          style={{ background: 'var(--accent-blue)', color: '#fff', border: 'none' }}>
          {mode === 'off' ? '⚙️ 配置自动交易' : '⚙️ 调整自动交易'}
        </button>
      </div>
    </>
  );
}

/* ===== 配置面板 ===== */
function ConfigPanel({ code, cfg, global, onClose, onSave, onEnable, onDisable, onPause, onResume }) {
  const [form, setForm] = useState(() => {
    const c = cfg || {};
    const p = c.prices || {};
    const rk = c.risk || {};
    const ac = c.actions || {};
    return {
      mode: c.mode || 'off',
      run_environment: c.run_environment || 'paper',
      authorization_expiry_type: c.authorization_expiry_type || 'daily',
      strategy_id: c.strategy_id || '',
      support_price: p.support_price ?? '', breakdown_price: p.breakdown_price ?? '',
      hard_stop_price: p.hard_stop_price ?? '', breakout_price: p.breakout_price ?? '',
      take_profit_1: p.take_profit_1 ?? '', take_profit_2: p.take_profit_2 ?? '',
      trailing_stop_type: p.trailing_stop_type || 'off',
      max_position_pct: rk.max_position_pct ?? 15, max_single_buy_pct: rk.max_single_buy_pct ?? 30,
      max_single_sell_pct: rk.max_single_sell_pct ?? 50, max_daily_orders: rk.max_daily_orders ?? 2,
      max_total_loss: rk.max_total_loss ?? '', max_slippage_pct: rk.max_slippage_pct ?? 0.5,
      signal_cooldown_seconds: rk.signal_cooldown_seconds ?? 600,
      allow_entry: !!ac.allow_entry, allow_add: !!ac.allow_add, allow_reduce: ac.allow_reduce !== false,
      allow_exit: ac.allow_exit !== false, allow_stop: ac.allow_stop !== false,
      allow_take_profit: ac.allow_take_profit !== false,
    };
  }, [cfg]);
  const [saving, setSaving] = useState(false);
  const [errMsg, setErrMsg] = useState('');
  const [confirmLive, setConfirmLive] = useState('');
  const [showLiveConfirm, setShowLiveConfirm] = useState(false);

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const f2n = (v) => (v === '' || v == null ? null : Number(v));

  // 开启前检查（规范 4.6 前端展示）
  const checks = [
    { ok: form.mode !== 'off', label: '交易模式已选择（风控托管/全自动）' },
    { ok: f2n(form.hard_stop_price) > 0, label: '硬止损价已配置' },
    { ok: f2n(form.max_position_pct) > 0, label: '单票最大仓位已配置' },
    { ok: f2n(form.max_total_loss) != null, label: '单票最大亏损已配置' },
    { ok: f2n(form.max_slippage_pct) != null && f2n(form.max_slippage_pct) > 0, label: '最大滑点已配置' },
    { ok: global?.enabled === true || true, label: '账户总开关（关闭时仅提醒不执行）' },
  ];
  const allPass = checks.slice(0, 5).every((c) => c.ok);

  const handleSave = async (enable) => {
    setSaving(true); setErrMsg('');
    const patch = {
      mode: form.mode,
      run_environment: form.run_environment,
      authorization_expiry_type: form.authorization_expiry_type,
      strategy_id: form.strategy_id,
      prices: {
        support_price: f2n(form.support_price), breakdown_price: f2n(form.breakdown_price),
        hard_stop_price: f2n(form.hard_stop_price), breakout_price: f2n(form.breakout_price),
        take_profit_1: f2n(form.take_profit_1), take_profit_2: f2n(form.take_profit_2),
        trailing_stop_type: form.trailing_stop_type,
      },
      risk: {
        max_position_pct: f2n(form.max_position_pct), max_single_buy_pct: f2n(form.max_single_buy_pct),
        max_single_sell_pct: f2n(form.max_single_sell_pct), max_daily_orders: f2n(form.max_daily_orders),
        max_total_loss: f2n(form.max_total_loss), max_slippage_pct: f2n(form.max_slippage_pct),
        signal_cooldown_seconds: f2n(form.signal_cooldown_seconds),
      },
      actions: {
        allow_entry: form.allow_entry, allow_add: form.allow_add, allow_reduce: form.allow_reduce,
        allow_exit: form.allow_exit, allow_stop: form.allow_stop, allow_take_profit: form.allow_take_profit,
      },
    };
    const okSaved = await onSave(code, patch);
    if (!okSaved) { setSaving(false); setErrMsg('保存失败，请重试'); return; }
    if (!enable) { setSaving(false); onClose(); return; }

    // 实盘二次确认
    if (form.run_environment === 'live' && !showLiveConfirm) {
      setShowLiveConfirm(true); setSaving(false); return;
    }
    const res = await onEnable(code, 'user');
    if (!res.ok) {
      setErrMsg(res.message || '开启前检查未通过'); setSaving(false);
      return;
    }
    setSaving(false); onClose();
  };

  const inputStyle = {
    width: '100%', boxSizing: 'border-box', border: '0.5px solid var(--border-color)', borderRadius: 6,
    padding: '4px 8px', fontSize: 12, background: 'var(--bg-input)', color: 'var(--text-primary)',
  };
  const Section = ({ title, children }) => (
    <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
      <div className="text-[11px] font-bold mb-1.5" style={{ color: 'var(--accent-blue)' }}>{title}</div>
      {children}
    </div>
  );
  const Field = ({ label, children }) => (
    <div className="flex items-center justify-between py-1 gap-2">
      <span className="text-[11px] shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <div className="w-32 shrink-0">{children}</div>
    </div>
  );
  const Radio = ({ active, onClick, label, desc }) => (
    <button onClick={onClick}
      className="flex-1 px-2 py-1.5 rounded-lg border text-[11px] text-left"
      style={{ borderColor: active ? 'var(--accent-blue)' : 'var(--border-color)', background: active ? 'rgba(59,130,246,0.08)' : 'transparent', color: active ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
      <div className="font-medium">{label}</div>
      {desc && <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{desc}</div>}
    </button>
  );

  const isLive = form.run_environment === 'live';

  return (
    <>
      <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--border-color)' }}>
        <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 个股自动交易配置 · {code}</span>
        <button onClick={onClose} className="px-2 py-0.5 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>✕</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <Section title="运行设置">
          <div className="flex gap-1.5 mb-1.5">
            <Radio active={form.mode === 'off'} onClick={() => set('mode', 'off')} label="关闭" desc="只提醒不下单" />
            <Radio active={form.mode === 'risk_only'} onClick={() => set('mode', 'risk_only')} label="风控托管" desc="减仓/止损/止盈" />
            <Radio active={form.mode === 'full_auto'} onClick={() => set('mode', 'full_auto')} label="全自动" desc="开/加/减/止盈" />
          </div>
          <div className="flex gap-1.5 mb-1.5">
            <Radio active={form.run_environment === 'paper'} onClick={() => set('run_environment', 'paper')} label="模拟" />
            <Radio active={isLive} onClick={() => set('run_environment', 'live')} label="实盘" />
            <Radio active={form.authorization_expiry_type === 'daily'} onClick={() => set('authorization_expiry_type', 'daily')} label="仅当日" />
            <Radio active={form.authorization_expiry_type === 'persistent'} onClick={() => set('authorization_expiry_type', 'persistent')} label="持续" />
          </div>
          <Field label="策略 ID"><input value={form.strategy_id} onChange={(e) => set('strategy_id', e.target.value)} placeholder="可选" style={inputStyle} /></Field>
        </Section>

        <Section title="关键价格">
          <Field label="防守位"><input type="number" value={form.support_price} onChange={(e) => set('support_price', e.target.value)} placeholder="43.00" style={inputStyle} /></Field>
          <Field label="确认破位线"><input type="number" value={form.breakdown_price} onChange={(e) => set('breakdown_price', e.target.value)} placeholder="42.80" style={inputStyle} /></Field>
          <Field label="硬止损价"><input type="number" value={form.hard_stop_price} onChange={(e) => set('hard_stop_price', e.target.value)} placeholder="41.50" style={inputStyle} /></Field>
          <Field label="突破位"><input type="number" value={form.breakout_price} onChange={(e) => set('breakout_price', e.target.value)} placeholder="46.00" style={inputStyle} /></Field>
          <Field label="第一止盈位"><input type="number" value={form.take_profit_1} onChange={(e) => set('take_profit_1', e.target.value)} placeholder="45.98" style={inputStyle} /></Field>
          <Field label="第二止盈位"><input type="number" value={form.take_profit_2} onChange={(e) => set('take_profit_2', e.target.value)} placeholder="48.50" style={inputStyle} /></Field>
          <Field label="移动止损">
            <select value={form.trailing_stop_type} onChange={(e) => set('trailing_stop_type', e.target.value)} style={inputStyle}>
              <option value="off">关闭</option><option value="ma10">MA10</option><option value="2atr">2ATR</option>
            </select>
          </Field>
        </Section>

        <Section title="风控限制">
          <Field label="单票最大仓位%"><input type="number" value={form.max_position_pct} onChange={(e) => set('max_position_pct', e.target.value)} style={inputStyle} /></Field>
          <Field label="单次最大买入%"><input type="number" value={form.max_single_buy_pct} onChange={(e) => set('max_single_buy_pct', e.target.value)} style={inputStyle} /></Field>
          <Field label="单次最大卖出%"><input type="number" value={form.max_single_sell_pct} onChange={(e) => set('max_single_sell_pct', e.target.value)} style={inputStyle} /></Field>
          <Field label="单票最大亏损¥"><input type="number" value={form.max_total_loss} onChange={(e) => set('max_total_loss', e.target.value)} placeholder="如 -3000" style={inputStyle} /></Field>
          <Field label="单日最大订单"><input type="number" value={form.max_daily_orders} onChange={(e) => set('max_daily_orders', e.target.value)} style={inputStyle} /></Field>
          <Field label="最大滑点%"><input type="number" step="0.1" value={form.max_slippage_pct} onChange={(e) => set('max_slippage_pct', e.target.value)} style={inputStyle} /></Field>
          <Field label="信号冷却(秒)"><input type="number" value={form.signal_cooldown_seconds} onChange={(e) => set('signal_cooldown_seconds', e.target.value)} style={inputStyle} /></Field>
        </Section>

        <Section title="允许动作">
          {[
            ['allow_reduce', '允许减仓'], ['allow_stop', '允许止损'], ['allow_take_profit', '允许止盈'],
            ['allow_exit', '允许清仓'], ['allow_entry', '允许开仓'], ['allow_add', '允许加仓'],
          ].map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5 py-0.5 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
              <input type="checkbox" checked={form[k]} onChange={(e) => set(k, e.target.checked)} />
              {label}
              {k === 'allow_entry' || k === 'allow_add' ? <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>（风控托管默认禁止）</span> : null}
            </label>
          ))}
        </Section>

        <Section title="开启前检查">
          {checks.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5 py-0.5 text-[11px]" style={{ color: c.ok ? '#22c55e' : 'var(--text-muted)' }}>
              <span>{c.ok ? '✅' : '⬜'}</span>{c.label}
            </div>
          ))}
        </Section>

        {showLiveConfirm && (
          <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <div className="rounded-lg p-2.5 text-[11px] space-y-1" style={{ background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.3)' }}>
              <div style={{ color: '#ef4444', fontWeight: 600 }}>⚠️ 确认开启「{code}」实盘自动交易？</div>
              <div style={{ color: 'var(--text-secondary)' }}>模式：{MODE_TEXT[form.mode]} · 有效期：{form.authorization_expiry_type === 'daily' ? '仅当日' : '持续有效'}</div>
              <div style={{ color: 'var(--text-secondary)' }}>请输入确认文字：开启实盘</div>
              <input value={confirmLive} onChange={(e) => setConfirmLive(e.target.value)} placeholder="开启实盘" style={{ ...inputStyle, borderColor: 'rgba(239,68,68,0.5)' }} />
            </div>
          </div>
        )}

        {errMsg && (
          <div className="px-4 py-2 text-[11px]" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.06)' }}>{errMsg}</div>
        )}
      </div>

      <div className="p-3 border-t shrink-0 space-y-1.5" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex gap-2">
          <button onClick={onClose} className="px-2.5 py-1.5 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>取消</button>
          <button onClick={() => handleSave(false)} disabled={saving} className="px-2.5 py-1.5 rounded-lg border text-xs disabled:opacity-50"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>保存</button>
          <button onClick={() => handleSave(true)} disabled={saving || (showLiveConfirm && confirmLive !== '开启实盘')} className="flex-1 px-2.5 py-1.5 rounded-lg text-xs font-medium disabled:opacity-40"
            style={{ background: 'var(--accent-blue)', color: '#fff', border: 'none' }}>
            {saving ? '处理中…' : (showLiveConfirm ? '确认开启' : (form.mode === 'off' ? '保存（未开启）' : '保存并开启'))}
          </button>
        </div>
        {cfg && cfg.mode !== 'off' && (
          <div className="flex gap-2">
            {cfg.status === 'PAUSED' ? (
              <button onClick={() => onResume(code)} className="flex-1 px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'rgba(34,197,94,0.4)', color: '#22c55e' }}>▶ 恢复监控</button>
            ) : (
              <button onClick={() => onPause(code, '手动暂停')} className="flex-1 px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'rgba(249,115,22,0.4)', color: '#f97316' }}>⏸ 暂停</button>
            )}
            <button onClick={() => onDisable(code)} className="flex-1 px-2 py-1 rounded-lg border text-[11px]" style={{ borderColor: 'rgba(239,68,68,0.4)', color: '#ef4444' }}>⛔ 关闭自动交易</button>
          </div>
        )}
      </div>
    </>
  );
}

/* ===== 审计面板 ===== */
function AuditPanel({ items, code, onClose, onRefresh }) {
  return (
    <>
      <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--border-color)' }}>
        <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📋 自动交易操作记录{code ? ` · ${code}` : ''}</span>
        <div className="flex gap-1.5">
          <button onClick={onRefresh} className="px-2 py-0.5 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄</button>
          <button onClick={onClose} className="px-2 py-0.5 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>✕</button>
        </div>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-2.5 space-y-1">
        {items.length === 0 ? (
          <div className="text-center py-10 text-xs" style={{ color: 'var(--text-muted)' }}>暂无记录</div>
        ) : items.map((a, i) => (
          <div key={a.id || i} className="rounded-lg border px-2.5 py-1.5 text-[11px]" style={{ borderColor: 'var(--border-color)' }}>
            <div className="flex items-center justify-between">
              <span className="font-medium" style={{ color: 'var(--accent-blue)' }}>{a.event_type}</span>
              <span style={{ color: 'var(--text-muted)' }}>{a.event_time}</span>
            </div>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{a.code || '全局'} · {a.operator || 'user'}{a.reason ? ` · ${a.reason}` : ''}</div>
          </div>
        ))}
      </div>
    </>
  );
}
