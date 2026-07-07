import { useState, useEffect, useCallback, useMemo } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import { apiFetch } from '../utils/request';
import DateNavigator from '../components/DateNavigator';
import ModuleGroup from '../components/sections/ModuleGroup';
import AfterConceptSectorFlowSection from '../components/sections/AfterConceptSectorFlowSection';
import RealtimeConceptSectorSection from '../components/sections/RealtimeConceptSectorSection';
import ConceptRealtimeTrendChart from '../components/charts/ConceptRealtimeTrendChart';
import ConceptSectorFilter, { loadSelectedConcepts, saveSelectedConcepts } from '../components/sections/ConceptSectorFilter';
import SharedTrendPanel from '../components/sections/SharedTrendPanel';
import { POLL_INTERVAL, SLOW_POLL_INTERVAL } from '../utils/constants';

/**
 * 概念板块独立页面
 * 复用 PanoramaPage 中的概念板块模块（盘后 vs 实时 + 筛选器 + 联动趋势）
 */
export default function ConceptFlowPage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();

  const [selectedSector, setSelectedSector] = useState(null);
  const [rtConceptSectors, setRtConceptSectors] = useState(null);
  const [autoRefresh, setAutoRefresh] = useState(true);

  // 共享盘中趋势
  const [trendType, setTrendType] = useState(null);
  const [trendData, setTrendData] = useState(null);

  // 概念板块筛选（左右盘后/实时共用，localStorage 持久化）
  const [selectedConcepts, setSelectedConcepts] = useState(() => loadSelectedConcepts());
  const handleConceptsChange = useCallback((arr) => {
    setSelectedConcepts(arr);
    saveSelectedConcepts(arr);
  }, []);

  // 全量可选概念列表（按近60天热度排序，定期自动刷新）+ 概念中文释义
  const [hotConceptSectors, setHotConceptSectors] = useState([]);
  const [conceptDescriptions, setConceptDescriptions] = useState({});
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const { ok, data } = await apiFetch('/api/concept-sector-hot?days=60');
      if (cancelled || !ok) return;
      const sectors = data?.sectors || [];
      setHotConceptSectors(sectors.map(s => s.sector));
      // 收集概念释义（后端返回的 description 字段）
      const descMap = {};
      sectors.forEach(s => {
        if (s.description) descMap[s.sector] = s.description;
      });
      if (!cancelled) setConceptDescriptions(prev => ({ ...prev, ...descMap }));
    };
    load();
    const id = setInterval(load, SLOW_POLL_INTERVAL); // 每5分钟刷新热门列表
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  const allConceptSectors = useMemo(() => {
    const hotSet = new Set(hotConceptSectors);
    const extra = (rtConceptSectors?.sectors || [])
      .map(s => s.sector)
      .filter(s => !hotSet.has(s));
    return [...hotConceptSectors, ...extra];
  }, [hotConceptSectors, rtConceptSectors]);

  // 根据已选概念数量动态计算图表高度：每条约 34px，最小 380px，最大 1200px
  // 概念多时自动拉高避免 endLabel 重叠，概念少时自动缩小节省空间
  const chartHeight = useMemo(() => {
    const n = selectedConcepts.length;
    return Math.max(380, Math.min(1200, n * 34 + 60));
  }, [selectedConcepts]);

  // 单一实时轮询（只拉概念板块）
  const fetchRealtime = useCallback(async () => {
    const { ok, data } = await apiFetch('/api/realtime/concept-sectors');
    if (ok) setRtConceptSectors(data);
  }, []);

  useEffect(() => {
    fetchRealtime();
    if (!autoRefresh) return;
    const id = setInterval(fetchRealtime, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [fetchRealtime, autoRefresh]);

  // 共享盘中趋势（概念走 concept-sector-trend 接口）
  const fetchTrend = useCallback(async (kind, name) => {
    setTrendType({ kind, name });
    const url = `/api/realtime/concept-sector-trend?sector=${encodeURIComponent(name)}`;
    const { ok, data } = await apiFetch(url);
    if (ok) setTrendData(data);
  }, []);

  const handleSelectSector = useCallback((name) => {
    setSelectedSector(name);
    if (name) fetchTrend('sector', name);
    else { setTrendType(null); setTrendData(null); }
  }, [fetchTrend]);

  const handleCloseTrend = useCallback(() => {
    setTrendType(null);
    setTrendData(null);
  }, []);

  return (
    <div className="space-y-2">
      {/* 页面标题 + 实时状态条 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
            概念板块资金流向
          </h2>
          <p className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>
            盘后 20 日净流入趋势 vs 盘中实时累计走势 · 顶部筛选器左右联动
          </p>
        </div>
        <RealtimeStatusBar />
      </div>

      {/* 日期导航 + 自动刷新开关 */}
      <div className="flex items-center gap-2 flex-wrap">
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          快照: {rtConceptSectors?.snapshot_time || '—'}
        </span>
        <button
          onClick={() => setAutoRefresh(r => !r)}
          className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
          style={{
            borderColor: autoRefresh ? '#22c55e' : 'var(--border-color)',
            color: autoRefresh ? '#22c55e' : 'var(--text-secondary)',
            background: autoRefresh ? 'rgba(34,197,94,0.1)' : 'transparent',
          }}
        >
          {autoRefresh ? '⏸ 暂停' : '▶ 刷新'}
        </button>
      </div>

      {/* 统一筛选器（通栏 · 下方所有模块联动） */}
      <div className="rounded-xl border p-2.5 flex items-center gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <span className="text-xs font-bold whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>🔍 统一筛选概念</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>
          已选 {selectedConcepts.length} 个 · 下方全部模块联动
        </span>
        <div className="flex-1 min-w-0">
          <ConceptSectorFilter
            allSectors={allConceptSectors}
            selected={selectedConcepts}
            onChange={handleConceptsChange}
            descriptions={conceptDescriptions}
          />
        </div>
      </div>

      {/* 通栏：概念板块 · 盘后 vs 实时 */}
      <ModuleGroup
        title="概念板块"
        badge={selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后 vs 实时` : ''}
        contentHeight={`${chartHeight}px`}
      >
        <ModuleGroup.Header
          left={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>盘后概念板块趋势</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>盘后数据</span>
            </div>
          }
          right={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>实时概念板块走势</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>最终表·混合采集</span>
            </div>
          }
        />
        <ModuleGroup.SubHeader
          left={
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              📊 concept_sector_flow 表（盘后归档）· 已选 {selectedConcepts.length} 个概念 · 20 日净流入趋势 · 点击折线联动
            </span>
          }
          right={
            <div className="flex items-center justify-end gap-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span>📊 realtime_concept_sector_flow 表</span>
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

      {/* 中转层（新浪直采）盘后 vs 实时 — 与上方最终表对比 */}
      <ModuleGroup
        title="中转层（新浪直采）"
        badge="纯新浪API · 与上方最终表对比"
        contentHeight={`${chartHeight}px`}
      >
        <ModuleGroup.Header
          left={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>盘后概念板块趋势</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>盘后数据</span>
            </div>
          }
          right={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>实时概念板块走势</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>中转层·新浪直采</span>
            </div>
          }
        />
        <ModuleGroup.SubHeader
          left={
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              📊 concept_sector_flow 表（盘后归档）· 已选 {selectedConcepts.length} 个概念 · 20 日净流入趋势
            </span>
          }
          right={
            <div className="flex items-center justify-end gap-3 text-[10px]" style={{ color: 'var(--text-muted)' }}>
              <span>📊 realtime_money_flow_snapshot 表 · 单位已转万</span>
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
            rtConceptSectors?.trade_date ? (
              <ConceptRealtimeTrendChart
                sectors={selectedConcepts}
                rtSectors={rtConceptSectors}
                selectedSector={selectedSector}
                onSectorClick={handleSelectSector}
                height="100%"
                maxLines={500}
                trendApiPath="/api/realtime/money-flow-trend"
                bulkTrendApiPath="/api/realtime/money-flow-trends"
              />
            ) : (
              <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>
            )
          }
        />
      </ModuleGroup>

      {/* 实时数据源对比：最终表（混合采集） vs 中转层（新浪直采） */}
      <ModuleGroup
        title="实时数据源对比"
        badge="最终表 vs 中转层"
        contentHeight={`${chartHeight}px`}
      >
        <ModuleGroup.Header
          left={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>最终表（混合采集）</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>新浪+成分股合成</span>
            </div>
          }
          right={
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>中转层（新浪直采）</span>
              <span className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>纯新浪API</span>
            </div>
          }
        />
        <ModuleGroup.SubHeader
          left={
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              📊 realtime_concept_sector_flow 表 · 新浪直采 + 成分股合成交替写入
            </span>
          }
          right={
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              📊 realtime_money_flow_snapshot 表 · 新浪API直接采集 · 单位已转万
            </span>
          }
        />
        <ModuleGroup.Content
          left={
            rtConceptSectors?.trade_date ? (
              <ConceptRealtimeTrendChart
                sectors={selectedConcepts}
                rtSectors={rtConceptSectors}
                selectedSector={selectedSector}
                onSectorClick={handleSelectSector}
                height="100%"
                maxLines={500}
                trendApiPath="/api/realtime/concept-sector-trend"
                bulkTrendApiPath="/api/realtime/concept-sector-trends"
              />
            ) : (
              <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>
            )
          }
          right={
            rtConceptSectors?.trade_date ? (
              <ConceptRealtimeTrendChart
                sectors={selectedConcepts}
                rtSectors={rtConceptSectors}
                selectedSector={selectedSector}
                onSectorClick={handleSelectSector}
                height="100%"
                maxLines={500}
                trendApiPath="/api/realtime/money-flow-trend"
                bulkTrendApiPath="/api/realtime/money-flow-trends"
              />
            ) : (
              <div className="flex items-center justify-center h-full text-sm" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>
            )
          }
        />
      </ModuleGroup>

      {/* 盘中趋势面板（由 selectedSector 驱动） */}
      <SharedTrendPanel trendType={trendType} trendData={trendData} onClose={handleCloseTrend} />
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
