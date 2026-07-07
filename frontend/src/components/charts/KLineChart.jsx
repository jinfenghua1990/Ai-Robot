import { useState, useEffect } from 'react';
import ReactECharts from 'echarts-for-react/lib/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { apiFetch } from '../../utils/request';

/**
 * K线图组件（2×3网格左列三格：K线主图 / 成交量 / MACD+KDJ）
 * 信息头/图例/指标说明已移到 KLineModal 顶部信息区
 * 通过 onSummary 回调把 summary 数据传给父组件
 */
export default function KLineChart({ stockCode, stockName, code, height, onSummary }) {
  // 兼容旧调用：code / height
  // compact 模式：传入 height（小图场景，如 WatchlistPage 右侧）只渲染单个 K 线主图
  const sc = stockCode || code;
  const sn = stockName || code;
  const compact = !!height;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!sc) return;
    setLoading(true);
    setError(null);
    apiFetch(`/api/trading/bs-signals?stockCode=${sc}&datalen=60`).then(({ ok, data, error }) => {
      if (ok) {
        setData(data);
        if (onSummary && data?.summary) onSummary(data.summary);
      } else {
        setError(error);
      }
      setLoading(false);
    });
  }, [sc]);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载K线数据...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-sm" style={{ color: '#ef4444' }}>加载失败: {error}</div>
      </div>
    );
  }

  if (!data) return null;

  const { klines = [], indicators = {}, techSignals = [], tradeRecords = [], summary } = data;
  if (!klines.length || !indicators.ma5) return (
    <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
      无K线数据
    </div>
  );
  const dates = klines.map(k => k.date);
  const ohlc = klines.map(k => [k.open, k.close, k.low, k.high]);
  const volumes = klines.map(k => k.volume);

  // === 成交量信号计算 ===
  const volumeSignals = [];
  for (let i = 0; i < klines.length; i++) {
    const v = klines[i].volume;
    const close = klines[i].close;
    const open = klines[i].open;

    if (i >= 5) {
      const avg5 = volumes.slice(i - 5, i).reduce((a, b) => a + b, 0) / 5;
      if (v >= avg5 * 1.5 && close > open) {
        volumeSignals.push({ idx: i, type: 'B', label: '倍量', reason: `倍量柱: 量比${(v/avg5).toFixed(2)}倍` });
        continue;
      }
      if (v >= avg5 * 1.5 && close < open) {
        volumeSignals.push({ idx: i, type: 'S', label: '放量跌', reason: `放量下跌: 量比${(v/avg5).toFixed(2)}倍` });
        continue;
      }
    }

    if (i >= 20) {
      const min20 = Math.min(...volumes.slice(i - 20, i));
      if (v <= min20) {
        volumeSignals.push({ idx: i, type: 'B', label: '地量', reason: '地量: 20日最低量' });
        continue;
      }
    }

    if (i >= 2) {
      const p1 = klines[i-2], p2 = klines[i-1], p3 = klines[i];
      if (p1.close < p2.close && p2.close < p3.close &&
          p1.volume < p2.volume && p2.volume < p3.volume) {
        volumeSignals.push({ idx: i, type: 'B', label: '量价齐升', reason: '量价齐升: 连续3日放量上涨' });
        continue;
      }
    }

    if (i >= 5) {
      const prev5 = klines.slice(i - 5, i);
      const upDays = prev5.filter(k => k.close > k.open).length;
      const avg5 = volumes.slice(i - 5, i).reduce((a, b) => a + b, 0) / 5;
      if (upDays >= 3 && close < open && v < avg5 * 0.7) {
        volumeSignals.push({ idx: i, type: 'B', label: '缩量调', reason: '缩量回调: 洗盘信号' });
        continue;
      }
    }

    if (i >= 1 && i >= 10) {
      const prev = klines[i - 1];
      const prevLow20 = Math.min(...klines.slice(Math.max(0, i - 20), i).map(k => k.low));
      const prevAvg5 = volumes.slice(Math.max(0, i - 5), i).reduce((a, b) => a + b, 0) / 5;
      if (prev.low <= prevLow20 && prev.volume < prevAvg5 &&
          close > open && close > prev.open && prev.close < prev.open) {
        volumeSignals.push({ idx: i, type: 'B', label: '背离反包', reason: '量价背离+次日反包立马冲: 底背离后阳线反包，看涨' });
        continue;
      }
    }
  }

  const volumeMarks = volumeSignals.map(s => ({
    coord: [s.idx, volumes[s.idx]],
    symbol: 'circle',
    symbolSize: 8,
    itemStyle: {
      color: s.type === 'B' ? '#ef4444' : '#22c55e',
      shadowBlur: 4,
      shadowColor: s.type === 'B' ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)',
    },
    label: {
      show: true,
      formatter: s.label,
      color: s.type === 'B' ? '#ef4444' : '#22c55e',
      fontSize: 8,
      fontWeight: 'bold',
      position: 'top',
      distance: 3,
    },
    value: s.reason,
  }));

  const techMarks = techSignals.map(s => {
    const idx = dates.indexOf(s.date);
    const k = klines[idx];
    if (!k) return null;
    const isB = s.type === 'B';
    return {
      coord: [idx, isB ? k.low : k.high],
      symbol: 'circle',
      symbolSize: 16,
      symbolOffset: isB ? [0, '120%'] : [0, '-120%'],
      itemStyle: {
        color: isB ? '#ef4444' : '#22c55e',
        borderColor: '#fff',
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: isB ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)',
      },
      label: {
        show: true,
        formatter: s.type,
        color: '#fff',
        fontSize: 10,
        fontWeight: 'bold',
      },
      z: 100,
    };
  }).filter(Boolean);

  const tradeMarks = tradeRecords.map(t => {
    const idx = dates.indexOf(t.date);
    if (idx < 0) return null;
    return {
      coord: [idx, t.price],
      symbol: 'circle',
      symbolSize: 10,
      itemStyle: {
        color: t.type === 'B' ? '#ef4444' : '#22c55e',
        borderColor: '#fff',
        borderWidth: 2,
      },
      label: {
        show: true,
        formatter: t.type,
        color: '#fff',
        fontSize: 9,
        fontWeight: 'bold',
        position: 'inside',
      },
    };
  }).filter(Boolean);

  const commonAxis = {
    axisLine: { lineStyle: { color: 'var(--border-color)' } },
    axisLabel: { color: 'var(--text-muted)', fontSize: 9 },
  };

  const dataZoom = [
    { type: 'inside', start: 40, end: 100, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true },
    { type: 'slider', bottom: 0, height: 14, borderColor: 'var(--border-color)', textStyle: { color: 'var(--text-muted)', fontSize: 9 } },
  ];

  const makeTooltip = (extraFn) => ({
    ...tooltipStyle,
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    formatter: (params) => {
      const idx = params[0]?.dataIndex;
      if (idx == null || !klines[idx]) return '';
      const k = klines[idx];
      const change = ((k.close - k.open) / k.open * 100).toFixed(2);
      const chgColor = k.close >= k.open ? '#ef4444' : '#22c55e';
      let html = `<div style="font-weight:700;margin-bottom:4px">${k.date}</div>`;
      html += `<div>开:${k.open.toFixed(2)} 收:<span style="color:${chgColor};font-weight:600">${k.close.toFixed(2)}</span> 涨跌:<span style="color:${chgColor}">${change}%</span></div>`;
      html += `<div>高:${k.high.toFixed(2)} 低:${k.low.toFixed(2)}</div>`;
      html += `<div>量:${(k.volume / 10000).toFixed(0)}万手</div>`;
      if (indicators.ma5[idx] != null) html += `<div>MA5:${indicators.ma5[idx]} MA20:${indicators.ma20[idx] ?? '--'}</div>`;
      if (indicators.supertrend?.[idx] != null) html += `<div>SuperTrend:${indicators.supertrend[idx]}</div>`;
      if (extraFn) html += extraFn(idx);
      const sig = techSignals.find(s => s.date === k.date);
      if (sig) {
        html += `<div style="margin-top:4px;color:${sig.type === 'B' ? '#ef4444' : '#22c55e'};font-weight:600">${sig.type === 'B' ? 'B 买入信号' : 'S 卖出信号'}</div>`;
        sig.reasons.forEach(r => html += `<div style="font-size:11px;color:#999">└ ${r}</div>`);
      }
      return html;
    },
  });

  // === K线主图 option ===
  const priceOption = {
    animation: false,
    tooltip: makeTooltip(),
    grid: { left: 50, right: 12, top: 8, bottom: 22 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { show: true, color: 'var(--text-muted)', fontSize: 9, formatter: v => v.slice(5), interval: Math.floor(dates.length / 6) },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    yAxis: {
      scale: true,
      axisLabel: { color: 'var(--text-secondary)', fontSize: 9, formatter: v => v.toFixed(2) },
      splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
    },
    dataZoom,
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: { color: '#ef4444', color0: '#22c55e', borderColor: '#ef4444', borderColor0: '#22c55e' },
        markPoint: { data: [...techMarks, ...tradeMarks], animation: false },
      },
      { name: 'MA5', type: 'line', data: indicators.ma5, smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#eab308' } },
      { name: 'MA20', type: 'line', data: indicators.ma20, smooth: true, symbol: 'none', lineStyle: { width: 1, color: '#3b82f6' } },
      { name: 'SuperTrend', type: 'line', data: indicators.supertrend, symbol: 'none', smooth: false, lineStyle: { width: 2, color: '#a855f7' }, z: 5 },
    ],
  };

  // === 成交量 option ===
  const volumeOption = {
    animation: false,
    tooltip: makeTooltip(),
    grid: { left: 50, right: 12, top: 8, bottom: 22 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { show: true, color: 'var(--text-muted)', fontSize: 9, formatter: v => v.slice(5), interval: Math.floor(dates.length / 6) },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    yAxis: {
      axisLabel: { color: 'var(--text-muted)', fontSize: 8, formatter: v => (v / 10000).toFixed(0) + '万' },
      splitLine: { show: false },
    },
    dataZoom,
    series: [{
      name: '成交量',
      type: 'bar',
      data: volumes.map((v, i) => ({
        value: v,
        itemStyle: {
          color: (() => {
            if (i >= 5) {
              const avg5 = volumes.slice(i - 5, i).reduce((a, b) => a + b, 0) / 5;
              if (v >= avg5 * 1.5) {
                return klines[i].close >= klines[i].open ? 'rgba(239,68,68,0.95)' : 'rgba(34,197,94,0.95)';
              }
            }
            return klines[i].close >= klines[i].open ? 'rgba(239,68,68,0.5)' : 'rgba(34,197,94,0.5)';
          })(),
        },
      })),
      markPoint: { data: volumeMarks, animation: false },
    }],
  };

  // === MACD+KDJ option ===
  const macdKdjOption = {
    animation: false,
    tooltip: makeTooltip((idx) => {
      let html = '';
      if (indicators.dif[idx] != null) html += `<div>DIF:${indicators.dif[idx]} DEA:${indicators.dea[idx]} MACD:${indicators.macd[idx]}</div>`;
      if (indicators.kdj_k[idx] != null) html += `<div>K:${indicators.kdj_k[idx]} D:${indicators.kdj_d[idx]} J:${indicators.kdj_j[idx]}</div>`;
      return html;
    }),
    grid: { left: 50, right: 50, top: 8, bottom: 22 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { show: true, color: 'var(--text-muted)', fontSize: 9, formatter: v => v.slice(5), interval: Math.floor(dates.length / 6) },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    yAxis: [
      { axisLabel: { color: 'var(--text-muted)', fontSize: 8 }, splitLine: { show: false } },
      { position: 'right', min: 0, max: 100, axisLabel: { color: 'var(--text-muted)', fontSize: 8 }, splitLine: { show: false } },
    ],
    dataZoom,
    series: [
      { name: 'MACD', type: 'bar', data: indicators.macd.map(v => ({ value: v, itemStyle: { color: v >= 0 ? 'rgba(239,68,68,0.6)' : 'rgba(34,197,94,0.6)' } })) },
      { name: 'DIF', type: 'line', data: indicators.dif, symbol: 'none', lineStyle: { width: 1, color: '#ffffff' } },
      { name: 'DEA', type: 'line', data: indicators.dea, symbol: 'none', lineStyle: { width: 1, color: '#f97316' } },
      { name: 'K', type: 'line', data: indicators.kdj_k, yAxisIndex: 1, symbol: 'none', lineStyle: { width: 1, color: '#fbbf24' } },
      { name: 'D', type: 'line', data: indicators.kdj_d, yAxisIndex: 1, symbol: 'none', lineStyle: { width: 1, color: '#22d3ee' } },
      { name: 'J', type: 'line', data: indicators.kdj_j, yAxisIndex: 1, symbol: 'none', lineStyle: { width: 1, color: '#f43f5e' } },
    ],
  };

  const ChartBox = ({ title, children, className = '' }) => (
    <div className={`rounded-lg border flex flex-col overflow-hidden ${className}`} style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', minHeight: 0 }}>
      <div className="text-[10px] font-bold px-2 pt-1.5 pb-0.5 flex-shrink-0 flex items-center justify-between" style={{ color: 'var(--text-secondary)' }}>
        <span>{title}</span>
      </div>
      <div className="flex-1" style={{ minHeight: 0 }}>
        {children}
      </div>
    </div>
  );

  const wrapperStyle = height ? { height } : undefined;

  // compact 模式：小图场景（WatchlistPage 右侧），只渲染单个 K 线主图
  if (compact) {
    return (
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', height }}>
        <ReactECharts echarts={echarts} option={priceOption} notMerge={true} key={`${sc}-compact`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
      </div>
    );
  }

  return (
    <div className="grid gap-1.5 h-full" style={{ gridTemplateRows: '1fr 0.6fr 0.8fr', ...wrapperStyle }}>
      <ChartBox title="K线主图">
        <ReactECharts echarts={echarts} option={priceOption} notMerge={true} key={`${sc}-price`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
      </ChartBox>
      <ChartBox title="成交量">
        <ReactECharts echarts={echarts} option={volumeOption} notMerge={true} key={`${sc}-vol`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
      </ChartBox>
      <ChartBox title="MACD + KDJ">
        <ReactECharts echarts={echarts} option={macdKdjOption} notMerge={true} key={`${sc}-macd`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
      </ChartBox>
    </div>
  );
}
