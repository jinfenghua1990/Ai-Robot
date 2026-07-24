import { useState, useEffect, useMemo, useCallback } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import StrategySignalCard from '../components/trading/StrategySignalCard';
import CardSafetyBoundary from '../components/CardSafetyBoundary';
import { apiFetch } from '../utils/request';

/**
 * 抗跌深V反转策略 v2
 *   1. 区间抗跌(真正跌过): 基准日(7月1日)至今累计跌幅在 -max_drawdown% ~ 0% 之间
 *      (只选7月1日以来真跌过的, 但没崩盘式下跌; 涨的股票不算"抗跌")
 *   2. 今日爆发: 今日收盘涨幅 ≥ min_close_up% (主板) / 1.5倍 (双创板)
 *   3. (可选) V形态: 盘中曾跌破 -min_intraday_drop% (强势V反)
 *   4. (可选) 板块共振: 同板块命中 ≥ N 只
 *   5. (可选) 板块强度: 板块命中数 ≤ max_sector_hit (避免被动跟涨稀释)
 *
 * 两个视图: all 全部命中 / sector 板块共振
 * 历史回测: T+1/T+3/T+5 胜率与超额收益
 */
const VIEW_OPTIONS = [
  { value: 'sector', label: '板块共振', icon: '🎯' },
  { value: 'all', label: '全部命中', icon: '📋' },
];

const DRAWDOWN_OPTIONS = [10, 20, 30];
const CLOSE_UP_OPTIONS = [3, 5, 6, 7, 10];
const INTRADAY_DROP_OPTIONS = [3, 5, 7, 10];
const SECTOR_MIN_OPTIONS = [2, 3, 4];
const SECTOR_MAX_OPTIONS = [5, 8, 12, 99];

const fmtPct = (v, withSign = true, digits = 2) => {
  if (v == null || Number.isNaN(v)) return '--';
  const sign = withSign && v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(digits)}%`;
};

const pctColor = (v) => {
  if (v == null || Number.isNaN(v)) return 'var(--text-muted)';
  return v >= 0 ? '#E24B4A' : '#1D9E75';
};

const winRateColor = (v) => {
  if (v == null || Number.isNaN(v)) return 'var(--text-muted)';
  if (v >= 60) return '#E24B4A';   // 高胜率 红
  if (v >= 40) return '#eab308';   // 中性 黄
  return '#1D9E75';               // 低胜率 绿 (反向信号)
};

export default function StrategyVReversalPage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  // 默认参数对齐用户原始想法: 抗跌(区间跌幅≤20%) + 今日涨≥6% + 不限板块 + 不要求V形态
  const [view, setView] = useState('all');
  const [maxDrawdown, setMaxDrawdown] = useState(20);
  const [minCloseUp, setMinCloseUp] = useState(6);
  const [minIntradayDrop, setMinIntradayDrop] = useState(5);
  const [requireVShape, setRequireVShape] = useState(false);
  const [minSectorHit, setMinSectorHit] = useState(2);
  const [maxSectorHit, setMaxSectorHit] = useState(8);
  const [baseDate] = useState('2026-07-01');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // 回测面板状态
  const [showBacktest, setShowBacktest] = useState(false);
  const [btData, setBtData] = useState(null);
  const [btLoading, setBtLoading] = useState(false);
  const [btError, setBtError] = useState(null);
  const [btDays, setBtDays] = useState(20);

  const load = useCallback(async () => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      date: selectedDate,
      base_date: baseDate,
      max_drawdown: String(maxDrawdown),
      min_close_up: String(minCloseUp),
      min_intraday_drop: String(minIntradayDrop),
      require_v_shape: String(requireVShape),
      min_sector_hit: String(minSectorHit),
      max_sector_hit: String(maxSectorHit),
      view,
    });
    const { ok, data: d, error: err } = await apiFetch(`/api/strategy-vreversal?${params}`);
    if (!ok) {
      setError(err || '加载失败');
      setData(null);
    } else {
      setData(d);
    }
    setLoading(false);
  }, [selectedDate, baseDate, maxDrawdown, minCloseUp, minIntradayDrop,
      requireVShape, minSectorHit, maxSectorHit, view]);

  useEffect(() => { load(); }, [load]);

  // 触发回测
  const runBacktest = useCallback(async () => {
    setBtLoading(true);
    setBtError(null);
    const params = new URLSearchParams({
      days: String(btDays),
      base_date: baseDate,
      max_drawdown: String(maxDrawdown),
      min_close_up: String(minCloseUp),
      min_intraday_drop: String(minIntradayDrop),
      require_v_shape: String(requireVShape),
      min_sector_hit: String(minSectorHit),
      max_sector_hit: String(maxSectorHit),
      view,
    });
    const { ok, data: d, error: err } = await apiFetch(`/api/strategy-vreversal/backtest?${params}`);
    if (!ok) {
      setBtError(err || '回测失败');
      setBtData(null);
    } else {
      setBtData(d);
    }
    setBtLoading(false);
  }, [btDays, baseDate, maxDrawdown, minCloseUp, minIntradayDrop,
      requireVShape, minSectorHit, maxSectorHit, view]);

  // 按 sector 分组(视图=sector时)
  const groupedSectors = useMemo(() => {
    if (!data?.stocks) return [];
    const map = {};
    for (const s of data.stocks) {
      const sec = s.sector || '未分类';
      if (!map[sec]) map[sec] = [];
      map[sec].push(s);
    }
    return Object.entries(map).map(([sector, stocks]) => ({
      sector,
      stocks,
      count: stocks.length,
      avgTodayPct: stocks.reduce((a, b) => a + (b.today_pct || 0), 0) / stocks.length,
      avgPeriodPct: stocks.reduce((a, b) => a + (b.period_pct || 0), 0) / stocks.length,
      avgVRebound: stocks.reduce((a, b) => a + (b.v_rebound_pct || 0), 0) / stocks.length,
    })).sort((a, b) => b.count - a.count || b.avgTodayPct - a.avgTodayPct);
  }, [data]);

  const sectorColors = useMemo(() => {
    const colors = ['#6366f1','#a855f7','#ec4899','#f43f5e','#f97316','#eab308','#22c55e','#14b8a6','#06b6d4','#3b82f6'];
    const m = {};
    groupedSectors.forEach((s, i) => { m[s.sector] = colors[i % colors.length]; });
    return m;
  }, [groupedSectors]);

  // 回测质量判定
  const btQuality = useMemo(() => {
    if (!btData?.summary) return null;
    const s = btData.summary;
    // 综合判定: T+3 胜率 + 超额收益
    const winAvg = (s.win_rate_t1 + s.win_rate_t3 + s.win_rate_t5) / 3;
    const excessAvg = (s.excess_t1 + s.excess_t3 + s.excess_t5) / 3;
    if (winAvg >= 55 && excessAvg >= 1) {
      return { label: '✅ 策略有效', color: '#E24B4A', desc: `三周期平均胜率 ${winAvg.toFixed(1)}%, 超额 ${excessAvg.toFixed(2)}%` };
    }
    if (winAvg <= 35 && excessAvg <= -1) {
      return { label: '⚠️ 反向信号', color: '#1D9E75', desc: `策略为反向指标, 考虑反向操作或弃用. 三周期平均胜率 ${winAvg.toFixed(1)}%, 超额 ${excessAvg.toFixed(2)}%` };
    }
    return { label: '⚖️ 信号中性', color: '#eab308', desc: `三周期平均胜率 ${winAvg.toFixed(1)}%, 超额 ${excessAvg.toFixed(2)}%` };
  }, [btData]);

  if (!selectedDate) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        正在获取交易日期...
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* 标题 + 日期导航 + 回测按钮 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-base font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <span>🛡️</span>
          <span>抗跌深V反转</span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-normal"
                style={{ background: 'rgba(99,102,241,0.12)', color: '#6366f1' }}>
            基准 {baseDate.slice(5).replace('-', '/')}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-normal"
                style={{ background: requireVShape ? 'rgba(226,75,74,0.1)' : 'var(--bg-elevated)',
                         color: requireVShape ? '#E24B4A' : 'var(--text-muted)' }}>
            {requireVShape ? 'V形态 ✓' : 'V形态 ✗'}
          </span>
        </h2>
        <div className="flex items-center gap-1">
          <button
            onClick={() => setShowBacktest(v => !v)}
            className="px-2 py-0.5 rounded text-xs border flex items-center gap-1"
            style={{
              borderColor: showBacktest ? '#6366f1' : 'var(--border-color)',
              background: showBacktest ? 'rgba(99,102,241,0.1)' : 'transparent',
              color: showBacktest ? '#6366f1' : 'var(--text-secondary)',
              fontWeight: showBacktest ? 600 : 400,
            }}
            title="展开/收起历史回测面板"
          >
            📊 历史回测
          </button>
          <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
        </div>
      </div>

      {/* 说明卡片 */}
      <div className="rounded-lg border px-2.5 py-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs mb-0.5"><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 抗跌深V反转 v2</div>
        <div className="text-[10px] space-y-0.5" style={{ color: 'var(--text-secondary)' }}>
          <div>1️⃣ <strong>区间抗跌(真正跌过)</strong>: 7月1日至今累计跌幅在 -{maxDrawdown}% ~ 0% 之间 (只选真跌过的, 排除涨的股票)</div>
          <div>2️⃣ <strong>今日爆发</strong>: 今日收盘涨幅 ≥ {minCloseUp}% (主板) / {minCloseUp * 1.5}% (双创板)</div>
          <div>3️⃣ <strong>V形态{requireVShape ? '(启用)' : '(已关闭)'}</strong>: 盘中曾跌破 -{minIntradayDrop}% (强势V反)</div>
          <div>4️⃣ <strong>板块共振{view === 'sector' ? '(启用)' : '(未启用)'}</strong>: 同板块 ≥ {minSectorHit} 只 且 ≤ {maxSectorHit === 99 ? '不限' : `${maxSectorHit}只`}</div>
        </div>
      </div>

      {/* 参数控制条 */}
      <div className="rounded-lg border p-2 flex items-center gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {/* 视图切换 */}
        <ParamGroup label="视图">
          {VIEW_OPTIONS.map(opt => (
            <ParamBtn key={opt.value} active={view === opt.value} onClick={() => setView(opt.value)}>
              {opt.icon} {opt.label}
            </ParamBtn>
          ))}
        </ParamGroup>

        <Divider />

        {/* 跌幅阈值 (区间跌幅上限, 下限固定为0=只选跌过的) */}
        <ParamGroup label="区间跌幅">
          {DRAWDOWN_OPTIONS.map(v => (
            <ParamBtn key={v} active={maxDrawdown === v} onClick={() => setMaxDrawdown(v)}>-{v}~0%</ParamBtn>
          ))}
        </ParamGroup>

        {/* 收盘涨幅 (分板) */}
        <ParamGroup label="主板收盘涨≥">
          {CLOSE_UP_OPTIONS.map(v => (
            <ParamBtn key={v} active={minCloseUp === v} onClick={() => setMinCloseUp(v)}>
              {v}%<span className="opacity-60">/双创{v * 1.5}%</span>
            </ParamBtn>
          ))}
        </ParamGroup>

        {/* V 形态开关 + 盘中跌幅 */}
        <ParamGroup label="V形态">
          <button
            onClick={() => setRequireVShape(v => !v)}
            className="px-1.5 py-0.5 rounded text-xs border"
            style={{
              borderColor: requireVShape ? '#E24B4A' : 'var(--border-color)',
              background: requireVShape ? 'rgba(226,75,74,0.1)' : 'transparent',
              color: requireVShape ? '#E24B4A' : 'var(--text-muted)',
              fontWeight: requireVShape ? 600 : 400,
            }}
          >
            {requireVShape ? '✓ 开' : '✗ 关'}
          </button>
          {requireVShape && (
            <>
              {INTRADAY_DROP_OPTIONS.map(v => (
                <ParamBtn key={v} active={minIntradayDrop === v} onClick={() => setMinIntradayDrop(v)}>-{v}%</ParamBtn>
              ))}
            </>
          )}
        </ParamGroup>

        {/* 板块共振数 (仅 sector 视图生效) */}
        {view === 'sector' && (
          <>
            <ParamGroup label="板块≥">
              {SECTOR_MIN_OPTIONS.map(v => (
                <ParamBtn key={v} active={minSectorHit === v} onClick={() => setMinSectorHit(v)}>{v}只</ParamBtn>
              ))}
            </ParamGroup>
            <ParamGroup label="板块≤">
              {SECTOR_MAX_OPTIONS.map(v => (
                <ParamBtn key={v} active={maxSectorHit === v} onClick={() => setMaxSectorHit(v)}>
                  {v === 99 ? '不限' : `${v}只`}
                </ParamBtn>
              ))}
            </ParamGroup>
          </>
        )}

        <div className="flex-1" />
        <button onClick={load} disabled={loading}
          className="px-2 py-0.5 rounded text-xs border flex items-center gap-1"
          style={{ borderColor: 'rgba(99,102,241,0.4)', color: '#6366f1' }}>
          {loading ? '⏳' : '🔄'} 刷新
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="rounded p-2 text-xs" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>
          {error}
        </div>
      )}

      {/* 历史回测面板 */}
      {showBacktest && (
        <div className="rounded-lg border p-2.5 space-y-2"
             style={{ borderColor: 'rgba(99,102,241,0.4)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="flex items-center gap-2">
              <span className="text-xs font-bold" style={{ color: '#6366f1' }}>📊 历史回测</span>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                · 用当前参数跑过去 N 天命中率与 T+1/T+3/T+5 收益率
              </span>
            </div>
            <div className="flex items-center gap-1">
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>回测天数:</span>
              {[10, 20, 30].map(v => (
                <button key={v} onClick={() => setBtDays(v)}
                  className="px-1.5 py-0.5 rounded text-[10px] border"
                  style={{
                    borderColor: btDays === v ? '#6366f1' : 'var(--border-color)',
                    background: btDays === v ? 'rgba(99,102,241,0.1)' : 'transparent',
                    color: btDays === v ? '#6366f1' : 'var(--text-secondary)',
                    fontWeight: btDays === v ? 600 : 400,
                  }}>{v}天</button>
              ))}
              <button
                onClick={runBacktest} disabled={btLoading}
                className="ml-1 px-2 py-0.5 rounded text-xs border flex items-center gap-1"
                style={{ borderColor: '#6366f1', color: '#6366f1', background: 'rgba(99,102,241,0.08)' }}
              >
                {btLoading ? '⏳ 跑回测...' : '▶ 运行回测'}
              </button>
            </div>
          </div>

          {btError && (
            <div className="rounded p-2 text-xs" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
              {btError}
            </div>
          )}

          {btLoading && !btData && (
            <div className="flex items-center justify-center h-32 gap-2">
              <div className="w-4 h-4 border-2 rounded-full animate-spin" style={{ borderColor: '#6366f1', borderTopColor: 'transparent' }} />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                正在跑 {btDays} 天回测, 每天需重新筛选命中, 耗时约 {Math.ceil(btDays * 0.4)} 秒...
              </span>
            </div>
          )}

          {btData?.summary && (
            <>
              {/* 策略质量提示 */}
              {btQuality && (
                <div className="rounded p-2 flex items-center gap-2 text-xs"
                     style={{ background: `${btQuality.color}10`, border: `1px solid ${btQuality.color}40` }}>
                  <span className="font-bold" style={{ color: btQuality.color }}>{btQuality.label}</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{btQuality.desc}</span>
                </div>
              )}

              {/* 回测汇总 */}
              <BacktestSummary summary={btData.summary} />
              {/* 每日明细 */}
              <BacktestDailyTable daily={btData.daily_stats} />
            </>
          )}
        </div>
      )}

      {/* 统计条 */}
      {data && (
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between flex-wrap gap-1.5">
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              命中 <strong style={{ color: 'var(--text-primary)' }}>{data.summary.total}</strong> 只
              {view === 'sector' && (
                <>
                  {' '}· 板块共振 <strong style={{ color: '#6366f1' }}>{data.summary.sector_resonance_count}</strong> 个
                  {' '}· 候选总数 <strong style={{ color: 'var(--text-secondary)' }}>{data.summary.total_all}</strong> 只
                  {data.summary.sector_crowded_count > 0 && (
                    <span className="ml-1 px-1 rounded text-[10px]"
                          style={{ background: 'rgba(234,179,8,0.12)', color: '#eab308' }}>
                      ⚠ 拥挤板块 {data.summary.sector_crowded_count}
                    </span>
                  )}
                </>
              )}
            </div>
            {data?.sectors?.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                {data.sectors.slice(0, 10).map(s => (
                  <span key={s.sector} className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{ background: s.is_too_crowded ? 'rgba(234,179,8,0.1)' : 'rgba(99,102,241,0.08)',
                                 color: s.is_too_crowded ? '#eab308' : 'var(--text-secondary)' }}
                        title={s.is_too_crowded ? '板块命中过多, 已过滤' : (s.is_resonance ? '板块共振' : '孤狼行情')}>
                    {s.sector} <strong style={{ color: s.is_too_crowded ? '#eab308' : '#6366f1' }}>{s.count}</strong>
                  </span>
                ))}
              </div>
            )}
          </div>
        </div>
      )}

      {/* 股票列表 */}
      <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        {loading ? (
          <div className="flex items-center justify-center h-64 gap-2">
            <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: '#6366f1', borderTopColor: 'transparent' }} />
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>筛选抗跌深V反转...</span>
          </div>
        ) : data?.stocks?.length > 0 ? (
          view === 'sector' ? (
            <div className="space-y-2">
              {groupedSectors.map(grp => (
                <div key={grp.sector} className="rounded border overflow-hidden"
                     style={{ borderColor: `${sectorColors[grp.sector]}30` }}>
                  {/* 板块头: 左色块 + 板块名 + 右结论标签 */}
                  <div className="flex items-center justify-between px-2.5 py-1"
                       style={{ background: `${sectorColors[grp.sector]}10`, borderBottom: `1px solid ${sectorColors[grp.sector]}30` }}>
                    <div className="flex items-center gap-2">
                      <span className="w-1.5 h-3.5 rounded" style={{ background: sectorColors[grp.sector] }} />
                      <span className="text-sm font-bold" style={{ color: sectorColors[grp.sector] }}>{grp.sector}</span>
                      <span className="text-[10px] px-1 rounded"
                            style={{ background: `${sectorColors[grp.sector]}20`, color: sectorColors[grp.sector] }}>
                        {grp.count}只
                      </span>
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                        今日均 <strong style={{ color: pctColor(grp.avgTodayPct) }}>{fmtPct(grp.avgTodayPct)}</strong>
                        {' '}· 区间均 <strong style={{ color: pctColor(grp.avgPeriodPct) }}>{fmtPct(grp.avgPeriodPct)}</strong>
                        {requireVShape && grp.avgVRebound > 0 && (
                          <> {' '}· V均 <strong style={{ color: '#6366f1' }}>{fmtPct(grp.avgVRebound, true, 1)}</strong></>
                        )}
                      </span>
                    </div>
                    <div className="flex items-center gap-1 text-[10px]">
                      {grp.count >= minSectorHit && (
                        <span className="px-1 py-0.5 rounded"
                              style={{ background: 'rgba(99,102,241,0.15)', color: '#6366f1' }}>共振</span>
                      )}
                      {grp.count > maxSectorHit && (
                        <span className="px-1 py-0.5 rounded"
                              style={{ background: 'rgba(234,179,8,0.15)', color: '#eab308' }}>拥挤</span>
                      )}
                    </div>
                  </div>
                  {/* 板块内个股 - 左右双栏 */}
                  <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 p-1.5">
                    {grp.stocks.map(stock => (
                      <div key={stock.ts_code} style={{ contentVisibility: 'auto', containIntrinsicSize: '300px' }}>
                        <CardSafetyBoundary>
                          <VReversalSignalItem stock={stock} sectorColor={sectorColors[grp.sector]}
                                              requireVShape={requireVShape} />
                        </CardSafetyBoundary>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {data.stocks.map(stock => (
                <div key={stock.ts_code} style={{ contentVisibility: 'auto', containIntrinsicSize: '300px' }}>
                  <CardSafetyBoundary>
                    <VReversalSignalItem stock={stock} sectorColor="#6366f1" requireVShape={requireVShape} />
                  </CardSafetyBoundary>
                </div>
              ))}
            </div>
          )
        ) : (
          <div className="flex items-center justify-center h-64 text-xs" style={{ color: 'var(--text-muted)' }}>
            {data ? '当日无命中, 可尝试: ① 关闭V形态 ② 降低今日涨幅 ③ 放宽区间跌幅' : '暂无数据'}
          </div>
        )}
      </div>
    </div>
  );
}

/* ============ 子组件 ============ */

const ParamGroup = ({ label, children }) => (
  <div className="flex items-center gap-0.5">
    <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}:</span>
    {children}
  </div>
);

const Divider = () => <div className="w-px h-4" style={{ background: 'var(--border-color)' }} />;

const ParamBtn = ({ active, onClick, children }) => (
  <button onClick={onClick}
    className="px-1.5 py-0.5 rounded text-xs border flex items-center gap-0.5"
    style={{
      borderColor: active ? '#6366f1' : 'var(--border-color)',
      background: active ? 'rgba(99,102,241,0.1)' : 'transparent',
      color: active ? '#6366f1' : 'var(--text-secondary)',
      fontWeight: active ? 600 : 400,
    }}>
    {children}
  </button>
);

/** 回测汇总: 三周期胜率 / 平均收益 / 超额收益 */
const BacktestSummary = ({ summary }) => {
  const cells = [
    { label: 'T+1', win: summary.win_rate_t1, ret: summary.avg_return_t1, mkt: summary.market_avg_t1, excess: summary.excess_t1 },
    { label: 'T+3', win: summary.win_rate_t3, ret: summary.avg_return_t3, mkt: summary.market_avg_t3, excess: summary.excess_t3 },
    { label: 'T+5', win: summary.win_rate_t5, ret: summary.avg_return_t5, mkt: summary.market_avg_t5, excess: summary.excess_t5 },
  ];
  return (
    <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
      {cells.map(c => (
        <div key={c.label} className="rounded border p-2"
             style={{ borderColor: 'var(--border-color)', background: 'var(--bg-elevated)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <span className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>{c.label}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded font-bold"
                  style={{ background: `${winRateColor(c.win)}15`, color: winRateColor(c.win) }}>
              胜率 {fmtPct(c.win, false, 1)}
            </span>
          </div>
          <div className="space-y-0.5 text-[10px]" style={{ color: 'var(--text-secondary)' }}>
            <div className="flex justify-between">
              <span>策略平均</span>
              <strong style={{ color: pctColor(c.ret) }}>{fmtPct(c.ret)}</strong>
            </div>
            <div className="flex justify-between">
              <span>大盘平均</span>
              <strong style={{ color: pctColor(c.mkt) }}>{fmtPct(c.mkt)}</strong>
            </div>
            <div className="flex justify-between border-t pt-0.5 mt-0.5" style={{ borderColor: 'var(--border-color)' }}>
              <span>超额收益</span>
              <strong style={{ color: pctColor(c.excess) }}>{fmtPct(c.excess)}</strong>
            </div>
          </div>
        </div>
      ))}
      <div className="col-span-full sm:col-span-3 flex items-center justify-between text-[10px] px-2 py-1 rounded"
           style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
        <span>累计 {summary.total_days} 天 · 总命中 {summary.total_hits} 只 · 日均 {summary.avg_hit_per_day} 只</span>
        <span>胜率颜色: <span style={{ color: '#E24B4A' }}>≥60%</span> / <span style={{ color: '#eab308' }}>40-60%</span> / <span style={{ color: '#1D9E75' }}>≤40% (反向)</span></span>
      </div>
    </div>
  );
};

/** 回测每日明细表 */
const BacktestDailyTable = ({ daily }) => {
  if (!daily?.length) return null;
  return (
    <div className="rounded border overflow-auto" style={{ borderColor: 'var(--border-color)' }}>
      <table className="w-full text-[10px]">
        <thead>
          <tr style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
            <th className="px-2 py-1 text-left">日期</th>
            <th className="px-2 py-1 text-right">命中</th>
            <th className="px-2 py-1 text-right">T+1</th>
            <th className="px-2 py-1 text-right">大盘 T+1</th>
            <th className="px-2 py-1 text-right">T+3</th>
            <th className="px-2 py-1 text-right">大盘 T+3</th>
            <th className="px-2 py-1 text-right">T+5</th>
            <th className="px-2 py-1 text-right">大盘 T+5</th>
          </tr>
        </thead>
        <tbody>
          {daily.map(d => (
            <tr key={d.date} style={{ borderBottom: '1px solid var(--border-color)' }}>
              <td className="px-2 py-1" style={{ color: 'var(--text-secondary)' }}>{d.date}</td>
              <td className="px-2 py-1 text-right" style={{ color: d.hit_count > 0 ? '#6366f1' : 'var(--text-muted)' }}>
                <strong>{d.hit_count}</strong>
              </td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.avg_t1) }}>{fmtPct(d.avg_t1)}</td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.market_t1), opacity: 0.7 }}>{fmtPct(d.market_t1)}</td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.avg_t3) }}>{fmtPct(d.avg_t3)}</td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.market_t3), opacity: 0.7 }}>{fmtPct(d.market_t3)}</td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.avg_t5) }}>{fmtPct(d.avg_t5)}</td>
              <td className="px-2 py-1 text-right" style={{ color: pctColor(d.market_t5), opacity: 0.7 }}>{fmtPct(d.market_t5)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

/**
 * 单只命中股票卡片
 * - 把 strategy-vreversal API 的字段注入到 SignalCard 期望的 signal 结构
 * - 显示今日涨幅/区间涨跌幅/V形态指标
 */
const VReversalSignalItem = ({ stock, sectorColor, requireVShape }) => {
  const signal = useMemo(() => {
    const vShapeStrong = requireVShape && stock.v_rebound_pct != null && stock.v_rebound_pct >= 10;
    // 股票名称: 优先用 name, 没有就退到 ts_code
    const stockName = stock.name || stock.ts_code;
    return {
      secCode: stock.ts_code,
      secName: stockName,
      code: stock.ts_code,
      signalLabel: `${stock.today_pct >= 0 ? '+' : ''}${stock.today_pct.toFixed(1)}%`,
      signalColor: sectorColor,
      score: stock.today_pct,
      sector: stock.sector,
      // 注入 position: SignalCard 行1 的「当日 X% / 现价」读这里
      position: {
        price: stock.today_close,
        dayProfitPct: stock.today_pct,
        avg_cost: stock.base_close,
        count: 0,
        profitPct: stock.period_pct, // 区间涨跌幅(相对基准日)
      },
      // 注入 quote: 实时图表与 sparkline 读这里
      quote: {
        price: stock.today_close,
        yesterdayClose: stock.pre_close,
        changePct: stock.today_pct,
        high: stock.today_close,
        low: stock.today_close,
      },
      // V 形态附加数据 (用于卡片角标, 后续可扩展)
      _vreversal: {
        minIntradayPct: stock.min_intraday_pct,
        vReboundPct: stock.v_rebound_pct,
        requiredCloseUp: stock.required_close_up,
        intradayRange: stock.intraday_range_pct,
        maxUpPct: stock.max_up_pct,
        isVShapeStrong: vShapeStrong,
        board: stock.board,
      },
    };
  }, [stock, sectorColor, requireVShape]);

  return (
    <StrategySignalCard
      signal={signal}
      mode="strategy"
      showWatchBtn
      showAnalysisButton
    />
  );
};
