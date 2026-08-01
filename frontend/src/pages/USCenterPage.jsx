/**
 * 美股智能交易系统（按《美股智能交易系统 V1.0》部署）
 * 路由: /us-market  (?tab=market|env|sectors|strategy|scores|risk)
 *
 * 模块：
 *  - 行情总览：指数 + 技术筛选 + 一键跟踪（复用 GlobalMarketPage）
 *  - 市场环境：Market Score 0-100（大盘趋势 + 市场宽度 + VIX）
 *  - 行业轮动：Sector Rotation（涨幅30/资金30/趋势20/强度20）
 *  - 策略：青龙趋势 / 白虎突破 / 回踩 / 财报 / 低估反转 / ETF 轮动
 *  - 评分：100 分模型（趋势30/基本面25/资金20/动量15/风险10）+ 7 维状态
 *  - 仓位：按市场环境 + 个股评分的仓位管理
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import {
  estimateFundamentals, usScore, usStatus, usStrategies, usMarketEnv, usSectors, usStatusColor,
  fetchFundamentals, mergeFundamentals,
} from '../utils/marketScore';
import GlobalMarketPage from './GlobalMarketPage';


const US_STRATEGY_DEFS = [
  { key: '青龙趋势', desc: 'MA20>MA50>MA200 · 站上均线 · 资金持续流入' },
  { key: '白虎突破', desc: '突破 60 日新高 · 量>150% 均量 · RSI 50-70' },
  { key: '回踩', desc: '上涨趋势 · 回调约 10% · 缩量 · 均线支撑' },
  { key: '财报', desc: 'EPS 超预期 · Revenue 超预期 · 上调指引' },
  { key: '低估反转', desc: 'PE 较低 · ROE 优秀 · 基本面稳定 · 资金流入' },
  { key: 'ETF轮动', desc: 'QQQ / SMH / XLK / XLE / XLV 轮动' },
];

function useEnhanced(market) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState('');
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/api/global-market/watchlist-enhanced/${market}`, {}, 30000, 0);
      if (res.ok) { setItems(res.data.items || []); setUpdated(res.data.updated_at || ''); }
    } catch {}
    setLoading(false);
  }, [market]);
  useEffect(() => { load(); }, [load]);
  return { items, loading, updated, reload: load };
}

function useOverview(market) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/api/global-market/overview/${market}`, {}, 15000, 0);
      if (res.ok) setData(res.data);
    } catch {}
    setLoading(false);
  }, [market]);
  useEffect(() => { load(); }, [load]);
  return { data, loading, reload: load };
}

const pctColor = (v) => (v == null || isNaN(Number(v))) ? '#6b7280' : Number(v) > 0 ? UP_COLOR : Number(v) < 0 ? DOWN_COLOR : '#6b7280';
const fmtPct = (v, sign = true) => {
  if (v == null) return '—'; const n = Number(v);
  if (n === 0) return '0.00%';
  return `${sign && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

// 真实基本面（腾讯 gtimg），页面级只拉一次
function useMarketReal(market) {
  const [fundamentals, setFundamentals] = useState(null);
  const [realUpdated, setRealUpdated] = useState('');
  const load = useCallback(async () => {
    const f = await fetchFundamentals(market);
    if (f) setFundamentals(f);
    setRealUpdated(new Date().toLocaleString('zh-CN', { hour12: false }));
  }, [market]);
  useEffect(() => { load(); }, [load]);
  return { fundamentals, realUpdated, reload: load };
}

function RealBadge({ real }) {
  if (!real || !Object.keys(real).length) return null;
  return (
    <span className="px-1.5 py-0.5 rounded text-[9px] font-medium" style={{ background: 'rgba(34,197,94,0.14)', color: '#22c55e' }}>
      实时·腾讯
    </span>
  );
}

function ScoreBar({ label, value, max, color = 'var(--accent-blue)' }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="w-12 text-[10px] shrink-0" style={{ color: 'var(--text-muted)' }}>{label}</span>
      <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-secondary)' }}>
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, (value / max) * 100)}%`, background: color }} />
      </div>
      <span className="w-7 text-right text-[10px] font-medium" style={{ color: 'var(--text-secondary)' }}>{value}</span>
    </div>
  );
}

function MarketEnvTab({ market }) {
  const { data, loading } = useOverview(market);
  const env = useMemo(() => usMarketEnv(data?.indices || [], data?.stats || {}), [data]);
  const envColor = env.total >= 60 ? UP_COLOR : env.total >= 40 ? '#f59e0b' : DOWN_COLOR;
  const posRange = env.total >= 90 ? '80% - 100%' : env.total >= 70 ? '50% - 80%' : env.total >= 50 ? '30% - 50%' : '降低仓位 (<30%)';

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <h2 className="text-base font-bold mb-1">🌐 美股市场环境评分</h2>
      <p className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>大盘趋势 + 市场宽度 + VIX 风险 → Market Score 0-100（VIX 为估算）</p>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-3">
        {[
          { label: '综合评分', v: env.total, c: envColor, sub: env.label },
          { label: '大盘趋势', v: env.trend, c: 'var(--accent-blue)', sub: '/50' },
          { label: '市场宽度', v: env.breadth, c: '#a855f7', sub: '/30' },
          { label: 'VIX 风险', v: env.vix, c: env.vix < 20 ? UP_COLOR : '#f97316', sub: `分 ${env.vixScore}` },
        ].map((s) => (
          <div key={s.label} className="p-3 rounded text-center" style={{ background: `${String(s.c)}10`, border: `1px solid ${String(s.c)}30` }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.label}</div>
            <div className="text-2xl font-bold" style={{ color: s.c }}>{s.v}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{s.sub}</div>
          </div>
        ))}
      </div>

      <div className="p-3 rounded mb-3" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="text-xs font-bold mb-1">📊 仓位建议（按市场环境）</div>
        <div className="text-sm" style={{ color: envColor }}>当前市场评分 {env.total}（{env.label}）→ 建议总仓位 <b>{posRange}</b></div>
        <div className="mt-2 grid grid-cols-4 gap-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          <span>≥90：80-100%</span><span>70-90：50-80%</span><span>50-70：30-50%</span><span>&lt;50：降至 30% 以下</span>
        </div>
      </div>

      {loading && !data && <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>}
      {data && (
        <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="p-2.5 border-b font-bold text-xs" style={{ borderColor: 'var(--border-color)' }}>主要指数</div>
          {(data.indices || []).map((idx) => (
            <div key={idx.code} className="flex items-center justify-between px-2.5 py-1.5 border-b text-xs" style={{ borderColor: 'var(--border-color)' }}>
              <span className="font-medium">{idx.name} <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{idx.code}</span></span>
              <span className="font-bold" style={{ color: pctColor(idx.change_pct) }}>{idx.price != null ? Number(idx.price).toFixed(2) : '—'} ({fmtPct(idx.change_pct)})</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SectorsTab() {
  const rows = useMemo(() => usSectors().sort((a, b) => b.score - a.score), []);
  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <h2 className="text-base font-bold mb-1">🔥 美股行业轮动（Sector Rotation）</h2>
      <p className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>行业评分 = 涨幅30% + 资金30% + 趋势20% + 强度20%（估算，仅演示）</p>
      <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr_1fr_0.8fr] gap-2 p-2.5 border-b font-medium text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
          <span>行业</span><span className="text-right">涨幅</span><span className="text-right">资金</span><span className="text-right">趋势</span><span className="text-right">强度</span><span className="text-right">综合</span>
        </div>
        {rows.map((r, i) => (
          <div key={r.name} className="grid grid-cols-[1.4fr_1fr_1fr_1fr_1fr_0.8fr] gap-2 px-2.5 py-1.5 border-b items-center text-xs" style={{ borderColor: 'var(--border-color)' }}>
            <span className="font-medium flex items-center gap-1"><span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>{r.name}</span>
            <span className="text-right" style={{ color: r.gainScore >= 60 ? UP_COLOR : 'var(--text-secondary)' }}>{r.gainScore}</span>
            <span className="text-right" style={{ color: r.capitalFlow >= 50 ? UP_COLOR : 'var(--text-secondary)' }}>{r.capitalFlow}</span>
            <span className="text-right" style={{ color: 'var(--text-secondary)' }}>{r.trendScore}</span>
            <span className="text-right" style={{ color: 'var(--text-secondary)' }}>{r.strengthScore}</span>
            <span className="text-right font-bold" style={{ color: i === 0 ? UP_COLOR : 'var(--text-primary)' }}>{r.score}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function StrategiesTab({ market, fundamentals }) {
  const { items, loading } = useEnhanced(market);
  const enriched = useMemo(() => items
    .filter((it) => it.price != null)
    .map((it) => {
      const realObj = fundamentals ? fundamentals[it.code] : null;
      const { f } = mergeFundamentals(market, it.code, realObj);
      return { ...it, f, strategies: usStrategies(it, f) };
    }), [items, fundamentals]);

  const byStrategy = useMemo(() => US_STRATEGY_DEFS.map((d) => ({
    ...d, stocks: enriched.filter((e) => e.strategies.includes(d.key)),
  })), [enriched]);

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <h2 className="text-base font-bold mb-1">🎯 美股交易策略</h2>
      <p className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>6 大策略扫描关注池；技术条件为真实行情，PE/估值分位为腾讯实时，ROE/增速/资金流为估算</p>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-2">
        {byStrategy.map((s) => (
          <div key={s.key} className="p-3 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center justify-between mb-1">
              <span className="text-sm font-bold" style={{ color: 'var(--accent-blue)' }}>{s.key}</span>
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: s.stocks.length ? 'rgba(239,68,68,0.12)' : 'var(--bg-secondary)', color: s.stocks.length ? UP_COLOR : 'var(--text-muted)' }}>{s.stocks.length} 只命中</span>
            </div>
            <div className="text-[10px] mb-2" style={{ color: 'var(--text-muted)' }}>{s.desc}</div>
            <div className="flex flex-wrap gap-1">
              {s.stocks.length ? s.stocks.map((st) => (
                <span key={st.code} className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: 'rgba(239,68,68,0.1)', color: UP_COLOR }}>{st.name}</span>
              )) : <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>暂无命中</span>}
            </div>
          </div>
        ))}
      </div>

      {loading && enriched.length === 0 && <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>扫描中…</div>}
    </div>
  );
}

function ScoresTab({ market, fundamentals, realUpdated }) {
  const { items, loading, updated, reload } = useEnhanced(market);
  const rows = useMemo(() => items
    .filter((it) => it.price != null)
    .map((it) => {
      const realObj = fundamentals ? fundamentals[it.code] : null;
      const { f, real } = mergeFundamentals(market, it.code, realObj);
      const s = usScore(it, f);
      return { ...it, f, real, score: s, status: usStatus(s, it, f), strategies: usStrategies(it, f) };
    })
    .sort((a, b) => b.score.total - a.score.total), [items, fundamentals]);

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="text-base font-bold">🧮 美股智能评分（100 分模型）</h2>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>趋势 30 · 基本面 25 · 资金 20 · 动量 15 · 风险 10 ｜ PE/估值分位为腾讯实时，ROE/增速/资金流为估算</p>
        </div>
        <div className="flex items-center gap-2">
          {realUpdated && <span className="text-[10px]" style={{ color: '#22c55e' }}>🟢 实时 {realUpdated}</span>}
          {updated && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🕐 行情 {updated}</span>}
          <button onClick={reload} className="px-2.5 py-1 rounded text-xs border" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
        </div>
      </div>

      {loading && rows.length === 0 ? (
        <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载评分中…</div>
      ) : (
        <div className="space-y-2">
          {rows.map((r) => (
            <div key={r.code} className="p-3 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <span className="font-bold text-sm">{r.name}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{r.code}</span>
                  <RealBadge real={r.real} />
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: `${usStatusColor(r.status)}20`, color: usStatusColor(r.status) }}>{r.status}</span>
                  {r.strategies.map((s) => (
                    <span key={s} className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(239,68,68,0.12)', color: UP_COLOR }}>{s}</span>
                  ))}
                </div>
                <div className="text-right">
                  <div className="text-lg font-bold" style={{ color: r.score.total >= 70 ? UP_COLOR : r.score.total >= 55 ? '#f59e0b' : 'var(--text-secondary)' }}>{r.score.total}</div>
                  <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>总分 / 100</div>
                </div>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1">
                <ScoreBar label="趋势" value={r.score.trend} max={30} color="#ef4444" />
                <ScoreBar label="基本面" value={r.score.fundamental} max={25} color="#3b82f6" />
                <ScoreBar label="资金" value={r.score.capital} max={20} color="#a855f7" />
                <ScoreBar label="动量" value={r.score.momentum} max={15} color="#22c55e" />
                <ScoreBar label="风险" value={r.score.risk} max={10} color="#f59e0b" />
                <div className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  <span className="w-12 shrink-0">PE</span>
                  <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>{r.f.pe != null ? r.f.pe.toFixed(1) : '—'}{r.real && r.real.pe != null ? '' : ' (估)'}</span>
                  <span className="ml-auto">RSI {r.rsi != null ? r.rsi.toFixed(0) : '—'} · 偏离 {r.deviation != null ? `${r.deviation > 0 ? '+' : ''}${r.deviation}%` : '—'}</span>
                </div>
              </div>
            </div>
          ))}
          {rows.length === 0 && <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无有效数据</div>}
        </div>
      )}
    </div>
  );
}

function RiskTab({ market, fundamentals }) {
  const { data } = useOverview(market);
  const { items } = useEnhanced(market);
  const env = useMemo(() => usMarketEnv(data?.indices || [], data?.stats || {}), [data]);
  const rows = useMemo(() => items
    .filter((it) => it.price != null)
    .map((it) => {
      const realObj = fundamentals ? fundamentals[it.code] : null;
      const { f } = mergeFundamentals(market, it.code, realObj);
      const s = usScore(it, f);
      return { ...it, score: s, status: usStatus(s, it, f) };
    })
    .sort((a, b) => b.score.total - a.score.total), [items, fundamentals]);

  const marketPos = env.total >= 90 ? '80%-100%' : env.total >= 70 ? '50%-80%' : env.total >= 50 ? '30%-50%' : '≤30%（防御）';

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <h2 className="text-base font-bold mb-1">🛡️ 仓位管理</h2>
      <p className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>市场环境评分决定总仓位；个股评分决定单股仓位（核心≤15% / 普通 5-10%）</p>

      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="p-3 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>市场环境总仓位</div>
          <div className="text-xl font-bold" style={{ color: env.total >= 60 ? UP_COLOR : '#f59e0b' }}>{marketPos}</div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Market Score {env.total}（{env.label}）</div>
        </div>
        <div className="p-3 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>单股仓位规则</div>
          <div className="text-sm font-bold mt-1" style={{ color: 'var(--text-primary)' }}>核心股票 ≤ 15%</div>
          <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>普通股票 5% - 10%</div>
        </div>
      </div>

      <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="grid grid-cols-[1.4fr_1fr_1fr_1fr] gap-2 p-2.5 border-b font-medium text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
          <span>个股</span><span className="text-right">评分</span><span className="text-right">状态</span><span className="text-right">建议仓位</span>
        </div>
        {rows.map((r) => {
          const pos = r.score.total >= 75 ? '≤15%（核心）' : r.score.total >= 60 ? '8%-10%' : '5%';
          return (
            <div key={r.code} className="grid grid-cols-[1.4fr_1fr_1fr_1fr] gap-2 px-2.5 py-1.5 border-b items-center text-xs" style={{ borderColor: 'var(--border-color)' }}>
              <span className="font-medium">{r.name}</span>
              <span className="text-right font-bold" style={{ color: r.score.total >= 70 ? UP_COLOR : 'var(--text-secondary)' }}>{r.score.total}</span>
              <span className="text-right"><span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: `${usStatusColor(r.status)}20`, color: usStatusColor(r.status) }}>{r.status}</span></span>
              <span className="text-right" style={{ color: 'var(--text-secondary)' }}>{pos}</span>
            </div>
          );
        })}
        {rows.length === 0 && <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>暂无数据</div>}
      </div>
    </div>
  );
}

export default function USCenterPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'market';
  const { fundamentals, realUpdated } = useMarketReal('US');

  return (
    <div style={{ minHeight: '100%' }}>
      <div>
        {tab === 'market' && <GlobalMarketPage market="US" />}
        {tab === 'env' && <MarketEnvTab market="US" />}
        {tab === 'sectors' && <SectorsTab />}
        {tab === 'strategy' && <StrategiesTab market="US" fundamentals={fundamentals} />}
        {tab === 'scores' && <ScoresTab market="US" fundamentals={fundamentals} realUpdated={realUpdated} />}
        {tab === 'risk' && <RiskTab market="US" fundamentals={fundamentals} />}
      </div>
    </div>
  );
}
