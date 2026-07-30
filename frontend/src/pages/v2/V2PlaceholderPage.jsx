import { useLocation } from 'react-router-dom';

const NAMES = {
  candidates: '选股中心',
  actions: '量化动作',
  yuzi: '游资',
  watchlist: '自选',
  holdings: '持仓与交易',
  analysis: '个股研究',
  validation: '因子验证',
  system: '系统状态',
  collection: '数据中心',
};

export default function V2PlaceholderPage() {
  const location = useLocation();
  const page = location.pathname.split('/').pop();
  const name = NAMES[page] || page;
  return (
    <div className="card" style={{ padding: 48, textAlign: 'center' }}>
      <h2>{name}</h2>
      <p className="muted">该页面已纳入 V2 迁移框架，UI 正在复刻中。</p>
      <p className="muted">当前可先访问：总览、板块流动。</p>
    </div>
  );
}
