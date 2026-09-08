import { useState, useRef, useEffect, useCallback } from 'react';
import { apiFetch, formatApiError } from '../../utils/request';

const MARKETS = [
  { key: 'A', label: 'A股', flag: '🇨🇳', placeholder: '例: 000001, 600519' },
  { key: 'HK', label: '港股', flag: '🇭🇰', placeholder: '例: 00700, 09988' },
  { key: 'US', label: '美股', flag: '🇺🇸', placeholder: '例: AAPL, TSLA' },
];

export default function QuickAddModal({ onAdded, onTrade }) {
  const [open, setOpen] = useState(false);
  const [market, setMarket] = useState('A');
  const [code, setCode] = useState('');
  const [name, setName] = useState('');
  const [status, setStatus] = useState('');
  const [searchResults, setSearchResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [selectedStock, setSelectedStock] = useState(null); // {code, name}
  const inputRef = useRef(null);
  const containerRef = useRef(null);
  const debounceRef = useRef(null);

  useEffect(() => {
    if (open && inputRef.current) setTimeout(() => inputRef.current.focus(), 100);
  }, [open, market]);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false); setStatus(''); setSearchResults([]); setSelectedStock(null);
      }
    };
    if (open) document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  // 搜索防抖（A股走 /api/trading/search；港股/美股走 us-quant watchlist/search）
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    const trimmed = code.trim();
    if (trimmed.length < 1) { setSearchResults([]); setSelectedStock(null); return; }
    debounceRef.current = setTimeout(async () => {
      setSearching(true);
      try {
        const url = market === 'A'
          ? `/api/trading/search?q=${encodeURIComponent(trimmed)}`
          : `/api/us-quant/watchlist/search?market=${market}&q=${encodeURIComponent(trimmed)}`;
        const { ok, data } = await apiFetch(url);
        if (ok && data?.results?.length > 0) {
          setSearchResults(data.results.slice(0, 5));
          setSelectedStock(null);
        } else {
          setSearchResults([]);
          // 搜索无结果时，直接用输入作为 code
          setSelectedStock({ code: trimmed.toUpperCase(), name: name.trim() || trimmed.toUpperCase() });
        }
      } catch {
        setSearchResults([]);
        setSelectedStock({ code: trimmed.toUpperCase(), name: name.trim() || trimmed.toUpperCase() });
      } finally {
        setSearching(false);
      }
    }, 300);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [code, market, name]);

  const selectStock = useCallback((stock) => {
    setSelectedStock(stock);
    setCode(stock.code);
    setName(stock.name || '');
    setSearchResults([]);
  }, []);

  const handleAddToWatchlist = async () => {
    if (!selectedStock) return;
    setStatus('添加自选中…');
    const body = market === 'A'
      ? { stockCode: selectedStock.code, stockName: selectedStock.name || selectedStock.code }
      : { market, symbol: selectedStock.code };
    const url = market === 'A' ? '/api/watchlist/add' : '/api/us-quant/watchlist/add';
    const { ok, data, error } = await apiFetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (ok && (data?.ok || data?.success || data?.id)) {
      setStatus('✅ 已加入自选');
      onAdded?.();
    } else {
      setStatus('❌ ' + formatApiError(data?.error ?? error, '添加失败'));
    }
  };

  const handleAddToFocus = async () => {
    if (!selectedStock) return;
    setStatus('加入重点中…');
    const { ok, error } = await apiFetch('/api/watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stockCode: selectedStock.code, stockName: selectedStock.name || selectedStock.code, group: '重点关注' }),
    });
    if (ok) {
      setStatus('✅ 已加入重点关注');
      onAdded?.();
    } else {
      setStatus('❌ ' + formatApiError(error, '添加失败'));
    }
  };

  const handleTrade = (type) => {
    if (!selectedStock) return;
    setOpen(false); setStatus(''); setSearchResults([]);
    onTrade?.(selectedStock.code, selectedStock.name || selectedStock.code, type);
  };

  const handleKeyDown = (e) => {
    if (e.key === 'Escape') { setOpen(false); setStatus(''); setSearchResults([]); setSelectedStock(null); }
    if (e.key === 'Enter' && selectedStock) handleAddToWatchlist();
  };

  // 重置状态
  const resetSearch = () => {
    setCode(''); setName(''); setSearchResults([]); setSelectedStock(null); setStatus('');
    if (inputRef.current) inputRef.current.focus();
  };

  return (
    <div className="relative" ref={containerRef}>
      {/* 快速添加按钮 */}
      <button
        onClick={() => { setOpen(o => !o); setStatus(''); setSearchResults([]); setSelectedStock(null); }}
        className="px-2.5 py-1 rounded-lg text-[11px] font-bold flex items-center gap-1 whitespace-nowrap transition-all"
        style={{
          background: open ? 'rgba(99,102,241,0.15)' : 'rgba(99,102,241,0.08)',
          color: '#6366f1',
          border: open ? '1px solid rgba(99,102,241,0.4)' : '1px solid rgba(99,102,241,0.2)',
        }}
        title="快速添加股票到自选股"
      >
        <span className="text-[13px] leading-none">+</span>
        <span>快速添加</span>
        <span className="text-[10px] opacity-60">{open ? '\u25b4' : '\u25be'}</span>
      </button>

      {/* 下拉面板 */}
      {open && (
        <div
          className="absolute right-0 top-full mt-1 z-50 rounded-xl border shadow-xl overflow-hidden"
          style={{
            width: 380,
            borderColor: 'var(--border-color)',
            background: 'var(--bg-card)',
          }}
        >
          {/* 市场选择 tabs */}
          <div className="flex border-b" style={{ borderColor: 'var(--border-color)' }}>
            {MARKETS.map(m => (
              <button
                key={m.key}
                onClick={() => { setMarket(m.key); setStatus(''); setSearchResults([]); setSelectedStock(null); }}
                className="flex-1 px-2 py-2 text-[11px] font-bold flex items-center justify-center gap-1 transition-all"
                style={{
                  background: market === m.key ? 'var(--bg-surface)' : 'transparent',
                  color: market === m.key ? 'var(--text-primary)' : 'var(--text-muted)',
                  borderBottom: market === m.key ? '2px solid #6366f1' : '2px solid transparent',
                }}
              >
                <span>{m.flag}</span>
                <span>{m.label}</span>
              </button>
            ))}
          </div>

          {/* 输入区域 */}
          <div className="p-3 space-y-2">
            <div className="flex items-center gap-2">
              <div className="relative flex-1">
                <input
                  ref={inputRef}
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder={MARKETS.find(m => m.key === market)?.placeholder || '\u8f93\u5165\u80a1\u7968\u4ee3\u7801'}
                  className="w-full px-2.5 py-1.5 rounded-lg border text-[12px] outline-none"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
                />
                {/* 搜索下拉结果 */}
                {searchResults.length > 0 && (
                  <div className="absolute left-0 right-0 top-full mt-0.5 z-10 rounded-lg border shadow-md overflow-hidden"
                    style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                    {searchResults.map((s, i) => (
                      <button
                        key={i}
                        onClick={() => selectStock(s)}
                        className="w-full px-2.5 py-1.5 text-[11px] text-left flex items-center gap-2 hover:brightness-110 transition-all"
                        style={{ borderBottom: i < searchResults.length - 1 ? '1px solid var(--border-color)' : 'none', color: 'var(--text-primary)' }}
                      >
                        <span className="font-bold">{s.code}</span>
                        <span style={{ color: 'var(--text-secondary)' }}>{s.name}</span>
                        {s.market && <span className="ml-auto text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.market}</span>}
                      </button>
                    ))}
                  </div>
                )}
                {searching && (
                  <div className="absolute right-2 top-1/2 -translate-y-1/2">
                    <span className="inline-block w-3 h-3 rounded-full border-2 border-indigo-400 border-t-transparent animate-spin" />
                  </div>
                )}
              </div>
            </div>
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="\u80a1\u7968\u540d\u79f0\uff08\u53ef\u9009\uff09"
              className="w-full px-2.5 py-1.5 rounded-lg border text-[11px] outline-none"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
            />
          </div>

          {/* 选中股票后的操作按钮 */}
          {selectedStock && (
            <div className="px-3 pb-3 space-y-2">
              <div className="flex items-center gap-2 px-2.5 py-1.5 rounded-lg" style={{ background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.15)' }}>
                <span className="text-[12px] font-bold" style={{ color: 'var(--text-primary)' }}>{selectedStock.code}</span>
                <span className="text-[11px]" style={{ color: 'var(--text-secondary)' }}>{selectedStock.name}</span>
              </div>

              <div className="grid grid-cols-3 gap-1.5">
                {/* 加入自选 */}
                <button
                  onClick={handleAddToWatchlist}
                  disabled={status.includes('\u2705') || status.includes('添加中')}
                  className="flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-[11px] font-bold transition-all disabled:opacity-50"
                  style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1', border: '1px solid rgba(99,102,241,0.25)' }}
                >
                  <span>📋</span>
                  <span>加入自选</span>
                </button>
                {/* 加入重点 */}
                <button
                  onClick={handleAddToFocus}
                  disabled={status.includes('\u2705') || status.includes('添加中')}
                  className="flex items-center justify-center gap-1 px-2 py-1.5 rounded-lg text-[11px] font-bold transition-all disabled:opacity-50"
                  style={{ background: 'rgba(249,115,22,0.12)', color: '#f97316', border: '1px solid rgba(249,115,22,0.25)' }}
                >
                  <span>🔔</span>
                  <span>加入重点</span>
                </button>
                {/* 直接买卖 */}
                <div className="flex gap-1">
                  <button
                    onClick={() => handleTrade('buy')}
                    className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1.5 rounded-lg text-[11px] font-bold transition-all"
                    style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.25)' }}
                    title="买入"
                  >
                    <span>💰</span>
                    <span>买入</span>
                  </button>
                  <button
                    onClick={() => handleTrade('sell')}
                    className="flex-1 flex items-center justify-center gap-0.5 px-1.5 py-1.5 rounded-lg text-[11px] font-bold transition-all"
                    style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.25)' }}
                    title="卖出"
                  >
                    <span>📤</span>
                    <span>卖出</span>
                  </button>
                </div>
              </div>

              {status && (
                <div className="text-[11px] text-center py-1" style={{ color: status.startsWith('\u2705') ? 'var(--accent-green)' : status.startsWith('\u274c') ? '#ef4444' : 'var(--text-muted)' }}>
                  {status}
                  {status.startsWith('\u2705') && (
                    <button onClick={resetSearch} className="ml-2 underline text-[10px]" style={{ color: 'var(--accent-blue)' }}>\u7ee7\u7eed\u6dfb\u52a0</button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* 未选中的提示 */}
          {!selectedStock && code.trim().length === 0 && (
            <div className="px-3 pb-3">
              <div className="text-[9px] text-center" style={{ color: 'var(--text-muted)' }}>
                \u8f93\u5165\u80a1\u7968\u4ee3\u7801\u540e\u53ef\u6dfb\u52a0\u81ea\u9009\u3001\u91cd\u70b9\u5173\u6ce8\u6216\u76f4\u63a5\u4e70\u5356
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
