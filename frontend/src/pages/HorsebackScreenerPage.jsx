import { useCallback, useEffect, useMemo, useState } from 'react';
import { apiFetch, formatApiError } from '../utils/request';

const ACTIVE = new Set(['QUEUED', 'COLLECTING', 'SCORING', 'QUOTING', 'CANCEL_REQUESTED']);
const STATUS_LABEL = {
  QUEUED: '排队中', COLLECTING: '采集候选', SCORING: '日线结构', QUOTING: '读取实时行情', CANCEL_REQUESTED: '正在取消',
  COMPLETED: '已完成', FAILED: '失败', CANCELLED: '已取消',
  SELECTED: '入选', WATCHING: '待触发', NOT_SELECTED: '观察池', INVALID: '数据无效',
};

const SHANGHAI_TODAY = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit',
}).format(new Date());  // 本机今日 YYYY-MM-DD；过去日期按 v1.1.5 使用历史结构 + 当前实时行情

const num = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);
const pct = (value) => value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}%`;

// 根据行情快照时间判断数据时段：9:30 前=盘前，9:30~15:00=盘中实时，15:00 后=盘后快照（价格为收盘价）
const sessionLabel = (iso) => {
  if (!iso) return '';
  const hm = iso.slice(11, 16);
  if (hm < '09:30') return '盘前';
  if (hm <= '15:00') return '盘中实时';
  return '盘后快照';
};

function StatusBadge({ status }) {
  const color = status === 'SELECTED' || status === 'COMPLETED'
    ? 'var(--flow-up)'
    : status === 'WATCHING'
      ? '#f59e0b'
      : status === 'FAILED' || status === 'INVALID'
        ? 'var(--accent-red)'
        : status === 'SCORING' || status === 'COLLECTING' || status === 'QUOTING'
          ? 'var(--accent-blue)'
          : 'var(--text-secondary)';
  return (
    <span className="inline-flex whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ color, borderColor: color }}>
      {STATUS_LABEL[status] || status}
    </span>
  );
}

function ScoreDetails({ row }) {
  if (!row.components?.length && !row.hard_failures?.length) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const items = row.components || [];
  return (
    <div className="text-[10px]">
      {row.hard_failures?.length > 0 && (
        <div className="mb-0.5 font-semibold" style={{ color: 'var(--accent-red)' }}>{row.hard_failures.join('；')}</div>
      )}
      {/* 9 项全显示：双列网格，每项单行不换行，失分红色、满分绿色 */}
      <div className="grid grid-cols-2 gap-x-4">
        {items.map((item) => {
          const full = item.points >= item.max_points;
          return (
            <div key={item.key} className="flex items-baseline justify-between gap-1.5 leading-[15px]" title={`${item.label} ${item.points}/${item.max_points}`}>
              <span className="truncate" style={{ color: full ? 'var(--text-muted)' : 'var(--text-primary)' }}>{item.label}</span>
              <b className="shrink-0" style={{ color: full ? 'var(--flow-up)' : 'var(--accent-red)' }}>{item.points}/{item.max_points}</b>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KlineSvg({ bars }) {
  const data = (bars || []).slice(-60);
  if (!data.length) return <div className="p-8 text-center text-sm">暂无 K 线</div>;
  const width = 900;
  const height = 320;
  const left = 48;
  const right = 12;
  const top = 18;
  const bottom = 30;
  const values = data.flatMap((bar) => [bar.low, bar.high, bar.ma5, bar.ma20, bar.ma60]).filter((value) => value != null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const x = (index) => left + ((index + 0.5) * (width - left - right)) / data.length;
  const y = (value) => top + ((max - value) / span) * (height - top - bottom);
  const candleWidth = Math.max(2, (width - left - right) / data.length * 0.58);
  const line = (key) => data.map((bar, index) => bar[key] == null ? null : `${x(index)},${y(bar[key])}`).filter(Boolean).join(' ');
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => max - span * ratio);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="block w-full" role="img" aria-label="截止日 K 线">
      {ticks.map((value) => (
        <g key={value}>
          <line x1={left} x2={width - right} y1={y(value)} y2={y(value)} stroke="var(--border-light)" strokeWidth="1" />
          <text x={left - 6} y={y(value) + 3} textAnchor="end" fontSize="10" fill="var(--text-muted)">{value.toFixed(2)}</text>
        </g>
      ))}
      {data.map((bar, index) => {
        const up = bar.close >= bar.open;
        const color = up ? 'var(--flow-up)' : 'var(--flow-down)';
        const bodyTop = y(Math.max(bar.open, bar.close));
        const bodyBottom = y(Math.min(bar.open, bar.close));
        return (
          <g key={bar.date}>
            <title>{`${bar.date} 开 ${bar.open} 高 ${bar.high} 低 ${bar.low} 收 ${bar.close}`}</title>
            <line x1={x(index)} x2={x(index)} y1={y(bar.high)} y2={y(bar.low)} stroke={color} />
            <rect x={x(index) - candleWidth / 2} y={bodyTop} width={candleWidth} height={Math.max(1, bodyBottom - bodyTop)} fill={color} />
          </g>
        );
      })}
      <polyline points={line('ma5')} fill="none" stroke="#f59e0b" strokeWidth="1.4" />
      <polyline points={line('ma20')} fill="none" stroke="#3b82f6" strokeWidth="1.4" />
      <polyline points={line('ma60')} fill="none" stroke="#a855f7" strokeWidth="1.4" />
      <text x={left} y={height - 8} fontSize="10" fill="#f59e0b">MA5</text>
      <text x={left + 38} y={height - 8} fontSize="10" fill="#3b82f6">MA20</text>
      <text x={left + 84} y={height - 8} fontSize="10" fill="#a855f7">MA60</text>
      <text x={width - right} y={height - 8} textAnchor="end" fontSize="10" fill="var(--text-muted)">
        {data[0].date} — {data[data.length - 1].date}
      </text>
    </svg>
  );
}

function KlineModal({ runId, stock, onClose }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let alive = true;
    apiFetch(`/api/horseback/runs/${runId}/kline/${encodeURIComponent(stock.ts_code)}`, {}, 15000, 1)
      .then((res) => {
        if (!alive) return;
        if (res.ok) setData(res.data);
        else setError(formatApiError(res.error, 'K 线加载失败'));
      });
    return () => { alive = false; };
  }, [runId, stock.ts_code]);
  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/55 p-5" onMouseDown={onClose}>
      <div className="max-h-[90vh] w-full max-w-5xl overflow-auto rounded-xl border shadow-2xl" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }} onMouseDown={(event) => event.stopPropagation()}>
        <div className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <b>{stock.name} · {stock.ts_code}</b>
            <div className="mt-1 text-[11px]" style={{ color: 'var(--text-muted)' }}>
              日线截至 {data?.as_of_date || '—'} · {data?.source || '本地日线'} · {data?.realtime_bar_included ? '含实时盘中 K 线' : '无实时盘中 K 线'}
            </div>
          </div>
          <button className="rounded border px-3 py-1 text-sm" style={{ borderColor: 'var(--border-color)' }} onClick={onClose}>关闭</button>
        </div>
        <div className="p-4">
          {error ? <div style={{ color: 'var(--accent-red)' }}>{error}</div> : data ? <KlineSvg bars={data.bars} /> : <div className="p-10 text-center">正在加载…</div>}
        </div>
      </div>
    </div>
  );
}

export default function HorsebackScreenerPage() {
  const [config, setConfig] = useState(null);
  const [token, setToken] = useState('');
  const [saving, setSaving] = useState(false);
  const [run, setRun] = useState(null);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('ALL');
  const [klineStock, setKlineStock] = useState(null);
  const [tokenModal, setTokenModal] = useState(false);
  const [options, setOptions] = useState({
    min_consolidation_days: 3,
    max_consolidation_days: 12,
    min_limit_count: 1,
    max_limit_count: 3,
    min_score: 75,
    max_candidates: 100,
    live_rise_pct_min: 3,
    live_volume_ratio_min: 1.2,
    allow_gem: false,
    allow_star: false,
    end_date: '',
  });

  const loadRun = useCallback(async (runId) => {
    const path = runId ? `/api/horseback/runs/${runId}` : '/api/horseback/runs/latest';
    const res = await apiFetch(path, {}, 15000, 1);
    if (res.ok) setRun(runId ? res.data : res.data.run);
    else setError(formatApiError(res.error, '任务读取失败'));
  }, []);

  useEffect(() => {
    let alive = true;
    Promise.all([
      apiFetch('/api/horseback/config', {}, 10000, 1),
      apiFetch('/api/horseback/runs/latest', {}, 15000, 1),
    ]).then(([configRes, runRes]) => {
      if (!alive) return;
      if (configRes.ok) setConfig(configRes.data);
      if (runRes.ok) setRun(runRes.data.run);
    });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    if (!run?.id || !ACTIVE.has(run.status)) return undefined;
    const timer = setInterval(() => loadRun(run.id), 1500);
    return () => clearInterval(timer);
  }, [run?.id, run?.status, loadRun]);

  // 终态后每 60 秒慢轮询：调度器盘中每 30 分钟自动刷新实时行情，
  // 页面不重载也能看到最新快照（状态变化时由上面的快轮询接管）。
  useEffect(() => {
    if (!run?.id || ACTIVE.has(run.status)) return undefined;
    const timer = setInterval(() => loadRun(run.id), 60000);
    return () => clearInterval(timer);
  }, [run?.id, run?.status, loadRun]);

  const saveToken = async () => {
    setSaving(true);
    setError('');
    const res = await apiFetch('/api/horseback/config', { method: 'PUT', body: JSON.stringify({ token }) }, 15000, 0);
    setSaving(false);
    if (!res.ok) {
      setError(formatApiError(res.error, '密钥保存失败'));
      return false;
    }
    setToken('');
    setConfig(res.data);
    return true;
  };

  const start = async () => {
    setError('');
    const { end_date, ...params } = options;
    const res = await apiFetch('/api/horseback/runs', { method: 'POST', body: JSON.stringify({ ...params, end_date: end_date || undefined }) }, 15000, 0);
    if (!res.ok) {
      setError(formatApiError(res.error, '启动失败'));
      return;
    }
    setRun({ ...res.data, results: [] });
  };

  const cancel = async () => {
    if (!run?.id) return;
    const res = await apiFetch(`/api/horseback/runs/${run.id}/cancel`, { method: 'POST' }, 15000, 0);
    if (res.ok) setRun(res.data);
    else setError(formatApiError(res.error, '取消失败'));
  };

  const refreshQuotes = async () => {
    if (!run?.id) return;
    setError('');
    const res = await apiFetch(`/api/horseback/runs/${run.id}/quotes`, { method: 'POST' }, 15000, 0);
    if (res.ok) setRun(res.data);
    else setError(formatApiError(res.error, '实时行情刷新失败'));
  };

  const rows = useMemo(() => {
    const results = run?.results || [];
    return filter === 'ALL' ? results : results.filter((item) => item.status === filter);
  }, [run?.results, filter]);
  const progress = run?.progress || {};
  const progressPct = progress.total ? Math.round((progress.processed / progress.total) * 100) : 0;
  const watchingCount = useMemo(() => (run?.results || []).filter((item) => item.status === 'WATCHING').length, [run?.results]);
  const running = Boolean(run && ACTIVE.has(run.status));
  const openAnalysis = (row) => {
    const child = window.open(`/stock-analysis?code=${encodeURIComponent(row.code)}`, '_blank', 'noopener,noreferrer');
    if (child) child.opener = null;
  };

  const panel = { background: 'var(--bg-card)', borderColor: 'var(--border-color)' };
  const input = { background: 'var(--bg-surface)', borderColor: 'var(--border-color)', color: 'var(--text-primary)' };

  return (
    <div className="flex h-screen min-h-0 flex-col gap-2 p-3 text-sm" style={{ color: 'var(--text-primary)' }}>
      {error && <div className="rounded border px-3 py-2 text-sm" style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)', background: 'color-mix(in srgb, var(--accent-red) 8%, var(--bg-card))' }}>{error}</div>}

      {/* 顶部：标题 + 密钥按钮（弹窗输入） */}
      <header className="flex shrink-0 flex-wrap items-center gap-3 border-b pb-2" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex items-baseline gap-2">
          <h1 className="text-lg font-bold">回马枪选股器</h1>
          <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>v1.1.6 live.2 · 全池结构评分</span>
          {run && <StatusBadge status={run.status} />}
          {run?.mode === 'historical_live' && (
            <span className="rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ color: '#f59e0b', borderColor: '#f59e0b' }}>历史结构 · 当前行情</span>
          )}
          {run?.mode === 'replay' && (
            <span className="rounded-full border px-2 py-0.5 text-[11px] font-semibold" style={{ color: '#f59e0b', borderColor: '#f59e0b' }}>旧版仅形态回放</span>
          )}
        </div>
        <div className="ml-auto flex items-center gap-2">
          <a href="/a-horseback-track" className="rounded border px-3 py-1 text-[11px] no-underline" style={{ borderColor: '#8b5cf6', color: '#8b5cf6' }}>20 日跟踪池</a>
          <span className="text-[11px]" style={{ color: config?.configured ? 'var(--flow-up)' : 'var(--accent-red)' }}>
            {config?.configured ? '密钥已配置' : '尚未配置密钥'}
          </span>
          {config?.source !== 'environment' && (
            <button onClick={() => setTokenModal(true)} className="rounded border px-3 py-1 text-[11px]" style={{ borderColor: 'var(--border-color)' }}>
              {config?.configured ? '更换密钥' : '配置密钥'}
            </button>
          )}
        </div>
      </header>

      {/* 第二行：日期 + 参数 + 操作 + 进度，全部一行内可见 */}
      <div className="flex shrink-0 flex-wrap items-center gap-2 rounded border px-3 py-2 text-[11px]" style={{ borderColor: 'var(--border-color)' }}>
        <span className="flex items-center gap-1">
          <span style={{ color: 'var(--text-muted)' }}>筛选日期</span>
          <input
            type="date"
            max={SHANGHAI_TODAY}
            value={options.end_date}
            onChange={(event) => setOptions({ ...options, end_date: event.target.value })}
            className="w-[112px] rounded border px-1 py-0.5 text-[11px]"
            style={input}
          />
          <span style={{ color: 'var(--text-muted)' }}>
            {options.end_date && options.end_date < SHANGHAI_TODAY ? '（历史结构 + 当前实时确认）' : '（当日实时）'}
          </span>
        </span>
        <span className="hidden h-3 w-px sm:inline-block" style={{ background: 'var(--border-color)' }} />
        <label className="flex items-center gap-1">整理
          <input type="number" min="1" max="15" value={options.min_consolidation_days} onChange={(event) => setOptions({ ...options, min_consolidation_days: Number(event.target.value) })} className="w-12 rounded border px-1 py-0.5 text-[11px]" style={input} />
          ~
          <input type="number" min="2" max="20" value={options.max_consolidation_days} onChange={(event) => setOptions({ ...options, max_consolidation_days: Number(event.target.value) })} className="w-12 rounded border px-1 py-0.5 text-[11px]" style={input} />
          日
        </label>
        <label className="flex items-center gap-1">涨停
          <input type="number" min="1" max="5" value={options.min_limit_count} onChange={(event) => setOptions({ ...options, min_limit_count: Number(event.target.value) })} className="w-10 rounded border px-1 py-0.5 text-[11px]" style={input} />
          ~
          <input type="number" min="1" max="10" value={options.max_limit_count} onChange={(event) => setOptions({ ...options, max_limit_count: Number(event.target.value) })} className="w-10 rounded border px-1 py-0.5 text-[11px]" style={input} />
          次
        </label>
        <label className="flex items-center gap-1">分数≥
          <input type="number" min="50" max="100" value={options.min_score} onChange={(event) => setOptions({ ...options, min_score: Number(event.target.value) })} className="w-12 rounded border px-1 py-0.5 text-[11px]" style={input} />
        </label>
        <label className="flex items-center gap-1" title="先完成全池本地结构评分，再按分数限制需要读取实时行情的形态候选数">实时上限
          <input type="number" min="0" max="1000" value={options.max_candidates} onChange={(event) => setOptions({ ...options, max_candidates: Number(event.target.value) })} className="w-14 rounded border px-1 py-0.5 text-[11px]" style={input} />
        </label>
        <label className="flex items-center gap-1">涨幅≥
          <input type="number" min="0" max="20" step="0.5" value={options.live_rise_pct_min} onChange={(event) => setOptions({ ...options, live_rise_pct_min: Number(event.target.value) })} className="w-12 rounded border px-1 py-0.5 text-[11px]" style={input} />
          %
        </label>
        <label className="flex items-center gap-1">量比≥
          <input type="number" min="0" max="20" step="0.1" value={options.live_volume_ratio_min} onChange={(event) => setOptions({ ...options, live_volume_ratio_min: Number(event.target.value) })} className="w-12 rounded border px-1 py-0.5 text-[11px]" style={input} />
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={options.allow_gem} onChange={(event) => setOptions({ ...options, allow_gem: event.target.checked })} />
          创业板
        </label>
        <label className="flex items-center gap-1">
          <input type="checkbox" checked={options.allow_star} onChange={(event) => setOptions({ ...options, allow_star: event.target.checked })} />
          科创板
        </label>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {run?.as_of_date && <span style={{ color: 'var(--text-muted)' }}>日线截至 {run.as_of_date}</span>}
          {run?.realtime_at && (
            <span style={{ color: run.realtime_at.slice(11, 16) > '15:00' ? 'var(--accent-red)' : 'var(--flow-up)' }}>
              行情 {run.realtime_at.slice(11, 16)} {sessionLabel(run.realtime_at)}
            </span>
          )}
          <button onClick={start} disabled={running || !config?.configured} className="rounded px-3 py-1 text-[11px] font-semibold text-white disabled:opacity-40" style={{ background: 'var(--accent-blue)' }}>{running ? '扫描中…' : options.end_date && options.end_date < SHANGHAI_TODAY ? '启动历史扫描' : '启动实时扫描'}</button>
          {running && <button onClick={cancel} className="rounded border px-2 py-1 text-[11px]" style={{ borderColor: 'var(--accent-red)', color: 'var(--accent-red)' }}>取消</button>}
          {run?.id && (run.results || []).length > 0 && <button onClick={refreshQuotes} disabled={running || !config?.configured} className="rounded border px-2 py-1 text-[11px] disabled:opacity-40" style={{ borderColor: 'var(--border-color)' }}>↻ 刷新实时行情</button>}
          {run?.id && (run.results || []).length > 0 && <a href={`/api/horseback/runs/${run.id}/export.csv`} className="rounded border px-2 py-1 text-[11px] no-underline" style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}>导出 CSV</a>}
        </div>
      </div>

      {/* 进度条：紧凑一行 */}
      {run && (
        <div className="flex shrink-0 flex-wrap items-center gap-3 text-[11px]">
          <span style={{ color: 'var(--text-secondary)' }}>{run.message || '—'}</span>
          <span style={{ color: 'var(--text-muted)' }}>涨停 {progress.source_count || 0} → 池 {progress.pool_count || 0} → 整理淘汰 {progress.prefiltered_count || 0}</span>
          <span style={{ color: 'var(--text-muted)' }}>已评分 {progress.processed || 0}/{progress.total || 0}</span>
          {progress.structure_eligible > 0 && <span style={{ color: '#f59e0b' }}>形态 {progress.structure_eligible}</span>}
          {progress.quote_total > 0 && <span style={{ color: 'var(--text-muted)' }}>行情 {progress.quote_processed || 0}/{progress.quote_total}</span>}
          <span style={{ color: 'var(--flow-up)' }}>入选 {progress.selected || 0}</span>
          {watchingCount > 0 && <span style={{ color: '#f59e0b' }}>待触发 {watchingCount}</span>}
          <div className="ml-2 h-1.5 w-32 overflow-hidden rounded-full" style={{ background: 'var(--bg-hover)' }}>
            <div className="h-full transition-all" style={{ width: `${progressPct}%`, background: 'var(--accent-blue)' }} />
          </div>
          {run.error && <span style={{ color: 'var(--accent-red)' }}>{run.error}</span>}
        </div>
      )}

      <section className="flex min-h-0 flex-1 flex-col rounded-xl border" style={panel}>
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-3 py-2" style={{ borderColor: 'var(--border-color)' }}>
          <b>入选池与观察池</b>
          {['ALL', 'SELECTED', 'WATCHING', 'NOT_SELECTED', 'INVALID'].map((value) => (
            <button key={value} onClick={() => setFilter(value)} className="rounded border px-2 py-0.5 text-[11px]" style={{ borderColor: filter === value ? 'var(--accent-blue)' : 'var(--border-color)', color: filter === value ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
              {value === 'ALL' ? '全部' : STATUS_LABEL[value]}
            </button>
          ))}
          <span className="ml-auto text-[11px]" style={{ color: 'var(--text-muted)' }}>
            入选须形态达标、实时涨幅&gt;{options.live_rise_pct_min}%、实时量比≥{options.live_volume_ratio_min}，且当日首次站上 MA5；<b style={{ color: '#f59e0b' }}>待触发</b>=形态达标等待盘中确认
          </span>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto">
          <table className="w-full table-auto text-left text-xs">
            <thead className="sticky top-0 z-10" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
              <tr>{['池', '分数', '股票', '最近涨停', '日线收盘', '实时行情', '今日入选条件', '结构指标', '触发价', '止损价', '失分项', '操作'].map((label) => <th key={label} className="whitespace-nowrap px-2 py-2 font-medium">{label}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.ts_code} className="border-t align-top" style={{ borderColor: 'var(--border-light)' }}>
                  <td className="px-2 py-2"><StatusBadge status={row.status} /></td>
                  <td className="px-2 py-2 text-base font-bold" style={{ color: row.status === 'SELECTED' ? 'var(--flow-up)' : 'var(--text-primary)' }}>{row.score ?? '—'}</td>
                  <td className="px-2 py-2"><b>{row.name}</b><div style={{ color: 'var(--text-muted)' }}>{row.ts_code}{row.limit_up_count == null ? '' : ` · ${row.leader ? '龙头' : '涨停'}×${row.limit_up_count}`}</div></td>
                  <td className="whitespace-nowrap px-2 py-2">{row.last_limit_date?.slice(5) || '—'}<div style={{ color: 'var(--text-muted)' }}>{row.days_since_limit == null ? '' : `距今 ${row.days_since_limit} 日`}</div></td>
                  <td className="whitespace-nowrap px-2 py-2">{num(row.close)}<div style={{ color: 'var(--text-muted)' }}>MA5 {num(row.ma5)}</div></td>
                  <td className="whitespace-nowrap px-2 py-2">{num(row.realtime_price)} <span style={{ color: Number(row.realtime_change_pct) >= 0 ? 'var(--flow-up)' : 'var(--flow-down)' }}>{pct(row.realtime_change_pct)}</span><div style={{ color: 'var(--text-muted)' }}>量比 {num(row.realtime_volume_ratio)} · {row.realtime_at ? `${row.realtime_at.slice(11, 16)} ${sessionLabel(row.realtime_at)}` : '—'}</div><div style={{ color: row.first_ma5_break ? 'var(--flow-up)' : 'var(--text-muted)' }}>首上MA5 {row.first_ma5_break ? '是' : '否'} {num(row.today_ma5)}</div></td>
                  <td className="w-[230px] min-w-[230px] px-2 py-2 text-[11px] leading-[16px]"><div style={{ color: 'var(--text-secondary)' }}>{row.realtime_state || '—'}</div><div style={{ color: 'var(--text-secondary)' }}>{row.realtime_gate || '等待实时行情'}</div></td>
                  <td className="whitespace-nowrap px-2 py-2">{pct(row.pullback_pct)}<div style={{ color: 'var(--text-muted)' }}>量 {num(row.volume_ratio)} · 敛 {pct(row.ma_convergence_pct)}</div></td>
                  <td className="whitespace-nowrap px-2 py-2 font-semibold">{num(row.suggested_buy)}</td>
                  <td className="whitespace-nowrap px-2 py-2" style={{ color: 'var(--accent-red)' }}>{num(row.stop_loss)}</td>
                  <td className="w-[270px] min-w-[270px] px-2 py-2"><ScoreDetails row={row} /></td>
                  <td className="whitespace-nowrap px-2 py-2"><div className="flex gap-1"><button onClick={() => setKlineStock(row)} className="rounded border px-2 py-1" style={{ borderColor: 'var(--border-color)' }}>K线</button><button onClick={() => openAnalysis(row)} className="rounded border px-2 py-1" style={{ borderColor: 'var(--border-color)' }}>分析 ↗</button></div></td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan="12" className="px-4 py-12 text-center" style={{ color: 'var(--text-muted)' }}>{run ? '暂无符合当前筛选的结果' : '配置密钥后启动第一次实时扫描'}</td></tr>}
            </tbody>
          </table>
        </div>
        <div className="shrink-0 border-t px-3 py-1.5 text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
          数据口径：先对符合涨停次数与整理日条件的全池读取本地日线并评分，“实时上限”仅限制形态达标后需要向 iFinD 请求行情的数量；选择过去日期时，涨停池与结构评分严格截止到该日，但最终入选使用启动或刷新时的当前实时行情，属于 v1.1.5 历史扫描兼容模式，不是历史回测；默认仅沪深主板，可勾选纳入创业板/科创板（20cm 回撤下限自适应放宽）；十日涨停池任一交易日缺失会使本次扫描失败，盘后当日日线覆盖不足会回退上一完整交易日，少于 63 根日线标为“数据无效”，实时行情缺失留在“待触发/观察池”，不用默认值补齐。
        </div>
      </section>

      {klineStock && run?.id && <KlineModal runId={run.id} stock={klineStock} onClose={() => setKlineStock(null)} />}

      {tokenModal && (
        <div className="fixed inset-0 z-[110] flex items-center justify-center bg-black/55 p-5" onMouseDown={() => !saving && setTokenModal(false)}>
          <div className="w-full max-w-lg rounded-xl border shadow-2xl" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }} onMouseDown={(event) => event.stopPropagation()}>
            <div className="flex items-center justify-between border-b px-4 py-3" style={{ borderColor: 'var(--border-color)' }}>
              <b>{config?.configured ? '更换 iFinD MCP 密钥' : '配置 iFinD MCP 密钥'}</b>
              <button className="rounded border px-2 py-0.5 text-[11px]" style={{ borderColor: 'var(--border-color)' }} onClick={() => !saving && setTokenModal(false)}>关闭</button>
            </div>
            <div className="p-4 text-[12px]">
              <p className="mb-2" style={{ color: 'var(--text-secondary)' }}>粘贴五段式 iFinD JWE 密钥，保存后不会回显，只写入运行 9000 的这台 Mac，权限为仅当前用户可读。</p>
              <textarea
                autoFocus
                autoComplete="new-password"
                value={token}
                onChange={(event) => setToken(event.target.value)}
                placeholder="eyJhbGciOiJFUzI1NiIs....（五段式 JWE）"
                rows={5}
                className="w-full rounded border px-3 py-2 font-mono text-[12px]"
                style={input}
              />
              <div className="mt-3 flex items-center justify-end gap-2">
                <button onClick={() => { setToken(''); setTokenModal(false); }} disabled={saving} className="rounded border px-3 py-1 text-[11px]" style={{ borderColor: 'var(--border-color)' }}>清空</button>
                <button
                  onClick={async () => { const ok = await saveToken(); if (ok) setTokenModal(false); }}
                  disabled={!token.trim() || saving}
                  className="rounded px-4 py-1 text-[11px] font-semibold text-white disabled:opacity-40"
                  style={{ background: 'var(--accent-blue)' }}
                >{saving ? '保存中…' : '保存'}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
