/**
 * 游资中心 — 合并龙虎榜 + 龙头系统
 *
 * Tab 切换两个子页面：
 *  - 龙虎榜：资金动向榜 + 共振信号池 + 游资战绩（原 YuziBillboardPage）
 *  - 龙头系统：主龙头加冕 + 候选龙头 + 板块状态 + 热度池（原 TradingSystemPage）
 */
import { useState, lazy, Suspense } from 'react';

const YuziBillboardPage = lazy(() => import('./YuziBillboardPage'));
const TradingSystemPage = lazy(() => import('./TradingSystemPage'));

const TABS = [
  { key: 'billboard', label: '龙虎榜', icon: '📊', desc: '资金动向 + 共振信号 + 游资战绩' },
  { key: 'leader', label: '龙头系统', icon: '👑', desc: '主龙头 + 候选 + 板块状态 + 热度池' },
];

export default function YuziCenterPage() {
  const [activeTab, setActiveTab] = useState('billboard');

  return (
    <div className="flex flex-col h-full">
      {/* Tab 栏 */}
      <div
        className="flex items-center gap-1 px-3 py-2 border-b flex-shrink-0"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        {TABS.map(tab => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className="px-3 py-1.5 rounded-lg text-sm font-medium transition-colors flex items-center gap-1.5"
            style={{
              background: activeTab === tab.key ? 'rgba(168,85,247,0.15)' : 'transparent',
              color: activeTab === tab.key ? '#a855f7' : 'var(--text-secondary)',
              border: `1px solid ${activeTab === tab.key ? 'rgba(168,85,247,0.4)' : 'var(--border-color)'}`,
            }}
          >
            <span>{tab.icon}</span>
            <span>{tab.label}</span>
          </button>
        ))}
        <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>
          {TABS.find(t => t.key === activeTab)?.desc}
        </span>
      </div>

      {/* Tab 内容 */}
      <div className="flex-1 overflow-auto">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-96">
              <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            </div>
          }
        >
          {activeTab === 'billboard' && <YuziBillboardPage />}
          {activeTab === 'leader' && <TradingSystemPage />}
        </Suspense>
      </div>
    </div>
  );
}
