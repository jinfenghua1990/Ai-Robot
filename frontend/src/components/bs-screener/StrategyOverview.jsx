import { useState } from 'react';

const BUILTIN_STRATEGIES = [
  { type: '龙头', color: '#ef4444', name: 'V4双引擎决策', desc: '板块趋势+龙头评分+候选+切换', dim: '全市场', tabKey: 'v4' },
  { type: '龙头', color: '#ef4444', name: 'V1龙头趋势阶段', desc: '5阶段趋势阶段追踪', dim: '全市场', tabKey: 'v1' },
  { type: '龙头', color: '#ef4444', name: 'V2龙头强度排行', desc: '多维度强度评分排序', dim: '全市场', tabKey: 'v2' },
  { type: '龙头', color: '#ef4444', name: 'V3龙头周期V3', desc: '龙头周期分析', dim: '全市场', tabKey: 'v3' },
  { type: '智能', color: '#3b82f6', name: '热度综合', desc: '板块热度Top5+突破/加速+主力净流入', dim: '全市场', tabKey: 'smart-heat' },
  { type: '智能', color: '#3b82f6', name: '白虎V3.0', desc: 'MA20强势回调，5维度≥6分', dim: '科创创业板', tabKey: 'smart-baihu' },
  { type: '智能', color: '#3b82f6', name: '青龙', desc: 'MA10主升浪回踩策略', dim: '全市场', tabKey: 'smart-qinglong' },
];

const DIM_LABELS = {
  star: '科创',
  chinext: '创业',
  all: '全A股',
};

const DIM_DISPLAY = {
  star: '科创板',
  chinext: '创业板',
  all: '全A股',
};

function describeBsStrategy(s) {
  const tags = [
    s.ma60_trend && 'MA60',
    s.rsi_filter && `RSI(${s.rsi_lower || 30}-${s.rsi_upper || 70})`,
    s.macd_filter && 'MACD',
    s.strong_volume && '强量',
  ].filter(Boolean).join('+');
  return tags ? `ATR(${s.atr_period},${s.atr_multiplier})+${tags}` : `ATR(${s.atr_period},${s.atr_multiplier})`;
}

function buildBsStrategyRow(s) {
  return {
    type: 'BS',
    color: '#22c55e',
    name: `BS-${DIM_LABELS[s.dimension] || '自定义'}-V${s.id}`,
    desc: describeBsStrategy(s),
    dim: DIM_DISPLAY[s.dimension] || s.dimension,
    winRate: s.win_rate,
    profitFactor: s.profit_factor,
    star: s.profit_factor >= 2.0 && s.win_rate >= 45 ? '★★★' : s.profit_factor >= 1.5 ? '★★' : '★',
    rawStrategy: s,
  };
}

export default function StrategyOverview({ bsStrategies = [], onRunBacktest, onShowHistory, onScanMain, onExport, hasSignals }) {
  const [collapsed, setCollapsed] = useState(false);
  const [toast, setToast] = useState(null);

  const allStrategies = [
    ...BUILTIN_STRATEGIES,
    ...bsStrategies.map(buildBsStrategyRow),
  ];

  const showToast = (msg) => {
    setToast(msg);
    setTimeout(() => setToast(null), 2500);
  };

  const handleViewTab = (tabKey, name) => {
    window.dispatchEvent(new CustomEvent('strategy-center-switch-tab', { detail: { tabKey } }));
    showToast(`已跳转到「${name}」Tab`);
  };

  const handleAction = (action, s) => {
    if (s.type === 'BS') {
      switch (action) {
        case 'scan': onScanMain?.(s.rawStrategy); break;
        case 'export': onExport?.(); break;
        case 'backtest': onRunBacktest?.(s.rawStrategy); break;
        case 'history': onShowHistory?.(); break;
      }
    } else {
      switch (action) {
        case 'scan': handleViewTab(s.tabKey, s.name); break;
        case 'export': showToast(`「${s.name}」导出功能开发中，请到对应Tab操作`); break;
        case 'backtest': showToast(`「${s.name}」回测功能开发中`); break;
        case 'history': showToast(`「${s.name}」暂无回测历史`); break;
      }
    }
  };

  const typeCount = (t) => allStrategies.filter(s => s.type === t).length;
  const actionBtn = (color, label, title, onClick, disabled) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="px-1.5 py-0.5 rounded text-[10px] border transition-colors hover:opacity-80 whitespace-nowrap"
      style={{ borderColor: color + '50', color, opacity: disabled ? 0.4 : 1 }}
      title={title}
    >
      {label}
    </button>
  );

  return (
    <div className="rounded-lg border relative" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      {toast && (
        <div className="absolute z-50 px-3 py-1.5 rounded-md text-xs" style={{
          background: 'rgba(59,130,246,0.9)', color: '#fff', top: 10, right: 10,
        }}>
          {toast}
        </div>
      )}

      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center justify-between px-3 py-2"
      >
        <div className="flex items-center gap-2">
          <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📋 策略总览</span>
          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
            共 {allStrategies.length} 个策略
          </span>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            龙头 {typeCount('龙头')} · 智能 {typeCount('智能')} · BS {typeCount('BS')}
          </span>
        </div>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{collapsed ? '展开 ▼' : '收起 ▲'}</span>
      </button>

      {!collapsed && (
        <div className="border-t overflow-x-auto" style={{ borderColor: 'var(--border-color)' }}>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: 'var(--bg-surface)', color: 'var(--text-muted)' }}>
                <th className="px-2 py-1.5 text-left whitespace-nowrap">类型</th>
                <th className="px-2 py-1.5 text-left whitespace-nowrap">策略名称</th>
                <th className="px-2 py-1.5 text-left whitespace-nowrap">参数/描述</th>
                <th className="px-2 py-1.5 text-center whitespace-nowrap">维度</th>
                <th className="px-2 py-1.5 text-right whitespace-nowrap">胜率</th>
                <th className="px-2 py-1.5 text-right whitespace-nowrap">盈亏比</th>
                <th className="px-2 py-1.5 text-center whitespace-nowrap">星级</th>
                <th className="px-2 py-1.5 text-center whitespace-nowrap">操作</th>
              </tr>
            </thead>
            <tbody>
              {allStrategies.map((s, i) => {
                const pf = s.profitFactor != null ? (s.profitFactor >= 999 ? 999 : s.profitFactor) : null;
                return (
                  <tr key={`${s.type}-${s.name}-${i}`} className="border-t" style={{ borderColor: 'var(--border-light)' }}>
                    <td className="px-2 py-1.5">
                      <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: s.color + '15', color: s.color }}>
                        {s.type}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 whitespace-nowrap font-medium" style={{ color: 'var(--text-primary)' }}>
                      {s.name}
                    </td>
                    <td className="px-2 py-1.5 text-[11px]" style={{ color: 'var(--text-muted)' }}>
                      {s.desc}
                    </td>
                    <td className="px-2 py-1.5 text-center text-[11px]" style={{ color: 'var(--text-secondary)' }}>
                      {s.dim}
                    </td>
                    <td className="px-2 py-1.5 text-right" style={{ color: s.winRate != null ? (s.winRate >= 50 ? '#ef4444' : 'var(--text-secondary)') : 'var(--text-muted)' }}>
                      {s.winRate != null ? `${s.winRate}%` : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-right" style={{ color: pf != null ? '#eab308' : 'var(--text-muted)' }}>
                      {pf != null ? (pf >= 999 ? '∞' : pf) : '-'}
                    </td>
                    <td className="px-2 py-1.5 text-center" style={{ color: s.color }}>
                      {s.star || '-'}
                    </td>
                    <td className="px-2 py-1.5">
                      <div className="flex items-center gap-1 justify-center">
                        {actionBtn('#22c55e', '🔍 扫描', s.type === 'BS' ? '用此策略参数扫描' : '跳转到对应Tab查看', () => handleAction('scan', s))}
                        {actionBtn('var(--text-secondary)', '📥 导出', '导出扫描结果', () => handleAction('export', s), s.type === 'BS' && !hasSignals)}
                        {actionBtn('#3b82f6', '📊 回测', s.type === 'BS' ? '用此策略参数回测' : '回测功能开发中', () => handleAction('backtest', s))}
                        {actionBtn('#eab308', '📋 历史', s.type === 'BS' ? '查看回测历史' : '暂无回测历史', () => handleAction('history', s))}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div className="px-3 py-1.5 text-[10px] flex items-center gap-3" style={{ color: 'var(--text-muted)', background: 'var(--bg-surface)' }}>
            <span>📊 BS策略：扫描+导出+回测+历史 全功能可用</span>
            <span>🔍 龙头/智能策略：扫描=跳转Tab，其他开发中</span>
            <span>⭐ 星级=盈亏比+胜率综合评级</span>
          </div>
        </div>
      )}
    </div>
  );
}
