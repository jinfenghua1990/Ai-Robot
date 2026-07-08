import { useState, useEffect, useCallback } from 'react';
import { createPortal } from 'react-dom';
import SinaLink from '../SinaLink';
import { useTrading } from '../../context/TradingContext';
import { apiFetch } from '../../utils/request';

/**
 * 交易弹窗组件
 * 支持买入/卖出，限价/市价委托
 * 自动获取新浪实时行情
 * 限价 = 自己指定价格，市价 = 用当前价格快速成交
 */
export default function TradeModal({ stockCode, stockName, type, positionCount = 0, onClose, onConfirm }) {
  const { balance } = useTrading();
  const [useMarketPrice, setUseMarketPrice] = useState(true);
  const [price, setPrice] = useState('');
  const [quantity, setQuantity] = useState('100');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [quote, setQuote] = useState(null);
  const [quoteLoading, setQuoteLoading] = useState(true);

  const isBuy = type === 'buy';
  const isSell = type === 'sell';
  // 可用资金（买入全仓计算用）
  const availBalance = balance?.availBalance || 0;
  // 卖出时的最大可卖数量（持仓数量）
  const maxSellQty = isSell ? positionCount : 0;

  // 获取实时行情
  useEffect(() => {
    let active = true;
    setQuoteLoading(true);
    (async () => {
      try {
        const { ok, data } = await apiFetch(`/api/trading/quote?code=${stockCode}`);
        if (!active) return;
        if (!ok) { setQuoteLoading(false); return; }
        setQuote(data);
        if (data.price && !price) {
          setPrice(data.price.toFixed(2));
        }
        setQuoteLoading(false);
      } catch {
        if (active) setQuoteLoading(false);
      }
    })();
    return () => { active = false; };
  }, [stockCode]);

  // 安全访问行情字段，避免 undefined.toFixed() 崩溃
  const qPrice = quote?.price ?? null;
  const qChange = quote?.change ?? null;
  const qChangePct = quote?.changePct ?? null;
  const qYesterdayClose = quote?.yesterdayClose ?? null;
  const qOpen = quote?.open ?? null;

  // 涨跌停价格计算（A股±10%，ST股±5%）
  const priceLimit = qYesterdayClose ? {
    upper: qYesterdayClose * 1.1,
    lower: qYesterdayClose * 0.9,
  } : null;

  const handleSubmit = useCallback(async () => {
    setError(null);
    if (!useMarketPrice && !price) {
      setError('请输入委托价格');
      return;
    }
    // 涨跌停验证
    if (!useMarketPrice && priceLimit && quote) {
      const p = parseFloat(price);
      if (p > priceLimit.upper) {
        setError(`委托价 ${p.toFixed(2)} 超过涨停价 ${priceLimit.upper.toFixed(2)}（昨收 ${quote.yesterdayClose.toFixed(2)} × 110%）`);
        return;
      }
      if (p < priceLimit.lower) {
        setError(`委托价 ${p.toFixed(2)} 低于跌停价 ${priceLimit.lower.toFixed(2)}（昨收 ${quote.yesterdayClose.toFixed(2)} × 90%）`);
        return;
      }
    }
    const qty = parseInt(quantity);
    if (!qty || qty % 100 !== 0) {
      setError('数量必须为100的整数倍');
      return;
    }
    // 卖出时检查持仓
    if (isSell && maxSellQty > 0 && qty > maxSellQty) {
      setError(`卖出数量 ${qty} 超过持仓 ${maxSellQty} 股`);
      return;
    }

    setSubmitting(true);
    const params = {
      type,
      stockCode,
      quantity: qty,
      useMarketPrice,
    };
    if (!useMarketPrice) {
      params.price = parseFloat(price);
    }

    try {
      await onConfirm(params);
      onClose();
    } catch (e) {
      setError(e.message || '操作失败');
    } finally {
      setSubmitting(false);
    }
  }, [useMarketPrice, price, quantity, type, stockCode, onConfirm, onClose, priceLimit, quote, isSell, maxSellQty]);

  // 预计金额
  const currentPrice = useMarketPrice ? (qPrice ?? 0) : (parseFloat(price) || 0);
  const estimatedAmount = currentPrice * (parseInt(quantity) || 0);

  // 买入全仓可买数量 = floor(可用资金 / 单价 / 100) * 100
  const maxBuyQty = isBuy && currentPrice > 0
    ? Math.floor(availBalance / currentPrice / 100) * 100
    : 0;

  // 快捷数量按钮
  const quickQtyBtns = isSell && maxSellQty > 0
    ? [
        { label: '全部', value: Math.floor(maxSellQty / 100) * 100 },
        { label: '1/2', value: Math.floor(maxSellQty / 2 / 100) * 100 },
        { label: '1/4', value: Math.floor(maxSellQty / 4 / 100) * 100 },
        { label: '200股', value: 200 },
        { label: '500股', value: 500 },
      ].filter(b => b.value >= 100)
    : isBuy
    ? [
        { label: '全仓', value: maxBuyQty },
        { label: '半仓', value: Math.floor(maxBuyQty / 2 / 100) * 100 },
        { label: '1/4仓', value: Math.floor(maxBuyQty / 4 / 100) * 100 },
        { label: '200股', value: 200 },
        { label: '500股', value: 500 },
      ].filter(b => b.value >= 100)
    : [
        { label: '100股', value: 100 },
        { label: '200股', value: 200 },
        { label: '500股', value: 500 },
        { label: '1000股', value: 1000 },
      ];

  // 使用 Portal 渲染到 document.body，脱离父元素 stacking context
  return createPortal((
    <div className="fixed inset-0 z-50 flex items-center justify-center" style={{ background: 'rgba(0,0,0,0.82)' }} onClick={onClose}>
      <div
        className="rounded-xl w-[calc(100vw-2rem)] max-w-sm p-5 space-y-4"
        style={{
          background: 'var(--bg-card)',
          border: '2px solid #3b82f6',
          boxShadow: '0 0 0 1px rgba(0,0,0,0.05), 0 2px 4px rgba(0,0,0,0.06), 0 12px 28px rgba(0,0,0,0.12), 0 30px 60px rgba(0,0,0,0.35)',
        }}
        onClick={e => e.stopPropagation()}
      >
        {/* 标题 */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold" style={{ color: isBuy ? '#ef4444' : '#22c55e' }}>
              {isBuy ? '买入' : '卖出'}
            </span>
            <span className="text-base font-medium" style={{ color: 'var(--text-primary)' }}>{stockName}</span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{stockCode}</span>
            <SinaLink tsCode={stockCode} />
          </div>
          <button onClick={onClose} className="text-lg" style={{ color: 'var(--text-muted)' }}>✕</button>
        </div>

        {/* 实时行情 + 涨跌停 */}
        <div className="rounded-lg p-3" style={{ background: 'var(--bg-surface)', border: '1px solid var(--border-color)' }}>
          {quoteLoading ? (
            <div className="text-xs text-center py-1" style={{ color: 'var(--text-muted)' }}>获取实时行情中...</div>
          ) : quote ? (
            <>
              <div className="flex items-center justify-between">
                <div>
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>当前价</div>
                  <div className="text-xl font-bold" style={{ color: (qChange ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                    {qPrice != null ? qPrice.toFixed(2) : '--'}
                  </div>
                </div>
                <div className="text-right space-y-0.5">
                  <div className="text-xs" style={{ color: (qChange ?? 0) >= 0 ? '#ef4444' : '#22c55e' }}>
                    {qChange != null ? `${qChange >= 0 ? '+' : ''}${qChange.toFixed(2)}` : '--'} ({qChangePct != null ? qChangePct.toFixed(2) : '--'}%)
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    昨收 {qYesterdayClose != null ? qYesterdayClose.toFixed(2) : '--'} · 开 {qOpen != null ? qOpen.toFixed(2) : '--'}
                  </div>
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    涨停 <span style={{ color: '#ef4444' }}>{qYesterdayClose ? (qYesterdayClose * 1.1).toFixed(2) : '--'}</span> · 跌停 <span style={{ color: '#22c55e' }}>{qYesterdayClose ? (qYesterdayClose * 0.9).toFixed(2) : '--'}</span>
                  </div>
                </div>
              </div>
              {/* 持仓信息（买入/卖出都显示） */}
              {positionCount > 0 && (
                <div className="mt-2 pt-2 border-t text-xs flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>📋 当前持仓</span>
                  <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{positionCount} 股</span>
                </div>
              )}
              {/* 买入时显示可用资金 */}
              {isBuy && availBalance > 0 && (
                <div className="mt-1 text-xs flex items-center justify-between">
                  <span style={{ color: 'var(--text-muted)' }}>💰 可用资金</span>
                  <span className="font-bold" style={{ color: 'var(--text-primary)' }}>
                    {availBalance.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元
                    {maxBuyQty > 0 && <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}> (可买 {maxBuyQty} 股)</span>}
                  </span>
                </div>
              )}
            </>
          ) : (
            <div className="text-xs text-center py-1" style={{ color: 'var(--text-muted)' }}>行情获取失败</div>
          )}
        </div>

        {/* 委托方式 + 说明 */}
        <div>
          <div className="flex gap-2">
            <button
              onClick={() => setUseMarketPrice(true)}
              className="flex-1 py-2 rounded-lg text-sm font-medium transition-all"
              style={{
                background: useMarketPrice ? 'var(--accent-color, #3b82f6)' : 'var(--bg-surface)',
                color: useMarketPrice ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${useMarketPrice ? 'transparent' : 'var(--border-color)'}`,
              }}
            >
              市价
            </button>
            <button
              onClick={() => setUseMarketPrice(false)}
              className="flex-1 py-2 rounded-lg text-sm font-medium transition-all"
              style={{
                background: !useMarketPrice ? 'var(--accent-color, #3b82f6)' : 'var(--bg-surface)',
                color: !useMarketPrice ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${!useMarketPrice ? 'transparent' : 'var(--border-color)'}`,
              }}
            >
              限价
            </button>
          </div>
          <div className="mt-1.5 text-xs" style={{ color: 'var(--text-muted)' }}>
            {useMarketPrice
              ? '💡 市价 = 以当前最新价格立即成交，速度快'
              : '💡 限价 = 自己指定价格，等市场价格到了才成交'
            }
          </div>
        </div>

        {/* 价格输入 */}
        {!useMarketPrice && (
          <div>
            <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>
              委托价格 (元) · 范围 {priceLimit ? `${priceLimit.lower.toFixed(2)} ~ ${priceLimit.upper.toFixed(2)}` : '--'}
            </label>
            <input
              type="number"
              value={price}
              onChange={e => setPrice(e.target.value)}
              placeholder="0.00"
              step="0.01"
              className="w-full px-3 py-2 rounded-lg border text-sm"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
            />
            {quote && (
              <button
                onClick={() => setPrice(quote.price.toFixed(2))}
                className="mt-1 text-xs"
                style={{ color: 'var(--accent-color, #3b82f6)' }}
              >
                ↻ 使用最新价 {quote.price.toFixed(2)}
              </button>
            )}
          </div>
        )}

        {/* 数量输入 + 快捷按钮 */}
        <div>
          <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>
            委托数量 (股，须100的整数倍)
            {positionCount > 0 && (
              <span style={{ color: 'var(--accent-color, #3b82f6)' }}> · 持仓 {positionCount} 股</span>
            )}
            {isBuy && maxBuyQty > 0 && (
              <span style={{ color: 'var(--text-muted)' }}> · 最多可买 {maxBuyQty} 股</span>
            )}
          </label>
          <input
            type="number"
            value={quantity}
            onChange={e => setQuantity(e.target.value)}
            step="100"
            min="100"
            className="w-full px-3 py-2 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
          />
          <div className="flex gap-1.5 mt-2 flex-wrap">
            {quickQtyBtns.map(btn => (
              <button
                key={btn.label}
                onClick={() => setQuantity(String(btn.value))}
                className="px-2.5 py-1 rounded text-xs border transition-all"
                style={{
                  borderColor: parseInt(quantity) === btn.value ? 'var(--accent-color, #3b82f6)' : 'var(--border-color)',
                  color: parseInt(quantity) === btn.value ? 'var(--accent-color, #3b82f6)' : 'var(--text-secondary)',
                  background: parseInt(quantity) === btn.value ? 'rgba(59,130,246,0.1)' : 'transparent',
                }}
              >
                {btn.label}
              </button>
            ))}
          </div>
        </div>

        {/* 预计金额 */}
        {estimatedAmount > 0 && (
          <div className="text-xs flex justify-between" style={{ color: 'var(--text-muted)' }}>
            <span>预计金额</span>
            <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>
              {estimatedAmount.toLocaleString('zh-CN', { minimumFractionDigits: 2 })} 元
            </span>
          </div>
        )}

        {/* 错误提示 */}
        {error && (
          <div className="text-xs px-3 py-2 rounded-lg" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.1)' }}>
            {error}
          </div>
        )}

        {/* 按钮 */}
        <div className="flex gap-2">
          <button
            onClick={onClose}
            className="flex-1 py-2.5 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            取消
          </button>
          <button
            onClick={handleSubmit}
            disabled={submitting}
            className="flex-1 py-2.5 rounded-lg text-sm font-medium text-white transition-all disabled:opacity-50"
            style={{ background: isBuy ? '#ef4444' : '#22c55e' }}
          >
            {submitting ? '提交中...' : `确认${isBuy ? '买入' : '卖出'}`}
          </button>
        </div>
      </div>
    </div>
  ), document.body);
}
