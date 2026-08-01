import { lazy, Suspense } from 'react';
import { BrowserRouter, Routes, Route, Navigate, useParams } from 'react-router-dom';
import Layout from './components/Layout';
import ErrorBoundary from './components/ErrorBoundary';
import { TradingProvider } from './context/TradingContext';

const PanoramaPage = lazy(() => import('./pages/PanoramaPage'));
const QualityPage = lazy(() => import('./pages/QualityPage'));
const StrategyCenterPage = lazy(() => import('./pages/StrategyCenterPage'));
const WatchlistPage = lazy(() => import('./pages/WatchlistPage'));
const YuziCenterPage = lazy(() => import('./pages/YuziCenterPage'));
const FocusStocksPage = lazy(() => import('./pages/FocusStocksPage'));
const ConceptFlowPage = lazy(() => import('./pages/ConceptFlowPage'));
const IndexFlowPage = lazy(() => import('./pages/IndexFlowPage'));
const HKCenterPage = lazy(() => import('./pages/HKCenterPage'));
const USCenterPage = lazy(() => import('./pages/USCenterPage'));
const FundWeatherPage = lazy(() => import('./pages/FundWeatherPage'));
const PortfolioPage = lazy(() => import('./pages/portfolio/PortfolioPage'));
const CxmtIpoPage = lazy(() => import('./pages/CxmtIpoPage'));
const UnitreeIpoPage = lazy(() => import('./pages/UnitreeIpoPage'));
const ResearchCenterPage = lazy(() => import('./pages/ResearchCenterPage'));
const StockAnalysisPage = lazy(() => import('./pages/StockAnalysisPage'));
const ReportDetailPage = lazy(() => import('./pages/ReportDetailPage'));
const OverviewPage = lazy(() => import('./pages/OverviewPage'));
const QuantVNextPage = lazy(() => import('./pages/QuantVNextPage'));
const USQuantPage = lazy(() => import('./pages/USQuantPage'));

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

// 盘中实时模块（已原生迁移）
const TodayPage = lazy(() => import('./pages/TodayPage'));

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
          <Route path="/quant-vnext" element={<QuantVNextPage />} />
          <Route path="/a-stock/v2" element={<Navigate to="/v2" replace />} />
          <Route path="/strategy-center" element={<StrategyCenterPage />} />
          <Route path="/yuzi-center" element={<YuziCenterPage />} />
          <Route path="/yuzi-tracker-20d" element={<Navigate to="/yuzi-center?tab=tracker" replace />} />
          <Route path="/yuzi-tracker" element={<Navigate to="/yuzi-center?tab=tracker" replace />} />
          <Route path="/watchlist" element={<WatchlistPage />} />
          <Route path="/stock-analysis" element={<StockAnalysisPage />} />
          {/* 重点关注：独立页面，从自选页拆分 */}
          <Route path="/focus" element={<FocusStocksPage />} />
          <Route path="/portfolio" element={<PortfolioPage />} />
          <Route path="/cxmt-ipo" element={<CxmtIpoPage />} />
          <Route path="/unitree-ipo" element={<UnitreeIpoPage />} />
          <Route path="/research-center" element={<ResearchCenterPage />} />
          <Route path="/report/:reportId" element={<ReportDetailPage />} />
          <Route path="/concept-flow" element={<ConceptFlowPage />} />
          <Route path="/concept-flow-compare" element={<Navigate to="/concept-flow?view=compare" replace />} />
          <Route path="/index-flow" element={<IndexFlowPage />} />
          <Route path="/hk-market" element={<HKCenterPage />} />
          <Route path="/hk-strategy" element={<Navigate to="/hk-market" replace />} />
          <Route path="/us-market" element={<USQuantPage />} />
          <Route path="/fund-weather" element={<FundWeatherPage />} />
          <Route path="/stock/:code" element={<StockCodeRedirect />} />
          <Route path="/wave-analysis" element={<WaveAnalysisPage />} />

          {/* 研究工作区二级页面 */}
          {/* 9000 原生研究工作区 */}
          <Route path="/research/daily-review" element={<ResearchDailyReviewPage />} />
          <Route path="/research/intel" element={<ResearchIntelPage />} />
          <Route path="/research/sectors" element={<ResearchSectorsPage />} />
          <Route path="/research/sectors/:key" element={<ResearchSectorsPage />} />
          <Route path="/research/radar" element={<ResearchRadarPage />} />
          <Route path="/research/reports" element={<ResearchReportsPage />} />
          <Route path="/research/notes" element={<ResearchNotesPage />} />
          <Route path="/research/settings" element={<ResearchSettingsPage />} />

          <Route path="/gostock" element={<Navigate to="/panorama" replace />} />
          <Route path="/stock-tracker" element={<StockTrackerPage />} />

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
