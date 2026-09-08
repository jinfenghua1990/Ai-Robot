import { useNavigate } from 'react-router-dom';
import MarketRankTable from '../components/watchlist/MarketRankTable';

/**
 * 全市场资金流排行页（行情研究 → 二级入口）
 * 独立页面：从 WatchlistPage 迁移，展开态进入，不再折叠挤压自选表格空间
 */
export default function MarketFlowRankPage({ embedded = false }) {
  const navigate = useNavigate();

  return (
    <div className="space-y-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h1 className="text-lg font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <span>🌐</span>
          <span>全市场资金流</span>
        </h1>
        {!embedded && <button
          onClick={() => navigate('/watchlist')}
          className="px-2.5 py-1 rounded-lg border text-xs"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
        >
          ← 返回自选股
        </button>}
      </div>

      {/* 全市场排行表格组件（展开态） */}
      <MarketRankTable defaultOpen={true} />
    </div>
  );
}
