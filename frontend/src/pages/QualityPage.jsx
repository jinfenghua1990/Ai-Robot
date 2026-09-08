import { useState, useEffect, useCallback } from 'react';
import { useSearchParams } from 'react-router-dom';
import ReactECharts from 'echarts-for-react/esm/core';
import echarts from '../lib/echarts';
import { tConfidence, tAction, tSource, tIndicator } from '../utils/i18n';
import { getEastMoneyUrl, getTHSUrl, getStockUrl, getTencentUrl } from '../utils/stockLink';
import { apiFetch } from '../utils/request';
import { POLL_INTERVAL } from '../utils/constants';
import MonitorRulesPage from './MonitorRulesPage';

// 服务状态语义（与 HealthStrip 一致）
const SERVICE_STATUS_META = {
  up:   { text: '运行中', color: 'var(--accent-green)' },
  down: { text: '离线',   color: 'var(--accent-red)' },
  ready:{ text: '就绪',   color: 'var(--accent-amber)' },
  idle: { text: '待命',   color: 'var(--accent-amber)' },
};

const QUALITY_MARKETS = [
  { id: 'all', label: '全市场', code: 'ALL' },
  { id: 'a', label: 'A股', code: 'CN' },
  { id: 'hk', label: '港股', code: 'HK' },
  { id: 'us', label: '美股', code: 'US' },
];

const QUALITY_SECTIONS = [
  { id: 'quality', label: '数据质量' },
  { id: 'risk', label: '系统风控' },
  { id: 'monitor', label: '监控规则' },
];

function QualityHubHeader({ market, section }) {
  const marketLabel = QUALITY_MARKETS.find(item => item.id === market)?.label || '全市场';
  const href = (nextMarket, nextSection = section) => {
    const query = new URLSearchParams();
    if (nextMarket !== 'all') query.set('market', nextMarket);
    if (nextSection !== 'quality') query.set('section', nextSection);
    const value = query.toString();
    return value ? `/quality?${value}` : '/quality';
  };
  return (
    <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div>
          <h2 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>🛡️ 系统与数据质量中心</h2>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>统一入口 · {marketLabel} · 数据质量、系统风控、监控规则</div>
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          {QUALITY_MARKETS.map(item => (
            <a key={item.id} href={href(item.id)} className="no-underline px-2 py-1 rounded-md text-xs border"
              style={{ borderColor: market === item.id ? 'var(--accent-blue)' : 'var(--border-color)', background: market === item.id ? 'rgba(59,130,246,0.1)' : 'transparent', color: market === item.id ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>
              {item.label}
            </a>
          ))}
          <span className="mx-0.5 h-4 w-px" style={{ background: 'var(--border-color)' }} />
          {QUALITY_SECTIONS.map(item => (
            <a key={item.id} href={href(market, item.id)} className="no-underline px-2 py-1 rounded-md text-xs"
              style={{ background: section === item.id ? 'var(--accent-blue)' : 'transparent', color: section === item.id ? '#fff' : 'var(--text-secondary)' }}>
              {item.label}
            </a>
          ))}
        </div>
      </div>
    </div>
  );
}

function statusMeta(status) {
  const value = String(status || 'NOT_READY').toUpperCase();
  if (value === 'SUCCESS' || value === 'VALID' || value === 'FRESH') return { label: '正常', color: '#22c55e' };
  if (value === 'NOT_READY' || value === 'STALE') return { label: value === 'STALE' ? '需关注' : '待就绪', color: '#f59e0b' };
  return { label: '异常', color: '#ef4444' };
}

function AllMarketsPanel({ mode = 'quality' }) {
  const [state, setState] = useState({ loading: true, services: [], aFreshness: null, hkHealth: null, hkHistory: null, usHealth: null, usHistory: null, usSystem: null });

  const load = useCallback(async () => {
    const results = await Promise.all([
      apiFetch('/api/services/status'),
      apiFetch('/api/quality/data-freshness'),
      apiFetch('/api/market-quant/HK/health?universe=CORE'),
      apiFetch('/api/market-quant/HK/history/status?universe=CORE'),
      apiFetch('/api/market-quant/US/health?universe=CORE'),
      apiFetch('/api/market-quant/US/history/status?universe=CORE'),
      mode === 'risk' ? apiFetch('/api/us-quant/system/status') : Promise.resolve({ ok: false }),
    ]);
    setState({
      loading: false,
      services: results[0].ok ? (results[0].data?.services || []) : [],
      aFreshness: results[1].ok ? results[1].data : null,
      hkHealth: results[2].ok ? results[2].data : null,
      hkHistory: results[3].ok ? results[3].data : null,
      usHealth: results[4].ok ? results[4].data : null,
      usHistory: results[5].ok ? results[5].data : null,
      usSystem: results[6]?.ok ? results[6].data : null,
    });
  }, [mode]);

  useEffect(() => { load(); }, [load]);

  if (state.loading) return <div className="text-center text-xs py-10" style={{ color: 'var(--text-muted)' }}>加载全市场系统状态…</div>;

  const marketRows = [
    {
      id: 'a', label: 'A股',
      status: state.aFreshness?.summary?.overall_status,
      updatedAt: state.aFreshness?.last_trade_day,
      coverage: state.aFreshness?.summary ? `${state.aFreshness.summary.fresh || 0}/${state.aFreshness.summary.total || 0} 数据源最新` : '暂无质量快照',
    },
    {
      id: 'hk', label: '港股',
      status: state.hkHealth?.latest_status,
      updatedAt: state.hkHealth?.latest_trade_date,
      coverage: state.hkHistory ? `历史覆盖 ${state.hkHistory.with_history || 0}/${state.hkHistory.expected || 0}` : '暂无历史覆盖',
    },
    {
      id: 'us', label: '美股',
      status: state.usHealth?.latest_status,
      updatedAt: state.usHealth?.latest_trade_date,
      coverage: state.usHistory ? `历史覆盖 ${state.usHistory.with_history || 0}/${state.usHistory.expected || 0}` : '暂无历史覆盖',
    },
  ];
  const servicesUp = state.services.filter(item => item.status === 'up').length;

  return (
    <div className="space-y-2">
      <div className="rounded-lg border p-2.5 flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>全市场系统总览</h3>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>服务、数据质量与风控统一查看；市场明细在本页内切换</div>
        </div>
        <button onClick={load} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>↻ 刷新</button>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
        {marketRows.map(item => {
          const meta = statusMeta(item.status);
          return (
            <a key={item.id} href={`/quality?market=${item.id}&section=${mode}`} className="rounded-lg border p-2.5 no-underline hover:opacity-80" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{item.label}</span>
                <span className="text-[11px] font-semibold" style={{ color: meta.color }}>{meta.label}</span>
              </div>
              <div className="text-[11px] mt-2" style={{ color: 'var(--text-secondary)' }}>{item.coverage}</div>
              <div className="text-[10px] mt-1" style={{ color: 'var(--text-muted)' }}>最近交易日：{item.updatedAt || '—'} · 查看明细 →</div>
            </a>
          );
        })}
      </div>

      <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 公共服务状态</h3>
          <span className="text-[10px]" style={{ color: servicesUp === state.services.length && state.services.length ? '#22c55e' : '#f59e0b' }}>{state.services.length ? `${servicesUp}/${state.services.length} 在线` : '暂无服务状态'}</span>
        </div>
        <div className="p-2 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
          {state.services.length === 0 ? <span className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无服务状态数据</span> : state.services.map(service => {
            const meta = SERVICE_STATUS_META[service.status] || SERVICE_STATUS_META.idle;
            return <div key={service.key} className="rounded-md border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
              <div className="flex items-center justify-between gap-2"><span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>{service.label}</span><span className="text-[10px] font-medium" style={{ color: meta.color }}>{meta.text}</span></div>
              <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{service.detail}</div>
            </div>;
          })}
        </div>
      </div>

      {mode === 'risk' && (
        <div className="rounded-lg border p-2.5 text-xs" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-secondary)' }}>
          <div className="font-bold mb-1" style={{ color: 'var(--text-primary)' }}>🔐 全市场风控说明</div>
          <div>数据质量和交易规则按市场独立校验；美股当前为 {state.usSystem?.allow_live ? '实盘已开启' : '实盘关闭'}，其余市场请在本页切换后查看对应状态。</div>
        </div>
      )}

      <USSystemPanel />
      <GoogleSheetsSyncPanel />
    </div>
  );
}

function USSystemPanel() {
  const [state, setState] = useState({ loading: true, overview: null, status: null });

  const load = useCallback(async () => {
    const [overview, status] = await Promise.all([
      apiFetch('/api/us-quant/overview', {}, 15000),
      apiFetch('/api/us-quant/system/status', {}, 10000),
    ]);
    setState({
      loading: false,
      overview: overview.ok ? overview.data : null,
      status: status.ok ? status.data : null,
    });
  }, []);

  useEffect(() => { load(); }, [load]);

  if (state.loading) return <div className="text-center text-xs py-6" style={{ color: 'var(--text-muted)' }}>加载美股系统状态…</div>;

  const overview = state.overview || {};
  const status = state.status || overview.system || {};
  const scan = status.last_scan || overview.scan || {};
  const regime = overview.regime;
  const quality = overview.data_quality || {};
  const modeLabel = { SHADOW: '影子模式', LIVE: '实盘模式', PAPER: '模拟模式' };
  const qualityOk = quality.status === 'VALID';
  const scanOk = scan.status === 'SUCCESS';
  const riskItems = [
    { label: '行情质量', value: qualityOk ? '正常' : quality.status === 'PENDING' ? '评估中' : '数据不足', color: qualityOk ? '#22c55e' : '#f59e0b', note: quality.message || '—' },
    { label: '数据延迟', value: status.live ? '实时在线' : '离线/延迟', color: status.live ? '#22c55e' : '#ef4444', note: overview.updated_at ? `最近更新 ${String(overview.updated_at).slice(0, 19)}` : '—' },
    { label: '券商连接', value: status.mode === 'SHADOW' ? '影子模式·无实盘' : (status.broker || '—'), color: status.mode === 'SHADOW' ? '#f59e0b' : '#22c55e', note: status.proxy ? `代理 ${status.proxy}` : '直连' },
    { label: '盘后扫描', value: scanOk ? '成功' : (scan.status || '未执行'), color: scanOk ? '#22c55e' : '#f59e0b', note: scan.trade_date ? `${scan.trade_date} · 扫描 ${scan.scanned_count || 0} 只` : '—' },
    { label: '实盘权限', value: status.allow_live ? '开启' : '关闭', color: status.allow_live ? '#ef4444' : '#22c55e', note: status.allow_live ? '请确认交易风控' : '当前为安全模式' },
    { label: '账户熔断', value: status.allow_live ? '未触发' : '监控关闭', color: status.allow_live ? '#22c55e' : '#94a3b8', note: status.allow_live ? '实盘风控有效' : '实盘关闭时不执行成交熔断' },
  ];

  return (
    <div className="space-y-2">
      <div className="rounded-lg border p-2.5 flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div>
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 美股运行与风控</h3>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>由统一系统中心承载，不再单独维护美股系统页</div>
        </div>
        <button onClick={load} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>↻ 刷新</button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
        {[
          ['运行模式', modeLabel[status.mode] || status.mode || '—', status.allow_live ? '允许实盘' : '实盘关闭'],
          ['数据源', status.data_provider || '—', status.live ? '实时行情 ✓' : '延迟行情'],
          ['交易账户', status.broker || '—', status.proxy ? `代理 ${status.proxy}` : '直连'],
          ['最近扫描', scan.candidate_count ?? '—', scan.trade_date ? `${scan.trade_date} · ${scan.pool_source || '统一股票池'}` : '暂无'],
        ].map(([label, value, sub]) => (
          <div key={label} className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
            <div className="text-base font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{value}</div>
            <div className="text-[10px] mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h4 className="text-xs font-bold mb-2" style={{ color: 'var(--text-primary)' }}>🔐 风险开关（实时）</h4>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
            {riskItems.map(item => (
              <div key={item.label} className="rounded-md p-2" style={{ background: 'var(--bg-hover)' }}>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{item.label}</span>
                  <span className="text-[11px] font-bold" style={{ color: item.color }}>● {item.value}</span>
                </div>
                <div className="text-[10px] mt-0.5 truncate" style={{ color: 'var(--text-muted)' }}>{item.note}</div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h4 className="text-xs font-bold mb-2" style={{ color: 'var(--text-primary)' }}>🌡️ 市场环境</h4>
          {regime ? (
            <>
              <div className="flex items-center gap-3">
                <span className="text-xl font-bold" style={{ color: regime.allow_new_positions ? '#22c55e' : '#f59e0b' }}>{regime.label || regime.regime || '—'}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>评分 {regime.score ?? '—'}</span>
              </div>
              <div className="text-xs mt-2 leading-5" style={{ color: 'var(--text-secondary)' }}>{regime.reason || '暂无环境说明'}</div>
              <div className="text-xs font-bold mt-2" style={{ color: regime.allow_new_positions ? '#22c55e' : '#ef4444' }}>{regime.allow_new_positions ? '✅ 允许开新仓' : '❌ 暂缓开新仓'}</div>
            </>
          ) : <div className="text-xs" style={{ color: 'var(--text-muted)' }}>暂无市场环境数据</div>}
        </div>
      </div>
    </div>
  );
}

function GoogleSheetsSyncPanel() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState(null);
  const [busy, setBusy] = useState('');
  const [message, setMessage] = useState('');

  const loadStatus = useCallback(async () => {
    const res = await apiFetch('/api/google-sheets/status', {}, 10000, 1);
    if (res.ok) setStatus(res.data?.data || null);
    else setMessage(res.error || '读取 Google Sheets 状态失败');
  }, []);

  useEffect(() => { loadStatus(); }, [loadStatus]);

  useEffect(() => {
    const result = params.get('google');
    if (result === 'connected') setMessage('Google 授权成功，请点击“立即同步”写入表格');
    if (result === 'error') setMessage(params.get('message') || 'Google 授权失败');
  }, [params]);

  const connect = async () => {
    setBusy('connect'); setMessage('正在打开 Google 授权…');
    const res = await apiFetch('/api/google-sheets/oauth/start', {}, 10000, 0);
    setBusy('');
    if (res.ok && res.data?.auth_url) window.location.assign(res.data.auth_url);
    else setMessage(res.error || '无法开始 Google 授权');
  };

  const sync = async () => {
    setBusy('sync'); setMessage('正在同步四个页签…');
    const res = await apiFetch('/api/google-sheets/sync', { method: 'POST' }, 60000, 0);
    setBusy('');
    if (res.ok && res.data?.ok) {
      setMessage(`同步完成：自选 ${res.data.counts?.自选 ?? 0} 行 · 持仓 ${res.data.counts?.持仓 ?? 0} 行 · 指标 ${res.data.counts?.指标 ?? 0} 行 · 信号 ${res.data.counts?.信号 ?? 0} 行`);
      await loadStatus();
    } else setMessage(res.error || res.data?.error || '同步失败');
  };

  const disconnect = async () => {
    if (!window.confirm('确定断开 Google Sheets？本机保存的授权文件会被删除。')) return;
    setBusy('disconnect');
    const res = await apiFetch('/api/google-sheets/disconnect', { method: 'POST' }, 15000, 0);
    setBusy('');
    if (res.ok) { setMessage('已断开 Google Sheets'); await loadStatus(); }
    else setMessage(res.error || '断开失败');
  };

  return (
    <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📄 Google Sheets 同步</h3>
        <span className="text-[11px]" style={{ color: status?.connected ? '#22c55e' : 'var(--text-muted)' }}>{status?.connected ? '● 已连接' : '○ 未连接'}</span>
      </div>
      <div className="flex items-center gap-2 flex-wrap text-[11px] mt-1.5" style={{ color: 'var(--text-secondary)' }}>
        <span>自选 · 持仓 · RSI/MACD/KDJ/BS · 美股信号</span>
        {!status?.configured && <span style={{ color: '#f59e0b' }}>需先配置 Google OAuth 凭据</span>}
        {status?.last_sync && <span style={{ color: 'var(--text-muted)' }}>上次同步 {status.last_sync}</span>}
        {status?.last_error && <span style={{ color: '#ef4444' }} title={status.last_error}>上次失败：{status.last_error}</span>}
      </div>
      {message && <div className="text-[11px] mt-1.5" style={{ color: message.includes('失败') ? '#ef4444' : 'var(--text-secondary)' }}>{message}</div>}
      <div className="flex gap-1.5 flex-wrap mt-2">
        {!status?.connected && <button onClick={connect} disabled={busy === 'connect' || !status?.configured} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)', background: 'transparent' }}>{busy === 'connect' ? '打开中…' : '连接 Google Sheets'}</button>}
        {status?.connected && <button onClick={sync} disabled={busy === 'sync'} className="px-2 py-1 rounded text-[11px]" style={{ border: 0, color: '#fff', background: 'var(--accent-blue)' }}>{busy === 'sync' ? '同步中…' : '立即同步'}</button>}
        {status?.spreadsheet_url && <a href={status.spreadsheet_url} target="_blank" rel="noreferrer" className="no-underline px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>打开表格 ↗</a>}
        <a href="/api/google-sheets/export.csv?sheet=自选" download className="no-underline px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>下载自选 CSV</a>
        {status?.connected && <button onClick={disconnect} disabled={busy === 'disconnect'} className="px-2 py-1 rounded border text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)', background: 'transparent' }}>{busy === 'disconnect' ? '处理中…' : '断开'}</button>}
      </div>
      {!status?.configured && <div className="text-[10px] mt-2 leading-5" style={{ color: 'var(--text-muted)' }}>在项目根目录 .env 配置 GOOGLE_SHEETS_CLIENT_ID、GOOGLE_SHEETS_CLIENT_SECRET；回调地址：{status?.redirect_uri || 'http://127.0.0.1:9000/api/google-sheets/oauth/callback'}</div>}
    </div>
  );
}

function MarketScopePicker({ section }) {
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>监控规则按市场管理</h3>
      <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>规则、交易时段和证券代码格式属于市场维度；仍在同一系统中心内，选择市场后即可维护规则与查看触发记录。</p>
      <div className="flex gap-2 flex-wrap mt-3">
        {QUALITY_MARKETS.filter(item => item.id !== 'all').map(item => (
          <a key={item.id} href={`/quality?market=${item.id}&section=${section}`} className="no-underline px-3 py-1.5 rounded-md border text-xs font-medium" style={{ borderColor: 'var(--border-color)', color: 'var(--accent-blue)' }}>管理{item.label}规则 →</a>
        ))}
      </div>
    </div>
  );
}

function MarketQualityPanel({ market, mode = 'quality' }) {
  const [state, setState] = useState({ loading: true, health: null, history: null, snapshot: null, overview: null, freshness: null, services: [], system: null });

  const load = useCallback(async () => {
    const isA = market === 'a';
    const requests = isA ? [
      apiFetch('/api/quality/overview'),
      apiFetch('/api/quality/data-freshness'),
      apiFetch('/api/services/status'),
    ] : [
      apiFetch(`/api/market-quant/${market.toUpperCase()}/health?universe=CORE`),
      apiFetch(`/api/market-quant/${market.toUpperCase()}/history/status?universe=CORE`),
      apiFetch(`/api/market-quant/${market.toUpperCase()}/snapshot?universe=CORE&limit=1`),
      apiFetch('/api/services/status'),
      market === 'us' && mode === 'risk' ? apiFetch('/api/us-quant/system/status') : Promise.resolve({ ok: false }),
    ];
    const results = await Promise.all(requests);
    if (isA) {
      setState({ loading: false, overview: results[0].ok ? results[0].data : null, freshness: results[1].ok ? results[1].data : null, services: results[2].ok ? (results[2].data?.services || []) : [], health: null, history: null, snapshot: null, system: null });
    } else {
      setState({ loading: false, health: results[0].ok ? results[0].data : null, history: results[1].ok ? results[1].data : null, snapshot: results[2].ok ? results[2].data : null, services: results[3].ok ? (results[3].data?.services || []) : [], system: results[4]?.ok ? results[4].data : null, overview: null, freshness: null });
    }
  }, [market, mode]);

  useEffect(() => { load(); }, [load]);

  const label = QUALITY_MARKETS.find(item => item.id === market)?.label || market;
  const goodServices = state.services.filter(item => item.status === 'up').length;
  const allServices = state.services.length;
  const freshnessStatus = state.freshness?.summary?.overall_status;
  const healthStatus = state.health?.latest_status || state.snapshot?.status
    || (freshnessStatus === 'fresh' ? 'VALID' : freshnessStatus === 'error' ? 'ERROR' : freshnessStatus ? 'STALE' : 'NOT_READY');
  const statusColor = healthStatus === 'SUCCESS' || healthStatus === 'VALID' ? '#22c55e' : healthStatus === 'NOT_READY' ? '#facc15' : '#ef4444';
  const historyRows = state.history?.min_rows || 0;

  if (state.loading) return <div className="text-center text-xs py-10" style={{ color: 'var(--text-muted)' }}>加载{label}系统状态…</div>;

  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>当前市场</div>
          <div className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{label}</div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>数据范围独立核验</div>
        </div>
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>数据状态</div>
          <div className="text-lg font-bold" style={{ color: state.overview ? (state.overview.avg_quality_score >= 70 ? '#22c55e' : '#facc15') : statusColor }}>{state.overview ? `${state.overview.avg_quality_score?.toFixed(1) || '—'} 分` : (healthStatus === 'SUCCESS' ? '正常' : healthStatus)}</div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{state.health?.updated_at || state.snapshot?.trade_date || state.overview?.trade_date || '暂无最新记录'}</div>
        </div>
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>历史日线</div>
          <div className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{state.overview ? (state.overview.total_stocks || 0) : historyRows}</div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{state.overview ? '质量快照股票数' : `最少 ${historyRows} 个交易日`}</div>
        </div>
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>服务状态</div>
          <div className="text-lg font-bold" style={{ color: goodServices === allServices && allServices > 0 ? '#22c55e' : '#facc15' }}>{allServices ? `${goodServices}/${allServices}` : '—'}</div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>在线服务</div>
        </div>
      </div>

      {mode === 'risk' && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-xs font-bold mb-2" style={{ color: 'var(--text-primary)' }}>🔐 {label}风控状态</h3>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-2 text-xs">
            <div><span style={{ color: 'var(--text-muted)' }}>数据可交易：</span><b style={{ color: statusColor }}>{healthStatus === 'SUCCESS' || healthStatus === 'VALID' ? '通过' : '待检查'}</b></div>
            <div><span style={{ color: 'var(--text-muted)' }}>候选池：</span><b style={{ color: 'var(--text-primary)' }}>{state.health?.pool_count ?? state.snapshot?.signals?.length ?? state.overview?.total_stocks ?? '—'}</b></div>
            <div><span style={{ color: 'var(--text-muted)' }}>交易权限：</span><b style={{ color: state.system?.allow_live ? '#facc15' : '#22c55e' }}>{state.system ? (state.system.allow_live ? '实盘已开启' : '实盘关闭') : '按市场数据状态'}</b></div>
          </div>
        </div>
      )}

      <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📡 {label}数据检查</h3>
          <button onClick={load} className="px-2 py-0.5 rounded border text-[10px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
        </div>
        <div className="p-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
          {state.freshness?.sources ? state.freshness.sources.map(item => <div key={item.table || item.name} className="flex justify-between py-1 border-b" style={{ borderColor: 'var(--border-color)' }}><span>{item.name}</span><span style={{ color: item.status === 'fresh' ? '#22c55e' : item.status === 'error' ? '#ef4444' : '#facc15' }}>{item.message || item.status}</span></div>) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
              <span>股票池：{state.health?.pool_count ?? '—'} 只</span>
              <span>快照：{state.snapshot?.signals?.length ?? 0} 条</span>
              <span>历史覆盖：{state.history?.with_history ?? 0}/{state.history?.expected ?? 0} 只</span>
              <span>最近交易日：{state.health?.latest_trade_date || state.snapshot?.trade_date || '—'}</span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function QualityPage() {
  const [searchParams] = useSearchParams();
  const requestedMarket = (searchParams.get('market') || 'all').toLowerCase();
  const market = QUALITY_MARKETS.some(item => item.id === requestedMarket) ? requestedMarket : 'all';
  const requestedSection = searchParams.get('section') || searchParams.get('tab') || 'quality';
  const sectionAliases = { health: 'risk', system: 'risk', rules: 'monitor', monitorRules: 'monitor' };
  const normalizedSection = sectionAliases[requestedSection] || requestedSection;
  const section = QUALITY_SECTIONS.some(item => item.id === normalizedSection) ? normalizedSection : 'quality';
  const [overview, setOverview] = useState(null);
  const [sources, setSources] = useState(null);
  const [dataSources, setDataSources] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [reviewQueue, setReviewQueue] = useState(null);
  const [logs, setLogs] = useState(null);
  const [errorStats, setErrorStats] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [services, setServices] = useState([]);
  const [serviceLoading, setServiceLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchServices = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/services/status');
    if (ok && data && Array.isArray(data.services)) setServices(data.services);
    setServiceLoading(false);
  }, []);

  const fetchAll = useCallback(async () => {
    try {
      const results = await Promise.all([
        apiFetch('/api/quality/overview'),
        apiFetch('/api/quality/sources?days=7'),
        apiFetch('/api/quality/data-sources'),
        apiFetch('/api/quality/anomalies?limit=30'),
        apiFetch('/api/quality/review-queue?status=pending'),
        apiFetch('/api/quality/logs?limit=30'),
        apiFetch('/api/quality/error-stats'),
        apiFetch('/api/quality/data-freshness'),
      ]);
      const [ov, src, ds, anom, review, lg, errs, fresh] = results.map(r => r.ok ? r.data : null);
      setOverview(ov);
      setSources(src);
      setDataSources(ds);
      setAnomalies(anom);
      setReviewQueue(review);
      setLogs(lg);
      setErrorStats(errs);
      setFreshness(fresh);
      setError(null);
    } catch (e) {
      setError('加载失败: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (market === 'a' && section === 'quality') {
      fetchAll();
      fetchServices();
    }
  }, [market, section, fetchAll, fetchServices]);

  useEffect(() => {
    if (market !== 'a' || section !== 'quality') return undefined;
    const interval = setInterval(async () => {
      const { ok, data } = await apiFetch('/api/quality/data-freshness');
      if (ok) setFreshness(data);
    }, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, [market, section]);

  const [selectedValues, setSelectedValues] = useState({});

  const handleReview = async (id, action) => {
    try {
      const finalValue = selectedValues[id] || null;
      const { ok, error } = await apiFetch(`/api/quality/review/${id}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action, final_value: finalValue, reviewer: 'admin' }),
      });
      if (!ok) throw new Error(error);
      setSelectedValues(prev => { const n = {...prev}; delete n[id]; return n; });
      fetchAll();
    } catch (e) {
      setError('审核失败: ' + e.message);
    }
  };

  const calcAuthorityValue = (sourcesData) => {
    if (!sourcesData) return null;
    const values = Object.values(sourcesData).map(d => typeof d === 'object' ? d.value : d).filter(v => v != null);
    if (values.length === 0) return null;
    if (values.length === 1) return Number(values[0]);
    const sorted = [...values].map(Number).sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2 === 0 ? (sorted[mid - 1] + sorted[mid]) / 2 : sorted[mid];
  };

  const confidencePieOption = useCallback(() => {
    if (!overview?.confidence_distribution) return null;
    const dist = overview.confidence_distribution;
    return {
      tooltip: { trigger: 'item', backgroundColor: 'rgba(20,20,20,0.95)', textStyle: { color: '#fff', fontSize: 11 } },
      legend: { bottom: 0, textStyle: { color: 'var(--text-muted)', fontSize: 10 } },
      series: [{
        type: 'pie', radius: ['40%', '70%'], center: ['50%', '45%'],
        label: { color: '#fff', fontSize: 10 },
        data: [
          { value: dist.high || 0, name: '高置信', itemStyle: { color: '#22c55e' } },
          { value: dist.medium || 0, name: '中置信', itemStyle: { color: '#facc15' } },
          { value: dist.low || 0, name: '低置信', itemStyle: { color: '#ef4444' } },
          { value: dist.disputed || 0, name: '争议', itemStyle: { color: '#a78bfa' } },
        ].filter(d => d.value > 0),
      }],
    };
  }, [overview]);

  const sourceBarOption = useCallback(() => {
    if (!sources?.sources) return null;
    const srcs = sources.sources;
    return {
      tooltip: { trigger: 'axis', backgroundColor: 'rgba(20,20,20,0.95)', textStyle: { color: '#fff', fontSize: 10 } },
      grid: { left: 75, right: 30, top: 5, bottom: 15 },
      xAxis: {
        type: 'value', max: 100,
        axisLabel: { color: 'var(--text-muted)', fontSize: 9 },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
      },
      yAxis: {
        type: 'category', inverse: true,
        data: srcs.map(s => tSource(s.source)),
        axisLabel: { color: 'var(--text-secondary)', fontSize: 10 },
        axisLine: { show: false }, axisTick: { show: false },
      },
      series: [{
        type: 'bar', barWidth: '50%',
        data: srcs.map(s => ({
          value: s.avg_score,
          itemStyle: {
            color: s.avg_score >= 70 ? '#22c55e' : s.avg_score >= 50 ? '#facc15' : '#ef4444',
            borderRadius: [0, 3, 3, 0],
          },
        })),
        label: { show: true, position: 'right', color: 'var(--text-muted)', fontSize: 9, formatter: '{c}' },
      }],
    };
  }, [sources]);

  // 港股/美股使用各自 market_quant 数据库快照；不把 A 股质量表伪装成其他市场。
  if (section === 'monitor') {
    return (
      <div className="space-y-2">
        <QualityHubHeader market={market} section={section} />
        {market === 'all' ? <MarketScopePicker section={section} /> : <MonitorRulesPage market={market} embedded />}
      </div>
    );
  }
  if (market === 'all') {
    return (
      <div className="space-y-2">
        <QualityHubHeader market={market} section={section} />
        <AllMarketsPanel mode={section} />
      </div>
    );
  }
  if (market !== 'a' || section === 'risk') {
    return (
      <div className="space-y-2">
        <QualityHubHeader market={market} section={section} />
        <MarketQualityPanel market={market} mode={section} />
        {market === 'us' && section === 'risk' && <USSystemPanel />}
      </div>
    );
  }
  if (loading) return <div className="flex items-center justify-center h-96"><div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div></div>;

  const upCount = services.filter(s => s.status === 'up').length;
  const downCount = services.filter(s => s.status === 'down').length;

  return (
    <div className="space-y-1">
      <QualityHubHeader market={market} section={section} />
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
          A股数据质量明细
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: 'var(--accent-amber)' }}>盘后数据</span>
        </h2>
        <button onClick={() => { fetchAll(); fetchServices(); }} className="px-2 py-1 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
      </div>

      {error && <div className="rounded-lg p-2 text-xs" style={{ background: 'rgba(239,68,68,0.1)', color: 'var(--accent-red)' }}>{error}</div>}

      {/* 服务状态 */}
      <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 服务状态 {services.length ? `(${upCount} 在线 · ${downCount} 离线)` : ''}</h3>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>每 10 秒自动刷新</span>
        </div>
        <div className="p-2">
          {serviceLoading ? (
            <div className="text-center text-xs py-4" style={{ color: 'var(--text-muted)' }}>加载服务状态中...</div>
          ) : services.length === 0 ? (
            <div className="text-center text-xs py-4" style={{ color: 'var(--text-muted)' }}>暂无服务状态数据</div>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-1.5">
              {services.map(s => {
                const m = SERVICE_STATUS_META[s.status] || SERVICE_STATUS_META.idle;
                const clickable = Boolean(s.path);
                const Tag = clickable ? 'a' : 'div';
                return (
                  <Tag key={s.key} href={s.path || undefined}
                    className={`flex items-center gap-2.5 rounded-md border p-2 no-underline ${clickable ? 'hover:opacity-80' : ''}`}
                    style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>
                    <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: m.color, boxShadow: `0 0 6px ${m.color}` }} />
                    <div className="flex-1 min-w-0">
                      <div className="text-xs font-medium truncate">{s.label}</div>
                      <div className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }}>{s.detail}</div>
                    </div>
                    <span className="text-[10px] font-medium shrink-0" style={{ color: m.color }}>{m.text}</span>
                    {clickable && <span className="shrink-0 text-[10px]" style={{ color: 'var(--text-muted)' }}>›</span>}
                  </Tag>
                );
              })}
            </div>
          )}
        </div>
      </div>

      {freshness && <DataFreshnessPanel freshness={freshness} />}

      {overview && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-1.5">
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>平均质量分</div>
            <div className="text-xl font-bold" style={{ color: overview.avg_quality_score >= 70 ? '#22c55e' : overview.avg_quality_score >= 50 ? '#facc15' : '#ef4444' }}>
              {overview.avg_quality_score?.toFixed(1) || '—'}
            </div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>总股票数</div>
            <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{overview.total_stocks || 0}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>多源验证</div>
            <div className="text-xl font-bold" style={{ color: '#38bdf8' }}>{overview.multi_source_validated || 0}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>已修正</div>
            <div className="text-xl font-bold" style={{ color: '#facc15' }}>{overview.action_stats?.correct || 0}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>待审核</div>
            <div className="text-xl font-bold" style={{ color: overview.pending_reviews > 0 ? '#ef4444' : 'var(--text-primary)' }}>{overview.pending_reviews || 0}</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-1.5">
        {confidencePieOption() && (
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <h3 className="text-xs font-bold mb-1" style={{ color: 'var(--text-primary)' }}>置信度分布</h3>
            <ReactECharts echarts={echarts} option={confidencePieOption()} style={{ height: 170 }} />
          </div>
        )}
        {sourceBarOption() && (
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <h3 className="text-xs font-bold mb-1" style={{ color: 'var(--text-primary)' }}>数据源可靠性评分</h3>
            <ReactECharts echarts={echarts} option={sourceBarOption()} style={{ height: 170 }} />
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-1.5">
        <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>🔍 审核队列 {reviewQueue?.count ? `(${reviewQueue.count})` : ''}</h3>
            {reviewQueue?.count > 0 && (
              <button
                onClick={async () => {
                  const { ok, data } = await apiFetch('/api/quality/auto-review', { method: 'POST' });
                  if (!ok) return;
                  alert(`自动审核完成：通过${data.auto_passed}条，保留人工${data.kept_manual}条`);
                  fetchAll();
                }}
                className="px-1.5 py-0.5 rounded text-[10px] font-medium"
                style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}
              >⚡ 自动审核</button>
            )}
          </div>
          <div className="max-h-64 overflow-y-auto">
            {reviewQueue?.items?.length > 0 ? (
              <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {reviewQueue.items.map(r => {
                  const authorityVal = calcAuthorityValue(r.sources_data);
                  const selectedVal = selectedValues[r.id];
                  const emUrl = getEastMoneyUrl(r.ts_code);
                  const thsUrl = getTHSUrl(r.ts_code);
                  const sinaUrl = getStockUrl(r.ts_code);
                  const txUrl = getTencentUrl(r.ts_code);
                  return (
                  <div key={r.id} className="p-2 text-[11px] space-y-1">
                    <div className="flex items-center justify-between">
                      <span className="font-medium" style={{ color: 'var(--text-primary)' }}>{r.name} <span style={{ color: 'var(--text-muted)' }}>{r.ts_code}</span></span>
                      <div className="flex items-center gap-1 flex-wrap justify-end">
                        <span className="px-1 py-0.5 rounded text-[10px]" style={{ background: 'rgba(250,204,21,0.15)', color: '#facc15' }}>{tIndicator(r.indicator)}</span>
                        {sinaUrl && <a href={sinaUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="px-1 py-0.5 rounded no-underline text-[10px]" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }} title="跳转新浪财经">📕新浪</a>}
                        {emUrl && <a href={emUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="px-1 py-0.5 rounded no-underline text-[10px]" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }} title="跳转东方财富">📈东财</a>}
                        {txUrl && <a href={txUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="px-1 py-0.5 rounded no-underline text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }} title="跳转腾讯财经">🐧腾讯</a>}
                        {thsUrl && <a href={thsUrl} target="_blank" rel="noopener noreferrer" onClick={e => e.stopPropagation()} className="px-1 py-0.5 rounded no-underline text-[10px]" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }} title="跳转同花顺">🔮同花顺</a>}
                      </div>
                    </div>
                    <div className="flex items-center gap-2" style={{ color: 'var(--text-muted)', fontSize: 10 }}>
                      <span>⏰ {r.created_at}</span>
                    </div>
                    <div style={{ color: '#facc15' }}>原因：{r.reason}</div>
                    <div className="rounded p-1.5" style={{ background: 'var(--bg-hover)' }}>
                      <div className="text-[10px] mb-0.5 flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
                        <span>各数据源返回值（点击选择）：</span>
                        {authorityVal != null && (
                          <span style={{ color: '#38bdf8' }}>推荐：{authorityVal.toLocaleString()}万 ({(authorityVal/10000).toFixed(2)}亿)</span>
                        )}
                      </div>
                      {Object.entries(r.sources_data || {}).map(([src, d]) => {
                        const val = typeof d === 'object' ? d.value : d;
                        const valWan = Number(val) || 0;
                        const valYi = (valWan / 10000).toFixed(2);
                        const isSelected = selectedVal === valWan;
                        const isAuthority = authorityVal != null && Math.abs(valWan - authorityVal) < 1;
                        return (
                          <div key={src} className="flex items-center justify-between py-0.5 cursor-pointer rounded px-1"
                               style={{ background: isSelected ? 'rgba(56,189,248,0.15)' : 'transparent' }}
                               onClick={() => setSelectedValues(prev => ({...prev, [r.id]: valWan}))}>
                            <span style={{ color: 'var(--text-secondary)', fontSize: 10 }}>
                              {tSource(src)}
                              {isAuthority && <span style={{ color: '#38bdf8', marginLeft: 3 }}>✓</span>}
                            </span>
                            <span style={{ color: isSelected ? '#38bdf8' : 'var(--text-primary)', fontWeight: 600, fontSize: 10 }}>
                              {valWan.toLocaleString()}万
                              <span style={{ color: 'var(--text-muted)', fontWeight: 400, marginLeft: 3 }}>({valYi}亿)</span>
                            </span>
                          </div>
                        );
                      })}
                    </div>
                    <div className="flex items-center gap-1.5 pt-0.5">
                      <button onClick={() => handleReview(r.id, 'approve')} className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>
                        通过{selectedVal != null ? `(${selectedVal.toLocaleString()}万)` : '(推荐值)'}
                      </button>
                      <button onClick={() => handleReview(r.id, 'reject')} className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>拒绝</button>
                    </div>
                  </div>
                  );
                })}
              </div>
            ) : (
              <div className="p-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无待审核数据</div>
            )}
          </div>
        </div>

        <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>⚠️ 异常数据 {anomalies?.count ? `(${anomalies.count})` : ''}</h3>
          </div>
          <div className="max-h-64 overflow-y-auto">
            {anomalies?.anomalies?.length > 0 ? (
              <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {anomalies.anomalies.map((a, i) => (
                  <div key={i} className="px-3 py-1.5 text-[11px] flex items-center gap-2">
                    <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: a.confidence === 'disputed' ? '#a78bfa' : '#ef4444' }} />
                    <span className="font-medium" style={{ color: 'var(--text-primary)' }}>{a.name}</span>
                    <span style={{ color: 'var(--text-muted)' }}>{a.ts_code}</span>
                    <span className="flex-1 text-right" style={{ color: a.main_force_inflow > 0 ? '#ef4444' : '#22c55e' }}>
                      {(a.main_force_inflow / 10000).toFixed(2)}亿
                    </span>
                    <span style={{ color: a.deviation_pct > 50 ? '#ef4444' : '#facc15' }}>偏差{a.deviation_pct}%</span>
                    <span className="px-1 py-0.5 rounded text-[10px]" style={{
                      background: a.confidence === 'disputed' ? 'rgba(167,139,250,0.15)' : 'rgba(239,68,68,0.15)',
                      color: a.confidence === 'disputed' ? '#a78bfa' : '#ef4444',
                    }}>{tConfidence(a.confidence)}</span>
                    <span style={{ color: '#38bdf8' }}>{a.sources_count}源</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="p-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无异常数据</div>
            )}
          </div>
        </div>
      </div>

      {sources?.sources?.length > 0 && (
        <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>🔌 数据源可靠性统计</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>数据源</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>总采集</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>异常次数</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>异常率</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>平均偏差</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>可靠性评分</th>
                </tr>
              </thead>
              <tbody>
                {sources.sources.map(s => (
                  <tr key={s.source} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="p-1.5 font-medium" style={{ color: 'var(--text-primary)', fontSize: 11 }}>{tSource(s.source)}</td>
                    <td className="p-1.5 text-right" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{s.total_count}</td>
                    <td className="p-1.5 text-right" style={{ color: s.outlier_count > 0 ? '#facc15' : 'var(--text-secondary)', fontSize: 11 }}>{s.outlier_count}</td>
                    <td className="p-1.5 text-right" style={{ color: s.outlier_rate > 10 ? '#ef4444' : 'var(--text-secondary)', fontSize: 11 }}>{s.outlier_rate}%</td>
                    <td className="p-1.5 text-right" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{s.avg_deviation}%</td>
                    <td className="p-1.5 text-right">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                        background: s.avg_score >= 70 ? 'rgba(34,197,94,0.15)' : s.avg_score >= 50 ? 'rgba(250,204,21,0.15)' : 'rgba(239,68,68,0.15)',
                        color: s.avg_score >= 70 ? '#22c55e' : s.avg_score >= 50 ? '#facc15' : '#ef4444',
                      }}>{s.avg_score}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {dataSources?.sources && (
        <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>🗂️ 全部数据源矩阵（{dataSources.available_count}已启用 / {dataSources.pending_count}待集成）</h3>
            <div className="flex gap-1.5 text-[10px]">
              <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>无限制 {dataSources.unlimited_count}</span>
              <span className="px-1.5 py-0.5 rounded" style={{ background: 'rgba(250,204,21,0.15)', color: '#facc15' }}>有额度 {dataSources.rate_limited_count}</span>
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left p-1.5 sticky left-0" style={{ color: 'var(--text-muted)', background: 'var(--bg-card)', fontSize: 10 }}>数据源</th>
                  <th className="text-center p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>状态</th>
                  <th className="text-center p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>额度</th>
                  <th className="text-center p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>协议</th>
                  <th className="text-center p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>优先级</th>
                  <th className="text-center p-1.5" style={{ color: '#ef4444', fontSize: 10 }}>主力净流入</th>
                  <th className="text-center p-1.5" style={{ color: '#38bdf8', fontSize: 10 }}>价格</th>
                  <th className="text-center p-1.5" style={{ color: '#22c55e', fontSize: 10 }}>涨跌幅</th>
                  <th className="text-center p-1.5" style={{ color: '#a78bfa', fontSize: 10 }}>板块资金</th>
                  <th className="text-center p-1.5" style={{ color: '#facc15', fontSize: 10 }}>K线</th>
                  <th className="text-center p-1.5" style={{ color: '#fb923c', fontSize: 10 }}>盘口</th>
                  <th className="text-center p-1.5" style={{ color: '#f472b6', fontSize: 10 }}>PE/PB</th>
                  <th className="text-center p-1.5" style={{ color: '#94a3b8', fontSize: 10 }}>财报</th>
                  <th className="text-center p-1.5" style={{ color: '#94a3b8', fontSize: 10 }}>公告</th>
                  <th className="text-center p-1.5" style={{ color: '#94a3b8', fontSize: 10 }}>龙虎榜</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>备注</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(dataSources.sources).map(([key, cfg]) => {
                  const has = (ind) => cfg.indicators.includes(ind);
                  const Cell = ({ ind, color }) => (
                    <td className="p-1.5 text-center">
                      {has(ind) ? (
                        <span style={{ color, fontSize: 12 }}>✓</span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)', opacity: 0.3 }}>—</span>
                      )}
                    </td>
                  );
                  return (
                  <tr key={key} style={{ borderBottom: '1px solid var(--border-color)', opacity: cfg.available ? 1 : 0.5 }}>
                    <td className="p-1.5 font-medium sticky left-0" style={{ color: 'var(--text-primary)', background: 'var(--bg-card)', fontSize: 11 }}>{cfg.display_name}</td>
                    <td className="p-1.5 text-center">
                      <span className="px-1 py-0.5 rounded text-[10px]" style={{
                        background: cfg.available ? 'rgba(34,197,94,0.15)' : 'rgba(148,163,184,0.15)',
                        color: cfg.available ? '#22c55e' : '#94a3b8',
                      }}>{cfg.available ? '已启用' : '待集成'}</span>
                    </td>
                    <td className="p-1.5 text-center">
                      <span className="text-[10px]" style={{ color: cfg.rate_limited ? '#facc15' : '#22c55e' }}>
                        {cfg.rate_limited ? '有限制' : '无限制'}
                      </span>
                    </td>
                    <td className="p-1.5 text-center" style={{ color: 'var(--text-secondary)', fontSize: 10 }}>{cfg.protocol}</td>
                    <td className="p-1.5 text-center" style={{ color: 'var(--text-secondary)', fontSize: 10 }}>{cfg.priority}</td>
                    <Cell ind="main_force_inflow" color="#ef4444" />
                    <Cell ind="price" color="#38bdf8" />
                    <Cell ind="price_chg" color="#22c55e" />
                    <Cell ind="sector_flow" color="#a78bfa" />
                    <Cell ind="kline" color="#facc15" />
                    <Cell ind="quote" color="#fb923c" />
                    <Cell ind="pe_ttm" color="#f472b6" />
                    <Cell ind="financial_report" color="#94a3b8" />
                    <Cell ind="announcement" color="#94a3b8" />
                    <Cell ind="dragon_tiger" color="#94a3b8" />
                    <td className="p-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>{cfg.note}</td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {errorStats && Object.keys(errorStats).length > 0 && (
        <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
            <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>⚠️ 数据源出错率监控</h3>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>高出错率源后续将替换/删除</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>数据源</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>总调用</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>错误次数</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>出错率</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>最后成功</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>最后错误</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(errorStats)
                  .sort((a, b) => (b[1].error_rate || 0) - (a[1].error_rate || 0))
                  .map(([src, stats]) => {
                    const rate = stats.error_rate || 0;
                    const rateColor = rate === 0 ? '#22c55e' : rate < 10 ? '#facc15' : rate < 30 ? '#fb923c' : '#ef4444';
                    return (
                      <tr key={src} style={{ borderBottom: '1px solid var(--border-color)' }}>
                        <td className="p-1.5 font-medium" style={{ color: 'var(--text-primary)', fontSize: 11 }}>{tSource(src)}</td>
                        <td className="p-1.5 text-right" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{stats.total_calls}</td>
                        <td className="p-1.5 text-right" style={{ color: stats.errors > 0 ? '#facc15' : 'var(--text-secondary)', fontSize: 11 }}>{stats.errors}</td>
                        <td className="p-1.5 text-right">
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                            background: rate === 0 ? 'rgba(34,197,94,0.15)' : rate < 10 ? 'rgba(250,204,21,0.15)' : rate < 30 ? 'rgba(251,146,60,0.15)' : 'rgba(239,68,68,0.15)',
                            color: rateColor,
                          }}>{rate}%</span>
                        </td>
                        <td className="p-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>{stats.last_success || '—'}</td>
                        <td className="p-1.5 text-[10px] max-w-md truncate" style={{ color: stats.last_error ? '#ef4444' : 'var(--text-muted)' }} title={stats.last_error || ''}>
                          {stats.last_error || '—'}
                        </td>
                      </tr>
                    );
                  })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-1.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h3 className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>📋 质量日志（仅显示修正/审核记录）</h3>
        </div>
        <div className="max-h-60 overflow-y-auto">
          {logs?.logs?.length > 0 ? (
            <table className="w-full text-xs">
              <thead className="sticky top-0" style={{ background: 'var(--bg-card)' }}>
                <tr style={{ borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>时间</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>股票</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>指标</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>权威值</th>
                  <th className="text-left p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>异常源</th>
                  <th className="text-right p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>质量分</th>
                  <th className="text-center p-1.5" style={{ color: 'var(--text-muted)', fontSize: 10 }}>动作</th>
                </tr>
              </thead>
              <tbody>
                {logs.logs.map(l => (
                  <tr key={l.id} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="p-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>{l.snapshot_time}</td>
                    <td className="p-1.5" style={{ color: 'var(--text-primary)', fontSize: 11 }}>{l.name}</td>
                    <td className="p-1.5 text-[10px]" style={{ color: 'var(--text-secondary)' }}>{tIndicator(l.indicator)}</td>
                    <td className="p-1.5 text-right" style={{ color: 'var(--text-secondary)', fontSize: 11 }}>{l.authority_value?.toFixed(2)}</td>
                    <td className="p-1.5 text-[10px]" style={{ color: '#ef4444' }}>{tSource(l.outliers) || '—'}</td>
                    <td className="p-1.5 text-right" style={{ color: l.quality_score >= 70 ? '#22c55e' : l.quality_score >= 50 ? '#facc15' : '#ef4444', fontSize: 11 }}>{l.quality_score?.toFixed(1)}</td>
                    <td className="p-1.5 text-center">
                      <span className="px-1.5 py-0.5 rounded text-[10px]" style={{
                        background: l.action === 'review' ? 'rgba(167,139,250,0.15)' : l.action === 'correct' ? 'rgba(250,204,21,0.15)' : 'rgba(239,68,68,0.15)',
                        color: l.action === 'review' ? '#a78bfa' : l.action === 'correct' ? '#facc15' : '#ef4444',
                      }}>{tAction(l.action)}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <div className="p-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无质量日志（需要采集后生成）</div>
          )}
        </div>
      </div>
    </div>
  );
}


function DataFreshnessPanel({ freshness }) {
  if (!freshness) return null;

  const { summary, sources, check_time, is_trading_day, is_trading_hours } = freshness;
  const overall = summary.overall_status;

  const overallConfig = {
    fresh: { icon: '✅', label: '数据最新', color: '#22c55e', bg: 'rgba(34,197,94,0.08)' },
    stale: { icon: '⚠️', label: '数据滞后', color: '#facc15', bg: 'rgba(250,204,21,0.08)' },
    error: { icon: '❌', label: '数据异常', color: '#ef4444', bg: 'rgba(239,68,68,0.08)' },
  };
  const oc = overallConfig[overall] || overallConfig.stale;

  const statusConfig = {
    fresh: { icon: '●', color: '#22c55e', bg: 'rgba(34,197,94,0.1)', label: '最新' },
    stale: { icon: '●', color: '#facc15', bg: 'rgba(250,204,21,0.1)', label: '滞后' },
    error: { icon: '●', color: '#ef4444', bg: 'rgba(239,68,68,0.1)', label: '异常' },
  };

  const freshPct = summary.total > 0 ? (summary.fresh / summary.total) * 100 : 0;

  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: oc.color + '40', background: oc.bg }}>
      <div className="flex items-center gap-2 px-3 py-2" style={{ borderBottom: '1px solid ' + oc.color + '20' }}>
        <span className="text-lg">{oc.icon}</span>
        <div className="flex-1">
          <div className="flex items-center gap-1.5">
            <span className="font-bold text-xs" style={{ color: oc.color }}>数据更新：{oc.label}</span>
            <span className="text-[10px] px-1 py-0.5 rounded" style={{ background: is_trading_hours ? 'rgba(239,68,68,0.15)' : 'rgba(148,163,184,0.15)', color: is_trading_hours ? '#ef4444' : '#94a3b8' }}>
              {is_trading_hours ? '🔴 盘中' : is_trading_day ? '⚪ 盘后' : '⚪ 非交易日'}
            </span>
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            {check_time} · {summary.fresh}/{summary.total} 最新
            {summary.stale > 0 && <span style={{ color: '#facc15' }}> · {summary.stale} 滞后</span>}
            {summary.error > 0 && <span style={{ color: '#ef4444' }}> · {summary.error} 异常</span>}
          </div>
        </div>
        <div className="flex-shrink-0 w-24">
          <div className="text-[10px] text-right mb-0.5" style={{ color: 'var(--text-muted)' }}>新鲜度 {freshPct.toFixed(0)}%</div>
          <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(148,163,184,0.2)' }}>
            <div className="h-full rounded-full transition-all duration-500" style={{
              width: `${freshPct}%`,
              background: freshPct >= 80 ? '#22c55e' : freshPct >= 50 ? '#facc15' : '#ef4444',
            }} />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-1.5 p-2">
        {sources.map((src, i) => {
          const sc = statusConfig[src.status] || statusConfig.stale;
          const isStale = src.status !== 'fresh';
          return (
            <div key={i} className="rounded p-1.5 border" style={{
              borderColor: isStale ? sc.color + '40' : 'var(--border-color)',
              background: isStale ? sc.bg : 'var(--bg-card)',
            }}>
              <div className="flex items-center justify-between mb-0.5">
                <span className="text-[10px] font-medium" style={{ color: 'var(--text-primary)' }}>{src.name}</span>
                <span className="text-[10px] px-1 py-0.5 rounded" style={{ background: sc.bg, color: sc.color }}>
                  {sc.icon} {sc.label}
                </span>
              </div>
              <div className="flex items-center justify-between text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>{src.latest_date || '无数据'}{src.latest_time && <span className="ml-1">{src.latest_time}</span>}</span>
                <span className="px-1 py-0.5 rounded text-[10px]" style={{ background: 'rgba(148,163,184,0.1)', color: 'var(--text-muted)' }}>
                  {src.category}
                </span>
              </div>
              {isStale && (
                <div className="mt-0.5 text-[10px] font-medium" style={{ color: sc.color }}>
                  ⚠ {src.message}
                  {src.expected_date && src.delay_days > 0 && (
                    <span style={{ color: 'var(--text-muted)' }}> (期望: {src.expected_date})</span>
                  )}
                </div>
              )}
              {src.status === 'stale' && src.delay_days > 0 && (
                <div className="mt-0.5 h-1 rounded-full overflow-hidden" style={{ background: 'rgba(250,204,21,0.15)' }}>
                  <div className="h-full rounded-full" style={{
                    width: `${Math.min(src.delay_days * 20, 100)}%`,
                    background: src.delay_days >= 3 ? '#ef4444' : '#facc15',
                  }} />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {summary.stale > 0 && (
        <div className="px-3 py-1.5 flex items-center gap-1.5 text-[10px]" style={{ background: 'rgba(250,204,21,0.06)', borderTop: '1px solid rgba(250,204,21,0.15)' }}>
          <span style={{ color: '#facc15' }}>⚠️</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            当前有 <b style={{ color: '#facc15' }}>{summary.stale}</b> 个数据源未及时更新。
            {summary.max_delay_days > 0 && `最大滞后 ${summary.max_delay_days} 个交易日。`}
          </span>
        </div>
      )}
    </div>
  );
}
