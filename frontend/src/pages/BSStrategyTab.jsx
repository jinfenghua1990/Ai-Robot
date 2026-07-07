import { useState, useEffect, useCallback } from 'react';
import SignalCard from '../components/trading/SignalCard';
import { apiFetch } from '../utils/request';

/**
 * BS策略轻量Tab组件
 * 接受一个回测策略参数，自动扫描并展示结果
 * 用于策略中心扁平化Tab
 */
export default function BSStrategyTab({ strategy }) {
  const [result, setResult] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);

  const runScan = useCallback(async () => {
    if (!strategy) return;
    setScanning(true);
    setError(null);
    try {
      // 优先读预计算结果（盘后定时任务已落库），无则 fallback 现场扫描
      if (strategy.id) {
        const todayRes = await apiFetch(`/api/bs-screener/today?backtest_id=${strategy.id}`);
        if (todayRes.ok) {
          setResult(todayRes.data);
          return;
        }
      }
      // fallback：现场扫描
      const qs = new URLSearchParams({
        atr_period: String(strategy.atr_period),
        atr_multiplier: String(strategy.atr_multiplier),
        scan_limit: '9999',
        sector: '',
        signal_type: 'B',
        volume_filter: String(strategy.volume_filter || false),
        ma20_filter: String(strategy.ma20_filter || false),
        ma60_trend: String(strategy.ma60_trend || false),
        rsi_filter: String(strategy.rsi_filter || false),
        strong_volume: String(strategy.strong_volume || false),
        macd_filter: String(strategy.macd_filter || false),
        kdj_filter: String(strategy.kdj_filter || false),
        rsi_lower: String(strategy.rsi_lower || 30),
        rsi_upper: String(strategy.rsi_upper || 70),
        dimension: String(strategy.dimension || ''),
      }).toString();
      const { ok, data, status } = await apiFetch(`/api/bs-screener/run?${qs}`);
      if (!ok) throw new Error(`扫描失败: ${status}`);
      setResult(data);
    } catch (e) {
      setError(e.message);
    } finally {
      setScanning(false);
    }
  }, [strategy]);

  // 首次挂载自动扫描
  useEffect(() => {
    runScan();
  }, [runScan]);

  const handleExportCSV = () => {
    if (!result?.signals?.length) return;
    const header = '代码,名称,板块,信号,价格,ATR上轨,涨幅%\n';
    const rows = result.signals.map(s =>
      `${s.ts_code},${s.name || ''},${s.sector || ''},${s.signal_type || 'B'},${s.price || ''},${s.atr_upper || ''},${s.change_pct || ''}`
    ).join('\n');
    const blob = new Blob([header + rows], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `BS_${strategy.name}_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const pf = strategy.profit_factor >= 999 ? 999 : strategy.profit_factor;
  const tabColor = pf >= 2.0 && strategy.win_rate >= 45 ? '#ef4444' : pf >= 1.5 ? '#eab308' : '#6b7280';
  const dimensionLabel = strategy.dimension === 'star' ? '科创板' : strategy.dimension === 'chinext' ? '创业板' : strategy.dimension === 'all' ? '全A股' : strategy.dimension;

  return (
    <div className="space-y-2">
      {/* 策略信息栏 */}
      <div className="flex items-center justify-between px-3 py-2 rounded-lg border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-3 text-xs">
          <span style={{ color: 'var(--text-primary)' }}>
            <strong>{strategy.name}</strong>
            <span className="ml-1.5 px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>{dimensionLabel}</span>
          </span>
          <span style={{ color: 'var(--text-muted)' }}>
            ATR({strategy.atr_period},{strategy.atr_multiplier})
            {[strategy.ma60_trend && 'MA60', strategy.rsi_filter && `RSI(${strategy.rsi_lower}-${strategy.rsi_upper})`, strategy.macd_filter && 'MACD', strategy.strong_volume && '强量'].filter(Boolean).join('+') && ` +${[strategy.ma60_trend && 'MA60', strategy.rsi_filter && `RSI(${strategy.rsi_lower}-${strategy.rsi_upper})`, strategy.macd_filter && 'MACD', strategy.strong_volume && '强量'].filter(Boolean).join('+')}`}
          </span>
        </div>
        <div className="flex items-center gap-2 text-xs">
          <span style={{ color: 'var(--text-muted)' }}>回测胜率 <strong style={{ color: strategy.win_rate >= 50 ? '#ef4444' : 'var(--text-secondary)' }}>{strategy.win_rate}%</strong></span>
          <span style={{ color: 'var(--text-muted)' }}>盈亏比 <strong style={{ color: '#eab308' }}>{pf >= 999 ? '∞' : pf}</strong></span>
          <span style={{ color: tabColor }}>{pf >= 2.0 && strategy.win_rate >= 45 ? '★★★' : pf >= 1.5 ? '★★' : '★'}</span>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="flex items-center justify-end gap-2">
        <button
          onClick={runScan}
          disabled={scanning}
          className="px-2 py-1 rounded-md text-xs border flex items-center gap-1 transition-colors"
          style={{
            borderColor: scanning ? 'var(--border-color)' : 'rgba(34,197,94,0.3)',
            color: scanning ? 'var(--text-muted)' : '#22c55e',
            background: scanning ? 'transparent' : 'rgba(34,197,94,0.05)',
          }}
        >
          {scanning ? '⏳ 扫描中...' : '🔍 开始扫描'}
        </button>
        <button
          onClick={handleExportCSV}
          disabled={!result?.signals?.length}
          className="px-2 py-1 rounded-md text-xs border flex items-center gap-1 transition-colors"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', opacity: !result?.signals?.length ? 0.5 : 1 }}
        >
          📥 导出CSV
        </button>
      </div>

      {/* 扫描结果 */}
      {scanning ? (
        <div className="text-center py-12">
          <div className="inline-block w-6 h-6 border-2 rounded-full animate-spin" style={{ borderColor: 'var(--accent-blue)', borderTopColor: 'transparent' }} />
          <div className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
            正在用 {strategy.name} 策略扫描全市场...
          </div>
        </div>
      ) : error ? (
        <div className="text-center py-8 text-sm" style={{ color: '#ef4444' }}>扫描失败: {error}</div>
      ) : result ? (
        <>
          <div className="text-xs px-1" style={{ color: 'var(--text-muted)' }}>
            扫描 {result.scanned} · 命中 <strong style={{ color: '#ef4444' }}>{result.summary?.total || 0}</strong>
          </div>
          {result.signals?.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {result.signals.map((s, i) => (
                <SignalCard key={i} signal={s} mode="watchlist" showWatchBtn showMarketState showBuyPower showAnalysisButton />
              ))}
            </div>
          ) : (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-muted)' }}>
              今日无符合条件的B点信号
            </div>
          )}
        </>
      ) : (
        <div className="text-center py-8 text-sm" style={{ color: 'var(--text-muted)' }}>
          点击"开始扫描"运行策略
        </div>
      )}
    </div>
  );
}
