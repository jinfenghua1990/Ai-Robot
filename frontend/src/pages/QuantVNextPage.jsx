import { useEffect, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';

const DIMENSIONS = ['trend', 'strength', 'sector', 'volume_price', 'position', 'risk'];
const DIMENSION_NAMES = { trend: '趋势结构', strength: '个股强度', sector: '板块强度', volume_price: '量价资金', position: '交易位置', risk: '风险控制' };
const FACTOR_NAMES = { return_5d: '5日收益', return_20d: '20日收益', ma20_slope: '20日均线斜率', trend_alignment: '均线多头排列', breakout_strength: '突破强度', volume_ratio_20d: '20日量比', up_volume_ratio: '上涨量能比', atr_pct_14d: 'ATR波动率', distance_high_60d: '距60日高点', pullback_depth_20d: '20日回撤深度', sector_relative_20d: '板块相对强度', liquidity_amount_20d: '20日流动性' };
const CATEGORY_NAMES = { momentum: '动量', trend: '趋势', volume_price: '量价', volatility: '波动', position: '位置', sector: '板块', risk: '风险' };
const STATE_NAMES = { WATCH: '观察', READY: '准备', TRIGGERED: '已触发', HOLD: '持有', NO_CHASE: '不可追高', INVALID: '无效' };

export default function QuantVNextPage() {
  const [data, setData] = useState(null);
  const [research, setResearch] = useState(null);
  const [registry, setRegistry] = useState(null);
  const location = useLocation();
  const activeTab = new URLSearchParams(location.search).get('tab') || 'overview';
  const [error, setError] = useState('');

  useEffect(() => {
    fetch('/api/vnext/snapshots?limit=50')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`HTTP ${response.status}`)))
      .then(setData)
      .catch((reason) => setError(reason.message));
    fetch('/api/vnext/research?days=5&limit=10')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error(`research HTTP ${response.status}`)))
      .then(setResearch)
      .catch(() => {});
    fetch('/api/vnext/registry')
      .then((response) => response.ok ? response.json() : Promise.reject(new Error('registry unavailable')))
      .then(setRegistry)
      .catch(() => {});
  }, []);

  return (
    <div className="p-4 md:p-6 space-y-5" style={{ color: 'var(--text-primary)' }}>
      <div>
        <div className="text-xs tracking-[0.18em]" style={{ color: 'var(--text-muted)' }}>全新量化引擎</div>
        <h1 className="text-2xl font-semibold mt-2">右侧多因子选股系统</h1>
        <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>独立因子、独立证据共振、生命周期与交易状态分离。</p>
      </div>
      {error && <div className="rounded-lg border border-red-500/40 bg-red-500/10 p-4 text-red-300">{error}</div>}
      {!data && !error && <div style={{ color: 'var(--text-secondary)' }}>正在读取新系统快照…</div>}
      {data && <>
        <div className="flex flex-wrap gap-2">
          {[['overview', '总览'], ['factors', '因子注册'], ['research', '研究验证'], ['outcomes', '信号结果']].map(([key, label]) => <Link key={key} to={key === 'overview' ? '/quant-vnext' : `/quant-vnext?tab=${key}`} className={`rounded-md px-3 py-1.5 text-xs border ${activeTab === key ? 'font-semibold' : ''}`} style={{ borderColor: activeTab === key ? 'var(--accent-blue)' : 'var(--border-color)', color: activeTab === key ? 'var(--accent-blue)' : 'var(--text-secondary)' }}>{label}</Link>)}
        </div>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <Metric label="交易日" value={data.trade_date || '-'} />
          <Metric label="股票池" value={data.universe_count ?? 0} />
          <Metric label="市场宽度" value={`${((data.market?.breadth || 0) * 100).toFixed(1)}%`} />
          <Metric label="快照数" value={data.snapshots?.length ?? 0} />
        </div>
        {activeTab === 'factors' && registry && <div className="rounded-xl border overflow-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><table className="w-full text-sm"><thead style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}><tr><th className="text-left p-3">因子</th><th className="text-left p-3">分类</th><th className="text-left p-3">公式</th><th className="text-left p-3">方向</th><th className="text-left p-3">生产</th></tr></thead><tbody>{registry.factors.map((factor) => <tr key={factor.name} className="border-t" style={{ borderColor: 'var(--border-color)' }}><td className="p-3">{FACTOR_NAMES[factor.name] || factor.name}</td><td className="p-3">{CATEGORY_NAMES[factor.category] || factor.category}</td><td className="p-3 text-xs" style={{ color: 'var(--text-secondary)' }}>{factor.formula}</td><td className="p-3">{factor.direction > 0 ? '正向' : '反向'}</td><td className="p-3">{factor.production ? '是' : '否'}</td></tr>)}</tbody></table></div>}
        <div className="rounded-xl border overflow-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <table className="w-full text-sm">
            <thead style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}><tr>
              <th className="text-left p-3">股票</th><th className="text-left p-3">综合因子分</th>
              <th className="text-left p-3">共振</th><th className="text-left p-3">生命周期</th>
              <th className="text-left p-3">交易状态</th><th className="text-left p-3">维度</th>
            </tr></thead>
            <tbody>{(data.snapshots || []).map((item) => <tr key={item.ts_code} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
              <td className="p-3 font-medium">{item.name || '未命名'}<div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{item.ts_code} {item.sector ? `· ${item.sector}` : ''}</div></td>
              <td className="p-3">{item.factor_score == null ? '-' : item.factor_score.toFixed(2)}</td>
              <td className="p-3">{item.resonance?.count ?? 0} 个维度 / {item.resonance?.eligible ? '通过' : '未通过'}</td>
              <td className="p-3">{item.lifecycle}</td>
              <td className="p-3"><span className="rounded px-2 py-1 text-xs" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>{STATE_NAMES[item.trading_state] || item.trading_state}</span></td>
              <td className="p-3 min-w-[330px]"><div className="flex flex-wrap gap-1">{DIMENSIONS.map((name) => {
                const score = item.dimensions?.[name]?.score;
                return <span key={name} className="text-xs rounded px-2 py-1" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>{DIMENSION_NAMES[name]}：{score == null ? '无数据' : score.toFixed(0)}</span>;
              })}</div></td>
            </tr>)}</tbody>
          </table>
        </div>
        {research && <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h2 className="font-semibold">研究验证（严格日期截断）</h2>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mt-3">
            {[1, 3, 5, 10, 20].map((horizon) => {
              const item = research.horizons?.[String(horizon)] || {};
              return <div key={horizon} className="rounded-lg p-3" style={{ background: 'var(--bg-hover)' }}><div className="text-xs" style={{ color: 'var(--text-secondary)' }}>未来第 {horizon} 个交易日</div><div className="mt-1">收益 {item.mean == null ? '-' : `${(item.mean * 100).toFixed(2)}%`}</div><div className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>胜率 {item.win_rate == null ? '-' : `${(item.win_rate * 100).toFixed(1)}%`}</div></div>;
            })}
          </div>
        </div>}
      </>}
    </div>
  );
}

function Metric({ label, value }) {
  return <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}><div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{label}</div><div className="text-lg font-semibold mt-2">{value}</div></div>;
}
