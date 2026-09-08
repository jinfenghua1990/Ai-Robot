import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { TradingProvider } from './context/TradingContext';

const MarketCenterPage = lazy(() => import('./pages/MarketCenterPage'));
const MarketDashboardPage = lazy(() => import('./pages/MarketDashboardPage'));
const UsStockAnalysisPage = lazy(() => import('./pages/UsStockAnalysisPage'));
const UsBsStrategyPage = lazy(() => import('./pages/UsBsStrategyPage'));
const QualityPage = lazy(() => import('./pages/QualityPage'));
const StrategyCenterPage = lazy(() => import('./pages/StrategyCenterPage'));
const StrategyTrackPage = lazy(() => import('./pages/StrategyTrackPage'));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'));
const YuziCenterPage = lazy(() => import('./pages/YuziCenterPage'));
const HKCenterPage = lazy(() => import('./pages/HKCenterPage'));
const FundWeatherPage = lazy(() => import('./pages/FundWeatherPage'));
const PortfolioPage = lazy(() => import('./pages/portfolio/PortfolioPage'));
const CxmtIpoPage = lazy(() => import('./pages/CxmtIpoPage'));
const UnitreeIpoPage = lazy(() => import('./pages/UnitreeIpoPage'));
const ResearchCenterPage = lazy(() => import('./pages/ResearchCenterPage'));
const StockAnalysisPage = lazy(() => import('./pages/StockAnalysisPage'));
const ReportDetailPage = lazy(() => import('./pages/ReportDetailPage'));
const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const TradingOverviewDetailPage = lazy(() => import('./pages/TradingOverviewDetailPage'));
const QuantVNextPage = lazy(() => import('./pages/QuantVNextPage'));
const USQuantPage = lazy(() => import('./pages/USQuantPage'));
const USDailyDecisionPage = lazy(() => import('./pages/USDailyDecisionPage'));
const UsPremarketPage = lazy(() => import('./pages/UsPremarketPage'));

// 右侧多因子 V2（9001 原汁原味迁移）
const V2Shell = lazy(() => import('./pages/v2/V2Shell'));
const V2OverviewPage = lazy(() => import('./pages/v2/V2OverviewPage'));
const V2SectorsPage = lazy(() => import('./pages/v2/V2SectorsPage'));
const V2PlaceholderPage = lazy(() => import('./pages/v2/V2PlaceholderPage'));

// 9000 原生研究工作区
const ResearchDailyReviewPage = lazy(() => import('./pages/research/ResearchDailyReviewPage'));
const ResearchIntelPage = lazy(() => import('./pages/research/ResearchIntelPage'));
const ResearchSectorsPage = lazy(() => import('./pages/research/ResearchSectorsPage'));
const ResearchRadarPage = lazy(() => import('./pages/research/ResearchRadarPage'));
const ResearchReportsPage = lazy(() => import('./pages/research/ResearchReportsPage'));
const ResearchNotesPage = lazy(() => import('./pages/research/ResearchNotesPage'));
const ResearchSettingsPage = lazy(() => import('./pages/research/ResearchSettingsPage'));
const MarketIntelHub = lazy(() => import('./pages/MarketIntelHub'));
const SectorResearchHub = lazy(() => import('./pages/SectorResearchHub'));
const ResearchWorkspaceHub = lazy(() => import('./pages/ResearchWorkspaceHub'));
const LlmGatewayPage = lazy(() => import('./pages/LlmGatewayPage'));

const StockTrackerPage = lazy(() => import('./pages/StockTrackerPage'));
const SectorRotationPage = lazy(() => import('./pages/SectorRotationPage'));
const IndustryStagePage = lazy(() => import('./pages/IndustryStagePage'));
const WaveAnalysisPage = lazy(() => import('./pages/WaveAnalysisPage'));

// TSP 移植模块（tickflow-stock-panel）
const StrategyScanPage = lazy(() => import('./pages/StrategyScanPage'));
const FactorBacktestPage = lazy(() => import('./pages/FactorBacktestPage'));
const LadderPage = lazy(() => import('./pages/LadderPage'));

// 横盘蓄势策略（A股 · 盘后圈股）
const AHorizontalPage = lazy(() => import('./pages/AHorizontalPage'));
const HorsebackScreenerPage = lazy(() => import('./pages/HorsebackScreenerPage'));
const HorsebackTrackPage = lazy(() => import('./pages/HorsebackTrackPage'));

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

          {/* TSP 移植模块（tickflow-stock-panel）*/}
          <Route path="/a-strategy-scan" element={<StrategyScanPage market="a" />} />
          <Route path="/us-strategy-scan" element={<Navigate to="/us-market?tab=scanner&view=tsp" replace />} />
          <Route path="/a-factor-backtest" element={<FactorBacktestPage market="a" />} />
          <Route path="/us-factor-backtest" element={<Navigate to="/us-market?tab=backtest&mode=factor" replace />} />
          <Route path="/a-ladder" element={<LadderPage />} />
          <Route path="/a-horizontal" element={<AHorizontalPage />} />
          <Route path="/a-horseback" element={<HorsebackScreenerPage />} />
          <Route path="/a-horseback-track" element={<HorsebackTrackPage />} />

          <Route path="/panorama" element={<MarketCenterPage />} />
          <Route path="/market-dashboard" element={<MarketDashboardPage />} />
          <Route path="/us-stock-analysis" element={<UsStockAnalysisPage />} />
          <Route path="/us-bs-strategy" element={<UsBsStrategyPage />} />
          <Route path="/us-premarket" element={<UsPremarketPage />} />
          <Route path="/quality" element={<QualityPage />} />
          <Route path="/quant-vnext" element={<QuantVNextPage />} />
          <Route path="/a-stock/v2" element={<Navigate to="/v2" replace />} />
          <Route path="/strategy-center" element={<StrategyCenterPage />} />
          <Route path="/strategy-track" element={<StrategyTrackPage />} />
          <Route path="/yuzi-center" element={<YuziCenterPage />} />
          <Route path="/yuzi-tracker-20d" element={<Navigate to="/yuzi-center?tab=tracker" replace />} />
          <Route path="/yuzi-tracker" element={<Navigate to="/yuzi-center?tab=tracker" replace />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/trading/sector-rotation" element={<SectorRotationPage />} />
          <Route path="/trading/industry-stage" element={<IndustryStagePage />} />
          <Route path="/stock-analysis" element={<StockAnalysisPage />} />
          <Route path="/focus" element={<Navigate to="/watchlist" replace />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/cxmt-ipo" element={<CxmtIpoPage />} />
          <Route path="/unitree-ipo" element={<UnitreeIpoPage />} />
          <Route path="/research-center" element={<ResearchCenterPage />} />
          <Route path="/report/:reportId" element={<ReportDetailPage />} />
          <Route path="/hk-market" element={<HKCenterPage />} />
          <Route path="/hk-strategy" element={<Navigate to="/hk-market" replace />} />
          <Route path="/us-market" element={<USQuantPage />} />
          <Route path="/us-sector-rotation" element={<Navigate to="/us-market?tab=tracking" replace />} />
          <Route path="/us-daily-decision" element={<USDailyDecisionPage />} />
          <Route path="/fund-weather" element={<FundWeatherPage />} />
          <Route path="/stock/:code" element={<StockCodeRedirect />} />
          <Route path="/wave-analysis" element={<WaveAnalysisPage />} />

          {/* 研究工作区二级页面 */}
          {/* 9000 原生研究工作区 */}
          <Route path="/research/daily-review" element={<MarketIntelHub />} />
          <Route path="/research/intel" element={<MarketIntelHub />} />
          <Route path="/research/sectors" element={<SectorResearchHub />} />
          <Route path="/research/sectors/:key" element={<SectorResearchHub />} />
          <Route path="/research/radar" element={<SectorResearchHub />} />
          <Route path="/research/reports" element={<ResearchWorkspaceHub />} />
          <Route path="/research/notes" element={<ResearchWorkspaceHub />} />
          <Route path="/research/settings" element={<ResearchSettingsPage />} />
          <Route path="/llm-gateway" element={<LlmGatewayPage />} />

          <Route path="/stock-tracker" element={<StockTrackerPage />} />
          <Route path="/trading-overview/:section" element={<TradingOverviewDetailPage />} />
          <Route path="/dsa/alerts" element={<Navigate to="/trading-overview/alerts" replace />} />

          {/* 右侧多因子 V2（9001 原汁原味迁移） */}
          <Route path="/v2" element={<V2Shell />}>
            <Route index element={<Navigate to="/v2/overview" replace />} />
            <Route path="overview" element={<V2OverviewPage />} />
            <Route path="sectors" element={<V2SectorsPage />} />
            <Route path="candidates" element={<V2PlaceholderPage />} />
            <Route path="actions" element={<V2PlaceholderPage />} />
            <Route path="yuzi" element={<V2PlaceholderPage />} />
            <Route path="watchlist" element={<V2PlaceholderPage />} />
            <Route path="holdings" element={<V2PlaceholderPage />} />
            <Route path="analysis" element={<V2PlaceholderPage />} />
            <Route path="validation" element={<V2PlaceholderPage />} />
            <Route path="system" element={<V2PlaceholderPage />} />
            <Route path="collection" element={<V2PlaceholderPage />} />
          </Route>

          <Route path="/" element={<OverviewPage />} />
          <Route path="/watchlist/flow" element={<Navigate to="/watchlist" replace />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="*" element={<Navigate to="/panorama" />} />
        </Route>
        </Routes>
        </Suspense>
        </TradingProvider>
      </ErrorBoundary>
    </BrowserRouter>
  );
}
