import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';

// 懒加载页面
const HeatmapPage = () => <div>热力图页面（待实现）</div>;
const RotationPage = () => <div>轮动图页面（待实现）</div>;
const LifecyclePage = () => <div>生命周期页面（待实现）</div>;
const MoneyFlowPage = () => <div>资金流页面（待实现）</div>;
const ScreenerPage = () => <div>选股页面（待实现）</div>;

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/heatmap" element={<HeatmapPage />} />
          <Route path="/rotation" element={<RotationPage />} />
          <Route path="/lifecycle" element={<LifecyclePage />} />
          <Route path="/money-flow" element={<MoneyFlowPage />} />
          <Route path="/screener" element={<ScreenerPage />} />
          <Route path="*" element={<Navigate to="/heatmap" />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
