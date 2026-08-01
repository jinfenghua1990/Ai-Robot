import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import TradeModal from '../components/trading/TradeModal';
import { useTrading } from '../context/TradingContext';
import { TOAST_DURATION } from '../utils/constants';
import { IPO_PROJECTS } from '../data/ipoProjects';
import { IpoTimeline, IpoListingCard, computeIpoProgress } from '../components/IpoTracker';

/* ─── 宇树科技IPO关联标的分类（供应链/概念梳理） ───
   说明：标的名单为公开供应链关联关系梳理，角色描述基于公开资料；
   评级/具体估值数字为「待补充」占位，正式结论请以招股说明书及实盘核实为准。
   ★★★ 强烈推荐 — 供应链核心环节、关联度最高
   ★★  可关注   — 间接受益或环节弹性有限
   ★   谨慎     — 关联度弱、概念属性偏主题
*/
const ASSESSMENT = {
  BUY: { label: '★★★ 可买', color: '#1D9E75', bg: 'rgba(29,158,117,0.1)', desc: '强关联' },
  WATCH: { label: '★★ 可关注', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)', desc: '持续追踪' },
  CAUTIOUS: { label: '★ 谨慎', color: '#E24B4A', bg: 'rgba(226,75,74,0.1)', desc: '主题为主' },
};
const CATEGORIES = [
  {
    key: 'reducer',
    label: '减速器/传动',
    icon: '⚙️',
    color: '#a855f7',
    desc: '机器人关节核心，谐波/行星减速器（国产替代主力环节）',
    assessment: `减速器是人形机器人用量最大、价值量最高的核心零部件之一，单台人形机器人需 30+ 个减速器。
    谐波减速器壁垒高，绿的谐波为国内龙头；行星减速器环节中大力德、双环传动具备规模与成本优势；
    灵巧手微传动由兆威机电等微型传动厂商覆盖。本环节与宇树本体出货量直接挂钩，关联度最高。`,
    stocks: [
      { code: '688017', name: '绿的谐波', role: '谐波减速器龙头·国产替代核心', rec: 'BUY' },
      { code: '002896', name: '中大力德', role: '行星减速器·人形机器人用量弹性大', rec: 'BUY' },
      { code: '002472', name: '双环传动', role: '齿轮/ RV 减速器·规模优势', rec: 'BUY' },
      { code: '003021', name: '兆威机电', role: '微型传动·灵巧手关节', rec: 'WATCH' },
    ],
  },
  {
    key: 'motor',
    label: '电机/伺服/运控',
    icon: '🔌',
    color: '#3b82f6',
    desc: '关节执行器核心：无框力矩电机、伺服驱动、运动控制',
    assessment: `关节执行器由「无框力矩电机 + 谐波减速器 + 编码器 + 驱动器」构成，是价值量第二高的环节。
    鸣志电器步进/无刷电机、汇川技术伺服与运动控制、雷赛智能运动控制卡、步科股份伺服电机均为主流供应商；
    江苏雷利布局线性执行器。关联度随宇树量产节拍提升而增强。`,
    stocks: [
      { code: '603728', name: '鸣志电器', role: '步进/无刷电机·关节执行器', rec: 'BUY' },
      { code: '300124', name: '汇川技术', role: '伺服/运动控制·工业自动化龙头', rec: 'BUY' },
      { code: '300660', name: '江苏雷利', role: '线性执行器/空心杯电机', rec: 'WATCH' },
      { code: '002979', name: '雷赛智能', role: '运动控制卡/步进系统', rec: 'WATCH' },
      { code: '688160', name: '步科股份', role: '伺服电机/驱动器·机器人应用', rec: 'WATCH' },
    ],
  },
  {
    key: 'screw',
    label: '丝杠/结构件',
    icon: '🔩',
    color: '#f97316',
    desc: '行星滚柱丝杠、轴承、结构件（量产降本关键）',
    assessment: `线性执行器（行星滚柱丝杠）是线性关节核心，工艺壁垒高、国产替代空间大；
    北特科技、贝斯特布局行星滚柱丝杠；五洲新春轴承+丝杠；拓普集团、三花智控具备总成与热管理/执行器能力，
    若进入宇树总成供应链则弹性显著。结构件环节单价低、需靠规模。`,
    stocks: [
      { code: '603009', name: '北特科技', role: '行星滚柱丝杠·线性关节', rec: 'BUY' },
      { code: '300580', name: '贝斯特', role: '丝杠/线性执行器零部件', rec: 'WATCH' },
      { code: '603667', name: '五洲新春', role: '轴承/丝杠·传动部件', rec: 'WATCH' },
      { code: '601689', name: '拓普集团', role: '执行器总成·汽零协同', rec: 'WATCH' },
      { code: '002050', name: '三花智控', role: '热管理/执行器·机电协同', rec: 'WATCH' },
    ],
  },
  {
    key: 'sensor',
    label: '传感器/感知',
    icon: '📡',
    color: '#22c55e',
    desc: '力传感器、3D 视觉（灵巧手/避障/导航）',
    assessment: `力传感器是实现触觉与力控闭环的关键，柯力传感等布局六维力传感器；
    奥比中光 3D 视觉传感器用于环境感知与导航。感知环节单价较高但单台用量有限，受益弹性中等。`,
    stocks: [
      { code: '603662', name: '柯力传感', role: '应变式/六维力传感器', rec: 'WATCH' },
      { code: '688322', name: '奥比中光', role: '3D 视觉传感器·机器人感知', rec: 'WATCH' },
    ],
  },
  {
    key: 'body',
    label: '本体/控制器',
    icon: '🦾',
    color: '#eab308',
    desc: '机器人本体、控制器及系统集成',
    assessment: `本体与控制器环节由宇树自身主导，A 股关联以工控/运动控制龙头为主。
    埃斯顿（工业机器人本体+控制器）、卧龙电驱（电机/驱动）为产业链配套标的，关联度相对间接。`,
    stocks: [
      { code: '002747', name: '埃斯顿', role: '工业机器人本体/控制器', rec: 'WATCH' },
      { code: '600580', name: '卧龙电驱', role: '电机/驱动·机器人配套', rec: 'CAUTIOUS' },
    ],
  },
];

const ALL_CODES = CATEGORIES.flatMap(c => c.stocks.map(s => s.code));

export default function UnitreeIpoPage() {
  const navigate = useNavigate();
  const [quotes, setQuotes] = useState({});
  const [sectorData, setSectorData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activeCat, setActiveCat] = useState('all');
  // 用户自选/持仓交叉比对
  const [userWatchlist, setUserWatchlist] = useState(new Set());
  const [userPortfolio, setUserPortfolio] = useState(new Set());
  // 折叠状态
  const [expandedAssessments, setExpandedAssessments] = useState(new Set());
  const [expandedResearch, setExpandedResearch] = useState(new Set());
  // 一键加入自选
  const addToWatchlist = useCallback(async (code, name) => {
    try {
      const { ok } = await apiFetch('/api/watchlist', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ secCode: code, secName: name, group: '默认' }),
      });
      if (ok) setUserWatchlist(prev => new Set([...prev, code]));
    } catch {}
  }, []);

  // 交易弹窗（买入）
  const { executeTrade, tradeResult, clearTradeResult } = useTrading();
  const [buyModal, setBuyModal] = useState(null);
  useEffect(() => {
    if (tradeResult) {
      const t = setTimeout(clearTradeResult, TOAST_DURATION);
      return () => clearTimeout(t);
    }
  }, [tradeResult, clearTradeResult]);

  // 刷新行情
  const [quoteProgress, setQuoteProgress] = useState({ loaded: 0, total: ALL_CODES.length });
  const refreshQuotes = useCallback(async () => {
    setQuoteProgress(p => ({ ...p, loaded: 0 }));
    const results = await Promise.allSettled(
      ALL_CODES.map(code =>
        apiFetch(`/api/trading/quote?code=${code}`, {}, 6000)
      )
    );
    let loaded = 0;
    const map = {};
    for (const r of results) {
      if (r.status === 'fulfilled' && r.value.ok) {
        const d = r.value.data;
        map[d.code] = d;
      }
      loaded++;
    }
    setQuotes(map);
    setQuoteProgress({ loaded, total: ALL_CODES.length });
    setLoading(false);
  }, []);

  // 交叉比对：哪些关联标的已在你的自选/持仓中
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const [wlRes, pfRes] = await Promise.allSettled([
          apiFetch('/api/watchlist', {}, 5000),
          apiFetch('/api/shared/portfolio', {}, 5000),
        ]);
        if (!active) return;
        const wlSet = new Set();
        if (wlRes.status === 'fulfilled' && wlRes.value.ok) {
          (wlRes.value.data?.signals || []).forEach(s => wlSet.add(s.secCode));
        }
        setUserWatchlist(wlSet);
        const pfSet = new Set();
        if (pfRes.status === 'fulfilled' && pfRes.value.ok) {
          (pfRes.value.data?.positions || []).forEach(p => pfSet.add(p.symbol));
        }
        setUserPortfolio(pfSet);
      } catch {}
    })();
    return () => { active = false; };
  }, []);

  // 获取实时行情 + 公司自身行情（后跟踪）
  useEffect(() => {
    let active = true;
    refreshQuotes().then(() => {
      if (active) setLoading(false);
    });
    refreshCompanyQuote();
    return () => { active = false; };
  }, [refreshQuotes, refreshCompanyQuote]);

  // 获取人形机器人板块数据
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/realtime/concept-sector-trend?sector=人形机器人', {}, 8000);
        if (active && ok) setSectorData(data);
      } catch {}
    })();
    return () => { active = false; };
  }, []);

  const fmtChg = (v) => {
    if (v == null) return '—';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
  };

  const fmtMoney = (v) => {
    if (v == null) return '—';
    if (Math.abs(v) >= 1e8) return (v / 1e8).toFixed(2) + '亿';
    if (Math.abs(v) >= 1e4) return (v / 1e4).toFixed(0) + '万';
    return String(v);
  };

  // IPO 跟踪（数据驱动，详见 src/data/ipoProjects.js）
  const project = IPO_PROJECTS.unitree;
  const [companyQuote, setCompanyQuote] = useState(null);

  // 公司自身实时行情（后跟踪）：上市后自动拉取
  const refreshCompanyQuote = useCallback(async () => {
    if (!project.listed || !project.code) return;
    try {
      const { ok, data } = await apiFetch(`/api/trading/quote?code=${project.code}`, {}, 6000);
      if (ok) setCompanyQuote(data);
    } catch {}
  }, [project]);

  // 当前 IPO 阶段（用于状态卡）
  const ipoStatus = useMemo(() => {
    const p = computeIpoProgress(project, Date.now());
    const next = p.nextIdx >= 0 ? p.stages[p.nextIdx] : null;
    const allDone = p.stages.every((s) => s.status === 'done');
    if (project.listed && allDone) return { icon: '🚀', label: '已上市', color: '#22c55e', sub: '后跟踪进行中' };
    if (next) {
      const diff = next.ms - Date.now();
      const dd = Math.floor(diff / 86400000);
      const hh = Math.floor((diff % 86400000) / 3600000);
      return { icon: '⏳', label: next.label, color: '#3b82f6', sub: dd > 0 ? `${dd}天${hh}小时` : `${hh}小时` };
    }
    return { icon: '📝', label: '进行中', color: 'var(--text-muted)', sub: '节点待披露' };
  }, [project]);

  const filteredCategories = useMemo(() => {
    if (activeCat === 'all') return CATEGORIES;
    return CATEGORIES.filter(c => c.key === activeCat);
  }, [activeCat]);

  return (
    <div className="space-y-3">

      {/* 交易结果 Toast */}
      {tradeResult && (
        <div className="fixed top-4 right-4 z-50 px-4 py-2 rounded-lg text-sm shadow-lg"
          style={{ background: tradeResult.success ? 'rgba(34,197,94,0.92)' : 'rgba(239,68,68,0.92)', color: '#fff' }}>
          {tradeResult.success ? '✅ ' : '❌ '}{tradeResult.message}
        </div>
      )}

      {/* ===== 标题栏 ===== */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <span>🤖 宇树科技 · IPO 关联标的</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
            科创板 · 申报中
          </span>
        </h2>
        <button onClick={() => { refreshQuotes(); refreshCompanyQuote(); }}
          className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
          🔄 刷新行情
          {quoteProgress.loaded < quoteProgress.total && (
            <span className="text-[10px]" style={{ color: '#f59e0b' }}>({quoteProgress.loaded}/{quoteProgress.total})</span>
          )}
        </button>
      </div>

      {/* 数据占位声明 */}
      <div className="rounded-xl border px-3 py-1.5 text-[10px] leading-relaxed"
        style={{ borderColor: 'rgba(245,158,11,0.3)', background: 'rgba(245,158,11,0.06)', color: 'var(--text-secondary)' }}>
        ⚠️ 本页为宇树机器人 IPO 关联分析骨架：标的名单基于公开供应链关联梳理，实时行情为真实数据；
        <strong style={{ color: '#f59e0b' }}>具体估值（PE/净利增速）与评级为「待补充」占位</strong>，正式结论请以招股说明书披露及实盘核实为准。
      </div>

      {/* ===== IPO 速览 Hero ===== */}
      <div className="rounded-xl border p-3 space-y-2.5" style={{
        borderColor: 'rgba(59,130,246,0.3)',
        background: 'linear-gradient(135deg, rgba(59,130,246,0.06) 0%, rgba(168,85,247,0.04) 100%)',
      }}>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>宇树科技</span>
          {(() => {
            const p = computeIpoProgress(project, Date.now());
            const doneStage = [...p.stages].reverse().find((s) => s.status === 'done');
            return (
              <span className="text-xs px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}>
                📝 {doneStage ? doneStage.label : '申报中'}
              </span>
            );
          })()}
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
            {project.board} · {project.code ? `代码 ${project.code}` : '代码待定'}
          </span>
        </div>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {[
            { label: '上市板块', value: '科创板', sub: '已递交 IPO 申报', color: '#3b82f6' },
            { label: '主营业务', value: '四足/人形机器人', sub: '全球出货量领先', color: '#22c55e' },
            { label: '融资金额', value: '待定', sub: '以招股书为准', color: '#f97316' },
            { label: '关联标的', value: `${ALL_CODES.length}只`, sub: '供应链/概念梳理', color: '#a855f7' },
          ].map((c, i) => (
            <div key={i} className="rounded-lg border p-2" style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{c.label}</div>
              <div className="text-base font-bold" style={{ color: c.color }}>{c.value}</div>
              <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.sub}</div>
            </div>
          ))}
        </div>
        <div className="text-[11px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          宇树科技（Unitree Robotics）成立于 2016 年，总部位于杭州，创始人王兴兴；
          是全球领先的四足机器人与通用人形机器人公司，产品涵盖 Go/B 系列四足机器人、G1/H1 人形机器人。
          2025 年起启动 A 股上市进程（申报科创板），被视为「人形机器人第一股」候选之一。
          下方关联标的覆盖本体、减速器、电机/伺服、丝杠、传感器、控制器等核心供应链环节。
        </div>
      </div>

      {/* ===== IPO 前/后跟踪（动态） ===== */}
      <IpoTimeline project={project} />
      <IpoListingCard project={project} quote={companyQuote} loading={loading} />

      {/* ===== 评估速览 + 倒计时 ===== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {[
          { label: 'IPO状态', value: `${ipoStatus.icon} ${ipoStatus.label}`, color: ipoStatus.color, sub: ipoStatus.sub },
          { label: '行情加载', value: `${quoteProgress.loaded}/${quoteProgress.total}`, color: quoteProgress.loaded === quoteProgress.total ? '#22c55e' : '#f59e0b', sub: quoteProgress.loaded === quoteProgress.total ? '已就绪' : '加载中...' },
          { label: '强关联(★★★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='BUY').length+'只', color: '#1D9E75', sub: '核心供应链' },
          { label: '可关注(★★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='WATCH').length+'只', color: '#f59e0b', sub: '间接受益' },
          { label: '谨慎(★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='CAUTIOUS').length+'只', color: '#E24B4A', sub: '主题为主' },
        ].map((c, i) => (
          <div key={i} className="rounded-xl border p-2.5"
            style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
            <div className="text-[10px] flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
              {c.label}
              <span className="text-[9px]">{c.sub}</span>
            </div>
            <div className="text-xl font-bold mt-0.5" style={{ color: c.color }}>{c.value}</div>
          </div>
        ))}
      </div>

      {/* ===== 分类标签导航 ===== */}
      <div className="flex items-center gap-1 flex-wrap">
        <button onClick={() => setActiveCat('all')}
          className="px-2.5 py-1 rounded-lg border text-[11px] font-medium"
          style={{
            background: activeCat === 'all' ? 'rgba(59,130,246,0.12)' : 'transparent',
            borderColor: activeCat === 'all' ? 'rgba(59,130,246,0.4)' : 'var(--border-color)',
            color: activeCat === 'all' ? '#3b82f6' : 'var(--text-secondary)',
          }}>
          📋 全部（{ALL_CODES.length}只）
        </button>
        {CATEGORIES.map(cat => (
          <button key={cat.key} onClick={() => setActiveCat(cat.key)}
            className="px-2.5 py-1 rounded-lg border text-[11px] flex items-center gap-1"
            style={{
              background: activeCat === cat.key ? `${cat.color}12` : 'transparent',
              borderColor: activeCat === cat.key ? `${cat.color}40` : 'var(--border-color)',
              color: activeCat === cat.key ? cat.color : 'var(--text-secondary)',
            }}>
            <span>{cat.icon}</span>
            <span>{cat.label}</span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{cat.stocks.length}</span>
          </button>
        ))}
      </div>

      {/* ===== 板块分组列表 ===== */}
      <div className="space-y-2">
        {filteredCategories.map(cat => {
          const catQuotes = [...cat.stocks]
            .map(s => ({ ...s, quote: quotes[s.code], isNew: s.role?.includes('新增') }))
            .sort((a, b) => {
              const pri = { BUY: 0, WATCH: 1, CAUTIOUS: 2 };
              return (pri[a.rec] ?? 9) - (pri[b.rec] ?? 9);
            });
          const avgChg = catQuotes.reduce((sum, s) => sum + (s.quote?.changePct ?? 0), 0) / Math.max(catQuotes.length, 1);
          const upCount = catQuotes.filter(s => (s.quote?.changePct ?? 0) > 0).length;
          const buyCount = catQuotes.filter(s => s.rec === 'BUY').length;
          const watchCount = catQuotes.filter(s => s.rec === 'WATCH').length;
          return (
            <div key={cat.key} className="rounded-xl border overflow-hidden" style={{ borderColor: `${cat.color}30`, background: 'var(--bg-card)' }}>
              <div className="flex items-center gap-2 px-3 py-1.5" style={{ borderBottom: '1px solid var(--border-color)' }}>
                <span className="text-sm">{cat.icon}</span>
                <span className="text-xs font-bold" style={{ color: cat.color }}>{cat.label}</span>
                <span className="text-[10px] px-1 rounded" style={{
                  background: avgChg >= 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                  color: avgChg >= 0 ? '#ef4444' : '#22c55e',
                }}>
                  {upCount}/{catQuotes.length}↑
                </span>
                <span className="text-xs font-bold" style={{ color: avgChg >= 0 ? '#ef4444' : '#22c55e' }}>
                  {fmtChg(avgChg)}
                </span>
                <span className="text-[9px] flex items-center gap-1">
                  {buyCount > 0 && <span style={{ color: '#1D9E75' }}>★{buyCount}</span>}
                  {watchCount > 0 && <span style={{ color: '#f59e0b' }}>★{watchCount}</span>}
                </span>
                {cat.assessment && (
                  <span className="text-[10px] ml-auto cursor-pointer hover:opacity-70" style={{ color: cat.color }}
                    onClick={() => {
                      setExpandedAssessments(prev => {
                        const n = new Set(prev);
                        n.has(cat.key) ? n.delete(cat.key) : n.add(cat.key);
                        return n;
                      });
                    }}>
                    📋 分析 {expandedAssessments.has(cat.key) ? '▴' : '▾'}
                  </span>
                )}
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{cat.desc}</span>
              </div>
              {cat.assessment && expandedAssessments.has(cat.key) && (
                <div className="px-3 py-1.5 text-[10px] leading-relaxed"
                  style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-surface)' }}>
                  {cat.assessment}
                </div>
              )}
              <div className="grid grid-cols-1 md:grid-cols-2 gap-1.5 px-3 py-2">
                {catQuotes.map(st => {
                  const q = st.quote;
                  const chg = q?.changePct;
                  const isUp = chg != null && chg >= 0;
                  return (
                    <div key={st.code} className="flex items-center gap-2 px-2 py-1.5 rounded-lg cursor-pointer hover:opacity-80"
                      style={{ background: 'var(--bg-surface)' }}
                      onClick={() => navigate(`/stock/${st.code}`)}>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-1">
                          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>{st.name}</span>
                          <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{st.code}</span>
                          {st.rec && (
                            <span className="text-[9px] px-1 py-0.5 rounded font-medium flex-shrink-0" style={{
                              background: ASSESSMENT[st.rec].bg,
                              color: ASSESSMENT[st.rec].color,
                              border: `0.5px solid ${ASSESSMENT[st.rec].color}40`,
                            }}>
                              {ASSESSMENT[st.rec].label}
                            </span>
                          )}
                        </div>
                        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{st.role}</div>
                      </div>
                      <div className="flex items-center gap-1 flex-shrink-0">
                        {userWatchlist.has(st.code) && (
                          <span className="text-[9px] px-1 py-0.5 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '0.5px solid rgba(34,197,94,0.3)' }}>⭐</span>
                        )}
                        {userPortfolio.has(st.code) && (
                          <span className="text-[9px] px-1 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '0.5px solid rgba(168,85,247,0.3)' }}>💼</span>
                        )}
                        {!userWatchlist.has(st.code) && (
                          <button onClick={(e) => { e.stopPropagation(); addToWatchlist(st.code, st.name); }}
                            className="text-[9px] px-1 py-0.5 rounded border hover:opacity-70"
                            style={{ borderColor: 'rgba(34,197,94,0.4)', color: '#22c55e', background: 'transparent', cursor: 'pointer' }}
                            title={`加入自选股`}>
                            ＋自选
                          </button>
                        )}
                      </div>
                      <div className="text-right flex-shrink-0">
                        {q ? (
                          <>
                            <div className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                              {q.price != null ? q.price.toFixed(2) : '-'}
                            </div>
                            <div className="text-[11px] font-bold" style={{ color: isUp ? '#ef4444' : '#22c55e' }}>
                              {fmtChg(chg)}
                            </div>
                          </>
                        ) : null}
                      </div>
                      <button onClick={(e) => { e.stopPropagation(); setBuyModal({ code: st.code, name: st.name }); }}
                        className="px-2 py-0.5 rounded text-[10px] font-medium border hover:opacity-80 flex-shrink-0"
                        style={{
                          borderColor: 'rgba(239,68,68,0.4)',
                          color: '#ef4444',
                          background: 'rgba(239,68,68,0.06)',
                          cursor: 'pointer',
                        }}>
                        买入
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>

      {/* ===== 人形机器人板块参考 ===== */}
      <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(59,130,246,0.3)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm">🦾</span>
          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>人形机器人概念板块</span>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 宇树上市核心受益赛道</span>
        </div>
        {sectorData ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            {[
              { label: '板块涨跌幅', value: fmtChg(sectorData.changePct ?? sectorData.change_percent), color: (sectorData.changePct ?? 0) >= 0 ? '#ef4444' : '#22c55e' },
              { label: '主力净流入', value: fmtMoney(sectorData.main_net ?? sectorData.main_force_inflow), color: (sectorData.main_net ?? 0) >= 0 ? '#ef4444' : '#22c55e' },
              { label: '板块热度', value: sectorData.heat != null ? sectorData.heat.toFixed(1) : '—', color: '#f97316' },
              { label: '成分股', value: sectorData.stock_count ? `${sectorData.stock_count}只` : '—', color: 'var(--text-primary)' },
            ].map((c, i) => (
              <div key={i} className="rounded-lg border p-2" style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
                <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{c.label}</div>
                <div className="text-sm font-bold" style={{ color: c.color }}>{c.value}</div>
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
            {loading ? '加载板块数据...' : '板块数据暂不可用（后端未配置该概念板块）'}
          </div>
        )}
        <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          人形机器人产业链涵盖：减速器（绿的谐波、中大力德）、电机/伺服（鸣志电器、汇川技术）、丝杠（北特科技、贝斯特）、
          传感器（柯力传感、奥比中光）、本体/控制器（埃斯顿）等环节。
        </div>
      </div>

      {/* ===== 研究评估 ===== */}
      <div className="space-y-2">
        <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: '#3b82f6' }}>
          📋 研究评估结论
          <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>关联梳理占位 · 估值数据待招股书披露后补全</span>
        </h3>

        {/* 宇树科技IPO评估 */}
        <div className="rounded-xl border p-2.5 space-y-2" style={{ borderColor: 'rgba(59,130,246,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-bold flex items-center gap-2 cursor-pointer hover:opacity-70"
            style={{ color: '#3b82f6' }}
            onClick={() => setExpandedResearch(prev => {
              const n = new Set(prev);
              n.has('unitree') ? n.delete('unitree') : n.add('unitree');
              return n;
            })}>
            宇树科技 IPO 申购评估（占位） <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expandedResearch.has('unitree') ? '▴' : '▾'}</span>
          </div>
          {expandedResearch.has('unitree') && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
            <div className="space-y-1">
              <div><span className="font-medium" style={{ color: '#1D9E75' }}>✅ 行业地位</span> · 全球四足机器人出货量领先，人形机器人 G1/H1 已量产交付</div>
              <div><span className="font-medium">国产替代</span> 机器人核心零部件（减速器/电机/丝杠）国产化加速，供应链弹性大</div>
              <div><span className="font-medium">商业化节奏</span> 2025-2026 年为人形机器人量产元年，特斯拉 Optimus 与中国厂商同步推进</div>
            </div>
            <div className="space-y-1">
              <div><span className="font-medium" style={{ color: '#E24B4A' }}>⚠️ 核心风险</span> — 量产良率/降本不及预期，行业估值整体偏高，主题炒作退潮风险</div>
              <div><span className="font-medium" style={{ color: '#E24B4A' }}>估值窗口</span> — 具体发行估值/募资额待招股书披露，需上市后结合业绩再评估</div>
              <div><span className="font-medium" style={{ color: '#f59e0b' }}>关键观测</span>：受理批文 → 招股书披露（融资金额/发行价） → 网上申购 → 上市交易</div>
              <div><span className="font-medium" style={{ color: '#3b82f6' }}>策略</span>：先布局确定性高的供应链环节，待定价充分再做二级决策</div>
            </div>
          </div>
          )}
        </div>

        {/* 行业研判 */}
        <div className="rounded-xl border p-2.5 space-y-1.5" style={{ borderColor: 'rgba(168,85,247,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-bold flex items-center gap-2 cursor-pointer hover:opacity-70"
            style={{ color: '#a855f7' }}
            onClick={() => setExpandedResearch(prev => {
              const n = new Set(prev);
              n.has('humanoid') ? n.delete('humanoid') : n.add('humanoid');
              return n;
            })}>
            🌐 人形机器人行业研判（2026 展望）<span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expandedResearch.has('humanoid') ? '▴' : '▾'}</span>
          </div>
          {expandedResearch.has('humanoid') && (
          <div className="text-[11px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            <strong>短期（6-12个月）</strong>：2025-2026 年进入人形机器人量产导入期，特斯拉 Optimus、宇树、智元、Figure 等厂商陆续小批量交付。
            供应链从「主题预期」走向「订单兑现」，减速器、电机、丝杠等环节率先放量。
            <strong>中期（12-24个月）</strong>：若量产成本降至消费级可接受区间，应用场景（工业巡检、仓储、服务）打开，板块从主题投资转向业绩驱动。
            <strong>风险</strong>：技术路线未定（谐波 vs 行星滚柱丝杠方案之争）、量产降本慢于预期、估值透支与主题退潮。
            <strong>结论</strong>：长期产业趋势明确，但短期需注意估值与业绩兑现节奏的匹配。
          </div>
          )}
        </div>

        {/* 关联标的评估表 */}
        <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'rgba(34,197,94,0.3)', background: 'var(--bg-card)' }}>
          <div className="px-3 py-1.5 text-xs font-bold flex items-center gap-2 cursor-pointer hover:opacity-70"
            style={{ color: '#22c55e', borderBottom: '1px solid var(--border-color)' }}
            onClick={() => setExpandedResearch(prev => {
              const n = new Set(prev);
              n.has('table') ? n.delete('table') : n.add('table');
              return n;
            })}>
            📊 关联标的评估总表 <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expandedResearch.has('table') ? '▴' : '▾'}</span>
          </div>
          {expandedResearch.has('table') && (
          <div className="overflow-x-auto">
            <table className="w-full text-[11px]">
              <thead>
                <tr style={{ color: 'var(--text-muted)', borderBottom: '1px solid var(--border-color)' }}>
                  <th className="text-left py-1 px-2">标的</th>
                  <th className="text-left py-1 px-2">代码</th>
                  <th className="text-left py-1 px-2">环节</th>
                  <th className="text-right py-1 px-2">2026H1净利增速</th>
                  <th className="text-right py-1 px-2">PE(TTM)</th>
                  <th className="text-center py-1 px-2">评级</th>
                  <th className="text-left py-1 px-2">核心逻辑</th>
                </tr>
              </thead>
              <tbody>
                {CATEGORIES.flatMap(c => c.stocks).map((r, i) => {
                  const a = ASSESSMENT[r.rec];
                  return (
                    <tr key={r.code} style={{ borderTop: i > 0 ? '1px solid var(--border-color)' : 'none' }}>
                      <td className="py-1 px-2 font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</td>
                      <td className="py-1 px-2" style={{ color: 'var(--text-muted)' }}>{r.code}</td>
                      <td className="py-1 px-2" style={{ color: 'var(--text-secondary)' }}>{r.role}</td>
                      <td className="py-1 px-2 text-right font-medium" style={{ color: '#1D9E75' }}>待补充</td>
                      <td className="py-1 px-2 text-right" style={{ color: 'var(--text-muted)' }}>待补充</td>
                      <td className="py-1 px-2 text-center">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: a.bg, color: a.color, border: `0.5px solid ${a.color}40` }}>
                          {a.label}
                        </span>
                      </td>
                      <td className="py-1 px-2 text-[10px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>供应链关联梳理（占位）</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          )}
        </div>

        {/* 风险提示 */}
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(239,68,68,0.2)', background: 'rgba(239,68,68,0.04)' }}>
          <div className="text-xs font-bold mb-1" style={{ color: '#E24B4A' }}>⚠️ 风险提示</div>
          <div className="text-[10px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            ① 量产风险：人形机器人仍处于量产早期，良率、降本、可靠性均存在不确定性。
            ② 估值风险：机器人概念板块整体估值偏高，需警惕主题退潮与戴维斯双杀。
            ③ 技术路线：减速器（谐波 vs 行星）、执行器方案尚未完全收敛，存在路线切换风险。
            ④ 关联度差异：部分标的仅为主题概念关联，实际订单弹性需以公告为准。
            <br /><br /><strong>免责声明：本页面标的名单为公开供应链关联梳理，估值/评级为占位，所有分析结论仅供研究参考，不构成个人投资建议。股票投资有风险，入市需谨慎。</strong>
          </div>
        </div>
      </div>

      {/* ===== 底部 ===== */}
      <div className="text-center text-[10px] py-1" style={{ color: 'var(--text-muted)' }}>
        数据来源：实时行情为后端真实接口 · 关联梳理基于公开资料 · 估值数据待招股书披露补全
        <br />本页仅供研究参考，不构成投资建议
      </div>

      {/* 交易弹窗 */}
      {buyModal && (
        <TradeModal
          stockCode={buyModal.code}
          stockName={buyModal.name}
          type="buy"
          onClose={() => setBuyModal(null)}
          onConfirm={(order) => executeTrade(order.type, order.stockCode, order.price, order.quantity)}
        />
      )}
    </div>
  );
}
