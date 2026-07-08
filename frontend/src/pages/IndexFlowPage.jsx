import { useState, useEffect, useMemo, useCallback } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../lib/echarts';
import { tooltipStyle } from '../utils/chartConfig';
import { apiFetch } from '../utils/request';

/**
 * 国家队资金动向 · 行业主题指数资金流向散点图 + 排行表
 * 二级页面路由：/index-flow
 *
 * 数据源：本地 stock_flow 按指数成分股聚合；缺数据时降级东方财富
 * 字段：1日/3日/5日主力净流入（单位：元）
 */
export default function IndexFlowPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedCode, setSelectedCode] = useState(null);
  const [history, setHistory] = useState(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [sortBy, setSortBy] = useState('inflow_5d');
  const [sortDir, setSortDir] = useState('desc');

  // 加载排名数据
  const loadRank = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    const { ok, data: d, error: err } = await apiFetch(`/api/index-flow/rank${force ? '?force=1' : ''}`);
    if (ok) {
      setData(d);
      // 数据源不可用时显示错误提示
      if (d?.error === 'data_source_unavailable') {
        setError(d.message || '数据源暂时不可用');
      } else if (d?.indices?.length > 0 && !selectedCode) {
        // 默认选中 5 日净流入最大的指数
        setSelectedCode(d.indices[0].ts_code);
      }
    } else {
      setError(err || '加载失败');
    }
    setLoading(false);
  }, [selectedCode]);

  // 加载选中指数的历史趋势
  const loadHistory = useCallback(async (code) => {
    if (!code) { setHistory(null); return; }
    setHistoryLoading(true);
    const { ok, data: d } = await apiFetch(`/api/index-flow/history?ts_code=${code}&days=20`);
    if (ok) setHistory(d);
    else setHistory(null);
    setHistoryLoading(false);
  }, [selectedCode]);

  useEffect(() => { loadRank(); }, [loadRank]);
  useEffect(() => { if (selectedCode) loadHistory(selectedCode); }, [selectedCode, loadHistory]);

  // 散点图 option
  const scatterOption = useMemo(() => {
    if (!data?.indices?.length) return null;

    // 气泡大小映射：1日净流入绝对值（归一化到 8~40 px）
    const absValues = data.indices.map(x => x.abs_1d || 0);
    const maxAbs = Math.max(...absValues, 1);

    // 按涨跌分两组：流入（红） vs 流出（绿）
    const inflowPoints = [];
    const outflowPoints = [];
    data.indices.forEach(idx => {
      const point = {
        name: idx.name,
        value: [idx.inflow_3d, idx.inflow_5d, idx.abs_1d, idx.ts_code, idx.name, idx.inflow_1d],
        symbolSize: 8 + (idx.abs_1d / maxAbs) * 32,
      };
      if (idx.inflow_1d >= 0) inflowPoints.push(point);
      else outflowPoints.push(point);
    });

    return {
      tooltip: {
        ...tooltipStyle,
        formatter: (p) => {
          const v = p.value;
          const fmt = (x) => {
            if (x == null || isNaN(x)) return '—';
            const abs = Math.abs(x);
            if (abs >= 1e8) return `${(x/1e8).toFixed(2)}亿`;
            if (abs >= 1e4) return `${(x/1e4).toFixed(2)}万`;
            return `${x.toFixed(0)}`;
          };
          return `<div style="font-weight:700;margin-bottom:4px">${v[4]}</div>` +
                 `<div style="font-size:11px;color:#aaa">代码：${v[3]}</div>` +
                 `<div style="margin-top:6px">` +
                 `<div>1日净流入：<span style="color:${v[5]>=0?'#ef4444':'#22c55e'};font-weight:600">${fmt(v[5])}</span></div>` +
                 `<div>3日净流入：<span style="color:${v[0]>=0?'#ef4444':'#22c55e'};font-weight:600">${fmt(v[0])}</span></div>` +
                 `<div>5日净流入：<span style="color:${v[1]>=0?'#ef4444':'#22c55e'};font-weight:600">${fmt(v[1])}</span></div>` +
                 `</div>`;
        },
      },
      grid: { top: 30, left: 70, right: 40, bottom: 50 },
      xAxis: {
        type: 'value',
        name: '3日净流入',
        nameLocation: 'middle',
        nameGap: 30,
        nameTextStyle: { color: 'var(--text-muted)', fontSize: 11 },
        axisLabel: {
          color: 'var(--text-secondary)', fontSize: 10,
          formatter: (v) => {
            const abs = Math.abs(v);
            if (abs >= 1e8) return `${(v/1e8).toFixed(1)}亿`;
            if (abs >= 1e4) return `${(v/1e4).toFixed(0)}万`;
            return v.toFixed(0);
          },
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
      },
      yAxis: {
        type: 'value',
        name: '5日净流入',
        nameTextStyle: { color: 'var(--text-muted)', fontSize: 11 },
        axisLabel: {
          color: 'var(--text-secondary)', fontSize: 10,
          formatter: (v) => {
            const abs = Math.abs(v);
            if (abs >= 1e8) return `${(v/1e8).toFixed(1)}亿`;
            if (abs >= 1e4) return `${(v/1e4).toFixed(0)}万`;
            return v.toFixed(0);
          },
        },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
      },
      legend: {
        show: true,
        top: 0,
        right: 10,
        textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
        data: [
          { name: '1日流入', icon: 'circle' },
          { name: '1日流出', icon: 'circle' },
        ],
      },
      series: [
        {
          name: '1日流入',
          type: 'scatter',
          data: inflowPoints,
          symbolSize: (d) => d[2] ? 8 + (d[2] / maxAbs) * 32 : 8,
          itemStyle: {
            color: 'rgba(239,68,68,0.7)',
            borderColor: '#ef4444',
            borderWidth: 1.5,
            shadowBlur: 8,
            shadowColor: 'rgba(239,68,68,0.3)',
          },
          emphasis: {
            itemStyle: { color: '#ef4444', borderColor: '#ef4444', borderWidth: 2, shadowBlur: 12 },
            scale: 1.15,
          },
          label: {
            show: true,
            position: 'right',
            formatter: (p) => p.value[4],
            color: 'var(--text-secondary)',
            fontSize: 10,
            fontWeight: 600,
          },
        },
        {
          name: '1日流出',
          type: 'scatter',
          data: outflowPoints,
          symbolSize: (d) => d[2] ? 8 + (d[2] / maxAbs) * 32 : 8,
          itemStyle: {
            color: 'rgba(34,197,94,0.7)',
            borderColor: '#22c55e',
            borderWidth: 1.5,
            shadowBlur: 8,
            shadowColor: 'rgba(34,197,94,0.3)',
          },
          emphasis: {
            itemStyle: { color: '#22c55e', borderColor: '#22c55e', borderWidth: 2, shadowBlur: 12 },
            scale: 1.15,
          },
          label: {
            show: true,
            position: 'right',
            formatter: (p) => p.value[4],
            color: 'var(--text-secondary)',
            fontSize: 10,
            fontWeight: 600,
          },
        },
      ],
    };
  }, [data]);

  const onScatterClick = useMemo(() => ({
    click: (params) => {
      const code = params?.value?.[3];
      if (code) setSelectedCode(code);
    },
  }), []);

  // 历史趋势图 option
  const historyOption = useMemo(() => {
    if (!history?.dates?.length) return null;
    const fmt = (v) => {
      const abs = Math.abs(v);
      if (abs >= 1e8) return `${(v/1e8).toFixed(2)}亿`;
      if (abs >= 1e4) return `${(v/1e4).toFixed(0)}万`;
      return v.toFixed(0);
    };
    return {
      tooltip: {
        ...tooltipStyle,
        trigger: 'axis',
        formatter: (params) => {
          const date = params[0].axisValue;
          let html = `<div style="font-weight:700;margin-bottom:4px">${date}</div>`;
          params.forEach(p => {
            const color = p.value >= 0 ? '#ef4444' : '#22c55e';
            html += `<div style="margin:2px 0;font-size:11px">${p.seriesName}：<span style="color:${color};font-weight:600">${fmt(p.value)}</span></div>`;
          });
          return html;
        },
      },
      legend: {
        show: true,
        top: 0,
        right: 10,
        textStyle: { color: 'var(--text-secondary)', fontSize: 11 },
        data: ['日净流入', '累计净流入'],
      },
      grid: { top: 35, left: 70, right: 70, bottom: 30 },
      xAxis: {
        type: 'category',
        data: history.dates,
        axisLabel: { color: 'var(--text-secondary)', fontSize: 10, rotate: 30, formatter: (v) => v.slice(5) },
        axisLine: { lineStyle: { color: 'var(--border-color)' } },
        axisTick: { show: false },
      },
      yAxis: [
        {
          type: 'value',
          name: '日净流入',
          nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
          axisLabel: {
            color: 'var(--text-secondary)', fontSize: 10,
            formatter: (v) => fmt(v),
          },
          splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.5 } },
          axisLine: { show: false },
          axisTick: { show: false },
        },
        {
          type: 'value',
          name: '累计',
          nameTextStyle: { color: 'var(--text-muted)', fontSize: 10 },
          axisLabel: {
            color: 'var(--text-secondary)', fontSize: 10,
            formatter: (v) => fmt(v),
          },
          splitLine: { show: false },
          axisLine: { show: false },
          axisTick: { show: false },
        },
      ],
      series: [
        {
          name: '日净流入',
          type: 'bar',
          data: history.main_net.map(v => ({
            value: v,
            itemStyle: { color: v >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)', borderColor: v >= 0 ? '#ef4444' : '#22c55e', borderWidth: 1 },
          })),
          barWidth: '60%',
        },
        {
          name: '累计净流入',
          type: 'line',
          yAxisIndex: 1,
          data: history.cumulative,
          smooth: true,
          symbol: 'circle',
          symbolSize: 5,
          lineStyle: { width: 2.5, color: '#3b82f6' },
          itemStyle: { color: '#3b82f6' },
        },
      ],
    };
  }, [history]);

  // 排序后的列表
  const sortedIndices = useMemo(() => {
    if (!data?.indices) return [];
    const dir = sortDir === 'desc' ? -1 : 1;
    return [...data.indices].sort((a, b) => {
      const va = a[sortBy] ?? 0;
      const vb = b[sortBy] ?? 0;
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });
  }, [data, sortBy, sortDir]);

  const fmtFlow = (v) => {
    if (v == null || isNaN(v)) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e8) return `${(v/1e8).toFixed(2)}亿`;
    if (abs >= 1e4) return `${(v/1e4).toFixed(0)}万`;
    return v.toFixed(0);
  };

  const fmtPct = (v) => {
    if (v == null || isNaN(v)) return '—';
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  };

  const handleSort = (key) => {
    if (sortBy === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(key);
      setSortDir('desc');
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
        <span className="ml-3 text-sm" style={{ color: 'var(--text-muted)' }}>加载指数资金流向数据...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg p-4 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
        加载失败: {error}
        <button onClick={() => loadRank(true)} className="ml-3 px-2 py-1 rounded border text-xs" style={{ borderColor: '#ef4444', color: '#ef4444' }}>重试</button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-3">
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between px-3 py-2 rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-3 text-sm">
          <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>国家队资金动向</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>行业主题指数</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span style={{ color: 'var(--text-muted)' }}>📅 {data.date || '--'}</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span style={{ color: 'var(--text-secondary)' }}>共 <b style={{ color: 'var(--text-primary)' }}>{data.count || 0}</b> 个指数</span>
        </div>
        <button
          onClick={() => loadRank(true)}
          className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'var(--bg-primary)' }}
        >
          🔄 刷新
        </button>
      </div>

      {/* 说明卡 */}
      <div className="rounded-lg border p-2.5 text-[11px] flex items-start gap-2" style={{ borderColor: 'rgba(59,130,246,0.2)', background: 'rgba(59,130,246,0.05)', color: 'var(--text-secondary)' }}>
        <span>💡</span>
        <div>
          <strong style={{ color: 'var(--text-primary)' }}>说明：</strong>
          展示国证/中证行业主题指数的主力资金流向。散点图 X 轴为 3 日主力净流入，Y 轴为 5 日主力净流入，气泡大小为 1 日净流入绝对值。
          <strong style={{ color: '#ef4444' }}> 红色</strong>=1日净流入为正，<strong style={{ color: '#22c55e' }}> 绿色</strong>=1日净流出。
          数据来源：<strong style={{ color: 'var(--text-primary)' }}>{data?.source === 'database' ? '本地数据库（按指数成分股聚合）' : data?.source === 'database+eastmoney' ? '数据库 + 东方财富' : '东方财富'}</strong>。点击散点或表格行查看该指数近 20 日资金流趋势。
        </div>
      </div>

      {/* 散点图 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs mb-1 font-medium" style={{ color: 'var(--text-secondary)' }}>📊 指数资金流向散点图</div>
        {scatterOption ? (
          <ReactECharts
            echarts={echarts}
            option={scatterOption}
            notMerge={true}
            style={{ height: 380, width: '100%' }}
            opts={{ renderer: 'canvas' }}
            onEvents={onScatterClick}
          />
        ) : (
          <div className="flex items-center justify-center h-80 text-sm" style={{ color: 'var(--text-muted)' }}>暂无数据</div>
        )}
      </div>

      {/* 排行表 + 历史趋势 双列 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 左列：排行表 */}
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-2 border-b text-xs font-medium flex items-center justify-between" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            <span>📋 指数资金流向排行</span>
            <span style={{ color: 'var(--text-muted)' }}>点击表头排序 · 点击行查看趋势</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
                  <th className="px-2 py-1.5 text-left font-medium">指数代码</th>
                  <th className="px-2 py-1.5 text-left font-medium">指数名称</th>
                  <th className="px-2 py-1.5 text-right font-medium cursor-pointer hover:text-blue-500" onClick={() => handleSort('pct_change')}>
                    涨跌幅 {sortBy === 'pct_change' && (sortDir === 'desc' ? '↓' : '↑')}
                  </th>
                  <th className="px-2 py-1.5 text-right font-medium cursor-pointer hover:text-blue-500" onClick={() => handleSort('inflow_1d')}>
                    1日净流入 {sortBy === 'inflow_1d' && (sortDir === 'desc' ? '↓' : '↑')}
                  </th>
                  <th className="px-2 py-1.5 text-right font-medium cursor-pointer hover:text-blue-500" onClick={() => handleSort('inflow_3d')}>
                    3日净流入 {sortBy === 'inflow_3d' && (sortDir === 'desc' ? '↓' : '↑')}
                  </th>
                  <th className="px-2 py-1.5 text-right font-medium cursor-pointer hover:text-blue-500" onClick={() => handleSort('inflow_5d')}>
                    5日净流入 {sortBy === 'inflow_5d' && (sortDir === 'desc' ? '↓' : '↑')}
                  </th>
                  <th className="px-2 py-1.5 text-right font-medium">1日净流入_绝对值</th>
                </tr>
              </thead>
              <tbody>
                {sortedIndices.map(idx => {
                  const isSelected = selectedCode === idx.ts_code;
                  return (
                    <tr
                      key={idx.ts_code}
                      onClick={() => setSelectedCode(idx.ts_code)}
                      className="cursor-pointer transition-colors"
                      style={{
                        background: isSelected ? 'rgba(59,130,246,0.08)' : 'transparent',
                        borderTop: '1px solid var(--border-light)',
                      }}
                    >
                      <td className="px-2 py-1.5" style={{ color: 'var(--text-secondary)' }}>{idx.ts_code}</td>
                      <td className="px-2 py-1.5 font-medium" style={{ color: 'var(--text-primary)' }}>{idx.name}</td>
                      <td className="px-2 py-1.5 text-right font-medium" style={{ color: (idx.pct_change ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                        {fmtPct(idx.pct_change)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-medium" style={{ color: (idx.inflow_1d ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                        {fmtFlow(idx.inflow_1d)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-medium" style={{ color: (idx.inflow_3d ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                        {fmtFlow(idx.inflow_3d)}
                      </td>
                      <td className="px-2 py-1.5 text-right font-medium" style={{ color: (idx.inflow_5d ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                        {fmtFlow(idx.inflow_5d)}
                      </td>
                      <td className="px-2 py-1.5 text-right" style={{ color: 'var(--text-muted)' }}>{fmtFlow(idx.abs_1d)}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>

        {/* 右列：选中指数历史趋势 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-1 font-medium flex items-center justify-between" style={{ color: 'var(--text-secondary)' }}>
            <span>📈 {history?.name || '选择指数'} 近 20 日资金流</span>
            {history?.latest_date && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>最新: {history.latest_date}</span>}
          </div>
          {historyLoading ? (
            <div className="flex items-center justify-center h-80 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
          ) : historyOption ? (
            <ReactECharts
              echarts={echarts}
              option={historyOption}
              notMerge={true}
              style={{ height: 380, width: '100%' }}
              opts={{ renderer: 'canvas' }}
            />
          ) : (
            <div className="flex items-center justify-center h-80 text-sm" style={{ color: 'var(--text-muted)' }}>暂无历史数据</div>
          )}
        </div>
      </div>
    </div>
  );
}
