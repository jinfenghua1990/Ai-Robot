import { useState, useEffect, useMemo, useRef } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import SignalCard from '../components/trading/SignalCard';
import { fmtFlow } from '../utils/format';
import { apiFetch } from '../utils/request';

const PAGE_SIZE = 20;

const DIM_COLORS = {
  shadow: '#ef4444',     // 下影线 - 红
  change: '#eab308',     // 涨幅 - 黄
  volume: '#3b82f6',     // 缩量 - 蓝
  rsi: '#a855f7',        // RSI - 紫
  deviation: '#22c55e',  // 偏离度 - 绿
};

const STRATEGIES = [
  { key: 'heat', label: '热度综合', desc: '板块热度 Top 5 + 突破/加速阶段 + 主力净流入', icon: '🔥' },
  { key: 'baihu', label: '白虎V3.0', desc: '双模式选股：缩量回踩守20日线 / 放量突破不破5/10日线，5维度评分≥5分入选，全市场', icon: '🐯' },
  { key: 'liangjia', label: '白虎V4.0', desc: '5种形态分类 + 3层分层（优先买入/等回踩/暂不参与）+ 交易计划', icon: '🐯' },
  { key: 'qinglong', label: '青龙', desc: 'MA10主升浪回踩策略', icon: '🐉' },
  { key: 'zhushenglang', label: '主升浪', desc: 'MA多头排列+主力资金流入，主升浪趋势选股', icon: '🚀' },
  { key: 'wave_band', label: '波段信号', desc: 'MA多头排列+回踩MA10缩量 / 放量突破MA20，RSI6+量比买卖点', icon: '🌊' },
];

export default function ScreenerPage({ initialStrategy, hideStrategySelector }) {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [strategy, setStrategy] = useState(initialStrategy || 'heat');
  const [backfilling, setBackfilling] = useState(false);
  const [message, setMessage] = useState(null);
  // 白虎V3.0筛选
  const [sectorFilter, setSectorFilter] = useState('全部');
  const [searchText, setSearchText] = useState('');
  const [currentPage, setCurrentPage] = useState(0);
  // 白虎V3.0独立数据
  const [baihuData, setBaihuData] = useState(null);
  const [baihuLoading, setBaihuLoading] = useState(false);
  // 量价报告独立数据
  const [liangjiaData, setLiangjiaData] = useState(null);
  const [liangjiaLoading, setLiangjiaLoading] = useState(false);
  const [liangjiaTier, setLiangjiaTier] = useState('priority');
  // 防止重复请求：记录已请求的 date+strategy
  const fetchedRef = useRef('');
  // 妙想智能选股（自然语言）
  const [mxQuery, setMxQuery] = useState('');
  const [mxResults, setMxResults] = useState(null);
  const [mxLoading, setMxLoading] = useState(false);
  const [mxError, setMxError] = useState(null);
  // 多因子量化选股
  const [mfPeMax, setMfPeMax] = useState('30');
  const [mfRoeMin, setMfRoeMin] = useState('5');
  const [mfGmMin, setMfGmMin] = useState('');
  const [mfInstMin, setMfInstMin] = useState('');
  const [mfNetInflow, setMfNetInflow] = useState('');
  const [mfSector, setMfSector] = useState('');
  const [mfMarket, setMfMarket] = useState('');
  const [mfSortBy, setMfSortBy] = useState('score');
  const [mfLimit, setMfLimit] = useState(20);
  const [mfResults, setMfResults] = useState(null);
  const [mfLoading, setMfLoading] = useState(false);
  const [mfError, setMfError] = useState(null);
  // 妙想选股示例
  const MX_EXAMPLES = [
    '股价大于10元的A股',
    '半导体板块成分股',
    '低PE高ROE的股票',
    '近5日涨幅超过10%的创业板股',
    '市值小于100亿的科创板股',
  ];

  const handleMxXuangu = async (e) => {
    e?.preventDefault();
    const q = mxQuery.trim();
    if (!q) { setMxError('请输入选股条件'); return; }
    setMxLoading(true); setMxError(null); setMxResults(null);
    try {
      const { ok, data, error } = await apiFetch('/api/mx/xuangu', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });
      if (!ok) setMxError(error || '请求失败');
      else if (data?.detail) setMxError(data.detail);
      else if (data?.error) setMxError(data.error);
      else setMxResults(data);
    } catch (err) {
      setMxError('请求失败: ' + err.message);
    }
    setMxLoading(false);
  };

  // 多因子量化选股
  const handleMfFilter = async (e) => {
    e?.preventDefault();
    setMfLoading(true); setMfError(null); setMfResults(null);
    try {
      const params = new URLSearchParams();
      if (mfPeMax) params.set('pe_max', mfPeMax);
      if (mfRoeMin) params.set('roe_min', mfRoeMin);
      if (mfGmMin) params.set('gm_min', mfGmMin);
      if (mfInstMin) params.set('inst_min', mfInstMin);
      if (mfNetInflow) params.set('net_inflow_min', mfNetInflow);
      if (mfSector) params.set('sector', mfSector);
      if (mfMarket) params.set('market', mfMarket);
      params.set('sort_by', mfSortBy);
      params.set('limit', mfLimit);
      const { ok, data, error } = await apiFetch(`/api/screener/filter?${params.toString()}`);
      if (!ok) setMfError(error || '请求失败');
      else setMfResults(data);
    } catch (err) {
      setMfError('请求失败: ' + err.message);
    }
    setMfLoading(false);
  };

  // 多因子自动加载（页面打开时先跑一次默认条件）
  const mfAutoRef = useRef(false);
  useEffect(() => {
    if (mfAutoRef.current) return;
    mfAutoRef.current = true;
    setTimeout(() => handleMfFilter(), 100); // 稍延后让页面渲染优先级优先
  }, []);

  // 主数据请求（只在 date+strategy 变化时触发一次）
  useEffect(() => {
    if (!selectedDate) return;
    const key = `${selectedDate}_${strategy}`;
    if (fetchedRef.current === key && data) return; // 已有数据则不重复请求
    fetchedRef.current = key;
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    (async () => {
      const { ok, data: d, error } = await apiFetch(`/api/screener?strategy=${strategy}&date=${selectedDate}`, { signal: controller.signal });
      if (!ok) {
        // 忽略 AbortError（组件卸载或依赖变化时取消）
        if (/abort/i.test(error || '')) return;
        setError('数据加载失败');
        setLoading(false);
        return;
      }
      setData(d);
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, strategy]);

  // 白虎V3.0独立请求
  useEffect(() => {
    if (strategy !== 'baihu' || !selectedDate) return;
    if (baihuData && baihuData.date === selectedDate) return; // 已有数据
    setBaihuLoading(true);
    const controller = new AbortController();
    (async () => {
      const { ok, data: d, error } = await apiFetch(`/api/baihu-screen?date=${selectedDate}`, { signal: controller.signal });
      if (!ok) {
        // 忽略 AbortError
        if (/abort/i.test(error || '')) return;
        setBaihuData(null);
        setBaihuLoading(false);
        return;
      }
      setBaihuData(d);
      setBaihuLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, strategy]);

  // 量价报告独立请求
  useEffect(() => {
    if (strategy !== 'liangjia' || !selectedDate) return;
    if (liangjiaData && liangjiaData.date === selectedDate) return;
    setLiangjiaLoading(true);
    const controller = new AbortController();
    (async () => {
      const { ok, data: d, error } = await apiFetch(`/api/liangjia-report?date=${selectedDate}`, { signal: controller.signal });
      if (!ok) {
        if (/abort/i.test(error || '')) return;
        setLiangjiaData(null);
        setLiangjiaLoading(false);
        return;
      }
      setLiangjiaData(d);
      setLiangjiaLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, strategy]);

  useEffect(() => { setCurrentPage(0); setSectorFilter('全部'); setSearchText(''); }, [strategy, selectedDate]);

  const handleBackfill = async () => {
    const token = prompt('请输入采集令牌:');
    if (!token) return;
    setBackfilling(true);
    setMessage(null);
    try {
      const { ok, data: result, error } = await apiFetch(`/api/backfill?date=${selectedDate}&token=${encodeURIComponent(token)}`, { method: 'POST' });
      if (!ok) {
        throw new Error(error || '补充采集失败');
      }
      setMessage({ type: 'success', text: result?.message || '补充采集完成' });
      setLoading(true);
      const { ok: ok2, data: d } = await apiFetch(`/api/screener?strategy=${strategy}&date=${selectedDate}`);
      if (ok2) { setData(d); setLoading(false); }
    } catch (e) {
      setMessage({ type: 'error', text: '补充采集失败：' + e.message });
    }
    setBackfilling(false);
  };

  // 白虎V3.0筛选逻辑（适配 enriched signal 数据结构）
  const sectorList = useMemo(() => {
    if (!baihuData?.stocks) return [];
    const counts = {};
    baihuData.stocks.forEach(s => { counts[s.sector] = (counts[s.sector] || 0) + 1; });
    return Object.entries(counts).sort((a, b) => b[1] - a[1]);
  }, [baihuData]);

  const filteredBaihuStocks = useMemo(() => {
    if (!baihuData?.stocks) return [];
    let result = baihuData.stocks;
    if (sectorFilter !== '全部') result = result.filter(s => s.sector === sectorFilter);
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      result = result.filter(s =>
        s.secCode?.toLowerCase().includes(q) ||
        s.secName?.toLowerCase().includes(q) ||
        s.sector?.toLowerCase().includes(q)
      );
    }
    return result;
  }, [baihuData, sectorFilter, searchText]);

  const totalPages = Math.ceil(filteredBaihuStocks.length / PAGE_SIZE);
  const pagedBaihuStocks = filteredBaihuStocks.slice(currentPage * PAGE_SIZE, (currentPage + 1) * PAGE_SIZE);

  if (!selectedDate) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        正在获取交易日期...
      </div>
    );
  }

  const formula = baihuData?.formula;
  const dimensions = formula?.dimensions || [];
  const maxScore = formula?.max_score || 10;
  const passThreshold = formula?.pass_threshold || 6;

  return (
    <div className="space-y-4">
      {/* 标题 + 日期导航 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          智能选股
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
        </h2>
        <div className="flex items-center gap-2">
          <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate}
            extra={<button
              onClick={handleBackfill}
              disabled={backfilling}
              className="px-3 py-1.5 rounded-lg text-sm border transition-all"
              style={{ borderColor: 'var(--accent-blue)', color: '#fff', background: 'var(--accent-blue)', opacity: backfilling ? 0.6 : 1 }}
            >
              {backfilling ? '采集中...' : '手动采集'}
            </button>}
          />
        </div>
      </div>

      {/* 错误提示（内联，不阻断页面） */}
      {error && (
        <div className="rounded-lg p-3 flex items-center justify-between" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <span className="text-sm" style={{ color: '#ef4444' }}>{error}</span>
          <button onClick={() => { setError(null); fetchedRef.current = ''; setSelectedDate(selectedDate); }} className="px-3 py-1 rounded text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>重试</button>
        </div>
      )}

      {/* 说明卡片（始终展开） */}
      <div>
        <div className="text-sm mb-2"><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 选股策略说明</div>
        <div className="space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
          <div><strong style={{ color: 'var(--text-primary)' }}>热度综合：</strong>板块热度Top5 + 突破/加速阶段龙头 + 主力净流入排序</div>
          <div><strong style={{ color: 'var(--text-primary)' }}>白虎V3.0：</strong>双模式选股：缩量回踩守20日线 / 放量突破不破5/10日线，5维度评分≥5分入选，全市场</div>
          <div><strong style={{ color: 'var(--text-primary)' }}>青龙：</strong>MA10主升浪回踩策略</div>
          <div><strong style={{ color: '#ef4444' }}>红色</strong>=上涨/流入，<strong style={{ color: '#22c55e' }}>绿色</strong>=下跌/流出（A股习惯）</div>
          <div><strong style={{ color: 'var(--text-primary)' }}>注意：</strong>筛选结果仅供参考，不构成投资建议</div>
        </div>
      </div>

      {/* 妙想智能选股（自然语言） */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(234,179,8,0.4)' }}>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            🧠 妙想智能选股
            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.15)', color: '#eab308' }}>自然语言</span>
          </h3>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>东方财富妙想 · 付费API</span>
        </div>
        <form onSubmit={handleMxXuangu} className="flex gap-2 mb-2">
          <input
            type="text"
            value={mxQuery}
            onChange={e => setMxQuery(e.target.value)}
            placeholder="输入自然语言选股条件，如「股价大于10元的A股」「半导体板块成分股」"
            className="flex-1 px-3 py-1.5 rounded-lg border text-sm outline-none"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
          />
          <button
            type="submit"
            disabled={mxLoading}
            className="px-4 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap"
            style={{ background: mxLoading ? 'rgba(234,179,8,0.4)' : '#eab308', color: '#fff', opacity: mxLoading ? 0.7 : 1 }}
          >
            {mxLoading ? '查询中...' : '🔍 选股'}
          </button>
        </form>
        <div className="flex flex-wrap gap-1 mb-2">
          {MX_EXAMPLES.map(ex => (
            <button key={ex} onClick={() => setMxQuery(ex)}
              className="px-2 py-0.5 rounded text-[11px] border transition-all hover:bg-opacity-20"
              style={{ borderColor: 'rgba(234,179,8,0.3)', color: 'var(--text-secondary)', background: 'rgba(234,179,8,0.05)' }}>
              {ex}
            </button>
          ))}
        </div>

        {mxError && (
          <div className="rounded p-2 text-xs mb-2" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>⚠ {mxError}</div>
        )}

        {mxResults && (
          <div>
            <div className="text-xs mb-2" style={{ color: 'var(--text-muted)' }}>
              查询: <strong style={{ color: 'var(--text-primary)' }}>{mxResults.query}</strong>
              {' · '}共 <strong style={{ color: '#ef4444' }}>{mxResults.count}</strong> 只
              {mxResults.data_source && ` · 来源: ${mxResults.data_source}`}
            </div>
            {mxResults.rows && mxResults.rows.length > 0 ? (
              <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10">
                    <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                      {mxResults.columns.map(col => (
                        <th key={col} className="text-left py-2 px-3 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{col}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {mxResults.rows.map((row, i) => (
                      <tr key={i} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                        {mxResults.columns.map(col => (
                          <td key={col} className="py-2 px-3 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{row[col] ?? '-'}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-6 text-sm" style={{ color: 'var(--text-muted)' }}>未找到符合条件的数据</div>
            )}
          </div>
        )}
      </div>

      {/* 多因子量化选股（免费F10数据） */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(99,102,241,0.4)' }}>
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
            📊 多因子量化选股
            <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(99,102,241,0.15)', color: '#818cf8' }}>免费F10</span>
            <span className="ml-1 px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>PG缓存</span>
          </h3>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>Tushare + 东方财富 · 本地缓存</span>
        </div>
        <form onSubmit={handleMfFilter}>
          <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2 mb-2">
            <input type="number" step="0.1" placeholder="PE上限" value={mfPeMax} onChange={e => setMfPeMax(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
            <input type="number" step="0.1" placeholder="ROE(%)下限" value={mfRoeMin} onChange={e => setMfRoeMin(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
            <input type="number" step="0.1" placeholder="毛利率(%)下限" value={mfGmMin} onChange={e => setMfGmMin(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
            <input type="number" step="0.1" placeholder="机构占比(%)下限" value={mfInstMin} onChange={e => setMfInstMin(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
            <input type="text" placeholder="主力净流入(元)" value={mfNetInflow} onChange={e => setMfNetInflow(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
          </div>
          <div className="flex flex-wrap gap-2 items-center mb-3">
            <input type="text" placeholder="行业(模糊匹配)" value={mfSector} onChange={e => setMfSector(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none w-28" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }} />
            <select value={mfMarket} onChange={e => setMfMarket(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}>
              <option value="">全部板块</option>
              <option value="主板">主板</option>
              <option value="创业板">创业板</option>
              <option value="科创板">科创板</option>
              <option value="北交所">北交所</option>
            </select>
            <select value={mfSortBy} onChange={e => setMfSortBy(e.target.value)}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}>
              <option value="score">综合评分↓</option>
              <option value="pe">PE低→高</option>
              <option value="roe">ROE高→低</option>
              <option value="gross_margin">毛利率高→低</option>
              <option value="inst_hold">机构占比高→低</option>
              <option value="net_inflow">主力净流入↓</option>
            </select>
            <select value={mfLimit} onChange={e => setMfLimit(Number(e.target.value))}
              className="px-2 py-1 rounded border text-xs outline-none" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}>
              <option value={20}>20只</option>
              <option value={50}>50只</option>
              <option value={100}>100只</option>
              <option value={200}>200只</option>
            </select>
            <button type="submit" disabled={mfLoading}
              className="px-4 py-1.5 rounded-lg text-xs font-medium whitespace-nowrap"
              style={{ background: mfLoading ? 'rgba(99,102,241,0.4)' : '#6366f1', color: '#fff', opacity: mfLoading ? 0.7 : 1 }}>
              {mfLoading ? '筛选中...' : '🔍 筛选'}
            </button>
          </div>
        </form>

        {mfError && (
          <div className="rounded p-2 text-xs mb-2" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>⚠ {mfError}</div>
        )}

        {mfResults && (
          <div>
            <div className="text-xs mb-2" style={{ color: 'var(--text-muted)' }}>
              共 <strong style={{ color: '#6366f1' }}>{mfResults.count}</strong> 只候选
              {mfResults.results?.length < mfResults.count && ` · 显示前 ${mfResults.results?.length} 只`}
            </div>
            {mfResults.results?.length > 0 ? (
              <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                <table className="w-full text-xs">
                  <thead className="sticky top-0 z-10">
                    <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                      <th className="text-left py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>代码</th>
                      <th className="text-left py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>名称</th>
                      <th className="text-left py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>行业</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>PE</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>ROE%</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>毛利率%</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>机构占比%</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>主力净流入</th>
                      <th className="text-right py-2 px-2 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>评分</th>
                    </tr>
                  </thead>
                  <tbody>
                    {mfResults.results.map((r, i) => (
                      <tr key={i} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                        <td className="py-1.5 px-2 whitespace-nowrap" style={{ color: 'var(--text-primary)' }}>{r.ts_code}</td>
                        <td className="py-1.5 px-2 whitespace-nowrap font-medium" style={{ color: 'var(--text-primary)' }}>{r.name}</td>
                        <td className="py-1.5 px-2 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{r.industry}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap" style={{ color: r.pe_ttm != null && r.pe_ttm < 15 ? '#22c55e' : 'var(--text-secondary)' }}>{r.pe_ttm?.toFixed(1) ?? '-'}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap" style={{ color: r.roe != null ? '#22c55e' : 'var(--text-secondary)' }}>{r.roe?.toFixed(1) ?? '-'}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{r.gross_margin?.toFixed(1) ?? '-'}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{r.inst_hold_ratio?.toFixed(2) ?? '-'}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap" style={{ color: r.main_net_inflow != null && r.main_net_inflow > 0 ? '#ef4444' : 'var(--text-secondary)' }}>{r.main_net_inflow != null ? fmtFlow(r.main_net_inflow) : '-'}</td>
                        <td className="py-1.5 px-2 text-right whitespace-nowrap font-bold" style={{ color: r.score != null ? '#818cf8' : 'var(--text-secondary)' }}>{r.score?.toFixed(3) ?? '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-center py-6 text-sm" style={{ color: 'var(--text-muted)' }}>未找到符合条件的股票</div>
            )}
          </div>
        )}
      </div>

      {/* 消息提示 */}
      {message && (
        <div className="rounded-lg border px-3 py-2 text-sm" style={{
          borderColor: message.type === 'error' ? 'rgba(239,68,68,0.3)' : 'rgba(34,197,94,0.3)',
          background: message.type === 'error' ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)',
          color: message.type === 'error' ? '#ef4444' : '#22c55e',
        }}>
          {message.text}
        </div>
      )}

      {/* 策略选择 */}
      {!hideStrategySelector && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {STRATEGIES.map(s => (
            <button
              key={s.key}
              onClick={() => setStrategy(s.key)}
              className="rounded-lg border p-3 text-left transition-all"
              style={{
                borderColor: strategy === s.key ? 'var(--accent-blue)' : 'var(--border-color)',
                background: strategy === s.key ? 'var(--accent-blue)' + '15' : 'var(--bg-card)',
              }}
            >
              <div className="font-medium text-sm mb-1" style={{ color: strategy === s.key ? 'var(--accent-blue)' : 'var(--text-primary)' }}>
                {s.icon} {s.label}
              </div>
              <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{s.desc}</div>
            </button>
          ))}
        </div>
      )}

      {/* ===== 热度综合/青龙：板块资金流 + 龙头趋势阶段 + 选股结果 ===== */}
      {strategy !== 'baihu' && (
        <>
          {/* 热门板块 */}
          {data?.top_sectors && data.top_sectors.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>热门板块 Top 5</h3>
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {data.top_sectors.map((s, i) => (
                  <div key={i} className="rounded-lg p-3 text-center" style={{ background: 'var(--bg-surface)' }}>
                    <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>#{i + 1}</div>
                    <div className="text-sm font-medium mb-1" style={{ color: 'var(--text-primary)' }}>{s.name}</div>
                    <div className="text-xs" style={{ color: 'var(--accent-amber)' }}>热度 {s.heat_score?.toFixed(1)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* 板块资金流 Top 10 */}
          {data?.sector_flows && data.sector_flows.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>板块资金流 Top 10</h3>
              <div className="overflow-x-auto max-h-[480px] overflow-y-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10">
                    <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                      <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>排名</th>
                      <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>板块</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>净流入</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>主力流入</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>涨停数</th>
                      <th className="text-right py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>热度</th>
                      <th className="text-left py-2 px-3 font-medium" style={{ color: 'var(--text-secondary)' }}>龙头股</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.sector_flows.slice(0, 10).map((s, i) => (
                      <tr key={i} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                        <td className="py-2 px-3 font-mono" style={{ color: 'var(--text-muted)' }}>#{i + 1}</td>
                        <td className="py-2 px-3" style={{ color: 'var(--text-primary)' }}>{s.sector}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: s.net_flow >= 0 ? '#ef4444' : '#22c55e' }}>
                          {s.net_flow >= 0 ? '+' : ''}{fmtFlow(s.net_flow || 0)}
                        </td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{fmtFlow(s.money_inflow || 0)}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--accent-amber)' }}>{s.limit_up_count}</td>
                        <td className="py-2 px-3 text-right font-mono" style={{ color: 'var(--text-secondary)' }}>{s.heat_score?.toFixed(1)}</td>
                        <td className="py-2 px-3" style={{ color: 'var(--text-muted)' }}>{s.leader_stock || '-'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* 龙头趋势阶段 Top 15（SignalCard 统一卡片） */}
          {data?.leaders && data.leaders.length > 0 && (
            <div>
              <h3 className="text-sm font-medium mb-3" style={{ color: 'var(--text-secondary)' }}>龙头趋势阶段 Top 15</h3>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-[600px] overflow-y-auto">
                {data.leaders.slice(0, 15).map((signal, i) => (
                  <SignalCard
                    key={signal.secCode || i}
                    signal={signal}
                    orders={[]}
                    showWatchBtn
                    mode="watchlist"
                    showMarketState
                    showBuyPower
                    showAnalysisButton
                  />
                ))}
              </div>
            </div>
          )}

          {/* 选股结果（热度/青龙） - SignalCard 统一卡片 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>选股结果</h3>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{data?.stocks?.length || 0} 只</span>
            </div>
            {/* 过滤信息 */}
            {data?.filter_info && (
              <div className="mb-3 flex flex-wrap items-center gap-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                <span className="px-1.5 py-0.5 rounded" style={{ background: data.filter_info.mode === 'leader' ? 'rgba(34,197,94,0.1)' : 'rgba(234,179,8,0.1)', color: data.filter_info.mode === 'leader' ? '#22c55e' : '#eab308' }}>
                  {data.filter_info.mode === 'leader' ? '龙头模式' : '降级模式'}
                </span>
                <span>上升趋势板块: <strong style={{ color: 'var(--text-primary)' }}>{data.filter_info.up_trend_sectors}</strong></span>
                <span>·</span>
                <span>候选: <strong style={{ color: 'var(--text-primary)' }}>{data.filter_info.total_candidates}</strong></span>
                <span>→</span>
                <span>精选: <strong style={{ color: '#ef4444' }}>{data.filter_info.filtered}</strong></span>
                <span className="ml-1">|</span>
                {data.filter_info.filters.map((f, i) => (
                  <span key={i} className="px-1 py-0.5 rounded" style={{ background: 'var(--bg-hover)' }}>{f}</span>
                ))}
              </div>
            )}
            {loading ? (
              <div className="flex items-center justify-center h-48 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : data?.stocks && data.stocks.length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2 max-h-[700px] overflow-y-auto">
                {data.stocks.map((signal, i) => (
                  <SignalCard
                    key={signal.secCode || i}
                    signal={signal}
                    orders={[]}
                    showWatchBtn
                    mode="watchlist"
                    showMarketState
                    showBuyPower
                    showAnalysisButton
                  />
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-center h-48 text-sm" style={{ color: 'var(--text-muted)' }}>暂无选股结果，请手动采集数据</div>
            )}
          </div>
        </>
      )}

      {/* ===== 白虎V3.0：5维度评分 + 筛选 + 分页 ===== */}
      {strategy === 'baihu' && (
        <>
          {/* 候选池统计 */}
          {baihuData && (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
              <div className="rounded-lg border p-3 text-center" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="text-2xl font-bold" style={{ color: 'var(--accent-blue)' }}>{baihuData.candidate_count || 0}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>候选池（全市场主力净流入前50）</div>
              </div>
              <div className="rounded-lg border p-3 text-center" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="text-2xl font-bold" style={{ color: '#22c55e' }}>{baihuData.total || 0}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>入选数</div>
              </div>
              <div className="rounded-lg border p-3 text-center" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="text-2xl font-bold" style={{ color: '#f97316' }}>
                  {baihuData.candidate_count ? ((baihuData.total / baihuData.candidate_count) * 100).toFixed(0) : 0}%
                </div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>通过率</div>
              </div>
            </div>
          )}

          {/* 筛选工具栏 */}
          <div className="flex flex-wrap items-center gap-2">
            <input type="text" placeholder="搜索代码 / 名称 / 板块" value={searchText}
              onChange={(e) => setSearchText(e.target.value)}
              className="px-3 py-1.5 rounded-lg border text-sm flex-1 min-w-[180px]"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
            <select value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}
              className="px-3 py-1.5 rounded-lg border text-sm"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
              <option value="全部">全部板块</option>
              {sectorList.map(([sector, count]) => (
                <option key={sector} value={sector}>{sector}（{count}）</option>
              ))}
            </select>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              共 {filteredBaihuStocks.length} 只{sectorFilter !== '全部' ? ` · ${sectorFilter}` : ''}
            </span>
            {(sectorFilter !== '全部' || searchText) && (
              <button onClick={() => { setSectorFilter('全部'); setSearchText(''); }}
                className="px-2 py-1 rounded-lg text-xs border"
                style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
                清除筛选
              </button>
            )}
          </div>

          {/* 白虎V3.0选股结果列表（SignalCard 统一卡片） */}
          <div>
            {baihuLoading ? (
              <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : pagedBaihuStocks.length > 0 ? (
              <>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                  {pagedBaihuStocks.map((signal, idx) => (
                    <SignalCard
                      key={signal.secCode || idx}
                      signal={signal}
                      orders={[]}
                      showWatchBtn
                      mode="watchlist"
                      showMarketState
                      showBuyPower
                      showAnalysisButton
                    />
                  ))}
                </div>
                {totalPages > 1 && (
                  <div className="flex items-center justify-center gap-2 mt-4 pt-3 border-t" style={{ borderColor: 'var(--border-color)' }}>
                    <button onClick={() => setCurrentPage(p => Math.max(0, p - 1))} disabled={currentPage === 0}
                      className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                      style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>上一页</button>
                    <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{currentPage + 1} / {totalPages} 页</span>
                    <button onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))} disabled={currentPage >= totalPages - 1}
                      className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                      style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>下一页</button>
                  </div>
                )}
              </>
            ) : (
              <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
                {baihuData?.stocks?.length > 0 ? '无匹配结果，请调整筛选条件' : '暂无选股结果 — 白虎策略在缩量回踩守20日线或放量突破不破5/10日线时触发，请切换日期查看'}
              </div>
            )}
          </div>

          {/* 白虎V3.0公式说明 */}
          <div>
            <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>白虎 V3.0 策略说明（全市场适配版）</h3>
            <div className="mb-3">
              <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>必过硬门槛（5项全满足）</div>
              <div className="flex flex-wrap gap-2">
                {(formula?.hard_rules || []).map((rule, i) => (
                  <span key={i} className="text-xs px-2 py-1 rounded" style={{ background: 'var(--bg-surface)', color: 'var(--text-secondary)' }}>
                    {i + 1}. {rule}
                  </span>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2 text-xs">
              {dimensions.map(d => (
                <div key={d.key} className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
                  <div className="font-medium" style={{ color: DIM_COLORS[d.key] || 'var(--text-secondary)' }}>
                    {d.name}（{d.max}分）
                  </div>
                  <div style={{ color: 'var(--text-muted)' }}>{d.desc}</div>
                </div>
              ))}
            </div>
            {(formula?.v3_improvements || []).length > 0 && (
              <div className="mt-3">
                <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>V3.0 相比 V2.6 的改进</div>
                <div className="flex flex-wrap gap-2">
                  {formula.v3_improvements.map((imp, i) => (
                    <span key={i} className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>
                      {imp}
                    </span>
                  ))}
                </div>
              </div>
            )}
            <div className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
              及格线：总分 ≥ {passThreshold} 分入选 · 满分 {maxScore} 分 · 回测胜率37%（V2.6为19%）
            </div>
          </div>
        </>
      )}

      {/* ===== 量价报告：3层分层 + 交易计划 ===== */}
      {strategy === 'liangjia' && (
        <>
          {/* 3层分层统计 */}
          {liangjiaData && (
            <div className="grid grid-cols-3 gap-2">
              {[
                { key: 'priority', label: '优先买入', count: liangjiaData.priority_count || 0, color: '#ef4444', desc: '只做条件触发，不追高' },
                { key: 'wait', label: '等回踩确认', count: liangjiaData.wait_count || 0, color: '#f59e0b', desc: '逻辑尚可，位置需优化' },
                { key: 'avoid', label: '暂不参与', count: liangjiaData.avoid_count || 0, color: '#6b7280', desc: '高位、破位或性价比不足' },
              ].map(t => (
                <button key={t.key} onClick={() => setLiangjiaTier(t.key)}
                  className="rounded-lg border p-3 text-center transition-all"
                  style={{
                    borderColor: liangjiaTier === t.key ? t.color : 'var(--border-color)',
                    background: liangjiaTier === t.key ? `${t.color}15` : 'var(--bg-card)',
                    borderWidth: liangjiaTier === t.key ? 2 : 1,
                  }}>
                  <div className="text-2xl font-bold" style={{ color: t.color }}>{t.count}</div>
                  <div className="text-xs mt-1 font-medium" style={{ color: 'var(--text-primary)' }}>{t.label}</div>
                  <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{t.desc}</div>
                </button>
              ))}
            </div>
          )}

          {/* 当前层股票列表 */}
          <div>
            {liangjiaLoading ? (
              <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : (liangjiaData?.groups?.[liangjiaTier] || []).length > 0 ? (
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
                {(liangjiaData.groups[liangjiaTier] || []).map((signal, idx) => (
                  <div key={signal.secCode || idx} className="space-y-1">
                    <SignalCard
                      signal={signal}
                      orders={[]}
                      showWatchBtn
                      mode="watchlist"
                      showMarketState
                      showBuyPower
                      showAnalysisButton
                    />
                    {/* 交易计划展示 */}
                    {signal.tradePlan && (
                      <div className="rounded-lg border p-2 text-xs space-y-1"
                        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-secondary)' }}>
                        <div className="flex items-center gap-2">
                          <span className="px-1.5 py-0.5 rounded font-bold"
                            style={{
                              background: signal.pattern === 'pullback' ? 'rgba(59,130,246,0.12)' :
                                signal.pattern === 'breakout' ? 'rgba(239,68,68,0.12)' :
                                signal.pattern === 'trend' ? 'rgba(168,85,247,0.12)' :
                                signal.pattern === 'repair' ? 'rgba(245,158,11,0.12)' : 'rgba(107,114,128,0.12)',
                              color: signal.pattern === 'pullback' ? '#3b82f6' :
                                signal.pattern === 'breakout' ? '#ef4444' :
                                signal.pattern === 'trend' ? '#a855f7' :
                                signal.pattern === 'repair' ? '#f59e0b' : '#6b7280',
                            }}>
                            {signal.patternDesc || signal.pattern}
                          </span>
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                            5日 {signal.gain5d}% | 量比 {signal.volRatio20}x | 距高点 {signal.distanceToHigh20}%
                          </span>
                        </div>
                        <div style={{ color: 'var(--text-secondary)' }}>
                          <span style={{ color: '#ef4444', fontWeight: 600 }}>买入:</span> {signal.tradePlan.buy}
                        </div>
                        <div style={{ color: 'var(--text-secondary)' }}>
                          <span style={{ color: '#6b7280', fontWeight: 600 }}>止损:</span> {signal.tradePlan.stop}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
                {liangjiaData ? `当前层级无股票，切换其他层级查看` : '暂无数据'}
              </div>
            )}
          </div>

          {/* 白虎V4.0策略说明 */}
          <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'rgba(168,85,247,0.2)' }}>
            <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>🐯 白虎V4.0策略说明（CodeBuddy）</h3>
            <div className="text-xs mb-2" style={{ color: 'var(--text-muted)' }}>
              按 CodeBuddy 量价筛选报告逻辑，5种形态分类 + 3层分层 + 具体交易计划
            </div>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>5种形态分类</div>
                <div className="space-y-1">
                  <div className="text-xs"><span style={{ color: '#3b82f6' }}>缩量回踩:</span> 最低价≤MA20、缩量、收盘守MA20</div>
                  <div className="text-xs"><span style={{ color: '#ef4444' }}>放量突破:</span> 收盘&gt;MA5/MA10、放量、接近20日高点</div>
                  <div className="text-xs"><span style={{ color: '#a855f7' }}>趋势延续:</span> 多头排列、均线结构尚可</div>
                  <div className="text-xs"><span style={{ color: '#f59e0b' }}>缩量修复:</span> 缩量、跌破MA5/MA10、守MA20</div>
                  <div className="text-xs"><span style={{ color: '#6b7280' }}>结构偏弱:</span> 跌破MA20或双线破位</div>
                </div>
              </div>
              <div>
                <div className="text-xs font-medium mb-1" style={{ color: 'var(--text-muted)' }}>执行规则</div>
                <div className="space-y-1">
                  <div className="text-xs">• 开盘高开&gt;3%不追，等回踩不破分时均线</div>
                  <div className="text-xs">• 优先看5/10日线附近缩量承接</div>
                  <div className="text-xs">• 突破型必须放量站上前高或平台上沿</div>
                  <div className="text-xs">• 放量跌破20日线，短线计划失效</div>
                  <div className="text-xs">• 冲高回落且放量，次日不接</div>
                </div>
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
