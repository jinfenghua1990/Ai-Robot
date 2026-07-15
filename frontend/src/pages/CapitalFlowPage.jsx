import { useState, useEffect, useMemo } from 'react';
import SankeyChart from '../components/charts/SankeyChart';
import CategoryLineChart from '../components/charts/CategoryLineChart';
import DateNavigator from '../components/DateNavigator';
import { apiFetch } from '../utils/request';

/**
 * 盘后 · 资金流向分析（汇总卡 + 轮动信号 + 桑基图 + 流入流出柱）
 * 日期/回看天数/联动状态由父组件 PanoramaPage 注入。实时板块柱已移至右栏 RealtimeSectorSection。
 */
export default function AfterCapitalSection({
  selectedDate, setSelectedDate, changeDate,
  lookbackDays, setLookbackDays,
  selectedSector, onSelectSector,
  showSankey = true,
  showFlowLine = true,
}) {
  const [rotationData, setRotationData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [showHelp, setShowHelp] = useState(false);

  const fmtFlow = (v) => {
    const abs = Math.abs(v);
    if (abs >= 10000) return `${(v / 10000).toFixed(2)}亿`;
    return `${v.toFixed(0)}万`;
  };

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    (async () => {
      const rot = await apiFetch(`/api/rotation?date=${selectedDate}&days=${lookbackDays}`, { signal: controller.signal });
      if (controller.signal.aborted) return;
      setRotationData(rot.ok ? rot.data : null);
      if (!rot.ok) setError('数据加载失败');
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, lookbackDays]);

  const handleSectorClick = (sectorName) => {
    if (onSelectSector) onSelectSector(sectorName);
  };

  const { totalInflow, totalOutflow, netFlow, topInflow, combinedData } = useMemo(() => {
    const totalIn = rotationData?.total_inflow || 0;
    const totalOut = rotationData?.total_outflow || 0;
    const netF = rotationData?.net_flow || (totalIn - totalOut);
    const allInflows = rotationData?.all_inflows || [];
    const allOutflows = rotationData?.all_outflows || [];
    const topIn = allInflows.length > 0 ? [allInflows[0].sector, allInflows[0].change] : null;
    const inflowSorted = allInflows.slice(0, 10);
    const outflowSorted = allOutflows.slice(0, 10);
    const combined = [
      ...outflowSorted.map(s => ({ name: s.sector, value: s.change, type: 'outflow', past: s.past, current: s.current })),
      ...inflowSorted.map(s => ({ name: s.sector, value: s.change, type: 'inflow', past: s.past, current: s.current })),
    ];
    return { totalInflow: totalIn, totalOutflow: totalOut, netFlow: netF, topInflow: topIn, combinedData: combined };
  }, [rotationData]);

  const chartData = useMemo(() => {
    if (combinedData.length === 0) return { categories: [], values: [], extras: {} };
    return {
      categories: combinedData.map(d => d.name),
      values: combinedData.map(d => d.value),
      extras: Object.fromEntries(combinedData.map(d => [d.name, { past: d.past, current: d.current, type: d.type }])),
    };
  }, [combinedData]);

  const tooltipFormatter = (params) => {
    const p = params[0];
    const extra = chartData.extras[p.name] || {};
    const absVal = Math.abs(p.value);
    const type = extra.type === 'outflow' ? '流出' : '流入';
    const color = extra.type === 'outflow' ? '#22c55e' : '#f87171';
    const formatted = absVal >= 10000 ? `${(absVal / 10000).toFixed(2)}亿` : `${absVal.toFixed(0)}万`;
    const past = extra.past || 0;
    const current = extra.current || 0;
    const fmtVal = (v) => {
      const a = Math.abs(v);
      return a >= 10000 ? `${(v / 10000).toFixed(2)}亿` : `${v.toFixed(0)}万`;
    };
    const noPast = past === 0 && current !== 0;
    const tip = noPast ? '<div style="font-size:10px;color:#818cf8;margin-top:2px">📅 无历史数据（维度切换）</div>' : '';
    return `<div style="font-weight:700;font-size:13px;margin-bottom:2px">${p.name}</div>` +
           `<div style="font-size:12px;color:#ccc">${type}：<span style="color:${color};font-weight:600">${formatted}</span></div>` +
           `<div style="font-size:11px;color:#999">今日：${fmtVal(current)} · ${lookbackDays}天前：${fmtVal(past)}</div>${tip}`;
  };

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-3">
        <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
        <button onClick={() => { setError(null); setSelectedDate(selectedDate); }} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>重试</button>
      </div>
    );
  }

  return (
    <div className="rounded-xl border p-3 space-y-1.5"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      {/* 顶部：标题 + 日期 + 回看天数 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
          资金流向分析
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
            {rotationData?.actual_date && rotationData.actual_date !== selectedDate && (
              <span className="ml-1">（已回退 {rotationData.actual_date.slice(5).replace('-', '月')}日）</span>
            )}
          </span>
        </h2>
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate}
          extra={<select value={lookbackDays} onChange={(e) => setLookbackDays(Number(e.target.value))} className="px-2 py-1 rounded-lg border text-xs" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
          <option value={3}>近3天</option>
          <option value={5}>近5天</option>
          <option value={10}>近10天</option>
        </select>}
        />
      </div>

      {/* 说明（折叠态一行显示） */}
      <div style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-2.5 py-1.5 text-xs rounded-lg" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 总流入 / 总流出 / 净轮动</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-2.5 pb-2 space-y-1 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>总流入：</strong>相比N天前净额增加板块的增加金额合计</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>总流出：</strong>相比N天前净额减少板块的减少金额合计</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>净轮动：</strong>总流入 − 总流出。正=情绪改善，负=情绪恶化</div>
            <div><strong style={{ color: '#ef4444' }}>红色</strong>=流入/上涨，<strong style={{ color: '#22c55e' }}>绿色</strong>=流出/下跌</div>
          </div>
        )}
      </div>

      {/* 汇总卡片 + 连续流入 */}
      {!loading && rotationData && (
        <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-1.5">
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总流入</div>
            <div className="text-sm font-bold" style={{ color: '#ef4444' }}>{fmtFlow(totalInflow)}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总流出</div>
            <div className="text-sm font-bold" style={{ color: '#22c55e' }}>{fmtFlow(totalOutflow)}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>净轮动</div>
            <div className="text-sm font-bold" style={{ color: netFlow > 0 ? '#ef4444' : '#22c55e' }}>{netFlow > 0 ? '+' : ''}{fmtFlow(netFlow)}</div>
          </div>
          <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>最强流入</div>
            <div className="text-xs font-bold truncate cursor-pointer hover:opacity-80"
              style={{ color: 'var(--text-primary)' }}
              onClick={() => topInflow && onSelectSector?.(topInflow[0])}>
              {topInflow ? topInflow[0] : '—'}
            </div>
            <div className="text-[10px]" style={{ color: '#ef4444' }}>
              {topInflow ? fmtFlow(topInflow[1]) : ''}
              {topInflow && rotationData?.streaks?.[topInflow[0]] >= 2 && (
                <span className="ml-1 px-1 rounded text-[10px]" style={{ background: 'rgba(239,68,68,0.2)', color: '#f87171' }}>连{rotationData.streaks[topInflow[0]]}天</span>
              )}
            </div>
          </div>
          {rotationData?.streaks && Object.values(rotationData.streaks).some(v => v >= 2) ? (
            <div className="rounded-lg border p-2 col-span-2 md:col-span-4 lg:col-span-1" style={{ borderColor: 'rgba(239,68,68,0.2)', background: 'var(--bg-card)' }}>
              <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>🔥 连续流入板块</div>
              <div className="flex flex-wrap gap-1">
                {Object.entries(rotationData.streaks)
                  .filter(([_, days]) => days >= 2)
                  .sort((a, b) => b[1] - a[1])
                  .slice(0, 8)
                  .map(([sector, days]) => (
                    <span key={sector} className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] cursor-pointer hover:opacity-80"
                      style={{ background: days >= 3 ? 'rgba(239,68,68,0.2)' : 'rgba(239,68,68,0.1)', color: days >= 3 ? '#f87171' : '#fca5a5' }}
                      onClick={() => handleSectorClick(sector)}>
                      {sector}<span style={{ opacity: 0.7 }}>{days}天</span>
                    </span>
                  ))}
              </div>
            </div>
          ) : null}
        </div>
      )}

      {/* 轮动信号：紧凑横向排列 */}
      {!loading && rotationData?.signals && rotationData.signals.length > 0 && (
        <div className="flex flex-wrap items-start gap-1.5">
          {rotationData.signals.map((signal, i) => {
            const isInflow = signal.includes('流入');
            const sectors = signal.replace(/资金(流入|流出)[：:]\s*/, '').split('、');
            return (
              <div key={i} className="inline-flex items-center gap-1 rounded-lg border px-2 py-1" style={{ borderColor: isInflow ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)', background: 'var(--bg-card)' }}>
                <span className="text-[10px]">{isInflow ? '🔥' : '❄️'}</span>
                <span className="text-[10px] font-medium whitespace-nowrap" style={{ color: isInflow ? '#ef4444' : '#22c55e' }}>{isInflow ? '资金流入' : '资金流出'}</span>
                <div className="flex items-center gap-0.5">
                  {sectors.map((sector, j) => (
                    <span key={j} className="text-[10px] px-1 py-0.5 rounded cursor-pointer hover:opacity-80"
                      style={{ background: isInflow ? 'rgba(239,68,68,0.15)' : 'rgba(34,197,94,0.15)', color: isInflow ? '#f87171' : '#4ade80' }}
                      onClick={() => handleSectorClick(sector)}>
                      {sector}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {showSankey && (
        <>
          {/* 盘后桑基图（全宽，联动高亮） */}
          <div className="rounded-lg p-2 text-xs flex items-center gap-2" style={{ background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)', color: '#a5b4fc' }}>
            <span>📅</span>
            <span>板块数据已切换为新浪财经（48个申万行业）。点击板块节点可与右侧实时数据联动。</span>
          </div>
          <div className="space-y-1">
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>📊 盘后 · 💡 点击板块节点联动</div>
            {loading ? (
              <div className="flex items-center justify-center h-80 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : (
              <SankeyChart data={rotationData} onNodeClick={handleSectorClick} selectedSector={selectedSector} />
            )}
          </div>
        </>
      )}

      {showFlowLine && (
        <>
          {/* 盘后轮动 · 流入 Top 5 vs 流出 Top 10（全宽，联动） */}
          {!loading && rotationData && chartData.categories.length > 0 && (
            <div className="space-y-1">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
                  📊 盘后轮动 · 流入 Top 5 vs 流出 Top 10（折线）
                </h3>
                <div className="flex items-center gap-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                  <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded" style={{background:'#22c55e'}}></span>流出</span>
                  <span className="flex items-center gap-1"><span className="inline-block w-2.5 h-2.5 rounded" style={{background:'#ef4444'}}></span>流入</span>
                </div>
              </div>
              <CategoryLineChart
                categories={chartData.categories}
                values={chartData.values}
                selectedItem={selectedSector}
                onItemClick={handleSectorClick}
                color="#6366f1"
                valueFormatter={(v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(0)}亿` : `${v.toFixed(0)}万`}
                tooltipFormatter={tooltipFormatter}
                height={320}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
