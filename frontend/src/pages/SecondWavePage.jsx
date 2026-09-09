import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

const UP = '#ef4444';
const DOWN = '#22c55e';
const BLUE = '#3b82f6';
const AMBER = '#f59e0b';

const n = (v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v));
const fmt = (v, d = 2) => {
  const x = n(v);
  return x == null ? '—' : x.toFixed(d);
};
const pct = (v) => {
  const x = n(v);
  return x == null ? '—' : `${x > 0 ? '+' : ''}${x.toFixed(1)}%`;
};
const tone = (v) => {
  const x = n(v);
  return x == null ? 'var(--text-muted)' : x >= 0 ? UP : DOWN;
};
const norm = (code) => String(code || '').split('.')[0].replace(/\D/g, '');

function Badge({ children, color = 'var(--text-secondary)', bg = 'var(--bg-hover)' }) {
  return <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold whitespace-nowrap" style={{ color, background: bg }}>{children}</span>;
}

function Card({ children, className = '' }) {
  return <div className={`rounded-xl border ${className}`} style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>{children}</div>;
}

function stageStyle(stage) {
  if (stage === '二波启动') return { c: UP, bg: 'rgba(239,68,68,.09)' };
  if (stage === '二波蓄势') return { c: BLUE, bg: 'rgba(59,130,246,.09)' };
  if (stage === '二波加速') return { c: AMBER, bg: 'rgba(245,158,11,.10)' };
  if (stage === '退潮' || stage === '无二波资格') return { c: DOWN, bg: 'rgba(34,197,94,.08)' };
  return { c: 'var(--text-muted)', bg: 'var(--bg-hover)' };
}

function actionStyle(action) {
  if (/买点触发|继续持有/.test(action || '')) return { c: UP, bg: 'rgba(239,68,68,.08)' };
  if (/等转强|等待|观察/.test(action || '')) return { c: BLUE, bg: 'rgba(59,130,246,.08)' };
  if (/不追高/.test(action || '')) return { c: AMBER, bg: 'rgba(245,158,11,.08)' };
  if (/不做|退出|减仓|跌破/.test(action || '')) return { c: DOWN, bg: 'rgba(34,197,94,.08)' };
  return { c: 'var(--text-secondary)', bg: 'var(--bg-hover)' };
}

function PositionGrid({ item }) {
  const lv = item.levels || {};
  return (
    <div className="grid grid-cols-3 md:grid-cols-6 gap-1 mt-2 text-[10px]">
      <div><span style={{ color: 'var(--text-muted)' }}>现价</span><div className="font-semibold">{fmt(item.price)}</div></div>
      <div><span style={{ color: 'var(--text-muted)' }}>突破参考</span><div style={{ color: UP }}>{fmt(lv.breakout_reference)}</div></div>
      <div><span style={{ color: 'var(--text-muted)' }}>距突破</span><div style={{ color: tone(-(n(lv.distance_to_breakout_pct) ?? 0)) }}>{pct(lv.distance_to_breakout_pct)}</div></div>
      <div><span style={{ color: 'var(--text-muted)' }}>结构防守</span><div style={{ color: AMBER }}>{fmt(lv.defense_reference)}</div></div>
      <div><span style={{ color: 'var(--text-muted)' }}>离高点</span><div style={{ color: tone(item.drawdown) }}>{pct(item.drawdown)}</div></div>
      <div><span style={{ color: 'var(--text-muted)' }}>距一波</span><div>{n(item.days_since_first_wave) == null ? '—' : `${Math.round(n(item.days_since_first_wave))}日`}</div></div>
    </div>
  );
}

function CandidateCard({ item, navigate, compact = false }) {
  const as = actionStyle(item.action);
  const ss = stageStyle(item.board_stage);
  return (
    <button
      onClick={() => navigate(`/stock-analysis?code=${encodeURIComponent(item.code)}`)}
      className="w-full rounded-lg border text-left transition-opacity hover:opacity-90"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)', padding: compact ? '8px' : '10px' }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <b className="text-sm">{item.name || item.code}</b>
            <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{item.code}</span>
            <Badge color={item.leader === '核心龙头' ? UP : BLUE}>{item.leader}</Badge>
          </div>
          <div className="mt-1 flex items-center gap-1 flex-wrap">
            <span className="text-[11px] font-semibold">{item.board}</span>
            <Badge>{item.board_kind}</Badge>
            <Badge color={ss.c} bg={ss.bg}>{item.board_stage}</Badge>
          </div>
        </div>
        <Badge color={as.c} bg={as.bg}>{item.action}</Badge>
      </div>
      <PositionGrid item={item} />
      {!compact && (
        <div className="mt-2 flex flex-wrap gap-1">
          <Badge>{item.structure}</Badge>
          {(item.reasons || []).slice(0, 3).map((r) => <Badge key={r}>{r}</Badge>)}
        </div>
      )}
    </button>
  );
}

function ActionColumn({ title, subtitle, items, color, empty, navigate }) {
  return (
    <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex items-center justify-between gap-2">
          <b className="text-sm" style={{ color }}>{title}</b>
          <Badge color={color}>{items.length}只</Badge>
        </div>
        <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{subtitle}</div>
      </div>
      <div className="p-2 space-y-2 min-h-[116px]">
        {items.length > 0 ? items.slice(0, 4).map((item) => <CandidateCard key={item.code} item={item} navigate={navigate} compact />) : (
          <div className="h-[96px] flex items-center justify-center text-xs text-center px-3" style={{ color: 'var(--text-muted)' }}>{empty}</div>
        )}
      </div>
    </div>
  );
}

export default function SecondWavePage() {
  const navigate = useNavigate();
  const [wave, setWave] = useState(null);
  const [portfolio, setPortfolio] = useState({ positions: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);
  const [selectedBoard, setSelectedBoard] = useState('');
  const [showSecond, setShowSecond] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    const [w, p] = await Promise.all([
      apiFetch('/api/quant/second-wave?limit=30', {}, 30000, 0),
      apiFetch('/api/shared/portfolio', {}, 15000, 0),
    ]);
    if (w.ok) {
      setWave(w.data);
      setError('');
    } else {
      setError(w.error || '二波数据加载失败');
    }
    if (p.ok) setPortfolio(p.data || { positions: [] });
    setUpdatedAt(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  const boards = useMemo(() => (wave?.boards || []).filter((b) => b.eligible).slice(0, 8), [wave]);
  const candidates = useMemo(() => wave?.candidates || [], [wave]);
  const coreCandidates = useMemo(() => candidates.filter((c) => c.leader === '核心龙头'), [candidates]);
  const secondCandidates = useMemo(() => candidates.filter((c) => c.leader === '强次龙'), [candidates]);

  // 第一屏只看核心龙头。强次龙仅作为备选，不参与“今日买点”数量。
  const triggered = useMemo(() => coreCandidates.filter((c) => c.action === '买点触发'), [coreCandidates]);
  const waiting = useMemo(() => coreCandidates.filter((c) => ['等转强', '等待'].includes(c.action)), [coreCandidates]);
  const holdingPriority = useMemo(() => coreCandidates.filter((c) => /持有优先|不追高/.test(c.action || '')), [coreCandidates]);

  const visibleCandidates = useMemo(() => {
    let rows = showSecond ? candidates : coreCandidates;
    if (selectedBoard) rows = rows.filter((c) => c.board === selectedBoard);
    return rows;
  }, [candidates, coreCandidates, selectedBoard, showSecond]);

  const candidateMap = useMemo(() => {
    const map = new Map();
    candidates.forEach((c) => map.set(norm(c.code), c));
    return map;
  }, [candidates]);

  const holdings = useMemo(() => (portfolio?.positions || []).map((p) => {
    const c = candidateMap.get(norm(p.symbol));
    const livePrice = n(p.last_price);
    const defense = n(c?.levels?.defense_reference);
    let action = '非二波池·单独管理';
    if (c) {
      if (livePrice != null && defense != null && livePrice < defense) action = '跌破结构防守·减仓检查';
      else if (c.structure === '二波主升' || c.structure === '二波触发') action = '继续持有';
      else if (c.structure === '缩量等待' || c.structure === '二波观察') action = '观察';
      else action = '减仓/退出检查';
    }
    return { ...p, candidate: c, action };
  }).sort((a, b) => {
    const risk = (x) => /跌破|退出|减仓/.test(x.action) ? 0 : /观察/.test(x.action) ? 1 : /继续持有/.test(x.action) ? 2 : 3;
    return risk(a) - risk(b);
  }), [portfolio, candidateMap]);

  const market = wave?.market || {};
  const marketColor = market.state === '可做' ? UP : market.state === '等待' ? 'var(--text-muted)' : AMBER;
  const decisiveText = triggered.length > 0
    ? `今天有 ${triggered.length} 只核心龙头达到二波触发资格，盘中只等板块同步与承接确认。`
    : waiting.length > 0
      ? `今天暂不抢，${waiting.length} 只核心龙头仍在等转强。`
      : holdingPriority.length > 0
        ? '当前核心机会主要处于主升/加速段，有仓持有，无仓不追。'
        : '当前没有值得出手的二波核心龙头，宁可等待。';

  return (
    <div className="space-y-3 max-w-[1500px] mx-auto" style={{ color: 'var(--text-primary)' }}>
      <Card className="p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold">二波作战</h1>
              <Badge color={marketColor} bg={market.state === '可做' ? 'rgba(239,68,68,.08)' : 'rgba(245,158,11,.08)'}>{market.state || '加载中'}</Badge>
              <Badge>{wave?.trade_date || '—'} 完成交易日</Badge>
            </div>
            <div className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
              只做：板块二波成立 + 核心龙头 + 上升趋势 + 盘中确认。
            </div>
          </div>
          <button onClick={load} disabled={loading} className="rounded-lg border px-3 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: BLUE }}>
            {loading ? '刷新中…' : '↻ 刷新'}
          </button>
        </div>

        <div className="mt-3 rounded-xl px-3 py-2.5" style={{ background: triggered.length ? 'rgba(239,68,68,.06)' : 'rgba(59,130,246,.05)', border: `1px solid ${triggered.length ? 'rgba(239,68,68,.18)' : 'rgba(59,130,246,.16)'}` }}>
          <div className="text-[10px] font-semibold" style={{ color: 'var(--text-muted)' }}>今日作战指令</div>
          <div className="text-sm font-bold mt-0.5" style={{ color: triggered.length ? UP : BLUE }}>{decisiveText}</div>
          <div className="text-[10px] mt-1" style={{ color: 'var(--text-secondary)' }}>
            市场判断：{market.reason || '正在计算'}
            {updatedAt && <span className="ml-2" style={{ color: 'var(--text-muted)' }}>更新 {updatedAt.toLocaleTimeString('zh-CN')}</span>}
          </div>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-6 gap-2 mt-3">
          {[
            ['今日环境', market.state || '—', marketColor],
            ['二波板块', market.eligible_board_count ?? 0, BLUE],
            ['核心龙头', coreCandidates.length, UP],
            ['买点触发', triggered.length, UP],
            ['等待转强', waiting.length, BLUE],
            ['强次龙备选', secondCandidates.length, AMBER],
          ].map(([label, value, color]) => (
            <div key={label} className="rounded-lg px-3 py-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
              <div className="text-lg font-bold mt-0.5" style={{ color }}>{value}</div>
            </div>
          ))}
        </div>
      </Card>

      {error && <div className="rounded-lg px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,.08)', color: UP }}>{error}</div>}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <ActionColumn title="🟢 二波触发" subtitle="盘后资格已成立；盘中仍要确认板块同步、承接和量价" items={triggered} color={UP} empty="今天没有达到二波触发资格的核心龙头" navigate={navigate} />
        <ActionColumn title="🔵 等转强" subtitle="结构还在，但没有触发；不要提前抢" items={waiting} color={BLUE} empty="当前没有等待转强的核心龙头" navigate={navigate} />
        <ActionColumn title="🟠 主升不追" subtitle="强是强，但位置偏高；有仓持有，无仓等回踩" items={holdingPriority} color={AMBER} empty="当前没有进入主升加速段的核心龙头" navigate={navigate} />
      </div>

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <b className="text-sm">① 板块二波雷达</b>
            <span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>点击板块，只看该板块核心龙头</span>
          </div>
          <div className="flex items-center gap-2">
            {selectedBoard && <button onClick={() => setSelectedBoard('')} className="text-[10px]" style={{ color: AMBER }}>清除筛选</button>}
            <button onClick={() => navigate('/trading/sector-rotation')} className="text-[10px]" style={{ color: BLUE }}>完整板块研究 →</button>
          </div>
        </div>
        {boards.length === 0 ? (
          <div className="p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>当前没有通过二波硬门槛的板块，宁可空着，不凑数。</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 p-2">
            {boards.map((b) => {
              const s = stageStyle(b.stage);
              const active = selectedBoard === b.name;
              return (
                <button key={`${b.kind}-${b.name}`} onClick={() => setSelectedBoard(active ? '' : b.name)} className="rounded-lg border p-2.5 text-left" style={{ borderColor: active ? BLUE : 'var(--border-color)', background: active ? 'rgba(59,130,246,.06)' : 'var(--bg-hover)' }}>
                  <div className="flex items-center justify-between gap-2"><div className="font-bold text-sm truncate">{b.name}</div><Badge color={s.c} bg={s.bg}>{b.stage}</Badge></div>
                  <div className="flex gap-1 mt-1.5 flex-wrap"><Badge>{b.kind}</Badge><Badge color={b.grade === 'A' ? UP : BLUE}>结构 {b.grade}</Badge><Badge>置信 {b.confidence}%</Badge></div>
                  <div className="grid grid-cols-4 gap-1 mt-2 text-[10px]">
                    <div><span style={{ color: 'var(--text-muted)' }}>5日</span><div style={{ color: tone(b.metrics?.ret_5d) }}>{pct(b.metrics?.ret_5d)}</div></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>趋势股</span><div>{pct(b.metrics?.trend_share)}</div></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>广度</span><div>{pct(b.metrics?.breadth)}</div></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>距一波</span><div>{n(b.median_days_since_first_wave) == null ? '—' : `${Math.round(n(b.median_days_since_first_wave))}日`}</div></div>
                  </div>
                  <div className="mt-2 text-[10px]" style={{ color: 'var(--text-secondary)' }}>{(b.reasons || []).slice(0, 2).join(' · ')}</div>
                </button>
              );
            })}
          </div>
        )}
      </Card>

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <b className="text-sm">② 核心龙头</b>
            <span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>{selectedBoard ? `当前筛选：${selectedBoard}` : '默认只展示板块排名第1'}</span>
          </div>
          <div className="flex items-center gap-2">
            <button onClick={() => setShowSecond((v) => !v)} className="rounded border px-2 py-1 text-[10px]" style={{ borderColor: 'var(--border-color)', color: showSecond ? AMBER : 'var(--text-secondary)' }}>
              {showSecond ? '隐藏强次龙' : `展开强次龙（${secondCandidates.length}）`}
            </button>
            <button onClick={() => navigate('/stock-analysis')} className="text-[10px]" style={{ color: BLUE }}>个股分析 →</button>
          </div>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr style={{ color: 'var(--text-muted)', background: 'var(--bg-hover)' }}>
              {['股票', '板块/阶段', '身份', '结构', '现价', '突破参考', '结构防守', '距高点', '距一波', '动作', '证据'].map((h) => <th key={h} className="px-2 py-2 text-left whitespace-nowrap">{h}</th>)}
            </tr></thead>
            <tbody>
              {visibleCandidates.map((c) => {
                const as = actionStyle(c.action);
                const ss = stageStyle(c.board_stage);
                const lv = c.levels || {};
                return <tr key={c.code} className="border-t hover:opacity-90 cursor-pointer" style={{ borderColor: 'var(--border-light)' }} onClick={() => navigate(`/stock-analysis?code=${encodeURIComponent(c.code)}`)}>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{c.name || c.code}</b><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.code}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{c.board}</b><div className="mt-0.5"><Badge color={ss.c} bg={ss.bg}>{c.board_stage}</Badge></div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><Badge color={c.leader === '核心龙头' ? UP : BLUE}>{c.leader}</Badge></td>
                  <td className="px-2 py-2 whitespace-nowrap">{c.structure}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{fmt(c.price)}</b><div style={{ color: tone(c.day_change_pct) }}>{pct(c.day_change_pct)}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><b style={{ color: UP }}>{fmt(lv.breakout_reference)}</b><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>距 {pct(lv.distance_to_breakout_pct)}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><b style={{ color: AMBER }}>{fmt(lv.defense_reference)}</b><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{lv.defense_basis || '—'}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap" style={{ color: tone(c.drawdown) }}>{pct(c.drawdown)}</td>
                  <td className="px-2 py-2 whitespace-nowrap">{n(c.days_since_first_wave) == null ? '—' : `${Math.round(n(c.days_since_first_wave))}日`}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><Badge color={as.c} bg={as.bg}>{c.action}</Badge></td>
                  <td className="px-2 py-2 min-w-52"><div className="flex flex-wrap gap-1">{(c.reasons || []).slice(0, 3).map((r) => <Badge key={r}>{r}</Badge>)}</div></td>
                </tr>;
              })}
              {!loading && visibleCandidates.length === 0 && <tr><td colSpan="11" className="p-8 text-center" style={{ color: 'var(--text-muted)' }}>当前筛选下没有符合条件的核心龙头。</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <div><b className="text-sm">③ 我的持仓</b><span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>先看风险，再看持有；跌破结构防守会自动置顶</span></div>
          <button onClick={() => navigate('/portfolio')} className="text-[10px]" style={{ color: BLUE }}>完整持仓管理 →</button>
        </div>
        {holdings.length === 0 ? <div className="p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>当前没有持仓</div> : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 p-2">
            {holdings.map((h) => {
              const c = h.candidate;
              const a = actionStyle(h.action);
              const pnl = n(h.unrealized_pnl_pct ?? h.profit_pct ?? h.pnl_pct);
              const defense = c?.levels?.defense_reference;
              return <button key={h.symbol} className="rounded-lg border p-2.5 text-left" style={{ borderColor: /跌破|退出|减仓/.test(h.action) ? 'rgba(34,197,94,.45)' : 'var(--border-color)', background: 'var(--bg-hover)' }} onClick={() => navigate(`/stock-analysis?code=${encodeURIComponent(h.symbol)}`)}>
                <div className="flex items-center justify-between gap-2"><div><b>{h.name || h.symbol}</b><span className="ml-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>{h.symbol}</span></div><Badge color={a.c} bg={a.bg}>{h.action}</Badge></div>
                <div className="grid grid-cols-4 gap-2 mt-2 text-[10px]">
                  <div><span style={{ color: 'var(--text-muted)' }}>成本</span><div>{fmt(h.avg_cost)}</div></div>
                  <div><span style={{ color: 'var(--text-muted)' }}>现价</span><div>{fmt(h.last_price)}</div></div>
                  <div><span style={{ color: 'var(--text-muted)' }}>盈亏</span><div style={{ color: tone(pnl) }}>{pct(pnl)}</div></div>
                  <div><span style={{ color: 'var(--text-muted)' }}>结构防守</span><div style={{ color: AMBER }}>{fmt(defense)}</div></div>
                </div>
                <div className="mt-2 text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {c ? <><span>{c.board} · {c.leader}</span><span className="mx-1">·</span><b>{c.structure}</b></> : '当前不在二波核心候选池，按持仓页的成本/趋势单独管理。'}
                </div>
              </button>;
            })}
          </div>
        )}
      </Card>

      <div className="rounded-lg px-3 py-2 text-[10px]" style={{ color: 'var(--text-muted)', background: 'var(--bg-hover)' }}>
        硬门槛：板块趋势破坏、广度过弱、个股跌破 MA20 上升趋势、非板块前2核心股，任一出现都不能靠其他因子加分补回来。突破参考与结构防守来自已完成日线，只作结构参考；盘中是否介入仍需确认板块同步、量价与承接。
      </div>
    </div>
  );
}
