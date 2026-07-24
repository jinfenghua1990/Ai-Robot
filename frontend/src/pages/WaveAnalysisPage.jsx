import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';

/* ─── Color palette (CSS variables for theme support) ───────────── */
const C = {
  bg:       'var(--bg-primary)',
  card:     'var(--bg-card)',
  border:   'var(--border-color)',
  borderL:  'var(--border-color)',
  text:     'var(--text-primary)',
  textDim:  'var(--text-secondary)',
  textMute: 'var(--text-muted)',
  heading:  'var(--text-primary)',
  blue:     'var(--accent-blue)',
  purple:   'var(--accent-purple)',
  orange:   'var(--accent-orange)',
  green:    'var(--accent-green)',
  red:      'var(--accent-red)',
  yellow:   'var(--accent-amber)',
};

/* ─── helpers ─────────────────────────────────────────────────────── */
const fmt = (v, d = 2) => {
  if (v === null || v === undefined || v === '') return '--';
  const n = Number(v);
  return isNaN(n) ? '--' : n.toLocaleString('zh-CN', { minimumFractionDigits: d, maximumFractionDigits: d });
};

const pctClass = (v) => Number(v) >= 0 ? C.green : C.red;

function getPhaseTagStyle(phase) {
  if (phase?.includes('A浪') || phase?.includes('C浪')) {
    return { background: 'rgba(220,38,38,0.08)', color: C.red, border: '1px solid rgba(220,38,38,0.15)' };
  }
  if (phase?.includes('B浪')) {
    return { background: 'rgba(22,163,74,0.08)', color: C.green, border: '1px solid rgba(22,163,74,0.15)' };
  }
  return { background: 'rgba(124,58,237,0.08)', color: C.purple, border: '1px solid rgba(124,58,237,0.15)' };
}

function getSignalColor(signal) {
  if (signal === '减仓' || signal === '清仓') return C.red;
  if (signal === '短多' || signal === '加仓') return C.green;
  return C.textDim;
}

function getRiskBadge(risk) {
  if (risk === '高') return { background: 'rgba(220,38,38,0.08)', color: C.red };
  if (risk === '中') return { background: 'rgba(202,138,4,0.08)', color: C.yellow };
  return { background: 'rgba(22,163,74,0.08)', color: C.green };
}

function getVerdictColor(verdict) {
  if (!verdict) return C.textDim;
  if (verdict.includes('谨慎') || verdict.includes('防守')) return C.yellow;
  if (verdict.includes('积极') || verdict.includes('进攻')) return C.green;
  return C.textDim;
}

function getDotColor(dot) {
  if (dot === 'green') return C.green;
  if (dot === 'red') return C.red;
  if (dot === 'yellow') return C.yellow;
  if (dot === 'purple') return C.purple;
  return C.textDim;
}

/* ─── Sub-components ──────────────────────────────────────────────── */

function Header({ tradeDate, generatedAt, onRun, onRefresh, running, loading }) {
  return (
    <div style={{
      textAlign: 'center', padding: '40px 20px 30px',
      borderBottom: `1px solid ${C.border}`, marginBottom: 32
    }}>
      <h1 style={{
        fontSize: 28, fontWeight: 700, marginBottom: 8,
        background: `linear-gradient(135deg, ${C.blue}, ${C.purple}, ${C.orange})`,
        WebkitBackgroundClip: 'text', WebkitTextFillColor: 'transparent',
        backgroundClip: 'text'
      }}>
        四大指数波段研判报告
      </h1>
      <div style={{ color: C.textDim, fontSize: 14 }}>
        波浪理论 + 斐波那契时空测算 · 独立分析
      </div>
      {tradeDate && (
        <div style={{
          display: 'inline-block', marginTop: 12, padding: '4px 14px',
          borderRadius: 20, background: C.card, border: `1px solid ${C.borderL}`,
          color: C.textDim, fontSize: 12
        }}>
          数据截止 {tradeDate} 收盘
        </div>
      )}
      <div style={{ marginTop: 16, display: 'flex', justifyContent: 'center', gap: 10 }}>
        <button
          onClick={onRun}
          disabled={running}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '6px 14px', background: 'var(--accent-amber)', color: '#fff',
            border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600,
            cursor: running ? 'not-allowed' : 'pointer', opacity: running ? 0.6 : 1,
          }}
        >
          <span className={running ? 'animate-pulse' : ''} style={{ fontSize: 13 }}>⚡</span>
          {running ? '运行中...' : '运行分析'}
        </button>
        <button
          onClick={onRefresh}
          disabled={loading}
          style={{
            display: 'inline-flex', alignItems: 'center', gap: 4,
            padding: '6px 14px', background: 'var(--accent-cyan)', color: '#fff',
            border: 'none', borderRadius: 6, fontSize: 12, fontWeight: 600,
            cursor: loading ? 'not-allowed' : 'pointer', opacity: loading ? 0.6 : 1,
          }}
        >
          <span className={loading ? 'animate-spin' : ''} style={{ fontSize: 13, display: 'inline-block' }}>🔄</span>
          刷新
        </button>
      </div>
    </div>
  );
}

function IndexGrid({ signals }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 24, marginBottom: 24
    }}>
      <h2 style={{
        fontSize: 18, color: C.heading, marginBottom: 16,
        paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8
      }}>
        <span style={{ fontSize: 20 }}>📡</span> 指数实时行情
      </h2>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16
      }}>
        {signals.map((s, i) => <IndexBox key={i} signal={s} />)}
      </div>
    </div>
  );
}

function IndexBox({ signal: s }) {
  const phaseTag = getPhaseTagStyle(s.phase);
  const chgColor = pctClass(s.change_pct);
  const chg5dColor = pctClass(s.change_5d);
  const chg20dColor = pctClass(s.change_20d);
  const ytdColor = pctClass(s.change_ytd);

  return (
    <div style={{
      background: C.bg, border: `1px solid ${C.border}`,
      borderRadius: 10, padding: 18, position: 'relative', overflow: 'hidden'
    }}>
      {/* Phase tag */}
      <div style={{
        position: 'absolute', top: 12, right: 12,
        padding: '2px 10px', borderRadius: 12, fontSize: 11, fontWeight: 600,
        ...phaseTag
      }}>
        {s.phase}
      </div>
      {/* Name */}
      <div style={{ fontSize: 16, fontWeight: 700, color: C.heading, marginBottom: 4 }}>
        {s.name} <span style={{ fontSize: 12, color: C.textDim, fontWeight: 400 }}>{s.code}</span>
      </div>
      {/* Price */}
      <div style={{ fontSize: 28, fontWeight: 800, color: chgColor, margin: '6px 0' }}>
        {fmt(s.close)}
      </div>
      {/* Change */}
      <div style={{
        fontSize: 14, fontWeight: 600, padding: '2px 8px', borderRadius: 4,
        display: 'inline-block', color: chgColor,
        background: Number(s.change_pct) >= 0 ? 'rgba(22,163,74,0.06)' : 'rgba(220,38,38,0.06)'
      }}>
        {Number(s.change_pct) >= 0 ? '+' : ''}{Number(s.change_pct).toFixed(2)}%
      </div>
      {/* Meta grid */}
      <div style={{
        fontSize: 12, color: C.textDim, marginTop: 8,
        display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 12px'
      }}>
        <span>5日: <span style={{ color: chg5dColor }}>{Number(s.change_5d) >= 0 ? '+' : ''}{Number(s.change_5d).toFixed(2)}%</span></span>
        <span>20日: <span style={{ color: chg20dColor }}>{Number(s.change_20d) >= 0 ? '+' : ''}{Number(s.change_20d).toFixed(2)}%</span></span>
        <span>年初至今: <span style={{ color: ytdColor }}>{Number(s.change_ytd) >= 0 ? '+' : ''}{Number(s.change_ytd).toFixed(2)}%</span></span>
        <span>回撤: {fmt(s.retracement_pct, 1)}%</span>
      </div>
    </div>
  );
}

function DecisionCard({ data, signals }) {
  const verdictColor = getVerdictColor(data.verdict);
  return (
    <div style={{
      background: `linear-gradient(135deg, var(--bg-surface), ${C.bg})`,
      border: `1px solid ${C.borderL}`, borderRadius: 14,
      padding: 28, textAlign: 'center', marginBottom: 24
    }}>
      <div style={{ fontSize: 14, color: C.textDim, marginBottom: 8 }}>
        📊 综合研判结论
      </div>
      <div style={{
        fontSize: 36, fontWeight: 900, margin: '16px 0 8px',
        letterSpacing: 2, color: verdictColor
      }}>
        {data.verdict}
      </div>
      {data.verdict_summary && (
        <div style={{ fontSize: 16, color: C.textDim, marginBottom: 16 }}>
          {data.verdict_summary}
        </div>
      )}
      <div style={{
        marginTop: 16, display: 'flex', justifyContent: 'center',
        gap: 24, flexWrap: 'wrap'
      }}>
        {signals.map((s, i) => (
          <div key={i} style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 12, color: C.textDim }}>{s.short || s.name}</div>
            <div style={{ color: getSignalColor(s.signal), fontWeight: 700 }}>{s.signal}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function WaveTimeline({ timeline }) {
  if (!timeline || timeline.length === 0) return null;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12, margin: '16px 0' }}>
      {timeline.map((item, i) => (
        <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'flex-start' }}>
          <div style={{
            width: 10, height: 10, borderRadius: '50%',
            marginTop: 6, flexShrink: 0, background: getDotColor(item.dot)
          }} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 12, color: C.textDim }}>{item.time}</div>
            <div style={{ fontSize: 13, color: C.text }}>{item.text}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

function FibTable({ levels }) {
  if (!levels || levels.length === 0) return null;
  return (
    <table style={{
      width: '100%', borderCollapse: 'collapse', fontSize: 13, margin: '10px 0'
    }}>
      <thead>
        <tr>
          {['回撤位', '点位', '含义', '状态'].map(h => (
            <th key={h} style={{
              background: C.border, color: C.textDim, padding: '8px 10px',
              textAlign: h === '点位' ? 'right' : 'left', fontWeight: 600
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {levels.map((lv, i) => {
          const isActive = lv.is_active;
          const txtStyle = isActive
            ? { color: C.orange, fontWeight: 700 }
            : { color: C.text };
          const rowBg = isActive ? 'rgba(194,65,12,0.06)' : 'transparent';
          return (
            <tr key={i} style={{ background: rowBg }}>
              <td style={{ padding: '7px 10px', borderBottom: `1px solid ${C.card}`, ...txtStyle }}>{lv.level}</td>
              <td style={{ padding: '7px 10px', borderBottom: `1px solid ${C.card}`, textAlign: 'right', fontFamily: 'monospace', ...txtStyle }}>{fmt(lv.price)}</td>
              <td style={{ padding: '7px 10px', borderBottom: `1px solid ${C.card}`, ...txtStyle }}>{lv.desc}</td>
              <td style={{ padding: '7px 10px', borderBottom: `1px solid ${C.card}`, ...txtStyle }}>{lv.status}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function TimeWindowsBox({ windows }) {
  if (!windows || windows.length === 0) return null;
  return (
    <SummaryBox>
      {windows.map((w, i) => {
        const isKey = w.status?.includes('关键');
        const isDone = w.status?.includes('已过');
        return (
          <li key={i} style={{
            padding: '6px 0', fontSize: 13,
            borderBottom: `1px solid ${C.border}`,
            listStyle: 'none'
          }}>
            T+<strong>{w.window}</strong>（{w.date}）
            <span style={{
              display: 'inline-block', marginLeft: 8,
              padding: '2px 8px', borderRadius: 10, fontSize: 11, fontWeight: 600,
              background: isKey ? 'rgba(202,138,4,0.08)' : isDone ? 'rgba(22,163,74,0.08)' : 'rgba(202,138,4,0.08)',
              color: isKey ? C.yellow : isDone ? C.green : C.yellow,
            }}>
              {w.status}
            </span>
          </li>
        );
      })}
    </SummaryBox>
  );
}

function SummaryBox({ children, title, titleColor }) {
  return (
    <div style={{
      background: `linear-gradient(135deg, rgba(29,78,216,0.03), rgba(124,58,237,0.03))`,
      border: `1px solid ${C.borderL}`, borderRadius: 12, padding: 20, margin: '16px 0'
    }}>
      {title && (
        <h3 style={{ color: titleColor || C.purple, marginBottom: 10, fontSize: 15, margin: '0 0 10px' }}>{title}</h3>
      )}
      <ul style={{ listStyle: 'none', padding: 0, margin: 0 }}>
        {typeof children === 'string'
          ? children.split('\n').filter(Boolean).map((line, i) => (
              <li key={i} style={{
                padding: '6px 0', fontSize: 13,
                borderBottom: `1px solid ${C.border}`,
              }}>
                <span style={{ color: C.blue }}>{'> '}</span>{line}
              </li>
            ))
          : children
        }
      </ul>
    </div>
  );
}

function IndexDetailCard({ signal: s }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 24, marginBottom: 24
    }}>
      <h2 style={{
        fontSize: 18, color: C.heading, marginBottom: 16,
        paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8
      }}>
        <span style={{ fontSize: 20 }}>📈</span> {s.name} · 波浪结构与斐波那契测算
      </h2>

      {/* Wave structure timeline */}
      {s.timeline && s.timeline.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 15, color: C.blue, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
            🌊 波浪结构判定
          </h3>
          <WaveTimeline timeline={s.timeline} />
          {s.wave_notes && s.wave_notes.length > 0 && (
            <div style={{ fontSize: 12, color: C.textDim, padding: '2px 0' }}>
              💡 {s.wave_notes.join('；')}
            </div>
          )}
        </div>
      )}

      {/* Fibonacci retracement table */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: 15, color: C.blue, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          📐 斐波那契回撤测算
        </h3>
        <FibTable levels={s.fib_levels} />
      </div>

      {/* Time windows */}
      <div style={{ marginBottom: 20 }}>
        <h3 style={{ fontSize: 15, color: C.blue, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          ⏱️ 斐波那契时间窗口
        </h3>
        <TimeWindowsBox windows={s.time_windows} />
      </div>

      {/* Strategy / reasoning */}
      <div style={{ marginBottom: 0 }}>
        <h3 style={{ fontSize: 15, color: C.blue, marginBottom: 10, display: 'flex', alignItems: 'center', gap: 6 }}>
          🎯 观点与策略
        </h3>
        <SummaryBox title={`${s.phase} — 置信度 ${s.confidence}%`}>
          {s.reasoning && s.reasoning.map((r, i) => (
            <li key={i} style={{
              padding: '6px 0', fontSize: 13,
              borderBottom: i < s.reasoning.length - 1 ? `1px solid ${C.border}` : 'none',
              listStyle: 'none'
            }}>
              <span style={{ color: C.blue }}>{'> '}</span>{r}
            </li>
          ))}
        </SummaryBox>
      </div>
    </div>
  );
}

function RiskMatrix({ signals }) {
  return (
    <table style={{
      width: '100%', borderCollapse: 'collapse', fontSize: 13, margin: '10px 0'
    }}>
      <thead>
        <tr>
          {['指数', '波浪位置', '回撤幅度', '操作建议', '风险评级'].map(h => (
            <th key={h} style={{
              background: C.border, color: C.textDim, padding: 8,
              textAlign: h === '指数' ? 'left' : 'center', fontWeight: 600, fontSize: 12
            }}>{h}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {signals.map((s, i) => {
          const riskBadge = getRiskBadge(s.risk);
          return (
            <tr key={i}>
              <td style={{
                padding: 8, textAlign: 'left', fontWeight: 600,
                color: C.heading, borderBottom: `1px solid ${C.card}`
              }}>{s.short || s.name}</td>
              <td style={{
                padding: 8, textAlign: 'center',
                borderBottom: `1px solid ${C.card}`
              }}>{s.phase}</td>
              <td style={{
                padding: 8, textAlign: 'center',
                borderBottom: `1px solid ${C.card}`
              }}>{fmt(s.retracement_pct, 1)}%</td>
              <td style={{
                padding: 8, textAlign: 'center',
                borderBottom: `1px solid ${C.card}`,
                color: getSignalColor(s.signal)
              }}>{s.signal}</td>
              <td style={{
                padding: 8, textAlign: 'center',
                borderBottom: `1px solid ${C.card}`
              }}>
                <span style={{
                  display: 'inline-block', padding: '2px 8px',
                  borderRadius: 10, fontSize: 11, fontWeight: 600,
                  ...riskBadge
                }}>{s.risk}</span>
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

function ComparisonSection({ signals }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 24, marginBottom: 24
    }}>
      <h2 style={{
        fontSize: 18, color: C.heading, marginBottom: 16,
        paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8
      }}>
        <span style={{ fontSize: 20 }}>🔄</span> 波浪节奏对比
      </h2>
      <RiskMatrix signals={signals} />
    </div>
  );
}

function ConfidenceBar({ value }) {
  const bars = 10;
  const filled = Math.round((value / 100) * bars);
  const barColor = value >= 70 ? C.green : value >= 40 ? C.yellow : C.red;
  return (
    <div style={{ display: 'flex', gap: 4, marginTop: 4 }}>
      {Array.from({ length: bars }).map((_, i) => (
        <div key={i} style={{
          width: 20, height: 6, borderRadius: 3,
          background: i < filled ? barColor : C.border,
        }} />
      ))}
    </div>
  );
}

function OperationSuggestions({ signals }) {
  return (
    <div style={{
      background: C.card, border: `1px solid ${C.border}`,
      borderRadius: 12, padding: 24, marginBottom: 24
    }}>
      <h2 style={{
        fontSize: 18, color: C.heading, marginBottom: 16,
        paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
        display: 'flex', alignItems: 'center', gap: 8
      }}>
        <span style={{ fontSize: 20 }}>📋</span> 操作建议汇总
      </h2>
      <div style={{
        display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 16
      }}>
        {signals.map((s, i) => (
          <div key={i} style={{
            background: C.bg, border: `1px solid ${C.border}`,
            borderRadius: 10, padding: 18
          }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: C.heading }}>{s.name}</div>
            <div style={{ marginTop: 12 }}>
              <SignalRow label="操作方向" value={s.signal} valueColor={getSignalColor(s.signal)} />
              <SignalRow label="入场区间"
                value={s.entry_range ? `${fmt(s.entry_range[0])}~${fmt(s.entry_range[1])}` : '--'}
                valueColor={C.green} />
              <SignalRow label="止损位"
                value={s.stop_loss ? fmt(s.stop_loss) : '--'}
                valueColor={C.red} />
              <SignalRow label="目标位"
                value={s.targets && s.targets.length > 0 ? s.targets.map(t => fmt(t)).join(' / ') : '—'}
                valueColor={C.blue} />
              <SignalRow label="仓位"
                value={s.position ? `${s.position[0]}~${s.position[1]}成` : '--'} />
              <div style={{ marginTop: 8 }}>
                <div style={{ fontSize: 11, color: C.textDim, marginBottom: 4 }}>置信度</div>
                <ConfidenceBar value={s.confidence} />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function SignalRow({ label, value, valueColor }) {
  return (
    <div style={{
      display: 'flex', justifyContent: 'space-between',
      fontSize: 13, marginBottom: 6
    }}>
      <span style={{ color: C.textDim }}>{label}</span>
      <span style={{ fontWeight: 700, color: valueColor || C.text }}>{value}</span>
    </div>
  );
}

function Disclaimer({ generatedAt }) {
  return (
    <div style={{
      textAlign: 'center', color: C.textMute, fontSize: 12,
      padding: 20, borderTop: `1px solid ${C.border}`, marginTop: 32,
      lineHeight: 1.8
    }}>
      ⚠️ 本报告基于公开市场数据与技术分析方法，仅供学习研究参考，不构成任何投资建议或操作指导。<br />
      波浪理论与斐波那契分析属于概率性工具，存在主观判断成分，市场走势可能与预测相反。<br />
      投资有风险，决策需谨慎。数据来源：AIROBOT 本地数据库。<br />
      {generatedAt && <>报告生成时间：{generatedAt}</>}
    </div>
  );
}

/* ─── Main Component ──────────────────────────────────────────────── */

export default function WaveAnalysisPage({ embedded = false } = {}) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(false);

  const fetchData = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const { ok, data } = await apiFetch('/api/ops/wave-analysis');
      if (ok && data.ok) {
        setData(data.data);
        setError('');
      } else {
        setError(data?.error || '加载失败');
      }
    } catch (e) {
      setError('网络错误');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { fetchData(); }, [fetchData]);

  const handleRun = async () => {
    setRunning(true);
    try {
      const { ok, data } = await apiFetch('/api/ops/wave-analysis/run', { method: 'POST' });
      if (ok && data.ok) {
        setTimeout(() => fetchData(), 3000);
      }
    } catch (e) {
      console.error('Failed to run wave analysis:', e);
    } finally {
      setRunning(false);
    }
  };

  const signals = data?.data?.signals || [];

  return (
    <div style={{
      fontFamily: '-apple-system, "PingFang SC", "Microsoft YaHei", sans-serif',
      background: C.bg, color: C.text, lineHeight: 1.7,
      maxWidth: 1200, margin: '0 auto', padding: '24px 16px',
      minHeight: embedded ? 'auto' : '100vh'
    }}>
      {/* Header */}
      <Header
        tradeDate={data?.trade_date}
        generatedAt={data?.generated_at}
        onRun={handleRun}
        onRefresh={fetchData}
        running={running}
        loading={loading}
      />

      {/* Loading / Error */}
      {loading && (
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '80px 0' }}>
          <span className="animate-spin" style={{ fontSize: 32, color: C.blue, display: 'inline-block' }}>⏳</span>
          <span style={{ marginLeft: 8, color: C.textDim, fontSize: 14 }}>加载波浪分析数据...</span>
        </div>
      )}

      {error && !loading && (
        <div style={{
          background: 'rgba(220,38,38,0.05)', border: `1px solid rgba(220,38,38,0.15)`,
          borderRadius: 12, padding: '32px 16px', textAlign: 'center'
        }}>
          <span style={{ fontSize: 32, color: C.red, margin: '0 auto 8px', display: 'inline-block' }}>⚠️</span>
          <p style={{ fontSize: 14, color: C.red }}>{error}</p>
          <button
            onClick={fetchData}
            style={{
              marginTop: 12, padding: '6px 16px',
              background: 'rgba(220,38,38,0.1)', border: 'none',
              borderRadius: 6, color: C.red, fontSize: 12, fontWeight: 600,
              cursor: 'pointer'
            }}
          >
            重试
          </button>
        </div>
      )}

      {!loading && !error && data && signals.length > 0 && (
        <>
          {/* Index overview grid */}
          <IndexGrid signals={signals} />

          {/* Decision card */}
          <DecisionCard data={data} signals={signals} />

          {/* Per-index wave analysis cards */}
          {signals.map((s, i) => (
            <IndexDetailCard key={i} signal={s} />
          ))}

          {/* Comparison section */}
          <ComparisonSection signals={signals} />

          {/* Time confluence */}
          {data.time_confluence && data.time_confluence.length > 0 && (
            <div style={{
              background: C.card, border: `1px solid ${C.border}`,
              borderRadius: 12, padding: 24, marginBottom: 24
            }}>
              <h2 style={{
                fontSize: 18, color: C.heading, marginBottom: 16,
                paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
                display: 'flex', alignItems: 'center', gap: 8
              }}>
                <span style={{ fontSize: 20 }}>⏱️</span> 时间窗口共振
              </h2>
              <SummaryBox>
                {data.time_confluence.map((item, i) => {
                  const isConfluence = item.includes('多指数共振');
                  return (
                    <li key={i} style={{
                      padding: '6px 0', fontSize: 13,
                      borderBottom: `1px solid ${C.border}`,
                      listStyle: 'none',
                      color: isConfluence ? C.orange : 'inherit',
                      fontWeight: isConfluence ? 600 : 400
                    }}>
                      {isConfluence && <span style={{ marginRight: 4 }}>⚡</span>}
                      {item}
                    </li>
                  );
                })}
              </SummaryBox>
            </div>
          )}

          {/* Operation suggestions */}
          <OperationSuggestions signals={signals} />

          {/* Core insights */}
          <div style={{
            background: C.card, border: `1px solid ${C.border}`,
            borderRadius: 12, padding: 24, marginBottom: 24
          }}>
            <h2 style={{
              fontSize: 18, color: C.heading, marginBottom: 16,
              paddingBottom: 10, borderBottom: `1px solid ${C.border}`,
              display: 'flex', alignItems: 'center', gap: 8
            }}>
              <span style={{ fontSize: 20 }}>💡</span> 核心观点
            </h2>
            <SummaryBox>
              {signals.map((s, i) => (
                <li key={i} style={{
                  padding: '6px 0', fontSize: 13,
                  borderBottom: i < signals.length - 1 ? `1px solid ${C.border}` : 'none',
                  listStyle: 'none'
                }}>
                  <span style={{ color: C.blue }}>{'> '}</span>
                  {s.short || s.name}：{s.phase}，回撤{fmt(s.retracement_pct, 1)}%
                  {s.reasoning && s.reasoning.length > 0 ? ` — ${s.reasoning[0]}` : ''}
                </li>
              ))}
            </SummaryBox>
          </div>

          {/* Disclaimer */}
          <Disclaimer generatedAt={data.generated_at} />
        </>
      )}
    </div>
  );
}
