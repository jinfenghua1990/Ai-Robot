import { useMemo } from 'react';

const channels = [
  { name: '主网关', role: '当前使用', status: '已配置', model: '当前模型', tone: 'var(--accent-green)' },
  { name: '备用渠道 01', role: '故障切换', status: '已配置', model: 'Fallback 模型', tone: 'var(--accent-blue)' },
  { name: '备用渠道 02', role: '故障切换', status: '未启用', model: '—', tone: 'var(--text-muted)' },
];

export default function LlmGatewayPage() {
  const masked = useMemo(() => '••••••••••••••••', []);
  return (
    <div className="max-w-5xl space-y-3 fade-in">
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <div className="text-[10px] uppercase tracking-wider" style={{ color: 'var(--accent-blue)' }}>LLM Gateway</div>
            <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>模型网关与轮动</h2>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>统一读取服务端配置 · 密钥与网关地址不在页面展示</div>
          </div>
          <div className="flex items-center gap-1.5 text-xs"><span className="h-2 w-2 rounded-full" style={{ background: 'var(--accent-green)' }} />网关已配置</div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {[
          ['当前渠道', '主网关'], ['备用渠道', '1 个'], ['轮动策略', '故障切换'], ['密钥状态', '已配置'],
        ].map(([label, value]) => <div key={label} className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div><div className="mt-1 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>{value}</div></div>)}
      </div>

      <section className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}><div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>渠道轮动队列</div><button className="rounded border px-2 py-1 text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>测试全部渠道</button></div>
        <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>{channels.map(channel => <div key={channel.name} className="grid grid-cols-[1.2fr_1fr_0.8fr_1fr_auto] items-center gap-2 px-3 py-2 text-xs" style={{ borderColor: 'var(--border-color)' }}><div className="font-medium" style={{ color: 'var(--text-primary)' }}>{channel.name}</div><div style={{ color: 'var(--text-secondary)' }}>{channel.role}</div><div style={{ color: channel.tone }}>{channel.status}</div><div style={{ color: 'var(--text-muted)' }}>{channel.model}</div><button className="rounded border px-2 py-1 text-[11px]" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>测试</button></div>)}</div>
      </section>

      <section className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>服务端配置摘要</div>
        <div className="mt-2 grid grid-cols-1 md:grid-cols-3 gap-2 text-xs"><div><span style={{ color: 'var(--text-muted)' }}>API Key</span><div className="mt-1 font-mono" style={{ color: 'var(--text-secondary)' }}>{masked}</div></div><div><span style={{ color: 'var(--text-muted)' }}>Base URL</span><div className="mt-1" style={{ color: 'var(--text-secondary)' }}>已隐藏</div></div><div><span style={{ color: 'var(--text-muted)' }}>Model</span><div className="mt-1" style={{ color: 'var(--text-secondary)' }}>服务端已配置</div></div></div>
      </section>
    </div>
  );
}
