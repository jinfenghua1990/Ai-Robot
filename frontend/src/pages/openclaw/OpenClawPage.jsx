import { useState, useRef, useEffect } from 'react';

// OpenClaw / robot3 控制面板 — 经 9000 同源代理 /_openclaw/ 加载（不再直连 18789）。
export default function OpenClawPage() {
  const iframeRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => { setLoading(true); setError(null); }, []);

  return (
    <div className="space-y-4">
      <div className="premium-card hero-grad fade-in p-4 flex items-center gap-3">
        <div className="text-3xl">🔧</div>
        <div>
          <h1 className="text-xl font-bold gradient-text">OpenClaw 控制面板</h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            robot3 / OpenClaw 控制台 · 经 9000 同源代理 <code>/_openclaw/</code> 加载（不再直连端口）
          </p>
        </div>
        <a href="/_openclaw/" target="_blank" rel="noopener noreferrer"
           className="magnetic ml-auto text-xs px-2.5 py-1 rounded-md border" style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}>
          ↗ 新窗口打开
        </a>
      </div>

      <div className="fade-in-2 iframe-frame relative" style={{ height: '76vh' }}>
        {loading && (
          <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载控制面板…</div>
          </div>
        )}
        {error && (
          <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
            <div className="text-sm text-red-500">加载失败：{error}</div>
          </div>
        )}
        <iframe
          ref={iframeRef}
          src="/_openclaw/"
          title="OpenClaw 控制面板"
          className="w-full h-full border-0"
          onLoad={() => setLoading(false)}
          onError={() => setError('iframe 加载异常')}
        />
      </div>
    </div>
  );
}
