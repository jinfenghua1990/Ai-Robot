import { useParams, useNavigate } from 'react-router-dom';
import TAgentsHomePage from './tagents/TAgentsHomePage';

const TABS = [
  { key: 'tagents', label: 'TradingAgents', icon: '🕸️' },
  { key: 'aihf', label: 'AI Hedge Fund', icon: '🦅' },
  { key: 'openclaw', label: 'OpenClaw', icon: '🔧' },
];

export default function AIAgentTeamPage() {
  const { tab } = useParams();
  const navigate = useNavigate();
  const activeTab = TABS.some(t => t.key === tab) ? tab : 'tagents';

  return (
    <div className="flex flex-col h-full" style={{ minHeight: 0 }}>
      {/* 标题 */}
      <div className="flex items-center justify-between mb-2 shrink-0">
        <div>
          <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
            🤖 智能体投资团
          </h2>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            AI Agent 驱动的智能投资工具箱
          </p>
        </div>
      </div>

      {/* Tab 栏（点击在页内切换，不跳原页面） */}
      <div className="flex gap-1 mb-2 shrink-0 border-b" style={{ borderColor: 'var(--border-color)' }}>
        {TABS.map(t => {
          const active = activeTab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => navigate('/ai-agents/' + t.key)}
              className="flex items-center gap-1 px-3 py-2 text-sm font-medium transition-colors"
              style={{
                color: active ? 'var(--text-primary)' : 'var(--text-muted)',
                borderBottom: active ? '2px solid #a855f7' : '2px solid transparent',
                marginBottom: '-1px',
              }}
            >
              <span>{t.icon}</span>
              {t.label}
            </button>
          );
        })}
      </div>

      {/* Tab 内容（页内展示） */}
      <div className="flex-1 overflow-hidden" style={{ minHeight: 0 }}>
        {activeTab === 'tagents' && (
          <div className="h-full overflow-y-auto" style={{ minHeight: 0 }}>
            <TAgentsHomePage />
          </div>
        )}
        {activeTab === 'aihf' && (
          <iframe
            src="/_aihf/"
            title="AI Hedge Fund"
            className="w-full h-full"
            style={{ border: 'none' }}
          />
        )}
        {activeTab === 'openclaw' && (
          <iframe
            src="/_openclaw/"
            title="OpenClaw Control"
            className="w-full h-full"
            style={{ border: 'none' }}
          />
        )}
      </div>
    </div>
  );
}
