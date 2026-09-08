import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch, formatApiError } from '../utils/request';
import { simplifyUSName, usNameCN } from '../utils/usStockNames';

const C = {
  card: 'var(--bg-card)',
  surface: 'var(--bg-surface)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  text: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  blue: 'var(--accent-blue)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  amber: 'var(--accent-amber)',
};

const REGIME_LABELS = {
  STRONG_BREADTH: '强势普涨',
  LEADER_CONCENTRATION: '龙头集中',
  HIGH_LEVEL_RANGE: '高位震荡',
  WEAK_REBOUND: '弱势反弹',
  RISK_OFF: '风险回避',
};

const number = (value) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
};

const pct = (value, digits = 2) => {
  const parsed = number(value);
  if (parsed == null) return '—';
  return `${parsed > 0 ? '+' : ''}${parsed.toFixed(digits)}%`;
};

const pctColor = (value) => {
  const parsed = number(value);
  if (parsed == null || parsed === 0) return C.muted;
  return parsed > 0 ? C.up : C.down;
};

const price = (value) => {
  const parsed = number(value);
  return parsed == null ? '—' : `$${parsed.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`;
};

const stockName = (item) => usNameCN(item?.symbol) || simplifyUSName(item?.name) || item?.name || item?.symbol || '—';

const quoteTime = (value) => {
  if (!value) return '—';
  const text = String(value);
  return text.includes(' ') ? text.slice(text.indexOf(' ') + 1) : text;
};

function executionStatus({ kind, quote, marketState, holding }) {
  if (holding) {
    return { label: '已有持仓，管理仓位', reason: '不重复新开仓，转持仓管理', color: C.blue };
  }
  const liveChange = number(quote?.chg_pct);
  if (marketState !== '允许开仓') {
    return { label: '暂缓开仓', reason: `${marketState}，不新开仓`, color: C.amber };
  }
  if (!quote || number(quote.price) == null || liveChange == null) {
    return { label: '行情异常', reason: '未收到有效实时价', color: C.amber };
  }
  if (liveChange >= 3) {
    return { label: '涨幅过大，不追', reason: `实时 ${pct(liveChange)}`, color: C.down };
  }
  if (liveChange <= -3) {
    return { label: '跌幅偏大，等待确认', reason: `实时 ${pct(liveChange)}`, color: C.amber };
  }
  if (liveChange >= 1.5) {
    return { label: '等待回踩', reason: `实时 ${pct(liveChange)}`, color: C.amber };
  }
  if (kind !== 'buy') {
    return { label: '等待触发', reason: '盘后尚未触发', color: C.amber };
  }
  return { label: '盘中可执行', reason: '盘后已触发，波动正常', color: C.up };
}

function changeColor(kind) {
  if (kind === 'new' || kind === 'upgraded') return C.up;
  if (kind === 'strengthened') return C.blue;
  return C.muted;
}

function selectionHistory(item) {
  const history = item?.selection_history;
  const consecutive = number(history?.consecutive_days);
  const selected = number(history?.selected_in_recent_scans);
  const window = number(history?.recent_scan_days);
  if (consecutive == null || consecutive < 1) {
    return { label: '连续记录待补', note: '缺少已落库快照' };
  }
  return {
    label: consecutive === 1 ? '新入选' : `连选 ${consecutive} 日`,
    note: selected != null && window != null ? `近 ${window} 个快照入选 ${selected} 次` : '已落库盘后快照',
  };
}

function sectorSignal(sector, realtime) {
  const score = number(sector?.total_score);
  const intraday = number(realtime?.change_pct);
  if (score == null || intraday == null) {
    return { label: '数据待齐', note: '因子或实时行情未返回', color: C.muted };
  }
  if (score >= 70 && intraday <= -0.3) {
    return { label: '强势回调', note: '盘后因子强、当日走弱，观察承接', color: C.amber };
  }
  if (score <= 45 && intraday >= 1) {
    return { label: '弱势反弹，不追', note: '因子偏弱、当日快速上涨', color: C.down };
  }
  if (score >= 70 && intraday >= 0.15) {
    return { label: '趋势共振', note: '盘后因子与当日表现同向', color: C.up };
  }
  if (score <= 45 && intraday <= -0.3) {
    return { label: '弱势回避', note: '因子与当日表现均偏弱', color: C.down };
  }
  return { label: '等待确认', note: '暂无明确共振或背离', color: C.muted };
}

function Card({ children, style }) {
  return (
    <section style={{
      background: C.card, border: `1px solid ${C.border}`, borderRadius: 12,
      minWidth: 0, ...style,
    }}>
      {children}
    </section>
  );
}

function SectionHeader({ icon, title, note, action }) {
  return (
    <header style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8,
      padding: '11px 12px 9px', borderBottom: `1px solid ${C.borderLight}`,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 15 }}>{icon}</span>
          <h2 style={{ margin: 0, color: C.text, fontSize: 14, fontWeight: 800 }}>{title}</h2>
        </div>
        {note && <div style={{ marginTop: 3, color: C.muted, fontSize: 10.5 }}>{note}</div>}
      </div>
      {action}
    </header>
  );
}

function Metric({ label, value, note, color, loading }) {
  return (
    <Card style={{ padding: '10px 12px' }}>
      <div style={{ color: C.muted, fontSize: 11 }}>{label}</div>
      <div style={{ marginTop: 4, color: color || C.text, fontSize: 21, fontWeight: 800, lineHeight: 1.15 }}>
        {loading ? '···' : value}
      </div>
      <div style={{ marginTop: 4, minHeight: 14, color: C.secondary, fontSize: 10.5 }}>{note}</div>
    </Card>
  );
}

function Badge({ children, color = C.blue, background }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', whiteSpace: 'nowrap',
      padding: '2px 6px', borderRadius: 6, border: `1px solid ${color}45`,
      background: background || `${color}14`, color, fontSize: 10, fontWeight: 700,
    }}>
      {children}
    </span>
  );
}

function Empty({ children }) {
  return <div style={{ padding: '22px 10px', color: C.muted, textAlign: 'center', fontSize: 12 }}>{children}</div>;
}

function CandidateRow({ item, kind, quote, marketState, isWatchlisted, holding, onOpen }) {
  const isBuy = kind === 'buy';
  const accent = isBuy ? C.up : C.amber;
  const livePct = quote?.chg_pct;
  const liveLabel = quote ? pct(livePct) : '行情未返回';
  const execution = executionStatus({ kind, quote, marketState, holding });
  const history = selectionHistory(item);
  const selectionChange = item?.selection_change;
  const portfolioRisk = item?.portfolio_risk;
  const related = portfolioRisk?.correlated_symbols || [];
  const changeLabel = selectionChange?.label === history.label ? selectionChange?.detail : selectionChange?.label;

  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'minmax(145px, 1.35fr) minmax(105px, 1fr) minmax(88px, .8fr) minmax(112px, .85fr)',
      gap: 8, alignItems: 'center', padding: '9px 12px', borderTop: `1px solid ${C.borderLight}`,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 0 }}>
          <span style={{ color: C.text, fontSize: 13, fontWeight: 800 }}>{item.symbol}</span>
          <Badge color={accent}>{isBuy ? '盘后触发' : '盘后候选'}</Badge>
        </div>
        <div title={stockName(item)} style={{ marginTop: 3, color: C.secondary, fontSize: 10.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {stockName(item)}
        </div>
        <div title={`${history.note}；${selectionChange?.detail || '本轮状态'}；${isWatchlisted ? '已在自选' : '未在自选'}；${holding ? `持仓中${number(holding.quantity) != null ? ` ${holding.quantity} 股` : ''}` : '未持仓'}`} style={{ marginTop: 3, color: C.muted, fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {history.label} · <span style={{ color: changeColor(selectionChange?.kind), fontWeight: 700 }}>{changeLabel || '本轮入选'}</span> · {isWatchlisted ? '已自选' : '自选外'} · {holding ? '持仓中' : '未持仓'}
        </div>
      </div>
      <div>
        <div style={{ color: C.muted, fontSize: 10 }}>盘后因子 / 共振</div>
        <div style={{ marginTop: 3, color: C.text, fontSize: 11.5, fontWeight: 700 }}>
          {number(item.factor_score)?.toFixed(1) || '—'} 分 · {item.resonance_count || 0} 维
        </div>
      </div>
      <div>
        <div style={{ color: C.muted, fontSize: 10 }}>实时验证</div>
        <div style={{ marginTop: 3, color: pctColor(livePct), fontSize: 12, fontWeight: 800 }}>{liveLabel}</div>
        <div style={{ marginTop: 2, color: C.muted, fontSize: 10 }}>{quote ? price(quote.price) : price(item.price)}</div>
        {related.length > 0 && <div title={`与 ${related.map((entry) => `${entry.symbol} ${(Number(entry.correlation) * 100).toFixed(0)}%`).join('、')} 高相关`} style={{ marginTop: 2, color: C.amber, fontSize: 9.5 }}>相关组 {portfolioRisk.group_size} 只</div>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 5, minWidth: 0 }}>
        <Badge color={execution.color}>{execution.label}</Badge>
        <span title={execution.reason} style={{ maxWidth: 130, color: C.muted, fontSize: 9.5, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{execution.reason}</span>
        <button
          type="button"
          onClick={() => onOpen(item.symbol)}
          style={{ border: `1px solid ${C.blue}55`, borderRadius: 6, padding: '3px 7px', background: 'transparent', color: C.blue, cursor: 'pointer', fontSize: 10.5, fontWeight: 700 }}
        >
          个股分析
        </button>
      </div>
    </div>
  );
}

function SectorRow({ sector, realtime }) {
  const intraday = realtime?.change_pct;
  const momentum = realtime?.ret_20d ?? sector.ret_20d;
  const signal = sectorSignal(sector, realtime);
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: 'minmax(105px, 1fr) 52px 68px 68px', gap: 6,
      alignItems: 'center', padding: '7px 0', borderTop: `1px solid ${C.borderLight}`,
    }}>
      <div style={{ minWidth: 0 }}>
        <div style={{ color: C.text, fontSize: 12, fontWeight: 700 }}>{sector.etf_name || sector.name}</div>
        <div title={signal.note} style={{ marginTop: 2, color: C.muted, fontSize: 10 }}>
          {sector.etf_symbol || sector.etf} · <span style={{ color: signal.color, fontWeight: 700 }}>{signal.label}</span>
        </div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: C.muted, fontSize: 9.5 }}>因子</div>
        <div style={{ color: C.text, fontSize: 11.5, fontWeight: 800 }}>{number(sector.total_score)?.toFixed(1) || '—'}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: C.muted, fontSize: 9.5 }}>当日</div>
        <div style={{ color: pctColor(intraday), fontSize: 11.5, fontWeight: 800 }}>{pct(intraday)}</div>
      </div>
      <div style={{ textAlign: 'right' }}>
        <div style={{ color: C.muted, fontSize: 9.5 }}>20 日</div>
        <div style={{ color: pctColor(momentum), fontSize: 11.5, fontWeight: 800 }}>{pct(momentum)}</div>
      </div>
    </div>
  );
}

function MoverRow({ item, onOpen }) {
  const change = item?.chg_pct;
  return (
    <button
      type="button"
      onClick={() => onOpen(item.symbol)}
      style={{
        width: '100%', display: 'grid', gridTemplateColumns: 'minmax(90px, 1fr) 70px 58px', gap: 6,
        alignItems: 'center', padding: '7px 0', border: 'none', borderTop: `1px solid ${C.borderLight}`,
        background: 'transparent', cursor: 'pointer', textAlign: 'left',
      }}
    >
      <span style={{ minWidth: 0 }}>
        <span style={{ color: C.text, fontSize: 12, fontWeight: 700 }}>{item.symbol}</span>
        <span style={{ marginLeft: 5, color: C.muted, fontSize: 10 }}>{usNameCN(item.symbol) || ''}</span>
      </span>
      <span style={{ color: C.secondary, fontSize: 11, textAlign: 'right' }}>{price(item.price)}</span>
      <span style={{ color: pctColor(change), fontSize: 12, fontWeight: 800, textAlign: 'right' }}>{pct(change)}</span>
    </button>
  );
}

function ChangeSummary({ changes }) {
  const dropped = changes?.dropped || [];
  if (!changes?.available) {
    return (
      <Card style={{ marginBottom: 10, padding: '9px 12px' }}>
        <span style={{ color: C.muted, fontSize: 11 }}>本轮变化：等待上一份已落库盘后快照后再比较，不补造昨日变化。</span>
      </Card>
    );
  }
  return (
    <Card style={{ marginBottom: 10, padding: '9px 12px', display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 7 }}>
      <span style={{ color: C.secondary, fontSize: 11, fontWeight: 800 }}>本轮变化</span>
      <span style={{ color: C.muted, fontSize: 10.5 }}>对比 {changes.baseline_trade_date || '上一盘后'}</span>
      <Badge color={C.up}>新入选 {changes.new_count || 0}</Badge>
      <Badge color={C.up}>观察→触发 {changes.upgraded_count || 0}</Badge>
      <Badge color={C.blue}>信号增强 {changes.strengthened_count || 0}</Badge>
      {dropped.length > 0 && <span title={dropped.map((item) => item.symbol).join('、')} style={{ color: C.muted, fontSize: 10.5 }}>移出 {dropped.length}：{dropped.map((item) => item.symbol).join('、')}</span>}
    </Card>
  );
}

function PortfolioGuardCard({ guard }) {
  const groups = guard?.groups || [];
  const policy = guard?.policy || {};
  return (
    <Card>
      <SectionHeader icon="🧩" title="组合防护" note="只用已入库日线计算 20 日收益相关性；提示不触发自动下单" />
      <div style={{ padding: '10px 12px' }}>
        {!guard?.available ? (
          <div style={{ color: C.muted, fontSize: 11 }}>{guard?.error || '相关性历史待补齐'}</div>
        ) : (
          <>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              <Badge color={C.blue}>已同步持仓 {guard.active_positions || 0} 只</Badge>
              <Badge color={C.secondary}>建议新开 ≤ {policy.max_new_positions || '—'} 只</Badge>
              <Badge color={C.amber}>同相关组 ≤ {policy.max_correlated_new_positions || '—'} 只</Badge>
            </div>
            <div style={{ marginTop: 9, color: C.muted, fontSize: 10.5 }}>
              {groups.length ? `发现 ${groups.length} 组高相关候选：` : '当前候选未发现达到阈值的高相关组合。'}
            </div>
            {groups.slice(0, 3).map((group) => (
              <div key={group.symbols.join('-')} style={{ marginTop: 6, padding: '6px 7px', borderRadius: 7, background: C.surface, color: C.secondary, fontSize: 10.5 }}>
                <b style={{ color: C.text }}>{group.symbols.join(' × ')}</b>
                <span style={{ marginLeft: 6 }}>20 日相关 {(Number(group.average_correlation) * 100).toFixed(0)}%</span>
              </div>
            ))}
          </>
        )}
      </div>
    </Card>
  );
}

function ReviewCard({ review }) {
  const horizons = review?.horizons || [];
  return (
    <Card>
      <SectionHeader icon="📈" title="策略复盘" note="历史盘后触发的已成熟样本；仅复盘，不参与当日评分或自动下单" />
      <div style={{ padding: '10px 12px' }}>
        {!review?.available ? (
          <div style={{ color: C.muted, fontSize: 11 }}>{review?.reason || '等待历史结果补齐'}</div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(92px, 1fr))', gap: 6 }}>
            {horizons.map((item) => (
              <div key={item.days} style={{ padding: '7px', borderRadius: 7, background: C.surface }}>
                <div style={{ color: C.muted, fontSize: 9.5 }}>{item.days} 日 · {item.count} 样本</div>
                <div style={{ marginTop: 3, color: C.text, fontSize: 11.5, fontWeight: 800 }}>胜率 {number(item.win_rate)?.toFixed(1) || '—'}%</div>
                <div style={{ marginTop: 2, color: pctColor(item.average_return), fontSize: 10.5 }}>均收益 {pct(item.average_return)}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}

export default function USDailyDecisionPage() {
  const navigate = useNavigate();
  const [data, setData] = useState({ overview: null, market: null, premarket: null });
  const [loading, setLoading] = useState(true);
  const [errors, setErrors] = useState([]);
  const [loadedAt, setLoadedAt] = useState('');
  const [decisionAlerts, setDecisionAlerts] = useState([]);
  const loadingRef = useRef(false);
  const alertBaselineRef = useRef(null);

  const load = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    setLoading(true);
    setErrors([]);
    try {
      // 候选实时价只依赖盘后决策结果；不等待市场资讯接口，缩短首屏行动清单的等待时间。
      const overviewPromise = apiFetch('/api/us-quant/overview', {}, 30000, 0);
      // 市场资讯是辅助判断；超时后保留上次成功数据，不能拖住盘后执行清单。
      const marketPromise = apiFetch('/api/market-dashboard/overview', {}, 9000, 0);
      const watchlistPromise = apiFetch('/api/us-stock-analysis/watchlist', {}, 15000, 0);
      const positionsPromise = apiFetch('/api/usmart-sync/positions', {}, 15000, 0);
      const overviewRes = await overviewPromise;
      const overviewReady = overviewRes.ok && overviewRes.data && overviewRes.data.ok !== false;
      if (overviewReady) {
        // 盘后清单是用户的主要动作入口。市场资讯较慢时先展示它，
        // 后续数据返回后再合并，不把首屏卡在外部行情接口上。
        setData((current) => ({ ...current, overview: overviewRes.data }));
        setLoadedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
      }
      const decision = overviewRes.ok ? overviewRes.data?.decision : null;
      const candidateSymbols = [...(decision?.buyable || []), ...(decision?.watch || [])]
        .map((item) => item.symbol)
        .filter(Boolean);
      const query = candidateSymbols.length ? `?symbols=${encodeURIComponent(candidateSymbols.join(','))}` : '';
      const [marketRes, premarketRes, watchlistRes, positionsRes] = await Promise.all([
        marketPromise,
        apiFetch(`/api/us-stock-analysis/premarket${query}`, {}, 12000, 0),
        watchlistPromise,
        positionsPromise,
      ]);
      const results = [
        { key: 'market', res: marketRes },
        { key: 'premarket', res: premarketRes },
        { key: 'watchlist', res: watchlistRes },
        { key: 'positions', res: positionsRes },
      ];

      const next = {};
      const messages = [];
      if (!overviewReady) {
        messages.push(`盘后决策：${formatApiError(overviewRes.error || overviewRes.data?.message, '暂不可用')}`);
      }
      for (const { key, res } of results) {
        if (res.ok && res.data && res.data.ok !== false) next[key] = res.data;
        else {
          const label = {
            market: '市场脉搏', premarket: '实时行情',
            watchlist: '自选状态', positions: '持仓状态',
          }[key] || key;
          messages.push(`${label}：${formatApiError(res.error || res.data?.message, '暂不可用')}`);
        }
      }
      if (Object.keys(next).length) setData((current) => ({ ...current, ...next }));
      setErrors(messages);
      setLoadedAt(new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }));
    } catch (error) {
      setErrors([`每日决策：${formatApiError(error, '读取失败')}`]);
    } finally {
      loadingRef.current = false;
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  const overview = data.overview;
  const market = data.market;
  const premarket = data.premarket;
  const decision = overview?.decision || {};
  const regime = overview?.regime || {};
  const buyable = useMemo(() => decision.buyable || [], [decision.buyable]);
  const watch = useMemo(() => decision.watch || [], [decision.watch]);
  const gateValue = decision?.market_gate?.allow_new_positions ?? regime?.allow_new_positions;
  const marketAllowed = gateValue === true;
  const marketState = gateValue === true ? '允许开仓' : gateValue === false ? '暂缓开仓' : '待判定';
  const quality = decision.data_quality || overview?.data_quality;
  const qualityGood = quality?.status === 'VALID';
  const session = premarket?.session || '实时';
  const liveQuoteUpdatedAt = premarket?.sgt_time;
  const openStock = (symbol) => navigate(`/us-stock-analysis?symbol=${encodeURIComponent(symbol)}`);

  const quoteBySymbol = useMemo(() => new Map((premarket?.stocks || []).map((item) => [item.symbol, item])), [premarket?.stocks]);
  const watchlistSymbols = useMemo(() => new Set((data.watchlist?.symbols || []).map((symbol) => String(symbol).toUpperCase())), [data.watchlist?.symbols]);
  const holdingsBySymbol = useMemo(() => new Map((data.positions?.positions || [])
    .filter((item) => item?.symbol)
    .map((item) => [String(item.symbol).toUpperCase(), item])), [data.positions?.positions]);
  const realtimeSectors = useMemo(() => new Map((market?.sectors || []).map((item) => [item.etf, item])), [market?.sectors]);
  const industryRows = useMemo(() => (overview?.sectors || []).slice(0, 5), [overview?.sectors]);
  const indices = useMemo(() => (market?.indices || []).slice(0, 3), [market?.indices]);
  const movers = useMemo(() => [...(premarket?.stocks || [])]
    .filter((item) => number(item.chg_pct) != null)
    .sort((a, b) => Math.abs(number(b.chg_pct) || 0) - Math.abs(number(a.chg_pct) || 0))
    .slice(0, 6), [premarket?.stocks]);
  const marketEtfs = useMemo(() => (premarket?.market || []).slice(0, 4), [premarket?.market]);
  const news = useMemo(() => (market?.news || []).slice(0, 3), [market?.news]);
  const candidateExecutionStates = useMemo(() => [...buyable.map((item) => ({ item, kind: 'buy' })), ...watch.map((item) => ({ item, kind: 'watch' }))]
    .map(({ item, kind }) => {
      const symbol = String(item.symbol || '').toUpperCase();
      return {
        symbol,
        label: executionStatus({
          kind,
          quote: quoteBySymbol.get(symbol),
          marketState,
          holding: holdingsBySymbol.get(symbol),
        }).label,
      };
    })
    .filter((item) => item.symbol), [buyable, holdingsBySymbol, marketState, quoteBySymbol, watch]);

  useEffect(() => {
    if (!decision.trade_date || !premarket?.stocks) return;
    const key = `us-daily-decision-status:${decision.trade_date}`;
    const current = Object.fromEntries(candidateExecutionStates.map((item) => [item.symbol, item.label]));
    let previous = alertBaselineRef.current;
    if (!previous) {
      try {
        previous = JSON.parse(window.sessionStorage.getItem(key) || '{}');
      } catch {
        previous = {};
      }
      if (!Object.keys(previous).length) {
        alertBaselineRef.current = current;
        window.sessionStorage.setItem(key, JSON.stringify(current));
        return;
      }
    }
    const changed = candidateExecutionStates
      .filter((item) => previous[item.symbol] && previous[item.symbol] !== item.label)
      .map((item) => ({ symbol: item.symbol, previous: previous[item.symbol], label: item.label }))
      .slice(0, 5);
    if (changed.length) setDecisionAlerts(changed);
    changed.forEach((item) => {
      const status = item.label === '盘中可执行' ? 'success' : item.label.includes('不追') || item.label === '暂缓开仓' ? 'error' : 'submitting';
      window.dispatchEvent(new CustomEvent('airobot:decision-alert', {
        detail: { ...item, status, message: `${item.previous} → ${item.label}` },
      }));
    });
    alertBaselineRef.current = current;
    window.sessionStorage.setItem(key, JSON.stringify(current));
  }, [candidateExecutionStates, decision.trade_date, premarket?.stocks]);

  return (
    <main style={{ minHeight: '100%', color: C.text }}>
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 850 }}>每日决策工作台</h1>
          <p style={{ margin: '4px 0 0', color: C.secondary, fontSize: 12 }}>
            盘后选股 × 市场许可 × 行业强弱 × {session}验证，集中为今天的执行清单
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: C.muted, fontSize: 11 }}>
          <span>{liveQuoteUpdatedAt ? `行情更新 ${quoteTime(liveQuoteUpdatedAt)}` : '行情待返回'}</span>
          <span>{loadedAt ? `${loading ? '盘后清单已更新' : '最近更新'} ${loadedAt}` : '正在读取数据'}</span>
          <button
            type="button"
            onClick={load}
            disabled={loading}
            style={{ border: `1px solid ${C.border}`, borderRadius: 7, padding: '5px 9px', background: C.card, color: C.secondary, cursor: loading ? 'wait' : 'pointer', fontSize: 11, fontWeight: 700 }}
          >
            {loading ? (overview ? '补充加载中…' : '读取中…') : '↻ 刷新'}
          </button>
        </div>
      </header>

      {errors.length > 0 && (
        <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, border: `1px solid ${C.amber}55`, background: `${C.amber}12`, color: C.secondary, fontSize: 11 }}>
          部分数据未更新，页面保留最近一次成功结果：{errors.join('；')}
        </div>
      )}

      {decisionAlerts.length > 0 && (
        <div style={{ marginBottom: 10, padding: '8px 10px', borderRadius: 8, border: `1px solid ${C.blue}55`, background: `${C.blue}10`, color: C.secondary, fontSize: 11 }}>
          <b style={{ color: C.blue }}>盘中状态变化</b>
          <span style={{ marginLeft: 7 }}>{decisionAlerts.map((item) => `${item.symbol}：${item.previous} → ${item.label}`).join('；')}</span>
          <span style={{ marginLeft: 7, color: C.muted }}>已同步到顶部动态栏</span>
        </div>
      )}

      <section style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: 8, marginBottom: 10 }}>
        <Metric
          label="今日市场许可"
          value={marketState}
          note={decision?.market_gate?.label || REGIME_LABELS[regime.regime] || regime.reason || '等待市场状态'}
          color={marketAllowed ? C.up : C.amber}
          loading={loading && !overview}
        />
        <Metric label="盘后触发" value={`${buyable.length} 只`} note="盘中状态仍需逐条验证" color={C.up} loading={loading && !overview} />
        <Metric label="关注观察" value={`${watch.length} 只`} note="已通过筛选，等待触发确认" color={C.amber} loading={loading && !overview} />
        <Metric
          label="数据质量"
          value={qualityGood ? '已验证' : quality?.status || '待检查'}
          note={decision?.trade_date ? `盘后交易日 ${decision.trade_date}` : quality?.message || '等待盘后快照'}
          color={qualityGood ? C.blue : C.amber}
          loading={loading && !overview}
        />
      </section>

      <ChangeSummary changes={decision.changes} />

      <section style={{ display: 'grid', gridTemplateColumns: 'minmax(0, 1.5fr) minmax(300px, .85fr)', gap: 10, alignItems: 'start' }}>
        <Card>
          <SectionHeader
            icon="✅"
            title="今日行动清单"
            note="盘后结果不变；执行状态只根据市场许可与实时涨跌做短时提示"
            action={<Badge color={liveQuoteUpdatedAt ? C.blue : C.amber}>{liveQuoteUpdatedAt ? `行情 ${quoteTime(liveQuoteUpdatedAt)}` : '行情待返回'}</Badge>}
          />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(360px, 1fr))' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ padding: '9px 12px 3px', color: C.up, fontSize: 11, fontWeight: 800 }}>可执行买入 · {buyable.length} 只</div>
              {buyable.length
                ? buyable.map((item) => <CandidateRow key={item.symbol} item={item} kind="buy" quote={quoteBySymbol.get(String(item.symbol).toUpperCase())} marketState={marketState} isWatchlisted={watchlistSymbols.has(String(item.symbol).toUpperCase())} holding={holdingsBySymbol.get(String(item.symbol).toUpperCase())} onOpen={openStock} />)
                : <Empty>{overview ? '本轮没有满足全部条件的股票，不建议强行开仓' : '正在读取盘后决策…'}</Empty>}
            </div>
            <div style={{ minWidth: 0, borderLeft: `1px solid ${C.borderLight}` }}>
              <div style={{ padding: '9px 12px 3px', color: C.amber, fontSize: 11, fontWeight: 800 }}>关注观察 · {watch.length} 只</div>
              {watch.length
                ? watch.map((item) => <CandidateRow key={item.symbol} item={item} kind="watch" quote={quoteBySymbol.get(String(item.symbol).toUpperCase())} marketState={marketState} isWatchlisted={watchlistSymbols.has(String(item.symbol).toUpperCase())} holding={holdingsBySymbol.get(String(item.symbol).toUpperCase())} onOpen={openStock} />)
                : <Empty>{overview ? '暂无待触发候选' : '正在读取盘后决策…'}</Empty>}
            </div>
          </div>
        </Card>

        <div style={{ display: 'grid', gap: 10 }}>
          <Card>
            <SectionHeader icon="🌡️" title="大盘与行业判断" note="行业标签直接标出因子与当日走势的共振或背离，不作为独立买卖信号" />
            <div style={{ padding: '10px 12px' }}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
                <span style={{ color: marketAllowed ? C.up : C.amber, fontSize: 17, fontWeight: 850 }}>{REGIME_LABELS[regime.regime] || '等待判定'}</span>
                <span style={{ color: C.muted, fontSize: 11 }}>评分 {number(regime.score)?.toFixed(1) || '—'}</span>
              </div>
              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 10 }}>
                {marketEtfs.map((item) => (
                  <span key={item.symbol} style={{ padding: '5px 7px', borderRadius: 7, background: C.surface, fontSize: 11 }}>
                    <b style={{ color: C.text }}>{item.symbol}</b>
                    <span style={{ marginLeft: 5, color: pctColor(item.chg_pct), fontWeight: 800 }}>{pct(item.chg_pct)}</span>
                  </span>
                ))}
                {!marketEtfs.length && <span style={{ color: C.muted, fontSize: 11 }}>等待实时市场数据</span>}
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 6, marginTop: 10 }}>
                {indices.map((item) => (
                  <div key={item.code} style={{ padding: '6px 7px', borderRadius: 7, background: C.surface }}>
                    <div style={{ color: C.muted, fontSize: 9.5 }}>{item.name}</div>
                    <div style={{ marginTop: 3, color: pctColor(item.change_pct), fontSize: 12, fontWeight: 800 }}>{pct(item.change_pct)}</div>
                    <div style={{ marginTop: 2, color: C.muted, fontSize: 9.5 }}>20 日 {pct(item.ret_20d, 1)}</div>
                  </div>
                ))}
              </div>
              <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid ${C.borderLight}` }}>
                <div style={{ marginBottom: 4, color: C.secondary, fontSize: 11, fontWeight: 800 }}>行业共识</div>
                <div style={{ color: C.muted, fontSize: 10 }}>盘后因子排名 × 当日 / 20 日表现</div>
                {industryRows.length
                  ? industryRows.map((sector) => <SectorRow key={sector.etf_symbol} sector={sector} realtime={realtimeSectors.get(sector.etf_symbol)} />)
                  : <Empty>暂无行业因子数据</Empty>}
              </div>
            </div>
          </Card>
          <PortfolioGuardCard guard={decision.portfolio_guard} />
          <ReviewCard review={decision.review} />
        </div>
      </section>

      <section style={{ marginTop: 10 }}>
        <Card>
          <SectionHeader icon="⚡" title={`盘中观察 · 候选与自选${session}异动`} note="把实时异动和影响市场的资讯放在同一个辅助判断区，点击股票可进入个股分析" />
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))' }}>
            <div style={{ minWidth: 0, padding: '0 12px 5px' }}>
              <div style={{ padding: '9px 0 3px', color: C.secondary, fontSize: 11, fontWeight: 800 }}>实时异动</div>
              {movers.length ? movers.map((item) => <MoverRow key={item.symbol} item={item} onOpen={openStock} />) : <Empty>暂无实时异动数据</Empty>}
            </div>
            <div style={{ minWidth: 0, padding: '0 12px 5px', borderLeft: `1px solid ${C.borderLight}` }}>
              <div style={{ padding: '9px 0 3px', color: C.secondary, fontSize: 11, fontWeight: 800 }}>市场资讯</div>
              {news.length ? news.map((item, index) => (
                <a
                  key={`${item.url || item.title}-${index}`}
                  href={item.url}
                  target="_blank"
                  rel="noreferrer"
                  style={{ display: 'block', padding: '9px 0', borderTop: `1px solid ${C.borderLight}`, color: C.text, textDecoration: 'none' }}
                >
                  <div style={{ fontSize: 12, lineHeight: 1.4 }}>{item.title}</div>
                  <div style={{ marginTop: 3, color: C.muted, fontSize: 10 }}>{item.media || '市场资讯'} {item.time ? `· ${item.time}` : ''}</div>
                </a>
              )) : <Empty>暂无市场资讯</Empty>}
            </div>
          </div>
        </Card>
      </section>

      <footer style={{ marginTop: 10, color: C.muted, fontSize: 10.5, lineHeight: 1.55 }}>
        使用顺序：先确认市场许可，再查看候选变化、组合相关性和实时执行状态，随后用行业共识与自选异动决定是否观察或执行。数据每 60 秒刷新一次；盘后因子、连续入选及历史复盘均只读取已落库数据，实时行情不改变盘后结论，也不会自动下单。
      </footer>
    </main>
  );
}
