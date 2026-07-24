// HermesModulePage — 已全量重写，完全脱离 hermes-today
// 每个子模块都是独立的页面组件，直接调用后端 API
import DataCenterOverviewPage from './DataCenterOverviewPage';
import DataCenterMarketPage from './DataCenterMarketPage';
import DataCenterSchedulePage from './DataCenterSchedulePage';
import ThemeReviewPage from './ThemeReviewPage';
import ConsolidatedDataPage from './ConsolidatedDataPage';
import StockMonitorPage from './StockMonitorPage';
import RobotStrategiesPage from './RobotStrategiesPage';
import StrategyPositionPage from './StrategyPositionPage';
import MockTradingPage from './MockTradingPage';

const MODULE_MAP = {
  dc_overview: DataCenterOverviewPage,
  dc_a_share: () => <DataCenterMarketPage market="a_share" />,
  dc_hk: () => <DataCenterMarketPage market="hk" />,
  dc_us: () => <DataCenterMarketPage market="us" />,
  dc_schedule: DataCenterSchedulePage,
  theme_review: ThemeReviewPage,
  consolidated: ConsolidatedDataPage,
  stock_monitor: StockMonitorPage,
  strategies: RobotStrategiesPage,
  strategy_position: StrategyPositionPage,
  mock_trading: MockTradingPage,
};

export default function HermesModulePage({ module }) {
  const Component = MODULE_MAP[module];
  if (!Component) {
    return (
      <div className="p-8 text-sm" style={{ color: 'var(--text-muted)' }}>
        未知模块：{module}
      </div>
    );
  }
  return <Component />;
}
