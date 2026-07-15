import { useState, useEffect, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import TradeModal from '../components/trading/TradeModal';
import { useTrading } from '../context/TradingContext';
import { TOAST_DURATION } from '../utils/constants';

/* ─── 长鑫科技IPO关联标的分类 ───
   评估说明：
   ★★★ 强烈推荐 — 基本面扎实，存储周期红利明确，估值合理(PEG<0.5)
   ★★  可关注   — 受益于长鑫扩产但估值偏高或受益弹性有限
   ★   谨慎     — 关联度低、估值透支、或短期涨幅过大需等待回踩
*/
const ASSESSMENT = {
  BUY: { label: '★★★ 可买', color: '#1D9E75', bg: 'rgba(29,158,117,0.1)', desc: '强烈推荐' },
  WATCH: { label: '★★ 可关注', color: '#f59e0b', bg: 'rgba(245,158,11,0.1)', desc: '持续追踪' },
  CAUTIOUS: { label: '★ 谨慎', color: '#E24B4A', bg: 'rgba(226,75,74,0.1)', desc: '等待回踩' },
};
const CATEGORIES = [
  {
    key: 'equity',
    label: '参股类',
    icon: '🏦',
    color: '#a855f7',
    desc: '直接或间接持有长鑫科技股权的上市公司',
    assessment: `参股类标的的收益来源是长鑫科技上市后的公允价值重估，而非主营业务增长。
    核心标的兆易创新持有 1.8% 长鑫科技股权且是唯一深度绑定标的（采购DRAM代工57亿），业绩弹性最大。
    合肥城建、美的集团作为财务投资者，上市后减持预期较强，受益弹性有限。`,
    stocks: [
      { code: '603986', name: '兆易创新', role: '创始人·持股1.8%·DRAM代工57亿·新增', rec: 'BUY' },
      { code: '600641', name: '万业企业', role: '持股0.95%+离子注入设备·双重受益·新增', rec: 'WATCH' },
      { code: '002208', name: '合肥城建', role: '合肥国资·参股', rec: 'WATCH' },
      { code: '000333', name: '美的集团', role: '战略投资·参股', rec: 'WATCH' },
      { code: '601816', name: '百合集团', role: '财务投资·参股', rec: 'CAUTIOUS' },
      { code: '000672', name: '上峰水泥', role: '间接持股0.16%·财务投资·新增', rec: 'CAUTIOUS' },
    ],
  },
  {
    key: 'equipment',
    label: '设备环节',
    icon: '🔧',
    color: '#3b82f6',
    desc: '半导体制造设备供应商，长鑫产线扩产核心受益（IPO募资设备购置220亿）',
    assessment: `设备类受益于长鑫科技IPO募资220亿用于设备购置+每年50-60亿美元设备采购，2026-2027年国产设备黄金窗口。
    北方华创为长鑫第一大国产设备商，平台型覆盖全工艺段，2026E PE 36x，PEG 1.34，长期配置价值明确。
    拓荆科技PECVD+HBM混合键合设备国内唯一，盛美上海清洗设备全系列复购。设备板块整体估值适度透支但确定性最强。`,
    stocks: [
      { code: '002371', name: '北方华创', role: '平台型设备龙头·刻蚀/薄膜/清洗·长鑫第一大国产设备商·新增', rec: 'BUY' },
      { code: '688072', name: '拓荆科技', role: 'HBM混合键合·PECVD·PE33×·净利+90%', rec: 'BUY' },
      { code: '688012', name: '中微公司', role: '介质刻蚀龙头·5nm全球量产·薄膜第二曲线·新增', rec: 'BUY' },
      { code: '688082', name: '盛美上海', role: '清洗设备龙头·全产线持续复购·新增', rec: 'BUY' },
      { code: '688120', name: '华海清科', role: 'CMP抛光设备·14nm验证推进·新增', rec: 'WATCH' },
      { code: '603690', name: '至纯科技', role: '湿法清洗设备', rec: 'WATCH' },
      { code: '688627', name: '精智达', role: 'DRAM专用测试设备·新增', rec: 'WATCH' },
      { code: '688596', name: '正帆科技', role: '工艺介质供应系统·新增', rec: 'WATCH' },
      { code: '601133', name: '柏诚股份', role: '洁净室工程', rec: 'WATCH' },
      { code: '603929', name: '亚翔集成', role: '洁净室工程', rec: 'WATCH' },
    ],
  },
  {
    key: 'material',
    label: '关键原材料',
    icon: '🧪',
    color: '#f97316',
    desc: 'DRAM 制造所需的硅片/特气/抛光液/化学品/靶材等',
    assessment: `材料类受益于长鑫+长江存储双线扩产，需求增长确定性强且不受存储涨跌周期扰动，化学品已成为长鑫第一大品类（采购占比37%）。
    安集科技CMP抛光液国内龙头+鼎龙股份CMP抛光垫垄断70%+，耗材属性持续性强。
    沪硅产业12英寸大硅片、华特气体电子特气龙头为核心受益。`,
    stocks: [
      { code: '300054', name: '鼎龙股份', role: 'CMP抛光垫垄断70%·PE30×·净利+68%', rec: 'BUY' },
      { code: '688019', name: '安集科技', role: 'CMP抛光液龙头·17nm批量供货·新增', rec: 'BUY' },
      { code: '688126', name: '沪硅产业', role: '12英寸大硅片龙头·DRAM基材·新增', rec: 'BUY' },
      { code: '688268', name: '华特气体', role: '电子特气龙头·长鑫核心供应商·新增', rec: 'WATCH' },
      { code: '688548', name: '广钢气体', role: '电子特气', rec: 'WATCH' },
      { code: '300666', name: '江丰电子', role: '靶材龙头·新增', rec: 'WATCH' },
      { code: '002409', name: '雅克科技', role: '前驱体/绝缘膜', rec: 'WATCH' },
      { code: '600206', name: '有研新材', role: '靶材', rec: 'CAUTIOUS' },
      { code: '603078', name: '江化微', role: '湿电子化学品', rec: 'CAUTIOUS' },
      { code: '300655', name: '晶瑞电材', role: '湿电子化学品·新增', rec: 'CAUTIOUS' },
    ],
  },
  {
    key: 'packaging',
    label: '封测模组',
    icon: '📦',
    color: '#22c55e',
    desc: 'DRAM 颗粒封装测试及模组组装（委外封测全部委托国内厂商）',
    assessment: `封测模组类受益于存储芯片量价齐升，涨价传导顺畅。
    长电科技为国内封测龙头+通富微电AMD核心封测伙伴，双重受益于先进封装景气上行。
    江波龙2026H1净利92-110亿，PE仅21-25×是板块估值最低的标的。
    华天科技南京基地深度绑定长鑫DDR5/先进封装。`,
    stocks: [
      { code: '301308', name: '江波龙', role: '存储模组龙头·PE21-25×·H1净利+62200%', rec: 'BUY' },
      { code: '002156', name: '通富微电', role: '先进封装·AMD+长鑫双客户', rec: 'BUY' },
      { code: '600584', name: '长电科技', role: '封测龙头·长鑫委外测试主要合作方·新增', rec: 'BUY' },
      { code: '002185', name: '华天科技', role: '南京基地绑定长鑫DDR5/先进封装·新增', rec: 'BUY' },
      { code: '000021', name: '深科技', role: '沛顿科技为长鑫最大委外封测供应商', rec: 'WATCH' },
    ],
  },
];

const ALL_CODES = CATEGORIES.flatMap(c => c.stocks.map(s => s.code));

export default function CxmtIpoPage() {
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

  // IPO 进度状态机
  const [quoteProgress, setQuoteProgress] = useState({ loaded: 0, total: ALL_CODES.length });
  const ipoState = useMemo(() => {
    const now = Date.now();
    const days = [
      { d: new Date('2026-07-15T00:00:00+08:00'), label: '询价定价', icon: '💰', color: '#f59e0b' },
      { d: new Date('2026-07-16T00:00:00+08:00'), label: '今日申购!', icon: '🎯', color: '#ef4444' },
      { d: new Date('2026-07-17T00:00:00+08:00'), label: '等待中签', icon: '⏳', color: '#3b82f6' },
      { d: new Date('2026-07-20T00:00:00+08:00'), label: '缴款截止', icon: '💳', color: '#f97316' },
      { d: new Date('2026-07-22T00:00:00+08:00'), label: '发行结果', icon: '📋', color: '#a855f7' },
    ];
    for (const phase of days) {
      if (now < phase.d.getTime()) {
        const diff = phase.d - now;
        const dd = Math.floor(diff / 86400000);
        const hh = Math.floor((diff % 86400000) / 3600000);
        return { ...phase, countdown: dd > 0 ? `${dd}天${hh}小时` : `${hh}小时`, done: false };
      }
    }
    return { label: '已上市', icon: '🚀', color: '#22c55e', countdown: '—', done: true };
  }, []);

  // 刷新行情
  const refreshQuotes = useCallback(async () => {
    setQuoteProgress(p => ({ ...p, loaded: 0 }));
    const results = await Promise.allSettled(
      ALL_CODES.map(code =>
        apiFetch(`/api/trading/realtime-quote?code=${code}`, {}, 6000)
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

  // 获取实时行情
  useEffect(() => {
    let active = true;
    refreshQuotes().then(() => {
      if (active) setLoading(false);
    });
    return () => { active = false; };
  }, [refreshQuotes]);

  // 获取存储芯片板块数据
  useEffect(() => {
    let active = true;
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/realtime/concept-sector-trend?sector=存储芯片', {}, 8000);
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
          <span>🔬 长鑫科技 · IPO 关联标的</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
            688825.SH
          </span>
        </h2>
        <button onClick={refreshQuotes}
          className="px-2.5 py-1 rounded-lg border text-xs flex items-center gap-1"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
          🔄 刷新行情
          {quoteProgress.loaded < quoteProgress.total && (
            <span className="text-[10px]" style={{ color: '#f59e0b' }}>({quoteProgress.loaded}/{quoteProgress.total})</span>
          )}
        </button>
      </div>

      {/* ===== IPO 速览 Hero ===== */}
      <div className="rounded-xl border p-3 space-y-2.5" style={{
        borderColor: 'rgba(168,85,247,0.3)',
        background: 'linear-gradient(135deg, rgba(168,85,247,0.06) 0%, rgba(59,130,246,0.04) 100%)',
      }}>
        {/* 顶部：公司名 + 申购日 */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>长鑫科技</span>
          <span className="text-xs px-1.5 py-0.5 rounded-full" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>
            🗓 7月16日网上申购
          </span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
            科创板 · 代码 688825
          </span>
        </div>
        {/* 关键数据卡 */}
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
          {[
            { label: '融资金额', value: '295亿', sub: '今年A股第一大IPO', color: '#ef4444' },
            { label: '申购上限', value: '167.2万股', sub: '顶格需沪市1672万', color: '#f97316' },
            { label: '2026H1营收', value: '1100-1200亿', sub: '同比增长612-677%', color: '#22c55e' },
            { label: '2026H1净利润', value: '500-570亿', sub: '同比增长2244-2544%', color: '#3b82f6' },
          ].map((c, i) => (
            <div key={i} className="rounded-lg border p-2" style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{c.label}</div>
              <div className="text-base font-bold" style={{ color: c.color }}>{c.value}</div>
              <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.sub}</div>
            </div>
          ))}
        </div>
        {/* 描述文字 */}
        <div className="text-[11px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          长鑫科技是中国规模第一、布局最全的 DRAM 研发设计制造一体化企业（IDM），
          成立于 2016 年（安徽合肥），创始人为兆易创新创始人朱一明。
          本次科创板上市拟募集 295 亿元，为科创板史上第二大 IPO（仅次于中芯国际 532 亿），
          也是科创板历史上发行股数最多的新股，中签率预计较高。
          网上申购代码 <strong style={{ color: '#a855f7' }}>787825</strong>，网下申购代码 <strong style={{ color: '#a855f7' }}>688825</strong>。
        </div>
      </div>

      {/* ===== 评估速览 + 倒计时 ===== */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {[
          { label: 'IPO状态', value: `${ipoState.icon} ${ipoState.label}`, color: ipoState.color, sub: ipoState.done ? '已上市' : ipoState.countdown },
          { label: '行情加载', value: `${quoteProgress.loaded}/${quoteProgress.total}`, color: quoteProgress.loaded === quoteProgress.total ? '#22c55e' : '#f59e0b', sub: quoteProgress.loaded === quoteProgress.total ? '已就绪' : '加载中...' },
          { label: '强烈推荐(★★★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='BUY').length+'只', color: '#1D9E75', sub: '★★★★★' },
          { label: '可关注(★★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='WATCH').length+'只', color: '#f59e0b', sub: '回调列入' },
          { label: '谨慎(★)', value: CATEGORIES.flatMap(c=>c.stocks).filter(s=>s.rec==='CAUTIOUS').length+'只', color: '#E24B4A', sub: '等待更佳' },
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
            background: activeCat === 'all' ? 'rgba(168,85,247,0.12)' : 'transparent',
            borderColor: activeCat === 'all' ? 'rgba(168,85,247,0.4)' : 'var(--border-color)',
            color: activeCat === 'all' ? '#a855f7' : 'var(--text-secondary)',
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
              {/* 板块头部 */}
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
              {/* 类别分析（可展开） */}
              {cat.assessment && expandedAssessments.has(cat.key) && (
                <div className="px-3 py-1.5 text-[10px] leading-relaxed"
                  style={{ color: 'var(--text-secondary)', borderBottom: '1px solid var(--border-color)', background: 'var(--bg-surface)' }}>
                  {cat.assessment}
                </div>
              )}
              {/* 个股列表 */}
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
                          {st.isNew && (
                            <span className="text-[9px] px-1 py-0.5 rounded font-bold"
                              style={{ background: 'rgba(59,130,246,0.12)', color: '#3b82f6', border: '0.5px solid rgba(59,130,246,0.3)' }}>
                              NEW
                            </span>
                          )}
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

      {/* ===== 存储芯片板块参考 ===== */}
      <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(59,130,246,0.3)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 mb-2">
          <span className="text-sm">💾</span>
          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>存储芯片概念板块</span>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 长鑫科技上市核心受益赛道</span>
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
            {loading ? '加载板块数据...' : '板块数据暂不可用'}
          </div>
        )}
        {/* 板块内重点标的 */}
        <div className="mt-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
          存储芯片板块涵盖：长鑫科技、兆易创新、北京君正、澜起科技、聚辰股份、普冉股份、东芯股份、恒烁股份等 DRAM/NAND/EEPROM 设计及 IDM 公司。
          <br />相关板块：半导体设备（北方华创、中微公司）、半导体材料（沪硅产业、安集科技）。
        </div>
      </div>

      {/* ===== 研究评估 ===== */}
      <div className="space-y-2">
        <h3 className="text-sm font-bold flex items-center gap-2" style={{ color: '#a855f7' }}>
          📋 研究评估结论
          <span className="text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>截至 2026年7月14日 · 数据来源详见文末</span>
        </h3>

        {/* 长鑫科技IPO评估 */}
        <div className="rounded-xl border p-2.5 space-y-2" style={{ borderColor: 'rgba(168,85,247,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-bold flex items-center gap-2 cursor-pointer hover:opacity-70"
            style={{ color: '#a855f7' }}
            onClick={() => setExpandedResearch(prev => {
              const n = new Set(prev);
              n.has('cxmt') ? n.delete('cxmt') : n.add('cxmt');
              return n;
            })}>
            长鑫科技 (688825) IPO 申购评估 <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expandedResearch.has('cxmt') ? '▴' : '▾'}</span>
          </div>
          {expandedResearch.has('cxmt') && (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-[11px]" style={{ color: 'var(--text-secondary)' }}>
            <div className="space-y-1">
              <div><span className="font-medium" style={{ color: '#1D9E75' }}>✅ 建议申购</span> · 中签率 0.3-0.8%（普通新股 10x+），每签成本约 3500-5000 元</div>
              <div><span className="font-medium">全球第四</span> DRAM（市占 10%+），中国第一，国产替代唯一 IDM 龙头</div>
              <div><span className="font-medium">营收增速</span> H1 +612~677%，净利润增速 +2244~2544%，戴维斯双击窗口</div>
              <div><span className="font-medium">295 亿募资</span> 投向：晶圆产线升级 + DRAM 技术升级 + 前瞻研发</div>
            </div>
            <div className="space-y-1">
              <div><span className="font-medium" style={{ color: '#E24B4A' }}>⚠️ 核心风险</span> — 周期顶点上市（DDR4 现货年涨 2300%），三星前总裁预警 2027H2 供给过剩</div>
              <div><span className="font-medium" style={{ color: '#E24B4A' }}>估值窗口窄</span> — 若按全年利润 1000 亿×20xPE=2 万亿，30xPE=3 万亿；IPO 参考估值仅 2950 亿（募资/10%）→ 上市后大概率冲高</div>
              <div><span className="font-medium" style={{ color: '#f59e0b' }}>关键观测</span>：7/15 确定发行价（判断合理估值区间）→ 7/16 申购 → 7/22 发行结果</div>
              <div><span className="font-medium" style={{ color: '#3b82f6' }}>策略</span>：积极申购打新，上市后观望 1-2 周等市场定价充分再做二级布局</div>
            </div>
          </div>
          )}
        </div>
        )}

        {/* 行业研判 */}
        <div className="rounded-xl border p-2.5 space-y-1.5" style={{ borderColor: 'rgba(59,130,246,0.3)', background: 'var(--bg-card)' }}>
          <div className="text-xs font-bold flex items-center gap-2 cursor-pointer hover:opacity-70"
            style={{ color: '#3b82f6' }}
            onClick={() => setExpandedResearch(prev => {
              const n = new Set(prev);
              n.has('dram') ? n.delete('dram') : n.add('dram');
              return n;
            })}>
            🌐 DRAM 行业研判（2026H2 展望）<span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{expandedResearch.has('dram') ? '▴' : '▾'}</span>
          </div>
          {expandedResearch.has('dram') && (
          <div className="text-[11px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
            <strong>短期（6-12个月）</strong>：AI 算力驱动的存储超级周期延续，服务器 DRAM 需求首超手机成为第一大应用。全球三大厂（三星/SK海力士/美光）将产能倾斜 HBM，通用 DRAM 供给紧缺至少延续至 2027 年 Q4。
            三季度 DRAM 合约价预计再涨 10-20%，全年均价涨幅 250-280%（杰富瑞/高盛预测）。
            <strong>中期风险（12-24个月）</strong>：长鑫+长江存储大幅扩产（2026 年长鑫设备采购 50-60 亿美元），三星前总裁庆桂显预警 2027H2-2028H1 供需格局逆转。
            若云厂商 AI 资本开支回报率不达预期，存储需求可能阶段性萎缩。
            <strong>结论</strong>：2026 全年存储板块"量价齐升"确定性强，但估值已反映较多乐观预期，需注意 2027 年起供给侧压力。
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
                  <th className="text-left py-1 px-2">类别</th>
                  <th className="text-right py-1 px-2">2026H1净利增速</th>
                  <th className="text-right py-1 px-2">PE(TTM)</th>
                  <th className="text-center py-1 px-2">评级</th>
                  <th className="text-left py-1 px-2">核心逻辑</th>
                </tr>
              </thead>
              <tbody>
                {[
                  { name:'长鑫科技', code:'688825', cat:'申购', growth:'+2244~2544%', pe:'—', rec:'BUY', logic:'国产DRAM唯一IDM·市占10%+·打新积极申购' },
                  { name:'兆易创新', code:'603986', cat:'参股', growth:'+1099%', pe:'134×', rec:'BUY', logic:'持长鑫1.8%+代工57亿·业绩爆发·可等回调' },
                  { name:'江波龙', code:'301308', cat:'封测', growth:'+62204%', pe:'21-25×', rec:'BUY', logic:'PE板块最低·H1净利92-110亿·企业级SSD' },
                  { name:'北方华创', code:'002371', cat:'设备', growth:'+33%(E)', pe:'36×', rec:'BUY', logic:'长鑫第一大国产设备商·平台型龙头·新增' },
                  { name:'中微公司', code:'688012', cat:'设备', growth:'+45%(E)', pe:'87×', rec:'BUY', logic:'刻蚀全球领先·5nm进台积电·新增' },
                  { name:'通富微电', code:'002156', cat:'封测', growth:'—', pe:'—', rec:'BUY', logic:'AMD核心封测+长鑫封测双重受益' },
                  { name:'拓荆科技', code:'688072', cat:'设备', growth:'+90%', pe:'33×', rec:'BUY', logic:'唯一HBM混合键合·PEG=0.37' },
                  { name:'长电科技', code:'600584', cat:'封测', growth:'—', pe:'—', rec:'BUY', logic:'封测龙头·长鑫委外测试主要合作方·新增' },
                  { name:'华天科技', code:'002185', cat:'封测', growth:'—', pe:'—', rec:'BUY', logic:'南京绑定长鑫DDR5·新增' },
                  { name:'鼎龙股份', code:'300054', cat:'材料', growth:'+64~74%', pe:'30×', rec:'BUY', logic:'CMP抛光垫垄断70%·PEG=0.44' },
                  { name:'安集科技', code:'688019', cat:'材料', growth:'—', pe:'—', rec:'BUY', logic:'CMP抛光液龙头·17nm批量·新增' },
                  { name:'沪硅产业', code:'688126', cat:'材料', growth:'—', pe:'—', rec:'BUY', logic:'12英寸大硅片龙头·DRAM基材·新增' },
                  { name:'盛美上海', code:'688082', cat:'设备', growth:'+42%(E)', pe:'61×', rec:'BUY', logic:'清洗龙头·全产线复购·新增' },
                  { name:'万业企业', code:'600641', cat:'参股', growth:'—', pe:'—', rec:'WATCH', logic:'持股0.95%+离子注入设备·新增' },
                  { name:'华海清科', code:'688120', cat:'设备', growth:'+31%', pe:'64×', rec:'WATCH', logic:'CMP抛光国产唯一·14nm验证·新增' },
                  { name:'精智达', code:'688627', cat:'设备', growth:'—', pe:'—', rec:'WATCH', logic:'DRAM测试设备·新增' },
                  { name:'正帆科技', code:'688596', cat:'设备', growth:'—', pe:'—', rec:'WATCH', logic:'工艺介质供应系统·新增' },
                  { name:'华特气体', code:'688268', cat:'材料', growth:'—', pe:'—', rec:'WATCH', logic:'电子特气龙头·新增' },
                  { name:'至纯科技', code:'603690', cat:'设备', growth:'—', pe:'—', rec:'WATCH', logic:'湿法清洗·竞争格局次于盛美' },
                  { name:'江丰电子', code:'300666', cat:'材料', growth:'—', pe:'—', rec:'WATCH', logic:'靶材龙头·新增' },
                  { name:'深科技', code:'000021', cat:'封测', growth:'—', pe:'—', rec:'WATCH', logic:'沛顿科技为长鑫最大委外封测供应商' },
                  { name:'广钢气体', code:'688548', cat:'材料', growth:'—', pe:'—', rec:'WATCH', logic:'电子特气国产替代' },
                  { name:'雅克科技', code:'002409', cat:'材料', growth:'—', pe:'—', rec:'WATCH', logic:'前驱体/绝缘膜' },
                  { name:'柏诚股份', code:'601133', cat:'设备', growth:'—', pe:'—', rec:'WATCH', logic:'洁净室工程' },
                  { name:'亚翔集成', code:'603929', cat:'设备', growth:'—', pe:'—', rec:'WATCH', logic:'洁净室工程' },
                  { name:'合肥城建', code:'002208', cat:'参股', growth:'—', pe:'—', rec:'WATCH', logic:'国资·减持预期' },
                  { name:'美的集团', code:'000333', cat:'参股', growth:'—', pe:'—', rec:'WATCH', logic:'战略投资·弹性有限' },
                  { name:'有研新材', code:'600206', cat:'材料', growth:'—', pe:'—', rec:'CAUTIOUS', logic:'靶材·估值偏高' },
                  { name:'江化微', code:'603078', cat:'材料', growth:'—', pe:'—', rec:'CAUTIOUS', logic:'湿电子化学品·体量小' },
                  { name:'晶瑞电材', code:'300655', cat:'材料', growth:'—', pe:'—', rec:'CAUTIOUS', logic:'湿电子化学品·新增' },
                  { name:'百合集团', code:'601816', cat:'参股', growth:'—', pe:'—', rec:'CAUTIOUS', logic:'财务投资·关联度低' },
                  { name:'上峰水泥', code:'000672', cat:'参股', growth:'—', pe:'—', rec:'CAUTIOUS', logic:'间接持股0.16%·新增' },
                ].map((r, i) => {
                  const a = ASSESSMENT[r.rec];
                  return (
                    <tr key={i} style={{ borderTop: i > 0 ? '1px solid var(--border-color)' : 'none' }}>
                      <td className="py-1 px-2 font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</td>
                      <td className="py-1 px-2" style={{ color: 'var(--text-muted)' }}>{r.code}</td>
                      <td className="py-1 px-2" style={{ color: 'var(--text-secondary)' }}>{r.cat}</td>
                      <td className="py-1 px-2 text-right font-medium" style={{ color: '#1D9E75' }}>{r.growth || '—'}</td>
                      <td className="py-1 px-2 text-right" style={{ color: r.pe === '—' ? 'var(--text-muted)' : '#f59e0b' }}>{r.pe}</td>
                      <td className="py-1 px-2 text-center">
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-medium" style={{ background: a.bg, color: a.color, border: `0.5px solid ${a.color}40` }}>
                          {a.label}
                        </span>
                      </td>
                      <td className="py-1 px-2 text-[10px] leading-relaxed" style={{ color: 'var(--text-secondary)' }}>{r.logic}</td>
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
            ① 周期风险：存储行业历史上呈 3-4 年周期波动，当前处于超级上行周期，价格已从底部上涨 2300%，未来 6-12 个月供需格局逆转概率不可忽视。
            ② 国产替代预期差：长鑫科技技术制程（DDR5/LPDDR5）落后三星/SK 海力士 1-2 代，HBM3E 尚未量产，实际竞争力有待验证。
            ③ 科创解禁压力：发行 10% 流通股本，战略配售 50%，24/36 个月解禁后压力显著。
            ④ 整体估值高位：板块 PE 普遍 30-170×，需警惕戴维斯双杀（业绩不及预期+估值压缩）。
            <br /><br /><strong>免责声明：本页面所有分析结论仅供研究参考，不构成个人投资建议。股票投资有风险，入市需谨慎。</strong>
          </div>
        </div>
      </div>

      {/* ===== 底部 ===== */}
      <div className="text-center text-[10px] py-1" style={{ color: 'var(--text-muted)' }}>
        数据来源：新浪财经实时行情 · 长鑫科技招股说明书 · 私募排排网概念股整理
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
