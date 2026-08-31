import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';

import { apiFetch } from '../utils/request';


const fmtPct = (value) => {
  if (value == null) return '—';
  const number = Number(value);
  return `${number > 0 ? '+' : ''}${number.toFixed(2)}%`;
};

const pctColor = (value) => {
  if (value == null || Number(value) === 0) return 'var(--text-muted)';
  return Number(value) > 0 ? 'var(--flow-up)' : 'var(--flow-down)';
};

const admissionLabel = (value) => (value === 'SELECTED' ? '正式入选' : '形态观察');

const openAnalysis = (code) => {
  if (!code) return;
  const child = window.open(`/stock-analysis?code=${encodeURIComponent(code)}`, '_blank', 'noopener,noreferrer');
  if (child) child.opener = null;
};

function SummaryChip({ label, value, color = 'var(--text-primary)' }) {
  return (
    <div className="rounded border px-2.5 py-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-bold" style={{ color }}>{value}</div>
    </div>
  );
}

function AdmissionBadge({ value }) {
  const selected = value === 'SELECTED';
  return (
    <span
      className="rounded-full border px-2 py-0.5 text-[10px] font-semibold whitespace-nowrap"
      style={{
        color: selected ? 'var(--flow-up)' : '#f59e0b',
        borderColor: selected ? 'var(--flow-up)' : '#f59e0b',
        background: selected ? 'color-mix(in srgb, var(--flow-up) 8%, transparent)' : 'rgba(245,158,11,0.08)',
      }}
    >
      {admissionLabel(value)}
    </span>
  );
}

function DailyStrip({ daily = [] }) {
  const byDay = new Map(daily.map((item) => [item.day_n, item]));
  return (
    <div className="overflow-x-auto">
      <div className="grid min-w-[980px] gap-1" style={{ gridTemplateColumns: 'repeat(20, minmax(44px, 1fr))' }}>
        {Array.from({ length: 20 }, (_, index) => index + 1).map((day) => {
          const item = byDay.get(day);
          return (
            <div
              key={day}
              className="rounded border px-1 py-1 text-center"
              style={{
                borderColor: item ? pctColor(item.cum_return_pct) : 'var(--border-light)',
                background: item ? 'var(--bg-card)' : 'var(--bg-surface)',
              }}
              title={item ? `${item.trade_date} · 收盘 ${Number(item.close).toFixed(2)} · 当日 ${fmtPct(item.daily_pct)} · 回撤 ${fmtPct(item.drawdown_pct)}` : `D${day} 尚无日线`}
            >
              <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>D{day}</div>
              <div className="text-[10px] font-semibold" style={{ color: pctColor(item?.cum_return_pct) }}>
                {item ? fmtPct(item.cum_return_pct) : '—'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function TrackTable({ rows, activeTab, acting, onArchive }) {
  if (!rows.length) {
    return (
      <div className="rounded border px-4 py-12 text-center text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
        {activeTab ? '暂无跟踪样本，先同步最新回马枪池' : '暂无已完成或已归档样本'}
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[1160px] text-[11px]">
          <thead style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
            <tr>
              <th className="px-2 py-2 text-center">池层级</th>
              <th className="px-2 py-2 text-left">股票</th>
              <th className="px-2 py-2 text-center">结构日 / Day0</th>
              <th className="px-2 py-2 text-right">Day0 快照价</th>
              <th className="px-2 py-2 text-right">最新价 / 累计</th>
              <th className="px-2 py-2 text-center">进度</th>
              <th className="px-2 py-2 text-right">最大累计</th>
              <th className="px-2 py-2 text-right">最大回撤</th>
              <th className="px-2 py-2 text-center">状态</th>
              <th className="px-2 py-2 text-center">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <TrackRows key={row.id} row={row} activeTab={activeTab} acting={acting} onArchive={onArchive} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TrackRows({ row, activeTab, acting, onArchive }) {
  const statusLabel = row.status === 'active' ? '跟踪中' : row.status === 'completed' ? '20日完成' : '已归档';
  const code = String(row.ts_code || '').split('.')[0];
  return (
    <>
      <tr className="border-t" style={{ borderColor: 'var(--border-color)' }}>
        <td className="px-2 py-2 text-center"><AdmissionBadge value={row.admission_status} /></td>
        <td className="px-2 py-2 whitespace-nowrap">
          <button onClick={() => openAnalysis(code)} className="font-bold hover:underline" style={{ color: 'var(--text-primary)' }}>
            {row.name || row.ts_code} ↗
          </button>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{row.ts_code} · {row.score ?? '—'} 分</div>
        </td>
        <td className="px-2 py-2 text-center whitespace-nowrap">
          <div>{row.structure_date || '—'}</div>
          <div style={{ color: 'var(--text-muted)' }}>Day0 {row.pool_date || '—'}</div>
        </td>
        <td className="px-2 py-2 text-right font-mono font-semibold">{row.entry_price == null ? '—' : Number(row.entry_price).toFixed(2)}</td>
        <td className="px-2 py-2 text-right whitespace-nowrap">
          <div className="font-mono font-semibold">{row.latest_close == null ? '—' : Number(row.latest_close).toFixed(2)}</div>
          <div className="font-bold" style={{ color: pctColor(row.latest_return_pct) }}>{fmtPct(row.latest_return_pct)}</div>
        </td>
        <td className="px-2 py-2 text-center whitespace-nowrap">
          <div className="font-bold">D{row.latest_day || 0} / 20</div>
          <div className="mt-1 h-1.5 w-24 overflow-hidden rounded-full" style={{ background: 'var(--bg-hover)' }}>
            <div className="h-full rounded-full" style={{ width: `${Math.min((Number(row.latest_day || 0) / 20) * 100, 100)}%`, background: '#8b5cf6' }} />
          </div>
        </td>
        <td className="px-2 py-2 text-right font-bold" style={{ color: pctColor(row.max_return_pct) }}>{fmtPct(row.max_return_pct)}</td>
        <td className="px-2 py-2 text-right font-bold" style={{ color: pctColor(row.max_drawdown_pct) }}>{fmtPct(row.max_drawdown_pct)}</td>
        <td className="px-2 py-2 text-center whitespace-nowrap">
          <span className="rounded border px-2 py-0.5" style={{ borderColor: 'var(--border-color)', color: row.status === 'active' ? '#8b5cf6' : 'var(--text-secondary)' }}>{statusLabel}</span>
        </td>
        <td className="px-2 py-2 text-center whitespace-nowrap">
          {activeTab ? (
            <button onClick={() => onArchive(row)} disabled={acting} className="rounded border px-2 py-1 disabled:opacity-40" style={{ borderColor: 'var(--border-color)' }}>归档</button>
          ) : (
            <span style={{ color: 'var(--text-muted)' }}>{row.completed_date || '—'}</span>
          )}
        </td>
      </tr>
      <tr className="border-t" style={{ borderColor: 'var(--border-light)', background: 'var(--bg-surface)' }}>
        <td colSpan="10" className="px-2 py-2"><DailyStrip daily={row.daily} /></td>
      </tr>
    </>
  );
}

export default function HorsebackTrackPage() {
  const [tab, setTab] = useState('active');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [acting, setActing] = useState(false);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    const path = tab === 'active' ? '/api/horseback-track/list?status=active' : '/api/horseback-track/history?limit=500';
    const response = await apiFetch(path, {}, 15000, 1);
    if (response.ok) setData(response.data);
    else setError(response.error || '加载回马枪跟踪池失败');
    setLoading(false);
  }, [tab]);

  useEffect(() => { load(); }, [load]);

  const syncLatest = async () => {
    setActing(true);
    const response = await apiFetch('/api/horseback-track/sync', { method: 'POST' }, 30000, 0);
    if (response.ok) {
      alert(`同步完成：新增 ${response.data.total_added || 0} 只，已存在 ${response.data.total_duplicates || 0} 只`);
      await load();
    } else {
      alert(`同步失败：${response.error || '未知错误'}`);
    }
    setActing(false);
  };

  const updateDaily = async () => {
    setActing(true);
    const response = await apiFetch('/api/horseback-track/daily-update', { method: 'POST' }, 60000, 0);
    if (response.ok) {
      alert(`日线更新完成：更新 ${response.data.total_updated || 0} 只，20 日完成 ${response.data.total_completed || 0} 只，错误 ${response.data.total_errors || 0} 只`);
      await load();
    } else {
      alert(`更新失败：${response.error || '未知错误'}`);
    }
    setActing(false);
  };

  const archive = async (row) => {
    if (!window.confirm(`确认归档 ${row.name || row.ts_code}？归档后不再更新日线。`)) return;
    setActing(true);
    const response = await apiFetch('/api/horseback-track/archive', {
      method: 'POST',
      body: JSON.stringify({ tracker_id: row.id, reason: 'MANUAL' }),
    }, 15000, 0);
    if (response.ok) await load();
    else alert(`归档失败：${response.error || '未知错误'}`);
    setActing(false);
  };

  const summary = data?.summary || {};
  const rows = data?.rows || [];
  const selectedCompleted = summary.completed_by_admission?.SELECTED || {};
  const watchingCompleted = summary.completed_by_admission?.WATCHING || {};

  return (
    <div className="space-y-3 p-3 text-sm" style={{ color: 'var(--text-primary)' }}>
      <header className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex flex-wrap items-center gap-2">
          <div className="h-5 w-1.5 rounded" style={{ background: '#8b5cf6' }} />
          <h1 className="text-lg font-bold">🐎 回马枪 20 日历史跟踪</h1>
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>独立池 · D1–D20 · 不自动交易</span>
          <div className="ml-auto flex flex-wrap items-center gap-2">
            <Link to="/a-horseback" className="rounded border px-2.5 py-1 text-[11px] no-underline" style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}>返回选股器</Link>
            <button onClick={syncLatest} disabled={acting} className="rounded border px-2.5 py-1 text-[11px] disabled:opacity-40" style={{ borderColor: '#8b5cf6', color: '#8b5cf6' }}>同步最新回马枪池</button>
            <button onClick={updateDaily} disabled={acting} className="rounded border px-2.5 py-1 text-[11px] disabled:opacity-40" style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}>更新 D1–D20</button>
            <button onClick={load} disabled={loading} className="rounded border px-2.5 py-1 text-[11px] disabled:opacity-40" style={{ borderColor: 'var(--border-color)' }}>{loading ? '加载中…' : '刷新'}</button>
          </div>
        </div>
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5 xl:grid-cols-10">
          <SummaryChip label="跟踪中" value={`${summary.active || 0} 只`} color="#8b5cf6" />
          <SummaryChip label="正式入选" value={`${summary.selected_active || 0} 只`} color="var(--flow-up)" />
          <SummaryChip label="形态观察" value={`${summary.watching_active || 0} 只`} color="#f59e0b" />
          <SummaryChip label="20日完成" value={`${summary.completed || 0} 只`} />
          <SummaryChip label="当前均值" value={fmtPct(summary.active_avg_return)} color={pctColor(summary.active_avg_return)} />
          <SummaryChip label="完成均值" value={fmtPct(summary.completed_avg_return)} color={pctColor(summary.completed_avg_return)} />
          <SummaryChip label="完成总胜率" value={summary.completed_win_rate == null ? '样本不足' : `${Number(summary.completed_win_rate).toFixed(1)}%`} color="var(--accent-blue)" />
          <SummaryChip label="正式入选胜率" value={selectedCompleted.win_rate == null ? '样本不足' : `${Number(selectedCompleted.win_rate).toFixed(1)}%`} color="var(--flow-up)" />
          <SummaryChip label="形态观察胜率" value={watchingCompleted.win_rate == null ? '样本不足' : `${Number(watchingCompleted.win_rate).toFixed(1)}%`} color="#f59e0b" />
          <SummaryChip label="胜率样本" value={`${summary.completed_samples || 0} 只`} />
        </div>
        {error && <div className="mt-2 text-xs" style={{ color: 'var(--accent-red)' }}>{error}</div>}
      </header>

      <div className="flex items-center gap-1 border-b" style={{ borderColor: 'var(--border-color)' }}>
        {[
          { key: 'active', label: `跟踪中 (${summary.active || 0})` },
          { key: 'history', label: `历史 (${(summary.completed || 0) + (summary.archived || 0)})` },
        ].map((item) => (
          <button
            key={item.key}
            onClick={() => setTab(item.key)}
            className="border-b-2 px-3 py-2 text-xs font-semibold"
            style={{ borderColor: tab === item.key ? '#8b5cf6' : 'transparent', color: tab === item.key ? '#8b5cf6' : 'var(--text-muted)' }}
          >
            {item.label}
          </button>
        ))}
      </div>

      {loading && !data ? (
        <div className="py-12 text-center" style={{ color: 'var(--text-muted)' }}>加载中…</div>
      ) : (
        <TrackTable rows={rows} activeTab={tab === 'active'} acting={acting} onArchive={archive} />
      )}

      <div className="rounded border px-3 py-2 text-[11px] leading-5" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)', background: 'var(--bg-card)' }}>
        入池口径：正式入选与形态观察分层记录，但必须已有真实实时快照价。历史结构扫描的“结构日”与实际 Day0 分开保存，收益从 Day0 快照价计算；D1–D20 仅使用本地日线。20 日胜率只统计已完成样本，未完成样本不进入分母。
      </div>
    </div>
  );
}
