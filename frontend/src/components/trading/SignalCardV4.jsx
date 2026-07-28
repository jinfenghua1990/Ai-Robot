import React, { useState, useRef, useEffect, useMemo, memo } from 'react';
import ReactECharts from 'echarts-for-react';
import StockActionButtons from './StockActionButtons';
import OrderHistoryModal from './OrderHistoryModal';
import SinaLink from '../SinaLink';
import { HIT_TAG_CONFIG } from './HitTagBar';
import { UP_COLOR, DOWN_COLOR, DOWN_DARK, REDUCE_COLOR } from '../../utils/colors';
import { formatWan } from '../../utils/format';
import AiDiagnosisModule from './AiDiagnosisModule';
import { apiFetch } from '../../utils/request';
// 标杆化：所有模块的 icon/name 集中在 moduleHeaderConfig，一处修改全局生效
import { MODULE_HEADER_CONFIG, stripRealtimePrefix, getRealtimeHeader as formatRealtimeHeader, getTechConclusion, getOrgConclusion, getFlowConclusion, getMarketConclusion } from './moduleHeaderConfig';


// 金额格式化：元/万自动转 万/亿（fromYuan=true 表示输入为元）
const fmtWanYi = (v, fromYuan = false) => {
  const wan = fromYuan ? (v || 0) / 10000 : (v || 0);
  if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
  return `${wan.toFixed(fromYuan ? 2 : 0)}万`;
};

// 模块级常量与纯函数：避免每次 render 重建，降低 GC 压力

// 12 维评分维度键（原本定义在组件内部，每次 render 重建）
const DIM_KEYS = ['trend_strength','capital_momentum','sector_resonance','relative_strength','volume_health','volatility_health','drawdown_status','institution_signal'];

// EMA 计算（纯函数）
const calcEma = (arr, n) => {
  const k = 2 / (n + 1);
  let prev = arr[0];
  return arr.map((v, i) => (prev = i === 0 ? v : v * k + prev * (1 - k)));
};

// 实时 MACD：基于当日分时价格序列计算（参数 idPrices 显式传入）
const calcIntradayMacd = (idPrices) => {
  if (idPrices.length < 26) return null;
  const e12 = calcEma(idPrices, 12);
  const e26 = calcEma(idPrices, 26);
  const dif = e12.map((v, i) => v - e26[i]);
  const dea = calcEma(dif, 9);
  const n = dif.length;
  return { dif: dif[n - 1], dea: dea[n - 1], macd: 2 * (dif[n - 1] - dea[n - 1]) };
};

// 实时 KDJ：基于当日分时价格序列计算（参数 idPrices 显式传入）
const calcIntradayKdj = (idPrices) => {
  const N = 9;
  if (idPrices.length < N) return null;
  let k = 50, d = 50;
  for (let i = N - 1; i < idPrices.length; i++) {
    const win = idPrices.slice(i - N + 1, i + 1);
    const hh = Math.max(...win), ll = Math.min(...win);
    const rsv = hh === ll ? 50 : ((idPrices[i] - ll) / (hh - ll)) * 100;
    k = (2 / 3) * k + (1 / 3) * rsv;
    d = (2 / 3) * d + (1 / 3) * k;
  }
  return { k, d, j: 3 * k - 2 * d };
};

// 维度评分 pill：内嵌在各分组标题行，显示该维度的盘后 / 实时评分（带颜色）
// v == null 时返回 null（不渲染），避免无数据时占位
function DimPill({ label, afterVal, rtVal, rtAvail }) {
  const c = (v) => v == null ? null : v >= 70 ? '#ef4444' : v >= 50 ? '#eab308' : v >= 30 ? '#f97316' : '#22c55e';
  const showAfter = afterVal != null;
  const showRt = rtAvail && rtVal != null;
  if (!showAfter && !showRt) return null;
  return (
    <span className="text-[9px] inline-flex items-center gap-0.5 px-1 py-0.5 rounded font-bold whitespace-nowrap"
          style={{ background: 'rgba(148,163,184,0.06)', border: '1px solid rgba(148,163,184,0.18)' }}
          title={`${label}：盘后 ${showAfter ? afterVal : '无数据'} · 实时 ${showRt ? rtVal : '无数据'}`}>
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      {showAfter && <span className="tabular-nums" style={{ color: c(afterVal) }}>{afterVal}</span>}
      {showRt && <span className="tabular-nums" style={{ color: c(rtVal) }}>/{rtVal}</span>}
    </span>
  );
}

// 游资阶段 → 犀利操作建议标签（每个阶段都带明确动作方向，不再用"观望"等模糊词）
const LEADER_STAGE_MAP = {
  '主升': { label: '主升·加仓',     color: '#dc2626', icon: '🚀' },
  '加速': { label: '加速·追涨',     color: '#fb923c', icon: '🚀' },
  '突破': { label: '突破·跟进',     color: '#facc15', icon: '📈' },
  '启动': { label: '启动·试仓',     color: '#f59e0b', icon: '🔥' },
  '发酵': { label: '发酵·加仓',     color: '#ef4444', icon: '🔥' },
  '分歧': { label: '分歧·减仓',     color: '#22c55e', icon: '⚠️' },
  '蓄势': { label: '蓄势·潜伏',     color: '#3b82f6', icon: '⏳' },
  '留意': { label: '留意·小仓试错', color: '#a78bfa', icon: '👀' },
  '关注': { label: '关注·小仓试错', color: '#a78bfa', icon: '👀' },
  '吸筹': { label: '吸筹·分批建仓', color: '#ef4444', icon: '💰' },
  '跟随': { label: '跟随·轻仓',     color: '#64748b', icon: '👣' },
  '观望': { label: '空仓·不追',     color: '#64748b', icon: '🛑' },
  '衰退': { label: '衰退·清仓',     color: '#22c55e', icon: '🔻' },
  '退潮': { label: '退潮·离场',     color: '#22c55e', icon: '🔻' },
};

/**
 * 单个持仓的信号卡片（紧凑三列模块化布局：左信息 | 中资金流 | 右操作）
 * mode: 'trading'(模拟盘) | 'leader'(龙头页面) | 'watchlist'(自选股) | 'sim_watchlist'
 */
function SignalCardTuned({
  signal,
  orders = [],
  onSell,
  onRemove,
  onRefresh,
  showWatchBtn = true,
  showBuyBtn,
  mode = 'trading',
  showAnalysisButton = false,
  showActionButton = true,
  strategyTags = [],
  realtimeFlow = null,
  showRealtimeDetail = true,
  dash = null,
}) {
  const [orderOpen, setOrderOpen] = useState(false);

  if (!signal || !signal.secCode) {
    return null;
  }
  const {
    secCode, secName, signalLabel, signalColor,
    riskLevel, sector, sectorTrend, position = {},
    score,
    marketState,
  } = signal;

  // ===== B 模式：资金模块统一读 dash（与底部 v4 仪表盘同一数据源）=====
  // 顶部 v3 资金模块优先消费 dash（元单位），无 dash 时回退 signal（v3 独立模式仍可用）。
  const fmtYuan = (v) => {
    if (v == null) return '—';
    const abs = Math.abs(v);
    if (abs >= 1e8) return `${(v / 1e8).toFixed(2)}亿`;
    return `${(v / 1e4).toFixed(0)}万`;
  };
  const mfDash = dash?.institution_flow || null;
  const sfDash = dash?.sector_flow || null;
  const cumDash = dash?.main_net_cumulative || null;
  const rtDash = dash?.realtime || null;

  // ===== 实时头部缓存 =====
  // formatRealtimeHeader 在原代码中被调用 5 次（同一 render 内重复计算同一入参），
  // 这里 useMemo 一次，所有调用复用。rtDash 变化时才会重算。
  const rtHdr = useMemo(() => formatRealtimeHeader(rtDash), [rtDash]);

  // ===== hitTags 缓存 =====
  // 原代码每次 render 都 new Set + filter，命中标签不变时无谓重算
  const hitCfgs = useMemo(
    () => signal.hitTags ? HIT_TAG_CONFIG.filter(cfg => signal.hitTags.includes(cfg.key)) : [],
    [signal.hitTags]
  );

  // ===== 饼图 option 缓存 =====
  // 原代码每次 render 都新建 pieData/pieOption 对象引用，ReactECharts 深比较也需重算
  // 拆为左饼图（5档盘后）和右饼图（3档实时）两份独立 memo

  // 左饼图：5档盘后（dash.institution_flow 优先，回退 signal.moneyFlow）
  const leftPieOption = useMemo(() => {
    if (!signal.moneyFlow?.available) return null;
    const useDash = !!dash && dash.institution_flow != null;
    const inst = dash?.institution_flow || {};
    const mf = signal.moneyFlow;
    let pieData = [];
    if (useDash) {
      const abs = (v) => Math.abs(v || 0);
      pieData = [
        { value: abs(inst.super_large_net), name: '特大', itemStyle: { color: '#ef4444' } },
        { value: abs(inst.large_net), name: '大单', itemStyle: { color: '#f97316' } },
        { value: abs(inst.medium_net), name: '中单', itemStyle: { color: '#eab308' } },
        { value: abs(inst.small_net), name: '小单', itemStyle: { color: '#3b82f6' } },
        { value: abs(inst.tiny_net), name: '散单', itemStyle: { color: '#94a3b8' } },
      ].filter(d => d.value > 0);
    } else {
      const mainBuy = mf.main_buy || 0;
      const mainSell = mf.main_sell || 0;
      const retailBuy = mf.retail_buy;
      const retailSell = mf.retail_sell;
      const hasRetail = retailBuy != null && retailSell != null;
      pieData = [
        { value: Math.max(mainBuy, 0), name: '主力买入', itemStyle: { color: '#d32f2f' } },
        { value: Math.max(mainSell, 0), name: '主力卖出', itemStyle: { color: '#388e3c' } },
        ...(hasRetail ? [
          { value: Math.max(retailBuy, 0), name: '散户买入', itemStyle: { color: '#ff7043' } },
          { value: Math.max(retailSell, 0), name: '散户卖出', itemStyle: { color: '#8bc34a' } },
        ] : []),
      ].filter(d => d.value > 0);
    }
    if (pieData.length === 0) return 'empty';
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c}万 ({d}%)' },
      legend: { show: false },
      series: [{
        type: 'pie',
        radius: ['30%', '55%'],
        center: ['50%', '50%'],
        label: { show: true, fontSize: 9, formatter: '{b}\n{d}%' },
        labelLine: { length: 4, length2: 4 },
        data: pieData,
      }],
    };
  }, [signal.moneyFlow, dash]);

  // 右饼图：3档实时（main_net/retail_net/sector_net）
  const rightPieOption = useMemo(() => {
    const rtAvailable = !!rtDash?.available;
    const rt = rtDash || {};
    if (!rtAvailable) return null;
    const abs = (v) => Math.abs(v || 0);
    const pieData = [
      { value: abs(rt.main_net), name: '主力', itemStyle: { color: '#ef4444' } },
      { value: abs(rt.retail_net), name: '散户', itemStyle: { color: '#3b82f6' } },
      { value: abs(rt.sector_net), name: '板块', itemStyle: { color: '#a855f7' } },
    ].filter(d => d.value > 0);
    if (pieData.length === 0) return 'empty';
    return {
      tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
      legend: { show: false },
      series: [{
        type: 'pie',
        radius: ['30%', '55%'],
        center: ['50%', '50%'],
        label: { show: true, fontSize: 9, formatter: '{b}\n{d}%' },
        labelLine: { length: 4, length2: 4 },
        data: pieData,
      }],
    };
  }, [rtDash]);

  // ===== 5档横条数据缓存 =====
  // 原代码在 IIFE 内每次 render 新建 10 个对象（leftRows 5 + rightRows 5）
  // 提到顶层 useMemo，仅 mfDash/rtDash/signal.moneyFlow 变化时重算

  // 左5档数据（mfDash 优先，回退 signal.moneyFlow；无中单时占位隐藏）
  const mfRows = useMemo(() => {
    if (mfDash) {
      return [
        { label: '特大', val: mfDash.super_large_net || 0, color: '#ef4444' },
        { label: '大单', val: mfDash.large_net || 0, color: '#f97316' },
        { label: '中单', val: mfDash.medium_net || 0, color: '#eab308' },
        { label: '小单', val: mfDash.small_net || 0, color: '#3b82f6' },
        { label: '散单', val: mfDash.tiny_net || 0, color: '#64748b' },
      ];
    }
    return [
      { label: '特大', val: signal.moneyFlow?.super_large || 0, color: '#ef4444' },
      { label: '大单', val: signal.moneyFlow?.large || 0, color: '#f97316' },
      null, // 中单档：signal.moneyFlow 无此数据，隐藏占位
      { label: '小单', val: signal.moneyFlow?.small || 0, color: '#3b82f6' },
      { label: '散单', val: signal.moneyFlow?.tiny || 0, color: '#64748b' },
    ];
  }, [mfDash, signal.moneyFlow]);

  // 右5档数据（实时3档真实 + 2档空占位，与左栏行对齐）
  // 维度对齐映射：左盘后5档 → 右实时对应位置
  // 左[特大, 大单, 中单, 小单, 散单] → 右[空, 主力, 空, 散户, 板块]
  const rtRows = useMemo(() => {
    const rtAvailable = !!rtDash?.available;
    const rt = rtDash || {};
    return [
      { label: '—', val: null, color: '#94a3b8', empty: true },        // 特大档（实时无）
      { label: '主力', val: rtAvailable ? (rt.main_net ?? null) : null, color: '#ef4444' },
      { label: '—', val: null, color: '#94a3b8', empty: true },        // 中单档（实时无）
      { label: '散户', val: rtAvailable ? (rt.retail_net ?? null) : null, color: '#3b82f6' },
      { label: '板块', val: rtAvailable ? (rt.sector_net ?? null) : null, color: '#a855f7' },
    ];
  }, [rtDash]);

  const isWatchlistStyle = mode === 'watchlist' || mode === 'sim_watchlist';
  // 风险等级：仅在 high/medium/low 时显示，其他值（含 null）一律显示"无数据"
  const riskColor = riskLevel === 'high' ? '#dc2626' : riskLevel === 'medium' ? '#f97316' : riskLevel === 'low' ? '#6b7280' : 'var(--text-muted)';
  const riskLabel = riskLevel === 'high' ? '高风险' : riskLevel === 'medium' ? '中风险' : riskLevel === 'low' ? '低风险' : '无数据';
  // 盈亏：null 即空值，不做 0 降级（显示逻辑改为 -- / 无数据）
  const profitPct = position?.profitPct ?? null;
  const dayProfitPct = position?.dayProfitPct ?? null;
  const profitColor = profitPct == null ? 'var(--text-muted)' : profitPct >= 0 ? UP_COLOR : DOWN_COLOR;
  const changeColor = dayProfitPct == null ? 'var(--text-muted)' : dayProfitPct >= 0 ? UP_COLOR : DOWN_COLOR;
  const hasOrders = (orders || []).length > 0;
  const scoreColorValue = (score == null) ? '#6b7280' : score <= -5 ? DOWN_DARK : score <= -2 ? REDUCE_COLOR : score >= 3 ? UP_COLOR : '#6b7280';

  // AI 动态决策：技术形态驱动标签
  const isTechnicalBreakdown = signal.technical?.stage === '破位';
  // 后端已根据 technical stage 覆写 signalLabel，前端据此决定标签样式
  // 注：BS 区间标签（B持仓.../S平仓...）属于普通标签，不进入 hardcore 样式
  const isHardcoreLabel = signalLabel === '破位：抛 / 减仓'
    || signalLabel === '破位：果断清仓'
    || signalLabel === '弱势：果断减仓'
    || signalLabel === '震荡：暂避不加'
    || signalLabel === '减仓防守';
  const mainNetWan = signal.moneyFlow?.main_net ?? 0;
  const isMainForceAggressiveBuy = (signal.hitTags || []).includes('capital')
    || ['建仓', '强仓', '锁仓'].includes(signal.mainForce?.stage)
    || mainNetWan >= 5000;
  const hasPriceVolumeDivergence = isTechnicalBreakdown && isMainForceAggressiveBuy;

  // BS 区间：B 起点 → S 终点 / 今天
  // 优先使用 dash.bs_interval（含 klines 序列，来自 /api/stock-dashboard/{code}）
  // 回退到 signal.bsInterval（来自 /api/watchlist，无 klines）
  const bsInt = dash?.bs_interval || signal.bsInterval;
  const bsKlines = bsInt?.klines || [];

  // 金额格式化函数已抽到文件顶层 fmtWanYi（fromYuan=true 表示输入为元）

  return (
    <div
      className="rounded-lg border overflow-hidden relative flex flex-col"
      style={{ borderColor: `${signalColor}40`, background: 'var(--bg-card)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {/* ===== 单列信息模块（操作按钮已上移至 v4 状态条） ===== */}
      <div className="px-2.5 py-1.5">

        {/* ========== 核心信息模块 ========== */}
        <div className="signalcard-module module-info w-full flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'transparent' }}>
          {/* 头部：标签 + 名称 + 按钮 */}
          <div className="flex items-start gap-2">
            <div
              className={`flex-shrink-0 min-h-[44px] rounded-md flex flex-col items-center justify-center font-bold px-1.5 py-1 ${isHardcoreLabel ? 'min-w-[88px]' : ''}`}
              style={{
                background: isHardcoreLabel ? signalColor : `${signalColor}15`,
                border: `2px solid ${isHardcoreLabel ? signalColor : signalColor}`,
                color: isHardcoreLabel ? '#FFFFFF' : undefined,
                fontWeight: isHardcoreLabel ? 'bold' : undefined,
              }}
              title={isHardcoreLabel ? `${signalLabel}（基于技术形态判定）` : signalLabel}
            >
              {isHardcoreLabel ? (
                <span className="text-[10px] leading-tight text-center">{signalLabel}</span>
              ) : (
                <>
                  <span className="text-[11px] leading-tight text-center whitespace-nowrap" style={{ color: signalColor }}>{signalLabel}</span>
                  {score != null && (
                    <span className="text-[10px] mt-0.5" style={{ color: scoreColorValue }}>{score > 0 ? '+' : ''}{score}</span>
                  )}
                </>
              )}
            </div>
            <div className="flex-1 min-w-0 flex flex-col gap-0.5">
              {/* 行1：身份信息（名称/代码/新浪/当日涨跌/现价） */}
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-medium text-sm" style={{ color: 'var(--text-primary)' }}>{secName}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{secCode}</span>
                <SinaLink tsCode={secCode} />
                {dayProfitPct == null ? (
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>当日 --</span>
                ) : (
                  <span className="text-xs font-bold" style={{ color: changeColor }}>
                    当日 {dayProfitPct >= 0 ? '+' : ''}{dayProfitPct}%
                  </span>
                )}
                <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                  {position?.price == null ? '--' : position.price.toFixed(2)}
                </span>
              </div>
              {/* 行1.5：持仓信息行（仅持仓股显示，标准化：自选股/持仓页统一渲染） */}
              {(position?.count ?? 0) > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                    background: profitPct == null ? 'rgba(148,163,184,0.12)' : (profitPct >= 0 ? 'rgba(226,75,74,0.15)' : 'rgba(29,158,117,0.15)'),
                    border: `0.5px solid ${profitPct == null ? 'rgba(148,163,184,0.3)' : (profitPct >= 0 ? 'rgba(226,75,74,0.35)' : 'rgba(29,158,117,0.35)')}`,
                    color: profitPct == null ? '#94a3b8' : (profitPct >= 0 ? UP_COLOR : DOWN_COLOR),
                  }}>
                    总 {profitPct == null ? '--' : `${profitPct >= 0 ? '+' : ''}${profitPct.toFixed(2)}%`}
                    {position?.profit != null && (
                      <span className="ml-1">({position.profit >= 0 ? '+' : ''}{position.profit.toFixed(0)})</span>
                    )}
                  </span>
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                    background: (position?.dayProfit ?? 0) >= 0 ? 'rgba(226,75,74,0.15)' : 'rgba(29,158,117,0.15)',
                    border: `0.5px solid ${(position?.dayProfit ?? 0) >= 0 ? 'rgba(226,75,74,0.35)' : 'rgba(29,158,117,0.35)'}`,
                    color: (position?.dayProfit ?? 0) >= 0 ? UP_COLOR : DOWN_COLOR,
                  }}>
                    当日 {dayProfitPct == null ? '--' : `${dayProfitPct >= 0 ? '+' : ''}${dayProfitPct.toFixed(2)}%`}
                    {position?.dayProfit != null && (
                      <span className="ml-1">({position.dayProfit >= 0 ? '+' : ''}{position.dayProfit.toFixed(0)})</span>
                    )}
                  </span>
                  {[
                    { label: '持仓', value: `${position?.count ?? 0}股`, color: 'var(--text-secondary)' },
                    { label: '成本', value: (position?.costPrice ?? 0).toFixed(2), color: 'var(--text-muted)' },
                    { label: '市值', value: formatWan(position?.value ?? 0), color: 'var(--text-secondary)' },
                    { label: '仓位', value: `${(position?.posPct ?? 0).toFixed(1)}%`, color: 'var(--text-secondary)' },
                  ].map((m, mi) => (
                    <span key={mi} className="px-1.5 py-0.5 rounded text-[10px]" style={{
                      background: 'var(--bg-surface)',
                      border: '0.5px solid var(--border-color)',
                      color: m.color,
                    }}>
                      <span style={{ color: 'var(--text-muted)' }}>{m.label} </span>
                      <span className="font-medium">{m.value}</span>
                    </span>
                  ))}
                </div>
              )}
              {isWatchlistStyle && signal.holdingState && (
                <div className="flex items-center gap-1 flex-wrap">
                  <span className="px-1.5 py-0.5 rounded text-[10px] font-bold" style={{
                    background: `${signal.holdingState.statusColor}18`,
                    color: signal.holdingState.statusColor,
                    border: `1px solid ${signal.holdingState.statusColor}45`,
                  }}>
                    持仓状态：{signal.holdingState.statusLabel}
                  </span>
                  <span className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                    {signal.holdingState.action}
                  </span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    因子 {signal.holdingState.factorScore}
                  </span>
                  {signal.holdingState.warnings?.slice(0, 2).map((warning) => (
                    <span key={warning} className="text-[10px]" style={{ color: '#dc2626' }}>⚠ {warning}</span>
                  ))}
                </div>
              )}
              {/* 行2：策略命中 + 6大命中雷达（合并到同一 flex-wrap 容器，避免换行分裂） */}
              {(signal.trackerNote?.includes('共振') || (strategyTags && strategyTags.length > 0) || signal.strategyMode || (isWatchlistStyle && signal.hitTags && signal.hitTags.length > 0)) && (
                <div className="flex items-center gap-1 flex-wrap">
                  {signal.trackerNote?.includes('共振') && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                      style={{ background: 'rgba(234,179,8,0.12)', color: '#ca8a04', border: '1px solid rgba(234,179,8,0.35)' }}
                      title={signal.trackerNote}
                    >
                      🔥 {signal.trackerNote}
                    </span>
                  )}
                  {strategyTags && strategyTags.length > 0 && strategyTags.map(tag => {
                    const isSci = tag === 'BS-科创-V7';
                    const isCy = tag === 'BS-创业-V9';
                    const isLeaderTag = tag === '游资龙头';
                    const isStageTag = tag.startsWith('游资阶段:');
                    const stageName = isStageTag ? tag.replace('游资阶段:', '') : '';
                    const stageInfo = isStageTag ? (LEADER_STAGE_MAP[stageName] || { label: stageName, color: '#06b6d4', icon: '📊' }) : null;
                    const tagColor = isLeaderTag ? '#ef4444'
                      : isStageTag ? stageInfo.color
                      : isSci ? '#a855f7' : isCy ? '#f97316' : '#06b6d4';
                    const tagLabel = isLeaderTag ? '游资龙头'
                      : isStageTag ? stageInfo.label
                      : isSci ? '科创V7' : isCy ? '创业V9' : tag;
                    const tagIcon = isLeaderTag ? '🔥' : isStageTag ? stageInfo.icon : '📊';
                    return (
                      <span
                        key={tag}
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                        style={{ background: `${tagColor}20`, color: tagColor, border: `1px solid ${tagColor}40` }}
                        title={`策略命中: ${tag}`}
                      >
                        {tagIcon} {tagLabel}
                      </span>
                    );
                  })}
                  {signal.strategyMode && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                      style={{
                        background: signal.strategyMode === 'breakout' ? 'rgba(239,68,68,0.12)' : 'rgba(59,130,246,0.12)',
                        color: signal.strategyMode === 'breakout' ? '#ef4444' : '#3b82f6',
                        border: `1px solid ${signal.strategyMode === 'breakout' ? 'rgba(239,68,68,0.35)' : 'rgba(59,130,246,0.35)'}`,
                      }}
                      title={signal.strategyMode === 'breakout' ? '放量突破不破5/10日线' : '缩量回踩仍守20日线'}
                    >
                      {signal.strategyMode === 'breakout' ? '🔥 放量突破' : '📉 缩量回踩'}
                    </span>
                  )}
                  {/* 6 大命中雷达标签内联到同一行（仅 watchlist 模式），与上方策略标签共享 flex-wrap 容器 */}
                  {isWatchlistStyle && hitCfgs.length > 0 && (
                    (() => {
                      return hitCfgs.map(cfg => (
                        <span
                          key={`hit-${cfg.key}`}
                          className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                          style={{ background: `${cfg.color}1a`, color: cfg.color, border: `1px solid ${cfg.color}55` }}
                          title={cfg.action}
                        >
                          <span>{cfg.icon}</span>
                          <span>{cfg.label}</span>
                        </span>
                      ));
                    })()
                  )}
                </div>
              )}
              {/* 行3：风险信号 / 操作（riskLevel/价量背离/风险退出/委托） */}
              {(riskLevel || hasPriceVolumeDivergence || signal.worstSeverity || hasOrders) && (
                <div className="flex items-center gap-1 flex-wrap">
                  {riskLevel && (
                    <span className="px-1 py-0.5 rounded text-[10px]" style={{ background: `${riskColor}15`, color: riskColor }}>{riskLabel}</span>
                  )}
                  {hasPriceVolumeDivergence && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                      style={{
                        background: 'rgba(220,38,38,0.12)',
                        color: '#dc2626',
                        border: '1px solid rgba(220,38,38,0.35)',
                      }}
                      title="技术破位但主力大额流入，存在主力刻意砸盘吸筹的欺骗性博弈"
                    >
                      ⚠️ 警惕：价量背离 / 疑似洗盘
                    </span>
                  )}
                  {signal.worstSeverity && (
                    <span
                      className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                      style={{
                        background: signal.worstSeverity === 'critical' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.12)',
                        color: signal.worstSeverity === 'critical' ? '#ef4444' : '#f59e0b',
                        border: `1px solid ${signal.worstSeverity === 'critical' ? 'rgba(239,68,68,0.4)' : 'rgba(245,158,11,0.35)'}`,
                      }}
                      title={signal.worstReason || '风险退出'}
                    >
                      🛡️ {signal.worstLabel || '风险退出'}
                    </span>
                  )}
                  {hasOrders && (
                    <button onClick={(e) => { e.stopPropagation(); setOrderOpen(true); }} className="px-1 py-0.5 rounded text-[10px] cursor-pointer" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
                      📋 {orders.length}笔委托
                    </button>
                  )}
                </div>
              )}
              {/* 风险退出指标条 */}
              {signal.worstSeverity && (
                <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
                  {signal.worstReason && (
                    <span className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }} title={signal.worstReason}>
                      {signal.worstReason}
                    </span>
                  )}
                  {signal.riskSignals && signal.riskSignals.length > 0 && signal.riskSignals.map((rs, i) => (
                    <span key={i} className="text-[10px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.08)', color: rs.severity === 'critical' ? '#ef4444' : '#f59e0b' }}>
                      {rs.label}
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>

        </div>{/* module-info：仅含头部；下方分组改为卡片级全宽横条 + 每行左盘后|右实时 */}

      </div>

      {/* ===================== 数据分组区：每个分组一行，行内 左盘后 | 右实时，分组之间全宽横条 ===================== */}
      {/* 新顺序（2026-07-18 v2）：
          核心诊断：1.🤖AI联动诊断 → 2.📈个股技术指标 → 3.🎯BS区间 → 4.🏛️机构/⚔️游资
          技术依据：6.💰资金流向
          环境参考：7.🏭板块 → 8.🌐市场 → 9.持仓
          原文件备份：SignalCardV4.jsx.bak.20260718_101712
      */}

      {/* —— 0. 📊 综合评分已上移至 v4 标识层（顶部评分环），8 维度评分已分散到对应分组 —— */}

      {/* —— 1. 🤖 AI 联动诊断（盘后 ‖ 实时 双列，规则化合成）—— */}
      <AiDiagnosisModule
        dash={dash}
        inst={dash?.institution_flow}
        rt={dash?.realtime}
        rtAvail={!!dash?.realtime?.available}
      />

      {/* —— 2. 📈 个股技术指标（盘后 KDJ/MACD/MA/支撑 | 实时 现价 vs MA/支撑/阻力）—— */}
      {(signal.indicators?.kdj_k || signal.indicators?.macd) && (() => {
        const ind = signal.indicators;
        // 实时价：优先 intraday 末尾点的 price，其次 signal.quote.price
        const idArr = rtDash?.intraday || [];
        const lastIntradayPrice = idArr.length ? idArr[idArr.length - 1]?.price : null;
        const curPrice = lastIntradayPrice ?? signal?.quote?.price ?? 0;
        const rowClass = "flex items-center gap-1 px-2 rounded text-[10px] tabular-nums min-h-[20px] whitespace-nowrap flex-nowrap";
        const rowStyleL = { background: 'rgba(59,130,246,0.04)' };
        const rowStyleRt = { background: 'rgba(34,197,94,0.04)' };
        const emptyRow = <div className={rowClass} style={{ visibility: 'hidden' }}>&nbsp;</div>;

          // 盘后 KDJ/MACD/MA/支撑（从 signal.indicators 读取）

          // 左盘后 — KDJ
          const kdjJ = ind?.kdj_j;
          const kdjColor = kdjJ == null ? 'var(--text-muted)' : kdjJ >= 80 ? '#ef4444' : kdjJ <= 20 ? '#22c55e' : 'var(--text-primary)';
          const kdjRow = kdjJ != null ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>KDJ</span>
              <span style={{ color: kdjColor }} className="font-mono">
                K{ind?.kdj_k?.toFixed(1)} D{ind?.kdj_d?.toFixed(1)} J{kdjJ.toFixed(1)}
              </span>
              {kdjJ >= 80 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>超买</span>}
              {kdjJ <= 20 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>超卖</span>}
              {kdjJ > 20 && kdjJ < 80 && ind?.kdj_k != null && ind?.kdj_d != null && ind?.kdj_k > ind?.kdj_d && (
                <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>K上穿D</span>
              )}
              {kdjJ > 20 && kdjJ < 80 && ind?.kdj_k != null && ind?.kdj_d != null && ind?.kdj_k < ind?.kdj_d && (
                <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>K下穿D</span>
              )}
            </div>
          ) : emptyRow;

          // 左盘后 — MACD
          const macdVal = ind?.macd;
          const macdColor = macdVal == null ? 'var(--text-muted)' : macdVal >= 0 ? '#ef4444' : '#22c55e';
          const dif = ind?.dif, dea = ind?.dea;
          const isGoldenCross = dif != null && dea != null && dif > dea;
          const isDeathCross = dif != null && dea != null && dif < dea;
          const macdRow = macdVal != null ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>MACD</span>
              <span style={{ color: macdColor }} className="font-mono">
                {macdVal.toFixed(3)} / DIF{dif?.toFixed(3)} DEA{dea?.toFixed(3)}
              </span>
              {isGoldenCross && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>金叉</span>}
              {isDeathCross && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>死叉</span>}
            </div>
          ) : emptyRow;

          // 左盘后 — MA
          const maRow = (ind?.ma5 != null && ind?.ma20 != null) ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>MA</span>
              <span style={{ color: ind.ma5 >= ind.ma20 ? '#ef4444' : '#22c55e' }} className="font-mono">
                MA5 {ind.ma5?.toFixed(2)} / MA20 {ind.ma20?.toFixed(2)}
              </span>
              {ind.ma5 > ind.ma20 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>多头</span>}
              {ind.ma5 < ind.ma20 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e' }}>空头</span>}
            </div>
          ) : emptyRow;

          // 左盘后 — 支撑/阻力
          const srRow = (ind?.support != null || ind?.resistance != null) ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>支撑</span>
              <span style={{ color: '#22c55e' }} className="font-mono">{ind?.support?.toFixed(2) ?? '--'}</span>
              <span style={{ color: 'var(--text-muted)' }}>/ 阻力</span>
              <span style={{ color: '#ef4444' }} className="font-mono">{ind?.resistance?.toFixed(2) ?? '--'}</span>
            </div>
          ) : emptyRow;

          // 左盘后 — RSI 14（从 signal.indicators.rsi）
          const rsiVal = ind?.rsi;
          const rsiColor = rsiVal == null ? 'var(--text-muted)' : rsiVal >= 70 ? '#ef4444' : rsiVal <= 30 ? '#22c55e' : 'var(--text-primary)';
          const rsiRow = rsiVal != null ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>RSI</span>
              <span className="font-mono" style={{ color: rsiColor }}>{rsiVal.toFixed(1)}</span>
              {rsiVal >= 70 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>超买</span>}
              {rsiVal <= 30 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>超卖</span>}
              {rsiVal > 30 && rsiVal < 70 && (
                <span className="text-[9px] px-1 rounded" style={{ background: rsiVal >= 50 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)', color: rsiVal >= 50 ? '#ef4444' : '#22c55e' }}>
                  {rsiVal >= 50 ? '偏强' : '偏弱'}
                </span>
              )}
            </div>
          ) : emptyRow;

          // 左盘后 — 量比（从 dash.features.volume_ratio）
          const vrVal = dash?.features?.volume_ratio;
          const vrColor = vrVal == null ? 'var(--text-muted)' : vrVal >= 1.5 ? '#ef4444' : vrVal <= 0.5 ? '#22c55e' : 'var(--text-primary)';
          const vrRow = vrVal != null ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>量比</span>
              <span className="font-mono" style={{ color: vrColor }}>{vrVal.toFixed(2)}</span>
              {vrVal >= 1.5 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>放量</span>}
              {vrVal <= 0.5 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>缩量</span>}
              {vrVal > 0.5 && vrVal < 1.5 && <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(148,163,184,0.15)', color: 'var(--text-muted)' }}>正常</span>}
            </div>
          ) : emptyRow;

          // 左盘后 — BIAS 乖离率（现价 vs MA5/MA20 偏离%）
          const biasMa5 = (ind?.ma5 != null && curPrice) ? (curPrice - ind.ma5) / ind.ma5 * 100 : null;
          const biasMa20 = (ind?.ma20 != null && curPrice) ? (curPrice - ind.ma20) / ind.ma20 * 100 : null;
          const biasRow = (biasMa5 != null && biasMa20 != null) ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>乖离</span>
              <span className="font-mono" style={{ color: biasMa5 >= 0 ? '#ef4444' : '#22c55e' }}>
                MA5{biasMa5 >= 0 ? '+' : ''}{biasMa5.toFixed(2)}%
              </span>
              <span style={{ color: 'var(--text-muted)' }}>/</span>
              <span className="font-mono" style={{ color: biasMa20 >= 0 ? '#ef4444' : '#22c55e' }}>
                MA20{biasMa20 >= 0 ? '+' : ''}{biasMa20.toFixed(2)}%
              </span>
              {(Math.abs(biasMa5) >= 5 || Math.abs(biasMa20) >= 10) && (
                <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(245,158,11,0.15)', color: '#f59e0b' }}>⚠回拉</span>
              )}
            </div>
          ) : emptyRow;

          // 实时 KDJ/MACD：基于当日分时序列实时计算；无 intraday 数据则空值
          const idPrices = (rtDash?.intraday || [])
            .map((d) => d?.price)
            .filter((v) => typeof v === 'number' && !Number.isNaN(v));
          // calcEma / calcIntradayMacd / calcIntradayKdj 已上移到模块顶层（纯函数，避免每次 render 重建）

          // 实时右侧 — 行1: 分钟KDJ（基于当日 intraday 序列实时计算；与盘后日级 KDJ 口径不同，不可直接比较）
          const rtKdj = calcIntradayKdj(idPrices);
          const rtKdjRow = rtKdj ? (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }} title="基于当日分时序列计算，与盘后日级 KDJ 口径不同">分KDJ</span>
              <span className="font-mono flex-shrink-0" style={{ color: rtKdj.j >= 80 ? '#ef4444' : rtKdj.j <= 20 ? '#22c55e' : 'var(--text-primary)' }}>
                K{rtKdj.k.toFixed(1)} D{rtKdj.d.toFixed(1)} J{rtKdj.j.toFixed(1)}
              </span>
              {rtKdj.j >= 80 && <span className="text-[9px] px-1 rounded flex-shrink-0" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>超买</span>}
              {rtKdj.j <= 20 && <span className="text-[9px] px-1 rounded flex-shrink-0" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>超卖</span>}
            </div>
          ) : emptyRow;

          // 实时右侧 — 行2: 分钟MACD（基于当日 intraday EMA(12)/EMA(26) 计算；与盘后日级 MACD 口径不同）
          const rtMacd = calcIntradayMacd(idPrices);
          const rtMacdRow = rtMacd ? (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }} title="基于当日分时序列计算，与盘后日级 MACD 口径不同">分MACD</span>
              <span className="font-mono flex-shrink-0" style={{ color: rtMacd.macd >= 0 ? '#ef4444' : '#22c55e' }}>
                {rtMacd.macd.toFixed(3)} / DIF{rtMacd.dif.toFixed(3)} DEA{rtMacd.dea.toFixed(3)}
              </span>
              {rtMacd.dif > rtMacd.dea && <span className="text-[9px] px-1 rounded flex-shrink-0" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>金叉</span>}
              {rtMacd.dif < rtMacd.dea && <span className="text-[9px] px-1 rounded flex-shrink-0" style={{ background: 'rgba(34,197,94,0.15)', color: '#22c55e' }}>死叉</span>}
            </div>
          ) : emptyRow;
          // 实时右侧 — 行3: MA5 / MA20 已删除(与盘后左栏重复, 盘后/实时用同一份 indicators 数据)
          const rtMaRow = emptyRow;
          // 实时右侧 — 行4: 现价距 支撑 / 阻力（仅偏离%，紧凑单行）
          const pctSup = (ind?.support != null && curPrice) ? (curPrice - ind.support) / ind.support * 100 : null;
          const pctRes = (ind?.resistance != null && curPrice) ? (curPrice - ind.resistance) / ind.resistance * 100 : null;
          const rtSrRow = (pctSup != null || pctRes != null) ? (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>支撑</span>
              {pctSup != null && (
                <span className="font-mono font-bold flex-shrink-0" style={{ color: pctSup >= 0 ? '#ef4444' : '#22c55e' }}>
                  支撑{pctSup >= 0 ? '+' : ''}{pctSup.toFixed(2)}%
                </span>
              )}
              {pctSup != null && pctRes != null && <span className="flex-shrink-0" style={{ color: 'var(--text-muted)' }}>/</span>}
              {pctRes != null && (
                <span className="font-mono font-bold flex-shrink-0" style={{ color: pctRes >= 0 ? '#ef4444' : '#22c55e' }}>
                  阻力{pctRes >= 0 ? '+' : ''}{pctRes.toFixed(2)}%
                </span>
              )}
            </div>
          ) : emptyRow;

          // 实时右侧 — 行5: 5分钟涨跌 / 日内振幅（替换原 RSI 占位）
          // 取近 5 个 intraday 点（约5分钟）的涨跌；振幅为整日 high-low / low
          const idArrRt = rtDash?.intraday || [];
          const rt5MinChg = (() => {
            const n = idArrRt.length;
            if (n < 2) return null;
            const last = idArrRt[n - 1]?.price;
            const prev = idArrRt[Math.max(0, n - 6)]?.price;
            if (last == null || prev == null || !prev) return null;
            return (last - prev) / prev * 100;
          })();
          const rtAmplitude = (() => {
            const prices = idArrRt.map((d) => d?.price).filter((v) => v != null && v > 0);
            if (prices.length < 2) return null;
            const hi = Math.max(...prices), lo = Math.min(...prices);
            return (hi - lo) / lo * 100;
          })();
          const rtRsiRow = (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>5分钟</span>
              {rt5MinChg == null ? (
                <span className="text-[10px] italic" style={{ color: 'var(--text-muted)' }}>无数据</span>
              ) : (
                <>
                  <span className="font-mono font-bold" style={{ color: rt5MinChg >= 0 ? '#ef4444' : '#22c55e' }}>
                    {rt5MinChg >= 0 ? '+' : ''}{rt5MinChg.toFixed(2)}%
                  </span>
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>· 振幅</span>
                  <span className="font-mono" style={{ color: rtAmplitude >= 3 ? '#f59e0b' : 'var(--text-primary)' }}>
                    {rtAmplitude != null ? `${rtAmplitude.toFixed(2)}%` : '--'}
                  </span>
                </>
              )}
            </div>
          );

          // 实时右侧 — 行6: 主力净流入占比 / 盘口强弱（替换原 量比 占位）
          // 主力净流入占比 = rtDash.main_net / (|main_net| + |retail_net|) × 100%
          // 盘口强弱：rtDash.main_net > 0 偏买；< 0 偏卖；金额越大越强
          const rtMainNet = rtDash?.main_net ?? null;
          const rtRetailNet = rtDash?.retail_net ?? null;
          const rtMainRatio = (() => {
            const absM = Math.abs(rtMainNet || 0);
            const absR = Math.abs(rtRetailNet || 0);
            const sum = absM + absR;
            if (sum === 0 || rtMainNet == null) return null;
            return rtMainNet / sum * 100;
          })();
          const rtVrRow = (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>主力占比</span>
              {rtMainRatio == null ? (
                <span className="text-[10px] italic" style={{ color: 'var(--text-muted)' }}>无数据</span>
              ) : (
                <>
                  <span className="font-mono font-bold" style={{ color: rtMainRatio >= 50 ? '#ef4444' : '#22c55e' }}>
                    {rtMainRatio.toFixed(1)}%
                  </span>
                  <span className="text-[9px] px-1 rounded" style={{
                    background: rtMainRatio >= 60 ? 'rgba(239,68,68,0.15)' : rtMainRatio >= 50 ? 'rgba(239,68,68,0.08)' : rtMainRatio <= 40 ? 'rgba(34,197,94,0.15)' : 'rgba(34,197,94,0.08)',
                    color: rtMainRatio >= 50 ? '#ef4444' : '#22c55e',
                  }}>
                    {rtMainRatio >= 60 ? '强买' : rtMainRatio >= 50 ? '偏买' : rtMainRatio <= 40 ? '强卖' : '偏卖'}
                  </span>
                </>
              )}
            </div>
          );

          // 实时右侧 — 行7: 乖离率（用实时价格重算，与 MA 行偏移%同源但更醒目）
          const rtBiasMa5 = (ind?.ma5 != null && curPrice) ? (curPrice - ind.ma5) / ind.ma5 * 100 : null;
          const rtBiasMa20 = (ind?.ma20 != null && curPrice) ? (curPrice - ind.ma20) / ind.ma20 * 100 : null;
          const rtBiasRow = (rtBiasMa5 != null && rtBiasMa20 != null) ? (
            <div className={rowClass} style={rowStyleRt}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>乖离</span>
              <span className="font-mono" style={{ color: rtBiasMa5 >= 0 ? '#ef4444' : '#22c55e' }}>
                MA5{rtBiasMa5 >= 0 ? '+' : ''}{rtBiasMa5.toFixed(2)}%
              </span>
              <span style={{ color: 'var(--text-muted)' }}>/</span>
              <span className="font-mono" style={{ color: rtBiasMa20 >= 0 ? '#ef4444' : '#22c55e' }}>
                MA20{rtBiasMa20 >= 0 ? '+' : ''}{rtBiasMa20.toFixed(2)}%
              </span>
            </div>
          ) : emptyRow;

          // 技术指标综合结论：统一调用 moduleHeaderConfig.getTechConclusion
          const techConclusion = getTechConclusion(ind);

          return (
            <>
              <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
              <div className="px-2.5 py-1.5">
                <div className="flex items-stretch">
                <div className="flex-1 min-w-0 pr-2.5 flex flex-col gap-0.5">
                  <ModuleHeader
                    icon={MODULE_HEADER_CONFIG.tech.icon}
                    name={MODULE_HEADER_CONFIG.tech.name}
                    conclusion={techConclusion.label}
                    conclusionColor={techConclusion.color}
                    title={`基于 KDJ/MACD/MA/RSI 综合判断`}
                  />
                  {kdjRow}
                  {macdRow}
                  {maRow}
                  {srRow}
                  {rsiRow}
                  {vrRow}
                  {biasRow}
                </div>
                <div className="shrink-0" style={{ width: '1.5px', backgroundColor: 'rgba(148,163,184,0.35)', margin: '2px 0' }} />
                <div className="flex-1 min-w-0 pl-2.5 flex flex-col gap-0.5">
                  <ModuleHeader
                    icon={MODULE_HEADER_CONFIG.rt.icon}
                    name={stripRealtimePrefix(rtHdr.label)}
                    conclusion={curPrice ? `现价 ${curPrice.toFixed(2)}` : null}
                    conclusionColor="#22c55e"
                    title={`快照: ${rtDash?.snapshot_time || ''}`}
                  />
                    {rtKdjRow}
                    {rtMacdRow}
                    {rtMaRow}
                  {rtSrRow}
                  {rtRsiRow}
                  {rtVrRow}
                  {rtBiasRow}
                </div>
              </div>
            </div>
            </>
          )
        })()}
      {bsInt && bsInt.state !== 'unknown' && (
        <>
          <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
          <div className="px-2.5 py-1.5">
            <div className="flex items-stretch">
              {/* 左：盘后 BS 区间档案（B 起点/S 终点/起止价/持有天数/区间盈亏%） */}
              <div className="flex-1 min-w-0 pr-2.5 flex flex-col gap-0.5">
                {(() => {
                  const isHolding = bsInt.state === 'holding';
                  const stateColor = isHolding ? '#ef4444' : '#f97316';
                  const sd = bsInt.start_date || '';
                  const ed = bsInt.end_date || (isHolding ? '今' : '');
                  const sp = bsInt.start_price || 0;
                  const ep = bsInt.end_price || 0;
                  const hd = bsInt.hold_days || 0;
                  const pnl = bsInt.pnl_pct;
                  // pnlColor: 使用 hex 颜色而非 CSS 变量，避免 `${pnlColor}10` 拼接得到 'var(--text-muted)10' 非法 CSS
                  const pnlColor = pnl == null ? '#94a3b8' : pnl >= 0 ? '#ef4444' : '#22c55e';
                  const pnlText = pnl == null ? '--' : `区间 ${pnl >= 0 ? '+' : ''}${pnl}%`;
                  return (
                    <div className="flex flex-col gap-1">
                      {/* 标题行：左=🎯 BS 区间（醒目色块） / 右=状态徽章（持仓中/已平仓） */}
                      <div className="flex items-center justify-between gap-1">
                        <span className="text-[11px] font-bold tracking-wider px-1.5 py-0.5 rounded"
                          style={{ background: 'rgba(59,130,246,0.12)', color: 'var(--accent-blue, #3b82f6)', border: '1px solid rgba(59,130,246,0.35)' }}>
                          🎯 BS 区间
                        </span>
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold inline-flex items-center gap-1"
                          style={{ background: isHolding ? 'rgba(239,68,68,0.12)' : 'rgba(249,115,22,0.12)', color: stateColor, border: `1px solid ${stateColor}40` }}>
                          <span className={`inline-block w-1.5 h-1.5 rounded-full ${isHolding ? 'animate-pulse' : ''}`} style={{ background: stateColor }} />
                          {isHolding ? '🔴 B 持仓中' : '🟠 S 已平仓'}
                        </span>
                      </div>
                      <div className="text-[10px] tabular-nums" style={{ color: 'var(--text-secondary)' }} title={`B 起点 ${sd} @ ${sp} → ${isHolding ? '当前' : 'S 终点 ' + ed} @ ${ep}`}>
                        <span style={{ color: 'var(--text-muted)' }}>B</span> {sd} <span style={{ color: stateColor }}>{sp.toFixed(2)}</span>
                        <span style={{ color: 'var(--text-muted)' }}> → </span>
                        <span style={{ color: 'var(--text-muted)' }}>{isHolding ? '今' : 'S'}</span> {ed} <span style={{ color: stateColor }}>{ep.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center justify-between gap-1 px-1 py-0.5 rounded" style={{ background: `${pnlColor}10` }}>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>持 {hd} 天</span>
                        <span className="text-[11px] font-bold tabular-nums" style={{ color: pnlColor }}>
                          {pnlText}
                        </span>
                      </div>
                      {/* 左栏底部：BS 区间日 K 走势（B 起点 → S 终点/今天，含起止标记和区间盈亏%） */}
                      {bsKlines.length >= 1 && (
                        <div className="mt-0.5 pt-0.5" style={{ borderTop: '0.5px dashed rgba(148,163,184,0.18)' }}>
                          <BSRangeSparkline klines={bsKlines} bsInt={bsInt} />
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
              {/* 竖分割线 */}
              <div className="shrink-0" style={{ width: '1.5px', backgroundColor: 'rgba(148,163,184,0.35)', margin: '2px 0' }} />
              {/* 右：实时对照（当前价 + 当日涨跌幅，跟左栏 BS 区间不重复） */}
              <div className="flex-1 min-w-0 pl-2.5 flex flex-col gap-0.5">
                {(() => {
                  // rtHdr 已在组件顶部 useMemo 缓存，此处直接复用
                  const isHolding = bsInt.state === 'holding';
                  // 当前价：优先 intraday 末尾点 price，其次 signal.quote.price
                  const idArrBs = rtDash?.intraday || [];
                  const lastIntraday = idArrBs.length ? idArrBs[idArrBs.length - 1] : null;
                  const curPrice = lastIntraday?.price ?? signal?.quote?.price ?? 0;
                  // 当日涨跌幅：从分时数据最后一点拿（盘中实时 / 收盘后定值）
                  const dayPct = lastIntraday?.pct_chg ?? signal?.quote?.pct_chg ?? null;
                  const dayColor = dayPct == null ? 'var(--text-muted)' : dayPct >= 0 ? '#ef4444' : '#22c55e';
                  return (
                    <div className="flex flex-col gap-1">
                      {/* 右侧标题：时间标签独占一行，避免和现价/盈亏挤在一起重叠 */}
                      <div className="mb-0.5">
                        <span className="text-[9px] font-bold tracking-wider whitespace-nowrap" style={{ color: rtHdr.color }} title={`快照: ${rtDash?.snapshot_time || ''}`}>
                          {rtHdr.label}
                        </span>
                      </div>
                      {/* 现价行：只显示当前价（不重复 B 起点） */}
                      <div className="flex items-center justify-between gap-1 text-[10px] tabular-nums">
                        <span style={{ color: 'var(--text-muted)' }}>实时价</span>
                        {curPrice ? (
                          <span className="font-bold" style={{ color: dayColor }}>现 {curPrice.toFixed(2)}</span>
                        ) : (
                          <span className="font-bold" style={{ color: 'var(--text-muted)' }}>--</span>
                        )}
                      </div>
                      {/* 当日涨幅：跟盘中分时实时联动，不跟 BS 区间（已平仓也保留，因为还有盘中观察价值） */}
                      <div className="flex items-center justify-between gap-1 px-1 py-0.5 rounded" style={{ background: `${dayColor}10` }}>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>当日</span>
                        <span className="text-[11px] font-bold tabular-nums" style={{ color: dayColor }}>
                          {dayPct == null ? '--' : `${dayPct >= 0 ? '+' : ''}${dayPct.toFixed(2)}%`}
                        </span>
                      </div>
                      {/* 右栏底部：当日分时 K 线（实时价格走势） */}
                      {rtDash?.intraday && rtDash.intraday.length >= 2 && (
                        <div className="mt-0.5 pt-0.5" style={{ borderTop: '0.5px dashed rgba(148,163,184,0.18)' }}>
                          <IntradaySparkline data={rtDash.intraday} showPriceLabel={false} />
                        </div>
                      )}
                    </div>
                  );
                })()}
              </div>
            </div>
          </div>
        </>
      )}


      {/* —— 3. 🏛️ 机构 / ⚔️ 游资（左右严格 2 行对齐：机构 / 游资）—— */}
      <>
      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
      <div className="px-2.5 py-1.5">
        {(() => {
          const rowClass = "flex items-center gap-1 px-2 rounded text-[10px] tabular-nums min-h-[20px] whitespace-nowrap flex-nowrap";
          const rowStyleL = { background: 'rgba(59,130,246,0.04)' };
          const rowStyleR = { background: 'rgba(34,197,94,0.04)' };
          const emptyRow = <div className={rowClass} style={{ visibility: 'hidden' }}>&nbsp;</div>;

          // 机构信号评分 → 颜色 + 进度条
          const instScore = dash?.institution_signal;
          const rtInstScore = rtDash?.institution_signal;

          // 左盘后 — 行1: 机构（标签简化为 吸筹/出逃/观望）
          const instNet = mfDash?.super_large_net != null ? mfDash.super_large_net : signal.moneyFlow?.super_large;
          const yzNet = mfDash?.large_net != null ? mfDash.large_net : signal.moneyFlow?.large;
          const fmtInst = mfDash ? fmtYuan : fmtWanYi;
          const instLabel = instNet == null ? '无数据' : instNet > 0 ? '吸筹' : instNet < 0 ? '出逃' : '观望';
          const yzLabel = yzNet == null ? '无数据' : yzNet > 0 ? '跟进' : yzNet < 0 ? '砸盘' : '蛰伏';
          const instColor = instNet == null ? 'var(--text-muted)' : instNet > 0 ? '#ef4444' : instNet < 0 ? '#22c55e' : '#64748b';
          const yzColor = yzNet == null ? 'var(--text-muted)' : yzNet > 0 ? '#ef4444' : yzNet < 0 ? '#22c55e' : '#64748b';
          const leftInst = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>🏛️ 机构</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                {instScore != null && (
                  <div className="h-full rounded-full" style={{ width: `${instScore}%`, background: scoreColor(instScore) }} />
                )}
              </div>
              <span className="ml-auto font-bold flex-shrink-0" style={{ color: instColor }}>{instLabel}</span>
              <span className="font-mono tabular-nums flex-shrink-0" style={{ color: instColor }}>
                {instNet == null ? '--' : `${instNet >= 0 ? '+' : ''}${fmtInst(instNet)}`}
              </span>
            </div>
          );
          const leftYz = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>⚔️ 游资</span>
              {/* 游资无独立评分，留空 flex-1 占位保持与机构行进度条对齐 */}
              <div className="flex-1 min-w-0" />
              <span className="ml-auto font-bold flex-shrink-0" style={{ color: yzColor }}>{yzLabel}</span>
              <span className="font-mono tabular-nums flex-shrink-0" style={{ color: yzColor }}>
                {yzNet == null ? '--' : `${yzNet >= 0 ? '+' : ''}${fmtInst(yzNet)}`}
              </span>
            </div>
          );

          // 右实时 — 行1: 实时主力净流 + 评分进度条
          const useDash = !!rtDash?.available;
          const src = useDash ? rtDash : realtimeFlow;
          const rtMainForce = useDash ? (src?.main_net ?? null) : (src?.main_force_inflow ?? null);
          const fmtRt = useDash ? fmtYuan : fmtWanYi;
          const mfColor = rtMainForce == null ? 'var(--text-muted)' : rtMainForce >= 0 ? '#ef4444' : '#22c55e';
          const mfLabel = rtMainForce == null ? '无数据' : rtMainForce > 0 ? '流入' : rtMainForce < 0 ? '流出' : '持平';
          const time = ((rtDash?.snapshot_time) || realtimeFlow?.latest_time)?.slice(11, 16) || '';
          const rtMainRow = (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>主力</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                {rtInstScore != null && (
                  <div className="h-full rounded-full" style={{ width: `${rtInstScore}%`, background: scoreColor(rtInstScore) }} />
                )}
              </div>
              <span className="ml-auto font-bold flex-shrink-0" style={{ color: mfColor }}>{mfLabel}</span>
              <span className="font-mono tabular-nums flex-shrink-0" style={{ color: mfColor }}>
                {rtMainForce == null ? '--' : `${rtMainForce >= 0 ? '+' : ''}${fmtRt(rtMainForce)}`}
              </span>
            </div>
          );
          // 右实时 — 行2: 实时散户净流（与左侧行2 游资 严格对齐，补齐散户评分进度条）
          // 散户评分 = 100 - rtInstScore（散户与主力对冲：主力流入则散户流出）
          const rtRetailScore = rtInstScore != null ? (100 - rtInstScore) : null;
          let rtRetailRow = emptyRow;
          if (useDash && rtDash?.retail_net != null) {
            const r = rtDash.retail_net;
            const rColor = r >= 0 ? '#ef4444' : '#22c55e';
            const rLabel = r > 0 ? '流入' : r < 0 ? '流出' : '持平';
            rtRetailRow = (
              <div className={rowClass} style={rowStyleR}>
                <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>散户</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                  {rtRetailScore != null && (
                    <div className="h-full rounded-full" style={{ width: `${rtRetailScore}%`, background: scoreColor(rtRetailScore) }} />
                  )}
                </div>
                <span className="ml-auto font-bold flex-shrink-0" style={{ color: rColor }}>{rLabel}</span>
                <span className="font-mono tabular-nums flex-shrink-0" style={{ color: rColor }}>
                  {`${r >= 0 ? '+' : ''}${fmtRt(r)}`}
                </span>
              </div>
            );
          } else if (!useDash && realtimeFlow?.retail_flow != null) {
            const r = realtimeFlow.retail_flow;
            const rColor = r >= 0 ? '#ef4444' : '#22c55e';
            const rLabel = r > 0 ? '流入' : r < 0 ? '流出' : '持平';
            rtRetailRow = (
              <div className={rowClass} style={rowStyleR}>
                <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>散户</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                  {rtRetailScore != null && (
                    <div className="h-full rounded-full" style={{ width: `${rtRetailScore}%`, background: scoreColor(rtRetailScore) }} />
                  )}
                </div>
                <span className="ml-auto font-bold flex-shrink-0" style={{ color: rColor }}>{rLabel}</span>
                <span className="font-mono tabular-nums flex-shrink-0" style={{ color: rColor }}>
                  {`${r >= 0 ? '+' : ''}${fmtRt(r)}`}
                </span>
              </div>
            );
          } else {
            // 无 net 金额时仍渲染占位行（保持 2 行对齐）
            rtRetailRow = (
              <div className={rowClass} style={rowStyleR}>
                <span className="text-[10px] flex-shrink-0 font-medium w-12" style={{ color: 'var(--text-muted)' }}>散户</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                {rtRetailScore != null && (
                  <div className="h-full rounded-full" style={{ width: `${rtRetailScore}%`, background: scoreColor(rtRetailScore) }} />
                )}
                </div>
                <span className="ml-auto font-bold flex-shrink-0" style={{ color: 'var(--text-muted)' }}>—</span>
                <span className="font-mono tabular-nums flex-shrink-0" style={{ color: 'var(--text-muted)' }}>—</span>
              </div>
            );
          }

          // 机构/游资综合结论：统一调用 moduleHeaderConfig.getOrgConclusion
          const orgConclusion = getOrgConclusion({ instNet, yzNet });

          return (
            <div className="flex items-stretch">
              <div className="flex-1 min-w-0 pr-2.5 flex flex-col gap-0.5">
                <ModuleHeader
                  icon="🏛️"
                  name="机构 / 游资"
                  conclusion={orgConclusion.label}
                  conclusionColor={orgConclusion.color}
                  title={`机构净额: ${instNet != null ? fmtInst(instNet) : '--'} · 游资净额: ${yzNet != null ? fmtInst(yzNet) : '--'}`}
                />
                {leftInst}
                {leftYz}
              </div>
              <div className="shrink-0" style={{ width: '1.5px', backgroundColor: 'rgba(148,163,184,0.35)', margin: '2px 0' }} />
              <div className="flex-1 min-w-0 pl-2.5 flex flex-col gap-0.5">
                <ModuleHeader
                  icon="🟢"
                  name={stripRealtimePrefix(rtHdr.label)}
                  conclusion={time || null}
                  conclusionColor={rtHdr.color}
                  title={`快照: ${rtDash?.snapshot_time || ''}`}
                />
                {rtMainRow}
                {rtRetailRow}
              </div>
            </div>
          );
        })()}
      </div>
      </>


      {/* —— 6. 💰 资金流向（横条下方全宽：左=盘后 | 右=实时）—— */}
      {/* —— 横条 above 资金流向 —— */}
      <>
      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />

      {/* ========== 资金流向模块（横条下方全宽：左=盘后 | 右=实时，参考综合评分系统排版） ========== */}
      <div className="signalcard-module module-flow px-2.5 py-1.5" style={{ background: 'var(--bg-card)' }}>

        {/* 当日分时迷你走势已移至右栏"实时"区域内（紧跟实时标签行） */}

        {/* 左右两栏：盘后 | 实时，中间明显竖分割线 */}
        {/* 共享行容器：CSS Grid 3列（左1fr | 分割线1.5px | 右1fr），每行天然等高对齐 */}
        <div className="grid" style={{ gridTemplateColumns: '1fr 1.5px 1fr', columnGap: '6px', rowGap: '2px' }}>
          {/* 行1: 标题行 — 左=💰 资金流向 + 主力爆买结论 + 📊 盘后日期；右=🟢 动态时间标签 */}
          <div className="min-w-0">
            {(() => {
              const mainNet = mfDash?.main_net != null ? mfDash.main_net : (signal.moneyFlow?.super_large != null ? signal.moneyFlow.super_large : null);
              // 资金流向综合结论：统一调用 moduleHeaderConfig.getFlowConclusion
              const flowConclusion = getFlowConclusion({ hitTags: signal.hitTags, mainNet });
              const conclusion = flowConclusion.label;
              const conclusionColor = flowConclusion.color;
              const pd = dash?.date ? dash.date.replace(/-/g, '') : (signal.moneyFlow?.trade_date ? String(signal.moneyFlow.trade_date) : null);
              const afterDateStr = pd ? `${pd.slice(0,4)}/${pd.slice(4,6)}/${pd.slice(6,8)}` : '';
              const _secFlowVal = sfDash?.net_flow != null ? sfDash.net_flow : (signal.sectorTrend?.total_net_flow ?? null);
              return (
                <ModuleHeader
                  icon={MODULE_HEADER_CONFIG.flow.icon}
                  name={MODULE_HEADER_CONFIG.flow.name}
                  conclusion={conclusion}
                  conclusionColor={conclusionColor}
                  title={`主力净额: ${mainNet != null ? fmtYuan(mainNet) : '--'} · 板块资金: ${_secFlowVal != null ? (_secFlowVal >= 0 ? '+' : '') + fmtWanYi(_secFlowVal) : '--'}`}
                  extra={afterDateStr && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
                      📊 盘后 {afterDateStr}
                    </span>
                  )}
                />
              );
            })()}
          </div>
          <div className="self-stretch" style={{ background: 'rgba(148,163,184,0.35)' }} />
          <div className="min-w-0">
            {(() => {
              // rtHdr 已在组件顶部 useMemo 缓存，此处直接复用
              // 板块资金净流入
              const secFlowVal2 = sfDash ? sfDash.net_flow : signal.sectorTrend?.total_net_flow;
              const secFlowStr = secFlowVal2 == null ? null : (secFlowVal2 >= 0 ? '+' : '') + (sfDash ? fmtYuan(secFlowVal2) : fmtWanYi(secFlowVal2));
              const secFlowColor = secFlowVal2 == null ? 'var(--text-muted)' : (secFlowVal2 >= 0 ? '#ef4444' : '#22c55e');
              // DimPill 额外辅助
              const extraPills = dash && (() => {
                const rt = dash.realtime || {};
                const rtAvail = !!rt.available;
                return (
                  <>
                    <DimPill label="资金分布分" afterVal={dash.capital_momentum} rtVal={rt.capital_momentum} rtAvail={rtAvail} />
                    <DimPill label="成交量能分" afterVal={dash.volume_health} rtVal={rt.volume_health} rtAvail={rtAvail} />
                  </>
                );
              })();
              return (
                <ModuleHeader
                  icon="🟢"
                  name={rtHdr.label.replace(/^🟢\s*/, '').replace(/^🟠\s*/, '').replace(/^上一交易日\s*/, '上一交易日 ')}
                  conclusion={secFlowStr ? `板块资金 ${secFlowStr}` : null}
                  conclusionColor={secFlowColor === 'var(--text-muted)' ? '#64748b' : secFlowColor}
                  title={rtHdr.title}
                  extra={extraPills}
                />
              );
            })()}
          </div>

          {/* 行2 已删除: 双饼图 - 与下方5档横条信息完全重复, 且ReactECharts渲染开销大 */}

          {/* 行3-7: 5档横条（每档一行：左[特大,大单,中单,小单,散单] / 右[空,主力,空,散户,板块]） */}
          {(() => {
            // mfRows / rtRows 已在组件顶部 useMemo 缓存，此处直接复用
            const leftRows = mfRows;
            const rightRows = rtRows;
            const leftMaxAbs = Math.max(...leftRows.filter(r => r).map(r => Math.abs(r.val)), 1);
            const leftFmtMF = mfDash ? fmtYuan : fmtWanYi;
            const rightMaxAbs = Math.max(...rightRows.map(r => Math.abs(r.val || 0)), 1);
            const leftAvail = signal.moneyFlow?.available;
            // 空占位行：与5档横条同结构，visibility:hidden 保持等高
            const hiddenBar = (
              <div className="flex items-center gap-1 text-[10px] whitespace-nowrap flex-nowrap" style={{ visibility: 'hidden' }}>
                <span className="w-6 flex-shrink-0">—</span>
                <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" />
                <span className="w-12 text-right flex-shrink-0 whitespace-nowrap">—</span>
              </div>
            );
            return [0, 1, 2, 3, 4].map(i => {
              const leftR = leftRows[i];
              const rightR = rightRows[i];
              return (
                <React.Fragment key={i}>
                  {/* 左 */}
                  <div className="min-w-0">
                    {leftAvail ? (
                      leftR ? (
                        (() => {
                          const isPos = leftR.val >= 0;
                          const pct = Math.min(100, Math.abs(leftR.val) / leftMaxAbs * 100);
                          return (
                            <div className="flex items-center gap-1 text-[10px] whitespace-nowrap flex-nowrap">
                              <span className="w-6 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{leftR.label}</span>
                              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: isPos ? leftR.color : '#22c55e' }} />
                              </div>
                              <span className="w-12 text-right font-bold flex-shrink-0 whitespace-nowrap" style={{ color: isPos ? '#ef4444' : '#22c55e' }}>
                                {isPos ? '+' : ''}{leftFmtMF(leftR.val)}
                              </span>
                            </div>
                          );
                        })()
                      ) : (
                        // 中单档隐藏占位（mfDash 无此数据）
                        hiddenBar
                      )
                    ) : null}
                  </div>
                  {/* 分割线 */}
                  <div className="self-stretch" style={{ background: 'rgba(148,163,184,0.35)' }} />
                  {/* 右 */}
                  <div className="min-w-0">
                    {rightR.empty ? (
                      // 空占位行：与左栏对应行等高，保持视觉对齐
                      hiddenBar
                    ) : (
                      (() => {
                        const isNull = rightR.val == null;
                        const isPos = !isNull && rightR.val >= 0;
                        const pct = isNull ? 0 : Math.min(100, Math.abs(rightR.val) / rightMaxAbs * 100);
                        return (
                          <div className="flex items-center gap-1 text-[10px] whitespace-nowrap flex-nowrap">
                            <span className="w-6 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{rightR.label}</span>
                            <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                              {isNull ? (
                                <div className="h-full w-full" style={{ background: 'repeating-linear-gradient(45deg, rgba(148,163,184,0.15), rgba(148,163,184,0.15) 3px, transparent 3px, transparent 6px)' }} />
                              ) : (
                                <div className="h-full rounded-full" style={{ width: `${pct}%`, background: isPos ? rightR.color : '#22c55e' }} />
                              )}
                            </div>
                            <span className="w-12 text-right font-bold flex-shrink-0 whitespace-nowrap" style={{ color: isNull ? 'var(--text-muted)' : (isPos ? '#ef4444' : '#22c55e') }}>
                              {isNull ? '—' : `${isPos ? '+' : ''}${fmtYuan(rightR.val)}`}
                            </span>
                          </div>
                        );
                      })()
                    )}
                  </div>
                </React.Fragment>
              );
            });
          })()}

          {/* 行8 已删除: 主力净流入(单日) - 已在上方5档横条和ModuleHeader tooltip中展示, 重复 */}

          {/* 行9 已删除: 主力净流入累计表格 - 5/10日累计对短线决策价值有限, 且个股1日累计与5档横条重复 */}

          {/* 行10 已移至 BS 区间模块右栏（与左栏 BS 区间日 K 走势对齐） */}

          {/* 行11 已删除: 盘中涨跌 - 盘后列空占位 + 实时涨跌已在顶部持仓盈亏模块和行情展示 */}

          {/* 行12-13 已删除: 资金动能 + 板块共振 (与轮动/资金参与度重复, 且板块共振在下方板块模块已有) */}


        </div>

        {/* 底部 MoneyFlowBoard 已删除：饼图移至上方左盘后，5档横条与主力/散户净额上方已有，板块资金净流入顶部已有，避免重复 */}
      </div>
      </>


      {/* —— 7. 🏭 板块（左右严格 3 行对齐：板块+热度 / 趋势 / 动能）—— */}
      <>
      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
      <div className="px-2.5 py-1.5">
        {(() => {
          const rowClass = "flex items-center gap-1 px-2 rounded text-[10px] tabular-nums min-h-[20px] whitespace-nowrap flex-nowrap";
          const rowStyleL = { background: 'rgba(168,85,247,0.04)' };
          const rowStyleR = { background: 'rgba(34,197,94,0.04)' };
          const emptyRow = <div className={rowClass} style={{ visibility: 'hidden' }}>&nbsp;</div>;

          // 板块评分（共振分）→ 颜色梯度
          const sectorScore = dash?.sector_resonance;

          // 行1: 左=板块名+热度 / 右=板块资金净流入（盘后）+ 涨幅
          const heatVal = sectorTrend?.latest_heat;
          const heatColor = heatVal == null ? 'var(--text-muted)' : heatVal >= 60 ? '#ef4444' : heatVal >= 40 ? '#eab308' : '#3b82f6';
          const heatTrendIcon = sectorTrend?.heat_trend === 'up' ? '↑' : sectorTrend?.heat_trend === 'down' ? '↓' : '→';
          const declineStr = (sectorTrend?.decline_days != null && sectorTrend.decline_days > 0) ? `${sectorTrend.decline_days}天` : '';
          // 板块涨幅（盘后，新）
          const secAvgChg = sfDash?.avg_chg;
          const secAvgChgColor = secAvgChg == null ? 'var(--text-muted)' : secAvgChg >= 0 ? '#ef4444' : '#22c55e';
          // 涨停数
          const limitUp = sfDash?.limit_up_count;
          // 板块赚钱效应：基于涨停数+平均涨幅+净流入方向综合判定
          // 算法：涨停数权重最高（火爆标志），平均涨幅为辅，资金流向作为确认信号
          const sectorNetFlowVal = sfDash?.net_flow != null ? sfDash.net_flow : (signal.sectorTrend?.total_net_flow ?? null);
          const sectorEffect = (() => {
            const hasAvg = secAvgChg != null;
            const hasLimit = limitUp != null && limitUp > 0;
            const hasFlow = sectorNetFlowVal != null;
            const isFlowIn = hasFlow && sectorNetFlowVal >= 0;
            const isFlowOut = hasFlow && sectorNetFlowVal < 0;

            // 主升浪：≥5涨停 且 平均涨幅≥2% 且 资金流入
            if (limitUp >= 5 && hasAvg && secAvgChg >= 2 && isFlowIn) return { label: '主升浪·追涨加仓', color: '#dc2626', icon: '🔥' };
            // 火爆：≥5涨停 且 平均涨幅≥2%
            if (limitUp >= 5 && hasAvg && secAvgChg >= 2) return { label: '火爆·加仓', color: '#ef4444', icon: '🔥' };
            // 强势：3-4涨停 且 平均涨幅≥1%
            if (limitUp >= 3 && hasAvg && secAvgChg >= 1) return { label: '强势·持股', color: '#ef4444', icon: '📈' };
            // 活跃：1-2涨停 且 平均涨幅≥0.5%
            if (hasLimit && hasAvg && secAvgChg >= 0.5) return { label: '活跃·跟进', color: '#f97316', icon: '⚡' };
            // 温和上涨：0涨停 但 平均涨幅≥0.3%
            if (hasAvg && secAvgChg >= 0.3) return { label: '温和·观望', color: '#eab308', icon: '⚖️' };
            // 走弱：平均涨幅<0
            if (hasAvg && secAvgChg < 0 && secAvgChg > -1) return { label: '走弱·减仓', color: '#3b82f6', icon: '📉' };
            // 冰点：平均涨幅≤-1% 或 涨停0且资金大幅流出
            if ((hasAvg && secAvgChg <= -1) || (!hasLimit && isFlowOut)) return { label: '冰点·回避', color: '#22c55e', icon: '❄️' };
            // 默认
            return { label: '中性·观望', color: '#94a3b8', icon: '⏳' };
          })();
          const leftHeat = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块名</span>
              <span className="font-bold truncate flex-1 min-w-0" style={{ color: 'var(--text-secondary)' }}>{sector || '--'}</span>
              {secAvgChg != null && (
                <span className="font-bold tabular-nums flex-shrink-0" style={{ color: secAvgChgColor }}>
                  {secAvgChg >= 0 ? '+' : ''}{secAvgChg.toFixed(2)}%
                </span>
              )}
              {limitUp > 0 && (
                <span className="text-[9px] px-1 rounded flex-shrink-0 whitespace-nowrap" style={{ background: 'rgba(239,68,68,0.15)', color: '#ef4444' }}>🔥{limitUp}</span>
              )}
              {heatVal != null && (
                <span className="font-bold tabular-nums flex-shrink-0" style={{ color: heatColor }}>
                  {heatVal.toFixed(1)}<span className="text-[9px] ml-0.5">{heatTrendIcon}{declineStr}</span>
                </span>
              )}
            </div>
          );
          // 右：板块资金净流入（实时）
          const rtSecFlowVal = rtDash?.sector_net;
          const secFlowColor = (v) => v == null ? 'var(--text-muted)' : v >= 0 ? '#ef4444' : '#22c55e';
          const secFlowFmt = sfDash ? fmtYuan : fmtWanYi;
          const rtSecFlow = rtSecFlowVal != null ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块资金</span>
              <span className="font-bold" style={{ color: secFlowColor(rtSecFlowVal) }}>{rtSecFlowVal >= 0 ? '净流入' : '净流出'}</span>
              <span className="ml-auto font-mono tabular-nums" style={{ color: secFlowColor(rtSecFlowVal) }}>
                {rtSecFlowVal >= 0 ? '+' : ''}{fmtYuan(rtSecFlowVal)}
              </span>
            </div>
          ) : (sectorNetFlowVal != null ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块资金</span>
              <span className="font-bold" style={{ color: secFlowColor(sectorNetFlowVal) }}>{sectorNetFlowVal >= 0 ? '净流入' : '净流出'}</span>
              <span className="ml-auto font-mono tabular-nums" style={{ color: secFlowColor(sectorNetFlowVal) }}>
                {sectorNetFlowVal >= 0 ? '+' : ''}{secFlowFmt(sectorNetFlowVal)}
              </span>
            </div>
          ) : emptyRow);

          // 行2: 左=赚钱效应（基于涨停+涨幅+资金，sectorEffect替代软stage标签） / 右=板块涨幅+个股超额
          const leftTrend = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>赚钱效应</span>
              <span className="font-bold flex-shrink-0">{sectorEffect.icon}</span>
              <span className="font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ color: sectorEffect.color, background: `${sectorEffect.color}15` }}>{sectorEffect.label}</span>
              {sectorScore != null && (
                <span className="ml-auto flex items-center gap-0.5 flex-shrink-0" style={{ minWidth: '44px', justifyContent: 'flex-end' }}>
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>共振</span>
                  <span className="font-bold tabular-nums" style={{ color: scoreColor(sectorScore) }}>{sectorScore.toFixed(0)}</span>
                </span>
              )}
            </div>
          );
          // 右：板块实时涨幅 + 个股 vs 板块（涨幅差 = 个股涨幅 - 板块涨幅，正值=跑赢板块）
          const rtSecRise = rtDash?.sector_rise;
          const rtOwnChg = rtDash?.price_chg;
          const rtDiff = (rtSecRise != null && rtOwnChg != null) ? (rtOwnChg - rtSecRise) : null;
          const rtSecRiseColor = rtSecRise == null ? 'var(--text-muted)' : rtSecRise >= 0 ? '#ef4444' : '#22c55e';
          const rtDiffColor = rtDiff == null ? 'var(--text-muted)' : rtDiff >= 0 ? '#ef4444' : '#22c55e';
          const rtLimitUp = (rtSecRise != null || rtDiff != null) ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块涨幅</span>
              {rtSecRise != null && (
                <span className="font-bold tabular-nums flex-shrink-0" style={{ color: rtSecRiseColor }}>
                  {rtSecRise >= 0 ? '+' : ''}{rtSecRise.toFixed(2)}%
                </span>
              )}
              {rtDiff != null && (
                <>
                  <span className="text-[9px] flex-shrink-0" style={{ color: 'var(--text-muted)' }}>· 个股</span>
                  <span className="font-bold tabular-nums flex-shrink-0" style={{ color: rtDiffColor }}>
                    {rtDiff >= 0 ? '+' : ''}{rtDiff.toFixed(2)}%
                  </span>
                </>
              )}
            </div>
          ) : emptyRow;

          // 行3: 左=板块资金参与度（净流入+涨跌家数比） / 右=板块实时资金方向
          const riseRatio = sfDash?.rise_ratio;  // 板块上涨股票占比 0-100
          // 资金参与度评级：净流入规模 + 上涨家数比
          const participationEffect = (() => {
            const netFlowWan = sectorNetFlowVal != null ? Math.abs(sectorNetFlowVal) / 1e4 : null;  // 元→万
            const hasRise = riseRatio != null;
            const hasFlow = netFlowWan != null;
            const isFlowIn = sectorNetFlowVal != null && sectorNetFlowVal >= 0;
            // 资金大幅流入 + 上涨家数>70%
            if (hasFlow && hasRise && isFlowIn && netFlowWan >= 5000 && riseRatio >= 70) return { label: '主力抢筹·跟进', color: '#dc2626', icon: '💰' };
            // 资金流入 + 上涨家数>50%
            if (hasFlow && hasRise && isFlowIn && netFlowWan >= 1000 && riseRatio >= 50) return { label: '主力进场·持有', color: '#ef4444', icon: '💰' };
            // 资金小幅流入
            if (hasFlow && isFlowIn && netFlowWan >= 100) return { label: '资金试探·观望', color: '#f97316', icon: '🔍' };
            // 资金流出
            if (hasFlow && !isFlowIn && netFlowWan >= 5000) return { label: '主力撤退·减仓', color: '#22c55e', icon: '🏃' };
            // 资金小幅流出
            if (hasFlow && !isFlowIn) return { label: '资金外流·谨慎', color: '#3b82f6', icon: '📉' };
            return { label: '资金中性·观望', color: '#94a3b8', icon: '⚖️' };
          })();
          const leftParticipation = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>资金参与度</span>
              <span className="font-bold flex-shrink-0">{participationEffect.icon}</span>
              <span className="font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ color: participationEffect.color, background: `${participationEffect.color}15` }}>{participationEffect.label}</span>
              {riseRatio != null && (
                <span className="ml-auto font-bold tabular-nums flex-shrink-0 whitespace-nowrap" style={{ color: riseRatio >= 50 ? '#ef4444' : '#22c55e' }}>
                  {riseRatio.toFixed(0)}%涨
                </span>
              )}
            </div>
          );
          // 右：板块共振度（个股 vs 板块资金方向一致性评分，独立维度，避免与行1的板块资金净额重复）
          const rtResonance = rtDash?.sector_resonance;
          const rtParticipation = rtResonance != null ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块共振</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                <div className="h-full rounded-full" style={{ width: `${rtResonance}%`, background: scoreColor(rtResonance) }} />
              </div>
              <span className="ml-auto font-bold tabular-nums flex-shrink-0 whitespace-nowrap px-1 rounded" style={{
                color: rtResonance >= 70 ? '#ef4444' : rtResonance >= 50 ? '#eab308' : '#22c55e',
                background: rtResonance >= 70 ? 'rgba(239,68,68,0.12)' : rtResonance >= 50 ? 'rgba(234,179,8,0.12)' : 'rgba(34,197,94,0.12)',
              }}>
                {rtResonance >= 70 ? '同向·加仓' : rtResonance >= 50 ? '弱共振·持有' : '背离·谨慎'}
              </span>
              <span className="font-bold tabular-nums flex-shrink-0" style={{ color: scoreColor(rtResonance), minWidth: '20px', textAlign: 'right' }}>
                {rtResonance.toFixed(0)}
              </span>
            </div>
          ) : emptyRow;

          // 行4: 左=板块强度趋势（连涨/连跌天数+热度趋势+板块排名） / 右=板块热度变化
          // 板块强度评级：连跌天数 + 热度趋势
          const declineDays = sectorTrend?.decline_days ?? 0;
          const heatTrend = sectorTrend?.heat_trend;  // 'up' / 'down' / 'stable'
          const heatScore = sfDash?.heat_score != null ? sfDash.heat_score : (sectorTrend?.latest_heat != null ? sectorTrend.latest_heat : null);
          const strengthEffect = (() => {
            // 连跌≥3 或 热度下行且热度<30
            if (declineDays >= 3 || (heatTrend === 'down' && heatScore != null && heatScore < 30)) return { label: '走弱·减仓', color: '#22c55e', icon: '📉' };
            // 热度上行且热度≥60
            if (heatTrend === 'up' && heatScore != null && heatScore >= 60) return { label: '升温·加仓', color: '#ef4444', icon: '🔥' };
            // 热度上行
            if (heatTrend === 'up') return { label: '走强·跟进', color: '#f97316', icon: '📈' };
            // 热度稳定且较高
            if (heatScore != null && heatScore >= 50) return { label: '稳健·持有', color: '#eab308', icon: '⚖️' };
            // 热度稳定但低
            if (heatScore != null && heatScore < 30) return { label: '低迷·回避', color: '#3b82f6', icon: '❄️' };
            return { label: '中性·观望', color: '#94a3b8', icon: '⏳' };
          })();
          const leftStrength = (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块强度</span>
              <span className="font-bold flex-shrink-0">{strengthEffect.icon}</span>
              <span className="font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ color: strengthEffect.color, background: `${strengthEffect.color}15` }}>{strengthEffect.label}</span>
              {declineDays > 0 && (
                <span className="ml-auto text-[9px] flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ background: 'rgba(34,197,94,0.12)', color: '#22c55e' }}>{declineDays}日跌</span>
              )}
              {heatScore != null && (
                <span className="font-bold tabular-nums flex-shrink-0 whitespace-nowrap" style={{ color: heatColor }}>
                  {heatScore.toFixed(0)}
                </span>
              )}
            </div>
          );
          // 右：板块排名（如果后端有数据则展示，否则用热度趋势）
          const sectorRank = sectorTrend?.rank;
          const rtStrength = sectorRank != null ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块排名</span>
              <div className="flex-1" />
              <span className="font-bold tabular-nums flex-shrink-0 whitespace-nowrap" style={{ color: sectorRank <= 5 ? '#ef4444' : sectorRank <= 20 ? '#f97316' : 'var(--text-muted)' }}>
                第{sectorRank}名
              </span>
            </div>
          ) : (heatTrend ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>热度趋势</span>
              <div className="flex-1" />
              <span className="font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{
                color: heatTrend === 'up' ? '#ef4444' : heatTrend === 'down' ? '#22c55e' : '#94a3b8',
                background: heatTrend === 'up' ? 'rgba(239,68,68,0.15)' : heatTrend === 'down' ? 'rgba(34,197,94,0.15)' : 'rgba(148,163,184,0.12)'
              }}>
                {heatTrend === 'up' ? '↑ 升温' : heatTrend === 'down' ? '↓ 降温' : '→ 持平'}
              </span>
            </div>
          ) : emptyRow);

          // 行5: 左=板块龙头表现 / 右=龙头涨幅
          const leaderStock = sfDash?.leader_stock;
          const leaderStrength = sfDash?.leader_strength;
          // 龙头强度评级
          const leaderEffect = (() => {
            if (!leaderStock) return null;
            if (leaderStrength == null) return { label: '龙头未明·观望', color: '#94a3b8', icon: '👑' };
            // 龙头强度≥9：龙头涨停，板块极强
            if (leaderStrength >= 9) return { label: '龙头涨停·主升浪', color: '#dc2626', icon: '👑' };
            if (leaderStrength >= 7) return { label: '龙头强势·加仓', color: '#ef4444', icon: '👑' };
            if (leaderStrength >= 5) return { label: '龙头活跃·跟进', color: '#f97316', icon: '👑' };
            if (leaderStrength >= 3) return { label: '龙头一般·持有', color: '#eab308', icon: '👑' };
            return { label: '龙头走弱·减仓', color: '#22c55e', icon: '👑' };
          })();
          const leftLeader = leaderEffect ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块龙头</span>
              <span className="font-bold flex-shrink-0">{leaderEffect.icon}</span>
              <span className="font-bold truncate flex-1 min-w-0" style={{ color: 'var(--text-secondary)' }} title={leaderStock}>{leaderStock}</span>
              <span className="ml-auto font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ color: leaderEffect.color, background: `${leaderEffect.color}15` }}>{leaderEffect.label}</span>
              {leaderStrength != null && (
                <span className="font-bold tabular-nums flex-shrink-0" style={{ color: scoreColor(leaderStrength * 10), minWidth: '20px', textAlign: 'right' }}>
                  {leaderStrength.toFixed(1)}
                </span>
              )}
            </div>
          ) : emptyRow;
          // 右：龙头强度评分（备用展示实时龙头涨幅，暂用leader_strength占位）
          const rtLeader = leaderStrength != null ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>龙头强度</span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                <div className="h-full rounded-full" style={{ width: `${leaderStrength * 10}%`, background: scoreColor(leaderStrength * 10) }} />
              </div>
              <span className="font-bold tabular-nums flex-shrink-0" style={{ color: scoreColor(leaderStrength * 10), minWidth: '20px', textAlign: 'right' }}>
                {leaderStrength.toFixed(1)}
              </span>
            </div>
          ) : emptyRow;

          // 行6: 左=板块轮动信号（资金连续性+入场天数+龙头持续性） / 右=热度趋势+5日累计涨幅
          const rotation = dash?.sector_rotation;
          const leftRotation = rotation?.rotation_signal ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>板块轮动</span>
              <span className="font-bold flex-shrink-0">{rotation.rotation_icon}</span>
              <span className="font-bold flex-shrink-0 whitespace-nowrap px-1 rounded truncate" style={{ color: rotation.rotation_color, background: `${rotation.rotation_color}15`, maxWidth: 'calc(100% - 80px)' }} title={rotation.rotation_signal}>
                {rotation.rotation_signal}
              </span>
              {rotation.inflow_strength != null && rotation.inflow_strength > 0 && (
                <span className="ml-auto flex items-center gap-0.5 flex-shrink-0" style={{ minWidth: '40px', justifyContent: 'flex-end' }}>
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>强度</span>
                  <span className="font-bold tabular-nums" style={{ color: scoreColor(rotation.inflow_strength) }}>{rotation.inflow_strength}</span>
                </span>
              )}
            </div>
          ) : emptyRow;
          // 右：5日累计涨幅 + 热度趋势
          const rtRotation = (() => {
            const cum5d = rotation?.cumulative_chg_5d;
            const heatTrendLabel = rotation?.heat_trend_label;
            if (cum5d == null && !heatTrendLabel) return emptyRow;
            return (
              <div className={rowClass} style={rowStyleR}>
                <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>5日累计</span>
                {cum5d != null && (
                  <span className="font-bold tabular-nums flex-shrink-0 whitespace-nowrap" style={{ color: cum5d >= 0 ? '#ef4444' : '#22c55e' }}>
                    {cum5d >= 0 ? '+' : ''}{cum5d.toFixed(2)}%
                  </span>
                )}
                {heatTrendLabel && (
                  <span className="ml-auto text-[9px] flex-shrink-0 whitespace-nowrap px-1 rounded" style={{
                    color: rotation.heat_trend === 'accel_up' ? '#dc2626' : rotation.heat_trend === 'steady_up' ? '#ef4444' : rotation.heat_trend === 'cooling_down' ? '#22c55e' : rotation.heat_trend === 'accel_down' ? '#22c55e' : 'var(--text-muted)',
                    background: rotation.heat_trend === 'accel_up' ? 'rgba(220,38,38,0.12)' : rotation.heat_trend === 'steady_up' ? 'rgba(239,68,68,0.12)' : rotation.heat_trend === 'cooling_down' ? 'rgba(34,197,94,0.12)' : rotation.heat_trend === 'accel_down' ? 'rgba(34,197,94,0.12)' : 'rgba(148,163,184,0.08)',
                  }}>
                    {heatTrendLabel}
                  </span>
                )}
              </div>
            );
          })();

          // 行7: 左=量价配合（量比+量价齐升/量增价跌） / 右=个股相对板块强弱
          // 改动说明：原『动能』本质是板块资金净流入+3日累计+连续性，与上方第6行『轮动』+第3行『资金参与度』高度重复，
          // 改为『量价』维度（量比+量价配合度），独立不重复。
          const vpVR = dash?.features?.volume_ratio;          // 量比
          const vpChg = signal.quote?.changePct;               // 当日涨跌幅%
          const stockRankInSector = dash?.stock_rank_in_sector;
          // 量价配合度判定（0-100 进度条 + 犀利动作标签）
          const vpInfo = (() => {
            if (vpVR == null && vpChg == null) return null;
            // 量价齐升 = 放量上涨，主力建仓信号
            if (vpVR != null && vpChg != null) {
              if (vpVR >= 1.5 && vpChg > 2)  return { label: '量价齐升·跟进', color: '#dc2626', bar: 90 };
              if (vpVR >= 1.5 && vpChg > 0)  return { label: '放量上涨·建仓', color: '#ef4444', bar: 80 };
              if (vpVR >= 1.5 && vpChg < -2) return { label: '量增价跌·减仓', color: '#22c55e', bar: 15 };
              if (vpVR >= 1.5 && vpChg < 0)  return { label: '放量下跌·离场', color: '#22c55e', bar: 25 };
              if (vpVR < 0.8 && vpChg > 0)   return { label: '缩量上涨·谨慎', color: '#3b82f6', bar: 55 };
              if (vpVR < 0.8 && vpChg < 0)   return { label: '缩量调整·观望', color: '#3b82f6', bar: 40 };
              if (vpVR < 0.8)                return { label: '缩量·观望', color: '#3b82f6', bar: 45 };
            }
            if (vpChg != null) {
              if (vpChg > 2)  return { label: '强势·持有', color: '#ef4444', bar: 75 };
              if (vpChg > 0)  return { label: '温和·持有', color: '#f97316', bar: 60 };
              if (vpChg < -2) return { label: '弱势·谨慎', color: '#22c55e', bar: 30 };
            }
            return { label: '平·观望', color: '#eab308', bar: 50 };
          })();
          const leftMomentum = vpInfo ? (
            <div className={rowClass} style={rowStyleL}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>量价配合</span>
              {vpVR != null && (
                <span className="font-bold tabular-nums flex-shrink-0 whitespace-nowrap" style={{ color: vpVR >= 1.5 ? '#ef4444' : vpVR <= 0.5 ? '#22c55e' : 'var(--text-primary)', minWidth: '32px' }}>
                  {vpVR.toFixed(2)}
                </span>
              )}
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'rgba(107,114,128,0.15)' }}>
                <div className="h-full rounded-full" style={{ width: `${vpInfo.bar}%`, background: scoreColor(vpInfo.bar) }} />
              </div>
              <span className="ml-auto font-bold flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ color: vpInfo.color, background: `${vpInfo.color}15` }}>{vpInfo.label}</span>
            </div>
          ) : emptyRow;
          // 右：相对强弱评分（个股跑赢板块的程度） + 板块内排名
          const relScore = dash?.relative_strength;
          const rtRelScore = rtDash?.relative_strength;
          const rtMomentum = (relScore != null || rtRelScore != null || stockRankInSector != null) ? (
            <div className={rowClass} style={rowStyleR}>
              <span className="text-[10px] flex-shrink-0 font-medium w-16" style={{ color: 'var(--text-muted)' }}>个股表现</span>
              {stockRankInSector != null && (
                <span className="text-[9px] flex-shrink-0 whitespace-nowrap px-1 rounded" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444' }}>
                  第{stockRankInSector}名
                </span>
              )}
              {relScore != null && (
                <span className="flex items-center gap-0.5 flex-shrink-0 ml-auto">
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>盘</span>
                  <span className="font-bold tabular-nums" style={{ color: scoreColor(relScore) }}>{relScore.toFixed(0)}</span>
                </span>
              )}
              {rtRelScore != null && (
                <span className="flex items-center gap-0.5 flex-shrink-0">
                  <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>实</span>
                  <span className="font-bold tabular-nums" style={{ color: scoreColor(rtRelScore) }}>{rtRelScore.toFixed(0)}</span>
                </span>
              )}
            </div>
          ) : emptyRow;

          return (
            <div className="flex items-stretch">
              <div className="flex-1 min-w-0 pr-2.5 flex flex-col gap-0.5">
                <ModuleHeader
                  icon={MODULE_HEADER_CONFIG.sector.icon}
                  name={MODULE_HEADER_CONFIG.sector.name}
                  conclusion={sectorEffect?.label}
                  conclusionColor={sectorEffect?.color || '#64748b'}
                  title={`板块: ${sector || '--'} · 涨停 ${limitUp ?? 0} · 涨幅 ${secAvgChg != null ? secAvgChg.toFixed(2) + '%' : '--'}`}
                />
                {leftHeat}
                {leftTrend}
                {leftParticipation}
                {leftStrength}
                {leftLeader}
                {leftRotation}
                {leftMomentum}
              </div>
              <div className="shrink-0" style={{ width: '1.5px', backgroundColor: 'rgba(148,163,184,0.35)', margin: '2px 0' }} />
              <div className="flex-1 min-w-0 pl-2.5 flex flex-col gap-0.5">
                <ModuleHeader
                  icon="🟢"
                  name={stripRealtimePrefix(rtHdr.label)}
                  conclusion={rtSecFlowVal != null ? (rtSecFlowVal >= 0 ? '板块资金净流入' : '板块资金净流出') : null}
                  conclusionColor={rtSecFlowVal != null ? (rtSecFlowVal >= 0 ? '#ef4444' : '#22c55e') : '#64748b'}
                  title={`快照: ${rtDash?.snapshot_time || ''}`}
                />
                {rtLimitUp}
                {rtParticipation}
                {rtStrength}
                {rtLeader}
                {rtRotation}
                {rtMomentum}
                {emptyRow}
              </div>
            </div>
          );
        })()}
      </div>
      </>


      {/* —— 8. 🌐 市场（精简为单行仓位建议：风险等级 → 仓位%，聚焦系统性风险与仓位控制）—— */}
      <>
      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
      <div className="px-2.5 py-1.5">
        {(() => {
          // 风险等级 → 仓位建议 + 操作标签
          // 系统性风险 veto：高危强制清仓，与个股板块信号无关
          const riskStage = signal.risk?.stage;
          const riskScore = signal.risk?.score;
          // 大盘状态（作为辅助信息合并到 extra）
          const ms = signal.marketState || {};
          const msState = ms.market_state;
          // 市场综合结论：统一调用 moduleHeaderConfig.getMarketConclusion
          const mktConclusion = getMarketConclusion({ riskStage, riskScore, msState });
          const posInfo = mktConclusion.label ? { label: mktConclusion.label, color: mktConclusion.color } : null;
          const stateLabel = mktConclusion.stateLabel;

          return (
            <ModuleHeader
              icon={MODULE_HEADER_CONFIG.market.icon}
              name={MODULE_HEADER_CONFIG.market.name}
              conclusion={posInfo?.label}
              conclusionColor={posInfo?.color || '#64748b'}
              title={mktConclusion.title}
              extra={
                <>
                  {stateLabel && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
                      📊 {stateLabel}
                    </span>
                  )}
                  {riskScore != null && (
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap tabular-nums" style={{ background: 'rgba(148,163,184,0.1)', color: 'var(--text-muted)' }}>
                      风险分 {riskScore}
                    </span>
                  )}
                </>
              }
            />
          );
        })()}
      </div>
      </>


      {/* 委托记录弹窗 */}
      {orderOpen && (
        <OrderHistoryModal stockName={secName} secCode={secCode} orders={orders} onClose={() => setOrderOpen(false)} />
      )}
    </div>
  );
}




const scoreColor = (v) => (v == null ? 'var(--text-muted)' : v >= 70 ? '#ef4444' : v >= 50 ? '#eab308' : v >= 30 ? '#f97316' : '#22c55e');

// 统一的模块标题行组件：左侧色块标题 + 右侧结论标签 + 可选辅助数据
// 与 BS 区间、AI 诊断模块风格一致：色块标题醒目，结论顶格在右
function ModuleHeader({ icon, name, conclusion, conclusionColor = '#64748b', extra = null, title = '' }) {
  return (
    <div className="flex items-center justify-between gap-1 mb-0.5 min-h-[18px]">
      <span
        className="text-[11px] font-bold tracking-wider px-1.5 py-0.5 rounded whitespace-nowrap flex-shrink-0"
        style={{
          background: 'rgba(59,130,246,0.12)',
          color: 'var(--accent-blue, #3b82f6)',
          border: '1px solid rgba(59,130,246,0.35)',
        }}
        title={title}
      >
        {icon} {name}
      </span>
      <div className="flex items-center gap-1.5 flex-shrink-0 min-w-0">
        {conclusion && (
          <span
            className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap"
            style={{
              background: `${conclusionColor}1a`,
              color: conclusionColor,
              border: `1px solid ${conclusionColor}40`,
            }}
            title={title}
          >
            {conclusion}
          </span>
        )}
        {extra}
      </div>
    </div>
  );
}

// 实时快照时间动态标签：已统一到 moduleHeaderConfig.getRealtimeHeader（通过顶部 import 引入）
// 删除本地实现，避免规则双源——修改一处全局生效

// 当日分时迷你走势：价格折线 + 固定交易时段时间轴（9:30-11:30 + 13:00-15:00）
// 颜色遵循 A 股惯例：红涨绿跌（project_memory 硬约束）
// 时间轴固定为完整交易日（240 分钟），数据点按实际时间映射到对应位置，
// 即使当前是 13:18，右侧仍然显示 15:00，与交易软件一致。
const TRADING_SESSIONS = [
  { start: 9 * 60 + 30, end: 11 * 60 + 30 },  // 9:30-11:30 = 120 分钟
  { start: 13 * 60, end: 15 * 60 },            // 13:00-15:00 = 120 分钟
];
const TOTAL_TRADING_MINUTES = 240;
const SESSION_LABELS = ['9:30', '11:30', '13:00', '15:00'];

function timeStrToMinutes(t) {
  if (!t || typeof t !== 'string') return null;
  const m = t.match(/^(\d{1,2}):(\d{2})/);
  if (!m) return null;
  return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
}

// 将 HH:MM 转换为 X 轴位置（0-240 映射到 0-W）
function minuteToX(minute, W) {
  let pos = 0;
  for (const s of TRADING_SESSIONS) {
    if (minute < s.start) break;          // 开盘前，留在起点
    if (minute <= s.end) {
      pos += (minute - s.start);
      return (pos / TOTAL_TRADING_MINUTES) * W;
    }
    pos += (s.end - s.start);              // 跳过午休
  }
  return W;                                // 收盘后，固定在最右
}

function IntradaySparkline({ data, showPriceLabel = true }) {
  if (!data || data.length < 2) return null;
  const W = 240, H = 38, padY = 5;
  const prices = data.map((d) => d.price).filter((v) => v != null);
  if (prices.length < 2) return null;
  const min = Math.min(...prices), max = Math.max(...prices);
  const span = max - min || 1;
  const last = data[data.length - 1];
  const up = (last.pct_chg ?? 0) >= 0;
  const stroke = up ? '#ef4444' : '#22c55e'; // 红涨绿跌
  // X 轴：按实际时间映射到固定交易时段位置
  const x = (d) => {
    const m = timeStrToMinutes(d.t);
    return m == null ? 0 : minuteToX(m, W);
  };
  const y = (p) => padY + (1 - (p - min) / span) * (H - 2 * padY);
  const pts = data.map((d) => (d.price == null ? null : `${x(d).toFixed(1)},${y(d.price).toFixed(1)}`)).filter(Boolean);
  const line = pts.join(' ');
  // 面积从首个点开始（不是从 X=0 开始），让折线与面积对齐
  const firstX = pts.length > 0 ? pts[0].split(',')[0] : '0';
  const area = `${firstX},${H} ${line} ${W},${H}`;
  // 当前价格点位置（用于在 SVG 内部右上角标注价格涨幅）
  const lastX = pts.length > 0 ? parseFloat(pts[pts.length - 1].split(',')[0]) : W;
  const priceLabelX = lastX > W * 0.6 ? Math.max(2, lastX - 2) : Math.min(W - 50, lastX + 4);
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: 'block' }}>
        {/* 午休分割线（11:30/13:00 之间为空白） */}
        <line x1={W / 2} y1={0} x2={W / 2} y2={H} stroke="var(--border-color)" strokeWidth={0.5} strokeDasharray="2,2" opacity={0.4} />
        <polygon points={area} fill={stroke} opacity={0.08} />
        <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.2} strokeLinejoin="round" />
      </svg>
      {/* 时间标签行：9:30 / 11:30 / 13:00 / 15:00，避免居中涨幅文字挤在中间 */}
      <div style={{ position: 'relative', width: '100%', height: '12px', fontSize: '9px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
        {/* 9:30 → 0%（左对齐） */}
        <span style={{ position: 'absolute', left: '0%', transform: 'translateX(0)' }}>9:30</span>
        {/* 11:30 → 50%（右对齐，标签右边贴着午休点） */}
        <span style={{ position: 'absolute', left: '50%', transform: 'translateX(-100%)', paddingRight: '2px' }}>11:30</span>
        {/* 13:00 → 50%（左对齐，标签左边贴着午休点） */}
        <span style={{ position: 'absolute', left: '50%', transform: 'translateX(0)', paddingLeft: '2px' }}>13:00</span>
        {/* 15:00 → 100%（右对齐） */}
        <span style={{ position: 'absolute', left: '100%', transform: 'translateX(-100%)' }}>15:00</span>
      </div>
      {/* 涨幅独立行：右下角显示价格 + 涨幅，与时间标签分离避免重叠（默认显示，外面已经在「当日」位置展示过时可关闭） */}
      {showPriceLabel && (
        <div style={{ position: 'relative', width: '100%', height: '11px', fontSize: '9px', whiteSpace: 'nowrap' }}>
          <span className="font-bold" style={{ position: 'absolute', right: '0%', color: stroke }}>
            {last.price?.toFixed(2)} {up ? '↑' : '↓'}{Math.abs(last.pct_chg ?? 0).toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}

// BS 区间日 K 迷你走势：收盘价折线 + B 起点 / S 终点（带竖虚线+标签）+ 起止日期 + 区间盈亏%
// 颜色遵循 A 股惯例：红涨绿跌（project_memory 硬约束）
// klines: [{date, open, close, high, low, volume}, ...]
// bsInt: {state, start_date, start_price, end_date, end_price, hold_days, pnl_pct}
function BSRangeSparkline({ klines, bsInt }) {
  if (!klines || klines.length < 1) return null;
  // viewBox 与实际像素 1:1，避免 preserveAspectRatio="none" 拉伸导致文字扭曲
  const W = 240, H = 48, padY = 10, padX = 8;
  const closes = klines.map((k) => k.close).filter((v) => v != null);
  if (closes.length < 1) return null;
  const sp = bsInt?.start_price;
  const ep = bsInt?.end_price;
  // y 轴范围：纳入 B 起点 / S 终点价格 + 10% padding，确保标记在可视区内
  const allVals = [...closes];
  if (sp != null) allVals.push(sp);
  if (ep != null) allVals.push(ep);
  const rawMin = Math.min(...allVals), rawMax = Math.max(...allVals);
  const rawSpan = (rawMax - rawMin) || Math.abs(rawMin) * 0.02 || 1;
  const min = rawMin - rawSpan * 0.15;
  const max = rawMax + rawSpan * 0.15;
  const span = max - min || 1;
  const n = klines.length;
  const isSingle = n === 1;
  // x 轴：按日期均匀分布在整个图宽
  const x = (i) => (n <= 1 ? W * 0.5 : padX + (i / (n - 1)) * (W - 2 * padX));
  const y = (p) => padY + (1 - (p - min) / span) * (H - 2 * padY);
  const last = klines[n - 1];
  const first = klines[0];
  const up = (last.close ?? 0) >= (first.close ?? 0);
  const stroke = up ? '#ef4444' : '#22c55e';
  const pts = klines.map((d, i) => (d.close == null ? null : `${x(i).toFixed(1)},${y(d.close).toFixed(1)}`)).filter(Boolean);
  const line = pts.join(' ');
  const area = `${padX},${H} ${line} ${W - padX},${H}`;
  const sd = bsInt?.start_date || '';
  const ed = bsInt?.end_date || '今';
  const pnl = bsInt?.pnl_pct;
  const pnlColor = pnl == null ? '#94a3b8' : pnl >= 0 ? '#ef4444' : '#22c55e';
  const isHolding = bsInt?.state === 'holding';
  const epColor = isHolding ? '#ef4444' : '#f97316';
  const epLabel = isHolding ? '现' : 'S';
  // B 点位置：在 60 天 klines 中找到 B 点日期对应的索引
  // 单点时强制左右分开（B 在左 1/4，现价在右 3/4）
  const bIdx = isSingle ? -1 : klines.findIndex(k => (k.date || '').slice(0, 10) === (sd || '').slice(0, 10));
  const bx = isSingle ? W * 0.25 : (bIdx >= 0 ? x(bIdx) : padX);
  const ex = isSingle ? W * 0.75 : W - padX;
  // 标签 y 位置：B 标签固定在上方，现价标签固定在下方，避免重叠
  const bLabelY = Math.max(11, y(sp) - 5);
  const eLabelY = Math.min(H - 3, y(ep) + 11);
  // 标签锚点：B 标签向右展开（text-anchor=start），现价标签向左展开（text-anchor=end）
  return (
    <div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="xMidYMid meet" style={{ display: 'block' }}>
        {/* 区间面积 + 折线 */}
        {!isSingle && (
          <>
            <polygon points={area} fill={stroke} opacity={0.08} />
            <polyline points={line} fill="none" stroke={stroke} strokeWidth={1.4} strokeLinejoin="round" />
          </>
        )}
        {/* 单点 / sp=ep 时用虚线连接 B→现价，明确显示是同一价还是有变动 */}
        {isSingle && sp != null && ep != null && (
          <line x1={bx} y1={y(sp)} x2={ex} y2={y(ep)} stroke={stroke} strokeWidth={1.6} strokeDasharray="3,2" />
        )}
        {/* B 起点竖虚线 + 圆点 + 标签（蓝色，固定在上方） */}
        {sp != null && (
          <g>
            <line x1={bx} y1={0} x2={bx} y2={H} stroke="#3b82f6" strokeWidth={1} strokeDasharray="3,2" opacity={0.7} />
            <circle cx={bx} cy={y(sp)} r={3.5} fill="#3b82f6" stroke="#fff" strokeWidth={1} />
            <text x={bx + 5} y={bLabelY} fontSize={9} fill="#3b82f6" fontWeight={700}>B {sp.toFixed(2)}</text>
          </g>
        )}
        {/* S 终点 / 当前价 竖虚线 + 圆点 + 标签（红/橙，固定在下方） */}
        {ep != null && (
          <g>
            <line x1={ex} y1={0} x2={ex} y2={H} stroke={epColor} strokeWidth={1} strokeDasharray="3,2" opacity={0.7} />
            <circle cx={ex} cy={y(ep)} r={3.5} fill={epColor} stroke="#fff" strokeWidth={1} />
            <text x={ex - 5} y={eLabelY} fontSize={9} fill={epColor} fontWeight={700} textAnchor="end">{epLabel} {ep.toFixed(2)}</text>
          </g>
        )}
      </svg>
      {/* 日期标签行：绝对定位精准对齐到 B 点 / S 点（当前价）的 X 位置 */}
      <div style={{ position: 'relative', width: '100%', height: '13px', fontSize: '9px', color: 'var(--text-secondary)', whiteSpace: 'nowrap' }}>
        {/* B 起点日期：对齐到 bx 位置（百分比），bx 靠近左边界时切换为右对齐避免溢出 */}
        <span style={{ position: 'absolute', left: `${(bx / W) * 100}%`, transform: (bx / W) < 0.25 ? 'translateX(0)' : 'translateX(-50%)' }}>{sd}</span>
        {/* S 终点 / 当前价日期：对齐到 ex 位置（百分比，右对齐避免溢出） */}
        <span style={{ position: 'absolute', left: `${(ex / W) * 100}%`, transform: 'translateX(-100%)' }}>{ed}</span>
        {/* 区间盈亏：左上角显示，避免和日期/线条重叠 */}
        <span className="font-bold" style={{ position: 'absolute', left: '0%', top: '0', color: pnlColor, background: 'var(--bg-card)', paddingRight: '4px' }}>
          区间 {pnl == null ? '--' : `${pnl >= 0 ? '+' : ''}${pnl}%`}
        </span>
      </div>
    </div>
  );
}

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
