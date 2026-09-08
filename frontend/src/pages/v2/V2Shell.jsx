import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom';
import '../../styles/v2.css';
import { v2api } from '../../api/v2';

const MARKET_TABS = [
  { key: 'cn', label: 'A股' },
  { key: 'hk', label: '港股', hint: '待接入' },
  { key: 'us', label: '美股', hint: '待接入' },
  { key: 'global', label: '全球', hint: '待接入' },
];

const NAV_GROUPS = [
  {
    label: '市场观察',
    items: [
      { page: 'overview', label: '总览', icon: '📊' },
      { page: 'sectors', label: '板块流动', icon: '🔥' },
      { page: 'candidates', label: '选股中心', icon: '🎯' },
    ],
  },
  {
    label: '交易研究',
    items: [
      { page: 'yuzi', label: '游资', icon: '🐉' },
      { page: 'actions', label: '量化动作', icon: '🧬' },
      { page: 'watchlist', label: '自选', icon: '⭐' },
      { page: 'holdings', label: '持仓与交易', icon: '💼' },
      { page: 'analysis', label: '个股研究', icon: '🔍' },
      { page: 'validation', label: '因子验证', icon: '🧪' },
    ],
  },
  {
    label: '系统管理',
    items: [
      { page: 'system', label: '系统状态', icon: '🛡️' },
      { page: 'collection', label: '数据中心', icon: '📡' },
    ],
  },
];

export default function V2Shell() {
  const location = useLocation();
  const navigate = useNavigate();
  const [health, setHealth] = useState(null);
  const [error, setError] = useState(null);

  const currentPage = location.pathname.split('/').pop() || 'overview';

  useEffect(() => {
    v2api.health()
      .then(setHealth)
      .catch((e) => setError(e.message));
  }, []);

  return (
    <div className="v2-scope app-shell">
      <header className="topbar">
        <div className="brand-block" aria-label="Ai-Robot V2">
          <div className="brand-mark">AI</div>
          <div className="brand-copy">
            <div className="eyebrow">AI-ROBOT V2</div>
            <strong>右侧多因子</strong>
          </div>
        </div>

        <div className="market-switch" aria-label="市场切换">
          {MARKET_TABS.map((m) => (
            <button
              key={m.key}
              className={`market-tab ${m.key === 'cn' ? 'active' : ''}`}
              disabled={m.key !== 'cn'}
              type="button"
            >
              {m.label}
              {m.hint && <span>{m.hint}</span>}
            </button>
          ))}
        </div>

        <div className="top-actions">
          <button
            type="button"
            className={`top-system ${currentPage === 'system' ? 'active' : ''}`}
            onClick={() => navigate('/v2/system')}
          >
            🛡️ 系统状态
          </button>
          <button
            type="button"
            className={`top-system ${currentPage === 'collection' ? 'active' : ''}`}
            onClick={() => navigate('/v2/collection')}
          >
            📡 数据中心
          </button>
          <span className="status-chip live">
            <i></i>新程序
          </span>
          <span className="port-chip">9001</span>
          <span className="top-date">研究版</span>
        </div>
      </header>

      <nav className="nav-tabs" aria-label="业务导航">
        {NAV_GROUPS.flatMap((group) => [
          <div key={`g-${group.label}`} className="nav-group-label">
            {group.label}
          </div>,
          ...group.items.map((item) => (
            <NavLink
              key={item.page}
              to={`/v2/${item.page}`}
              className={({ isActive }) =>
                `nav-tab ${isActive ? 'active' : ''}`
              }
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
            </NavLink>
          )),
        ])}
      </nav>

      <div className="status-strip">
        <span className="status-dot"></span>
        <b>{error ? 'V2 数据链路异常' : 'V2 数据链路正常'}</b>
        <span className="strip-divider"></span>
        <span>旧系统 9000 保留</span>
        <span className="strip-divider"></span>
        <span className="danger-text">自动下单关闭</span>
        <span className="strip-spacer"></span>
        <span className="strip-hint">
          {health
            ? `信号交易日 ${health.trade_date} · 股票池 ${health.eligible_universe} 只 · 生产因子 ${health.production_factor_count} 个`
            : '先看市场，再看共振，最后看交易状态'}
        </span>
      </div>

      <main className="content">
        {error ? (
          <div className="notice danger">
            <strong>新 V2 页面读取失败</strong>
            {error}
            <br />
            <span>请先确认 PostgreSQL 和 9000/9001 新程序已启动。</span>
          </div>
        ) : (
          <Outlet />
        )}
      </main>
    </div>
  );
}
