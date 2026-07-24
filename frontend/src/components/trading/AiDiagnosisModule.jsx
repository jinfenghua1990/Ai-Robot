// AiDiagnosisModule：底部独立 AI 联动诊断（盘后 ‖ 实时 双列，规则化合成）。
// 2026-07-19 v2：3 行结构化布局
//   行1：结论标签 + 多空评分进度条（空头/多头双向条）
//   行2：多头逻辑（绿底）+ 命中条件
//   行3：空头风险（红底）+ 命中条件
// 左右严格对齐：左盘后 / 右实时

import { memo, useMemo } from 'react';

function synthesize(dash, inst, rt, rtAvail, side) {
  const isRt = side === 'rt';
  const trend = isRt ? (rtAvail ? rt.trend_strength : null) : dash.trend_strength;
  const chg = isRt ? (rtAvail ? rt.price_chg : null) : (dash.quote ? dash.quote.change : null);
  const rel = isRt ? (rtAvail ? rt.relative_strength : null) : dash.relative_strength;
  const mainNet = isRt ? (rtAvail ? rt.main_net : null) : (inst ? inst.main_net : null);

  const signals = [];
  if (trend != null && trend < 40) {
    signals.push({ type: 'bear', weight: -2, text: '技术破位（触发风控）' });
  } else if (trend != null && trend >= 60) {
    signals.push({ type: 'bull', weight: 1, text: '技术走强' });
  }
  if (chg != null && chg > 0) signals.push({ type: 'bull', weight: 1, text: '当日上涨' });
  if (rel != null && rel > 50) signals.push({ type: 'bull', weight: 1, text: '板块升温' });
  if (mainNet != null && mainNet > 0) signals.push({ type: 'bull', weight: 1, text: '资金流入' });

  const bear = signals.filter((s) => s.type === 'bear').reduce((a, s) => a + s.weight, 0);
  const bull = signals.filter((s) => s.type === 'bull').reduce((a, s) => a + s.weight, 0);
  const riskTriggered = signals.some((s) => s.type === 'bear' && s.weight <= -2);
  const bullTexts = signals.filter((s) => s.type === 'bull').map((s) => s.text);
  const bearTexts = signals.filter((s) => s.type === 'bear').map((s) => s.text);
  return { signals, bear, bull, riskTriggered, trend, bullTexts, bearTexts };
}

// 综合评级：基于多空分差给出 5 档评级
function grade(bear, bull, riskTriggered) {
  if (riskTriggered) return { label: '风控', color: '#ef4444', bg: 'rgba(239,68,68,0.15)' };
  const net = bull + bear; // bear 为负数
  if (net >= 3) return { label: '强烈看多', color: '#dc2626', bg: 'rgba(220,38,38,0.12)' };
  if (net >= 1) return { label: '偏多', color: '#ef4444', bg: 'rgba(239,68,68,0.08)' };
  if (net === 0) return { label: '中性', color: '#94a3b8', bg: 'rgba(148,163,184,0.08)' };
  if (net >= -1) return { label: '偏空', color: '#22c55e', bg: 'rgba(34,197,94,0.08)' };
  return { label: '看空', color: '#16a34a', bg: 'rgba(22,163,74,0.12)' };
}

function AiDiagnosisModule({ dash, inst, rt, rtAvail }) {
  const after = useMemo(() => dash ? synthesize(dash, inst, null, false, 'after') : null, [dash, inst]);
  const real = useMemo(() => (dash && rtAvail) ? synthesize(dash, inst, rt, true, 'rt') : null, [dash, inst, rt, rtAvail]);

  if (!dash) return null;

  // 多空维度上限（用于行1的 N/M 格式显示）
  // 多头维度上限 = 4（技术走强 + 当日上涨 + 板块升温 + 资金流入）
  // 空头维度上限 = 2（技术破位 weight=-2；其他维度暂未加空头）
  const BULL_MAX = 4;
  const BEAR_MAX = 2;

  // 渲染行1（结论标签 + 多空计数）— 合并到模块标题同一行
  const renderHeader = (syn, title, isRt) => {
    const g = syn ? grade(syn.bear, syn.bull, syn.riskTriggered) : null;
    const bullAbs = syn ? syn.bull : 0;
    const bearAbs = syn ? Math.abs(syn.bear) : 0;
    const net = syn ? (syn.bull + syn.bear) : 0;
    return (
      <div className="flex items-center justify-between gap-1 mb-0.5 min-h-[16px]">
        <span className="text-[9px] font-bold tracking-wider whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{title}</span>
        {syn ? (
          <div className="flex items-center gap-1.5 flex-shrink-0">
            <span
              className="text-[10px] px-1.5 py-0.5 rounded font-bold whitespace-nowrap"
              style={{ background: g.bg, color: g.color, border: `1px solid ${g.color}40` }}
              title={`多 ${bullAbs}/${BULL_MAX} · 空 ${bearAbs}/${BEAR_MAX}（bear 为负数，net=${net}）`}
            >
              {g.label}
            </span>
            <span className="text-[10px] tabular-nums whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>
              <span style={{ color: '#ef4444' }} className="font-bold">多{bullAbs}/{BULL_MAX}</span>
              <span style={{ color: 'var(--text-muted)' }}> · </span>
              <span style={{ color: '#22c55e' }} className="font-bold">空{bearAbs}/{BEAR_MAX}</span>
            </span>
          </div>
        ) : (
          <span className="text-[10px] italic" style={{ color: 'var(--text-muted)' }}>
            {isRt ? '实时暂无数据' : '盘后暂无数据'}
          </span>
        )}
      </div>
    );
  };

  // 渲染行2+行3（多头逻辑 + 空头风险）
  const renderBody = (syn) => (
    <>
      {/* 行2：多头逻辑 */}
      <div className="flex items-start gap-1 px-1 py-0.5 rounded min-h-[16px]" style={{ background: (syn && syn.bull > 0) ? 'rgba(239,68,68,0.06)' : 'transparent' }}>
        <span className="text-[9px] font-bold flex-shrink-0" style={{ color: (syn && syn.bull > 0) ? '#ef4444' : 'var(--text-muted)' }}>多</span>
        <span className="text-[10px] leading-snug" style={{ color: (syn && syn.bull > 0) ? 'var(--text-primary)' : 'var(--text-muted)' }}>
          {(syn && syn.bullTexts.length > 0) ? syn.bullTexts.join(' + ') : '无显著多头信号'}
        </span>
      </div>

      {/* 行3：空头风险 */}
      <div className="flex items-start gap-1 px-1 py-0.5 rounded min-h-[16px]" style={{ background: (syn && syn.bear < 0) ? 'rgba(34,197,94,0.06)' : 'transparent' }}>
        <span className="text-[9px] font-bold flex-shrink-0" style={{ color: (syn && syn.bear < 0) ? '#22c55e' : 'var(--text-muted)' }}>空</span>
        <span className="text-[10px] leading-snug" style={{ color: (syn && syn.bear < 0) ? 'var(--text-primary)' : 'var(--text-muted)' }}>
          {(syn && syn.bearTexts.length > 0) ? syn.bearTexts.join(' + ') : '无显著空头风险'}
        </span>
      </div>
    </>
  );

  return (
    <>
      {/* 全宽横条分隔（与其他模块统一：h-px + 同色 border-color） */}
      <div className="h-px w-full" style={{ backgroundColor: 'var(--border-color)' }} />
      <div className="px-2.5 py-1.5">
        <div className="flex items-stretch">
          {/* 左：盘后 */}
          <div className="flex-1 min-w-0 pr-2.5 flex flex-col gap-0.5">
            {renderHeader(after, '🤖 AI 联动诊断 · 盘后', false)}
            {renderBody(after)}
          </div>
          {/* 中间分割线 */}
          <div className="shrink-0" style={{ width: '1.5px', backgroundColor: 'rgba(148,163,184,0.35)', margin: '2px 0' }} />
          {/* 右：实时 */}
          <div className="flex-1 min-w-0 pl-2.5 flex flex-col gap-0.5">
            {renderHeader(real, '🟢 实时', true)}
            {renderBody(real)}
          </div>
        </div>
      </div>
    </>
  );
}

export default memo(AiDiagnosisModule);
