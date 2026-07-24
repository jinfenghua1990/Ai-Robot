import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

const UP_COLOR = '#ef4444';
const DOWN_COLOR = '#22c55e';
const MUTED = 'var(--text-muted)';

function pctStr(v) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  return n > 0 ? `+${n.toFixed(2)}%` : `${n.toFixed(2)}%`;
}

function pctColor(v) {
  if (v == null || isNaN(v)) return MUTED;
  return Number(v) > 0 ? UP_COLOR : Number(v) < 0 ? DOWN_COLOR : MUTED;
}

function numStr(v) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toLocaleString();
}

export default function TodayPage() {
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [data, setData] = useState(null);
  const [selectedDate, setSelectedDate] = useState('');

  const loadData = useCallback(async (date) => {
    setLoading(true);
    setError(null);
    const params = date ? `?date=${date}` : '';
    try {
      const [marketRes, themesRes, fundflowRes, emotionRes, riskRes, summaryRes] = await Promise.all([
        apiFetch(`/api/market${params}`),
        apiFetch(`/api/themes${params}`),
        apiFetch(`/api/fundflow${params}`),
        apiFetch(`/api/emotion${params}`),
        apiFetch(`/api/risk${params}`),
        apiFetch(`/api/summary${params}`),
      ]);
      setData({
        market: marketRes.ok ? marketRes.data : null,
        themes: themesRes.ok ? themesRes.data : null,
        fundflow: fundflowRes.ok ? fundflowRes.data : null,
        emotion: emotionRes.ok ? emotionRes.data : null,
        risk: riskRes.ok ? riskRes.data : null,
        summary: summaryRes.ok ? summaryRes.data : null,
      });
    } catch (e) {
      setError(e.message || '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadData(selectedDate); }, [selectedDate, loadData]);

  if (loading) return <LoadingView />;
  if (error) return <ErrorView message={error} onRetry={() => loadData(selectedDate)} />;

  const { market, themes, fundflow, emotion, risk, summary } = data || {};

  return (
    <div className="space-y-3">
      {/* 日期选择 + 标题 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>盘中实时</h2>
        <div className="flex items-center gap-2">
          <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)}
            className="px-2 py-1 rounded border text-xs" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
          <button onClick={() => loadData(selectedDate)} className="px-2 py-1 rounded border text-xs hover:opacity-80"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>刷新</button>
        </div>
      </div>

      {/* 指数概览 */}
      <IndexCards indices={market?.indices || []} />

      {/* 市场广度 */}
      <MarketBreadth breadth={market?.breadth} limitUp={market?.limit_up} />

      {/* 题材战场 */}
      <ThemeBattlefield themes={themes} />

      {/* 资金流向 */}
      <FundFlowPanel fundflow={fundflow} />

      {/* 情绪 + 风险 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        <EmotionPanel emotion={emotion} />
        <RiskPanel risk={risk} />
      </div>

      {/* 摘要 */}
      {summary?.text && <SummaryCard summary={summary} />}
    </div>
  );
}

/* ──────────── 子组件 ──────────── */

function LoadingView() {
  return (
    <div className="flex items-center justify-center py-20">
      <div className="text-sm" style={{ color: MUTED }}>加载中...</div>
    </div>
  );
}

function ErrorView({ message, onRetry }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 gap-3">
      <div className="text-sm" style={{ color: '#ef4444' }}>加载失败：{message}</div>
      <button onClick={onRetry} className="px-3 py-1 rounded border text-xs"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>重试</button>
    </div>
  );
}

function IndexCards({ indices }) {
  if (!indices?.length) return null;
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-2">
      {indices.map((idx, i) => (
        <div key={i} className="rounded-lg border p-3 flex flex-col gap-1"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs" style={{ color: MUTED }}>{idx.name || idx.code}</div>
          <div className="text-lg font-bold font-mono" style={{ color: 'var(--text-primary)' }}>
            {idx.price != null ? Number(idx.price).toFixed(2) : '—'}
          </div>
          <div className="text-xs font-mono font-medium" style={{ color: pctColor(idx.change_pct) }}>
            {pctStr(idx.change_pct)}
          </div>
        </div>
      ))}
    </div>
  );
}

function MarketBreadth({ breadth, limitUp }) {
  if (!breadth && !limitUp) return null;
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场广度</div>
      <div className="flex flex-wrap gap-4 text-xs">
        {breadth && (
          <>
            <span><span style={{ color: UP_COLOR }}>上涨 {breadth.up ?? '—'}</span></span>
            <span><span style={{ color: DOWN_COLOR }}>下跌 {breadth.down ?? '—'}</span></span>
            <span style={{ color: MUTED }}>平盘 {breadth.flat ?? '—'}</span>
          </>
        )}
        {limitUp && (
          <>
            <span style={{ color: UP_COLOR }}>涨停 {limitUp.limit_up ?? '—'}</span>
            <span style={{ color: '#eab308' }}>炸板 {limitUp.broken ?? '—'}</span>
            <span style={{ color: DOWN_COLOR }}>跌停 {limitUp.limit_down ?? '—'}</span>
          </>
        )}
      </div>
    </div>
  );
}

function ThemeBattlefield({ themes }) {
  const sections = themes?.sections || themes?.theme_sections || [];
  if (!sections.length) return null;

  const COLORS = {
    main: { bg: 'rgba(239,68,68,0.06)', border: 'rgba(239,68,68,0.15)', color: '#ef4444', label: '主线' },
    watch: { bg: 'rgba(234,179,8,0.06)', border: 'rgba(234,179,8,0.15)', color: '#eab308', label: '观察' },
    alive: { bg: 'rgba(34,197,94,0.06)', border: 'rgba(34,197,94,0.15)', color: '#22c55e', label: '活口' },
  };

  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>题材战场</div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {sections.map((sec, si) => {
          const style = COLORS[sec.type] || COLORS.main;
          const items = sec.items || sec.themes || [];
          return (
            <div key={si} className="rounded-md p-2" style={{ background: style.bg, border: `1px solid ${style.border}` }}>
              <div className="text-xs font-bold mb-1.5" style={{ color: style.color }}>{style.label} ({items.length})</div>
              <div className="space-y-1.5">
                {items.slice(0, 8).map((item, ii) => (
                  <div key={ii} className="rounded p-1.5" style={{ background: 'var(--bg-hover)', border: '1px solid var(--border-color)' }}>
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-medium truncate" style={{ color: 'var(--text-primary)' }}>{item.name}</span>
                      <span className="text-xs font-mono ml-2" style={{ color: pctColor(item.change) }}>{pctStr(item.change)}</span>
                    </div>
                    {item.strength != null && (
                      <div className="flex items-center gap-1 mt-1">
                        <span className="text-[9px]" style={{ color: MUTED }}>强度</span>
                        <div className="flex-1 h-1 rounded-full" style={{ background: 'var(--bg-surface)' }}>
                          <div className="h-1 rounded-full" style={{ width: `${Math.min(100, Math.max(0, item.strength))}%`, background: style.color }} />
                        </div>
                        <span className="text-[9px] font-mono" style={{ color: style.color }}>{item.strength}%</span>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function FundFlowPanel({ fundflow }) {
  if (!fundflow) return null;
  const sectors = fundflow.sectors || fundflow.top_sectors || [];
  const summary = fundflow.summary || {};
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>资金流向</div>
      {summary.main_inflow != null && (
        <div className="flex flex-wrap gap-3 text-xs mb-2">
          <span>主力净流入: <span style={{ color: summary.main_inflow >= 0 ? UP_COLOR : DOWN_COLOR }}>{numStr(summary.main_inflow)}</span></span>
          <span>散户净流入: <span style={{ color: summary.retail_inflow >= 0 ? UP_COLOR : DOWN_COLOR }}>{numStr(summary.retail_inflow)}</span></span>
        </div>
      )}
      {sectors.length > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-1.5">
          {sectors.slice(0, 12).map((s, i) => (
            <div key={i} className="flex items-center justify-between text-xs p-1 rounded"
              style={{ background: 'var(--bg-hover)' }}>
              <span className="truncate" style={{ color: 'var(--text-primary)' }}>{s.name || s.sector}</span>
              <span className="font-mono ml-1" style={{ color: (s.inflow ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>
                {numStr(s.inflow || s.net_inflow)}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function EmotionPanel({ emotion }) {
  if (!emotion) return null;
  const stage = emotion.stage || emotion.market_stage || {};
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场情绪</div>
      {stage.name && (
        <div className="text-sm font-bold mb-1" style={{ color: 'var(--text-primary)' }}>{stage.name}</div>
      )}
      {stage.description && (
        <div className="text-xs leading-relaxed" style={{ color: MUTED }}>{stage.description}</div>
      )}
      {emotion.sentiment_score != null && (
        <div className="mt-2 flex items-center gap-2">
          <span className="text-xs" style={{ color: MUTED }}>情绪分</span>
          <div className="flex-1 h-2 rounded-full" style={{ background: 'var(--bg-surface)' }}>
            <div className="h-2 rounded-full" style={{
              width: `${Math.min(100, Math.max(0, emotion.sentiment_score))}%`,
              background: emotion.sentiment_score > 50 ? UP_COLOR : emotion.sentiment_score > 30 ? '#eab308' : DOWN_COLOR,
            }} />
          </div>
          <span className="text-xs font-mono" style={{ color: 'var(--text-primary)' }}>{emotion.sentiment_score}</span>
        </div>
      )}
    </div>
  );
}

function RiskPanel({ risk }) {
  if (!risk) return null;
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>风险评估</div>
      {risk.level && (
        <div className="text-sm font-bold" style={{
          color: risk.level === 'high' ? UP_COLOR : risk.level === 'medium' ? '#eab308' : DOWN_COLOR,
        }}>
          {risk.level === 'high' ? '高风险' : risk.level === 'medium' ? '中风险' : '低风险'}
        </div>
      )}
      {risk.summary && <div className="text-xs mt-1 leading-relaxed" style={{ color: MUTED }}>{risk.summary}</div>}
      {risk.warnings?.length > 0 && (
        <div className="mt-2 space-y-1">
          {risk.warnings.map((w, i) => (
            <div key={i} className="text-xs flex items-start gap-1">
              <span style={{ color: '#eab308' }}>⚠</span>
              <span style={{ color: 'var(--text-secondary)' }}>{w}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function SummaryCard({ summary }) {
  return (
    <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场摘要</div>
      <div className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>
        {summary.text || summary.markdown || '暂无摘要'}
      </div>
    </div>
  );
}