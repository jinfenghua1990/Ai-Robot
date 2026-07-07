import { useState, useEffect, useCallback, useMemo } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../lib/echarts';
import LineChart from '../components/charts/TrendLineChart';
import StageBar from '../components/StageBar';
import { tConfidence, tSource, confidenceMap } from '../utils/i18n';

export default function RealtimePage() {
  const [status, setStatus] = useState(null);
  const [sectors, setSectors] = useState(null);
  const [stocks, setStocks] = useState(null);
  const [qualityOverview, setQualityOverview] = useState(null);
  const [trendData, setTrendData] = useState(null);
  const [trendType, setTrendType] = useState(null); // {kind: 'sector'|'stock', name: '...'}
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lastRefresh, setLastRefresh] = useState('');

  const fmtFlow = (v) => {
    const abs = Math.abs(v);
    if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
    return `${v.toFixed(0)}万`;
  };

  // 拉取数据
  const fetchAll = useCallback(async () => {
    try {
      const [statusResp, sectorResp, stockResp, qualityResp] = await Promise.all([
        fetch('/api/realtime/status').then(r => r.json()),
        fetch('/api/realtime/latest-sectors').then(r => r.json()),
        fetch('/api/realtime/latest-stocks?limit=20&sort_by=main_force_inflow').then(r => r.json()),
        fetch('/api/quality/overview').then(r => r.json()).catch(() => null),
      ]);
      setStatus(statusResp);
      setSectors(sectorResp);
      setStocks(stockResp);
      setQualityOverview(qualityResp);
      setLastRefresh(new Date().toLocaleTimeString('zh-CN'));
      setError(null);
    } catch (e) {
      setError('数据加载失败: ' + e.message);
    } finally {
      setLoading(false);
    }
  }, []);

  // 初始加载 + 自动刷新
  useEffect(() => {
    fetchAll();
    if (!autoRefresh) return;
    const interval = setInterval(fetchAll, 30000); // 30秒刷新
    return () => clearInterval(interval);
  }, [fetchAll, autoRefresh]);

  // 拉取趋势数据
  const fetchTrend = useCallback(async (kind, name) => {
    setTrendType({ kind, name });
    try {
      const url = kind === 'sector'
        ? `/api/realtime/sector-trend?sector=${encodeURIComponent(name)}`
        : `/api/realtime/stock-trend?ts_code=${encodeURIComponent(name)}`;
      const resp = await fetch(url).then(r => r.json());
      setTrendData(resp);
    } catch (e) {
      setError('趋势加载失败: ' + e.message);
    }
  }, []);

  // 板块流入/流出Top10
  const { topInflow, topOutflow } = useMemo(() => {
    const list = sectors?.sectors || [];
    const inflow = list.filter(s => s.net_flow > 0).sort((a, b) => b.net_flow - a.net_flow).slice(0, 10);
    const outflow = list.filter(s => s.net_flow < 0).sort((a, b) => a.net_flow - b.net_flow).slice(0, 10);
    return { topInflow: inflow, topOutflow: outflow };
  }, [sectors]);

  // 置信度颜色
  const confColor = (c) => ({ high: '#22c55e', medium: '#facc15', low: '#ef4444', disputed: '#a78bfa' }[c] || '#64748b');

  // 个股流入/流出Top10
  const { topStockInflow, topStockOutflow } = useMemo(() => {
    const list = stocks?.stocks || [];
    const inflow = list.slice(0, 10);
    const outflow = [...list].sort((a, b) => a.main_force_inflow - b.main_force_inflow).slice(0, 10);
    return { topStockInflow: inflow, topStockOutflow: outflow };
  }, [stocks]);

  // 趋势图配置
  const trendOption = useMemo(() => {
    if (!trendData?.points?.length) return null;
    const points = trendData.points;
    return {
      tooltip: {
        trigger: 'axis',
        backgroundColor: 'rgba(20,20,20,0.95)',
        borderColor: 'rgba(255,255,255,0.15)',
        textStyle: { color: '#fff', fontSize: 12 },
      },
      grid: { left: 60, right: 60, top: 30, bottom: 30 },
      xAxis: {
        type: 'category',
        data: points.map(p => p.time),
        axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
      },
      yAxis: [
        {
          type: 'value',
          name: '净流入(万)',
          position: 'left',
          axisLabel: {
            color: 'var(--text-muted)', fontSize: 10,
            formatter: (v) => Math.abs(v) >= 10000 ? `${(v/10000).toFixed(1)}亿` : `${v.toFixed(0)}`,
          },
          splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
        },
        {
          type: 'value',
          name: trendType?.kind === 'stock' ? '价格' : '涨跌幅',
          position: 'right',
          axisLabel: { color: 'var(--text-muted)', fontSize: 10 },
          splitLine: { show: false },
        },
      ],
      series: [
        {
          name: '净流入',
          type: 'line',
          data: points.map(p => p.net_flow || p.main_force_inflow || 0),
          smooth: true,
          symbol: 'circle',
          symbolSize: 6,
          lineStyle: { color: '#ef4444', width: 2 },
          itemStyle: { color: '#ef4444' },
          areaStyle: {
            color: {
              type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(239,68,68,0.3)' },
                { offset: 1, color: 'rgba(239,68,68,0)' },
              ],
            },
          },
        },
        ...(trendType?.kind === 'stock' ? [{
          name: '价格',
          type: 'line',
          yAxisIndex: 1,
          data: points.map(p => p.price || 0),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#38bdf8', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#38bdf8' },
        }] : [{
          name: '涨跌幅',
          type: 'line',
          yAxisIndex: 1,
          data: points.map(p => p.rise_ratio || 0),
          smooth: true,
          symbol: 'none',
          lineStyle: { color: '#38bdf8', width: 1.5, type: 'dashed' },
          itemStyle: { color: '#38bdf8' },
        }]),
      ],
    };
  }, [trendData, trendType]);

  if (loading) {
    return <div className="flex items-center justify-center h-96"><div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div></div>;
  }

  return (
    <div className="space-y-2">
      {/* 顶部状态栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          实时监控
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>盘中实时</span>
        </h2>
        <div className="flex items-center gap-2">
          {status?.is_trading_hours && (
            <span className="px-2 py-1 rounded text-xs font-medium" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>
              ● 盘中
            </span>
          )}
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            最后更新: {sectors?.snapshot_time || '—'}
          </span>
          <button
            onClick={() => setAutoRefresh(!autoRefresh)}
            className="px-3 py-1.5 rounded-lg border text-sm flex items-center gap-1.5"
            style={{
              borderColor: autoRefresh ? '#22c55e' : 'var(--border-color)',
              color: autoRefresh ? '#22c55e' : 'var(--text-secondary)',
              background: autoRefresh ? 'rgba(34,197,94,0.1)' : 'transparent',
            }}
          >
            {autoRefresh ? '⏸ 暂停刷新' : '▶ 自动刷新'}
          </button>
          <button
            onClick={fetchAll}
            className="px-3 py-1.5 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {/* 状态卡片 */}
      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>板块快照</div>
            <div className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{status.total_sector_snapshots || 0}</div>
          </div>
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>个股快照</div>
            <div className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{status.total_stock_snapshots || 0}</div>
          </div>
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>今日采集次数</div>
            <div className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>{status.today_snapshots || 0}</div>
          </div>
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>个股最后更新</div>
            <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{status.latest_stock_time || '—'}</div>
          </div>
        </div>
      )}

      {/* 数据质量总览 */}
      {qualityOverview && qualityOverview.total_stocks > 0 && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(99,102,241,0.3)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>平均质量分</div>
            <div className="text-base font-bold" style={{ color: qualityOverview.avg_quality_score >= 70 ? '#22c55e' : qualityOverview.avg_quality_score >= 50 ? '#facc15' : '#ef4444' }}>
              {qualityOverview.avg_quality_score.toFixed(1)}
            </div>
          </div>
          <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>多源验证</div>
            <div className="text-base font-bold" style={{ color: '#38bdf8' }}>
              {qualityOverview.multi_source_validated}/{qualityOverview.total_stocks}
            </div>
          </div>
          {[
            { key: 'high', label: '高置信', color: '#22c55e' },
            { key: 'medium', label: '中置信', color: '#facc15' },
            { key: 'low', label: '低置信', color: '#ef4444' },
          ].map(({ key, label, color }) => (
            <div key={key} className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</div>
              <div className="text-base font-bold" style={{ color }}>
                {qualityOverview.confidence_distribution?.[key] || 0}
              </div>
            </div>
          ))}
        </div>
      )}

      {error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>{error}</div>
      )}

      {/* 趋势图（点击板块/个股后显示） */}
      {trendOption && (
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              📈 {trendType?.kind === 'sector' ? '板块' : '个股'}盘中趋势：{trendType?.name}
            </h3>
            <button onClick={() => { setTrendType(null); setTrendData(null); }} className="text-xs" style={{ color: 'var(--text-muted)' }}>✕ 关闭</button>
          </div>
          <ReactECharts echarts={echarts} option={trendOption} style={{ height: 240 }} />
        </div>
      )}

      {/* 板块双排：流入Top10 / 流出Top10 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: '#ef4444' }}>🔥 板块流入 Top10</h3>
          <div className="space-y-1">
            {topInflow.length === 0 && <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据</div>}
            {topInflow.map((s, i) => (
              <div key={s.sector} className="flex items-center gap-2 py-1 px-2 rounded hover:bg-opacity-50 cursor-pointer"
                   style={{ background: 'rgba(239,68,68,0.05)' }}
                   onClick={() => fetchTrend('sector', s.sector)}>
                <span className="text-xs w-5" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                <span className="text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                <span className="text-xs" style={{ color: '#ef4444', fontWeight: 600 }}>{fmtFlow(s.net_flow)}</span>
                <span className="text-xs w-12 text-right" style={{ color: s.rise_ratio > 0 ? '#ef4444' : '#22c55e' }}>
                  {s.rise_ratio > 0 ? '+' : ''}{s.rise_ratio.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: '#22c55e' }}>💧 板块流出 Top10</h3>
          <div className="space-y-1">
            {topOutflow.length === 0 && <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据</div>}
            {topOutflow.map((s, i) => (
              <div key={s.sector} className="flex items-center gap-2 py-1 px-2 rounded cursor-pointer"
                   style={{ background: 'rgba(34,197,94,0.05)' }}
                   onClick={() => fetchTrend('sector', s.sector)}>
                <span className="text-xs w-5" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                <span className="text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                <span className="text-xs" style={{ color: '#22c55e', fontWeight: 600 }}>{fmtFlow(s.net_flow)}</span>
                <span className="text-xs w-12 text-right" style={{ color: s.rise_ratio > 0 ? '#ef4444' : '#22c55e' }}>
                  {s.rise_ratio > 0 ? '+' : ''}{s.rise_ratio.toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 个股双排：流入Top10 / 流出Top10 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: '#ef4444' }}>🚀 个股主力流入 Top10</h3>
          <div className="space-y-1">
            {topStockInflow.length === 0 && <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据（盘中采集后显示）</div>}
            {topStockInflow.map((s, i) => (
              <div key={s.ts_code} className="py-1 px-2 rounded cursor-pointer"
                   style={{ background: 'rgba(239,68,68,0.05)' }}
                   onClick={() => fetchTrend('stock', s.ts_code)}>
                <div className="flex items-center gap-2">
                  <span className="text-xs w-5" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: confColor(s.confidence) }} title={`置信度:${tConfidence(s.confidence)} 源数:${s.sources_count||1}`} />
                  <span className="text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{s.name}</span>
                  {s.sources_count > 1 && <span className="text-xs px-1 rounded" style={{ background: 'rgba(56,189,248,0.15)', color: '#38bdf8' }} title={tSource(s.sources_used)}>{s.sources_count}源</span>}
                  {s.is_corrected && <span className="text-xs" style={{ color: '#facc15' }} title="已修正异常源">⚠</span>}
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.ts_code.replace('.SH', '').replace('.SZ', '')}</span>
                  <span className="text-xs w-14 text-right" style={{ color: s.price_chg > 0 ? '#ef4444' : '#22c55e' }}>
                    {s.price_chg > 0 ? '+' : ''}{s.price_chg.toFixed(2)}%
                  </span>
                  <span className="text-xs w-20 text-right" style={{ color: '#ef4444', fontWeight: 600 }}>{fmtFlow(s.main_force_inflow)}</span>
                </div>
                <div className="flex items-center gap-1 mt-0.5 pl-7">
                  <StageBar stage={null} value={s.main_force_inflow} />
                </div>
              </div>
            ))}
          </div>
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: '#22c55e' }}>📉 个股主力流出 Top10</h3>
          <div className="space-y-1">
            {topStockOutflow.length === 0 && <div className="text-xs text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无数据（盘中采集后显示）</div>}
            {topStockOutflow.map((s, i) => (
              <div key={s.ts_code} className="py-1 px-2 rounded cursor-pointer"
                   style={{ background: 'rgba(34,197,94,0.05)' }}
                   onClick={() => fetchTrend('stock', s.ts_code)}>
                <div className="flex items-center gap-2">
                  <span className="text-xs w-5" style={{ color: 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="w-1.5 h-1.5 rounded-full flex-shrink-0" style={{ background: confColor(s.confidence) }} title={`置信度:${tConfidence(s.confidence)} 源数:${s.sources_count||1}`} />
                  <span className="text-sm flex-1 truncate" style={{ color: 'var(--text-primary)' }}>{s.name}</span>
                  {s.sources_count > 1 && <span className="text-xs px-1 rounded" style={{ background: 'rgba(56,189,248,0.15)', color: '#38bdf8' }} title={tSource(s.sources_used)}>{s.sources_count}源</span>}
                  {s.is_corrected && <span className="text-xs" style={{ color: '#facc15' }} title="已修正异常源">⚠</span>}
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.ts_code.replace('.SH', '').replace('.SZ', '')}</span>
                  <span className="text-xs w-14 text-right" style={{ color: s.price_chg > 0 ? '#ef4444' : '#22c55e' }}>
                    {s.price_chg > 0 ? '+' : ''}{s.price_chg.toFixed(2)}%
                  </span>
                  <span className="text-xs w-20 text-right" style={{ color: '#22c55e', fontWeight: 600 }}>{fmtFlow(s.main_force_inflow)}</span>
                </div>
                <div className="flex items-center gap-1 mt-0.5 pl-7">
                  <StageBar stage={null} value={s.main_force_inflow} />
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 提示 */}
      <div className="rounded-lg p-2 text-xs flex items-center gap-2" style={{ background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', color: '#a5b4fc' }}>
        <span>💡</span>
        <span>盘中每15分钟自动采集一次快照。点击板块/个股名称查看盘中趋势图。数据源：东方财富(个股) + 新浪(板块) + 国信证券(验证)。</span>
      </div>
    </div>
  );
}
