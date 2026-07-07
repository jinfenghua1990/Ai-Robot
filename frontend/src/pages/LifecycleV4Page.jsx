import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';
import LifecycleSectorOverview from '../components/lifecycle/LifecycleSectorOverview';
import LifecycleLeaderCard from '../components/lifecycle/LifecycleLeaderCard';
import LifecycleCandidateList, { LifecycleHeatPool } from '../components/lifecycle/LifecycleCandidateList';
import LifecycleHistoryStats from '../components/lifecycle/LifecycleHistoryStats';

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
export default function LifecycleV4Page() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [stats, setStats] = useState(null);
  const [history, setHistory] = useState([]);

  useEffect(() => {
    (async () => {
      const { ok, data, error } = await apiFetch('/api/leader/system');
      if (ok) { setData(data); setError(null); }
      else { setError(error); }
      setLoading(false);
    })();
    (async () => {
      const { ok, data } = await apiFetch('/api/leader/stats');
      if (ok) setStats(data);
    })();
    (async () => {
      const { ok, data } = await apiFetch('/api/leader/history?limit=50');
      if (ok) setHistory(data);
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
        <span className="ml-3 text-sm" style={{ color: 'var(--text-muted)' }}>双引擎决策分析中...</span>
      </div>
    );
  }

  if (error) {
    return <div className="rounded-lg p-4 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>加载失败: {error}</div>;
  }

  if (!data) return null;

  const sf = data.sector_filter || {};
  const summary = sf.summary || {};
  const leader = data.leader;
  const candidates = data.candidates || [];
  const allStocks = data.all_stocks || [];
  const switchWarning = data.switch_warning;

  return (
    <div className="space-y-2">
      {/* 顶部状态条 */}
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
