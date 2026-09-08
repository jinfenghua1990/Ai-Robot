/**
 * 6 大命中雷达标签栏（只显示已命中的维度，未命中不渲染 → 减少灰色视觉噪点）
 *
 * 注：strategy（策略）已下线——与顶部 strategyTags（📊 BS-XXX / 🔥 游资龙头）数据源完全相同，
 * 都是 BSDailyScan 表，重复显示造成视觉冗余。策略命中由顶部 strategyTags 承担显示。
 */

import { HIT_TAG_CONFIG } from './hitTagConfig';

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
