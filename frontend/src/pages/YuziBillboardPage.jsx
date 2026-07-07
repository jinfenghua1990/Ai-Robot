/**
 * 游资龙虎榜二级页面
 *
 * 三模块布局（仿截图）：
 * - 顶部:日期 + 汇总指标（上榜游资/共振股/总净买/涨停数）
 * - 左:资金动向榜（按大佬聚合，逐股明细）
 * - 右:共振信号池（按股聚合，按 quant_score 排序）
 * - 底部:某游资近 N 日战绩 + 某股游资历史
 *
 * 数据来源:
 * - GET /api/yuzi/billboard         当日资金动向榜
 * - GET /api/yuzi/resonance         当日共振信号池
 * - GET /api/yuzi/seat-stats        某游资战绩
 * - GET /api/yuzi/stock-history     某股游资历史
 * - GET /api/yuzi/dates             DB 已有日期
 * - POST /api/yuzi/refresh          触发盘后清洗
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK, BULLISH_COLOR, BEARISH_COLOR, upBg, downBg } from '../utils/colors';
import SinaLink from '../components/SinaLink';

const fmtWan = (v) => {
  if (v == null) return '-';
  const n = Number(v);
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)}亿`;
  if (Math.abs(n) >= 1) return `${n.toFixed(0)}万`;
  return `${n.toFixed(2)}`;
};

const fmtNet = (v) => {
  if (v == null) return '-';
  const n = Number(v);
  if (n === 0) return '0';
  if (n > 0) return `+${fmtWan(n)}`;
  return `-${fmtWan(Math.abs(n))}`;
};

const netColor = (v) => {
  if (v == null || v === 0) return '#6b7280';
  return v > 0 ? UP_COLOR : DOWN_COLOR;
};

const groupColor = (g) => {
  if (g === '顶级游资') return '#dc2626';
  if (g === '实力游资') return '#f59e0b';
  if (g === '机构') return '#3b82f6';
  if (g === '假游资') return '#9ca3af';
  return '#6b7280';
};

// 风格色板（稳健绿/一日游蓝/砸盘红/接力橙/低吸紫/趋势青/首板黄/机构灰）
const styleColor = (s) => {
  if (s === '稳健') return '#16a34a';
  if (s === '一日游') return '#3b82f6';
  if (s === '砸盘') return '#dc2626';
  if (s === '接力') return '#f97316';
  if (s === '低吸') return '#a855f7';
  if (s === '趋势') return '#06b6d4';
  if (s === '首板') return '#eab308';
  if (s === '机构') return '#6b7280';
  return '#9ca3af';
};

const STYLE_OPTIONS = ['稳健', '一日游', '砸盘', '接力', '低吸', '趋势', '首板', '机构'];

const scoreColor = (s) => {
  if (s >= 90) return '#dc2626';
  if (s >= 80) return '#ef4444';
  if (s >= 70) return '#f59e0b';
  if (s >= 60) return '#3b82f6';
  return '#9ca3af';
};

export default function YuziBillboardPage() {
  const navigate = useNavigate();
  const [billboard, setBillboard] = useState(null);
  const [resonance, setResonance] = useState(null);
  const [dates, setDates] = useState([]);
  const [date, setDate] = useState('');
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [groupFilter, setGroupFilter] = useState('');
  const [styleFilter, setStyleFilter] = useState('');
  const [searchSeat, setSearchSeat] = useState('');
  const [minResonance, setMinResonance] = useState(1);
  const [seatStatsAlias, setSeatStatsAlias] = useState('');
  const [seatStats, setSeatStats] = useState(null);
  const [stockCode, setStockCode] = useState('');
  const [stockHist, setStockHist] = useState(null);
  const [error, setError] = useState('');

  // 加载日期列表
  useEffect(() => {
    (async () => {
      const { ok, data } = await apiFetch('/api/yuzi/dates?limit=20');
      if (ok && data?.dates) {
        setDates(data.dates);
        if (data.dates[0]?.date) setDate(data.dates[0].date);
      }
    })();
  }, []);

  // 加载数据
  const loadData = useCallback(async () => {
    if (!date) return;
    setLoading(true);
    setError('');
    try {
      const [bRes, rRes] = await Promise.all([
        apiFetch(`/api/yuzi/billboard?date=${date}&group=${groupFilter}&style=${styleFilter}`),
        apiFetch(`/api/yuzi/resonance?date=${date}&min_resonance=${minResonance}&limit=200`),
      ]);
      if (bRes.ok) setBillboard(bRes.data);
      else setError('加载资金动向榜失败');
      if (rRes.ok) setResonance(rRes.data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [date, groupFilter, styleFilter, minResonance]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleRefresh = async () => {
    if (!confirm(`触发 ${date || '当日'} 盘后清洗？会拉 Tushare 并覆写当日数据。`)) return;
    setRefreshing(true);
    try {
      const { ok, data } = await apiFetch('/api/yuzi/refresh', {
        method: 'POST',
        body: JSON.stringify({ date: date || null }),
      });
      if (ok) {
        alert(`✅ 清洗完成\n上榜 ${data.top_list}，席位明细 ${data.top_inst}，匹配 ${data.matched}，写入信号 ${data.signals}\n未匹配席位 ${data.unmatched_count} 个`);
        // 刷新日期列表（可能新增一天）
        const { ok: ok2, data: d2 } = await apiFetch('/api/yuzi/dates?limit=20');
        if (ok2 && d2?.dates) {
          setDates(d2.dates);
          if (!date && d2.dates[0]?.date) setDate(d2.dates[0].date);
        }
        loadData();
      } else {
        alert('❌ 清洗失败：' + JSON.stringify(data));
      }
    } catch (e) {
      alert('❌ ' + String(e));
    } finally {
      setRefreshing(false);
    }
  };

  const handleSeatStats = async (alias) => {
    setSeatStatsAlias(alias);
    setSeatStats(null);
    const { ok, data } = await apiFetch(`/api/yuzi/seat-stats?alias=${encodeURIComponent(alias)}&days=10`);
    if (ok) setSeatStats(data);
  };

  const handleStockHist = async () => {
    if (!stockCode) return;
    setStockHist(null);
    const code = stockCode.trim();
    const full = code.includes('.') ? code : (code.startsWith('6') ? `${code}.SH` : code.startsWith('0') || code.startsWith('3') ? `${code}.SZ` : `${code}.SH`);
    const { ok, data } = await apiFetch(`/api/yuzi/stock-history?ts_code=${full}&days=20`);
    if (ok) setStockHist(data);
  };

  const dateLabel = date ? `${date.slice(0, 4)}-${date.slice(4, 6)}-${date.slice(6, 8)}` : '加载中...';

  return (
    <div className="space-y-3">
      {/* ============ 顶部:标题 + 汇总 ============ */}
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-lg font-bold flex items-center gap-1" style={{ color: 'var(--accent-blue)' }}>
            🐉 游资龙虎榜
          </h1>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>Day1 盘后清洗 → 量化共振 → Day2 观察池</span>
          <div className="flex items-center gap-1 ml-auto flex-wrap">
            <label className="text-xs" style={{ color: 'var(--text-muted)' }}>日期</label>
            <select
              value={date}
              onChange={(e) => setDate(e.target.value)}
              className="px-2 py-1 text-xs rounded border"
              style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
            >
              {dates.length === 0 && <option value="">暂无数据</option>}
              {dates.map(d => (
                <option key={d.date} value={d.date}>
                  {d.date.slice(0,4)}-{d.date.slice(4,6)}-{d.date.slice(6,8)} ({d.signal_count}信号)
                </option>
              ))}
            </select>
            <button
              onClick={handleRefresh}
              disabled={refreshing}
              className="px-2 py-1 text-xs rounded border disabled:opacity-50"
              style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
              title="从 Tushare 拉当日龙虎榜并清洗落库"
            >
              {refreshing ? '⏳ 清洗中...' : '🔄 盘后清洗'}
            </button>
          </div>
        </div>

        {/* 汇总卡片 */}
        {billboard && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-2">
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>上榜游资数</div>
              <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{billboard.count}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>共振信号</div>
              <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{resonance?.count || 0}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总净买入(万)</div>
              <div className="text-base font-bold" style={{ color: netColor(billboard.total_net) }}>{fmtNet(billboard.total_net)}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>净流入(万)</div>
              <div className="text-base font-bold" style={{ color: UP_COLOR }}>{fmtWan(billboard.net_in)}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>净流出(万)</div>
              <div className="text-base font-bold" style={{ color: DOWN_COLOR }}>{fmtWan(billboard.net_out)}</div>
            </div>
          </div>
        )}

        {/* 过滤 */}
        <div className="flex items-center gap-2 flex-wrap mt-2">
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>分组</span>
          {['', '顶级游资', '实力游资', '机构', '假游资'].map(g => (
            <button
              key={g || 'all'}
              onClick={() => setGroupFilter(g)}
              className="px-2 py-0.5 text-[10px] rounded border"
              style={{
                borderColor: groupColor(g || ''),
                background: groupFilter === g ? `${groupColor(g || '')}20` : 'transparent',
                color: groupColor(g || ''),
                fontWeight: groupFilter === g ? 700 : 400,
              }}
            >
              {g || '全部'}
            </button>
          ))}
          <span className="text-[10px] ml-3" style={{ color: 'var(--text-muted)' }}>🎯 风格</span>
          {['', ...STYLE_OPTIONS].map(s => {
            const sc = s ? styleColor(s) : '#6b7280';
            const isActive = styleFilter === s;
            // 风格分布计数(显示在按钮上)
            const dist = billboard?.style_distribution?.find(d => d.style === s);
            const cnt = s ? (dist?.count || 0) : (billboard?.count || 0);
            return (
              <button
                key={s || 'all'}
                onClick={() => setStyleFilter(s)}
                className="px-2 py-0.5 text-[10px] rounded border"
                style={{
                  borderColor: sc,
                  background: isActive ? `${sc}25` : 'transparent',
                  color: sc,
                  fontWeight: isActive ? 700 : 400,
                }}
                title={s ? `${s}风格 (${cnt}位)` : `全部风格 (${cnt}位)`}
              >
                {s || '全部'} <span style={{ opacity: 0.6 }}>·{cnt}</span>
              </button>
            );
          })}
          <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>最小共振</span>
          <input
            type="number"
            min={1}
            max={10}
            value={minResonance}
            onChange={(e) => setMinResonance(Number(e.target.value) || 1)}
            className="w-12 px-1 py-0.5 text-[10px] rounded border"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
          <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>席位搜索</span>
          <input
            type="text"
            value={searchSeat}
            onChange={(e) => setSearchSeat(e.target.value)}
            placeholder="大佬标签 / 营业部"
            className="px-1 py-0.5 text-[10px] rounded border w-32"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
        </div>

        {error && <div className="text-xs mt-2" style={{ color: DOWN_COLOR }}>{error}</div>}
      </div>

      {/* ============ 主区:左(资金动向榜) + 右(共振信号池) ============ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 左:资金动向榜(按大佬聚合) */}
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 资金动向榜 · 按大佬聚合</h2>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{billboard?.count || 0} 位游资</span>
          </div>
          {loading && <div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div>}
          {!loading && billboard?.billboard?.length === 0 && (
            <div className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>
              {dateLabel} 无数据，点击右上「盘后清洗」可触发采集
            </div>
          )}
          <div className="space-y-1.5 max-h-[calc(100vh-380px)] overflow-y-auto">
            {billboard?.billboard
              ?.filter(b => !searchSeat || b.alias.includes(searchSeat) || b.seat_names.some(s => s.includes(searchSeat)))
              ?.map((b, i) => (
              <div
                key={b.alias}
                className="rounded border p-1.5 cursor-pointer hover:opacity-90"
                style={{
                  borderColor: `${groupColor(b.group)}50`,
                  background: `${groupColor(b.group)}08`,
                }}
                onClick={() => handleSeatStats(b.alias)}
                title="点击查看该游资近 10 日战绩"
              >
                {/* 大佬行 */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs font-bold min-w-12" style={{ color: groupColor(b.group) }}>{b.alias}</span>
                  <span className="text-[10px] px-1 rounded" style={{ background: `${groupColor(b.group)}20`, color: groupColor(b.group) }}>{b.group}</span>
                  {b.style && b.style !== '未分类' && (
                    <span
                      className="text-[10px] px-1 rounded font-medium"
                      style={{ background: `${styleColor(b.style)}25`, color: styleColor(b.style), border: `1px solid ${styleColor(b.style)}50` }}
                      title={`操作风格: ${b.style}`}
                    >
                      {b.style}
                    </span>
                  )}
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{b.region}</span>
                  <span className="text-[10px] ml-auto font-bold" style={{ color: netColor(b.total_net) }}>{fmtNet(b.total_net)}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{b.buy_count}买 / {b.sell_count}卖</span>
                </div>
                {/* 逐股明细 */}
                <div className="mt-0.5 flex flex-wrap gap-1">
                  {b.stocks.slice(0, 6).map(s => (
                    <span
                      key={s.ts_code + s.side}
                      className="text-[10px] px-1 rounded cursor-pointer"
                      style={{
                        background: s.side === 'BUY' ? upBg(0.1) : downBg(0.1),
                        color: s.side === 'BUY' ? UP_COLOR : DOWN_COLOR,
                      }}
                      onClick={(e) => { e.stopPropagation(); navigate(`/stock/${s.ts_code.split('.')[0]}`); }}
                      title={`${s.name} (${s.ts_code}) ${s.side === 'BUY' ? '买入' : '卖出'} ${fmtNet(s.net)}\n上榜原因: ${s.reason || '-'}`}
                    >
                      {s.name} {fmtNet(s.net)}
                    </span>
                  ))}
                  {b.stocks.length > 6 && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>... +{b.stocks.length - 6}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 右:共振信号池(按股聚合) */}
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🔥 共振信号池 · Day2 观察池</h2>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{resonance?.count || 0} 只</span>
          </div>
          {loading && <div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div>}
          {!loading && resonance?.signals?.length === 0 && (
            <div className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>
              {dateLabel} 无共振信号
            </div>
          )}
          <div className="space-y-1.5 max-h-[calc(100vh-380px)] overflow-y-auto">
            {resonance?.signals?.map(s => (
              <div
                key={s.ts_code}
                className="rounded border p-1.5"
                style={{
                  borderColor: s.limit_up_flag ? UP_DARK : 'var(--border-color)',
                  background: s.limit_up_flag ? upBg(0.05) : 'transparent',
                }}
              >
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span
                    className="text-sm font-bold cursor-pointer"
                    style={{ color: s.change_pct >= 0 ? UP_COLOR : DOWN_COLOR }}
                    onClick={() => navigate(`/stock/${s.ts_code.split('.')[0]}`)}
                  >{s.name || s.ts_code}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{s.ts_code}</span>
                  <SinaLink tsCode={s.ts_code} />
                  {s.limit_up_flag && <span className="text-[10px] px-1 rounded font-bold" style={{ background: UP_COLOR, color: '#fff' }}>涨停</span>}
                  <span className="text-xs ml-1" style={{ color: s.change_pct >= 0 ? UP_COLOR : DOWN_COLOR }}>{s.change_pct > 0 ? '+' : ''}{s.change_pct.toFixed(2)}%</span>
                  <span className="text-[10px] ml-auto font-bold px-1.5 py-0.5 rounded" style={{ background: scoreColor(s.quant_score), color: '#fff' }}>{s.quant_score}分</span>
                </div>
                <div className="flex items-center gap-1.5 mt-0.5 flex-wrap">
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>净买</span>
                  <span className="text-xs font-bold" style={{ color: netColor(s.total_net_buy) }}>{fmtNet(s.total_net_buy)}</span>
                  <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>× {s.resonance_count}位共振</span>
                  {s.turnover_rate > 0 && <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>换手 {s.turnover_rate.toFixed(1)}%</span>}
                </div>
                <div className="flex flex-wrap gap-1 mt-0.5">
                  {s.boss_list.map(b => (
                    <span
                      key={b}
                      className="text-[10px] px-1 rounded cursor-pointer"
                      style={{ background: 'rgba(239,68,68,0.1)', color: UP_COLOR }}
                      onClick={() => handleSeatStats(b)}
                      title="点击查看该游资近 10 日战绩"
                    >{b}</span>
                  ))}
                </div>
                {s.list_reason && <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>上榜：{s.list_reason}</div>}
                {s.seat_detail?.length > 0 && (
                  <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
                    逐席位:
                    {s.seat_detail.slice(0, 5).map(d => (
                      <span key={d.alias} className="ml-1" style={{ color: d.side === 'BUY' ? UP_COLOR : DOWN_COLOR }}>
                        {d.alias} {fmtNet(d.net_buy)}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ============ 战绩区:游资战绩 + 个股历史 ============ */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* 游资战绩 */}
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>👤 游资近 10 日战绩</h2>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>点击榜单上的游资</span>
          </div>
          {!seatStatsAlias && <div className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>点击上方资金动向榜中的游资名查看战绩</div>}
          {seatStatsAlias && !seatStats && <div className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>加载 {seatStatsAlias} 战绩...</div>}
          {seatStats && (
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-sm font-bold" style={{ color: 'var(--accent-blue)' }}>{seatStats.alias}</span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>近 10 日 {seatStats.total_records} 笔</span>
                <span className="text-xs ml-auto" style={{ color: netColor(seatStats.total_net) }}>累计净买 {fmtNet(seatStats.total_net)}</span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>胜率 {seatStats.win_rate}%</span>
              </div>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {seatStats.history.map(h => (
                  <div key={h.date} className="rounded border p-1.5" style={{ borderColor: 'var(--border-color)' }}>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] font-bold" style={{ color: 'var(--text-primary)' }}>{h.date.slice(0,4)}-{h.date.slice(4,6)}-{h.date.slice(6,8)}</span>
                      <span className="text-xs font-bold" style={{ color: netColor(h.total_net) }}>{fmtNet(h.total_net)}</span>
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{h.buy_count}买/{h.sell_count}卖</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {h.stocks.map((s, i) => (
                        <span
                          key={i}
                          className="text-[10px] px-1 rounded cursor-pointer"
                          style={{
                            background: s.side === 'BUY' ? upBg(0.1) : downBg(0.1),
                            color: s.side === 'BUY' ? UP_COLOR : DOWN_COLOR,
                          }}
                          onClick={() => navigate(`/stock/${s.ts_code.split('.')[0]}`)}
                        >{s.name} {fmtNet(s.net)}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* 个股历史 */}
        <div className="rounded-lg border p-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-1.5">
            <h2 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>🔍 个股游资历史</h2>
            <div className="flex items-center gap-1">
              <input
                type="text"
                value={stockCode}
                onChange={(e) => setStockCode(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && handleStockHist()}
                placeholder="股票代码 600793"
                className="px-1 py-0.5 text-[10px] rounded border w-24"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
              />
              <button
                onClick={handleStockHist}
                className="px-1.5 py-0.5 text-[10px] rounded"
                style={{ background: 'var(--accent-blue)', color: '#fff' }}
              >查</button>
            </div>
          </div>
          {!stockHist && <div className="text-xs p-2" style={{ color: 'var(--text-muted)' }}>输入股票代码查询近 20 日游资介入记录</div>}
          {stockHist && (
            <div>
              <div className="flex items-center gap-2 mb-1.5">
                <span className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>{stockHist.ts_code}</span>
                <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>近 20 日出现 {stockHist.appeared_days} 天</span>
                <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>游资: {stockHist.all_bosses.join('、') || '-'}</span>
              </div>
              <div className="space-y-1 max-h-64 overflow-y-auto">
                {stockHist.history.map(h => (
                  <div key={h.date} className="rounded border p-1.5" style={{ borderColor: 'var(--border-color)' }}>
                    <div className="flex items-center gap-1.5">
                      <span className="text-[10px] font-bold">{h.date.slice(0,4)}-{h.date.slice(4,6)}-{h.date.slice(6,8)}</span>
                      <span className="text-xs font-bold" style={{ color: netColor(h.total_net) }}>{fmtNet(h.total_net)}</span>
                      <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{h.yuzu_count} 位游资</span>
                    </div>
                    <div className="flex flex-wrap gap-1 mt-0.5">
                      {h.seats.map((s, i) => (
                        <span
                          key={i}
                          className="text-[10px] px-1 rounded cursor-pointer"
                          style={{
                            background: s.side === 'BUY' ? upBg(0.1) : downBg(0.1),
                            color: s.side === 'BUY' ? UP_COLOR : DOWN_COLOR,
                          }}
                          onClick={() => handleSeatStats(s.alias)}
                        >{s.alias} {fmtNet(s.net)}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ============ 提示 ============ */}
      <div className="text-[10px] text-center" style={{ color: 'var(--text-muted)' }}>
        数据源：Tushare Pro top_list + top_inst · 仅供研究，不构成投资建议
      </div>
    </div>
  );
}
