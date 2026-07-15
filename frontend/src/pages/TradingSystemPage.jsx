/**
 * 游资详情页 — 游资买入了什么、买了多少、什么阶段
 *
 * 数据源：/api/leader/system
 *  - leader(主龙头 1只):加冕特写
 *  - candidates(候选龙头 ≤3只):横向卡片
 *  - all_stocks(热度池前 20):表格
 *  - sector_filter:可交易板块分布
 *  - switch_warning:龙头切换预警
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';
import StockActionButtons from '../components/trading/StockActionButtons';

// 游资阶段配色（覆盖所有阶段名变体）
const STAGE_COLORS = {
  '主升': '#dc2626', '加速': '#fb923c', '突破': '#facc15',
  '分歧': '#f97316', '蓄势': '#3b82f6', '留意': '#a78bfa', '观望': '#64748b',
  '启动': '#f59e0b', '发酵': '#ef4444',
  '关注': '#a78bfa', '吸筹': '#3b82f6', '跟随': '#64748b',
  '衰退': '#94a3b8', '退潮': '#94a3b8',
};
const stageColor = (s) => STAGE_COLORS[s] || '#06b6d4';

// 板块状态配色
const SECTOR_STATE_COLORS = {
  'STRONG_TREND': { bg: 'rgba(239,68,68,0.1)', color: '#ef4444', label: '强势' },
  'ROTATION': { bg: 'rgba(234,179,8,0.1)', color: '#eab308', label: '轮动' },
  'DOWN': { bg: 'rgba(34,197,94,0.1)', color: '#22c55e', label: '走弱' },
};

export default function TradingSystemPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [selectedDate, setSelectedDate] = useState('');
  const reqIdRef = useRef(0);
  const navigate = useNavigate();

  const loadAll = useCallback(async (silent = false, date = '') => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    setError(null);
    const myId = ++reqIdRef.current;
    try {
      const dateParam = date ? `?target_date=${date}` : '';
      const res = await apiFetch(`/api/leader/system${dateParam}`);
      if (myId !== reqIdRef.current) return;
      if (res.ok) {
        setData(res.data);
      } else {
        setError(`加载失败: ${res.status}`);
      }
    } catch (e) {
      if (myId !== reqIdRef.current) return;
      setError('加载失败: ' + e.message);
    } finally {
      if (myId === reqIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  const handleDateChange = (e) => {
    const d = e.target.value;
    setSelectedDate(d);
    loadAll(false, d);
  };

  const leader = data?.leader;
  const candidates = data?.candidates || [];
  const allStocks = data?.all_stocks || [];
  const sectorFilter = data?.sector_filter || {};
  const switchWarning = data?.switch_warning;

  return (
    <div className="space-y-3 px-1">
      {/* 顶部标题栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <div>
          <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            ⚡ 游资详情
            <span className="ml-2 text-[11px] font-normal" style={{ color: 'var(--text-muted)' }}>
              {data?.date ? `${data.date} · 主龙+候选+热度池` : '主龙 + 候选 + 热度池'}
            </span>
          </h2>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={selectedDate}
            onChange={handleDateChange}
            className="px-2 py-1 rounded-md text-[11px] border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
          />
          <button
            onClick={() => loadAll(true, selectedDate)}
            disabled={refreshing}
            className="px-2 py-1 rounded-md text-[11px] border transition-colors disabled:opacity-50"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            {refreshing ? '⏳' : '🔄'} 刷新
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-md p-2 text-xs"
          style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
          {error}
        </div>
      )}

      {/* 龙头切换警告 */}
      {switchWarning && (
        <div className="rounded-md p-2 text-xs flex items-start gap-2"
          style={{ background: 'rgba(250,204,21,0.1)', color: '#a16207', border: '1px solid rgba(250,204,21,0.3)' }}>
          <span className="text-base">⚠</span>
          <div>
            <span className="font-bold">龙头切换预警：</span>
            {switchWarning.new_candidate} 评分接近主龙
            <span className="ml-2 text-[10px]">{switchWarning.reason}</span>
          </div>
        </div>
      )}

      {/* 主龙头加冕卡 */}
      <section>
        <div className="text-[11px] font-bold mb-1" style={{ color: 'var(--text-muted)' }}>👑 主龙头</div>
        {loading && !leader ? (
          <div className="rounded-lg border p-6 text-center text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
            ⏳ 加载中…
          </div>
        ) : !leader ? (
          <div className="rounded-lg border p-6 text-center text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
            暂无主龙头（{data?.message || '无可用数据'}）
          </div>
        ) : (
          <LeaderHeroCard leader={leader} onClick={(code) => navigate(`/stock/${code}`)} onRefresh={() => loadAll(true, selectedDate)} />
        )}
      </section>

      {/* 候选龙头 */}
      {candidates.length > 0 && (
        <section>
          <div className="text-[11px] font-bold mb-1" style={{ color: 'var(--text-muted)' }}>🔥 候选龙头（{candidates.length}）</div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {candidates.map((c, i) => (
              <CandidateCard key={c.secCode || i} stock={c} rank={i + 2}
                onClick={(code) => navigate(`/stock/${code}`)} onRefresh={() => loadAll(true, selectedDate)} />
            ))}
          </div>
        </section>
      )}

      {/* 板块状态：可交易板块（强势/轮动） */}
      {(sectorFilter.strong?.length > 0 || sectorFilter.rotation?.length > 0) && (
        <section>
          <div className="text-[11px] font-bold mb-1" style={{ color: 'var(--text-muted)' }}>📊 可交易板块</div>
          <div className="grid grid-cols-2 gap-2">
            <SectorListCard title="🔥 强势板块" items={sectorFilter.strong || []} stateKey="STRONG_TREND" />
            <SectorListCard title="🔄 轮动板块" items={sectorFilter.rotation || []} stateKey="ROTATION" />
          </div>
        </section>
      )}

      {/* 热度池前 20 表格 */}
      <section>
        <div className="flex items-center justify-between mb-1">
          <div className="text-[11px] font-bold" style={{ color: 'var(--text-muted)' }}>
            📋 热度池（{allStocks.length} / 共 {data?.all_count || 0} 只）
          </div>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            点击行查看详情
          </div>
        </div>
        {allStocks.length === 0 ? (
          <div className="rounded-lg border p-6 text-center text-xs" style={{ borderColor: 'var(--border-color)', color: 'var(--text-muted)' }}>
            暂无热度池数据
          </div>
        ) : (
          <HeatPoolTable stocks={allStocks} leaderCode={leader?.secCode}
            onRowClick={(code) => navigate(`/stock/${code}`)}
            onRefresh={() => loadAll(true, selectedDate)} />
        )}
      </section>
    </div>
  );
}

/* ========================= 主龙头加冕卡 ========================= */
function LeaderHeroCard({ leader, onClick, onRefresh }) {
  const stage = leader.stage || leader.lifecycleStage || '主升';
  const color = stageColor(stage);
  const mf = leader.mainForce || {};
  const inflow1 = mf.inflow_1d || 0;
  const inflow3 = mf.inflow_3d || 0;
  const inflow5 = mf.inflow_5d || 0;
  const continuity = mf.flow_continuity || 0;
  const changePct = leader.position?.dayProfitPct ?? leader.change_rate ?? 0;
  const price = leader.position?.price || 0;
  const leaderScore = leader.leaderScore ?? leader.details?.change != null ? 0 : 0;
  // leaderScore 来自 leader_engine 0-10 分
  const rawLeaderScore = leader.leaderScore ?? null;
  const strength = leader.strength ?? null;
  const days = leader.consecutive_days ?? 0;

  return (
    <div
      onClick={() => onClick(leader.secCode)}
      className="rounded-lg border-2 p-4 cursor-pointer hover:opacity-90 transition-opacity"
      style={{ borderColor: color, background: 'var(--bg-card)' }}
    >
      <div className="flex items-start gap-3 flex-wrap">
        {/* 左侧：阶段 + 评分 */}
        <div className="flex-shrink-0 flex flex-col items-center justify-center w-20 h-20 rounded-lg"
          style={{ background: `${color}15`, border: `2px solid ${color}` }}>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>游资阶段</span>
          <span className="text-base font-bold mt-0.5" style={{ color }}>{stage}</span>
          {rawLeaderScore != null && (
            <span className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
              龙头评分 {rawLeaderScore}/10
            </span>
          )}
        </div>

        {/* 中间：股票名 + 关键信息 */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>{leader.secName}</span>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{leader.secCode}</span>
            <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: `${color}20`, color, fontWeight: 700 }}>
              👑 主龙头
            </span>
            {leader.sector && (
              <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
                板块：{leader.sector}
              </span>
            )}
          </div>
          <div className="flex items-baseline gap-3 mt-2 flex-wrap">
            <div>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>现价</span>
              <span className="ml-1 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{price.toFixed(2)}</span>
            </div>
            <div>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>当日</span>
              <span className="ml-1 text-sm font-bold" style={{ color: changePct >= 0 ? UP_COLOR : DOWN_COLOR }}>
                {changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%
              </span>
            </div>
            {strength != null && (
              <div>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>强度</span>
                <span className="ml-1 text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{Number(strength).toFixed(1)}</span>
              </div>
            )}
            {days > 0 && (
              <div>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>连板</span>
                <span className="ml-1 text-sm font-bold" style={{ color: UP_COLOR }}>{days}连板</span>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* 主力净流入（游资买入金额代理） */}
      <div className="mt-3 grid grid-cols-4 gap-2">
        <InflowBox label="1日主力净流入" value={inflow1} />
        <InflowBox label="3日累计" value={inflow3} />
        <InflowBox label="5日累计" value={inflow5} />
        <div className="rounded-md px-2 py-1.5 text-center" style={{ background: 'rgba(168,85,247,0.1)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>连续净流入</div>
          <div className="text-sm font-bold mt-0.5" style={{ color: '#a855f7' }}>
            {continuity > 0 ? `${continuity}天` : '—'}
          </div>
        </div>
      </div>

      {/* 操作按钮 */}
      <div className="mt-3 flex items-center justify-between flex-wrap gap-2">
        <StockActionButtons
          stockCode={leader.secCode}
          stockName={leader.secName}
          size="sm"
          onRefresh={onRefresh}
        />
      </div>
    </div>
  );
}

function InflowBox({ label, value }) {
  const positive = value >= 0;
  const color = positive ? UP_COLOR : DOWN_COLOR;
  return (
    <div className="rounded-md px-2 py-1.5 text-center"
      style={{ background: positive ? `${UP_COLOR}14` : `${DOWN_COLOR}14` }}>
      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className="text-sm font-bold mt-0.5" style={{ color }}>
        {positive ? '+' : ''}{(value / 10000).toFixed(1)}万
      </div>
    </div>
  );
}

/* ========================= 候选龙头卡片 ========================= */
function CandidateCard({ stock, rank, onClick, onRefresh }) {
  const stage = stock.stage || stock.lifecycleStage || '蓄势';
  const color = stageColor(stage);
  const mf = stock.mainForce || {};
  const inflow1 = mf.inflow_1d || 0;
  const changePct = stock.position?.dayProfitPct ?? stock.change_rate ?? 0;
  const price = stock.position?.price || 0;
  const strength = stock.strength ?? null;
  const days = stock.consecutive_days ?? 0;
  const leaderScore = stock.leaderScore ?? null;

  return (
    <div onClick={() => onClick(stock.secCode)}
      className="rounded-lg border p-3 cursor-pointer hover:opacity-90 transition-opacity"
      style={{ borderColor: `${color}80`, background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5 min-w-0">
          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold flex-shrink-0"
            style={{ background: `${color}20`, color }}>第{rank}候选</span>
          <span className="font-bold text-sm truncate" style={{ color: 'var(--text-primary)' }}>{stock.secName}</span>
          <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--text-muted)' }}>{stock.secCode}</span>
        </div>
        <span className="text-[10px] px-1.5 py-0.5 rounded flex-shrink-0" style={{ background: `${color}20`, color, fontWeight: 700 }}>
          {stage}
        </span>
      </div>
      <div className="flex items-center gap-3 mt-2 text-[11px] flex-wrap" style={{ color: 'var(--text-muted)' }}>
        <span>现价 <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{price.toFixed(2)}</span></span>
        <span>当日 <span style={{ color: changePct >= 0 ? UP_COLOR : DOWN_COLOR, fontWeight: 600 }}>{changePct >= 0 ? '+' : ''}{changePct.toFixed(2)}%</span></span>
        {strength != null && <span>强度 <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{Number(strength).toFixed(1)}</span></span>}
        {days > 0 && <span>连板 <span style={{ color: UP_COLOR, fontWeight: 600 }}>{days}</span></span>}
        {leaderScore != null && <span>评分 <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{leaderScore}/10</span></span>}
      </div>
      <div className="mt-2 grid grid-cols-3 gap-1 text-[10px]">
        <InflowBox label="1日" value={inflow1} />
        <InflowBox label="3日" value={mf.inflow_3d || 0} />
        <InflowBox label="5日" value={mf.inflow_5d || 0} />
      </div>
      <div className="mt-2">
        <StockActionButtons
          stockCode={stock.secCode}
          stockName={stock.secName}
          size="xs"
          onRefresh={onRefresh}
        />
      </div>
    </div>
  );
}

/* ========================= 板块列表卡 ========================= */
function SectorListCard({ title, items, stateKey }) {
  const style = SECTOR_STATE_COLORS[stateKey] || SECTOR_STATE_COLORS.ROTATION;
  return (
    <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between mb-1.5">
        <span className="text-[11px] font-bold" style={{ color: 'var(--text-primary)' }}>{title}</span>
        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: style.bg, color: style.color }}>
          {style.label} {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <div className="text-[10px] text-center py-2" style={{ color: 'var(--text-muted)' }}>暂无</div>
      ) : (
        <div className="flex flex-wrap gap-1">
          {items.slice(0, 8).map((s, i) => (
            <span key={i} className="text-[10px] px-1.5 py-0.5 rounded"
              style={{ background: style.bg, color: style.color }}>
              {s.sector} <span className="font-mono font-bold">{s.score?.toFixed?.(1) || s.score || '-'}</span>
            </span>
          ))}
          {items.length > 8 && (
            <span className="text-[10px] px-1.5 py-0.5" style={{ color: 'var(--text-muted)' }}>+{items.length - 8}</span>
          )}
        </div>
      )}
    </div>
  );
}

/* ========================= 热度池表格 ========================= */
function HeatPoolTable({ stocks, leaderCode, onRowClick, onRefresh }) {
  return (
    <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
              <th className="px-2 py-1.5 text-left text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>#</th>
              <th className="px-2 py-1.5 text-left text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>股票</th>
              <th className="px-2 py-1.5 text-left text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>板块</th>
              <th className="px-2 py-1.5 text-left text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>阶段</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>现价</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>当日</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>强度</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>连板</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>评分</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>1日主力</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>3日主力</th>
              <th className="px-2 py-1.5 text-right text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>5日主力</th>
              <th className="px-2 py-1.5 text-left text-[10px] font-bold" style={{ color: 'var(--text-muted)' }}>操作</th>
            </tr>
          </thead>
          <tbody>
            {stocks.map((s, i) => {
              const stage = s.stage || s.lifecycleStage || '观望';
              const c = stageColor(stage);
              const change = s.position?.dayProfitPct ?? s.change_rate ?? 0;
              const price = s.position?.price || 0;
              const strength = s.strength ?? null;
              const days = s.consecutive_days ?? 0;
              const ls = s.leaderScore ?? null;
              const mf = s.mainForce || {};
              const isLeader = s.secCode === leaderCode;
              return (
                <tr key={s.secCode || i}
                  onClick={() => onRowClick(s.secCode)}
                  className="border-b cursor-pointer hover:opacity-80 transition-opacity"
                  style={{ borderColor: 'var(--border-color)', background: isLeader ? `${c}10` : 'transparent' }}>
                  <td className="px-2 py-1.5 font-mono" style={{ color: 'var(--text-muted)' }}>{i + 1}</td>
                  <td className="px-2 py-1.5">
                    <div className="flex items-center gap-1.5">
                      {isLeader && <span style={{ color: c }}>👑</span>}
                      <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{s.secName}</span>
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.secCode}</span>
                    </div>
                  </td>
                  <td className="px-2 py-1.5" style={{ color: 'var(--text-secondary)' }}>{s.sector || '-'}</td>
                  <td className="px-2 py-1.5">
                    <span className="text-[10px] px-1.5 py-0.5 rounded font-bold inline-block"
                      style={{ background: `${c}20`, color: c }}>
                      {stage}
                    </span>
                  </td>
                  <td className="px-2 py-1.5 text-right font-bold" style={{ color: 'var(--text-primary)' }}>
                    {price.toFixed(2)}
                  </td>
                  <td className="px-2 py-1.5 text-right font-bold"
                    style={{ color: change >= 0 ? UP_COLOR : DOWN_COLOR }}>
                    {change >= 0 ? '+' : ''}{change.toFixed(2)}%
                  </td>
                  <td className="px-2 py-1.5 text-right" style={{ color: 'var(--text-primary)' }}>
                    {strength != null ? Number(strength).toFixed(1) : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-bold" style={{ color: days > 0 ? UP_COLOR : 'var(--text-muted)' }}>
                    {days > 0 ? `${days}连板` : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-bold" style={{ color: 'var(--text-primary)' }}>
                    {ls != null ? `${ls}/10` : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono"
                    style={{ color: (mf.inflow_1d || 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>
                    {mf.inflow_1d != null ? `${(mf.inflow_1d / 10000).toFixed(1)}万` : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono"
                    style={{ color: (mf.inflow_3d || 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>
                    {mf.inflow_3d != null ? `${(mf.inflow_3d / 10000).toFixed(1)}万` : '-'}
                  </td>
                  <td className="px-2 py-1.5 text-right font-mono"
                    style={{ color: (mf.inflow_5d || 0) >= 0 ? UP_COLOR : DOWN_COLOR }}>
                    {mf.inflow_5d != null ? `${(mf.inflow_5d / 10000).toFixed(1)}万` : '-'}
                  </td>
                  <td className="px-2 py-1.5" onClick={(e) => e.stopPropagation()}>
                    <StockActionButtons
                      stockCode={s.secCode}
                      stockName={s.secName}
                      size="xs"
                      onRefresh={onRefresh}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
