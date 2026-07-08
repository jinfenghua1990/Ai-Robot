import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { TradingProvider } from './context/TradingContext';

const PanoramaPage = lazy(() => import('./pages/PanoramaPage'));
const QualityPage = lazy(() => import('./pages/QualityPage'));
const StrategyCenterPage = lazy(() => import('./pages/StrategyCenterPage'));
const TradingSystemPage = lazy(() => import('./pages/TradingSystemPage'));
const TradingPage = lazy(() => import('./pages/TradingPage'));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'));
const YuziCenterPage = lazy(() => import('./pages/YuziCenterPage'));
const FocusStocksPage = lazy(() => import('./pages/FocusStocksPage'));
const StockDetailPage = lazy(() => import('./pages/StockDetailPage'));
const YuziBillboardPage = lazy(() => import('./pages/YuziBillboardPage'));
const YuziLifecycleTrackerPage = lazy(() => import('./pages/YuziLifecycleTrackerPage'));
const ConceptFlowPage = lazy(() => import('./pages/ConceptFlowPage'));
const ConceptFlowComparePage = lazy(() => import('./pages/ConceptFlowComparePage'));
const IndexFlowPage = lazy(() => import('./pages/IndexFlowPage'));
const GlobalMarketPage = lazy(() => import('./pages/GlobalMarketPage'));

function PageLoader() {
  return (
    <div className="flex items-center justify-center h-96">
      <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
    </div>
  );
}

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <TradingProvider>
        <Suspense fallback={<PageLoader />}>
        <Routes>
        <Route element={<Layout />}>
          <Route path="/panorama" element={<PanoramaPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/strategy-center" element={<StrategyCenterPage />} />
          <Route path="/yuzi-center" element={<YuziCenterPage />} />
          <Route path="/yuzi-tracker-20d" element={<YuziLifecycleTrackerPage />} />
          <Route path="/yuzi-tracker" element={<YuziLifecycleTrackerPage />} />
          <Route path="/trading" element={<TradingPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/focus" element={<FocusStocksPage />} />
          <Route path="/concept-flow" element={<ConceptFlowPage />} />
          <Route path="/concept-flow-compare" element={<ConceptFlowComparePage />} />
          <Route path="/index-flow" element={<IndexFlowPage />} />
          <Route path="/global-market" element={<GlobalMarketPage />} />
          <Route path="/stock/:code" element={<StockDetailPage />} />
          <Route path="/mx-tools" element={<Navigate to="/watchlist" replace />} />
          {/* 合并后的重定向：龙虎榜+游资系统→游资中心，资金流→自选股 */}
          <Route path="/yuzi-billboard" element={<Navigate to="/yuzi-center" replace />} />
          <Route path="/trading-system" element={<Navigate to="/yuzi-center" replace />} />
          <Route path="/watchlist/flow" element={<Navigate to="/watchlist" replace />} />
          {/* 旧路径重定向到板块全景或策略中心 */}
          <Route path="/heatmap" element={<Navigate to="/panorama" replace />} />
          <Route path="/capital-flow" element={<Navigate to="/panorama" replace />} />
          <Route path="/realtime" element={<Navigate to="/panorama" replace />} />
          <Route path="/portfolio" element={<Navigate to="/panorama" replace />} />
          <Route path="/lifecycle" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v2" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v3" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v4" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-hub" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/screener" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/bs-screener" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/baihu" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/rotation" element={<Navigate to="/panorama" replace />} />
          <Route path="/money-flow" element={<Navigate to="/concept-flow" replace />} />
          <Route path="*" element={<Navigate to="/panorama" />} />
        </Route>
        </Routes>
        </Suspense>
        </TradingProvider>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
