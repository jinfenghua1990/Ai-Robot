/** 在独立浏览器页打开个股分析，避免打断当前列表/决策页面。 */
export function openStockAnalysis(code, market = 'a') {
  if (!code) return;
  const param = market === 'us' ? `symbol=${encodeURIComponent(code)}` : `code=${encodeURIComponent(code)}`;
  const path = market === 'us' ? '/us-stock-analysis' : '/stock-analysis';
  window.open(`${path}?${param}`, '_blank', 'noopener,noreferrer');
}
