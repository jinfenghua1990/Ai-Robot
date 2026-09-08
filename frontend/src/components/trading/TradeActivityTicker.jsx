import { useCallback, useEffect, useState } from 'react';
import { useTrading } from '../../context/tradingContextCore';

const statusColor = {
  success: '#16a34a',
  error: '#dc2626',
  submitting: '#d97706',
};

/** 全局顶部交易状态栏：跨页面保留最近的委托进度。 */
export default function TradeActivityTicker() {
  const { tradeResult } = useTrading();
  const [items, setItems] = useState([]);

  const appendItem = useCallback((item) => {
    setItems((prev) => [item, ...prev.filter((entry) => entry.code !== item.code || entry.status !== item.status)].slice(0, 8));
  }, []);

  useEffect(() => {
    if (!tradeResult) return;
    const item = {
      id: `${tradeResult.status}-${tradeResult.stockCode}-${Date.now()}`,
      status: tradeResult.status || (tradeResult.success ? 'success' : 'error'),
      message: tradeResult.message || '交易状态更新',
      action: tradeResult.type === 'buy' ? '买入' : tradeResult.type === 'sell' ? '卖出' : '交易',
      code: tradeResult.stockCode || '—',
      quantity: tradeResult.quantity || null,
      at: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
    };
    appendItem(item);
  }, [appendItem, tradeResult]);

  useEffect(() => {
    const handleDecisionAlert = (event) => {
      const detail = event?.detail || {};
      if (!detail.symbol) return;
      appendItem({
        id: `decision-${detail.symbol}-${Date.now()}`,
        status: detail.status || 'submitting',
        message: detail.message || `执行状态更新为 ${detail.label || '待确认'}`,
        action: '决策',
        code: detail.symbol,
        at: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      });
    };
    window.addEventListener('airobot:decision-alert', handleDecisionAlert);
    return () => window.removeEventListener('airobot:decision-alert', handleDecisionAlert);
  }, [appendItem]);

  const renderItems = items.length > 0 ? [...items, ...items] : [];

  return (
    <div
      className="hidden lg:flex items-center gap-2 h-7 min-w-[250px] flex-[0_1_380px] max-w-[380px] rounded-md border px-2 overflow-hidden"
      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)' }}
      title="交易与每日决策状态反馈"
    >
      <span className="shrink-0 text-[11px] font-bold" style={{ color: 'var(--accent-blue)' }}>🔔 动态</span>
      <span className="h-3.5 w-px shrink-0" style={{ background: 'var(--border-color)' }} />
      <div className="min-w-0 flex-1 overflow-hidden">
        {items.length > 0 ? (
          <div className="trade-activity-ticker flex items-center gap-5 whitespace-nowrap">
            {renderItems.map((item, index) => (
              <span key={`${item.id}-${index}`} className="inline-flex items-center gap-1 text-[10px]" style={{ color: statusColor[item.status] || statusColor.submitting }}>
                <b>{item.action} {item.code}{item.quantity ? ` ${item.quantity}股` : ''}</b>
                <span>{item.message}</span>
                <span style={{ color: 'var(--text-muted)' }}>{item.at}</span>
              </span>
            ))}
          </div>
        ) : (
          <span className="block truncate text-[10px]" style={{ color: 'var(--text-muted)' }}>暂无交易或决策变化</span>
        )}
      </div>
    </div>
  );
}
