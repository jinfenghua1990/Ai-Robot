import { useState, useRef, useEffect } from 'react';
import TradeModal from './TradeModal';
import { useTrading } from '../../context/TradingContext';
import { apiFetch } from '../../utils/request';

/**
 * 手动输入股票买入栏
 * 支持代码(000001)或中文名(平安银行)双模式搜索
 */
export default function ManualTradeBar({ children }) {
  const { executeTrade } = useTrading();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [showResults, setShowResults] = useState(false);
  const [loading, setLoading] = useState(false);
  const [selected, setSelected] = useState(null); // {code, name, ts_code}
  const [modalOpen, setModalOpen] = useState(false);
  const debounceRef = useRef(null);
  const containerRef = useRef(null);

  // 搜索防抖
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (query.trim().length < 1) {
      setResults([]);
      return;
    }
    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const { ok, data } = await apiFetch(`/api/trading/search?q=${encodeURIComponent(query.trim())}`);
        if (!ok) { setResults([]); return; }
        setResults(data.results || []);
        setShowResults(true);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  // 点击外部关闭结果
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setShowResults(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  const handleSelect = (item) => {
    setSelected(item);
    setQuery(`${item.name} (${item.code})`);
    setShowResults(false);
    setModalOpen(true);
  };

  // 直接输入6位代码回车
  const handleKeyDown = (e) => {
    if (e.key === 'Enter') {
      const code6 = query.trim().replace(/\D/g, '');
      if (code6.length === 6) {
        // 直接用6位代码
        const suffix = code6[0] === '6' || code6[0] === '9' ? '.SH' : '.SZ';
        handleSelect({ code: code6, name: code6, ts_code: code6 + suffix });
      } else if (results.length > 0) {
        handleSelect(results[0]);
      }
    }
  };

  const [justAdded, setJustAdded] = useState('');
  const addToWatchlist = async (item) => {
    const code = item.code || item.ts_code?.replace(/\.\w+$/, '');
    if (!code) return;
    try {
      await apiFetch('/api/watchlist/add', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stockCode: code, stockName: item.name, group: '默认' })
      });
      setJustAdded(code);
      setTimeout(() => setJustAdded(''), 2000);
    } catch (e) { /* silent */ }
  };

  return (
    <>
      <div ref={containerRef} className="relative flex items-center gap-2 px-3 py-2 rounded-lg border flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <span className="text-sm font-medium flex-shrink-0" style={{ color: 'var(--text-primary)' }}>🔍 手动买入</span>
        <div className="relative w-64 max-w-[16rem]">
          <input
            type="text"
            value={query}
            onChange={e => { setQuery(e.target.value); setSelected(null); }}
            onKeyDown={handleKeyDown}
            onFocus={() => results.length > 0 && setShowResults(true)}
            placeholder="输入代码或名称（如 000001 / 平安银行）"
            className="w-full px-3 py-1.5 rounded-md text-sm outline-none"
            style={{ background: 'var(--bg-surface)', color: 'var(--text-primary)', border: '1px solid var(--border-color)' }}
          />
          {/* 搜索结果下拉 */}
          {showResults && (results.length > 0 || loading) && (
            <div className="absolute top-full left-0 right-0 mt-1 rounded-md border overflow-hidden z-50 max-h-72 overflow-y-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              {loading && <div className="px-3 py-2 text-xs" style={{ color: 'var(--text-muted)' }}>搜索中...</div>}
              {!loading && results.map(r => {
                const c = r.code || r.ts_code?.replace(/\.\w+$/, '');
                const added = justAdded === c;
                return (
                  <div key={r.ts_code} className="flex items-center px-3 py-2 text-sm" style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <button onClick={() => handleSelect(r)} className="flex-1 flex items-center justify-between text-left" title="点击买入">
                      <span style={{ color: 'var(--text-primary)' }}>{r.name}</span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{r.code} {r.sector && `· ${r.sector}`}</span>
                    </button>
                    <button onClick={(e) => { e.stopPropagation(); addToWatchlist(r); }}
                      className="ml-2 px-2 py-0.5 rounded text-xs flex-shrink-0"
                      style={{ background: added ? 'rgba(34,197,94,0.15)' : 'rgba(234,179,8,0.1)', color: added ? '#22c55e' : '#eab308' }}
                      title="加入自选股">
                      {added ? '✓已加入' : '⭐自选'}
                    </button>
                  </div>
                );
              })}
            </div>
          )}
        </div>
        {selected && (
          <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6)' }}>
            已选: {selected.name} {selected.code}
          </span>
        )}
        {/* 右侧工具栏插槽：分组 + 排序 + 批量，横向排开 */}
        {children && (
          <div className="flex items-center gap-2 flex-wrap ml-auto">{children}</div>
        )}
      </div>

      {/* 交易弹窗 */}
      {modalOpen && selected && (
        <TradeModal
          stockCode={selected.code}
          stockName={selected.name}
          type="buy"
          positionCount={0}
          onClose={() => { setModalOpen(false); setQuery(''); setSelected(null); }}
          onConfirm={executeTrade}
        />
      )}
    </>
  );
}
