import { useEffect, useState, useCallback } from 'react';
import DSAEmbed from '../../components/DSAEmbed';
import { apiFetch } from '../../utils/request';

export default function DSAHomePage() {
  const [dsaUp, setDsaUp] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const checkStatus = useCallback(async () => {
    try {
      const res = await apiFetch('/api/v1/health');
      setDsaUp(res?.ok === true || res?.status === 'ok');
    } catch {
      setDsaUp(false);
    }
  }, []);

  useEffect(() => {
    checkStatus();
    const timer = setInterval(checkStatus, 15000);
    return () => clearInterval(timer);
  }, [checkStatus]);

  const handleRefresh = () => {
    setRefreshing(true);
    checkStatus().finally(() => setTimeout(() => setRefreshing(false), 1000));
  };

  const statusDot = dsaUp === null ? 'pulse-dot amber' : dsaUp ? 'pulse-dot' : 'pulse-dot red';
  const statusLabel = dsaUp === null ? '检测中…' : dsaUp ? '在线' : '离线';

  return (
    <div className="fade-in">
      <div className="premium-card iframe-frame flex flex-col overflow-hidden" style={{ height: 'calc(100vh - 132px)' }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex items-center gap-2">
            <span className="text-base">🤖</span>
            <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>DSA 智能分析</span>
          </div>
          <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-muted)' }}>
            <span className={statusDot} />
            <span style={{ color: dsaUp ? 'var(--text-secondary)' : 'var(--text-danger, #E24B4A)' }}>
              {statusLabel}
            </span>
            <button onClick={handleRefresh} disabled={refreshing}
              style={{
                padding: '3px 10px', borderRadius: 6, border: '0.5px solid var(--border-color, #ddd)',
                background: 'transparent', cursor: refreshing ? 'default' : 'pointer',
                opacity: refreshing ? 0.5 : 1,
                color: 'var(--text-secondary, #888)',
              }}>
              {refreshing ? '↻' : '↻ 刷新'}
            </button>
          </div>
        </div>
        <div style={{ flex: 1, minHeight: 0 }}>
          {dsaUp === false ? (
            <div className="flex items-center justify-center w-full h-full" style={{ background: 'var(--bg-color)' }}>
              <div className="flex flex-col items-center gap-3">
                <span className="text-3xl">🤖</span>
                <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>DSA 后端未启动</p>
                <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  启动方式：launchctl kickstart gui/$(id -u)/com.airobot.dsa
                </p>
                <button onClick={checkStatus}
                  style={{
                    padding: '6px 18px', borderRadius: 8, border: '0.5px solid var(--border-color)',
                    background: 'transparent', fontSize: 13, cursor: 'pointer',
                    color: 'var(--text-secondary)',
                  }}>
                  重试检测
                </button>
              </div>
            </div>
          ) : (
            <DSAEmbed path="/" title="DSA 智能分析" />
          )}
        </div>
      </div>
    </div>
  );
}
