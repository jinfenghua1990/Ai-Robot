import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

/* ---------- 设计系统元数据 ---------- */
const SOURCE_META = {
  tdx:       { label: '通达信', icon: '📊', color: '#3b82f6', soft: 'rgba(59,130,246,0.10)' },
  ifind:     { label: '同花顺', icon: '📈', color: '#a855f7', soft: 'rgba(168,85,247,0.10)' },
  recap:     { label: '盘后复盘', icon: '📆', color: '#2c56ba', soft: 'rgba(44,86,186,0.08)' },
  portfolio: { label: '持仓报告', icon: '💼', color: '#16a34a', soft: 'rgba(22,163,74,0.10)' },
};

const CATEGORIES = [
  { key: 'all',      label: '全部报告', icon: '📋', color: 'var(--accent-blue)', dot: false },
  { key: 'recap',    label: '盘后复盘', icon: '📆', color: '#2c56ba',          dot: false },
  { key: 'portfolio',label: '持仓报告', icon: '💼', color: 'var(--accent-green)', dot: false },
  { key: 'tdx',      label: '通达信分析', icon: '📊', color: '#3b82f6',         dot: false },
  { key: 'ifind',    label: '同花顺分析', icon: '📈', color: '#a855f7',         dot: false },
];

const RATING_META = {
  '买入': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.12)', border: 'rgba(22,163,74,0.32)' },
  '增持': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.10)', border: 'rgba(22,163,74,0.28)' },
  '强烈推荐': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.12)', border: 'rgba(22,163,74,0.32)' },
  '持有': { color: 'var(--accent-amber)', bg: 'rgba(217,119,6,0.12)', border: 'rgba(217,119,6,0.32)' },
  '中性': { color: 'var(--text-muted)', bg: 'rgba(100,116,139,0.10)', border: 'rgba(100,116,139,0.28)' },
  '减持': { color: 'var(--accent-red)', bg: 'rgba(220,38,38,0.10)', border: 'rgba(220,38,38,0.28)' },
  '卖出': { color: 'var(--accent-red)', bg: 'rgba(220,38,38,0.12)', border: 'rgba(220,38,38,0.32)' },
};

const flowColor = (v) => {
  if (v == null) return 'var(--text-muted)';
  if (typeof v === 'number') return v >= 0 ? 'var(--flow-up)' : 'var(--flow-down)';
  return String(v).includes('+') ? 'var(--flow-up)' : 'var(--flow-down)';
};
const fmtPct = (v) => {
  if (v == null) return '—';
  if (typeof v === 'number') return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  return String(v);
};

export default function ResearchCenterPage() {
  const navigate = useNavigate();
  const [requests, setRequests] = useState([]);
  const [results, setResults] = useState([]);
  const [notifs, setNotifs] = useState([]);
  const [unread, setUnread] = useState(0);
  const [loading, setLoading] = useState(true);
  const [activeCat, setActiveCat] = useState('all');

  const loadData = useCallback(async () => {
    try {
      const [reqRes, resRes, notifRes] = await Promise.all([
        apiFetch('/api/analysis/requests?status=all'),
        apiFetch('/api/analysis/results?limit=30'),
        apiFetch('/api/analysis/notifications'),
      ]);
      if (reqRes.ok) setRequests(reqRes.data.requests || []);
      if (resRes.ok) setResults(resRes.data.results || []);
      if (notifRes.ok) {
        setNotifs(notifRes.data.notifications || []);
        setUnread(notifRes.data.unread_count || 0);
      }
    } catch (e) { /* 静默 */ }
    setLoading(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const markAllRead = async () => {
    for (const n of notifs) {
      if (!n.read) await apiFetch(`/api/analysis/notifications/read/${n.id}`, { method: 'POST' });
    }
    loadData();
  };

  /* 计数 */
  const counts = {
    all: results.length,
    recap: results.filter(r => r.source === 'recap').length,
    portfolio: results.filter(r => r.source === 'portfolio').length,
    tdx: results.filter(r => r.source === 'tdx').length,
    ifind: results.filter(r => r.source === 'ifind').length,
  };
  const pending = requests.filter(r => r.status === 'pending');
  const unreadNotifs = notifs.filter(n => !n.read);

  const recaps = results.filter(r => r.source === 'recap')
    .sort((a, b) => (b.date || '').localeCompare(a.date || ''));
  const stocks = results.filter(r => r.source === 'tdx' || r.source === 'ifind');
  const portfolios = results.filter(r => r.source === 'portfolio');
  const curStocks = activeCat === 'all' ? stocks : stocks.filter(r => r.source === activeCat);

  const showRecap = activeCat === 'all' || activeCat === 'recap';
  const showStocks = activeCat === 'all' || activeCat === 'tdx' || activeCat === 'ifind';
  const showPortfolio = activeCat === 'all' || activeCat === 'portfolio';

  /* 片段：迷你指标 */
  const MiniStat = ({ label, value, color }) => (
    <div className="rounded-lg px-1.5 py-1" style={{ background: 'var(--bg-hover)' }}>
      <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-[11px] font-semibold truncate" style={{ color: color || 'var(--text-primary)' }}>{value}</div>
    </div>
  );

  /* 片段：个股报告卡 */
  const StockCard = ({ r, idx }) => {
    const src = SOURCE_META[r.source] || SOURCE_META.tdx;
    const rating = r.summary?.rating;
    const rm = rating ? (RATING_META[rating] || RATING_META['中性']) : null;
    const q = r.quotes || {};
    const f = r.financials || {};
    const mf = r.money_flow?.today || {};
    const t = r.technical || {};
    return (
      <div className={`premium-card magnetic p-3 cursor-pointer fade-in-${idx < 3 ? idx + 1 : 1}`}
        onClick={() => navigate(`/report/${r.id}`)}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="text-[13px] font-bold truncate" style={{ color: 'var(--text-primary)' }}>{r.stock_name}</div>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{r.stock_code}</div>
          </div>
          <span className="shrink-0 text-[10px] font-medium px-1.5 py-0.5 rounded-full"
            style={{ background: src.soft, color: src.color }}>{src.icon} {src.label}</span>
        </div>

        <div className="mt-2 flex items-center gap-2">
          {rm && (
            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded"
              style={{ background: rm.bg, color: rm.color, border: `0.5px solid ${rm.border}` }}>{rating}</span>
          )}
          {q.price != null && (
            <span className="text-[12px] font-bold" style={{ color: flowColor(q.change_pct) }}>
              {q.price?.toFixed(2)} <span className="text-[10px]">{fmtPct(q.change_pct)}</span>
            </span>
          )}
          <span className="ml-auto text-[9px]" style={{ color: 'var(--text-muted)' }}>
            {r.created_at?.slice(5, 10)} {r.created_at?.slice(11, 16)}
          </span>
        </div>

        <div className="mt-2 grid grid-cols-3 gap-1.5">
          <MiniStat label="PE" value={f.pe != null ? `${f.pe}x` : '—'} color="var(--accent-amber)" />
          <MiniStat label="主力净流入" value={mf.main_net || '—'} color={flowColor(mf.main_net)} />
          <MiniStat label="RSI" value={t.rsi != null ? t.rsi.toFixed(0) : '—'}
            color={t.rsi > 70 ? 'var(--flow-up)' : t.rsi < 30 ? 'var(--flow-down)' : 'var(--accent-amber)'} />
        </div>
      </div>
    );
  };

  /* 片段：复盘日报大卡 */
  const RecapCard = ({ r }) => {
    const idx = r.indices || {};
    return (
      <div className="premium-card hero-grad p-4 cursor-pointer fade-in"
        onClick={() => navigate(`/report/${r.id}`)}>
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="text-[15px] font-bold gradient-text">📆 盘后复盘</span>
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{r.date}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(44,86,186,0.10)', color: '#2c56ba' }}>
              A股市场日报
            </span>
          </div>
          <span className="text-[11px]" style={{ color: 'var(--accent-blue)' }}>查看完整 →</span>
        </div>

        {/* 指数条 */}
        <div className="flex gap-4 overflow-x-auto pb-1">
          {Object.entries(idx).map(([name, v]) => (
            <div key={name} className="shrink-0 text-center px-2">
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{name}</div>
              <div className="text-[13px] font-bold" style={{ color: flowColor(v.change_pct) }}>
                {v.price?.toFixed(0)}
              </div>
              <div className="text-[10px]" style={{ color: flowColor(v.change_pct) }}>{fmtPct(v.change_pct)}</div>
            </div>
          ))}
          {Object.keys(idx).length === 0 && (
            <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>盘后数据采集中…</div>
          )}
        </div>

        {/* 关键观点 */}
        {r.summary?.key_points?.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {r.summary.key_points.map((p, i) => (
              <span key={i} className="text-[10px] px-2 py-1 rounded-lg"
                style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>{p}</span>
            ))}
          </div>
        )}
      </div>
    );
  };

  /* 片段：持仓卡 */
  const PortfolioCard = ({ r, idx }) => (
    <div className={`premium-card magnetic p-3 cursor-pointer fade-in-${idx < 3 ? idx + 1 : 1}`}
      onClick={() => navigate(`/report/${r.id}`)}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-[16px]">💼</span>
          <div>
            <div className="text-[12px] font-bold" style={{ color: 'var(--text-primary)' }}>持仓分析报告</div>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              {r.created_at?.slice(0, 10)} {r.created_at?.slice(11, 16)}
            </div>
          </div>
        </div>
        <span className="text-[11px]" style={{ color: 'var(--accent-green)' }}>查看 →</span>
      </div>
    </div>
  );

  return (
    <div className="flex gap-4 max-w-7xl mx-auto">
      {/* ===== 左侧分类导航（lg 显示） ===== */}
      <aside className="hidden lg:block w-52 shrink-0">
        <div className="sticky top-4 space-y-4">
          <div className="premium-card p-3">
            <div className="text-[11px] font-bold mb-2" style={{ color: 'var(--text-secondary)' }}>报告分类</div>
            <nav className="space-y-1">
              {CATEGORIES.map(cat => (
                <button key={cat.key} onClick={() => setActiveCat(cat.key)}
                  className="w-full flex items-center gap-2 px-2.5 py-2 rounded-xl text-left transition"
                  style={{
                    background: activeCat === cat.key ? 'color-mix(in srgb, var(--accent-blue) 12%, transparent)' : 'transparent',
                  }}>
                  <span className="text-[14px]">{cat.icon}</span>
                  <span className="text-[12px] font-medium flex-1"
                    style={{ color: activeCat === cat.key ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>{cat.label}</span>
                  <span className="text-[10px] px-1.5 py-0.5 rounded-full"
                    style={{
                      background: activeCat === cat.key ? 'var(--accent-blue)' : 'var(--bg-hover)',
                      color: activeCat === cat.key ? '#fff' : 'var(--text-muted)',
                    }}>{counts[cat.key] || 0}</span>
                </button>
              ))}
            </nav>
          </div>

          {/* 待处理队列 */}
          {pending.length > 0 && (
            <div className="premium-card p-3" style={{ borderColor: 'rgba(217,119,6,0.3)' }}>
              <div className="flex items-center gap-1.5 mb-2">
                <span className="pulse-dot amber" />
                <span className="text-[11px] font-bold" style={{ color: 'var(--accent-amber)' }}>分析队列</span>
              </div>
              <div className="text-[10px] leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                {pending.length} 个分析请求排队中，下次对话自动处理
              </div>
            </div>
          )}

          {/* 未读通知 */}
          {unreadNotifs.length > 0 && (
            <div className="premium-card p-3" style={{ borderColor: 'rgba(220,38,38,0.28)' }}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-1.5">
                  <span className="pulse-dot red" />
                  <span className="text-[11px] font-bold" style={{ color: 'var(--accent-red)' }}>未读 {unread}</span>
                </div>
                <button onClick={markAllRead} className="text-[9px] hover:underline" style={{ color: 'var(--text-muted)' }}>全部已读</button>
              </div>
              <div className="space-y-1">
                {unreadNotifs.slice(0, 4).map(n => {
                  const src = SOURCE_META[n.source] || SOURCE_META.tdx;
                  return (
                    <div key={n.id} className="text-[10px] px-2 py-1.5 rounded-lg cursor-pointer hover:opacity-70 flex items-center gap-1.5"
                      style={{ background: src.soft }}
                      onClick={() => navigate(`/report/${n.id.replace('notif_', '')}`)}>
                      <span>{src.icon}</span>
                      <span className="truncate flex-1" style={{ color: 'var(--text-primary)' }}>{n.title || `${n.stock_name}报告`}</span>
                      <span style={{ color: 'var(--accent-green)' }}>✓</span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      </aside>

      {/* ===== 主内容区 ===== */}
      <main className="flex-1 min-w-0 space-y-3">
        {/* 顶部栏：标题 + 刷新 + 未读铃铛（移动端） */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <h2 className="text-[17px] font-bold gradient-text">研报中心</h2>
            <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
              共 {results.length} 份 · 待处理 {pending.length}
            </span>
          </div>
          <div className="flex items-center gap-2">
            {unread > 0 && (
              <span className="text-[10px] px-2 py-0.5 rounded-full font-medium"
                style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
                🛎️ {unread} 未读
              </span>
            )}
            <button onClick={loadData} className="px-2.5 py-1 rounded-lg text-[11px] transition hover:opacity-70"
              style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
          </div>
        </div>

        {/* 移动端分类 chips */}
        <div className="flex items-center gap-1.5 overflow-x-auto lg:hidden pb-1">
          {CATEGORIES.map(cat => (
            <button key={cat.key} onClick={() => setActiveCat(cat.key)}
              className={`chip ${activeCat === cat.key ? 'active' : ''}`}>
              {cat.icon} {cat.label} {counts[cat.key] || 0}
            </button>
          ))}
        </div>

        {/* 加载态：骨架屏 */}
        {loading && (
          <div className="space-y-3">
            <div className="premium-card p-4">
              <div className="h-5 w-40 rounded bg-[var(--bg-hover)] animate-pulse mb-3" />
              <div className="flex gap-4">
                {[1, 2, 3, 4].map(i => <div key={i} className="h-10 w-20 rounded bg-[var(--bg-hover)] animate-pulse" />)}
              </div>
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
              {[1, 2, 3, 4, 5, 6].map(i => (
                <div key={i} className="premium-card p-3 h-32 animate-pulse" style={{ background: 'var(--bg-hover)' }} />
              ))}
            </div>
          </div>
        )}

        {/* 空态 */}
        {!loading && results.length === 0 && (
          <div className="premium-card p-10 text-center fade-in">
            <div className="text-4xl mb-3">📊</div>
            <div className="text-[14px] font-bold" style={{ color: 'var(--text-primary)' }}>研报中心空空如也</div>
            <div className="text-[11px] mt-1 max-w-sm mx-auto" style={{ color: 'var(--text-muted)' }}>
              在个股详情页点击「📊 通达信分析」或「📈 同花顺分析」提交分析请求；盘后系统会自动生成 A 股市场复盘报告。
            </div>
          </div>
        )}

        {/* 内容 */}
        {!loading && results.length > 0 && (
          <>
            {/* 复盘日报（顶部突出） */}
            {showRecap && recaps.length > 0 && (
              <section className="space-y-2">
                {recaps.slice(0, 1).map(r => <RecapCard key={r.id} r={r} />)}
                {recaps.length > 1 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                    {recaps.slice(1, 3).map(r => <RecapCard key={r.id} r={r} />)}
                  </div>
                )}
              </section>
            )}

            {/* 个股分析网格 */}
            {showStocks && curStocks.length > 0 && (
              <section>
                {(activeCat === 'all') && (
                  <div className="text-[11px] font-bold mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                    <span className="w-1 h-3 rounded" style={{ background: 'var(--accent-blue)' }} /> 个股分析
                    <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>{curStocks.length} 份</span>
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {curStocks.map((r, i) => <StockCard key={r.id} r={r} idx={i} />)}
                </div>
              </section>
            )}

            {/* 持仓报告 */}
            {showPortfolio && portfolios.length > 0 && (
              <section>
                {(activeCat === 'all') && (
                  <div className="text-[11px] font-bold mb-2 flex items-center gap-1.5" style={{ color: 'var(--text-secondary)' }}>
                    <span className="w-1 h-3 rounded" style={{ background: 'var(--accent-green)' }} /> 持仓报告
                    <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>{portfolios.length} 份</span>
                  </div>
                )}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                  {portfolios.map((r, i) => <PortfolioCard key={r.id} r={r} idx={i} />)}
                </div>
              </section>
            )}

            {/* 当前分类下空态 */}
            {showRecap && recaps.length === 0 && !showStocks && !showPortfolio && (
              <div className="premium-card p-8 text-center text-[12px]" style={{ color: 'var(--text-muted)' }}>
                暂无复盘报告，盘后 15:30 系统将自动生成。
              </div>
            )}
            {showStocks && curStocks.length === 0 && !showRecap && (
              <div className="premium-card p-8 text-center text-[12px]" style={{ color: 'var(--text-muted)' }}>
                该分类下暂无报告。
              </div>
            )}
          </>
        )}

        {/* 底部引导 */}
        <div className="text-center text-[10px] py-2" style={{ color: 'var(--text-muted)' }}>
          个股详情页点击「📊 通达信分析」「📈 同花顺分析」提交 · 数据来源于对应终端实时行情，仅供参考
        </div>
      </main>
    </div>
  );
}
