/**
 * 监控规则引擎页 —— 移植自 tickflow-stock-panel 的 monitor_rules 设计
 * 多条件 AND/OR 规则 + 冷却 + 严重级别 + 触发日志
 * market="a"（A股）/ "hk"（港股）/ "us"（美股）
 */
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../utils/request';

const MARKET_LABEL = { a: 'A股', hk: '港股', us: '美股' };

// 与后端 ALLOWED_FIELDS 对齐
const FIELDS = [
  { id: 'price', label: '现价' },
  { id: 'change_pct', label: '涨跌幅(小数)', hint: '如 0.03 = +3%' },
  { id: 'change_pct_pct', label: '涨跌幅(%)', hint: '如 3 = +3%' },
  { id: 'volume', label: '成交量' },
  { id: 'vol_ratio_5d', label: '量比(5日)' },
  { id: 'rsi_14', label: 'RSI(14)' },
  { id: 'momentum_20d', label: '20日动量(小数)' },
  { id: 'annual_vol_20d', label: '年化波动率' },
  { id: 'ma20_bias', label: '价/MA20偏离(小数)' },
  { id: 'ma60_bias', label: '价/MA60偏离(小数)' },
  { id: 'amplitude', label: '日振幅(小数)' },
  { id: 'consecutive_limit_ups', label: '连板数(A股)' },
  { id: 'near_limit_up_pct', label: '距涨停%(A股)' },
  { id: 'limit_up', label: '当日涨停(A股)', truth: true },
  { id: 'macd_golden', label: 'MACD金叉', truth: true },
  { id: 'breakout_ma20', label: '突破MA20', truth: true },
];
const TRUTH_FIELDS = FIELDS.filter((f) => f.truth).map((f) => f.id);
const OPS = ['>', '>=', '<', '<=', '==', '!='];
const SEVERITIES = [
  { id: 'info', label: '普通', color: '#64748b' },
  { id: 'warn', label: '警告', color: '#f59e0b' },
  { id: 'critical', label: '严重', color: '#ef4444' },
];

const emptyCond = { field: 'change_pct', op: '>', value: 0.03 };

export default function MonitorRulesPage({ market = 'a', embedded = false }) {
  const [tab, setTab] = useState('list');
  const [rules, setRules] = useState([]);
  const [logs, setLogs] = useState([]);
  const [checkResult, setCheckResult] = useState(null);
  const [checking, setChecking] = useState(false);
  const [checkSymbols, setCheckSymbols] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [form, setForm] = useState(null);
  const [feishuCfg, setFeishuCfg] = useState(null);
  const [pushing, setPushing] = useState(false);

  const K = {
    panel: 'var(--bg-card)', border: 'var(--border-color)', borderLight: 'var(--border-light)',
    text: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)',
    up: 'var(--flow-up)', down: 'var(--flow-down)', blue: 'var(--accent-blue)',
    hover: 'var(--bg-hover)', red: 'var(--accent-red)',
  };

  const loadRules = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/monitor-rules/list?market=${market}`, {}, 15000);
      if (res?.ok && res.data?.ok) setRules(res.data.data || []);
    } catch {}
  }, [market]);

  const loadLogs = useCallback(async () => {
    try {
      const res = await apiFetch(`/api/monitor-rules/logs?market=${market}&limit=50`, {}, 15000);
      if (res?.ok && res.data?.ok) setLogs(res.data.data || []);
    } catch {}
  }, [market]);

  useEffect(() => { loadRules(); }, [loadRules]);
  useEffect(() => { if (tab === 'logs') loadLogs(); }, [tab, loadLogs]);

  // 飞书推送配置状态
  useEffect(() => {
    (async () => {
      try {
        const res = await apiFetch('/api/monitor-rules/feishu-config', {}, 8000);
        if (res?.ok && res.data?.ok) setFeishuCfg(res.data.data);
      } catch {}
    })();
  }, []);

  const testPush = async () => {
    setPushing(true);
    setError('');
    try {
      const res = await apiFetch('/api/monitor-rules/test-push', { method: 'POST' }, 20000);
      if (res?.ok && res.data?.ok) {
        setError('✅ 测试消息已发送到飞书');
      } else {
        setError(res.data?.error || res?.error || '测试推送失败');
      }
    } catch (e) { setError(String(e.message || e)); }
    finally { setPushing(false); }
  };

  const newForm = () => ({
    id: `rule_${Date.now().toString(36)}`,
    name: '', type: 'price', market, scope: 'symbols', symbols: [],
    conditions: [{ ...emptyCond }], logic: 'and',
    cooldown_seconds: 3600, severity: 'info', enabled: true, message: '',
    webhook_channels: [],
  });

  const save = async () => {
    setSaving(true);
    setError('');
    try {
      const body = { ...form };
      if (body.scope === 'symbols') {
        body.symbols = (body.symbols_text || '').split(/[,，\s]+/).map((s) => s.trim()).filter(Boolean).map((s) => s.toUpperCase());
      } else body.symbols = [];
      const res = await apiFetch('/api/monitor-rules/save', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ rule: body }),
      });
      if (res?.ok && res.data?.ok) {
        setForm(null);
        setTab('list');
        loadRules();
      } else setError(res.data?.error || res?.error || '保存失败');
    } catch (e) { setError(String(e.message || e)); }
    finally { setSaving(false); }
  };

  const remove = async (id) => {
    if (!window.confirm(`删除规则 ${id}？`)) return;
    const res = await apiFetch(`/api/monitor-rules/${id}`, { method: 'DELETE' });
    if (res?.ok && res.data?.ok) loadRules();
    else setError(res.data?.error || res?.error || '删除失败');
  };

  const checkNow = async () => {
    setChecking(true);
    setError('');
    setCheckResult(null);
    try {
      const qs = new URLSearchParams({ market });
      if (checkSymbols.trim()) qs.set('symbols', checkSymbols);
      const res = await apiFetch(`/api/monitor-rules/check?${qs}`, { method: 'POST' }, 90000);
      if (res?.ok && res.data?.ok) setCheckResult(res.data.data);
      else setError(res.data?.error || res?.error || '检查失败');
    } catch (e) { setError(String(e.message || e)); }
    finally { setChecking(false); }
  };

  const toggleEnabled = async (r) => {
    const body = { ...r, enabled: !r.enabled };
    const res = await apiFetch('/api/monitor-rules/save', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rule: body }),
    });
    if (res?.ok && res.data?.ok) loadRules();
  };

  const setCond = (idx, patch) => {
    const conds = form.conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c));
    setForm({ ...form, conditions: conds });
  };

  const fieldLabel = (id) => FIELDS.find((f) => f.id === id)?.label || id;
  const sevLabel = (id) => SEVERITIES.find((s) => s.id === id)?.label || id;
  const sevColor = (id) => SEVERITIES.find((s) => s.id === id)?.color || '#64748b';
  const condText = (c) => {
    if (c.op === 'truth') return `${fieldLabel(c.field)} 成立`;
    return `${fieldLabel(c.field)} ${c.op} ${c.value}`;
  };

  const inputStyle = { background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 };
  const btn = (bg, fg) => ({ padding: '6px 14px', borderRadius: 8, fontSize: 12, cursor: 'pointer', background: bg, color: fg, border: 'none' });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 1280, margin: embedded ? 0 : '0 auto', padding: embedded ? 0 : 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: K.text }}>
          监控规则引擎 · {MARKET_LABEL[market]}
          <span style={{ fontSize: 11, fontWeight: 400, color: K.muted, marginLeft: 8 }}>
            移植自 tickflow-stock-panel · 多条件 AND/OR + 冷却 + 触发日志
          </span>
        </div>
        <div style={{ display: 'flex', gap: 6, marginLeft: 'auto' }}>
          {[['list', '规则列表'], ['new', '＋ 新建规则'], ['logs', '触发日志']].map(([k, l]) => (
            <button key={k} onClick={() => { setTab(k); if (k === 'new') setForm(newForm()); setError(''); }}
              style={{
                padding: '5px 12px', borderRadius: 8, fontSize: 12, cursor: 'pointer',
                border: `1px solid ${tab === k ? K.blue : K.borderLight}`,
                background: tab === k ? K.hover : 'transparent',
                color: tab === k ? K.blue : K.secondary,
              }}>
              {l}
            </button>
          ))}
        </div>
      </div>

      {error && <div style={{ fontSize: 12, color: K.red }}>{error}</div>}

      {/* ── 规则列表 ── */}
      {tab === 'list' && (
        <>
          <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: K.text }}>已启用 {rules.filter((r) => r.enabled).length} / {rules.length} 条规则</span>
              <span style={{ fontSize: 11, color: K.muted }}>检查代码（可选，逗号分隔）</span>
              <input value={checkSymbols} onChange={(e) => setCheckSymbols(e.target.value)} placeholder="600519,000001"
                style={{ ...inputStyle, width: 180 }} />
              <button onClick={checkNow} disabled={checking} style={btn(K.blue, '#fff')}>
                {checking ? '检查中…' : '▶ 立即检查'}
              </button>
              <button onClick={testPush} disabled={pushing}
                style={{ ...btn('transparent', '#3370ff'), border: '1px solid #3370ff', fontSize: 11 }}>
                {pushing ? '发送中…' : (feishuCfg?.configured ? '📨 飞书测试推送' : '📨 飞书未配置')}
              </button>
              {feishuCfg && !feishuCfg.configured && (
                <span style={{ fontSize: 10, color: K.muted }}>配置 FEISHU_WEBHOOK_URL 环境变量后可用</span>
              )}
              {checkResult && (
                <span style={{ fontSize: 11, color: K.muted }}>
                  扫描 {checkResult.checked} 只 · 规则 {checkResult.rules} 条 · 命中 {checkResult.triggers?.length || 0} 条
                </span>
              )}
            </div>
            {checkResult?.triggers?.length > 0 && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 8 }}>
                {checkResult.triggers.map((t, i) => (
                  <div key={i} style={{ fontSize: 12, padding: '5px 8px', borderRadius: 6, background: K.hover, color: K.text }}>
                    <span style={{ color: sevColor(t.severity), fontWeight: 600 }}>[{sevLabel(t.severity)}]</span>{' '}
                    {t.rule_name} · {t.symbol} · 现价 {t.price} · {t.change_pct >= 0 ? '+' : ''}{t.change_pct}%
                  </div>
                ))}
              </div>
            )}
            {rules.length === 0 && <div style={{ fontSize: 12, color: K.muted, padding: 8 }}>暂无规则，点击右上角「新建规则」创建</div>}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {rules.map((r) => (
                <div key={r.id} style={{ border: `1px solid ${K.borderLight}`, borderRadius: 8, padding: '8px 10px' }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: K.text }}>{r.name}</span>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: K.hover, color: sevColor(r.severity) }}>{sevLabel(r.severity)}</span>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: K.hover, color: K.secondary }}>{r.type === 'signal' ? '信号' : '价格'}</span>
                    <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: K.hover, color: K.secondary }}>{r.scope === 'all' ? '全池扫描' : `${(r.symbols || []).length} 只`}</span>
                    <span style={{ fontSize: 10, color: K.muted }}>冷却 {(r.cooldown_seconds || 3600) / 60}min</span>
                    {(r.webhook_channels || []).includes('feishu') && (
                      <span style={{ fontSize: 10, padding: '1px 6px', borderRadius: 4, background: K.hover, color: '#3370ff' }}>飞书推送</span>
                    )}
                    <span style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
                      <button onClick={() => toggleEnabled(r)}
                        style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: `1px solid ${r.enabled ? K.up : K.borderLight}`, background: 'transparent', color: r.enabled ? K.up : K.secondary }}>
                        {r.enabled ? '启用中' : '已停用'}
                      </button>
                      <button onClick={() => { setForm({ ...r, symbols_text: (r.symbols || []).join(',') }); setTab('new'); }}
                        style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: `1px solid ${K.borderLight}`, background: 'transparent', color: K.secondary }}>编辑</button>
                      <button onClick={() => remove(r.id)}
                        style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: `1px solid ${K.red}`, background: 'transparent', color: K.red }}>删除</button>
                    </span>
                  </div>
                  <div style={{ fontSize: 11, color: K.secondary, marginTop: 4 }}>
                    {r.conditions.map((c, i) => (
                      <span key={i}>{i > 0 && <span style={{ color: K.blue, fontWeight: 700, margin: '0 4px' }}>{r.logic.toUpperCase()}</span>}
                        <span style={{ color: K.text }}>{condText(c)}</span>
                      </span>
                    ))}
                  </div>
                  {r.message && <div style={{ fontSize: 11, color: K.muted, marginTop: 2 }}>推送: {r.message}</div>}
                </div>
              ))}
            </div>
          </div>
        </>
      )}

      {/* ── 新建/编辑 ── */}
      {tab === 'new' && form && (
        <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
            <label style={{ fontSize: 11, color: K.secondary }}>ID
              <input value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })}
                style={{ ...inputStyle, width: 160, marginLeft: 4 }} />
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>名称
              <input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                style={{ ...inputStyle, width: 160, marginLeft: 4 }} />
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>类型
              <select value={form.type} onChange={(e) => setForm({ ...form, type: e.target.value })} style={{ ...inputStyle, marginLeft: 4 }}>
                <option value="price">价格</option>
                <option value="signal">信号</option>
              </select>
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>作用范围
              <select value={form.scope} onChange={(e) => setForm({ ...form, scope: e.target.value })} style={{ ...inputStyle, marginLeft: 4 }}>
                <option value="symbols">指定代码</option>
                <option value="all">全候选池</option>
              </select>
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>逻辑
              <select value={form.logic} onChange={(e) => setForm({ ...form, logic: e.target.value })} style={{ ...inputStyle, marginLeft: 4 }}>
                <option value="and">AND（全部满足）</option>
                <option value="or">OR（任一满足）</option>
              </select>
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>级别
              <select value={form.severity} onChange={(e) => setForm({ ...form, severity: e.target.value })} style={{ ...inputStyle, marginLeft: 4 }}>
                {SEVERITIES.map((s) => <option key={s.id} value={s.id}>{s.label}</option>)}
              </select>
            </label>
            <label style={{ fontSize: 11, color: K.secondary }}>冷却(秒)
              <input type="number" min={0} value={form.cooldown_seconds} onChange={(e) => setForm({ ...form, cooldown_seconds: parseInt(e.target.value) || 0 })}
                style={{ ...inputStyle, width: 90, marginLeft: 4 }} />
            </label>
            <label style={{ fontSize: 11, color: K.secondary, display: 'flex', alignItems: 'center', gap: 4 }}>
              <input type="checkbox" checked={(form.webhook_channels || []).includes('feishu')}
                onChange={(e) => {
                  const cur = form.webhook_channels || [];
                  setForm({ ...form, webhook_channels: e.target.checked ? [...cur, 'feishu'] : cur.filter((c) => c !== 'feishu') });
                }} />
              飞书推送
              {!feishuCfg?.configured && <span style={{ fontSize: 10, color: K.muted }}>(未配置)</span>}
            </label>
          </div>

          {form.scope === 'symbols' && (
            <div>
              <div style={{ fontSize: 11, color: K.secondary, marginBottom: 4 }}>监控代码（逗号分隔）</div>
              <input value={form.symbols_text || ''} onChange={(e) => setForm({ ...form, symbols_text: e.target.value })} placeholder="600519,000001"
                style={{ ...inputStyle, width: '100%' }} />
            </div>
          )}

          {/* 条件行 */}
          <div>
            <div style={{ fontSize: 11, color: K.secondary, marginBottom: 4 }}>条件（最多 8 条）</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              {form.conditions.map((c, i) => (
                <div key={i} style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap' }}>
                  {i > 0 && <span style={{ fontSize: 11, fontWeight: 700, color: K.blue, width: 40 }}>{form.logic.toUpperCase()}</span>}
                  <select value={c.field} onChange={(e) => setCond(i, { field: e.target.value, op: FIELDS.find((f) => f.id === e.target.value)?.truth ? 'truth' : c.op })}
                    style={{ ...inputStyle, width: 170 }}>
                    {FIELDS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                  </select>
                  {TRUTH_FIELDS.includes(c.field) ? (
                    <span style={{ fontSize: 11, color: K.secondary }}>成立（true）</span>
                  ) : (
                    <>
                      <select value={c.op} onChange={(e) => setCond(i, { op: e.target.value })}
                        style={{ ...inputStyle, width: 64 }}>
                        {OPS.map((o) => <option key={o} value={o}>{o}</option>)}
                      </select>
                      <input type="number" step="any" value={c.value} onChange={(e) => setCond(i, { value: parseFloat(e.target.value) })}
                        style={{ ...inputStyle, width: 100 }} />
                    </>
                  )}
                  <button onClick={() => setForm({ ...form, conditions: form.conditions.filter((_, j) => j !== i) })}
                    style={{ padding: '2px 8px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: `1px solid ${K.borderLight}`, background: 'transparent', color: K.muted }}>
                    ✕
                  </button>
                  {FIELDS.find((f) => f.id === c.field)?.hint && (
                    <span style={{ fontSize: 10, color: K.muted }}>{FIELDS.find((f) => f.id === c.field).hint}</span>
                  )}
                </div>
              ))}
            </div>
            {form.conditions.length < 8 && (
              <button onClick={() => setForm({ ...form, conditions: [...form.conditions, { ...emptyCond }] })}
                style={{ marginTop: 6, padding: '3px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer', border: `1px dashed ${K.borderLight}`, background: 'transparent', color: K.secondary }}>
                ＋ 添加条件
              </button>
            )}
          </div>

          <div>
            <div style={{ fontSize: 11, color: K.secondary, marginBottom: 4 }}>推送消息（可选）</div>
            <input value={form.message || ''} onChange={(e) => setForm({ ...form, message: e.target.value })} placeholder="触发后推送的内容模板"
              style={{ ...inputStyle, width: '100%' }} />
          </div>

          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={save} disabled={saving} style={btn(K.blue, '#fff')}>{saving ? '保存中…' : '💾 保存规则'}</button>
            <button onClick={() => { setForm(null); setTab('list'); }} style={{ ...btn('transparent', K.secondary), border: `1px solid ${K.borderLight}` }}>取消</button>
          </div>
        </div>
      )}

      {/* ── 触发日志 ── */}
      {tab === 'logs' && (
        <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 12 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 8 }}>
            触发日志
            <button onClick={loadLogs} style={{ ...btn('transparent', K.secondary), border: `1px solid ${K.borderLight}`, marginLeft: 8, padding: '2px 10px' }}>刷新</button>
          </div>
          {logs.length === 0 && <div style={{ fontSize: 12, color: K.muted, padding: 8 }}>暂无触发记录</div>}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {logs.map((l, i) => (
              <div key={i} style={{ fontSize: 12, padding: '6px 8px', borderRadius: 6, background: K.hover }}>
                <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
                  <span style={{ color: sevColor(l.severity), fontWeight: 600 }}>[{sevLabel(l.severity)}]</span>
                  <span style={{ color: K.text, fontWeight: 600 }}>{l.rule_name}</span>
                  <span style={{ color: K.blue }}>{l.symbol}</span>
                  <span style={{ color: K.secondary }}>{l.name}</span>
                  <span style={{ color: K.text }}>现价 {l.price}</span>
                  <span style={{ color: l.change_pct >= 0 ? K.up : K.down }}>{l.change_pct >= 0 ? '+' : ''}{l.change_pct}%</span>
                  <span style={{ color: K.muted, marginLeft: 'auto' }}>{l.ts}</span>
                </div>
                <div style={{ fontSize: 10, color: K.muted, marginTop: 2 }}>
                  {Object.entries(l.feats || {}).map(([k, v]) => (
                    <span key={k} style={{ marginRight: 8 }}>{fieldLabel(k)}={typeof v === 'number' ? v.toFixed(3) : String(v)}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
