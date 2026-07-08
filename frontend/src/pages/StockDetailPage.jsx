import { useState, useEffect, useCallback } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import KLineChart from '../components/charts/KLineChart';
import IntradayPanel from '../components/trading/IntradayPanel';
import SinaLink from '../components/SinaLink';
import { apiFetch } from '../utils/request';
import { POLL_INTERVAL } from '../utils/constants';

const TABS = [
  { key: 'kline', label: 'K线' },
  { key: 'intraday', label: '盘中实时' },
  { key: 'mflow', label: '主力资金' },
  { key: 'news', label: '资讯搜索' },
  { key: 'data', label: '金融数据' },
  { key: 'history', label: '搜索历史' },
  { key: 'strategy', label: '策略' },
  { key: 'ai', label: 'AI分析' },
];

// 策略标签颜色映射（key → {bg, color}）
const STRATEGY_TAG_COLORS = {
  baihu_v26: { bg: 'rgba(234,179,8,0.15)', color: '#eab308', border: 'rgba(234,179,8,0.4)' },
  baihu_v30: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', border: 'rgba(245,158,11,0.4)' },
  qinglong: { bg: 'rgba(34,197,94,0.15)', color: '#22c55e', border: 'rgba(34,197,94,0.4)' },
  zhushenglang: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', border: 'rgba(239,68,68,0.4)' },
};

const NEWS_QUICK = ['最新公告', '最新研报', '机构观点', '分红派息'];
const DATA_QUICK = ['最新价', '近三年净利润', '十大股东', '公司简介', '主力资金流向'];

export default function StockDetailPage() {
  const { code } = useParams();
  const navigate = useNavigate();

  const [activeTab, setActiveTab] = useState('kline');
  const [stockName, setStockName] = useState(code);
  const [sector, setSector] = useState('');
  const [quote, setQuote] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(true);

  // 妙想资讯搜索
  const [newsQuery, setNewsQuery] = useState('');
  const [newsResult, setNewsResult] = useState(null);
  const [newsLoading, setNewsLoading] = useState(false);
  const [newsError, setNewsError] = useState(null);

  // 妙想金融数据
  const [dataQuery, setDataQuery] = useState('');
  const [dataResult, setDataResult] = useState(null);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState(null);

  // 搜索历史
  const [newsHistory, setNewsHistory] = useState(null);
  const [dataHistory, setDataHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);

  // AI 分析
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiStats, setAiStats] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);

  // 策略标签
  const [strategyData, setStrategyData] = useState(null);
  const [strategyLoading, setStrategyLoading] = useState(false);

  // 盘中实时（双轨制聚合）
  const [superPanel, setSuperPanel] = useState(null);
  const [realtimeData, setRealtimeData] = useState(null);

  // 自选状态
  const [inWatchlist, setInWatchlist] = useState(false);
  const [watchLoading, setWatchLoading] = useState(false);

  // 跳模拟盘买入
  const gotoSimBuy = () => {
    navigate(`/trading?code=${code}&action=buy`);
  };

  // 切换自选
  const toggleWatchlist = async () => {
    if (watchLoading) return;
    setWatchLoading(true);
    try {
      if (inWatchlist) {
        const { ok, data } = await apiFetch(`/api/watchlist/${code}`, { method: 'DELETE' });
        if (ok) {
          setInWatchlist(false);
          alert(`✅ 已从自选股移除 ${stockName}`);
        } else {
          alert('❌ 移除失败: ' + JSON.stringify(data));
        }
      } else {
        const { ok, data } = await apiFetch('/api/watchlist/add', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stockCode: code, stockName: stockName || code }),
        });
        if (ok) {
          setInWatchlist(true);
          alert(`✅ 已加入自选股: ${stockName}`);
        } else {
          const detail = data?.detail || JSON.stringify(data);
          // 重复添加视为成功
          if (detail.includes('已在自选列表中')) {
            setInWatchlist(true);
          } else {
            alert('❌ 添加失败: ' + detail);
          }
        }
      }
    } catch (e) {
      alert('❌ 请求失败: ' + e.message);
    } finally {
      setWatchLoading(false);
    }
  };

  // 拉取股票名 + 行情
  useEffect(() => {
    let active = true;
    if (!code) return;
    setQuoteLoading(true);

    (async () => {
      // 1. 从 watchlist 取股票名/板块
      try {
        const { ok, data: d } = await apiFetch('/api/watchlist');
        if (ok) {
          const sig = (d?.signals || []).find(s => s.secCode === code);
          if (active) {
            if (sig) {
              setStockName(sig.secName || code);
              setSector(sig.sector || '');
              if (sig.quote) setQuote(sig.quote);
            }
            // 是否已在自选
            const inWl = (d?.signals || d?.items || d?.stocks || d || []).some(s => s.secCode === code || s.stock_code === code);
            setInWatchlist(!!inWl);
          }
        }
      } catch (e) { console.error('[StockDetail] watchlist fetch failed:', e); }

      // 2. 实时行情（覆盖）
      try {
        const { ok, data: q } = await apiFetch(`/api/trading/quote?code=${code}`);
        if (ok) {
          if (active && q && q.price != null) {
            setQuote(q);
            if (q.name) setStockName(q.name);
          }
        }
      } catch (e) { console.error('[StockDetail] quote fetch failed:', e); }

      if (active) setQuoteLoading(false);
    })();

    return () => { active = false; };
  }, [code]);

  // 默认搜索词预填
  useEffect(() => {
    if (stockName && stockName !== code) {
      setNewsQuery(prev => prev || `${stockName}最新公告`);
      setDataQuery(prev => prev || `${stockName}最新价`);
    }
  }, [stockName, code]);

  // 拉取策略标签数据
  useEffect(() => {
    if (!code) return;
    let active = true;
    setStrategyLoading(true);
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/stock-strategies/${code}`);
        if (active && ok) setStrategyData(data);
      } catch (e) { console.error('[StockDetail] strategy fetch failed:', e); }
      if (active) setStrategyLoading(false);
    })();
    return () => { active = false; };
  }, [code]);

  // 妙想资讯搜索
  const runNewsSearch = useCallback(async (queryText) => {
    const q = (queryText ?? newsQuery).trim();
    if (!q) { setNewsError('请输入搜索内容'); return; }
    setNewsLoading(true); setNewsError(null); setNewsResult(null);
    try {
      const res = await apiFetch('/api/mx/search', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, stock_code: code, stock_name: stockName }),
      });
      const d = res.data;
      if (d?.detail) setNewsError(d.detail);
      else if (d?.error) setNewsError(d.error);
      else setNewsResult(d);
    } catch (err) {
      setNewsError('请求失败: ' + err.message);
    }
    setNewsLoading(false);
  }, [newsQuery, code, stockName]);

  // 妙想金融数据查询
  const runDataQuery = useCallback(async (queryText) => {
    const q = (queryText ?? dataQuery).trim();
    if (!q) { setDataError('请输入查询内容'); return; }
    setDataLoading(true); setDataError(null); setDataResult(null);
    try {
      const res = await apiFetch('/api/mx/data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q, stock_code: code, stock_name: stockName }),
      });
      const d = res.data;
      if (d?.detail) setDataError(d.detail);
      else if (d?.error) setDataError(d.error);
      else setDataResult(d);
    } catch (err) {
      setDataError('请求失败: ' + err.message);
    }
    setDataLoading(false);
  }, [dataQuery, code, stockName]);

  // Tab4 搜索历史
  const loadHistory = useCallback(async () => {
    if (!code) return;
    setHistoryLoading(true);
    try {
      const [newsResp, dataResp] = await Promise.all([
        (async () => { const { ok, data } = await apiFetch(`/api/stock/${code}/research/news`); return ok ? data : null; })(),
        (async () => { const { ok, data } = await apiFetch(`/api/stock/${code}/research/data`); return ok ? data : null; })(),
      ]);
      setNewsHistory(newsResp);
      setDataHistory(dataResp);
    } catch (e) { /* silent */ }
    setHistoryLoading(false);
  }, [code]);

  // Tab5 AI 分析
  const loadAI = useCallback(async () => {
    if (!code) return;
    setAiLoading(true);
    try {
      const [analysisResp, statsResp] = await Promise.all([
        (async () => { const { ok, data } = await apiFetch(`/api/ai/stock/${code}/analysis`); return ok ? data : null; })(),
        (async () => { const { ok, data } = await apiFetch(`/api/ai/stock/${code}/history`); return ok ? data : null; })(),
      ]);
      setAiAnalysis(analysisResp);
      setAiStats(statsResp);
    } catch (e) { /* silent */ }
    setAiLoading(false);
  }, [code]);

  // 切到历史/AI tab 时按需加载
  useEffect(() => {
    if (activeTab === 'history' && newsHistory === null) loadHistory();
    if (activeTab === 'ai' && aiAnalysis === null) loadAI();
    if (activeTab === 'intraday' && superPanel === null) loadSuperPanel();
  }, [activeTab]);

  // 拉取 super_panel 静态段(只拉 1 次)
  const loadSuperPanel = useCallback(async () => {
    if (!code) return;
    try {
      const { ok, data } = await apiFetch(`/api/v1/stock/super_panel?code=${code}&section=static`);
      if (ok) setSuperPanel(data);
    } catch (e) { /* silent */ }
  }, [code]);

  // 拉取 super_panel 实时段(盘中每 3 秒)
  const fetchRealtime = useCallback(async () => {
    if (!code) return;
    try {
      const { ok, data } = await apiFetch(`/api/v1/stock/super_panel?code=${code}&section=realtime`);
      if (ok) setRealtimeData(data);
    } catch (e) { /* silent */ }
  }, [code]);

  // 切到盘中 tab 时启动 5 秒轮询（页面隐藏时暂停）
  useEffect(() => {
    if (activeTab !== 'intraday') return;
    fetchRealtime();
    const t = setInterval(() => { if (!document.hidden) fetchRealtime(); }, POLL_INTERVAL);
    return () => clearInterval(t);
  }, [activeTab, fetchRealtime]);

  const changePct = quote?.changePct;
  const isUp = changePct == null ? null : changePct >= 0;
  const chgColor = isUp === null ? 'var(--text-secondary)' : (isUp ? '#ef4444' : '#22c55e');

  return (
    <div className="flex flex-col h-full" style={{ background: 'var(--bg-surface)' }}>
      {/* 顶部返回栏 */}
      <div
        className="flex items-center gap-2 px-3 py-2 border-b flex-shrink-0"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        <button
          onClick={() => navigate(-1)}
          className="px-2 py-1 rounded text-sm hover:opacity-80"
          style={{ color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}
        >
          ← 返回
        </button>
        <div className="flex items-center gap-1.5 flex-1 min-w-0">
          <span className="font-bold text-base truncate" style={{ color: 'var(--text-primary)' }}>
            {stockName}
          </span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{code}</span>
          <SinaLink tsCode={code} />
        </div>
        {/* 操作按钮组:加自选 / 模拟买入 */}
        <button
          onClick={toggleWatchlist}
          disabled={watchLoading}
          className="px-2 py-1 rounded text-xs font-medium inline-flex items-center gap-0.5 disabled:opacity-50"
          style={{
            background: inWatchlist ? 'rgba(34,197,94,0.15)' : 'rgba(168,85,247,0.1)',
            color: inWatchlist ? '#22c55e' : '#a855f7',
            border: `1px solid ${inWatchlist ? 'rgba(34,197,94,0.4)' : 'rgba(168,85,247,0.3)'}`,
          }}
          title={inWatchlist ? '点击移除自选' : '点击加入自选股'}
        >
          {watchLoading ? '⏳' : inWatchlist ? '⭐ 已自选' : '☆ 加自选'}
        </button>
        <button
          onClick={gotoSimBuy}
          className="px-2 py-1 rounded text-xs font-medium inline-flex items-center gap-0.5"
          style={{
            background: 'rgba(239,68,68,0.12)',
            color: '#ef4444',
            border: '1px solid rgba(239,68,68,0.4)',
          }}
          title="跳转到模拟盘买入此股"
        >
          💰 买入
        </button>
      </div>

      {/* 头部行情卡 */}
      <div
        className="px-3 py-2 border-b flex-shrink-0 flex items-center gap-4 flex-wrap"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        {quoteLoading ? (
          <span className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</span>
        ) : quote ? (
          <>
            <div className="flex items-baseline gap-1.5">
              <span className="text-2xl font-bold" style={{ color: chgColor }}>
                {quote.price != null ? quote.price.toFixed(2) : '--'}
              </span>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>现价</span>
            </div>
            {quote.change != null && (
              <div className="text-sm font-medium" style={{ color: chgColor }}>
                {quote.change >= 0 ? '+' : ''}{quote.change}
                {changePct != null && ` (${changePct >= 0 ? '+' : ''}${changePct}%)`}
              </div>
            )}
            {sector && (
              <div className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
                板块: {sector}
              </div>
            )}
            {strategyData?.today_strategies?.map(s => {
              const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
              return (
                <div
                  key={s.strategy_key}
                  className="text-xs px-1.5 py-0.5 rounded font-medium"
                  style={{ background: c.bg, color: c.color, border: `1px solid ${c.border}` }}
                  title={`${s.strategy_name} 评分${s.score}`}
                  onClick={() => setActiveTab('strategy')}
                >
                  {s.icon} {s.strategy_name} {s.score}
                </div>
              );
            })}
            {quote.yesterdayClose != null && (
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                昨收 {quote.yesterdayClose.toFixed(2)}
              </div>
            )}
          </>
        ) : (
          <span className="text-sm" style={{ color: 'var(--text-muted)' }}>暂无行情</span>
        )}
      </div>

      {/* Tab 栏 */}
      <div
        className="flex gap-1 px-2 border-b flex-shrink-0"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        {TABS.map(t => {
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setActiveTab(t.key)}
              className="px-3 py-2 text-sm font-medium relative transition-colors"
              style={{
                color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                borderBottom: active ? '2px solid #a855f7' : '2px solid transparent',
                marginBottom: '-1px',
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-hidden" style={{ minHeight: 0 }}>
        {/* Tab1 K线 */}
        {activeTab === 'kline' && (
          <div className="h-full grid gap-1.5 p-1.5" style={{ gridTemplateColumns: '1fr 1fr', minHeight: 0 }}>
            <div className="overflow-hidden" style={{ minWidth: 0 }}>
              <KLineChart stockCode={code} stockName={stockName} />
            </div>
            <div className="overflow-hidden" style={{ minWidth: 0 }}>
              <IntradayPanel code={code} />
            </div>
          </div>
        )}

        {/* Tab2 盘中实时(双轨制聚合) */}
        {activeTab === 'intraday' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            {/* 实时大盘(5秒刷新) */}
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between mb-2">
                <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>📊 盘中实时（5秒刷新）</h3>
                {realtimeData?.source_health?.realtime && (
                  <span
                    className="px-2 py-0.5 rounded text-[10px]"
                    style={{
                      background: realtimeData.source_health.realtime === 'live' ? 'rgba(34,197,94,0.15)' : 'rgba(107,114,128,0.15)',
                      color: realtimeData.source_health.realtime === 'live' ? '#22c55e' : '#6b7280',
                    }}
                  >
                    {realtimeData.source_health.realtime === 'live' ? '🟢 LIVE' :
                     realtimeData.source_health.realtime === 'closed' ? '⚪ 已收盘' : '🟡 待采集'}
                  </span>
                )}
              </div>
              {realtimeData?.realtime_intraday?.available ? (
                <IntradayLive data={realtimeData.realtime_intraday} />
              ) : (
                <div className="text-center py-4 text-sm" style={{ color: 'var(--text-muted)' }}>
                  {realtimeData?.realtime_intraday?.message || '等待实时数据...'}
                </div>
              )}
            </div>

            {/* 盘后静态底牌(只拉1次) */}
            {superPanel?.post_market_base && (
              <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <h3 className="text-sm font-semibold mb-2" style={{ color: 'var(--text-primary)' }}>🎯 盘后底牌</h3>
                <PostMarketBase data={superPanel.post_market_base} />
              </div>
            )}
          </div>
        )}

        {/* Tab2 资讯搜索 */}
        {activeTab === 'news' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <form
                onSubmit={e => { e.preventDefault(); runNewsSearch(); }}
                className="flex gap-2 mb-2"
              >
                <input
                  type="text"
                  value={newsQuery}
                  onChange={e => setNewsQuery(e.target.value)}
                  placeholder={`${stockName}最新公告`}
                  className="flex-1 px-3 py-1.5 rounded-lg border text-sm outline-none"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                />
                <button
                  type="submit"
                  disabled={newsLoading}
                  className="px-4 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap"
                  style={{ background: newsLoading ? 'rgba(234,179,8,0.4)' : '#eab308', color: '#fff', opacity: newsLoading ? 0.7 : 1 }}
                >
                  {newsLoading ? '搜索中...' : '🔍 搜索'}
                </button>
              </form>
              <div className="flex flex-wrap gap-1">
                {NEWS_QUICK.map(q => (
                  <button
                    key={q}
                    onClick={() => {
                      const full = `${stockName}${q}`;
                      setNewsQuery(full);
                      runNewsSearch(full);
                    }}
                    className="px-2 py-0.5 rounded text-[11px] border"
                    style={{ borderColor: 'rgba(234,179,8,0.3)', color: 'var(--text-secondary)', background: 'rgba(234,179,8,0.05)' }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            {newsError && (
              <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>
                ⚠ {newsError}
              </div>
            )}

            {newsLoading && (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                加载中... 妙想API调用中
              </div>
            )}

            {newsResult && !newsLoading && (
              <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="text-xs mb-2" style={{ color: 'var(--text-muted)' }}>
                  搜索: <strong style={{ color: 'var(--text-primary)' }}>{newsResult.query}</strong>
                </div>
                {newsResult.content ? (
                  <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                    {newsResult.content}
                  </div>
                ) : (
                  <div className="text-sm" style={{ color: 'var(--text-muted)' }}>未找到相关资讯</div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab3 金融数据 */}
        {activeTab === 'data' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <form
                onSubmit={e => { e.preventDefault(); runDataQuery(); }}
                className="flex gap-2 mb-2"
              >
                <input
                  type="text"
                  value={dataQuery}
                  onChange={e => setDataQuery(e.target.value)}
                  placeholder={`${stockName}最新价`}
                  className="flex-1 px-3 py-1.5 rounded-lg border text-sm outline-none"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                />
                <button
                  type="submit"
                  disabled={dataLoading}
                  className="px-4 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap"
                  style={{ background: dataLoading ? 'rgba(234,179,8,0.4)' : '#eab308', color: '#fff', opacity: dataLoading ? 0.7 : 1 }}
                >
                  {dataLoading ? '查询中...' : '📊 查询'}
                </button>
              </form>
              <div className="flex flex-wrap gap-1">
                {DATA_QUICK.map(q => (
                  <button
                    key={q}
                    onClick={() => {
                      const full = `${stockName}${q}`;
                      setDataQuery(full);
                      runDataQuery(full);
                    }}
                    className="px-2 py-0.5 rounded text-[11px] border"
                    style={{ borderColor: 'rgba(234,179,8,0.3)', color: 'var(--text-secondary)', background: 'rgba(234,179,8,0.05)' }}
                  >
                    {q}
                  </button>
                ))}
              </div>
            </div>

            {dataError && (
              <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>
                ⚠ {dataError}
              </div>
            )}

            {dataLoading && (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                加载中... 妙想API调用中
              </div>
            )}

            {dataResult && !dataLoading && (
              <div className="space-y-3">
                {dataResult.condition && (
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    查询条件: <strong style={{ color: 'var(--text-primary)' }}>{dataResult.condition}</strong>
                    {dataResult.total_rows != null && (
                      <> · 共 <strong style={{ color: '#ef4444' }}>{dataResult.total_rows}</strong> 行</>
                    )}
                  </div>
                )}
                {dataResult.tables && dataResult.tables.length > 0 ? (
                  dataResult.tables.map((table, ti) => (
                    <div key={ti} className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                      {table.sheet_name && (
                        <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>{table.sheet_name}</h3>
                      )}
                      <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                        <table className="w-full text-sm">
                          <thead className="sticky top-0 z-10">
                            <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                              {(table.fieldnames || []).map(col => (
                                <th key={col} className="text-left py-2 px-3 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{col}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {(table.rows || []).map((row, ri) => (
                              <tr key={ri} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                                {(table.fieldnames || []).map(col => (
                                  <td key={col} className="py-2 px-3 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{row[col] ?? '-'}</td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  ))
                ) : (
                  <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                    {dataResult.error || '未找到相关数据'}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* Tab4 搜索历史 */}
        {activeTab === 'history' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            {historyLoading ? (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                加载中...
              </div>
            ) : (
              <>
                <HistorySection
                  title="资讯搜索历史"
                  items={newsHistory}
                  emptyText="暂无资讯搜索历史"
                />
                <HistorySection
                  title="金融数据查询历史"
                  items={dataHistory}
                  emptyText="暂无金融数据查询历史"
                />
              </>
            )}
          </div>
        )}

        {/* Tab 策略标签 */}
        {activeTab === 'strategy' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            {strategyLoading ? (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                加载中...
              </div>
            ) : !strategyData || (strategyData.today_count === 0 && strategyData.history.length === 0) ? (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                近 10 天未命中任何策略
              </div>
            ) : (
              <>
                {/* 今日命中 */}
                <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                  <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
                    今日命中 {strategyData.today_count} 个策略
                  </h3>
                  {strategyData.today_count === 0 ? (
                    <div className="text-sm py-2 text-center" style={{ color: 'var(--text-muted)' }}>今日未命中</div>
                  ) : (
                    <div className="space-y-2">
                      {strategyData.today_strategies.map(s => {
                        const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
                        const d = s.detail || {};
                        return (
                          <div key={s.strategy_key} className="rounded-lg border p-2.5" style={{ borderColor: c.border, background: c.bg }}>
                            <div className="flex items-center justify-between mb-1.5">
                              <div className="flex items-center gap-2">
                                <span className="text-sm font-bold" style={{ color: c.color }}>{s.icon} {s.strategy_name}</span>
                                <span className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ background: c.color, color: '#fff' }}>评分 {s.score}</span>
                              </div>
                              {s.exit_signal && (
                                <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>
                                  退出: {s.exit_signal}
                                </span>
                              )}
                            </div>
                            <div className="grid grid-cols-3 gap-2 text-xs" style={{ color: 'var(--text-secondary)' }}>
                              {d['20day_gain'] != null && <div>20日涨幅: <strong style={{ color: d['20day_gain'] >= 20 ? '#ef4444' : 'var(--text-primary)' }}>{d['20day_gain']}%</strong></div>}
                              {d.deviation != null && <div>偏离MA: <strong>{d.deviation}%</strong></div>}
                              {d.rsi != null && <div>RSI: <strong style={{ color: d.rsi > 70 ? '#ef4444' : d.rsi < 30 ? '#22c55e' : 'var(--text-primary)' }}>{d.rsi}</strong></div>}
                              {d.change_pct != null && <div>当日涨幅: <strong style={{ color: d.change_pct >= 0 ? '#ef4444' : '#22c55e' }}>{d.change_pct >= 0 ? '+' : ''}{d.change_pct}%</strong></div>}
                              {d.vol_ratio != null && <div>量比: <strong>{d.vol_ratio}%</strong></div>}
                              {d.lower_shadow != null && <div>下影线: <strong>{d.lower_shadow}%</strong></div>}
                              {d.ma_spread != null && <div>MA排列强度: <strong>{d.ma_spread}%</strong></div>}
                              {d.bias_20 != null && <div>Bias: <strong>{d.bias_20}</strong></div>}
                              {d.continuity_days != null && <div>资金连续: <strong>{d.continuity_days}天</strong></div>}
                              {d.close != null && <div>收盘价: <strong>{d.close}</strong></div>}
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>

                {/* 历史命中 */}
                {strategyData.history.length > 0 && (
                  <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                    <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
                      近 10 天命中历史（{strategyData.history.length} 天）
                    </h3>
                    <div className="space-y-1.5">
                      {strategyData.history.map(h => (
                        <div key={h.trade_date} className="flex items-center gap-2 rounded-lg border px-2.5 py-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
                          <span className="text-xs font-medium whitespace-nowrap" style={{ color: 'var(--text-muted)', minWidth: 80 }}>{h.trade_date}</span>
                          <div className="flex flex-wrap gap-1">
                            {h.strategies.map(s => {
                              const c = STRATEGY_TAG_COLORS[s.strategy_key] || { bg: 'rgba(168,85,247,0.1)', color: '#a855f7', border: 'rgba(168,85,247,0.3)' };
                              return (
                                <span key={s.strategy_key} className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ background: c.bg, color: c.color, border: `1px solid ${c.border}` }}>
                                  {s.icon} {s.strategy_name} {s.score}
                                </span>
                              );
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {/* Tab5 AI分析 */}
        {activeTab === 'ai' && (
          <div className="h-full overflow-y-auto p-3 space-y-3">
            {aiLoading ? (
              <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                加载中...
              </div>
            ) : (
              <>
                <div className="rounded-xl border p-3 text-sm" style={{ borderColor: 'rgba(168,85,247,0.3)', background: 'rgba(168,85,247,0.05)', color: 'var(--text-secondary)' }}>
                  💡 AI全面分析功能即将上线，当前已沉淀该股票的
                  <strong style={{ color: '#a855f7' }}> {aiStats?.news_count ?? 0} </strong>
                  条资讯搜索 +
                  <strong style={{ color: '#a855f7' }}> {aiStats?.data_count ?? 0} </strong>
                  条金融数据查询记录
                </div>

                {aiAnalysis ? (
                  <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                    <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>已沉淀的AI分析结果</h3>
                    {typeof aiAnalysis === 'string' ? (
                      <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                        {aiAnalysis}
                      </div>
                    ) : aiAnalysis.content ? (
                      <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                        {aiAnalysis.content}
                      </div>
                    ) : (
                      <pre className="text-xs whitespace-pre-wrap" style={{ color: 'var(--text-muted)' }}>
                        {JSON.stringify(aiAnalysis, null, 2)}
                      </pre>
                    )}
                  </div>
                ) : (
                  <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                    暂无AI分析结果
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// 盘中实时数据展示（5秒刷新）
function IntradayLive({ data }) {
  const pct = data.pct_chg;
  const isUp = pct == null ? null : pct >= 0;
  const pctColor = isUp === null ? 'var(--text-secondary)' : isUp ? '#ef4444' : '#22c55e';
  const activeRatio = data.large_order_active_ratio || 0;
  const ratioColor = activeRatio > 60 ? '#ef4444' : activeRatio > 40 ? '#eab308' : '#22c55e';
  return (
    <div className="space-y-2">
      {/* 价格 + 涨跌幅 */}
      <div className="flex items-baseline gap-3">
        <span className="text-2xl font-bold" style={{ color: pctColor }}>
          {data.current_price?.toFixed(2) || '—'}
        </span>
        <span className="text-base font-semibold" style={{ color: pctColor }}>
          {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}
        </span>
        {data.last_close > 0 && (
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            昨收 {data.last_close.toFixed(2)}
          </span>
        )}
      </div>
      {/* 关键指标 grid */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        <Metric label="换手率" value={data.turnover_rate ? `${data.turnover_rate.toFixed(2)}%` : '—'} />
        <Metric label="主力净流入" value={data.main_force_inflow ? `${(data.main_force_inflow / 10000).toFixed(0)}万` : '—'} />
        <Metric label="成交量" value={data.volume ? `${(data.volume / 10000).toFixed(0)}万手` : '—'} />
      </div>
      {/* 大单主动率 + 千单频次 */}
      <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
        <div className="flex items-center justify-between mb-1">
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>大单主动买入比</span>
          <span className="text-sm font-bold" style={{ color: ratioColor }}>{activeRatio.toFixed(1)}%</span>
        </div>
        <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.2)' }}>
          <div
            className="h-full transition-all"
            style={{ width: `${activeRatio}%`, background: ratioColor }}
          />
        </div>
        <div className="flex items-center justify-between mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          <span>近3秒买 {data.large_buy_count_3s} / 卖 {data.large_sell_count_3s}</span>
          <span>千单/分 {data.thousand_order_count_per_min || 0}</span>
        </div>
      </div>
      {/* 承接评价 */}
      <div className="text-xs px-2 py-1.5 rounded" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
        {data.support_level_eval || '—'}
      </div>
      {/* 盘口 */}
      {data.bid_price_1 > 0 && (
        <div className="grid grid-cols-2 gap-1 text-[10px]">
          <div className="px-2 py-1 rounded" style={{ background: 'rgba(239,68,68,0.08)' }}>
            <span style={{ color: '#ef4444' }}>买一 {data.bid_price_1?.toFixed(2)}</span>
            <span className="ml-1" style={{ color: 'var(--text-muted)' }}>{data.bid_vol_1 || 0}手</span>
          </div>
          <div className="px-2 py-1 rounded" style={{ background: 'rgba(34,197,94,0.08)' }}>
            <span style={{ color: '#22c55e' }}>卖一 {data.ask_price_1?.toFixed(2)}</span>
            <span className="ml-1" style={{ color: 'var(--text-muted)' }}>{data.ask_vol_1 || 0}手</span>
          </div>
        </div>
      )}
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="rounded p-1.5" style={{ background: 'var(--bg-surface)' }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{value}</div>
    </div>
  );
}

// 盘后静态底牌展示（只拉1次）
function PostMarketBase({ data }) {
  const score = data.quant_score;
  const scoreColor = score == null ? '#6b7280' : score >= 80 ? '#ef4444' : score >= 60 ? '#eab308' : '#22c55e';
  return (
    <div className="space-y-2 text-xs">
      {/* 量化分 */}
      <div className="flex items-center gap-3">
        <span className="px-2 py-1 rounded font-bold" style={{ background: `${scoreColor}20`, color: scoreColor }}>
          游资分 {score ?? '—'}
        </span>
        <span style={{ color: 'var(--text-muted)' }}>共振 {data.resonance_count} 位</span>
        <span style={{ color: 'var(--text-muted)' }}>净买 {data.total_net_buy_wan ? `${(data.total_net_buy_wan / 10000).toFixed(2)}亿` : '—'}</span>
      </div>
      {data.concept_sector && (
        <div className="text-xs">
          板块: <span style={{ color: '#a855f7' }}>{data.concept_sector}</span>
          {data.sector_hot_money_count > 0 && (
            <span className="ml-2" style={{ color: 'var(--text-muted)' }}>同板块共振 {data.sector_hot_money_count}</span>
          )}
        </div>
      )}
      {/* 昨日 boss 列表 */}
      {data.yesterday_bosses && data.yesterday_bosses.length > 0 && (
        <div>
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>游资名单</div>
          <div className="space-y-1">
            {data.yesterday_bosses.slice(0, 6).map((b, i) => (
              <div key={i} className="flex items-center justify-between text-xs">
                <span style={{ color: 'var(--text-primary)' }}>{b.name}</span>
                <span className="flex items-center gap-1.5">
                  <span
                    className="px-1 rounded text-[10px]"
                    style={{
                      background: b.action === '新进' ? 'rgba(239,68,68,0.15)' : b.action === '砸盘' ? 'rgba(34,197,94,0.15)' : 'rgba(107,114,128,0.15)',
                      color: b.action === '新进' ? '#ef4444' : b.action === '砸盘' ? '#22c55e' : '#6b7280',
                    }}
                  >
                    {b.action}
                  </span>
                  <span style={{ color: b.net_buy_wan >= 0 ? '#ef4444' : '#22c55e' }}>
                    {b.net_buy_wan >= 0 ? '+' : ''}{(b.net_buy_wan / 10000).toFixed(2)}亿
                  </span>
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function HistorySection({ title, items, emptyText }) {
  const list = Array.isArray(items) ? items : (items?.items || items?.history || items?.records || []);
  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>{title}</h3>
      {list.length === 0 ? (
        <div className="text-sm py-3 text-center" style={{ color: 'var(--text-muted)' }}>{emptyText}</div>
      ) : (
        <div className="space-y-1.5">
          {list.map((item, i) => (
            <div
              key={i}
              className="rounded-lg border px-2.5 py-1.5 text-sm"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-medium truncate" style={{ color: 'var(--text-primary)' }}>
                  {item.query || item.keyword || item.title || item.query_text || '—'}
                </span>
                <span className="text-[10px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
                  {item.created_at || item.time || item.timestamp || item.updated_at || ''}
                </span>
              </div>
              {(item.summary || item.content || item.abstract || item.snippet) && (
                <div className="text-xs mt-1 line-clamp-2" style={{ color: 'var(--text-muted)' }}>
                  {item.summary || item.content || item.abstract || item.snippet}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
