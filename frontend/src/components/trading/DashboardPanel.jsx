import { useState } from 'react';

const DIMENSIONS = [
  { key: 'trend_strength', label: '趋势强度', icon: '📈' },
  { key: 'capital_momentum', label: '资金动能', icon: '💰' },
  { key: 'sector_resonance', label: '板块共振', icon: '🔄' },
  { key: 'institution_signal', label: '机构信号', icon: '🏦' },
  { key: 'volume_health', label: '量能健康度', icon: '📊' },
  { key: 'volatility_health', label: '波动健康度', icon: '〰️' },
  { key: 'relative_strength', label: '相对强度', icon: '⚡' },
  { key: 'drawdown_status', label: '回撤状态', icon: '📉' },
];

function barColor(v) {
  if (v >= 70) return '#22c55e';
  if (v >= 50) return '#eab308';
  if (v >= 30) return '#f97316';
  return '#ef4444';
}

function fmtWan(val) {
  if (val == null) return '—';
  const abs = Math.abs(val);
  if (abs >= 1e8) return `${(val / 1e8).toFixed(2)}亿`;
  return `${(val / 1e4).toFixed(0)}万`;
}

export default function DashboardPanel({ dashboard, loading }) {
  const [detailOpen, setDetailOpen] = useState(false);

  if (loading) {
    return (
      <div className="rounded-lg border p-4 text-center text-xs"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)', background: 'var(--bg-card)' }}>
        ⏳ 加载仪表盘...
      </div>
    );
  }

  if (!dashboard || dashboard.error) {
    return (
      <div className="rounded-lg border p-4 text-center text-xs"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)', background: 'var(--bg-card)' }}>
        {dashboard?.error || '暂无决策仪表盘数据'}
      </div>
    );
  }

  const {
    action_label, action_color,
    trend_strength, capital_momentum, sector_resonance,
    volume_health, volatility_health, relative_strength, drawdown_status,
    institution_signal,
    sector_flow, institution_flow, date,
  } = dashboard;

  const hasFlow = sector_flow || (institution_flow && Object.keys(institution_flow).length > 0);

  return (
    <div className="rounded-lg border p-4 space-y-3"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>

      {/* 顶部操作建议标签 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <span
            className="px-3 py-1.5 rounded-lg text-sm font-bold"
            style={{ background: `${action_color}22`, color: action_color, border: `1.5px solid ${action_color}50` }}
          >
            {action_label}
          </span>
          {date && (
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              数据日期：{date}
            </span>
          )}
        </div>
        {hasFlow && (
          <button
            onClick={() => setDetailOpen(!detailOpen)}
            className="text-[10px] underline"
            style={{ color: 'var(--text-muted)' }}
          >
            {detailOpen ? '收起资金详情' : '展开资金详情'}
          </button>
        )}
      </div>

      {/* 8 维进度条 */}
      <div className="grid grid-cols-2 gap-x-3 gap-y-2">
        {DIMENSIONS.map(d => {
          const val = dashboard[d.key] ?? 50;
          const c = barColor(val);
          return (
            <div key={d.key} className="flex items-center gap-1.5 min-w-0">
              <span className="text-xs flex-shrink-0">{d.icon}</span>
              <span className="text-[10px] flex-shrink-0 w-14 truncate" style={{ color: 'var(--text-secondary)' }}>
                {d.label}
              </span>
              <div className="flex-1 h-1.5 rounded-full overflow-hidden min-w-0" style={{ background: 'var(--bg-muted)' }}>
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${val}%`, background: c }}
                />
              </div>
              <span className="text-[10px] font-medium w-7 text-right flex-shrink-0" style={{ color: c }}>
                {Math.round(val)}
              </span>
            </div>
          );
        })}
      </div>

      {/* 资金详情折叠区 */}
      {detailOpen && hasFlow && (
        <div className="border-t pt-2 mt-1 space-y-2" style={{ borderColor: 'var(--border-color)' }}>
          {sector_flow && (
            <div className="text-xs space-y-0.5">
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                📡 板块：{sector_flow.sector}
              </span>
              <div className="grid grid-cols-3 gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <div>净流入 <span style={{ color: sector_flow.net_flow >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmtWan(sector_flow.net_flow)}</span></div>
                <div>平均涨幅 <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{sector_flow.avg_chg?.toFixed(2)}%</span></div>
                <div>涨停数 <span style={{ fontWeight: 600, color: '#f97316' }}>{sector_flow.limit_up_count || 0}</span></div>
              </div>
            </div>
          )}
          {institution_flow && Object.keys(institution_flow).length > 0 && (
            <div className="text-xs space-y-0.5">
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>🏦 机构资金（特大单）</span>
              <div className="grid grid-cols-2 gap-2 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                <div>特大单净 <span style={{ color: institution_flow.super_large_net >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmtWan(institution_flow.super_large_net)}</span></div>
                <div>主力净 <span style={{ color: institution_flow.main_net >= 0 ? '#22c55e' : '#ef4444', fontWeight: 600 }}>{fmtWan(institution_flow.main_net)}</span></div>
                <div>主力买 <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>{fmtWan(institution_flow.main_buy)}</span></div>
                <div>主力卖 <span style={{ fontWeight: 600, color: 'var(--text-muted)' }}>{fmtWan(institution_flow.main_sell)}</span></div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
