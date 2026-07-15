import ReactECharts from 'echarts-for-react';

const fmtWan = (v) => {
  const x = v || 0;
  return Math.abs(x) >= 10000 ? (x / 10000).toFixed(2) + '亿' : x.toFixed(0) + '万';
};

export default function MoneyFlowBoard({ moneyFlow, sectorTrend, sector }) {
  if (!moneyFlow?.available) {
    return (
      <div className="rounded-md px-2 py-3 text-center text-[10px]" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
        暂无盘后资金流向数据
      </div>
    );
  }

  const mf = moneyFlow;
  const mainBuy = mf.main_buy || 0;
  const mainSell = mf.main_sell || 0;
  const retailBuy = mf.retail_buy;
  const retailSell = mf.retail_sell;
  const hasRetail = retailBuy != null && retailSell != null;

  const pieOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c}万 ({d}%)' },
    legend: { show: false },
    series: [{
      type: 'pie',
      radius: ['35%', '62%'],
      center: ['50%', '52%'],
      label: { show: true, fontSize: 10, formatter: '{b}\n{d}%' },
      labelLine: { length: 6, length2: 5 },
      data: [
        { value: Math.max(mainBuy, 0), name: '主力买入', itemStyle: { color: '#d32f2f' } },
        { value: Math.max(mainSell, 0), name: '主力卖出', itemStyle: { color: '#388e3c' } },
        ...(hasRetail ? [
          { value: Math.max(retailBuy, 0), name: '散户买入', itemStyle: { color: '#ff7043' } },
          { value: Math.max(retailSell, 0), name: '散户卖出', itemStyle: { color: '#8bc34a' } },
        ] : []),
      ].filter(d => d.value > 0),
    }],
  };

  const flowRows = [
    { name: '特大单', val: mf.super_large || 0, pct: mf.super_large_pct },
    { name: '大单', val: mf.large || 0, pct: mf.large_pct },
    { name: '小单', val: mf.small || 0, pct: mf.small_pct },
    { name: '散单', val: mf.tiny || 0, pct: mf.tiny_pct },
  ];
  const maxAbs = Math.max(...flowRows.map(d => Math.abs(d.val)), 1);

  return (
    <div className="rounded-md px-2 py-1.5 flex flex-col gap-1.5" style={{ background: 'transparent', border: '1px solid rgba(107,114,128,0.2)' }}>
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] font-bold" style={{ color: 'var(--flow-up)' }}>资金流向</span>
          {mf.trade_date && (
            <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: 'var(--color-blue)' }}>
              📊 盘后 {String(mf.trade_date).slice(0,4)}/{String(mf.trade_date).slice(4,6)}/{String(mf.trade_date).slice(6,8)}
            </span>
          )}
        </div>
      </div>

      {/* 板块净流入 */}
      {sectorTrend?.available && sectorTrend?.total_net_flow != null && (
        <div className="flex items-center justify-between text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)' }}>
          <span style={{ color: 'var(--text-muted)' }}>🏭 {sector || '板块'}资金净流入</span>
          <span className="font-bold" style={{ color: (sectorTrend.total_net_flow || 0) >= 0 ? 'var(--flow-up)' : 'var(--flow-down)' }}>
            {(sectorTrend.total_net_flow || 0) >= 0 ? '+' : ''}{fmtWan(sectorTrend.total_net_flow)}
          </span>
        </div>
      )}

      {/* 上排：饼图 + 净额摘要 */}
      <div className="grid grid-cols-5 gap-2">
        <div className="col-span-2">
          <ReactECharts option={pieOption} style={{ height: 108 }} opts={{ renderer: 'svg' }} />
        </div>
        <div className="col-span-3 flex flex-col justify-center gap-1">
          <div className="flex items-center justify-between text-[10px] px-2 py-1 rounded" style={{ background: (mf.main_net || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)' }}>
            <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>主力</span>
            <span className="font-bold" style={{ color: (mf.main_net || 0) >= 0 ? '#d32f2f' : '#388e3c' }}>
              {(mf.main_net || 0) >= 0 ? '+' : ''}{fmtWan(mf.main_net || 0)}
            </span>
          </div>
          <div className="flex items-center justify-between text-[10px] px-2 py-1 rounded" style={{ background: (mf.retail_net || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)' }}>
            <span className="font-medium" style={{ color: 'var(--text-secondary)' }}>散户</span>
            <span className="font-bold" style={{ color: (mf.retail_net || 0) >= 0 ? '#d32f2f' : '#388e3c' }}>
              {(mf.retail_net || 0) >= 0 ? '+' : ''}{fmtWan(mf.retail_net || 0)}
            </span>
          </div>
        </div>
      </div>

      {/* 简化：仅 4 档横条（去掉表格和累计行，降低信息密度） */}
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
                {isPos ? '+' : ''}{fmtWan(d.val)}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
