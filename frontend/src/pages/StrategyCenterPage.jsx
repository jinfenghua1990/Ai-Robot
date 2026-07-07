import { useState, lazy, Suspense, useCallback, useEffect, useMemo } from 'react';
import { apiFetch } from '../utils/request';

/**
 * 策略中心：所有策略扁平化单行Tab
 * [龙头] V4双引擎 / V1趋势阶段 / V2强度排行 / V3周期V3
 * [智能] 热度综合 / 白虎V3.0 / 青龙 / 主升浪
 * [BS]   动态策略1 / 动态策略2 / ... + 完整配置
 */
const LifecycleV4Page = lazy(() => import('./LifecycleV4Page'));
const LifecyclePage = lazy(() => import('./LifecyclePage'));
const LifecycleV2Page = lazy(() => import('./LifecycleV2Page'));
const LifecycleV3Page = lazy(() => import('./LifecycleV3Page'));
const ScreenerPage = lazy(() => import('./ScreenerPage'));
const BSScreenerPage = lazy(() => import('./BSScreenerPage'));
const BSStrategyTab = lazy(() => import('./BSStrategyTab'));

// 静态Tab定义（已调试完成的策略，每天看结果）
const STATIC_TABS = [
  // 龙头组
  { key: 'v4', label: '双引擎决策', shortLabel: 'V4双引擎', icon: '🧠', group: 'leader', Component: LifecycleV4Page },
  { key: 'v1', label: '龙头趋势阶段', shortLabel: 'V1趋势阶段', icon: '👑', group: 'leader', Component: LifecyclePage },
  { key: 'v2', label: '龙头强度排行', shortLabel: 'V2强度排行', icon: '⚡', group: 'leader', Component: LifecycleV2Page },
  { key: 'v3', label: '龙头周期V3', shortLabel: 'V3周期', icon: '🔄', group: 'leader', Component: LifecycleV3Page },
  // 智能选股组（3个子策略拆开）
  { key: 'smart-heat', label: '热度综合', shortLabel: '热度综合', icon: '🔥', group: 'smart', Component: ScreenerPage, props: { initialStrategy: 'heat', hideStrategySelector: true } },
  { key: 'smart-baihu', label: '白虎V3.0', shortLabel: '白虎V3.0', icon: '🐯', group: 'smart', Component: ScreenerPage, props: { initialStrategy: 'baihu', hideStrategySelector: true } },
  { key: 'smart-qinglong', label: '青龙', shortLabel: '青龙', icon: '🐉', group: 'smart', Component: ScreenerPage, props: { initialStrategy: 'qinglong', hideStrategySelector: true } },
  { key: 'smart-zhushenglang', label: '主升浪', shortLabel: '主升浪', icon: '🚀', group: 'smart', Component: ScreenerPage, props: { initialStrategy: 'zhushenglang', hideStrategySelector: true } },
];

// BS配置页（策略编辑器，不参与扁平Tab，放右侧操作区）
const BS_CONFIG_TAB = { key: 'bs-full', label: '策略配置调整中心', Component: BSScreenerPage };

const GROUP_LABELS = {
  leader: '龙头',
  smart: '智能',
  bs: 'BS',
  'bs-config': 'BS',
};

const GROUP_COLORS = {
  leader: '#ef4444',
  smart: '#3b82f6',
  bs: '#22c55e',
  'bs-config': '#22c55e',
};

function TabLoader() {
  return (
    <div className="flex items-center justify-center h-64 gap-2">
      <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>策略加载中...</span>
    </div>
  );
}

export default function StrategyCenterPage() {
  const [activeKey, setActiveKey] = useState('v4');
  const [loadedKeys, setLoadedKeys] = useState(() => new Set(['v4']));
  const [refreshTicks, setRefreshTicks] = useState({});
  // BS动态策略Tab（从回测历史加载）
  const [bsStrategies, setBsStrategies] = useState([]);
  // 策略健康状态
  const [healthData, setHealthData] = useState(null);
  const [healthLoading, setHealthLoading] = useState(false);
  const [scanning, setScanning] = useState(false);

  // 加载BS回测历史前5个策略作为独立Tab
  useEffect(() => {
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/bs-screener/backtest/history?limit=5');
        if (ok) {
          setBsStrategies(data.history || []);
        }
      } catch (e) { /* 静默失败 */ }
    })();
  }, []);

  // 拉取策略健康状态
  const loadHealth = useCallback(async () => {
    setHealthLoading(true);
    try {
      const { ok, data } = await apiFetch('/api/strategy-health');
      if (ok) setHealthData(data);
    } catch (e) { console.error('[StrategyCenter] health fetch failed:', e); }
    setHealthLoading(false);
  }, []);

  useEffect(() => { loadHealth(); }, [loadHealth]);

  // 手动触发策略扫描
  const triggerScan = useCallback(async () => {
    if (scanning) return;
    setScanning(true);
    try {
      await apiFetch('/api/strategy-scan/trigger', { method: 'POST' });
      await loadHealth();
    } catch (e) { /* silent */ }
    setScanning(false);
  }, [scanning, loadHealth]);

  // 动态BS策略Tab（命名规则：BS-{维度}-V{版本号}）
  const bsDynamicTabs = useMemo(() => bsStrategies.map((h) => {
    const dimLabel = h.dimension === 'star' ? '科创' : h.dimension === 'chinext' ? '创业' : h.dimension === 'all' ? '全A股' : '自定义';
    const displayName = `BS-${dimLabel}-V${h.id}`;
    return {
      key: `bs-strategy-${h.id}`,
      label: displayName,
      shortLabel: displayName,
      icon: '📊',
      group: 'bs',
      Component: BSStrategyTab,
      props: { strategy: {
        id: h.id,
        name: displayName,
        dimension: h.dimension,
        win_rate: h.win_rate,
        stock_win_rate: h.stock_win_rate,
        profit_factor: h.profit_factor,
        atr_period: h.atr_period,
        atr_multiplier: h.atr_multiplier,
        volume_filter: h.volume_filter,
        ma20_filter: h.ma20_filter,
        ma60_trend: h.ma60_trend,
        rsi_filter: h.rsi_filter,
        strong_volume: h.strong_volume,
        macd_filter: h.macd_filter,
        kdj_filter: h.kdj_filter,
        rsi_lower: h.rsi_lower || 30,
        rsi_upper: h.rsi_upper || 70,
      }},
    };
  }), [bsStrategies]);

  // 合并所有Tab（不包含BS配置，配置在右侧操作区）
  const allTabs = useMemo(() => [...STATIC_TABS, ...bsDynamicTabs], [bsDynamicTabs]);

  const handleTabChange = useCallback((key) => {
    setActiveKey(key);
    setLoadedKeys(prev => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }, []);

  // 监听策略总览的"查看Tab"事件（从策略配置调整中心跳转）
  useEffect(() => {
    const handler = (e) => {
      const { tabKey } = e.detail || {};
      if (tabKey) {
        handleTabChange(tabKey);
      }
    };
    window.addEventListener('strategy-center-switch-tab', handler);
    return () => window.removeEventListener('strategy-center-switch-tab', handler);
  }, [handleTabChange]);

  const handleRefresh = useCallback(() => {
    setRefreshTicks(prev => ({ ...prev, [activeKey]: (prev[activeKey] || 0) + 1 }));
  }, [activeKey]);

  // 打开BS配置页（策略编辑器）
  const handleOpenBSConfig = useCallback(() => {
    handleTabChange(BS_CONFIG_TAB.key);
  }, [handleTabChange]);

  const activeTab = allTabs.find(t => t.key === activeKey);
  const isBSConfigActive = activeKey === BS_CONFIG_TAB.key;
  // 用于渲染内容区的完整Tab列表（包含BS配置）
  const allRenderTabs = useMemo(() => [...allTabs, BS_CONFIG_TAB], [allTabs]);

  return (
    <div className="space-y-2">
      {/* 单行Tab导航：左侧策略Tab + 右侧操作区(刷新+BS配置) */}
      <div className="flex items-center gap-0.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
        {/* 左侧：策略Tab扁平化 */}
        <div className="flex items-center gap-0.5 overflow-x-auto flex-1">
          {allTabs.map((tab, idx) => {
            const isActive = tab.key === activeKey;
            const prevTab = allTabs[idx - 1];
            const showDivider = idx > 0 && prevTab && prevTab.group !== tab.group;
            const groupColor = GROUP_COLORS[tab.group] || 'var(--text-muted)';
            return (
              <div key={tab.key} className="flex items-center flex-shrink-0">
                {showDivider && (
                  <span className="mx-1 text-xs" style={{ color: 'var(--border-color)' }}>|</span>
                )}
                <button
                  onClick={() => handleTabChange(tab.key)}
                  className="relative px-2 py-1.5 text-xs font-medium transition-all flex items-center gap-1 rounded-md"
                  style={{
                    color: isActive ? groupColor : 'var(--text-muted)',
                    background: isActive ? groupColor + '10' : 'transparent',
                  }}
                  title={tab.label}
                >
                  <span className="text-sm">{tab.icon}</span>
                  <span className="hidden sm:inline">{tab.shortLabel}</span>
                  {isActive && (
                    <span className="absolute left-0 right-0 bottom-0 h-0.5 rounded-full" style={{ background: groupColor }} />
                  )}
                  {loadedKeys.has(tab.key) && !isActive && (
                    <span className="absolute top-1 right-1 w-1 h-1 rounded-full" style={{ background: 'rgba(34,197,94,0.6)' }} title="已加载" />
                  )}
                </button>
              </div>
            );
          })}
        </div>

        {/* 右侧：操作区（刷新 + BS策略配置） */}
        <div className="flex items-center gap-1 flex-shrink-0 ml-2">
          <button
            onClick={handleRefresh}
            className="px-2 py-1 rounded-md text-xs flex items-center gap-1 transition-colors hover:opacity-80 border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            title="刷新当前策略数据"
          >
            🔄 刷新
          </button>
          <button
            onClick={handleOpenBSConfig}
            className="px-2 py-1 rounded-md text-xs flex items-center gap-1 transition-colors border font-medium"
            style={{
              borderColor: isBSConfigActive ? 'rgba(34,197,94,0.5)' : 'var(--border-color)',
              color: isBSConfigActive ? '#22c55e' : 'var(--text-secondary)',
              background: isBSConfigActive ? 'rgba(34,197,94,0.08)' : 'transparent',
            }}
            title="策略配置调整中心：调整参数、跑回测、保存策略"
          >
            🔧 策略配置
          </button>
        </div>
      </div>

      {/* 策略运行状态条 */}
      <StrategyHealthBar data={healthData} loading={healthLoading} onRefresh={loadHealth} onScan={triggerScan} scanning={scanning} />

      {/* Tab内容区（包含BS配置页） */}
      <div className="tab-content">
        {allRenderTabs.map(tab => {
          if (!loadedKeys.has(tab.key)) return null;
          const isActive = tab.key === activeKey;
          const { Component } = tab;
          const extraProps = tab.props || {};
          return (
            <div
              key={tab.key}
              className="transition-opacity duration-200"
              style={{
                display: isActive ? 'block' : 'none',
                opacity: isActive ? 1 : 0,
              }}
            >
              <Suspense fallback={<TabLoader />}>
                <Component key={`${tab.key}-${refreshTicks[tab.key] || 0}`} {...extraProps} />
              </Suspense>
            </div>
          );
        })}
        {!loadedKeys.has(activeKey) && <TabLoader />}
      </div>
    </div>
  );
}

// 策略运行状态条组件
const STATUS_CONFIG = {
  success: { color: '#22c55e', label: '成功', dot: '🟢' },
  failed: { color: '#ef4444', label: '失败', dot: '🔴' },
  running: { color: '#eab308', label: '运行中', dot: '🟡' },
  never_run: { color: 'var(--text-muted)', label: '未运行', dot: '⚪' },
};

function StrategyHealthBar({ data, loading, onRefresh, onScan, scanning }) {
  if (loading && !data) {
    return (
      <div className="flex items-center gap-2 px-2 py-1.5 rounded-md text-xs" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
        <div className="w-3 h-3 border rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
        策略状态加载中...
      </div>
    );
  }

  if (!data) return null;

  const { strategies = [], all_done, trade_date, today_total_hits } = data;

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 rounded-md flex-wrap" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
      <span className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>
        📊 {trade_date} 策略状态
      </span>
      <span className="text-xs" style={{ color: all_done ? '#22c55e' : 'var(--text-muted)' }}>
        {all_done ? '✓ 全部完成' : '⏳ 部分待运行'}
      </span>
      {today_total_hits != null && (
        <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
          今日命中 {today_total_hits}
        </span>
      )}
      <span className="text-xs" style={{ color: 'var(--border-color)' }}>|</span>
      {strategies.map(s => {
        const cfg = STATUS_CONFIG[s.status] || STATUS_CONFIG.never_run;
        const isToday = s.is_today;
        return (
          <div
            key={s.key}
            className="flex items-center gap-1 text-xs px-1.5 py-0.5 rounded"
            style={{ background: cfg.color + '10', color: cfg.color }}
            title={s.error_msg ? `错误: ${s.error_msg}` : `${s.name} ${cfg.label}${s.duration_seconds ? ` ${s.duration_seconds}s` : ''}`}
          >
            <span>{s.icon}</span>
            <span>{s.name}</span>
            <span>{cfg.dot}</span>
            {isToday && s.hit_count != null && (
              <span style={{ fontWeight: 600 }}>{s.hit_count}只</span>
            )}
            {isToday && s.duration_seconds != null && (
              <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{s.duration_seconds}s</span>
            )}
          </div>
        );
      })}
      <div className="flex-1" />
      <button
        onClick={onRefresh}
        className="text-xs px-1.5 py-0.5 rounded hover:opacity-80"
        style={{ color: 'var(--text-muted)', border: '1px solid var(--border-color)' }}
        title="刷新策略状态"
      >
        🔄
      </button>
      <button
        onClick={onScan}
        disabled={scanning || all_done}
        className="text-xs px-2 py-0.5 rounded font-medium disabled:opacity-50"
        style={{
          color: scanning ? 'var(--text-muted)' : '#fff',
          background: scanning ? 'var(--border-color)' : (all_done ? 'var(--border-color)' : '#3b82f6'),
          border: 'none',
        }}
        title={all_done ? '今日已全部跑完' : '手动触发策略扫描'}
      >
        {scanning ? '扫描中...' : (all_done ? '已完成' : '▶ 触发扫描')}
      </button>
    </div>
  );
}
