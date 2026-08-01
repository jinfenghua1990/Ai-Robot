import React, { useState, useRef, useEffect, useMemo, memo } from 'react';
import { apiFetch } from '../../utils/request';
import SignalCardTuned from './SignalCardTuned';
import StockActionButtons from './StockActionButtons';
import { DIM_KEYS } from './SignalCardUtils';


function SignalCardV4Inner({
  signal,
  orders = [],
  onSell,
  onRemove,
  onRefresh,
  showWatchBtn = true,
  showBuyBtn,
  mode = 'trading',
  showAnalysisButton = false,
  onAnalyze,
  showActionButton = true,
  // 父组件（如策略中心/共振页）已预取的 stock-dashboard 数据，传入时直接消费，
  // 不再触发 IntersectionObserver 内的单只请求，避免 100+ 卡片同时打 /api/stock-dashboard。
  prefetchedDash = null,
  // 父组件明确告知「等待批量预取中」，卡片就跳过自身的 IntersectionObserver 自取，
  // 直到 prefetchedDash 被填上。用于避免「list 接口返回后 100+ 卡片同时打单只接口」
  // → 后端被打挂。父组件完成 batch 后再通过 prefetchedDash 注入。
  awaitParentPrefetch = false,
  ...rest
}) {
  const code = signal?.secCode;
  // 注意：useState 初始化只跑一次，prefetchedDash prop 后续变化不会自动同步。
  // 用受控 dashRef + useEffect 监听 prop 变化，再回写到 dash state。
  const [dash, setDash] = useState(prefetchedDash);
  const [loading, setLoading] = useState(prefetchedDash ? false : true);
  const [dashUnavail, setDashUnavail] = useState(prefetchedDash ? null : null); // 'no-data' | 'backend-down' | null

  // 用 ref 同步最新 dash，使轮询闭包能读到当前的 realtime.mode
  const dashRef = useRef(dash);
  useEffect(() => { dashRef.current = dash; }, [dash]);

  // prop prefetchedDash 变化（如父组件批量预取完成）→ 同步到 dash，跳过自身单只请求
  useEffect(() => {
    if (prefetchedDash && prefetchedDash !== dashRef.current) {
      setDash(prefetchedDash);
      setLoading(false);
      setDashUnavail(null);
    }
  }, [prefetchedDash]);

  const rootRef = useRef(null);
  const visibleRef = useRef(false); // 默认不可见：等 IntersectionObserver 确认后再加载

  useEffect(() => {
    if (!code) return;
    let active = true;
    let timer = null;

    // 已被父组件预取：直接跳过自取
    if (prefetchedDash) {
      setLoading(false);
      setDashUnavail(null);
      // 预取数据一般不带 realtime 滚动，无需频繁轮询；只在 mode='live' 时 60s 探活
      if (prefetchedDash?.realtime?.mode === 'live') {
        timer = setTimeout(async () => {
          if (!active) return;
          try {
            const { ok, data } = await apiFetch(`/api/stock-dashboard/${code}`);
            if (active && ok && data && !data.error) setDash(data);
          } catch { /* keep last */ }
        }, 60000);
      }
      return () => { active = false; if (timer) clearTimeout(timer); };
    }

    // 父组件明确告知等待批量预取 → 跳过自身自取，避免 100+ 卡片同时打单只接口
    if (awaitParentPrefetch) {
      setLoading(true);
      return () => { active = false; };
    }

    setLoading(true);
    setDashUnavail(null);

    const load = async () => {
      try {
        const { ok, data } = await apiFetch(`/api/stock-dashboard/${code}`);
        if (!active) return;
        if (ok && data && !data.error) {
          setDash(data);
        } else {
          setDashUnavail(data && data.error ? 'no-data' : 'backend-down');
        }
      } catch {
        if (active) setDashUnavail('backend-down');
      }
    };

    // 轻量轮询：可见时按状态刷新；滑出视口后仅低频探活
    const schedule = () => {
      if (timer) { clearTimeout(timer); timer = null; }
      const mode = dashRef.current?.realtime?.mode;
      if (visibleRef.current) {
        const delay = mode === 'live' ? 30000 : 300000;
        timer = setTimeout(async () => {
          if (!active) return;
          await load();
          if (active) schedule();
        }, delay);
      } else {
        timer = setTimeout(() => { if (active) schedule(); }, 10000);
      }
    };

    // 可见性门控：滚入视口才开始加载，滚出停轮询
    let io = null;
    const startLoading = () => {
      load().finally(() => { if (active) setLoading(false); });
      schedule();
    };
    if (typeof IntersectionObserver !== 'undefined' && rootRef.current) {
      io = new IntersectionObserver((entries) => {
        const vis = entries.some((e) => e.isIntersecting);
        if (vis === visibleRef.current) return;
        visibleRef.current = vis;
        if (vis) { if (active) startLoading(); }
        else { schedule(); }
      }, { threshold: 0.01 });
      io.observe(rootRef.current);
    } else {
      // 降级：无 IntersectionObserver 时直接加载
      startLoading();
    }

    return () => {
      active = false;
      if (timer) clearTimeout(timer);
      if (io) io.disconnect();
    };
  }, [code, prefetchedDash]);

  // v4 始终显示标识层 + v3 主体；dash 成败都不伪装成 v3
  const { action_label, action_color } = dash || {};
  const sf = dash?.sector_flow || {};
  const inst = dash?.institution_flow || {};
  // 操作按钮所需数据：从 signal 解构，与 SignalCardTuned 同源
  const {
    secCode: v4_secCode, secName: v4_secName,
    position: v4_position = {},
  } = signal || {};
  const v4_isLeader = mode === 'leader';

  // 综合评分（盘后 / 实时）：null 安全过滤，避免 NaN 传给 conic-gradient 崩溃
  const dimKeys = DIM_KEYS;
  const avgScore = useMemo(() => {
    if (!dash) return null;
    const valid = dimKeys.map(k => dash[k]).filter(v => v != null && !isNaN(v));
    return valid.length ? Math.round(valid.reduce((s, v) => s + v, 0) / valid.length) : null;
  }, [dash]);
  const rtData = useMemo(() => dash ? (dash.realtime || {}) : {}, [dash]);
  const rtAvailTop = !!rtData.available;
  const rtAvgScore = useMemo(() => {
    if (!rtAvailTop) return null;
    const valid = dimKeys.map(k => rtData[k]).filter(v => v != null && !isNaN(v));
    return valid.length ? Math.round(valid.reduce((s, v) => s + v, 0) / valid.length) : null;
  }, [rtData, rtAvailTop]);
  const rtAction = useMemo(() => {
    if (rtAvgScore == null) return null;
    if (rtAvgScore >= 70) return { label: '看多', color: '#ef4444' };
    if (rtAvgScore >= 50) return { label: '观望', color: '#eab308' };
    if (rtAvgScore >= 30) return { label: '谨慎', color: '#f97316' };
    return { label: '看空', color: '#22c55e' };
  }, [rtAvgScore]);

  return (
    <div
      ref={rootRef}
      className="rounded-lg overflow-hidden"
      style={{ border: '1px solid var(--border-color)' }}
    >
      {/* v4 标识层（始终可见，杜绝静默回退） */}
      <div
        className="relative flex items-center justify-between flex-wrap gap-1"
      >
        {/* 背景色条：充满整行宽度，延伸到卡片左右边缘 */}
        <div
          className="absolute inset-0 -z-0"
          style={{ background: dash ? `${action_color}0D` : 'rgba(168,85,247,0.06)' }}
        />
        <span
          className="relative z-10 text-xs px-2 py-0.5 m-1 rounded-md font-bold"
          style={dash
            ? { background: `${action_color}22`, color: action_color, border: `1px solid ${action_color}40` }
            : { background: 'rgba(168,85,247,0.15)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.4)' }}
        >
          {loading ? 'v4 · 加载中…' : dash ? `v4 · ${action_label}` : 'v4 · 仪表盘不可用'}
        </span>
        {/* 综合评分（盘后 | 实时）：简化为单行文字，删除装饰性conic-gradient圆环 */}
        {dash && (
          <div className="relative z-10 flex items-center gap-1.5 m-1 text-[10px] font-bold" title="综合评分: 盘后 / 实时">
            {(() => {
              const v = avgScore;
              const c = action_color || '#64748b';
              return <span style={{ color: c }}>盘后 {v == null ? '—' : v}</span>;
            })()}
            {(() => {
              const v = rtAvgScore;
              const base = avgScore;
              if (v == null || base == null) return null;
              const diff = v - base;
              const arrow = diff > 3 ? '↑' : diff < -3 ? '↓' : '→';
              const color = diff > 3 ? '#ef4444' : diff < -3 ? '#22c55e' : '#94a3b8';
              const tip = diff > 3 ? `盘中走强 +${diff.toFixed(0)}` : diff < -3 ? `盘中走弱 ${diff.toFixed(0)}` : '盘中持平';
              return <span style={{ color }} title={tip}>{arrow}</span>;
            })()}
            {(() => {
              const v = rtAvgScore;
              const c = rtAction ? rtAction.color : '#94a3b8';
              return <span style={{ color: c }}>实时 {v == null ? '—' : v}{rtAction ? `·${rtAction.label}` : ''}</span>;
            })()}
          </div>
        )}
        {!loading && !dash && dashUnavail === 'no-data' && (
          <span className="relative z-10 text-[10px] m-1" style={{ color: '#f97316' }}>该票暂无盘后数据</span>
        )}
        {!loading && !dash && dashUnavail === 'backend-down' && (
          <span className="relative z-10 text-[10px] m-1" style={{ color: '#ef4444' }}>后端连接失败</span>
        )}
        {/* 操作按钮组：与 v4 标签同一排水平排列（K线BS / 购买力 / 🔍分析 / 买 / 卖 / 跟踪 / 自选 / 新浪 / 操作） */}
        {/* "趋势/主升/震荡"标签已下线：与下方"📊 综合评分"模块的趋势维度重复 */}
        <div className="relative z-10 ml-auto flex items-center gap-1 flex-wrap m-1">
          <StockActionButtons
            stockCode={v4_secCode}
            stockName={v4_secName}
            signal={signal}
            positionCount={v4_position?.count || 0}
            showBuy={showBuyBtn ?? showWatchBtn}
            showSell={!v4_isLeader && (v4_position?.count || 0) > 0}
            showTrack={showBuyBtn ?? showWatchBtn}
            showWatch={showWatchBtn}
            showMore={showActionButton}
            showKline={showAnalysisButton}
            showAnalysis={showAnalysisButton}
            onAnalyze={onAnalyze}
            layout="inline"
            size="sm"
            onRefresh={onRefresh}
            onRemove={onRemove}
          />
        </div>
      </div>

      {/* 横条1：顶部状态区 与 信息/操作区 分隔（全宽 1.5px） */}
      <div className="w-full h-[1.5px]" style={{ backgroundColor: 'var(--border-color)' }} />

      {/* v3 主体（完整保留，零改动） */}
      <SignalCardTuned
        signal={signal}
        orders={orders}
        onSell={onSell}
        onRemove={onRemove}
        onRefresh={onRefresh}
        showWatchBtn={showWatchBtn}
        showBuyBtn={showBuyBtn}
        mode={mode}
        showAnalysisButton={showAnalysisButton}
        showActionButton={showActionButton}
        dash={dash}
        {...rest}
      />

      {/* 资金流向拆解已并入上方「主力资金」下方，此处不再重复 */}
      {/* v4 评分卡已上移至分组0（📊 综合评分），此处不再重复 */}
    </div>
  );
}

// memo 包装：避免 WatchlistItem 因 isSelected 变化导致全部 v4 卡片重渲染
export default memo(SignalCardV4Inner);
