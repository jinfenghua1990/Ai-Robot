import { createContext, useContext, useState, useCallback, useRef, useEffect } from 'react';
import { apiFetch } from '../utils/request';
import { SLOW_POLL_INTERVAL } from '../utils/constants';

const TradingContext = createContext(null);

export function TradingProvider({ children }) {
  const [balance, setBalance] = useState(null);
  const [positions, setPositions] = useState(null);
  const [loading, setLoading] = useState(false);
  const [tradeResult, setTradeResult] = useState(null); // { success, message, orderId }
  const refreshTimer = useRef(null);

  const refreshBalance = useCallback(async (force = false) => {
    try {
      const { ok, data } = await apiFetch(`/api/trading/balance${force ? '?force=1' : ''}`);
      if (!ok) return;
      setBalance(data);
    } catch (e) { /* silent */ }
  }, []);

  const refreshPositions = useCallback(async (force = false) => {
    try {
      const { ok, data } = await apiFetch(`/api/trading/positions${force ? '?force=1' : ''}`);
      if (!ok) return;
      setPositions(data);
    } catch (e) { /* silent */ }
  }, []);

  const refreshAll = useCallback(async (force = false) => {
    setLoading(true);
    await Promise.all([refreshBalance(force), refreshPositions(force)]);
    setLoading(false);
  }, [refreshBalance, refreshPositions]);

  const executeTrade = useCallback(async (params) => {
    try {
      const { ok, data, error } = await apiFetch('/api/trading/trade', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      if (ok) {
        setTradeResult({ success: true, message: '委托成功', data });
        // 交易后刷新数据
        setTimeout(() => refreshAll(), 500);
      } else {
        setTradeResult({ success: false, message: error || '委托失败' });
      }
      return data;
    } catch (e) {
      setTradeResult({ success: false, message: '网络错误' });
      return null;
    }
  }, [refreshAll]);

  const cancelOrder = useCallback(async (params) => {
    try {
      const { ok, data } = await apiFetch('/api/trading/cancel', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(params),
      });
      if (ok) {
        setTimeout(() => refreshAll(), 500);
      }
      return data;
    } catch (e) {
      return null;
    }
  }, [refreshAll]);

  const clearTradeResult = useCallback(() => setTradeResult(null), []);

  // 判断是否在A股交易时间（9:30-11:30, 13:00-15:00）
  const _isTradingHours = () => {
    const now = new Date();
    const h = now.getHours();
    const m = now.getMinutes();
    const t = h * 60 + m;
    const day = now.getDay();
    // 周末不刷新
    if (day === 0 || day === 6) return false;
    // 9:30-11:30 或 13:00-15:00
    return (t >= 570 && t <= 690) || (t >= 780 && t <= 900);
  };

  // 初始加载一次 + 盘中5分钟自动刷新（非交易时间不调用，节省妙想API配额）
  useEffect(() => {
    refreshAll();
    const timer = setInterval(() => {
      if (_isTradingHours()) {
        refreshAll();
      }
    }, SLOW_POLL_INTERVAL); // 5分钟
    refreshTimer.current = timer;
    return () => clearInterval(refreshTimer.current);
  }, [refreshAll]);

  return (
    <TradingContext.Provider value={{
      balance, positions, loading, tradeResult,
      refreshAll, refreshBalance, refreshPositions,
      executeTrade, cancelOrder, clearTradeResult,
    }}>
      {children}
    </TradingContext.Provider>
  );
}

export function useTrading() {
  const ctx = useContext(TradingContext);
  if (!ctx) throw new Error('useTrading must be used within TradingProvider');
  return ctx;
}
