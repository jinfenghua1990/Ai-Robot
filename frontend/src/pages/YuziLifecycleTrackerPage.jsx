/**
 * 游资共振股 20 天生命周期心电图矩阵
 *
 * 布局（仿截图）：
 * ┌──────────────────────────────────────────────────────────────────────────┐
 * │  20天顶级游资共振股 - 动态生命周期跟踪 (T+20 Matrix)                        │
 * ├──────────────────────────────────────────────────────────────────────────┤
 * │ 汇总: 总跟踪/大妖股/A杀/平均 20d 收益       触发范围 [手动跑一次]            │
 * ├──────────────────────────────────────────────────────────────────────────┤
 * │ 股票 | 触发分 | Day1 | Day2 | Day3 | ... | Day20 | 结局 | 20d收益         │
 * │ 多氟多|  93   | [涨停]| [+4%晋级]| [跌停A杀]| ...|        | 🟢大妖│         │
 * │      |       |方新侠  |竞价:+3.2%|大佬砸盘   |    |        | +34% │         │
 * └──────────────────────────────────────────────────────────────────────────┘
 *
 * 数据: GET /api/yuzi/tracker
 */
import { useState, useEffect, useCallback, useMemo } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { apiFetch } from '../utils/request';
import { UP_COLOR, DOWN_COLOR, UP_DARK, DOWN_DARK } from '../utils/colors';
import { computeSignalScore, fmtHitCount, computeTrendSignalScore, fmtTrendTooltip } from '../utils/signalScore';
import SinaLink from '../components/SinaLink';

const fmtPct = (v) => {
  if (v == null) return '-';
  const n = Number(v);
  if (n === 0) return '0%';
  if (n > 0) return `+${n.toFixed(2)}%`;
  return `${n.toFixed(2)}%`;
};

const pctColor = (v) => {
  if (v == null) return '#6b7280';
  if (v >= 5) return UP_DARK;
  if (v >= 0.5) return UP_COLOR;
  if (v <= -5) return DOWN_DARK;
  if (v <= -0.5) return DOWN_COLOR;
  return '#6b7280';
};

// 推算 anchor (YYYYMMDD) + n 天 后的日期字符串(YYYYMMDD)
const addDaysStr = (yyyymmdd, n) => {
  if (!yyyymmdd || yyyymmdd.length !== 8) return '';
  const y = +yyyymmdd.slice(0, 4);
  const m = +yyyymmdd.slice(4, 6) - 1;
  const d = +yyyymmdd.slice(6, 8);
  const dt = new Date(y, m, d);
  dt.setDate(dt.getDate() + n);
  const yy = dt.getFullYear();
  const mm = String(dt.getMonth() + 1).padStart(2, '0');
  const dd = String(dt.getDate()).padStart(2, '0');
  return `${yy}${mm}${dd}`;
};

// 价格状态色块（红=强/绿=弱/灰=震荡）
const stageColor = (stage) => {
  if (!stage) return '#6b7280';
  if (stage === '连板' || stage === '晋级' || stage === '偏多') return UP_COLOR;
  if (stage === '跌停A杀' || stage === '偏空') return DOWN_COLOR;
  if (stage === '分歧') return '#f59e0b';
  return '#9ca3af';
};

// 结局 emoji + 色块
const outcomeStyle = (o) => {
  if (o === '大妖股') return { emoji: '🟢', label: '大妖股', bg: '#15803d', color: '#fff' };
  if (o === 'A杀退潮') return { emoji: '🔴', label: 'A杀退潮', bg: '#dc2626', color: '#fff' };
  if (o === '高位震荡') return { emoji: '🟡', label: '高位震荡', bg: '#eab308', color: '#000' };
  if (o === '横盘') return { emoji: '⚪', label: '横盘', bg: '#9ca3af', color: '#fff' };
  if (o === '弱势回调') return { emoji: '🟠', label: '弱势回调', bg: '#f97316', color: '#fff' };
  return { emoji: '⏳', label: '未结束', bg: '#64748b', color: '#fff' };
};

// ============================================================
// 操作指令 4 方向:把 20 天矩阵提炼为可执行操盘信号
// ============================================================
// buy    = 🟢 寻找买点: D3-D7 阶段, 前几天是跌停/分歧, 今天出现修复/偏多
// hold   = 🔵 坚定持有: 最新一格是连板/晋级/偏多, 大妖股/未结束
// sell   = 🔴 卖出警报: 最新一格是跌停A杀/分歧, 已确认走弱
// skip   = ⚫ 放弃: 竞价负溢价 + 开盘无承接, 或已 A 杀退潮
const ACTION_STYLE = {
  buy:  { emoji: '🟢', label: '寻找买点', bg: '#15803d', short: '买' },
  hold: { emoji: '🔵', label: '坚定持有', bg: '#0ea5e9', short: '持' },
  sell: { emoji: '🔴', label: '卖出警报', bg: '#dc2626', short: '卖' },
  skip: { emoji: '⚫', label: '放弃参与', bg: '#475569', short: '弃' },
};

const _lastFilledDay = (lc) => {
  // 找 lifecycle_data 里最大的 d{n}
  if (!lc || typeof lc !== 'object') return null;
  let best = null, bestN = 0;
  for (const k of Object.keys(lc)) {
    if (k.startsWith('d')) {
      const n = parseInt(k.slice(1), 10);
      if (!isNaN(n) && n > bestN) { bestN = n; best = lc[k]; }
    }
  }
  return best ? { ...best, _n: bestN } : null;
};

const _classifyAction = (row) => {
  const lc = row.lifecycle_data || {};
  const last = _lastFilledDay(lc);
  if (!last) return 'skip';
  const stage = last.price_stage || '震荡';
  const openPrem = Number(last.open_premium || 0);
  const outcome = row.final_outcome || '未结束';

  // 算近3天累计涨跌(用于趋势判定,避免"最新一格偏多但近3天暴跌"误判)
  const n = last._n;
  const recent3 = [0, 1, 2].map(i => lc[`d${n - i}`]).filter(d => d);
  const recent3Pct = recent3.map(d => Number(d.pct_chg ?? d.win_rate_impact ?? 0));
  const recent3Sum = recent3Pct.reduce((a, b) => a + b, 0);
  const recent3AllDown = recent3Pct.length >= 3 && recent3Pct.every(p => p < 0);

  // 已 final 的走弱/退潮 → 卖出 / 放弃
  if (outcome === 'A杀退潮') return 'sell';
  if (outcome === '弱势回调') return 'sell';
  // 已 final 的大妖股 / 高位震荡 → 持有 (但要警惕近期走弱)
  if (outcome === '大妖股' || outcome === '高位震荡') {
    if (stage === '跌停A杀' || stage === '砸盘' || stage === '分歧' || stage === '偏空') return 'sell';
    if (recent3AllDown && recent3Sum <= -5) return 'sell';  // 高位但近3天暴跌 = 退潮信号
    return 'hold';
  }
  if (outcome === '横盘') {
    if (stage === '连板' || stage === '晋级' || stage === '偏多') {
      if (recent3AllDown && recent3Sum <= -5) return 'sell';
      return 'hold';
    }
    if (stage === '跌停A杀' || stage === '砸盘' || stage === '偏空') return 'sell';
    return 'skip';
  }

  // 未结束: 4 方向判定
  // ❌ 放弃: 竞价负溢价 + 无承接 (D2 是关键观察日)
  if (n === 2 && openPrem <= -2) return 'skip';
  if (openPrem <= -3) return 'skip';

  // 🚨 卖出: 最新一格是跌停/分歧/砸盘/偏空
  if (stage === '跌停A杀' || stage === '砸盘' || stage === '爆量滞涨') return 'sell';
  if (stage === '偏空') return 'sell';  // 偏空 = 明确走弱,应卖出
  if (stage === '分歧' && n >= 5) return 'sell'; // D5+ 分歧通常走弱

  // 🚨 卖出: 近3天累计跌幅过大(>8%)或连续3天下跌
  if (recent3AllDown && recent3Sum <= -8) return 'sell';
  if (recent3AllDown && n >= 4) return 'sell';  // D4+ 连跌3天 = 趋势走坏

  // 🎯 寻找买点: D3-D7, 前 1-2 天是走弱, 今天修复/偏多
  if (n >= 3 && n <= 7) {
    const prev1 = lc[`d${n - 1}`];
    const prev2 = lc[`d${n - 2}`];
    const prevWeakened = [prev1, prev2].some(p => p && ['跌停A杀', '分歧', '砸盘', '弱势回调'].includes(p.price_stage));
    if (prevWeakened && (stage === '震荡' || stage === '偏多' || stage === '晋级')) {
      return 'buy';
    }
  }

  // 🔋 持有: 仅当最新一格明确偏多且近3天没暴跌
  if (stage === '连板' || stage === '晋级' || stage === '偏多') {
    if (recent3AllDown && recent3Sum <= -5) return 'sell';  // 即使最新偏多,但3天累计跌>5% = 风险
    return 'hold';
  }

  // 默认: 中性观察(不轻易建议持有)
  return 'skip';
};

// 资金格式化:万/亿
const fmtMoney = (v) => {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  if (n === 0) return '—';
  const abs = Math.abs(n);
  if (abs >= 10000) return `${(n / 10000).toFixed(1)}亿`;
  return `${n > 0 ? '+' : ''}${n.toFixed(0)}万`;
};

// Day 单元格渲染 — 一眼看懂：涨跌幅 + 主力资金 + 散户 + 竞价 + 大佬卖出标记
const DayCell = ({ data, dayNum, bossExits }) => {
  if (!data) {
    return <div className="text-[9px] text-center" style={{ color: '#9ca3af' }}>—</div>;
  }
  const stage = data.price_stage || '震荡';
  const openPrem = Number(data.open_premium || 0);
  const pctChg = Number(data.pct_chg ?? data.win_rate_impact ?? 0);
  const mainForce = Number(data.main_force_inflow || 0); // 主力净流入(万)
  const netInflow = Number(data.net_inflow || 0); // 总净流入(万)
  const retail = Number(data.retail_flow || 0); // 散户净流入(万)
  const mfRatio = Number(data.main_force_ratio || 0); // 主力主导度(%)
  const amp = Number(data.intra_amplitude || 0);
  const support = data.support_level || '-';

  // 涨跌幅色块（红=涨/绿=跌/灰=平）
  const chgBg = pctChg >= 5 ? 'rgba(239,68,68,0.2)' :
                pctChg > 0 ? 'rgba(239,68,68,0.08)' :
                pctChg <= -5 ? 'rgba(34,197,94,0.2)' :
                pctChg < 0 ? 'rgba(34,197,94,0.08)' : 'rgba(156,163,175,0.08)';
  const chgColor = pctChg > 0 ? UP_COLOR : pctChg < 0 ? DOWN_COLOR : '#6b7280';

  // 主力资金流向（红=流入/绿=流出）
  const mfColor = mainForce > 0 ? UP_COLOR : mainForce < 0 ? DOWN_COLOR : '#6b7280';
  const mfText = fmtMoney(mainForce);

  // 散户流向(通常与主力相反)
  const retailColor = retail > 0 ? UP_COLOR : retail < 0 ? DOWN_COLOR : '#6b7280';
  const retailText = fmtMoney(retail);

  // 承接力度色块
  const supportBg = support === '强' ? UP_COLOR : support === '弱' ? DOWN_COLOR : '#6b7280';

  // 主力主导度: 主力 vs 总净流入(>70% = 主力主导, <30% = 散户主导)
  const isMainDominant = mfRatio >= 70 && mainForce !== 0;

  // 7 维度信号命中数
  const sigScore = computeSignalScore(data);

  // 大佬卖出记录 (D1 大佬在这一天卖了)
  const dayDate = data.date || '';
  const bossSells = (bossExits && dayDate && bossExits[dayDate]) || [];
  const hasBossSell = bossSells.length > 0;

  const tooltip = [
    `📅${data.date || ''}`,
    `涨跌:${pctChg.toFixed(2)}%`,
    `阶段:${stage}`,
    `竞价:${openPrem.toFixed(1)}%`,
    `振幅:${amp.toFixed(1)}%`,
    `💰主力:${mfText} (${mfRatio}%主导)`,
    `总净流入:${fmtMoney(netInflow)}`,
    `散户:${retailText}`,
    `承接:${support}`,
    `7维信号:${sigScore ? fmtHitCount(sigScore) : '—'} (${sigScore?.label || '—'})`,
    hasBossSell ? `🚨大佬卖出:${bossSells.map(s => `${s.alias} ${fmtMoney(s.net)}`).join(', ')}` : '',
  ].filter(Boolean).join(' | ');

  return (
    <div className="rounded p-1 min-w-[78px] relative" style={{ background: chgBg, border: hasBossSell ? '1px solid #dc2626' : '1px solid var(--border-color)' }} title={tooltip}>
      {/* 大佬卖出角标 — 红色警示,贴右上角 */}
      {hasBossSell && (
        <div
          className="absolute -top-1 -right-1 px-1 py-0 rounded text-[8px] font-bold z-10"
          style={{ background: '#dc2626', color: '#fff', border: '1px solid #fff' }}
          title={`🚨 大佬卖出: ${bossSells.map(s => `${s.alias} ${fmtMoney(s.net)}`).join(', ')}`}
        >
          💰卖{bossSells.length}
        </div>
      )}
      {/* 7维命中数标签 — 最顶部，一眼看多空 */}
      {sigScore && (
        <div className="text-center mb-0.5">
          <span
            className="text-[8px] font-bold px-1 py-0 rounded inline-block"
            style={{ background: sigScore.bg, color: sigScore.color, border: `1px solid ${sigScore.color}40` }}
            title={`7维命中: ${fmtHitCount(sigScore)} (得分${sigScore.score > 0 ? '+' : ''}${sigScore.score})`}
          >
            {sigScore.label} {sigScore.score > 0 ? '+' : ''}{sigScore.score}
          </span>
        </div>
      )}
      {/* 涨跌幅 — 最醒目大字 */}
      <div className="text-[12px] font-bold text-center leading-tight" style={{ color: chgColor }}>
        {pctChg > 0 ? '+' : ''}{pctChg.toFixed(1)}%
      </div>
      {/* 阶段标签 + 承接力度（并列） */}
      <div className="flex items-center justify-center gap-0.5 mt-0.5 mb-0.5">
        <span className="text-[9px] font-bold px-1 py-0.5 rounded" style={{ background: stageColor(stage), color: '#fff' }}>
          {stage}
        </span>
        <span className="text-[8px] px-0.5 rounded" style={{ background: supportBg, color: '#fff' }} title={`承接:${support}`}>
          {support}
        </span>
      </div>
      {/* 💰主力净流入 — 用户最关心，粗体 */}
      <div className="text-[10px] text-center font-bold" style={{ color: mfColor }}>
        💰{mfText}
      </div>
      {/* 主力主导度 + 散户流向 — 第二行资金信息 */}
      <div className="flex items-center justify-between text-[8px] mt-0.5">
        <span style={{ color: isMainDominant ? mfColor : '#9ca3af' }} title="主力主导度">
          {mfRatio > 0 ? `${mfRatio}%` : '—'}
        </span>
        <span style={{ color: retailColor }} title={`散户净流入 ${retailText}`}>
          👥{retail === 0 ? '—' : retail > 0 ? '+' : ''}{Math.abs(retail) >= 10000 ? `${(retail/10000).toFixed(1)}亿` : `${Math.abs(retail).toFixed(0)}万`}
        </span>
      </div>
    </div>
  );
};

export default function YuziLifecycleTrackerPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialTsCode = searchParams.get('ts_code') || '';
  const initialMinScore = searchParams.get('min_score');
  const [data, setData] = useState(null);
  const [minScore, setMinScore] = useState(initialMinScore != null ? Number(initialMinScore) : 70);
  const [outcome, setOutcome] = useState('');
  const [action, setAction] = useState('');  // 操作指令过滤: '' / buy / hold / sell / skip
  const [searchText, setSearchText] = useState(initialTsCode);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const url = `/api/yuzi/tracker?min_score=${minScore}&days_back=30&limit=200${outcome ? `&outcome=${encodeURIComponent(outcome)}` : ''}`;
      const { ok, data: d } = await apiFetch(url);
      if (ok) setData(d);
      else setError('加载失败');
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [minScore, outcome]);

  useEffect(() => { load(); }, [load]);

  // 给每行算操作指令 (前端纯展示逻辑)
  const rowsWithAction = useMemo(() => {
    if (!data?.rows) return [];
    return data.rows.map(r => ({ ...r, _action: _classifyAction(r) }));
  }, [data]);

  // 按 action + 搜索文本过滤
  const filteredRows = useMemo(() => {
    let result = rowsWithAction;
    if (action) result = result.filter(r => r._action === action);
    if (searchText.trim()) {
      const q = searchText.trim().toLowerCase();
      result = result.filter(r => {
        const bosses = Array.isArray(r.boss_list_d1) ? r.boss_list_d1.join(',') : (r.boss_list_d1 || '');
        return r.ts_code?.toLowerCase().includes(q) ||
               r.stock_name?.toLowerCase().includes(q) ||
               bosses.toLowerCase().includes(q);
      });
    }
    return result;
  }, [rowsWithAction, action, searchText]);

  // 4 方向数量统计
  const actionCounts = useMemo(() => {
    const c = { buy: 0, hold: 0, sell: 0, skip: 0 };
    rowsWithAction.forEach(r => { c[r._action] = (c[r._action] || 0) + 1; });
    return c;
  }, [rowsWithAction]);

  const handleRun = async () => {
    if (!confirm('触发一次完整的 d1 + update? 会拉 Tushare 当日数据')) return;
    setRunning(true);
    try {
      const today = new Date().toISOString().slice(0, 10).replace(/-/g, '');
      const { ok, data: d } = await apiFetch('/api/yuzi/tracker/run', {
        method: 'POST',
        body: JSON.stringify({ date: today }),
      });
      if (ok) {
        alert(`✅ 完成\nD1 插入: ${d.d1_inserted}\n更新: ${d.updated}\n跳过: ${d.skipped}\n最终化: ${d.finalized}`);
        load();
      } else {
        alert('❌ 失败: ' + JSON.stringify(d));
      }
    } catch (e) {
      alert('❌ ' + String(e));
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="space-y-3">
      {/* ============ 顶部:标题 + 汇总 ============ */}
      <div className="rounded-lg border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <div className="flex items-center gap-2 flex-wrap">
          <h1 className="text-lg font-bold" style={{ color: 'var(--accent-blue)' }}>
            📈 20天顶级游资共振股 - 动态生命周期跟踪
          </h1>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>T+20 Matrix</span>
          <button
            onClick={handleRun}
            disabled={running}
            className="ml-auto px-2 py-1 text-xs rounded border disabled:opacity-50"
            style={{ borderColor: 'var(--accent-blue)', color: 'var(--accent-blue)' }}
            title="触发 D1 + Update 调度"
          >
            {running ? '⏳ 调度中...' : '🔄 手动跑一次'}
          </button>
        </div>

        {/* 汇总卡 */}
        {data && (
          <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mt-2">
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>总跟踪数</div>
              <div className="text-base font-bold" style={{ color: 'var(--accent-blue)' }}>{data.count}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>≥85分 高分股</div>
              <div className="text-base font-bold" style={{ color: UP_DARK }}>{data.high_score_count}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🟢 大妖股</div>
              <div className="text-base font-bold" style={{ color: '#15803d' }}>{data.by_outcome['大妖股'] || 0}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>🔴 A杀退潮</div>
              <div className="text-base font-bold" style={{ color: DOWN_DARK }}>{data.by_outcome['A杀退潮'] || 0}</div>
            </div>
            <div className="rounded border p-2" style={{ borderColor: 'var(--border-color)' }}>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>平均 20d 收益</div>
              <div className="text-base font-bold" style={{ color: pctColor(data.avg_20d_return) }}>{fmtPct(data.avg_20d_return)}</div>
            </div>
          </div>
        )}

        {/* 过滤 - 结局 + 操作指令 */}
        <div className="flex items-center gap-2 flex-wrap mt-2">
          <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>最小触发分</span>
          <input
            type="number"
            min={0}
            max={100}
            value={minScore}
            onChange={(e) => setMinScore(Number(e.target.value) || 0)}
            className="w-16 px-1 py-0.5 text-[10px] rounded border"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
          <span className="text-[10px] ml-2" style={{ color: 'var(--text-muted)' }}>结局</span>
          {['', '大妖股', 'A杀退潮', '高位震荡', '横盘', '弱势回调', '未结束'].map(o => (
            <button
              key={o || 'all'}
              onClick={() => setOutcome(o)}
              className="px-2 py-0.5 text-[10px] rounded border"
              style={{
                borderColor: outcomeStyle(o).bg,
                background: outcome === o ? `${outcomeStyle(o).bg}30` : 'transparent',
                color: outcomeStyle(o).bg,
                fontWeight: outcome === o ? 700 : 400,
              }}
            >{o || '全部'}</button>
          ))}
          <input
            type="text"
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="搜索代码/名称/游资"
            className="ml-2 px-2 py-0.5 text-[10px] rounded border w-32"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
          />
          {initialTsCode && (
            <button
              onClick={() => { setSearchText(''); setMinScore(70); setSearchParams({}); }}
              className="px-2 py-0.5 text-[10px] rounded border"
              style={{ borderColor: '#a855f7', color: '#a855f7' }}
            >清除筛选</button>
          )}

          {/* 操作指令 4 方向过滤 (小喇叭决策栏) */}
          <span className="text-[10px] ml-3" style={{ color: 'var(--text-muted)' }}>🎯 操作指令</span>
          {['', 'buy', 'hold', 'sell', 'skip'].map(a => {
            const s = a ? ACTION_STYLE[a] : null;
            const isActive = action === a;
            const count = a ? (actionCounts[a] || 0) : rowsWithAction.length;
            return (
              <button
                key={a || 'all'}
                onClick={() => setAction(a)}
                className="px-2 py-0.5 text-[10px] rounded border"
                style={{
                  borderColor: s ? s.bg : 'var(--border-color)',
                  background: isActive ? `${s?.bg || '#64748b'}30` : 'transparent',
                  color: s ? s.bg : 'var(--text-secondary)',
                  fontWeight: isActive ? 700 : 400,
                }}
                title={s ? `${s.label} (${count}只)` : `全部 (${count}只)`}
              >
                {s ? `${s.emoji} ${s.label}` : `全部`} <span style={{ opacity: 0.6 }}>·{count}</span>
              </button>
            );
          })}
        </div>

        {error && <div className="text-xs mt-2" style={{ color: DOWN_COLOR }}>{error}</div>}
      </div>

      {/* ============ 心电图矩阵 ============ */}
      {loading && <div className="text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div>}
      {!loading && rowsWithAction.length === 0 && (
        <div className="text-xs p-4 text-center rounded border" style={{ color: 'var(--text-muted)', borderColor: 'var(--border-color)' }}>
          暂无数据,试试降低"最小触发分"或点"手动跑一次"补数据
        </div>
      )}
      {rowsWithAction.length > 0 && (
        <div className="rounded-lg border overflow-x-auto" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <table className="w-full text-xs">
            <thead>
              <tr style={{ background: 'var(--bg-hover)' }}>
                <th className="px-2 py-2 text-left font-bold sticky left-0 z-10" style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}>股票</th>
                <th className="px-1 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>触发分</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>今日动作</th>
                {Array.from({ length: 20 }, (_, i) => i + 1).map(d => (
                  <th key={d} className="px-1 py-2 text-center font-bold text-[10px]" style={{ color: 'var(--text-primary)' }}>D{d}</th>
                ))}
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>最终结局</th>
                <th className="px-2 py-2 text-center font-bold" style={{ color: 'var(--text-primary)' }}>20d 收益</th>
              </tr>
            </thead>
            <tbody>
              {filteredRows.map((r, i) => {
                const os = outcomeStyle(r.final_outcome);
                const ac = ACTION_STYLE[r._action];
                const isSelected = selected?.id === r.id;
                // 取每只股的 D1 触发日,作为相对锚点
                const anchor = r.lifecycle_data.d1?.date || r.trigger_date;
                return (
                  <tr
                    key={r.id}
                    className="border-t cursor-pointer hover:opacity-90"
                    style={{ borderColor: 'var(--border-color)', background: isSelected ? 'var(--bg-hover)' : (i % 2 ? 'rgba(0,0,0,0.02)' : 'transparent') }}
                    onClick={() => setSelected(isSelected ? null : r)}
                  >
                    <td className="px-2 py-2 sticky left-0 z-10" style={{ background: isSelected ? 'var(--bg-hover)' : (i % 2 ? 'rgba(0,0,0,0.02)' : 'var(--bg-card)') }}>
                      <div className="flex items-center gap-1">
                        <span className="font-bold" style={{ color: 'var(--text-primary)' }}>{r.stock_name}</span>
                        <SinaLink tsCode={r.ts_code} />
                        <button
                          onClick={(e) => { e.stopPropagation(); navigate(`/stock/${r.ts_code.split('.')[0]}`); }}
                          className="px-1 py-0.5 rounded text-[10px]"
                          style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}
                          title="跳转个股详情页"
                        >
                          📈
                        </button>
                      </div>
                      <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>{r.ts_code} · 触发 {r.trigger_date}</div>
                      <div className="text-[10px] mt-0.5 flex flex-wrap gap-0.5">
                        {r.boss_list_d1.slice(0, 3).map(b => (
                          <span key={b} className="px-1 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: UP_COLOR }}>{b}</span>
                        ))}
                        {r.boss_list_d1.length > 3 && <span className="text-[9px]" style={{ color: 'var(--text-muted)' }}>+{r.boss_list_d1.length - 3}</span>}
                      </div>
                    </td>
                    <td className="px-1 py-2 text-center">
                      <div className="font-bold text-base" style={{ color: r.quant_score_d1 >= 85 ? UP_DARK : r.quant_score_d1 >= 70 ? UP_COLOR : '#6b7280' }}>{r.quant_score_d1.toFixed(0)}</div>
                      <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>×{r.resonance_count_d1}位</div>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <div
                        className="px-2 py-1 rounded font-bold text-xs inline-block whitespace-nowrap"
                        style={{ background: ac.bg, color: '#fff' }}
                        title={ac.label}
                      >
                        {ac.emoji} {ac.label}
                      </div>
                      {/* 3天趋势标签 — 今日动作下方 (基于最近3天7维得分综合判断强度+走势) */}
                      {(() => {
                        const trend = computeTrendSignalScore(r.lifecycle_data);
                        if (!trend) return null;
                        const arrow = trend.trajectory >= 2 ? '↑' : trend.trajectory <= -2 ? '↓' : '→';
                        return (
                          <div
                            className="mt-1 px-1 py-0.5 rounded text-[9px] font-bold inline-block whitespace-nowrap"
                            style={{ background: trend.bg, color: trend.color, border: `1px solid ${trend.color}40` }}
                            title={fmtTrendTooltip(trend)}
                          >
                            {trend.label} {arrow}{trend.avgScore > 0 ? '+' : ''}{trend.avgScore}
                          </div>
                        );
                      })()}
                      {/* 最新一天 7维命中数 (副标签,小字) */}
                      {(() => {
                        const keys = Object.keys(r.lifecycle_data || {}).filter(k => k.startsWith('d')).map(k => parseInt(k.slice(1)));
                        if (!keys.length) return null;
                        const maxN = Math.max(...keys);
                        const lastDay = r.lifecycle_data[`d${maxN}`];
                        const sig = computeSignalScore(lastDay);
                        if (!sig) return null;
                        return (
                          <div
                            className="mt-0.5 text-[8px]"
                            style={{ color: sig.color, opacity: 0.75 }}
                            title={`D${maxN} 7维命中: ${fmtHitCount(sig)}`}
                          >
                            D{maxN}:{sig.label}{sig.score > 0 ? '+' : ''}{sig.score}
                          </div>
                        );
                      })()}
                    </td>
                    {Array.from({ length: 20 }, (_, i) => i + 1).map(d => {
                      // 只用实际填入的 date 字段,没有数据就不显示日期(避免错误推算导致重复)
                      const dd = r.lifecycle_data[`d${d}`];
                      const dayDate = dd?.date || '';
                      return (
                        <td key={d} className="px-0.5 py-1 text-center">
                          <div className="text-[9px] font-bold mb-0.5" style={{ color: dayDate ? 'var(--text-secondary)' : 'var(--text-muted)' }}>
                            {dayDate ? dayDate.slice(4, 6) + '-' + dayDate.slice(6, 8) : ''}
                          </div>
                          <DayCell data={dd} dayNum={d} bossExits={r.boss_exits} />
                        </td>
                      );
                    })}
                    <td className="px-2 py-2 text-center">
                      <div
                        className="px-2 py-1 rounded font-bold text-xs inline-block"
                        style={{ background: os.bg, color: os.color }}
                        title={`${r.final_outcome} · ${fmtPct(r.net_return_20d)}`}
                      >
                        {os.emoji} {os.label}
                      </div>
                    </td>
                    <td className="px-2 py-2 text-center">
                      <div className="font-bold text-base" style={{ color: pctColor(r.net_return_20d) }}>{fmtPct(r.net_return_20d)}</div>
                      <div className="text-[9px]" style={{ color: 'var(--text-muted)' }}>20d 最高</div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* ============ 选中行详情（固定悬浮在视口底部，无论股票在顶部还是底部都能看到）============ */}
      {selected && (
        <div className="fixed bottom-0 left-0 right-0 z-50 rounded-t-lg border-t-2 border-x p-3 max-h-[60vh] overflow-auto shadow-2xl" style={{ borderColor: 'var(--accent-blue)', background: 'var(--bg-card)' }}>
          <div className="flex items-center gap-2 mb-2">
            <h3 className="text-sm font-bold" style={{ color: 'var(--accent-blue)' }}>
              {selected.stock_name} ({selected.ts_code}) 7天轨迹详情
            </h3>
            <SinaLink tsCode={selected.ts_code} />
            <button
              onClick={() => navigate(`/stock/${selected.ts_code.split('.')[0]}`)}
              className="px-2 py-0.5 rounded text-xs font-medium"
              style={{ background: 'rgba(59,130,246,0.1)', color: '#3b82f6', border: '1px solid rgba(59,130,246,0.3)' }}
              title="跳转个股详情页（K线/实时/资讯）"
            >
              📈 个股详情
            </button>
            <button onClick={() => setSelected(null)} className="ml-auto text-xs px-2 py-0.5 rounded" style={{ background: 'var(--bg-hover)' }}>关闭</button>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 text-xs">
            <div><span style={{ color: 'var(--text-muted)' }}>触发日:</span> <span className="font-bold">{selected.trigger_date}</span></div>
            <div><span style={{ color: 'var(--text-muted)' }}>Day1 评分:</span> <span className="font-bold" style={{ color: UP_DARK }}>{selected.quant_score_d1}</span></div>
            <div><span style={{ color: 'var(--text-muted)' }}>Day1 共振:</span> <span className="font-bold">{selected.resonance_count_d1} 位大佬</span></div>
            <div><span style={{ color: 'var(--text-muted)' }}>20d 收益:</span> <span className="font-bold" style={{ color: pctColor(selected.net_return_20d) }}>{fmtPct(selected.net_return_20d)}</span></div>
            <div className="col-span-2 md:col-span-4">
              <span style={{ color: 'var(--text-muted)' }}>Day1 大佬:</span>
              <div className="mt-1 flex flex-wrap gap-1">
                {selected.boss_list_d1.map(b => (
                  <span key={b} className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: UP_COLOR, border: '1px solid rgba(239,68,68,0.3)' }}>{b}</span>
                ))}
              </div>
            </div>
          </div>
          <div className="mt-2 grid grid-cols-5 md:grid-cols-10 gap-1 text-[10px]">
            {Array.from({ length: 20 }, (_, i) => i + 1).map(d => {
              const dd = selected.lifecycle_data[`d${d}`];
              if (!dd) return (
                <div key={d} className="rounded p-1 text-center" style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}>
                  <div className="font-bold">D{d}</div>
                  <div>—</div>
                </div>
              );
              return (
                <div key={d} className="rounded p-1 text-center" style={{ background: 'var(--bg-hover)' }}>
                  <div className="font-bold">D{d}</div>
                  <div style={{ color: stageColor(dd.price_stage) }}>{dd.price_stage}</div>
                  <div style={{ color: pctColor(dd.win_rate_impact) }}>{fmtPct(dd.win_rate_impact)}</div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* ============ 提示 ============ */}
      <div className="text-[10px] text-center" style={{ color: 'var(--text-muted)' }}>
        数据源：Tushare Pro daily + top_list · 每天 15:30 自动调度 · 仅供研究不构成投资建议
      </div>
    </div>
  );
}
