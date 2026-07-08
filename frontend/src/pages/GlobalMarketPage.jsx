/**
 * 港股/美股行情中心
 * 路由: /global-market
 *
 * 数据源: Yahoo Finance (经后端 /api/global-market/* 代理)
 * 功能:
 *  - 市场切换 (港股 HK / 美股 US)
 *  - 指数卡片 (恒生/道琼斯等)
 *  - 关注列表 (12只港股 + 12只美股) + 技术指标
 *  - 涨跌统计
 */
import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';

const MARKETS = [
  { key: 'HK', label: '港股', icon: '🇭🇰' },
  { key: 'US', label: '美股', icon: '🇺🇸' },
];

const fmtPct = (v, withSign = true) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  if (n === 0) return '0%';
  const sign = withSign && n > 0 ? '+' : '';
  return `${sign}${n.toFixed(2)}%`;
};

const fmtNum = (v, digits = 2) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  return n.toFixed(digits);
};

const fmtVol = (v) => {
  if (v == null) return '—';
  const n = Number(v);
  if (isNaN(n)) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(2)}K`;
  return n.toString();
};

const pctColor = (v) => {
  if (v == null) return '#6b7280';
  const n = Number(v);
  if (n > 0) return UP_COLOR;
  if (n < 0) return DOWN_COLOR;
  return '#6b7280';
};

// 迷你 sparkline (SVG)
const Sparkline = ({ data, width = 80, height = 24 }) => {
  if (!data || data.length < 2) return <span style={{ color: '#9ca3af', fontSize: '10px' }}>—</span>;
  const closes = data.map(d => Number(d.c)).filter(c => !isNaN(c));
  if (closes.length < 2) return <span style={{ color: '#9ca3af', fontSize: '10px' }}>—</span>;
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const range = max - min || 1;
  const points = closes.map((c, i) => {
    const x = (i / (closes.length - 1)) * width;
    const y = height - ((c - min) / range) * height;
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  const isUp = closes[closes.length - 1] >= closes[0];
  const color = isUp ? UP_COLOR : DOWN_COLOR;
  return (
    <svg width={width} height={height} style={{ display: 'inline-block', verticalAlign: 'middle' }}>
      <polyline points={points} fill="none" stroke={color} strokeWidth="1.2" />
    </svg>
  );
};

export default function GlobalMarketPage() {
  const [market, setMarket] = useState('HK');
  const [overview, setOverview] = useState(null);
  const [watchlist, setWatchlist] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState('');

  const load = useCallback(async (mkt) => {
    setLoading(true);
    setError('');
    try {
      const [ovRes, wlRes] = await Promise.all([
        apiFetch(`/api/global-market/overview/${mkt}`),
        apiFetch(`/api/global-market/watchlist-enhanced/${mkt}`),
      ]);
      if (ovRes.ok) {
        setOverview(ovRes.data);
        setUpdated(ovRes.data?.updated_at || '');
      } else {
        setError(ovRes.error || '加载失败');
      }
      if (wlRes.ok) setWatchlist(wlRes.data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(market); }, [market, load]);

  const indices = overview?.indices || [];
  const quotes = overview?.quotes || [];
  const stats = overview?.stats || {};
  const items = watchlist?.items || [];

  // 按 change_pct 降序排序关注列表
  const sortedItems = [...items].sort((a, b) => (b.change_pct || 0) - (a.change_pct || 0));

  return (
    <div className="p-4 md:p-6" style={{ color: 'var(--text-primary)' }}>
      <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
        <div>
          <h1 className="text-xl md:text-2xl font-bold">🌍 港股 / 美股行情</h1>
          <p className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>
            数据源: Yahoo Finance · 关注列表 + 指数 + 技术指标
          </p>
        </div>
        <div className="flex items-center gap-2">
          {MARKETS.map(m => (
            <button
              key={m.key}
              onClick={() => setMarket(m.key)}
              className="px-3 py-1.5 rounded text-sm font-bold transition"
              style={{
                background: market === m.key ? UP_COLOR : 'var(--bg-card)',
                color: market === m.key ? '#fff' : 'var(--text-secondary)',
                border: `1px solid ${market === m.key ? UP_COLOR : 'var(--border-color)'}`,
              }}
            >
              {m.icon} {m.label}
            </button>
          ))}
          <button
            onClick={() => load(market)}
            className="px-3 py-1.5 rounded text-sm"
            style={{ background: 'var(--bg-card)', color: 'var(--text-secondary)', border: '1px solid var(--border-color)' }}
          >
            🔄 刷新
          </button>
        </div>
      </div>

      {updated && (
        <div className="text-[11px] mb-3" style={{ color: 'var(--text-muted)' }}>
          更新时间: {updated}
        </div>
      )}

      {error && (
        <div className="p-3 mb-4 rounded text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: DOWN_DARK, border: '1px solid rgba(239,68,68,0.3)' }}>
          ⚠️ {error}
        </div>
      )}

      {/* 指数卡片 */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-5">
        {loading && !overview ? (
          [1, 2, 3].map(i => (
            <div key={i} className="p-4 rounded animate-pulse" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)', height: 100 }} />
          ))
        ) : indices.length === 0 ? (
          <div className="col-span-3 p-4 rounded text-center text-sm" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)', border: '1px solid var(--border-color)' }}>
            指数数据暂不可用 (Yahoo Finance 可能被限流)
          </div>
        ) : indices.map(idx => (
          <div key={idx.code} className="p-4 rounded" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold">{idx.name}</span>
              <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{idx.code}</span>
            </div>
            <div className="text-2xl font-bold" style={{ color: pctColor(idx.change_pct) }}>
              {idx.price != null ? fmtNum(idx.price) : '—'}
            </div>
            <div className="text-sm mt-1" style={{ color: pctColor(idx.change_pct) }}>
              {fmtPct(idx.change_pct)} {idx.change_amount != null ? `(${idx.change_amount > 0 ? '+' : ''}${fmtNum(idx.change_amount)})` : ''}
            </div>
          </div>
        ))}
      </div>

      {/* 涨跌统计 */}
      {stats.total > 0 && (
        <div className="grid grid-cols-3 gap-2 mb-4">
          <div className="p-2 rounded text-center" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>上涨</div>
            <div className="text-lg font-bold" style={{ color: UP_COLOR }}>{stats.up}</div>
          </div>
          <div className="p-2 rounded text-center" style={{ background: 'rgba(156,163,175,0.1)', border: '1px solid var(--border-color)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>平盘</div>
            <div className="text-lg font-bold" style={{ color: '#6b7280' }}>{stats.flat}</div>
          </div>
          <div className="p-2 rounded text-center" style={{ background: 'rgba(34,197,94,0.1)', border: '1px solid rgba(34,197,94,0.2)' }}>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>下跌</div>
            <div className="text-lg font-bold" style={{ color: DOWN_COLOR }}>{stats.down}</div>
          </div>
        </div>
      )}

      {/* 关注列表表格 */}
      <div className="rounded overflow-hidden" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="p-3 border-b" style={{ borderColor: 'var(--border-color)' }}>
          <h2 className="text-sm font-bold">📊 关注列表 · {market === 'HK' ? '港股' : '美股'} ({items.length})</h2>
        </div>
        <div style={{ overflowX: 'auto' }}>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: 'var(--bg-secondary)', color: 'var(--text-muted)' }}>
                <th className="px-2 py-2 text-left">代码/名称</th>
                <th className="px-2 py-2 text-right">最新价</th>
                <th className="px-2 py-2 text-right">涨跌幅</th>
                <th className="px-2 py-2 text-right">开盘</th>
                <th className="px-2 py-2 text-right">最高</th>
                <th className="px-2 py-2 text-right">最低</th>
                <th className="px-2 py-2 text-right">成交量</th>
                <th className="px-2 py-2 text-right">MA5</th>
                <th className="px-2 py-2 text-right">MA10</th>
                <th className="px-2 py-2 text-right">MA20</th>
                <th className="px-2 py-2 text-right">RSI</th>
                <th className="px-2 py-2 text-right">5日</th>
                <th className="px-2 py-2 text-right">20日</th>
                <th className="px-2 py-2 text-right">偏离度</th>
                <th className="px-2 py-2 text-center">20日走势</th>
              </tr>
            </thead>
            <tbody>
              {loading && !watchlist ? (
                <tr><td colSpan={15} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>加载中...</td></tr>
              ) : sortedItems.length === 0 ? (
                <tr><td colSpan={15} className="text-center py-8" style={{ color: 'var(--text-muted)' }}>暂无数据</td></tr>
              ) : sortedItems.map(it => {
                const isUp = (it.change_pct || 0) > 0;
                const isDown = (it.change_pct || 0) < 0;
                return (
                  <tr key={it.code} style={{ borderBottom: '1px solid var(--border-color)' }}>
                    <td className="px-2 py-2">
                      <div className="font-bold">{it.name}</div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{it.code}</div>
                    </td>
                    <td className="px-2 py-2 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>
                      {fmtNum(it.price)}
                    </td>
                    <td className="px-2 py-2 text-right font-bold" style={{ color: pctColor(it.change_pct) }}>
                      {fmtPct(it.change_pct)}
                    </td>
                    <td className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtNum(it.open)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: UP_COLOR }}>{fmtNum(it.high)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: DOWN_COLOR }}>{fmtNum(it.low)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtVol(it.volume)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtNum(it.ma5)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtNum(it.ma10)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: 'var(--text-secondary)' }}>{fmtNum(it.ma20)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: it.rsi != null ? (it.rsi >= 70 ? DOWN_DARK : it.rsi <= 30 ? UP_DARK : 'var(--text-secondary)') : 'var(--text-muted)' }}>
                      {fmtNum(it.rsi)}
                    </td>
                    <td className="px-2 py-2 text-right" style={{ color: pctColor(it.change5d) }}>{fmtPct(it.change5d)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: pctColor(it.change20d) }}>{fmtPct(it.change20d)}</td>
                    <td className="px-2 py-2 text-right" style={{ color: pctColor(it.deviation) }}>
                      {it.deviation != null ? `${it.deviation > 0 ? '+' : ''}${fmtNum(it.deviation)}%` : '—'}
                    </td>
                    <td className="px-2 py-2 text-center">
                      <Sparkline data={it.sparkline} />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      <div className="mt-4 text-[11px]" style={{ color: 'var(--text-muted)' }}>
        💡 提示: 数据来自 Yahoo Finance API，需本地代理 (127.0.0.1:7897)。RSI ≥ 70 超买，≤ 30 超卖。偏离度 = (现价 - MA20) / MA20 × 100%。
      </div>
    </div>
  );
}
