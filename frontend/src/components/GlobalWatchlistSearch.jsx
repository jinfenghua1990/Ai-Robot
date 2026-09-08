import { useState, useRef, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import TradeModal from './trading/TradeModal';
import { useTrading } from '../context/tradingContextCore';
import { openStockAnalysis } from '../utils/openStockAnalysis';

// 三市场标签 + 颜色
const META = {
  'a-stock': { label: 'A', bg: 'rgba(239,68,68,0.12)', fg: '#ef4444', name: '沪深' },
  hk:        { label: '港', bg: 'rgba(249,115,22,0.12)', fg: '#f97316', name: '港股' },
  us:        { label: '美', bg: 'rgba(59,130,246,0.12)', fg: '#3b82f6', name: '美股' },
};

/**
 * 顶栏全局自选搜索框（跨市场：A 股 + 港股 + 美股 合并去重）
 * - 输入即并行调三个搜索接口，合并去重（最多 8 条）
 * - 每条候选前面带市场标签 A / 港 / 美
 * - 点候选主体：跳转到对应市场自选页并过滤
 * - 点 ⭐自选按钮：按市场调对应 add 端点加入自选
 */
export default function GlobalWatchlistSearch() {
  const navigate = useNavigate();
  const { executeTrade } = useTrading();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);   // [{ market, code, name, ts_code, sector }]
  const [showResults, setShowResults] = useState(false);
  const [loading, setLoading] = useState(false);
  const [justAdded, setJustAdded] = useState(''); // `${market}|${code}`
  const [buyTarget, setBuyTarget] = useState(null); // {code, name, market} 准备打开买入弹窗
  const debounceRef = useRef(null);
  const containerRef = useRef(null);

  // 搜索防抖：并行调三个端点，按 (market+code) 合并去重
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = query.trim();
    if (trimmed.length < 1) { setResults([]); setShowResults(false); return; }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      const tasks = [
        apiFetch(`/api/trading/search?q=${encodeURIComponent(trimmed)}`).then(r => (r.ok ? r.data?.results || [] : []).map(x => ({ ...x, market: 'a-stock' }))),
        apiFetch(`/api/us-quant/watchlist/search?market=HK&q=${encodeURIComponent(trimmed)}`).then(r => (r.ok ? r.data?.results || [] : []).map(x => ({ ...x, market: 'hk' }))),
        apiFetch(`/api/us-quant/watchlist/search?market=US&q=${encodeURIComponent(trimmed)}`).then(r => (r.ok ? r.data?.results || [] : []).map(x => ({ ...x, market: 'us' }))),
      ];
      try {
        const groups = await Promise.allSettled(tasks);
        const merged = [];
        const seen = new Set();
        for (const g of groups) {
          const arr = g.status === 'fulfilled' ? g.value : [];
          for (const it of arr) {
            const code = (it.code || it.ts_code?.replace(/\.\w+$/, '') || '').toString();
            const key = `${it.market}|${code}`;
            if (!code || seen.has(key)) continue;
            seen.add(key);
            merged.push({ ...it, code });
          }
        }
        // 排序：A股 → 港股 → 美股；同名 code 一致排前面
        const order = { 'a-stock': 0, hk: 1, us: 2 };
        merged.sort((a, b) => (order[a.market] ?? 9) - (order[b.market] ?? 9));
        setResults(merged.slice(0, 8));
        setShowResults(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) setShowResults(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  // 点击候选主体：按市场跳转到自选页并过滤
  const handleSelect = (item) => {
    setShowResults(false);
    setQuery(`${item.name} (${item.code})`);
    if (item.market === 'a-stock') {
      navigate(`/watchlist?search=${encodeURIComponent(item.code)}`);
    } else {
      // 港美股跳 us-market（usmart Tab 自带搜索过滤）
      navigate(`/us-market?tab=usmart&search=${encodeURIComponent(item.code)}`);
    }
  };

  // ⭐自选：按市场调对应 add 端点
  const addToWatchlist = async (item, e) => {
    e.stopPropagation();
    const code = (item.code || '').toString();
    if (!code) return;
    const key = `${item.market}|${code}`;
    try {
      if (item.market === 'a-stock') {
        await apiFetch('/api/watchlist/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ stockCode: code, stockName: item.name, group: '默认' }),
        });
      } else {
        // 港美股：5 位数字归一化
        const symbol = item.market === 'hk' ? code.replace(/\D/g, '').padStart(5, '0') : code.toUpperCase();
        await apiFetch('/api/us-quant/watchlist/add', {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ market: item.market === 'hk' ? 'HK' : 'US', symbol }),
        });
      }
      setJustAdded(key);
      setTimeout(() => setJustAdded(''), 2000);
    } catch { /* silent */ }
  };

  // 🛒买入：A 股弹交易弹窗，港/美股跳转到统一个股分析页
  const handleBuy = (item, e) => {
    e.stopPropagation();
    if (item.market === 'a-stock') {
      setBuyTarget({ code: item.code, name: item.name, market: 'a-stock' });
    } else {
      const sym = item.market === 'hk' ? item.code.replace(/\D/g, '').padStart(5, '0') : item.code;
      openStockAnalysis(sym, 'us');
    }
  };

  return (
    <div ref={containerRef} className="relative flex items-center">
      <span className="absolute left-1.5 text-[11px] pointer-events-none" style={{ color: 'var(--text-muted)' }}>🔍</span>
      <input
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        onFocus={() => results.length > 0 && setShowResults(true)}
        placeholder="代码/名称(全市场)"
        className="pl-5 pr-4 py-1 rounded-lg border text-[11px] outline-none w-28 focus:w-48 transition-all"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
      />
      {query && (
        <button
          onClick={() => { setQuery(''); setResults([]); setShowResults(false); }}
          className="absolute right-1 w-3.5 h-3.5 flex items-center justify-center rounded-full text-[11px] leading-none"
          style={{ color: 'var(--text-muted)', background: 'var(--bg-surface)' }}
          title="清除搜索"
        >×</button>
      )}

      {/* 候选下拉 */}
      {showResults && (results.length > 0 || loading) && (
        <div className="absolute top-full right-0 mt-1 rounded-md border overflow-hidden z-50 max-h-80 overflow-y-auto w-[26rem]"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          {loading && <div className="px-3 py-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>搜索中...</div>}
          {!loading && results.map(r => {
            const meta = META[r.market];
            const added = justAdded === `${r.market}|${r.code}`;
            return (
              <div key={`${r.market}|${r.code}`} className="flex items-center px-2 py-1.5 text-[11px] gap-1.5"
                style={{ borderBottom: '1px solid var(--border-color)' }}>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold flex-shrink-0"
                  style={{ background: meta.bg, color: meta.fg }}>{meta.label}</span>
                <button onClick={() => handleSelect(r)} className="flex-1 flex items-center justify-between text-left gap-2 min-w-0" title="点选跳转">
                  <span className="truncate font-bold" style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                  <span className="flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{r.code}{r.sector && ` · ${r.sector}`}</span>
                </button>
                <button onClick={(e) => addToWatchlist(r, e)}
                  className="px-1.5 py-0.5 rounded text-[10px] flex-shrink-0"
                  style={{ background: added ? 'rgba(34,197,94,0.15)' : 'rgba(234,179,8,0.1)', color: added ? '#22c55e' : '#eab308' }}
                  title={`加入${meta.name}自选`}>
                  {added ? '✓已加入' : '⭐'}
                </button>
                {/* A 股弹交易弹窗，港美股进入统一个股分析页 */}
                <button onClick={(e) => handleBuy(r, e)}
                  className="px-1.5 py-0.5 rounded text-[10px] flex-shrink-0 font-bold"
                  style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}
                  title={r.market === 'a-stock' ? `买入 ${r.name}` : `查看 ${r.name} 详情`}>
                  {r.market === 'a-stock' ? '🛒买' : '→详情'}
                </button>
              </div>
            );
          })}
          {!loading && results.length === 0 && (
            <div className="px-3 py-2 text-[11px]" style={{ color: 'var(--text-muted)' }}>无匹配，输入「688」「茅台」「00700」「AAPL」试试</div>
          )}
        </div>
      )}
      {/* A 股买入弹窗 */}
      {buyTarget && (
        <TradeModal
          stockCode={buyTarget.code}
          stockName={buyTarget.name}
          type="buy"
          positionCount={0}
          onClose={() => setBuyTarget(null)}
          onConfirm={executeTrade}
        />
      )}
    </div>
  );
}
