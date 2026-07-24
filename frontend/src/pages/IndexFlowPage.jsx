/**
 * 指数资金流向 — 策略决策版
 *
 * 设计思路：
 * - 去散点图（占空间但对策略帮助小）
 * - 全宽单表：所有指数按净流入排序，红绿区分方向
 * - 1/3/5/10/22日维度全展示，一眼看清短期→中期趋势
 * - 趋势标签：根据多维度数据自动判定"持续流入/短期流入/持续流出/短期流出"
 * - 关键行高亮：连续流入/大额流入加背景色
 * - 模块标题：左色块 + 右结论标签
 * - 紧凑布局：减少 padding、边框、间距
 */
import { useState, useEffect, useMemo, useCallback } from 'react';
import { apiFetch } from '../utils/request';

export default function IndexFlowPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [sortBy, setSortBy] = useState('inflow_1d');
  const [sortDir, setSortDir] = useState('desc');
  const [filterDir, setFilterDir] = useState('all'); // all | inflow | outflow

  // 加载数据
  const loadRank = useCallback(async (force = false) => {
    setLoading(true);
    setError(null);
    const { ok, data: d, error: err } = await apiFetch(`/api/index-flow/rank${force ? '?force=1' : ''}`);
    if (ok) {
      setData(d);
      if (d?.error === 'data_source_unavailable') {
        setError(d.message || '数据源暂时不可用');
      }
    } else {
      setError(err || '加载失败');
    }
    setLoading(false);
  }, []);

  useEffect(() => { loadRank(); }, [loadRank]);

  // 亿元格式化
  const fmtYi = (v) => {
    if (v == null || isNaN(v)) return '—';
    return `${(v / 1e8).toFixed(1)}`;
  };

  const fmtDateCN = (iso) => {
    if (!iso || !/^\d{4}-\d{2}-\d{2}$/.test(iso)) return iso || '--';
    const [y, m, d] = iso.split('-').map(Number);
    return `${y}年${m}月${d}日`;
  };

  // 颜色
  const red = (v) => v >= 0 ? '#ef4444' : '#22c55e';
  const redBg = (v) => v >= 0 ? 'rgba(239,68,68,0.06)' : 'rgba(34,197,94,0.06)';

  // 趋势判定
  const getTrend = (item) => {
    const d1 = item.inflow_1d ?? 0;
    const d3 = item.inflow_3d ?? 0;
    const d5 = item.inflow_5d ?? 0;
    const d10 = item.inflow_10d ?? 0;

    if (d1 > 0 && d3 > 0 && d5 > 0 && d10 > 0) {
      return { label: '持续流入', color: '#ef4444', level: 3 };
    }
    if (d1 > 0 && d3 > 0 && d5 > 0) {
      return { label: '中期流入', color: '#ef4444', level: 2 };
    }
    if (d1 > 0 && d3 > 0) {
      return { label: '短期流入', color: '#f97316', level: 1 };
    }
    if (d1 > 0) {
      return { label: '今日流入', color: '#f59e0b', level: 0 };
    }
    if (d1 < 0 && d3 < 0 && d5 < 0 && d10 < 0) {
      return { label: '持续流出', color: '#22c55e', level: -3 };
    }
    if (d1 < 0 && d3 < 0 && d5 < 0) {
      return { label: '中期流出', color: '#22c55e', level: -2 };
    }
    if (d1 < 0 && d3 < 0) {
      return { label: '短期流出', color: '#3b82f6', level: -1 };
    }
    if (d1 < 0) {
      return { label: '今日流出', color: '#64748b', level: 0 };
    }
    return { label: '观望', color: '#94a3b8', level: 0 };
  };

  // 排序 + 过滤
  const sortedAll = useMemo(() => {
    if (!data?.indices) return [];
    const list = data.indices.map(item => ({ ...item, trend: getTrend(item) }));

    const dir = sortDir === 'desc' ? -1 : 1;
    list.sort((a, b) => {
      const va = a[sortBy] ?? 0;
      const vb = b[sortBy] ?? 0;
      return (va < vb ? -1 : va > vb ? 1 : 0) * dir;
    });

    if (filterDir === 'inflow') return list.filter(x => (x.inflow_1d ?? 0) >= 0);
    if (filterDir === 'outflow') return list.filter(x => (x.inflow_1d ?? 0) < 0);
    return list;
  }, [data, sortBy, sortDir, filterDir]);

  const handleSort = (key) => {
    if (sortBy === key) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(key);
      setSortDir('desc');
    }
  };

  const sortIcon = (key) => {
    if (sortBy !== key) return '⇅';
    return sortDir === 'desc' ? '↓' : '↑';
  };

  // 顶部结论
  const topStats = useMemo(() => {
    if (!data?.indices) return null;
    const indices = data.indices;
    const inflowCount = indices.filter(x => (x.inflow_1d ?? 0) >= 0).length;
    const outflowCount = indices.filter(x => (x.inflow_1d ?? 0) < 0).length;
    const topInflow = indices.reduce((best, cur) => {
      const c = cur.inflow_1d ?? 0;
      const b = best.inflow_1d ?? 0;
      return c > b ? cur : best;
    }, indices[0]);
    const topOutflow = indices.reduce((best, cur) => {
      const c = cur.inflow_1d ?? 0;
      const b = best.inflow_1d ?? 0;
      return c < b ? cur : best;
    }, indices[0]);
    return { inflowCount, outflowCount, topInflow, topOutflow };
  }, [data]);

  // 表格列定义
  const cols = [
    { key: 'name', name: '指数名称', align: 'left', w: '120px' },
    { key: 'pct_change', name: '涨跌', align: 'right', w: '55px' },
    { key: 'inflow_1d', name: '1日净流入', align: 'right', w: '70px' },
    { key: 'inflow_3d', name: '3日净流入', align: 'right', w: '70px' },
    { key: 'inflow_5d', name: '5日净流入', align: 'right', w: '70px' },
    { key: 'inflow_10d', name: '10日净流入', align: 'right', w: '75px' },
    { key: 'inflow_22d', name: '22日净流入', align: 'right', w: '75px' },
    { key: 'trend', name: '趋势', align: 'center', w: '65px', noSort: true },
  ];

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="w-5 h-5 border-2 rounded-full animate-spin" style={{ borderColor: '#3b82f6', borderTopColor: 'transparent' }} />
        <span className="ml-2 text-xs" style={{ color: 'var(--text-muted)' }}>加载指数资金流向数据...</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-lg p-3 text-xs" style={{ background: 'rgba(239,68,68,0.08)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.2)' }}>
        加载失败: {error}
        <button onClick={() => loadRank(true)} className="ml-2 px-2 py-0.5 rounded border text-[10px]" style={{ borderColor: '#ef4444', color: '#ef4444' }}>重试</button>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-2">
      {/* ===== 标题栏：左色块 + 右结论 ===== */}
      <div className="flex items-center justify-between px-2.5 py-2 rounded-lg" style={{ background: 'var(--bg-card)', border: '1px solid var(--border-color)' }}>
        <div className="flex items-center gap-2">
          <span className="text-xs font-bold px-1.5 py-0 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', borderLeft: '2px solid #3b82f6' }}>
            指数资金流向
          </span>
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
            {fmtDateCN(data.date)}
          </span>
        </div>
        {topStats && (
          <div className="flex items-center gap-2 text-[10px]">
            <span className="px-1.5 py-0.5 rounded font-bold" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.2)' }}>
              流入 {topStats.inflowCount}
            </span>
            <span className="px-1.5 py-0.5 rounded font-bold" style={{ background: 'rgba(34,197,94,0.1)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.2)' }}>
              流出 {topStats.outflowCount}
            </span>
            <span className="px-1.5 py-0.5 rounded font-bold truncate max-w-[140px]" style={{ background: 'rgba(239,68,68,0.08)', color: '#ef4444' }} title={`${topStats.topInflow?.name} +${fmtYi(topStats.topInflow?.inflow_1d)}亿`}>
              最强: {topStats.topInflow?.name} +{fmtYi(topStats.topInflow?.inflow_1d)}亿
            </span>
          </div>
        )}
      </div>

      {/* ===== 过滤按钮 ===== */}
      <div className="flex items-center gap-1.5 px-2.5">
        {[
          { key: 'all', label: '全部', count: data.indices?.length || 0 },
          { key: 'inflow', label: '流入', count: topStats?.inflowCount || 0 },
          { key: 'outflow', label: '流出', count: topStats?.outflowCount || 0 },
        ].map(f => (
          <button
            key={f.key}
            onClick={() => setFilterDir(f.key)}
            className="px-2 py-0.5 rounded text-[10px] font-bold transition-colors"
            style={{
              background: filterDir === f.key ? (f.key === 'inflow' ? 'rgba(239,68,68,0.12)' : f.key === 'outflow' ? 'rgba(34,197,94,0.12)' : 'rgba(59,130,246,0.12)') : 'transparent',
              color: filterDir === f.key ? (f.key === 'inflow' ? '#ef4444' : f.key === 'outflow' ? '#22c55e' : '#3b82f6') : 'var(--text-muted)',
              border: `1px solid ${filterDir === f.key ? (f.key === 'inflow' ? 'rgba(239,68,68,0.3)' : f.key === 'outflow' ? 'rgba(34,197,94,0.3)' : 'rgba(59,130,246,0.3)') : 'var(--border-color)'}`,
            }}
          >
            {f.label} {f.count}
          </button>
        ))}
        <div className="ml-auto text-[9px]" style={{ color: 'var(--text-muted)' }}>
          数据来源: {data.source === 'database' ? '数据库' : '数据库+东方财富'}
        </div>
      </div>

      {/* ===== 全宽数据表 ===== */}
      <div className="rounded-lg overflow-hidden" style={{ border: '1px solid var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="overflow-x-auto">
          <table className="w-full text-[10px]">
            <thead>
              <tr style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
                {cols.map(col => (
                  <th
                    key={col.key}
                    className={`px-1.5 py-1 font-medium whitespace-nowrap ${col.align === 'right' ? 'text-right' : col.align === 'center' ? 'text-center' : 'text-left'}`}
                    style={{ width: col.w, minWidth: col.w, cursor: col.noSort ? 'default' : 'pointer' }}
                    onClick={() => !col.noSort && handleSort(col.key)}
                  >
                    {col.name}
                    {!col.noSort && <span className="ml-0.5 opacity-50">{sortIcon(col.key)}</span>}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sortedAll.length === 0 ? (
                <tr>
                  <td colSpan={cols.length} className="px-2 py-4 text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    无数据
                  </td>
                </tr>
              ) : sortedAll.map((item) => {
                const isInflow = (item.inflow_1d ?? 0) >= 0;
                const trend = item.trend;
                const isStrong = trend.level >= 2 || trend.level <= -2;
                const pct = item.pct_change;

                return (
                  <tr
                    key={item.ts_code}
                    className="transition-colors"
                    style={{
                      borderTop: '1px solid var(--border-color)',
                      background: isStrong ? redBg(item.inflow_1d) : 'transparent',
                    }}
                  >
                    {/* 指数名称 */}
                    <td className="px-1.5 py-1 whitespace-nowrap">
                      <div className="font-bold" style={{ color: 'var(--text-primary)' }}>{item.name}</div>
                      <div className="text-[9px] font-mono" style={{ color: 'var(--text-muted)' }}>{item.ts_code}</div>
                    </td>

                    {/* 涨跌 */}
                    <td className="px-1.5 py-1 text-right font-mono font-bold" style={{ color: red(pct ?? 0) }}>
                      {pct != null ? `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%` : '—'}
                    </td>

                    {/* 1日净流入 */}
                    <td className="px-1.5 py-1 text-right font-mono font-bold" style={{ color: red(item.inflow_1d ?? 0) }}>
                      {fmtYi(item.inflow_1d)}
                    </td>

                    {/* 3日净流入 */}
                    <td className="px-1.5 py-1 text-right font-mono" style={{ color: red(item.inflow_3d ?? 0) }}>
                      {fmtYi(item.inflow_3d)}
                    </td>

                    {/* 5日净流入 */}
                    <td className="px-1.5 py-1 text-right font-mono" style={{ color: red(item.inflow_5d ?? 0) }}>
                      {fmtYi(item.inflow_5d)}
                    </td>

                    {/* 10日净流入 */}
                    <td className="px-1.5 py-1 text-right font-mono" style={{ color: red(item.inflow_10d ?? 0) }}>
                      {fmtYi(item.inflow_10d)}
                    </td>

                    {/* 22日净流入 */}
                    <td className="px-1.5 py-1 text-right font-mono" style={{ color: red(item.inflow_22d ?? 0) }}>
                      {fmtYi(item.inflow_22d)}
                    </td>

                    {/* 趋势标签 */}
                    <td className="px-1.5 py-1 text-center">
                      <span className="text-[9px] px-1 py-0 rounded font-bold whitespace-nowrap"
                        style={{ background: `${trend.color}14`, color: trend.color, border: `1px solid ${trend.color}30` }}>
                        {trend.label}
                      </span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>

      {/* ===== 底部说明 ===== */}
      <div className="px-2.5 text-[9px] flex items-center gap-3" style={{ color: 'var(--text-muted)' }}>
        <span>单位：亿元</span>
        <span>|</span>
        <span>趋势判定：1日/3日/5日/10日 均为正则持续流入</span>
        <span>|</span>
        <span>红色 = 净流入 / 上涨，绿色 = 净流出 / 下跌</span>
      </div>
    </div>
  );
}
