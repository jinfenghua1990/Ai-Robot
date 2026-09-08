import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { openStockAnalysis } from '../../utils/openStockAnalysis';
import { apiFetch } from '../../utils/request';
import { formatWan, toFiniteNumber } from '../../utils/format';
import StockActionButtons from '../../components/trading/StockActionButtons';
import StockTableFrame, { STOCK_TABLE_SURFACE } from '../../components/StockTableFrame';

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

const num = (v, d = 2) => {
  const n = toFiniteNumber(v);
  return n == null ? '—' : n.toFixed(d);
};
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

function DrawerSection({ title, children }) {
  return (
    <div className="px-4 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
      <div className="text-[11px] font-bold mb-1.5" style={{ color: 'var(--accent-blue)' }}>{title}</div>
      {children}
    </div>
  );
}

function PortfolioDetailRow({ k, v, c }) {
  return (
    <div className="flex items-center justify-between py-0.5 text-[11px]">
      <span style={{ color: 'var(--text-muted)' }}>{k}</span>
      <span className="font-medium" style={{ color: c || 'var(--text-primary)' }}>{v}</span>
    </div>
  );
}

function ConfigField({ label, children }) {
  return (
    <div className="flex items-center justify-between py-1 gap-2">
      <span className="text-[11px] shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <div className="w-32 shrink-0">{children}</div>
    </div>
  );
}

function ConfigRadio({ active, onClick, label, desc }) {
  return (
    <button onClick={onClick}
      className="flex-1 px-2 py-1.5 rounded-lg border text-[11px] text-left"
      style={{ borderColor: active ? 'var(--accent-blue)' : 'var(--border-color)', background: active ? 'rgba(59,130,246,0.08)' : 'transparent', color: active ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
      <div className="font-medium">{label}</div>
      {desc && <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{desc}</div>}
    </button>
  );
}

/** 持仓 + 自选信号 + 自动交易配置 → 表格行 */
function buildRow(holding, sig, cfg, global) {
  const q = sig?.quote || {};
  const ind = sig?.indicators || {};
  const pos = sig?.position || {};
  const mf = sig?.moneyFlow || {};
  const sectorTrend = sig?.sectorTrend || sig?.sector_trend || {};
  const sector = sig?.sector || sectorTrend.sector || holding.sector || '—';
  const sectorFlow = sectorTrend.total_net_flow ?? null;
  const sectorHeat = sectorTrend.latest_heat ?? null;
  const sectorState = sectorTrend.flow_direction === 'inflow' ? '资金流入' : sectorTrend.flow_direction === 'outflow' ? '资金流出' : sectorTrend.heat_trend === 'up' ? '板块升温' : sectorTrend.heat_trend === 'down' ? '板块降温' : '板块中性';
  const price = q.price ?? holding.last_price ?? pos.price ?? 0;
  const cost = pos.costPrice ?? holding.avg_cost ?? 0;
  const changePct = q.changePct ?? holding.day_pnl_pct ?? pos.dayProfitPct ?? null;
  const dayPnl = holding.day_pnl ?? pos.dayProfit ?? null;
  const profitPct = pos.profitPct ?? (cost > 0 ? ((price - cost) / cost) * 100 : 0);
  const profit = pos.profit ?? ((price - cost) * (holding.quantity ?? 0));
  const score = sig?.overallScore ?? null;
  // 均线结构：明确展示 MA5 / MA20 / MA60 的数值、排列和现价相对 MA20 的偏离。
  let maStruct = '—';
  const ma5Val = ind.ma5 ?? null;
  const ma20Val = ind.ma20 ?? null;
  const ma60Val = ind.ma60 ?? null;
  const ma20Above = (ma20Val != null && price != null) ? price >= ma20Val : null;
  const ma20Dist = (ma20Val != null && price != null) ? (price - ma20Val) / ma20Val * 100 : null;
  const ma20Slope = ind.ma20_slope ?? null;
  const maOrder = ma5Val != null && ma20Val != null && ma60Val != null
    ? (ma5Val >= ma20Val && ma20Val >= ma60Val ? '多头排列' : ma5Val <= ma20Val && ma20Val <= ma60Val ? '空头排列' : '均线交错')
    : ma5Val != null && ma20Val != null ? (ma5Val >= ma20Val ? '短线多头' : '短线空头') : '—';
  if (ma20Val != null) maStruct = `${maOrder} · ${ma20Above ? '现价高于 MA20' : '现价低于 MA20'}`;
  // MACD
  let macdTxt = '—';
  if (ind.dif != null && ind.dea != null) {
    macdTxt = ind.dif >= ind.dea ? (ind.dif >= 0 ? '零轴上金叉' : '零轴下金叉') : '死叉';
  } else if (ind.macd != null) {
    macdTxt = ind.macd >= 0 ? '多头' : '空头';
  }
  const kdj = ind.kdj || {};
  const kdjK = kdj.k ?? ind.kdj_k ?? null;
  const kdjD = kdj.d ?? ind.kdj_d ?? null;
  const kdjJ = kdj.j ?? ind.kdj_j ?? null;
  const rsi = ind.rsi ?? null;
  const support = ind.support ?? null;
  const resistance = ind.resistance ?? null;
  const kdjState = kdjJ == null ? '—' : kdjJ >= 100 ? '超买' : kdjJ <= 0 ? '超卖' : kdjK != null && kdjD != null && kdjK >= kdjD ? '金叉偏强' : '死叉偏弱';
  const riskHints = [];
  if (rsi != null && rsi >= 70) riskHints.push({ text: 'RSI超买', tone: 'warn' });
  if (kdjState === '超买') riskHints.push({ text: 'KDJ超买', tone: 'warn' });
  if (ma20Above === false) riskHints.push({ text: '跌破MA20·止损观察', tone: 'danger' });
  if (support != null && price < support) riskHints.push({ text: '跌破支撑·止损关注', tone: 'danger' });
  if (/死叉/.test(macdTxt)) riskHints.push({ text: 'MACD死叉·收紧止损', tone: 'danger' });
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
    price, changePct, dayPnl, cost, profitPct, profit,
    quantity: holding.quantity ?? null,
    marketValue: holding.market_value ?? (price * (holding.quantity ?? 0)),
    posPct: pos.posPct ?? holding.pos_pct ?? null,
    score,
    maStruct, ma5Val, ma20Val, ma60Val, maOrder, ma20Above, ma20Dist, ma20Slope, rsi, macdTxt,
    kdjK, kdjD, kdjJ, kdjState, riskHints,
    volRatio: mf.turnover_rate ?? null,
    mainNet: mf.main_net ?? null, sector, sectorFlow, sectorHeat, sectorState,
    support, resistance,
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

  // 排序状态：默认按盈亏比例降序（盈利在上方）
  const [sortKey, setSortKey] = useState('profitPct');
  const [sortDir, setSortDir] = useState('desc');

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

  // 点击表头排序：再次点击切换升/降序
  const toggleSort = (key) => {
    if (sortKey === key) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  };

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

  const positions = useMemo(() => portfolio?.positions ?? [], [portfolio?.positions]);
  const totalMv = portfolio?.total_market_value ?? 0;
  const totalPnl = portfolio?.total_unrealized_pnl ?? 0;
  const totalAssets = portfolio?.total_assets ?? (totalMv + (portfolio?.available_cash ?? 0));
  const availableCash = portfolio?.available_cash ?? 0;
  const totalCost = portfolio?.total_cost ?? 0;
  const totalDayPnl = portfolio?.total_day_pnl ?? 0;

  const rows = useMemo(() => positions
    .map((p) => buildRow(p, wlSignals[p.symbol], autoStocks[p.symbol], autoGlobal))
    .sort((a, b) => {
      if (sortKey === 'risk') {
        // 风险指令优先：已开启自动交易置顶，其次按盈亏比例降序
        const ra = a.mode !== 'off' ? 1 : 0;
        const rb = b.mode !== 'off' ? 1 : 0;
        if (ra !== rb) return rb - ra;
        return (b.profitPct ?? 0) - (a.profitPct ?? 0);
      }
      const va = a[sortKey];
      const vb = b[sortKey];
      const na = (va == null || isNaN(Number(va)));
      const nb = (vb == null || isNaN(Number(vb)));
      if (na && nb) return 0;
      if (na) return 1;   // 缺失值排末尾
      if (nb) return -1;
      const diff = Number(va) - Number(vb);
      return sortDir === 'desc' ? -diff : diff;
    }), [positions, wlSignals, autoStocks, autoGlobal, sortKey, sortDir]);

  const g = autoGlobal || { enabled: false, run_environment: 'paper', paused: false, today_orders: 0, today_pnl: 0 };
  const riskCount = rows.filter((r) => r.mode !== 'off').length;
  const lossCount = rows.filter((r) => (r.profitPct ?? 0) < 0).length;
  const sumMv = rows.reduce((s, r) => s + (r.price || 0) * (r.quantity || 0), 0);
  const sumProfit = rows.reduce((s, r) => s + (r.profit || 0), 0);
  const sumCost = sumMv - sumProfit;
  const sumProfitPct = sumCost > 0 ? (sumProfit / sumCost) * 100 : 0;

  return (
    <div className="space-y-3">

      {/* ===== 持仓页工具栏 ===== */}
      <div className="rounded-xl p-2.5 space-y-2"
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

      {/* ===== 数据质量提示 ===== */}
      {portfolio?.data_quality && (
        <div className="rounded-xl border px-2.5 py-1.5 text-[11px]" style={{ background: 'rgba(245,158,11,0.08)', borderColor: 'rgba(245,158,11,0.3)', color: '#f59e0b' }}>
          ⚠️ {portfolio.data_quality}
        </div>
      )}

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
          { label: '总盈亏', value: formatWan(totalPnl), color: totalPnl >= 0 ? UP_COLOR : DOWN_COLOR, sub: totalCost > 0 ? `持仓成本收益率 ${((totalPnl / totalCost) * 100).toFixed(2)}%` : (totalPnl >= 0 ? '盈利中' : '亏损中') },
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
        <StockTableFrame
          minWidth={1480}
          footer={
            <div className="flex items-center gap-3 px-3 py-1.5 text-[10px] flex-wrap" style={{ borderTop: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
              <span>点击行查看详情 · 点击「自动交易」配置个股</span>
              <span><b style={{ color: 'var(--accent-blue)' }}>MA5</b> 短期 · <b style={{ color: 'var(--accent-amber)' }}>MA20</b> 中期 · MA60 长期</span>
              <button onClick={() => { setSortKey('risk'); setSortDir('desc'); }}
                className="px-1.5 py-0.5 rounded border text-[10px]"
                style={{
                  borderColor: sortKey === 'risk' ? 'var(--accent-blue)' : 'var(--border-color)',
                  color: sortKey === 'risk' ? 'var(--accent-blue)' : 'var(--text-muted)',
                  background: sortKey === 'risk' ? 'rgba(59,130,246,0.08)' : 'transparent',
                }}>⚡ 风险优先</button>
              <button onClick={() => { setSortKey('profit'); setSortDir('desc'); }}
                className="px-1.5 py-0.5 rounded border text-[10px]"
                style={{
                  borderColor: sortKey === 'profit' ? 'var(--accent-blue)' : 'var(--border-color)',
                  color: sortKey === 'profit' ? 'var(--accent-blue)' : 'var(--text-muted)',
                  background: sortKey === 'profit' ? 'rgba(59,130,246,0.08)' : 'transparent',
                }}>💰 按金额</button>
              <span className="flex-1" />
              <span>默认按盈亏%排序（盈利在上）· 可切「按金额」· 关键位决定动作 · 技术指标负责确认</span>
            </div>
          }>
          <thead>
                <tr style={{ background: STOCK_TABLE_SURFACE }}>
                  {[
                    { k: '股票', w: 130, sticky: 'left', align: 'left' },
                    { k: '数量', w: 105, align: 'right', sort: 'quantity' },
                    { k: '现价 / 成本价', w: 112, align: 'left' },
                    { k: '当日盈亏 / 当日涨幅', w: 126, align: 'left', sort: 'changePct' },
                    { k: '持仓盈亏 / 持仓收益率', w: 136, align: 'left', sort: 'profitPct' },
                    { k: '仓位', w: 62, align: 'right', sort: 'posPct' },
                    { k: '评分', w: 56, align: 'center', sort: 'score' },
                    { k: '均线结构（MA5/20/60）', w: 190, align: 'left' },
                    { k: 'RSI14', w: 56, align: 'center', sort: 'rsi' },
                    { k: 'MACD状态', w: 92, align: 'left' },
                    { k: 'KDJ（K/D/J）', w: 104, align: 'left' },
                    { k: '换手率', w: 64, align: 'center', sort: 'volRatio' },
                    { k: '个股资金 / 板块', w: 148, align: 'left', sort: 'mainNet' },
                    { k: '支撑 / 压力位', w: 112, align: 'left' },
                    { k: '风险提示', w: 150, align: 'left' },
                    { k: '建议', w: 92, align: 'left' },
                    { k: '操作', w: 176, align: 'center' },
                    { k: '自动交易', w: 128, sticky: 'right', align: 'center' },
                  ].map((c) => {
                    const active = sortKey === c.sort;
                    const arrow = !c.sort ? null : active ? (sortDir === 'desc' ? '▼' : '▲') : '⇅';
                    const headColor = c.sort ? (active ? 'var(--accent-blue)' : 'var(--text-muted)') : 'var(--text-muted)';
                    return (
                      <th key={c.k} className="px-2 py-1.5 font-semibold whitespace-nowrap"
                        style={{
                          color: headColor, width: c.w, textAlign: c.align || 'left',
                          position: c.sticky ? 'sticky' : 'static',
                          left: c.sticky === 'left' ? 0 : undefined, right: c.right != null ? c.right : (c.sticky === 'right' ? 0 : undefined),
                          zIndex: c.sticky ? 2 : 1, background: STOCK_TABLE_SURFACE,
                        }}>
                        {c.sort ? (
                          <button onClick={() => toggleSort(c.sort)} title="点击排序"
                            className="flex items-center gap-0.5 select-none w-full"
                            style={{
                              justifyContent: c.align === 'right' ? 'flex-end' : c.align === 'center' ? 'center' : 'flex-start',
                              color: headColor, background: 'transparent', border: 'none',
                              font: 'inherit', fontWeight: 600, cursor: 'pointer', padding: 0,
                            }}>
                            <span>{c.k}</span>
                            <span style={{ fontSize: 9, opacity: active ? 1 : 0.5 }}>{arrow}</span>
                          </button>
                        ) : c.k}
                      </th>
                    );
                  })}
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const profitVal = r.profit ?? 0;
                  const rowBg = profitVal >= 0 ? 'rgba(239,68,68,0.04)' : 'rgba(34,197,94,0.04)';
                  return (
                  <tr key={r.code} onClick={(e) => {
                    // 表格内的买卖、分析、自动交易等控件只执行自身动作，不能同时打开详情抽屉。
                    if (e.target.closest('button, a, input, select, textarea, .fixed')) return;
                    openDetail(r.code);
                  }}
                    className="cursor-pointer hover:opacity-90 transition-colors"
                    style={{ borderTop: '1px solid var(--border-color)', background: rowBg }}>
                    {/* 股票（固定左） */}
                    <td className="px-2 py-1 whitespace-nowrap sticky left-0 z-[2]" style={{ background: rowBg }}>
                      <div className="flex items-center gap-1.5">
                        <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                        <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{r.code}</span>
                        {(r.profitPct ?? 0) < 0 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: DOWN_COLOR }}>亏</span>}
                      </div>
                    </td>
                    {/* 数量 */}
                    <td className="px-2 py-1 whitespace-nowrap text-right" style={{ color: 'var(--text-secondary)' }}>
                      <div>{r.quantity != null ? `${num(r.quantity, 0)}股` : '—'}</div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>持仓金额 {fmtMoney(r.marketValue)}</div>
                    </td>
                    {/* 价格列只放价格：现价与持仓平均成本直接对比 */}
                    <td className="px-2 py-1 whitespace-nowrap">
                      <div style={{ color: 'var(--text-primary)', fontWeight: 600 }}>现价 {num(r.price)}</div>
                      <div style={{ color: 'var(--text-muted)' }}>成本 {num(r.cost)}</div>
                    </td>
                    {/* 当日盈亏与当日涨幅成对显示 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="当日盈亏为券商/模拟盘提供的当日浮动金额；当日涨幅为相对昨日收盘价的百分比。">
                      <div style={{ color: (r.dayPnl ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>盈亏 {fmtMoney(r.dayPnl)}</div>
                      <div style={{ color: (r.changePct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>涨幅 {pct(r.changePct)}</div>
                    </td>
                    {/* 持仓盈亏与持仓收益率成对显示 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="持仓盈亏金额 =（现价 - 持仓成本）× 持仓数量；持仓收益率以持仓成本为基准。">
                      <div style={{ color: (r.profit ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>盈亏 {fmtMoney(r.profit)}</div>
                      <div style={{ color: (r.profitPct ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>收益 {pct(r.profitPct)}</div>
                    </td>
                    {/* 仓位 */}
                    <td className="px-2 py-1 text-right" style={{ color: 'var(--text-secondary)' }}>
                      {r.posPct != null ? `${num(r.posPct, 1)}%` : '—'}
                    </td>
                    {/* 评分 */}
                    <td className="px-2 py-1 text-center">
                      {r.score != null ? (
                        <span className="font-bold" style={{ color: r.score >= 70 ? UP_COLOR : r.score >= 55 ? '#f59e0b' : 'var(--text-muted)' }}>{Math.round(r.score)}</span>
                      ) : <span style={{ color: 'var(--text-muted)' }}>—</span>}
                    </td>
                    {/* 均线结构：明确均线周期、均线值、排列及现价偏离 */}
                    <td
                      className="px-2 py-1 whitespace-nowrap cursor-help"
                      title={'MA5、MA20、MA60 为对应交易日收盘价均线；排列表示短中长期均线的相对位置；现价偏离 MA20 的百分比不是收益率。'}
                    >
                      <div className="font-mono text-[10px]">
                        <span style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>MA5 {r.ma5Val != null ? num(r.ma5Val) : '—'}</span>
                        <span style={{ color: 'var(--border-color)' }}> · </span>
                        <span style={{ color: 'var(--accent-amber)', fontWeight: 700 }}>MA20 {r.ma20Val != null ? num(r.ma20Val) : '—'}</span>
                        <span style={{ color: 'var(--border-color)' }}> · </span>
                        <span style={{ color: 'var(--text-muted)' }}>MA60 {r.ma60Val != null ? num(r.ma60Val) : '—'}</span>
                      </div>
                      <div style={{ color: r.ma20Above ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>
                        {r.maOrder} · {r.ma20Above ? '现价高于 MA20' : '现价低于 MA20'}
                        {r.ma20Dist != null ? ` ${r.ma20Dist >= 0 ? '+' : ''}${num(r.ma20Dist, 1)}%` : ''}
                      </div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        {r.ma20Slope == null ? 'MA20斜率：—' : `MA20斜率：${r.ma20Slope >= 0 ? '+' : ''}${num(r.ma20Slope, 1)}%`}
                      </div>
                    </td>
                    {/* RSI14：14日相对强弱指标 */}
                    <td className="px-2 py-1 text-center" title="RSI14：14日相对强弱指标，通常 70 以上偏超买，30 以下偏超卖。" style={{ color: r.rsi == null ? 'var(--text-muted)' : r.rsi >= 70 ? UP_COLOR : r.rsi <= 30 ? DOWN_COLOR : 'var(--text-secondary)' }}>
                      {r.rsi != null ? num(r.rsi, 0) : '—'}
                    </td>
                    {/* MACD：显示交叉和零轴位置 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="MACD状态：金叉/死叉表示 DIF 与 DEA 的交叉，零轴上/下表示多空背景。" style={{ color: /金叉/.test(r.macdTxt) ? UP_COLOR : /死叉/.test(r.macdTxt) ? DOWN_COLOR : 'var(--text-muted)' }}>{r.macdTxt}</td>
                    {/* KDJ：补齐 K/D/J 数值和状态 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="KDJ：K、D、J 为随机指标三条线；金叉偏强，死叉偏弱，J值极高/极低提示超买/超卖。">
                      <div className="font-mono text-[10px]" style={{ color: 'var(--text-secondary)' }}>K {r.kdjK == null ? '—' : num(r.kdjK, 1)} / D {r.kdjD == null ? '—' : num(r.kdjD, 1)} / J {r.kdjJ == null ? '—' : num(r.kdjJ, 1)}</div>
                      <div style={{ color: /金叉|超买/.test(r.kdjState) ? UP_COLOR : /死叉|超卖/.test(r.kdjState) ? DOWN_COLOR : 'var(--text-muted)' }}>{r.kdjState}</div>
                    </td>
                    {/* 换手率：当日成交活跃度，不等于资金流入 */}
                    <td className="px-2 py-1 text-center" title="换手率：当日成交股数占流通股本的比例，用于衡量交易活跃度。" style={{ color: r.volRatio == null ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
                      {r.volRatio != null ? `${num(r.volRatio, 1)}%` : '—'}
                    </td>
                    {/* 个股资金 + 所属板块：一列两层，避免继续增加表格宽度 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="个股资金为行情估算的主力净买入/净卖出；板块信息用于判断所属行业的热度和资金方向，不等于账户资金。">
                      <div style={{ color: (r.mainNet ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>主力 {fmtMoney(r.mainNet)}</div>
                      <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{r.sector} · {r.sectorState}{r.sectorHeat != null ? ` ${num(r.sectorHeat, 1)}` : ''}</div>
                    </td>
                    {/* 关键位：支撑价与压力/突破价 */}
                    <td className="px-2 py-1 whitespace-nowrap" title="支撑位：价格回落时可能获得承接的位置；压力位：价格上涨时可能遇到抛压的位置。" style={{ color: 'var(--text-muted)' }}>
                      {r.support != null ? `支撑 ${num(r.support)}` : '支撑 —'}{r.resistance != null ? ` · 压力 ${num(r.resistance)}` : ' · 压力 —'}
                    </td>
                    {/* 风险提示：只做提醒，不直接执行交易 */}
                    <td className="px-2 py-1" title="技术风险提示仅供复核，不会自动改变持仓或触发交易。">
                      {r.riskHints.length > 0 ? (
                        <div className="flex flex-wrap gap-1">
                          {r.riskHints.map((h) => <span key={h.text} className="px-1 py-0.5 rounded text-[9px] whitespace-nowrap" style={{ background: h.tone === 'danger' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.14)', color: h.tone === 'danger' ? '#ef4444' : '#d97706' }}>{h.text}</span>)}
                        </div>
                      ) : <span style={{ color: 'var(--text-muted)' }}>暂无明显风险</span>}
                    </td>
                    {/* 建议 */}
                    <td className="px-2 py-1 whitespace-nowrap font-medium" style={{ color: ACTION_COLOR(r.action) }}>{r.action}</td>
                    {/* 操作（买入/卖出/分析/更多；普通列，宽度裁溢出，避免与自动交易列错位重叠） */}
                    <td className="px-2 py-1 text-center" style={{ background: rowBg, width: 176, maxWidth: 176, overflow: 'hidden' }}>
                      <StockActionButtons
                        stockCode={r.code}
                        stockName={r.name}
                        positionCount={r.quantity || 0}
                        size="xs"
                        showKline={false}
                        showWatch={false}
                        showTrack={false}
                        showSina={false}
                        showAutoTrade={false}
                      />
                    </td>
                    {/* 自动交易（固定右，唯一 sticky 列，始终可见） */}
                    <td className="px-2 py-1 text-center sticky right-0 z-[2]" style={{ background: rowBg }}>
                      <button
                        onClick={(e) => { e.stopPropagation(); openConfig(r.code); }}
                        className="px-1.5 py-0.5 rounded border text-[10px] whitespace-nowrap"
                        style={{ borderColor: `${r.atColor}55`, color: r.atColor, background: `${r.atColor}10` }}>
                        {r.atStatus}{r.atHint ? `·${r.atHint}` : ''}
                      </button>
                    </td>
                  </tr>
                );})}
              </tbody>
              <tfoot>
                <tr style={{ borderTop: '2px solid var(--border-color)', background: STOCK_TABLE_SURFACE }}>
                  <td colSpan={18} className="px-3 py-2">
                    <div className="flex items-center gap-4 flex-wrap text-[11px]">
                      <span style={{ color: 'var(--text-muted)' }}>合计 {rows.length} 只</span>
                      <span>持仓市值 <b style={{ color: 'var(--text-primary)' }}>{formatWan(sumMv)}</b></span>
                      <span>总盈亏 <b style={{ color: sumProfit >= 0 ? UP_COLOR : DOWN_COLOR }}>{formatWan(sumProfit)}（{pct(sumProfitPct)}）</b></span>
                      <span className="flex-1" />
                      <span style={{ color: 'var(--text-muted)' }}>与顶部总览卡片一致</span>
                    </div>
                  </td>
                </tr>
              </tfoot>
        </StockTableFrame>
      )}

      {/* ===== 右侧抽屉 ===== */}
      {drawer && (
        <Drawer code={drawerCode} mode={drawer}
          wlSignal={drawerCode ? wlSignals[drawerCode] : null}
          holding={drawerCode ? positions.find(p => p.symbol === drawerCode) : null}
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
function Drawer({ code, mode, wlSignal, holding, cfg, global, notes, auditItems, onClose, onOpenConfig, onOpenDetail, onSave, onEnable, onDisable, onPause, onResume, onRefreshAudit, navigate }) {
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
            holding={holding}
            cfg={cfg} global={global} notes={notes}
            onClose={onClose} onOpenConfig={() => onOpenConfig(code)} onOpenDetail={onOpenDetail} navigate={navigate} />
        )}
      </div>
    </div>
  );
}

/* ===== 详情面板 ===== */
function DetailPanel({ code, sig, q, ind, pos, mf, holding, cfg, global, notes, onClose, onOpenConfig, navigate }) {
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

  return (
    <>
      {header}
      <div className="flex-1 overflow-y-auto">
        <DrawerSection title="📦 持仓信息">
          <PortfolioDetailRow k="持仓数量" v={holding?.quantity != null ? `${num(holding.quantity, 0)} 股` : pos.count != null ? `${num(pos.count, 0)} 股` : '— 股'} />
          <PortfolioDetailRow k="可卖数量" v={holding?.quantity != null ? `${num(holding.quantity, 0)} 股（模拟盘）` : '—（需券商确认）'} />
          <PortfolioDetailRow k="持仓成本" v={num(cost)} />
          <PortfolioDetailRow k="当前价格" v={num(price)} />
          <PortfolioDetailRow k="当前盈亏" v={fmtMoney(pos.profit)} c={(pos.profit ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR} />
          <PortfolioDetailRow k="盈亏比例" v={pct(profitPct)} c={profitPct >= 0 ? UP_COLOR : DOWN_COLOR} />
          <PortfolioDetailRow k="当前仓位" v={pos.posPct != null ? `${num(pos.posPct, 1)}%` : '—'} />
        </DrawerSection>

        <DrawerSection title="📊 技术指标">
          <PortfolioDetailRow k="均线数值（MA5 / MA20 / MA60）" v={[ind.ma5, ind.ma20, ind.ma60].map((v) => v != null ? num(v) : '—').join(' / ')} />
          {(() => {
            const mv = ind.ma20; const ab = (mv != null && price != null) ? price >= mv : null;
            const dist = (mv != null && price != null) ? (price - mv) / mv * 100 : null;
            const sl = ind.ma20_slope ?? null;
            if (mv == null) return null;
            return (
              <div className="flex items-center justify-between py-0.5 text-[11px] cursor-help" title={'MA20 位置：百分比表示现价相对 MA20 的偏离，不是持仓收益率；斜率表示 MA20 本身的方向。'}>
                <span style={{ color: 'var(--text-muted)' }}>现价相对 MA20</span>
                <span className="font-medium">
                  <span style={{ color: ab ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>{ab ? '▲站上' : '▼破位'}{dist != null ? ` ${dist >= 0 ? '+' : ''}${num(dist, 1)}%` : ''}</span>
                  <span className="font-mono text-[10px] ml-1" style={{ color: sl == null ? 'var(--text-muted)' : sl > 0.5 ? UP_COLOR : sl < -0.5 ? DOWN_COLOR : 'var(--text-muted)' }}>{sl == null ? '' : `${sl > 0.5 ? '↑' : sl < -0.5 ? '↓' : '→'}${sl >= 0 ? '+' : ''}${num(sl, 1)}%`}</span>
                </span>
              </div>
            );
          })()}
          <PortfolioDetailRow k="RSI14" v={ind.rsi != null ? num(ind.rsi) : '—'} />
          <PortfolioDetailRow k="MACD DIF/DEA" v={`${ind.dif != null ? num(ind.dif) : '—'} / ${ind.dea != null ? num(ind.dea) : '—'}`} />
          <PortfolioDetailRow k="KDJ（K / D / J）" v={[ind.kdj?.k ?? ind.kdj_k, ind.kdj?.d ?? ind.kdj_d, ind.kdj?.j ?? ind.kdj_j].map((v) => v != null ? num(v, 1) : '—').join(' / ')} />
          <PortfolioDetailRow k="量比/换手" v={mf.turnover_rate != null ? `${num(mf.turnover_rate)}%` : '—'} />
          <PortfolioDetailRow k="今日主力净流入" v={fmtMoney(mf.main_net)} c={(mf.main_net ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR} />
          <PortfolioDetailRow k="支撑 / 突破位" v={`${ind.support != null ? num(ind.support) : '—'} / ${ind.resistance != null ? num(ind.resistance) : '—'}`} />
          <PortfolioDetailRow k="综合评分" v={sig.overallScore != null ? Math.round(sig.overallScore) : '—'} />
        </DrawerSection>

        <DrawerSection title="🎯 自动交易计划">
          <PortfolioDetailRow k="模式" v={MODE_TEXT[mode] || '关闭'} />
          <PortfolioDetailRow k="状态" v={cfg ? `${STATUS_TEXT[cfg.status] || cfg.status}${cfg.status_reason ? '·' + cfg.status_reason : ''}` : '未开启'} c={cfg?.status === 'MONITORING' ? '#22c55e' : 'var(--text-secondary)'} />
          <PortfolioDetailRow k="防守位" v={p.support_price != null ? num(p.support_price) : '—'} />
          <PortfolioDetailRow k="确认破位线" v={p.breakdown_price != null ? num(p.breakdown_price) : '—'} />
          <PortfolioDetailRow k="硬止损价" v={p.hard_stop_price != null ? num(p.hard_stop_price) : '—'} />
          <PortfolioDetailRow k="第一/第二止盈" v={`${p.take_profit_1 != null ? num(p.take_profit_1) : '—'} / ${p.take_profit_2 != null ? num(p.take_profit_2) : '—'}`} />
          <PortfolioDetailRow k="移动止损" v={p.trailing_stop_type === 'off' ? '关闭' : `${p.trailing_stop_type}${p.trailing_stop_value ? '(' + p.trailing_stop_value + ')' : ''}`} />
          <PortfolioDetailRow k="单票最大仓位" v={rk.max_position_pct != null ? `${rk.max_position_pct}%` : '—'} />
          {global && !global.enabled && mode !== 'off' && (
            <div className="mt-1.5 px-2 py-1 rounded text-[10px]" style={{ background: 'rgba(245,158,11,0.1)', color: '#f59e0b' }}>⚠️ 账户总开关关闭，该股自动交易未执行</div>
          )}
        </DrawerSection>

        <DrawerSection title="💡 触发依据">
          {reasons.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>暂无信号依据</div>
          ) : reasons.map((r, i) => (
            <div key={i} className="py-0.5 text-[11px]" style={{ color: /空头|跌破|流出|亏损/.test(r) ? '#ef4444' : /金叉|流入|盈利|突破/.test(r) ? '#22c55e' : 'var(--text-secondary)' }}>{r}</div>
          ))}
        </DrawerSection>

        {notes?.note && (
          <DrawerSection title="📝 备注">
            <div className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{notes.note}</div>
          </DrawerSection>
        )}

        <DrawerSection title="📋 操作记录（最近）">
          {audit.length === 0 ? (
            <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>暂无操作记录</div>
          ) : audit.slice(0, 6).map((a, i) => (
            <div key={i} className="flex items-center justify-between py-0.5 text-[10px]">
              <span style={{ color: 'var(--text-secondary)' }}>{a.event_type} {a.reason ? '·' + a.reason : ''}</span>
              <span style={{ color: 'var(--text-muted)' }}>{a.event_time}</span>
            </div>
          ))}
        </DrawerSection>
      </div>

      <div className="p-3 border-t shrink-0 flex gap-2" style={{ borderColor: 'var(--border-color)' }}>
        <button onClick={() => openStockAnalysis(code)}
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
    { ok: !!global?.enabled, label: '账户总开关（关闭时仅提醒不执行）' },
  ];


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
  const isLive = form.run_environment === 'live';

  return (
    <>
      <div className="flex items-center justify-between px-4 py-2.5 border-b shrink-0" style={{ borderColor: 'var(--border-color)' }}>
        <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 个股自动交易配置 · {code}</span>
        <button onClick={onClose} className="px-2 py-0.5 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>✕</button>
      </div>

      <div className="flex-1 overflow-y-auto">
        <DrawerSection title="运行设置">
          <div className="flex gap-1.5 mb-1.5">
            <ConfigRadio active={form.mode === 'off'} onClick={() => set('mode', 'off')} label="关闭" desc="只提醒不下单" />
            <ConfigRadio active={form.mode === 'risk_only'} onClick={() => set('mode', 'risk_only')} label="风控托管" desc="减仓/止损/止盈" />
            <ConfigRadio active={form.mode === 'full_auto'} onClick={() => set('mode', 'full_auto')} label="全自动" desc="开/加/减/止盈" />
          </div>
          <div className="flex gap-1.5 mb-1.5">
            <ConfigRadio active={form.run_environment === 'paper'} onClick={() => set('run_environment', 'paper')} label="模拟" />
            <ConfigRadio active={isLive} onClick={() => set('run_environment', 'live')} label="实盘" />
            <ConfigRadio active={form.authorization_expiry_type === 'daily'} onClick={() => set('authorization_expiry_type', 'daily')} label="仅当日" />
            <ConfigRadio active={form.authorization_expiry_type === 'persistent'} onClick={() => set('authorization_expiry_type', 'persistent')} label="持续" />
          </div>
          <ConfigField label="策略 ID"><input value={form.strategy_id} onChange={(e) => set('strategy_id', e.target.value)} placeholder="可选" style={inputStyle} /></ConfigField>
        </DrawerSection>

        <DrawerSection title="关键价格">
          <ConfigField label="防守位"><input type="number" value={form.support_price} onChange={(e) => set('support_price', e.target.value)} placeholder="43.00" style={inputStyle} /></ConfigField>
          <ConfigField label="确认破位线"><input type="number" value={form.breakdown_price} onChange={(e) => set('breakdown_price', e.target.value)} placeholder="42.80" style={inputStyle} /></ConfigField>
          <ConfigField label="硬止损价"><input type="number" value={form.hard_stop_price} onChange={(e) => set('hard_stop_price', e.target.value)} placeholder="41.50" style={inputStyle} /></ConfigField>
          <ConfigField label="突破位"><input type="number" value={form.breakout_price} onChange={(e) => set('breakout_price', e.target.value)} placeholder="46.00" style={inputStyle} /></ConfigField>
          <ConfigField label="第一止盈位"><input type="number" value={form.take_profit_1} onChange={(e) => set('take_profit_1', e.target.value)} placeholder="45.98" style={inputStyle} /></ConfigField>
          <ConfigField label="第二止盈位"><input type="number" value={form.take_profit_2} onChange={(e) => set('take_profit_2', e.target.value)} placeholder="48.50" style={inputStyle} /></ConfigField>
          <ConfigField label="移动止损">
            <select value={form.trailing_stop_type} onChange={(e) => set('trailing_stop_type', e.target.value)} style={inputStyle}>
              <option value="off">关闭</option><option value="ma10">MA10</option><option value="2atr">2ATR</option>
            </select>
          </ConfigField>
        </DrawerSection>

        <DrawerSection title="风控限制">
          <ConfigField label="单票最大仓位%"><input type="number" value={form.max_position_pct} onChange={(e) => set('max_position_pct', e.target.value)} style={inputStyle} /></ConfigField>
          <ConfigField label="单次最大买入%"><input type="number" value={form.max_single_buy_pct} onChange={(e) => set('max_single_buy_pct', e.target.value)} style={inputStyle} /></ConfigField>
          <ConfigField label="单次最大卖出%"><input type="number" value={form.max_single_sell_pct} onChange={(e) => set('max_single_sell_pct', e.target.value)} style={inputStyle} /></ConfigField>
          <ConfigField label="单票最大亏损¥"><input type="number" value={form.max_total_loss} onChange={(e) => set('max_total_loss', e.target.value)} placeholder="如 -3000" style={inputStyle} /></ConfigField>
          <ConfigField label="单日最大订单"><input type="number" value={form.max_daily_orders} onChange={(e) => set('max_daily_orders', e.target.value)} style={inputStyle} /></ConfigField>
          <ConfigField label="最大滑点%"><input type="number" step="0.1" value={form.max_slippage_pct} onChange={(e) => set('max_slippage_pct', e.target.value)} style={inputStyle} /></ConfigField>
          <ConfigField label="信号冷却(秒)"><input type="number" value={form.signal_cooldown_seconds} onChange={(e) => set('signal_cooldown_seconds', e.target.value)} style={inputStyle} /></ConfigField>
        </DrawerSection>

        <DrawerSection title="允许动作">
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
        </DrawerSection>

        <DrawerSection title="开启前检查">
          {checks.map((c, i) => (
            <div key={i} className="flex items-center gap-1.5 py-0.5 text-[11px]" style={{ color: c.ok ? '#22c55e' : 'var(--text-muted)' }}>
              <span>{c.ok ? '✅' : '⬜'}</span>{c.label}
            </div>
          ))}
        </DrawerSection>

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
