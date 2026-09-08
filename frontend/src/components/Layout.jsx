import { useState, useEffect } from 'react';
import { Link, NavLink, Outlet, useLocation } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import HealthStrip from './HealthStrip';
import SystemCheckBanner from './SystemCheckBanner';
import GlobalWatchlistSearch from './GlobalWatchlistSearch';
import TradeActivityTicker from './trading/TradeActivityTicker';

// 顶部只负责切换全局市场；A股默认进入二波作战，不再先进入功能堆叠页。
const topNav = [
  { key: 'a-stock', path: '/second-wave', label: 'A股', icon: '🇨🇳' },
  { key: 'hk', path: '/hk-market', label: '港股', icon: '🇭🇰' },
  { key: 'us', path: '/us-market', label: '美股', icon: '🇺🇸' },
  { key: 'ipo', path: '/cxmt-ipo', label: 'IPO', icon: '🧾' },
  { key: 'llm', path: '/llm-gateway', label: 'LLM', icon: '🤖' },
];

// A股导航做减法：日常只保留真正形成交易闭环的入口。
// 旧策略/研究代码仍保留，统一下沉到低频工具，避免每天被十几个入口分散注意力。
const mainSections = [
  { section: '核心作战', items: [
    { path: '/second-wave', label: '二波作战', icon: '②' },
    { path: '/portfolio', label: '持仓管理', icon: '💼' },
    { path: '/watchlist', label: '自选观察', icon: '⭐' },
    { path: '/stock-analysis', label: '个股分析', icon: '🔍' },
    { path: '/panorama', label: '市场中心', icon: '📊' },
  ]},
  { section: '低频工具', items: [
    { path: '/trading/sector-rotation', label: '完整板块研究', icon: '🔄' },
    { path: '/strategy-center', label: '旧选股策略', icon: '🎯' },
    { path: '/quant-vnext', label: '量化 / 因子研究', icon: '🧮' },
    { path: '/a-factor-backtest', label: '因子回测', icon: '📉' },
    { path: '/research-center', label: '研报中心', icon: '📚' },
    { path: '/yuzi-center', label: '游资研究', icon: '🐉' },
  ]},
];

// 各市场子菜单。量化 VNext / 游资不再拥有重复的独立侧栏体系，统一归入 A股低频工具。
const projectMenus = {
  'a-stock': { title: 'A股', icon: '🇨🇳', sections: mainSections },
  hk: {
    title: '港股量化', icon: '🇭🇰', sections: [
      { section: '核心工作台', items: [
        { path: '/hk-market?tab=market', label: '行情总览', icon: '📈' },
        { path: '/hk-market?tab=watchlist', label: '自选清单', icon: '⭐' },
        { path: '/hk-market?tab=scores', label: '智能评分', icon: '🧮' },
      ]},
      { section: '策略研究', items: [
        { path: '/hk-market?tab=sectors', label: '行业轮动', icon: '🔥' },
        { path: '/hk-market?tab=south', label: '南向资金', icon: '💰' },
        { path: '/hk-market?tab=strategy', label: '策略扫描', icon: '🎯' },
      ]},
    ],
  },
  us: {
    title: '美股量化', icon: '🇺🇸', sections: [
      { section: '每日决策', items: [
        { path: '/us-daily-decision', label: '每日决策', icon: '🎯' },
        { path: '/us-market?tab=strategy-tracking', label: '策略跟踪（30日）', icon: '📊' },
      ]},
      { section: '我的交易', items: [
        { path: '/us-market?tab=positions', label: '持仓交易', icon: '💼' },
        { path: '/us-market?tab=tracking', label: '重点关注（含板块）', icon: '👀' },
        { path: '/us-stock-analysis', label: '个股分析', icon: '🔍' },
        { path: '/us-market?tab=usmart', label: '自选同步', icon: '⭐' },
      ]},
      { section: '策略研究', items: [
        { path: '/us-market?tab=scanner', label: '策略研究（量化 / TSP）', icon: '🔬' },
        { path: '/us-market?tab=factors', label: '因子与股票池', icon: '🧮' },
        { path: '/us-bs-strategy', label: 'B/S策略', icon: '🅱️' },
        { path: '/us-market?tab=backtest', label: '回测中心', icon: '⏪' },
      ]},
    ],
  },
  ipo: {
    title: 'IPO',
    icon: '🧾',
    sections: [
      { section: 'IPO 专栏', items: [
        { path: '/cxmt-ipo', label: '长鑫 IPO', icon: '🔬' },
        { path: '/unitree-ipo', label: '宇树机器人', icon: '🤖' },
      ]},
    ],
  },
};

function detectProject(pathname) {
  if (pathname === '/' || pathname.startsWith('/second-wave') || pathname.startsWith('/research-center')) return 'a-stock';
  if (pathname.startsWith('/llm-gateway')) return 'llm';
  if (pathname.startsWith('/quality')) return 'system';
  if (pathname.startsWith('/cxmt-ipo')) return 'ipo';
  if (pathname.startsWith('/unitree-ipo')) return 'ipo';
  if (pathname.startsWith('/hk-market') || pathname.startsWith('/hk-strategy')) return 'hk';
  if (pathname.startsWith('/us-')) return 'us';
  if (pathname.startsWith('/a-ladder') || pathname.startsWith('/a-strategy-scan') || pathname.startsWith('/a-factor-backtest') || pathname.startsWith('/a-horizontal') || pathname.startsWith('/a-horseback')) return 'a-stock';
  if (pathname.startsWith('/us-market') || pathname.startsWith('/market-dashboard') || pathname.startsWith('/us-stock-analysis') || pathname.startsWith('/us-bs-strategy') || pathname.startsWith('/us-premarket')) return 'us';
  if (pathname.startsWith('/v2') || pathname.startsWith('/a-stock/v2') || pathname.startsWith('/panorama') || pathname.startsWith('/fund-weather') || pathname.startsWith('/wave-analysis') || pathname.startsWith('/strategy-center') || pathname.startsWith('/yuzi-center') || pathname.startsWith('/quant-vnext') || pathname.startsWith('/watchlist') || pathname.startsWith('/portfolio') || pathname.startsWith('/stock-analysis') || pathname.startsWith('/research/') || pathname.startsWith('/trading/')) return 'a-stock';
  return 'main';
}

/** 将侧边栏内部路径转为外部独立页URL(新标签页),返回null表示内部路由 */
function externalPageUrl(path) {
  if (path.startsWith('/research')) return null;
  return null;
}

/** 侧边栏子项是否高亮：同时比较 pathname 与 ?tab= 参数（默认 tab 视为 market） */
function itemActive(path, loc) {
  const [p, q] = path.split('?');
  if (p === '/us-daily-decision' && (
    loc.pathname === '/market-dashboard'
    || loc.pathname === '/us-premarket'
    || (loc.pathname === '/us-market' && ['dashboard', 'sectors'].includes(new URLSearchParams(loc.search).get('tab')))
  )) return true;
  if (loc.pathname !== p) return false;
  if (p === '/us-daily-decision') return true;
  if (!q) return true;
  const tab = new URLSearchParams(q).get('tab');
  const cur = new URLSearchParams(loc.search).get('tab');
  if (tab === cur) return true;
  if (cur == null) {
    const DEFAULT_TABS = { '/us-market': 'dashboard', '/hk-market': 'market' };
    if (DEFAULT_TABS[p] === tab) return true;
  }
  return false;
}

export default function Layout() {
  const [theme, setTheme] = useState('light');
  const [currentDate, setCurrentDate] = useState('');
  const [navOpen, setNavOpen] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [pushMsg, setPushMsg] = useState('');
  const location = useLocation();
  const activeProject = detectProject(location.pathname);
  const isStockAnalysisPage = location.pathname === '/stock-analysis';
  const isStandalonePage = location.pathname.startsWith('/quality') || location.pathname.startsWith('/llm-gateway');

  useEffect(() => {
    const saved = localStorage.getItem('airobot-theme') || 'light';
    setTheme(saved);
    document.documentElement.setAttribute('data-theme', saved);
    setCurrentDate(new Date().toLocaleDateString('zh-CN'));
  }, []);

  const [reportNotifCount, setReportNotifCount] = useState(0);
  useEffect(() => {
    const check = async () => {
      try {
        const { ok, data } = await apiFetch('/api/analysis/notifications');
        if (ok) setReportNotifCount(data.unread_count || 0);
      } catch {
        // 通知轮询失败不打断主界面；下一轮会自动重试。
      }
    };
    check();
    const t = setInterval(check, 30000);
    return () => clearInterval(t);
  }, []);

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem('airobot-theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };

  const handlePush = async () => {
    setPushing(true);
    setPushMsg('');
    try {
      const { ok, data, error } = await apiFetch('/api/git-push', { method: 'POST' });
      if (ok && data) {
        setPushMsg(data.had_changes ? '✅ 已上传' : '✅ 已同步');
      } else {
        setPushMsg('❌ ' + (error || '失败'));
      }
    } catch {
      setPushMsg('❌ 网络错误');
    } finally {
      setPushing(false);
      setTimeout(() => setPushMsg(''), 3000);
    }
  };

  const renderSidebarContent = () => {
    if (activeProject === 'main') {
      return (
        <>
          {mainSections.map((sec, idx) => (
            <div key={idx} className={`${idx > 0 ? 'mt-3 pt-2 border-t' : ''}`} style={{ borderColor: 'var(--border-color)' }}>
              <div className="px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                {sec.section}
              </div>
              <div className="space-y-0.5">
                {sec.items.map(item => {
                  const active = itemActive(item.path, location);
                  return (
                  <Link
                    key={item.path}
                    to={item.path}
                    onClick={() => setNavOpen(false)}
                    aria-current={active ? 'page' : undefined}
                    className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all"
                    style={{
                      background: active ? 'var(--bg-hover)' : 'transparent',
                      color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                      fontWeight: active ? 600 : 400,
                    }}
                  >
                    <span className="text-sm">{item.icon}</span>
                    {item.label}
                  </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      );
    }

    const project = projectMenus[activeProject];
    if (!project) {
      return <div className="px-2.5 py-4 text-xs text-center" style={{ color: 'var(--text-muted)' }}>选择模块查看详情</div>;
    }
    if (project.sections) {
      return (
        <>
          <div className="px-2.5 py-2 text-xs font-bold" style={{ color: 'var(--accent-blue)' }}>
            <span className="mr-1">{project.icon}</span>{project.title}
          </div>
          {project.sections.map((sec, idx) => (
            <div key={idx} className={`${idx > 0 ? 'mt-2 pt-2 border-t' : ''}`} style={{ borderColor: 'var(--border-color)' }}>
              <div className="px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                {sec.section}
              </div>
              <div className="space-y-0.5">
                {sec.items.map(sub => {
                  const ext = externalPageUrl(sub.path);
                  const active = itemActive(sub.path, location);
                  if (ext) {
                    return (
                      <a key={sub.path} href={ext} target="_blank" rel="noopener noreferrer"
                        className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all hover:opacity-80"
                        style={{ color: 'var(--text-secondary)' }}
                        onClick={() => setNavOpen(false)}>
                        <span className="text-sm">{sub.icon}</span>
                        {sub.label}
                        <span className="ml-auto text-[9px]" style={{ color: 'var(--text-muted)' }}>↗</span>
                      </a>
                    );
                  }
                  return (
                    <Link key={sub.path} to={sub.path}
                      onClick={() => setNavOpen(false)}
                      aria-current={active ? 'page' : undefined}
                      className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all"
                      style={{
                        background: active ? 'var(--bg-hover)' : 'transparent',
                        color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                        fontWeight: active ? 600 : 400,
                      }}>
                      <span className="text-sm">{sub.icon}</span>
                      {sub.label}
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </>
      );
    }

    return (
      <>
        <div className="px-2.5 py-2 text-xs font-bold" style={{ color: 'var(--accent-blue)' }}>
          <span className="mr-1">{project.icon}</span>{project.title}
        </div>
        <div className="space-y-0.5">
          {(project.items || []).map(sub => {
            const active = itemActive(sub.path, location);
            const ext = externalPageUrl(sub.path);
            if (ext) {
              return (
                <a key={sub.path} href={ext} target="_blank" rel="noopener noreferrer"
                  className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all hover:opacity-80"
                  style={{ color: 'var(--text-secondary)' }}
                  onClick={() => setNavOpen(false)}>
                  <span className="text-sm">{sub.icon}</span>
                  {sub.label}
                  <span className="ml-auto text-[9px]" style={{ color: 'var(--text-muted)' }}>↗</span>
                </a>
              );
            }
            return (
              <Link key={sub.path} to={sub.path}
                onClick={() => setNavOpen(false)}
                aria-current={active ? 'page' : undefined}
                className="flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all"
                style={{
                  background: active ? 'var(--bg-hover)' : 'transparent',
                  color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  fontWeight: active ? 600 : 400,
                }}>
                <span className="text-sm">{sub.icon}</span>
                {sub.label}
              </Link>
            );
          })}
        </div>
      </>
    );
  };

  return (
    <div className="h-screen flex flex-col md:flex-row overflow-hidden" style={{ background: 'var(--bg-primary)' }}>
      {!isStandalonePage && (<>
      <button
        onClick={() => setNavOpen(!navOpen)}
        className="md:hidden fixed top-2 left-2 z-50 px-2 py-1 rounded-md border"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-secondary)' }}
      >
        {navOpen ? '✕' : '☰'}
      </button>

      <nav
        className={`w-48 border-r flex-col ${navOpen ? 'flex' : 'hidden'} md:flex fixed md:relative top-0 left-0 z-40 h-full shrink-0`}
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        <div className="px-3 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h1 className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>AIROBOT</h1>
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>二波龙头作战系统</p>
        </div>
        <div className="flex-1 px-1.5 py-2 space-y-0.5 overflow-auto">
          {renderSidebarContent()}
        </div>
      </nav>

      {navOpen && (
        <div onClick={() => setNavOpen(false)} className="md:hidden fixed inset-0 z-30" style={{ background: 'rgba(0,0,0,0.4)' }} />
      )}
      </>)}

      <div className="flex-1 flex flex-col w-full min-w-0 h-full overflow-hidden">
        <header className={`shrink-0 z-50 h-10 border-b flex items-center justify-between ${isStandalonePage ? 'pl-4' : 'pl-12'} md:pl-4 pr-2 md:pr-4`}
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-1 flex-1 min-w-0">
            <div className="flex items-center gap-1 overflow-x-auto no-scrollbar flex-1 min-w-0">
              {topNav.map(({ key, path, label, icon }) => {
                const active = detectProject(location.pathname) === key;
                const target = key === 'llm'
                  ? 'http://127.0.0.1:9002/llm-gateway'
                  : (window.location.port === '9002' ? `http://127.0.0.1:9000${path}` : path);
                return (
                <a
                  key={key}
                  href={target}
                  onClick={() => setNavOpen(false)}
                  aria-current={active ? 'page' : undefined}
                  className={`flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs transition-colors whitespace-nowrap ${active ? 'font-semibold' : ''}`}
                  style={{
                    background: active ? 'var(--bg-hover)' : 'transparent',
                    color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                    border: active ? '1px solid var(--accent-blue)' : '1px solid transparent',
                  }}
                >
                  <span>{icon}</span>
                  {label}
                </a>
                );
              })}
            </div>
            <TradeActivityTicker />
          </div>
          <div className="flex items-center gap-1 ml-2">
            <GlobalWatchlistSearch />
            <NavLink to="/research-center" className="relative flex items-center gap-1 px-1.5 py-1 rounded-md text-xs hover:opacity-80 no-underline"
              style={{ color: reportNotifCount > 0 ? '#ef4444' : 'var(--text-secondary)' }}>
              <span>🛎️</span>
              {reportNotifCount > 0 && (
                <span className="absolute -top-1 -right-1 text-[9px] font-bold px-1 py-0.5 rounded-full min-w-[16px] text-center"
                  style={{ background: '#ef4444', color: '#fff', lineHeight: '1' }}>
                  {reportNotifCount > 9 ? '9+' : reportNotifCount}
                </span>
              )}
            </NavLink>
            <HealthStrip />
            <div className="text-xs hidden sm:block mr-2" style={{ color: 'var(--text-secondary)' }}>{currentDate}</div>
            <a
              href="https://dapanyuntu.com"
              target="_blank"
              rel="noopener noreferrer"
              className="flex px-2 py-1 rounded-md text-xs border transition-colors items-center gap-1"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
              title="跳转大盘云图"
            >
              <span>🗺️</span><span className="hidden sm:inline">云图</span>
            </a>
            <a
              href="https://finance.sina.com.cn/stock/"
              target="_blank"
              rel="noopener noreferrer"
              className="flex px-2 py-1 rounded-md text-xs border transition-colors items-center gap-1"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
              title="跳转新浪财经行情数据"
            >
              <span>📡</span><span className="hidden sm:inline">新浪</span>
            </a>
            <button
              onClick={handlePush}
              disabled={pushing}
              className="px-2 py-1 rounded-md text-xs border transition-colors flex items-center gap-1"
              style={{
                borderColor: pushMsg.startsWith('✅') ? 'var(--accent-green, #22c55e)' : 'var(--border-color)',
                color: pushMsg.startsWith('✅') ? 'var(--accent-green, #22c55e)' : 'var(--text-secondary)',
                opacity: pushing ? 0.6 : 1,
                cursor: pushing ? 'wait' : 'pointer',
              }}
              title="一键上传代码到 GitHub"
            >
              {pushing ? '⏳' : '📤'} {pushMsg || '上传'}
            </button>
            <button
              onClick={toggleTheme}
              className="px-2 py-1 rounded-md text-xs border transition-colors flex items-center gap-1"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              <span>{theme === 'light' ? '🌙' : '☀️'}</span>
              <span className="hidden sm:inline">{theme === 'light' ? '黑夜' : '白天'}</span>
            </button>
          </div>
        </header>

        <SystemCheckBanner />
        <main className={`flex-1 overflow-auto ${isStockAnalysisPage ? 'p-0' : 'p-3 md:p-4'}`} style={{ background: 'var(--bg-primary)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
