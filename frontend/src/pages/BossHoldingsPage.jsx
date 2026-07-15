/**
 * 大佬持仓跟踪 — 把游资大佬的 BUY/SELL 配对成"持仓周期"
 *
 * 数据: GET /api/yuzi/holdings
 *
 * 表格列: 大佬 | 股票 | 买入日(金额) | 卖出日(金额) | 持有天数 | 收益率 | 状态
 *
 * 解决痛点: 之前只能看到大佬"当天买入",不知道他们什么时候跑。
 * 现在能直接看到 "赵老哥 买 D1 +8812万 → 卖 D3 -9347万 持3天 +2.56%"
 */
import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';
import SinaLink from '../components/SinaLink';
import StockActionButtons from '../components/trading/StockActionButtons';

const fmtWan = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)}亿`;
  if (Math.abs(n) >= 1) return `${n.toFixed(0)}万`;
  return `${n.toFixed(2)}`;
};

const fmtNet = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  if (n === 0) return '0';
  if (n > 0) return `+${fmtWan(n)}`;
  return `-${fmtWan(Math.abs(n))}`;
};

const fmtDate = (yyyymmdd) => {
  if (!yyyymmdd || yyyymmdd.length !== 8) return '—';
  return `${yyyymmdd.slice(4, 6)}-${yyyymmdd.slice(6, 8)}`;
};

const pctColor = (v) => {
  if (v == null) return '#6b7280';
  if (v >= 5) return UP_DARK;
  if (v > 0) return UP_COLOR;
  if (v <= -5) return DOWN_DARK;
  if (v < 0) return DOWN_COLOR;
  return '#6b7280';
};

// 持有天数色块: 1-2天=一日游(蓝) / 3-5天=短线(红) / 6-10天=波段(橙) / >10天=趋势(紫)
const holdDaysStyle = (d) => {
  if (d == null) return { color: '#6b7280', bg: 'rgba(156,163,175,0.12)', label: '持仓中' };
  if (d <= 2) return { color: '#3b82f6', bg: 'rgba(59,130,246,0.12)', label: '一日游' };
  if (d <= 5) return { color: '#ef4444', bg: 'rgba(239,68,68,0.12)', label: '短线' };
  if (d <= 10) return { color: '#f97316', bg: 'rgba(249,115,22,0.12)', label: '波段' };
  return { color: '#a855f7', bg: 'rgba(168,85,247,0.12)', label: '趋势' };
};

const STATUS_OPTIONS = [
  { key: '', label: '全部' },
  { key: 'open', label: '未平仓' },
  { key: 'closed', label: '已平仓' },
];

export default function BossHoldingsPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // 过滤
  const [days, setDays] = useState(30);
  const [status, setStatus] = useState('');
  const [alias, setAlias] = useState('');
  const [minHoldDays, setMinHoldDays] = useState(0);
  const [search, setSearch] = useState('');

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({
        days: String(days),
        limit: '500',
      });
      if (status) params.set('status', status);
      if (alias.trim()) params.set('alias', alias.trim());
      if (minHoldDays > 0) params.set('min_hold_days', String(minHoldDays));
      const { ok, data: d } = await apiFetch(`/api/yuzi/holdings?${params}`);
      if (ok) setData(d);
      else setError('加载失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [days, status, alias, minHoldDays]);

  useEffect(() => { load(); }, [load]);

  // 客户端二次过滤(支持模糊搜索股票名/代码/大佬)
  const filteredHoldings = (() => {
    if (!data?.holdings) return [];
    const q = search.trim().toLowerCase();
    if (!q) return data.holdings;
    return data.holdings.filter(h =>
      h.alias?.toLowerCase().includes(q) ||
      h.ts_code?.toLowerCase().includes(q) ||
      h.stock_name?.toLowerCase().includes(q)
    );
  })();

  return (
    <div className="p-3 space-y-3">
      {/* ============ 顶部: 标题 + 过滤 ============ */}
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <h2 className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>
            💼 大佬持仓跟踪
          </h2>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            BUY → SELL 配对 · 持有几天跑了 · 赚还是亏
          </span>
        </div>

        {/* 汇总卡 */}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-2">
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总持仓</div>
              <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{data.total}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🟢 未平仓</div>
              <div className="text-base font-bold" style={{ color: UP_COLOR }}>{data.open_count}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🔴 已平仓</div>
              <div className="text-base font-bold" style={{ color: DOWN_COLOR }}>{data.closed_count}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>平均持有天数</div>
              <div className="text-base font-bold" style={{ color: '#f97316' }}>{data.avg_hold_days}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>已平仓胜率</div>
              <div className="text-base font-bold" style={{ color: pctColor(data.win_rate) }}>{data.win_rate}%</div>
            </div>
          </div>
        )}

        {/* 过滤行 */}
        <div className="flex items-center gap-2 flex-wrap mt-2">
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>回溯</span>
          <select
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="px-2 py-0.5 text-[10px] rounded border"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          >
            <option value={15}>15 天</option>
            <option value={30}>30 天</option>
            <option value={60}>60 天</option>
            <option value={90}>90 天</option>
          </select>

          <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>状态</span>
          {STATUS_OPTIONS.map(s => (
            <button
              key={s.key || 'all'}
              onClick={() => setStatus(s.key)}
              className="px-2 py-0.5 text-[10px] rounded border"
              style={{
                borderColor: status === s.key ? 'var(--accent-blue)' : 'var(--border-color)',
                background: status === s.key ? 'rgba(168,85,247,0.15)' : 'transparent',
                color: status === s.key ? '#a855f7' : 'var(--text-secondary)',
                fontWeight: status === s.key ? 700 : 400,
              }}
            >{s.label}</button>
          ))}

          <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>最小持有</span>
          <select
            value={minHoldDays}
            onChange={(e) => setMinHoldDays(Number(e.target.value))}
            className="px-2 py-0.5 text-[10px] rounded border"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          >
            <option value={0}>不限</option>
            <option value={1}>≥1天</option>
            <option value={3}>≥3天</option>
            <option value={5}>≥5天</option>
            <option value={10}>≥10天</option>
          </select>

          <input
            type="text"
            value={alias}
            onChange={(e) => setAlias(e.target.value)}
            placeholder="大佬名(精确匹配,如 赵老哥)"
            className="ml-2 px-2 py-0.5 text-[10px] rounded border w-44"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />

          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="模糊搜索(大佬/股票/代码)"
            className="ml-2 px-2 py-0.5 text-[10px] rounded border w-48"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />

          <button
            onClick={load}
            className="ml-auto px-2 py-0.5 text-[10px] rounded border"
            style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
          >
            🔄 刷新
          </button>
        </div>

        {error && <div className="text-xs mt-2" style={{ color: DOWN_COLOR }}>{error}</div>}
      </div>

      {/* ============ 持仓表 ============ */}
      {loading && <div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div>}
      {!loading && filteredHoldings.length === 0 && (
        <div className="text-xs p-4 text-center rounded border" style={{ color: 'var(--text-muted)', borderColor: 'var(--border-color)' }}>
          暂无持仓记录,试试调整过滤条件或扩大回溯天数
        </div>
      )}
      {filteredHoldings.length > 0 && (
        <div className="rounded-lg border overflow-x-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: 'var(--bg-hover)' }}>
                <th className="px-2 py-2 text-left font-bold sticky left-0 z-10" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>大佬</th>
                <th className="px-2 py-2 text-left font-bold" style={{ color: 'var(--text-primary)' }}>股票</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>买入日</th>
                <th className="px-2 py-2 text-right font-bold" style={{ color: 'var(--text-primary)' }}>买入额</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>卖出日</th>
                <th className="px-2 py-2 text-right font-bold" style={{ color: 'var(--text-primary)' }}>卖出额</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>持有天数</th>
                <th className="px-2 py-2 text-right font-bold" style={{ color: 'var(--text-primary)' }}>收益率</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>状态</th>
                <th className="px-2 py-2 text-left font-bold" style={{ color: 'var(--text-primary)' }}>操作</th>
              </tr>
            </thead>
            <tbody>
              {filteredHoldings.map((h, i) => {
                const hd = holdDaysStyle(h.hold_days);
                const isOpen = h.status === 'open';
                return (
                  <tr
                    key={`${h.alias}-${h.ts_code}-${h.open_date}-${i}`}
                    className="border-t cursor-pointer hover:opacity-90"
                    style={{ borderColor: 'var(--border-color)', background: i % 2 ? 'rgba(0,0,0,0.02)' : 'transparent' }}
                    onClick={() => navigate(`/stock/${h.ts_code.split('.')[0]}`)}
                  >
                    <td className="px-2 py-2 sticky left-0 z-10" style={{ background: i % 2 ? 'rgba(0,0,0,0.02)' : 'var(--bg-card)' }}>
                      <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{h.alias}</span>
                    </td>
                    <td className="px-2 py-2">
                      <div className="flex items-center gap-1">
                        <span className="font-medium" style={{ color: 'var(--text-primary)' }}>{h.stock_name}</span>
                        <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{h.ts_code}</span>
                        <SinaLink tsCode={h.ts_code} />
                      </div>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span style={{ color: 'var(--text-secondary)' }}>{fmtDate(h.open_date)}</span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      <span className="font-bold" style={{ color: UP_COLOR }}>{fmtNet(h.open_amount)}</span>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span style={{ color: isOpen ? 'var(--text-muted)' : 'var(--text-secondary)' }}>
                        {h.close_date ? fmtDate(h.close_date) : '—'}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      {h.close_amount != null ? (
                        <span className="font-bold" style={{ color: DOWN_COLOR }}>{fmtNet(h.close_amount)}</span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold whitespace-nowrap"
                        style={{ background: hd.bg, color: hd.color, border: `1px solid ${hd.color}40` }}
                        title={hd.label}
                      >
                        {h.hold_days != null ? `${h.hold_days}天` : '持仓中'}
                      </span>
                    </td>
                    <td className="px-2 py-2 text-right">
                      {h.return_pct != null ? (
                        <span className="font-bold" style={{ color: pctColor(h.return_pct) }}>
                          {h.return_pct > 0 ? '+' : ''}{h.return_pct.toFixed(2)}%
                        </span>
                      ) : (
                        <span style={{ color: 'var(--text-muted)' }}>—</span>
                      )}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-bold"
                        style={{
                          background: isOpen ? 'rgba(34,197,94,0.12)' : 'rgba(156,163,175,0.12)',
                          color: isOpen ? UP_COLOR : '#6b7280',
                          border: `1px solid ${isOpen ? UP_COLOR : '#6b7280'}40`,
                        }}
                      >
                        {isOpen ? '🟢 持仓中' : '⚫ 已平仓'}
                      </span>
                    </td>
                    <td className="px-2 py-2" onClick={(e) => e.stopPropagation()}>
                      <StockActionButtons
                        stockCode={h.ts_code.split('.')[0]}
                        stockName={h.stock_name}
                        size="xs"
                        onRefresh={load}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ============ 提示 ============ */}
      <div className="text-[10px] text-center" style={{ color: 'var(--text-muted)' }}>
        数据源：YuziSeatDaily (Tushare top_inst) · BUY/SELL 配对用简化 FIFO 算法 · 收益率用 StockDailyKline close 价计算 · 仅供研究不构成投资建议
      </div>
    </div>
  );
}
