import { useState, useEffect } from 'react';

// LLM 网关状态页 — 经 9000 同源代理 /_llm_api/ 访问本机 8001 网关，
// 不再需要直连端口。展示各模型/provider 健康度，便于监控免费网关可用性。
export default function LLMGatewayPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [lastCheck, setLastCheck] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await fetch('/_llm_api/api/status', { cache: 'no-store' });
      if (!r.ok) throw new Error('HTTP ' + r.status);
      setData(await r.json());
      setLastCheck(new Date().toLocaleTimeString('zh-CN'));
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); }, []);

  const models = data?.models || [];
  const tally = models.reduce((acc, m) => {
    (m.providers || []).forEach((p) => {
      if (p.health === 'up') acc.up++;
      else if (p.health === 'down') acc.down++;
      else acc.unknown++;
    });
    return acc;
  }, { up: 0, down: 0, unknown: 0 });

  const healthStyle = (h) => {
    if (h === 'up') return { bg: 'color-mix(in srgb, var(--accent-green) 16%, transparent)', fg: 'var(--accent-green)' };
    if (h === 'down') return { bg: 'color-mix(in srgb, var(--accent-red) 14%, transparent)', fg: 'var(--accent-red)' };
    return { bg: 'color-mix(in srgb, var(--text-muted) 18%, transparent)', fg: 'var(--text-muted)' };
  };

  return (
    <div className="space-y-4">
      <div className="premium-card hero-grad fade-in p-4 flex items-center gap-3">
        <div className="text-3xl">🔌</div>
        <div>
          <h1 className="text-xl font-bold gradient-text">LLM 网关状态</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            本机免费模型网关 · 经 9000 同源代理 <code>/_llm_api/</code> 访问（不再直连 8001）
          </p>
        </div>
        <button onClick={load} disabled={loading}
          className="magnetic ml-auto text-xs px-3 py-1.5 rounded-md text-white disabled:opacity-60"
          style={{ background: 'var(--accent-blue)' }}>
          {loading ? '检测中…' : '🔄 刷新状态'}
        </button>
      </div>

      {error && (
        <div className="fade-in-2 premium-card p-4 text-xs" style={{ borderColor: 'color-mix(in srgb, var(--accent-red) 45%, var(--border-color))', color: 'var(--accent-red)' }}>
          ⚠️ 网关代理不可达：{error}。请确认本机 LLM 网关（com.gino.free-llm-gateway）已启动。
        </div>
      )}

      {!error && (
        <div className="fade-in-2 flex items-center gap-3 flex-wrap">
          <span className="text-xs px-2.5 py-1 rounded-md" style={{ background: 'color-mix(in srgb, var(--accent-green) 14%, transparent)', color: 'var(--accent-green)' }}>
            🟢 可用 {tally.up}
          </span>
          <span className="text-xs px-2.5 py-1 rounded-md" style={{ background: 'color-mix(in srgb, var(--accent-red) 12%, transparent)', color: 'var(--accent-red)' }}>
            🔴 不可用 {tally.down}
          </span>
          <span className="text-xs px-2.5 py-1 rounded-md" style={{ background: 'color-mix(in srgb, var(--text-muted) 18%, transparent)', color: 'var(--text-muted)' }}>
            ⚪ 未知 {tally.unknown}
          </span>
          {lastCheck && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>最近检测 {lastCheck}</span>}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {models.map((m, i) => (
          <div key={m.name + i} className="premium-card p-4 fade-in-3">
            <div className="flex items-center justify-between mb-2">
              <b className="text-sm" style={{ color: 'var(--text-primary)' }}>{m.name}</b>
              {m.active_provider && (
                <span className="text-xs px-2 py-0.5 rounded-md" style={{ background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)', color: 'var(--accent-green)' }}>
                  活跃: {m.active_provider}
                </span>
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              {(m.providers || []).map((p, j) => {
                const st = healthStyle(p.health);
                return (
                  <div key={p.provider + j} className="flex items-center gap-2 text-xs flex-wrap">
                    <span className="px-2 py-0.5 rounded-md" style={{ background: st.bg, color: st.fg }}>
                      {p.health === 'up' ? '🟢' : p.health === 'down' ? '🔴' : '⚪'} {p.provider}
                    </span>
                    <span style={{ color: 'var(--text-muted)' }}>{p.model}</span>
                    {p.has_key === false && <span style={{ color: 'var(--accent-amber)' }}>· 缺 Key</span>}
                    {p.rate_limited && <span style={{ color: 'var(--accent-amber)' }}>· 限流</span>}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {!loading && models.length === 0 && !error && (
        <div className="premium-card p-8 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
          暂无模型数据。
        </div>
      )}
    </div>
  );
}
