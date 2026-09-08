import { useState, useEffect } from 'react';
import ReactECharts from 'echarts-for-react/esm/core';
import echarts from '../../lib/echarts';
import { tooltipStyle } from '../../utils/chartConfig';
import { apiFetch } from '../../utils/request';

/**
 * K线图组件：完整模式使用同一坐标画布对齐价格、成交量与MACD+KDJ；
 * MACD使用左轴，KDJ使用0-100右轴，保持时间轴一致且避免量纲互相干扰。
 * 通过 onSummary 回调把 summary 数据传给父组件
 */
function hexToRgba(hex, a) {
  const h = hex.replace('#', '');
  const r = parseInt(h.slice(0, 2), 16), g = parseInt(h.slice(2, 4), 16), b = parseInt(h.slice(4, 6), 16);
  return `rgba(${r},${g},${b},${a})`;
}

export default function KLineChart({ stockCode, code, height, onSummary, upColor = '#ef4444', downColor = '#22c55e', dataAsOf }) {
  // 兼容旧调用：code / height
  // compact 模式：传入 height（小图场景，如 WatchlistPage 右侧）只渲染单个 K 线主图
  const sc = stockCode || code;

  const compact = !!height;
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!sc) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    const query = new URLSearchParams({ stockCode: sc, datalen: '60' });
    if (dataAsOf) query.set('as_of', dataAsOf);
    apiFetch(`/api/trading/bs-signals?${query.toString()}`).then(({ ok, data, error }) => {
      if (cancelled) return;
      if (ok) {
        setData(data);
        if (onSummary && data?.summary) onSummary(data.summary);
      } else {
        setError(error);
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [sc, onSummary, dataAsOf]);

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

  const { klines = [], indicators: rawInd = {}, techSignals = [], tradeRecords = [] } = data;
  if (!klines.length || !rawInd.ma5) return (
    <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>
      无K线数据
    </div>
  );
  // 防御性兜底：后端在计算降级时可能仅返回部分指标数组（例如有 ma5 但缺 macd/dif 等），
  // 未兜底会导致 indicators.macd.map(...) 抛 "Cannot read properties of undefined" 并触发 ErrorBoundary 白屏。
  // 统一把缺失的指标数组强制为 []，图表区域为空但不崩溃。
  const indicators = {
    ma5: rawInd.ma5 || [],
    ma20: rawInd.ma20 || [],
    supertrend: rawInd.supertrend || [],
    macd: rawInd.macd || [],
    dif: rawInd.dif || [],
    dea: rawInd.dea || [],
    kdj_k: rawInd.kdj_k || [],
    kdj_d: rawInd.kdj_d || [],
    kdj_j: rawInd.kdj_j || [],
  };
  // 日K图严格展示已完成交易日；实时行情单独由“盘中分时”区域展示，
  // 不把当日价格篡改为上一交易日蜡烛，避免指标和图形日期不一致。
  const displayKlines = klines;
  const dates = displayKlines.map(k => k.date);
  const ohlc = displayKlines.map(k => [k.open, k.close, k.low, k.high]);
  const volumes = displayKlines.map(k => k.volume);

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

  // 窄图只保留最近的有效量价标记，避免标签覆盖K线阅读区。
  const volumeMarks = volumeSignals.slice(-8).map(s => ({
    coord: [s.idx, volumes[s.idx]],
    symbol: 'circle',
    symbolSize: 8,
      itemStyle: {
        color: s.type === 'B' ? upColor : downColor,
        shadowBlur: 4,
        shadowColor: s.type === 'B' ? hexToRgba(upColor, 0.5) : hexToRgba(downColor, 0.5),
      },
    label: {
      show: true,
        formatter: s.label,
        color: s.type === 'B' ? upColor : downColor,
      fontSize: 8,
      fontWeight: 'bold',
      position: 'top',
      distance: 3,
    },
    value: s.reason,
  }));

  const techMarks = techSignals.map(s => {
    const idx = dates.indexOf(s.date);
    const k = displayKlines[idx];
    if (!k) return null;
    const isB = s.type === 'B';
    return {
      coord: [idx, isB ? k.low : k.high],
      symbol: 'circle',
      symbolSize: 16,
      symbolOffset: isB ? [0, '120%'] : [0, '-120%'],
      itemStyle: {
        color: isB ? upColor : downColor,
        borderColor: '#fff',
        borderWidth: 2,
        shadowBlur: 6,
        shadowColor: isB ? hexToRgba(upColor, 0.5) : hexToRgba(downColor, 0.5),
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
        color: t.type === 'B' ? upColor : downColor,
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

  // === B/S 区间带（首买~末卖，原型浅蓝带；与 K 线同一坐标系，可直接对比）===
  const bsIdx = [];
  (techSignals || []).forEach(s => { const i = dates.indexOf(s.date); if (i >= 0) bsIdx.push(i); });
  (tradeRecords || []).forEach(t => { const i = dates.indexOf(t.date); if (i >= 0) bsIdx.push(i); });
  const bsBand = bsIdx.length >= 2
    ? [[{ xAxis: dates[Math.min(...bsIdx)] }, { xAxis: dates[Math.max(...bsIdx)] }]]
    : null;



  const visibleSessions = Math.min(40, dates.length);
  const zoomStart = dates.length ? Math.max(0, 100 - (visibleSessions / dates.length) * 100) : 0;
  const compactDataZoom = [
    { type: 'inside', start: zoomStart, end: 100, zoomOnMouseWheel: false, moveOnMouseWheel: false, moveOnMouseMove: true },
  ];

  const makeTooltip = (extraFn) => ({
    ...tooltipStyle,
    trigger: 'axis',
    axisPointer: { type: 'cross' },
    formatter: (params) => {
      const idx = params.find(p => p?.dataIndex != null)?.dataIndex;
      if (idx == null || !displayKlines[idx]) return '';
      const k = displayKlines[idx];
      const change = ((k.close - k.open) / k.open * 100).toFixed(2);
      const chgColor = k.close >= k.open ? upColor : downColor;
      let html = `<div style="font-weight:700;margin-bottom:4px">${k.date}</div>`;
      html += `<div>开:${k.open.toFixed(2)} 收:<span style="color:${chgColor};font-weight:600">${k.close.toFixed(2)}</span> 涨跌:<span style="color:${chgColor}">${change}%</span></div>`;
      html += `<div>高:${k.high.toFixed(2)} 低:${k.low.toFixed(2)}</div>`;
      html += `<div>量:${(k.volume / 10000).toFixed(0)}万手</div>`;
      if (indicators.ma5[idx] != null) html += `<div>MA5:${indicators.ma5[idx]} MA20:${indicators.ma20[idx] ?? '--'}</div>`;
      if (indicators.supertrend?.[idx] != null) html += `<div>SuperTrend:${indicators.supertrend[idx]}</div>`;
      if (extraFn) html += extraFn(idx);
      const sig = techSignals.find(s => s.date === k.date);
      if (sig) {
        html += `<div style="margin-top:4px;color:${sig.type === 'B' ? upColor : downColor};font-weight:600">${sig.type === 'B' ? 'B 买入信号' : 'S 卖出信号'}</div>`;
        sig.reasons.forEach(r => html += `<div style="font-size:11px;color:#999">└ ${r}</div>`);
      }
      return html;
    },
  });

  // === K线主图 option ===
  const priceOption = {
    animation: false,
    tooltip: makeTooltip(),
    grid: { left: 50, right: 12, top: 8, bottom: 18 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { show: true, color: 'var(--text-muted)', fontSize: 9, formatter: v => (typeof v === 'number' ? '' : (v || '').slice(5)), interval: Math.floor(dates.length / 6) },
      axisLine: { lineStyle: { color: 'var(--border-color)' } },
    },
    yAxis: {
      scale: true,
      axisLabel: { color: 'var(--text-secondary)', fontSize: 9, formatter: v => v.toFixed(2) },
      splitLine: { lineStyle: { color: 'var(--border-color)', type: 'dashed', opacity: 0.3 } },
    },
    dataZoom: compactDataZoom,
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        barMinWidth: 4,
        barMaxWidth: 12,
        itemStyle: { color: upColor, color0: downColor, borderColor: upColor, borderColor0: downColor },
        markPoint: { data: [...techMarks, ...tradeMarks], animation: false },
        ...(bsBand ? { markArea: { silent: true, itemStyle: { color: 'rgba(56,138,221,0.10)', borderColor: '#85B7EB', borderWidth: 1, borderType: 'dashed' }, data: bsBand } } : {}),
      },
      { name: 'MA5', type: 'line', data: indicators.ma5, symbol: 'none', lineStyle: { width: 1.4, color: '#eab308', opacity: 0.9 } },
      { name: 'MA20', type: 'line', data: indicators.ma20, symbol: 'none', lineStyle: { width: 1.4, color: '#3b82f6', opacity: 0.9 } },
      { name: 'SuperTrend', type: 'line', data: indicators.supertrend, symbol: 'none', smooth: false, lineStyle: { width: 1.5, color: '#a855f7', opacity: 0.85 }, z: 5 },
    ],
  };

  const volumeSeriesData = volumes.map((v, i) => ({
    value: v,
    itemStyle: {
      color: (() => {
        if (i >= 5) {
          const avg5 = volumes.slice(i - 5, i).reduce((a, b) => a + b, 0) / 5;
          if (v >= avg5 * 1.5) {
            return klines[i].close >= klines[i].open ? hexToRgba(upColor, 0.9) : hexToRgba(downColor, 0.9);
          }
        }
        return klines[i].close >= klines[i].open ? hexToRgba(upColor, 0.48) : hexToRgba(downColor, 0.48);
      })(),
    },
  }));

  const axisLabelInterval = Math.max(0, Math.floor(visibleSessions / 6) - 1);
  const axisTextColor = '#7c8aa0';
  const axisLineColor = 'rgba(148,163,184,0.28)';
  const splitLineColor = 'rgba(148,163,184,0.16)';

  // KDJ 轴自适应范围：J = 3K - 2D，强趋势下 J 会跌破 0 或突破 100。
  // 若 K/D/J 都在 [0,100] 内则保持经典 0-100 观感；否则按数据扩展范围并加 10% 缓冲，
  // 避免 J 线尖峰超出绘图区被裁切。
  const kdjAxis = (() => {
    let min = 0, max = 100;
    for (let i = 0; i < indicators.kdj_j.length; i++) {
      const j = indicators.kdj_j[i];
      if (j == null) continue;
      if (j < min) min = j;
      if (j > max) max = j;
    }
    if (min === 0 && max === 100) return { min: 0, max: 100 };
    const pad = Math.max((max - min) * 0.1, 5);
    return { min: Math.floor(min - pad), max: Math.ceil(max + pad) };
  })();

  // 完整模式：一个ECharts实例内对齐三组坐标；仅保留图内拖动缩放，不显示底部缩放条。
  const fullOption = {
    animation: false,
    backgroundColor: 'transparent',
    tooltip: makeTooltip((idx) => {
      const rows = [];
      if (indicators.dif[idx] != null) {
        rows.push(`<div>DIF:${indicators.dif[idx]} DEA:${indicators.dea[idx]} MACD:${indicators.macd[idx]}</div>`);
      }
      if (indicators.kdj_k[idx] != null) {
        rows.push(`<div>K:${indicators.kdj_k[idx]} D:${indicators.kdj_d[idx]} J:${indicators.kdj_j[idx]}</div>`);
      }
      return rows.join('');
    }),
    axisPointer: {
      link: [{ xAxisIndex: [0, 1, 2] }],
      label: { backgroundColor: '#475569', fontSize: 9 },
    },
    title: [
      { text: '价格', left: 10, top: 5, textStyle: { color: axisTextColor, fontSize: 10, fontWeight: 600 } },
      { text: '成交量', left: 10, top: '51.5%', textStyle: { color: axisTextColor, fontSize: 10, fontWeight: 600 } },
      { text: 'MACD + KDJ', left: 10, top: '70.5%', textStyle: { color: axisTextColor, fontSize: 10, fontWeight: 600 } },
    ],
    legend: [
      {
        data: ['MA5', 'MA20', 'SuperTrend'],
        selectedMode: false,
        top: 4,
        right: 10,
        itemWidth: 12,
        itemHeight: 3,
        itemGap: 10,
        textStyle: { color: axisTextColor, fontSize: 9 },
      },
      {
        data: ['DIF', 'DEA', 'K', 'D', 'J'],
        selectedMode: false,
        top: '70.2%',
        right: 28,
        itemWidth: 11,
        itemHeight: 2,
        itemGap: 7,
        textStyle: { color: axisTextColor, fontSize: 8 },
      },
    ],
    grid: [
      { left: 46, right: 16, top: 30, height: '43%' },
      { left: 46, right: 16, top: '56%', height: '12%' },
      { left: 46, right: 32, top: '75%', bottom: 18 },
    ],
    xAxis: [0, 1, 2].map((gridIndex) => ({
      type: 'category',
      gridIndex,
      data: dates,
      boundaryGap: true,
      axisTick: { show: false },
      axisLine: { show: gridIndex === 2, lineStyle: { color: axisLineColor } },
      axisLabel: gridIndex === 2
        ? { show: true, color: axisTextColor, fontSize: 9, formatter: v => (typeof v === 'number' ? '' : (v || '').slice(5)), interval: axisLabelInterval }
        : { show: false },
      splitLine: { show: false },
      axisPointer: { show: true, snap: true },
    })),
    yAxis: [
      {
        gridIndex: 0,
        scale: true,
        splitNumber: 5,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: axisTextColor, fontSize: 9, formatter: v => Number(v).toFixed(2) },
        splitLine: { lineStyle: { color: splitLineColor, type: 'dashed' } },
      },
      {
        gridIndex: 1,
        splitNumber: 2,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: axisTextColor, fontSize: 8, formatter: v => `${(v / 10000).toFixed(0)}万` },
        splitLine: { show: false },
      },
      {
        gridIndex: 2,
        scale: true,
        splitNumber: 3,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: axisTextColor, fontSize: 8 },
        splitLine: { lineStyle: { color: splitLineColor, type: 'dashed' } },
      },
      {
        gridIndex: 2,
        position: 'right',
        min: kdjAxis.min,
        max: kdjAxis.max,
        splitNumber: 2,
        axisTick: { show: false },
        axisLine: { show: false },
        axisLabel: { color: axisTextColor, fontSize: 8, formatter: value => Number(value).toFixed(0) },
        splitLine: { show: false },
      },
    ],
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: [0, 1, 2],
        start: zoomStart,
        end: 100,
        zoomOnMouseWheel: false,
        moveOnMouseWheel: false,
        moveOnMouseMove: true,
      },
    ],
    series: [
      ...priceOption.series.map(series => ({ ...series, xAxisIndex: 0, yAxisIndex: 0 })),
      {
        name: '成交量',
        type: 'bar',
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 12,
        data: volumeSeriesData,
        markPoint: { data: volumeMarks, animation: false },
      },
      {
        name: 'MACD',
        type: 'bar',
        xAxisIndex: 2,
        yAxisIndex: 2,
        barMaxWidth: 12,
        data: indicators.macd.map(v => ({ value: v, itemStyle: { color: v >= 0 ? hexToRgba(upColor, 0.62) : hexToRgba(downColor, 0.62) } })),
        markLine: { silent: true, symbol: 'none', label: { show: false }, lineStyle: { color: axisLineColor, width: 1 }, data: [{ yAxis: 0 }] },
      },
      { name: 'DIF', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: indicators.dif, symbol: 'none', lineStyle: { width: 1.3, color: '#38bdf8' } },
      { name: 'DEA', type: 'line', xAxisIndex: 2, yAxisIndex: 2, data: indicators.dea, symbol: 'none', lineStyle: { width: 1.3, color: '#f59e0b' } },
      { name: 'K', type: 'line', xAxisIndex: 2, yAxisIndex: 3, data: indicators.kdj_k, symbol: 'none', lineStyle: { width: 1.15, color: '#fbbf24' }, z: 4 },
      { name: 'D', type: 'line', xAxisIndex: 2, yAxisIndex: 3, data: indicators.kdj_d, symbol: 'none', lineStyle: { width: 1.15, color: '#22d3ee' }, z: 4 },
      { name: 'J', type: 'line', xAxisIndex: 2, yAxisIndex: 3, data: indicators.kdj_j, symbol: 'none', lineStyle: { width: 1.15, color: '#f43f5e' }, z: 4 },
    ],
  };

  // compact 模式：小图场景（WatchlistPage 右侧），只渲染单个 K 线主图
  if (compact) {
    return (
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', height }}>
        <ReactECharts echarts={echarts} option={priceOption} notMerge={true} key={`${sc}-compact`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
      </div>
    );
  }

  return (
    <div className="h-full rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', boxShadow: 'inset 0 1px 0 rgba(148,163,184,0.06)' }}>
      <ReactECharts echarts={echarts} option={fullOption} notMerge={true} key={`${sc}-terminal`} style={{ height: '100%', width: '100%' }} opts={{ renderer: 'canvas' }} />
    </div>
  );
}
