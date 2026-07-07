import { useState, useEffect, useCallback } from 'react';
import { apiFetch } from '../utils/request';
import { formatMoney, formatProfit } from '../utils/format';
import { UP_COLOR, DOWN_COLOR } from '../utils/colors';

const ACTION_LABELS = { buy: '买入', sell: '卖出', skip: '跳过' };
const ACTION_COLORS = { buy: '#ef4444', sell: '#22c55e', skip: '#9ca3af' };
const STATUS_COLORS = { success: '#22c55e', failed: '#ef4444', skipped: '#9ca3af', pending: '#eab308' };

export default function MxTradingPage() {
  const [config, setConfig] = useState(null);
  const [signals, setSignals] = useState([]);
  const [logs, setLogs] = useState([]);
  const [balance, setBalance] = useState(null);
  const [positions, setPositions] = useState([]);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState(null);

  const fetchAll = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [cfgRes, sigRes, logRes, balRes, posRes] = await Promise.all([
        apiFetch('/api/auto-trade/config'),
        apiFetch('/api/auto-trade/signals'),
        apiFetch('/api/auto-trade/logs?limit=50'),
        apiFetch('/api/mx-trading/balance'),
        apiFetch('/api/mx-trading/positions'),
      ]);
      if (cfgRes.ok) setConfig(cfgRes.data);
      if (sigRes.ok) setSignals(sigRes.data.signals || []);
      if (logRes.ok) setLogs(logRes.data.logs || []);
      if (balRes.ok) setBalance(balRes.data);
      if (posRes.ok) setPositions(posRes.data.positions || []);
    } catch (e) {
      setError('数据加载失败: ' + e.message);
    }
    setLoading(false);
  }, []);

  useEffect(() => { fetchAll(); }, [fetchAll]);

  // 盘中5分钟轮询
  useEffect(() => {
    const now = new Date();
    const h = now.getHours() * 100 + now.getMinutes();
    const isTradingHours = (925 <= h && h <= 1130) || (1300 <= h && h <= 1500);
    const isWeekday = now.getDay() >= 1 && now.getDay() <= 5;
    if (!isTradingHours || !isWeekday) return;
    const timer = setInterval(fetchAll, 5 * 60 * 1000);
    return () => clearInterval(timer);
  }, [fetchAll]);

  const updateConfig = async (key, value) => {
    setConfig(prev => ({ ...prev, [key]: value }));
    const { ok, error } = await apiFetch('/api/auto-trade/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ [key]: value }),
    });
    if (!ok) setError('配置更新失败: ' + (error || ''));
  };

  const runOnce = async (dryRun) => {
    setRunning(true);
    setError(null);
    try {
      const { ok, data, error } = await apiFetch(`/api/auto-trade/run?dry_run=${dryRun}`, { method: 'POST' });
      if (!ok) {
        setError('执行失败: ' + (error || ''));
      } else {
        setLogs(data.logs || []);
      }
      fetchAll();
    } catch (e) {
      setError('执行异常: ' + e.message);
    }
    setRunning(false);
  };

  const fmtMoney = (v) => {
    const n = Number(v || 0);
    return n >= 10000 ? (n / 10000).toFixed(2) + '万' : n.toFixed(2);
  };

  if (loading && !config) {
    return <div className="flex items-center justify-center h-96 text-sm" style={{ color: 'var(--text-muted)' }}>加载中...</div>;
  }

  return (
    <div className="space-y-4 p-4">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          🤖 东财模拟盘 · 自动化交易
        </h2>
        <div className="flex gap-2">
          <button onClick={() => runOnce(true)} disabled={running}
            className="px-3 py-1.5 rounded-lg text-sm border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
            {running ? '执行中...' : '🔍 预览信号'}
          </button>
          <button onClick={() => runOnce(false)} disabled={running || !config?.enabled}
            className="px-3 py-1.5 rounded-lg text-sm text-white"
            style={{ background: config?.enabled ? '#ef4444' : '#6b7280', opacity: running || !config?.enabled ? 0.6 : 1 }}>
            {running ? '执行中...' : '⚡ 手动执行'}
          </button>
        </div>
      </div>

      {error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
          {error}
        </div>
      )}

      {/* 账户概览 */}
      {balance && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: '总资产', value: fmtMoney(balance.totalAssets), color: 'var(--text-primary)' },
            { label: '可用资金', value: fmtMoney(balance.availBalance), color: '#3b82f6' },
            { label: '持仓市值', value: fmtMoney(balance.totalPosValue), color: '#eab308' },
            { label: '总盈亏', value: fmtMoney(balance.totalAssets - balance.initMoney), color: (balance.totalAssets - balance.initMoney) >= 0 ? '#ef4444' : '#22c55e' },
          ].map(({ label, value, color }) => (
            <div key={label} className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
              <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>{label}</div>
              <div className="text-lg font-bold" style={{ color }}>{value}</div>
            </div>
          ))}
        </div>
      )}

      {/* 风控配置面板 */}
      {config && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚙️ 风控配置</h3>
            <label className="flex items-center gap-2 cursor-pointer">
              <span className="text-sm" style={{ color: config.enabled ? '#ef4444' : 'var(--text-muted)' }}>
                {config.enabled ? '🟢 自动交易已开启' : '⚪ 自动交易已关闭'}
              </span>
              <input type="checkbox" checked={config.enabled || false}
                onChange={(e) => updateConfig('enabled', e.target.checked)}
                className="w-4 h-4" />
            </label>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            {[
              { key: 'single_position_pct', label: '单票仓位上限(%)', step: 1, min: 1, max: 50 },
              { key: 'max_positions', label: '最大持仓数', step: 1, min: 1, max: 30 },
              { key: 'max_buy_count', label: '每日最多买入(只)', step: 1, min: 1, max: 50 },
              { key: 'buy_quantity', label: '每次买入股数', step: 100, min: 100, max: 100000 },
              { key: 'sell_quantity', label: '每次卖出股数', step: 100, min: 100, max: 100000 },
              { key: 'stop_loss_pct', label: '止损(%)', step: 0.5, min: -20, max: 0 },
              { key: 'take_profit_pct', label: '止盈(%)', step: 1, min: 5, max: 50 },
              { key: 'min_vote_score', label: '最小投票数', step: 1, min: 1, max: 6 },
            ].map(({ key, label, step, min, max }) => (
              <div key={key} className="flex items-center justify-between">
                <span style={{ color: 'var(--text-secondary)' }}>{label}</span>
                <input type="number" value={config[key] ?? ''} step={step} min={min} max={max}
                  onChange={(e) => updateConfig(key, parseFloat(e.target.value))}
                  className="w-24 px-2 py-1 rounded text-right border"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-main)', color: 'var(--text-primary)' }} />
              </div>
            ))}
            <div className="flex items-center justify-between">
              <span style={{ color: 'var(--text-secondary)' }}>市价委托</span>
              <input type="checkbox" checked={config.use_market_price || false}
                onChange={(e) => updateConfig('use_market_price', e.target.checked)}
                className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-2 text-xs" style={{ color: 'var(--text-muted)' }}>
            提示：开启后盘中每5分钟自动检查信号并下单。止盈止损优先于买入信号执行。
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* 当日信号预览 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            📊 当日聚合信号 ({signals.length})
          </h3>
          <div className="max-h-80 overflow-y-auto">
            {signals.length === 0 ? (
              <div className="text-sm text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无信号</div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ color: 'var(--text-muted)' }}>
                    <th className="text-left py-1">股票</th>
                    <th className="text-center">投票</th>
                    <th className="text-left">命中策略</th>
                  </tr>
                </thead>
                <tbody>
                  {signals.map((s, i) => (
                    <tr key={i} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="py-1">
                        <div style={{ color: 'var(--text-primary)' }}>{s.name || s.ts_code}</div>
                        <div style={{ color: 'var(--text-muted)' }}>{s.ts_code}</div>
                      </td>
                      <td className="text-center">
                        <span className="px-1.5 py-0.5 rounded font-bold" style={{ background: 'rgba(239,68,68,0.1)', color: '#ef4444' }}>
                          {s.vote_score}
                        </span>
                      </td>
                      <td className="text-left" style={{ color: 'var(--text-secondary)' }}>
                        {(s.strategies || []).join(' + ')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        {/* 交易日志 */}
        <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
            📝 交易日志 ({logs.length})
          </h3>
          <div className="max-h-80 overflow-y-auto">
            {logs.length === 0 ? (
              <div className="text-sm text-center py-4" style={{ color: 'var(--text-muted)' }}>暂无日志</div>
            ) : (
              <table className="w-full text-xs">
                <thead>
                  <tr style={{ color: 'var(--text-muted)' }}>
                    <th className="text-left py-1">时间</th>
                    <th className="text-left">股票</th>
                    <th className="text-center">动作</th>
                    <th className="text-left">原因</th>
                    <th className="text-center">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {logs.map((l) => (
                    <tr key={l.id} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                      <td className="py-1" style={{ color: 'var(--text-muted)' }}>{l.created_at?.slice(11) || ''}</td>
                      <td style={{ color: 'var(--text-primary)' }}>{l.ts_code}</td>
                      <td className="text-center">
                        <span style={{ color: ACTION_COLORS[l.action] || 'var(--text-muted)' }}>
                          {ACTION_LABELS[l.action] || l.action}
                        </span>
                      </td>
                      <td className="text-left" style={{ color: 'var(--text-secondary)', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {l.reason}
                      </td>
                      <td className="text-center">
                        <span style={{ color: STATUS_COLORS[l.status] || 'var(--text-muted)' }}>{l.status}</span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>

      {/* 持仓列表（字段与模拟盘 TradingPage 一致） */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <h3 className="text-sm font-bold mb-2" style={{ color: 'var(--text-primary)' }}>
          💼 持仓 ({positions.length})
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="text-left py-1">代码</th>
                <th className="text-left">名称</th>
                <th className="text-right">持仓</th>
                <th className="text-right">可用</th>
                <th className="text-right">成本</th>
                <th className="text-right">现价</th>
                <th className="text-right">市值</th>
                <th className="text-right">仓位%</th>
                <th className="text-right">当日盈亏</th>
                <th className="text-right">总盈亏</th>
                <th className="text-right">总盈亏%</th>
              </tr>
            </thead>
            <tbody>
              {positions.length === 0 ? (
                <tr>
                  <td colSpan={11} className="py-4 text-center" style={{ color: 'var(--text-muted)' }}>暂无持仓</td>
                </tr>
              ) : positions.map((p, i) => {
                const cost = parseFloat(p.costPrice || 0);
                const cur = parseFloat(p.price || 0);
                const count = parseInt(p.count || 0, 10);
                const availCount = parseInt(p.availCount || 0, 10);
                const value = parseFloat(p.value || 0);
                const posPct = parseFloat(p.posPct || 0);
                const dayProfit = parseFloat(p.dayProfit || 0);
                const profit = parseFloat(p.profit || 0);
                const profitPct = parseFloat(p.profitPct || 0);
                const dayProfitPct = parseFloat(p.dayProfitPct || 0);
                return (
                  <tr key={i} className="border-t" style={{ borderColor: 'var(--border-color)' }}>
                    <td className="py-1" style={{ color: 'var(--text-secondary)' }}>{p.secCode}</td>
                    <td style={{ color: 'var(--text-primary)' }}>{p.secName}</td>
                    <td className="text-right">{count}</td>
                    <td className="text-right" style={{ color: 'var(--text-muted)' }}>{availCount}</td>
                    <td className="text-right">{cost.toFixed(2)}</td>
                    <td className="text-right">{cur.toFixed(2)}</td>
                    <td className="text-right">{formatMoney(value)}</td>
                    <td className="text-right">{posPct.toFixed(1)}%</td>
                    <td className="text-right font-bold" style={{ color: dayProfitPct >= 0 ? UP_COLOR : DOWN_COLOR }}>
                      {formatProfit(dayProfit)} ({dayProfitPct >= 0 ? '+' : ''}{dayProfitPct.toFixed(2)}%)
                    </td>
                    <td className="text-right font-bold" style={{ color: profit >= 0 ? UP_COLOR : DOWN_COLOR }}>
                      {formatProfit(profit)}
                    </td>
                    <td className="text-right font-bold" style={{ color: profitPct >= 0 ? UP_COLOR : DOWN_COLOR }}>
                      {profitPct >= 0 ? '+' : ''}{profitPct.toFixed(2)}%
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
