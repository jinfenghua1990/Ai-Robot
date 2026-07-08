import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

const navItems = [
  { path: '/panorama', label: '板块全景', icon: '🔥' },
  { path: '/concept-flow', label: '资金流向', icon: '💸' },
  { path: '/concept-flow-compare', label: '概念资金', icon: '📊' },
  { path: '/index-flow', label: '指数资金', icon: '🇨🇳' },
  { path: '/global-market', label: '港美股', icon: '🌍' },
  { path: '/strategy-center', label: '策略中心', icon: '🎯' },
  { path: '/yuzi-center', label: '游资中心', icon: '🐉' },
  { path: '/yuzi-tracker-20d', label: '20天跟踪', icon: '🧬' },
  { path: '/trading', label: '模拟盘', icon: '📈' },
  { path: '/focus', label: '重点关注', icon: '🎯' },
  { path: '/watchlist', label: '自选股', icon: '⭐' },
];

export default function Layout() {
  const [theme, setTheme] = useState('light');
  const [currentDate, setCurrentDate] = useState('');
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem('airobot-theme') || 'light';
    setTheme(saved);
    document.documentElement.setAttribute('data-theme', saved);
    setCurrentDate(new Date().toLocaleDateString('zh-CN'));
  }, []);

  const toggleTheme = () => {
    const next = theme === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem('airobot-theme', next);
    document.documentElement.setAttribute('data-theme', next);
  };

  return (
    <div className="min-h-screen flex flex-col md:flex-row" style={{ background: 'var(--bg-primary)' }}>
      {/* 移动端顶栏 hamburger */}
      <button
        onClick={() => setNavOpen(!navOpen)}
        className="md:hidden fixed top-2 left-2 z-50 px-2 py-1 rounded-md border"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-secondary)' }}
      >
        {navOpen ? '✕' : '☰'}
      </button>

      {/* 左侧导航（桌面端常驻 / 移动端抽屉） */}
      <nav
        className={`w-48 border-r flex-col ${navOpen ? 'flex' : 'hidden'} md:flex fixed md:static top-0 md:top-auto left-0 z-40 h-full md:h-auto mt-10 md:mt-0`}
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        <div className="px-3 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h1 className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>AIROBOT</h1>
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>市场指挥舱</p>
        </div>
        <div className="flex-1 px-1.5 py-2 space-y-0.5">
          {navItems.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              onClick={() => setNavOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all ${
                  isActive ? 'font-medium' : ''
                }`
              }
              style={({ isActive }) => ({
                background: isActive ? 'var(--bg-hover)' : 'transparent',
                color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
              })}
            >
              <span className="text-sm">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* 移动端遮罩 */}
      {navOpen && (
        <div
          onClick={() => setNavOpen(false)}
          className="md:hidden fixed inset-0 z-30"
          style={{ background: 'rgba(0,0,0,0.4)' }}
        />
      )}

      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col w-full md:w-0">
        {/* 顶栏 */}
        <header className="h-10 border-b flex items-center justify-between pl-12 md:pl-4 pr-2 md:pr-4"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs hidden sm:block" style={{ color: 'var(--text-secondary)' }}>{currentDate}</div>
          <div className="flex items-center gap-1 ml-auto">
            <a
              href={`http://${window.location.hostname}:8788/`}
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex px-2 py-1 rounded-md text-xs border transition-colors items-center gap-1"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
              title={`Hermes控制台 (http://${window.location.hostname}:8788/)`}
            >
              🎛️
            </a>
            <NavLink
              to="/quality"
              className={({ isActive }) =>
                `px-2 py-1 rounded-md text-xs border transition-colors flex items-center gap-1 ${
                  isActive ? 'font-medium' : ''
                }`
              }
              style={({ isActive }) => ({
                borderColor: 'var(--border-color)',
                background: isActive ? 'var(--bg-hover)' : 'transparent',
                color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
              })}
            >
              🛡️
            </NavLink>
            <a
              href="https://finance.sina.com.cn/stock/"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden sm:flex px-2 py-1 rounded-md text-xs border transition-colors items-center gap-1"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
              title="跳转新浪财经行情数据"
            >
              📡
            </a>
            <button
              onClick={toggleTheme}
              className="px-2 py-1 rounded-md text-xs border transition-colors"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              {theme === 'light' ? '🌙' : '☀️'}
            </button>
          </div>
        </header>

        {/* 页面内容 */}
        <main className="flex-1 p-3 md:p-4 overflow-auto" style={{ background: 'var(--bg-primary)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
