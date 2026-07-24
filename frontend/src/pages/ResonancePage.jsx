import { useState, useEffect, useMemo, useCallback } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import StrategySignalCard from '../components/trading/StrategySignalCard';
import CardSafetyBoundary from '../components/CardSafetyBoundary';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';
import { stripCode } from '../utils/format';
import SinaLink from '../components/SinaLink';

const RESONANCE_COLORS = {
  2: '#3b82f6',
  3: '#eab308',
  4: '#f97316',
  5: '#ef4444',
};
const getResonanceColor = (count) => RESONANCE_COLORS[count] || '#dc2626';

const MIN_COUNT_OPTIONS = [
  { value: 1, label: '全部' },
  { value: 2, label: '2+共振' },
  { value: 3, label: '3+共振' },
  { value: 4, label: '4+共振' },
  { value: 5, label: '5+共振' },
];

const EMPTY_ARR = [];

// === 20天跟踪 helpers (复制自 StrategyTrackPage) ===
const fmtPct = (v) => {
  if (v == null) return '-';
  const n = Number(v);
  if (n === 0) return '0%';
  if (n > 0) return `+${n.toFixed(2)}%`;
  return `${n.toFixed(2)}%`;
};

const pctColor = (v) => {
  if (v == null) return '#6b7280';
  const n = Number(v);
  if (n >= 5) return UP_DARK;
  if (n >= 0.5) return UP_COLOR;
  if (n <= -5) return DOWN_DARK;
  if (n <= -0.5) return DOWN_COLOR;
  return '#6b7280';
};

// Mini sparkline: 60x20 SVG 折线图 (取最后 20 个 cum_pct 点)
const Sparkline = ({ points }) => {
  if (!points || points.length === 0) return null;
  const pts = points.slice(-20);
  const vals = pts.map((p) => Number(p.cum_pct ?? 0));
  const min = Math.min(...vals, 0);
  const max = Math.max(...vals, 0);
  const range = max - min || 1;
  const W = 60, H = 20, pad = 2;
  const xStep = pts.length > 1 ? (W - pad * 2) / (pts.length - 1) : 0;
  const y = (v) => H - pad - ((v - min) / range) * (H - pad * 2);
  const path = pts
    .map((p, i) => `${i === 0 ? 'M' : 'L'} ${(pad + i * xStep).toFixed(2)} ${y(Number(p.cum_pct ?? 0)).toFixed(2)}`)
    .join(' ');
  const zeroY = y(0);
  const lastVal = vals[vals.length - 1];
  const lineColor = lastVal >= 0 ? UP_COLOR : DOWN_COLOR;
  const lastX = pts.length > 1 ? pad + (pts.length - 1) * xStep : pad;
  return (
    <svg width={W} height={H} style={{ display: 'block' }}>
      <line x1={pad} y1={zeroY} x2={W - pad} y2={zeroY} stroke="#9ca3af" strokeWidth="0.5" strokeDasharray="2 2" />
      <path d={path} fill="none" stroke={lineColor} strokeWidth="1.2" />
      <circle cx={lastX.toFixed(2)} cy={y(lastVal).toFixed(2)} r="1.5" fill={lineColor} />
    </svg>
  );
};

// 撤离原因样式
const exitReasonStyle = (reason) => {
  if (reason === 'BS_S_SIGNAL') return { label: 'BS卖出信号', color: DOWN_COLOR, bg: 'rgba(34,197,94,0.12)', border: 'rgba(34,197,94,0.4)' };
  if (reason === 'MAX_DAYS_REACHED') return { label: '满20天到期', color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.4)' };
  if (reason === 'MANUAL') return { label: '手动撤离', color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', border: 'rgba(59,130,246,0.4)' };
  return { label: reason || '未知', color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.4)' };
};

// BS 信号 badge: B → 持仓中(green), S → 已平仓(red), null → 无信号(gray)
const bsBadgeStyle = (signal) => {
  if (signal === 'B') return { label: 'B 持仓中', color: DOWN_COLOR, bg: 'rgba(34,197,94,0.12)', border: 'rgba(34,197,94,0.4)' };
  if (signal === 'S') return { label: 'S 已平仓', color: UP_COLOR, bg: 'rgba(239,68,68,0.12)', border: 'rgba(239,68,68,0.4)' };
  return { label: '无信号', color: '#6b7280', bg: 'rgba(107,114,128,0.12)', border: 'rgba(107,114,128,0.4)' };
};

// 汇总 chip
function Chip({ label, value, color }) {
  return (
    <div className="rounded border px-2 py-1 flex items-center gap-1.5" style={{ borderColor: 'var(--border-color)' }}>
      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="text-xs font-bold" style={{ color }}>{value}</span>
    </div>
  );
}

// 跟踪中股票卡片
function TrackerCard({ row, onExit, acting }) {
  const r = row;
  const bs = bsBadgeStyle(r.latest_bs_signal);
  const cumPct = r.latest_pct;
  const lastDay = r.latest_day ?? 0;
  const progressPct = Math.min((lastDay / 20) * 100, 100);
  // 进度条颜色: cum_pct > 0 → green, < 0 → red (按需求规格)
  const progressBarColor =
    cumPct != null && Number(cumPct) > 0 ? DOWN_COLOR :
    cumPct != null && Number(cumPct) < 0 ? UP_COLOR : '#6b7280';
  const strategies = r.strategies || [];
  const strategyTooltip = strategies
    .map((s) => `${s.icon || ''} ${s.name}${s.score != null ? ` (${s.score})` : ''}`)
    .join('\n');

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      {/* Header: 股票名 + 代码(新浪) + 板块标签 */}
      <div className="flex items-center gap-1.5 px-2.5 py-2 border-b" style={{ borderColor: 'var(--border-color)', background: 'rgba(168,85,247,0.04)' }}>
        <div className="w-1 h-4 rounded-sm" style={{ background: '#a855f7' }} />
        <span className="font-bold text-sm" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
        <SinaLink tsCode={r.ts_code} />
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{stripCode(r.ts_code)}</span>
        {r.sector && (
          <span
            className="ml-auto px-1.5 py-0.5 rounded text-[10px]"
            style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
            title="板块"
          >
            {r.sector}
          </span>
        )}
      </div>

      {/* Pool info: 入池日期 | 命中策略 | 入池价 */}
      <div className="grid grid-cols-3 gap-1 px-2.5 py-1.5 text-[11px] border-b" style={{ borderColor: 'var(--border-color)' }}>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>入池日期</div>
          <div className="font-medium" style={{ color: 'var(--text-secondary)' }}>{r.pool_date || '-'}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>命中策略</div>
          <div className="font-medium flex items-center gap-0.5" style={{ color: 'var(--text-secondary)' }} title={strategyTooltip}>
            {r.strategy_count ?? 0}个
            {strategies.length > 0 && <span className="text-[9px]" style={{ color: '#a855f7' }}>ⓘ</span>}
          </div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>入池价</div>
          <div className="font-medium" style={{ color: 'var(--text-secondary)' }}>{r.pool_close != null ? Number(r.pool_close).toFixed(2) : '-'}</div>
        </div>
      </div>

      {/* Latest info: 天数 | 最新价 | 累计 | 当日 */}
      <div className="grid grid-cols-4 gap-1 px-2.5 py-1.5 text-[11px] border-b" style={{ borderColor: 'var(--border-color)' }}>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>天数</div>
          <div className="font-bold" style={{ color: 'var(--text-primary)' }}>{lastDay}/20</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>最新价</div>
          <div className="font-bold" style={{ color: pctColor(r.latest_daily_chg) }}>{r.latest_close != null ? Number(r.latest_close).toFixed(2) : '-'}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>累计</div>
          <div className="font-bold" style={{ color: pctColor(r.latest_pct) }}>{fmtPct(r.latest_pct)}</div>
        </div>
        <div>
          <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>当日</div>
          <div className="font-bold" style={{ color: pctColor(r.latest_daily_chg) }}>{fmtPct(r.latest_daily_chg)}</div>
        </div>
      </div>

      {/* BS 信号 badge + 20天进度条 */}
      <div className="px-2.5 py-2 border-b flex items-center gap-2" style={{ borderColor: 'var(--border-color)' }}>
        <span
          className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
          style={{ background: bs.bg, color: bs.color, border: `1px solid ${bs.border}` }}
          title={r.latest_bs_reason || bs.label}
        >
          {bs.label}
        </span>
        <div className="flex-1 flex items-center gap-1.5">
          <div className="flex-1 h-2 rounded-full overflow-hidden" style={{ background: 'var(--bg-hover)' }}>
            <div className="h-full rounded-full transition-all" style={{ width: `${progressPct}%`, background: progressBarColor }} />
          </div>
          <span className="text-[10px] font-medium" style={{ color: 'var(--text-muted)' }}>{lastDay}/20</span>
        </div>
      </div>

      {/* Sparkline + 极值 */}
      <div className="px-2.5 py-2 border-b flex items-center gap-2" style={{ borderColor: 'var(--border-color)' }}>
        <Sparkline points={r.daily} />
        <div className="flex-1 flex items-center justify-end gap-3 text-[10px]">
          <div className="flex items-center gap-1">
            <span style={{ color: 'var(--text-muted)' }}>最大</span>
            <span className="font-bold" style={{ color: pctColor(r.max_return_pct) }}>{fmtPct(r.max_return_pct)}</span>
          </div>
          <div className="flex items-center gap-1">
            <span style={{ color: 'var(--text-muted)' }}>最小</span>
            <span className="font-bold" style={{ color: pctColor(r.min_return_pct) }}>{fmtPct(r.min_return_pct)}</span>
          </div>
        </div>
      </div>

      {/* Action button */}
      <div className="px-2.5 py-2">
        <button
          onClick={() => onExit(r.id, r.name)}
          disabled={acting}
          className="w-full px-2 py-1 text-xs rounded border disabled:opacity-50 font-medium"
          style={{ borderColor: '#3b82f6', color: '#3b82f6' }}
        >
          🚪 手动撤离
        </button>
      </div>
    </div>
  );
}

export default function ResonancePage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [minCount, setMinCount] = useState(1);
  // 重试触发器：递增以重新触发 useEffect
  const [retryNonce, setRetryNonce] = useState(0);
  // 预取的 stock-dashboard 数据：{[ts_code]: dash}，供每张 SignalCard 直接消费，
  // 避免 100+ 卡片同时各自打 /api/stock-dashboard/{code} 把后端打挂。
  const [dashMap, setDashMap] = useState({});
  // 批量预取是否已完成（含失败回退）。true 之后每张卡片按 prefetchedDash
  // 决定是否走自取（fallback 兜底）。
  const [prefetchDone, setPrefetchDone] = useState(true);

  // 20天跟踪 state
  const [trackTab, setTrackTab] = useState('active');  // 'active' | 'history'
  const [trackActive, setTrackActive] = useState(null);
  const [trackHistory, setTrackHistory] = useState(null);
  const [trackLoading, setTrackLoading] = useState(false);
  const [trackActing, setTrackActing] = useState(false);
  const [trackError, setTrackError] = useState('');

  const loadTrackActive = useCallback(async () => {
    setTrackLoading(true); setTrackError('');
    try {
      const { ok, data } = await apiFetch('/api/strategy-track/list?status=active');
      if (ok) setTrackActive(data); else setTrackError('跟踪数据加载失败');
    } catch (e) { setTrackError(String(e)); }
    finally { setTrackLoading(false); }
  }, []);

  const loadTrackHistory = useCallback(async () => {
    try {
      const { ok, data } = await apiFetch('/api/strategy-track/history?limit=100&offset=0');
      if (ok) setTrackHistory(data);
    } catch (e) {}
  }, []);

  useEffect(() => {
    if (trackTab === 'active') loadTrackActive();
    else loadTrackHistory();
  }, [trackTab, loadTrackActive, loadTrackHistory]);

  // Initial load of active tracking
  useEffect(() => { loadTrackActive(); }, [loadTrackActive]);

  const handlePool = useCallback(async (dateStr) => {
    setTrackActing(true);
    try {
      const { ok, data } = await apiFetch(`/api/strategy-track/pool?date=${dateStr}&min_count=2`, { method: 'POST' });
      if (ok) {
        alert(`入池完成: 新增 ${data.total_added} 只, 跳过重复 ${data.skipped_duplicates.length} 只`);
        loadTrackActive();
      } else {
        alert('入池失败');
      }
    } catch (e) { alert('入池错误: ' + String(e)); }
    finally { setTrackActing(false); }
  }, [loadTrackActive]);

  const handlePoolSelectedDate = useCallback(() => {
    // Use the currently selected resonance date (more accurate than "today")
    if (selectedDate) handlePool(selectedDate);
  }, [selectedDate, handlePool]);

  const handlePoolCustomDate = useCallback(() => {
    const d = window.prompt('请输入入池日期 YYYY-MM-DD:', selectedDate || new Date().toISOString().slice(0,10));
    if (d && /^\d{4}-\d{2}-\d{2}$/.test(d)) handlePool(d);
  }, [selectedDate, handlePool]);

  const handleDailyUpdate = useCallback(async () => {
    setTrackActing(true);
    try {
      const { ok, data } = await apiFetch('/api/strategy-track/daily-update', { method: 'POST' });
      if (ok) {
        alert(`每日更新完成: 更新 ${data.total_updated} 只, BS撤离 ${data.total_exited} 只, 到期 ${data.total_expired} 只`);
        loadTrackActive();
      } else { alert('更新失败'); }
    } catch (e) { alert('更新错误: ' + String(e)); }
    finally { setTrackActing(false); }
  }, [loadTrackActive]);

  const handleManualExit = useCallback(async (trackerId, name) => {
    if (!confirm(`确认撤离 ${name} ?`)) return;
    setTrackActing(true);
    try {
      const { ok } = await apiFetch('/api/strategy-track/manual-exit', {
        method: 'POST', body: JSON.stringify({ tracker_id: trackerId, reason: 'MANUAL' })
      });
      if (ok) { loadTrackActive(); if (trackTab==='history') loadTrackHistory(); }
    } catch (e) {}
    finally { setTrackActing(false); }
  }, [loadTrackActive, loadTrackHistory, trackTab]);

  useEffect(() => {
    if (!selectedDate) return;
    let cancelled = false;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setDashMap({}); // 清空旧预取，避免日期切换后残留错位
    setPrefetchDone(false); // 卡片看到 list 后开始等批量预取
    (async () => {
      const { ok, data: d, error: err, status } = await apiFetch(
        `/api/strategy-resonance?date=${selectedDate}&min_count=${minCount}`,
        { signal: controller.signal }
      );
      if (cancelled) return;
      if (!ok) {
        // 429 给用户准确的提示
        if (status === 429) {
          setError('请求被限流，请稍后重试');
        } else if (/timeout|超时/i.test(err || '')) {
          // abort 来源：deps 变化或组件卸载触发的取消，不弹错误
          // 但组件卸载场景已被 cancelled 守卫拦截，此处只剩 deps 变化
          // 交由下一次 effect 重新发起请求，不设置 error
        } else {
          setError('数据加载失败');
        }
        setLoading(false);
        setPrefetchDone(true); // 让卡片走单只接口 fallback
        return;
      }
      setData(d);
      setLoading(false);

      // ===== 批量预取 stock-dashboard（替代每张卡片独立请求）=====
      // 共振列表一次可能 50-200+ 只，若每张卡片 IntersectionObserver 各自打单只接口，
      // 一次性 100+ 并发请求会触发限流 / 把浏览器 / 后端打挂。
      // 用后端的 /api/stock-dashboard/batch 一次性拿，命中 5min 进程内缓存。
      const codes = (d?.stocks || []).map(s => s.ts_code).filter(Boolean);
      if (codes.length === 0) {
        setPrefetchDone(true);
        return;
      }

      const chunkSize = 50; // 后端单次上限 50
      const chunks = [];
      for (let i = 0; i < codes.length; i += chunkSize) {
        chunks.push(codes.slice(i, i + chunkSize));
      }
      // 手动重试（retryNonce>0）时强制刷新缓存，拉最新盘后数据；平时走 6h 缓存秒回
      const refreshParam = retryNonce > 0 ? '&refresh=1' : '';
      // 串行 chunk：避免 chunk 间也并发；chunk 内由后端串行处理
      for (const ch of chunks) {
        if (cancelled) return;
        try {
          const { ok: bok, data: bd } = await apiFetch(
            `/api/stock-dashboard/batch?codes=${ch.map(encodeURIComponent).join(',')}${refreshParam}`,
            { signal: controller.signal }
          );
          if (cancelled) return;
          if (bok && bd?.results) {
            // 仅把成功（无 error）且非空的结果灌进 map；有 error 的由卡片自取逻辑兜底
            setDashMap(prev => {
              const next = { ...prev };
              for (const [c, v] of Object.entries(bd.results)) {
                if (v && !v.error) next[c] = v;
              }
              return next;
            });
          }
        } catch (e) {
          // 批量失败静默：每张卡片仍有自己的单只请求兜底
          if (cancelled) return;
        }
      }
      if (cancelled) return;
      setPrefetchDone(true);
    })();
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [selectedDate, minCount, retryNonce]);

  const distribution = useMemo(() => {
    if (!data?.stocks) return EMPTY_ARR;
    const dist = {};
    data.stocks.forEach(s => {
      const c = s.resonance_count;
      dist[c] = (dist[c] || 0) + 1;
    });
    return Object.entries(dist).sort((a, b) => Number(a[0]) - Number(b[0]));
  }, [data]);

  if (!selectedDate) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        正在获取交易日期...
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 标题 + 日期导航 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          🎯 多策略共振
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
        </h2>
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
      </div>

      {/* 说明卡片 */}
      <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-sm mb-1"><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 多策略共振</div>
        <div className="text-xs space-y-1" style={{ color: 'var(--text-secondary)' }}>
          <div>共振 = 同一只股票被多个策略同时命中。不同维度（趋势/资金/形态/突破）共振意味着更强信号，胜率更高。</div>
          <div className="flex items-center gap-3 flex-wrap mt-1">
            {data?.strategy_meta?.map(s => (
              <span key={s.key} className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                {s.icon} {s.name}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="rounded-lg p-3 flex items-center justify-between" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <span className="text-sm" style={{ color: '#ef4444' }}>{error}</span>
          <button
            onClick={() => setRetryNonce(n => n + 1)}
            className="px-3 py-1 rounded text-xs border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            重试
          </button>
        </div>
      )}

      {/* 统计条 + 共振数过滤 */}
      {data && (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            共 <strong style={{ color: 'var(--text-primary)' }}>{data.total_stocks}</strong> 只 ·
            <strong style={{ color: 'var(--text-primary)' }}> {data.total_hits}</strong> 次命中
            {distribution.length > 0 && (
              <span className="ml-2">
                {distribution.map(([count, num]) => (
                  <span key={count} className="ml-1.5">
                    <span style={{ color: getResonanceColor(Number(count)) }}>{count}共振</span>:{num}
                  </span>
                ))}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>筛选:</span>
            {MIN_COUNT_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setMinCount(opt.value)}
                className="px-2 py-0.5 rounded text-xs border transition-all"
                style={{
                  borderColor: minCount === opt.value ? '#a855f7' : 'var(--border-color)',
                  background: minCount === opt.value ? 'rgba(168,85,247,0.1)' : 'transparent',
                  color: minCount === opt.value ? '#a855f7' : 'var(--text-secondary)',
                  fontWeight: minCount === opt.value ? 600 : 400,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 股票列表 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-64 gap-2">
            <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: '#a855f7', borderTopColor: 'transparent' }} />
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>加载共振数据...</span>
          </div>
        ) : data?.stocks?.length > 0 ? (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
            {data.stocks.map((stock, idx) => (
              <div key={stock.ts_code} style={{ contentVisibility: 'auto', containIntrinsicSize: '360px' }}>
                <CardSafetyBoundary>
                  <ResonanceSignalItem
                    stock={stock}
                    prefetchedDash={dashMap[stock.ts_code] || null}
                    awaitParentPrefetch={!prefetchDone}
                  />
                </CardSafetyBoundary>
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
            {data ? '当日无共振股票，降低筛选阈值试试（如切换到"全部"或"2+"）' : '暂无数据'}
          </div>
        )}
      </div>

      {/* === 20天跟踪模块 (完整复制自 StrategyTrackPage) === */}
      <div className="border-t pt-3 mt-4" style={{ borderColor: 'var(--border-color)' }}>
        {/* 顶栏: 标题 + 操作按钮 */}
        <div className="flex items-center justify-between flex-wrap gap-2 mb-2">
          <div className="flex items-center gap-2">
            <span style={{ display:'inline-block', width:4, height:18, background:'#a855f7', borderRadius:2 }} />
            <h3 className="text-base font-bold">📊 20天跟踪</h3>
            <span className="text-xs text-gray-500">BS出现S撤离 · 满20天到期</span>
          </div>
          <div className="flex items-center gap-1.5 flex-wrap">
            <button onClick={handlePoolSelectedDate} disabled={trackActing}
              className="px-2.5 py-1 text-xs rounded-md font-medium"
              style={{ background:'#7c3aed', color:'#fff' }}
              title={`入池当前选中日期 ${selectedDate || ''}`}>
              ➕ 入池({selectedDate || '今日'})
            </button>
            <button onClick={handlePoolCustomDate} disabled={trackActing}
              className="px-2.5 py-1 text-xs rounded-md font-medium"
              style={{ background:'#7c3aed', color:'#fff' }}>
              📅 入池(指定日期)
            </button>
            <button onClick={handleDailyUpdate} disabled={trackActing}
              className="px-2.5 py-1 text-xs rounded-md font-medium"
              style={{ background:'#2563eb', color:'#fff' }}>
              ⚡ 每日更新
            </button>
            <button onClick={() => { if (trackTab==='active') loadTrackActive(); else loadTrackHistory(); }}
              className="px-2.5 py-1 text-xs rounded-md font-medium"
              style={{ background:'#6b7280', color:'#fff' }}>
              🔄 刷新
            </button>
          </div>
        </div>

        {/* 汇总 chips */}
        {trackActive?.summary && (
          <div className="flex items-center gap-2 flex-wrap mb-2">
            <Chip label="跟踪中" value={trackActive.summary.active} color="#7c3aed" />
            <Chip label="已撤离" value={trackActive.summary.exited + trackActive.summary.expired} color="#dc2626" />
            <Chip label="平均收益" value={fmtPct(trackActive.summary.avg_return)} color={pctColor(trackActive.summary.avg_return)} />
            <Chip label="胜率" value={(trackActive.summary.win_rate * 100).toFixed(0) + '%'} color="#2563eb" />
            <Chip label="最大收益" value={fmtPct(trackActive.summary.max_return)} color={UP_COLOR} />
            <Chip label="最小收益" value={fmtPct(trackActive.summary.min_return)} color={DOWN_COLOR} />
          </div>
        )}

        {/* Tabs */}
        <div className="flex items-center gap-3 mb-2 border-b" style={{ borderColor:'var(--border-color)' }}>
          <button onClick={() => setTrackTab('active')}
            className="px-3 py-1.5 text-sm font-medium border-b-2"
            style={{ borderColor: trackTab==='active' ? '#a855f7' : 'transparent', color: trackTab==='active' ? '#a855f7' : 'var(--text-muted)' }}>
            跟踪中 ({trackActive?.summary?.active ?? 0})
          </button>
          <button onClick={() => setTrackTab('history')}
            className="px-3 py-1.5 text-sm font-medium border-b-2"
            style={{ borderColor: trackTab==='history' ? '#a855f7' : 'transparent', color: trackTab==='history' ? '#a855f7' : 'var(--text-muted)' }}>
            历史 ({(trackHistory?.rows?.length) ?? 0})
          </button>
        </div>

        {/* 跟踪中 - 卡片网格 */}
        {trackTab === 'active' && (
          trackLoading ? (
            <div className="text-center py-4 text-sm text-gray-500">加载跟踪数据...</div>
          ) : trackActive?.rows?.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
              {trackActive.rows.map(r => (
                <TrackerCard key={r.id} row={r} onExit={handleManualExit} acting={trackActing} />
              ))}
            </div>
          ) : (
            <div className="text-center py-4 text-sm text-gray-500">暂无跟踪中的股票，点击"入池"开始跟踪</div>
          )
        )}

        {/* 历史 - 表格 */}
        {trackTab === 'history' && (
          trackHistory?.rows?.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background:'var(--bg-secondary)' }} className="text-left">
                    <th className="px-2 py-1.5">撤离日期</th>
                    <th className="px-2 py-1.5">股票</th>
                    <th className="px-2 py-1.5">入池日期</th>
                    <th className="px-2 py-1.5">跟踪天数</th>
                    <th className="px-2 py-1.5">撤离原因</th>
                    <th className="px-2 py-1.5">入池价</th>
                    <th className="px-2 py-1.5">撤离价</th>
                    <th className="px-2 py-1.5">撤离收益%</th>
                    <th className="px-2 py-1.5">命中策略数</th>
                  </tr>
                </thead>
                <tbody>
                  {trackHistory.rows.map((r, i) => {
                    const exitStyle = exitReasonStyle(r.exit_reason);
                    return (
                      <tr key={r.id} style={{ background: i % 2 === 0 ? 'transparent' : 'var(--bg-secondary)' }}>
                        <td className="px-2 py-1.5">{r.exit_date}</td>
                        <td className="px-2 py-1.5">
                          <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{r.name}</span>{' '}
                          <SinaLink tsCode={r.ts_code} />
                        </td>
                        <td className="px-2 py-1.5">{r.pool_date}</td>
                        <td className="px-2 py-1.5">{r.latest_day}</td>
                        <td className="px-2 py-1.5">
                          <span className="px-1.5 py-0.5 rounded text-white text-[10px]"
                            style={{ background: exitStyle.bg, color: exitStyle.color }}>
                            {exitStyle.label}
                          </span>
                        </td>
                        <td className="px-2 py-1.5">{r.pool_close}</td>
                        <td className="px-2 py-1.5">{r.exit_price ?? r.latest_close}</td>
                        <td className="px-2 py-1.5 font-bold" style={{ color: pctColor(r.exit_return_pct) }}>
                          {fmtPct(r.exit_return_pct)}
                        </td>
                        <td className="px-2 py-1.5">{r.strategy_count}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="text-center py-4 text-sm text-gray-500">暂无历史记录</div>
          )
        )}
      </div>
    </div>
  );
}

/**
 * 单只共振股票卡片：把 signal 对象用 useMemo 缓存，避免父组件重渲染时
 * 每个卡片的 signal prop 都是新引用，破坏 SignalCardV4 的 memo。
 *
 * 关键：把 resonance API 的 latest_price/pct_chg 注入到 position 与 quote，
 * 让 SignalCardTuned 内部读取 position.price / position.dayProfitPct 时能拿到值。
 * 否则 stock_features_daily 缺失的股票（占共振列表 90%+）会显示 "当日 -- --"。
 *
 * 性能：把父组件批量预取的 dashMap[code] 通过 prefetchedDash 透传，
 * 避免每张卡片 IntersectionObserver 各自打 /api/stock-dashboard/{code}。
 *
 * awaitParentPrefetch 阶段：父组件还在跑批量预取，卡片必须等
 *   （避免 100+ 卡片同时打单只接口 → 后端被打挂）。
 */
const ResonanceSignalItem = ({ stock, prefetchedDash = null, awaitParentPrefetch = false }) => {
  const signal = useMemo(() => {
    const lp = stock.latest_price;
    const pc = stock.pct_chg;
    const lpNum = lp == null ? null : Number(lp);
    const pcNum = pc == null ? null : Number(pc);
    return {
      secCode: stock.ts_code,
      secName: stock.name,
      code: stock.ts_code,
      signalLabel: `${stock.resonance_count}共振`,
      signalColor: getResonanceColor(stock.resonance_count),
      score: stock.total_score,
      strategies: stock.strategies,
      sector: stock.sector,
      latest_price: lp,
      pct_chg: pc,
      return_20d: stock.return_20d,
      // 注入 position：SignalCardTuned 行1 的「当日 X% / 现价」读这里
      position: {
        price: lpNum,
        dayProfitPct: pcNum,
        avg_cost: null,
        count: 0,
        profitPct: null,
      },
      // 注入 quote：实时图表与 sparkline 读这里
      quote: lpNum != null ? { price: lpNum, changePct: pcNum } : null,
    };
  }, [stock]);

  return (
    <StrategySignalCard
      signal={signal}
      mode="watchlist"
      showWatchBtn
      showAnalysisButton
      prefetchedDash={prefetchedDash}
      awaitParentPrefetch={awaitParentPrefetch}
    />
  );
};
