/**
 * 根据 ts_code 生成新浪财经实时行情链接
 * 支持两种格式：带后缀 "688981.SH" 或纯6位代码 "688981"
 * @param {string} tsCode - 股票代码
 * @returns {string} 新浪财经链接，无法解析时返回 null
 */
export function getStockUrl(tsCode) {
  if (!tsCode) return null;
  const parts = tsCode.toUpperCase().split('.');
  let code, exchange;
  if (parts.length === 2) {
    [code, exchange] = parts;
  } else if (parts.length === 1 && /^\d{6}$/.test(tsCode)) {
    // 纯6位代码：6/9开头为沪市，0/3开头为深市
    code = tsCode;
    exchange = tsCode[0] === '6' || tsCode[0] === '9' ? 'SH' : 'SZ';
  } else {
    return null;
  }
  if (exchange === 'SH') {
    return `https://finance.sina.com.cn/realstock/company/sh${code}/nc.shtml`;
  }
  if (exchange === 'SZ') {
    return `https://finance.sina.com.cn/realstock/company/sz${code}/nc.shtml`;
  }
  return null;
}

/**
 * 根据板块名称生成新浪财经板块行情链接
 * @param {string} sectorName - 板块名称，如 "半导体"、"元器件"
 * @returns {string} 新浪财经板块搜索链接
 */
export function getSectorUrl(sectorName) {
  if (!sectorName) return null;
  return `https://search.sina.com.cn/?q=${encodeURIComponent(sectorName + ' 板块')}&c=stock`;
}

/**
 * 根据 ts_code 生成东方财富实时行情链接
 * @param {string} tsCode - 股票代码
 * @returns {string} 东方财富链接，无法解析时返回 null
 */
export function getEastMoneyUrl(tsCode) {
  if (!tsCode) return null;
  const parts = tsCode.toUpperCase().split('.');
  let code, exchange;
  if (parts.length === 2) {
    [code, exchange] = parts;
  } else if (parts.length === 1 && /^\d{6}$/.test(tsCode)) {
    code = tsCode;
    exchange = tsCode[0] === '6' || tsCode[0] === '9' ? 'SH' : 'SZ';
  } else {
    return null;
  }
  if (exchange === 'SH') {
    return `https://quote.eastmoney.com/sh${code}.html`;
  }
  if (exchange === 'SZ') {
    return `https://quote.eastmoney.com/sz${code}.html`;
  }
  return null;
}

/**
 * 根据 ts_code 生成同花顺行情链接
 * @param {string} tsCode - 股票代码
 * @returns {string} 同花顺链接，无法解析时返回 null
 */
export function getTHSUrl(tsCode) {
  if (!tsCode) return null;
  const parts = tsCode.toUpperCase().split('.');
  let code;
  if (parts.length === 2) {
    code = parts[0];
  } else if (parts.length === 1 && /^\d{6}$/.test(tsCode)) {
    code = tsCode;
  } else {
    return null;
  }
  return `https://stockpage.10jqka.com.cn/${code}/`;
}

/**
 * 根据 ts_code 生成腾讯财经行情链接（a-stock-data 底层数据源）
 * @param {string} tsCode - 股票代码
 * @returns {string} 腾讯财经链接，无法解析时返回 null
 */
export function getTencentUrl(tsCode) {
  if (!tsCode) return null;
  const parts = tsCode.toUpperCase().split('.');
  let code, exchange;
  if (parts.length === 2) {
    [code, exchange] = parts;
  } else if (parts.length === 1 && /^\d{6}$/.test(tsCode)) {
    code = tsCode;
    exchange = tsCode[0] === '6' || tsCode[0] === '9' ? 'SH' : 'SZ';
  } else {
    return null;
  }
  if (exchange === 'SH') {
    return `https://gu.qq.com/sh${code}`;
  }
  if (exchange === 'SZ') {
    return `https://gu.qq.com/sz${code}`;
  }
  return null;
}

/**
 * 根据 ts_code 生成国信证券金太阳行情链接
 * 国信证券没有公开网页行情，跳转到金太阳在线交易页面
 * @param {string} tsCode - 股票代码
 * @returns {string} 国信证券链接，无法解析时返回 null
 */
export function getGuosenUrl(tsCode) {
  if (!tsCode) return null;
  const parts = tsCode.toUpperCase().split('.');
  let code;
  if (parts.length === 2) {
    code = parts[0];
  } else if (parts.length === 1 && /^\d{6}$/.test(tsCode)) {
    code = tsCode;
  } else {
    return null;
  }
  // 国信证券金太阳网页版行情搜索
  return `https://www.guosen.com.cn/search.html?q=${code}`;
}

/**
 * 股票行悬停样式（可点击态）
 */
export const stockRowHover = {
  cursor: 'pointer',
  transition: 'background 0.15s',
};

export const stockRowHoverStyle = (isHover) => ({
  background: isHover ? 'var(--bg-hover)' : 'transparent',
});