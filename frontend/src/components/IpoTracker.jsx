import { useState, useEffect, useMemo } from 'react';
import { parseStageDate } from '../data/ipoProjects';

// ─────────────────────────────────────────────────────────────────────────
// IPO 跟踪共享组件
//   IpoTimeline    —— 前跟踪：横向步进器 + 实时倒计时（按当前时间自动推进）
//   IpoListingCard —— 后跟踪：上市后拉取公司自身实时行情卡
// ─────────────────────────────────────────────────────────────────────────

// 计算当前所处阶段
export function computeIpoProgress(project, now) {
  const enriched = project.stages.map((s) => ({ ...s, ms: parseStageDate(s.date) }));
  let currentIdx = -1;
  enriched.forEach((s, i) => {
    if (s.ms != null && s.ms <= now) currentIdx = i;
  });
  const nextIdx = enriched.findIndex((s) => s.ms != null && s.ms > now);
  return enriched.map((s, i) => {
    let status;
    if (s.ms == null) status = 'unknown';
    else if (i < currentIdx) status = 'done';
    else if (i === currentIdx) status = 'done';
    else if (i === nextIdx) status = 'active';
    else status = 'upcoming';
    return { ...s, status };
  }).reduce((acc, s, i) => {
    acc.stages.push(s);
    if (s.status === 'active') acc.nextIdx = i;
    return acc;
  }, { stages: [], nextIdx: -1, currentIdx });
}

const STATUS_STYLE = {
  done: { color: '#22c55e', bg: 'rgba(34,197,94,0.12)', border: 'rgba(34,197,94,0.4)', icon: '✓' },
  active: { color: '#3b82f6', bg: 'rgba(59,130,246,0.14)', border: 'rgba(59,130,246,0.5)', icon: '●' },
  upcoming: { color: 'var(--text-muted)', bg: 'var(--bg-surface)', border: 'var(--border-color)', icon: '○' },
  unknown: { color: 'var(--text-muted)', bg: 'var(--bg-surface)', border: 'var(--border-color)', icon: '?' },
};

function fmtCountdown(ms) {
  if (ms < 0) ms = 0;
  const dd = Math.floor(ms / 86400000);
  const hh = Math.floor((ms % 86400000) / 3600000);
  const mm = Math.floor((ms % 3600000) / 60000);
  if (dd > 0) return `${dd}天${hh}小时`;
  if (hh > 0) return `${hh}小时${mm}分`;
  return `${mm}分`;
}

function fmtDate(d) {
  if (!d) return '待披露';
  return d.replace(/-/g, '/');
}

// ===== 前跟踪：进程时间线 + 实时倒计时 =====
export function IpoTimeline({ project }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 30000); // 每 30s 刷新倒计时
    return () => clearInterval(t);
  }, []);

  const { stages, nextIdx } = useMemo(() => computeIpoProgress(project, now), [project, now]);
  const nextStage = nextIdx >= 0 ? stages[nextIdx] : null;
  const allDone = stages.every((s) => s.status === 'done');

  let statusLine;
  if (project.listed && allDone) {
    statusLine = { text: '已上市 · 后跟踪进行中', color: '#22c55e', icon: '🚀' };
  } else if (nextStage) {
    const diff = nextStage.ms - now;
    statusLine = {
      text: `距「${nextStage.label}」还有 ${fmtCountdown(diff)}`,
      color: STATUS_STYLE.active.color,
      icon: '⏳',
    };
  } else {
    statusLine = { text: '进程进行中 · 后续节点待披露', color: 'var(--text-muted)', icon: '📝' };
  }

  return (
    <div className="rounded-xl border p-3 space-y-2.5" style={{
      borderColor: 'rgba(59,130,246,0.3)',
      background: 'linear-gradient(135deg, rgba(59,130,246,0.05) 0%, rgba(168,85,247,0.04) 100%)',
    }}>
      {/* 顶部状态行 */}
      <div className="flex items-center gap-2 flex-wrap">
        <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{project.name}</span>
        <span className="text-xs px-2 py-0.5 rounded-full flex items-center gap-1"
          style={{ background: `${statusLine.color}14`, color: statusLine.color, border: `1px solid ${statusLine.color}40` }}>
          {statusLine.icon} {statusLine.text}
        </span>
        <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
          {project.board}{project.code ? ` · ${project.code}` : ' · 代码待定'}
        </span>
      </div>

      {/* 步进器 */}
      <div className="flex items-center gap-1 flex-wrap">
        {stages.map((s, i) => {
          const st = STATUS_STYLE[s.status];
          return (
            <div key={s.key} className="flex items-center gap-1">
              <div className="flex flex-col items-center" title={s.label}>
                <div className="w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold"
                  style={{ background: st.bg, color: st.color, border: `1px solid ${st.border}` }}>
                  {st.icon}
                </div>
                <div className="text-[9px] mt-0.5 whitespace-nowrap" style={{ color: s.status === 'upcoming' || s.status === 'unknown' ? 'var(--text-muted)' : st.color }}>
                  {s.label}
                </div>
                <div className="text-[8px] whitespace-nowrap" style={{ color: 'var(--text-muted)' }}>{fmtDate(s.date)}</div>
              </div>
              {i < stages.length - 1 && (
                <div className="w-4 h-px mb-4" style={{
                  background: s.status === 'done' ? 'rgba(34,197,94,0.5)' : 'var(--border-color)',
                }} />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ===== 后跟踪：上市后公司自身实时行情卡 =====
export function IpoListingCard({ project, quote, loading }) {
  if (!project.listed || !project.code) {
    return (
      <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(148,163,184,0.3)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-sm">📈</span>
          <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>上市后跟踪（后跟踪）</span>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 上市后自动激活</span>
        </div>
        <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          {project.name} 尚未上市（代码待定）。上市后本模块将自动拉取该公司自身实时行情：
          现价、涨跌、较发行价涨跌幅、市值估算，无需手动配置。
        </div>
      </div>
    );
  }

  const price = quote?.price;
  const chg = quote?.changePct;
  const isUp = chg != null && chg >= 0;
  const vsIssue = project.issuePrice && price != null
    ? (price / project.issuePrice - 1) * 100
    : null;
  const marketCap = project.totalShares && price != null
    ? price * project.totalShares
    : null;
  const fmtCap = (v) => {
    if (v == null) return '待补充';
    if (v >= 1e12) return (v / 1e12).toFixed(2) + '万亿';
    return (v / 1e8).toFixed(0) + '亿';
  };
  const fmtChgPct = (v) => {
    if (v == null) return '—';
    return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  };

  const cards = [
    {
      label: '现价', value: price != null ? price.toFixed(2) : '—',
      color: 'var(--text-primary)', sub: project.code,
    },
    {
      label: '涨跌幅', value: fmtChgPct(chg),
      color: isUp ? '#ef4444' : '#22c55e', sub: isUp ? '▲' : '▼',
    },
    {
      label: '较发行价', value: vsIssue != null ? fmtChgPct(vsIssue) : (project.issuePrice ? '—' : '待补充'),
      color: vsIssue == null ? 'var(--text-muted)' : (vsIssue >= 0 ? '#ef4444' : '#22c55e'),
      sub: project.issuePrice ? `发行价 ${project.issuePrice}` : '发行价待补充',
    },
    {
      label: '估算市值', value: fmtCap(marketCap),
      color: 'var(--text-primary)', sub: project.totalShares ? '基于总股本' : '总股本待补充',
    },
  ];

  return (
    <div className="rounded-xl border p-3" style={{ borderColor: 'rgba(34,197,94,0.3)', background: 'var(--bg-card)' }}>
      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm">📈</span>
        <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>上市后跟踪（后跟踪）</span>
        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 实时行情 {project.code}</span>
        {loading && !quote && <span className="text-[10px]" style={{ color: '#f59e0b' }}>加载中…</span>}
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
        {cards.map((c, i) => (
          <div key={i} className="rounded-lg border p-2" style={{ borderColor: `${c.color}25`, background: `${c.color}08` }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{c.label}</div>
            <div className="text-base font-bold" style={{ color: c.color }}>{c.value}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{c.sub}</div>
          </div>
        ))}
      </div>
      <div className="mt-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
        数据来源：后端实时行情接口 · 发行价/总股本请在 src/data/ipoProjects.js 补全以启用对应指标
      </div>
    </div>
  );
}
