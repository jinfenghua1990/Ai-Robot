import { useState, useEffect } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../lib/echarts';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import { fmtFlow } from '../utils/format';

export default function PortfolioPage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [lookbackDays, setLookbackDays] = useState(5);
  const [showHelp, setShowHelp] = useState(false);

  useEffect(() => {
    if (!selectedDate) return;
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    fetch(`/api/portfolio?date=${selectedDate}&days=${lookbackDays}`, { signal: controller.signal })
      .then(r => r.json())
      .then(d => { setData(d); setLoading(false); })
      .catch(err => {
        if (err.name === 'AbortError') return;
        setError('数据加载失败');
        setLoading(false);
      });
    return () => controller.abort();
  }, [selectedDate, lookbackDays]);

  // 配置饼图
  const pieOption = data?.allocation ? {
    tooltip: {
      trigger: 'item',
      backgroundColor: 'rgba(20,20,20,0.95)',
      borderColor: 'rgba(255,255,255,0.15)',
      textStyle: { color: '#fff', fontSize: 12 },
      formatter: (params) => {
        const stocks = params.data.stocks?.length ? `<br/>个股：${params.data.stocks.join('、')}` : '';
        return `<div style="font-weight:700">${params.name}</div>` +
               `<div>占比：${params.value}%</div>` +
               `<div style="font-size:11px;color:#ccc;margin-top:2px">${params.data.reason}</div>${stocks}`;
      },
    },
    series: [{
      type: 'pie',
      radius: ['45%', '70%'],
      center: ['50%', '50%'],
      data: data.allocation.map((a, i) => ({
        name: a.category,
        value: a.percentage,
        reason: a.reason,
        stocks: a.stocks,
        itemStyle: {
          color: ['#3b82f6', '#8b5cf6', '#10b981', '#6b7280'][i] || '#94a3b8',
          borderColor: '#1f2937',
          borderWidth: 2,
        },
      })),
      label: {
        color: 'var(--text-primary)',
        fontSize: 12,
        fontWeight: 600,
        formatter: '{b}\n{d}%',
      },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0,0,0,0.3)' } },
    }],
  } : {};

  // 风格雷达图
  const radarOption = data?.market_style ? {
    tooltip: {},
    radar: {
      indicator: [
        { name: '成长', max: 1000 },
        { name: '价值', max: 1000 },
        { name: '制造', max: 1000 },
        { name: '周期', max: 1000 },
        { name: '防御', max: 1000 },
      ],
      axisName: { color: 'var(--text-secondary)', fontSize: 11 },
      splitLine: { lineStyle: { color: 'var(--border-color)' } },
      splitArea: { areaStyle: { color: ['rgba(255,255,255,0.02)', 'rgba(255,255,255,0.04)'] } },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    series: [{
      type: 'radar',
      data: [{
        value: [
          data.market_style.inflow_tech || 0,
          data.market_style.inflow_finance || 0,
          data.market_style.inflow_manufacturing || 0,
          data.market_style.inflow_cyclical || 0,
          data.market_style.inflow_defensive || 0,
        ],
        name: '当前风格',
        areaStyle: { color: 'rgba(59,130,246,0.2)' },
        lineStyle: { color: '#3b82f6', width: 2 },
        itemStyle: { color: '#3b82f6' },
      }],
    }],
  } : {};

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-3">
        <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
        <button onClick={() => { setError(null); setSelectedDate(selectedDate); }} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>重试</button>
      </div>
    );
  }

  if (!data || data.error) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>暂无数据</div>
      </div>
    );
  }

  const ms = data.market_style;
  const summary = data.summary;

  return (
    <div className="space-y-4">
      {/* 标题 + 日期 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          投资组合风格分析
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
        </h2>
        <div className="flex items-center gap-3">
          <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate}
            extra={<select value={lookbackDays} onChange={(e) => setLookbackDays(Number(e.target.value))} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
            <option value={3}>近3天</option>
            <option value={5}>近5天</option>
            <option value={10}>近10天</option>
          </select>}
          />
        </div>
      </div>

      {/* 说明卡片（可折叠） */}
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-3 py-2.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 持仓风格分析</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-3 pb-3 space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>组合分析：</strong>基于持仓个股的资金流向和市场表现，评估投资组合风格</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>分析维度：</strong>行业分布、资金流向、风险暴露、风格特征</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>调仓建议：</strong>根据市场环境变化，提供风格转换和仓位调整建议</div>
          </div>
        )}
      </div>

      {/* 市场风格概览卡片 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>主导风格</div>
          <div className="text-lg font-bold" style={{ color: '#3b82f6' }}>{ms?.dominant || '—'}</div>
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>成长 与 价值</div>
          <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{ms?.growth_vs_value || '—'}</div>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>科技流入 {ms?.inflow_tech != null ? fmtFlow(ms.inflow_tech) : '—'}</div>
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>龙头股数量</div>
          <div className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{summary?.leader_total || 0}</div>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            {Object.entries(data.leaders?.stage_counts || {}).map(([k, v]) => `${k}：${v}`).join(' ')}
          </div>
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>净轮动</div>
          <div className="text-lg font-bold" style={{ color: summary?.net_flow > 0 ? '#ef4444' : '#22c55e' }}>
            {summary?.net_flow > 0 ? '+' : ''}{summary?.net_flow != null ? fmtFlow(summary.net_flow) : '—'}
          </div>
        </div>
      </div>

      {/* 风格雷达 + 配置饼图 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>市场风格雷达</h3>
          <ReactECharts echarts={echarts} option={radarOption} style={{ height: '280px', width: '100%' }} />
        </div>
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>推荐配置比例</h3>
          <ReactECharts echarts={echarts} option={pieOption} style={{ height: '280px', width: '100%' }} />
        </div>
      </div>

      {/* 减持 与 增持 */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {/* 减持建议 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(34,197,94,0.3)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">❄️</span>
            <span className="text-sm font-medium" style={{ color: '#22c55e' }}>减持方向（资金流出）</span>
          </div>
          <div className="space-y-2">
            {data.recommendations?.reduce?.map((item, i) => (
              <div key={i} className="flex items-center justify-between rounded-lg px-3 py-2" style={{ background: 'rgba(34,197,94,0.06)' }}>
                <div>
                  <span className="text-sm font-medium" style={{ color: '#4ade80' }}>{item.sector}</span>
                  <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{item.reason}</div>
                </div>
                <span className="text-xs font-mono" style={{ color: '#22c55e' }}>-{fmtFlow(item.outflow)}</span>
              </div>
            ))}
          </div>
        </div>

        {/* 增持建议 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(239,68,68,0.3)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🔥</span>
            <span className="text-sm font-medium" style={{ color: '#ef4444' }}>增持方向（资金流入）</span>
          </div>
          <div className="space-y-2">
            {data.recommendations?.increase?.map((item, i) => (
              <div key={i} className="rounded-lg px-3 py-2" style={{ background: 'rgba(239,68,68,0.06)' }}>
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium" style={{ color: '#f87171' }}>{item.sector}</span>
                  <span className="text-xs font-mono" style={{ color: '#ef4444' }}>+{fmtFlow(item.inflow)}</span>
                </div>
                {item.stocks?.length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {item.stocks.map((s, j) => (
                      <span key={j} className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: '#f87171' }}>
                        {s.name} {s.price_chg > 0 ? '+' : ''}{s.price_chg}%
                      </span>
                    ))}
                  </div>
                )}
                {item.leader_count > 0 && (
                  <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                    龙头股 {item.leader_count} 只：{item.leaders?.join('、')}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 配置详情 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>配置详情</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {data.allocation?.map((a, i) => (
            <div key={i} className="rounded-lg p-3" style={{ background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between mb-1">
                <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>{a.category}</span>
                <span className="text-lg font-bold" style={{ color: ['#3b82f6', '#8b5cf6', '#10b981', '#6b7280'][i] }}>{a.percentage}%</span>
              </div>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>{a.sectors.join(', ') || '现金管理'}</div>
              <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{a.reason}</div>
              {a.stocks?.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {a.stocks.map((s, j) => (
                    <span key={j} className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#60a5fa' }}>
                      {s.name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      {/* 风控建议 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(234,179,8,0.3)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-lg">⚠️</span>
          <span className="text-sm font-medium" style={{ color: '#eab308' }}>风险控制</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>止损线</div>
            <div className="text-sm" style={{ color: 'var(--text-primary)' }}>{data.risk_control?.stop_loss}</div>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>止盈线</div>
            <div className="text-sm" style={{ color: 'var(--text-primary)' }}>{data.risk_control?.stop_profit}</div>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>监控指标</div>
            <div className="text-sm" style={{ color: 'var(--text-primary)' }}>{data.risk_control?.monitor}</div>
          </div>
          <div className="rounded-lg p-3" style={{ background: 'var(--bg-card)' }}>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>仓位限制</div>
            <div className="text-sm" style={{ color: 'var(--text-primary)' }}>{data.risk_control?.position_limit}</div>
          </div>
        </div>
      </div>
    </div>
  );
}
