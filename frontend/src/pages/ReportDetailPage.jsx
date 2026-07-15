import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

/* ---------- 设计系统元数据 ---------- */
const SOURCE_META = {
  tdx:       { label: '通达信', icon: '📊', color: '#3b82f6', soft: 'rgba(59,130,246,0.10)' },
  ifind:     { label: '同花顺', icon: '📈', color: '#a855f7', soft: 'rgba(168,85,247,0.10)' },
};

const RATING_META = {
  '买入': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.14)', border: 'rgba(22,163,74,0.35)' },
  '增持': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.10)', border: 'rgba(22,163,74,0.30)' },
  '强烈推荐': { color: 'var(--accent-green)', bg: 'rgba(22,163,74,0.14)', border: 'rgba(22,163,74,0.35)' },
  '持有': { color: 'var(--accent-amber)', bg: 'rgba(217,119,6,0.14)', border: 'rgba(217,119,6,0.35)' },
  '中性': { color: 'var(--text-muted)', bg: 'rgba(100,116,139,0.12)', border: 'rgba(100,116,139,0.30)' },
  '减持': { color: 'var(--accent-red)', bg: 'rgba(220,38,38,0.10)', border: 'rgba(220,38,38,0.30)' },
  '卖出': { color: 'var(--accent-red)', bg: 'rgba(220,38,38,0.14)', border: 'rgba(220,38,38,0.35)' },
};

const flowColor = (v) => {
  if (v == null) return 'var(--text-muted)';
  if (typeof v === 'number') return v >= 0 ? 'var(--flow-up)' : 'var(--flow-down)';
  return String(v).includes('+') ? 'var(--flow-up)' : 'var(--flow-down)';
};
const fmtPct = (v) => {
  if (v == null) return '—';
  if (typeof v === 'number') return `${v >= 0 ? '+' : ''}${v.toFixed(2)}%`;
  return String(v);
};

/* 通用区块卡片 */
const SectionCard = ({ title, icon, color, children, className }) => (
  <div className={`premium-card p-3 ${className || ''}`}>
    <div className="flex items-center gap-1.5 mb-2.5">
      <span className="w-1 h-3.5 rounded" style={{ background: color }} />
      <span className="text-[12px] font-bold" style={{ color }}>{icon} {title}</span>
    </div>
    {children}
  </div>
);

/* 迷你指标块 */
const Stat = ({ label, value, color, sub }) => (
  <div className="rounded-xl px-2.5 py-2" style={{ background: 'var(--bg-hover)' }}>
    <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{label}</div>
    <div className="text-[14px] font-bold leading-tight" style={{ color: color || 'var(--text-primary)' }}>{value}</div>
    {sub && <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>{sub}</div>}
  </div>
);

export default function ReportDetailPage() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      const { ok, data } = await apiFetch(`/api/analysis/result/${reportId}`);
      if (ok) setReport(data.result);
      setLoading(false);
    })();
  }, [reportId]);

  if (loading) return (
    <div className="flex items-center justify-center h-96">
      <div className="text-[12px] flex items-center gap-2" style={{ color: 'var(--text-muted)' }}>
        <span className="pulse-dot" /> 加载报告…
      </div>
    </div>
  );

  if (!report) return (
    <div className="flex items-center justify-center h-96">
      <div className="text-center">
        <div className="text-4xl mb-3">📄</div>
        <div className="text-[14px]" style={{ color: 'var(--text-secondary)' }}>报告未找到</div>
        <button onClick={() => navigate('/research-center')}
          className="mt-3 px-3 py-1.5 rounded-lg text-[12px] transition hover:opacity-70"
          style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>
          ← 返回研报中心
        </button>
      </div>
    </div>
  );

  const src = SOURCE_META[report.source] || SOURCE_META.tdx;
  const s = report.summary || {};
  const q = report.quotes || {};
  const k = report.kline_analysis || {};
  const f = report.financials || {};
  const rm = s.rating ? (RATING_META[s.rating] || RATING_META['中性']) : null;

  /* 复盘报告：简化版布局 */
  if (report.source === 'recap') {
    const idx = report.indices || {};
    return (
      <div className="space-y-3 max-w-4xl mx-auto">
        <div className="flex items-center gap-2">
          <button onClick={() => navigate('/research-center')}
            className="px-2.5 py-1 rounded-lg text-[12px] transition hover:opacity-70"
            style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>← 研报中心</button>
          <span className="text-[11px] px-2 py-0.5 rounded-full" style={{ background: 'rgba(44,86,186,0.10)', color: '#2c56ba' }}>📆 A股市场日报</span>
        </div>

        <div className="premium-card hero-grad p-5 fade-in">
          <div className="text-[18px] font-bold gradient-text">盘后复盘 · {report.date}</div>
          <div className="text-[11px] mt-1" style={{ color: 'var(--text-muted)' }}>{report.report_type}</div>

          <div className="mt-4 flex gap-5 overflow-x-auto pb-1">
            {Object.entries(idx).length === 0 && (
              <div className="text-[12px]" style={{ color: 'var(--text-muted)' }}>盘后数据采集中…</div>
            )}
            {Object.entries(idx).map(([name, v]) => (
              <div key={name} className="text-center px-3">
                <div className="text-[11px]" style={{ color: 'var(--text-muted)' }}>{name}</div>
                <div className="text-[20px] font-bold" style={{ color: flowColor(v.change_pct) }}>{v.price?.toFixed(0)}</div>
                <div className="text-[12px] font-semibold" style={{ color: flowColor(v.change_pct) }}>{fmtPct(v.change_pct)}</div>
              </div>
            ))}
          </div>

          {s.key_points?.length > 0 && (
            <div className="mt-4 space-y-1.5">
              {s.key_points.map((p, i) => (
                <div key={i} className="flex items-start gap-2 text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                  <span style={{ color: '#2c56ba', flexShrink: 0 }}>•</span><span>{p}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="text-center text-[10px] py-2" style={{ color: 'var(--text-muted)' }}>
          {report.disclaimer || '盘后复盘基于公开数据生成，仅供参考，不构成投资建议'}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3 max-w-4xl mx-auto">
      {/* 顶部导航 */}
      <div className="flex items-center gap-2 flex-wrap">
        <button onClick={() => navigate('/research-center')}
          className="px-2.5 py-1 rounded-lg text-[12px] transition hover:opacity-70"
          style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>← 研报中心</button>
        <button onClick={() => navigate(`/stock/${report.stock_code}`)}
          className="px-2.5 py-1 rounded-lg text-[12px] transition hover:opacity-70"
          style={{ border: '1px solid var(--border-color)', color: 'var(--text-secondary)' }}>📈 个股详情</button>
        <span className="ml-auto text-[11px] px-2 py-0.5 rounded-full" style={{ background: src.soft, color: src.color }}>
          {src.icon} {src.label}分析
        </span>
      </div>

      {/* Hero 摘要卡 */}
      <div className="premium-card hero-grad p-4 fade-in">
        <div className="flex items-start justify-between gap-3 flex-wrap">
          <div>
            <div className="flex items-center gap-2">
              <span className="text-[22px] font-bold" style={{ color: 'var(--text-primary)' }}>{report.stock_name}</span>
              <span className="text-[12px]" style={{ color: 'var(--text-muted)' }}>{report.stock_code}</span>
            </div>
            <div className="text-[11px] mt-0.5" style={{ color: 'var(--text-muted)' }}>
              {report.created_at?.slice(0, 10)} {report.created_at?.slice(11, 16)} · {report.report_type}
            </div>
          </div>
          <div className="flex items-center gap-2">
            {rm && (
              <span className="text-[14px] font-bold px-3 py-1.5 rounded-xl"
                style={{ background: rm.bg, color: rm.color, border: `1px solid ${rm.border}` }}>{s.rating}</span>
            )}
            {s.target_price && (
              <div className="text-right">
                <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>目标价</div>
                <div className="text-[14px] font-bold" style={{ color: 'var(--accent-blue)' }}>{s.target_price}</div>
              </div>
            )}
            {s.confidence && (
              <div className="text-right">
                <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>置信度</div>
                <div className="text-[14px] font-bold" style={{ color: 'var(--text-primary)' }}>{s.confidence}</div>
              </div>
            )}
          </div>
        </div>

        {s.key_points?.length > 0 && (
          <div className="mt-3 pt-3 space-y-1.5" style={{ borderTop: '1px solid var(--border-color)' }}>
            {s.key_points.map((p, i) => (
              <div key={i} className="flex items-start gap-2 text-[12px]" style={{ color: 'var(--text-secondary)' }}>
                <span style={{ color: src.color, flexShrink: 0 }}>▍</span><span>{p}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* 行情数据 */}
      {q.price != null && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Stat label="最新价" value={q.price.toFixed(2)} color={flowColor(q.change_pct)}
            sub={fmtPct(q.change_pct)} />
          <Stat label="最高 / 最低" value={`${q.high ?? '—'} / ${q.low ?? '—'}`} color="var(--text-primary)" />
          <Stat label="成交量" value={q.volume || '—'} color="var(--text-primary)" />
          <Stat label="成交额" value={q.amount || '—'} color="var(--text-primary)"
            sub={q.turnover_rate != null ? `换手 ${q.turnover_rate}%` : undefined} />
        </div>
      )}

      {/* K线 + 财务 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {k.period && (
          <SectionCard title={`K线技术分析（${k.period}）`} icon="📈" color="var(--accent-amber)">
            <div className="space-y-1.5 text-[12px]" style={{ color: 'var(--text-secondary)' }}>
              <Row label="区间涨跌幅" value={fmtPct(k.change_pct)} vcolor={flowColor(k.change_pct)} />
              <Row label="区间高低" value={`高 ${k.high_60d} · 低 ${k.low_60d}`} vcolor="var(--text-primary)" />
              {k.ma_status && <Row label="均线状态" value={k.ma_status} vcolor="var(--text-primary)" />}
              {k.support && <Row label="支撑位" value={k.support} vcolor="var(--flow-down)" />}
              {k.resistance && <Row label="压力位" value={k.resistance} vcolor="var(--flow-up)" />}
            </div>
          </SectionCard>
        )}
        {f.eps != null && (
          <SectionCard title="财务数据" icon="📊" color="var(--accent-blue)">
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-[12px]" style={{ color: 'var(--text-secondary)' }}>
              <Row label="EPS" value={f.eps} vcolor="var(--text-primary)" />
              <Row label="BPS" value={f.bps} vcolor="var(--text-primary)" />
              <Row label="PE" value={`${f.pe}x`} vcolor="var(--accent-amber)" />
              <Row label="PB" value={`${f.pb}x`} vcolor="var(--accent-amber)" />
              <Row label="总市值" value={f.market_cap} vcolor="var(--text-primary)" />
              <Row label="总股本" value={f.total_shares} vcolor="var(--text-primary)" />
              {f.revenue && <Row label="营收" value={f.revenue} vcolor="var(--text-primary)" />}
              {f.net_profit && <Row label="净利润" value={f.net_profit} vcolor="var(--text-primary)" />}
            </div>
          </SectionCard>
        )}
      </div>

      {/* 板块对比 */}
      {report.sector && (
        <SectionCard title={`板块对比 · ${report.sector.name}`} icon="🏭" color="#2c56ba"
          className="">
          <div className="flex items-center gap-3 mb-2.5 flex-wrap text-[10px]" style={{ color: 'var(--text-muted)' }}>
            <span>板块涨跌 <b style={{ color: flowColor(report.sector.sector_change_pct) }}>{report.sector.sector_change_pct}%</b></span>
            <span>热度 <b style={{ color: 'var(--text-primary)' }}>{report.sector.sector_heat}</b></span>
            <span>主力 <b style={{ color: flowColor(report.sector.sector_main_net) }}>{report.sector.sector_main_net}</b></span>
            {report.sector.rank_in_sector && <span>个股排名 <b style={{ color: 'var(--text-primary)' }}>{report.sector.rank_in_sector}</b></span>}
          </div>
          {report.sector.peer_comparison?.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-[11px]">
                <thead>
                  <tr style={{ borderBottom: '1px solid var(--border-color)', color: 'var(--text-muted)' }}>
                    <th className="text-left py-1.5 pr-2 font-medium">名称</th>
                    <th className="text-right py-1.5 px-2 font-medium">PE</th>
                    <th className="text-right py-1.5 px-2 font-medium">PB</th>
                    <th className="text-right py-1.5 px-2 font-medium">市值</th>
                    <th className="text-right py-1.5 pl-2 font-medium">涨跌幅</th>
                  </tr>
                </thead>
                <tbody>
                  {report.sector.peer_comparison.map((p, i) => (
                    <tr key={i} style={{ borderTop: '1px solid var(--border-light)' }}>
                      <td className="py-1.5 pr-2 font-medium" style={{ color: p.name === report.stock_name ? src.color : 'var(--text-primary)' }}>
                        {p.name} {p.name === report.stock_name && '◀'}
                      </td>
                      <td className="py-1.5 px-2 text-right" style={{ color: 'var(--accent-amber)' }}>{p.pe}</td>
                      <td className="py-1.5 px-2 text-right" style={{ color: 'var(--accent-amber)' }}>{p.pb}</td>
                      <td className="py-1.5 px-2 text-right" style={{ color: 'var(--text-secondary)' }}>{p.mcap}</td>
                      <td className="py-1.5 pl-2 text-right font-medium" style={{ color: flowColor(p.change) }}>{p.change}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </SectionCard>
      )}

      {/* 资金流向 */}
      {report.money_flow && (
        <SectionCard title="资金流向" icon="💰" color="var(--accent-red)">
          <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2 mb-2.5">
            <Stat label="主力净流入" value={report.money_flow.today?.main_net || '—'} color={flowColor(report.money_flow.today?.main_net)} />
            <Stat label="超大单" value={report.money_flow.today?.super_large || '—'} color={flowColor(report.money_flow.today?.super_large)} />
            <Stat label="大单" value={report.money_flow.today?.large || '—'} color={flowColor(report.money_flow.today?.large)} />
            <Stat label="中单" value={report.money_flow.today?.medium || '—'} color={flowColor(report.money_flow.today?.medium)} />
            <Stat label="小单" value={report.money_flow.today?.small || '—'} color={flowColor(report.money_flow.today?.small)} />
          </div>
          {report.money_flow.period_stats && (
            <div className="flex items-center gap-2 flex-wrap mb-2.5">
              <span className="text-[10px] font-medium" style={{ color: 'var(--text-muted)' }}>区间统计：</span>
              {Object.entries(report.money_flow.period_stats).map(([kk, vv]) => (
                <span key={kk} className="px-2 py-0.5 rounded-full text-[11px] font-medium"
                  style={{ background: flowColor(vv) === 'var(--flow-up)' ? 'rgba(220,38,38,0.10)' : 'rgba(22,163,74,0.10)', color: flowColor(vv) }}>
                  {kk} {vv}
                </span>
              ))}
            </div>
          )}
          {report.money_flow.trend?.length > 0 && (
            <div>
              <div className="text-[10px] font-medium mb-1.5" style={{ color: 'var(--text-muted)' }}>近10日资金趋势：</div>
              <div className="flex items-center gap-1 flex-wrap">
                {report.money_flow.trend.map((t, i) => (
                  <span key={i} className="px-1.5 py-0.5 rounded text-[9px] font-medium" title={`${t.date} · 主力${t.main_net} · 涨跌${t.change}`}
                    style={{
                      background: t.status === '流入' ? 'rgba(220,38,38,0.10)' : 'rgba(22,163,74,0.10)',
                      color: t.status === '流入' ? 'var(--flow-up)' : 'var(--flow-down)',
                    }}>
                    {t.date.slice(-2)}日 {t.main_net?.startsWith('+') ? '↑' : '↓'}
                  </span>
                ))}
              </div>
            </div>
          )}
        </SectionCard>
      )}

      {/* 技术指标 */}
      {report.technical && (
        <SectionCard title="技术指标分析" icon="📐" color="var(--accent-amber)">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2.5">
            <Stat label="RSI" value={report.technical.rsi != null ? report.technical.rsi.toFixed(1) : '—'}
              color={(report.technical.rsi || 0) > 70 ? 'var(--flow-up)' : (report.technical.rsi || 0) < 30 ? 'var(--flow-down)' : 'var(--accent-amber)'} />
            <Stat label="MACD" value={report.technical.macd || '—'} color={report.technical.macd === '金叉' ? 'var(--flow-up)' : 'var(--flow-down)'} />
            <Stat label="KDJ" value={report.technical.kdj || '—'} color={report.technical.kdj === '超买区' ? 'var(--flow-up)' : report.technical.kdj === '超卖区' ? 'var(--flow-down)' : 'var(--accent-amber)'} />
            <Stat label="布林带" value={report.technical.boll || '—'} color={report.technical.boll === '触及上轨' ? 'var(--accent-amber)' : 'var(--text-primary)'} />
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2.5">
            <Stat label="MA5" value={report.technical.ma5?.toFixed(1) || '—'} />
            <Stat label="MA10" value={report.technical.ma10?.toFixed(1) || '—'} />
            <Stat label="MA20" value={report.technical.ma20?.toFixed(1) || '—'} />
            <Stat label="MA60" value={report.technical.ma60?.toFixed(1) || '—'} />
          </div>
          {report.technical.volume_ratio != null && (
            <div className="text-[11px] mb-2" style={{ color: 'var(--text-secondary)' }}>量比：<b style={{ color: 'var(--text-primary)' }}>{report.technical.volume_ratio}</b></div>
          )}
          {report.technical.summary && (
            <div className="text-[11px] leading-relaxed pt-2" style={{ color: 'var(--text-secondary)', borderTop: '1px solid var(--border-light)' }}>{report.technical.summary}</div>
          )}
        </SectionCard>
      )}

      {/* 估值分析 */}
      {report.valuation && (
        <SectionCard title="估值分析" icon="🏷️" color="#a855f7">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mb-2.5">
            <Stat label="PE(TTM)" value={`${report.valuation.pe_ttm?.toFixed(1)}x`} color="var(--accent-amber)"
              sub={`近5年${report.valuation.pe_percentile_5y}分位`} />
            <Stat label="PB" value={`${report.valuation.pb?.toFixed(1)}x`} color="var(--accent-amber)"
              sub={`近5年${report.valuation.pb_percentile_5y}分位`} />
            <Stat label="PEG" value={report.valuation.peg?.toFixed(2)} color={(report.valuation.peg || 0) < 1 ? 'var(--accent-green)' : 'var(--accent-amber)'}
              sub={(report.valuation.peg || 0) < 1 ? '合理偏低' : '偏高'} />
            <Stat label="行业均值" value={`PE ${report.valuation.industry_avg_pe}x`} color="var(--text-primary)"
              sub={`PB ${report.valuation.industry_avg_pb}x`} />
          </div>
          {report.valuation.assessment && (
            <div className="text-[11px] leading-relaxed pt-2" style={{ color: 'var(--text-secondary)', borderTop: '1px solid var(--border-light)' }}>{report.valuation.assessment}</div>
          )}
        </SectionCard>
      )}

      {/* 机构持仓 */}
      {report.institutional && (
        <SectionCard title="机构持仓" icon="🏛️" color="var(--accent-green)">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <Stat label="基金持有" value={`${report.institutional.fund_count}只`} color="var(--text-primary)" />
            <Stat label="基金持仓占比" value={report.institutional.fund_holding_ratio || '—'} color="var(--accent-blue)" />
            <Stat label="季度变动" value={report.institutional.fund_change_quarter || '—'} color={flowColor(report.institutional.fund_change_quarter)} />
            <Stat label="北向(5日)" value={report.institutional.north_bound_5d || '—'} color={flowColor(report.institutional.north_bound_5d)} />
          </div>
        </SectionCard>
      )}

      {/* 多空分析 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {report.bull_case?.length > 0 && (
          <SectionCard title="看多因素" icon="📈" color="var(--accent-green)">
            <ul className="space-y-1.5">
              {report.bull_case.map((p, i) => (
                <li key={i} className="text-[12px] flex items-start gap-2" style={{ color: 'var(--text-secondary)' }}>
                  <span style={{ color: 'var(--accent-green)', flexShrink: 0 }}>+</span><span>{p}</span>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}
        {report.bear_case?.length > 0 && (
          <SectionCard title="看空因素" icon="📉" color="var(--accent-red)">
            <ul className="space-y-1.5">
              {report.bear_case.map((p, i) => (
                <li key={i} className="text-[12px] flex items-start gap-2" style={{ color: 'var(--text-secondary)' }}>
                  <span style={{ color: 'var(--accent-red)', flexShrink: 0 }}>−</span><span>{p}</span>
                </li>
              ))}
            </ul>
          </SectionCard>
        )}
      </div>

      {/* 风险提示 */}
      {report.risk_factors?.length > 0 && (
        <SectionCard title="风险提示" icon="⚠️" color="var(--accent-red)">
          <ul className="space-y-1">
            {report.risk_factors.map((p, i) => (
              <li key={i} className="text-[12px] flex items-start gap-2" style={{ color: 'var(--text-secondary)' }}>
                <span style={{ color: 'var(--accent-red)', flexShrink: 0 }}>⚠</span><span>{p}</span>
              </li>
            ))}
          </ul>
        </SectionCard>
      )}

      {/* 数据来源 + 免责 */}
      <div className="text-center text-[10px] py-2 space-y-1" style={{ color: 'var(--text-muted)' }}>
        <div>数据来源：{src.icon} {src.label} MCP（{src.label}实时行情 / 财务数据）</div>
        <div>{report.disclaimer || '本报告仅供研究参考，不构成个人投资建议'}</div>
      </div>
    </div>
  );
}

/* 行内键值行 */
function Row({ label, value, vcolor }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span style={{ color: 'var(--text-muted)' }}>{label}</span>
      <span className="font-medium text-right" style={{ color: vcolor || 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}
