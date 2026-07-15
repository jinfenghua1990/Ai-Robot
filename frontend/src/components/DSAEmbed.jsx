import { useEffect, useRef, useState } from 'react';

function getAirobotTheme() {
  if (typeof window === 'undefined') return 'light';
  return localStorage.getItem('airobot-theme') || 'light';
}

export default function DSAEmbed({ path, title }) {
  const iframeRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(getAirobotTheme);

  useEffect(() => {
    setLoading(true);
    setError(null);
  }, [path]);

  // 监听 AIROBOT 主题变化，同步给 iframe 内的 DSA
  useEffect(() => {
    const syncTheme = () => {
      const next = getAirobotTheme();
      setTheme(next);
      const iframe = iframeRef.current;
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'airobot-theme', theme: next }, window.location.origin);
      }
    };
    window.addEventListener('storage', syncTheme);
    const interval = setInterval(syncTheme, 2000);
    return () => {
      window.removeEventListener('storage', syncTheme);
      clearInterval(interval);
    };
  }, []);

  // 超时检测：15秒后仍 loading 则标记异常
  useEffect(() => {
    if (!loading) return;
    const t = setTimeout(() => {
      if (loading) setError('页面加载超时，DSA 后端可能未启动');
    }, 15000);
    return () => clearTimeout(t);
  }, [loading, path]);

  const handleRetry = () => {
    setLoading(true);
    setError(null);
    setTheme(t => t);
    if (iframeRef.current) {
      iframeRef.current.src = iframeRef.current.src;
    }
  };

  const src = `/_dsa${path}${path.includes('?') ? '&' : '?'}theme=${theme}&embedded=true`;

  return (
    <div className="relative w-full h-full">
      {loading && !error && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载 DSA 页面...</div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
          <div className="flex flex-col items-center gap-3">
            <span className="text-sm" style={{ color: 'var(--text-danger, #E24B4A)' }}>{error}</span>
            <button onClick={handleRetry}
              style={{
                padding: '5px 14px', borderRadius: 8, border: '0.5px solid var(--border-color, #ddd)',
                background: 'transparent', fontSize: 12, cursor: 'pointer',
                color: 'var(--text-secondary, #888)',
              }}>
              重新加载
            </button>
          </div>
        </div>
      )}
      <iframe
        ref={iframeRef}
        src={src}
        title={title}
        className="w-full h-full border-0"
        onLoad={() => setLoading(false)}
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-downloads allow-popups-to-escape-sandbox"
      />
    </div>
  );
}