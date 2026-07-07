import { useState, lazy, Suspense, useCallback, useEffect } from 'react';

// 懒加载四个子页面
const LifecyclePage = lazy(() => import('./LifecyclePage'));
const LifecycleV2Page = lazy(() => import('./LifecycleV2Page'));
const LifecycleV3Page = lazy(() => import('./LifecycleV3Page'));
const LifecycleV4Page = lazy(() => import('./LifecycleV4Page'));

const TABS = [
  { key: 'v4', label: '双引擎决策', icon: '🧠', Component: LifecycleV4Page },
  { key: 'v1', label: '龙头趋势阶段', icon: '👑', Component: LifecyclePage },
  { key: 'v2', label: '龙头强度排行', icon: '⚡', Component: LifecycleV2Page },
  { key: 'v3', label: '龙头周期V3', icon: '🔄', Component: LifecycleV3Page },
];

function TabLoader() {
  return (
    <div className="flex items-center justify-center h-64 gap-2">
      <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>模块加载中...</span>
    </div>
  );
}

/**
 * 龙头分析Tab容器
 * 二级Tab栏已上移到 StrategyCenterPage，本组件只负责渲染内容
 * 接受 subKey / onSubKeyChange 由父组件控制
 */
export default function LifecycleHubPage({ subKey, onSubKeyChange }) {
  // 默认"双引擎决策"
  const [innerKey, setInnerKey] = useState('v4');
  // 父组件控制优先
  const activeKey = subKey || innerKey;
  const setActiveKey = (k) => {
    setInnerKey(k);
    if (onSubKeyChange) onSubKeyChange(k);
  };

  // 已加载过的tab集合（缓存：首次切换才加载，之后保留状态）
  const [loadedKeys, setLoadedKeys] = useState(() => new Set([activeKey]));
  // 各tab独立的刷新令牌
  const [refreshTicks, setRefreshTicks] = useState({});

  // 同步外部 subKey 变化（点击外层Tab时）
  useEffect(() => {
    if (subKey && subKey !== innerKey) {
      setInnerKey(subKey);
      setLoadedKeys(prev => {
        if (prev.has(subKey)) return prev;
        const next = new Set(prev);
        next.add(subKey);
        return next;
      });
    }
  }, [subKey]);

  const handleTabChange = useCallback((key) => {
    setActiveKey(key);
    setLoadedKeys(prev => {
      if (prev.has(key)) return prev;
      const next = new Set(prev);
      next.add(key);
      return next;
    });
  }, []);

  const handleRefresh = useCallback(() => {
    setRefreshTicks(prev => ({ ...prev, [activeKey]: (prev[activeKey] || 0) + 1 }));
  }, [activeKey]);

  return (
    <div className="space-y-2">
      {/* 二级Tab栏已上移到外层，这里仅保留刷新按钮（极简） */}
      <div className="flex justify-end">
        <button
          onClick={handleRefresh}
          className="px-2 py-1 rounded-md border text-xs flex items-center gap-1 transition-colors hover:opacity-80"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          title="刷新当前子模块数据"
        >
          🔄 刷新子模块
        </button>
      </div>

      {/* 内容区：已加载的tab保持挂载以保留状态，用display隐藏 */}
      <div className="tab-content">
        {TABS.map(tab => {
          if (!loadedKeys.has(tab.key)) return null;
          const isActive = tab.key === activeKey;
          const { Component } = tab;
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
                <Component key={`${tab.key}-${refreshTicks[tab.key] || 0}`} />
              </Suspense>
            </div>
          );
        })}
        {!loadedKeys.has(activeKey) && <TabLoader />}
      </div>
    </div>
  );
}
