import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import LifecycleSectorOverview from '../components/lifecycle/LifecycleSectorOverview';
import LifecycleLeaderCard from '../components/lifecycle/LifecycleLeaderCard';
import LifecycleCandidateList, { LifecycleHeatPool } from '../components/lifecycle/LifecycleCandidateList';
import LifecycleHistoryStats from '../components/lifecycle/LifecycleHistoryStats';
import { POLL_INTERVAL } from '../utils/constants';

/**
 * 龙头双引擎决策系统 V4
 * 板块趋势引擎(Level1) → 龙头引擎(Level2) → 个股评分(Level3)
 *
 * 页面结构（各 section 已拆为独立组件）：
 * ① 板块状态总览 → LifecycleSectorOverview
 * ② 主龙卡      → LifecycleLeaderCard
 * ③ 候选龙      → LifecycleCandidateList
 * ④ 热度池      → LifecycleHeatPool
 * ⑤ 历史统计    → LifecycleHistoryStats
 */
const isIntraday = () => {
  const now = new Date();
  const wd = now.getDay();
  if (wd === 0 || wd === 6) return false;
  const t = now.getHours() * 60 + now.getMinutes();
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900);
};

export default function LifecycleV4Page() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [history, setHistory] = useState([]);
  const [autoRefresh, setAutoRefresh] = useState(true);
  const [snapshotTime, setSnapshotTime] = useState('');

  const fetchSystem = useCallback(async (date) => {
    const url = date ? `/api/leader/system?target_date=${date}` : '/api/leader/system';
    const { ok, data, error } = await apiFetch(url);
    if (ok) { setData(data); setError(null); }
    else { setError(error); }
    setLoading(false);
    setSnapshotTime(new Date().toLocaleTimeString('zh-CN'));
  }, []);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    fetchSystem(selectedDate);
  }, [selectedDate, fetchSystem]);

  useEffect(() => {
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/leader/stats');
        if (ok) setStats(data);
      } catch (e) { console.error('[StrategyCenter] leader/stats failed:', e); }
    })();
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/leader/history?limit=50');
        if (ok) setHistory(data);
      } catch (e) { console.error('[StrategyCenter] leader/history failed:', e); }
    })();
  }, []);

  useEffect(() => {
    if (!autoRefresh || !isIntraday()) return;
    const handler = () => { if (!document.hidden) fetchSystem(selectedDate); };
    const id = setInterval(handler, POLL_INTERVAL);
    return () => clearInterval(id);
  }, [autoRefresh, selectedDate, fetchSystem]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
        <span className="ml-3 text-sm" style={{ color: 'var(--text-muted)' }}>双引擎决策分析中...</span>
      </div>
    );
  }

  if (error && !data) {
    return <div className="rounded-lg p-4 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>加载失败: {error}</div>;
  }

  if (!data) return null;

  const sf = data.sector_filter || {};
  const summary = sf.summary || {};
  const leader = data.leader;
  const candidates = data.candidates || [];
  const allStocks = data.all_stocks || [];
  const switchWarning = data.switchWarning;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between flex-wrap gap-2">
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
        <div className="flex items-center gap-2">
          {snapshotTime && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>快照: {snapshotTime}</span>
          )}
          <button onClick={() => setAutoRefresh(r => !r)} className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
            style={{ borderColor: autoRefresh ? '#22c55e' : 'var(--border-color)', color: autoRefresh ? '#22c55e' : 'var(--text-secondary)', background: autoRefresh ? 'rgba(34,197,94,0.1)' : 'transparent' }}>
            {autoRefresh ? '⏸ 暂停' : '▶ 刷新'}
          </button>
        </div>
      </div>

      <div className="flex items-center justify-between px-3 py-2 rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-3 text-sm">
          <span style={{ color: 'var(--text-muted)' }}>📅 {data.date || '--'}</span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            板块: <b style={{ color: '#ef4444' }}>{summary.strong_count || 0}</b>主升
            <b style={{ color: '#facc15', marginLeft: 8 }}>{summary.rotation_count || 0}</b>轮动
            <b style={{ color: 'var(--text-muted)', marginLeft: 8 }}>{summary.down_count || 0}</b>下降
          </span>
          <span style={{ color: 'var(--text-muted)' }}>|</span>
          <span style={{ color: 'var(--text-secondary)' }}>
            龙头池: <b style={{ color: 'var(--text-primary)' }}>{data.all_count || 0}</b>只
          </span>
        </div>
        {data.message && data.message !== 'ok' && (
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(250,204,21,0.1)', color: '#facc15' }}>
            ⚠ {data.message}
          </span>
        )}
      </div>

      <LifecycleSectorOverview sectorFilter={sf} />
      <LifecycleLeaderCard leader={leader} switchWarning={switchWarning} />
      <LifecycleCandidateList candidates={candidates} />
      <LifecycleHeatPool allStocks={allStocks} />
      <LifecycleHistoryStats stats={stats} history={history} />
    </div>
  );
}
