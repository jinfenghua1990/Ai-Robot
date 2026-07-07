import { useState, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTrading } from '../context/TradingContext';
import TradeModal from '../components/trading/TradeModal';
import SignalCard from '../components/trading/SignalCard';
import StrategyConfig from '../components/trading/StrategyConfig';
import ManualTradeBar from '../components/trading/ManualTradeBar';
import { fmtFlow, formatMoney, formatProfit } from '../utils/format';
import { CLEAR_COLOR, REDUCE_COLOR, ADD_COLOR } from '../utils/colors';
import { apiFetch } from '../utils/request';
import { TOAST_DURATION } from '../utils/constants';

export default function TradingPage() {
  const { balance, loading, refreshAll, executeTrade, cancelOrder, tradeResult, clearTradeResult } = useTrading();
  const [searchParams, setSearchParams] = useSearchParams();
  const todayStr = new Date().toLocaleDateString('en-CA');
  const selectedDate = searchParams.get('date') || todayStr;
  const setSelectedDate = (d) => {
    if (d === todayStr) {
      setSearchParams({}, { replace: true });
    } else {
      setSearchParams({ date: d }, { replace: true });
    }
  };
  const [sellModal, setSellModal] = useState(null);
  const [canceling, setCanceling] = useState(false);
  const [signals, setSignals] = useState(null);
  const [orders, setOrders] = useState(null);
  const [strategyConfig, setStrategyConfig] = useState(null);
  const [showConfig, setShowConfig] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [historyDates, setHistoryDates] = useState([]);
  const [historyAccount, setHistoryAccount] = useState(null);

  const [signalsError, setSignalsError] = useState(null);
  const [strategyPicks, setStrategyPicks] = useState({});

  const isToday = selectedDate === todayStr;

  // 加载历史日期列表
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const { ok, data } = await apiFetch('/api/trading/history');
      if (cancelled || !ok) return;
      setHistoryDates(data.dates || []);
    })();
    return () => { cancelled = true; };
  }, []);

  // 加载分析信号 + 委托记录（根据 selectedDate）
  useEffect(() => {
    let cancelled = false;
    setSignals(null);
    setSignalsError(null);
    setHistoryAccount(null);
    (async () => {
      const [sigRes, ordRes, histRes, picksRes] = await Promise.all([
        apiFetch(`/api/trading/signals${selectedDate ? `?date=${selectedDate}` : ''}`),
        isToday ? apiFetch('/api/trading/orders') : Promise.resolve({ ok: true, data: { orders: [] } }),
        isToday ? Promise.resolve({ ok: false }) : apiFetch(`/api/trading/history/${selectedDate}`),
        apiFetch('/api/bs-screener/strategy-picks'),
      ]);
      if (cancelled) return;
      const sigData = sigRes.ok ? sigRes.data : null;
      const ordData = ordRes.ok ? ordRes.data : null;
      const histData = histRes.ok ? histRes.data : null;
      if (picksRes.ok && picksRes.data?.code_to_strategies) {
        setStrategyPicks(picksRes.data.code_to_strategies);
      }
      if (sigData && sigData.summary) {
        setSignals(sigData);
        setStrategyConfig(sigData.config);
        setSignalsError(null);
      } else if (sigData && sigData.detail) {
        setSignalsError(sigData.detail);
      }
      if (ordData && ordData.orders) setOrders(ordData);
      if (histData && histData.account) setHistoryAccount(histData.account);
    })();
    return () => { cancelled = true; };
  }, [selectedDate, isToday]);

  // 更新策略配置
  const handleUpdateConfig = async (newConfig) => {
    const res = await apiFetch('/api/trading/strategy-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newConfig),
    });
    if (res.ok && res.data?.config) setStrategyConfig(res.data.config);
    setSignals(null);
    setSignalsError(null);
    const { ok, data: sigData } = await apiFetch('/api/trading/signals');
    if (!ok) return;
    if (sigData.summary) setSignals(sigData);
    else if (sigData.detail) setSignalsError(sigData.detail);
  };

  // 交易结果Toast
  useEffect(() => {
    if (tradeResult) {
      const t = setTimeout(clearTradeResult, TOAST_DURATION);
      return () => clearTimeout(t);
    }
  }, [tradeResult, clearTradeResult]);

  const handleCancelAll = async () => {
    setCanceling(true);
    await cancelOrder({ type: 'all' });
    // 刷新委托记录
    const { ok, data } = await apiFetch('/api/trading/orders');
    if (ok) setOrders(data);
    setCanceling(false);
  };

  if (loading && !balance) {
    return (
      <div className="space-y-4">
        <div className="h-4 w-32 rounded animate-pulse" style={{ background: 'var(--bg-hover)' }} />
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          {[1, 2, 3, 4].map(i => (
            <div key={i} className="h-24 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
          ))}
        </div>
        <div className="h-96 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
      </div>
    );
  }

  // 按股票代码分组委托记录
  const ordersByCode = {};
  if (orders?.orders) {
    for (const o of orders.orders) {
      if (!ordersByCode[o.secCode]) ordersByCode[o.secCode] = [];
      ordersByCode[o.secCode].push(o);
    }
  }
  const pendingCount = orders?.orders?.filter(o => [2, 3, 5, 6].includes(o.status)).length || 0;

  // balance为null时的安全访问
  const bal = balance || { accName: '--', oprDays: 0, nav: 0, totalAssets: 0, initMoney: 0, availBalance: 0, frozenMoney: 0, totalPosValue: 0, totalPosPct: 0 };

  return (
    <div className="space-y-4">
      {/* Toast 通知 */}
      {tradeResult && (
        <div
          className="fixed top-4 right-4 z-50 px-3 py-2 rounded-lg shadow-lg text-sm"
          style={{
            background: tradeResult.success ? 'rgba(34,197,94,0.9)' : 'rgba(239,68,68,0.9)',
            color: '#fff',
          }}
        >
          {tradeResult.success ? '✅ ' : '❌ '}{tradeResult.message}
        </div>
      )}

      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>模拟盘</h2>
        <div className="flex items-center gap-2">
          {(isToday ? balance : historyAccount) && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              账户: {(isToday ? balance : historyAccount).accName} · 运作 {(isToday ? balance : historyAccount).oprDays} 天 · 净值 {(isToday ? balance : historyAccount).nav}
            </span>
          )}
          {pendingCount > 0 && (
            <button
              onClick={handleCancelAll}
              disabled={canceling}
              className="px-3 py-1.5 rounded-lg text-xs border"
              style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444', background: 'rgba(239,68,68,0.05)' }}
            >
              {canceling ? '撤单中...' : `撤单(${pendingCount})`}
            </button>
          )}
          <input
            type="date"
            value={selectedDate}
            max={todayStr}
            onChange={(e) => {
              const d = e.target.value;
              setSelectedDate(d);
              if (d === todayStr) {
                setSearchParams({});
              } else {
                setSearchParams({ date: d });
              }
            }}
            className="px-2 py-1.5 rounded-lg border text-sm"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
          />
          {isToday && (
            <button
              onClick={() => {
                refreshAll(true);  // force=true 跳过缓存，直接调用妙想API
                setSignals(null);
                (async () => {
                  const { ok, data } = await apiFetch('/api/trading/signals');
                  if (ok) setSignals(data);
                })();
                (async () => {
                  const { ok, data } = await apiFetch('/api/trading/orders');
                  if (ok) setOrders(data);
                })();
              }}
              className="px-3 py-1.5 rounded-lg border text-sm"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              🔄 刷新
            </button>
          )}
          {!isToday && (
            <span className="text-xs px-2 py-1 rounded" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
              历史快照
            </span>
          )}
        </div>
      </div>

      {/* 说明卡片（可折叠） */}
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-3 py-2.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 模拟盘说明</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-3 pb-3 space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>模拟盘：</strong>基于策略自动生成的虚拟交易账户，不涉及真实资金，用于验证策略效果与持仓评分</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>信号类型：</strong>
              <span style={{ color: CLEAR_COLOR }}>清仓</span>（强烈卖出，评分极低）·
              <span style={{ color: REDUCE_COLOR }}>减仓</span>（部分卖出，评分偏低）·
              <span style={{ color: '#6b7280' }}>持仓</span>（继续持有，评分中性）·
              <span style={{ color: ADD_COLOR }}>加仓</span>（增加持仓，评分较高）
            </div>
            <div><strong style={{ color: '#ef4444' }}>红色</strong>=盈利/上涨，<strong style={{ color: '#22c55e' }}>绿色</strong>=亏损/下跌（A股习惯）</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>策略配置：</strong>可调整持仓评分阈值、买卖参数等，修改后会重新生成分析信号</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>操作提示：</strong>点击信号卡片中的"卖出"按钮可手动下单，点击"撤单"可批量撤销未成交委托</div>
          </div>
        )}
      </div>

      {/* 账户概览：今天用实时 balance，历史用快照 account */}
      {(() => {
        const acc = isToday ? balance : historyAccount;
        if (!acc) return null;
        return (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>总资产</div>
              <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{formatMoney(acc.totalAssets)}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>初始: {formatMoney(acc.initMoney)}</div>
            </div>
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>可用资金</div>
              <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{formatMoney(acc.availBalance)}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>冻结: {formatMoney(acc.frozenMoney)}</div>
            </div>
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>持仓市值</div>
              <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{formatMoney(acc.totalPosValue)}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>仓位: {(acc.totalPosPct || 0).toFixed(1)}%</div>
            </div>
            <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>总盈亏</div>
              <div className="text-xl font-bold" style={{ color: (acc.totalAssets - acc.initMoney) >= 0 ? '#ef4444' : '#22c55e' }}>
                {formatProfit(acc.totalAssets - acc.initMoney)}
              </div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
                收益率: {(((acc.totalAssets - acc.initMoney) / acc.initMoney) * 100).toFixed(2)}%
              </div>
            </div>
          </div>
        );
      })()}

      {/* 信号加载错误提示 */}
      {signalsError && (
        <div className="rounded-lg p-3 flex items-center justify-between" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <span className="text-sm" style={{ color: '#ef4444' }}>⚠ {signalsError}</span>
          <button
            onClick={async () => {
              setSignalsError(null);
              const { ok, data } = await apiFetch('/api/trading/signals');
              if (!ok) { setSignalsError('网络请求失败'); return; }
              if (data.summary) { setSignals(data); setStrategyConfig(data.config); }
              else if (data.detail) setSignalsError(data.detail);
            }}
            className="px-3 py-1 rounded text-xs"
            style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}
          >
            重试
          </button>
        </div>
      )}

      {/* 信号汇总 */}
      {signals && signals.summary && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
          {[
            { label: '清仓', count: signals.summary.strong_sell, color: CLEAR_COLOR },
            { label: '减仓', count: signals.summary.sell, color: REDUCE_COLOR },
            { label: '持仓', count: signals.summary.hold, color: '#6b7280' },
            { label: '加仓', count: signals.summary.add, color: ADD_COLOR },
            { label: '高风险', count: signals.summary.high_risk, color: '#ef4444' },
          ].map(item => (
            <div key={item.label} className="rounded-xl border p-3 text-center" style={{ borderColor: `${item.color}40`, background: 'var(--bg-card)' }}>
              <div className="text-2xl font-bold" style={{ color: item.color }}>{item.count}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{item.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* 策略配置入口（独立于signals，API失败时也能打开） */}
      <div className="flex items-center justify-between">
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
          {signals && signals.summary
            ? <>{isToday ? '分析时间' : '快照日期'}: {signals.date || selectedDate} {signals.generated_at} · 共 {signals.summary.total} 只持仓
              {isToday && pendingCount > 0 && ` · ${pendingCount} 笔未成交委托`}
              {!isToday && (
                <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
                  历史快照
                </span>
              )}
              {isToday && (() => {
                const now = new Date();
                const h = now.getHours();
                const m = now.getMinutes();
                const isTradeTime = (h === 9 && m >= 25) || (h >= 10 && h < 15) || (h === 15 && m === 0);
                const label = isTradeTime ? '盘中实时' : '盘后数据';
                const color = isTradeTime ? '#22c55e' : '#eab308';
                return (
                  <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: `${color}1a`, color }}>
                    {label}
                  </span>
                );
              })()}
            </>
            : signalsError ? '⚠ 信号加载失败，可调整策略后重试' : '加载中...'
          }
        </div>
        <button
          onClick={() => setShowConfig(!showConfig)}
          className="px-3 py-1.5 rounded-lg text-xs border"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
        >
          {showConfig ? '收起策略配置' : '⚙ 策略配置'}
        </button>
      </div>

      {showConfig && strategyConfig && (
        <StrategyConfig config={strategyConfig} onUpdate={handleUpdateConfig} />
      )}
      {showConfig && !strategyConfig && (
        <div className="rounded-xl border p-3 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
          策略配置加载中... 如果持续显示，请先刷新页面
        </div>
      )}

      {/* 手动买入栏：仅今天可操作 */}
      {isToday && <ManualTradeBar />}

      {/* 信号卡片列表（单列布局，可展开查看更多数据维度） */}
      <div className="grid grid-cols-1 gap-2">
        {signals ? (
          signals.signals.map(sig => (
            <SignalCard
              key={sig.secCode}
              signal={sig}
              orders={ordersByCode[sig.secCode] || []}
              onSell={setSellModal}
              mode="sim_watchlist"
              strategyTags={strategyPicks[sig.secCode] || []}
              showMarketState
              showBuyPower
              showAnalysisButton
            />
          ))
        ) : (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
              ))}
            </div>
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
            ))}
          </>
        )}
        {signals && signals.signals.length === 0 && (
          <div className="text-center py-12 text-sm" style={{ color: 'var(--text-muted)' }}>暂无持仓数据</div>
        )}
      </div>

      {/* 卖出弹窗 */}
      {sellModal && (
        <TradeModal
          stockCode={sellModal.stockCode}
          stockName={sellModal.stockName}
          type="sell"
          positionCount={sellModal.positionCount || 0}
          onClose={() => setSellModal(null)}
          onConfirm={executeTrade}
        />
      )}
    </div>
  );
}
