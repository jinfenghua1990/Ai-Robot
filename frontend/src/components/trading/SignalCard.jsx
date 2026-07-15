import { useState, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import TradeButton from './TradeButton';
import StockActionButtons from './StockActionButtons';
import MoneyFlowBoard from './MoneyFlowBoard';
import KLineModal from './KLineModal';
import OrderHistoryModal from './OrderHistoryModal';
import SinaLink from '../SinaLink';
import StageBar from '../StageBar';
import HitTagBar from './HitTagBar';
import IndicatorSettings, { loadSettings } from '../IndicatorSettings';
import { UP_COLOR, DOWN_COLOR, DOWN_DARK, REDUCE_COLOR, BULLISH_COLOR, BEARISH_COLOR } from '../../utils/colors';
import { getMarketStateStyle } from '../../utils/stateStyles';
import { apiFetch } from '../../utils/request';

// 根据持仓盈亏推断趋势阶段
function inferStageFromProfit(profitPct) {
  if (profitPct >= 20) return '主升';
  if (profitPct >= 10) return '加速';
  if (profitPct >= 3) return '突破';
  if (profitPct >= -3) return '蓄势';
  if (profitPct >= -10) return '留意';
  return '观望';
}

/**
 * 单个持仓的信号卡片（紧凑三列模块化布局：左信息 | 中资金流 | 右操作）
 * mode: 'trading'(模拟盘) | 'leader'(龙头页面) | 'watchlist'(自选股) | 'sim_watchlist'
 */
function SignalCard({
  signal,
  orders = [],
  onSell,
  onRemove,
  onRefresh,
  showWatchBtn = true,
  showFocusBtn = true,
  showBuyBtn,
  mode = 'trading',
  showMarketState = false,
  showBuyPower = false,
  showAnalysisButton = false,
  showActionButton = true,
  strategyTags = [],
  realtimeFlow = null,
  showRealtimeDetail = true,
}) {
  const [klineOpen, setKlineOpen] = useState(false);
  const [orderOpen, setOrderOpen] = useState(false);
  const [settings, setSettings] = useState(loadSettings());
  const [settingsOpen, setSettingsOpen] = useState(false);
  const navigate = useNavigate();

  if (!signal || !signal.secCode) {
    return null;
  }
  const {
    secCode, secName, signalLabel, signalColor,
    riskLevel, sector, sectorTrend, position = {},
    score, positiveFactors = [], negativeFactors = [],
    marketState, buyPower,
  } = signal;

  const st = getMarketStateStyle(marketState?.market_state);
  const bp = buyPower || {};

  const isLeader = mode === 'leader';
  const isWatchlistStyle = mode === 'watchlist' || mode === 'sim_watchlist';
  const riskColor = riskLevel === 'high' ? '#dc2626' : riskLevel === 'medium' ? '#f97316' : '#6b7280';
  const riskLabel = riskLevel === 'high' ? '高风险' : riskLevel === 'medium' ? '中风险' : '低风险';
  const profitPct = position?.profitPct ?? 0;
  const dayProfitPct = position?.dayProfitPct ?? 0;
  const profitColor = profitPct >= 0 ? UP_COLOR : DOWN_COLOR;
  const changeColor = dayProfitPct >= 0 ? UP_COLOR : DOWN_COLOR;
  const hasOrders = (orders || []).length > 0;
  const scoreColor = (score == null) ? '#6b7280' : score <= -5 ? DOWN_DARK : score <= -2 ? REDUCE_COLOR : score >= 3 ? UP_COLOR : '#6b7280';

  // AI 动态决策：技术形态驱动标签
  const isTechnicalBreakdown = signal.technical?.stage === '破位';
  // 后端已根据 technical stage 覆写 signalLabel，前端据此决定标签样式
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

  // 输入为元（如持仓盈亏），自动转换为万/亿
  const formatYuanToWanYi = (v) => {
    const yuan = v || 0;
    const wan = yuan / 10000;
    if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
    return `${wan.toFixed(2)}万`;
  };
  // 输入已为万元（如资金流），自动转换为万/亿
  const fmtWanYi = (v) => {
    const wan = v || 0;
    if (Math.abs(wan) >= 10000) return `${(wan / 10000).toFixed(2)}亿`;
    return `${wan.toFixed(0)}万`;
  };

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ borderColor: `${signalColor}40`, background: 'var(--bg-card)', boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}
    >
      {/* ===== 三列模块化布局：左信息 | 中资金流 | 右操作 ===== */}
      <div className="flex flex-row items-stretch gap-2 px-3 py-2">

        {/* ========== 左列：核心信息模块 ========== */}
        <div className="signalcard-module module-info flex-1 min-w-[220px] flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'transparent' }}>
          {/* 头部：标签 + 名称 + 按钮 */}
          <div className="flex items-start gap-2">
            <div
              className={`flex-shrink-0 h-11 rounded-md flex flex-col items-center justify-center font-bold ${isHardcoreLabel ? 'min-w-[88px] px-1.5' : 'w-11'}`}
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
                  <span className="text-xs" style={{ color: signalColor }}>{signalLabel}</span>
                  {score != null && (
                    <span className="text-[10px] mt-0.5" style={{ color: scoreColor }}>{score > 0 ? '+' : ''}{score}</span>
                  )}
                </>
              )}
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setSettingsOpen(true); }}
              className="flex-shrink-0 w-6 h-11 rounded-md flex flex-col items-center justify-center text-[10px] cursor-pointer leading-tight"
              style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
              title="指标模块组合设置"
            >
              <span>⚙</span>
              <span>指标</span>
            </button>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5 flex-wrap">
                <span className="font-medium text-sm" style={{ color: 'var(--text-primary)' }}>{secName}</span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{secCode}</span>
                <span className="text-xs font-bold" style={{ color: changeColor }}>
                  当日 {dayProfitPct >= 0 ? '+' : ''}{dayProfitPct}%
                </span>
                <span className="text-xs font-medium" style={{ color: 'var(--text-primary)' }}>
                  {(position?.price || 0).toFixed(2)}
                </span>
                <SinaLink tsCode={secCode} />
                {strategyTags && strategyTags.length > 0 && strategyTags.map(tag => {
                  const isSci = tag === 'BS-科创-V7';
                  const isCy = tag === 'BS-创业-V9';
                  const isLeaderTag = tag === '游资龙头';
                  const isStageTag = tag.startsWith('游资阶段:');
                  const stageColorMap = {
                    '主升': '#dc2626', '加速': '#fb923c', '突破': '#facc15',
                    '分歧': '#f97316', '蓄势': '#3b82f6', '留意': '#a78bfa', '观望': '#64748b',
                    '启动': '#f59e0b', '发酵': '#ef4444',
                    '关注': '#a78bfa', '吸筹': '#3b82f6', '跟随': '#64748b',
                    '衰退': '#94a3b8', '退潮': '#94a3b8',
                  };
                  const stageName = isStageTag ? tag.replace('游资阶段:', '') : '';
                  const tagColor = isLeaderTag ? '#ef4444'
                    : isStageTag ? (stageColorMap[stageName] || '#06b6d4')
                    : isSci ? '#a855f7' : isCy ? '#f97316' : '#06b6d4';
                  const tagLabel = isLeaderTag ? '游资龙头'
                    : isStageTag ? stageName
                    : isSci ? '科创V7' : isCy ? '创业V9' : tag;
                  const tagIcon = isLeaderTag ? '🔥' : isStageTag ? '📈' : '📊';
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
                <span className="px-1 py-0.5 rounded text-[10px]" style={{ background: `${riskColor}15`, color: riskColor }}>{riskLabel}</span>
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
                {signal.waveSignal && (
                  <span
                    className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                    style={{
                      background: 'rgba(34,197,94,0.12)',
                      color: '#22c55e',
                      border: '1px solid rgba(34,197,94,0.35)',
                    }}
                    title={signal.waveReason || '波段信号'}
                  >
                    🌊 {signal.waveSignal === 'buy' ? '买入' : signal.waveSignal === 'sell' ? '卖出' : '观望'} {signal.confidence ? `${signal.confidence.toFixed(0)}%` : ''}
                  </span>
                )}
                {hasOrders && (
                  <button onClick={(e) => { e.stopPropagation(); setOrderOpen(true); }} className="px-1 py-0.5 rounded text-[10px] cursor-pointer" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
                    📋 {orders.length}笔委托
                  </button>
                )}
              </div>
              {/* 6 大命中雷达标签（仅 watchlist 模式） */}
              {isWatchlistStyle && signal.hitTags && signal.hitTags.length > 0 && (
                <HitTagBar tags={signal.hitTags} />
              )}
              {/* 波段信号指标条 */}
              {signal.waveSignal && (
                <div className="flex items-center gap-1.5 flex-wrap mt-0.5">
                  {signal.waveReason && (
                    <span className="text-[10px] truncate" style={{ color: 'var(--text-muted)' }} title={signal.waveReason}>
                      {signal.waveReason}
                    </span>
                  )}
                  <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }} title="RSI6">
                    RSI6 {signal.rsi6?.toFixed(1)}
                  </span>
                  {signal.ma5 > 0 && (
                    <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA5 {signal.ma5.toFixed(2)}
                    </span>
                  )}
                  {signal.ma10 > 0 && (
                    <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA10 {signal.ma10.toFixed(2)}
                    </span>
                  )}
                  {signal.ma20 > 0 && (
                    <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA20 {signal.ma20.toFixed(2)}
                    </span>
                  )}
                  {signal.volRatio > 0 && (
                    <span className="text-[10px] px-1 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }} title="量比">
                      量比 {signal.volRatio.toFixed(2)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>

          {/* 状态条：趋势阶段 + 个股强度 */}
          <div className="flex flex-col gap-0.5">
            <div className="flex items-center gap-2">
              <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>趋势阶段</span>
              <div className="flex-1 min-w-0">
                <StageBar
                  stage={isWatchlistStyle ? (signal.lifecycleStage || '未入选') : (isLeader ? signalLabel : inferStageFromProfit(profitPct))}
                  value={0}
                  showLabels={isWatchlistStyle}
                  compact={isWatchlistStyle}
                />
              </div>
            </div>
            {isWatchlistStyle && (
              <div className="flex items-center gap-2">
                <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>个股强度</span>
                <div className="flex-1 min-w-0">
                  <StageBar stage={signal.qualityStatus || '中性'} showLabels compact variant="quality" />
                </div>
              </div>
            )}
            {/* 5 段指标 */}
            {(() => {
              if (settings.standaloneMainForce) {
                return signal.mainForce ? (
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: '#ef4444' }}>主力资金</span>
                    <div className="flex-1 min-w-0"><StageBar stage={signal.mainForce.stage} compact variant="mainForce" /></div>
                    <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{signal.mainForce.score}分</span>
                  </div>
                ) : null;
              }
              const modeSettings = isWatchlistStyle ? settings.watchlist : settings.trading;
              return (
                <>
                  {modeSettings.sentiment && signal.sentiment && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>情绪温度</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.sentiment.stage} compact variant="sentiment" /></div>
                    </div>
                  )}
                  {modeSettings.momentum && signal.momentum && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>资金动能</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.momentum.stage} compact variant="momentum" /></div>
                    </div>
                  )}
                  {modeSettings.mainForce && signal.mainForce && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>主力资金</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.mainForce.stage} compact variant="mainForce" /></div>
                    </div>
                  )}
                  {modeSettings.technical && signal.technical && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>技术形态</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.technical.stage} compact variant="technical" /></div>
                    </div>
                  )}
                  {modeSettings.sector && signal.sectorResonance && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>板块共振</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.sectorResonance.stage} compact variant="sector" /></div>
                    </div>
                  )}
                  {modeSettings.risk && signal.risk && (
                    <div className="flex items-center gap-2">
                      <span className="text-[10px] flex-shrink-0 font-medium" style={{ color: 'var(--text-muted)' }}>风险等级</span>
                      <div className="flex-1 min-w-0"><StageBar stage={signal.risk.stage} compact variant="risk" /></div>
                    </div>
                  )}
                </>
              );
            })()}
          </div>

          {/* 破位 + 主力大额净流入：左侧多维博弈状态栏 */}
          {isTechnicalBreakdown && isMainForceAggressiveBuy && (
            <div className="flex flex-col gap-1 p-1.5 rounded border" style={{ background: 'rgba(220,38,38,0.06)', borderColor: 'rgba(220,38,38,0.25)' }}>
              <div className="flex items-center justify-between text-[10px]">
                <span className="font-medium">🏛️ 机构正规军</span>
                <span style={{ color: '#52C41A', fontWeight: 700 }}>逆市吸筹 / 持续锁仓</span>
              </div>
              <div className="flex items-center justify-between text-[10px]">
                <span className="font-medium">⚔️ 游资敢死队</span>
                <span style={{ color: '#FF4D4F', fontWeight: 700 }}>短线砸盘 / 获利了结</span>
              </div>
            </div>
          )}

          {/* 关键数据横条：watchlist 模式下涨跌/现价/主力已整合到头部和资金流模块，此处只保留持仓详情 */}
          <div className="flex items-center gap-2 text-[11px] flex-wrap" style={{ color: 'var(--text-muted)' }}>
            {isWatchlistStyle ? (
              <>
                {mode === 'sim_watchlist' && (position?.count || 0) > 0 && (
                  <>
                    <span>总盈亏: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct.toFixed(2)}%</span></span>
                    <span>总: <span style={{ color: profitColor, fontWeight: 700 }}>{(position?.profit || 0) >= 0 ? '+' : ''}{formatYuanToWanYi(position?.profit)}</span></span>
                    <span>持仓: <span style={{ color: 'var(--text-primary)' }}>{position?.count || 0}股</span></span>
                    <span>成本: <span style={{ color: 'var(--text-primary)' }}>{(position?.costPrice || 0).toFixed(2)}</span></span>
                    <span>市值: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{((position?.value || 0) / 10000).toFixed(1)}万</span></span>
                    <span>仓位: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.posPct.toFixed(2)}%</span></span>
                    <span>当日: <span style={{ color: (position?.dayProfit || 0) >= 0 ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>{(position?.dayProfit || 0) >= 0 ? '+' : ''}{(position?.dayProfit || 0).toFixed(2)}</span></span>
                  </>
                )}
              </>
            ) : isLeader ? (
              <>
                <span>涨幅: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct.toFixed(2)}%</span></span>
                <span>连板: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.count || 0}</span></span>
                <span>强度: <span style={{ color: scoreColor, fontWeight: 700 }}>{score == null ? '-' : score}</span></span>
              </>
            ) : (
              <>
                <span>总盈亏: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct.toFixed(2)}%</span></span>
                <span>总: <span style={{ color: profitColor, fontWeight: 700 }}>{(position?.profit || 0) >= 0 ? '+' : ''}{fmtWanYi(position.profit)}</span></span>
                <span>仓位: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.posPct.toFixed(2)}%</span></span>
                <span>市值: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{((position?.value || 0) / 10000).toFixed(1)}万</span></span>
                <span>成本: <span style={{ color: 'var(--text-primary)' }}>{(position?.costPrice || 0).toFixed(2)}</span></span>
                <span>现价: <span style={{ color: 'var(--text-primary)' }}>{(position?.price || 0).toFixed(2)}</span></span>
                <span>持仓: <span style={{ color: 'var(--text-primary)' }}>{position?.count || 0}股</span></span>
                <span>当日: <span style={{ color: (position?.dayProfit || 0) >= 0 ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>{(position?.dayProfit || 0) >= 0 ? '+' : ''}{(position?.dayProfit || 0).toFixed(2)}</span></span>
              </>
            )}
          </div>

          {/* 板块热度 + 因子 */}
          <div className="flex flex-col gap-1 mt-0.5">
            {sectorTrend?.available && (
              <div
                className="flex items-center gap-2 px-2 py-1 rounded border"
                style={{
                  background: (sectorTrend.latest_heat || 0) >= 60 ? 'rgba(239,68,68,0.06)' : (sectorTrend.latest_heat || 0) >= 40 ? 'rgba(234,179,8,0.06)' : 'rgba(59,130,246,0.06)',
                  borderColor: (sectorTrend.latest_heat || 0) >= 60 ? 'rgba(239,68,68,0.25)' : (sectorTrend.latest_heat || 0) >= 40 ? 'rgba(234,179,8,0.25)' : 'rgba(59,130,246,0.25)',
                }}
              >
                <div className="flex items-baseline gap-1.5 min-w-0">
                  <span className="text-[10px] font-bold truncate" style={{ color: 'var(--text-secondary)' }}>{sector}</span>
                  <span className="text-base font-bold leading-none" style={{ color: (sectorTrend.latest_heat || 0) >= 60 ? '#ef4444' : (sectorTrend.latest_heat || 0) >= 40 ? '#eab308' : '#3b82f6' }}>
                    {(sectorTrend.latest_heat || 0).toFixed(1)}
                  </span>
                  <span className="text-[10px] font-bold whitespace-nowrap" style={{ color: sectorTrend.heat_trend === 'up' ? '#ef4444' : sectorTrend.heat_trend === 'down' ? '#22c55e' : '#999' }}>
                    {sectorTrend.heat_trend === 'up' ? '↑' : sectorTrend.heat_trend === 'down' ? '↓' : '→'}{(sectorTrend.decline_days || 0) > 0 ? `${sectorTrend.decline_days}天` : ''}
                  </span>
                </div>
                {Array.isArray(sectorTrend.heat_history) && sectorTrend.heat_history.length > 1 && (() => {
                  const data = sectorTrend.heat_history.slice(-7).map(v => Number(v) || 0);
                  const W = 60, H = 20, PAD = 2;
                  const dMax = Math.max(...data), dMin = Math.min(...data);
                  const range = Math.max(dMax - dMin, 20);
                  const base = (dMax + dMin - range) / 2;
                  const stepX = (W - PAD * 2) / (data.length - 1);
                  const pts = data.map((v, i) => ({
                    x: PAD + i * stepX,
                    y: H - PAD - ((v - base) / range) * (H - PAD * 2),
                  }));
                  const line = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x.toFixed(1)},${p.y.toFixed(1)}`).join(' ');
                  const tc = sectorTrend.heat_trend === 'up' ? '#ef4444' : sectorTrend.heat_trend === 'down' ? '#22c55e' : '#a855f7';
                  const last = pts[pts.length - 1];
                  return (
                    <svg width={W} height={H} className="ml-auto flex-shrink-0" style={{ overflow: 'visible' }}>
                      <path d={line} fill="none" stroke={tc} strokeWidth="1.2" strokeLinejoin="round" strokeLinecap="round" />
                      <circle cx={last.x} cy={last.y} r="1.8" fill={tc} />
                    </svg>
                  );
                })()}
              </div>
            )}
            {isHardcoreLabel ? (
              <div
                className="rounded border p-1.5 text-[10px]"
                style={{
                  background: isTechnicalBreakdown ? 'rgba(220,38,38,0.06)' : 'rgba(234,179,8,0.06)',
                  borderColor: isTechnicalBreakdown ? 'rgba(220,38,38,0.25)' : 'rgba(234,179,8,0.25)',
                }}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold" style={{ color: isTechnicalBreakdown ? '#dc2626' : '#f97316' }}>
                    AI 联动诊断 · {isTechnicalBreakdown ? '风控优先' : '防守优先'}</span>
                  {hasPriceVolumeDivergence && (
                    <span className="px-1 rounded text-[10px] font-bold" style={{ background: 'rgba(220,38,38,0.12)', color: '#dc2626' }}>
                      价量背离
                    </span>
                  )}
                </div>
                <div className="flex flex-col gap-0.5" style={{ color: 'var(--text-secondary)' }}>
                  <div className="flex items-start gap-1">
                    <span className="font-bold flex-shrink-0" style={{ color: BEARISH_COLOR }}>空2</span>
                    <div className="flex flex-wrap gap-0.5 min-w-0">
                      <span className="px-1 rounded" style={{ background: 'rgba(34,197,94,0.08)' }}>
                        <span className="font-mono font-bold mr-0.5" style={{ color: BEARISH_COLOR }}>-2</span>
                        {isTechnicalBreakdown ? '技术破位（触发风控）' : '技术弱势（卖出信号）'}
                      </span>
                      {sectorTrend?.heat_trend === 'down' && (
                        <span className="px-1 rounded" style={{ background: 'rgba(34,197,94,0.08)' }}>
                          <span className="font-mono font-bold mr-0.5" style={{ color: BEARISH_COLOR }}>-1</span>板块降温
                        </span>
                      )}
                    </div>
                  </div>
                  {(positiveFactors || []).length > 0 && (
                    <div className="flex items-start gap-1">
                      <span className="font-bold flex-shrink-0" style={{ color: BULLISH_COLOR }}>多{(positiveFactors || []).length}</span>
                      <div className="flex flex-wrap gap-0.5 min-w-0">
                        {(positiveFactors || []).filter(f => f.factor !== '资金流出').slice(0, 3).map((f, i) => (
                          <span key={i} className="px-1 rounded" style={{ background: 'rgba(239,68,68,0.08)' }} title={f.factor}>
                            <span className="font-mono font-bold mr-0.5" style={{ color: BULLISH_COLOR }}>+{f.weight}</span>{f.factor}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}
                  <div className="mt-0.5 leading-relaxed" style={{ color: 'var(--text-muted)' }}>
                    {isTechnicalBreakdown ? (
                      <>
                        🔴 技术面：已严重破位，触发最高级别风控，必须执行抛售或大幅减仓。<br />
                        {isMainForceAggressiveBuy ? (
                          <>🟢 资金面：全景雷达捕捉到主力/机构逆市大额吸筹，近5日累计加仓超23亿。</>
                        ) : (
                          <>⚪ 资金面：未出现明显主力逆势建仓信号。</>
                        )}<br />
                        <span style={{ color: '#dc2626' }}>核心结论：破位已确认，风控第一原则，立即执行抛/减仓，不抱侥幸。</span>
                      </>
                    ) : signalLabel === '弱势：果断减仓' ? (
                      <>
                        🟠 技术面：技术形态弱势，均线支撑失守，短期趋势向下。<br />
                        {isMainForceAggressiveBuy ? (
                          <>🟢 资金面：虽有主力资金流入，但技术面偏弱需谨慎。</>
                        ) : (
                          <>⚪ 资金面：资金面无明确支撑信号。</>
                        )}<br />
                        <span style={{ color: '#f97316' }}>核心结论：弱势确认，果断减仓控制风险，等均线企稳再考虑回补。</span>
                      </>
                    ) : (
                      <>
                        🟡 技术面：技术形态震荡，方向不明确，BS信号已触发卖出。<br />
                        <span style={{ color: '#eab308' }}>核心结论：震荡偏空，暂避不加仓，等方向明确再行动。</span>
                      </>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="flex flex-col gap-0.5 text-[10px] min-w-0">
                <div className="flex items-start gap-1">
                  <span className="font-bold flex-shrink-0" style={{ color: BEARISH_COLOR }}>空{(negativeFactors || []).length > 0 ? (negativeFactors || []).length : ''}</span>
                  <div className="flex flex-wrap gap-0.5 min-w-0">
                    {(negativeFactors || []).length === 0 ? (
                      <span style={{ color: 'var(--text-muted)' }}>无</span>
                    ) : (negativeFactors || []).slice(0, 4).map((f, i) => (
                      <span key={i} className="px-1 rounded" style={{ background: 'rgba(34,197,94,0.08)' }} title={f.factor}>
                        <span className="font-mono font-bold mr-0.5" style={{ color: BEARISH_COLOR }}>{f.weight}</span>{f.factor}
                      </span>
                    ))}
                    {(negativeFactors || []).length > 4 && (
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>+{(negativeFactors || []).length - 4}</span>
                    )}
                  </div>
                </div>
                <div className="flex items-start gap-1">
                  <span className="font-bold flex-shrink-0" style={{ color: BULLISH_COLOR }}>多{(positiveFactors || []).length > 0 ? (positiveFactors || []).length : ''}</span>
                  <div className="flex flex-wrap gap-0.5 min-w-0">
                    {(positiveFactors || []).length === 0 ? (
                      <span style={{ color: 'var(--text-muted)' }}>无</span>
                    ) : (positiveFactors || []).slice(0, 4).map((f, i) => (
                      <span key={i} className="px-1 rounded" style={{ background: 'rgba(239,68,68,0.08)' }} title={f.factor}>
                        <span className="font-mono font-bold mr-0.5" style={{ color: BULLISH_COLOR }}>+{f.weight}</span>{f.factor}
                      </span>
                    ))}
                    {(positiveFactors || []).length > 4 && (
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>+{(positiveFactors || []).length - 4}</span>
                    )}
                  </div>
                </div>
              </div>
            )}
            {isWatchlistStyle && signal.actionHint && (
              <div className="flex items-start gap-1 mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>⚡</span>
                <span style={{ color: 'var(--text-secondary)' }}>{signal.actionHint}</span>
              </div>
            )}
          </div>
        </div>

        {/* ========== 中列：资金流向模块（紧凑 2x2 网格：盘后 + 实时） ========== */}
        <div className="signalcard-module module-flow flex-1 min-w-[320px] flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-bold" style={{ color: '#ef4444' }}>💰 资金流向</span>
              {(signal.hitTags || []).includes('capital') && (
                <span className="text-[10px] px-1 rounded font-bold" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>主力爆买</span>
              )}
            </div>
            <div className="flex items-center gap-1" />
          </div>

          {/* 板块资金净流入 */}
          {signal.sectorTrend?.available && signal.sectorTrend?.total_net_flow != null && (
            <div className="flex items-center justify-between text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.08)', border: '1px solid rgba(168,85,247,0.2)' }}>
              <span style={{ color: 'var(--text-muted)' }}>🏭 {signal.sector || '板块'}资金净流入</span>
              <span className="font-bold" style={{ color: (signal.sectorTrend.total_net_flow || 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                {(signal.sectorTrend.total_net_flow || 0) >= 0 ? '+' : ''}{fmtWanYi(signal.sectorTrend.total_net_flow)}
              </span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-1.5">
            {/* 左上：盘后 4 档（紧凑横向进度条） + 近N日累计 */}
            {signal.moneyFlow?.available ? (
              <div className="flex flex-col gap-0.5">
                <div className="flex items-center gap-1 mb-0.5">
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
                    📊 盘后{signal.moneyFlow?.trade_date ? ` ${String(signal.moneyFlow.trade_date).slice(0,4)}/${String(signal.moneyFlow.trade_date).slice(4,6)}/${String(signal.moneyFlow.trade_date).slice(6,8)}` : ''}
                  </span>
                </div>
                {(() => {
                  const mf = signal.moneyFlow;
                  const rows = [
                    { label: '特大', val: mf.super_large || 0, color: '#ef4444' },
                    { label: '大单', val: mf.large || 0, color: '#f97316' },
                    { label: '小单', val: mf.small || 0, color: '#3b82f6' },
                    { label: '散单', val: mf.tiny || 0, color: '#64748b' },
                  ];
                  const maxAbs = Math.max(...rows.map(r => Math.abs(r.val)), 1);
                  return rows.map((r, i) => {
                    const isPos = r.val >= 0;
                    const pct = Math.min(100, Math.abs(r.val) / maxAbs * 100);
                    return (
                      <div key={i} className="flex items-center gap-1 text-[10px]">
                        <span className="w-6 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{r.label}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.15)' }}>
                          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: isPos ? r.color : '#22c55e' }} />
                        </div>
                        <span className="w-10 text-right font-bold flex-shrink-0" style={{ color: isPos ? '#ef4444' : '#22c55e' }}>
                          {isPos ? '+' : ''}{fmtWanYi(r.val)}
                        </span>
                      </div>
                    );
                  });
                })()}
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>主力净流入累计</div>
                <div className="grid grid-cols-5 gap-0.5 text-[10px]">
                  {(() => {
                    const mf = signal.moneyFlow;
                    return [
                      { label: '近1日', val: mf.inflow_1d ?? 0 },
                      { label: '近2日', val: mf.inflow_2d ?? 0 },
                      { label: '近3日', val: mf.inflow_3d ?? 0 },
                      { label: '近5日', val: mf.inflow_5d ?? 0 },
                      { label: '近10日', val: mf.inflow_10d },
                    ].map((c, i) => {
                      const isNull = c.val === null || c.val === undefined;
                      return (
                        <div key={i} className="rounded px-0.5 py-0.5 text-center" style={{ background: isNull ? 'rgba(107,114,128,0.08)' : (c.val >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)') }}>
                          <div style={{ color: 'var(--text-muted)' }}>{c.label}</div>
                          <div className="font-bold" style={{ color: isNull ? 'var(--text-muted)' : (c.val >= 0 ? '#ef4444' : '#22c55e') }}>
                            {isNull ? '—' : `${c.val >= 0 ? '+' : ''}${fmtWanYi(c.val)}`}
                          </div>
                        </div>
                      );
                    });
                  })()}
                </div>
              </div>
            ) : (
              <div className="text-[10px] text-center py-2" style={{ color: 'var(--text-muted)' }}>暂无盘后数据</div>
            )}

            {/* 右上：实时数据（价格 + 主力净流入 + 散户净流） */}
            {showRealtimeDetail && realtimeFlow && (realtimeFlow.intraday_points?.length > 0 || realtimeFlow.main_force_inflow != null) ? (
              <>
                <div className="flex items-center gap-1 mb-0.5">
                  <span className="text-[10px] px-1.5 py-0.5 rounded font-bold inline-flex items-center gap-1" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
                    <span className={`inline-block w-1.5 h-1.5 rounded-full ${realtimeFlow.is_stale ? '' : 'animate-pulse'}`} style={{ background: realtimeFlow.is_stale ? '#64748b' : '#ef4444' }} />
                    🔴 实时{realtimeFlow?.latest_time ? ` ${realtimeFlow.latest_time.slice(11, 16)}` : ''}
                  </span>
                </div>
                {(() => {
                  const pts = realtimeFlow.intraday_points || [];
                  const hasPts = pts.length > 1;
                  const last = hasPts ? pts[pts.length - 1] : realtimeFlow;
                  const w = 70;
                  const step = hasPts ? w / (pts.length - 1) : 0;

                  const buildPath = (vals, minV, rangeV, h) => {
                    if (!hasPts) return '';
                    return vals.map((v, i) => {
                      const x = i * step;
                      const y = h - ((v - minV) / rangeV) * h;
                      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
                    }).join(' ');
                  };

                  const prices = hasPts ? pts.map(p => p.price || 0) : [];
                  const minP = hasPts ? Math.min(...prices) : 0;
                  const maxP = hasPts ? Math.max(...prices) : 1;
                  const rangeP = hasPts ? (maxP - minP || 1) : 1;

                  const mfVals = hasPts ? pts.map(p => p.main_force_inflow || 0) : [];
                  const minM = hasPts ? Math.min(...mfVals) : 0;
                  const maxM = hasPts ? Math.max(...mfVals) : 1;
                  const rangeM = hasPts ? (maxM - minM || 1) : 1;

                  const retailVals = hasPts ? pts.map(p => p.retail_flow || -(p.main_force_inflow || 0)) : [];
                  const minR = hasPts ? Math.min(...retailVals) : 0;
                  const maxR = hasPts ? Math.max(...retailVals) : 1;
                  const rangeR = hasPts ? (maxR - minR || 1) : 1;

                  const firstP = hasPts ? (pts[0].price || 0) : 0;
                  const lastPrice = last.price ?? realtimeFlow.price ?? 0;
                  const chgPct = firstP ? ((lastPrice - firstP) / firstP) * 100 : (realtimeFlow.price_chg || 0);
                  const chgColor = chgPct >= 0 ? '#ef4444' : '#22c55e';

                  const mainForce = last.main_force_inflow ?? realtimeFlow.main_force_inflow ?? 0;
                  const retailFlow = last.retail_flow ?? realtimeFlow.retail_flow ?? -mainForce;
                  const mfColor = mainForce >= 0 ? '#ef4444' : '#22c55e';
                  const retailColor = retailFlow >= 0 ? '#ef4444' : '#22c55e';

                  return (
                    <div className="flex flex-col gap-1 col-span-1">
                      {/* 实时价格走势 */}
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex flex-col">
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>最新价</span>
                          <span className="text-[10px] font-bold tabular-nums" style={{ color: chgColor }}>
                            {lastPrice ? lastPrice.toFixed(2) : '--'} {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%
                          </span>
                        </div>
                        {hasPts && (
                          <svg width="50%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <path d={`${buildPath(prices, minP, rangeP, 20)} L${w},20 L0,20 Z`} fill={chgPct >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(prices, minP, rangeP, 20)} fill="none" stroke={chgColor} strokeWidth="1" />
                            <circle cx={w} cy={20 - ((lastPrice - minP) / rangeP) * 20} r="1.2" fill={chgColor} />
                          </svg>
                        )}
                      </div>

                      {/* 主力净流入 */}
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex flex-col">
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>主力净流</span>
                          <span className="text-[10px] font-bold tabular-nums" style={{ color: mfColor }}>
                            {mainForce >= 0 ? '+' : ''}{fmtWanYi(mainForce)}
                          </span>
                        </div>
                        {hasPts && (
                          <svg width="50%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <line x1="0" y1={20 - ((0 - minM) / rangeM) * 20} x2={w} y2={20 - ((0 - minM) / rangeM) * 20} stroke="rgba(107,114,128,0.25)" strokeWidth="0.4" strokeDasharray="2,2" />
                            <path d={`${buildPath(mfVals, minM, rangeM, 20)} L${w},20 L0,20 Z`} fill={mainForce >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(mfVals, minM, rangeM, 20)} fill="none" stroke={mfColor} strokeWidth="1" />
                            <circle cx={w} cy={20 - ((mainForce - minM) / rangeM) * 20} r="1.2" fill={mfColor} />
                          </svg>
                        )}
                      </div>

                      {/* 散户净流（实时数据源不提供总净流入，按日内资金平衡估算） */}
                      <div className="flex items-center justify-between gap-1">
                        <div className="flex flex-col">
                          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>散户净流*</span>
                          <span className="text-[10px] font-bold tabular-nums" style={{ color: retailColor }}>
                            {retailFlow >= 0 ? '+' : ''}{fmtWanYi(retailFlow)}
                          </span>
                        </div>
                        {hasPts && (
                          <svg width="50%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <line x1="0" y1={20 - ((0 - minR) / rangeR) * 20} x2={w} y2={20 - ((0 - minR) / rangeR) * 20} stroke="rgba(107,114,128,0.25)" strokeWidth="0.4" strokeDasharray="2,2" />
                            <path d={`${buildPath(retailVals, minR, rangeR, 20)} L${w},20 L0,20 Z`} fill={retailFlow >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(retailVals, minR, rangeR, 20)} fill="none" stroke={retailColor} strokeWidth="1" />
                            <circle cx={w} cy={20 - ((retailFlow - minR) / rangeR) * 20} r="1.2" fill={retailColor} />
                          </svg>
                        )}
                      </div>

                      {realtimeFlow.latest_time && (
                        <div className="text-[7px] text-right" style={{ color: 'var(--text-muted)' }}>
                          盘中 {realtimeFlow.latest_time.slice(11, 16)} · *散户净流=估算
                        </div>
                      )}
                    </div>
                  );
                })()}
              </>
            ) : (
              <div className="text-[10px] text-center py-2 col-span-1" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>
            )}
          </div>

          {/* 新增：同花顺风格盘后资金流向看板 */}
          {isWatchlistStyle && (
            <MoneyFlowBoard moneyFlow={signal.moneyFlow} sectorTrend={signal.sectorTrend} sector={signal.sector} />
          )}
        </div>

        {/* ========== 右列：操作按钮模块（竖排） ========== */}
        <div className="signalcard-module module-actions flex-shrink-0 flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'var(--bg-card)', minWidth: '64px' }}>
          <button
            onClick={(e) => { e.stopPropagation(); setKlineOpen(true); }}
            className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center"
            style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}
          >
            K线BS
          </button>
          {showMarketState && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center"
              style={{ background: st.bg, color: st.color }}
              title={marketState?.reasons?.join('、') || st.label}>
              {st.icon} {st.label}
            </span>
          )}
          {showBuyPower && bp.score > 0 && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center"
              style={{ background: `${bp.color}22`, color: bp.color }}
              title={`量${bp.dimensions?.volume||0} 位${bp.dimensions?.position||0} 流${bp.dimensions?.flow||0} 热${bp.dimensions?.heat||0} 形${bp.dimensions?.tech||0}`}>
              购买力
            </span>
          )}
          {showAnalysisButton && (
            <button
              onClick={(e) => { e.stopPropagation(); navigate(`/stock/${secCode}`); }}
              className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center"
              style={{ background: 'rgba(168,85,247,0.12)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
            >
              🔍分析
            </button>
          )}
          <StockActionButtons
            stockCode={secCode}
            stockName={secName}
            signal={signal}
            positionCount={position?.count || 0}
            showBuy={showBuyBtn ?? showWatchBtn}
            showSell={!isLeader && (position?.count || 0) > 0}
            showWatch={showWatchBtn}
            showFocus={showFocusBtn}
            showMore={showActionButton}
            size="sm"
            onRefresh={onRefresh}
            onRemove={onRemove}
          />
        </div>
      </div>

      {/* K线BS点弹窗 */}
      {klineOpen && (
        <KLineModal stockCode={secCode} stockName={secName} onClose={() => setKlineOpen(false)} />
      )}

      {/* 委托记录弹窗 */}
      {orderOpen && (
        <OrderHistoryModal stockName={secName} secCode={secCode} orders={orders} onClose={() => setOrderOpen(false)} />
      )}

      {/* 指标模块组合设置弹窗 */}
      <IndicatorSettings
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        settings={settings}
        onChange={setSettings}
      />
    </div>
  );
}

export default memo(SignalCard);
