import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { usNameCN } from '../utils/usStockNames';
import { openStockAnalysis } from '../utils/openStockAnalysis';

const K = {
  panel: 'var(--bg-card)',
  border: 'var(--border-color)',
  borderLight: 'var(--border-light)',
  text: 'var(--text-primary)',
  secondary: 'var(--text-secondary)',
  muted: 'var(--text-muted)',
  up: 'var(--flow-up)',
  down: 'var(--flow-down)',
  hover: 'var(--bg-hover)',
};

const fmt = (v, d = 2) => (v == null || Number.isNaN(v) ? '—' : Number(v).toFixed(d));
const fmtBig = (v) => {
  if (v == null) return '—';
  if (v >= 1e12) return (v / 1e12).toFixed(2) + 'T';
  if (v >= 1e8) return (v / 1e8).toFixed(2) + '亿';
  if (v >= 1e4) return (v / 1e4).toFixed(1) + '万';
  return String(v);
};

function Panel({ title, extra, children, style }) {
  return (
    <div style={{ background: K.panel, border: '1px solid ' + K.border, borderRadius: 10, padding: '14px 16px', ...style }}>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: 10 }}>
        <span style={{ fontSize: 13, fontWeight: 600, color: K.text }}>{title}</span>
        {extra && <span style={{ marginLeft: 'auto' }}>{extra}</span>}
      </div>
      {children}
    </div>
  );
}

export default function UsPremarketPage() {
  const navigate = useNavigate();
  const [pmData, setPmData] = useState(null);
  const [pmSort, setPmSort] = useState('move');
  const [pmCollapsed, setPmCollapsed] = useState(false);
  const [watchlist, setWatchlist] = useState([]);
  const [positions, setPositions] = useState([]);

  useEffect(() => {
    const loadPm = () => {
      apiFetch('/api/us-stock-analysis/premarket').then((res) => {
        if (res?.ok && res.data?.ok) setPmData(res.data);
      }).catch(() => {});
    };
    loadPm();
    const t = setInterval(loadPm, 30000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    apiFetch('/api/us-stock-analysis/watchlist').then((res) => {
      if (res?.ok && res.data?.ok) setWatchlist(res.data.symbols || []);
    }).catch(() => {});
    apiFetch('/api/usmart-sync/positions').then((res) => {
      const list = res?.ok && Array.isArray(res.data) ? res.data : (res?.data?.positions || []);
      setPositions(list);
    }).catch(() => {});
  }, []);

  const stocks = pmSort === 'move'
    ? [...(pmData?.stocks || [])].sort((a, b) => Math.abs(b.chg_pct ?? 0) - Math.abs(a.chg_pct ?? 0))
    : pmSort === 'up'
      ? [...(pmData?.stocks || [])].sort((a, b) => (b.chg_pct ?? 0) - (a.chg_pct ?? 0))
      : pmSort === 'down'
        ? [...(pmData?.stocks || [])].sort((a, b) => (a.chg_pct ?? 0) - (b.chg_pct ?? 0))
        : [...(pmData?.stocks || [])].sort((a, b) => (b.vol ?? 0) - (a.vol ?? 0));

  const goToAnalysis = (symbol) => {
    openStockAnalysis(symbol, 'us');
  };

  return (
    <div style={{ padding: 16, maxWidth: 1460, margin: '0 auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14, flexWrap: 'wrap', gap: 8 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: K.text }}>📊 盘前策略</h2>
          {pmData?.session && (
            <span style={{
              fontSize: 12, fontWeight: 600, padding: '3px 10px', borderRadius: 6,
              background: pmData.session === '盘中' ? 'rgba(0,200,83,.12)' : pmData.session === '盘前' ? 'rgba(64,158,255,.12)' : 'rgba(156,39,176,.12)',
              color: pmData.session === '盘中' ? '#00c853' : pmData.session === '盘前' ? '#409eff' : '#9c27b0',
              border: '1px solid ' + (pmData.session === '盘中' ? 'rgba(0,200,83,.3)' : pmData.session === '盘前' ? 'rgba(64,158,255,.3)' : 'rgba(156,39,176,.3)'),
            }}>{pmData.session}</span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11, color: K.muted }}>
          {pmData?.us_time && <span>🇺🇸 {pmData.us_time}</span>}
          <span>🕐 {pmData?.sgt_time?.slice(11, 16) || '—'} 更新</span>
          <span style={{ fontSize: 11, color: K.muted }}>· 30s 自动刷新</span>
        </div>
      </div>

      <div style={{ display: 'flex', gap: 14 }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <Panel title="📈 大盘风向标" extra={<span style={{ fontSize: 11, color: K.muted }}>实时 · 盘前/盘中/盘后</span>}>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {(pmData?.market || []).map(m => (
                <span key={m.symbol} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, background: K.hover, borderRadius: 7, padding: '4px 10px' }}>
                  <span style={{ color: K.text, fontWeight: 600 }}>{m.symbol}</span>
                  <span style={{ color: (m.chg_pct ?? 0) >= 0 ? K.up : K.down, fontWeight: 700 }}>
                    {(m.chg_pct ?? 0) > 0 ? '+' : ''}{fmt(m.chg_pct, 2)}%
                  </span>
                  <span style={{ color: K.muted }}>{fmt(m.price)}</span>
                </span>
              ))}
              {!pmData?.market?.length && <span style={{ fontSize: 12, color: K.muted }}>暂无大盘数据</span>}
            </div>
          </Panel>

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, margin: '12px 0 8px' }}>
            <span style={{ fontSize: 12, fontWeight: 600, color: K.text }}>自选池盘前行情</span>
            <span style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              {[['move', '异动'], ['up', '涨幅'], ['down', '跌幅'], ['vol', '量能']].map(([k, l]) => (
                <button key={k} onClick={() => setPmSort(k)} style={{
                  fontSize: 11, padding: '3px 10px', borderRadius: 6, cursor: 'pointer',
                  border: '1px solid ' + (pmSort === k ? 'var(--accent-blue)' : K.border),
                  background: pmSort === k ? 'var(--accent-blue)' : K.panel,
                  color: pmSort === k ? '#fff' : K.secondary,
                }}>{l}</button>
              ))}
              <button onClick={() => setPmCollapsed(v => !v)} style={{ fontSize: 11, padding: '3px 10px', borderRadius: 6, cursor: 'pointer', border: '1px solid ' + K.border, background: K.panel, color: K.secondary }}>{pmCollapsed ? '展开' : '收起'}</button>
            </span>
          </div>

          <div style={{ background: K.panel, border: '1px solid ' + K.border, borderRadius: 10, overflow: 'hidden' }}>
            {!pmCollapsed && (
              <>
                <div style={{ display: 'flex', gap: 8, fontSize: 10.5, color: K.muted, padding: '8px 12px', borderBottom: '1px solid ' + K.borderLight }}>
                  <span style={{ width: 22 }}>#</span>
                  <span style={{ flex: 1.3 }}>名称</span>
                  <span style={{ width: 72, textAlign: 'right' }}>盘前涨跌</span>
                  <span style={{ width: 64, textAlign: 'right' }}>现价</span>
                  <span style={{ width: 72, textAlign: 'right' }}>盘前量</span>
                  <span style={{ width: 110, textAlign: 'right' }}>盘前区间</span>
                  <span style={{ width: 80 }}>信号</span>
                </div>
                <div style={{ maxHeight: 560, overflowY: 'auto' }}>
                  {stocks.map((st, i) => {
                    const pct = st.chg_pct ?? 0;
                    const vol = st.vol ?? 0;
                    const volMed = (() => {
                      const vols = (pmData?.stocks || []).map(s => s.vol || 0).filter(v => v > 0).sort((a, b) => a - b);
                      return vols.length ? vols[Math.floor(vols.length / 2)] : 0;
                    })();
                    const hotVol = volMed > 0 && vol > volMed * 3;
                    const thin = vol > 0 && vol < 1000;
                    const pos = st.pos_in_range;
                    const signals = [
                      hotVol ? '放量' : null,
                      thin ? '清淡' : null,
                      pos != null && pos >= 90 ? '贴高' : null,
                      pos != null && pos <= 10 ? '贴低' : null,
                    ].filter(Boolean);
                    return (
                      <div key={st.symbol} style={{ display: 'flex', gap: 8, alignItems: 'center', fontSize: 12, padding: '5px 12px', cursor: 'pointer', borderBottom: '1px solid ' + K.borderLight }}
                        onClick={() => goToAnalysis(st.symbol)}
                        onMouseEnter={(e) => e.currentTarget.style.background = K.hover}
                        onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                        <span style={{ width: 22, color: K.muted, fontSize: 10.5 }}>{i + 1}</span>
                        <span style={{ flex: 1.3, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          <span style={{ color: K.text, fontWeight: 600 }}>{usNameCN(st.symbol) || st.name || st.symbol}</span>
                          <span style={{ color: K.muted, fontSize: 10.5, marginLeft: 5 }}>{st.symbol}</span>
                        </span>
                        <span style={{ width: 72, textAlign: 'right', fontSize: 13, fontWeight: 700, color: pct > 0 ? K.up : pct < 0 ? K.down : K.muted }}>
                          {pct > 0 ? '+' : ''}{fmt(pct, 2)}%
                        </span>
                        <span style={{ width: 64, textAlign: 'right', color: K.text, fontWeight: 600 }}>{fmt(st.price)}</span>
                        <span style={{ width: 72, textAlign: 'right', color: vol > 0 ? K.text : K.muted }}>{vol > 0 ? fmtBig(Math.round(vol)) : '—'}</span>
                        <span style={{ width: 110, textAlign: 'right', color: K.muted, fontSize: 11 }}>{st.low != null ? fmt(st.low) + ' — ' + fmt(st.high) : '—'}</span>
                        <span style={{ width: 80, display: 'flex', gap: 3 }}>
                          {signals.map(sg => (
                            <span key={sg} style={{ fontSize: 10, padding: '1px 5px', borderRadius: 4, border: '1px solid ' + K.borderLight, color: sg === '放量' ? 'var(--accent-blue)' : K.muted, background: K.hover }}>{sg}</span>
                          ))}
                        </span>
                      </div>
                    );
                  })}
                  {!stocks.length && (
                    <div style={{ padding: 20, textAlign: 'center', fontSize: 12, color: K.muted }}>
                      {pmData ? '暂无盘前数据（可能停牌或无行情）' : '加载盘前数据…'}
                    </div>
                  )}
                </div>
              </>
            )}
            {pmCollapsed && (
              <div style={{ padding: 20, textAlign: 'center', fontSize: 12, color: K.muted }}>
                已收起 · 点击「展开」查看 {stocks.length} 只自选股盘前行情
              </div>
            )}
          </div>
        </div>

        <div style={{ width: 220, flexShrink: 0, display: 'flex', flexDirection: 'column', gap: 14 }}>
          <Panel title="⭐ 自选池" extra={<span style={{ fontSize: 11, color: K.muted }}>{watchlist.length}</span>}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 300, overflowY: 'auto' }}>
              {watchlist.map(sym => (
                <button key={sym} onClick={() => goToAnalysis(sym)} style={{
                  textAlign: 'left', cursor: 'pointer', border: 'none', borderRadius: 6,
                  background: 'transparent', color: K.text, fontSize: 12, padding: '4px 6px',
                }} onMouseEnter={(e) => e.currentTarget.style.background = K.hover}
                   onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                  <span style={{ fontWeight: 600 }}>{usNameCN(sym) || sym}</span>
                  <span style={{ marginLeft: 6, fontSize: 10, color: K.muted }}>{sym}</span>
                </button>
              ))}
              {!watchlist.length && <span style={{ fontSize: 12, color: K.muted }}>自选池为空</span>}
            </div>
          </Panel>

          <Panel title="💼 美股持仓" extra={<span style={{ fontSize: 11, color: K.muted }}>{positions.length}</span>}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 2, maxHeight: 300, overflowY: 'auto' }}>
              {positions.map(p => (
                <button key={p.symbol} onClick={() => goToAnalysis(p.symbol)} style={{
                  textAlign: 'left', cursor: 'pointer', border: 'none', borderRadius: 6,
                  background: 'transparent', color: K.text, fontSize: 12, padding: '4px 6px',
                }} onMouseEnter={(e) => e.currentTarget.style.background = K.hover}
                   onMouseLeave={(e) => e.currentTarget.style.background = 'transparent'}>
                  <span style={{ fontWeight: 600 }}>{p.name || p.symbol}</span>
                  <span style={{ marginLeft: 6, fontSize: 10, color: K.muted }}>{p.symbol}</span>
                  <span style={{ float: 'right', fontSize: 10, color: K.muted }}>×{p.quantity || 0}</span>
                </button>
              ))}
              {!positions.length && <span style={{ fontSize: 12, color: K.muted }}>暂无持仓</span>}
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
