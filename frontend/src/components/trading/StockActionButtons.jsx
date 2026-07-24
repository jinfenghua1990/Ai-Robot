import { useState } from 'react';
import TradeModal from './TradeModal';
import StockActionModal from './StockActionModal';
import TrackButton from './TrackButton';
import KLineModal from './KLineModal';
import { useTrading } from '../../context/TradingContext';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../../utils/request';

/**
 * 统一股票操作面板：
 * - 横排：买 / 卖 / 跟踪 / 自选 / 操作
 * - 竖排：K线BS / 分析
 * 通过 showXxx 开关控制，layout 控制排列方向
 *
 * 已下线并删除的按钮：
 * - "重点"：迁入"操作"弹窗（StockActionModal）
 * - "市场状态"标签（趋势/主升/震荡）：与"📊 综合评分"模块趋势维度重复
 * - "购买力"徽章：与 8 维综合评分重复，后端 API 已不再返回 buyPower 字段
 */
export default function StockActionButtons({
  stockCode,
  stockName,
  signal = null,
  positionCount = 0,
  showBuy = true,
  showSell = true,
  showTrack = true,
  showWatch = true,
  showMore = true,
  showSina = true,
  showKline = true,
  showAnalysis = true,
  layout = 'inline', // 'inline' | 'vertical' | 'both'
  size = 'sm',
  className = '',
  onRefresh,
  onRemove,
  onAnalyze,
}) {
  const { executeTrade } = useTrading();
  const [tradeType, setTradeType] = useState(null);
  const [moreOpen, setMoreOpen] = useState(false);
  const [watchAdded, setWatchAdded] = useState(false);
  const [klineOpen, setKlineOpen] = useState(false);
  const navigate = useNavigate();

  if (!stockCode) return null;

  const sizeClass = size === 'xs'
    ? 'px-1.5 py-0 text-[10px] h-5'
    : size === 'md'
    ? 'px-2.5 py-1 text-xs h-7'
    : 'px-2 py-0.5 text-xs h-6';

  const sinaPrefix = (code) => {
    if (!code) return 'sh';
    if (code.startsWith('6') || code.startsWith('9') || code.startsWith('68')) return 'sh';
    if (code.startsWith('8') || code.startsWith('4')) return 'bj';
    return 'sz';
  };
  const openSina = (e) => {
    e?.stopPropagation?.();
    window.open(`https://finance.sina.com.cn/realstock/company/${sinaPrefix(stockCode)}${stockCode}/nc.shtml`, '_blank');
  };

  const handleWatch = async (e) => {
    e?.stopPropagation?.();
    if (watchAdded) return;
    const { ok } = await apiFetch('/api/watchlist/add', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ stockCode, stockName }),
    });
    if (ok) setWatchAdded(true);
  };

  const fullSignal = signal || { secCode: stockCode, secName: stockName };

  const isVertical = layout === 'vertical' || layout === 'both';
  const isInline = layout === 'inline' || layout === 'both';
  const isGrid = layout === 'grid';

  const verticalBtnClass = 'px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center';
  // inline 模式下也显示「K线BS / 🔍分析」（原本仅 vertical 显示）
  // 使用与 inline 主按钮一致的尺寸类，保证一排内高度对齐
  // grid 模式下追加 w-full，让按钮撑满单元格、彼此分隔
  const inlineTagClass = `${sizeClass} rounded font-bold whitespace-nowrap inline-flex items-center justify-center${isGrid ? ' w-full' : ''}`;
  // 普通主按钮（买/卖/自选/新浪/操）在 grid 模式下也撑满单元格
  const mainBtnClass = (extra) => `${sizeClass} rounded font-medium inline-flex items-center justify-center${extra ? ' ' + extra : ''}${isGrid ? ' w-full' : ''}`;

  return (
    <>
      <div className={`${isVertical && !isInline ? 'flex flex-col gap-1' : isGrid ? 'inline-grid grid-cols-2 gap-1.5' : 'inline-flex items-center gap-1 flex-wrap'} ${className}`}>
        {showKline && (
          <button
            onClick={(e) => { e.stopPropagation(); setKlineOpen(true); }}
            className={isInline ? inlineTagClass : verticalBtnClass}
            style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}
          >
            K线BS
          </button>
        )}
        {showAnalysis && (
          <button
            onClick={(e) => { e.stopPropagation(); onAnalyze ? onAnalyze(stockCode) : navigate(`/stock/${stockCode}`); }}
            className={isInline ? inlineTagClass : verticalBtnClass}
            style={{ background: 'rgba(168,85,247,0.12)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
          >
            🔍分析
          </button>
        )}
        {showBuy && (
          <button
            onClick={(e) => { e.stopPropagation(); setTradeType('buy'); }}
            className={mainBtnClass()}
            style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}
            title="买入"
          >
            买
          </button>
        )}
        {showSell && (
          <button
            onClick={(e) => { e.stopPropagation(); setTradeType('sell'); }}
            className={mainBtnClass()}
            style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }}
            title="卖出"
          >
            卖
          </button>
        )}
        {showTrack && (
          <TrackButton stockCode={stockCode} stockName={stockName} size={size} className={isGrid ? 'w-full' : ''} />
        )}
        {showWatch && (
          <button
            onClick={handleWatch}
            className={mainBtnClass()}
            style={watchAdded
              ? { background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
              : { background: 'rgba(234,179,8,0.1)', color: '#eab308', border: '1px solid rgba(234,179,8,0.3)' }
            }
            title="加入自选股"
          >
            {watchAdded ? '✓已加' : '自选'}
          </button>
        )}
        {showSina && (
          <button
            onClick={openSina}
            className={mainBtnClass()}
            style={{ background: 'rgba(249,115,22,0.1)', color: '#f97316', border: '1px solid rgba(249,115,22,0.3)' }}
            title="新浪财经"
          >
            新浪
          </button>
        )}
        {showMore && (
          <button
            onClick={(e) => { e.stopPropagation(); setMoreOpen(true); }}
            className={mainBtnClass()}
            style={{ background: 'rgba(107,114,128,0.1)', color: '#6b7280', border: '1px solid rgba(107,114,128,0.3)' }}
            title="更多操作"
          >
            操作
          </button>
        )}
      </div>

      {tradeType && (
        <TradeModal
          stockCode={stockCode}
          stockName={stockName}
          type={tradeType}
          positionCount={positionCount}
          onClose={() => setTradeType(null)}
          onConfirm={executeTrade}
        />
      )}

      {moreOpen && (
        <StockActionModal
          signal={fullSignal}
          onClose={() => setMoreOpen(false)}
          onRemove={onRemove}
          onRefresh={onRefresh}
        />
      )}

      {klineOpen && (
        <KLineModal stockCode={stockCode} stockName={stockName} onClose={() => setKlineOpen(false)} />
      )}
    </>
  );
}
