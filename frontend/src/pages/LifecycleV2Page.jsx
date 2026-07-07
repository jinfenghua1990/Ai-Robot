import { useState } from 'react';
import { useLifecycleData } from '../hooks/useLifecycleData';
import DateNavigator from '../components/DateNavigator';
import SignalCard from '../components/trading/SignalCard';
import { leaderToSignal } from '../utils/format';

export default function LifecycleV2Page() {
  const {
    data, loading, error, retry,
    selectedDate, setSelectedDate, changeDate,
    stageFilter, setStageFilter,
    sectorFilter, setSectorFilter,
    sectorList,
    searchText, setSearchText,
    stageCounts,
    filteredLeaders, pagedLeaders,
    currentPage, setCurrentPage, totalPages,
  } = useLifecycleData('/api/lifecycle-v2');

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
      {/* 描述 + 日期导航 */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p className="text-xs flex-1 min-w-0" style={{ color: 'var(--text-muted)' }}>多维度强度评分（连板30 + 涨幅10 + 资金40 + 阶段20 = 100分）</p>
        <div className="flex items-center gap-2 text-xs flex-shrink-0">
          <span className="px-1.5 py-0.5 rounded font-normal whitespace-nowrap" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            {selectedDate ? `${selectedDate.slice(5).replace('-', '月')}日 盘后数据` : '盘后数据'}
          </span>
          <DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
        </div>
      </div>

      {/* 说明卡片（可折叠） */}
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <button onClick={() => setShowHelp(!showHelp)} className="w-full flex items-center justify-between px-3 py-2.5 text-sm" style={{ color: 'var(--text-secondary)' }}>
          <span><strong style={{ color: 'var(--text-primary)' }}>📖 名词解释</strong> · 强度评分逻辑</span>
          <span style={{ color: 'var(--text-muted)' }}>{showHelp ? '收起 ▲' : '展开 ▼'}</span>
        </button>
        {showHelp && (
          <div className="px-3 pb-3 space-y-1.5 text-xs" style={{ color: 'var(--text-secondary)' }}>
            <div><strong style={{ color: 'var(--text-primary)' }}>评分逻辑：</strong>采用多维度强度评分系统（总分100分）</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>连板高度（30分）</strong>：2-3板最优，4板+递减（高位风险）</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>涨幅表现（20分）</strong>：当日涨幅越大得分越高</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>资金流入（30分）</strong>：主力净流入金额越大得分越高</div>
            <div>· <strong style={{ color: 'var(--text-primary)' }}>阶段加成（20分）</strong>：发酵阶段加成最高（20分），主升阶段次之（10分）</div>
            <div><strong style={{ color: 'var(--text-primary)' }}>与V1区别：</strong>V2采用非单调连板评分，避免盲目追高；增加资金维度，量化主力参与度</div>
          </div>
        )}
      </div>

      {/* 阶段统计卡片 */}
      {stageCounts.length > 0 && (
        <div className="grid grid-cols-4 md:grid-cols-8 gap-3">
          {stageCounts.map(s => (
            <button key={s.stage}
              onClick={() => setStageFilter(stageFilter === s.stage ? '全部' : s.stage)}
              className="rounded-lg border p-3 text-center transition-all"
              style={{
                borderColor: stageFilter === s.stage ? s.color : 'var(--border-color)',
                background: stageFilter === s.stage ? s.color + '20' : 'var(--bg-card)',
              }}>
              <div className="text-2xl font-bold" style={{ color: s.color }}>{s.count}</div>
              <div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{s.stage}</div>
            </button>
          ))}
        </div>
      )}

      {/* 筛选工具栏 */}
      <div className="flex flex-wrap items-center gap-3">
        <input type="text" placeholder="搜索代码 / 名称 / 板块" value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="px-3 py-1.5 rounded-lg border text-sm flex-1 min-w-[180px]"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
        <select value={sectorFilter} onChange={(e) => setSectorFilter(e.target.value)}
          className="px-3 py-1.5 rounded-lg border text-sm"
          style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
          <option value="全部">全部板块</option>
          {sectorList.map(([sector, count]) => (
            <option key={sector} value={sector}>{sector}（{count}）</option>
          ))}
        </select>
        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
          共 {filteredLeaders.length} 只{stageFilter !== '全部' ? ` · ${stageFilter}` : ''}{sectorFilter !== '全部' ? ` · ${sectorFilter}` : ''}
        </span>
        {(stageFilter !== '全部' || sectorFilter !== '全部' || searchText) && (
          <button onClick={() => { setStageFilter('全部'); setSectorFilter('全部'); setSearchText(''); }}
            className="px-2 py-1 rounded-lg text-xs border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            清除筛选
          </button>
        )}
      </div>

      {/* 强度排行列表 */}
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
                <button onClick={() => setCurrentPage(p => Math.max(0, p - 1))} disabled={currentPage === 0}
                  className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                  style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>上一页</button>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{currentPage + 1} / {totalPages} 页</span>
                <button onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))} disabled={currentPage >= totalPages - 1}
                  className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
                  style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>下一页</button>
              </div>
            )}
          </>
        ) : (
          <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>
            {data?.leaders?.length > 0 ? '无匹配结果，请调整筛选条件' : '暂无龙头数据'}
          </div>
        )}
      </div>

      {/* 公式说明 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>强度计算公式（回测优化版 V2.1）</h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
            <div className="font-medium" style={{ color: '#3b82f6' }}>连板分（30分）</div>
            <div style={{ color: 'var(--text-muted)' }}>非单调：2-3板满分，4板+递减</div>
          </div>
          <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
            <div className="font-medium" style={{ color: '#22c55e' }}>涨幅分（10分）</div>
            <div style={{ color: 'var(--text-muted)' }}>|涨幅| × 1，涨停无区分度故降权</div>
          </div>
          <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
            <div className="font-medium" style={{ color: '#f97316' }}>资金分（40分）</div>
            <div style={{ color: 'var(--text-muted)' }}>sqrt(流入/50万) × 40，平方根曲线</div>
          </div>
          <div className="rounded-lg p-2" style={{ background: 'var(--bg-surface)' }}>
            <div className="font-medium" style={{ color: 'var(--text-secondary)' }}>阶段加成（20分）</div>
            <div style={{ color: 'var(--text-muted)' }}>发酵20 / 启动15 / 主升10 / 分歧5 / 退潮0</div>
          </div>
        </div>
      </div>
    </div>
  );
}
