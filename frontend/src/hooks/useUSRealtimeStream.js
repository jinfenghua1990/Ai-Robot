/**
 * 美股/港股自选实时行情 SSE hook
 *
 * 数据源：GET /api/us-quant/watchlist/realtime/stream?market=US
 * 帧格式：{market, server_time, data: {SYM: {price, change_pct, quote_time}}}
 *
 * 与 A 股 useWatchlistRealtimeStream 同型：
 * - EventSource 自动重连（30s 退避）
 * - 服务端约 5s 一帧，前端不做额外节流
 * - 字段级合并，仅变化项更新引用，避免全量重渲染
 */
import { useEffect, useState, useRef, useCallback } from 'react';

const API_KEY = (typeof window !== 'undefined' && window.__AIROBOT_API_KEY) || '';

export function useUSRealtimeStream(market = 'US', enabled = true) {
  const [realtimeMap, setRealtimeMap] = useState({});
  const [serverTime, setServerTime] = useState(null);
  const [streamStatus, setStreamStatus] = useState('closed');
  const esRef = useRef(null);

  const url = `/api/us-quant/watchlist/realtime/stream?market=${market}&interval=5`
    + (API_KEY ? `&api_key=${encodeURIComponent(API_KEY)}` : '');

  const applyPayload = useCallback((payload) => {
    if (!payload?.data) return;
    setServerTime(payload.server_time);
    setRealtimeMap((prev) => {
      let next = prev;
      let dirty = false;
      for (const [sym, item] of Object.entries(payload.data)) {
        if (prev[sym]?.price !== item.price || prev[sym]?.change_pct !== item.change_pct || prev[sym]?.quote_time !== item.quote_time) {
          if (!dirty) { next = { ...prev }; dirty = true; }
          next[sym] = item;
        }
      }
      return dirty ? next : prev;
    });
  }, []);

  useEffect(() => {
    if (!enabled || typeof EventSource === 'undefined') {
      setStreamStatus('closed');
      return;
    }
    setStreamStatus('connecting');
    let cancelled = false;
    let reconnectTimer = null;

    const connect = () => {
      if (cancelled) return;
      try {
        const es = new EventSource(url);
        esRef.current = es;
        es.onopen = () => { if (!cancelled) setStreamStatus('open'); };
        es.onmessage = (evt) => {
          if (cancelled) return;
          try { applyPayload(JSON.parse(evt.data)); } catch { /* ignore */ }
        };
        es.onerror = () => {
          if (cancelled) return;
          es.close();
          if (esRef.current === es) esRef.current = null;
          setStreamStatus('fallback');
          if (reconnectTimer) clearTimeout(reconnectTimer);
          reconnectTimer = setTimeout(() => { if (!cancelled) connect(); }, 30000);
        };
      } catch {
        setStreamStatus('fallback');
      }
    };

    connect();
    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (esRef.current) { esRef.current.close(); esRef.current = null; }
    };
  }, [url, enabled, applyPayload]);

  return { realtimeMap, serverTime, streamStatus };
}
