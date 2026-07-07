export const tooltipStyle = {
  backgroundColor: 'rgba(20, 20, 20, 0.95)',
  borderColor: 'rgba(255, 255, 255, 0.15)',
  borderWidth: 1,
  padding: [8, 12],
  textStyle: { color: '#fff', fontSize: 12 },
  extraCssText: 'border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);',
};

export const getHeatColor = (score) => {
  if (score >= 70) return '#ef4444';
  if (score >= 55) return '#f97316';
  if (score >= 40) return '#eab308';
  if (score >= 25) return '#22c55e';
  return '#3b82f6';
};
