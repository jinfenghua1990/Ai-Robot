import { memo, useEffect, useRef, useState } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries } from 'lightweight-charts';
import { UP_COLOR, DOWN_COLOR, B_SIGNAL_COLOR, S_SIGNAL_COLOR } from '../../utils/colors';
import { apiFetch } from '../../utils/request';

/**
 * K线图组件（memoized：仅在 code 变化时重新拉取渲染）
 * 叠加：
 *  - 蜡烛K线（价格）
 *  - SuperTrend 操盘线（黄色）
 *  - 板块趋势线（紫色 Area）：该股所属板块的近期热量走势，独立 Y 轴
 *  - B/S 买卖点 markers
 */
function KLineChart({ code, height = 260 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef({});
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState('');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setErr('');

    (async () => {
      try {
        const { ok, data, error } = await apiFetch(`/api/trading/bs-signals?stockCode=${code}&datalen=120`);
        if (cancelled) return;
        if (!ok) { setErr(error || '加载失败'); setLoading(false); return; }
        if (data.detail) throw new Error(data.detail);
        render(data);
        setLoading(false);
      } catch (e) {
        if (!cancelled) { setErr(e.message); setLoading(false); }
      }
    })();

    return () => { cancelled = true; cleanup(); };
  }, [code]);

  function cleanup() {
    if (chartRef.current) {
      try { chartRef.current.remove(); } catch {}
      chartRef.current = null;
      seriesRef.current = {};
    }
  }

  function render(data) {
    cleanup();
    if (!containerRef.current) return;
    const klines = data.klines || [];
    if (klines.length === 0) { setErr('无K线数据'); return; }

    const chart = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height,
      layout: { background: { color: 'transparent' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
    });
    chartRef.current = chart;

    // 1) K线
    const candle = chart.addSeries(CandlestickSeries, {
      upColor: UP_COLOR, downColor: DOWN_COLOR,
      borderUpColor: UP_COLOR, borderDownColor: DOWN_COLOR,
      wickUpColor: UP_COLOR, wickDownColor: DOWN_COLOR,
    });
    candle.setData(klines.map(k => ({
      time: k.date,
      open: k.open, high: k.high, low: k.low, close: k.close,
    })));
    seriesRef.current.candle = candle;

    // 2) SuperTrend 操盘线（与 K线同 Y 轴，多头=绿支撑 / 空头=红阻力）
    const supertrend = data.indicators?.supertrend || [];
    if (supertrend.length > 0) {
      const line = chart.addSeries(LineSeries, {
        color: '#eab308', lineWidth: 2, title: 'SuperTrend',
        priceLineVisible: false, lastValueVisible: false,
      });
      const points = [];
      klines.forEach((k, i) => {
        if (supertrend[i] != null) points.push({ time: k.date, value: supertrend[i] });
      });
      line.setData(points);
      seriesRef.current.supertrend = line;
    }

    // 3) 板块趋势线 - 独立 Y 轴，紫色 Area
    // strategy_engine 已经在 watchlist signal.sectorTrend.heat_series 暴露 7 天板块数据
    // 这里直接从 watchlist 缓存里取
    const sectorSeries = buildSectorSeries(code, klines);
    if (sectorSeries && sectorSeries.length > 0) {
      const heatLine = chart.addSeries(AreaSeries, {
        priceScaleId: 'sector',
        lineColor: '#a855f7', topColor: 'rgba(168,85,247,0.4)', bottomColor: 'rgba(168,85,247,0.05)',
        lineWidth: 2, title: '板块热量',
        priceLineVisible: false, lastValueVisible: false,
      });
      heatLine.setData(sectorSeries);
      seriesRef.current.heatLine = heatLine;
      chart.priceScale('sector').applyOptions({
        scaleMargins: { top: 0.7, bottom: 0 },  // 板块线放主图顶部 30% 区域
        borderColor: 'rgba(168,85,247,0.3)',
      });
    }

    // 4) BS 点 markers
    const techSignals = data.techSignals || [];
    if (techSignals.length > 0) {
      const markers = techSignals.map(s => ({
        time: s.date,
        position: s.type === 'B' ? 'belowBar' : 'aboveBar',
        color: s.type === 'B' ? B_SIGNAL_COLOR : S_SIGNAL_COLOR,
        shape: s.type === 'B' ? 'arrowUp' : 'arrowDown',
        text: s.type,
      }));
      try { candle.setMarkers(markers); } catch { /* chart cleanup: ignore */ }
    }

    // 自适应
    chart.timeScale().fitContent();
    const ro = new ResizeObserver(entries => {
      const w = entries[0]?.contentRect?.width;
      if (w) chart.applyOptions({ width: w });
    });
    ro.observe(containerRef.current);
    seriesRef.current._ro = ro;
  }

  // 7 天板块热度序列对齐到 K线时间轴（最近一天对齐到 K线最后一天）
  function buildSectorSeries(code, klines) {
    // 同步拿一下 watchlist 缓存里的 sectorTrend
    // 简单做法：直接 fetch /api/watchlist 拿到 selected 的 sectorTrend
    // 但这里为了避免 race condition，直接从全局 fetch
    const data = window.__wlSectorCache || {};
    const heatSeries = data[code];
    if (!heatSeries || heatSeries.length === 0) return null;
    // 对齐：板块 series 7 天 → 摊到 K线最后 7 根上
    const tail = klines.slice(-heatSeries.length);
    if (tail.length === 0) return null;
    return tail.map((k, i) => ({
      time: k.date,
      value: heatSeries[i]?.heat ?? 0,
    })).filter(p => p.value != null);
  }

  if (err) return <div className="h-full flex items-center justify-center text-xs" style={{ color: '#ef4444' }}>{err}</div>;
  return (
    <div className="relative">
      {loading && <div className="absolute inset-0 flex items-center justify-center text-xs" style={{ color: 'var(--text-muted)' }}>加载K线…</div>}
      <div ref={containerRef} style={{ height }} />
    </div>
  );
}

export default memo(KLineChart);
