import { memo, useEffect, useRef, useState } from 'react';
import { createChart, AreaSeries, HistogramSeries, LineSeries } from 'lightweight-charts';
import { apiFetch } from '../../utils/request';
import { POLL_INTERVAL } from '../../utils/constants';

/**
 * 分时面板（2×3网格右侧三格）
 * 上：当日5分钟分时走势
 * 中：板块当天实时热度（成分股合成）
 * 下：板块7天热度折线
 */
function IntradayPanel({ code }) {
  const intradayRef = useRef(null);
  const sectorTodayRef = useRef(null);
  const sector7dRef = useRef(null);
  const chartRefs = useRef({});
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const load = async () => {
      const { ok, data } = await apiFetch(`/api/trading/intraday/${code}`);
      if (!cancelled) {
        if (ok) setData(data);
        setLoading(false);
      }
    };
    load();
    const timer = setInterval(load, POLL_INTERVAL);
    return () => { cancelled = true; clearInterval(timer); cleanupAll(); };
  }, [code]);

  function cleanupAll() {
    for (const key of ['intraday', 'sectorToday', 'sector7d']) {
      const c = chartRefs.current[key];
      if (c?.chart) { try { c.chart.remove(); } catch {} }
      if (c?.ro) c.ro.disconnect();
    }
    chartRefs.current = {};
  }

  function buildChart(container, opts) {
    const { timeFormat, timeScale: userTimeScale, labelMap, ...restOpts } = opts || {};
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight || 120,
      layout: { background: { color: 'transparent' }, textColor: '#9ca3af', fontSize: 9 },
      grid: { vertLines: { color: 'rgba(255,255,255,0.03)' }, horzLines: { color: 'rgba(255,255,255,0.03)' } },
      timeScale: {
        borderColor: 'rgba(255,255,255,0.1)',
        tickMarkFormatter: (time) => {
          // 虚拟时间轴模式：用 labelMap 反查真实 HH:MM
          if (labelMap) {
            const idx = Math.round(Number(time) / 300);
            return labelMap[idx] || '';
          }
          let ts = time;
          if (typeof time === 'string') {
            ts = Math.floor(new Date(time).getTime() / 1000);
          }
          const d = new Date((ts + 28800) * 1000); // UTC→北京时间
          if (timeFormat === 'date') return `${d.getUTCMonth() + 1}/${d.getUTCDate()}`;
          return `${String(d.getUTCHours()).padStart(2, '0')}:${String(d.getUTCMinutes()).padStart(2, '0')}`;
        },
        ...userTimeScale,
      },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.1)' },
      crosshair: { mode: 1 },
      ...restOpts,
    });
    const ro = new ResizeObserver(e => {
      const w = e[0]?.contentRect?.width;
      const h = e[0]?.contentRect?.height;
      if (w) chart.applyOptions({ width: w });
      if (h) chart.applyOptions({ height: h });
    });
    ro.observe(container);
    return { chart, ro };
  }

  // 分时图
  useEffect(() => {
    if (!data?.intraday?.length || !intradayRef.current) return;
    const old = chartRefs.current.intraday;
    if (old?.chart) { try { old.chart.remove(); } catch { /* chart cleanup: ignore */ } }
    if (old?.ro) old.ro.disconnect();

    // 构建连续虚拟时间轴：每根 K 线间隔 300 秒，消除午休和隔夜间隔
    // labelMap 用于 tickMarkFormatter 反查真实 HH:MM
    const labelMap = data.intraday.map(k => {
      const t = k.time || '';
      return t.length >= 16 ? t.slice(11, 16) : t;
    });

    const { chart, ro } = buildChart(intradayRef.current, {
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true, secondsVisible: false },
      labelMap,
    });

    const sq = data.stockQuote;
    const isUp = sq ? sq.changePct >= 0 : true;
    const color = isUp ? '#ef4444' : '#22c55e';

    const area = chart.addSeries(AreaSeries, {
      lineColor: color, topColor: `${color}44`, bottomColor: `${color}05`,
      lineWidth: 2, priceLineVisible: true, lastValueVisible: true,
    });
    area.setData(data.intraday.map((k, idx) => ({
      time: idx * 300, // 虚拟时间戳
      value: k.close,
    })));

    const vol = chart.addSeries(HistogramSeries, {
      priceScaleId: 'vol', priceLineVisible: false, lastValueVisible: false,
    });
    vol.setData(data.intraday.map((k, idx) => ({
      time: idx * 300,
      value: k.volume,
      color: k.close >= k.open ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)',
    })));
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chart.timeScale().fitContent();
    chartRefs.current.intraday = { chart, ro };
  }, [data]);

  // 板块当天实时热度
  useEffect(() => {
    if (!data?.sector_today_series?.length || !sectorTodayRef.current) return;
    const old = chartRefs.current.sectorToday;
    if (old?.chart) { try { old.chart.remove(); } catch {} }
    if (old?.ro) old.ro.disconnect();

    const { chart, ro } = buildChart(sectorTodayRef.current, {
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: true, secondsVisible: false },
    });

    const series = data.sector_today_series;
    const last = series[series.length - 1].value;
    const color = last >= 0 ? '#ef4444' : '#22c55e';

    const line = chart.addSeries(LineSeries, {
      color, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
    });
    line.setData(series.map(h => ({
      time: h.ts,
      value: h.value,
    })));

    chart.timeScale().fitContent();
    chartRefs.current.sectorToday = { chart, ro };
  }, [data]);

  // 板块7天热度
  useEffect(() => {
    if (!data?.sector?.heat_series?.length || !sector7dRef.current) return;
    const old = chartRefs.current.sector7d;
    if (old?.chart) { try { old.chart.remove(); } catch { /* chart cleanup: ignore */ } }
    if (old?.ro) old.ro.disconnect();

	    const { chart, ro } = buildChart(sector7dRef.current, {
      timeFormat: 'date',
      timeScale: { borderColor: 'rgba(255,255,255,0.1)', timeVisible: false },
    });

    const heatTrend = data.sector.heat_trend;
    const heatColor = heatTrend === 'up' ? '#ef4444' : heatTrend === 'down' ? '#22c55e' : '#a855f7';

    const line = chart.addSeries(LineSeries, {
      color: heatColor, lineWidth: 2, priceLineVisible: false, lastValueVisible: true,
    });
    line.setData(data.sector.heat_series.map(h => ({
      time: h.date,
      value: h.heat,
    })));

    chart.timeScale().fitContent();
    chartRefs.current.sector7d = { chart, ro };
  }, [data]);

  const sq = data?.stockQuote;
  const sector = data?.sector;
  const todaySeries = data?.sector_today_series || [];

  const ChartBox = ({ title, extra, children, className = '' }) => (
    <div className={`rounded-lg border flex flex-col overflow-hidden ${className}`} style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', minHeight: 0 }}>
      <div className="text-[10px] font-bold px-2 pt-1.5 pb-0.5 flex-shrink-0 flex items-center justify-between" style={{ color: 'var(--text-secondary)' }}>
        <span>{title}</span>
        {extra && <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>{extra}</span>}
      </div>
      <div className="flex-1" style={{ minHeight: 0 }}>
        {children}
      </div>
    </div>
  );

  return (
    <div className="grid gap-1.5 h-full" style={{ gridTemplateRows: '1fr 0.6fr 0.8fr' }}>
      {/* 分时图（第1行） */}
      <ChartBox
        title="当日分时（5分钟）"
        extra={sq ? `${sq.name} ${sq.price.toFixed(2)} ${sq.changePct >= 0 ? '+' : ''}${sq.changePct}%` : ''}
      >
        {loading ? (
          <div className="h-full flex items-center justify-center text-[11px]" style={{ color: 'var(--text-muted)' }}>加载中…</div>
        ) : data?.intraday?.length > 0 ? (
          <div ref={intradayRef} className="w-full h-full" />
        ) : (
          <div className="h-full flex items-center justify-center text-[11px]" style={{ color: 'var(--text-muted)' }}>无分时数据</div>
        )}
      </ChartBox>

      {/* 板块当天实时热度（第2行） */}
      <ChartBox
        title={`板块当天热度 ${sector?.name || '—'}`}
        extra={todaySeries.length > 0 ? `采样${todaySeries.length}次` : ''}
      >
        {todaySeries.length >= 2 ? (
          <div ref={sectorTodayRef} className="w-full h-full" />
        ) : todaySeries.length === 1 ? (
          <div className="h-full flex flex-col items-center justify-center gap-1">
            <span className="text-2xl font-bold" style={{ color: todaySeries[0].value >= 0 ? '#ef4444' : '#22c55e' }}>
              {todaySeries[0].value >= 0 ? '+' : ''}{todaySeries[0].value}%
            </span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>板块成分股平均涨跌（实时）</span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>更新时间 {todaySeries[0].time}</span>
          </div>
        ) : (
          <div className="h-full flex items-center justify-center text-[11px]" style={{ color: 'var(--text-muted)' }}>暂无板块当天数据</div>
        )}
      </ChartBox>

      {/* 板块7天热度（第3行） */}
      <ChartBox
        title={`板块7天热度 ${sector?.name || '—'}`}
        extra={sector?.latest_heat > 0 ? `热度${sector.latest_heat} ${sector.heat_trend === 'up' ? '↑' : sector.heat_trend === 'down' ? '↓' : '→'}` : ''}
      >
        {sector?.heat_series?.length > 0 ? (
          <div ref={sector7dRef} className="w-full h-full" />
        ) : (
          <div className="h-full flex items-center justify-center text-[11px]" style={{ color: 'var(--text-muted)' }}>无板块数据</div>
        )}
      </ChartBox>
    </div>
  );
}

export default memo(IntradayPanel);
