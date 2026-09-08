import { useSearchParams } from 'react-router-dom';
import TodayPage from './TodayPage';
import PanoramaPage from './PanoramaPage';
import MarketFlowRankPage from './MarketFlowRankPage';
import ConceptFlowPage from './ConceptFlowPage';
import IndexFlowPage from './IndexFlowPage';

const TABS = [
  { key: 'overview', label: '市场总览', icon: '📊', Component: TodayPage },
  { key: 'panorama', label: '板块轮动', icon: '🔥', Component: PanoramaPage },
  { key: 'stock-flow', label: '全市场资金', icon: '🌐', Component: MarketFlowRankPage },
  { key: 'concept', label: '概念资金', icon: '💸', Component: ConceptFlowPage },
  { key: 'index-flow', label: '指数资金', icon: '🇨🇳', Component: IndexFlowPage },
];

/**
 * A 股市场的唯一入口。页面通过页签组织不同观察层级，避免在左侧导航
 * 重复出现同一份市场、板块与资金数据。
 */
export default function MarketCenterPage() {
  const [params, setParams] = useSearchParams();
  const requestedTab = params.get('tab');
  const activeTab = TABS.some((tab) => tab.key === requestedTab) ? requestedTab : 'overview';
  const active = TABS.find((tab) => tab.key === activeTab);
  const ActivePage = active.Component;

  const selectTab = (key) => {
    const next = new URLSearchParams();
    if (key !== 'overview') next.set('tab', key);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-3">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>市场中心</h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            先看市场状态，再看板块、资金和概念轮动
          </p>
        </div>
        <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="市场中心视图">
          {TABS.map((tab) => {
            const selected = activeTab === tab.key;
            return (
              <button
                key={tab.key}
                type="button"
                role="tab"
                aria-selected={selected}
                onClick={() => selectTab(tab.key)}
                className="px-2.5 py-1.5 rounded-lg border text-xs transition-colors"
                style={{
                  borderColor: selected ? 'var(--accent-blue)' : 'var(--border-color)',
                  background: selected ? 'rgba(59,130,246,0.1)' : 'var(--bg-card)',
                  color: selected ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  fontWeight: selected ? 600 : 400,
                }}
              >
                {tab.icon} {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <div role="tabpanel">
        {activeTab === 'stock-flow' ? <ActivePage embedded /> :
          activeTab === 'concept' ? <ActivePage embedded /> : <ActivePage />}
      </div>
    </div>
  );
}
