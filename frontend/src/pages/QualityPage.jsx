import { useState, useEffect, useCallback } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../lib/echarts';
import { tConfidence, tAction, tSource, tIndicator } from '../utils/i18n';
import { getEastMoneyUrl, getTHSUrl, getStockUrl, getTencentUrl } from '../utils/stockLink';
import { apiFetch } from '../utils/request';
import { POLL_INTERVAL } from '../utils/constants';

export default function QualityPage() {
  const [overview, setOverview] = useState(null);
  const [sources, setSources] = useState(null);
  const [dataSources, setDataSources] = useState(null);
  const [anomalies, setAnomalies] = useState(null);
  const [reviewQueue, setReviewQueue] = useState(null);
  const [logs, setLogs] = useState(null);
  const [errorStats, setErrorStats] = useState(null);
  const [freshness, setFreshness] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

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

  useEffect(() => { fetchAll(); }, [fetchAll]);

  useEffect(() => {
    const interval = setInterval(async () => {
      const { ok, data } = await apiFetch('/api/quality/data-freshness');
      if (ok) setFreshness(data);
    }, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, []);

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

  if (loading) return <div className="flex items-center justify-center h-96"><div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div></div>;

  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>
          数据质量仪表盘
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>盘后数据</span>
        </h2>
        <button onClick={fetchAll} className="px-2 py-1 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>🔄 刷新</button>
      </div>

      {error && <div className="rounded-lg p-2 text-xs" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{error}</div>}

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
                <span className="px-1 py-0.5 rounded text-[9px]" style={{ background: 'rgba(148,163,184,0.1)', color: 'var(--text-muted)' }}>
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
