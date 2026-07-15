/**
 * 订阅 watchlist 实时推送 (SSE)
 *
 * 数据源：GET /api/watchlist/realtime/stream
 * 数据格式：{server_time, count, data: {ts_code: {current_price, pct_chg, main_force_inflow, ...}}}
 *
 * 转换逻辑：
 * 1. 复用 SSE 连接，避免每只股票单独请求
 * 2. 将 REALTIME_STATE 格式（current_price/pct_chg）映射为 SignalCard 期望的实时字段（price/price_chg）
 * 3. 暴露 realtimeMap: secCode -> {price, price_chg, main_force_inflow, ...}
 *
 * 设计权衡：
 * - EventSource 自动重连，但服务端每 5s 推送一帧，前端不要做额外节流
 * - 组件卸载时调用 es.close() 释放连接
 * - 非交易时段返回空 data 帧，连接保持
 */
import { useEffect, useState, useRef, useCallback } from 'react';

const STREAM_URL = '/api/watchlist/realtime/stream';
const POLL_FALLBACK_URL = '/api/watchlist/realtime/snapshot';
const FALLBACK_POLL_INTERVAL = 15000;  // 15s 兜底轮询（非交易时段或 SSE 失败时）

function mapRealtimePayload(payload) {
  if (!payload?.data) return { serverTime: payload?.server_time, byCode: {} };
  const byCode = {};
  for (const [tsCode, item] of Object.entries(payload.data)) {
    const code = tsCode.split('.')[0];
    if (!code) continue;
    const mainForce = item.main_force_inflow ?? 0;
    byCode[code] = {
      price: item.current_price ?? 0,
      price_chg: item.pct_chg ?? 0,
      main_force_inflow: mainForce,
      // 实时数据源仅提供主力净流入，总净流入不存在；散户净流按日内资金平衡估算
      net_inflow: null,
      retail_flow: -mainForce,
      latest_time: item.snapshot_time,
      source: item.source,
      turnover_rate: item.turnover_rate,
      large_buy_count_3s: item.large_buy_count_3s,
      large_sell_count_3s: item.large_sell_count_3s,
      large_order_active_ratio: item.large_order_active_ratio,
      thousand_count_1m: item.thousand_order_count_per_min,
      support_level: item.support_level_eval,
      bid_price_1: item.bid_price_1,
      bid_vol_1: item.bid_vol_1,
      ask_price_1: item.ask_price_1,
      ask_vol_1: item.ask_vol_1,
      is_stale: item.snapshot_time ? (Date.now() - new Date(item.snapshot_time).getTime() > 300000) : true,
    };
  }
  return { serverTime: payload.server_time, byCode };
}

/**
 * 主 hook：SSE + 兜底轮询
 * - 优先用 SSE（5s 推送）
 * - SSE 出错或不支持时降级到 15s 轮询
 */
export function useWatchlistRealtimeStream() {
  const [realtimeMap, setRealtimeMap] = useState({});
  const [serverTime, setServerTime] = useState(null);
  const [streamStatus, setStreamStatus] = useState('connecting');  // connecting | open | fallback | closed
  const esRef = useRef(null);
  const pollTimerRef = useRef(null);

  const applyPayload = useCallback((payload) => {
    const { serverTime, byCode } = mapRealtimePayload(payload);
    setServerTime(serverTime);
    if (Object.keys(byCode).length > 0) {
      setRealtimeMap((prev) => ({ ...prev, ...byCode }));
    }
  }, []);

  const startPollingFallback = useCallback(() => {
    if (pollTimerRef.current) return;
    setStreamStatus('fallback');
    const tick = async () => {
      try {
        const res = await fetch(POLL_FALLBACK_URL);
        if (res.ok) applyPayload(await res.json());
      } catch { /* silent */ }
    };
    tick();
    pollTimerRef.current = setInterval(tick, FALLBACK_POLL_INTERVAL);
  }, [applyPayload]);

  useEffect(() => {
    if (typeof window === 'undefined' || typeof EventSource === 'undefined') {
      startPollingFallback();
      return;
    }

    let cancelled = false;
    let reconnectTimer = null;

    const connect = () => {
      if (cancelled) return;
      try {
        const es = new EventSource(STREAM_URL);
        esRef.current = es;

        es.onopen = () => {
          if (cancelled) return;
          setStreamStatus('open');
          if (pollTimerRef.current) {
            clearInterval(pollTimerRef.current);
            pollTimerRef.current = null;
          }
        };

        es.onmessage = (evt) => {
          if (cancelled) return;
          try {
            applyPayload(JSON.parse(evt.data));
          } catch { /* ignore parse error */ }
        };

        es.onerror = () => {
          if (cancelled) return;
          setStreamStatus('fallback');
          es.close();
          esRef.current = null;
          if (!pollTimerRef.current) startPollingFallback();
          // 30s 后重试 SSE
          reconnectTimer = setTimeout(() => { if (!cancelled) connect(); }, 30000);
        };
      } catch {
        startPollingFallback();
      }
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      if (esRef.current) { esRef.current.close(); esRef.current = null; }
      if (pollTimerRef.current) { clearInterval(pollTimerRef.current); pollTimerRef.current = null; }
      setStreamStatus('closed');
    };
  }, [applyPayload, startPollingFallback]);

  return { realtimeMap, serverTime, streamStatus };
}
