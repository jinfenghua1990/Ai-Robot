import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import SignalCard from '../../components/trading/SignalCard';
import { useWatchlistRealtimeStream } from '../../hooks/useWatchlistRealtimeStream';
import { apiFetch } from '../../utils/request';

const ACTIVE_INTERVAL = 30000;
const IDLE_INTERVAL = 60000;

function formatWan(v) {
  if (v == null) return '-';
  if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (Math.abs(v) >= 10000) return (v / 10000).toFixed(1) + 'w';
  return v.toFixed(2);
}

function timeAgo(iso) {
  if (!iso) return '';
  const sec = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (sec < 5) return '刚刚';
  if (sec < 60) return `${sec}秒前`;
  return `${Math.floor(sec / 60)}分钟前`;
}

const SOURCE_STYLES = {
  miaoxiang: { bg: '#FAEEDA', fg: '#854F0B', label: '妙想' },
  dsa: { bg: '#E6F1FB', fg: '#185FA5', label: 'DSA' },
};

/**
 * 把「持仓」与「自选股信号」合并为一个 SignalCard 可渲染的 signal 对象。
 * - 优先复用自选股的完整标签（signalLabel / hitTags / strategyTags / 因子 / 资金流 / 板块热度）
 * - 用持仓真实数量 / 成本 / 盈亏覆盖 position 字段，确保持仓明细准确
 */
function buildSignal(holding, wlSignal, totalMv) {
  const qty = holding.quantity || 0;
  const cost = holding.avg_cost || 0;
  const price = holding.last_price || 0;
  const value = holding.market_value || (qty * price);
  const pnl = holding.unrealized_pnl || 0;
  const pnlPct = cost > 0 ? ((price - cost) / cost) * 100 : 0;
  const posPct = totalMv > 0 ? (value / totalMv) * 100 : 0;
  const position = {
    price,
    count: qty,
    costPrice: cost,
    profit: pnl,
    profitPct: pnlPct,
    value,
    posPct,
    dayProfit: holding.day_pnl ?? wlSignal?.position?.dayProfit ?? 0,
    dayProfitPct: holding.day_pnl_pct ?? wlSignal?.position?.dayProfitPct ?? 0,
  };
  if (wlSignal) {
    return {
      ...wlSignal,
      secCode: wlSignal.secCode || holding.symbol,
      secName: wlSignal.secName || holding.name || holding.symbol,
      position,
    };
  }
  // 自选股中不存在该标的：构建最小可用 signal（仍展示持仓明细 + 基础标签）
  return {
    secCode: holding.symbol,
    secName: holding.name || holding.symbol,
    signalLabel: '持仓',
    signalColor: '#6b7280',
    riskLevel: 'medium',
    position,
    hitTags: [],
    positiveFactors: [],
    negativeFactors: [],
    moneyFlow: null,
    sectorTrend: null,
    marketState: null,
  };
}

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState(null);
  const [wlSignals, setWlSignals] = useState({});   // secCode -> signal
  const [strategyPicks, setStrategyPicks] = useState({}); // code -> [strategy]
  const [notes, setNotes] = useState({});
  const [editingNote, setEditingNote] = useState(null);
  const [editForm, setEditForm] = useState({ note: '', target_price: '' });
  const [loading, setLoading] = useState(true);
  const [syncing, setSyncing] = useState(false);
  const [lastSync, setLastSync] = useState(null);
  const [visible, setVisible] = useState(true);
  const timerRef = useRef(null);

  // SSE 实时资金流（与自选股同款，自动推送 5s）
  const { realtimeMap, streamStatus } = useWatchlistRealtimeStream();

  useEffect(() => {
    const onVis = () => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', onVis);
    return () => document.removeEventListener('visibilitychange', onVis);
  }, []);

  const loadWatchlistSignals = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/watchlist');
    if (ok && data) {
      const map = {};
      for (const s of (data.signals || [])) {
        if (s.secCode) map[s.secCode] = s;
      }
      setWlSignals(map);
    }
  }, []);

  const loadStrategyPicks = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/bs-screener/strategy-picks');
    if (ok && data) setStrategyPicks(data.code_to_strategies || {});
  }, []);

  const loadNotes = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/shared/stock-notes');
    if (ok && data) setNotes(data);
  }, []);

  const loadData = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/shared/portfolio');
    if (ok && data) {
      setPortfolio(data);
      setLastSync(new Date().toISOString());
    }
    await Promise.all([loadWatchlistSignals(), loadNotes()]);
    setLoading(false);
  }, [loadWatchlistSignals, loadNotes]);

  useEffect(() => {
    loadData();
    loadStrategyPicks();
    const interval = visible ? ACTIVE_INTERVAL : IDLE_INTERVAL;
    timerRef.current = setInterval(loadData, interval);
    return () => clearInterval(timerRef.current);
  }, [loadData, loadStrategyPicks, visible]);

  const handleSync = async () => {
    setSyncing(true);
    await apiFetch('/api/shared/portfolio/refresh', { method: 'POST' });
    await loadData();
    setSyncing(false);
  };

  const positions = portfolio?.positions ?? [];
  const sources = portfolio?.data_sources ?? {};
  const totalMv = portfolio?.total_market_value ?? 0;
  const totalPnl = portfolio?.total_unrealized_pnl ?? 0;
  const totalAssets = portfolio?.total_assets ?? (totalMv + (portfolio?.available_cash ?? 0));
  const availableCash = portfolio?.available_cash ?? 0;
  const totalCost = portfolio?.total_cost ?? 0;
  const totalDayPnl = portfolio?.total_day_pnl ?? 0;

  const countLoss = positions.filter(p => (p.unrealized_pnl ?? 0) < 0).length;
  const countProfit = positions.filter(p => (p.unrealized_pnl ?? 0) > 0).length;

  // 合并持仓 + 自选股标签，构造 SignalCard 列表（按盈亏额降序）
  const merged = positions
    .map(p => buildSignal(p, wlSignals[p.symbol], totalMv))
    .sort((a, b) => (b.position?.profit ?? 0) - (a.position?.profit ?? 0));

  // 按板块分组（同重点关注排版）
  const [collapsedSectors, setCollapsedSectors] = useState(new Set());
  const toggleSector = (name) => {
    setCollapsedSectors(prev => {
      const n = new Set(prev);
      if (n.has(name)) n.delete(name); else n.add(name);
      return n;
    });
  };
  const SECTOR_ICONS = {
    'MLCC':'','CPO':'','PCB':'🟩','存储芯片':'💾','先进封装':'🔧','光纤光缆':'🔆',
    'AI PC':'🖥️','AI芯片':'🧠','AI服务器':'🖧','OCS':'🔷','培育钻石':'','玻璃基板':'🔲',
    '陶瓷基板':'🏺','高速链接':'⚡','铜箔':'🟫','树脂':'🍃','电子布':'🧵','液冷':'❄️',
    '六氟化钨':'⚗️','碳酸铁锂':'🔋',
  };
  const SECTOR_COLORS = [
    '#6366f1','#a855f7','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6',
    '#06b6d4','#3b82f6','#8b5cf6','#d946ef','#64748b','#84cc16','#10b981','#0ea5e9',
  ];
  const groupedSectors = useMemo(() => {
    const map = {};
    for (const sig of merged) {
      const sec = sig.sector || sig.sectorTrend?.sector || '其他';
      if (!map[sec]) map[sec] = [];
      map[sec].push(sig);
    }
    return Object.entries(map).map(([sector, stocks], i) => {
      const avgChg = stocks.reduce((sum, s) => sum + (s.position?.profitPct ?? 0), 0) / Math.max(stocks.length, 1);
      const upCount = stocks.filter(s => (s.position?.profit ?? 0) >= 0).length;
      return { sector, stocks, avgChg, upCount, color: SECTOR_COLORS[i % SECTOR_COLORS.length] };
    }).sort((a, b) => b.avgChg - a.avgChg);
  }, [merged]);
  const fmtChg = (v) => { if (v == null) return ''; const sign = v >= 0 ? '+' : ''; return `${sign}${v.toFixed(2)}%`; };
  const openEdit = (sym) => {
    const n = notes[sym] || {};
    setEditForm({ note: n.note || '', target_price: n.target_price || '' });
    setEditingNote(sym);
  };

  const saveNote = async () => {
    if (!editingNote) return;
    const { ok } = await apiFetch(`/api/shared/stock-notes/${editingNote}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        note: editForm.note,
        target_price: editForm.target_price || null,
        tags: [],
      }),
    });
    if (ok) {
      setNotes(prev => ({
        ...prev,
        [editingNote]: {
          note: editForm.note,
          target_price: editForm.target_price || null,
          updated_at: new Date().toISOString().slice(0, 10),
        },
      }));
    }
    setEditingNote(null);
  };

  return (
    <div className="space-y-3">

      {/* ===== Sticky 顶栏 ===== */}
      <div className="sticky top-0 z-30 rounded-xl p-2.5 space-y-2"
        style={{
          background: 'var(--bg-card)',
          borderBottom: '2px solid var(--border-color)',
          boxShadow: '0 2px 12px rgba(0,0,0,0.06)',
        }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h2 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
            <span>我的持仓</span>
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: 'var(--accent-green)' }}>
              {positions.length}只
            </span>
            <span className="pulse-dot" style={{
              width: 8, height: 8, borderRadius: '50%',
              background: streamStatus === 'open' ? '#1D9E75' : (visible ? '#f59e0b' : '#888780'),
            }}/>
          </h2>
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              实时{streamStatus === 'open' ? '已连接' : streamStatus === 'fallback' ? '兜底轮询' : '连接中'} · {timeAgo(lastSync)}
            </span>
            <button onClick={handleSync} disabled={syncing}
              className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1 disabled:opacity-50"
              style={{
                borderColor: syncing ? 'var(--border-color)' : 'rgba(59,130,246,0.4)',
                color: 'var(--accent-blue)',
                background: syncing ? 'rgba(59,130,246,0.06)' : 'transparent',
              }}>
              {syncing ? '⏳' : '🔄'} 同步
            </button>
          </div>
        </div>
      </div>

      {/* ===== 总览卡片 ===== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {[
          { label: '总资产', value: formatWan(totalAssets), color: 'var(--text-primary)', sub: `持仓 ${formatWan(totalMv)} · 可用 ${formatWan(availableCash)}` },
          { label: '可用资金', value: formatWan(availableCash), color: '#3b82f6', sub: totalAssets > 0 ? `仓位 ${((totalMv / totalAssets) * 100).toFixed(1)}%` : '—' },
          { label: '总盈亏', value: formatWan(totalPnl), color: totalPnl >= 0 ? '#E24B4A' : '#1D9E75', sub: totalCost > 0 ? `收益率 ${((totalPnl / totalCost) * 100).toFixed(2)}%` : (totalPnl >= 0 ? '盈利中' : '亏损中') },
          { label: '当日盈亏', value: formatWan(totalDayPnl), color: totalDayPnl >= 0 ? '#E24B4A' : '#1D9E75', sub: totalDayPnl >= 0 ? '今日盈利' : '今日亏损' },
        ].map((c, i) => (
          <div key={i}
            className="rounded-xl border p-2.5"
            style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
            <div className="text-[10px] flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
              {c.label}
              <span className="text-[9px]">{c.sub}</span>
            </div>
            <div className="text-xl font-bold mt-0.5" style={{ color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* ===== 来源分布条 ===== */}
      <div className="rounded-xl border p-2.5 flex items-center gap-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <span className="text-[11px] font-medium" style={{ color: 'var(--text-secondary)' }}>数据来源</span>
        {[
          { key: 'miaoxiang', label: '妙想模拟盘', count: sources.miaoxiang ?? 0, bg: '#FAEEDA', fg: '#854F0B' },
          { key: 'dsa', label: 'DSA 持仓', count: sources.dsa ?? 0, bg: '#E6F1FB', fg: '#185FA5' },
        ].map(s => (
          <div key={s.key} className="flex items-center gap-1 px-2 py-1 rounded-lg text-[11px]" style={{ background: s.bg, color: s.fg }}>
            <span className="font-bold">{s.count}</span>
            <span>{s.label}</span>
          </div>
        ))}
        <div className="flex-1" />
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
          妙想优先 · DSA 补充
        </span>
      </div>

      {/* ===== 持仓富模块列表（自选股同款 SignalCard）===== */}
      {loading ? (
        <div className="space-y-2">
          {[1,2,3,4].map(i => (
            <div key={i} className="h-40 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
          ))}
        </div>
      ) : positions.length === 0 ? (
        <div className="text-center py-12 rounded-xl border" style={{ borderColor: 'var(--border-color)' }}>
          <div className="text-3xl mb-2">💼</div>
          <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>暂无持仓数据</div>
          <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>在妙想模拟盘交易后自动同步</div>
        </div>
      ) : groupedSectors.length > 0 ? (
        <div className="space-y-2">
          {groupedSectors.map((sec) => {
            const expanded = !collapsedSectors.has(sec.sector);
            return (
              <div key={sec.sector} className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                {/* 板块头部 */}
                <div className="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
                  style={{ borderBottom: expanded ? '1px solid var(--border-color)' : 'none' }}
                  onClick={() => toggleSector(sec.sector)}>
                  <span className="text-sm">{SECTOR_ICONS[sec.sector] || '📌'}</span>
                  <span className="text-xs font-bold" style={{ color: sec.color }}>{sec.sector}</span>
                  <span className="text-[10px] px-1 rounded" style={{
                    background: sec.avgChg >= 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: sec.avgChg >= 0 ? '#ef4444' : '#22c55e',
                  }}>
                    {sec.upCount}/{sec.stocks.length}↑
                  </span>
                  <span className="text-xs font-bold" style={{ color: sec.avgChg >= 0 ? '#ef4444' : '#22c55e' }}>
                    {fmtChg(sec.avgChg)}
                  </span>
                  <span className="ml-auto text-[10px] w-4 text-center" style={{ color: 'var(--text-muted)' }}>
                    {expanded ? '▾' : '▸'}
                  </span>
                </div>
                {expanded && (
                  <div className="grid grid-cols-1 xl:grid-cols-2 gap-2 px-3 py-2 items-start">
                    {sec.stocks.map((sig) => {
                      const sym = sig.secCode;
                      const note = notes[sym];
                      const isEditing = editingNote === sym;
                      return (
                        <div key={sym} className="space-y-1">
                          {/* 持仓速览头（醒目：左边条+大号盈亏pill+分组标签） */}
                          <div className="flex items-stretch rounded-lg overflow-hidden"
                            style={{ border: '1px solid var(--border-color)' }}>
                            {/* 左侧彩条：盈利红 / 亏损绿 */}
                            <div style={{
                              width: 4, flexShrink: 0,
                              background: (sig.position?.profitPct ?? 0) >= 0
                                ? 'linear-gradient(180deg,#E24B4A,#f97316)'
                                : 'linear-gradient(180deg,#1D9E75,#14b8a6)',
                            }} />
                            <div className="flex-1 px-2.5 py-1.5 space-y-1" style={{ background: 'var(--bg-card)' }}>
                              {/* 第一行：名称 + 总盈亏大号pill + 总盈亏金额 */}
                              <div className="flex items-center gap-2 flex-wrap">
                                <span className="text-sm font-bold whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>
                                  {sig.secName}
                                  <span className="text-[11px] font-normal ml-1" style={{ color: 'var(--text-muted)' }}>{sig.secCode}</span>
                                </span>
                                <span className="px-2 py-0.5 rounded-full text-[13px] font-bold" style={{
                                  background: (sig.position?.profitPct ?? 0) >= 0 ? 'rgba(226,75,74,0.15)' : 'rgba(29,158,117,0.15)',
                                  color: (sig.position?.profitPct ?? 0) >= 0 ? '#E24B4A' : '#1D9E75',
                                  border: `1px solid ${(sig.position?.profitPct ?? 0) >= 0 ? 'rgba(226,75,74,0.3)' : 'rgba(29,158,117,0.3)'}`,
                                }}>
                                  总 {(sig.position?.profitPct ?? 0) >= 0 ? '+' : ''}{(sig.position?.profitPct ?? 0).toFixed(2)}%
                                </span>
                                <span className="text-xs font-medium" style={{
                                  color: (sig.position?.profit ?? 0) >= 0 ? '#E24B4A' : '#1D9E75',
                                }}>
                                  总 {formatWan(sig.position?.profit ?? 0)}
                                </span>
                              </div>
                              {/* 第二行：当日盈亏突出 + 紧凑指标标签 */}
                              <div className="flex items-center gap-1.5 flex-wrap">
                                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                                  background: (sig.position?.dayProfit ?? 0) >= 0 ? 'rgba(226,75,74,0.15)' : 'rgba(29,158,117,0.15)',
                                  border: `1px solid ${(sig.position?.dayProfit ?? 0) >= 0 ? 'rgba(226,75,74,0.35)' : 'rgba(29,158,117,0.35)'}`,
                                  color: (sig.position?.dayProfit ?? 0) >= 0 ? '#E24B4A' : '#1D9E75',
                                }}>
                                  当日 {(sig.position?.dayProfit ?? 0) >= 0 ? '+' : ''}{(sig.position?.dayProfit ?? 0).toFixed(0)}
                                  {(sig.position?.dayProfitPct ?? 0) !== 0 && (
                                    <span className="ml-0.5">
                                      ({(sig.position?.dayProfitPct ?? 0) >= 0 ? '+' : ''}{(sig.position?.dayProfitPct ?? 0).toFixed(2)}%)
                                    </span>
                                  )}
                                </span>
                                {[
                                  { label: '持仓', value: `${sig.position?.count ?? 0}股`, color: 'var(--text-secondary)' },
                                  { label: '成本', value: (sig.position?.costPrice ?? 0).toFixed(2), color: 'var(--text-muted)' },
                                  { label: '市值', value: formatWan(sig.position?.value ?? 0), color: 'var(--text-secondary)' },
                                  { label: '仓位', value: `${(sig.position?.posPct ?? 0).toFixed(1)}%`, color: 'var(--text-secondary)' },
                                ].map((m, mi) => (
                                  <span key={mi} className="px-1.5 py-0.5 rounded text-[10px]" style={{
                                    background: 'var(--bg-surface)',
                                    border: '0.5px solid var(--border-color)',
                                    color: m.color,
                                  }}>
                                    <span style={{ color: 'var(--text-muted)' }}>{m.label} </span>
                                    <span className="font-medium">{m.value}</span>
                                  </span>
                                ))}
                              </div>
                            </div>
                          </div>
                          <SignalCard
                            signal={sig}
                            mode="sim_watchlist"
                            showMarketState
                            showAnalysisButton
                            showActionButton={false}
                            showWatchBtn={false}
                            showFocusBtn={false}
                            showBuyBtn={true}
                            strategyTags={strategyPicks[sym] || []}
                            realtimeFlow={realtimeMap?.[sym] || null}
                            showRealtimeDetail
                          />
                          {/* 个股备注条 */}
                          <div className="flex items-center gap-2 px-2">
                            {note?.note ? (
                              <span className="text-[11px] flex items-center gap-1" style={{ color: 'var(--text-muted)' }}>
                                💬 {note.note}
                                {note.target_price && (
                                  <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--accent-blue)' }}>目标 {note.target_price}</span>
                                )}
                              </span>
                            ) : (
                              <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>暂无备注</span>
                            )}
                            <button onClick={() => openEdit(sym)}
                              className="ml-auto text-[11px] px-2 py-0.5 rounded border"
                              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'transparent', cursor: 'pointer' }}>
                              📝 备注
                            </button>
                          </div>
                          {isEditing && (
                            <div className="rounded-xl border p-2.5 space-y-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                              <textarea
                                value={editForm.note}
                                onChange={e => setEditForm(f => ({ ...f, note: e.target.value }))}
                                placeholder="输入分析备注…"
                                style={{ width: '100%', boxSizing: 'border-box', minHeight: 40, border: '0.5px solid var(--border-color)', borderRadius: 8,
                                  padding: '6px 8px', fontSize: 12, fontFamily: 'inherit', resize: 'vertical',
                                  background: 'var(--bg-input)', color: 'var(--text-primary)' }}
                              />
                              <div className="flex items-center gap-2">
                                <input value={editForm.target_price} onChange={e => setEditForm(f => ({ ...f, target_price: e.target.value }))}
                                  placeholder="目标价" style={{ border: '0.5px solid var(--border-color)', borderRadius: 6, padding: '4px 8px', fontSize: 12, width: 100,
                                    background: 'var(--bg-input)', color: 'var(--text-primary)' }} />
                                <button onClick={saveNote}
                                  className="px-3 py-1 rounded-lg text-xs"
                                  style={{ background: 'var(--accent-blue)', color: '#fff', border: 'none', cursor: 'pointer' }}>保存</button>
                                <button onClick={() => setEditingNote(null)}
                                  className="px-3 py-1 rounded-lg text-xs"
                                  style={{ background: 'transparent', border: '0.5px solid var(--border-color)', color: 'var(--text-secondary)', cursor: 'pointer' }}>取消</button>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <div className="text-center py-12 rounded-xl border" style={{ borderColor: 'var(--border-color)' }}>
          <div className="text-3xl mb-2">💼</div>
          <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>暂无持仓数据</div>
          <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>在妙想模拟盘交易后自动同步</div>
        </div>
      )}

      {/* ===== 底部栏 ===== */}
      <div className="rounded-xl border p-2.5 flex items-center gap-3 text-[11px] flex-wrap"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
        <span>🔍 分析 → 个股深度页</span>
        <span>💰 实时资金流（SSE 推送）</span>
        <span>📝 备注编辑</span>
        <span className="flex-1" />
        <span style={{ color: 'var(--text-secondary)' }}>{positions.length} 只 · 总资产 {formatWan(totalAssets)}</span>
      </div>
    </div>
  );
}
