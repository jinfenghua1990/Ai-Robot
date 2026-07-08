import { useState, useEffect, useMemo } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import SignalCard from '../components/trading/SignalCard';
import { apiFetch } from '../utils/request';

const RESONANCE_COLORS = {
  2: '#3b82f6',
  3: '#eab308',
  4: '#f97316',
  5: '#ef4444',
};
const getResonanceColor = (count) => RESONANCE_COLORS[count] || '#dc2626';

const MIN_COUNT_OPTIONS = [
  { value: 1, label: '全部' },
  { value: 2, label: '2+共振' },
  { value: 3, label: '3+共振' },
  { value: 4, label: '4+共振' },
  { value: 5, label: '5+共振' },
];

export default function ResonancePage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [minCount, setMinCount] = useState(1);

  useEffect(() => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    const controller = new AbortController();
    (async () => {
      const { ok, data: d, error: err } = await apiFetch(
        `/api/strategy-resonance?date=${selectedDate}&min_count=${minCount}`,
        { signal: controller.signal }
      );
      if (!ok) {
        if (/abort/i.test(err || '')) return;
        setError('数据加载失败');
        setLoading(false);
        return;
      }
      setData(d);
      setLoading(false);
    })();
    return () => controller.abort();
  }, [selectedDate, minCount]);

  const toSignal = (stock) => ({
    secCode: stock.secCode,
    secName: stock.name,
    sector: stock.sector,
    signalLabel: `${stock.resonance_count}共振`,
    signalColor: getResonanceColor(stock.resonance_count),
    score: stock.total_score,
    positiveFactors: stock.strategies.map(s => ({
      factor: `${s.icon} ${s.strategy_name}`,
      weight: s.score,
      detail: `${s.strategy_name} 评分 ${s.score}`,
    })),
  });

  const distribution = useMemo(() => {
    if (!data?.stocks) return [];
    const dist = {};
    data.stocks.forEach(s => {
      const c = s.resonance_count;
      dist[c] = (dist[c] || 0) + 1;
    });
    return Object.entries(dist).sort((a, b) => Number(a[0]) - Number(b[0]));
  }, [data]);

  if (!selectedDate) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        正在获取交易日期...
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* 标题 + 日期导航 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          🎯 多策略共振
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
        </h2>
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
      </div>

      {/* 说明卡片 */}
      <div className="rounded-xl border px-3 py-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-sm mb-1"><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 多策略共振</div>
        <div className="text-xs space-y-1" style={{ color: 'var(--text-secondary)' }}>
          <div>共振 = 同一只股票被多个策略同时命中。不同维度（趋势/资金/形态/突破）共振意味着更强信号，胜率更高。</div>
          <div className="flex items-center gap-3 flex-wrap mt-1">
            {data?.strategy_meta?.map(s => (
              <span key={s.key} className="text-[11px]" style={{ color: 'var(--text-muted)' }}>
                {s.icon} {s.name}
              </span>
            ))}
          </div>
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="rounded-lg p-3 flex items-center justify-between" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)' }}>
          <span className="text-sm" style={{ color: '#ef4444' }}>{error}</span>
          <button onClick={() => { setError(null); setMinCount(minCount); }} className="px-3 py-1 rounded text-xs border" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>重试</button>
        </div>
      )}

      {/* 统计条 + 共振数过滤 */}
      {data && (
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            共 <strong style={{ color: 'var(--text-primary)' }}>{data.total_stocks}</strong> 只 ·
            <strong style={{ color: 'var(--text-primary)' }}> {data.total_hits}</strong> 次命中
            {distribution.length > 0 && (
              <span className="ml-2">
                {distribution.map(([count, num]) => (
                  <span key={count} className="ml-1.5">
                    <span style={{ color: getResonanceColor(Number(count)) }}>{count}共振</span>:{num}
                  </span>
                ))}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>筛选:</span>
            {MIN_COUNT_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setMinCount(opt.value)}
                className="px-2 py-0.5 rounded text-xs border transition-all"
                style={{
                  borderColor: minCount === opt.value ? '#a855f7' : 'var(--border-color)',
                  background: minCount === opt.value ? 'rgba(168,85,247,0.1)' : 'transparent',
                  color: minCount === opt.value ? '#a855f7' : 'var(--text-secondary)',
                  fontWeight: minCount === opt.value ? 600 : 400,
                }}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* 股票列表 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-64 gap-2">
            <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: '#a855f7', borderTopColor: 'transparent' }} />
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>加载共振数据...</span>
          </div>
        ) : data?.stocks?.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {data.stocks.map((stock, idx) => (
              <div key={stock.ts_code} className="space-y-1">
                <div className="flex items-center gap-1.5 text-[10px]" style={{ color: 'var(--text-muted)' }}>
                  <span className="font-mono">#{idx + 1}</span>
                  <span className="px-1.5 py-0.5 rounded font-bold" style={{ background: `${getResonanceColor(stock.resonance_count)}15`, color: getResonanceColor(stock.resonance_count) }}>
                    {stock.resonance_count}共振 · 总分 {stock.total_score}
                  </span>
                  <span className="flex gap-0.5">
                    {stock.strategies.map(s => (
                      <span key={s.strategy_key} title={`${s.strategy_name} ${s.score}分`}>{s.icon}</span>
                    ))}
                  </span>
                </div>
                <SignalCard
                  signal={toSignal(stock)}
                  orders={[]}
                  showWatchBtn
                  mode="watchlist"
                  showMarketState
                  showBuyPower
                  showAnalysisButton
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="flex items-center justify-center h-64 text-sm" style={{ color: 'var(--text-muted)' }}>
            {data ? '当日无共振股票，降低筛选阈值试试（如切换到"全部"或"2+"）' : '暂无数据'}
          </div>
        )}
      </div>
    </div>
  );
}
