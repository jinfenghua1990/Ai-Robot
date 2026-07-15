import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

const fmtWan = (v) => {
  const n = Number(v || 0);
  if (Math.abs(n) >= 100000000) return (n / 100000000).toFixed(2) + '亿';
  if (Math.abs(n) >= 10000) return (n / 10000).toFixed(0) + '万';
  return n.toFixed(0);
};

const fmtYi = (v) => {
  const n = Number(v || 0);
  return (n / 100000000).toFixed(2) + '亿';
};

// 迷你资金流横条（主力/散户）
function MiniFlowBar({ row }) {
  const mainNet = row.main_net || 0;
  const retailNet = row.retail_net || 0;
  const maxAbs = Math.max(Math.abs(mainNet), Math.abs(retailNet), 1);
  const maxW = 50;

  return (
    <div className="flex items-center gap-2" style={{ minWidth: 140 }}>
      <div className="flex flex-col items-center flex-1">
        <div className="text-[10px] tabular-nums" style={{ color: mainNet >= 0 ? '#dc2626' : '#22c55e' }}>
          主力 {mainNet >= 0 ? '+' : ''}{fmtYi(mainNet)}
        </div>
        <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.15)' }}>
          <div className="h-full rounded-full" style={{
            width: `${Math.abs(mainNet) / maxAbs * maxW}%`,
            background: mainNet >= 0 ? '#dc2626' : '#22c55e',
            marginLeft: mainNet < 0 ? `${maxW - Math.abs(mainNet) / maxAbs * maxW}%` : '50%',
          }} />
        </div>
      </div>
      <div className="flex flex-col items-center flex-1">
        <div className="text-[10px] tabular-nums" style={{ color: retailNet >= 0 ? '#dc2626' : '#22c55e' }}>
          散户 {retailNet >= 0 ? '+' : ''}{fmtYi(retailNet)}
        </div>
        <div className="h-1.5 w-full rounded-full overflow-hidden" style={{ background: 'rgba(107,114,128,0.15)' }}>
          <div className="h-full rounded-full" style={{
            width: `${Math.abs(retailNet) / maxAbs * maxW}%`,
            background: retailNet >= 0 ? '#dc2626' : '#22c55e',
            marginLeft: retailNet < 0 ? `${maxW - Math.abs(retailNet) / maxAbs * maxW}%` : '50%',
          }} />
        </div>
      </div>
    </div>
  );
}

// 主力/散户柱状图详情（替代原来的4档图）
function MainForcePanel({ data, compact = false }) {
  const { main_buy, main_sell, main_net, retail_buy, retail_sell, retail_net, turnover, name } = data;
  const mn = main_net || 0;
  const rn = retail_net || 0;

  let signal, sigColor, sigBg;
  if (mn > 50000000) {
    signal = '主力大幅流入'; sigColor = '#dc2626'; sigBg = 'rgba(220,38,38,0.15)';
  } else if (mn > 10000000) {
    signal = '主力小幅流入'; sigColor = '#f59e0b'; sigBg = 'rgba(245,158,11,0.15)';
  } else if (mn < -50000000) {
    signal = '主力大幅流出'; sigColor = '#22c55e'; sigBg = 'rgba(34,197,94,0.15)';
  } else if (mn < -10000000) {
    signal = '主力小幅流出'; sigColor = '#16a34a'; sigBg = 'rgba(34,197,94,0.12)';
  } else {
    signal = '主力观望'; sigColor = '#6b7280'; sigBg = 'rgba(107,114,128,0.12)';
  }

  const maxVal = Math.max(Math.abs(mn), Math.abs(rn), 1);

  return (
    <div className="space-y-3">
      {/* 头部 */}
      <div className="flex items-center justify-between flex-wrap gap-1.5">
        <h3 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
          💰 {name} 资金流向
        </h3>
        <div className="px-2 py-0.5 rounded text-[10px] font-medium" style={{ background: sigBg, color: sigColor }}>
          {signal}
        </div>
      </div>

      {/* 主力/散户柱状对比 */}
      <div className="grid grid-cols-2 gap-4 items-end" style={{ height: compact ? 110 : 140 }}>
        {[
          { label: '主力', val: mn, buy: main_buy, sell: main_sell, color: '#dc2626' },
          { label: '散户', val: rn, buy: retail_buy, sell: retail_sell, color: '#22c55e' },
        ].map(item => {
          const isPos = item.val >= 0;
          const hPct = Math.abs(item.val) / maxVal * 100;
          return (
            <div key={item.label} className="flex flex-col items-center gap-1 h-full">
              <div className="text-[10px] font-semibold tabular-nums" style={{ color: isPos ? '#dc2626' : '#22c55e' }}>
                {isPos ? '+' : ''}{fmtYi(item.val)}
              </div>
              <div className="w-full flex flex-col items-center justify-end" style={{ height: compact ? 70 : 90, position: 'relative' }}>
                <div style={{ position: 'absolute', top: '50%', width: '100%', borderTop: '1px dashed var(--border-color)' }} />
                {isPos ? (
                  <div style={{ width: '60%', height: `${hPct / 2}%`, background: item.color, borderRadius: '2px 2px 0 0', marginBottom: '50%' }} />
                ) : (
                  <div style={{ width: '60%', height: `${hPct / 2}%`, background: item.color, borderRadius: '0 0 2px 2px', marginTop: '50%', opacity: 0.7 }} />
                )}
              </div>
              <div className="text-[10px]" style={{ color: 'var(--text-secondary)' }}>{item.label}</div>
            </div>
          );
        })}
      </div>

      {/* 主力/散户卡片 */}
      <div className="grid grid-cols-2 gap-2">
        <div className="rounded-lg p-2" style={{
          background: mn >= 0 ? 'rgba(220,38,38,0.08)' : 'rgba(34,197,94,0.08)',
          border: `1px solid ${mn >= 0 ? 'rgba(220,38,38,0.3)' : 'rgba(34,197,94,0.3)'}`,
        }}>
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>主力净流入</div>
          <div className="text-base font-bold tabular-nums" style={{ color: mn >= 0 ? '#dc2626' : '#22c55e' }}>
            {mn >= 0 ? '+' : ''}{fmtYi(mn)}
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            买 {fmtYi(main_buy || 0)} / 卖 {fmtYi(main_sell || 0)}
          </div>
        </div>
        <div className="rounded-lg p-2" style={{
          background: rn >= 0 ? 'rgba(220,38,38,0.08)' : 'rgba(34,197,94,0.08)',
          border: `1px solid ${rn >= 0 ? 'rgba(220,38,38,0.3)' : 'rgba(34,197,94,0.3)'}`,
        }}>
          <div className="text-[10px] mb-1" style={{ color: 'var(--text-muted)' }}>散户净流入</div>
          <div className="text-base font-bold tabular-nums" style={{ color: rn >= 0 ? '#dc2626' : '#22c55e' }}>
            {rn >= 0 ? '+' : ''}{fmtYi(rn)}
          </div>
          <div className="text-[10px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
            买 {fmtYi(retail_buy || 0)} / 卖 {fmtYi(retail_sell || 0)}
          </div>
        </div>
      </div>
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
  const [filter, setFilter] = useState('all');

  // 1. 加载自选股列表
  useEffect(() => {
    (async () => {
      const { ok, data } = await apiFetch('/api/watchlist');
      if (ok) {
        setWatchlist(data);
        if (data?.signals?.length && !selectedCode) {
          setSelectedCode(data.signals[0].secCode);
        }
      } else {
        setWatchlist({ signals: [] });
      }
    })();
  }, []);

  // 2. 加载自选股实时资金流(emdatah5 批量)
  useEffect(() => {
    if (!watchlist?.signals?.length) return;
    const codes = watchlist.signals.map(s => s.secCode).join(',');
    (async () => {
      setLoading(true);
      const { ok, data } = await apiFetch(`/api/watchlist/realtime-flow-batch?codes=${codes}`);
      if (ok) setFlowData(data);
      setLoading(false);
    })();
  }, [watchlist?.signals?.length]);

  // 3. 加载选中个股的实时资金流详情(emdatah5)
  useEffect(() => {
    if (!selectedCode) return;
    (async () => {
      setDetailLoading(true);
      const { ok, data } = await apiFetch(`/api/watchlist/realtime-flow/${selectedCode}`);
      if (ok) setDetailData(data);
      setDetailLoading(false);
    })();
  }, [selectedCode]);

  // 排行表: 把 watchlist + realtime flow 合并
  const rows = useMemo(() => {
    if (!flowData?.data) return [];
    const fm = flowData.data;
    const list = watchlist?.signals || [];
    let arr = list.map(s => {
      const d = fm[s.secCode];
      return {
        secCode: s.secCode,
        name: s.name || s.secCode,
        ts_code: d?.ts_code || s.secCode,
        main_net: d?.main_net || 0,
        retail_net: d?.retail_net || 0,
        main_buy: d?.main_buy || 0,
        main_sell: d?.main_sell || 0,
        retail_buy: d?.retail_buy || 0,
        retail_sell: d?.retail_sell || 0,
        turnover: d?.turnover || 0,
        available: d?.available || false,
      };
    });
    // 按主力净流入排序
    arr.sort((a, b) => b.main_net - a.main_net);
    if (filter === 'inflow') arr = arr.filter(r => r.main_net > 0);
    else if (filter === 'outflow') arr = arr.filter(r => r.main_net < 0);
    return arr;
  }, [flowData, watchlist, filter]);

  // 统计
  const stats = useMemo(() => {
    const arr = rows;
    return {
      total: arr.length,
      inflow: arr.filter(r => r.main_net > 0).length,
      outflow: arr.filter(r => r.main_net < 0).length,
      totalMainNet: arr.reduce((s, r) => s + (r.main_net || 0), 0),
    };
  }, [rows]);

  return (
    <div className="space-y-3">
      {/* 标题栏 */}
      <div className="flex items-center justify-between flex-wrap gap-2">
        <h2 className="text-xl font-bold flex items-center gap-2 flex-wrap" style={{ color: 'var(--text-primary)' }}>
          <span>💸 自选股实时资金流</span>
          {flowData?.success && (
            <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6' }}>
              东方财富 L2
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
            {stats.totalMainNet >= 0 ? '+' : ''}{fmtYi(stats.totalMainNet)}
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
          💡 点击个股行查看详情
        </span>
      </div>

      {/* 排行表 */}
      <div className="rounded-xl border" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="px-3 py-2 border-b text-xs font-bold" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
          📊 主力净流入排行（按金额降序 · 东方财富 L2 口径）
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
                  {/* 股票名 */}
                  <div className="min-w-0 flex-shrink-0" style={{ width: 90 }}>
                    <div className="text-sm font-medium truncate" style={{ color: 'var(--text-primary)' }}>{r.name}</div>
                    <div className="text-[10px] tabular-nums" style={{ color: 'var(--text-muted)' }}>{r.secCode}</div>
                  </div>
                  {/* 主力净流入 */}
                  <div className="flex-shrink-0 text-right" style={{ width: 100 }}>
                    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>主力净流入</div>
                    <div className="text-sm font-bold tabular-nums" style={{ color: r.main_net >= 0 ? '#dc2626' : '#22c55e' }}>
                      {r.main_net >= 0 ? '+' : ''}{fmtYi(r.main_net)}
                    </div>
                  </div>
                  {/* 迷你资金流横条 */}
                  <div className="flex-1 min-w-0">
                    {r.available ? <MiniFlowBar row={r} /> : <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>无数据</span>}
                  </div>
                  {/* 散户净额 */}
                  <div className="flex-shrink-0 text-right hidden md:block" style={{ width: 80 }}>
                    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>散户</div>
                    <div className="text-xs tabular-nums" style={{ color: r.retail_net >= 0 ? '#dc2626' : '#22c55e' }}>
                      {r.retail_net >= 0 ? '+' : ''}{fmtYi(r.retail_net)}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* 单股详情面板 */}
      {selectedCode && detailData?.data && (
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-2 flex-wrap gap-1.5">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              🔍 单股详情 · {rows.find(r => r.secCode === selectedCode)?.name || selectedCode}
            </h3>
            <button
              onClick={() => navigate(`/stock/${selectedCode}`)}
              className="px-2 py-0.5 rounded text-[10px]"
              style={{ background: 'rgba(168,85,247,0.1)', color: '#a855f7', border: '1px solid rgba(168,85,247,0.3)' }}
            >
              查看完整详情 →
            </button>
          </div>
          {detailLoading ? (
            <div className="text-center py-6 text-sm" style={{ color: 'var(--text-muted)' }}>加载单股资金流...</div>
          ) : (
            <MainForcePanel data={detailData.data} />
          )}
        </div>
      )}

      {/* 底部说明 */}
      <div className="text-[10px] text-right space-x-2" style={{ color: 'var(--text-muted)' }}>
        <span>数据源: 东方财富 L2 逐笔（展示用）</span>
        <span>|</span>
        <span>Tushare（策略回测用）</span>
      </div>
    </div>
  );
}
