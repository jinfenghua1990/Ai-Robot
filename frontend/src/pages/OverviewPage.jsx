import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

/* ============ 主题感知配色（复用全局 CSS 变量，明暗双主题自适应） ============ */
const C = {
  card: 'var(--bg-card)',
  surface: 'var(--bg-surface)',
  hover: 'var(--bg-hover)',
  primary: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  blue: 'var(--accent-blue)',
  up: 'var(--flow-up)',      // 涨 / 盈利 / 多头 —— 红
  down: 'var(--flow-down)',  // 跌 / 亏损 / 空头 —— 绿
  amber: 'var(--accent-amber)',
};

const money = (n, d = 0) =>
  (n == null || isNaN(n)) ? '-' : Number(n).toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (n) => {
  if (n == null || isNaN(n)) return '-';
  return (n >= 0 ? '+' : '') + Number(n).toFixed(2) + '%';
};
const signed = (n, d = 0) =>
  (n == null || isNaN(n)) ? '-' : (n >= 0 ? '+' : '') + money(n, d);
const pnlStyle = (v) => ({ color: v > 0 ? C.up : v < 0 ? C.down : C.muted });
const hitRate = (hit, cand) => (cand > 0 ? (hit / cand) * 100 : 0);

/* ============ 数据域 ============ */
const ENDPOINTS = {
  portfolio: '/api/trading/portfolio-snapshot',
  alerts: '/api/alerts/recent',
  health: '/api/strategy-health?days=14',
  leader: '/api/leader/system',
};

const LEVEL_STYLE = {
  error: { bg: 'rgba(220,38,38,0.12)', color: C.down, label: '严重' },
  warning: { bg: 'rgba(217,119,6,0.12)', color: C.amber, label: '警告' },
  info: { bg: 'rgba(44,86,186,0.12)', color: C.blue, label: '提示' },
};

function Panel({ title, icon, href, onMore, children, loading }) {
  return (
    <section style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 14,
      padding: '16px 18px', display: 'flex', flexDirection: 'column', minHeight: 280,
    }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ fontSize: 18 }}>{icon}</span>
          <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: C.primary }}>{title}</h3>
          {loading && <span style={{ fontSize: 11, color: C.muted }}>加载中…</span>}
        </div>
        {href && (
          <a href={href} onClick={(e) => { e.preventDefault(); onMore && onMore(href); }}
             style={{ fontSize: 12, color: C.blue, textDecoration: 'none' }}>
            查看全部 →
          </a>
        )}
      </header>
      <div style={{ flex: 1, overflow: 'auto' }}>{children}</div>
    </section>
  );
}

function Kpi({ label, value, sub, color, loading }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 14,
      padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 12, color: C.muted }}>{label}</span>
      {loading ? (
        <span style={{ fontSize: 22, fontWeight: 800, color: C.muted }}>···</span>
      ) : (
        <span style={{ fontSize: 24, fontWeight: 800, color: color || C.primary, lineHeight: 1.1 }}>{value}</span>
      )}
      {sub && <span style={{ fontSize: 11, color: C.secondary }}>{sub}</span>}
    </div>
  );
}

function Empty({ text = '暂无数据' }) {
  return <div style={{ padding: '32px 8px', textAlign: 'center', color: C.muted, fontSize: 13 }}>{text}</div>;
}

export default function OverviewPage() {
  const navigate = useNavigate();
  const [data, setData] = useState({ portfolio: null, alerts: null, health: null, leader: null });
  const [errs, setErrs] = useState({});
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [updatedAt, setUpdatedAt] = useState(null);
  const timerRef = useRef(null);

  const loadAll = useCallback(async (isRefresh = false) => {
    isRefresh ? setRefreshing(true) : setLoading(true);
    const [pf, al, hl, ld] = await Promise.allSettled([
      apiFetch(ENDPOINTS.portfolio, {}, 12000),
      apiFetch(ENDPOINTS.alerts, {}, 12000),
      apiFetch(ENDPOINTS.health, {}, 12000),
      apiFetch(ENDPOINTS.leader, {}, 12000),
    ]);
    const next = {}; const e = {};
    const pick = (r) => (r.status === 'fulfilled' && r.value.ok ? r.value.data : null);
    next.portfolio = pick(pf); if (!next.portfolio) e.portfolio = true;
    next.alerts = pick(al); if (!next.alerts) e.alerts = true;
    next.health = pick(hl); if (!next.health) e.health = true;
    next.leader = pick(ld); if (!next.leader) e.leader = true;
    setData(next); setErrs(e); setUpdatedAt(new Date());
    setLoading(false); setRefreshing(false);
  }, []);

  useEffect(() => {
    loadAll(false);
    timerRef.current = setInterval(() => loadAll(true), 60000); // 每 60s 自动刷新
    return () => timerRef.current && clearInterval(timerRef.current);
  }, [loadAll]);

  const go = (href) => navigate(href);

  /* ---------- 派生指标 ---------- */
  const pf = data.portfolio;
  const acc = pf?.accounts?.[0];
  const totalEquity = pf?.total_equity;
  const unrealPnl = pf?.unrealized_pnl;
  const positions = (acc?.positions || []).slice().sort((a, b) => (b.market_value_base || 0) - (a.market_value_base || 0)).slice(0, 8);

  const alertsArr = data.alerts?.data || [];
  const alertCounts = alertsArr.reduce((m, a) => { m[a.level] = (m[a.level] || 0) + 1; return m; }, {});

  const health = data.health;
  const strategies = health?.strategies || [];
  const todayHits = health?.today_total_hits ?? strategies.reduce((s, x) => s + (x.hit_count || 0), 0);

  const leader = data.leader;
  const candidates = leader?.candidates || [];

  return (
    <div style={{ padding: 20, maxWidth: 1320, margin: '0 auto', color: C.primary }}>
      {/* 头部 */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, display: 'flex', alignItems: 'center', gap: 8 }}>
            <span>📡</span> 预测交易总览
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: C.secondary }}>
            信号 · 策略 · 持仓 · 预警 一站式前瞻视图
            {updatedAt && <span style={{ color: C.muted }}> · 更新 {updatedAt.toLocaleTimeString('zh-CN')}</span>}
          </p>
        </div>
        <button onClick={() => loadAll(true)} disabled={refreshing}
          style={{ background: C.blue, color: '#fff', border: 'none', borderRadius: 10, padding: '8px 16px', fontSize: 13, fontWeight: 600, cursor: refreshing ? 'default' : 'pointer', opacity: refreshing ? 0.7 : 1 }}>
          {refreshing ? '刷新中…' : '↻ 刷新'}
        </button>
      </div>

      {/* KPI 卡片 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(190px, 1fr))', gap: 12, marginBottom: 16 }}>
        <Kpi label="账户总资产" value={`¥${money(totalEquity)}`} sub={`现金 ¥${money(pf?.total_cash)} · 持仓 ¥${money(pf?.total_market_value)}`} loading={loading} />
        <Kpi label="未实现盈亏" value={signed(unrealPnl)} sub={`已实现 ${signed(pf?.realized_pnl)}`} color={unrealPnl > 0 ? C.up : unrealPnl < 0 ? C.down : C.muted} loading={loading} />
        <Kpi label="实时预警" value={alertsArr.length} sub={`严重 ${alertCounts.error || 0} · 警告 ${alertCounts.warning || 0} · 提示 ${alertCounts.info || 0}`} color={alertCounts.error ? C.down : C.amber} loading={loading} />
        <Kpi label="策略命中" value={todayHits} sub={`${strategies.length} 个策略 · 今日运行`} color={C.blue} loading={loading} />
        <Kpi label="龙头候选" value={candidates.length} sub={`${leader?.all_count ?? '-'} 只跟踪 · 信号驱动`} color={C.blue} loading={loading} />
      </div>

      {/* 四宫格面板 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(380px, 1fr))', gap: 14 }}>

        {/* —— 持仓盈亏 —— */}
        <Panel title="持仓盈亏" icon="💼" href="/portfolio" onMore={go} loading={loading}>
          {errs.portfolio ? <Empty text="持仓数据获取失败" /> :
            !acc ? <Empty /> : (
              <div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 10 }}>
                  <div style={{ background: C.surface, borderRadius: 10, padding: '8px 10px' }}>
                    <div style={{ fontSize: 11, color: C.muted }}>持仓市值</div>
                    <div style={{ fontSize: 16, fontWeight: 700 }}>¥{money(acc.total_market_value)}</div>
                  </div>
                  <div style={{ background: C.surface, borderRadius: 10, padding: '8px 10px' }}>
                    <div style={{ fontSize: 11, color: C.muted }}>浮动盈亏</div>
                    <div style={{ fontSize: 16, fontWeight: 700, ...pnlStyle(acc.unrealized_pnl) }}>{signed(acc.unrealized_pnl)}</div>
                  </div>
                </div>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ color: C.muted, textAlign: 'right' }}>
                      <th style={{ textAlign: 'left', padding: '4px 6px', fontWeight: 600 }}>代码</th>
                      <th style={{ padding: '4px 6px', fontWeight: 600 }}>现价</th>
                      <th style={{ padding: '4px 6px', fontWeight: 600 }}>市值</th>
                      <th style={{ padding: '4px 6px', fontWeight: 600 }}>浮动盈亏</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={p.symbol} style={{ borderTop: `1px solid ${C.borderLight}`, cursor: 'pointer' }}
                          onClick={() => go(`/stock-analysis?code=${p.symbol}`)}>
                        <td style={{ textAlign: 'left', padding: '6px', color: C.primary, fontWeight: 600 }}>{p.symbol}</td>
                        <td style={{ textAlign: 'right', padding: '6px', color: C.secondary }}>{money(p.last_price, 2)}</td>
                        <td style={{ textAlign: 'right', padding: '6px', color: C.secondary }}>{money(p.market_value_base)}</td>
                        <td style={{ textAlign: 'right', padding: '6px', fontWeight: 600, ...pnlStyle(p.unrealized_pnl_base) }}>{signed(p.unrealized_pnl_base)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <div style={{ fontSize: 11, color: C.muted, marginTop: 6 }}>共 {acc.positions?.length || 0} 个持仓 · 点击查看个股</div>
              </div>
            )}
        </Panel>

        {/* —— 实时预警 —— */}
        <Panel title="实时预警" icon="🚨" href="/dsa/alerts" onMore={go} loading={loading}>
          {errs.alerts ? <Empty text="预警数据获取失败" /> :
            alertsArr.length === 0 ? <Empty /> : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {alertsArr.slice(0, 9).map((a) => {
                  const lv = LEVEL_STYLE[a.level] || LEVEL_STYLE.info;
                  return (
                    <li key={a.id} style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '7px 4px', borderTop: `1px solid ${C.borderLight}` }}>
                      <span style={{ flexShrink: 0, fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 6, background: lv.bg, color: lv.color }}>{lv.label}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: 12, color: C.primary, lineHeight: 1.35 }}>{a.message}</div>
                        <div style={{ fontSize: 10, color: C.muted, marginTop: 2 }}>{a.trade_date} · {a.created_at?.slice(11, 19)}</div>
                      </div>
                    </li>
                  );
                })}
              </ul>
            )}
        </Panel>

        {/* —— 策略胜率 —— */}
        <Panel title="策略胜率" icon="🎯" href="/strategy-center" onMore={go} loading={loading}>
          {errs.health ? <Empty text="策略数据获取失败" /> :
            strategies.length === 0 ? <Empty /> : (
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: C.muted, textAlign: 'right' }}>
                    <th style={{ textAlign: 'left', padding: '4px 6px', fontWeight: 600 }}>策略</th>
                    <th style={{ padding: '4px 6px', fontWeight: 600 }}>状态</th>
                    <th style={{ padding: '4px 6px', fontWeight: 600 }}>候选/命中</th>
                    <th style={{ padding: '4px 6px', fontWeight: 600, width: 90 }}>胜率</th>
                  </tr>
                </thead>
                <tbody>
                  {strategies.map((s) => {
                    const rate = hitRate(s.hit_count, s.candidate_count);
                    return (
                      <tr key={s.key} style={{ borderTop: `1px solid ${C.borderLight}` }}>
                        <td style={{ textAlign: 'left', padding: '6px', color: C.primary, fontWeight: 600 }}>
                          <span style={{ marginRight: 4 }}>{s.icon}</span>{s.name}
                        </td>
                        <td style={{ textAlign: 'right', padding: '6px' }}>
                          <span style={{ fontSize: 10, fontWeight: 700, padding: '2px 6px', borderRadius: 6,
                            background: s.status === 'success' ? 'rgba(22,163,74,0.12)' : s.status === 'failed' ? 'rgba(220,38,38,0.12)' : 'rgba(217,119,6,0.12)',
                            color: s.status === 'success' ? C.down : s.status === 'failed' ? C.up : C.amber }}>
                            {s.status === 'success' ? '成功' : s.status === 'failed' ? '失败' : '运行中'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'right', padding: '6px', color: C.secondary }}>{s.candidate_count}/{s.hit_count}</td>
                        <td style={{ textAlign: 'right', padding: '6px' }}>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'flex-end' }}>
                            <div style={{ flex: 1, height: 6, background: C.surface, borderRadius: 4, overflow: 'hidden', maxWidth: 50 }}>
                              <div style={{ width: `${Math.min(100, rate)}%`, height: '100%', background: rate >= 50 ? C.down : C.amber }} />
                            </div>
                            <span style={{ fontWeight: 700, color: rate >= 50 ? C.down : C.amber, minWidth: 38, textAlign: 'right' }}>{rate.toFixed(0)}%</span>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
        </Panel>

        {/* —— 信号候选 —— */}
        <Panel title="信号候选" icon="⚡" href="/strategy-center" onMore={go} loading={loading}>
          {errs.leader ? <Empty text="信号数据获取失败" /> :
            candidates.length === 0 ? <Empty text="今日暂无龙头信号候选" /> : (
              <ul style={{ listStyle: 'none', margin: 0, padding: 0 }}>
                {candidates.map((c) => (
                  <li key={c.secCode} onClick={() => go(`/stock-analysis?code=${c.secCode}`)}
                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, padding: '8px 4px', borderTop: `1px solid ${C.borderLight}`, cursor: 'pointer' }}>
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: C.primary }}>{c.secName} <span style={{ fontSize: 11, color: C.muted, fontWeight: 400 }}>{c.secCode}</span></div>
                      <div style={{ fontSize: 11, color: C.secondary, marginTop: 1 }}>评分 {c.score ?? '-'} · 风险 {c.riskLevel || '-'}</div>
                    </div>
                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ fontSize: 12, fontWeight: 700, color: c.signalColor || C.blue }}>{c.signalLabel || c.signal}</div>
                      <div style={{ fontSize: 13, fontWeight: 800, ...pnlStyle(c.change_rate) }}>{pct(c.change_rate)}</div>
                    </div>
                  </li>
                ))}
              </ul>
            )}
        </Panel>

      </div>
    </div>
  );
}
