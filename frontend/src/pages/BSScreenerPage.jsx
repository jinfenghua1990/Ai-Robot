import { useState, useEffect, useCallback, useRef } from 'react';
import SignalCard from '../components/trading/SignalCard';
import StrategyOverview from '../components/bs-screener/StrategyOverview';
import { DEFAULT_BS_PARAMS, SIGNAL_TYPES } from '../components/bs-screener/constants';
import * as echarts from 'echarts';
import { apiFetch } from '../utils/request';
import { TOAST_DURATION } from '../utils/constants';

export default function BSScreenerPage() {
  const [params, setParams] = useState(DEFAULT_BS_PARAMS);
  const [signals, setSignals] = useState(null);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState(null);
  const [toast, setToast] = useState(null);
  const [showConfig, setShowConfig] = useState(true);

  // 策略保存/加载
  const [strategies, setStrategies] = useState([]);
  const [strategyName, setStrategyName] = useState('');
  const [showStrategyPanel, setShowStrategyPanel] = useState(false);

  // 回测
  const [showBacktest, setShowBacktest] = useState(false);
  const [backtestParams, setBacktestParams] = useState({
    start_date: new Date(Date.now() - 180 * 86400000).toISOString().slice(0, 10),
    end_date: new Date().toISOString().slice(0, 10),
    initial_capital: 100000,
  });
  const [backtestResult, setBacktestResult] = useState(null);
  const [backtesting, setBacktesting] = useState(false);
  const equityChartRef = useRef(null);
  const chartInstanceRef = useRef(null);

  // 回测历史
  const [backtestHistory, setBacktestHistory] = useState([]);
  const [showHistory, setShowHistory] = useState(false);

  // 自动选股Tab（从回测历史加载5个策略）
  const [autoTabs, setAutoTabs] = useState([]);

  // Toast 自动消失
  useEffect(() => {
    if (toast) {
      const t = setTimeout(() => setToast(null), TOAST_DURATION);
      return () => clearTimeout(t);
    }
  }, [toast]);

  // 加载策略列表
  const loadStrategies = useCallback(async () => {
    try {
      const { ok, data } = await apiFetch('/api/bs-screener/strategies');
      if (ok) setStrategies(data?.strategies || []);
    } catch (e) {
      /* silent */
    }
  }, []);

  useEffect(() => {
    loadStrategies();
  }, [loadStrategies]);

  // 运行选股扫描
  const runScreener = useCallback(async (scanParams = params) => {
    setScanning(true);
    setError(null);
    try {
      const qs = new URLSearchParams({
        atr_period: String(scanParams.atr_period),
        atr_multiplier: String(scanParams.atr_multiplier),
        scan_limit: String(scanParams.scan_limit),
        sector: scanParams.sector || '',
        signal_type: scanParams.signal_type,
        volume_filter: String(scanParams.volume_filter || false),
        ma20_filter: String(scanParams.ma20_filter || false),
        ma60_trend: String(scanParams.ma60_trend || false),
        rsi_filter: String(scanParams.rsi_filter || false),
        strong_volume: String(scanParams.strong_volume || false),
        macd_filter: String(scanParams.macd_filter || false),
        kdj_filter: String(scanParams.kdj_filter || false),
        dimension: String(scanParams.dimension || ''),
      }).toString();
      const { ok, data, status } = await apiFetch(`/api/bs-screener/run?${qs}`);
      if (!ok) throw new Error(`扫描失败: ${status}`);
      setSignals(data);
      setToast({ success: true, message: `扫描完成：共扫描 ${data.scanned} 只，命中 ${data.summary.total} 只` });
    } catch (e) {
      setError(e.message || '扫描失败');
      setToast({ success: false, message: e.message || '扫描失败' });
    } finally {
      setScanning(false);
    }
  }, [params]);

  // 参数变更
  const handleParamChange = (key, value) => {
    setParams(prev => ({ ...prev, [key]: value }));
  };

  // 保存策略
  const handleSaveStrategy = async () => {
    if (!strategyName.trim()) {
      setToast({ success: false, message: '请输入策略名称' });
      return;
    }
    try {
      const res = await apiFetch('/api/bs-screener/strategies', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: strategyName.trim(),
          atr_period: Number(params.atr_period),
          atr_multiplier: Number(params.atr_multiplier),
          scan_limit: Number(params.scan_limit),
          sector_filter: params.sector || '',
          signal_type: params.signal_type,
          volume_filter: params.volume_filter || false,
          ma20_filter: params.ma20_filter || false,
          ma60_trend: params.ma60_trend || false,
          rsi_filter: params.rsi_filter || false,
          strong_volume: params.strong_volume || false,
          macd_filter: params.macd_filter || false,
          kdj_filter: params.kdj_filter || false,
        }),
      });
      if (!res.ok) { setToast({ success: false, message: '保存失败' }); return; }
      if (res.data?.success) {
        setToast({ success: true, message: `策略「${strategyName}」已保存` });
        setStrategyName('');
        loadStrategies();
      } else {
        throw new Error('保存失败');
      }
    } catch (e) {
      setToast({ success: false, message: e.message || '保存失败' });
    }
  };

  // 加载策略
  const handleLoadStrategy = (s) => {
    setParams({
      atr_period: s.atr_period,
      atr_multiplier: s.atr_multiplier,
      scan_limit: s.scan_limit,
      sector: s.sector_filter || '',
      signal_type: s.signal_type,
      volume_filter: s.volume_filter || false,
      ma20_filter: s.ma20_filter || false,
      ma60_trend: s.ma60_trend || false,
      rsi_filter: s.rsi_filter || false,
      strong_volume: s.strong_volume || false,
      macd_filter: s.macd_filter || false,
      kdj_filter: s.kdj_filter || false,
      stop_loss_pct: s.stop_loss_pct || 0,
    });
    setToast({ success: true, message: `已加载策略「${s.name}」，点击"开始扫描"应用` });
  };

  // 删除策略
  const handleDeleteStrategy = async (id, name) => {
    if (!confirm(`确认删除策略「${name}」？`)) return;
    try {
      const res = await apiFetch(`/api/bs-screener/strategies/${id}`, { method: 'DELETE' });
      if (!res.ok) { setToast({ success: false, message: '删除失败' }); return; }
      if (res.data?.success) {
        setToast({ success: true, message: `策略「${name}」已删除` });
        loadStrategies();
      }
    } catch (e) {
      setToast({ success: false, message: '删除失败' });
    }
  };

  // 导出CSV
  const handleExport = () => {
    if (!signals?.signals?.length) {
      setToast({ success: false, message: '暂无数据可导出' });
      return;
    }
    const headers = ['代码', '名称', '板块', '信号', '信号日期', '信号价', '现价', '涨跌幅%', '趋势', '评分', '原因'];
    const rows = signals.signals.map(s => [
      s.secCode,
      s.secName,
      s.sector || '',
      s.signalLabel,
      s.signalDate || '',
      s.signalPrice ?? '',
      s.position?.price ?? '',
      s.position?.profitPct ?? '',
      s.trend || '',
      s.score ?? '',
      (s.reasons || []).join(' | '),
    ]);
    const csv = [headers, ...rows]
      .map(r => r.map(c => `"${String(c).replace(/"/g, '""')}"`).join(','))
      .join('\n');
    // 加 BOM 防止 Excel 中文乱码
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `BS选股结果_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    setToast({ success: true, message: `已导出 ${rows.length} 条结果` });
  };

  // 加载回测历史
  const loadHistory = useCallback(async () => {
    try {
      const { ok, data } = await apiFetch('/api/bs-screener/backtest/history?limit=50');
      if (ok) {
        setBacktestHistory(data.history || []);
        return data.history || [];
      }
    } catch (e) { /* ignore */ }
    return [];
  }, []);

  // 页面加载时获取历史，初始化自动选股Tab（不自动选股，用户手动点击）
  useEffect(() => {
    (async () => {
      const history = await loadHistory();
      // 取前5个策略作为Tab
      const tabs = history.slice(0, 5).map(h => ({
        id: h.id,
        name: h.name,
        dimension: h.dimension,
        win_rate: h.win_rate,
        stock_win_rate: h.stock_win_rate,
        profit_factor: h.profit_factor,
        atr_period: h.atr_period,
        atr_multiplier: h.atr_multiplier,
        volume_filter: h.volume_filter,
        ma20_filter: h.ma20_filter,
        ma60_trend: h.ma60_trend,
        rsi_filter: h.rsi_filter,
        strong_volume: h.strong_volume,
        macd_filter: h.macd_filter,
        kdj_filter: h.kdj_filter,
        rsi_lower: h.rsi_lower || 30,
        rsi_upper: h.rsi_upper || 70,
      }));
      setAutoTabs(tabs);
    })();
  }, [loadHistory]);

  // 删除历史记录
  const handleDeleteHistory = async (id) => {
    try {
      await apiFetch(`/api/bs-screener/backtest/history/${id}`, { method: 'DELETE' });
      loadHistory();
      setToast({ success: true, message: '已删除回测记录' });
    } catch (e) {
      setToast({ success: false, message: '删除失败' });
    }
  };

  // 运行回测（用扫描结果中的股票，或手动输入）
  const handleRunBacktest = async () => {
    const stocks = (signals?.signals || []).map(s => s.secCode).slice(0, 10);
    if (stocks.length === 0) {
      setToast({ success: false, message: '请先扫描获取选股结果，回测将使用结果中的股票' });
      return;
    }
    setBacktesting(true);
    setBacktestResult(null);
    try {
      const { ok, data, status } = await apiFetch('/api/bs-screener/backtest', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          stocks,
          atr_period: Number(params.atr_period),
          atr_multiplier: Number(params.atr_multiplier),
          start_date: backtestParams.start_date,
          end_date: backtestParams.end_date,
          initial_capital: Number(backtestParams.initial_capital),
          volume_filter: params.volume_filter || false,
          ma20_filter: params.ma20_filter || false,
          ma60_trend: params.ma60_trend || false,
          rsi_filter: params.rsi_filter || false,
          strong_volume: params.strong_volume || false,
          macd_filter: params.macd_filter || false,
          kdj_filter: params.kdj_filter || false,
          stop_loss_pct: Number(params.stop_loss_pct || 0),
          rsi_lower: Number(params.rsi_lower || 30),
          rsi_upper: Number(params.rsi_upper || 70),
          ma60_rising: params.ma60_rising || false,
        }),
      });
      if (!ok) throw new Error(`回测失败: ${status}`);
      setBacktestResult(data);
      setToast({ success: true, message: `回测完成：${data.summary.total_trades} 笔交易，胜率 ${data.summary.win_rate}%` });

      // 自动保存回测结果到历史
      try {
        const filterTags = [
          params.volume_filter ? '量' : '',
          params.ma20_filter ? 'MA20' : '',
          params.ma60_trend ? 'MA60' : '',
          params.rsi_filter ? 'RSI' : '',
          params.strong_volume ? '强量' : '',
          params.macd_filter ? 'MACD' : '',
          params.kdj_filter ? 'KDJ' : '',
          (params.stop_loss_pct || 0) > 0 ? `止损${params.stop_loss_pct}%` : '',
        ].filter(Boolean).join('+') || '无过滤';
        const btName = `BT-${Date.now().toString().slice(-6)}`;
        await apiFetch('/api/bs-screener/backtest/save', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            name: btName,
            dimension: 'custom',
            stock_count: stocks.length,
            start_date: backtestParams.start_date,
            end_date: backtestParams.end_date,
            initial_capital: Number(backtestParams.initial_capital),
            atr_period: Number(params.atr_period),
            atr_multiplier: Number(params.atr_multiplier),
            volume_filter: params.volume_filter || false,
            ma20_filter: params.ma20_filter || false,
            ma60_trend: params.ma60_trend || false,
            rsi_filter: params.rsi_filter || false,
            strong_volume: params.strong_volume || false,
            macd_filter: params.macd_filter || false,
            kdj_filter: params.kdj_filter || false,
            stop_loss_pct: Number(params.stop_loss_pct || 0),
            total_trades: data.summary.total_trades,
            win_trades: data.summary.win_trades,
            loss_trades: data.summary.loss_trades,
            win_rate: data.summary.win_rate,
            stock_win_rate: 0,
            total_profit_pct: data.summary.total_profit_pct,
            annual_return: data.summary.annual_return,
            max_drawdown_pct: data.summary.max_drawdown_pct,
            profit_factor: data.summary.profit_factor === Infinity ? 999.99 : data.summary.profit_factor,
            avg_hold_days: data.summary.avg_hold_days,
            max_profit_pct: data.summary.max_profit_pct,
            max_loss_pct: data.summary.max_loss_pct,
            total_profit: data.summary.total_profit,
            note: `ATR(${params.atr_period},${params.atr_multiplier}) ${filterTags}`,
          }),
        });
        loadHistory(); // 刷新历史列表
      } catch (e) { /* 保存失败不影响回测结果 */ }
    } catch (e) {
      setToast({ success: false, message: e.message || '回测失败' });
    } finally {
      setBacktesting(false);
    }
  };

  // 渲染收益曲线
  useEffect(() => {
    if (!backtestResult?.equity_curve?.length || !equityChartRef.current) return;
    if (chartInstanceRef.current) {
      chartInstanceRef.current.dispose();
    }
    const chart = echarts.init(equityChartRef.current);
    chartInstanceRef.current = chart;
    const curve = backtestResult.equity_curve;
    chart.setOption({
      tooltip: { trigger: 'axis', formatter: p => `${p[0].axisValue}<br/>权益: ¥${p[0].data.toLocaleString()}` },
      grid: { left: 60, right: 20, top: 20, bottom: 30 },
      xAxis: { type: 'category', data: curve.map(p => p.date), axisLabel: { fontSize: 10 } },
      yAxis: { type: 'value', name: '权益(¥)', axisLabel: { fontSize: 10 } },
      series: [{
        type: 'line',
        data: curve.map(p => p.equity),
        smooth: true,
        symbol: 'none',
        lineStyle: { width: 2, color: '#3b82f6' },
        areaStyle: { color: 'rgba(59,130,246,0.1)' },
      }],
    });
    const handleResize = () => chart.resize();
    window.addEventListener('resize', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      chart.dispose();
      chartInstanceRef.current = null;
    };
  }, [backtestResult]);

  return (
    <div className="space-y-2">
      {/* Toast 通知 */}
      {toast && (
        <div
          className="fixed top-4 right-4 z-50 px-3 py-2 rounded-lg shadow-lg text-sm"
          style={{
            background: toast.success ? 'rgba(34,197,94,0.9)' : 'rgba(239,68,68,0.9)',
            color: '#fff',
          }}
        >
          {toast.success ? '✅ ' : '❌ '}{toast.message}
        </div>
      )}

      {/* 标题栏（简化：只保留标题 + 参数配置开关） */}
      <div className="flex items-center justify-between">
        <h2 className="text-base font-bold" style={{ color: 'var(--text-primary)' }}>🔧 策略配置调整中心</h2>
        <div className="flex items-center gap-1.5">
          {signals && (
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              扫描 {signals.scanned} · 命中 {signals.summary.total}
            </span>
          )}
          <button
            onClick={() => setShowConfig(!showConfig)}
            className="px-2 py-1 rounded-md text-xs border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            {showConfig ? '收起参数' : '⚙ 参数配置'}
          </button>
        </div>
      </div>

      {/* 策略总览区：所有策略统一管理（一行一个策略） */}
      <StrategyOverview
        bsStrategies={autoTabs}
        onRunBacktest={(strategy) => {
          // 用指定策略参数预填并打开回测面板
          if (strategy) {
            setParams({
              ...params,
              atr_period: strategy.atr_period,
              atr_multiplier: strategy.atr_multiplier,
              volume_filter: strategy.volume_filter || false,
              ma20_filter: strategy.ma20_filter || false,
              ma60_trend: strategy.ma60_trend || false,
              rsi_filter: strategy.rsi_filter || false,
              strong_volume: strategy.strong_volume || false,
              macd_filter: strategy.macd_filter || false,
              kdj_filter: strategy.kdj_filter || false,
              rsi_lower: strategy.rsi_lower || 30,
              rsi_upper: strategy.rsi_upper || 70,
            });
          }
          setShowBacktest(true);
          loadHistory();
        }}
        onShowHistory={() => { setShowHistory(true); loadHistory(); }}
        onScanMain={(strategy) => {
          // 用指定策略参数在主区扫描
          if (strategy) {
            setParams(prev => ({
              ...prev,
              atr_period: strategy.atr_period,
              atr_multiplier: strategy.atr_multiplier,
              volume_filter: strategy.volume_filter || false,
              ma20_filter: strategy.ma20_filter || false,
              ma60_trend: strategy.ma60_trend || false,
              rsi_filter: strategy.rsi_filter || false,
              strong_volume: strategy.strong_volume || false,
              macd_filter: strategy.macd_filter || false,
              kdj_filter: strategy.kdj_filter || false,
              rsi_lower: strategy.rsi_lower || 30,
              rsi_upper: strategy.rsi_upper || 70,
            }));
            setTimeout(() => runScreener(), 100);
          } else {
            runScreener();
          }
        }}
        onExport={handleExport}
        hasSignals={!!signals?.signals?.length}
      />

      {/* 选股参数配置面板（替代账户概览位置） */}
      {showConfig && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>⚙ 选股参数配置</h3>
            <button
              onClick={() => setShowStrategyPanel(!showStrategyPanel)}
              className="text-xs px-2 py-1 rounded border"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
            >
              {showStrategyPanel ? '收起策略库' : '💾 策略保存/加载'}
            </button>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {/* ATR周期 */}
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>ATR周期</label>
              <input
                type="number"
                min="5"
                max="30"
                value={params.atr_period}
                onChange={e => handleParamChange('atr_period', Number(e.target.value))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            {/* ATR乘数 */}
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>ATR乘数</label>
              <input
                type="number"
                step="0.1"
                min="0.5"
                max="5"
                value={params.atr_multiplier}
                onChange={e => handleParamChange('atr_multiplier', Number(e.target.value))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            {/* 扫描数量 */}
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>扫描数量</label>
              <input
                type="number"
                min="10"
                max="500"
                step="10"
                value={params.scan_limit}
                onChange={e => handleParamChange('scan_limit', Number(e.target.value))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            {/* 信号类型 */}
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>信号类型</label>
              <select
                value={params.signal_type}
                onChange={e => handleParamChange('signal_type', e.target.value)}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              >
                {SIGNAL_TYPES.map(t => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
            {/* 板块筛选 */}
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>板块筛选(逗号分隔)</label>
              <input
                type="text"
                value={params.sector}
                onChange={e => handleParamChange('sector', e.target.value)}
                placeholder="如:半导体,人工智能"
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
          </div>

          {/* 信号准确率过滤开关 */}
          <div className="mt-3 flex flex-wrap items-center gap-4 text-xs">
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.volume_filter || false}
                onChange={e => handleParamChange('volume_filter', e.target.checked)}
                className="cursor-pointer"
              />
              <span>📊 量过滤（&gt;5日均量）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.ma20_filter || false}
                onChange={e => handleParamChange('ma20_filter', e.target.checked)}
                className="cursor-pointer"
              />
              <span>📈 MA20方向</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.ma60_trend || false}
                onChange={e => handleParamChange('ma60_trend', e.target.checked)}
                className="cursor-pointer"
              />
              <span>🛡️ MA60趋势（价在MA60上）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.rsi_filter || false}
                onChange={e => handleParamChange('rsi_filter', e.target.checked)}
                className="cursor-pointer"
              />
              <span>⚡ RSI过滤（</span>
              <input
                type="number"
                min="10"
                max="50"
                value={params.rsi_lower || 30}
                onChange={e => handleParamChange('rsi_lower', Number(e.target.value))}
                className="w-12 px-1 py-0.5 rounded border text-xs"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
              <span>-</span>
              <input
                type="number"
                min="50"
                max="90"
                value={params.rsi_upper || 70}
                onChange={e => handleParamChange('rsi_upper', Number(e.target.value))}
                className="w-12 px-1 py-0.5 rounded border text-xs"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
              <span>）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.strong_volume || false}
                onChange={e => handleParamChange('strong_volume', e.target.checked)}
                className="cursor-pointer"
              />
              <span>🔥 强量突破（&gt;2倍均量）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.macd_filter || false}
                onChange={e => handleParamChange('macd_filter', e.target.checked)}
                className="cursor-pointer"
              />
              <span>📊 MACD动能（柱&gt;0）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <input
                type="checkbox"
                checked={params.kdj_filter || false}
                onChange={e => handleParamChange('kdj_filter', e.target.checked)}
                className="cursor-pointer"
              />
              <span>⚠️ KDJ超买（K&lt;80）</span>
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer" style={{ color: 'var(--text-secondary)' }}>
              <span>🛑 止损%</span>
              <input
                type="number"
                min="0"
                max="20"
                step="1"
                value={params.stop_loss_pct || 0}
                onChange={e => handleParamChange('stop_loss_pct', Number(e.target.value))}
                className="w-16 px-2 py-1 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
              <span className="text-xs" style={{ color: 'var(--text-muted)' }}>（0=不止损）</span>
            </label>
          </div>

          {/* 策略保存/加载面板 */}
          {showStrategyPanel && (
            <div className="mt-4 pt-3 border-t" style={{ borderColor: 'var(--border-color)' }}>
              <div className="flex items-center gap-2 mb-3">
                <input
                  type="text"
                  value={strategyName}
                  onChange={e => setStrategyName(e.target.value)}
                  placeholder="策略名称"
                  className="flex-1 px-2 py-1.5 rounded border text-sm"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
                />
                <button
                  onClick={handleSaveStrategy}
                  className="px-3 py-1.5 rounded text-xs border"
                  style={{ borderColor: 'rgba(34,197,94,0.3)', color: '#22c55e', background: 'rgba(34,197,94,0.05)' }}
                >
                  💾 保存当前参数
                </button>
              </div>
              {strategies.length === 0 ? (
                <div className="text-xs text-center py-2" style={{ color: 'var(--text-muted)' }}>暂无保存的策略</div>
              ) : (
                <div className="space-y-1.5 max-h-48 overflow-y-auto">
                  {strategies.map(s => (
                    <div
                      key={s.id}
                      className="flex items-center justify-between px-3 py-2 rounded border text-xs"
                      style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}
                    >
                      <div className="flex-1 min-w-0">
                        <div className="font-medium truncate" style={{ color: 'var(--text-primary)' }}>{s.name}</div>
                        <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                          ATR({s.atr_period},{s.atr_multiplier}) · 扫{s.scan_limit} · {s.signal_type}点
                          {s.sector_filter && ` · ${s.sector_filter}`}
                          {' · '}{s.created_at}
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5 ml-2">
                        <button
                          onClick={() => handleLoadStrategy(s)}
                          className="px-2 py-1 rounded text-[11px] border"
                          style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
                        >
                          加载
                        </button>
                        <button
                          onClick={() => handleDeleteStrategy(s.id, s.name)}
                          className="px-2 py-1 rounded text-[11px] border"
                          style={{ borderColor: 'rgba(239,68,68,0.3)', color: '#ef4444' }}
                        >
                          删除
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* 信号汇总卡片 */}
      {signals && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
            {[
              { label: 'B点(买入)', count: signals.summary.buy, color: B_SIGNAL_COLOR },
              { label: 'S点(卖出)', count: signals.summary.sell, color: S_SIGNAL_COLOR },
              { label: '关注', count: signals.summary.watch, color: '#3b82f6' },
              { label: '扫描总数', count: signals.summary.scanned, color: 'var(--text-primary)' },
              { label: '命中率', count: signals.summary.scanned ? `${((signals.summary.total / signals.summary.scanned) * 100).toFixed(1)}%` : '0%', color: '#eab308' },
            ].map(item => (
              <div key={item.label} className="rounded-xl border p-3 text-center" style={{ borderColor: `${item.color}40`, background: 'var(--bg-card)' }}>
                <div className="text-2xl font-bold" style={{ color: item.color }}>{item.count}</div>
                <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{item.label}</div>
              </div>
            ))}
          </div>

          <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
            分析时间: {signals.generated_at} · 参数 ATR({signals.params.atr_period}, {signals.params.atr_multiplier}) · 扫描 {signals.params.scan_limit} 只 · 信号类型 {signals.params.signal_type}
            {signals.params.sector && ` · 板块: ${signals.params.sector}`}
            {(() => {
              const now = new Date();
              const h = now.getHours();
              const m = now.getMinutes();
              const isTradeTime = (h === 9 && m >= 25) || (h >= 10 && h < 15) || (h === 15 && m === 0);
              const label = isTradeTime ? '盘中实时' : '盘后数据';
              const color = isTradeTime ? '#22c55e' : '#eab308';
              const dateStr = `${now.getMonth() + 1}月${now.getDate()}日`;
              return (
                <span className="ml-2 px-1.5 py-0.5 rounded text-[10px]" style={{ background: `${color}1a`, color }}>
                  {dateStr} {label}
                </span>
              );
            })()}
          </div>
        </>
      )}

      {/* 错误提示 */}
      {error && (
        <div className="rounded-xl border p-4 text-center" style={{ borderColor: 'rgba(239,68,68,0.3)', background: 'rgba(239,68,68,0.05)' }}>
          <div className="text-sm" style={{ color: '#ef4444' }}>{error}</div>
          <button
            onClick={() => runScreener()}
            className="mt-2 px-3 py-1.5 rounded-lg border text-xs"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            重试
          </button>
        </div>
      )}

      {/* 信号卡片列表 */}
      <div className="space-y-2">
        {scanning && !signals ? (
          <>
            <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
              {[1, 2, 3, 4, 5].map(i => (
                <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
              ))}
            </div>
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 rounded-xl animate-pulse" style={{ background: 'var(--bg-hover)' }} />
            ))}
          </>
        ) : signals ? (
          signals.signals.length > 0 ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
              {signals.signals.map(sig => (
                <SignalCard key={sig.secCode} signal={sig} orders={[]} showWatchBtn={false} mode="watchlist" showMarketState showBuyPower showAnalysisButton />
              ))}
            </div>
          ) : (
            <div className="text-center py-12 text-sm" style={{ color: 'var(--text-muted)' }}>
              未扫描到符合条件的股票，请调整参数后重试
            </div>
          )
        ) : (
          <div className="text-center py-12">
            <div className="text-sm mb-3" style={{ color: 'var(--text-muted)' }}>
              点击"开始扫描"运行BS点选股
            </div>
            <button
              onClick={() => runScreener()}
              className="px-3 py-2 rounded-lg text-sm border"
              style={{ borderColor: 'rgba(34,197,94,0.3)', color: '#22c55e', background: 'rgba(34,197,94,0.05)' }}
            >
              🔍 开始扫描
            </button>
          </div>
        )}
      </div>

      {/* 策略回测面板 */}
      {showBacktest && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>📊 策略回测</h3>
            <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
              回测使用当前扫描结果中的前10只股票
            </span>
          </div>

          {/* 回测参数 */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 mb-3">
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>开始日期</label>
              <input
                type="date"
                value={backtestParams.start_date}
                onChange={e => setBacktestParams(prev => ({ ...prev, start_date: e.target.value }))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>结束日期</label>
              <input
                type="date"
                value={backtestParams.end_date}
                onChange={e => setBacktestParams(prev => ({ ...prev, end_date: e.target.value }))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            <div>
              <label className="text-xs block mb-1" style={{ color: 'var(--text-muted)' }}>初始资金(¥)</label>
              <input
                type="number"
                min="10000"
                step="10000"
                value={backtestParams.initial_capital}
                onChange={e => setBacktestParams(prev => ({ ...prev, initial_capital: Number(e.target.value) }))}
                className="w-full px-2 py-1.5 rounded border text-sm"
                style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)', color: 'var(--text-primary)' }}
              />
            </div>
            <div className="flex items-end">
              <button
                onClick={handleRunBacktest}
                disabled={backtesting || !signals?.signals?.length}
                className="w-full px-3 py-1.5 rounded-lg text-sm border"
                style={{
                  borderColor: backtesting ? 'var(--border-color)' : 'rgba(59,130,246,0.3)',
                  color: backtesting ? 'var(--text-muted)' : '#3b82f6',
                  background: backtesting ? 'transparent' : 'rgba(59,130,246,0.05)',
                }}
              >
                {backtesting ? '⏳ 回测中...' : '🚀 运行回测'}
              </button>
            </div>
          </div>

          {/* 回测结果 */}
          {backtestResult && (
            <div className="space-y-2">
              {/* 统计卡片 */}
              <div className="grid grid-cols-2 md:grid-cols-5 gap-2">
                {[
                  { label: '总交易数', value: backtestResult.summary.total_trades, color: 'var(--text-primary)' },
                  { label: '胜率', value: `${backtestResult.summary.win_rate}%`, color: backtestResult.summary.win_rate >= 50 ? '#ef4444' : '#22c55e' },
                  { label: '总收益率', value: `${backtestResult.summary.total_profit_pct}%`, color: backtestResult.summary.total_profit_pct >= 0 ? '#ef4444' : '#22c55e' },
                  { label: '最大回撤', value: `${backtestResult.summary.max_drawdown_pct}%`, color: '#f97316' },
                  { label: '盈亏比', value: backtestResult.summary.profit_factor === Infinity ? '∞' : backtestResult.summary.profit_factor, color: '#eab308' },
                ].map(item => (
                  <div key={item.label} className="rounded-lg border p-3 text-center" style={{ borderColor: `${item.color}40`, background: 'var(--bg-primary)' }}>
                    <div className="text-xl font-bold" style={{ color: item.color }}>{item.value}</div>
                    <div className="text-xs mt-1" style={{ color: 'var(--text-muted)' }}>{item.label}</div>
                  </div>
                ))}
              </div>

              {/* 扩展统计 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>年化收益: </span>
                  <span style={{ color: backtestResult.summary.annual_return >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                    {backtestResult.summary.annual_return}%
                  </span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>平均持仓: </span>
                  <span style={{ color: 'var(--text-primary)', fontWeight: 600 }}>{backtestResult.summary.avg_hold_days} 天</span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>最大盈利: </span>
                  <span style={{ color: '#ef4444', fontWeight: 600 }}>{backtestResult.summary.max_profit_pct}%</span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>最大亏损: </span>
                  <span style={{ color: '#22c55e', fontWeight: 600 }}>{backtestResult.summary.max_loss_pct}%</span>
                </div>
              </div>

              {/* 盈亏金额明细 */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
                <div className="rounded-lg border p-2.5" style={{ borderColor: '#ef444440', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>总盈利金额: </span>
                  <span style={{ color: '#ef4444', fontWeight: 600 }}>
                    ¥{(backtestResult.summary.gross_profit || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: '#22c55e40', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>总亏损金额: </span>
                  <span style={{ color: '#22c55e', fontWeight: 600 }}>
                    ¥{(backtestResult.summary.gross_loss || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>净盈亏: </span>
                  <span style={{ color: (backtestResult.summary.total_profit || 0) >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                    ¥{(backtestResult.summary.total_profit || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                  </span>
                </div>
                <div className="rounded-lg border p-2.5" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-primary)' }}>
                  <span style={{ color: 'var(--text-muted)' }}>盈利交易: </span>
                  <span style={{ color: '#ef4444', fontWeight: 600 }}>{backtestResult.summary.win_trades}</span>
                  <span style={{ color: 'var(--text-muted)' }}> / 亏损: </span>
                  <span style={{ color: '#22c55e', fontWeight: 600 }}>{backtestResult.summary.loss_trades}</span>
                </div>
              </div>

              {/* 策略评价 */}
              {(() => {
                const s = backtestResult.summary;
                const pf = s.profit_factor === Infinity ? 999 : s.profit_factor;
                const wr = s.win_rate;
                const dd = s.max_drawdown_pct;
                let rating, ratingColor, opinion;
                if (pf >= 2.0 && wr >= 45) {
                  rating = '★★★ 优秀';
                  ratingColor = '#ef4444';
                  opinion = '策略表现优秀，盈亏比>2且胜率接近50%，赢时赚得多、输时亏得少，值得后续实盘使用。建议在科创板优先应用（历史回测个股胜率55%+）。';
                } else if (pf >= 1.5 && wr >= 40) {
                  rating = '★★ 良好';
                  ratingColor = '#eab308';
                  opinion = '策略表现良好，盈亏比>1.5且胜率>40%，整体盈利能力正向。可作为辅助选股工具使用，建议结合市场环境择时操作。';
                } else if (pf >= 1.2) {
                  rating = '★ 一般';
                  ratingColor = '#f97316';
                  opinion = '策略表现一般，盈亏比略高于1，盈利空间有限。建议继续优化参数或增加过滤条件后再使用。';
                } else {
                  rating = '☆ 需优化';
                  ratingColor = '#22c55e';
                  opinion = '策略盈亏比偏低，当前参数不适合直接使用，建议调整ATR参数或过滤器组合后重新回测。';
                }
                return (
                  <div className="rounded-lg border p-3" style={{ borderColor: `${ratingColor}40`, background: 'var(--bg-primary)' }}>
                    <div className="flex items-center gap-2 mb-1.5">
                      <span className="text-sm font-bold" style={{ color: ratingColor }}>{rating}</span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>| 策略评价</span>
                    </div>
                    <div className="text-xs leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
                      {opinion}
                    </div>
                    <div className="text-xs mt-2 pt-2 border-t" style={{ color: 'var(--text-muted)', borderColor: 'var(--border-color)' }}>
                      评分依据: 盈亏比 {pf === 999 ? '∞' : pf} · 胜率 {wr}% · 最大回撤 {dd}%
                    </div>
                  </div>
                );
              })()}

              {/* 收益曲线 */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>📈 权益曲线</div>
                <div ref={equityChartRef} style={{ width: '100%', height: 240 }} />
              </div>

              {/* 交易明细 */}
              <div>
                <div className="text-xs mb-1" style={{ color: 'var(--text-muted)' }}>
                  📋 交易明细（共 {backtestResult.trades.length} 笔）
                </div>
                <div className="max-h-64 overflow-y-auto rounded-lg border" style={{ borderColor: 'var(--border-color)' }}>
                  <table className="w-full text-xs">
                    <thead className="sticky top-0" style={{ background: 'var(--bg-hover)' }}>
                      <tr style={{ color: 'var(--text-muted)' }}>
                        <th className="px-2 py-1.5 text-left">买入日</th>
                        <th className="px-2 py-1.5 text-right">买价</th>
                        <th className="px-2 py-1.5 text-left">卖出日</th>
                        <th className="px-2 py-1.5 text-right">卖价</th>
                        <th className="px-2 py-1.5 text-right">收益%</th>
                        <th className="px-2 py-1.5 text-right">持仓天</th>
                      </tr>
                    </thead>
                    <tbody>
                      {backtestResult.trades.map((t, i) => (
                        <tr key={i} className="border-t" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
                          <td className="px-2 py-1.5">{t.entry_date}</td>
                          <td className="px-2 py-1.5 text-right">{t.entry_price}</td>
                          <td className="px-2 py-1.5">{t.exit_date}</td>
                          <td className="px-2 py-1.5 text-right">{t.exit_price}</td>
                          <td className="px-2 py-1.5 text-right" style={{ color: t.profit_pct >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                            {t.profit_pct >= 0 ? '+' : ''}{t.profit_pct}%
                          </td>
                          <td className="px-2 py-1.5 text-right">{t.hold_days}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* 回测历史面板 */}
      {showHistory && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
              📋 回测历史（{backtestHistory.length}条）
            </h3>
            <button onClick={loadHistory} className="text-xs" style={{ color: 'var(--text-secondary)' }}>🔄 刷新</button>
          </div>

          {backtestHistory.length === 0 ? (
            <div className="text-center py-8 text-sm" style={{ color: 'var(--text-muted)' }}>
              暂无回测历史，运行回测后会自动保存
            </div>
          ) : (
            <div className="max-h-96 overflow-auto rounded-lg border" style={{ borderColor: 'var(--border-color)' }}>
              <table className="w-full text-xs">
                <thead className="sticky top-0" style={{ background: 'var(--bg-hover)' }}>
                  <tr style={{ color: 'var(--text-muted)' }}>
                    <th className="px-2 py-2 text-left">类型</th>
                    <th className="px-2 py-2 text-left">编号</th>
                    <th className="px-2 py-2 text-left">时间</th>
                    <th className="px-2 py-2 text-left">参数</th>
                    <th className="px-2 py-2 text-right">股票数</th>
                    <th className="px-2 py-2 text-right">交易数</th>
                    <th className="px-2 py-2 text-right">交易胜率</th>
                    <th className="px-2 py-2 text-right">个股胜率</th>
                    <th className="px-2 py-2 text-right">盈亏比</th>
                    <th className="px-2 py-2 text-right">净盈亏</th>
                    <th className="px-2 py-2 text-center">推荐评价</th>
                    <th className="px-2 py-2 text-left">区间</th>
                    <th className="px-2 py-2 text-center">操作</th>
                  </tr>
                </thead>
                <tbody>
                  {backtestHistory.map((h) => {
                    const pf = h.profit_factor >= 999 ? 999 : h.profit_factor;
                    const wr = h.win_rate;
                    let rating, ratingColor, recommend;
                    if (pf >= 2.0 && wr >= 45) {
                      rating = '★★★'; ratingColor = '#ef4444'; recommend = '推荐买入';
                    } else if (pf >= 1.5 && wr >= 40) {
                      rating = '★★'; ratingColor = '#eab308'; recommend = '可关注';
                    } else if (pf >= 1.2) {
                      rating = '★'; ratingColor = '#f97316'; recommend = '谨慎';
                    } else {
                      rating = '☆'; ratingColor = '#6b7280'; recommend = '不建议';
                    }
                    // 策略类型推断：BS回测历史都是BS策略
                    const strategyType = 'BS';
                    const typeColor = '#22c55e';
                    return (
                    <tr key={h.id} className="border-t" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>
                      <td className="px-2 py-1.5">
                        <span className="text-[10px] px-1.5 py-0.5 rounded font-bold" style={{ background: typeColor + '15', color: typeColor }}>
                          {strategyType}
                        </span>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap" style={{ color: 'var(--accent-blue)', fontWeight: 600 }}>{h.name}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">{h.run_at}</td>
                      <td className="px-2 py-1.5 whitespace-nowrap">
                        <span style={{ color: 'var(--text-primary)' }}>ATR({h.atr_period},{h.atr_multiplier})</span>
                        {h.volume_filter && <span style={{ color: '#3b82f6' }}> 量</span>}
                        {h.ma20_filter && <span style={{ color: '#eab308' }}> MA20</span>}
                        {h.ma60_trend && <span style={{ color: '#22c55e' }}> MA60</span>}
                        {h.rsi_filter && <span style={{ color: '#a855f7' }}> RSI</span>}
                        {h.strong_volume && <span style={{ color: '#ef4444' }}> 强量</span>}
                        {h.macd_filter && <span style={{ color: '#06b6d4' }}> MACD</span>}
                        {h.kdj_filter && <span style={{ color: '#f97316' }}> KDJ</span>}
                        {h.stop_loss_pct > 0 && <span style={{ color: '#dc2626' }}> 止损{h.stop_loss_pct}%</span>}
                      </td>
                      <td className="px-2 py-1.5 text-right">{h.stock_count}</td>
                      <td className="px-2 py-1.5 text-right">{h.total_trades}</td>
                      <td className="px-2 py-1.5 text-right" style={{ color: wr >= 50 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                        {wr}%
                      </td>
                      <td className="px-2 py-1.5 text-right" style={{ color: (h.stock_win_rate || 0) >= 50 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                        {(h.stock_win_rate || 0)}%
                      </td>
                      <td className="px-2 py-1.5 text-right" style={{ color: pf >= 2 ? '#ef4444' : pf >= 1.5 ? '#eab308' : 'var(--text-secondary)', fontWeight: 600 }}>
                        {pf >= 999 ? '∞' : pf}
                      </td>
                      <td className="px-2 py-1.5 text-right" style={{ color: (h.total_profit || 0) >= 0 ? '#ef4444' : '#22c55e', fontWeight: 600 }}>
                        ¥{(h.total_profit || 0).toLocaleString(undefined, { maximumFractionDigits: 0 })}
                      </td>
                      <td className="px-2 py-1.5 text-center whitespace-nowrap">
                        <span style={{ color: ratingColor, fontWeight: 700, fontSize: '11px' }}>{rating}</span>
                        <div style={{ color: ratingColor, fontSize: '10px', marginTop: '2px' }}>{recommend}</div>
                      </td>
                      <td className="px-2 py-1.5 whitespace-nowrap text-[10px]">{h.start_date}~{h.end_date}</td>
                      <td className="px-2 py-1.5 text-center">
                        <button
                          onClick={() => handleDeleteHistory(h.id)}
                          className="text-[10px] px-1.5 py-0.5 rounded"
                          style={{ color: '#ef4444', border: '1px solid rgba(239,68,68,0.3)' }}
                        >
                          删除
                        </button>
                      </td>
                    </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
