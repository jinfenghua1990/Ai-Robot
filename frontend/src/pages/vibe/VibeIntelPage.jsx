import VibeEmbed from '../../components/VibeEmbed';
import AihfMarketKey from '../../components/AihfMarketKey';

export default function VibeIntelPage() {
  return (
    <div className="fade-in">
      <div className="premium-card iframe-frame flex flex-col overflow-hidden" style={{ height: 'calc(100vh - 132px)' }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <div className="flex items-center gap-2">
            <span className="text-base">📡</span>
            <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>Vibe 资讯雷达</span>
          </div>
        </div>
        <AihfMarketKey />
        <div style={{ flex: 1, minHeight: 0 }}>
          <VibeEmbed path="/intel" title="Vibe 资讯雷达" />
        </div>
      </div>
    </div>
  );
}
