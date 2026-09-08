import { getStockUrl } from './stockLink';
import { usTradingViewUrl, usSinaUrl } from './usStockExchange';

export function sinaUrl(marketOrTsCode, code) {
  if (code == null) return getStockUrl(marketOrTsCode) || '';

  const normalizedCode = String(code).trim();
  if (marketOrTsCode === 'US') {
    return [usTradingViewUrl(normalizedCode), usSinaUrl(normalizedCode)].filter(Boolean);
  }
  if (marketOrTsCode === 'HK') {
    const digits = normalizedCode.replace(/[^0-9]/g, '');
    const hkCode = digits ? digits.padStart(5, '0') : normalizedCode.toUpperCase();
    return `https://stock.finance.sina.com.cn/hkstock/quotes/${hkCode}.html`;
  }
  return getStockUrl(normalizedCode) || '';
}
