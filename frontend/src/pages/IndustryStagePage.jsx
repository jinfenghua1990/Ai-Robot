import { useEffect, useMemo, useState } from 'react';
import ReactECharts from 'echarts-for-react/esm/core';

import echarts from '../lib/echarts';
import { apiFetch } from '../utils/request';
import { openStockAnalysis } from '../utils/openStockAnalysis';


const STATE_META = {
  ACTIVE: { label: '活跃', color: '#ef4444', bg: 'rgba(239,68,68,.10)' },
  CANDIDATE: { label: '候选', color: '#f59e0b', bg: 'rgba(245,158,11,.10)' },
  COOLING: { label: '降温', color: '#3b82f6', bg: 'rgba(59,130,246,.10)' },
  INACTIVE: { label: '观察', color: '#64748b', bg: 'rgba(100,116,139,.08)' },
};

const FILTERS = [
  ['ALL', '全部 31 行业'],
  ['ACTIVE', '活跃'],
  ['CANDIDATE', '候选'],
  ['COOLING', '降温'],
  ['INACTIVE', '观察'],
];

const fmt = (value, digits = 2) => value == null ? '—' : Number(value).toFixed(digits);
const pct = (value) => value == null ? '—' : `${value > 0 ? '+' : ''}${Number(value).toFixed(2)}%`;
const mv = (value) => {
  if (value == null) return '—';
  const yi = Number(value) / 10000;
  return yi >= 10000 ? `${(yi / 10000).toFixed(2)}万亿` : `${yi.toFixed(1)}亿`;
};
const amountWan = (value) => {
  if (value == null) return '—';
  const numeric = Number(value);
  return numeric >= 10000 ? `${(numeric / 10000).toFixed(2)}亿` : `${numeric.toFixed(0)}万`;
};
const clock = (value) => value ? String(value).slice(11, 19) : '—';
const changeColor = (value) => Number(value || 0) > 0
  ? '#dc2626'
  : Number(value || 0) < 0 ? '#16a34a' : '#64748b';

function applyRealtimeLayer(data, realtime) {
  if (!data?.sectors?.length || !realtime?.is_live) return data;
  const quoteMap = new Map(
    (realtime.quotes || []).filter((quote) => !quote.is_stale).map((quote) => [quote.ts_code, quote]),
  );
  const mergeStock = (stock) => {
    const quote = quoteMap.get(stock.ts_code);
    return quote ? {
      ...stock,
      price: quote.price,
      day_change_pct: quote.day_change_pct,
      realtime_amount_wan: quote.amount_wan,
      turnover_rate: quote.turnover_rate,
      volume_ratio: quote.volume_ratio,
      realtime_as_of: quote.snapshot_time,
      is_realtime: true,
    } : stock;
  };
  return {
    ...data,
    sectors: data.sectors.map((sector) => ({
      ...sector,
      stocks: (sector.stocks || []).map(mergeStock),
      children: (sector.children || []).map((child) => ({
        ...child,
        stocks: (child.stocks || []).map(mergeStock),
      })),
    })),
  };
}

function stockLeaf(stock, fallbackValue) {
  const value = Math.max(Number(stock.total_mv || fallbackValue || 1), 1);
  return {
    name: stock.name,
    value,
    kind: 'stock',
    stock,
    itemStyle: {
      color: changeColor(stock.day_change_pct),
      borderColor: 'rgba(255,255,255,.75)',
      borderWidth: 1,
    },
  };
}

function buildTreemap(sectors) {
  return sectors.map((sector) => {
    const children = (sector.children || []).map((l2) => {
      const useMarketCap = Number(l2.total_mv || 0) > 0;
      const leaves = (l2.stocks || []).map((stock) => stockLeaf(stock, useMarketCap ? 1 : 1));
      const selectedValue = leaves.reduce((sum, item) => sum + item.value, 0);
      const parentValue = useMarketCap ? Number(l2.total_mv) : Math.max(Number(l2.universe_count || 0), 1);
      const remainder = Math.max(parentValue - selectedValue, useMarketCap ? parentValue * 0.005 : 1);
      leaves.push({
        name: '其他成分',
        value: remainder,
        kind: 'remainder',
        itemStyle: { color: 'rgba(100,116,139,.22)', borderColor: 'rgba(255,255,255,.35)' },
      });
      return {
        name: l2.l2_name,
        value: parentValue,
        kind: 'l2',
        l1Code: sector.l1_code,
        l2Code: l2.l2_code,
        children: leaves,
      };
    });
    const meta = STATE_META[sector.state] || STATE_META.INACTIVE;
    return {
      name: sector.l1_name,
      value: Number(sector.total_mv || sector.universe_count || 1),
      kind: 'l1',
      l1Code: sector.l1_code,
      sector,
      children,
      itemStyle: { borderColor: meta.color },
    };
  });
}

function StatCard({ label, value, hint, color = 'var(--text-primary)' }) {
  return (
    <div className="rounded-xl border px-4 py-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="mt-1 text-xl font-bold" style={{ color }}>{value}</div>
      <div className="mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>{hint}</div>
    </div>
  );
}

export default function IndustryStagePage() {
  const [data, setData] = useState(null);
  const [realtime, setRealtime] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filter, setFilter] = useState('ALL');
  const [selectedCode, setSelectedCode] = useState('');

  useEffect(() => {
    const ctrl = new AbortController();
    setLoading(true);
    apiFetch('/api/industry-stage/v2/overview', { signal: ctrl.signal }, 12000, 1).then((result) => {
      if (!result.ok) {
        setError(result.error || '行业阶段池加载失败');
        setLoading(false);
        return;
      }
      setData(result.data);
      setError('');
      setLoading(false);
    });
    return () => ctrl.abort();
  }, []);

  useEffect(() => {
    let stopped = false;
    let timer = null;
    let ctrl = null;

    const loadRealtime = async () => {
      ctrl = new AbortController();
      const result = await apiFetch('/api/industry-stage/v2/realtime', { signal: ctrl.signal }, 8000, 0);
      if (stopped) return;
      if (result.ok) {
        setRealtime(result.data);
        const delaySeconds = Math.max(10, Number(result.data?.refresh_after_seconds || 30));
        timer = window.setTimeout(loadRealtime, delaySeconds * 1000);
      } else {
        setRealtime((current) => ({ ...current, status: 'FAILED', is_live: false, message: result.error || '实时行情读取失败' }));
        timer = window.setTimeout(loadRealtime, 30000);
      }
    };

    loadRealtime();
    return () => {
      stopped = true;
      if (timer) window.clearTimeout(timer);
      ctrl?.abort();
    };
  }, []);

  const displayData = useMemo(() => applyRealtimeLayer(data, realtime), [data, realtime]);

  useEffect(() => {
    if (!displayData?.sectors?.length || selectedCode) return;
    const first = displayData.sectors.find((sector) => sector.state === 'ACTIVE')
      || displayData.sectors.find((sector) => sector.state === 'CANDIDATE')
      || displayData.sectors[0];
    setSelectedCode(first?.l1_code || '');
  }, [displayData, selectedCode]);

  const visibleSectors = useMemo(() => (
    (displayData?.sectors || []).filter((sector) => filter === 'ALL' || sector.state === filter)
  ), [displayData, filter]);

  const selected = useMemo(() => (
    (displayData?.sectors || []).find((sector) => sector.l1_code === selectedCode) || visibleSectors[0] || null
  ), [displayData, selectedCode, visibleSectors]);

  const treeData = useMemo(() => buildTreemap(visibleSectors), [visibleSectors]);
  const option = useMemo(() => ({
    tooltip: {
      confine: true,
      backgroundColor: 'rgba(15,23,42,.94)',
      borderWidth: 0,
      textStyle: { color: '#f8fafc', fontSize: 12 },
      formatter: (params) => {
        const node = params.data || {};
        if (node.kind === 'stock') {
          const stock = node.stock;
          const quoteLine = stock.is_realtime
            ? `现价 ${fmt(stock.price)} · 涨跌 ${pct(stock.day_change_pct)} · 量比 ${fmt(stock.volume_ratio)}`
            : `收盘 ${fmt(stock.close)} · 当日 ${pct(stock.day_change_pct)}`;
          return `<b>${stock.name} ${stock.code}</b><br/>${quoteLine}<br/>20日 ${pct(stock.ret_20d)} · 阶段分 ${fmt(stock.score)}<br/><span style="color:#94a3b8">点击后在新标签页打开个股分析</span>`;
        }
        if (node.kind === 'l1') {
          const sector = node.sector;
          return `<b>${sector.l1_name}</b><br/>行业分 ${fmt(sector.score)} · ${STATE_META[sector.state]?.label || sector.state}<br/>阶段股 ${sector.selected_count}/${sector.max_candidates}`;
        }
        if (node.kind === 'l2') return `<b>${node.name}</b>`;
        return node.name || '';
      },
    },
    series: [{
      type: 'treemap',
      data: treeData,
      roam: false,
      nodeClick: false,
      breadcrumb: { show: false },
      visibleMin: 18,
      leafDepth: 3,
      squareRatio: 1.1,
      label: {
        show: true,
        color: '#fff',
        fontSize: 10,
        overflow: 'truncate',
        formatter: (params) => {
          const node = params.data || {};
          if (node.kind === 'stock') return `${node.stock.name}\n${pct(node.stock.day_change_pct)}`;
          if (node.kind === 'remainder') return '';
          return node.name;
        },
      },
      upperLabel: { show: true, height: 24, color: '#fff', fontSize: 12, fontWeight: 700 },
      itemStyle: { borderColor: 'var(--bg-primary)', borderWidth: 1, gapWidth: 1 },
      levels: [
        { itemStyle: { borderWidth: 3, gapWidth: 3, borderColor: 'var(--bg-primary)' }, upperLabel: { show: false } },
        { itemStyle: { borderWidth: 2, gapWidth: 2 }, upperLabel: { show: true, height: 26 } },
        { itemStyle: { borderWidth: 1, gapWidth: 1 }, upperLabel: { show: true, height: 20, fontSize: 10 } },
        { itemStyle: { borderWidth: 1, gapWidth: 1 }, label: { show: true } },
      ],
    }],
  }), [treeData]);

  const onEvents = useMemo(() => ({
    click: (params) => {
      const node = params.data || {};
      if (node.kind === 'stock') openStockAnalysis(node.stock.code, 'a');
      else if (node.l1Code) setSelectedCode(node.l1Code);
    },
  }), []);

  if (loading) {
    return <div className="flex min-h-[60vh] items-center justify-center text-sm" style={{ color: 'var(--text-muted)' }}>正在读取独立行业阶段快照…</div>;
  }
  if (error) {
    return <div className="m-5 rounded-xl border p-6" style={{ borderColor: '#ef4444', color: '#ef4444' }}>{error}</div>;
  }
  if (!data || data.status === 'MISSING') {
    return <div className="m-5 rounded-xl border p-6" style={{ borderColor: 'var(--border-color)' }}>独立行业阶段池尚未生成快照。</div>;
  }

  const summary = data.summary || {};
  const quality = data.quality || {};
  const selectedStocks = selected?.stocks || [];
  const realtimeLabel = realtime?.is_live
    ? `盘中实时 ${clock(realtime.snapshot_time)}`
    : realtime?.status === 'FAILED' ? '实时行情异常'
      : realtime?.status === 'STALE' ? '实时行情延迟'
        : realtime?.market_phase === 'BREAK' ? '午间休市'
          : realtime?.market_phase === 'PREOPEN' ? '等待开盘'
            : '盘后快照';
  const realtimeColor = realtime?.is_live ? '#16a34a' : realtime?.status === 'FAILED' || realtime?.status === 'STALE' ? '#dc2626' : '#64748b';
  const realtimeHint = realtime?.is_live
    ? `实时覆盖 ${realtime.fresh_count}/${realtime.expected_count} · 每 10 秒刷新`
    : realtime?.status === 'FAILED' || realtime?.status === 'STALE'
      ? (realtime.message || '实时行情暂不可用，保留盘后快照')
      : '休市使用盘后完整快照';

  return (
    <div className="space-y-3 p-3 md:p-4">
      <section className="rounded-2xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <h1 className="text-xl font-bold">行业阶段强势池</h1>
              <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ color: '#2563eb', background: 'rgba(37,99,235,.10)' }}>独立 V2</span>
              <span className="rounded-full px-2 py-1 text-[10px]" style={{ color: data.status === 'READY' ? '#16a34a' : '#d97706', background: data.status === 'READY' ? 'rgba(22,163,74,.10)' : 'rgba(217,119,6,.10)' }}>{data.status}</span>
              <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ color: realtimeColor, background: realtime?.is_live ? 'rgba(22,163,74,.10)' : 'rgba(100,116,139,.10)' }}>{realtimeLabel}</span>
            </div>
            <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
              申万 2021 固定分类 · 股票名单盘后更新 · 盘中行情每 10 秒覆盖 · 研究池不连接自动交易
            </p>
          </div>
          <div className="text-right text-xs" style={{ color: 'var(--text-muted)' }}>
            <div>阶段池截止 {data.data_as_of}</div>
            <div className="mt-1">{realtimeHint}</div>
          </div>
        </div>
      </section>

      <section className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-6">
        <StatCard label="阶段股票" value={summary.selected_stock_count || 0} hint="全市场动态候选" color="#2563eb" />
        <StatCard label="活跃行业" value={summary.active_sector_count || 0} hint="已连续确认" color="#ef4444" />
        <StatCard label="候选行业" value={summary.candidate_sector_count || 0} hint="等待持续确认" color="#f59e0b" />
        <StatCard label="降温行业" value={summary.cooling_sector_count || 0} hint="暂缓切换" color="#3b82f6" />
        <StatCard label="行业覆盖率" value={`${fmt(quality.membership_coverage)}%`} hint={`${quality.membership_count || 0} 只成分`} />
        <StatCard label="市值覆盖率" value={`${fmt(quality.daily_basic_coverage)}%`} hint={`${quality.daily_basic_count || 0} 只`} />
      </section>

      <section className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex flex-wrap items-center gap-2">
          {FILTERS.map(([key, label]) => (
            <button key={key} type="button" onClick={() => setFilter(key)} className="rounded-lg border px-3 py-1.5 text-xs font-medium" style={{ borderColor: filter === key ? '#2563eb' : 'var(--border-color)', background: filter === key ? 'rgba(37,99,235,.10)' : 'transparent', color: filter === key ? '#2563eb' : 'var(--text-secondary)' }}>{label}</button>
          ))}
          <span className="ml-auto text-[10px]" style={{ color: 'var(--text-muted)' }}>面积=盘后总市值 · 红涨绿跌={realtime?.is_live ? '盘中实时' : '盘后快照'} · 灰色=未入选成分</span>
        </div>
      </section>

      <section className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="rounded-xl border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          {treeData.length ? (
            <ReactECharts echarts={echarts} option={option} notMerge style={{ height: 720, width: '100%' }} opts={{ renderer: 'canvas' }} onEvents={onEvents} />
          ) : (
            <div className="flex h-[420px] items-center justify-center text-sm" style={{ color: 'var(--text-muted)' }}>当前筛选下没有行业</div>
          )}
        </div>

        <aside className="space-y-3">
          <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="mb-2 text-xs font-bold">一级行业排名</div>
            <div className="max-h-[350px] space-y-1 overflow-auto pr-1">
              {visibleSectors.map((sector) => {
                const meta = STATE_META[sector.state] || STATE_META.INACTIVE;
                return (
                  <button key={sector.l1_code} type="button" onClick={() => setSelectedCode(sector.l1_code)} className="flex w-full items-center gap-2 rounded-lg border px-2.5 py-2 text-left" style={{ borderColor: selected?.l1_code === sector.l1_code ? meta.color : 'transparent', background: selected?.l1_code === sector.l1_code ? meta.bg : 'var(--bg-hover)' }}>
                    <span className="w-6 text-[10px]" style={{ color: 'var(--text-muted)' }}>{sector.rank}</span>
                    <span className="min-w-0 flex-1 truncate text-xs font-semibold">{sector.l1_name}</span>
                    <span className="text-[10px]" style={{ color: meta.color }}>{meta.label}</span>
                    <span className="w-10 text-right text-xs font-bold">{fmt(sector.score, 1)}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {selected && (
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="flex items-center justify-between gap-2">
                <div className="font-bold">{selected.l1_name}</div>
                <span className="rounded-full px-2 py-1 text-[10px] font-bold" style={{ color: STATE_META[selected.state]?.color, background: STATE_META[selected.state]?.bg }}>{STATE_META[selected.state]?.label}</span>
              </div>
              <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
                <div>行业得分 <b>{fmt(selected.score)}</b></div>
                <div>排名 <b>{selected.rank}/31</b></div>
                <div>20日中位数 <b style={{ color: changeColor(selected.ret_20d_median) }}>{pct(selected.ret_20d_median)}</b></div>
                <div>60日中位数 <b style={{ color: changeColor(selected.ret_60d_median) }}>{pct(selected.ret_60d_median)}</b></div>
                <div>MA20广度 <b>{pct(selected.breadth_ma20)}</b></div>
                <div>阶段股 <b>{selected.selected_count}/{selected.max_candidates}</b></div>
              </div>
              <div className="mt-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                行业共 {selected.universe_count} 只；动态上限 {selected.max_candidates} 只，不强制填满。
              </div>
            </div>
          )}
        </aside>
      </section>

      <section className="overflow-hidden rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex flex-wrap items-center justify-between gap-2 border-b px-4 py-3" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <div className="font-bold">{selected?.l1_name || '行业'}阶段股票</div>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>阶段名单盘后固定；盘中仅覆盖价格、涨跌、成交额、换手和量比。点击股票在新标签页打开分析。</div>
          </div>
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{selectedStocks.length} 只</div>
        </div>
        {selectedStocks.length ? (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[1240px] text-xs">
              <thead style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
                <tr><th className="px-3 py-2 text-left">排名</th><th className="px-3 py-2 text-left">股票</th><th className="px-3 py-2 text-left">二级行业</th><th className="px-3 py-2 text-right">阶段分</th><th className="px-3 py-2 text-right">现价</th><th className="px-3 py-2 text-right">涨跌幅</th><th className="px-3 py-2 text-right">成交额</th><th className="px-3 py-2 text-right">换手</th><th className="px-3 py-2 text-right">量比</th><th className="px-3 py-2 text-right">20日</th><th className="px-3 py-2 text-right">60日</th><th className="px-3 py-2 text-right">总市值</th><th className="px-3 py-2 text-center">层级</th></tr>
              </thead>
              <tbody>
                {selectedStocks.map((stock) => (
                  <tr key={stock.ts_code} onClick={() => openStockAnalysis(stock.code, 'a')} className="cursor-pointer border-t hover:opacity-80" style={{ borderColor: 'var(--border-light)' }}>
                    <td className="px-3 py-2">{stock.rank}</td>
                    <td className="px-3 py-2"><b>{stock.name}</b><span className="ml-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>{stock.code}</span></td>
                    <td className="px-3 py-2">{stock.l2_name}</td>
                    <td className="px-3 py-2 text-right font-bold">{fmt(stock.score)}</td>
                    <td className="px-3 py-2 text-right font-bold">{fmt(stock.price ?? stock.close)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: changeColor(stock.day_change_pct) }}>{pct(stock.day_change_pct)}</td>
                    <td className="px-3 py-2 text-right">{stock.is_realtime ? amountWan(stock.realtime_amount_wan) : '—'}</td>
                    <td className="px-3 py-2 text-right">{pct(stock.turnover_rate)}</td>
                    <td className="px-3 py-2 text-right">{fmt(stock.volume_ratio)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: changeColor(stock.ret_20d) }}>{pct(stock.ret_20d)}</td>
                    <td className="px-3 py-2 text-right" style={{ color: changeColor(stock.ret_60d) }}>{pct(stock.ret_60d)}</td>
                    <td className="px-3 py-2 text-right">{mv(stock.total_mv)}</td>
                    <td className="px-3 py-2 text-center"><span className="rounded-full px-2 py-1 text-[10px]" style={{ color: stock.tier === 'CORE' ? '#ef4444' : '#2563eb', background: stock.tier === 'CORE' ? 'rgba(239,68,68,.10)' : 'rgba(37,99,235,.10)' }}>{stock.tier === 'CORE' ? '核心' : '候选'}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-10 text-center text-sm" style={{ color: 'var(--text-muted)' }}>该行业当前没有通过阶段门槛的股票，保留空仓观察。</div>
        )}
      </section>
    </div>
  );
}
