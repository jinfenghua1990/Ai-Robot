/**
 * 策略扫描页 —— 18 个内置选股策略（移植自 tickflow-stock-panel）
 * market="a"（A股）/ "us"（美股）
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiFetch } from '../utils/request';

const MARKET_LABEL = { a: 'A股', us: '美股' };

export default function StrategyScanPage({ market = 'a' }) {
  const [strategies, setStrategies] = useState([]);
  const [selId, setSelId] = useState('');
  const [params, setParams] = useState({});
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [limit, setLimit] = useState(30);
  const [refresh, setRefresh] = useState(0);
  
  const paramsRef = useRef(params);

  useEffect(() => {
    paramsRef.current = params;
  }, [params]);

  const K = {
    panel: 'var(--bg-card)', border: 'var(--border-color)', borderLight: 'var(--border-light)',
    text: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)',
    up: 'var(--flow-up)', down: 'var(--flow-down)', blue: 'var(--accent-blue)',
    hover: 'var(--bg-hover)',
  };

  const loadStrategies = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/strategy-scan/strategies?market=${market}`, {}, 15000);
      if (res?.ok && res.data?.ok && res.data.data?.length) {
        setStrategies(res.data.data);
        if (!selId) setSelId(res.data.data[0].id);
      } else {
        setError(res.data?.error || res?.error || '策略列表加载失败');
      }
    } catch (e) {
      setError(String(e.message || e));
    }
  }, [market, selId]);

  useEffect(() => { loadStrategies(); }, [loadStrategies]);

  const sel = strategies.find((s) => s.id === selId) || null;

  const run = useCallback(async () => {
    if (!selId) return;
    setLoading(true);
    setError('');
    try {
      const res = await apiFetch(
        `/api/strategy-scan/run?market=${market}&strategy_id=${selId}&limit=${limit}&params_json=${encodeURIComponent(JSON.stringify(paramsRef.current))}&refresh=${refresh ? 1 : 0}`,
        {}, 90000
      );
      if (res?.ok && res.data?.ok && res.data.data) {
        setResult(res.data.data);
        setError('');
      } else {
        setError(res.data?.error || res?.error || '扫描失败');
      }
    } catch (e) {
      setError(String(e.message || e));
    } finally {
      setLoading(false);
    }
  }, [market, selId, limit, refresh]);

  useEffect(() => {
    if (selId) run();
  }, [selId, run]);

  const setParam = (pid, v) => setParams((p) => ({ ...p, [pid]: v }));

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 1280, margin: '0 auto', padding: 12 }}>
      <div style={{ fontSize: 15, fontWeight: 700, color: K.text }}>
        {market === 'us' ? '传统策略扫描（TSP）' : '选股策略扫描'} · {MARKET_LABEL[market]}
        <span style={{ fontSize: 11, fontWeight: 400, color: K.muted, marginLeft: 8 }}>
          移植自 tickflow-stock-panel 的 18 个内置策略
        </span>
      </div>

      {/* 策略选择 */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {strategies.map((s) => (
          <button
            key={s.id}
            onClick={() => { setSelId(s.id); setParams({}); }}
            style={{
              padding: '5px 10px', borderRadius: 8, cursor: 'pointer', fontSize: 12,
              border: `1px solid ${s.id === selId ? K.blue : K.borderLight}`,
              background: s.id === selId ? K.hover : 'transparent',
              color: s.id === selId ? K.blue : K.secondary,
            }}
          >
            {s.name}
          </button>
        ))}
      </div>

      {/* 策略说明 + 参数 */}
      {sel && (
        <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'baseline' }}>
            <span style={{ fontSize: 13, fontWeight: 600, color: K.text }}>{sel.name}</span>
            <span style={{ fontSize: 12, color: K.secondary }}>{sel.description}</span>
            <span style={{ fontSize: 11, color: K.muted }}>{(sel.tags || []).join(' / ')}</span>
            {sel.market === 'a' && <span style={{ fontSize: 10, color: K.blue }}>A股专属</span>}
          </div>
          {/* 参数 */}
          {(sel.params || []).length > 0 && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8, alignItems: 'center' }}>
              {(sel.params || []).map((p) => (
                <label key={p.id} style={{ fontSize: 11, color: K.secondary, display: 'flex', alignItems: 'center', gap: 4 }}>
                  {p.label}
                  {p.type === 'bool' ? (
                    <input type="checkbox" checked={params[p.id] ?? p.default}
                      onChange={(e) => setParam(p.id, e.target.checked)} />
                  ) : (
                    <input type="number" step={p.step || 0.1}
                      defaultValue={p.default}
                      onChange={(e) => setParam(p.id, parseFloat(e.target.value))}
                      style={{ width: 70, background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '2px 6px', color: K.text, fontSize: 12 }} />
                  )}
                </label>
              ))}
            </div>
          )}
          <div style={{ display: 'flex', gap: 8, marginTop: 10, alignItems: 'center' }}>
            <label style={{ fontSize: 11, color: K.secondary }}>
              数量
              <input type="number" min={1} max={100} value={limit} onChange={(e) => setLimit(Math.max(1, Math.min(100, parseInt(e.target.value) || 30)))}
                style={{ width: 56, marginLeft: 4, background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '2px 6px', color: K.text, fontSize: 12 }} />
            </label>
            <button onClick={() => setRefresh((r) => r + 1)} disabled={loading}
              style={{ padding: '5px 14px', borderRadius: 8, fontSize: 12, cursor: 'pointer', background: K.blue, color: '#fff', border: 'none' }}>
              {loading ? '扫描中…' : '▶ 运行扫描'}
            </button>
            {result && (
              <span style={{ fontSize: 11, color: K.muted }}>
                命中 {result.total} 只 / 扫描 {result.scanned} 只 · 耗时 {result.elapsed_ms}ms
              </span>
            )}
          </div>
        </div>
      )}

      {error && <div style={{ fontSize: 12, color: 'var(--accent-red)' }}>{error}</div>}

      {/* 结果列表 */}
      {result && result.hits && (
        <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 8 }}>命中结果</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <div style={{ display: 'flex', gap: 8, fontSize: 11, color: K.muted, padding: '4px 8px' }}>
              <span style={{ width: 100 }}>代码</span>
              <span style={{ width: 120 }}>名称</span>
              <span style={{ width: 70 }}>现价</span>
              <span style={{ width: 70 }}>涨跌幅</span>
              <span style={{ width: 60 }}>量比</span>
              <span style={{ width: 50 }}>RSI</span>
              <span style={{ flex: 1 }}>原因</span>
            </div>
            {result.hits.map((h, i) => (
              <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, padding: '5px 8px', borderRadius: 6, background: K.hover }}>
                <span style={{ width: 100, color: K.blue, fontWeight: 600 }}>{h.code}</span>
                <span style={{ width: 120, color: K.text }}>{h.name}</span>
                <span style={{ width: 70, color: K.text }}>{h.price}</span>
                <span style={{ width: 70, color: h.change_pct >= 0 ? K.up : K.down, fontWeight: 600 }}>{h.change_pct >= 0 ? '+' : ''}{h.change_pct}%</span>
                <span style={{ width: 60, color: K.secondary }}>{h.vol_ratio ?? '—'}</span>
                <span style={{ width: 50, color: K.secondary }}>{h.rsi ?? '—'}</span>
                <span style={{ flex: 1, color: K.muted }}>{h.reason}{h.boards > 0 ? ` · ${h.boards}连板` : ''}</span>
              </div>
            ))}
            {result.hits.length === 0 && <div style={{ fontSize: 12, color: K.muted, padding: 8 }}>当前候选池无命中</div>}
          </div>
        </div>
      )}
    </div>
  );
}
