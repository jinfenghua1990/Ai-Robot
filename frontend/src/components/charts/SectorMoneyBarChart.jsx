import CategoryLineChart from './CategoryLineChart';

const fmtFlow = (v) => {
  if (v == null || isNaN(v)) return '—';
  const abs = Math.abs(v);
  if (abs >= 10000) return `${(v / 10000).toFixed(1)}亿`;
  return `${v.toFixed(0)}万`;
};

/**
 * 板块资金流向折线图（分类 X 轴 + 数值 Y 轴）
 * 统一使用 CategoryLineChart 的 Top 10 热度趋势样式。
 */
export default function SectorMoneyBarChart({ sectors, selectedSector, onSectorClick }) {
  const categories = sectors.map(s => s.name);
  const values = sectors.map(s => s.value);

  const tooltipFormatter = (params) => {
    const p = params[0];
    const v = p.value;
    const color = v > 0 ? '#ef4444' : v < 0 ? '#22c55e' : '#6b7280';
    const direction = v > 0 ? '净流入' : v < 0 ? '净流出' : '持平';
    return `<div style="font-weight:700;font-size:13px;margin-bottom:2px">${p.name}</div>` +
           `<div style="font-size:12px;color:#ccc">${direction}：<span style="color:${color};font-weight:600">${v > 0 ? '+' : ''}${fmtFlow(v)}</span></div>`;
  };

  return (
    <CategoryLineChart
      categories={categories}
      values={values}
      selectedItem={selectedSector}
      onItemClick={onSectorClick}
      color="#6366f1"
      valueFormatter={(v) => Math.abs(v) >= 10000 ? `${(v / 10000).toFixed(0)}亿` : `${v.toFixed(0)}万`}
      tooltipFormatter={tooltipFormatter}
      height={280}
    />
  );
}
