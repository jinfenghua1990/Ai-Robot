import { useState, memo } from 'react';
import { useNavigate } from 'react-router-dom';
import TradeButton from './TradeButton';
import KLineModal from './KLineModal';
import OrderHistoryModal from './OrderHistoryModal';
import StockActionModal from './StockActionModal';
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
  mode = 'trading',
  showMarketState = false,
  showBuyPower = false,
  showAnalysisButton = false,
  showActionButton = false,
  strategyTags = [],
  realtimeFlow = null,
}) {
  const [klineOpen, setKlineOpen] = useState(false);
  const [orderOpen, setOrderOpen] = useState(false);
  const [watchAdded, setWatchAdded] = useState(false);
  const [focusAdded, setFocusAdded] = useState(false);
  const [actionOpen, setActionOpen] = useState(false);
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

  const fmtWan = (v) => {
    const x = v || 0;
    return Math.abs(x) >= 10000 ? (x / 10000).toFixed(2) + '亿' : x.toFixed(0) + '万';
  };

  return (
    <div
      className="rounded-lg border overflow-hidden"
      style={{ borderColor: `${signalColor}40`, background: 'var(--bg-card)' }}
    >
      {/* ===== 三列模块化布局：左信息 | 中资金流 | 右操作 ===== */}
      <div className="flex flex-row items-stretch gap-2 px-3 py-2">

        {/* ========== 左列：核心信息模块 ========== */}
        <div className="signalcard-module module-info flex-1 min-w-[220px] flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'var(--bg-card)' }}>
          {/* 头部：标签 + 名称 + 按钮 */}
          <div className="flex items-start gap-2">
            <div
              className="flex-shrink-0 w-11 h-11 rounded-md flex flex-col items-center justify-center font-bold"
              style={{ background: `${signalColor}15`, border: `2px solid ${signalColor}` }}
            >
              <span className="text-xs" style={{ color: signalColor }}>{signalLabel}</span>
              {score != null && (
                <span className="text-[10px] mt-0.5" style={{ color: scoreColor }}>{score > 0 ? '+' : ''}{score}</span>
              )}
            </div>
            <button
              onClick={(e) => { e.stopPropagation(); setSettingsOpen(true); }}
              className="flex-shrink-0 w-6 h-11 rounded-md flex flex-col items-center justify-center text-[9px] cursor-pointer leading-tight"
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
                  {dayProfitPct >= 0 ? '+' : ''}{dayProfitPct}%
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
                  <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }} title="RSI6">
                    RSI6 {signal.rsi6?.toFixed(1)}
                  </span>
                  {signal.ma5 > 0 && (
                    <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA5 {signal.ma5.toFixed(2)}
                    </span>
                  )}
                  {signal.ma10 > 0 && (
                    <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA10 {signal.ma10.toFixed(2)}
                    </span>
                  )}
                  {signal.ma20 > 0 && (
                    <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }} title="均线">
                      MA20 {signal.ma20.toFixed(2)}
                    </span>
                  )}
                  {signal.volRatio > 0 && (
                    <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }} title="量比">
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
                    <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{signal.mainForce.score}分</span>
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

          {/* 关键数据横条：watchlist 模式下涨跌/现价/主力已整合到头部和资金流模块，此处只保留持仓详情 */}
          <div className="flex items-center gap-2 text-[11px] flex-wrap" style={{ color: 'var(--text-muted)' }}>
            {isWatchlistStyle ? (
              <>
                {mode === 'sim_watchlist' && (position?.count || 0) > 0 && (
                  <>
                    <span>盈亏: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct}%</span></span>
                    <span>盈亏额: <span style={{ color: profitColor, fontWeight: 700 }}>{(position?.profit || 0) >= 0 ? '+' : ''}{fmtWan(position?.profit)}</span></span>
                    <span>持仓: <span style={{ color: 'var(--text-primary)' }}>{position?.count || 0}股</span></span>
                    <span>成本: <span style={{ color: 'var(--text-primary)' }}>{(position?.costPrice || 0).toFixed(2)}</span></span>
                    <span>市值: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{((position?.value || 0) / 10000).toFixed(1)}万</span></span>
                    <span>仓位: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.posPct || 0}%</span></span>
                    <span>当日: <span style={{ color: (position?.dayProfit || 0) >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{(position?.dayProfit || 0) >= 0 ? '+' : ''}{position?.dayProfit || 0}</span></span>
                  </>
                )}
              </>
            ) : isLeader ? (
              <>
                <span>涨幅: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct}%</span></span>
                <span>连板: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.count || 0}</span></span>
                <span>强度: <span style={{ color: scoreColor, fontWeight: 700 }}>{score == null ? '-' : score}</span></span>
              </>
            ) : (
              <>
                <span>盈亏: <span style={{ color: profitColor, fontWeight: 700 }}>{profitPct >= 0 ? '+' : ''}{profitPct}%</span></span>
                <span>盈亏额: <span style={{ color: profitColor, fontWeight: 700 }}>{(position?.profit || 0) >= 0 ? '+' : ''}{fmtWan(position.profit)}</span></span>
                <span>仓位: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{position?.posPct || 0}%</span></span>
                <span>市值: <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{((position?.value || 0) / 10000).toFixed(1)}万</span></span>
                <span>成本: <span style={{ color: 'var(--text-primary)' }}>{(position?.costPrice || 0).toFixed(2)}</span></span>
                <span>现价: <span style={{ color: 'var(--text-primary)' }}>{(position?.price || 0).toFixed(2)}</span></span>
                <span>持仓: <span style={{ color: 'var(--text-primary)' }}>{position?.count || 0}股</span></span>
                <span>当日: <span style={{ color: (position?.dayProfit || 0) >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>{(position?.dayProfit || 0) >= 0 ? '+' : ''}{position?.dayProfit || 0}</span></span>
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
                    <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>+{(negativeFactors || []).length - 4}</span>
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
                    <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>+{(positiveFactors || []).length - 4}</span>
                  )}
                </div>
              </div>
            </div>
            {isWatchlistStyle && signal.actionHint && (
              <div className="flex items-start gap-1 mt-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <span>⚡</span>
                <span style={{ color: 'var(--text-secondary)' }}>{signal.actionHint}</span>
              </div>
            )}
          </div>
        </div>

        {/* ========== 中列：资金流向模块（紧凑 2x2 网格：盘后 + 实时） ========== */}
        <div className="signalcard-module module-flow flex-1 min-w-[200px] flex flex-col gap-1 rounded-md px-2 py-1" style={{ background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-1">
              <span className="text-[10px] font-bold" style={{ color: '#ef4444' }}>💰 资金流向</span>
              {(signal.hitTags || []).includes('capital') && (
                <span className="text-[9px] px-1 rounded font-bold" style={{ background: 'rgba(239,68,68,0.12)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}>主力爆买</span>
              )}
            </div>
            <div className="flex items-center gap-1">
              {signal.moneyFlow?.available && signal.moneyFlow?.trade_date && (
                <span className="text-[9px] px-1 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>盘后 {String(signal.moneyFlow.trade_date).slice(6,8)}日</span>
              )}
              {realtimeFlow?.latest_time && (
                <span className="text-[9px] px-1 rounded inline-flex items-center gap-0.5" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
                  <span className={`inline-block w-1 h-1 rounded-full ${realtimeFlow.is_stale ? '' : 'animate-pulse'}`} style={{ background: realtimeFlow.is_stale ? '#64748b' : '#ef4444' }} />
                  {realtimeFlow.latest_time.slice(11, 16)}
                </span>
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-1.5">
            {/* 左上：盘后 4 档（紧凑横向进度条） */}
            {signal.moneyFlow?.available ? (
              <div className="flex flex-col gap-0.5">
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
                      <div key={i} className="flex items-center gap-1 text-[9px]">
                        <span className="w-6 flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{r.label}</span>
                        <div className="flex-1 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.15)' }}>
                          <div className="h-full rounded-full" style={{ width: `${pct}%`, background: isPos ? r.color : '#22c55e' }} />
                        </div>
                        <span className="w-10 text-right font-bold flex-shrink-0" style={{ color: isPos ? '#ef4444' : '#22c55e' }}>
                          {isPos ? '+' : ''}{fmtWan(r.val)}
                        </span>
                      </div>
                    );
                  });
                })()}
                <div className="grid grid-cols-5 gap-0.5 text-[9px] mt-0.5">
                  {(() => {
                    const mf = signal.moneyFlow;
                    return [
                      { label: '1日', val: mf.inflow_1d || 0 },
                      { label: '2日', val: mf.inflow_2d || 0 },
                      { label: '3日', val: mf.inflow_3d || 0 },
                      { label: '4日', val: mf.inflow_4d || 0 },
                      { label: '5日', val: mf.inflow_5d || 0 },
                    ].map((c, i) => (
                      <div key={i} className="rounded px-0.5 py-0.5 text-center" style={{ background: c.val >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)' }}>
                        <div style={{ color: 'var(--text-muted)' }}>{c.label}</div>
                        <div className="font-bold" style={{ color: c.val >= 0 ? '#ef4444' : '#22c55e' }}>
                          {c.val >= 0 ? '+' : ''}{fmtWan(c.val)}
                        </div>
                      </div>
                    ));
                  })()}
                </div>
              </div>
            ) : (
              <div className="text-[10px] text-center py-2" style={{ color: 'var(--text-muted)' }}>暂无盘后数据</div>
            )}

            {/* 右上 + 左下 + 右下：实时数据（价格 + 主力净流入 + 总净流入） */}
            {realtimeFlow && realtimeFlow.intraday_points && realtimeFlow.intraday_points.length > 0 ? (
              <>
                {(() => {
                  const pts = realtimeFlow.intraday_points;
                  const last = pts[pts.length - 1];
                  const prices = pts.map(p => p.price || 0);
                  const minP = Math.min(...prices), maxP = Math.max(...prices);
                  const rangeP = maxP - minP || 1;
                  const mfVals = pts.map(p => p.main_force_inflow || 0);
                  const minM = Math.min(...mfVals), maxM = Math.max(...mfVals);
                  const rangeM = maxM - minM || 1;
                  const netVals = pts.map(p => p.net_inflow || 0);
                  const minN = Math.min(...netVals), maxN = Math.max(...netVals);
                  const rangeN = maxN - minN || 1;
                  const w = 100;
                  const step = w / Math.max(pts.length - 1, 1);

                  const buildPath = (vals, minV, rangeV, h) => {
                    return vals.map((v, i) => {
                      const x = i * step;
                      const y = h - ((v - minV) / rangeV) * h;
                      return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
                    }).join(' ');
                  };

                  const firstP = pts[0].price || 0;
                  const chgPct = firstP ? ((last.price - firstP) / firstP) * 100 : 0;
                  const chgColor = chgPct >= 0 ? '#ef4444' : '#22c55e';

                  return (
                    <div className="flex flex-col gap-1 col-span-1">
                      {/* 实时价格走势 */}
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between text-[9px]">
                          <span style={{ color: 'var(--text-muted)' }}>最新价</span>
                          <span className="font-bold" style={{ color: chgColor }}>{last.price != null ? last.price.toFixed(2) : '--'} {chgPct >= 0 ? '+' : ''}{chgPct.toFixed(2)}%</span>
                        </div>
                        <div className="relative h-5">
                          <svg width="100%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <path d={`${buildPath(prices, minP, rangeP, 20)} L${w},20 L0,20 Z`} fill={chgPct >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(prices, minP, rangeP, 20)} fill="none" stroke={chgColor} strokeWidth="1" />
                            <circle cx={(pts.length - 1) * step} cy={20 - ((last.price - minP) / rangeP) * 20} r="1.2" fill={chgColor} />
                          </svg>
                          <div className="flex justify-between text-[7px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                            <span>{pts[0]?.time}</span>
                            <span>{last?.time}</span>
                          </div>
                        </div>
                      </div>

                      {/* 主力净流入 */}
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between text-[9px]">
                          <span style={{ color: 'var(--text-muted)' }}>主力净流</span>
                          <span className="font-bold" style={{ color: (last.main_force_inflow || 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                            {(last.main_force_inflow || 0) >= 0 ? '+' : ''}{fmtWan(last.main_force_inflow)}
                          </span>
                        </div>
                        <div className="relative h-5">
                          <svg width="100%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <line x1="0" y1={20 - ((0 - minM) / rangeM) * 20} x2={w} y2={20 - ((0 - minM) / rangeM) * 20} stroke="rgba(107,114,128,0.25)" strokeWidth="0.4" strokeDasharray="2,2" />
                            <path d={`${buildPath(mfVals, minM, rangeM, 20)} L${w},20 L0,20 Z`} fill={(last.main_force_inflow || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(mfVals, minM, rangeM, 20)} fill="none" stroke={(last.main_force_inflow || 0) >= 0 ? '#ef4444' : '#22c55e'} strokeWidth="1" />
                            <circle cx={(pts.length - 1) * step} cy={20 - ((last.main_force_inflow - minM) / rangeM) * 20} r="1.2" fill={(last.main_force_inflow || 0) >= 0 ? '#ef4444' : '#22c55e'} />
                          </svg>
                          <div className="flex justify-between text-[7px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                            <span>{pts[0]?.time}</span>
                            <span>{last?.time}</span>
                          </div>
                        </div>
                      </div>

                      {/* 总净流入 */}
                      <div className="flex flex-col gap-0.5">
                        <div className="flex items-center justify-between text-[9px]">
                          <span style={{ color: 'var(--text-muted)' }}>总净流入</span>
                          <span className="font-bold" style={{ color: (last.net_inflow || 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                            {(last.net_inflow || 0) >= 0 ? '+' : ''}{fmtWan(last.net_inflow)}
                          </span>
                        </div>
                        <div className="relative h-5">
                          <svg width="100%" height="20" viewBox={`0 0 ${w} 20`} preserveAspectRatio="none" style={{ display: 'block' }}>
                            <line x1="0" y1={20 - ((0 - minN) / rangeN) * 20} x2={w} y2={20 - ((0 - minN) / rangeN) * 20} stroke="rgba(107,114,128,0.25)" strokeWidth="0.4" strokeDasharray="2,2" />
                            <path d={`${buildPath(netVals, minN, rangeN, 20)} L${w},20 L0,20 Z`} fill={(last.net_inflow || 0) >= 0 ? 'rgba(239,68,68,0.08)' : 'rgba(34,197,94,0.08)'} />
                            <path d={buildPath(netVals, minN, rangeN, 20)} fill="none" stroke={(last.net_inflow || 0) >= 0 ? '#ef4444' : '#22c55e'} strokeWidth="1" />
                            <circle cx={(pts.length - 1) * step} cy={20 - ((last.net_inflow - minN) / rangeN) * 20} r="1.2" fill={(last.net_inflow || 0) >= 0 ? '#ef4444' : '#22c55e'} />
                          </svg>
                          <div className="flex justify-between text-[7px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                            <span>{pts[0]?.time}</span>
                            <span>{last?.time}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  );
                })()}
              </>
            ) : (
              realtimeFlow && <div className="text-[10px] text-center py-2 col-span-1" style={{ color: 'var(--text-muted)' }}>暂无实时数据</div>
            )}
          </div>
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
          <TradeButton stockCode={secCode} stockName={secName} type="buy" positionCount={position?.count || 0} className="h-7 min-w-[48px] !px-2 !py-0" />
          {!isLeader && (position?.count || 0) > 0 && (
            <button
              onClick={(e) => { e.stopPropagation(); onSell?.({ stockCode: secCode, stockName: secName, positionCount: position?.count || 0 }); }}
              className="px-2 text-xs rounded font-medium inline-flex items-center justify-center h-7 min-w-[48px]"
              style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}
            >
              卖
            </button>
          )}
          {showActionButton && (
            <button
              onClick={(e) => { e.stopPropagation(); setActionOpen(true); }}
              className="px-2 text-xs rounded font-medium inline-flex items-center justify-center h-7 min-w-[48px]"
              style={{ background: 'rgba(107,114,128,0.1)', color: '#6b7280', border: '1px solid rgba(107,114,128,0.3)' }}
            >
              操作
            </button>
          )}
          {showWatchBtn && (
            <button
              onClick={async (e) => {
                e.stopPropagation();
                if (watchAdded) return;
                const { ok } = await apiFetch('/api/watchlist/add', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ stockCode: secCode, stockName: secName }),
                });
                if (ok) setWatchAdded(true);
              }}
              className="px-2 text-xs rounded font-medium inline-flex items-center justify-center h-7 min-w-[48px]"
              style={watchAdded
                ? { background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
                : { background: 'rgba(234,179,8,0.1)', color: '#eab308', border: '1px solid rgba(234,179,8,0.3)' }
              }
            >
              {watchAdded ? '✓已加' : '自选'}
            </button>
          )}
          {showFocusBtn && (
            <button
              onClick={async (e) => {
                e.stopPropagation();
                if (focusAdded) return;
                const res = await apiFetch('/api/watchlist/add', {
                  method: 'POST',
                  headers: { 'Content-Type': 'application/json' },
                  body: JSON.stringify({ stockCode: secCode, stockName: secName, group: '重点关注' }),
                });
                if (res.ok) {
                  setFocusAdded(true);
                } else if (res.status === 400) {
                  const moveRes = await apiFetch(`/api/watchlist/${secCode}/move-group`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ target_group: '重点关注' }),
                  });
                  if (moveRes.ok) setFocusAdded(true);
                }
              }}
              className="px-2 text-xs rounded font-medium inline-flex items-center justify-center h-7 min-w-[48px]"
              style={focusAdded
                ? { background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
                : { background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }
              }
            >
              {focusAdded ? '✓已关注' : '重点'}
            </button>
          )}
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

      {/* 操作弹窗（移除等） */}
      {actionOpen && (
        <StockActionModal
          signal={signal}
          onRemove={onRemove}
          onRefresh={onRefresh}
          onClose={() => setActionOpen(false)}
        />
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
