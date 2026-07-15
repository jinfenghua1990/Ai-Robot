import { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

// 计算需要提醒的事项：离线服务 + AIHF 缺行情 Key
function computeIssues(services) {
  const issues = [];
  for (const s of services) {
    if (s.status === 'down') {
      issues.push({ key: s.key, label: s.label, level: 'error', msg: '服务离线', path: s.path });
    } else if (s.key === 'aihf' && s.has_market_key === false) {
      issues.push({ key: s.key, label: s.label, level: 'warn', msg: '缺行情 Key（无法跑真实分析）', path: s.path });
    }
  }
  return issues;
}

export default function SystemCheckBanner() {
  const [issues, setIssues] = useState([]);
  const [dismissed, setDismissed] = useState(false);
  const [checked, setChecked] = useState(false);
  const navigate = useNavigate();
  const hadIssues = useRef(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      const { ok, data } = await apiFetch('/api/services/status');
      if (!alive || !ok || !data || !Array.isArray(data.services)) return;
      const next = computeIssues(data.services);
      // 问题清空时重置「已忽略」状态，便于下次再出现时重新提示
      if (next.length === 0 && hadIssues.current) setDismissed(false);
      hadIssues.current = next.length > 0;
      setIssues(next);
      setChecked(true);
    };
    load();
    const t = setInterval(load, 30000);
    return () => { alive = false; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!checked || dismissed || issues.length === 0) return null;

  const hasError = issues.some((i) => i.level === 'error');
  const accent = hasError ? 'var(--accent-red)' : 'var(--accent-amber)';
  const icon = hasError ? '⚠️' : '🔔';

  return (
    <div
      className="fade-in flex items-center gap-2.5 px-3 py-2 mx-3 md:mx-4 mt-3 rounded-xl border premium-card"
      style={{
        borderColor: accent,
        background: hasError
          ? 'color-mix(in srgb, var(--accent-red) 7%, var(--bg-card))'
          : 'color-mix(in srgb, var(--accent-amber) 9%, var(--bg-card))',
      }}
    >
      <span className="text-base shrink-0">{icon}</span>
      <div className="flex-1 min-w-0 text-xs" style={{ color: 'var(--text-primary)' }}>
        <span className="font-semibold">系统自检：</span>
        {issues.map((i, idx) => (
          <span key={i.key}>
            {idx > 0 && <span style={{ color: 'var(--text-muted)' }}> · </span>}
            {i.path ? (
              <a
                onClick={(e) => { e.preventDefault(); navigate(i.path); }}
                href={i.path}
                className="cursor-pointer hover:underline"
                style={{ color: accent }}
              >
                {i.label} {i.msg}
              </a>
            ) : (
              <span style={{ color: accent }}>{i.label} {i.msg}</span>
            )}
          </span>
        ))}
      </div>
      <button
        onClick={() => setDismissed(true)}
        className="shrink-0 px-1.5 py-0.5 rounded text-xs transition-colors"
        style={{ color: 'var(--text-muted)' }}
        title="忽略本次提示"
      >
        ✕
      </button>
    </div>
  );
}
