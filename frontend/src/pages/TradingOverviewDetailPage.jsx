import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { openStockAnalysis } from '../utils/openStockAnalysis';
import { apiFetch, formatApiError } from '../utils/request';

const C = {
  card: 'var(--bg-card)', surface: 'var(--bg-surface)', primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)', muted: 'var(--text-muted)', border: 'var(--border-color)',
  blue: 'var(--accent-blue)', up: 'var(--flow-up)', down: 'var(--flow-down)', amber: 'var(--accent-amber)',
};

const SECTIONS = {
  alerts: {
    title: '预警中心', icon: '🚨', endpoint: '/api/alerts/recent?hours=168&limit=200',
    subtitle: '查看最近 7 天已入库的数据质量与采集预警。',
  },
  strategies: {
    title: '策略运行与命中', icon: '🎯', endpoint: '/api/strategy-health?days=14',
    subtitle: '查看最近一次策略运行；命中比例不是实盘或回测胜率。',
  },
  signals: {
    title: '信号候选', icon: '⚡', endpoint: '/api/leader/system',
    subtitle: '查看当前已落库的龙头与候选信号，仍需结合个股分析和账户风控。',
  },
};

const alertTone = (level) => {
  if (level === 'critical' || level === 'error') return { color: C.down, bg: 'rgba(220,38,38,0.12)', label: level === 'critical' ? '严重' : '错误' };
  if (level === 'warning') return { color: C.amber, bg: 'rgba(217,119,6,0.12)', label: '警告' };
  return { color: C.blue, bg: 'rgba(44,86,186,0.12)', label: '提示' };
};

const strategyTone = (status) => {
  if (status === 'success') return { color: C.down, bg: 'rgba(216,80,74,0.12)', label: '成功' };
  if (status === 'failed') return { color: C.up, bg: 'rgba(59,154,46,0.12)', label: '失败' };
  if (status === 'never_run') return { color: C.muted, bg: 'rgba(136,135,128,0.12)', label: '未运行' };
  return { color: C.amber, bg: 'rgba(217,119,6,0.12)', label: '运行中' };
};

const num = (value, digits = 0) => value == null || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(digits);
const dateTime = (value) => value ? String(value).replace('T', ' ').slice(0, 16) : '—';

function StatusTag({ tone }) {
  return <span style={{ color: tone.color, background: tone.bg, borderRadius: 6, padding: '2px 7px', fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap' }}>{tone.label}</span>;
}

function Empty({ text = '暂无可展示的数据' }) {
  return <div style={{ padding: '48px 16px', textAlign: 'center', color: C.muted, fontSize: 13 }}>{text}</div>;
}

function AlertList({ alerts }) {
  if (!alerts.length) return <Empty text="最近 7 天没有已入库预警" />;
  return <div style={{ display: 'grid', gap: 10 }}>
    {alerts.map((alert) => {
      const tone = alertTone(alert.level);
      const details = alert.details && typeof alert.details === 'object'
        ? Object.entries(alert.details).filter(([, value]) => value != null && value !== '').slice(0, 4)
        : [];
      return (
        <article key={alert.id} style={{ padding: '14px 16px', border: `1px solid ${C.border}`, borderRadius: 12, background: C.card }}>
          <div style={{ display: 'flex', alignItems: 'flex-start', gap: 10 }}>
            <StatusTag tone={tone} />
            <div style={{ minWidth: 0, flex: 1 }}>
              <div style={{ color: C.primary, fontWeight: 700, fontSize: 14, lineHeight: 1.45 }}>{alert.message || '未提供预警描述'}</div>
              <div style={{ color: C.muted, fontSize: 11, marginTop: 5 }}>{alert.category || '未分类'} · 交易日 {alert.trade_date || '—'} · 记录于 {dateTime(alert.created_at)}</div>
              {details.length > 0 && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 9 }}>
                {details.map(([key, value]) => <span key={key} style={{ color: C.secondary, background: C.surface, borderRadius: 5, padding: '3px 6px', fontSize: 11 }}>{key}: {Array.isArray(value) ? value.join('、') : String(value)}</span>)}
              </div>}
            </div>
          </div>
        </article>
      );
    })}
  </div>;
}

function StrategyList({ data }) {
  const strategies = data?.strategies || [];
  if (!strategies.length) return <Empty text="数据库中没有策略运行记录" />;
  return <>
    <div style={{ marginBottom: 14, padding: '11px 13px', borderRadius: 10, background: 'rgba(217,119,6,0.10)', color: C.secondary, fontSize: 12, lineHeight: 1.55 }}>
      命中比例 = 本次命中数 ÷ 本次候选数，只反映规则筛选强度；不等同于收益率、回测胜率或真实交易胜率。
    </div>
    <div style={{ overflowX: 'auto', border: `1px solid ${C.border}`, borderRadius: 12, background: C.card }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 760, fontSize: 13 }}>
        <thead><tr style={{ color: C.muted, textAlign: 'left', background: C.surface }}>
          {['策略', '最近运行', '状态', '候选', '命中', '命中比例', '耗时', '异常'].map((label) => <th key={label} style={{ padding: '10px 12px', fontWeight: 600, whiteSpace: 'nowrap' }}>{label}</th>)}
        </tr></thead>
        <tbody>{strategies.map((strategy) => {
          const tone = strategyTone(strategy.status);
          const candidates = Number(strategy.candidate_count);
          const hits = Number(strategy.hit_count);
          const ratio = Number.isFinite(candidates) && candidates > 0 && Number.isFinite(hits) ? `${(hits / candidates * 100).toFixed(1)}%` : '—';
          return <tr key={strategy.key} style={{ borderTop: `1px solid ${C.border}` }}>
            <td style={{ padding: '11px 12px', color: C.primary, fontWeight: 700 }}>{strategy.icon} {strategy.name}</td>
            <td style={{ padding: '11px 12px', color: C.secondary, whiteSpace: 'nowrap' }}>{strategy.trade_date || '未运行'}</td>
            <td style={{ padding: '11px 12px' }}><StatusTag tone={tone} /></td>
            <td style={{ padding: '11px 12px', color: C.secondary }}>{num(strategy.candidate_count)}</td>
            <td style={{ padding: '11px 12px', color: C.primary, fontWeight: 700 }}>{num(strategy.hit_count)}</td>
            <td style={{ padding: '11px 12px', color: C.secondary }}>{ratio}</td>
            <td style={{ padding: '11px 12px', color: C.secondary }}>{strategy.duration_seconds == null ? '—' : `${num(strategy.duration_seconds, 1)} 秒`}</td>
            <td style={{ padding: '11px 12px', color: strategy.error_msg ? C.down : C.muted, maxWidth: 260 }}>{strategy.error_msg || '—'}</td>
          </tr>;
        })}</tbody>
      </table>
    </div>
  </>;
}

function SignalCard({ item, main = false }) {
  if (!item) return null;
  const up = Number(item.change_rate) >= 0;
  return <article style={{ padding: '15px 16px', border: `1px solid ${C.border}`, borderRadius: 12, background: C.card }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
      <div>
        <div style={{ color: C.primary, fontSize: main ? 17 : 15, fontWeight: 800 }}>{main ? '主龙 · ' : ''}{item.secName || item.name || item.secCode}</div>
        <div style={{ color: C.muted, fontSize: 11, marginTop: 3 }}>{item.secCode || item.code} · {item.sector || '板块数据不足'}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: item.signalColor || C.blue, fontSize: 12, fontWeight: 700 }}>{item.signalLabel || item.signal || '观察'}</div>
        <div style={{ color: up ? C.up : C.down, fontSize: 15, fontWeight: 800, marginTop: 3 }}>{item.change_rate == null ? '—' : `${up ? '+' : ''}${num(item.change_rate, 2)}%`}</div>
      </div>
    </div>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 7, marginTop: 12 }}>
      {[['综合评分', num(item.score, 0)], ['风险等级', item.riskLevel || '—'], ['阶段', item.lifecycleStage || item.stage || '—']].map(([label, value]) => <div key={label} style={{ background: C.surface, borderRadius: 8, padding: '7px 8px' }}><div style={{ color: C.muted, fontSize: 10 }}>{label}</div><div style={{ color: C.primary, fontSize: 13, fontWeight: 700, marginTop: 2 }}>{value}</div></div>)}
    </div>
    {item.reasons?.[0] && <div style={{ color: C.secondary, fontSize: 12, lineHeight: 1.5, marginTop: 10 }}>{item.reasons[0]}</div>}
    <button onClick={() => openStockAnalysis(item.secCode || item.code)} style={{ marginTop: 12, padding: '6px 10px', color: C.blue, border: `1px solid ${C.blue}`, borderRadius: 7, background: 'transparent', fontSize: 12, cursor: 'pointer' }}>查看个股分析 →</button>
  </article>;
}

function SignalList({ data }) {
  const candidates = data?.candidates || [];
  return <>
    {data?.switch_warning && <div style={{ marginBottom: 14, padding: '11px 13px', borderRadius: 10, background: 'rgba(217,119,6,0.10)', color: C.secondary, fontSize: 12 }}>{data.switch_warning.reason || '检测到主龙切换风险'}</div>}
    {data?.leader && <div style={{ marginBottom: 14 }}><SignalCard item={data.leader} main /></div>}
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, margin: '18px 0 10px' }}><h2 style={{ margin: 0, color: C.primary, fontSize: 16 }}>候选信号</h2><span style={{ color: C.muted, fontSize: 12 }}>{candidates.length} 只</span></div>
    {candidates.length ? <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>{candidates.map((item) => <SignalCard key={item.secCode || item.code} item={item} />)}</div> : <Empty text="当前没有可展示的候选信号" />}
  </>;
}

export default function TradingOverviewDetailPage() {
  const { section } = useParams();
  const navigate = useNavigate();
  const config = SECTIONS[section];
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    if (!config) return;
    setLoading(true);
    setError('');
    const result = await apiFetch(config.endpoint, {}, 12000, 0);
    if (!result.ok || result.data?.ok === false) {
      setData(null);
      setError(formatApiError(result.data?.error ?? result.error, '数据库数据暂不可用'));
    } else {
      setData(result.data);
    }
    setLoading(false);
  }, [config]);

  useEffect(() => { load(); }, [load]);

  const body = useMemo(() => {
    if (loading) return <Empty text="正在读取已落库数据…" />;
    if (error) return <Empty text={error} />;
    if (section === 'alerts') return <AlertList alerts={data?.data || []} />;
    if (section === 'strategies') return <StrategyList data={data} />;
    return <SignalList data={data} />;
  }, [data, error, loading, section]);

  if (!config) {
    return <div style={{ padding: 24 }}><Empty text="不存在的预测交易二级页面" /><button onClick={() => navigate('/')} style={{ color: C.blue, background: 'transparent', border: 'none', cursor: 'pointer' }}>返回预测交易总览</button></div>;
  }

  return <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12, marginBottom: 18 }}>
      <div>
        <button onClick={() => navigate('/')} style={{ color: C.blue, background: 'transparent', border: 'none', padding: 0, cursor: 'pointer', fontSize: 12 }}>← 返回预测交易总览</button>
        <h1 style={{ margin: '8px 0 4px', fontSize: 22, fontWeight: 800 }}>{config.icon} {config.title}</h1>
        <div style={{ color: C.secondary, fontSize: 13 }}>{config.subtitle}</div>
      </div>
      <button onClick={load} disabled={loading} style={{ color: '#fff', background: C.blue, border: 'none', borderRadius: 9, padding: '8px 14px', cursor: loading ? 'default' : 'pointer', opacity: loading ? 0.7 : 1 }}>{loading ? '读取中…' : '↻ 刷新'}</button>
    </div>
    <nav style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
      {Object.entries(SECTIONS).map(([key, item]) => <button key={key} onClick={() => navigate(`/trading-overview/${key}`)} style={{ border: `1px solid ${key === section ? C.blue : C.border}`, color: key === section ? C.blue : C.secondary, background: key === section ? 'rgba(44,86,186,0.09)' : C.card, borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>{item.icon} {item.title}</button>)}
      <button onClick={() => navigate('/portfolio')} style={{ border: `1px solid ${C.border}`, color: C.secondary, background: C.card, borderRadius: 8, padding: '7px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 600 }}>💼 持仓管理</button>
    </nav>
    {body}
  </div>;
}
