/**
 * 关键价位卡片 —— 11 类支撑/压力位（移植自 tickflow-stock-panel 设计）
 * 用法：<PriceLevelsCard market="a|us" symbol="600519|MSFT" />
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { apiFetch, formatApiError } from '../utils/request';

const TYPE_LABELS = {
  sr: '压力支撑', pivot: '枢轴点', extreme: '前高前低', boll: '布林带',
  keltner_s: 'Keltner短期', keltner_m: 'Keltner中期', keltner_l: 'Keltner长期',
  atr_stop: 'ATR通道', gap: '缺口位', fib: '斐波那契', round: '整数关口',
};

const COLORS = {
  resistance: 'var(--flow-up)',
  support: 'var(--flow-down)',
  neutral: 'var(--text-secondary)',
};

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));

/** 聚合 11 类价位 → 最近支撑/阻力 → 执行价位 + 风险回报比 */
function buildPlan(levels, close) {
  if (!levels || !close) return null;
  const all = Object.entries(levels).flatMap(([type, points]) =>
    (points || []).map((point) => ({ ...point, type: point.type || type })),
  ).filter((p) => p && Number(p.value) > 0);
  const strength = { strong: 3, medium: 2, weak: 1 };
  const nearest = (side, direction) => {
    const seen = new Set();
    return all
      .filter((point) => point.side === side)
      .sort((a, b) => direction * (Number(a.value) - Number(b.value)) || (strength[b.strength] || 0) - (strength[a.strength] || 0))
      .filter((point) => {
        const value = Math.round(Number(point.value) * 100) / 100;
        if (seen.has(value)) return false;
        seen.add(value);
        point.value = value;
        return side === 'resistance' ? value > close : value < close;
      });
  };
  const resist = nearest('resistance', 1);
  const support = nearest('support', -1);
  const r1Point = resist[0], r2Point = resist[1], s1Point = support[0], s2Point = support[1];
  const r1 = r1Point?.value, r2 = r2Point?.value, s1 = s1Point?.value, s2 = s2Point?.value;
  if (r1 == null || s1 == null) return null;
  const entryRisk = close - s1;
  const holdRisk = close - (s2 ?? s1);
  const reward = r1 - close;
  const entryRr = entryRisk > 0 ? reward / entryRisk : null;
  const holdRr = holdRisk > 0 ? reward / holdRisk : null;
  const ref = (point) => {
    if (!point) return '';
    const group = TYPE_LABELS[point.type] || point.type;
    return point.label.includes(group) ? point.label : `${group} · ${point.label}`;
  };
  return {
    r1, r2, s1, s2, entryRisk, holdRisk, reward, entryRr, holdRr,
    r1Ref: ref(r1Point), r2Ref: ref(r2Point), s1Ref: ref(s1Point), s2Ref: ref(s2Point),
  };
}

/** 数据库关键价位 + 当前持仓 → 规则化执行结论 */
function buildDecision(plan, close, positionCount = 0, signalContext = {}) {
  if (!plan || !close) return null;
  const held = Number(positionCount) > 0;
  const dS = ((close - plan.s1) / close) * 100;
  const dR = ((plan.r1 - close) / close) * 100;
  const stop = held ? (plan.s2 ?? plan.s1) : plan.s1;
  const riskPct = ((close - stop) / close) * 100;
  const rewardPct = ((plan.r1 - close) / close) * 100;
  const rr = held ? plan.holdRr : plan.entryRr;
  const nearSupport = dS <= 3;
  const nearResistance = dR <= 3;
  const rrStrong = rr != null && rr >= 1.5;
  const rrPoor = rr != null && rr < 1;

  const flowValues = [signalContext.flow1d, signalContext.flow3d, signalContext.flow5d]
    .map(Number)
    .filter(Number.isFinite);
  const flowWeak = flowValues.length >= 2 && flowValues.filter(value => value < 0).length >= 2;
  const doubleBear = signalContext.macd === '空头' && signalContext.kdj === '空头';
  const belowMa20 = Number.isFinite(Number(signalContext.closeVsMa20)) && Number(signalContext.closeVsMa20) < 0;
  const volumeRatio = Number(signalContext.volumeRatio);
  const lowVolume = Number.isFinite(volumeRatio) && volumeRatio < 0.8;
  const rsi = Number(signalContext.rsi);
  const rsiNeutral = Number.isFinite(rsi) && rsi > 30 && rsi < 70;
  const ma20Slope = Number(signalContext.ma20Slope);
  const ma20Flat = Number.isFinite(ma20Slope) && Math.abs(ma20Slope) <= 0.5;
  const kdjLow = (Number.isFinite(Number(signalContext.kdjK)) && Number(signalContext.kdjK) < 20)
    || (Number.isFinite(Number(signalContext.kdjJ)) && Number(signalContext.kdjJ) < 0);
  const overallWeak = signalContext.overallState === '偏弱' || String(signalContext.actionLabel || '').includes('减仓');
  const weakContext = overallWeak || (doubleBear && (belowMa20 || flowWeak)) || (belowMa20 && flowWeak);
  const reasons = [];
  if (doubleBear) reasons.push('MACD/KDJ同为空头');
  if (kdjLow && signalContext.kdj === '空头') reasons.push('KDJ处于低位但尚未形成金叉');
  if (belowMa20) reasons.push(`${ma20Flat ? 'MA20斜率走平，但' : ''}股价仍低于MA20 ${fmt(Math.abs(Number(signalContext.closeVsMa20)) * 100, 1)}%`);
  if (rsiNeutral) reasons.push(`RSI ${fmt(rsi, 1)}中性仅表示未到极值，不代表趋势转强`);
  if (lowVolume) reasons.push(`量比 ${fmt(volumeRatio, 2)}，成交偏弱`);
  if (flowWeak) reasons.push('1/3/5日资金以净流出为主');

  let action;
  let summary;
  let color;
  if (held && weakContext) {
    action = '持有，不加码；反弹减仓';
    summary = '趋势或资金仍弱，且当前持仓风险回报不占优，反弹优先降低仓位。';
    color = 'var(--accent-amber)';
  } else if (!held && weakContext) {
    action = '空仓观望，不追涨';
    summary = '技术趋势尚未转强，当前空仓不参与；仅价格突破不足以构成买点。';
    color = 'var(--accent-amber)';
  } else if (held && nearResistance && rrPoor) {
    action = '持有，不加码；逢高减仓';
    summary = '上方空间小于完整防守风险，反弹至压力区优先降低仓位。';
    color = 'var(--accent-amber)';
  } else if (held && nearSupport && rrStrong) {
    action = '持有，可小幅加码';
    summary = '现价靠近支撑且风险回报占优，可在支撑确认有效后分批加码。';
    color = 'var(--flow-up)';
  } else if (held && rrStrong) {
    action = '继续持有';
    summary = '尚未触发防守位，且上方空间相对下方风险占优。';
    color = 'var(--accent-blue)';
  } else if (held) {
    action = '持有，不加码';
    summary = '当前尚未破位，但风险回报不占优，维持原仓等待方向确认。';
    color = 'var(--accent-amber)';
  } else if (nearSupport && rrStrong) {
    action = '小仓试错';
    summary = '现价靠近支撑且风险回报占优，可等待支撑确认后小仓参与。';
    color = 'var(--flow-up)';
  } else if (!held && (nearResistance || rrPoor)) {
    action = '空仓观望，不追涨';
    summary = '当前试仓风险回报不占优，等待压力区被有效突破后重新评估。';
    color = 'var(--accent-amber)';
  } else {
    action = held ? '持有观察' : '继续空仓观察';
    summary = '现价处于支撑和阻力之间，暂未到达具有明确优势的执行位置。';
    color = 'var(--text-secondary)';
  }

  const defense = held
    ? plan.s2 != null
      ? `收盘跌破第一防守位 ${fmt(plan.s1)}（${plan.s1Ref}）先减仓；收盘跌破清仓线 ${fmt(plan.s2)}（${plan.s2Ref}）清仓。`
      : `收盘跌破防守位 ${fmt(plan.s1)}（${plan.s1Ref}）清仓。`
    : `当前空仓，不存在减仓或清仓动作；${fmt(plan.s1)}（${plan.s1Ref}）仅作为后续试仓的失效参考。`;
  const pressureZone = plan.r2 != null ? `${fmt(plan.r1)}—${fmt(plan.r2)}` : fmt(plan.r1);
  const offense = weakContext
    ? held
      ? `反弹至 ${pressureZone} 压力区优先减仓；只有放量收盘站上 ${fmt(plan.r2 ?? plan.r1)} 且技术或资金转强后，才重新评估加码。`
      : `当前不买；只有放量收盘站上 ${fmt(plan.r2 ?? plan.r1)}，并出现 MACD/KDJ 或 MA20 转强确认后，才重新评估试仓。`
    : `放量收盘突破第一阻力 ${fmt(plan.r1)}（${plan.r1Ref}）后再评估参与${plan.r2 != null ? `，第二确认位 ${fmt(plan.r2)}（${plan.r2Ref}）` : ''}。`;
  const rrLabel = held ? '持仓盈亏比' : '试仓盈亏比';
  const basis = `${held ? `按清仓线 ${fmt(stop)}` : `按第一防守位 ${fmt(stop)}`} 计算，下行风险 ${fmt(riskPct, 1)}%，至第一阻力上行空间 ${fmt(rewardPct, 1)}%${rr != null ? `，${rrLabel} 1:${fmt(rr, 1)}` : ''}。`;
  const signalBasis = reasons.length ? `${reasons.join('；')}。` : '趋势、量能与资金确认数据不足，本结论仅参考关键价位。';
  const short = held
    ? `不加码；${pressureZone} 压力区反弹减仓，收盘跌破 ${fmt(plan.s1)} 减仓、跌破 ${fmt(plan.s2 ?? plan.s1)} 清仓`
    : weakContext
      ? `当前不买；需放量站上 ${fmt(plan.r2 ?? plan.r1)} 并等待技术或资金转强`
      : `当前空仓观察；放量站上 ${fmt(plan.r1)} 后再评估`;
  return { action, summary, color, defense, offense, basis, signalBasis, held, rr, rrLabel, short };
}

export default function PriceLevelsCard({ market, symbol, dataStatus, dataAsOf, historyBars, minRequiredBars = 30, onPlanChange, compact = false, positionCount = 0, signalContext, currentPrice = null }) {
  const [data, setData] = useState(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [visible, setVisible] = useState(Object.fromEntries(Object.keys(TYPE_LABELS).map((k) => [k, true])));
  const [detailsOpen, setDetailsOpen] = useState(false);
  const timer = useRef(null);
  const requestSeq = useRef(0);
  const canLoad = dataStatus == null || dataStatus === 'READY';

  const load = useCallback(async () => {
    if (!symbol) return;
    if (!canLoad) {
      setData(null);
      setError(`数据库日K不足（${historyBars ?? 0}/${minRequiredBars} 根），关键价位暂不计算`);
      setLoading(false);
      return;
    }
    const seq = ++requestSeq.current;
    setLoading(true);
    try {
      const query = new URLSearchParams({ market, symbol });
      if (dataAsOf) query.set('as_of', dataAsOf);
      const res = await apiFetch(`/api/price-levels?${query.toString()}`, {}, 30000);
      if (seq !== requestSeq.current) return;
      if (res?.ok && res.data?.ok && res.data.data) {
        setData(res.data.data);
        setError('');
      } else {
        setError(formatApiError(res.data?.error ?? res?.error, '加载失败'));
      }
    } catch (e) {
      if (seq === requestSeq.current) setError(formatApiError(e, '加载失败'));
    } finally {
      if (seq === requestSeq.current) setLoading(false);
    }
  }, [canLoad, dataAsOf, historyBars, market, minRequiredBars, symbol]);

  useEffect(() => {
    requestSeq.current += 1;
    setData(null);
    setError('');
    load();
    if (canLoad) timer.current = setInterval(load, 300000);
    return () => {
      requestSeq.current += 1;
      clearInterval(timer.current);
    };
  }, [canLoad, load]);

  const toggle = (k) => setVisible((v) => ({ ...v, [k]: !v[k] }));

  // 价位库按最近收盘日生成，但盘中执行距离必须用数据库中的当前报价重算。
  // 否则当日大幅跳空后，页面会展示实时价，却仍给出上一日收盘价的进出场结论。
  const referencePrice = Number(currentPrice) > 0 ? Number(currentPrice) : data?.close;
  const plan = useMemo(() => buildPlan(data?.levels, referencePrice), [data?.levels, referencePrice]);
  const decision = useMemo(() => buildDecision(plan, referencePrice, positionCount, signalContext), [plan, positionCount, referencePrice, signalContext]);

  useEffect(() => {
    onPlanChange?.(plan ? {
      ...plan,
      rr: decision?.rr ?? null,
      rrLabel: decision?.rrLabel,
      close: referencePrice ?? null,
      levelClose: data?.close ?? null,
      dataAsOf: data?.data_as_of ?? null,
      decision,
    } : null);
  }, [data?.data_as_of, data?.close, decision, onPlanChange, plan, referencePrice]);

  useEffect(() => {
    setDetailsOpen(false);
  }, [compact, symbol]);

  const showDetails = !compact || detailsOpen;

  if (loading && !data) {
    return (
      <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 10, padding: compact ? 10 : 14 }}>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>关键价位加载中…</div>
      </div>
    );
  }

  return (
    <div style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', borderRadius: 10, padding: compact ? 10 : 14 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{compact ? '关键价位明细' : '关键价位'}</span>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          {data && !compact && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>数据库 · {data.n_days} 根 · 截至 {data.data_as_of} · 收盘 {data.close}{referencePrice != null && Number(referencePrice) !== Number(data.close) ? ` · 当前参考 ${fmt(referencePrice)}` : ''}</span>}
          <button
            onClick={load}
            disabled={loading || !canLoad}
            style={{ fontSize: 11, color: 'var(--accent-blue)', background: 'transparent', border: 'none', cursor: 'pointer', padding: 2 }}
          >
            {loading ? '刷新中…' : '↻ 刷新'}
          </button>
        </div>
      </div>

      {data && compact && (
        <>
          <div style={{ marginTop: -4, marginBottom: 8, fontSize: 10, color: 'var(--text-muted)' }}>
            数据库 · {data.n_days} 根 · 截至 {data.data_as_of} · 收盘 {data.close}{referencePrice != null && Number(referencePrice) !== Number(data.close) ? ` · 当前参考 ${fmt(referencePrice)}` : ''}
          </div>
          <button
            type="button"
            onClick={() => setDetailsOpen(open => !open)}
            style={{
              width: '100%', marginBottom: detailsOpen ? 8 : 0, padding: '5px 8px', borderRadius: 8,
              border: '1px solid var(--border-color)', cursor: 'pointer', fontSize: 10, fontWeight: 600,
              color: 'var(--accent-blue)', background: 'var(--bg-hover)',
            }}
          >
            {detailsOpen ? '收起 11 类价位明细' : '展开全部 11 类价位'}
          </button>
        </>
      )}

      {error && <div style={{ fontSize: 12, color: 'var(--accent-red)' }}>{error}</div>}

      {data && decision && !compact && (
        <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, border: '1px solid var(--border-color)', background: 'var(--bg-hover)' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>系统指导 · 数据库价位规则推导</span>
            <span style={{ fontSize: 14, fontWeight: 700, color: decision.color }}>{decision.action}</span>
            <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--text-muted)' }}>{decision.held ? `当前持仓 ${positionCount} 股` : '当前空仓'}</span>
          </div>
          <div style={{ marginTop: 3, fontSize: 11, fontWeight: 500, color: 'var(--text-primary)' }}>{decision.summary}</div>
          <div style={{ marginTop: 5, display: 'grid', gap: 2, fontSize: 10, lineHeight: 1.45, color: 'var(--text-secondary)' }}>
            <div><b style={{ color: 'var(--text-primary)' }}>防守：</b>{decision.defense}</div>
            <div><b style={{ color: 'var(--text-primary)' }}>进攻：</b>{decision.offense}</div>
            <div><b style={{ color: 'var(--text-primary)' }}>价位依据：</b>{decision.basis}</div>
            <div><b style={{ color: 'var(--text-primary)' }}>指标依据：</b>{decision.signalBasis}</div>
          </div>
        </div>
      )}

      {/* 类型开关 */}
      {showDetails && !compact && <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
        {Object.entries(TYPE_LABELS).map(([k, label]) => (
          <button
            key={k}
            onClick={() => toggle(k)}
            style={{
              fontSize: 10, padding: '2px 7px', borderRadius: 8, cursor: 'pointer',
              border: `1px solid ${visible[k] ? 'var(--accent-blue)' : 'var(--border-color)'}`,
              color: visible[k] ? 'var(--accent-blue)' : 'var(--text-muted)',
              background: visible[k] ? 'var(--bg-hover)' : 'transparent',
            }}
          >
            {label}
          </button>
        ))}
      </div>}

      {/* 价位列表 */}
      {data && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {showDetails && Object.entries(data.levels).map(([type, pts]) => {
            if (!visible[type] || !pts?.length) return null;
            const sorted = [...pts].sort((a, b) => a.value - b.value);
            return (
              <div key={type} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 11 }}>
                <span style={{ width: 62, flexShrink: 0, color: 'var(--text-muted)' }}>{TYPE_LABELS[type]}</span>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, flex: 1 }}>
                  {sorted.map((p, i) => (
                    <span
                      key={`${type}-${i}`}
                      title={p.label}
                      style={{
                        padding: '1px 6px', borderRadius: 6, whiteSpace: 'nowrap',
                        background: 'var(--bg-hover)', border: '1px solid var(--border-light)',
                        color: COLORS[p.side] || 'var(--text-secondary)',
                        fontWeight: p.strength === 'strong' ? 600 : 400,
                      }}
                    >
                      {p.label.replace(/^\S+\s/, '')} {p.value}
                    </span>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
