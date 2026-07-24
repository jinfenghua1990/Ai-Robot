import { useState, useEffect, useMemo, useCallback } from 'react';
import { useDatePicker } from '../hooks/useDatePicker';
import DateNavigator from '../components/DateNavigator';
import StrategySignalCard from '../components/trading/StrategySignalCard';
import StrategyResultsTable from '../components/StrategyResultsTable';
import CardSafetyBoundary from '../components/CardSafetyBoundary';
import { apiFetch } from '../utils/request';

/**
 * 7月抗跌反弹观察池（固定口径版）
 *
 * 用户原始策略（2026-07-01 至今）:
 *   1) 区间净跌: 基准日(7/1)至今 收盘累计跌幅 在 -maxDrawdown% ~ 0% 之间
 *      (真跌过、但没崩盘式下跌; 涨的股票不算"抗跌"不纳入)
 *   2) 今日爆发: 今日收盘涨幅 ≥ minCloseUp%（主板 / 双创板 1.5×）
 *   - 不要求 V 形态
 *   - 不要求板块共振
 *   → 纯观察池：盘后看哪些票"抗跌且今日反包"，适合当板块强度信号，T+1 谨慎追
 *
 * 复用后端 /api/strategy-vreversal，固定 require_v_shape=false / view=all / 无板块约束。
 */
const DRAWDOWN_OPTIONS = [10, 20, 30];
const CLOSE_UP_OPTIONS = [5, 6, 10];

const fmtPct = (v, withSign = true, digits = 2) => {
  if (v == null || Number.isNaN(v)) return '--';
  const sign = withSign && v >= 0 ? '+' : '';
  return `${sign}${v.toFixed(digits)}%`;
};

const pctColor = (v) => {
  if (v == null || Number.isNaN(v)) return 'var(--text-muted)';
  return v >= 0 ? '#E24B4A' : '#1D9E75';
};

export default function StrategyDrawdownReboundPage() {
  const { selectedDate, setSelectedDate, changeDate } = useDatePicker();
  // 用户精确口径: 7/1 净跌 0%~20% + 今日涨 ≥5%
  const [maxDrawdown, setMaxDrawdown] = useState(20);
  const [minCloseUp, setMinCloseUp] = useState(5);
  const [baseDate] = useState('2026-07-01');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    if (!selectedDate) return;
    setLoading(true);
    setError(null);
    const params = new URLSearchParams({
      date: selectedDate,
      base_date: baseDate,
      max_drawdown: String(maxDrawdown),
      min_close_up: String(minCloseUp),
      min_intraday_drop: '5',
      require_v_shape: 'false',
      min_sector_hit: '1',
      max_sector_hit: '99',
      view: 'all',
    });
    const { ok, data: d, error: err } = await apiFetch(`/api/strategy-vreversal?${params}`);
    if (!ok) {
      setError(err || '加载失败');
      setData(null);
    } else {
      setData(d);
    }
    setLoading(false);
  }, [selectedDate, baseDate, maxDrawdown, minCloseUp]);

  useEffect(() => { load(); }, [load]);

  // 板块分布（仅展示，不做共振过滤）
  const sectorChips = useMemo(() => {
    if (!data?.sectors?.length) return [];
    return [...data.sectors]
      .sort((a, b) => b.count - a.count)
      .slice(0, 12);
  }, [data]);

  if (!selectedDate) {
    return (
      <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
        正在获取交易日期...
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* 标题 + 日期导航 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-base font-bold flex items-center gap-2" style={{ color: 'var(--text-primary)' }}>
          <span>📉</span>
          <span>7月抗跌反弹</span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-normal"
                style={{ background: 'rgba(249,115,22,0.12)', color: '#f97316' }}>
            基准 {baseDate.slice(5).replace('-', '/')}
          </span>
          <span className="px-1.5 py-0.5 rounded text-[10px] font-normal"
                style={{ background: 'var(--bg-elevated)', color: 'var(--text-muted)' }}>
            观察池
          </span>
        </h2>
        <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
      </div>

      {/* 口径说明卡片 */}
      <div className="rounded-lg border px-2.5 py-1.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="text-xs mb-0.5"><strong style={{ color: 'var(--text-primary)' }}>📖 策略口径</strong> · 7月抗跌反弹（固定）</div>
        <div className="text-[10px] space-y-0.5" style={{ color: 'var(--text-secondary)' }}>
          <div>1️⃣ <strong>区间净跌</strong>: {baseDate.slice(5).replace('-', '/')} 至今收盘累计跌幅在 <strong style={{ color: '#f97316' }}>-{maxDrawdown}% ~ 0%</strong> 之间（只选真跌过、没崩盘的）</div>
          <div>2️⃣ <strong>今日爆发</strong>: 今日收盘涨幅 ≥ <strong style={{ color: '#f97316' }}>{minCloseUp}%</strong>（主板）/ <strong style={{ color: '#f97316' }}>{minCloseUp * 1.5}%</strong>（双创板）</div>
          <div>3️⃣ 不要求 V 形态、不要求板块共振 —— 纯盘后观察，T+1 谨慎追涨</div>
        </div>
      </div>

      {/* 参数控制条（仅两个核心旋钮，保持清爽） */}
      <div className="rounded-lg border p-2 flex items-center gap-2 flex-wrap" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <ParamGroup label="区间跌幅≤">
          {DRAWDOWN_OPTIONS.map(v => (
            <ParamBtn key={v} active={maxDrawdown === v} onClick={() => setMaxDrawdown(v)}>-{v}%</ParamBtn>
          ))}
        </ParamGroup>
        <Divider />
        <ParamGroup label="今涨≥">
          {CLOSE_UP_OPTIONS.map(v => (
            <ParamBtn key={v} active={minCloseUp === v} onClick={() => setMinCloseUp(v)}>
              {v}%<span className="opacity-60">/双创{v * 1.5}%</span>
            </ParamBtn>
          ))}
        </ParamGroup>
        <div className="flex-1" />
        <button onClick={load} disabled={loading}
          className="px-2 py-0.5 rounded text-xs border flex items-center gap-1"
          style={{ borderColor: 'rgba(249,115,22,0.4)', color: '#f97316' }}>
          {loading ? '⏳' : '🔄'} 刷新
        </button>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="rounded p-2 text-xs" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>
          {error}
        </div>
      )}

      {/* 统计条 + 板块分布 */}
      {data && (
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between flex-wrap gap-1.5">
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              命中 <strong style={{ color: 'var(--text-primary)' }}>{data.summary?.total ?? 0}</strong> 只
              {' · '}候选池 <strong style={{ color: 'var(--text-secondary)' }}>{data.summary?.total_all ?? 0}</strong> 只
            </div>
            {sectorChips.length > 0 && (
              <div className="flex items-center gap-1 flex-wrap">
                {sectorChips.map(s => (
                  <span key={s.sector} className="text-[10px] px-1.5 py-0.5 rounded"
                        style={{ background: 'rgba(249,115,22,0.08)', color: 'var(--text-secondary)' }}>
                    {s.sector} <strong style={{ color: '#f97316' }}>{s.count}</strong>
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
            <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: '#f97316', borderTopColor: 'transparent' }} />
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>筛选抗跌反弹...</span>
          </div>
        ) : data?.stocks?.length > 0 ? (
          <StrategyResultsTable
            rows={data.stocks}
            getRowKey={(row, i) => row.ts_code || i}
            columns={[
              { key: 'code', label: '代码', render: r => r.ts_code, width: '70px' },
              { key: 'name', label: '名称', render: r => r.name, width: '80px' },
              { key: 'todayPct', label: '今日涨幅', render: r => r.today_pct, type: 'percent', align: 'right', width: '75px' },
              { key: 'periodPct', label: '区间涨跌', render: r => r.period_pct, type: 'percent', align: 'right', width: '75px' },
              { key: 'minIntra', label: '盘中最低', render: r => r.min_intraday_pct, type: 'percent', align: 'right', width: '75px' },
              { key: 'vRebound', label: '反弹幅度', render: r => r.v_rebound_pct, type: 'percent', align: 'right', width: '75px' },
              { key: 'sector', label: '板块', render: r => r.sector, width: '80px' },
              { key: 'board', label: '板', render: r => r.board, width: '60px' },
            ]}
            cardComponent={StrategySignalCard}
            cardProps={{ mode: 'watchlist', showWatchBtn: true, showAnalysisButton: true }}
          />
        ) : (
          <div className="flex items-center justify-center h-64 text-xs" style={{ color: 'var(--text-muted)' }}>
            {data ? '当日无命中, 可尝试: ① 降低今日涨幅 ② 放宽区间跌幅' : '暂无数据'}
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
      borderColor: active ? '#f97316' : 'var(--border-color)',
      background: active ? 'rgba(249,115,22,0.1)' : 'transparent',
      color: active ? '#f97316' : 'var(--text-secondary)',
      fontWeight: active ? 600 : 400,
    }}>
    {children}
  </button>
);

/**
 * 单只命中股票卡片
 * 复用 strategy-vreversal API 的字段, 注入 SignalCard 期望的 signal 结构。
 * 本策略不要求 V 形态, 故 vRebound 角标恒为非强。
 */
const ReboundSignalItem = ({ stock, sectorColor }) => {
  const signal = useMemo(() => {
    const stockName = stock.name || stock.ts_code;
    return {
      secCode: stock.ts_code,
      secName: stockName,
      code: stock.ts_code,
      signalLabel: `${stock.today_pct >= 0 ? '+' : ''}${stock.today_pct.toFixed(1)}%`,
      signalColor: sectorColor,
      score: stock.today_pct,
      sector: stock.sector,
      position: {
        price: stock.today_close,
        dayProfitPct: stock.today_pct,
        avg_cost: stock.base_close,
        count: 0,
        profitPct: stock.period_pct, // 区间相对基准日涨跌幅
      },
      quote: {
        price: stock.today_close,
        yesterdayClose: stock.pre_close,
        changePct: stock.today_pct,
        high: stock.today_close,
        low: stock.today_close,
      },
      _vreversal: {
        minIntradayPct: stock.min_intraday_pct,
        vReboundPct: stock.v_rebound_pct,
        requiredCloseUp: stock.required_close_up,
        intradayRange: stock.intraday_range_pct,
        maxUpPct: stock.max_up_pct,
        isVShapeStrong: false,
        board: stock.board,
      },
    };
  }, [stock, sectorColor]);

  return (
    <SignalCard
      signal={signal}
      mode="watchlist"
      showWatchBtn
      showAnalysisButton
    />
  );
};
