import ReactECharts from 'echarts-for-react';

const fmtWan = (v) => {
  const x = v || 0;
  return Math.abs(x) >= 10000 ? (x / 10000).toFixed(2) + '亿' : x.toFixed(0) + '万';
};

const fmtYuan = (v) => {
  // dash 数据单位为元，统一格式化成 万/亿
  const x = v || 0;
  const wan = x / 10000;
  return Math.abs(wan) >= 10000 ? (wan / 10000).toFixed(2) + '亿' : wan.toFixed(wan === 0 ? 0 : 2) + '万';
};

export default function MoneyFlowBoard({ moneyFlow, sectorTrend, sector, dash }) {
  const useDash = !!dash && dash.institution_flow != null;
  const inst = dash?.institution_flow || {};
  const sf = dash?.sector_flow || {};

  const mf = moneyFlow;
  const hasMf = mf?.available;

  if (!useDash && !hasMf) {
    return (
      <div className="rounded-md px-2 py-3 text-center text-[10px]" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
        暂无盘后资金流向数据
      </div>
    );
  }

  // 饼图：优先用 dash 5 档净流入绝对值分布；fallback 用旧 moneyFlow 买入/卖出
  let pieData = [];
  if (useDash) {
    const abs = (v) => Math.abs(v || 0);
    pieData = [
      { value: abs(inst.super_large_net), name: '特大', itemStyle: { color: '#ef4444' } },
      { value: abs(inst.large_net), name: '大单', itemStyle: { color: '#f97316' } },
      { value: abs(inst.medium_net), name: '中单', itemStyle: { color: '#eab308' } },
      { value: abs(inst.small_net), name: '小单', itemStyle: { color: '#3b82f6' } },
      { value: abs(inst.tiny_net), name: '散单', itemStyle: { color: '#94a3b8' } },
    ].filter(d => d.value > 0);
  } else {
    const mainBuy = mf.main_buy || 0;
    const mainSell = mf.main_sell || 0;
    const retailBuy = mf.retail_buy;
    const retailSell = mf.retail_sell;
    const hasRetail = retailBuy != null && retailSell != null;
    pieData = [
      { value: Math.max(mainBuy, 0), name: '主力买入', itemStyle: { color: '#d32f2f' } },
      { value: Math.max(mainSell, 0), name: '主力卖出', itemStyle: { color: '#388e3c' } },
      ...(hasRetail ? [
        { value: Math.max(retailBuy, 0), name: '散户买入', itemStyle: { color: '#ff7043' } },
        { value: Math.max(retailSell, 0), name: '散户卖出', itemStyle: { color: '#8bc34a' } },
      ] : []),
    ].filter(d => d.value > 0);
  }

  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c}' + (useDash ? '万' : '万') + ' ({d}%)' },
    legend: { show: false },
    series: [{
      type: 'pie',
      radius: ['35%', '62%'],
      center: ['50%', '52%'],
      label: { show: true, fontSize: 10, formatter: '{b}\n{d}%' },
      labelLine: { length: 6, length2: 5 },
      data: pieData,
    }],
  };

  const flowRows = useDash ? [
    { name: '特大单', val: inst.super_large_net || 0 },
    { name: '大单', val: inst.large_net || 0 },
    { name: '中单', val: inst.medium_net || 0 },
    { name: '小单', val: inst.small_net || 0 },
    { name: '散单', val: inst.tiny_net || 0 },
  ] : [
    { name: '特大单', val: mf.super_large || 0 },
    { name: '大单', val: mf.large || 0 },
    { name: '小单', val: mf.small || 0 },
    { name: '散单', val: mf.tiny || 0 },
  ];
  const maxAbs = Math.max(...flowRows.map(d => Math.abs(d.val)), 1);
  const fmt = useDash ? fmtYuan : fmtWan;

  const mainNet = useDash ? inst.main_net : mf.main_net;
  const retailNet = useDash ? (inst.retail_net != null ? inst.retail_net : -(inst.main_net || 0)) : mf.retail_net;
  const sectorNet = useDash ? sf.net_flow : sectorTrend?.total_net_flow;
  const sectorName = useDash ? (sf.sector || sector) : sector;

  return (
    <div className="rounded-md px-2 py-1.5 flex flex-col gap-1.5" style={{ background: 'transparent', border: '1px solid rgba(107,114,128,0.2)' }}>
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-bold" style={{ color: 'var(--flow-up)' }}>资金流向</span>
          {hasMf && !useDash && mf.trade_date && (
            <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--color-blue)' }}>
              📊 盘后 {String(mf.trade_date).slice(0,4)}/{String(mf.trade_date).slice(4,6)}/{String(mf.trade_date).slice(6,8)}
            </span>
          )}
          {useDash && dash.date && (
            <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--color-blue)' }}>
              📊 盘后 {dash.date}
            </span>
          )}
        </div>
      </div>

      {/* 板块净流入 */}
      {sectorNet != null && (
        <div className="flex items-center justify-between text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)' }}>
          <span style={{ color: 'var(--text-muted)' }}>🏭 {sectorName || '板块'}资金净流入</span>
          <span className="font-bold" style={{ color: (sectorNet || 0) >= 0 ? 'var(--flow-up)' : 'var(--flow-down)' }}>
            {(sectorNet || 0) >= 0 ? '+' : ''}{fmtYuan(sectorNet)}
          </span>
        </div>
      )}

      {/* 上排：饼图 + 净额摘要 */}
      <div className="grid grid-cols-5 gap-2">
        <div className="col-span-2">
          {pieData.length > 0 ? (
            <ReactECharts option={pieOption} style={{ height: 108 }} opts={{ renderer: 'svg' }} />
          ) : (
            <div className="h-[108px] flex items-center justify-center text-[10px]" style={{ color: 'var(--text-muted)' }}>暂无分布数据</div>
          )}
        </div>
        <div className="col-span-3 flex flex-col justify-center gap-1">
          <div className="flex items-center justify-between text-[10px] px-2 py-1 rounded" style={{ background: (mainNet || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)' }}>
            <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>主力</span>
            <span className="font-bold" style={{ color: (mainNet || 0) >= 0 ? '#d32f2f' : '#388e3c' }}>
              {(mainNet || 0) >= 0 ? '+' : ''}{fmt(mainNet || 0)}
            </span>
          </div>
          <div className="flex items-center justify-between text-[10px] px-2 py-1 rounded" style={{ background: (retailNet || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)' }}>
            <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>散户</span>
            <span className="font-bold" style={{ color: (retailNet || 0) >= 0 ? '#d32f2f' : '#388e3c' }}>
              {(retailNet || 0) >= 0 ? '+' : ''}{fmt(retailNet || 0)}
            </span>
          </div>
        </div>
      </div>

      {/* 5 档横条 */}
      <div className="flex flex-col gap-1">
        {flowRows.map((d, i) => {
          const isPos = d.val >= 0;
          const pct = Math.min(100, Math.abs(d.val) / maxAbs * 100);
          return (
            <div key={i} className="flex items-center gap-1.5 text-[10px]">
              <span className="w-6 flex-shrink-0 text-right font-medium" style={{ color: 'var(--text-secondary)' }}>{d.name}</span>
              <div className="flex-1 h-2 rounded-full" style={{ background: 'rgba(107,114,128,0.08)' }}>
                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: isPos ? '#d32f2f' : '#388e3c', opacity: 0.8 }} />
              </div>
              <span className="w-14 text-right font-bold tabular-nums" style={{ color: isPos ? '#d32f2f' : '#388e3c' }}>
                {isPos ? '+' : ''}{fmt(d.val)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
