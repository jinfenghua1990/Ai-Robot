import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { f2, colorForPct } from '../utils/format';
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
  const [exitedOpen, setExitedOpen] = useState(true);

  const loadStocks = useCallback(async () => {
    setLoading(true);
    try {
      const [activeRes, exitedRes] = await Promise.all([
        apiFetch('/api/stock-tracker'),
        apiFetch('/api/stock-tracker/exited'),
      ]);
      if (activeRes.ok && Array.isArray(activeRes.data)) setStocks(activeRes.data);
      if (exitedRes.ok && Array.isArray(exitedRes.data)) setExited(exitedRes.data);
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
    } catch (e) { setAddError('网络错误'); }
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
    } catch (e) { /* silent */ }
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
    } catch (err) { alert('网络错误'); }
  };

  const handleUpdateNote = async (id, note) => {
    try {
      await apiFetch(`/api/stock-tracker/${id}/note`, {
        method: 'PUT',
        body: JSON.stringify({ note }),
      });
      setEditNoteId(null);
      loadStocks();
    } catch (e) { /* silent */ }
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
    } catch (e) { setRefreshMsg('网络错误'); }
    setRefreshing(false);
    setTimeout(() => setRefreshMsg(''), 4000);
  };

  const summary = useMemo(() => {
    const total = stocks.length;
    const avg = total ? stocks.reduce((s, x) => s + (Number(x.total_pct_chg) || 0), 0) / total : 0;
    const positive = stocks.filter(x => (Number(x.total_pct_chg) || 0) > 0).length;
    const negative = stocks.filter(x => (Number(x.total_pct_chg) || 0) < 0).length;
    return { total, avg, positive, negative };
  }, [stocks]);

  // 入选后 D2-D5 累计收益（每个交易日分别的平均）
  // D1=入选日(pct=0)，D2=入选后第1个交易日，D3=第2个交易日...以此类推
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

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: 'var(--bg-primary)' }}>
      {/* 顶部：标题 + 汇总 + 添加 */}
      <div className="p-3 border-b space-y-3" style={{ borderColor: 'var(--border-color)' }}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div>
            <h2 className="text-lg font-bold gradient-text">📈 股票跟踪</h2>
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
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总跟踪数</div>
            <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{summary.total}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>平均累计收益</div>
            <div className="text-base font-bold" style={{ color: pctColor(summary.avg) }}>{fmtPct(summary.avg)}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>盈利股</div>
            <div className="text-base font-bold" style={{ color: '#ef4444' }}>{summary.positive}</div>
          </div>
          <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
            <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>亏损股</div>
            <div className="text-base font-bold" style={{ color: '#22c55e' }}>{summary.negative}</div>
          </div>
        </div>

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
                  <span>{count}/{summary.total} 只</span>
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

      {/* 主体：平铺矩阵 */}
      <div className="flex-1 overflow-auto p-3">
        {loading ? <PageLoader height="6rem" />
          : stocks.length === 0 && exited.length === 0 ? <EmptyState text="暂无跟踪股票" subText="上方输入代码名称加入" />
          : (<>
            {/* 图例：帮助理解「累计」与「当日」两个百分比 */}
            <div className="mb-3 rounded-lg border p-2 text-[11px] leading-relaxed" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
              <div className="font-semibold mb-1" style={{ color: 'var(--text-primary)' }}>📖 怎么看这张表</div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1" style={{ color: 'var(--text-secondary)' }}>
                <span>每个格子 <b style={{ color: 'var(--text-primary)' }}>「累计 +1.8%」</b> = 自入选价<b>累计收益</b></span>
                <span>每个格子 <b style={{ color: 'var(--text-primary)' }}>「当日 -3.1%」</b> = 该交易日<b>当日涨跌幅</b></span>
                <span>列 D1–D30 = 入选后的第 N 个交易日</span>
                <span>🟥 红=盈利(涨)　🟩 绿=亏损(跌)</span>
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
                    <th className="px-2 py-1 text-center font-bold sticky right-0 top-0" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)', minWidth: '82px', zIndex: 30 }}>累计(至今)</th>
                  </tr>
                </thead>
                <tbody>
                  {stocks.map((s, i) => {
                    const source = parseSource(s.note);
                    const dailyMap = {};
                    (s.daily || []).forEach(d => { dailyMap[d.day_n] = d; });
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
                          <div className="text-[9px] leading-tight mt-0.5" style={{ color: 'var(--text-muted)' }}>
                            入选 {s.entry_date || ''} · ¥{f2(s.entry_price)} · 现 ¥{f2(s.current_price)} · {s.days_held ?? 0} 天
                          </div>
                          <div className="mt-1 flex items-center gap-1 flex-wrap leading-tight">
                            {editNoteId === s.id ? (
                              <input autoFocus defaultValue={s.note || ''}
                                onBlur={e => handleUpdateNote(s.id, e.target.value)}
                                onKeyDown={e => { if (e.key === 'Enter') handleUpdateNote(s.id, e.target.value); }}
                                className="w-20 px-1 py-0.5 text-[9px] rounded border"
                                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                                onClick={e => e.stopPropagation()} />
                            ) : (
                              <span className="text-[9px] cursor-pointer px-1 rounded leading-tight" style={{ color: 'var(--text-muted)', background: 'var(--bg-primary)' }}
                                onClick={e => { e.stopPropagation(); setEditNoteId(s.id); }}>
                                {s.note ? `📝${s.note}` : '📝备注'}
                              </span>
                            )}
                          </div>
                          <div className="mt-1 flex items-center gap-1 flex-wrap leading-tight">
                            <StockActionButtons stockCode={s.stock_code} stockName={s.stock_name} size="xs" showTrack={false} showSina={true} onRefresh={loadStocks} />
                            <button onClick={(e) => handleRemove(e, s.id)}
                              className="text-[9px] px-1 rounded hover:opacity-70 leading-tight" style={{ color: '#ef4444', background: 'rgba(239,68,68,0.08)' }}>✕ 移除</button>
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

            {exited.length > 0 && (
              <div className="mt-4 rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                <button
                  type="button"
                  onClick={() => setExitedOpen(o => !o)}
                  className="w-full flex items-center justify-between px-3 py-2 text-left"
                >
                  <span className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
                    🚪 已退出 {exited.length} 只
                    <span className="ml-2 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>（BS 转 S 自动退出 / 手动移除，不再计入跟踪）</span>
                  </span>
                  <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{exitedOpen ? '▾' : '▸'}</span>
                </button>
                {exitedOpen && (
                  <>
                    {(() => {
                      const vals = exited.map(e => e.total_pct_chg || 0);
                      const scaleMax = Math.max(10, ...vals.map(Math.abs));
                      const hi = Math.max(...vals), lo = Math.min(...vals);
                      return (
                        <div className="px-3 pt-2 pb-1">
                          <div className="flex items-end gap-[3px] h-14" style={{ borderBottom: '1px solid var(--border-color)' }}>
                            {exited.map(x => {
                              const v = x.total_pct_chg || 0;
                              const h = Math.max(2, (Math.abs(v) / scaleMax) * 48);
                              return <div key={`bar-${x.id}`} title={`${x.stock_name} ${fmtPct(v)}`} className="flex-1 min-w-[3px] rounded-t" style={{ height: `${h}px`, background: pctColor(v) }} />;
                            })}
                          </div>
                          <div className="mt-1 flex justify-between text-[9px]" style={{ color: 'var(--text-muted)' }}>
                            <span>退出盈亏分布（红涨绿跌 · 共 {exited.length} 只）</span>
                            <span>最高 {fmtPct(hi)} · 最低 {fmtPct(lo)}</span>
                          </div>
                        </div>
                      );
                    })()}
                    <div className="px-3 pb-3 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2">
                    {exited.map(x => {
                      const reasonColor = x.exit_reason === 'BS 转 S 自动退出' ? '#ea580c' : '#9ca3af';
                      return (
                        <div key={x.id} className="rounded border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-hover)' }}>
                          <div className="flex items-center justify-between gap-2">
                            <div className="flex items-center gap-1.5 min-w-0">
                              <span className="font-bold text-sm truncate" style={{ color: 'var(--text-primary)' }}>{x.stock_name || '—'}</span>
                              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{x.stock_code}</span>
                            </div>
                            <span className="px-1 py-0 rounded text-[9px] font-bold shrink-0" style={{ background: `${reasonColor}15`, color: reasonColor, border: `1px solid ${reasonColor}40` }}>{x.exit_reason}</span>
                          </div>
                          <div className="mt-1 flex items-center justify-between text-[11px]">
                            <span style={{ color: 'var(--text-muted)' }}>退出 {x.exit_date}</span>
                            <span className="font-bold font-mono" style={{ color: pctColor(x.total_pct_chg) }}>{fmtPct(x.total_pct_chg)}</span>
                          </div>
                          <div className="mt-0.5 text-[10px] leading-tight" style={{ color: 'var(--text-muted)' }}>
                            入选 {x.entry_date} · ¥{f2(x.entry_price)} · 持有 {x.days_held ?? 0} 天
                          </div>
                          {x.detail ? (
                            <div className="mt-1 text-[10px] leading-tight truncate" style={{ color: 'var(--text-secondary)' }} title={x.detail}>📝 {x.detail}</div>
                          ) : null}
                          <button
                            type="button"
                            onClick={e => handleRetrack(e, x)}
                            className="mt-1.5 w-full text-[10px] rounded border py-1 hover:opacity-80"
                            style={{ borderColor: 'var(--border-color)', color: '#3b82f6', background: 'transparent' }}
                          >↻ 重新跟踪</button>
                        </div>
                      );
                    })}
                  </div>
                  </>
                )}
              </div>
            )}
          </>)}
      </div>
    </div>
  );
}
