/**
 * 策略共振股 20 天跟踪
 *
 * 多策略共振选股入池后，跟踪 20 天。出现 BS S 信号则撤离到历史。
 *
 * 布局：
 * ┌──────────────────────────────────────────────────────────────────┐
 * │ 🎯 策略共振股 20 天跟踪  [入池(今日)][入池(指定日期)][每日更新][刷新]   │
 * │ 跟踪中 N | 已撤离 N | 平均收益 +X% | 胜率 X% | 最大 +X% | 最小 -X%  │
 * ├──────────────────────────────────────────────────────────────────┤
 * │ [跟踪中] [历史]                                                    │
 * ├──────────────────────────────────────────────────────────────────┤
 * │ ┌──────────┐ ┌──────────┐ ┌──────────┐                           │
 * │ │ 股票卡片  │ │ 股票卡片  │ │ 股票卡片  │                           │
 * │ └──────────┘ └──────────┘ └──────────┘                           │
 * └──────────────────────────────────────────────────────────────────┘
 *
 * API:
 *   GET  /api/strategy-track/list?status=active
 *   GET  /api/strategy-track/history?limit=100&offset=0
 *   POST /api/strategy-track/pool?date=YYYY-MM-DD&min_count=2
 *   POST /api/strategy-track/daily-update
 *   POST /api/strategy-track/manual-exit  body: { tracker_id, reason }
 */
import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';
import SinaLink from '../components/SinaLink';
import { stripCode } from '../utils/format';

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

export default function StrategyTrackPage() {
  const [tab, setTab] = useState('active'); // 'active' | 'history'
  const [activeData, setActiveData] = useState(null);
  const [historyData, setHistoryData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState('');

  const loadActive = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { ok, data, error: err } = await apiFetch('/api/strategy-track/list?status=active');
      if (ok) setActiveData(data);
      else setError(err || '加载跟踪列表失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadHistory = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { ok, data, error: err } = await apiFetch('/api/strategy-track/history?limit=100&offset=0');
      if (ok) setHistoryData(data);
      else setError(err || '加载历史失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const load = useCallback(() => {
    if (tab === 'active') return loadActive();
    return loadHistory();
  }, [tab, loadActive, loadHistory]);

  useEffect(() => { load(); }, [load]);

  // 入池
  const doPool = async (date) => {
    setActing(true);
    try {
      const { ok, data, error: err } = await apiFetch(`/api/strategy-track/pool?date=${date}&min_count=2`, { method: 'POST' });
      if (ok) {
        const added = data?.total_added ?? 0;
        const skipped = data?.skipped_duplicates?.length ?? 0;
        alert(`✅ 入池完成\n日期: ${data?.pool_date || date}\n新增: ${added} 只\n跳过重复: ${skipped} 只`);
        loadActive();
      } else {
        alert('❌ 入池失败: ' + (err || '未知错误'));
      }
    } catch (e) {
      alert('❌ ' + String(e));
    } finally {
      setActing(false);
    }
  };

  const handlePoolToday = () => {
    const today = new Date().toISOString().slice(0, 10);
    doPool(today);
  };

  const handlePoolDate = () => {
    const date = window.prompt('请输入入池日期 YYYY-MM-DD:', '2026-07-23');
    if (!date) return;
    doPool(date.trim());
  };

  // 每日更新
  const handleDailyUpdate = async () => {
    setActing(true);
    try {
      const { ok, data, error: err } = await apiFetch('/api/strategy-track/daily-update', { method: 'POST' });
      if (ok) {
        alert(`✅ 每日更新完成\n更新: ${data?.total_updated ?? 0} 只\n撤离(BS卖出): ${data?.total_exited ?? 0} 只\n到期(满20天): ${data?.total_expired ?? 0} 只`);
        loadActive();
      } else {
        alert('❌ 更新失败: ' + (err || '未知错误'));
      }
    } catch (e) {
      alert('❌ ' + String(e));
    } finally {
      setActing(false);
    }
  };

  // 手动撤离
  const handleManualExit = async (trackerId, name) => {
    if (!confirm(`确认手动撤离 ${name}?`)) return;
    setActing(true);
    try {
      const { ok, error: err } = await apiFetch('/api/strategy-track/manual-exit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tracker_id: trackerId, reason: 'MANUAL' }),
      });
      if (ok) {
        alert(`✅ 已撤离 ${name}`);
        loadActive();
      } else {
        alert('❌ 撤离失败: ' + (err || '未知错误'));
      }
    } catch (e) {
      alert('❌ ' + String(e));
    } finally {
      setActing(false);
    }
  };

  const summary = activeData?.summary || {};
  const activeRows = activeData?.rows || [];
  const historyRows = historyData?.rows || [];
  const exitedCount = (summary.exited || 0) + (summary.expired || 0);

  return (
    <div className="space-y-2">
      {/* ============ 顶部:标题 + 操作 + 汇总 (sticky) ============ */}
      <div
        className="sticky top-0 z-20 rounded-lg border p-2.5"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        <div className="flex items-center gap-2 flex-wrap">
          {/* 左侧色块 + 标题 */}
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-5 rounded-sm" style={{ background: '#a855f7' }} />
            <h1 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
              🎯 策略共振股 20 天跟踪
            </h1>
          </div>
          {/* 操作按钮 */}
          <div className="flex items-center gap-1 ml-auto flex-wrap">
            <button
              onClick={handlePoolToday}
              disabled={acting}
              className="px-2 py-1 text-xs rounded border disabled:opacity-50"
              style={{ borderColor: '#a855f7', color: '#a855f7' }}
            >
              ➕ 入池(今日)
            </button>
            <button
              onClick={handlePoolDate}
              disabled={acting}
              className="px-2 py-1 text-xs rounded border disabled:opacity-50"
              style={{ borderColor: '#a855f7', color: '#a855f7' }}
            >
              📅 入池(指定日期)
            </button>
            <button
              onClick={handleDailyUpdate}
              disabled={acting}
              className="px-2 py-1 text-xs rounded border disabled:opacity-50"
              style={{ borderColor: '#3b82f6', color: '#3b82f6' }}
            >
              ⚡ 每日更新
            </button>
            <button
              onClick={load}
              disabled={loading}
              className="px-2 py-1 text-xs rounded border disabled:opacity-50"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              {loading ? '⏳ 加载中...' : '🔄 刷新'}
            </button>
          </div>
        </div>

        {/* 汇总 chips */}
        {activeData && (
          <div className="flex items-center gap-1.5 flex-wrap mt-2">
            <Chip label="跟踪中" value={`${summary.active ?? 0} 只`} color="#a855f7" />
            <Chip label="已撤离" value={`${exitedCount} 只`} color="#6b7280" />
            <Chip label="平均收益" value={fmtPct(summary.avg_return)} color={pctColor(summary.avg_return)} />
            <Chip label="胜率" value={summary.win_rate != null ? `${Number(summary.win_rate).toFixed(1)}%` : '-'} color="#3b82f6" />
            <Chip label="最大收益" value={fmtPct(summary.max_return)} color={pctColor(summary.max_return)} />
            <Chip label="最小收益" value={fmtPct(summary.min_return)} color={pctColor(summary.min_return)} />
          </div>
        )}

        {error && <div className="text-xs mt-2" style={{ color: DOWN_COLOR }}>{error}</div>}
      </div>

      {/* ============ Tabs ============ */}
      <div className="flex items-center gap-1">
        {[
          { key: 'active', label: '跟踪中', count: summary.active ?? 0 },
          { key: 'history', label: '历史', count: exitedCount },
        ].map((t) => {
          const isActive = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="px-3 py-1 text-xs font-medium rounded-t border-b-2 transition-colors"
              style={{
                color: isActive ? '#a855f7' : 'var(--text-muted)',
                borderColor: isActive ? '#a855f7' : 'transparent',
                background: isActive ? 'rgba(168,85,247,0.06)' : 'transparent',
              }}
            >
              {t.label} <span style={{ opacity: 0.7 }}>({t.count})</span>
            </button>
          );
        })}
      </div>

      {/* ============ 跟踪中: 股票卡片 ============ */}
      {tab === 'active' && (
        <div>
          {loading && !activeData && (
            <div className="text-xs p-4 text-center" style={{ color: 'var(--text-muted)' }}>加载中...</div>
          )}
          {!loading && activeRows.length === 0 && (
            <div className="text-xs p-4 text-center rounded border" style={{ color: 'var(--text-muted)', borderColor: 'var(--border-color)' }}>
              暂无跟踪中的股票，点击"入池(今日)"开始
            </div>
          )}
          {activeRows.length > 0 && (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2.5">
              {activeRows.map((r) => (
                <TrackerCard key={r.id} row={r} onExit={handleManualExit} acting={acting} />
              ))}
            </div>
          )}
        </div>
      )}

      {/* ============ 历史: 表格 ============ */}
      {tab === 'history' && (
        <div>
          {loading && !historyData && (
            <div className="text-xs p-4 text-center" style={{ color: 'var(--text-muted)' }}>加载中...</div>
          )}
          {!loading && historyRows.length === 0 && (
            <div className="text-xs p-4 text-center rounded border" style={{ color: 'var(--text-muted)', borderColor: 'var(--border-color)' }}>
              暂无历史记录
            </div>
          )}
          {historyRows.length > 0 && (
            <div className="rounded-lg border overflow-x-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ background: 'var(--bg-hover)' }}>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>撤离日期</th>
                    <th className="px-2 py-2 text-left font-bold" style={{ color: 'var(--text-primary)' }}>股票</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>入池日期</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>跟踪天数</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>撤离原因</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>入池价</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>撤离价</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>撤离收益%</th>
                    <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>命中策略数</th>
                  </tr>
                </thead>
                <tbody>
                  {historyRows.map((r, i) => {
                    const rs = exitReasonStyle(r.exit_reason);
                    return (
                      <tr key={r.id} className="border-t" style={{ borderColor: 'var(--border-color)', background: i % 2 ? 'rgba(0,0,0,0.02)' : 'transparent' }}>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.exit_date || '-'}</td>
                        <td className="px-2 py-2">
                          <div className="flex items-center gap-1">
                            <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                            <SinaLink tsCode={r.ts_code} />
                          </div>
                          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{stripCode(r.ts_code)}</div>
                        </td>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.pool_date || '-'}</td>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.track_days != null ? `${r.track_days}天` : '-'}</td>
                        <td className="px-2 py-2 text-center">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap" style={{ background: rs.bg, color: rs.color, border: `1px solid ${rs.border}` }}>
                            {rs.label}
                          </span>
                        </td>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.pool_close != null ? Number(r.pool_close).toFixed(2) : '-'}</td>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.exit_price != null ? Number(r.exit_price).toFixed(2) : '-'}</td>
                        <td className="px-2 py-2 text-center font-bold" style={{ color: pctColor(r.exit_return_pct) }}>{fmtPct(r.exit_return_pct)}</td>
                        <td className="px-2 py-2 text-center" style={{ color: 'var(--text-secondary)' }}>{r.strategy_count ?? '-'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ============ 提示 ============ */}
      <div className="text-[10px] text-center" style={{ color: 'var(--text-muted)' }}>
        多策略共振选股 · 20 天跟踪周期 · 出现 BS 卖出信号即撤离 · 仅供研究不构成投资建议
      </div>
    </div>
  );
}

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
