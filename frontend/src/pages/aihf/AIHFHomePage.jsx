import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';

const REPO = 'https://github.com/virattt/ai-hedge-fund';

export default function AIHFHomePage() {
  const [status, setStatus] = useState(null);
  const [starting, setStarting] = useState(false);
  const [keyInput, setKeyInput] = useState('');
  const [saving, setSaving] = useState(false);
  const [keyMsg, setKeyMsg] = useState('');
  const [restarting, setRestarting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState(null);
  const [tab, setTab] = useState('app'); // 'app' = 策略后台, 'reports' = 分析控制台
  const timer = useRef(null);

  const checkStatus = async () => {
    try {
      const r = await fetch('/api/aihf/status');
      const d = await r.json();
      setStatus(d);
    } catch {
      setStatus({ running: false, has_market_key: false });
    }
  };

  useEffect(() => {
    checkStatus();
    timer.current = setInterval(checkStatus, 5000);
    return () => clearInterval(timer.current);
  }, []);

  const start = async () => {
    setStarting(true);
    try {
      await fetch('/api/aihf/start', { method: 'POST' });
      for (let i = 0; i < 12; i++) {
        await new Promise((res) => setTimeout(res, 1500));
        const d = await (await fetch('/api/aihf/status')).json();
        if (d.running) { setStatus(d); break; }
      }
    } finally {
      setStarting(false);
    }
  };

  const saveKey = async () => {
    if (!keyInput.trim()) return;
    setSaving(true);
    setKeyMsg('');
    setRestarting(true);
    try {
      const r = await fetch('/api/aihf/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ key: keyInput.trim() }),
      });
      const d = await r.json();
      setStatus((s) => ({ ...(s || {}), has_market_key: !!d.has_market_key }));
      setKeyMsg(d.restarted ? '✅ 已保存，后端重启中…' : '✅ 已保存');
      setKeyInput('');
    } catch (e) {
      setKeyMsg('❌ 保存失败：' + e.message);
    } finally {
      setSaving(false);
      setTimeout(() => setRestarting(false), 4000);
    }
  };

  const running = status?.running;
  const hasKey = status?.has_market_key;

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

  const testBanner = (r) => {
    if (!r) return null;
    const isAmber = r.state === 'no_credits';
    const bg = r.ok
      ? 'color-mix(in srgb, var(--accent-green) 12%, transparent)'
      : isAmber ? 'color-mix(in srgb, var(--accent-amber) 14%, transparent)'
      : 'color-mix(in srgb, var(--accent-red) 12%, transparent)';
    const fg = r.ok ? 'var(--accent-green)' : isAmber ? 'var(--accent-amber)' : 'var(--accent-red)';
    const icon = r.ok ? '✅ ' : isAmber ? '⚠️ ' : '❌ ';
    return (
      <div className="text-xs px-2.5 py-1.5 rounded-md" style={{ background: bg, color: fg }}>
        {icon}{r.message}
        {isAmber && (
          <a href="https://financialdatasets.ai" target="_blank" rel="noopener noreferrer"
             className="ml-1 underline" style={{ color: 'var(--accent-blue)' }}>去充值 →</a>
        )}
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* Hero */}
      <div className="premium-card hero-grad fade-in p-4 flex items-center gap-3">
        <div className="text-3xl">🦅</div>
        <div>
          <h1 className="text-xl font-bold gradient-text">AI Hedge Fund</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            多智能体投资军团 · 12 位大师 Agent + 内置回测 · LLM 走本机 8001 网关
          </p>
        </div>
        <a href={REPO} target="_blank" rel="noopener noreferrer"
           className="magnetic ml-auto text-xs px-2.5 py-1 rounded-md border transition-colors"
           style={{ borderColor: 'var(--border-color)', color: 'var(--accent-blue)' }}>
          🔗 GitHub
        </a>
      </div>

      {/* 状态条 */}
      <div className="fade-in-2 flex items-center gap-3 flex-wrap">
        {running ? (
          <span className="text-xs px-2.5 py-1 rounded-md flex items-center gap-2"
                style={{ background: 'color-mix(in srgb, var(--accent-green) 15%, transparent)', color: 'var(--accent-green)' }}>
            <span className="pulse-dot" /> 后端运行中
          </span>
        ) : (
          <span className="text-xs px-2.5 py-1 rounded-md flex items-center gap-2"
                style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
            <span className="pulse-dot amber" /> 后端未启动
          </span>
        )}
        {!running && (
          <button onClick={start} disabled={starting}
            className="magnetic text-xs px-3 py-1 rounded-md text-white disabled:opacity-60"
            style={{ background: 'var(--accent-blue)' }}>
            {starting ? '启动中…' : '▶ 启动后端'}
          </button>
        )}
        <a href="/_aihf/" target="_blank" rel="noopener noreferrer"
          className="magnetic text-xs px-2.5 py-1 rounded-md border" style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}>
          在浏览器打开
        </a>
      </div>

      {/* 行情 Key 提示 / 配置 */}
      {!hasKey && (
        <div className="fade-in-2 premium-card p-4 space-y-3" style={{ borderColor: 'color-mix(in srgb, var(--accent-amber) 45%, var(--border-color))' }}>
          <div className="flex items-start gap-2">
            <span className="text-lg">⚠️</span>
            <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
              <b>缺行情数据源 Key</b>：AI Hedge Fund 跑真实分析需 <code>FINANCIAL_DATASETS_API_KEY</code>
              （来自 financialdatasets.ai，免费注册）。LLM 已接本机 8001 网关，与此 Key 无关。
              填入后保存将自动重启后端使其生效。
            </div>
          </div>
          <div className="flex items-center gap-2">
            <input value={keyInput} onChange={(e) => setKeyInput(e.target.value)}
              placeholder="粘贴 FINANCIAL_DATASETS_API_KEY"
              className="flex-1 rounded-md px-2.5 py-1.5 text-xs outline-none"
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
            <button onClick={saveKey} disabled={saving || !keyInput.trim()}
              className="magnetic text-xs px-3 py-1.5 rounded-md text-white disabled:opacity-60"
              style={{ background: 'var(--accent-blue)' }}>
              {saving ? '保存中…' : '💾 保存并重启'}
            </button>
          </div>
          {keyMsg && <div className="text-xs" style={{ color: keyMsg.startsWith('✅') ? 'var(--accent-green)' : 'var(--accent-red)' }}>{keyMsg}</div>}
        </div>
      )}
      {hasKey && (
        <div className="fade-in-2 space-y-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs px-2.5 py-1 rounded-md flex items-center gap-2 w-fit"
                  style={{ background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)', color: 'var(--accent-green)' }}>
              <span className="pulse-dot" /> 已配置行情数据源 Key
            </span>
            <button onClick={testConn} disabled={testing}
              className="magnetic text-xs px-3 py-1 rounded-md border disabled:opacity-60"
              style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}>
              {testing ? '测试中…' : '🔌 测试行情连通性'}
            </button>
          </div>
          {testBanner(testResult)}
        </div>
      )}

      {/* 主体：Tab 切换 —— 策略后台 / 分析控制台 */}
      <div className="fade-in-3 space-y-3">
        <div className="flex items-center gap-2 flex-wrap">
          <button onClick={() => setTab('app')}
            className="magnetic text-xs px-3 py-1.5 rounded-md transition-colors"
            style={tab === 'app'
              ? { background: 'var(--accent-blue)', color: '#fff' }
              : { border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
            🦅 策略后台
          </button>
          <button onClick={() => setTab('reports')}
            className="magnetic text-xs px-3 py-1.5 rounded-md transition-colors"
            style={tab === 'reports'
              ? { background: 'var(--accent-blue)', color: '#fff' }
              : { border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
            📊 分析控制台
          </button>
          {tab === 'reports' && (
            <span className="text-xs px-2 py-0.5 rounded-md"
                  style={{ background: 'color-mix(in srgb, var(--accent-green) 12%, transparent)', color: 'var(--accent-green)' }}>
              静态数据 · 无需后端
            </span>
          )}
        </div>

        {tab === 'reports' ? (
          <div className="iframe-frame" style={{ height: '74vh' }}>
            <iframe src="/_aihf_reports/_dashboard/index.html" title="AIHF 分析控制台"
              className="w-full h-full" style={{ border: 'none', background: '#fff' }} />
          </div>
        ) : running ? (
          <div className="iframe-frame relative" style={{ height: '74vh' }}>
            {restarting && (
              <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'rgba(255,255,255,0.72)' }}>
                <span className="text-xs px-3 py-1.5 rounded-md" style={{ background: 'var(--bg-card)', color: 'var(--text-secondary)' }}>后端重启中…</span>
              </div>
            )}
            <iframe src="/_aihf/" title="AI Hedge Fund" className="w-full h-full" style={{ border: 'none', background: '#fff' }} />
          </div>
        ) : (
          <div className="premium-card p-8 text-center">
            <div className="text-4xl mb-3">🦅</div>
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>
              AIHF 后端尚未启动。点击上方「启动后端」即可在 AIROBOT 内嵌运行（前端已托管于 <code>/_aihf/</code>）。
            </p>
            <p className="text-xs mt-2" style={{ color: 'var(--text-muted)' }}>
              启动后此页自动切换为实时 Web 界面。真实分析另需行情 Key（见上方提示）。<br />
              也可直接切到「📊 分析控制台」查看离线报告与多标的基本面对比（无需后端）。
            </p>
          </div>
        )}
      </div>

      <Link to="/panorama" className="text-xs" style={{ color: 'var(--text-muted)' }}>← 返回 AIROBOT 主页</Link>
    </div>
  );
}
