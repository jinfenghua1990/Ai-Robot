import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { f2 } from '../utils/format';
import EmptyState from '../components/EmptyState';
import PageLoader from '../components/PageLoader';
import StockActionButtons from '../components/trading/StockActionButtons';

const fmtPct = (v) => {
  if (v == null || isNaN(v)) return '-';
  const n = Number(v);
  if (n === 0) return '0%';
  if (n > 0) return `+${n.toFixed(1)}%`;
  return `${n.toFixed(1)}%`;
};

const pctColor = (v) => {
  if (v == null) return '#6b7280';
  if (v >= 5) return '#dc2626';
  if (v > 0) return '#ef4444';
  if (v <= -5) return '#16a34a';
  if (v < 0) return '#22c55e';
  return '#6b7280';
};

const dayCellBg = (v) => {
  if (v == null) return 'transparent';
  if (v >= 5) return 'rgba(239,68,68,0.22)';
  if (v > 0) return 'rgba(239,68,68,0.08)';
  if (v <= -5) return 'rgba(34,197,94,0.22)';
  if (v < 0) return 'rgba(34,197,94,0.08)';
  return 'rgba(156,163,175,0.06)';
};

// 推断来源标签
const parseSource = (note) => {
  if (!note) return { label: '手动', color: '#6b7280' };
  if (note.includes('共振选股')) return { label: '🔥共振', color: '#ea580c' };
  return { label: '手动', color: '#6b7280' };
};

const DayCell = ({ d }) => {
  if (!d) return (
    <div
      className="rounded h-full flex items-center justify-center"
      style={{ background: 'rgba(156,163,175,0.04)', border: '1px solid var(--border-color)' }}
    >
      <span className="text-[10px] leading-none" style={{ color: '#9ca3af' }}>—</span>
    </div>
  );
  const dateStr = (d.trade_date || '').slice(5).replace('-', '/');
  const pct = Number(d.pct_chg) || 0;       // 累计收益（入选价 → 该交易日）
  const daily = Number(d.daily_chg) || 0;    // 当日涨跌幅（该交易日自身）
  const reason = d.reason || '';
  // 当日 ≈ 0 时显示 0.0%（避免看起来空）
  const dailyText = `${daily > 0 ? '+' : daily < 0 ? '' : ''}${daily.toFixed(1)}%`;
  return (
    <div
      className="rounded h-full flex flex-col items-stretch justify-between text-center overflow-hidden"
      style={{ background: dayCellBg(pct), border: '1px solid var(--border-color)' }}
      title={`${d.trade_date} 收盘:¥${f2(d.close_price)}｜累计收益:${fmtPct(pct)}（入选至今）｜当日涨跌:${fmtPct(daily)}${reason ? '｜' + reason : ''}`}
    >
      {/* 日期 */}
      <div className="text-[10px] leading-none text-center py-1" style={{ color: 'var(--text-muted)' }}>{dateStr}</div>

      {/* 累计（主指标，深-brown黑加粗） */}
      <div className="flex-1 flex items-center justify-center gap-1 px-1" style={{ background: 'rgba(0,0,0,0.10)' }}>
        <span className="text-[10px] font-bold leading-none" style={{ color: 'var(--text-muted)' }}>累计</span>
        <span className="text-[13px] font-bold font-mono leading-none" style={{ color: pctColor(pct) }}>{fmtPct(pct)}</span>
      </div>

      {/* 当日（辅指标-较浅+较细） */}
      <div className="flex-1 flex items-center justify-center gap-1 px-1">
        <span className="text-[10px] leading-none" style={{ color: 'var(--text-muted)' }}>当日</span>
        <span className="text-[11px] font-mono leading-none" style={{ color: pctColor(daily) }}>{dailyText}</span>
      </div>
    </div>
  );
};

export default function StockTrackerPage() {
  const navigate = useNavigate();
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [addForm, setAddForm] = useState({ code: '', name: '', note: '' });
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState('');
  const [editNoteId, setEditNoteId] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  const [refreshMsg, setRefreshMsg] = useState('');
  const [exited, setExited] = useState([]);
  const [view, setView] = useState('active'); // 'active' | 'exited'
  const [trackerSummary, setTrackerSummary] = useState(null);

  const loadStocks = useCallback(async () => {
    setLoading(true);
    try {
      const [activeRes, exitedRes, summaryRes] = await Promise.all([
        apiFetch('/api/stock-tracker'),
        apiFetch('/api/stock-tracker/exited'),
        apiFetch('/api/stock-tracker/summary'),
      ]);
      if (activeRes.ok && Array.isArray(activeRes.data)) setStocks(activeRes.data);
      if (exitedRes.ok && Array.isArray(exitedRes.data)) setExited(exitedRes.data);
      if (summaryRes.ok && summaryRes.data) setTrackerSummary(summaryRes.data);
    } catch (e) { console.error('loadStocks', e); }
    setLoading(false);
  }, []);

  useEffect(() => { loadStocks(); }, [loadStocks]);

  const handleAdd = async () => {
    if (!addForm.code || !addForm.name) { setAddError('请输入股票代码和名称'); return; }
    setAdding(true);
    setAddError('');
    try {
      const { ok, error } = await apiFetch('/api/stock-tracker', {
        method: 'POST',
        body: JSON.stringify({ stock_code: addForm.code, stock_name: addForm.name, note: addForm.note }),
      });
      if (ok) {
        setAddForm({ code: '', name: '', note: '' });
        loadStocks();
      } else {
        setAddError(error || '添加失败');
      }
    } catch { setAddError('网络错误'); }
    setAdding(false);
  };

  const handleRemove = async (e, id) => {
    e.stopPropagation();
    if (!confirm('确定要移除该跟踪吗？')) return;
    try {
      const { ok } = await apiFetch(`/api/stock-tracker/${id}`, { method: 'DELETE' });
      if (ok) {
        loadStocks();
      }
    } catch { /* silent */ }
  };

  const handleRetrack = async (e, x) => {
    e.stopPropagation();
    if (!confirm(`重新跟踪 ${x.stock_name}（${x.stock_code}）？\n将按当前最新价重新计入跟踪列表。`)) return;
    try {
      const { ok, error } = await apiFetch('/api/stock-tracker', {
        method: 'POST',
        body: JSON.stringify({
          stock_code: x.stock_code,
          stock_name: x.stock_name,
          note: `重新跟踪（原:${x.exit_reason}）`,
        }),
      });
      if (ok) {
        loadStocks();
      } else {
        alert(error || '重新跟踪失败');
      }
    } catch { alert('网络错误'); }
  };

  const handleUpdateNote = async (id, note) => {
    try {
      await apiFetch(`/api/stock-tracker/${id}/note`, {
        method: 'PUT',
        body: JSON.stringify({ note }),
      });
      setEditNoteId(null);
      loadStocks();
    } catch { /* silent */ }
  };

  const handleRefresh = async () => {
    setRefreshing(true);
    setRefreshMsg('');
    try {
      const { ok, data } = await apiFetch('/api/stock-tracker/daily-refresh', { method: 'POST' });
      if (ok) {
        setRefreshMsg(`已刷新 ${data.records_updated} 条记录`);
        loadStocks();
      } else {
        setRefreshMsg('刷新失败');
      }
    } catch { setRefreshMsg('网络错误'); }
    setRefreshing(false);
    setTimeout(() => setRefreshMsg(''), 4000);
  };

  const summary = trackerSummary?.overall || {
    count: stocks.length,
    average_return_pct: null,
    positive_count: 0,
    negative_count: 0,
    win_rate_pct: null,
  };
  const activeSummary = trackerSummary?.active || { count: stocks.length };
  const exitedSummary = trackerSummary?.exited || { count: exited.length, average_return_pct: null };

  // 入选后 D2-D5 累计收益（每个交易日分别的平均）
  // D1=入选后的第1个交易日，D2=第2个交易日，依此类推。
  const d2to5Summary = useMemo(() => {
    const result = [];
    for (let day = 2; day <= 5; day++) {
      let sum = 0, count = 0;
      for (const s of stocks) {
        const dayData = (s.daily || []).find(d => d.day_n === day);
        if (dayData && dayData.pct_chg != null) {
          sum += Number(dayData.pct_chg);
          count++;
        }
      }
      result.push({
        day,
        avg: count > 0 ? sum / count : null,
        count,
      });
    }
    return result;
  }, [stocks]);

  const renderMatrix = (list, isExited) => (
    <>
      {/* 图例：帮助理解「累计」与「当日」两个百分比 */}
      <div className="mb-3 rounded-lg border p-2 text-[11px] leading-relaxed" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
        <div className="font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>📖 怎么看这张表</div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1" style={{ color: 'var(--text-secondary)' }}>
          <span>每个格子 <b style={{ color: 'var(--text-primary)' }}>「累计 +1.8%」</b> = 自入选价<b>累计收益</b></span>
          <span>每个格子 <b style={{ color: 'var(--text-primary)' }}>「当日 -3.1%」</b> = 该交易日<b>当日涨跌幅</b></span>
          <span>列 D1–D30 = 入选后的第 N 个交易日</span>
          <span>🟥 红=盈利(涨) · 🟩 绿=亏损(跌)</span>
        </div>
      </div>
      <div className="rounded-lg border overflow-x-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <table className="w-full text-xs border-collapse" style={{ minWidth: '1400px' }}>
          <thead>
            <tr className="sticky top-0" style={{ background: 'var(--bg-hover)', height: '28px', zIndex: 20 }}>
              <th className="px-2 py-1 text-left font-bold sticky left-0 top-0" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)', minWidth: '220px', zIndex: 30 }}>股票</th>
              {Array.from({ length: 30 }, (_, i) => i + 1).map(d => (
                <th key={d} className="px-0.5 py-1 text-center font-bold text-[10px] sticky top-0" style={{ color: 'var(--text-primary)', minWidth: '72px', width: '72px', background: 'var(--bg-hover)', zIndex: 20 }}>D{d}</th>
              ))}
              <th className="px-2 py-1 text-center font-bold sticky right-0 top-0" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)', minWidth: '82px', zIndex: 30 }}>{isExited ? '累计(退出)' : '累计(至今)'}</th>
            </tr>
          </thead>
          <tbody>
            {list.map((s, i) => {
              const source = parseSource(s.note);
              const dailyMap = {};
              (s.daily || []).forEach(d => { dailyMap[d.day_n] = d; });
              const priceLine = isExited
                ? `入选 ${s.entry_date || ''} · ¥${f2(s.entry_price)} · 退出 ¥${f2(s.exit_price)} · ${s.days_held ?? 0} 天`
                : `入选 ${s.entry_date || ''} · ¥${f2(s.entry_price)} · 现 ¥${f2(s.current_price)} · ${s.days_held ?? 0} 天`;
              const noteText = isExited
                ? (s.detail ? `📝${s.detail}` : (s.note ? `📝${s.note}` : '📝—'))
                : (s.note ? `📝${s.note}` : '📝备注');
              return (
                <tr
                  key={s.id}
                  className="border-t hover:opacity-95"
                  style={{ borderColor: 'var(--border-color)', background: i % 2 ? 'rgba(0,0,0,0.02)' : 'transparent', height: '62px' }}
                >
                  <td className="px-2 py-1 sticky left-0 z-10" style={{ background: i % 2 ? 'rgba(0,0,0,0.02)' : 'var(--bg-card)', minWidth: '220px' }}>
                    <div className="flex items-center gap-1.5 flex-wrap leading-tight">
                      <span className="font-bold text-sm" style={{ color: 'var(--text-primary)' }}>{s.stock_name || '—'}</span>
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.stock_code || ''}</span>
                      <span className="px-1 py-0 rounded text-[9px] font-bold leading-tight" style={{ background: `${source.color}15`, color: source.color, border: `1px solid ${source.color}40` }}>{source.label}</span>
                    </div>
                    <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>{priceLine}</div>
                    <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>
                      {isExited ? (
                        <span className="px-1 rounded leading-tight" style={{ background: 'var(--bg-primary)' }}>{noteText}</span>
                      ) : (
                        editNoteId === s.id ? (
                          <input autoFocus defaultValue={s.note || ''}
                            onBlur={e => handleUpdateNote(s.id, e.target.value)}
                            onKeyDown={e => { if (e.key === 'Enter') handleUpdateNote(s.id, e.target.value); }}
                            className="w-20 px-1 py-0.5 text-[9px] rounded border"
                            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                            onClick={e => e.stopPropagation()} />
                        ) : (
                          <span className="text-[9px] cursor-pointer px-1 rounded leading-tight" style={{ color: 'var(--text-muted)', background: 'var(--bg-primary)' }}
                            onClick={e => { e.stopPropagation(); setEditNoteId(s.id); }}>
                            {noteText}
                          </span>
                        )
                      )}
                    </div>
                    <div className="mt-1 flex items-center gap-1 flex-wrap leading-tight">
                      <StockActionButtons stockCode={s.stock_code} stockName={s.stock_name} size="xs" showTrack={false} showSina={true} onRefresh={loadStocks} />
                      {isExited ? (
                        <button onClick={(e) => handleRetrack(e, s)} className="text-[9px] px-1 rounded hover:opacity-70 leading-tight" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>↻ 重新跟踪</button>
                      ) : (
                        <button onClick={(e) => handleRemove(e, s.id)}
                          className="text-[9px] px-1 rounded hover:opacity-70 leading-tight" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.08)' }}>✕ 移除</button>
                      )}
                      <button onClick={(e) => { e.stopPropagation(); navigate(`/stock/${s.stock_code}`); }}
                        className="text-[9px] px-1 rounded leading-tight" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>📈 详情</button>
                    </div>
                  </td>
                  {Array.from({ length: 30 }, (_, i) => i + 1).map(d => (
                    <td key={d} className="px-0.5 py-1 align-middle" style={{ width: '72px', minWidth: '72px' }}>
                      <div style={{ height: '52px' }}><DayCell d={dailyMap[d]} /></div>
                    </td>
                  ))}
                  <td className="px-2 py-1 text-center sticky right-0 z-10" style={{ background: i % 2 ? 'rgba(0,0,0,0.02)' : 'var(--bg-card)', minWidth: '82px' }}>
                    <div className="text-base font-bold font-mono leading-tight" style={{ color: pctColor(s.total_pct_chg) }}>{fmtPct(s.total_pct_chg)}</div>
                    <div className="text-[9px] leading-tight" style={{ color: 'var(--text-muted)' }}>持有 {s.days_held ?? 0} 天</div>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: 'var(--bg-primary)' }}>
      {/* 顶部：标题 + 汇总 + 添加 */}
      <div className="p-3 border-b space-y-3" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-lg font-bold gradient-text">📈 BS 跟踪池</h2>
            <p className="text-xs" style={{ color: 'var(--text-muted)' }}>平铺展示每只股票入选后的 1-30 日累计收益</p>
          </div>
          <div className="flex items-center gap-2">
            {refreshMsg && <span className="text-xs" style={{ color: 'var(--accent-blue)' }}>{refreshMsg}</span>}
            <button onClick={handleRefresh} disabled={refreshing}
              className="px-3 py-1 text-xs rounded border transition-all disabled:opacity-50"
              style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)', background: 'transparent' }}>
              {refreshing ? '刷新中...' : '🔄 刷新分析'}
            </button>
          </div>
        </div>

        {/* 汇总卡 */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>跟踪总样本</div>
            <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{summary.count}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总体等权平均收益</div>
            <div className="text-base font-bold" style={{ color: pctColor(summary.average_return_pct) }}>{fmtPct(summary.average_return_pct)}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总体胜率</div>
            <div className="text-base font-bold" style={{ color: pctColor(summary.win_rate_pct) }}>{fmtPct(summary.win_rate_pct)}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>盈利 {summary.positive_count}/{summary.count}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>已完成平均收益</div>
            <div className="text-base font-bold" style={{ color: pctColor(exitedSummary.average_return_pct) }}>{fmtPct(exitedSummary.average_return_pct)}</div>
            <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>已退出 {exitedSummary.count} 只</div>
          </div>
        </div>
        <p className="text-[10px] -mt-1" style={{ color: 'var(--text-muted)' }}>
          总体收益按每只股票等权平均，已包含仍在跟踪和已退出样本；不含仓位、手续费与滑点，不等同于实盘账户收益。
        </p>

        {/* D2-D5 入选后表现（选入日=买入日） */}
        <div>
          <div className="text-[10px] font-medium mb-1 flex items-center gap-1" style={{ color: 'var(--text-secondary)' }}>
            <span>📈 入选后 D2-D5 累计收益（选入日 = 买入日）</span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>· 矩阵 D1 = 入选后第 1 个交易日</span>
          </div>
          <div className="grid grid-cols-4 gap-2">
            {d2to5Summary.map(({ day, avg, count }) => (
              <div key={day} className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <div className="text-[10px] flex items-center justify-between" style={{ color: 'var(--text-muted)' }}>
                  <span>D{day} 累计</span>
                  <span>{count}/{activeSummary.count} 只</span>
                </div>
                <div className="text-base font-bold leading-tight" style={{ color: pctColor(avg) }}>{fmtPct(avg)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* 添加表单 */}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-xs" style={{ color: 'var(--text-secondary)' }}>➕ 加入跟踪</span>
          <input type="text" placeholder="代码" value={addForm.code}
            onChange={e => setAddForm(p => ({ ...p, code: e.target.value }))}
            className="w-24 px-2 py-1 text-xs rounded border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
          <input type="text" placeholder="名称" value={addForm.name}
            onChange={e => setAddForm(p => ({ ...p, name: e.target.value }))}
            className="w-32 px-2 py-1 text-xs rounded border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
          <input type="text" placeholder="备注/来源" value={addForm.note}
            onChange={e => setAddForm(p => ({ ...p, note: e.target.value }))}
            className="flex-1 min-w-[120px] px-2 py-1 text-xs rounded border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }} />
          <button onClick={handleAdd} disabled={adding}
            className="px-3 py-1 text-xs rounded font-medium transition-all disabled:opacity-50"
            style={{ background: 'var(--accent-blue)', color: '#fff' }}>{adding ? '...' : '跟踪'}</button>
          {addError && <span className="text-[10px]" style={{ color: '#ef4444' }}>{addError}</span>}
        </div>
      </div>

       {/* 顶部 tab：正常跟踪 / 历史跟踪 */}
       <div className="flex items-center gap-1 px-3 py-2 border-b" style={{ borderColor: 'var(--border-color)' }}>
         <button onClick={() => setView('active')}
           className="px-3 py-1.5 text-xs rounded font-medium transition-all"
           style={view === 'active'
             ? { background: 'var(--accent-blue)', color: '#fff' }
             : { background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
           📊 正常跟踪{stocks.length ? ` (${stocks.length})` : ''}
         </button>
         <button onClick={() => setView('exited')}
           className="px-3 py-1.5 text-xs rounded font-medium transition-all"
           style={view === 'exited'
             ? { background: 'var(--accent-blue)', color: '#fff' }
             : { background: 'transparent', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}>
           🚪 历史跟踪{exited.length ? ` (${exited.length})` : ''}
         </button>
       </div>

       {/* 主体：平铺矩阵 */}
       <div className="flex-1 overflow-auto p-3">
         {loading ? <PageLoader height="6rem" />
           : view === 'active'
             ? (stocks.length === 0
                 ? <EmptyState text="暂无跟踪股票" subText="上方输入代码名称加入" />
                 : renderMatrix(stocks, false))
             : (exited.length === 0
                 ? <EmptyState text="暂无已退出股票" subText="BS 转 S 自动退出或手动移除后会进入这里" />
                 : renderMatrix(exited, true))
         }
      </div>
    </div>
  );
}
