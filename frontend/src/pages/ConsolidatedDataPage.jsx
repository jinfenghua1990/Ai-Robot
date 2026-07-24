import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const MUTED = 'var(--text-muted)';
const UP = '#ef4444';
const DOWN = '#22c55e';

export default function ConsolidatedDataPage() {
  const [loading, setLoading] = useState(true);
  const [data, setData] = useState(null);
  const [date, setDate] = useState('');

  useEffect(() => {
    setLoading(true);
    const params = date ? `?date=${date}` : '';
    Promise.all([
      apiFetch(`/api/emotion${params}`),
      apiFetch(`/api/risk${params}`),
      apiFetch(`/api/cognition${params}`),
      apiFetch(`/api/tomorrow-plan${params}`),
      apiFetch(`/api/summary${params}`),
    ]).then(([eRes, rRes, cRes, tRes, sRes]) => {
      setData({
        emotion: eRes.ok ? eRes.data : null,
        risk: rRes.ok ? rRes.data : null,
        cognition: cRes.ok ? cRes.data : null,
        tomorrowPlan: tRes.ok ? tRes.data : null,
        summary: sRes.ok ? sRes.data : null,
      });
    }).finally(() => setLoading(false));
  }, [date]);

  if (loading) return <div className="flex items-center justify-center py-20 text-sm" style={{ color: MUTED }}>加载中...</div>;

  const { emotion, risk, cognition, tomorrowPlan, summary } = data || {};

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>综合数据</h2>
        <input type="date" value={date} onChange={e => setDate(e.target.value)} className="px-2 py-1 rounded border text-xs" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {/* 情绪 */}
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场情绪</div>
          {emotion ? (
            <>
              <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{emotion.stage?.name || emotion.market_stage?.name || '—'}</div>
              <div className="text-xs mt-1" style={{ color: MUTED }}>{emotion.stage?.description || emotion.market_stage?.description || emotion.summary || '—'}</div>
              {emotion.sentiment_score != null && (
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex-1 h-2 rounded-full" style={{ background: 'var(--bg-surface)' }}>
                    <div className="h-2 rounded-full" style={{ width: `${Math.min(100, Math.max(0, emotion.sentiment_score))}%`, background: emotion.sentiment_score > 50 ? UP : emotion.sentiment_score > 30 ? '#eab308' : DOWN }} />
                  </div>
                  <span className="text-xs font-mono">{emotion.sentiment_score}</span>
                </div>
              )}
            </>
          ) : <div className="text-xs" style={{ color: MUTED }}>暂无数据</div>}
        </div>

        {/* 风险 */}
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>风险评估</div>
          {risk ? (
            <>
              <div className="text-sm font-bold" style={{ color: risk.level === 'high' ? UP : risk.level === 'medium' ? '#eab308' : DOWN }}>{risk.level === 'high' ? '高风险' : risk.level === 'medium' ? '中风险' : '低风险'}</div>
              <div className="text-xs mt-1" style={{ color: MUTED }}>{risk.summary || '—'}</div>
              {risk.warnings?.length > 0 && risk.warnings.map((w, i) => <div key={i} className="text-xs mt-1 flex gap-1"><span style={{ color: '#eab308' }}>⚠</span><span style={{ color: 'var(--text-secondary)' }}>{w}</span></div>)}
            </>
          ) : <div className="text-xs" style={{ color: MUTED }}>暂无数据</div>}
        </div>

        {/* 认知 */}
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场认知</div>
          {cognition ? (
            <div className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{cognition.text || cognition.summary || JSON.stringify(cognition, null, 2)}</div>
          ) : <div className="text-xs" style={{ color: MUTED }}>暂无数据</div>}
        </div>

        {/* 明日计划 */}
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>明日计划</div>
          {tomorrowPlan ? (
            <div className="text-xs leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{tomorrowPlan.text || tomorrowPlan.summary || JSON.stringify(tomorrowPlan, null, 2)}</div>
          ) : <div className="text-xs" style={{ color: MUTED }}>暂无数据</div>}
        </div>
      </div>

      {/* 摘要 */}
      {summary?.text && (
        <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场摘要</div>
          <div className="text-sm leading-relaxed whitespace-pre-wrap" style={{ color: 'var(--text-primary)' }}>{summary.text || summary.markdown}</div>
        </div>
      )}
    </div>
  );
}
