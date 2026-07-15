import { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import HealthStrip from './HealthStrip';
import SystemCheckBanner from './SystemCheckBanner';

// AIROBOT 主菜单 — 底部子系统模块，共享数据入口统一放到顶部栏
const mainSections = [
  { section: '市场分析', items: [
    { path: '/panorama', label: '板块全景', icon: '🔥' },
    { path: '/concept-flow', label: '资金流向', icon: '💸' },
    { path: '/fund-weather', label: '资金气象', icon: '🌦️' },
    { path: '/concept-flow-compare', label: '概念资金', icon: '📊' },
    { path: '/index-flow', label: '指数资金', icon: '🇨🇳' },
    { path: '/hk-market', label: '港股', icon: '🇭🇰' },
    { path: '/us-market', label: '美股', icon: '🇺🇸' },
    { path: '/strategy-center', label: '策略中心', icon: '🎯' },
    { path: '/yuzi-center', label: '游资中心', icon: '🐉' },
    { path: '/yuzi-tracker-20d', label: '20天跟踪', icon: '🧬' },
  ]},
];

// 各项目子菜单（仅在 AIROBOT 布局内切换用）
const projectMenus = {
  vibe: {
    title: 'Vibe-Research',
    icon: '📡',
    sections: [
      { section: '概览', items: [
        { path: '/vibe/intel', label: '资讯雷达', icon: '📡' },
        { path: '/vibe/daily-review', label: '每日复盘', icon: '📰' },
        { path: '/vibe/sectors', label: '板块中心', icon: '🔲' },
        { path: '/vibe/radar', label: '细分板块', icon: '🧩' },
      ]},
      { section: '热门板块', items: [
        { path: '/vibe/sectors/humanoid', label: '人形机器人', icon: '🦾' },
        { path: '/vibe/sectors/ai-computing', label: 'AI 算力', icon: '🧠' },
        { path: '/vibe/sectors/hbm', label: 'HBM', icon: '💾' },
        { path: '/vibe/sectors/cpo', label: '光互联', icon: '💡' },
        { path: '/vibe/sectors/semiconductor', label: '半导体国产替代', icon: '🔬' },
        { path: '/vibe/sectors/business-space', label: '商业航天', icon: '🚀' },
        { path: '/vibe/sectors/innovative-drug', label: '创新药', icon: '💊' },
        { path: '/vibe/sectors/low-altitude', label: '低空经济', icon: '✈️' },
      ]},
      { section: '数据', items: [
        { path: '/vibe/stock-data', label: '个股数据', icon: '🔍' },
      ]},
      { section: '研究', items: [
        { path: '/vibe/my-reports', label: '我的研报', icon: '📄' },
        { path: '/vibe/notes', label: '研究记录', icon: '📝' },
        { path: '/vibe/settings', label: '接入 AI', icon: '⚙️' },
      ]},
    ],
  },
  dsa: {
    title: 'DSA 智能分析',
    icon: '🤖',
    items: [
      { path: '/dsa', label: '智能分析', icon: '🤖' },
      { path: '/dsa/chat', label: 'Agent 问股', icon: '💬' },
      { path: '/dsa/decision-signals', label: '决策信号', icon: '🎯' },
      { path: '/dsa/screening', label: '选股筛选', icon: '🔬' },
      { path: '/dsa/backtest', label: '策略回测', icon: '📊' },
      { path: '/dsa/portfolio', label: '持仓管理', icon: '💼' },
      { path: '/dsa/alerts', label: '实时告警', icon: '🚨' },
      { path: '/dsa/usage', label: 'Token 用量', icon: '🔢' },
      { path: '/dsa/settings', label: 'DSA 设置', icon: '⚙️' },
    ],
  },
  hermes: {
    title: 'Hermes',
    icon: '⚡',
    sections: [
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
    ],
  },
  aihf: {
    title: 'AI Hedge Fund',
    icon: '🦅',
    items: [
      { path: '/aihf', label: '项目主页', icon: '🦅' },
    ],
  },
  tagents: {
    title: 'TradingAgents',
    icon: '🕸️',
    items: [
      { path: '/tagents', label: '项目主页', icon: '🕸️' },
    ],
  },
  gostock: null,
  llm: {
    title: 'LLM 网关',
    icon: '🔌',
    items: [
      { path: '/llm', label: '网关状态', icon: '🔌' },
    ],
  },
  openclaw: {
    title: 'OpenClaw 控制面板',
    icon: '🔧',
    items: [
      { path: '/openclaw', label: '控制面板', icon: '🔧' },
    ],
  },
  'ai-agents': {
    title: '智能体投资团',
    icon: '🤖',
    items: [
      { path: '/ai-agents', label: '投资团总览', icon: '🤖' },
      { path: '/ai-agents/tagents', label: 'TradingAgents', icon: '🕸️' },
      { path: '/ai-agents/aihf', label: 'AI Hedge Fund', icon: '🦅' },
      { path: '/ai-agents/openclaw', label: 'OpenClaw', icon: '🔧' },
    ],
  },
};

const projectKeys = [
  { key: 'main', label: 'AIROBOT', icon: '🔷' },
  { key: 'vibe', label: 'Vibe', icon: '📡' },
  { key: 'dsa', label: 'DSA', icon: '🤖' },
  { key: 'hermes', label: 'Hermes', icon: '⚡' },
  { key: 'llm', label: '网关', icon: '🔌' },
  { key: 'ai-agents', label: '智能体投资团', icon: '🤖' },
];

function detectProject(pathname) {
  if (pathname.startsWith('/vibe/') || pathname === '/vibe') return 'vibe';
  if (pathname.startsWith('/dsa/') || pathname === '/dsa') return 'dsa';
  if (pathname.startsWith('/hermes/') || pathname === '/hermes') return 'hermes';
  if (pathname.startsWith('/aihf/') || pathname === '/aihf') return 'aihf';
  if (pathname.startsWith('/tagents/') || pathname === '/tagents') return 'tagents';
  if (pathname.startsWith('/gostock/') || pathname === '/gostock') return 'gostock';
  if (pathname.startsWith('/llm/') || pathname === '/llm') return 'llm';
  if (pathname.startsWith('/openclaw/') || pathname === '/openclaw') return 'openclaw';
  if (pathname.startsWith('/ai-agents')) return 'ai-agents';
  return 'main';
}

/** 将侧边栏内部路径转为外部独立页URL(新标签页),返回null表示内部路由 */
function externalPageUrl(path) {
  if (path.startsWith('/hermes/')) return `/_hermes/#${path.replace('/hermes', '')}`;
  if (path === '/hermes') return '/_hermes/';
  if (path.startsWith('/dsa'))    return `/_dsa${path.replace('/dsa', '') || '/'}`;
  if (path.startsWith('/vibe'))   return `/_vibe${path.replace('/vibe', '') || '/'}`;
  if (path.startsWith('/aihf'))   return `/_aihf/${path.replace('/aihf', '')}`;
  if (path.startsWith('/openclaw')) return `/_openclaw${path.replace('/openclaw', '') || '/'}`;
  return null;
}

/** 顶部菜单统一走内部路由（点击在当前页内切换到对应模块，左侧栏随之切换） */
function projectExternalUrl(key) {
  return null;
}

export default function Layout() {
  const [theme, setTheme] = useState('light');
  const [currentDate, setCurrentDate] = useState('');
  const [navOpen, setNavOpen] = useState(false);
  const [pushing, setPushing] = useState(false);
  const [pushMsg, setPushMsg] = useState('');
  const [sharedData, setSharedData] = useState({ watchlist: [], portfolio: null, focus: null });
  const location = useLocation();
  const [activeProject, setActiveProject] = useState(() => detectProject(location.pathname));

  useEffect(() => {
    const saved = localStorage.getItem('airobot-theme') || 'light';
    setTheme(saved);
    document.documentElement.setAttribute('data-theme', saved);
    setCurrentDate(new Date().toLocaleDateString('zh-CN'));
  }, []);

  // 研报通知轮询（每30秒检查新报告）
  const [reportNotifCount, setReportNotifCount] = useState(0);
  useEffect(() => {
    const check = async () => {
      try {
        const { ok, data } = await apiFetch('/api/analysis/notifications');
        if (ok) setReportNotifCount(data.unread_count || 0);
      } catch {}
    };
    check();
    const t = setInterval(check, 30000);
    return () => clearInterval(t);
  }, []);

  // 加载共享数据（自选股/持仓/重点关注）
  useEffect(() => {
    const loadShared = async () => {
      try {
        const [wl, pf, fc] = await Promise.all([
          apiFetch('/api/shared/watchlist').then(r => r.ok ? r.data : null),
          apiFetch('/api/shared/portfolio').then(r => r.ok ? r.data : null),
          apiFetch('/api/shared/focus-stocks').then(r => r.ok ? r.data : null),
        ]);
        setSharedData({
          watchlist: wl?.stocks ?? [],
          portfolio: pf ?? null,
          focus: fc ?? null,
        });
      } catch (e) {
        // 静默失败
      }
    };
    loadShared();
    const interval = setInterval(loadShared, 30000); // 每30秒刷新
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setActiveProject(detectProject(location.pathname));
  }, [location.pathname]);

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

  const switchProject = (key) => {
    setActiveProject(key);
    setNavOpen(false);
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
                {sec.items.map(item => (
                  <NavLink
                    key={item.path}
                    to={item.path}
                    onClick={() => setNavOpen(false)}
                    className={({ isActive }) =>
                      `flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all ${isActive ? 'font-medium' : ''}`
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
            </div>
          ))}
        </>
      );
    }

    const project = projectMenus[activeProject];
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
                    <NavLink key={sub.path} to={sub.path}
                      onClick={() => setNavOpen(false)}
                      className={({ isActive }) =>
                        `flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all ${isActive ? 'font-medium' : ''}`
                      }
                      style={({ isActive }) => ({
                        background: isActive ? 'var(--bg-hover)' : 'transparent',
                        color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
                      })}>
                      <span className="text-sm">{sub.icon}</span>
                      {sub.label}
                    </NavLink>
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
          {project.items.map(sub => {
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
              <NavLink key={sub.path} to={sub.path}
                onClick={() => setNavOpen(false)}
                className={({ isActive }) =>
                  `flex items-center gap-2 rounded-md px-2.5 py-1.5 text-xs transition-all ${isActive ? 'font-medium' : ''}`
                }
                style={({ isActive }) => ({
                  background: isActive ? 'var(--bg-hover)' : 'transparent',
                  color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
                })}>
                <span className="text-sm">{sub.icon}</span>
                {sub.label}
              </NavLink>
            );
          })}
        </div>
      </>
    );
  };

  return (
    <div className="h-screen flex flex-col md:flex-row overflow-hidden" style={{ background: 'var(--bg-primary)' }}>
      {/* 移动端顶栏 hamburger */}
      <button
        onClick={() => setNavOpen(!navOpen)}
        className="md:hidden fixed top-2 left-2 z-50 px-2 py-1 rounded-md border"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-secondary)' }}
      >
        {navOpen ? '✕' : '☰'}
      </button>

      {/* 左侧导航 */}
      <nav
        className={`w-48 border-r flex-col ${navOpen ? 'flex' : 'hidden'} md:flex fixed md:relative top-0 left-0 z-40 h-full shrink-0`}
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}
      >
        <div className="px-3 py-2.5 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h1 className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>AIROBOT</h1>
          <p className="text-[10px]" style={{ color: 'var(--text-muted)' }}>市场指挥舱</p>
        </div>
        <div className="flex-1 px-1.5 py-2 space-y-0.5 overflow-auto">
          {renderSidebarContent()}
        </div>
      </nav>

      {/* 移动端遮罩 */}
      {navOpen && (
        <div onClick={() => setNavOpen(false)} className="md:hidden fixed inset-0 z-30" style={{ background: 'rgba(0,0,0,0.4)' }} />
      )}

      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col w-full min-w-0 h-full overflow-hidden">
        {/* 顶栏 */}
        <header className="shrink-0 z-30 h-10 border-b flex items-center justify-between pl-12 md:pl-4 pr-2 md:pr-4"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-1">
            {projectKeys.map(({ key, label, icon }) => {
              const active = activeProject === key;
              const extUrl = projectExternalUrl(key);
              if (extUrl) {
                return (
                  <a key={key} href={extUrl} target="_blank" rel="noopener noreferrer"
                    className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition-colors whitespace-nowrap ${active ? 'font-medium' : ''}`}
                    style={{
                      background: active ? 'var(--bg-hover)' : 'transparent',
                      color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                      border: active ? '1px solid var(--accent-blue)' : '1px solid transparent',
                    }}>
                    <span>{icon}</span>
                    {label}
                    <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>↗</span>
                  </a>
                );
              }
              return (
                <NavLink
                  key={key}
                  to={key === 'main' ? '/panorama' : key === 'ai-agents' ? '/ai-agents' : projectMenus[key]?.items?.[0]?.path || projectMenus[key]?.sections?.[0]?.items?.[0]?.path || '/'}
                  onClick={() => key === 'ai-agents' ? setNavOpen(false) : switchProject(key)}
                  className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-xs transition-colors whitespace-nowrap ${active ? 'font-medium' : ''}`}
                  style={{
                    background: active ? 'var(--bg-hover)' : 'transparent',
                    color: active ? 'var(--accent-blue)' : 'var(--text-secondary)',
                    border: active ? '1px solid var(--accent-blue)' : '1px solid transparent',
                  }}
                >
                  <span>{icon}</span>
                  {label}
                </NavLink>
              );
            })}
          </div>
          {/* 共享数据入口：直接跳转二级页面（带名称） */}
          <div className="flex items-center gap-2 ml-3 text-xs border-l pl-3" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            <NavLink to="/watchlist" className="flex items-center gap-1 hover:opacity-80 no-underline" style={{ color: 'var(--text-secondary)' }}>
              <span>⭐</span><span>自选股</span><span className="font-medium">{sharedData.watchlist.length}</span>
            </NavLink>
            <NavLink to="/portfolio" className="flex items-center gap-1 hover:opacity-80 no-underline" style={{ color: 'var(--text-secondary)' }}>
              <span>💼</span><span>持仓</span>
              <span className="font-medium">
                {(sharedData.portfolio?.total_market_value ?? 0) >= 10000
                  ? `${((sharedData.portfolio?.total_market_value ?? 0) / 10000).toFixed(0)}w`
                  : (sharedData.portfolio?.total_market_value ?? 0).toFixed(0)}
              </span>
            </NavLink>
            <NavLink to="/focus" className="flex items-center gap-1 hover:opacity-80 no-underline" style={{ color: 'var(--text-secondary)' }}>
              <span>🎯</span><span>重点关注</span><span className="font-medium">{sharedData.focus?.count ?? 0}</span>
            </NavLink>
            <NavLink to="/cxmt-ipo" className="flex items-center gap-1 hover:opacity-80 no-underline" style={{ color: 'var(--text-secondary)' }}>
              <span>🔬</span><span>长鑫IPO</span>
            </NavLink>
            <NavLink to="/research-center" className="flex items-center gap-1 hover:opacity-80 no-underline" style={{ color: 'var(--text-secondary)' }}>
              <span>📋</span><span>研报中心</span>
            </NavLink>
          </div>
          <div className="flex items-center gap-1 ml-2">
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

        {/* 页面内容 */}
        <SystemCheckBanner />
        <main className="flex-1 overflow-auto p-3 md:p-4" style={{ background: 'var(--bg-primary)' }}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
