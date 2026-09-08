import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { v2api } from '../../api/v2';

const STATE_KEYS = ['TRIGGERED', 'READY', 'WATCH', 'HOLD', 'NO_CHASE', 'INVALID'];
const LABELS = {
  TRIGGERED: '已触发',
  READY: '准备',
  WATCH: '观察',
  HOLD: '持有',
  NO_CHASE: '禁止追高',
  INVALID: '失效',
};

function fmtScore(v) {
  return v == null ? '—' : Number(v).toFixed(1);
}
function fmtPct(v, digits = 1) {
  return v == null ? '—' : `${(Number(v) * 100).toFixed(digits)}%`;
}
function stateTag(value) {
  const tone =
    value === 'TRIGGERED'
      ? 'red'
      : value === 'READY'
      ? 'amber'
      : value === 'HOLD'
      ? 'green'
      : '';
  return <span className={`tag ${tone}`}>{LABELS[value] || value}</span>;
}
function MarketBanner({ market }) {
  if (!market) {
    return (
      <div className="notice warn">
        <strong>没有完成交易日数据</strong>数据库暂时没有可计算的日线。
      </div>
    );
  }
  return (
    <div className="market-banner">
      <div>
        <div className="metric-label">信号交易日 {market.trade_date}</div>
        <div className={`market-state ${market.state}`}>
          {market.sentiment}
        </div>
      </div>
      <div className="market-facts">
        <span>
          上涨比例<b>{fmtPct(market.breadth)}</b>
        </span>
        <span>
          涨停<b>{market.limit_up}</b>
        </span>
        <span>
          跌停<b>{market.limit_down}</b>
        </span>
        <span>
          20日市场收益<b>{fmtPct(market.market_return_20d)}</b>
        </span>
      </div>
    </div>
  );
}
function Metric({ label, value, note, tone }) {
  return (
    <div className={`card metric-${tone}`}>
      <div className="metric-label">{label}</div>
      <div className="metric-value">{value}</div>
      <div className="metric-note">{note}</div>
    </div>
  );
}

export default function V2OverviewPage() {
  const navigate = useNavigate();
  const [dashboard, setDashboard] = useState(null);
  const [candidates, setCandidates] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = async () => {
    setLoading(true);
    setError(null);
    try {
      const [d, c] = await Promise.all([
        v2api.dashboard(),
        v2api.candidates(80),
      ]);
      setDashboard(d);
      setCandidates(c.signals || []);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, []);

  const handlePersist = async () => {
    try {
      await v2api.persistSnapshot();
      alert('本日 V2 快照已保存');
    } catch (e) {
      alert(e.message);
    }
  };

  if (loading) {
    return (
      <div className="loading-card">
        <div className="loading-spinner" aria-hidden="true"></div>
        <strong>正在读取 V2 数据…</strong>
        <span>正在读取最近完成交易日、股票池和因子评分；首次计算可能需要十几秒。</span>
        <div className="loading-skeleton" aria-hidden="true">
          <i></i><i></i><i></i><i></i>
        </div>
      </div>
    );
  }
  if (error) {
    return (
      <div className="notice danger">
        <strong>新 V2 页面读取失败</strong>
        {error}
      </div>
    );
  }

  const d = dashboard || {};
  const counts = d.state_counts || {};

  return (
    <>
      <div className="page-head">
        <div>
          <h2>系统总览</h2>
          <p>
            先看市场环境，再看可执行信号；总分不是买入理由，只有“已触发（TRIGGERED）”才是右侧触发。
          </p>
        </div>
        <div className="actions">
          <button className="button" type="button" onClick={load}>
            刷新计算
          </button>
          <button className="button primary" type="button" onClick={handlePersist}>
            保存本日快照
          </button>
        </div>
      </div>

      <MarketBanner market={d.market} />

      <div className="grid grid-4 section">
        <Metric
          label={d.production_ready ? '生产股票池' : '研究股票池'}
          value={d.universe_count || 0}
          note={`已过滤 ST ${d.st_filtered_count || 0} 只；日线/成交量有效`}
          tone="blue"
        />
        <Metric
          label={d.production_ready ? '共振通过' : '研究共振通过'}
          value={d.resonance_eligible || 0}
          note="至少4个机会维度，趋势通过，风险闸门通过"
          tone="green"
        />
        <Metric
          label="右侧已触发"
          value={d.triggered || 0}
          note="已触发；仍需人工确认与账户风控"
          tone="red"
        />
        <Metric label="信号交易日" value={d.trade_date || '—'} note="不是自然日；只使用最近完成的日线" tone="amber" />
      </div>

      <div className="section card">
        <div className="section-title">
          <h3>交易状态分布</h3>
          <span>风险维度不计入机会共振，只能否决</span>
        </div>
        <div className="state-grid">
          {STATE_KEYS.map((key) => (
            <div key={key} className={`state-box state-${key}`}>
              <strong>{counts[key] || 0}</strong>
              <span>{LABELS[key]}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="grid grid-2 section">
        <div className="card">
          <div className="section-title">
            <h3>今日排名前10</h3>
            <span>全市场横向排名后展示</span>
          </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>排名</th>
                  <th>股票</th>
                  <th>分数</th>
                  <th>状态</th>
                  <th>共振</th>
                </tr>
              </thead>
              <tbody>
                {candidates.slice(0, 10).map((item) => (
                  <tr
                    key={item.code}
                    className="clickable"
                    onClick={() => navigate(`/v2/analysis?code=${encodeURIComponent(item.code)}`)}
                  >
                    <td>#{item.rank}</td>
                    <td>
                      <b>{item.name}</b>
                      <div className="stock-code">{item.code}</div>
                    </td>
                    <td className="score">{fmtScore(item.factor_score)}</td>
                    <td>{stateTag(item.trading_state)}</td>
                    <td>{item.resonance_count}/6</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        <div className="card">
          <div className="section-title">
            <h3>如何使用这一页</h3>
            <span>V2 决策顺序</span>
          </div>
          <div className="notice">
            <strong>1. 市场环境</strong>市场偏弱时，候选只能观察或禁止追高，不会因为个股分高而强行买入。
          </div>
          <div className="notice section">
            <strong>2. 独立证据</strong>共振至少4个机会维度，趋势必须有效；风险只做闸门，不能增加共振数量。
          </div>
          <div className="notice warn section">
            <strong>3. 交易状态</strong>主升不等于买入。只有已触发状态才能进入交易预览，且当前新程序默认不下单。
          </div>
        </div>
      </div>

      <div className="footer-note">
        数据来源：{(d.data_sources || {}).daily_bars || '旧库'}；没有把旧策略命中数当成胜率。
      </div>
    </>
  );
}
