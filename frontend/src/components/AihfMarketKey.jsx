import { useState, useEffect, useRef } from 'react';

// AI Hedge Fund 行情数据源 Key 状态条：独立轮询 /api/aihf/status，
// 缺 Key 时渲染琥珀色配置卡（可就地粘贴 FINANCIAL_DATASETS_API_KEY 并保存重启），
// 已配置时渲染绿色状态药丸。与全局 SystemCheckBanner 解耦，确保稳定可见。
export default function AihfMarketKey() {
  const [status, setStatus] = useState(null);
  const [keyInput, setKeyInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState('');
  const [restarting, setRestarting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const timer = useRef(null);

  const check = async () => {
    try {
      const d = await (await fetch('/api/aihf/status')).json();
      setStatus(d);
    } catch {
      setStatus({ running: false, has_market_key: false });
    }
  };

  useEffect(() => {
    check();
    timer.current = setInterval(check, 8000);
    return () => clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (!keyInput.trim()) return;
    setSaving(true);
    setMsg('');
    setRestarting(true);
    try {
      const r = await fetch('/api/aihf/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: keyInput.trim() }),
      });
      const d = await r.json();
      setStatus((s) => ({ ...(s || {}), has_market_key: !!d.has_market_key }));
      setMsg(d.restarted ? '✅ 已保存，后端重启中…' : '✅ 已保存');
      setKeyInput('');
    } catch (e) {
      setMsg('❌ 保存失败：' + e.message);
    } finally {
      setSaving(false);
      setTimeout(() => setRestarting(false), 4000);
    }
  };

  const hasKey = status?.has_market_key;
  const running = status?.running;

  const testConn = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const d = await (await fetch('/api/aihf/test-connection')).json();
      setTestResult(d);
    } catch (e) {
      setTestResult({ ok: false, state: 'error', message: '请求失败：' + e.message });
    } finally {
      setTesting(false);
    }
  };

  if (hasKey) {
    const r = testResult;
    const isAmber = r?.state === 'no_credits';
    const bannerBg = r?.ok
      ? 'color-mix(in srgb, var(--accent-green) 12%, transparent)'
      : isAmber ? 'color-mix(in srgb, var(--accent-amber) 14%, transparent)'
      : 'color-mix(in srgb, var(--accent-red) 12%, transparent)';
    const bannerFg = r?.ok ? 'var(--accent-green)' : isAmber ? 'var(--accent-amber)' : 'var(--accent-red)';
    return (
      <div className="px-3 py-2 space-y-1.5">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className="text-xs px-2 py-1 rounded-md inline-flex items-center gap-1.5"
            style={{ background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)', color: 'var(--accent-green)' }}
          >
            <span className="pulse-dot" />
            AIHF 已配置行情数据源 Key{running ? ' · 后端在线' : ''}
          </span>
          <button
            onClick={testConn}
            disabled={testing}
            className="magnetic text-xs px-2.5 py-1 rounded-md border disabled:opacity-60"
            style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
          >
            {testing ? '测试中…' : '🔌 测试连通性'}
          </button>
        </div>
        {r && (
          <div className="text-xs px-2 py-1 rounded-md" style={{ background: bannerBg, color: bannerFg }}>
            {r.ok ? '✅ ' : isAmber ? '⚠️ ' : '❌ '}
            {r.message}
            {isAmber && (
              <a href="https://financialdatasets.ai" target="_blank" rel="noopener noreferrer"
                 className="ml-1 underline" style={{ color: 'var(--accent-blue)' }}>去充值 →</a>
            )}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      className="px-3 py-2 border-b"
      style={{
        borderColor: 'color-mix(in srgb, var(--accent-amber) 40%, var(--border-color))',
        background: 'color-mix(in srgb, var(--accent-amber) 6%, transparent)',
      }}
    >
      <div className="flex items-start gap-2">
        <span className="text-base leading-5">⚠️</span>
        <div className="flex-1 min-w-0">
          <div className="text-xs mb-1.5" style={{ color: 'var(--text-secondary)' }}>
            <b>AI Hedge Fund 缺行情 Key</b>：跑真实分析需 <code>FINANCIAL_DATASETS_API_KEY</code>
            （<a href="https://financialdatasets.ai" target="_blank" rel="noopener noreferrer" style={{ color: 'var(--accent-blue)' }}>financialdatasets.ai</a> 免费注册）。
            LLM 已走本机 8001 网关，与此 Key 无关。填好保存将自动重启后端生效。
          </div>
          <div className="flex items-center gap-2">
            <input
              value={keyInput}
              onChange={(e) => setKeyInput(e.target.value)}
              placeholder="粘贴 FINANCIAL_DATASETS_API_KEY"
              className="flex-1 rounded-md px-2.5 py-1.5 text-xs outline-none"
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}
            />
            <button
              onClick={save}
              disabled={saving || !keyInput.trim()}
              className="magnetic text-xs px-3 py-1.5 rounded-md text-white disabled:opacity-60"
              style={{ background: 'var(--accent-blue)' }}
            >
              {saving ? '保存中…' : '💾 保存并重启'}
            </button>
          </div>
          {msg && (
            <div className="text-xs mt-1" style={{ color: msg.startsWith('✅') ? 'var(--accent-green)' : 'var(--accent-red)' }}>
              {msg}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
