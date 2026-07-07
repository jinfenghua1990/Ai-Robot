import { useState } from 'react';
import { useLifecycleData } from '../hooks/useLifecycleData';
import DateNavigator from '../components/DateNavigator';
import SignalCard from '../components/trading/SignalCard';
import { leaderToSignal } from '../utils/format';

export default function LifecycleV3Page() {
  const {
    data, loading, error, retry,
    selectedDate, setSelectedDate, changeDate,
    stageFilter, setStageFilter,
    sectorFilter, setSectorFilter,
    searchText, setSearchText,
    sortBy, setSortBy,
    stageCounts,
    filteredLeaders, pagedLeaders,
    currentPage, setCurrentPage, totalPages,
  } = useLifecycleData('/api/lifecycle-v3', { sortByDefault: 'strength' });

  const [showHelp, setShowHelp] = useState(false);

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
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-3 py-2.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 龙头趋势阶段V3</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-3 pb-3 space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>V3版本：</strong>在趋势阶段基础上新增「二波行情」识别，捕捉衰退后重新走强的龙头股</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>二波行情：</strong>龙头股经历衰退阶段后，再次突破一轮上涨行情。通常由分歧转一致、资金回流触发</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>阶段说明：</strong>
              <span style={{ color: '#3b82f6' }}>突破</span> →
              <span style={{ color: '#eab308' }}>加速</span> →
              <span style={{ color: '#ef4444' }}>主升</span> →
              <span style={{ color: '#f97316' }}>分歧</span> →
              <span style={{ color: '#64748b' }}>衰退</span>
            </div>
            <div><strong style={{ color: '#3b82f6' }}>突破：</strong>板块龙头首板涨停，资金开始聚焦</div>
            <div><strong style={{ color: '#eab308' }}>加速：</strong>连续涨停带动板块，跟风盘涌入</div>
            <div><strong style={{ color: '#ef4444' }}>主升：</strong>加速放量上涨，情绪达到高潮</div>
            <div><strong style={{ color: '#f97316' }}>分歧：</strong>多空出现分歧，放量震荡换手</div>
            <div><strong style={{ color: '#64748b' }}>衰退：</strong>龙头断板回落，资金开始撤出</div>
          </div>
        )}
      </div>

      {/* 统计概览 */}
      {data && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-2xl font-bold" style={{ color: 'var(--accent-blue)' }}>{data.total_leaders}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>龙头总数</div>
          </div>
          <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-2xl font-bold" style={{ color: '#22c55e' }}>{data.total_sectors}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>关联板块</div>
          </div>
          <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-2xl font-bold" style={{ color: '#eab308' }}>{data.second_wave?.length || 0}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>二波股票</div>
          </div>
          <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>{filteredLeaders.length}</div>
            <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>筛选结果</div>
          </div>
        </div>
      )}

      {/* 二波股票区域 */}
      {data?.second_wave?.length > 0 && (
        <div className="rounded-xl border p-3" style={{ borderColor: '#eab308', background: 'rgba(234,179,8,0.1)' }}>
          <div className="flex items-center gap-2 mb-3">
            <span className="text-lg">🔄</span>
            <span className="font-bold" style={{ color: '#eab308' }}>二波行情</span>
            <span className="text-xs px-2 py-0.5 rounded-full" style={{ background: '#eab308', color: '#fff' }}>{data.second_wave.length}只</span>
            <span className="text-xs" style={{ color: '#eab308' }}>· 衰退后重新走强的股票</span>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
            {data.second_wave.map((leader) => (
              <SignalCard
                key={leader.ts_code}
                signal={leaderToSignal(leader)}
                mode="watchlist"
                showWatchBtn
                showMarketState
                showBuyPower
                showAnalysisButton
              />
            ))}
          </div>
        </div>
      )}

      {/* 阶段统计卡片 */}
      {stageCounts.length > 0 && (
        <div className="grid grid-cols-4 md:grid-cols-8 gap-3">
          {stageCounts.map(s => (
            <button
              key={s.stage}
              onClick={() => setStageFilter(stageFilter === s.stage ? '全部' : s.stage)}
              className="rounded-lg border p-3 text-center transition-all"
              style={{
                borderColor: stageFilter === s.stage ? s.color : 'var(--border-color)',
                background: stageFilter === s.stage ? s.color + '20' : 'var(--bg-card)',
              }}
            >
              <div className="text-2xl font-bold" style={{ color: s.color }}>{s.count}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{s.stage}</div>
            </button>
          ))}
        </div>
      )}

      {/* 顶部板块导航 */}
      {data?.sector_list?.length > 0 && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => setSectorFilter('全部')}
            className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${sectorFilter === '全部' ? '' : ''}`}
            style={{
              background: sectorFilter === '全部' ? 'var(--accent-blue)' : 'var(--bg-card)',
              color: sectorFilter === '全部' ? '#fff' : 'var(--text-secondary)',
              borderColor: 'var(--border-color)',
              border: '1px solid',
            }}
          >
            全部板块
          </button>
          {data.sector_list.map(s => (
            <button
              key={s.name}
              onClick={() => setSectorFilter(s.name)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-all ${sectorFilter === s.name ? '' : ''}`}
              style={{
                background: sectorFilter === s.name ? 'var(--accent-blue)' : 'var(--bg-card)',
                color: sectorFilter === s.name ? '#fff' : 'var(--text-secondary)',
                borderColor: 'var(--border-color)',
                border: '1px solid',
              }}
            >
              {s.name} <span className="text-xs opacity-70">({s.count})</span>
            </button>
          ))}
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

      {/* 龙头列表（卡片式进度条） */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
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