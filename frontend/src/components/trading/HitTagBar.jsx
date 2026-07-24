/**
 * 6 大命中雷达标签栏（只显示已命中的维度，未命中不渲染 → 减少灰色视觉噪点）
 *
 * 注：strategy（策略）已下线——与顶部 strategyTags（📊 BS-XXX / 🔥 游资龙头）数据源完全相同，
 * 都是 BSDailyScan 表，重复显示造成视觉冗余。策略命中由顶部 strategyTags 承担显示。
 */

export const HIT_TAG_CONFIG = [
  { key: 'yuzi', icon: '🎯', label: '游资', color: '#a855f7', action: '游资共振净买入，关注次日溢价' },
  { key: 'trend', icon: '📈', label: '趋势', color: '#ef4444', action: '多头排列（MA5>MA20>MA60）或 20日新高突破' },
  { key: 'capital', icon: '💰', label: '资金', color: '#ef4444', action: '主力爆买创30天新高，防踏空' },
  { key: 'popularity', icon: '🔥', label: '人气', color: '#f97316', action: '板块爆发人气龙头，打板' },
  { key: 'support', icon: '🛡️', label: '承接', color: '#eab308', action: '昨日上榜今日V反，深水低吸' },
  { key: 'accumulation', icon: '🧲', label: '吸筹', color: '#ef4444', action: '股东户数减少，筹码集中' },
];

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
