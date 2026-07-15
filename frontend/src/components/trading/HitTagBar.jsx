/**
 * 7 大命中雷达标签栏（只显示已命中的维度，未命中不渲染 → 减少灰色视觉噪点）
 */

export const HIT_TAG_CONFIG = [
  { key: 'yuzi', icon: '🎯', label: '游资', color: '#a855f7', action: '游资共振净买入，关注次日溢价' },
  { key: 'strategy', icon: '🤖', label: '策略', color: '#3b82f6', action: '量化策略命中，按模式死磕' },
  { key: 'trend', icon: '📈', label: '趋势', color: '#22c55e', action: '多头排列，回踩均线低吸' },
  { key: 'capital', icon: '💰', label: '资金', color: '#ef4444', action: '主力爆买创30天新高，防踏空' },
  { key: 'popularity', icon: '🔥', label: '人气', color: '#f97316', action: '板块爆发人气龙头，打板' },
  { key: 'support', icon: '🛡️', label: '承接', color: '#eab308', action: '昨日上榜今日V反，深水低吸' },
  { key: 'accumulation', icon: '🧲', label: '吸筹', color: '#06b6d4', action: '股东户数减少，筹码集中' },
];

const TAG_MAP = Object.fromEntries(HIT_TAG_CONFIG.map(t => [t.key, t]));

export default function HitTagBar({ tags = [] }) {
  const hitSet = new Set(tags || []);

  const hitTags = HIT_TAG_CONFIG.filter(cfg => hitSet.has(cfg.key));

  if (hitTags.length === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-1.5 mt-1">
      {hitTags.map(cfg => (
        <span
          key={cfg.key}
          className="inline-flex items-center gap-0.5 px-2 py-1 rounded text-[11px] font-bold whitespace-nowrap"
          style={{
            background: `${cfg.color}1a`,
            color: cfg.color,
            border: `1px solid ${cfg.color}55`,
          }}
          title={cfg.action}
        >
          <span>{cfg.icon}</span>
          <span>{cfg.label}</span>
        </span>
      ))}
    </div>
  );
}
