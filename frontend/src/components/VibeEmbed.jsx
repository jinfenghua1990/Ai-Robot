import { useEffect, useRef, useState } from 'react';

function getAirobotTheme() {
  if (typeof window === 'undefined') return 'light';
  return localStorage.getItem('airobot-theme') || 'light';
}

export default function VibeEmbed({ path, title }) {
  const iframeRef = useRef(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
  }, [path]);

  // 通过 BroadcastChannel + storage 事件同步主题，不再轮询
  useEffect(() => {
    const channel = typeof BroadcastChannel !== 'undefined' ? new BroadcastChannel('airobot-theme') : null;

    const syncTheme = () => {
      const next = getAirobotTheme();
      const iframe = iframeRef.current;
      if (iframe && iframe.contentWindow) {
        iframe.contentWindow.postMessage({ type: 'airobot-theme', theme: next }, window.location.origin);
      }
    };

    // 初始同步一次
    syncTheme();

    // storage 事件：跨标签页主题切换
    window.addEventListener('storage', syncTheme);

    // BroadcastChannel：同标签页内主题切换（localStorage.setItem 不触发自身 storage 事件）
    if (channel) {
      channel.onmessage = syncTheme;
    }

    return () => {
      window.removeEventListener('storage', syncTheme);
      if (channel) channel.close();
    };
  }, []);

  // src 不再携带 theme 参数，避免主题切换导致 iframe 整体重载
  const src = `/_vibe${path}${path.includes('?') ? '&' : '?'}embedded=true`;

  return (
    <div className="relative w-full h-full">
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--bg-color)' }}>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载 Vibe-Research 页面...</div>
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
