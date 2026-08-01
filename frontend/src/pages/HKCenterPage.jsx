/**
 * 港股研究中心（按《Ai-Robot 港股研究中心技术架构设计 V1.0》部署）
 * 路由: /hk-market  (?tab=market|scores|south|sectors|strategy)
 *
 * 模块：
 *  - 行情总览：指数 + 技术筛选 + 一键跟踪（复用 GlobalMarketPage）
 *  - 智能评分：100 分模型（基本面30/资金25/估值20/趋势15/催化10）+ 7 维状态体系
 *  - 南向资金：南向净流入 → 行业 → 个股 排序（估算）
 *  - 行业轮动：科技/互联网/半导体/创新药/消费/汽车/金融/能源/地产（估算）
 *  - 策略扫描：南向资金流入 / 价值修复 / 成长趋势 / 高股息（复用 HKStrategyPage）
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useSearchParams } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import {
  estimateFundamentals, hkScore, hkStatus, hkStrategies, hkSectors, hkStatusColor,
  fetchFundamentals, fetchSouthbound, mergeFundamentals,
} from '../utils/marketScore';
import GlobalMarketPage from './GlobalMarketPage';
import HKStrategyPage from './HKStrategyPage';


// 拉取增强行情（含技术指标），供评分/资金/策略模块使用
function useEnhanced(market) {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const [updated, setUpdated] = useState('');
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await apiFetch(`/api/global-market/watchlist-enhanced/${market}`, {}, 30000, 0);
      if (res.ok) {
        setItems(res.data.items || []);
        setUpdated(res.data.updated_at || '');
      }
    } catch {}
    setLoading(false);
  }, [market]);
  useEffect(() => { load(); }, [load]);
  return { items, loading, updated, reload: load };
}

const pctColor = (v) => (v == null || isNaN(Number(v))) ? '#6b7280' : Number(v) > 0 ? UP_COLOR : Number(v) < 0 ? DOWN_COLOR : '#6b7280';
const fmtPct = (v, sign = true) => {
  if (v == null) return '—'; const n = Number(v);
  if (n === 0) return '0.00%';
  return `${sign && n > 0 ? '+' : ''}${n.toFixed(2)}%`;
};

// 真实数据（腾讯 gtimg 基本面 + Eastmoney 南向资金），页面级只拉一次
function useMarketReal(market) {
  const [fundamentals, setFundamentals] = useState(null); // {code: {real:{...}}}
  const [southbound, setSouthbound] = useState(null);     // {totalNet20d, latestNet, byStock}
  const [realUpdated, setRealUpdated] = useState('');
  const load = useCallback(async () => {
    const [f, sb] = await Promise.all([
      market === 'HK' ? fetchFundamentals(market) : fetchFundamentals(market),
      market === 'HK' ? fetchSouthbound() : Promise.resolve(null),
    ]);
    if (f) setFundamentals(f);
    if (market === 'HK' && sb) setSouthbound(sb);
    setRealUpdated(new Date().toLocaleString('zh-CN', { hour12: false }));
  }, [market]);
  useEffect(() => { load(); }, [load]);
  return { fundamentals, southbound, realUpdated, reload: load };
}

// 真实数据徽标
function RealBadge({ real }) {
  if (!real || !Object.keys(real).length) return null;
  return (
    <span className="px-1.5 py-0.5 rounded text-[9px] font-medium" style={{ background: 'rgba(34,197,94,0.14)', color: '#22c55e' }}>
      实时·腾讯
    </span>
  );
}

// 评分分项进度条
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

function ScoresTab({ market, fundamentals, realUpdated }) {
  const { items, loading, updated, reload } = useEnhanced(market);
  const rows = useMemo(() => items
    .filter((it) => it.price != null)
    .map((it) => {
      const realObj = fundamentals ? fundamentals[it.code] : null;
      const { f, real } = mergeFundamentals(market, it.code, realObj);
      const s = hkScore(it, f);
      return { ...it, f, real, score: s, status: hkStatus(s, it, f), strategies: hkStrategies(it, f) };
    })
    .sort((a, b) => b.score.total - a.score.total), [items, fundamentals]);

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="text-base font-bold">🧮 港股智能评分（100 分模型）</h2>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            基本面 30 · 资金 25 · 估值 20 · 趋势 15 · 催化 10 ｜ PE/PB/股息/估值分位为腾讯实时，ROE/增速/南向/资金流为估算
          </p>
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
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: `${hkStatusColor(r.status)}20`, color: hkStatusColor(r.status) }}>{r.status}</span>
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
                <ScoreBar label="基本面" value={r.score.fundamental} max={30} color="#3b82f6" />
                <ScoreBar label="资金" value={r.score.capital} max={25} color="#ef4444" />
                <ScoreBar label="估值" value={r.score.valuation} max={20} color="#a855f7" />
                <ScoreBar label="趋势" value={r.score.trend} max={15} color="#22c55e" />
                <ScoreBar label="催化" value={r.score.catalyst} max={10} color="#f59e0b" />
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

function SouthboundTab({ market, southbound }) {
  const { items, loading } = useEnhanced(market);
  const realTotal = southbound && southbound.totalNet20d != null ? southbound.totalNet20d : null;
  const realLatest = southbound && southbound.latestNet != null ? southbound.latestNet : null;
  const byStock = southbound && southbound.byStock ? southbound.byStock : {};
  const rows = useMemo(() => items
    .map((it) => {
      const est = estimateFundamentals(market, it.code);
      const realNet = byStock[it.code];
      const net = realNet != null ? realNet : est.southNet20d;
      const isReal = realNet != null;
      return { ...it, net, isReal, f: est };
    })
    .sort((a, b) => (b.net) - (a.net)), [items, byStock]);
  const total = realTotal != null ? realTotal : rows.reduce((s, r) => s + (r.net || 0), 0);
  const inflow = rows.filter((r) => (r.net || 0) > 0).length;
  const isReal = southbound && southbound.source === 'eastmoney';

  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div>
          <h2 className="text-base font-bold">💰 南向资金中心</h2>
          <p className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            港股通南向净流入 → 个股排序（{isReal ? '实时·Eastmoney 港股通' : '港股通源暂不可用，回退估算，仅演示'}）
          </p>
        </div>
        {isReal && <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.14)', color: '#22c55e' }}>实时·Eastmoney</span>}
      </div>
      <div className="grid grid-cols-3 gap-2 mb-3">
        {[
          { label: '南向净流入(20日)', v: `${total > 0 ? '+' : ''}${total.toFixed(0)} 亿`, c: total >= 0 ? UP_COLOR : DOWN_COLOR },
          { label: realLatest != null ? '最新一日净买' : '净流入个股数', v: realLatest != null ? `${realLatest > 0 ? '+' : ''}${realLatest.toFixed(0)} 亿` : `${inflow}/${rows.length}`, c: 'var(--accent-blue)' },
          { label: '重点行业', v: '9 类', c: '#a855f7' },
        ].map((s) => (
          <div key={s.label} className="p-2 rounded text-center" style={{ background: `${String(s.c)}10`, border: `1px solid ${String(s.c)}30` }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.label}</div>
            <div className="text-base font-bold" style={{ color: s.c }}>{s.v}</div>
          </div>
        ))}
      </div>

      <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="p-2.5 border-b font-bold text-xs" style={{ borderColor: 'var(--border-color)' }}>📊 个股南向净流入（{isReal ? '港股通持股变化' : '20 日 · 估算'}）</div>
        {loading && rows.length === 0 ? (
          <div className="p-6 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>
        ) : (
          rows.map((r) => {
            const v = r.net || 0;
            const c = v >= 0 ? UP_COLOR : DOWN_COLOR;
            const maxAbs = Math.max(70, ...rows.map((x) => Math.abs(x.net || 0)));
            return (
              <div key={r.code} className="flex items-center gap-2 px-2.5 py-1.5 border-b text-xs" style={{ borderColor: 'var(--border-color)' }}>
                <span className="font-medium w-20 truncate">{r.name}</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-secondary)' }}>
                  <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.abs(v) / maxAbs * 100)}%`, background: c, marginLeft: v < 0 ? `${100 - Math.min(100, Math.abs(v) / maxAbs * 100)}%` : 0 }} />
                </div>
                <span className="w-16 text-right font-medium" style={{ color: c }}>{v > 0 ? '+' : ''}{v.toFixed(0)} 亿</span>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}

function SectorsTab() {
  const rows = useMemo(() => hkSectors().sort((a, b) => b.score - a.score), []);
  return (
    <div className="p-4" style={{ color: 'var(--text-primary)', minHeight: '100%' }}>
      <h2 className="text-base font-bold mb-1">🔥 港股行业轮动</h2>
      <p className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>行业热度 / 资金流 / 趋势 / 估值综合评分（估算，仅演示架构）</p>
      <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="grid grid-cols-[1.2fr_1fr_1fr_1fr_1fr_0.8fr] gap-2 p-2.5 border-b font-medium text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
          <span>行业</span><span className="text-right">热度</span><span className="text-right">资金流(亿)</span><span className="text-right">趋势</span><span className="text-right">估值</span><span className="text-right">综合</span>
        </div>
        {rows.map((r, i) => (
          <div key={r.name} className="grid grid-cols-[1.2fr_1fr_1fr_1fr_1fr_0.8fr] gap-2 px-2.5 py-1.5 border-b items-center text-xs" style={{ borderColor: 'var(--border-color)' }}>
            <span className="font-medium flex items-center gap-1"><span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>{r.name}</span>
            <span className="text-right" style={{ color: r.heatScore >= 70 ? UP_COLOR : 'var(--text-secondary)' }}>{r.heatScore}</span>
            <span className="text-right" style={{ color: r.capitalFlow >= 0 ? UP_COLOR : DOWN_COLOR }}>{r.capitalFlow > 0 ? '+' : ''}{r.capitalFlow}</span>
            <span className="text-right" style={{ color: 'var(--text-secondary)' }}>{r.trendScore}</span>
            <span className="text-right" style={{ color: 'var(--text-secondary)' }}>{r.valuationScore}</span>
            <span className="text-right font-bold" style={{ color: i === 0 ? UP_COLOR : 'var(--text-primary)' }}>{r.score}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function HKCenterPage() {
  const [params, setParams] = useSearchParams();
  const tab = params.get('tab') || 'market';
  const { fundamentals, southbound, realUpdated } = useMarketReal('HK');

  return (
    <div style={{ minHeight: '100%' }}>
      <div>
        {tab === 'market' && <GlobalMarketPage market="HK" />}
        {tab === 'scores' && <ScoresTab market="HK" fundamentals={fundamentals} realUpdated={realUpdated} />}
        {tab === 'south' && <SouthboundTab market="HK" southbound={southbound} />}
        {tab === 'sectors' && <SectorsTab />}
        {tab === 'strategy' && <HKStrategyPage />}
      </div>
    </div>
  );
}
