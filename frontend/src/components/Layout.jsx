import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';

const navItems = [
  { path: '/heatmap', label: '主线热力图', icon: '🔥' },
  { path: '/rotation', label: '板块轮动', icon: '🔄' },
  { path: '/lifecycle', label: '龙头生命周期', icon: '👑' },
  { path: '/money-flow', label: '资金流路径', icon: '💰' },
  { path: '/screener', label: '智能选股', icon: '🎯' },
];

export default function Layout() {
  const [theme, setTheme] = useState('light');
  const [currentDate, setCurrentDate] = useState('');

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
    <div className="min-h-screen flex" style={{ background: 'var(--bg-primary)' }}>
      {/* 左侧导航 */}
      <nav className="w-56 border-r flex flex-col" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="p-4 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h1 className="text-lg font-bold" style={{ color: 'var(--accent-blue)' }}>AIROBOT</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>市场指挥舱</p>
        </div>
        <div className="flex-1 p-2 space-y-1">
          {navItems.map(item => (
            <NavLink
              key={item.path}
              to={item.path}
              className={({ isActive }) =>
                `flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-all ${
                  isActive ? 'font-medium' : ''
                }`
              }
              style={({ isActive }) => ({
                background: isActive ? 'var(--bg-hover)' : 'transparent',
                color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
              })}
            >
              <span className="text-base">{item.icon}</span>
              {item.label}
            </NavLink>
          ))}
        </div>
      </nav>

      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col">
        {/* 顶栏 */}
        <header className="h-14 border-b flex items-center justify-between px-6"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-sm" style={{ color: 'var(--text-secondary)' }}>{currentDate}</div>
          <button
            onClick={toggleTheme}
            className="px-3 py-1.5 rounded-lg text-sm border transition-colors"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            {theme === 'light' ? '🌙 深色' : '☀️ 浅色'}
          </button>
        </header>

        {/* 页面内容 */}
        <main className="flex-1 p-6 overflow-auto" style={{ background: 'var(--bg-primary)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
