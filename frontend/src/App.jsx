import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import Layout from './components/Layout';
import HeatmapPage from './pages/HeatmapPage';
import RotationPage from './pages/RotationPage';
import LifecyclePage from './pages/LifecyclePage';
import MoneyFlowPage from './pages/MoneyFlowPage';
import ScreenerPage from './pages/ScreenerPage';

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
