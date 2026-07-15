import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

export default function HealthStrip() {
  const [services, setServices] = useState([]);
  const navigate = useNavigate();

  const load = async () => {
    const { ok, data } = await apiFetch('/api/services/status');
    if (ok && data && Array.isArray(data.services)) setServices(data.services);
  };

  useEffect(() => {
    load();
    const t = setInterval(load, 10000);
    return () => clearInterval(t);
  }, []);

  const upCount = services.filter((s) => s.status === 'up').length;
  const downCount = services.filter((s) => s.status === 'down').length;
  const statusColor = downCount > 0 ? 'var(--accent-red)' : (services.length > 0 && upCount === services.length ? 'var(--accent-green)' : 'var(--accent-amber)');

  return (
    <button
      onClick={() => navigate('/quality')}
      className="flex items-center gap-1 px-2 py-1 rounded-md text-xs border transition-colors"
      style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
      title="前往系统与服务健康"
    >
      <span>🛡️</span>
      <span>系统</span>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: statusColor, boxShadow: `0 0 5px ${statusColor}` }} />
      <span style={{ color: downCount ? 'var(--accent-red)' : 'var(--text-muted)' }}>
        {services.length ? `${upCount}/${services.length}` : '…'}
      </span>
    </button>
  );
}
