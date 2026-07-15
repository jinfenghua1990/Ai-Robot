import { useState, useEffect, useRef } from 'react';
import { Link } from 'react-router-dom';

const REPO = 'https://github.com/TauricResearch/TradingAgents-CN';
const PRESETS = ['NVDA', 'AAPL', 'TSLA', '600519', 'BTC'];

export default function TAgentsHomePage() {
  const [ticker, setTicker] = useState('NVDA');
  const [tradeDate, setTradeDate] = useState('2024-05-10');
  const [assetType, setAssetType] = useState('stock');
  const [running, setRunning] = useState(false);
  const [runId, setRunId] = useState(null);
  const [log, setLog] = useState('');
  const [decision, setDecision] = useState('');
  const [elapsed, setElapsed] = useState(0);
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  const elapsedTimer = useRef(null);
  const logRef = useRef(null);

  useEffect(() => () => { clearInterval(timer.current); clearInterval(elapsedTimer.current); }, []);

  // 日志自动滚到底
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [log]);

  const poll = async (id) => {
    try {
      const r = await fetch(`/api/tagents/log/${id}`);
      const d = await r.json();
      setLog(d.log || '');
      if (!d.running) {
        setRunning(false);
        clearInterval(timer.current);
        clearInterval(elapsedTimer.current);
        const m = (d.log || '').match(/FINAL DECISION[\s\S]*?END\s*={5,}/);
        if (m) setDecision(m[0]);
      }
    } catch { /* ignore */ }
  };

  const run = async () => {
    if (running) return;
    setDecision('');
    setLog('提交分析任务…');
    setElapsed(0);
    setRunning(true);
    elapsedTimer.current = setInterval(() => setElapsed((s) => s + 1), 1000);
    try {
      const r = await fetch('/api/tagents/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ticker, trade_date: tradeDate, asset_type: assetType }),
      });
      const d = await r.json();
      if (d.run_id) {
        setRunId(d.run_id);
        timer.current = setInterval(() => poll(d.run_id), 2000);
      } else {
        setLog('启动失败：' + JSON.stringify(d));
        setRunning(false);
        clearInterval(elapsedTimer.current);
      }
    } catch (e) {
      setLog('请求错误：' + e.message);
      setRunning(false);
      clearInterval(elapsedTimer.current);
    }
  };

  const copyDecision = async () => {
    try {
      await navigator.clipboard.writeText(decision);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch { /* ignore */ }
  };

  const fmt = (s) => `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;

  return (
    <div className="max-w-4xl mx-auto space-y-4">
      {/* Hero */}
      <div className="premium-card hero-grad fade-in p-4 flex items-center gap-3">
        <div className="text-3xl">🕸️</div>
        <div>
          <h1 className="text-xl font-bold gradient-text">TradingAgents</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>多智能体虚拟投研团队 · 辩论投票式决策 · LLM 走本机 8001 网关</p>
        </div>
        <a href={REPO} target="_blank" rel="noopener noreferrer"
           className="magnetic ml-auto text-xs px-2.5 py-1 rounded-md border transition-colors"
           style={{ borderColor: 'var(--border-color)', color: 'var(--accent-blue)' }}>🔗 GitHub</a>
      </div>

      {/* 运行表单 */}
      <div className="premium-card fade-in-2 p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="text-xs block">
            <span style={{ color: 'var(--text-secondary)' }}>标的代码</span>
            <input value={ticker} onChange={(e) => setTicker(e.target.value.toUpperCase())}
              className="mt-1 w-full rounded-md px-2 py-1.5 text-sm outline-none"
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
          </label>
          <label className="text-xs block">
            <span style={{ color: 'var(--text-secondary)' }}>交易日期</span>
            <input value={tradeDate} onChange={(e) => setTradeDate(e.target.value)} placeholder="YYYY-MM-DD"
              className="mt-1 w-full rounded-md px-2 py-1.5 text-sm outline-none"
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }} />
          </label>
          <label className="text-xs block">
            <span style={{ color: 'var(--text-secondary)' }}>资产类型</span>
            <select value={assetType} onChange={(e) => setAssetType(e.target.value)}
              className="mt-1 w-full rounded-md px-2 py-1.5 text-sm outline-none"
              style={{ background: 'var(--bg-primary)', border: '1px solid var(--border-color)', color: 'var(--text-primary)' }}>
              <option value="stock">stock</option>
              <option value="crypto">crypto</option>
            </select>
          </label>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>快捷：</span>
          {PRESETS.map((p) => (
            <span key={p} className={`chip ${ticker.toUpperCase() === p ? 'active' : ''}`}
              onClick={() => { setTicker(p); setAssetType(p === 'BTC' ? 'crypto' : 'stock'); }}>
              {p}
            </span>
          ))}
        </div>
        <div className="flex items-center gap-3">
          <button onClick={run} disabled={running}
            className="magnetic text-sm px-4 py-2 rounded-md text-white disabled:opacity-60"
            style={{ background: 'var(--accent-blue)' }}>
            {running ? '分析中…（可切走，日志自动刷新）' : '🚀 运行分析'}
          </button>
          {running && (
            <span className="text-xs px-2 py-1 rounded-md flex items-center gap-2" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
              <span className="pulse-dot" /> {fmt(elapsed)}
            </span>
          )}
        </div>
        <p className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
          多智能体分析通常需数分钟，日志实时滚动。A 股代码如 600519（贵州茅台）亦可。
        </p>
      </div>

      {/* 实时日志 */}
      {log && (
        <div className="premium-card fade-in-3 overflow-hidden">
          <div className="px-3 py-1.5 text-xs flex items-center gap-2" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
            运行日志 {runId ? `· ${runId}` : ''} {running && <span className="pulse-dot" />}
          </div>
          <pre ref={logRef} className="text-xs p-3 overflow-auto max-h-72" style={{ background: 'var(--bg-primary)', color: 'var(--text-secondary)' }}>{log}</pre>
        </div>
      )}

      {/* 最终决策 */}
      {decision && (
        <div className="premium-card fade-in-3 p-4" style={{ borderColor: 'var(--accent-blue)' }}>
          <div className="flex items-center justify-between mb-2">
            <div className="text-sm font-medium" style={{ color: 'var(--accent-blue)' }}>📊 最终决策</div>
            <button onClick={copyDecision}
              className="magnetic text-xs px-2 py-1 rounded-md border" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
              {copied ? '✅ 已复制' : '📋 复制'}
            </button>
          </div>
          <pre className="text-xs whitespace-pre-wrap overflow-auto" style={{ color: 'var(--text-primary)' }}>{decision}</pre>
        </div>
      )}

      <Link to="/panorama" className="text-xs" style={{ color: 'var(--text-muted)' }}>← 返回 AIROBOT 主页</Link>
    </div>
  );
}
