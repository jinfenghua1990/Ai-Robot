import { useEffect, useRef, useState } from 'react';

function getAirobotTheme() {
  if (typeof window === 'undefined') return 'light';
  return localStorage.getItem('airobot-theme') || 'light';
}

export default function HermesEmbed({ path, title }) {
  const iframeRef = useRef(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [theme, setTheme] = useState(getAirobotTheme);

  useEffect(() => {
    setLoading(true);
    setError(null);
  }, [path]);

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

  // Hermes 使用 HashRouter：/_hermes/?theme=dark&embedded=true#/today
  const src = `/_hermes/?theme=${theme}&embedded=true#${path}`;

  return (
    <div className="relative w-full h-full">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载 Hermes 页面...</div>
        </div>
      )}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
          <div className="text-sm text-red-500">加载失败：{error}</div>
        </div>
      )}
      <iframe
        key={src}
        ref={iframeRef}
        src={src}
        title={title}
        className="w-full h-full border-0"
        onLoad={() => setLoading(false)}
        onError={() => setError('iframe 加载异常')}
        sandbox="allow-same-origin allow-scripts allow-popups allow-forms allow-downloads"
      />
    </div>
  );
}