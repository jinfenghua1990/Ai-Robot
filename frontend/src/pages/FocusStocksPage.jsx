import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import SignalCard from '../components/trading/SignalCard';

// 赛道图标映射（匹配截图风格）
const SECTOR_ICONS = {
  'MLCC': '', 'CPO': '', 'PCB': '🟩', '存储芯片': '💾',
  '先进封装': '🔧', '光纤光缆': '🔆', 'AI PC': '🖥️', 'AI芯片': '🧠',
  'AI服务器': '🖧', 'OCS': '🔷', '培育钻石': '', '玻璃基板': '🔲',
  '陶瓷基板': '🏺', '高速链接': '⚡', '铜箔': '🟫', '树脂': '🍃',
  '电子布': '🧵', '液冷': '❄️', '六氟化钨': '⚗️', '碳酸铁锂': '🔋',
};

export default function FocusStocksPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState(null);
  const [strategyPicks, setStrategyPicks] = useState({});

  const showToast = (msg, type = 'success') => {
    setToast({ msg, type });
    setTimeout(() => setToast(null), 2000);
  };

  const loadData = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    else setRefreshing(true);
    try {
      const [res, picksRes] = await Promise.all([
        apiFetch('/api/focus-stocks'),
        apiFetch('/api/bs-screener/strategy-picks'),
      ]);
      if (res.ok) setData(res.data);
      if (picksRes.ok && picksRes.data?.code_to_strategies) {
        setStrategyPicks(picksRes.data.code_to_strategies);
      }
    } catch (e) {
      showToast('数据加载失败', 'error');
    }
    setLoading(false);
    setRefreshing(false);
  }, []);

  useEffect(() => { loadData(); }, [loadData]);

  const batchAdd = useCallback(async (sectorName) => {
    try {
      const res = await apiFetch('/api/focus-stocks/batch-add', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sector: sectorName, group: '重点关注' }),
      });
      if (!res.ok) { showToast(res.data?.detail || '失败', 'error'); return; }
      const json = res.data;
      if (json?.success) showToast(`${sectorName}: +${json.added} 跳过${json.skipped}`);
      else showToast(json?.detail || '失败', 'error');
    } catch { showToast('批量添加失败', 'error'); }
  }, []);

  // 赛道展开/收起（默认全展开）
  const [collapsedSectors, setCollapsedSectors] = useState(new Set());
  const toggleSector = (name) => {
    setCollapsedSectors(prev => {
      const n = new Set(prev);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      return n;
    });
  };

  // 按平均涨跌幅排序
  const sortedSectors = useMemo(() => {
    if (!data) return [];
    return [...data.sectors].map(s => {
      const avgChg = s.stocks.reduce((sum, st) => sum + (st.quote?.changePct ?? 0), 0) / Math.max(s.stocks.length, 1);
      const upCount = s.stocks.filter(st => st.quote?.changePct > 0).length;
      return { ...s, avgChg, upCount };
    }).sort((a, b) => b.avgChg - a.avgChg);
  }, [data]);

  const summary = data?.summary;
  const fmtChg = (v) => {
    if (v == null) return '';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
  };

  return (
    <div className="space-y-2">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 px-3 py-1.5 rounded-lg text-xs shadow-lg"
          style={{ background: toast.type === 'error' ? 'rgba(239,68,68,0.92)' : toast.type === 'info' ? 'rgba(59,130,246,0.92)' : 'rgba(34,197,94,0.92)', color: '#fff' }}>
          {toast.msg}
        </div>
      )}

      {/* 标题栏 */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
          重点关注
          {summary && (
            <span className="ml-2 text-[11px] font-normal" style={{ color: 'var(--text-muted)' }}>
              {summary.total_sectors}赛道 · {summary.total_stocks}股 · 涨{summary.up_count} 跌{summary.down_count}
              {summary.limit_up_count > 0 && <span style={{ color: '#f97316' }}> 涨停{summary.limit_up_count}</span>}
            </span>
          )}
        </h2>
        <div className="flex items-center gap-1.5">
          <button onClick={() => loadData(true)} disabled={refreshing}
            className="px-2 py-0.5 rounded border text-[11px] disabled:opacity-50"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            {refreshing ? '⏳' : '🔄'}
          </button>
          <button onClick={() => navigate('/watchlist')}
            className="px-2 py-0.5 rounded border text-[11px]"
            style={{ borderColor: 'rgba(168,85,247,0.3)', color: '#a855f7' }}>
            ⭐自选股
          </button>
        </div>
      </div>

      {/* 赛道卡片列表 */}
      {loading ? (
        <div className="space-y-1.5">
          {[1,2,3,4,5,6,7,8].map(i => (
            <div key={i} className="h-16 rounded-lg animate-pulse" style={{ background: 'var(--bg-hover)' }} />
          ))}
        </div>
      ) : (
        <div className="space-y-1.5">
          {sortedSectors.map((sector) => {
            const expanded = !collapsedSectors.has(sector.sector);
            const avgChg = sector.avgChg;
            return (
              <div key={sector.sector}
                className="rounded-lg border overflow-hidden"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                {/* 赛道头部 - 点击展开/收起 */}
                <div
                  className="flex items-center gap-2 px-3 py-1.5 cursor-pointer select-none"
                  style={{ borderBottom: expanded ? '1px solid var(--border-color)' : 'none' }}
                  onClick={() => toggleSector(sector.sector)}>
                  <span className="text-sm">{SECTOR_ICONS[sector.sector] || '📌'}</span>
                  <span className="text-xs font-bold" style={{ color: sector.color }}>{sector.sector}</span>
                  <span className="text-[10px] px-1 rounded" style={{
                    background: avgChg >= 0 ? 'rgba(239,68,68,0.1)' : 'rgba(34,197,94,0.1)',
                    color: avgChg >= 0 ? '#ef4444' : '#22c55e',
                  }}>
                    {sector.upCount}/{sector.stocks.length}↑
                  </span>
                  <span className="text-xs font-bold" style={{ color: avgChg >= 0 ? '#ef4444' : '#22c55e' }}>
                    {fmtChg(avgChg)}
                  </span>
                  <div className="ml-auto flex items-center gap-1.5">
                    <button
                      onClick={(e) => { e.stopPropagation(); batchAdd(sector.sector); }}
                      className="text-[10px] px-1.5 py-0.5 rounded border"
                      style={{ borderColor: `${sector.color}40`, color: sector.color }}
                      title="整赛道加入自选股">
                      ＋整赛道
                    </button>
                    <span className="text-[10px] w-4 text-center" style={{ color: 'var(--text-muted)' }}>
                      {expanded ? '▾' : '▸'}
                    </span>
                  </div>
                </div>
                {/* 个股列表（使用 SignalCard，与自选股完全一致）*/}
                {expanded && (
                  <div className="grid grid-cols-1 gap-1.5 px-3 py-2">
                    {sector.stocks.map((signal) => (
                      <SignalCard
                        key={signal.secCode}
                        signal={signal}
                        orders={[]}
                        showWatchBtn
                        mode="watchlist"
                        showMarketState
                        showBuyPower
                        showAnalysisButton
                        strategyTags={strategyPicks[signal.secCode] || []}
                      />
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* 底部 */}
      {data && (
        <div className="text-center text-[10px] py-0.5" style={{ color: 'var(--text-muted)' }}>
          {data.generated_at} · 点击个股卡片查看详情 · 点击赛道头收起/展开
        </div>
      )}
    </div>
  );
}
