import { lazy, Suspense, useState } from 'react';
import { useLocation, useSearchParams } from 'react-router-dom';

const IntelPage = lazy(() => import('./research/ResearchIntelPage'));
const DailyReviewPage = lazy(() => import('./research/ResearchDailyReviewPage'));

const TABS = [
  { key: 'intel', label: '资讯雷达', icon: '📡', path: '/research/intel', Component: IntelPage },
  { key: 'daily', label: '每日复盘', icon: '📰', path: '/research/daily-review', Component: DailyReviewPage },
];

export default function MarketIntelHub() {
  const [sp] = useSearchParams();
  const { pathname } = useLocation();
  const fromQuery = TABS.find(t => t.key === sp.get('tab'));
  const fromPath = TABS.find(t => pathname.startsWith(t.path));
  const [tab, setTab] = useState((fromQuery || fromPath || TABS[0]).key);
  const active = TABS.find(t => t.key === tab) || TABS[0];
  const Component = active.Component;

  return (
    <div className="space-y-3 fade-in">
      <div className="flex items-center gap-1 border-b pb-2" style={{ borderColor: 'var(--border-color)' }}>
        {TABS.map(t => {
          const on = t.key === active.key;
          return (
            <button key={t.key} onClick={() => setTab(t.key)}
              className="flex items-center gap-1 px-3 py-1.5 rounded-md text-xs transition-colors"
              style={{
                background: on ? 'var(--bg-hover)' : 'transparent',
                color: on ? 'var(--accent-blue)' : 'var(--text-secondary)',
                border: on ? '1px solid var(--accent-blue)' : '1px solid transparent',
                fontWeight: on ? 600 : 400,
              }}>
              <span>{t.icon}</span>{t.label}
            </button>
          );
        })}
      </div>
      <Suspense fallback={<div className="text-center py-16 text-xs" style={{ color: 'var(--text-muted)' }}>加载中…</div>}>
        <Component />
      </Suspense>
    </div>
  );
}