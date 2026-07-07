import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

// 4 档配置（与 MainForcePanel 保持一致）
const TIERS = [
  { key: 'super_large', label: '特大单', color: '#dc2626' },
  { key: 'large', label: '大单', color: '#f59e0b' },
  { key: 'small', label: '小单', color: '#10b981' },
  { key: 'tiny', label: '散单', color: '#3b82f6' },
];

const fmtWan = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 10000) return (n / 10000).toFixed(2) + '亿';
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(2) + '千万';
  return n.toFixed(2) + '万';
};

// 一行：4 档迷你水平柱状图(以 0 轴为中心)
function MiniTierBars({ row }) {
  const max = Math.max(...TIERS.map(t => Math.abs(row[t.key] || 0)), 1);
  return (
    <div className="flex items-center gap-1" style={{ minWidth: 120 }}>
      {TIERS.map(t => {
        const v = row[t.key] || 0;
        const w = Math.abs(v) / max * 50;
        return (
          <div key={t.key} className="flex flex-col items-center" title={`${t.label}: ${v >= 0 ? '+' : ''}${fmtWan(v)}`}>
            <div className="text-[9px] tabular-nums" style={{ color: v >= 0 ? '#dc2626' : '#22c55e' }}>
              {v >= 0 ? '+' : ''}{fmtWan(v)}
            </div>
            <div className="h-1.5 w-12 rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.15)' }}>
              <div
                className="h-full"
                style={{
                  width: `${w}%`,
                  background: t.color,
                  marginLeft: v < 0 ? `${50 - w}%` : '50%',
                }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

// 单股 4 档柱状图（无饼图）
function MainForcePanel({ data, compact = false }) {
  const cur = data.current;
  const recent = data.recent_5d || [];

  const maxAbs = Math.max(
    ...TIERS.map(t => Math.abs(cur[t.key] || 0)),
    1
  );

  // 操作建议
  const mainNet = cur.main_net || 0;
  let signal, sigColor, sigBg;
  if (mainNet > 5000) {
    signal = '主力大幅流入';
    sigColor = '#dc2626';
    sigBg = 'rgba(220,38,38,0.15)';
  } else if (mainNet > 1000) {
    signal = '主力小幅流入';
    sigColor = '#f59e0b';
    sigBg = 'rgba(245,158,11,0.15)';
  } else if (mainNet < -5000) {
    signal = '主力大幅流出';
    sigColor = '#22c55e';
    sigBg = 'rgba(34,197,94,0.15)';
  } else if (mainNet < -1000) {
    signal = '主力小幅流出';
    sigColor = '#16a34a';
    sigBg = 'rgba(34,197,94,0.12)';
  } else {
    signal = '主力观望';
    sigColor = '#6b7280';
    sigBg = 'rgba(107,114,128,0.12)';
  }

  const retailNet = cur.retail_net || 0;

  return (
    <div className="space-y-2.5">
      {/* 头部：日期 + 状态徽章 */}
      <div className="flex items-center justify-between flex-wrap gap-1.5">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          💰 4 档资金流 · {cur.trade_date?.slice(0, 4)}-{cur.trade_date?.slice(4, 6)}-{cur.trade_date?.slice(6, 8)}
        </h3>
        <div
          className="px-2 py-0.5 rounded text-[10px] font-medium"
          style={{ background: sigBg, color: sigColor }}
        >
          {signal}
        </div>
      </div>

      {/* 4 档柱状图 */}
      <div className="grid grid-cols-4 gap-2 items-end" style={{ height: compact ? 110 : 140 }}>
        {TIERS.map(t => {
          const v = cur[t.key] || 0;
          const isPositive = v >= 0;
          const heightPct = Math.abs(v) / maxAbs * 100;
          return (
            <div key={t.key} className="flex flex-col items-center gap-1 h-full">
              <div className="text-[10px] font-semibold tabular-nums" style={{ color: isPositive ? '#dc2626' : '#22c55e' }}>
                {isPositive ? '+' : ''}{fmtWan(v)}
              </div>
              <div className="w-full flex flex-col items-center justify-end" style={{ height: compact ? 70 : 90, position: 'relative' }}>
                <div style={{ position: 'absolute', top: '50%', width: '100%', borderTop: '1px dashed var(--border-color)' }} />
                {isPositive && (
                  <div
                    style={{
                      width: '60%',
                      height: `${heightPct / 2}%`,
                      background: t.color,
                      borderRadius: '2px 2px 0 0',
                      marginBottom: '50%',
                    }}
                    title={`${t.label}: +${fmtWan(v)}`}
                  />
                )}
                {!isPositive && (
                  <div
                    style={{
                      width: '60%',
                      height: `${heightPct / 2}%`,
                      background: t.color,
                      borderRadius: '0 0 2px 2px',
                      marginTop: '50%',
                      opacity: 0.7,
                    }}
                    title={`${t.label}: ${fmtWan(v)}`}
                  />
                )}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{t.label}</div>
            </div>
          );
        })}
      </div>

      {/* 主力 vs 散户 */}
      <div className="grid grid-cols-2 gap-2">
        <div
          className="rounded-lg p-2"
          style={{
            background: mainNet >= 0 ? 'rgba(220,38,38,0.08)' : 'rgba(34,197,94,0.08)',
            border: `1px solid ${mainNet >= 0 ? 'rgba(220,38,38,0.3)' : 'rgba(34,197,94,0.3)'}`,
          }}
        >
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>主力净流入</div>
          <div className="text-base font-bold tabular-nums" style={{ color: mainNet >= 0 ? '#dc2626' : '#22c55e' }}>
            {mainNet >= 0 ? '+' : ''}{fmtWan(mainNet)}
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            买 {fmtWan(cur.main_buy)} / 卖 {fmtWan(cur.main_sell)}
          </div>
        </div>
        <div
          className="rounded-lg p-2"
          style={{
            background: retailNet >= 0 ? 'rgba(220,38,38,0.08)' : 'rgba(34,197,94,0.08)',
            border: `1px solid ${retailNet >= 0 ? 'rgba(220,38,38,0.3)' : 'rgba(34,197,94,0.3)'}`,
          }}
        >
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>散户净流入</div>
          <div className="text-base font-bold tabular-nums" style={{ color: retailNet >= 0 ? '#dc2626' : '#22c55e' }}>
            {retailNet >= 0 ? '+' : ''}{fmtWan(retailNet)}
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            换手 {cur.turnover_rate?.toFixed(2)}%
          </div>
        </div>
      </div>

      {/* 近 5 日主力净流入趋势 */}
      {recent.length > 1 && (
        <div>
          <div className="text-[10px] font-medium mb-1" style={{ color: 'var(--text-secondary)' }}>
            📈 近 {recent.length} 日主力净流入(亿)
          </div>
          <div className="flex items-end gap-1" style={{ height: 60 }}>
            {recent.slice().reverse().map((d) => {
              const v = d.main_net || 0;
              const maxV = Math.max(...recent.map(x => Math.abs(x.main_net || 0)), 1);
              const h = Math.abs(v) / maxV * 60;
              const isPos = v >= 0;
              return (
                <div key={d.trade_date} className="flex-1 flex flex-col items-center gap-0.5" style={{ height: '100%' }}>
                  <div className="text-[9px] tabular-nums" style={{ color: isPos ? '#dc2626' : '#22c55e' }}>
                    {v >= 0 ? '+' : ''}{(v / 10000).toFixed(2)}
                  </div>
                  <div className="w-full flex items-center justify-center" style={{ height: 50, position: 'relative' }}>
                    <div style={{ position: 'absolute', top: 25, width: '100%', borderTop: '1px dashed var(--border-color)' }} />
                    {isPos ? (
                      <div style={{ width: '70%', height: `${h / 2}%`, background: '#dc2626', borderRadius: '1px 1px 0 0', marginBottom: '50%' }} />
                    ) : (
                      <div style={{ width: '70%', height: `${h / 2}%`, background: '#22c55e', borderRadius: '0 0 1px 1px', marginTop: '50%', opacity: 0.7 }} />
                    )}
                  </div>
                  <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>
                    {d.trade_date?.slice(4, 6)}-{d.trade_date?.slice(6, 8)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

export default function WatchlistFlowPage() {
  const navigate = useNavigate();
  const [watchlist, setWatchlist] = useState(null);
  const [flowData, setFlowData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [selectedCode, setSelectedCode] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [filter, setFilter] = useState('all'); // all | inflow | outflow

  // 1. 加载自选股列表
  useEffect(() => {
    (async () => {
      const { ok, data } = await apiFetch('/api/watchlist');
      if (ok) {
        setWatchlist(data);
        // 默认选中主力净流入第一名
        if (data?.signals?.length && !selectedCode) {
          setSelectedCode(data.signals[0].secCode);
        }
      } else {
        setWatchlist({ signals: [] });
      }
    })();
  }, []);

  // 2. 加载自选股资金流(批量)
  useEffect(() => {
    if (!watchlist?.signals?.length) return;
    const codes = watchlist.signals.map(s => s.secCode).join(',');
    (async () => {
      setLoading(true);
      const { ok, data } = await apiFetch(`/api/watchlist/money-flow?codes=${codes}`);
      if (ok) setFlowData(data);
      setLoading(false);
    })();
  }, [watchlist?.signals?.length]);

  // 3. 加载选中个股的4档资金流详情
  useEffect(() => {
    if (!selectedCode) return;
    (async () => {
      setDetailLoading(true);
      const { ok, data } = await apiFetch(`/api/stock/${selectedCode}/money-flow-detail`);
      if (ok) setDetailData(data);
      setDetailLoading(false);
    })();
  }, [selectedCode]);

  // 排行表:把 watchlist + moneyflow 合并
  const rows = useMemo(() => {
    if (!flowData?.rows) return [];
    let arr = flowData.rows.map(r => ({
      ...r,
      // 转换 main_net 为显示用
      isInflow: r.main_net > 0,
      isOutflow: r.main_net < 0,
    }));
    if (filter === 'inflow') arr = arr.filter(r => r.main_net > 0);
    else if (filter === 'outflow') arr = arr.filter(r => r.main_net < 0);
    return arr;
  }, [flowData, filter]);

  // 统计
  const stats = useMemo(() => {
    if (!flowData?.rows) return { total: 0, inflow: 0, outflow: 0, totalMainNet: 0 };
    const arr = flowData.rows;
    return {
      total: arr.length,
      inflow: arr.filter(r => r.main_net > 0).length,
      outflow: arr.filter(r => r.main_net < 0).length,
      totalMainNet: arr.reduce((s, r) => s + (r.main_net || 0), 0),
    };
  }, [flowData]);

  return (
    <div className="space-y-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-primary)' }}>
          <span>💸 自选股资金流</span>
          {flowData?.trade_date && (
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7' }}>
              {flowData.trade_date.slice(0, 4)}-{flowData.trade_date.slice(4, 6)}-{flowData.trade_date.slice(6, 8)}
            </span>
          )}
        </h2>
        <button
          onClick={() => navigate('/watchlist')}
          className="px-2.5 py-1 rounded-lg border text-xs"
          style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
        >
          ← 返回自选股
        </button>
      </div>

      {/* 顶部统计卡 */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>自选股总数</div>
          <div className="text-xl font-bold mt-0.5" style={{ color: 'var(--text-primary)' }}>{stats.total}</div>
        </div>
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(220,38,38,0.3)', background: 'rgba(220,38,38,0.05)' }}>
          <div className="text-[10px]" style={{ color: '#dc2626' }}>主力净流入</div>
          <div className="text-xl font-bold mt-0.5 tabular-nums" style={{ color: '#dc2626' }}>{stats.inflow}</div>
        </div>
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'rgba(34,197,94,0.3)', background: 'rgba(34,197,94,0.05)' }}>
          <div className="text-[10px]" style={{ color: '#22c55e' }}>主力净流出</div>
          <div className="text-xl font-bold mt-0.5 tabular-nums" style={{ color: '#22c55e' }}>{stats.outflow}</div>
        </div>
        <div className="rounded-xl border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>合计主力净流入</div>
          <div className="text-xl font-bold mt-0.5 tabular-nums" style={{ color: stats.totalMainNet >= 0 ? '#dc2626' : '#22c55e' }}>
            {stats.totalMainNet >= 0 ? '+' : ''}{fmtWan(stats.totalMainNet)}
          </div>
        </div>
      </div>

      {/* 过滤栏 */}
      <div className="flex items-center gap-1.5 flex-wrap">
        {[
          { key: 'all', label: '全部', color: '#a855f7' },
          { key: 'inflow', label: '净流入', color: '#dc2626' },
          { key: 'outflow', label: '净流出', color: '#22c55e' },
        ].map(f => {
          const active = filter === f.key;
          return (
            <button
              key={f.key}
              onClick={() => setFilter(f.key)}
              className="px-2.5 py-1 rounded-lg text-xs font-medium transition-all"
              style={{
                background: active ? `${f.color}25` : 'transparent',
                color: active ? f.color : 'var(--text-secondary)',
                border: `1px solid ${active ? f.color : 'var(--border-color)'}`,
              }}
            >
              {f.label}
            </button>
          );
        })}
        <span className="text-[10px] ml-auto" style={{ color: 'var(--text-muted)' }}>
          💡 点击个股行查看 4 档柱状图详情
        </span>
      </div>

      {/* 排行表 */}
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-2 border-b text-xs font-bold" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
          📊 主力净流入排行（按金额降序）
        </div>
        {loading ? (
          <div className="p-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>
        ) : rows.length === 0 ? (
          <div className="p-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>暂无数据</div>
        ) : (
          <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
            {rows.map((r, i) => {
              const active = selectedCode === r.secCode;
              return (
                <div
                  key={r.ts_code}
                  onClick={() => setSelectedCode(r.secCode)}
                  className="px-3 py-2 cursor-pointer transition-all flex items-center gap-3"
                  style={{
                    background: active ? 'rgba(168,85,247,0.1)' : 'transparent',
                    borderLeft: active ? '3px solid #a855f7' : '3px solid transparent',
                  }}
                >
                  {/* 排名 */}
                  <div
                    className="w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold flex-shrink-0"
                    style={{
                      background: i < 3 ? '#a855f7' : 'rgba(107,114,128,0.2)',
                      color: i < 3 ? '#fff' : 'var(--text-muted)',
                    }}
                  >
                    {i + 1}
                  </div>
                  {/* 股票名+代码 */}
                  <div className="min-w-0 flex-shrink-0" style={{ width: 110 }}>
                    <div className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>{r.name}</div>
                    <div className="text-[10px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{r.sec_code || r.ts_code?.split('.')[0]}</div>
                  </div>
                  {/* 主力净流入 */}
                  <div className="flex-shrink-0 text-right" style={{ width: 90 }}>
                    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>主力净流入</div>
                    <div className="text-sm font-bold tabular-nums" style={{ color: r.main_net >= 0 ? '#dc2626' : '#22c55e' }}>
                      {r.main_net >= 0 ? '+' : ''}{fmtWan(r.main_net)}
                    </div>
                  </div>
                  {/* 4 档迷你柱状图 */}
                  <div className="flex-1 min-w-0">
                    <MiniTierBars row={r} />
                  </div>
                  {/* 换手率 */}
                  <div className="flex-shrink-0 text-right hidden md:block" style={{ width: 60 }}>
                    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>换手</div>
                    <div className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)' }}>{(r.turnover_rate || 0).toFixed(2)}%</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 单股详情面板 */}
      {selectedCode && (
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-2 flex-wrap gap-1.5">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              🔍 单股详情 · {rows.find(r => r.sec_code === selectedCode || r.ts_code?.startsWith(selectedCode))?.name || selectedCode}
            </h3>
            <button
              onClick={() => navigate(`/stock/${selectedCode}`)}
              className="px-2 py-0.5 rounded text-[10px]"
              style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
              title="跳转到个股详情页"
            >
              查看完整详情 →
            </button>
          </div>
          {detailLoading ? (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-muted)' }}>加载单股资金流...</div>
          ) : detailData?.available ? (
            <MainForcePanel data={detailData} />
          ) : (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-muted)' }}>
              {detailData?.message || '暂无 4 档资金流数据'}
            </div>
          )}
        </div>
      )}

      {/* 底部说明 */}
      <div className="text-[10px] text-right" style={{ color: 'var(--text-muted)' }}>
        数据源: Tushare moneyflow · 每日 17:30 自动更新 · 单位:万元
      </div>
    </div>
  );
}
