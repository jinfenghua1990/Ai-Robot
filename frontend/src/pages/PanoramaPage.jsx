import { useState, useEffect, useCallback, useMemo } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import { apiFetch } from '../utils/request';
import AfterHeatmapSection from './HeatmapPage';
import AfterCapitalSection from './CapitalFlowPage';
import DateNavigator from '../components/DateNavigator';
import RealtimeSectorSection from '../components/sections/RealtimeSectorSection';
import RealtimeHeatSection from '../components/sections/RealtimeHeatSection';
import AfterSectorFlowSection from '../components/sections/AfterSectorFlowSection';
import PostMarketSankeySection from '../components/sections/PostMarketSankeySection';
import RealtimeSankeyChart from '../components/charts/RealtimeSankeyChart';
import RealtimeStockSection from '../components/sections/RealtimeStockSection';
import SectorMoneyFlowCompareSection from '../components/sections/SectorMoneyFlowCompareSection';
import ModuleGroup from '../components/sections/ModuleGroup';
import SharedTrendPanel from '../components/sections/SharedTrendPanel';
import StockCompareSection from '../components/sections/StockCompareSection';
import AfterConceptSectorFlowSection from '../components/sections/AfterConceptSectorFlowSection';
import RealtimeConceptSectorSection from '../components/sections/RealtimeConceptSectorSection';
import ConceptSectorFilter, { loadSelectedConcepts, saveSelectedConcepts } from '../components/sections/ConceptSectorFilter';
import MarketStageBar from '../components/MarketStageBar';
import { POLL_INTERVAL } from '../utils/constants';

/**
 * 板块全景 — 全通栏对比布局
 * 每个主题都是一个通栏，左右盘后 vs 实时对比。
 * 持有全部共享状态：日期、联动选中、趋势、单一实时轮询。
 */
export default function PanoramaPage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [days, setDays] = useState(20);
  const [lookbackDays, setLookbackDays] = useState(5);

  const [selectedSector, setSelectedSector] = useState(null);
  const [selectedStock, setSelectedStock] = useState(null);

  // 板块热度数据由 ModuleGroup 管理，用于 Header/SubHeader/Content 分离后仍能共享
  const [heatmapData, setHeatmapData] = useState(null);
  const [heatmapLoading, setHeatmapLoading] = useState(false);
  const [heatmapError, setHeatmapError] = useState(null);
  const [viewDate, setViewDate] = useState('');
  const [showHelp, setShowHelp] = useState(false);

  const [trendType, setTrendType] = useState(null);
  const [trendData, setTrendData] = useState(null);

  const [rtSectors, setRtSectors] = useState(null);
  const [rtStocks, setRtStocks] = useState(null);
  const [rtConceptSectors, setRtConceptSectors] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // 概念板块筛选（左右盘后/实时共用，localStorage 持久化）
  const [selectedConcepts, setSelectedConcepts] = useState(() => loadSelectedConcepts());
  const handleConceptsChange = useCallback((arr) => {
    setSelectedConcepts(arr);
    saveSelectedConcepts(arr);
  }, []);

  // 全量可选概念列表 + 板块热度数据并行拉取（原两个 useEffect 合并）
  const [conceptRankSectors, setConceptRankSectors] = useState([]);
  useEffect(() => {
    if (!selectedDate) return;
    let cancelled = false;
    setHeatmapLoading(true);
    setHeatmapError(null);
    Promise.all([
      apiFetch(`/api/concept-sector-flow-rank?date=${selectedDate}`),
      apiFetch(`/api/heatmap?date=${selectedDate}&days=${days}`),
    ]).then(([rankRes, heatRes]) => {
      if (cancelled) return;
      if (rankRes.ok) {
        setConceptRankSectors((rankRes.data?.sectors || []).map(s => s.sector));
      }
      if (heatRes.ok) {
        const payload = heatRes.data || heatRes;
        setHeatmapData(payload);
        if (payload?.dates?.length) {
          setViewDate(payload.dates[payload.dates.length - 1]);
        }
      }
    }).catch(err => {
      if (!cancelled) setHeatmapError(err.message || '加载失败');
    }).finally(() => {
      if (!cancelled) setHeatmapLoading(false);
    });
    return () => { cancelled = true; };
  }, [selectedDate, days]);

  const allConceptSectors = useMemo(() => {
    const map = new Map();
    for (const s of conceptRankSectors) map.set(s, true);
    for (const s of (rtConceptSectors?.sectors || [])) map.set(s.sector, true);
    return [...map.keys()];
  }, [conceptRankSectors, rtConceptSectors]);

  // 单一实时轮询（消除原三处重复请求）
  const fetchRealtime = useCallback(async () => {
    const [sec, stk, csec] = await Promise.all([
      apiFetch('/api/realtime/latest-sectors'),
      apiFetch('/api/realtime/latest-stocks?limit=500&sort_by=main_force_inflow'),
      apiFetch('/api/realtime/concept-sectors'),
    ]);
    if (sec.ok) setRtSectors(sec.data);
    if (stk.ok) setRtStocks(stk.data);
    if (csec.ok) setRtConceptSectors(csec.data);
  }, []);

  useEffect(() => {
    fetchRealtime();
    if (!autoRefresh) return;
    const id = setInterval(() => { if (!document.hidden) fetchRealtime(); }, POLL_INTERVAL);
    const onVisible = () => { if (!document.hidden) fetchRealtime(); };
    document.addEventListener('visibilitychange', onVisible);
    return () => { clearInterval(id); document.removeEventListener('visibilitychange', onVisible); };
  }, [fetchRealtime, autoRefresh]);

  // 共享盘中趋势
  const fetchTrend = useCallback(async (kind, name) => {
    setTrendType({ kind, name });
    const url = kind === 'stock'
      ? `/api/realtime/stock-trend?ts_code=${encodeURIComponent(name)}`
      : `/api/realtime/sector-trend?sector=${encodeURIComponent(name)}`;
    const { ok, data } = await apiFetch(url);
    if (ok) setTrendData(data);
  }, []);

  const handleSelectSector = useCallback((name) => {
    setSelectedSector(name);
    if (name) fetchTrend('sector', name);
    else { setTrendType(null); setTrendData(null); }
  }, [fetchTrend]);

  const handleSelectStock = useCallback((tsCode) => {
    setSelectedStock(tsCode);
    if (tsCode) fetchTrend('stock', tsCode);
    else { setTrendType(null); setTrendData(null); }
  }, [fetchTrend]);

  const handleCloseTrend = useCallback(() => {
    setTrendType(null);
    setTrendData(null);
  }, []);

  const heatExtra = (
    <div className="flex items-center gap-2">
      <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate}
        extra={<select value={days} onChange={(e) => setDays(Number(e.target.value))} className="px-2.5 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
          <option value={3}>近3天</option>
          <option value={5}>近5天</option>
          <option value={10}>近10天</option>
          <option value={20}>近20天</option>
        </select>}
      />
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>快照: {rtSectors?.snapshot_time || '—'}</span>
      <button onClick={() => setAutoRefresh(r => !r)} className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
        style={{ borderColor: autoRefresh ? '#22c55e' : 'var(--border-color)', color: autoRefresh ? '#22c55e' : 'var(--text-secondary)', background: autoRefresh ? 'rgba(34,197,94,0.1)' : 'transparent' }}>
        {autoRefresh ? '⏸ 暂停' : '▶ 刷新'}
      </button>
    </div>
  );

  return (
    <div className="space-y-2">
      {/* 标题 + 实时状态条 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          板块全景
        </h2>
        <RealtimeStatusBar />
      </div>

      {/* 市场情绪 6 阶段（从 8788 迁移） */}
      <MarketStageBar date={selectedDate} />

      {/* 通栏 1：资金流向分析 · 全通栏 */}
      <AfterCapitalSection
          selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate}
          lookbackDays={lookbackDays} setLookbackDays={setLookbackDays}
          selectedSector={selectedSector} onSelectSector={handleSelectSector}
          showSankey={false}
          showFlowLine={false}
        />

      {/* 通栏 2：板块资金轮动 · 盘后 vs 实时 排名 */}
      <ModuleGroup
        title="板块资金轮动"
        badge={selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后 vs 实时` : ''}
        contentHeight="480px"
      >
        <ModuleGroup.Content
          left={
            <PostMarketSankeySection
              selectedDate={selectedDate}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
            />
          }
          right={
            <RealtimeSankeyChart
              rtSectors={rtSectors}
              selectedSector={selectedSector} onNodeClick={handleSelectSector}
            />
          }
        />
      </ModuleGroup>

      {/* 通栏 3：概念板块 · 盘后 vs 实时 */}
      <ModuleGroup
        title="概念板块"
        badge={selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后 vs 实时` : ''}
        contentHeight="520px"
        extra={
          <ConceptSectorFilter
            allSectors={allConceptSectors}
            selected={selectedConcepts}
            onChange={handleConceptsChange}
          />
        }
      >
        <ModuleGroup.SubHeader
          left={
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              📖 已选 {selectedConcepts.length} 个概念 · 20 日净流入趋势 · 点击折线联动
            </span>
          }
          right={
            <div className="flex items-center justify-end gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#22c55e' }} />净流出</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#ef4444' }} />净流入</span>
            </div>
          }
        />
        <ModuleGroup.Content
          left={
            <AfterConceptSectorFlowSection
              selectedDate={selectedDate}
              sectors={selectedConcepts}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
            />
          }
          right={
            <RealtimeConceptSectorSection
              rtConceptSectors={rtConceptSectors}
              sectors={selectedConcepts}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
            />
          }
        />
      </ModuleGroup>

      {/* 通栏 4：板块热度 · 盘后 vs 实时 */}
      <ModuleGroup
        title="板块热度"
        badge={selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后 vs 实时` : ''}
        extra={heatExtra}
      >
        <ModuleGroup.SubHeader
          left={
            <div className="flex flex-col gap-1.5">
              <div className="flex items-center justify-between gap-2">
                <button onClick={() => setShowHelp(!showHelp)} className="text-xs flex items-center gap-1 shrink-0" style={{ color: 'var(--text-muted)' }}>
                  📖 名词解释 {showHelp ? '▲' : '▼'}
                </button>
                <div className="flex items-center gap-1.5 min-w-0">
                  <span className="text-xs whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>视角：</span>
                  <select
                    value={viewDate}
                    onChange={(e) => setViewDate(e.target.value)}
                    className="px-2 py-1 rounded border text-xs min-w-0"
                    style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
                  >
                    {heatmapData?.dates.map((d) => (
                      <option key={d} value={d}>{d}</option>
                    ))}
                  </select>
                  {heatmapData?.actual_date && heatmapData.actual_date !== selectedDate && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
                      数据日期 {heatmapData.actual_date}
                    </span>
                  )}
                </div>
              </div>
              {showHelp && (
                <div className="text-[10px] space-y-0.5 p-1.5 rounded" style={{ color: 'var(--text-muted)', background: 'var(--bg-card)' }}>
                  <p><strong style={{ color: 'var(--text-primary)' }}>板块热度</strong>：综合板块涨幅、涨停股数量、资金净流入、龙头强度等指标计算的综合评分（0-100）。</p>
                  <p><strong style={{ color: 'var(--text-primary)' }}>折线走势</strong>：展示 Top 10 板块在最近 N 个交易日内的热度变化。</p>
                </div>
              )}
            </div>
          }
          right={
            <div className="flex items-center justify-end gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#22c55e' }} />下跌</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#ef4444' }} />上涨</span>
            </div>
          }
        />
        <ModuleGroup.Content
          left={
            heatmapLoading ? (
              <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : heatmapError ? (
              <div className="flex items-center justify-center h-full text-sm" style={{ color: '#ef4444' }}>加载失败：{heatmapError}</div>
            ) : (
              <AfterHeatmapSection
                data={heatmapData} viewDate={viewDate}
                selectedSector={selectedSector} onSelectSector={handleSelectSector}
              />
            )
          }
          right={
            <RealtimeHeatSection
              rtSectors={rtSectors}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
            />
          }
        />
      </ModuleGroup>

      {/* 通栏 2：板块动向 · 盘后 vs 实时 */}
      <ModuleGroup
        title="板块动向"
        badge={selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后 vs 实时` : ''}
      >
        <ModuleGroup.SubHeader
          right={
            <div className="flex items-center justify-end gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#22c55e' }} />流出</span>
              <span className="flex items-center gap-1"><span className="inline-block w-2 h-2 rounded-sm" style={{ background: '#ef4444' }} />流入</span>
            </div>
          }
        />
        <ModuleGroup.Content
          left={
            <AfterSectorFlowSection
              selectedDate={selectedDate}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
            />
          }
          right={
            <RealtimeSectorSection
              rtSectors={rtSectors}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
              mode="bar" showHeader={false}
            />
          }
        />
      </ModuleGroup>

      {/* 通栏 4：Top 10 板块资金流向对比（盘后日度走势 vs 实时分钟走势） */}
      <SectorMoneyFlowCompareSection
        selectedDate={selectedDate} rtSectors={rtSectors}
        selectedSector={selectedSector} onSelectSector={handleSelectSector}
      />

      {/* 通栏 5：盘中趋势（由 selectedSector/selectedStock 驱动） */}
      <SharedTrendPanel trendType={trendType} trendData={trendData} onClose={handleCloseTrend} />

      {/* 通栏 6：个股资金对比（盘后 vs 实时个股卡片） */}
      <StockCompareSection
        selectedDate={selectedDate} rtStocks={rtStocks}
        selectedStock={selectedStock} onSelectStock={handleSelectStock}
      />

      {/* 通栏 7：实时个股动向（按板块联动筛选） */}
      <ModuleGroup title="个股动向" badge="实时" contentHeight="auto">
        <ModuleGroup.Header
          left={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>实时个股 Top 20</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>盘中数据</span>
            </div>
          }
          right={
            <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>操作提示</span>
          }
        />
        <ModuleGroup.Content
          left={
            <RealtimeStockSection
              rtStocks={rtStocks}
              selectedSector={selectedSector} onSelectSector={handleSelectSector}
              selectedStock={selectedStock} onSelectStock={handleSelectStock}
            />
          }
          right={
            <div className="rounded-xl border p-4 flex items-center justify-center min-h-[200px]"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
              <div className="text-center text-sm space-y-2">
                <div className="text-3xl">💡</div>
                <div>点击左侧个股查看盘中趋势</div>
                <div className="text-xs">选中的板块/个股会联动上方所有图表</div>
              </div>
            </div>
          }
        />
      </ModuleGroup>
    </div>
  );
}

/* ──────────────────────────────────────────────────────────── */

/**
 * 轻量实时状态指示条
 */
function RealtimeStatusBar() {
  const [status, setStatus] = useState(null);
  const [snapshotTime, setSnapshotTime] = useState('');

  useEffect(() => {
    const fetchStatus = async () => {
      const { ok, data } = await apiFetch('/api/realtime/status');
      if (!ok) return;
      setStatus(data);
      setSnapshotTime(data.latest_sector_time || data.latest_stock_time || '');
    };
    fetchStatus();
    const interval = setInterval(fetchStatus, POLL_INTERVAL);
    return () => clearInterval(interval);
  }, []);

  const isTrading = status?.is_trading_hours;

  return (
    <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg border text-xs"
      style={{
        borderColor: isTrading ? 'rgba(239,68,68,0.3)' : 'var(--border-color)',
        background: isTrading ? 'rgba(239,68,68,0.05)' : 'var(--bg-card)',
      }}
    >
      <span className="flex items-center gap-1 font-medium" style={{ color: isTrading ? '#ef4444' : 'var(--text-muted)' }}>
        <span className={`inline-block w-1.5 h-1.5 rounded-full ${isTrading ? 'animate-pulse' : ''}`}
          style={{ background: isTrading ? '#ef4444' : '#94a3b8' }} />
        {isTrading ? '盘中' : '盘后'}
      </span>
      {snapshotTime && (
        <span style={{ color: 'var(--text-muted)' }}>快照 {snapshotTime.slice(11) || snapshotTime}</span>
      )}
      {status && (
        <span style={{ color: 'var(--text-muted)' }}>· {status.today_snapshots || 0}次采集</span>
      )}
    </div>
  );
}
