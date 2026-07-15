import { useState, useMemo } from 'react';
import { useLifecycleData } from '../hooks/useLifecycleData';
import SignalCard from '../components/trading/SignalCard';
import DateNavigator from '../components/DateNavigator';
import { STAGE_COLORS } from '../constants/stages';
import { leaderToSignal } from '../utils/format';

export default function LifecyclePage() {
  const {
    data, loading, error, retry,
    selectedDate, setSelectedDate, changeDate,
    stageFilter, setStageFilter,
    sectorFilter, setSectorFilter,
    sectorList,
    searchText, setSearchText,
    sortBy, setSortBy,
    stageCounts,
    filteredLeaders, pagedLeaders,
    currentPage, setCurrentPage, totalPages,
  } = useLifecycleData('/api/lifecycle');

  const [showHelp, setShowHelp] = useState(false);

  // 市场概览统计
  const marketOverview = useMemo(() => {
    if (!data?.leaders) return null;
    const leaders = data.leaders;
    const total = leaders.length;
    const upCount = leaders.filter(l => l.change_rate > 0).length;
    const downCount = leaders.filter(l => l.change_rate < 0).length;
    const flatCount = total - upCount - downCount;
    const avgChange = total > 0 ? leaders.reduce((s, l) => s + (l.change_rate || 0), 0) / total : 0;
    const maxDays = Math.max(0, ...leaders.map(l => l.consecutive_days || 0));
    const avgStrength = total > 0 ? leaders.reduce((s, l) => s + (l.strength || 0), 0) / total : 0;
    const topStage = stageCounts.length > 0 ? stageCounts.reduce((a, b) => a.count >= b.count ? a : b) : null;
    return { total, upCount, downCount, flatCount, avgChange, maxDays, avgStrength, topStage };
  }, [data, stageCounts]);

  // 连板梯队统计
  const limitUpTiers = useMemo(() => {
    if (!data?.leaders) return [];
    const tiers = { 1: 0, 2: 0, 3: 0, 4: 0 };
    data.leaders.forEach(l => {
      const d = l.consecutive_days || 0;
      if (d >= 4) tiers[4]++;
      else if (d >= 1) tiers[d]++;
    });
    return [
      { label: '4板+', count: tiers[4], color: '#ef4444', desc: '高位主升' },
      { label: '3板', count: tiers[3], color: '#f97316', desc: '发酵加速' },
      { label: '2板', count: tiers[2], color: '#eab308', desc: '共识形成' },
      { label: '1板', count: tiers[1], color: '#3b82f6', desc: '启动初期' },
    ].filter(t => t.count > 0);
  }, [data]);

  // 板块热度Top（按龙头数量）
  const sectorTopList = useMemo(() => {
    if (!data?.leaders) return [];
    const map = {};
    data.leaders.forEach(l => {
      if (!l.sector) return;
      if (!map[l.sector]) map[l.sector] = { sector: l.sector, count: 0, totalChange: 0, totalStrength: 0, stages: {} };
      map[l.sector].count++;
      map[l.sector].totalChange += l.change_rate || 0;
      map[l.sector].totalStrength += l.strength || 0;
      map[l.sector].stages[l.stage] = (map[l.sector].stages[l.stage] || 0) + 1;
    });
    return Object.values(map)
      .map(s => ({
        ...s,
        avgChange: s.count > 0 ? s.totalChange / s.count : 0,
        avgStrength: s.count > 0 ? s.totalStrength / s.count : 0,
      }))
      .sort((a, b) => b.count - a.count)
      .slice(0, 8);
  }, [data]);

  // 强度榜Top10
  const strengthTop10 = useMemo(() => {
    if (!data?.leaders) return [];
    return [...data.leaders]
      .sort((a, b) => (b.strength || 0) - (a.strength || 0))
      .slice(0, 10);
  }, [data]);

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center h-96 gap-3">
        <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
        <button onClick={retry} className="px-3 py-1.5 rounded-lg border text-sm" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>重试</button>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {/* 日期导航（标题由外壳 Tab 显示，避免重复） */}
      <div className="flex items-center justify-end">
        <div className="flex items-center gap-2 text-xs">
          <span className="px-1.5 py-0.5 rounded font-normal" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
          <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
        </div>
      </div>

      {/* 说明卡片（可折叠） */}
      <div>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-3 py-2.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 龙头趋势阶段</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-3 pb-3 space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>选股逻辑：</strong>基于全部个股的主力资金流向和涨停股连板高度，识别市场龙头股，追踪其从资金留意到衰退的完整趋势阶段</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>阶段说明：</strong></div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>观望</strong>：主力资金未明显介入，个股随市场波动</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>留意</strong>：主力资金开始流入（≥1000万），值得跟踪观察</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>蓄势</strong>：主力资金大幅流入（≥1亿），潜在突破信号</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>突破</strong>：首板涨停，资金开始关注，处于行情初期</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>加速</strong>：2-3连板，市场共识形成，资金加速流入，是最优参与阶段</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>主升</strong>：4连板以上，涨幅扩大但高位风险增加，需谨慎参与</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>分歧</strong>：连板中断或大幅震荡，多空分歧加大，方向选择关键期</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>衰退</strong>：资金流出，涨幅收窄甚至下跌，行情进入尾声</div>
          </div>
        )}
      </div>

      {/* 市场概览（4卡片，参考模拟盘账户概览） */}
      {marketOverview && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>龙头总数</div>
            <div className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>{marketOverview.total}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
              主导阶段：<span style={{ color: marketOverview.topStage?.color }}>{marketOverview.topStage?.stage || '--'}</span>
            </div>
          </div>
          <div>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>涨跌情况</div>
            <div className="text-xl font-bold flex items-center gap-2">
              <span style={{ color: '#ef4444' }}>{marketOverview.upCount}</span>
              <span className="text-sm font-normal" style={{ color: 'var(--text-muted)' }}>/</span>
              <span style={{ color: '#22c55e' }}>{marketOverview.downCount}</span>
            </div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>涨 / 跌 · 平 {marketOverview.flatCount}</div>
          </div>
          <div>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>平均涨幅</div>
            <div className="text-xl font-bold" style={{ color: marketOverview.avgChange >= 0 ? '#ef4444' : '#22c55e' }}>
              {marketOverview.avgChange >= 0 ? '+' : ''}{marketOverview.avgChange.toFixed(2)}%
            </div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>平均强度: {marketOverview.avgStrength.toFixed(0)}</div>
          </div>
          <div>
            <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>最高连板</div>
            <div className="text-xl font-bold" style={{ color: '#ef4444' }}>{marketOverview.maxDays}<span className="text-sm font-normal ml-1" style={{ color: 'var(--text-muted)' }}>板</span></div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>连板高度</div>
          </div>
        </div>
      )}

      {/* 阶段分布（8卡片，带占比进度条） */}
      {stageCounts.length > 0 && marketOverview && (
        <div className="grid grid-cols-4 md:grid-cols-8 gap-3">
          {stageCounts.map(s => {
            const pct = marketOverview.total > 0 ? (s.count / marketOverview.total * 100) : 0;
            const isActive = stageFilter === s.stage;
            return (
              <button
                key={s.stage}
                onClick={() => setStageFilter(isActive ? '全部' : s.stage)}
                className="rounded-lg border p-3 text-center transition-all"
                style={{
                  borderColor: isActive ? s.color : 'var(--border-color)',
                  background: isActive ? s.color + '20' : 'var(--bg-card)',
                }}
              >
                <div className="text-2xl font-bold" style={{ color: s.color }}>{s.count}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{s.stage}</div>
                <div className="mt-1.5 h-1 rounded-full overflow-hidden" style={{ background: 'var(--bg-hover)' }}>
                  <div className="h-full rounded-full" style={{ width: `${pct}%`, background: s.color }} />
                </div>
                <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{pct.toFixed(0)}%</div>
              </button>
            );
          })}
        </div>
      )}

      {/* 连板梯队 + 板块热度Top（并排两列） */}
      {data?.leaders?.length > 0 && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          {/* 连板梯队 */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🔥 连板梯队</h3>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>按连板高度分组</span>
            </div>
            <div className="grid grid-cols-4 gap-2">
              {limitUpTiers.length > 0 ? limitUpTiers.map(t => (
                <div key={t.label} className="rounded-lg p-2 text-center" style={{ background: t.color + '10', border: `1px solid ${t.color}30` }}>
                  <div className="text-lg font-bold" style={{ color: t.color }}>{t.count}</div>
                  <div className="text-xs font-medium" style={{ color: 'var(--text-secondary)' }}>{t.label}</div>
                  <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>{t.desc}</div>
                </div>
              )) : (
                <div className="col-span-4 text-center text-xs py-2" style={{ color: 'var(--text-muted)' }}>暂无连板数据</div>
              )}
            </div>
          </div>

          {/* 板块热度Top */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 板块热度Top{sectorTopList.length}</h3>
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>按龙头数量排序</span>
            </div>
            <div className="space-y-1.5 max-h-[140px] overflow-y-auto">
              {sectorTopList.length > 0 ? sectorTopList.map((s, i) => (
                <div key={s.sector} className="flex items-center gap-2 text-xs">
                  <span className="w-5 text-center font-bold" style={{ color: i < 3 ? '#ef4444' : 'var(--text-muted)' }}>{i + 1}</span>
                  <span className="flex-1 truncate font-medium" style={{ color: 'var(--text-primary)' }}>{s.sector}</span>
                  <span style={{ color: 'var(--text-secondary)' }}>{s.count}只</span>
                  <span style={{ color: s.avgChange >= 0 ? '#ef4444' : '#22c55e', minWidth: '52px', textAlign: 'right' }}>
                    {s.avgChange >= 0 ? '+' : ''}{s.avgChange.toFixed(2)}%
                  </span>
                  <div className="w-16 h-1.5 rounded-full overflow-hidden" style={{ background: 'var(--bg-hover)' }}>
                    <div className="h-full rounded-full" style={{ width: `${Math.min(100, s.avgStrength)}%`, background: '#3b82f6' }} />
                  </div>
                </div>
              )) : (
                <div className="text-center text-xs py-2" style={{ color: 'var(--text-muted)' }}>暂无板块数据</div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* 强度榜Top10（紧凑表格） */}
      {strengthTop10.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>💪 强度榜Top10</h3>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>点击阶段卡片可筛选</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {strengthTop10.map((l, i) => {
              const stageColor = STAGE_COLORS[l.stage] || '#6b7280';
              return (
                <div key={l.ts_code} className="rounded-lg p-2 border" style={{ borderColor: `${stageColor}30`, background: `${stageColor}08` }}>
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-bold" style={{ color: i < 3 ? '#ef4444' : 'var(--text-muted)' }}>#{i + 1}</span>
                    <span className="text-[10px] px-1 rounded" style={{ background: stageColor + '20', color: stageColor }}>{l.stage}</span>
                  </div>
                  <div className="text-sm font-medium mt-0.5 truncate" style={{ color: 'var(--text-primary)' }} title={l.name}>{l.name || l.ts_code}</div>
                  <div className="flex items-center justify-between mt-1 text-[11px]">
                    <span style={{ color: 'var(--text-muted)' }}>{l.consecutive_days}板</span>
                    <span style={{ color: l.change_rate >= 0 ? '#ef4444' : '#22c55e' }}>
                      {l.change_rate >= 0 ? '+' : ''}{l.change_rate?.toFixed(2)}%
                    </span>
                    <span className="font-bold" style={{ color: stageColor }}>{l.strength?.toFixed(0)}</span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* 筛选工具栏 */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="搜索代码 / 名称 / 板块"
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="px-3 py-1.5 rounded-lg border text-sm flex-1 min-w-[180px]"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
        />
        <select
          value={sectorFilter}
          onChange={(e) => setSectorFilter(e.target.value)}
          className="px-3 py-1.5 rounded-lg border text-sm"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
        >
          <option value="全部">全部板块</option>
          {sectorList.map(([sector, count]) => (
            <option key={sector} value={sector}>{sector}（{count}）</option>
          ))}
        </select>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value)}
          className="px-3 py-1.5 rounded-lg border text-sm"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
        >
          <option value="strength">按强度排序</option>
          <option value="days">按连板数排序</option>
          <option value="change">按涨幅排序</option>
        </select>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          共 {filteredLeaders.length} 只{stageFilter !== '全部' ? ` · ${stageFilter}` : ''}{sectorFilter !== '全部' ? ` · ${sectorFilter}` : ''}
        </span>
        {(stageFilter !== '全部' || sectorFilter !== '全部' || searchText) && (
          <button
            onClick={() => { setStageFilter('全部'); setSectorFilter('全部'); setSearchText(''); }}
            className="px-2 py-1 rounded-lg text-xs border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            清除筛选
          </button>
        )}
      </div>

      {/* 趋势阶段列表 */}
      <div>
        {loading ? (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : pagedLeaders.length > 0 ? (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {pagedLeaders.map((leader) => (
                <SignalCard key={leader.ts_code} signal={leaderToSignal(leader)} mode="watchlist" showWatchBtn showMarketState showBuyPower showAnalysisButton />
              ))}
            </div>
            {totalPages > 1 && (
              <div className="flex items-center justify-center gap-2 mt-4 pt-3 border-t" style={{ borderColor: 'var(--border-color)' }}>
                <button
                  onClick={() => setCurrentPage(p => Math.max(0, p - 1))}
                  disabled={currentPage === 0}
                  className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                  style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                >
                  上一页
                </button>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {currentPage + 1} / {totalPages} 页
                </span>
                <button
                  onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))}
                  disabled={currentPage >= totalPages - 1}
                  className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                  style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
                >
                  下一页
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
            {data?.leaders?.length > 0 ? '无匹配结果，请调整筛选条件' : '暂无龙头数据'}
          </div>
        )}
      </div>
    </div>
  );
}
