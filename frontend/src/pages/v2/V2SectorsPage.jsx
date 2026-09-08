import { useEffect, useState } from 'react';
import { v2api } from '../../api/v2';

function fmt0(v) {
  return v == null ? '—' : Number(v).toFixed(0);
}
function fmt1(v) {
  return v == null ? '—' : Number(v).toFixed(1);
}
function fmt2(v) {
  return v == null ? '—' : `${Number(v).toFixed(2)}%`;
}

export default function V2SectorsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    v2api.sectors(50)
      .then(setData)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) {
    return (
      <div className="loading-card">
        <div className="loading-spinner" aria-hidden="true"></div>
        <strong>正在读取板块流动…</strong>
      </div>
    );
  }
  if (error) {
    return (
      <div className="notice danger">
        <strong>读取失败</strong>
        {error}
      </div>
    );
  }

  const sectors = data?.sectors || [];
  const firstFlowDate = sectors[0]?.flow_date;

  return (
    <>
      <div className="page-head">
        <div>
          <h2>板块流动</h2>
          <p>板块资金是独立证据，必须与个股趋势、强度和交易位置共同判断。</p>
        </div>
        <span className="muted">
          评分日 {data?.trade_date || '—'} · 资金日 {firstFlowDate || '—'}
        </span>
      </div>

      <div className="notice">
        资金流入只说明板块环境改善，不等于个股可以买入；右侧触发仍由 V2 交易状态决定。
      </div>

      <div className="card section">
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>板块</th>
                <th>资金净流入</th>
                <th>热度</th>
                <th>上涨比例</th>
                <th>平均涨跌</th>
                <th>股票数</th>
                <th>平均因子分</th>
                <th>共振/触发</th>
              </tr>
            </thead>
            <tbody>
              {sectors.length ? (
                sectors.map((item) => {
                  const flow = Number(item.net_flow || 0);
                  const flowClass = flow >= 0 ? 'positive' : 'negative';
                  return (
                    <tr key={item.sector}>
                      <td>
                        <b>{item.sector}</b>
                      </td>
                      <td className={flowClass}>
                        {item.net_flow == null ? '—' : fmt0(item.net_flow)}
                      </td>
                      <td>{fmt1(item.heat_score)}</td>
                      <td>
                        {item.rise_ratio == null
                          ? '—'
                          : `${(Number(item.rise_ratio) * 100).toFixed(1)}%`}
                      </td>
                      <td>{fmt2(item.avg_chg)}</td>
                      <td>{item.count}</td>
                      <td className="score">{fmt1(item.avg_score)}</td>
                      <td>
                        {item.eligible}/{item.triggered}
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan="8">
                    <div className="empty">暂无板块数据</div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </>
  );
}
