import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

const UP = '#ef4444';
const DOWN = '#22c55e';
const BLUE = '#3b82f6';
const AMBER = '#f59e0b';

const n = (v) => (v == null || Number.isNaN(Number(v)) ? null : Number(v));
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
  return <span className="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold" style={{ color, background: bg }}>{children}</span>;
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
  if (/触发|持有/.test(action || '')) return { c: UP, bg: 'rgba(239,68,68,.08)' };
  if (/等|等待/.test(action || '')) return { c: BLUE, bg: 'rgba(59,130,246,.08)' };
  if (/不做|退出|减仓/.test(action || '')) return { c: DOWN, bg: 'rgba(34,197,94,.08)' };
  return { c: AMBER, bg: 'rgba(245,158,11,.08)' };
}

export default function SecondWavePage() {
  const navigate = useNavigate();
  const [wave, setWave] = useState(null);
  const [portfolio, setPortfolio] = useState({ positions: [] });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updatedAt, setUpdatedAt] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    const [w, p] = await Promise.all([
      apiFetch('/api/quant/second-wave?limit=12', {}, 30000, 0),
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
  const candidates = wave?.candidates || [];
  const candidateMap = useMemo(() => {
    const map = new Map();
    candidates.forEach((c) => map.set(norm(c.code), c));
    return map;
  }, [candidates]);

  const holdings = useMemo(() => (portfolio?.positions || []).map((p) => {
    const c = candidateMap.get(norm(p.symbol));
    let action = '非二波池·单独管理';
    if (c) {
      if (c.structure === '二波主升' || c.structure === '二波触发') action = '继续持有';
      else if (c.structure === '缩量等待' || c.structure === '二波观察') action = '观察';
      else action = '减仓/退出检查';
    }
    return { ...p, candidate: c, action };
  }), [portfolio, candidateMap]);

  const market = wave?.market || {};
  const marketColor = market.state === '可做' ? UP : market.state === '等待' ? 'var(--text-muted)' : AMBER;

  return (
    <div className="space-y-3 max-w-[1500px] mx-auto" style={{ color: 'var(--text-primary)' }}>
      <Card className="p-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold">二波作战</h1>
              <Badge color={marketColor} bg={market.state === '可做' ? 'rgba(239,68,68,.08)' : 'rgba(245,158,11,.08)'}>{market.state || '加载中'}</Badge>
              <Badge>{wave?.trade_date || '—'} 完成交易日</Badge>
            </div>
            <div className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
              市场 → 板块二波 → 核心龙头 → 个股结构 → 买点触发。因子只解释，不再用总分凑股票。
            </div>
          </div>
          <button onClick={load} disabled={loading} className="rounded-lg border px-3 py-1.5 text-xs" style={{ borderColor: 'var(--border-color)', color: BLUE }}>
            {loading ? '刷新中…' : '↻ 刷新'}
          </button>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mt-3">
          {[
            ['今日环境', market.state || '—', marketColor],
            ['二波板块', market.eligible_board_count ?? 0, BLUE],
            ['启动板块', market.startup_count ?? 0, UP],
            ['核心候选', market.candidate_count ?? 0, AMBER],
          ].map(([label, value, color]) => (
            <div key={label} className="rounded-lg px-3 py-2" style={{ background: 'var(--bg-hover)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
              <div className="text-lg font-bold mt-0.5" style={{ color }}>{value}</div>
            </div>
          ))}
        </div>
        <div className="mt-2 rounded-lg px-3 py-2 text-xs" style={{ background: 'rgba(59,130,246,.05)', color: 'var(--text-secondary)' }}>
          <b style={{ color: BLUE }}>系统结论：</b> {market.reason || '正在计算板块二波资格'}
          {updatedAt && <span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>更新 {updatedAt.toLocaleTimeString('zh-CN')}</span>}
        </div>
      </Card>

      {error && <div className="rounded-lg px-3 py-2 text-xs" style={{ background: 'rgba(239,68,68,.08)', color: UP }}>{error}</div>}

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <div>
            <b className="text-sm">① 板块二波</b>
            <span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>主题优先，行业确认；只显示有二波资格的板块</span>
          </div>
          <button onClick={() => navigate('/trading/sector-rotation')} className="text-[10px]" style={{ color: BLUE }}>看完整板块研究 →</button>
        </div>
        {boards.length === 0 ? (
          <div className="p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>当前没有通过二波硬门槛的板块，宁可空着，不凑数。</div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2 p-2">
            {boards.map((b) => {
              const s = stageStyle(b.stage);
              return (
                <div key={`${b.kind}-${b.name}`} className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-bold text-sm truncate">{b.name}</div>
                    <Badge color={s.c} bg={s.bg}>{b.stage}</Badge>
                  </div>
                  <div className="flex gap-1 mt-1.5"><Badge>{b.kind}</Badge><Badge color={b.grade === 'A' ? UP : BLUE}>结构 {b.grade}</Badge><Badge>置信 {b.confidence}%</Badge></div>
                  <div className="grid grid-cols-3 gap-1 mt-2 text-[10px]">
                    <div><span style={{ color: 'var(--text-muted)' }}>5日</span><div style={{ color: tone(b.metrics?.ret_5d) }}>{pct(b.metrics?.ret_5d)}</div></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>趋势股</span><div>{pct(b.metrics?.trend_share)}</div></div>
                    <div><span style={{ color: 'var(--text-muted)' }}>广度</span><div>{pct(b.metrics?.breadth)}</div></div>
                  </div>
                  <div className="mt-2 space-y-0.5 text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                    {(b.reasons || []).slice(0, 3).map((r) => <div key={r}>✓ {r}</div>)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <div><b className="text-sm">② 龙头个股</b><span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>每个二波板块最多核心龙头 + 强次龙，不展示跟风</span></div>
          <button onClick={() => navigate('/stock-analysis')} className="text-[10px]" style={{ color: BLUE }}>个股分析 →</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr style={{ color: 'var(--text-muted)', background: 'var(--bg-hover)' }}>
              {['股票', '板块', '身份', '板块状态', '个股结构', '现价/日涨', '回撤', '量比', '动作', '证据'].map((h) => <th key={h} className="px-2 py-2 text-left whitespace-nowrap">{h}</th>)}
            </tr></thead>
            <tbody>
              {candidates.map((c) => {
                const as = actionStyle(c.action);
                const ss = stageStyle(c.board_stage);
                return <tr key={c.code} className="border-t hover:opacity-90 cursor-pointer" style={{ borderColor: 'var(--border-light)' }} onClick={() => navigate(`/stock-analysis?code=${encodeURIComponent(c.code)}`)}>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{c.name || c.code}</b><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.code}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{c.board}</b><div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.board_kind}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap"><Badge color={c.leader === '核心龙头' ? UP : BLUE}>{c.leader}</Badge></td>
                  <td className="px-2 py-2 whitespace-nowrap"><Badge color={ss.c} bg={ss.bg}>{c.board_stage}</Badge></td>
                  <td className="px-2 py-2 whitespace-nowrap">{c.structure}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><b>{n(c.price)?.toFixed(2) || '—'}</b><div style={{ color: tone(c.day_change_pct) }}>{pct(c.day_change_pct)}</div></td>
                  <td className="px-2 py-2 whitespace-nowrap" style={{ color: tone(c.drawdown) }}>{pct(c.drawdown)}</td>
                  <td className="px-2 py-2 whitespace-nowrap">{n(c.volume_ratio)?.toFixed(2) || '—'}</td>
                  <td className="px-2 py-2 whitespace-nowrap"><Badge color={as.c} bg={as.bg}>{c.action}</Badge></td>
                  <td className="px-2 py-2 min-w-56"><div className="flex flex-wrap gap-1">{(c.reasons || []).slice(0, 3).map((r) => <Badge key={r}>{r}</Badge>)}</div></td>
                </tr>;
              })}
              {!loading && candidates.length === 0 && <tr><td colSpan="10" className="p-8 text-center" style={{ color: 'var(--text-muted)' }}>没有满足“板块二波 + 龙头 + 上升趋势”的股票，今天不凑票。</td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card>
        <div className="px-3 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
          <div><b className="text-sm">③ 我的持仓</b><span className="ml-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>持仓保留独立管理页，这里只叠加二波状态给动作</span></div>
          <button onClick={() => navigate('/portfolio')} className="text-[10px]" style={{ color: BLUE }}>完整持仓管理 →</button>
        </div>
        {holdings.length === 0 ? <div className="p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>当前没有持仓</div> : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 p-2">
            {holdings.map((h) => {
              const c = h.candidate;
              const a = actionStyle(h.action);
              const pnl = n(h.unrealized_pnl_pct ?? h.profit_pct ?? h.pnl_pct);
              return <div key={h.symbol} className="rounded-lg border p-2.5 cursor-pointer" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }} onClick={() => navigate(`/stock-analysis?code=${encodeURIComponent(h.symbol)}`)}>
                <div className="flex items-center justify-between gap-2"><div><b>{h.name || h.symbol}</b><span className="ml-1 text-[10px]" style={{ color: 'var(--text-muted)' }}>{h.symbol}</span></div><Badge color={a.c} bg={a.bg}>{h.action}</Badge></div>
                <div className="grid grid-cols-3 gap-2 mt-2 text-[10px]">
                  <div><span style={{ color: 'var(--text-muted)' }}>成本</span><div>{n(h.avg_cost)?.toFixed(2) || '—'}</div></div>
                  <div><span style={{ color: 'var(--text-muted)' }}>现价</span><div>{n(h.last_price)?.toFixed(2) || '—'}</div></div>
                  <div><span style={{ color: 'var(--text-muted)' }}>盈亏</span><div style={{ color: tone(pnl) }}>{pct(pnl)}</div></div>
                </div>
                <div className="mt-2 text-[10px]" style={{ color: 'var(--text-secondary)' }}>
                  {c ? <><span>{c.board} · {c.leader}</span><span className="mx-1">·</span><b>{c.structure}</b></> : '当前不在二波核心候选池，按持仓页的成本/止损/趋势单独管理。'}
                </div>
              </div>;
            })}
          </div>
        )}
      </Card>

      <div className="rounded-lg px-3 py-2 text-[10px]" style={{ color: 'var(--text-muted)', background: 'var(--bg-hover)' }}>
        硬门槛：板块趋势破坏、广度过弱、个股跌破 MA20 上升趋势、非板块前2核心股，任一出现都不能靠其他因子加分补回来。二波页面使用已完成交易日日线做资格筛选，盘中买点仍以实时转强确认。
      </div>
    </div>
  );
}
