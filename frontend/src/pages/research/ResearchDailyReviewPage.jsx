import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../../utils/request';

export default function ResearchDailyReviewPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setLoading(true); setError('');
    const requests = [
      ['overview', '/api/research-workspace/market/overview'],
      ['emotion', '/api/research-workspace/market/emotion'],
      ['turnover', '/api/research-workspace/market/turnover-top'],
      ['radar', '/api/research-workspace/radar'],
      ['global', '/api/research-workspace/global/indices'],
    ];
    const results = await Promise.all(requests.map(async ([key, url]) => [key, await apiFetch(url, {}, 12000, 1)]));
    const next = Object.fromEntries(results.map(([key, result]) => [key, result.ok ? result.data?.data || result.data : null]));
    if (!Object.values(next).some(Boolean)) setError('今日复盘暂时没有可用数据');
    setData(next); setLoading(false);
  }, []);

  useEffect(() => { load(); }, [load]);
  if (loading) return <WorkspaceLoading text="正在生成每日复盘…" />;
  const sentiment = data?.overview?.sentiment || {};
  const emotion = data?.emotion || {};
  const turnover = data?.turnover?.stocks || [];
  const articles = (data?.radar?.industries || []).flatMap(group => (group.items || []).slice(0, 3).map(item => ({ ...item, group: group.name, accent: group.accent }))).slice(0, 12);

  return <div className="space-y-3 fade-in">
    <PageHead title="每日复盘" subtitle="把市场状态、短线情绪、成交主线和资讯放到同一个收盘检查页" onRefresh={load} />
    {error && <Notice text={error} />}
    <div className="grid grid-cols-2 gap-2 md:grid-cols-6">
      <Metric label="市场宽度" value={sentiment.breadth || '—'} />
      <Metric label="上涨家数" value={sentiment.up ?? '—'} tone="up" />
      <Metric label="下跌家数" value={sentiment.down ?? '—'} tone="down" />
      <Metric label="涨停" value={sentiment.zt ?? '—'} tone="up" />
      <Metric label="跌停" value={sentiment.dt ?? '—'} tone="down" />
      <Metric label="最高连板" value={emotion.max_boards ? `${emotion.max_boards}板` : '—'} />
    </div>
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-3">
      <Panel title="今日结论" className="xl:col-span-2">
        <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
          <Conclusion label="市场环境" value={sentiment.breadth || '暂无'} detail={`${sentiment.up ?? '—'} 家上涨 / ${sentiment.down ?? '—'} 家下跌`} />
          <Conclusion label="短线情绪" value={emotion.max_boards ? `${emotion.max_boards}板高度` : '暂无'} detail={`${emotion.lianban_count ?? '—'} 只连板股`} />
          <Conclusion label="交易纪律" value={sentiment.breadth === '偏弱' ? '降低追价' : '等待确认'} detail="复盘结论不直接生成买卖指令" />
        </div>
      </Panel>
      <Panel title="全球背景"><div className="space-y-1.5">{(data?.global || []).slice(0, 8).map(item => <div key={item.key} className="flex justify-between text-xs"><span>{item.name}</span><span style={{ color: item.change_pct >= 0 ? '#ef4444' : '#22c55e' }}>{item.price?.toLocaleString?.() || '—'} · {item.change_pct == null ? '—' : `${item.change_pct > 0 ? '+' : ''}${item.change_pct.toFixed(2)}%`}</span></div>)}</div></Panel>
    </div>
    <div className="grid grid-cols-1 gap-3 xl:grid-cols-2">
      <Panel title="成交额前十"><ResearchTable rows={turnover.slice(0, 10).map((item, i) => [`#${i + 1} ${item.name}`, item.industry || '—', item.pct == null ? '—' : `${item.pct.toFixed(2)}%`])} /></Panel>
      <Panel title="资讯回看"><div className="space-y-1">{articles.map((item, i) => <a key={`${item.title}-${i}`} href={item.url || '#'} target="_blank" rel="noreferrer" className="block border-b py-1.5 no-underline" style={{ borderColor: 'var(--border-color)' }}><div className="text-[10px]" style={{ color: item.accent || 'var(--accent-blue)' }}>{item.group} · {item.time || ''}</div><div className="text-xs" style={{ color: 'var(--text-primary)' }}>{item.title}</div></a>)}{!articles.length && <Empty />}</div></Panel>
    </div>
    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>复盘用于整理证据，不替代因子评分、风险闸门或人工交易确认。</div>
  </div>;
}

function PageHead({ title, subtitle, onRefresh }) { return <div className="flex items-center justify-between gap-2"><div><div className="text-xs" style={{ color: 'var(--text-muted)' }}>研究工作区</div><h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2><div className="text-xs" style={{ color: 'var(--text-muted)' }}>{subtitle}</div></div><button onClick={onRefresh} className="rounded border px-2.5 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button></div>; }
function Panel({ title, children, className = '' }) { return <section className={`rounded-lg border p-3 ${className}`} style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><h3 className="mb-2 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{title}</h3>{children}</section>; }
function Metric({ label, value, tone }) { return <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="mt-1 text-base font-bold" style={{ color: tone === 'up' ? '#ef4444' : tone === 'down' ? '#22c55e' : 'var(--text-primary)' }}>{value}</div></div>; }
function Conclusion({ label, value, detail }) { return <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}><div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="mt-1 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{value}</div><div className="mt-1 text-[10px]" style={{ color: 'var(--text-secondary)' }}>{detail}</div></div>; }
function ResearchTable({ rows }) { if (!rows.length) return <Empty />; return <div className="space-y-1">{rows.map((row, i) => <div key={i} className="grid grid-cols-[1.4fr_1fr_0.6fr] gap-2 border-b py-1.5 text-xs" style={{ borderColor: 'var(--border-color)' }}><span style={{ color: 'var(--text-primary)' }}>{row[0]}</span><span style={{ color: 'var(--text-muted)' }}>{row[1]}</span><span style={{ color: row[2]?.startsWith?.('-') ? '#22c55e' : '#ef4444' }}>{row[2]}</span></div>)}</div>; }
function Empty() { return <div className="py-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无数据</div>; }
function Notice({ text }) { return <div className="rounded border px-3 py-2 text-xs" style={{ borderColor: '#f59e0b66', background: '#f59e0b12', color: '#b45309' }}>{text}</div>; }
function WorkspaceLoading({ text }) { return <div className="rounded-lg border p-8 text-center text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>{text}</div>; }
