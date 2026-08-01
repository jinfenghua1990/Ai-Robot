import { useCallback, useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { apiFetch } from '../../utils/request';

export default function ResearchSectorsPage() {
  const { key } = useParams();
  const [data, setData] = useState(null); const [loading, setLoading] = useState(true); const [error, setError] = useState('');
  const load = useCallback(async () => {
    setLoading(true); setError('');
    const [industry, overview, radar] = await Promise.all([
      apiFetch('/api/research-workspace/industry?top=30', {}, 15000, 1),
      apiFetch('/api/research-workspace/market/overview', {}, 12000, 1),
      apiFetch('/api/research-workspace/radar', {}, 12000, 1),
    ]);
    setData({ industry: industry.ok ? industry.data?.data || industry.data : null, overview: overview.ok ? overview.data?.data || overview.data : null, radar: radar.ok ? radar.data?.data || radar.data : null });
    if (!industry.ok && !overview.ok && !radar.ok) setError('板块数据暂时不可用');
    setLoading(false);
  }, []);
  useEffect(() => { load(); }, [load]);
  if (loading) return <div className="p-8 text-center text-xs" style={{ color: 'var(--text-muted)' }}>正在读取板块数据…</div>;
  const groups = data?.radar?.industries || []; const selected = key ? groups.find(group => group.key === key) : null;
  const sectors = data?.industry?.sectors || data?.industry?.industries || data?.overview?.sectors || [];
  return <div className="space-y-3 fade-in"><Head title={selected ? selected.name : '板块中心'} subtitle="行业强度、资讯主题和市场板块数据统一展示" refresh={load} />{error && <Notice text={error} />}<div className="grid grid-cols-1 gap-3 xl:grid-cols-3"><Panel title="行业强弱排名" className="xl:col-span-2"><div className="grid grid-cols-1 gap-x-5 md:grid-cols-2">{sectors.slice(0, 30).map((item, i) => <div key={item.code || item.name || i} className="flex items-center justify-between border-b py-1.5 text-xs" style={{ borderColor: 'var(--border-color)' }}><span><b className="mr-1.5" style={{ color: 'var(--text-muted)' }}>#{i + 1}</b>{item.name || item.industry || item.sector || '—'}</span><span style={{ color: Number(item.change_pct ?? item.change ?? item.pct) >= 0 ? '#ef4444' : '#22c55e' }}>{fmtPct(item.change_pct ?? item.change ?? item.pct)}</span></div>)}{!sectors.length && <Empty />}</div></Panel><Panel title="主题导航"><div className="flex flex-wrap gap-1.5">{groups.map(group => <a key={group.key} href={`/research/sectors/${group.key}`} className="rounded border px-2 py-1.5 text-xs no-underline" style={{ borderColor: group.key === key ? 'var(--accent-blue)' : 'var(--border-color)', color: group.key === key ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>{group.name}<span className="ml-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>{group.total ?? group.items?.length ?? 0}</span></a>)}{!groups.length && <Empty />}</div>{selected && <div className="mt-3 space-y-1">{(selected.items || []).slice(0, 8).map((item, i) => <a key={`${item.title}-${i}`} href={item.url || '#'} target="_blank" rel="noreferrer" className="block border-b py-1.5 text-xs no-underline" style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}>{item.title}</a>)}</div>}</Panel></div><Panel title="使用说明"><div className="text-xs leading-6" style={{ color: 'var(--text-secondary)' }}>行业排名用于观察强弱，主题资讯用于解释变化；两者都不直接替代右侧多因子评分。点击主题可查看对应资讯，点击顶部“刷新”重新读取。</div></Panel></div>;
}
function Head({ title, subtitle, refresh }) { return <div className="flex items-center justify-between gap-2"><div><div className="text-xs" style={{ color: 'var(--text-muted)' }}>研究工作区</div><h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{title}</h2><div className="text-xs" style={{ color: 'var(--text-muted)' }}>{subtitle}</div></div><button onClick={refresh} className="rounded border px-2.5 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button></div>; }
function Panel({ title, children, className = '' }) { return <section className={`rounded-lg border p-3 ${className}`} style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><h3 className="mb-2 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{title}</h3>{children}</section>; }
function Empty() { return <div className="py-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无数据</div>; }
function Notice({ text }) { return <div className="rounded border px-3 py-2 text-xs" style={{ borderColor: '#f59e0b66', background: '#f59e0b12', color: '#b45309' }}>{text}</div>; }
function fmtPct(v) { if (v == null || Number.isNaN(Number(v))) return '—'; const n = Number(v); return `${n > 0 ? '+' : ''}${n.toFixed(2)}%`; }
