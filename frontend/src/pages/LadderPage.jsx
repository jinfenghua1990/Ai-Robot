/**
 * 连板梯队面板（A股）—— 移植自 tickflow-stock-panel 的连板梯队设计
 * 分层：首板 / 2连板 / 3连板 / 高位板(≥4) + 炸板预警 + 情绪温度
 */
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '../utils/request';

const LEVEL_COLORS = { 4: 'var(--accent-red)', 3: '#f59e0b', 2: '#3b82f6', 1: '#22c55e' };

export default function LadderPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [tradeDate, setTradeDate] = useState('');
  const [rotation, setRotation] = useState(null);

  const K = {
    panel: 'var(--bg-card)', border: 'var(--border-color)', borderLight: 'var(--border-light)',
    text: 'var(--text-primary)', secondary: 'var(--text-secondary)', muted: 'var(--text-muted)',
    up: 'var(--flow-up)', down: 'var(--flow-down)', blue: 'var(--accent-blue)',
    hover: 'var(--bg-hover)', red: 'var(--accent-red)',
  };

  const load = useCallback(async (bypass = false) => {
    setLoading(true);
    setError('');
    try {
      const qs = [];
      if (tradeDate) qs.push(`trade_date=${tradeDate}`);
      if (bypass) qs.push('nocache=1');
      const q = qs.length ? `?${qs.join('&')}` : '';
      const res = await apiFetch(`/api/ladder/board${q}`, {}, 30000);
      if (res?.ok && res.data?.ok && res.data.data) setData(res.data.data);
      else setError(res.data?.error || res?.error || '加载失败');
    } catch (e) { setError(String(e.message || e)); }
    finally { setLoading(false); }
  }, [tradeDate]);

  useEffect(() => { load(); }, [load]);

  // 概念轮动（板块涨停家数排名矩阵 → 主线/新晋/退潮）
  const loadRotation = useCallback(async (bypass = false) => {
    try {
      const rq = bypass ? '?days=12&nocache=1' : '?days=12';
      const res = await apiFetch(`/api/ladder/rotation${rq}`, {}, 30000);
      if (res?.ok && res.data?.ok && res.data.data) setRotation(res.data.data);
    } catch {}
  }, []);

  useEffect(() => { loadRotation(); }, [loadRotation]);

  const rot = rotation?.signals || {};
  const rotSummary = rotation?.summary || {};
  const rankStr = (r) => (r.ranks || []).map((x) => (x >= 999 ? '—' : x)).join('→');

  const s = data?.summary || {};
  const momentumColor = s.board_momentum === '升温' ? K.up : s.board_momentum === '降温' ? K.down : K.secondary;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxWidth: 1280, margin: '0 auto', padding: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: K.text }}>
          连板梯队 · {s.date || ''}
          <span style={{ fontSize: 11, fontWeight: 400, color: K.muted, marginLeft: 8 }}>
            移植自 tickflow-stock-panel · 层级梯队 + 炸板预警 + 情绪温度
          </span>
        </div>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 8, alignItems: 'center' }}>
          <input type="date" value={tradeDate} onChange={(e) => setTradeDate(e.target.value)}
            style={{ background: K.hover, border: `1px solid ${K.borderLight}`, borderRadius: 6, padding: '4px 8px', color: K.text, fontSize: 12 }} />
          <button onClick={() => { load(true); loadRotation(true); }} disabled={loading}
            title="盘后快照已缓存，点此跳过缓存强制重算"
            style={{ padding: '6px 14px', borderRadius: 8, fontSize: 12, cursor: 'pointer', background: K.blue, color: '#fff', border: 'none' }}>
            {loading ? '加载中…' : '↻ 刷新'}
          </button>
        </div>
      </div>

      {error && <div style={{ fontSize: 12, color: K.red }}>{error}</div>}

      {/* 情绪总览 */}
      {data && (
        <>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '10px 12px' }}>
              <div style={{ fontSize: 11, color: K.muted }}>当日涨停</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: K.up }}>{s.total_limit_up ?? '—'}</div>
              {s.yesterday && <div style={{ fontSize: 10, color: K.muted }}>昨日 {s.yesterday.total_limit_up ?? '—'}</div>}
            </div>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '10px 12px' }}>
              <div style={{ fontSize: 11, color: K.muted }}>高位板 (≥3连板)</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: K.red }}>{s.high_board_count ?? '—'}</div>
              {s.yesterday && <div style={{ fontSize: 10, color: K.muted }}>昨日 {s.yesterday.high_board_count ?? '—'}</div>}
            </div>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '10px 12px' }}>
              <div style={{ fontSize: 11, color: K.muted }}>情绪温度</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: momentumColor }}>{s.board_momentum || '—'}</div>
              {s.prev_date && <div style={{ fontSize: 10, color: K.muted }}>对比 {s.prev_date}</div>}
            </div>
            <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: '10px 12px' }}>
              <div style={{ fontSize: 11, color: K.muted }}>炸板预警</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: '#f59e0b' }}>{data.broken_board?.length || 0}</div>
              <div style={{ fontSize: 10, color: K.muted }}>盘中触板未封住</div>
            </div>
          </div>

          {/* 梯队分层 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {(data.ladders || []).map((lv) => {
              const color = LEVEL_COLORS[lv.level] || K.secondary;
              return (
                <div key={lv.level} style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 10 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 6 }}>
                    <span style={{ fontSize: 10, fontWeight: 700, color: '#fff', background: color, borderRadius: 4, padding: '1px 8px' }}>{lv.label}</span>
                    <span style={{ fontSize: 12, color: K.secondary }}>{lv.count} 只</span>
                    {lv.level === 4 && lv.count > 0 && (
                      <span style={{ fontSize: 11, color: K.red }}>🔥 市场高度</span>
                    )}
                  </div>
                  {(lv.stocks || []).length === 0 && <div style={{ fontSize: 11, color: K.muted, padding: '4px 2px' }}>无</div>}
                  <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                    {(lv.stocks || []).map((st) => (
                      <div key={st.ts_code} title={`${st.name} · ${st.sector || ''}`}
                        style={{ border: `1px solid ${K.borderLight}`, borderRadius: 8, padding: '5px 10px', background: K.hover, cursor: 'pointer' }}
                        onClick={() => window.open(`/stock-analysis?code=${st.code}`, '_blank')}>
                        <div style={{ fontSize: 13, fontWeight: 700, color: color }}>{st.name}</div>
                        <div style={{ fontSize: 10, color: K.muted }}>{st.code} · {st.boards}连板</div>
                        <div style={{ fontSize: 10, color: st.change_pct >= 0 ? K.up : K.down }}>{st.change_pct >= 0 ? '+' : ''}{st.change_pct}%</div>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>

          {/* 概念轮动（板块涨停家数排名矩阵） */}
          <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 6 }}>
              🔄 概念轮动 <span style={{ fontSize: 11, fontWeight: 400, color: K.muted }}>近 12 日板块涨停家数排名矩阵 · 排名越小越强</span>
              {rotSummary.main_lines?.length > 0 && (
                <span style={{ fontSize: 11, marginLeft: 8, color: K.up }}>主线: {rotSummary.main_lines.join('、')}</span>
              )}
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 8 }}>
              {!rotation && <div style={{ fontSize: 11, color: K.muted, padding: '4px 2px', gridColumn: '1 / -1' }}>概念轮动计算中…</div>}
              {[
                ['🎯 主线（连续霸榜）', rot.persistent_leaders || [], K.red],
                ['🆕 新晋强势（排名跃升）', rot.rising || [], '#f59e0b'],
                ['📉 退潮预警（高位滑落）', rot.fading || [], K.down],
                ['🏛️ 机构特征（排名稳定）', rot.institutional || [], K.blue],
                ['🎰 游资特征（排名波动大）', rot.hot_money || [], '#a855f7'],
              ].map(([title, items, color]) => (
                <div key={title} style={{ border: `1px solid ${K.borderLight}`, borderRadius: 8, padding: '8px 10px', background: K.hover }}>
                  <div style={{ fontSize: 11, fontWeight: 700, color, marginBottom: 4 }}>{title}</div>
                  {items.length === 0 && <div style={{ fontSize: 10, color: K.muted }}>无明显信号</div>}
                  {items.map((s) => (
                    <div key={s.name} style={{ fontSize: 11, color: K.text, padding: '2px 0', display: 'flex', gap: 6, alignItems: 'baseline' }}>
                      <span style={{ fontWeight: 600 }}>{s.name}</span>
                      <span style={{ color: K.muted, fontSize: 10 }}>排名 {rankStr(s)}</span>
                      <span style={{ color: K.secondary, fontSize: 10 }}>均{s.avg_rank} σ{s.rank_std}</span>
                    </div>
                  ))}
                </div>
              ))}
            </div>
          </div>

          {/* 炸板预警 */}
          <div style={{ background: K.panel, border: `1px solid ${K.border}`, borderRadius: 10, padding: 10 }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: K.text, marginBottom: 6 }}>
              ⚠️ 炸板预警 <span style={{ fontSize: 11, fontWeight: 400, color: K.muted }}>盘中触及涨停价但收盘未封住</span>
            </div>
            {data.broken_board?.length === 0 && <div style={{ fontSize: 11, color: K.muted, padding: '4px 2px' }}>今日无炸板</div>}
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {(data.broken_board || []).map((st) => (
                <div key={st.ts_code} title={st.sector || ''}
                  style={{ border: `1px solid ${K.borderLight}`, borderRadius: 8, padding: '5px 10px', background: K.hover, cursor: 'pointer' }}
                  onClick={() => window.open(`/stock-analysis?code=${st.code}`, '_blank')}>
                  <div style={{ fontSize: 13, fontWeight: 700, color: '#f59e0b' }}>{st.name}</div>
                  <div style={{ fontSize: 10, color: K.muted }}>{st.code} · 最高{st.boards}连板</div>
                  <div style={{ fontSize: 10, color: K.down }}>{st.change_pct >= 0 ? '+' : ''}{st.change_pct}%</div>
                </div>
              ))}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
