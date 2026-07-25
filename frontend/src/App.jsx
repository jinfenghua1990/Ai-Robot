import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
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
const YuziBillboardPage = lazy(() => import('./pages/YuziBillboardPage'));
const YuziLifecycleTrackerPage = lazy(() => import('./pages/YuziLifecycleTrackerPage'));
const ConceptFlowPage = lazy(() => import('./pages/ConceptFlowPage'));
const ConceptFlowComparePage = lazy(() => import('./pages/ConceptFlowComparePage'));
const IndexFlowPage = lazy(() => import('./pages/IndexFlowPage'));
const GlobalMarketPage = lazy(() => import('./pages/GlobalMarketPage'));
const HKMarketPage = lazy(() => import('./pages/HKMarketPage'));
const USMarketPage = lazy(() => import('./pages/USMarketPage'));
const FundWeatherPage = lazy(() => import('./pages/FundWeatherPage'));
const PortfolioPage = lazy(() => import('./pages/portfolio/PortfolioPage'));
const CxmtIpoPage = lazy(() => import('./pages/CxmtIpoPage'));
const ResearchCenterPage = lazy(() => import('./pages/ResearchCenterPage'));
const StockAnalysisPage = lazy(() => import('./pages/StockAnalysisPage'));
const ReportDetailPage = lazy(() => import('./pages/ReportDetailPage'));

// Vibe-Research 二级页面
const VibeDailyReviewPage = lazy(() => import('./pages/vibe/VibeDailyReviewPage'));
const VibeIntelPage = lazy(() => import('./pages/vibe/VibeIntelPage'));
const VibeSectorsPage = lazy(() => import('./pages/vibe/VibeSectorsPage'));
const VibeRadarPage = lazy(() => import('./pages/vibe/VibeRadarPage'));
const VibeStockDataPage = lazy(() => import('./pages/vibe/VibeStockDataPage'));
const VibeWatchlistPage = lazy(() => import('./pages/vibe/VibeWatchlistPage'));
const VibePortfolioPage = lazy(() => import('./pages/vibe/VibePortfolioPage'));
const VibeMyReportsPage = lazy(() => import('./pages/vibe/VibeMyReportsPage'));
const VibeNotesPage = lazy(() => import('./pages/vibe/VibeNotesPage'));
const VibeSettingsPage = lazy(() => import('./pages/vibe/VibeSettingsPage'));

// daily_stock_analysis (DSA) 二级页面
const DSAHomePage = lazy(() => import('./pages/dsa/DSAHomePage'));
const DSAChatPage = lazy(() => import('./pages/dsa/DSAChatPage'));
const DSAPortfolioPage = lazy(() => import('./pages/dsa/DSAPortfolioPage'));
const DSADecisionSignalsPage = lazy(() => import('./pages/dsa/DSADecisionSignalsPage'));
const DSAScreeningPage = lazy(() => import('./pages/dsa/DSAScreeningPage'));
const DSABacktestPage = lazy(() => import('./pages/dsa/DSABacktestPage'));
const DSAAlertsPage = lazy(() => import('./pages/dsa/DSAAlertsPage'));
const DSATokenUsagePage = lazy(() => import('./pages/dsa/DSATokenUsagePage'));
const DSASettingsPage = lazy(() => import('./pages/dsa/DSASettingsPage'));

// 盘中实时模块（已原生迁移）
const TodayPage = lazy(() => import('./pages/TodayPage'));

// 股票分析套件
const AIHFHomePage = lazy(() => import('./pages/aihf/AIHFHomePage'));
const OpenClawPage = lazy(() => import('./pages/openclaw/OpenClawPage'));
const TAgentsHomePage = lazy(() => import('./pages/tagents/TAgentsHomePage'));

const AIAgentTeamPage = lazy(() => import('./pages/AIAgentTeamPage'));
const StockTrackerPage = lazy(() => import('./pages/StockTrackerPage'));
const WaveAnalysisPage = lazy(() => import('./pages/WaveAnalysisPage'));

import PageLoader from './components/PageLoader';

function StockCodeRedirect() {
  const { code } = useParams();
  return <Navigate to={`/stock-analysis?code=${code}`} replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <ErrorBoundary>
        <TradingProvider>
        <Suspense fallback={<PageLoader />}>
        <Routes>
        <Route element={<Layout />}>

          <Route path="/today" element={<TodayPage />} />
          <Route path="/panorama" element={<PanoramaPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/strategy-center" element={<StrategyCenterPage />} />
          <Route path="/yuzi-center" element={<YuziCenterPage />} />
          <Route path="/yuzi-tracker-20d" element={<YuziLifecycleTrackerPage />} />
          <Route path="/yuzi-tracker" element={<YuziLifecycleTrackerPage />} />
          <Route path="/trading" element={<TradingPage />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/stock-analysis" element={<StockAnalysisPage />} />
          <Route path="/focus" element={<FocusStocksPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/cxmt-ipo" element={<CxmtIpoPage />} />
          <Route path="/research-center" element={<ResearchCenterPage />} />
          <Route path="/report/:reportId" element={<ReportDetailPage />} />
          <Route path="/concept-flow" element={<ConceptFlowPage />} />
          <Route path="/concept-flow-compare" element={<ConceptFlowComparePage />} />
          <Route path="/index-flow" element={<IndexFlowPage />} />
          <Route path="/global-market" element={<GlobalMarketPage />} />
          <Route path="/hk-market" element={<HKMarketPage />} />
          <Route path="/hk-strategy" element={<Navigate to="/hk-market" replace />} />
          <Route path="/us-market" element={<USMarketPage />} />
          <Route path="/fund-weather" element={<FundWeatherPage />} />
          <Route path="/stock/:code" element={<StockCodeRedirect />} />
          <Route path="/wave-analysis" element={<WaveAnalysisPage />} />

          {/* Vibe-Research 二级页面 */}
          <Route path="/vibe/daily-review" element={<VibeDailyReviewPage />} />
          <Route path="/vibe/intel" element={<VibeIntelPage />} />
          <Route path="/vibe/sectors" element={<VibeSectorsPage />} />
          <Route path="/vibe/sectors/:key" element={<VibeSectorsPage />} />
          <Route path="/vibe/radar" element={<VibeRadarPage />} />
          <Route path="/vibe/stock-data" element={<VibeStockDataPage />} />
          <Route path="/vibe/watchlist" element={<VibeWatchlistPage />} />
          <Route path="/vibe/portfolio" element={<VibePortfolioPage />} />
          <Route path="/vibe/my-reports" element={<VibeMyReportsPage />} />
          <Route path="/vibe/notes" element={<VibeNotesPage />} />
          <Route path="/vibe/settings" element={<VibeSettingsPage />} />

          {/* daily_stock_analysis (DSA) 二级页面 */}
          <Route path="/dsa" element={<DSAHomePage />} />
          <Route path="/dsa/" element={<DSAHomePage />} />
          <Route path="/dsa/chat" element={<DSAChatPage />} />
          <Route path="/dsa/portfolio" element={<DSAPortfolioPage />} />
          <Route path="/dsa/decision-signals" element={<DSADecisionSignalsPage />} />
          <Route path="/dsa/screening" element={<DSAScreeningPage />} />
          <Route path="/dsa/backtest" element={<DSABacktestPage />} />
          <Route path="/dsa/alerts" element={<DSAAlertsPage />} />
          <Route path="/dsa/usage" element={<DSATokenUsagePage />} />
          <Route path="/dsa/settings" element={<DSASettingsPage />} />

          {/* 股票分析套件二级页面 */}
          <Route path="/aihf" element={<AIHFHomePage />} />
          <Route path="/openclaw" element={<OpenClawPage />} />
          <Route path="/openclaw/" element={<OpenClawPage />} />
          <Route path="/aihf/" element={<AIHFHomePage />} />
          <Route path="/tagents" element={<TAgentsHomePage />} />
          <Route path="/tagents/" element={<TAgentsHomePage />} />
          <Route path="/gostock" element={<Navigate to="/panorama" replace />} />
          <Route path="/ai-agents" element={<AIAgentTeamPage />} />
          <Route path="/ai-agents/:tab" element={<AIAgentTeamPage />} />
          <Route path="/stock-tracker" element={<StockTrackerPage />} />

          <Route path="/" element={<Navigate to="/ai-agents" replace />} />
          <Route path="/mx-tools" element={<Navigate to="/watchlist" replace />} />
          <Route path="/yuzi-billboard" element={<Navigate to="/yuzi-center" replace />} />
          <Route path="/trading-system" element={<Navigate to="/yuzi-center" replace />} />
          <Route path="/watchlist/flow" element={<Navigate to="/watchlist" replace />} />
          <Route path="/heatmap" element={<Navigate to="/panorama" replace />} />
          <Route path="/capital-flow" element={<Navigate to="/panorama" replace />} />
          <Route path="/realtime" element={<Navigate to="/panorama" replace />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/lifecycle" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v2" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v3" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-v4" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/lifecycle-hub" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/screener" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/bs-screener" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/baihu" element={<Navigate to="/strategy-center" replace />} />
          <Route path="/resonance" element={<Navigate to="/strategy-center" replace />} />
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