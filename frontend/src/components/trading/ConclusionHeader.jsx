// 结论统领区：单一信源的 AI 联动诊断（盘后 ‖ 实时），置于卡片最顶部镇场子。
// 数据全部来自 dash（与卡片其余模块同源）；盘后 verdict 取自 signal.signalLabel。
// 原 AiDiagnosisModule 的 synthesize 逻辑上移至此，避免卡片内出现两份 AI 诊断。

// 规则化合成：盘后 / 实时 双口径，输出 空多 tally + 加权信号
function synthesize(dash, inst, rt, rtAvail, side) {
  const isRt = side === 'rt';
  const trend = isRt ? (rtAvail ? rt.trend_strength : null) : dash.trend_strength;
  const chg = isRt ? (rtAvail ? rt.price_chg : null) : (dash.quote ? dash.quote.change : null);
  const rel = isRt ? (rtAvail ? rt.relative_strength : null) : dash.relative_strength;
  const mainNet = isRt ? (rtAvail ? rt.main_net : null) : (inst ? inst.main_net : null);

  const signals = [];
  // 技术破位（风控核心，权重 -2）
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
  return { signals, bear, bull, riskTriggered, trend };
}

// 盘后 verdict 标签 → 配色（红=破位/减仓，绿=建仓/锁仓，其余琥珀）
function verdictColor(label) {
  if (!label) return '#64748b';
  if (label.includes('破位') || label.includes('减仓') || label.includes('清仓') || label.includes('暂避') || label.includes('防守')) return '#ef4444';
  if (label.includes('建仓') || label.includes('强仓') || label.includes('锁仓') || label.includes('持有') || label.includes('买入')) return '#22c55e';
  return '#eab308';
}

export default function ConclusionHeader({ signal, dash }) {
  const rt = dash?.realtime || {};
  const rtAvail = !!rt.available;
  const inst = dash?.institution_flow || null;

  const after = dash ? synthesize(dash, inst, null, false, 'after') : null;
  const real = (dash && rtAvail) ? synthesize(dash, inst, rt, true, 'rt') : null;

  const signalLabel = signal?.signalLabel || signal?.label || '--';

  // —— 盘后结论 ——
  const afterRisk = after?.riskTriggered;
  const afterBear = after ? Math.abs(after.bear) : 0;
  const afterBull = after ? after.bull : 0;
  const afterColor = verdictColor(signalLabel);
  const techText = !after
    ? '技术面：盘后仪表盘不可用'
    : after.riskTriggered
      ? '技术面：破位，必须减仓'
      : (dash.trend_strength ?? 0) >= 60
        ? '技术面：走强，趋势健康'
        : '技术面：中性，未见破位';

  // —— 实时结论 ——
  const realBear = real ? Math.abs(real.bear) : 0;
  const realBull = real ? real.bull : 0;
  const realBullTexts = real ? real.signals.filter((s) => s.type === 'bull').map((s) => s.text) : [];
  const realLogic = realBullTexts.length ? realBullTexts.join(' + ') : '暂无显著信号';
  const realColor = !real
    ? '#64748b'
    : realBull > realBear
      ? '#22c55e'
      : realBear >= realBull
        ? '#ef4444'
        : '#eab308';
  const caution = dash && rtAvail && rt.mode === 'live'
    ? '注意：仍需谨防午后冲高回落'
    : dash && rtAvail
      ? '注意：实时已定格，以盘后结论为准'
      : '注意：非交易时段，实时暂无';

  return (
    <div
      className="px-3 py-2"
      style={{ background: 'linear-gradient(180deg, rgba(168,85,247,0.07), rgba(168,85,247,0.02))', borderBottom: '1.5px solid var(--border-color)' }}
    >
      <div className="flex items-center gap-1.5 mb-1.5">
        <span className="text-[11px] font-bold" style={{ color: 'var(--text-primary)' }}>结论统领区</span>
        <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.14)', color: '#a855f7' }}>AI 联动诊断 · 单一信源</span>
      </div>
      <div className="flex items-stretch">
        {/* 左：盘后结论 */}
        <div className="flex-1 pr-3">
          <div className="text-[9px] font-medium mb-1" style={{ color: 'var(--text-tertiary)' }}>盘后结论</div>
          <div className="mb-1.5">
            <span
              className="text-[13px] font-bold px-2 py-1 rounded-md"
              style={{ background: `${afterColor}1A`, color: afterColor, border: `1px solid ${afterColor}40` }}
            >{signalLabel}</span>
          </div>
          <div className="text-[10px] leading-snug" style={{ color: 'var(--text-secondary)' }}>
            AI联动诊断：<b style={{ color: afterRisk ? '#ef4444' : '#64748b' }}>{afterRisk ? '风险控制' : '防守'}</b>{' '}
            <span style={{ color: '#ef4444' }}>空{afterBear}</span> + <span style={{ color: '#22c55e' }}>多{afterBull}</span>
          </div>
          <div className="text-[10px] leading-snug mt-0.5" style={{ color: afterRisk ? '#dc2626' : 'var(--text-muted)' }}>{techText}</div>
        </div>
        {/* 中间分割线 */}
        <div className="shrink-0" style={{ borderLeft: '1.5px solid var(--border-color)' }} />
        {/* 右：实时结论 */}
        <div className="flex-1 pl-3">
          <div className="text-[9px] font-medium mb-1" style={{ color: 'var(--text-tertiary)' }}>实时结论</div>
          <div className="mb-1.5">
            <span
              className="text-[13px] font-bold px-2 py-1 rounded-md"
              style={{ background: `${realColor}1A`, color: realColor, border: `1px solid ${realColor}40` }}
            >
              {real ? `实时：空${realBear} + 多${realBull}` : '实时：暂无'}
            </span>
          </div>
          <div className="text-[10px] leading-snug" style={{ color: 'var(--text-secondary)' }}>
            实时逻辑：{realLogic}
          </div>
          <div className="text-[10px] leading-snug mt-0.5" style={{ color: '#f97316' }}>{caution}</div>
        </div>
      </div>
    </div>
  );
}
