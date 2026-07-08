import { useState, useEffect } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { apiFetch } from '../utils/request';

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
  { section: 'Vibe-Research', items: [
    { path: '/vibe/intel', label: '资讯雷达', icon: '📡' },
    { path: '/vibe/daily-review', label: '每日复盘', icon: '📰' },
    { path: '/vibe/sectors', label: '板块中心', icon: '🔲' },
    { path: '/vibe/stock-data', label: '个股数据', icon: '🔍' },
    { path: '/vibe/watchlist', label: '自选股', icon: '📋' },
    { path: '/vibe/portfolio', label: '我的持仓', icon: '💼' },
    { path: '/vibe/my-reports', label: '我的研报', icon: '📄' },
    { path: '/vibe/notes', label: '研究记录', icon: '📝' },
    { path: '/vibe/settings', label: '接入 AI', icon: '⚙️' },
  ]},
  { section: 'DSA 智能分析', items: [
    { path: '/dsa', label: '智能分析', icon: '🤖' },
    { path: '/dsa/chat', label: 'Agent 问股', icon: '💬' },
    { path: '/dsa/decision-signals', label: '决策信号', icon: '🎯' },
    { path: '/dsa/screening', label: '选股筛选', icon: '🔬' },
    { path: '/dsa/backtest', label: '策略回测', icon: '📊' },
    { path: '/dsa/portfolio', label: '持仓管理', icon: '💼' },
    { path: '/dsa/alerts', label: '实时告警', icon: '🚨' },
    { path: '/dsa/usage', label: 'Token 用量', icon: '🔢' },
    { path: '/dsa/settings', label: 'DSA 设置', icon: '⚙️' },
  ]},
  { section: 'Hermes A股', items: [
    { path: '/hermes/today', label: '盘中实时', icon: '⚡' },
    { path: '/hermes/main-hub', label: '主控中心', icon: '🎛️' },
    { path: '/hermes/theme-review', label: '题材复盘', icon: '🔥' },
    { path: '/hermes/wave-analysis', label: '波浪分析', icon: '🌊' },
    { path: '/hermes/stock-monitor', label: '选股持仓', icon: '🎯' },
    { path: '/hermes/stock-analysis', label: '选股分析', icon: '🔍' },
    { path: '/hermes/strategies', label: '策略信号', icon: '🤖' },
    { path: '/hermes/screener', label: '智能选股', icon: '🔬' },
    { path: '/hermes/mock-trading', label: '模拟交易', icon: '📈' },
    { path: '/hermes/strategy-position', label: '波段信号', icon: '波段' },
  ]},
  { section: 'Hermes 港美股', items: [
    { path: '/hermes/us-market', label: '美股总览', icon: '🇺🇸' },
    { path: '/hermes/us-monitor', label: '美股监控', icon: '📡' },
    { path: '/hermes/us-analysis', label: '美股分析', icon: '📊' },
    { path: '/hermes/us-strategies', label: '美股策略', icon: '🎯' },
    { path: '/hermes/us-trading', label: '美股交易', icon: '💹' },
    { path: '/hermes/hk-market', label: '港股总览', icon: '🇭🇰' },
    { path: '/hermes/hk-monitor', label: '港股监控', icon: '📡' },
    { path: '/hermes/hk-analysis', label: '港股分析', icon: '📊' },
    { path: '/hermes/hk-strategies', label: '港股策略', icon: '🎯' },
    { path: '/hermes/hk-trading', label: '港股交易', icon: '💹' },
  ]},
];

export default function Layout() {
  const [theme, setTheme] = useState('light');
  const [currentDate, setCurrentDate] = useState('');
  const [navOpen, setNavOpen] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [pushMsg, setPushMsg] = useState('');

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
    } catch (e) {
      setPushMsg('❌ 网络错误');
    } finally {
      setPushing(false);
      setTimeout(() => setPushMsg(''), 3000);
    }
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
        <div className="flex-1 px-1.5 py-2 space-y-0.5 overflow-auto">
          {navItems.map((item, idx) => {
            if (item.section) {
              return (
                <div key={idx} className="mt-2 pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
                  <div className="px-2.5 py-1 text-[10px] font-medium uppercase tracking-wider" style={{ color: 'var(--text-muted)' }}>
                    {item.section}
                  </div>
                  <div className="space-y-0.5">
                    {item.items.map(sub => (
                      <NavLink
                        key={sub.path}
                        to={sub.path}
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
                        <span className="text-sm">{sub.icon}</span>
                        {sub.label}
                      </NavLink>
                    ))}
                  </div>
                </div>
              );
            }
            return (
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
            );
          })}
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
