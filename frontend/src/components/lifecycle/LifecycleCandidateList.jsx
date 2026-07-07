import { useState } from 'react';
import SignalCard from '../trading/SignalCard';

const SIGNAL_CARD_PROPS = {
  orders: [],
  showWatchBtn: true,
  mode: 'watchlist',
  showMarketState: true,
  showBuyPower: true,
  showAnalysisButton: true,
};

/**
 * ③ 候选龙（≤3只，SignalCard 统一卡片）
 */
export default function LifecycleCandidateList({ candidates = [] }) {
  if (candidates.length === 0) return null;

  return (
    <div>
      <h3 className="text-sm font-bold mb-2 flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
        <span>🔄</span> 候选龙
        <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>（{candidates.length}只）</span>
      </h3>
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        {candidates.map((signal) => (
          <SignalCard
            key={signal.secCode}
            signal={signal}
            {...SIGNAL_CARD_PROPS}
          />
        ))}
      </div>
    </div>
  );
}

/**
 * ④ 热度池（折叠，默认收起）
 */
export function LifecycleHeatPool({ allStocks = [] }) {
  const [open, setOpen] = useState(false);
  if (allStocks.length === 0) return null;

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-3 py-2 rounded-lg border text-sm font-medium transition-colors hover:opacity-80"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
      >
        <span className="flex items-center gap-2">
          <span>📊</span> 热度池
          <span className="text-xs font-normal" style={{ color: 'var(--text-muted)' }}>（{allStocks.length}只）</span>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>{open ? '▲ 收起' : '▼ 展开'}</span>
      </button>
      {open && (
        <div className="mt-2 grid grid-cols-1 md:grid-cols-2 gap-2">
          {allStocks.map((signal) => (
            <SignalCard
              key={signal.secCode}
              signal={signal}
              {...SIGNAL_CARD_PROPS}
            />
          ))}
        </div>
      )}
    </div>
  );
}
