/**
 * 市场情绪阶段条 — 显示当前市场处于 6 阶段中的哪个阶段
 * 6 阶段: 冰点 → 修复 → 发酵 → 高潮 → 分歧 → 退潮
 * 每阶段对应仓位建议: 2-3成 / 4成 / 6成 / 7成 / 4-5成 / 3成
 *
 * 数据源: /api/market-stage (从 StockFlow 实时统计)
 */
import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const STAGE_ORDER = ['冰点', '修复', '发酵', '高潮', '分歧', '退潮'];

const STAGE_COLORS = {
  '冰点': '#3b82f6',
  '修复': '#06b6d4',
  '发酵': '#f59e0b',
  '高潮': '#ef4444',
  '分歧': '#a855f7',
  '退潮': '#6b7280',
};

export default function MarketStageBar({ date }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      setLoading(true);
      const url = date ? `/api/market-stage?date=${date}` : '/api/market-stage';
      const { ok, data: d } = await apiFetch(url);
      if (!cancelled) {
        if (ok) setData(d);
        setLoading(false);
      }
    };
    load();
    return () => { cancelled = true; };
  }, [date]);

  if (loading && !data) {
    return (
      <div className="rounded-lg p-3 animate-pulse" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', height: 80 }} />
    );
  }

  if (!data || data.error) {
    return (
      <div className="rounded-lg p-3 text-xs" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
        市场情绪阶段数据暂不可用{data?.error ? `: ${data.error}` : ''}
      </div>
    );
  }

  const { stage, score, description, position, color, signals = [], drivers = [], metrics = {}, trade_date } = data;
  const currentIdx = STAGE_ORDER.indexOf(stage);

  const tooltip = [
    `📅${trade_date || ''}`,
    `阶段:${stage} (得分${score})`,
    description,
    position ? `建议仓位:${position}` : '',
    metrics.limit_up != null ? `涨停:${metrics.limit_up} 跌停:${metrics.limit_down || 0} 炸板:${metrics.broken || 0}` : '',
    metrics.up != null ? `上涨:${metrics.up} 下跌:${metrics.down} 平盘:${metrics.flat || 0}` : '',
    metrics.heat_value != null ? `热度:${metrics.heat_value}` : '',
    metrics.broken_rate != null ? `炸板率:${(metrics.broken_rate * 100).toFixed(1)}%` : '',
    signals.length ? `信号:${signals.join('、')}` : '',
  ].filter(Boolean).join(' | ');

  return (
    <div className="rounded-lg p-3" style={{ background: 'var(--bg-card)', border: `1px solid ${color}40` }} title={tooltip}>
      {/* 阶段进度条 */}
      <div className="flex items-center gap-1 mb-2">
        {STAGE_ORDER.map((s, i) => {
          const isActive = i === currentIdx;
          const isPassed = i < currentIdx;
          const sColor = STAGE_COLORS[s];
          return (
            <div
              key={s}
              className="flex-1 text-center py-1 px-2 rounded text-[11px] font-bold transition-all"
              style={{
                background: isActive ? sColor : (isPassed ? `${sColor}20` : 'var(--bg-secondary)'),
                color: isActive ? '#fff' : (isPassed ? sColor : 'var(--text-muted)'),
                border: `1px solid ${isActive ? sColor : 'transparent'}`,
                transform: isActive ? 'scale(1.05)' : 'scale(1)',
              }}
              title={s}
            >
              {s}
            </div>
          );
        })}
      </div>

      {/* 当前阶段详情 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-3">
          <div className="text-lg font-bold" style={{ color }}>
            {stage} <span className="text-sm">({score}分)</span>
          </div>
          <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>
            {description}
          </div>
        </div>
        <div className="flex items-center gap-2">
          {position && (
            <span className="px-2 py-1 rounded text-xs font-bold" style={{ background: `${color}20`, color, border: `1px solid ${color}40` }}>
              💰 建议仓位 {position}
            </span>
          )}
          {metrics.limit_up != null && (
            <span className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
              涨停 <b style={{ color: '#ef4444' }}>{metrics.limit_up}</b> · 跌停 <b style={{ color: '#22c55e' }}>{metrics.limit_down || 0}</b> · 上涨 <b style={{ color: '#ef4444' }}>{metrics.up}</b> · 下跌 <b style={{ color: '#22c55e' }}>{metrics.down}</b> · 热度 <b style={{ color }}>{metrics.heat_value}</b>
            </span>
          )}
        </div>
      </div>

      {/* 信号标签 */}
      {signals.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2">
          {signals.slice(0, 6).map((sig, i) => (
            <span key={i} className="px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}>
              {sig}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
