import { useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import HealthStrip from './HealthStrip';
import SystemCheckBanner from './SystemCheckBanner';

// 顶部只负责切换全局上下文；业务功能进入对应上下文的左侧菜单。
const coreNav = [
  { path: '/v2', label: '右侧多因子 V2', icon: '🧠' },
  { path: '/panorama', label: '板块流动', icon: '🔥' },
  { path: '/strategy-center', label: '选股策略中心', icon: '🎯' },
  { path: '/yuzi-center', label: '游资', icon: '🐉' },
  { path: '/quant-vnext', label: '量化动作', icon: '🧬' },
  { path: '/watchlist', label: '自选', icon: '⭐' },
  { path: '/portfolio', label: '持仓', icon: '💼' },
  { path: '/stock-analysis', label: '个股分析', icon: '🔍' },
  { path: '/quality', label: '系统状态', icon: '🛡️' },
];

const topNav = [
  { key: 'a-stock', path: '/panorama', label: 'A股', icon: '🇨🇳' },
  { key: 'hk', path: '/hk-market', label: '港股', icon: '🇭🇰' },
  { key: 'us', path: '/us-market', label: '美股', icon: '🇺🇸' },
  { key: 'system', path: '/quality', label: '系统', icon: '🛡️' },
];

const mainSections = [
  { section: '核心工作台', items: coreNav },
  { section: '原有功能', items: [
    { path: '/', label: '预测总览', icon: '📡' },
    { path: '/trading', label: '交易', icon: '💼' },
    { path: '/research-center', label: '研究中心', icon: '📚' },
    { path: '/focus', label: '重点关注', icon: '🎯' },
    { path: '/cxmt-ipo', label: '长鑫 IPO', icon: '🔬' },
    { path: '/stock-tracker', label: '股票跟踪', icon: '📈' },
  ]},
  { section: '行情与研究', items: [
    { path: '/today', label: '盘中实时', icon: '⚡' },
    { path: '/concept-flow', label: '资金流向', icon: '💸' },
    { path: '/fund-weather', label: '资金气象', icon: '🌦️' },
    { path: '/index-flow', label: '指数资金', icon: '🇨🇳' },
    { path: '/wave-analysis', label: '波浪分析', icon: '🌊' },
  ]},
];

const systemSections = [
  { section: '系统管理', items: [
    { path: '/quality', label: '系统状态', icon: '🛡️' },
    { path: '/quality', label: '数据质量', icon: '🧪' },
    { path: '/today', label: '数据采集', icon: '📡' },
  ]},
];

// 各项目子菜单（仅在 AIROBOT 布局内切换用）
const projectMenus = {
  'a-stock': { title: 'A股', icon: '🇨🇳', sections: mainSections },
  system: { title: '系统', icon: '🛡️', sections: systemSections },
  'quant-vnext': {
    title: '量化 VNext',
    icon: '🧬',
    sections: [
      { section: '新系统', items: [
        { path: '/quant-vnext', label: '量化总览', icon: '🧬' },
        { path: '/quant-vnext?tab=factors', label: '因子注册', icon: '🧮' },
        { path: '/quant-vnext?tab=research', label: '研究验证', icon: '🔬' },
        { path: '/quant-vnext?tab=outcomes', label: '信号结果', icon: '📈' },
      ]},
    ],
  },
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
  gostock: null,
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
  tracker: {
    title: '股票跟踪',
    icon: '📈',
    items: [
      { path: '/stock-tracker', label: '跟踪列表', icon: '📈' },
    ],
  },
  'market-overview': {
    title: '行情全景',
    icon: '🔥',
    items: [
      { path: '/panorama', label: '板块全景', icon: '🔥' },
      { path: '/today', label: '盘中实时', icon: '⚡' },
      { path: '/concept-flow', label: '资金流向', icon: '💸' },
      { path: '/fund-weather', label: '资金气象', icon: '🌦️' },
      { path: '/index-flow', label: '指数资金', icon: '🇨🇳' },
      { path: '/concept-flow?view=compare', label: '概念资金', icon: '📊' },
      { path: '/wave-analysis', label: '波浪分析', icon: '🌊' },
    ],
  },
  yuzi: {
    title: '游资主题',
    icon: '🐉',
    items: [
      { path: '/yuzi-center', label: '游资中心', icon: '🐉' },
      { path: '/yuzi-center?tab=tracker', label: '20天跟踪', icon: '🧬' },
    ],
  },
  global: {
    title: '全球市场',
    icon: '🌐',
    items: [
      { path: '/global-market', label: '全球', icon: '🌐' },
    ],
  },
  hk: {
    title: '港股', icon: '🇭🇰', items: [
      { path: '/hk-market', label: '港股总览', icon: '🇭🇰' },
    ],
  },
  us: {
    title: '美股', icon: '🇺🇸', items: [
      { path: '/us-market', label: '美股总览', icon: '🇺🇸' },
    ],
  },
};

function detectProject(pathname) {
  if (pathname.startsWith('/quality')) return 'system';
  if (pathname.startsWith('/hk-market') || pathname.startsWith('/hk-strategy')) return 'hk';
  if (pathname.startsWith('/us-market')) return 'us';
  if (pathname.startsWith('/v2') || pathname.startsWith('/a-stock/v2') || pathname.startsWith('/panorama') || pathname.startsWith('/strategy-center') || pathname.startsWith('/yuzi-center') || pathname.startsWith('/quant-vnext') || pathname.startsWith('/watchlist') || pathname.startsWith('/portfolio') || pathname.startsWith('/stock-analysis')) return 'a-stock';
  if (pathname.startsWith('/quant-vnext')) return 'quant-vnext';
  // 行情全景一级：板块全景/盘中实时/资金流向/资金气象/指数资金/波浪分析
  if (pathname.startsWith('/panorama') || pathname.startsWith('/today') || pathname.startsWith('/concept-flow') || pathname.startsWith('/fund-weather') || pathname.startsWith('/index-flow') || pathname.startsWith('/wave-analysis')) return 'market-overview';
  // 游资一级
  if (pathname.startsWith('/yuzi-center')) return 'yuzi';
  // 全球一级
  if (pathname.startsWith('/global-market')) return 'global';
  if (pathname.startsWith('/vibe/') || pathname === '/vibe') return 'vibe';
  if (pathname.startsWith('/dsa/') || pathname === '/dsa') return 'dsa';
  if (pathname.startsWith('/gostock/') || pathname === '/gostock') return 'gostock';
  // DSA：预测核心功能打破子系统边界，并入主侧边栏（detectProject 判 main，保留主菜单）
  if (pathname === '/dsa') return 'dsa';
  if (pathname.startsWith('/dsa/')) {
    const dsaInMain = ['/dsa/decision-signals', '/dsa/screening', '/dsa/backtest', '/dsa/alerts', '/dsa/portfolio'];
    return dsaInMain.includes(pathname) ? 'main' : 'dsa';
  }
  if (pathname.startsWith('/ai-agents')) return 'ai-agents';
  if (pathname.startsWith('/stock-tracker')) return 'tracker';
  return 'main';
}

/** 将侧边栏内部路径转为外部独立页URL(新标签页),返回null表示内部路由 */
function externalPageUrl(path) {
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
  const location = useLocation();
  const [activeProject, setActiveProject] = useState(() => detectProject(location.pathname));
  // 所有顶层上下文都保留左侧菜单；页面内容只随菜单切换，不再隐藏导航。
  const isStandalonePage = false;

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
      {!isStandalonePage && (<>
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
      </>)}

      {/* 右侧内容区 */}
      <div className="flex-1 flex flex-col w-full min-w-0 h-full overflow-hidden">
        {/* 顶栏 */}
        <header className={`shrink-0 z-30 h-10 border-b flex items-center justify-between ${isStandalonePage ? 'pl-4' : 'pl-12'} md:pl-4 pr-2 md:pr-4`}
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-1 overflow-x-auto no-scrollbar flex-1 min-w-0">
            {topNav.map(({ key, path, label, icon }) => (
              <NavLink
                key={key}
                to={path}
                onClick={() => setNavOpen(false)}
                className={({ isActive }) => `flex items-center gap-1 px-2.5 py-1.5 rounded-md text-xs transition-colors whitespace-nowrap ${isActive ? 'font-semibold' : ''}`}
                style={({ isActive }) => ({
                  background: isActive ? 'var(--bg-hover)' : 'transparent',
                  color: isActive ? 'var(--accent-blue)' : 'var(--text-secondary)',
                  border: isActive ? '1px solid var(--accent-blue)' : '1px solid transparent',
                })}
              >
                <span>{icon}</span>
                {label}
              </NavLink>
            ))}
          </div>
          {/* 共享数据只保留状态提示，避免与核心导航重复 */}
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
