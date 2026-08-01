/**
 * 游资中心 — 合并龙虎榜 + 龙头系统 + 大佬持仓
 *
 * Tab 切换三个子页面：
 *  - 龙虎榜：资金动向榜 + 共振信号池 + 游资战绩（原 YuziBillboardPage）
 *  - 龙头系统：主龙头加冕 + 候选龙头 + 板块状态 + 热度池（原 TradingSystemPage）
 *  - 大佬持仓：BUY→SELL 配对,持有几天跑了,赚还是亏（BossHoldingsPage）
 */
import { lazy, Suspense } from 'react';
import { useSearchParams } from 'react-router-dom';

const YuziBillboardPage = lazy(() => import('./YuziBillboardPage'));
const TradingSystemPage = lazy(() => import('./TradingSystemPage'));
const BossHoldingsPage = lazy(() => import('./BossHoldingsPage'));
const YuziLifecycleTrackerPage = lazy(() => import('./YuziLifecycleTrackerPage'));


export default function YuziCenterPage() {
  const [params] = useSearchParams();
  const tab = params.get('tab') || 'billboard';

  return (
    <div className="flex flex-col h-full">
      {/* Tab 内容 */}
      <div className="flex-1 overflow-auto">
        <Suspense
          fallback={
            <div className="flex items-center justify-center h-96">
              <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            </div>
          }
        >
          {tab === 'billboard' && <YuziBillboardPage />}
          {tab === 'leader' && <TradingSystemPage />}
          {tab === 'holdings' && <BossHoldingsPage />}
          {tab === 'tracker' && <YuziLifecycleTrackerPage />}
        </Suspense>
      </div>
    </div>
  );
}
