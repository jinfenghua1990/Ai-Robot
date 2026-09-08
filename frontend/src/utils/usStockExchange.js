/**
 * 美股代码 → TradingView 交易所前缀映射
 *
 * TradingView 链接格式：https://cn.tradingview.com/symbols/{EXCHANGE}-{SYMBOL}/technicals/
 * 实测 TradingView 对错误交易所前缀零容错（NASDAQ-BABA 直接 404），
 * 因此必须按股票实际上市交易所生成前缀：
 *   - NASDAQ：默认（绝大多数科技/成长股）
 *   - NYSE  ：传统蓝筹、金融、能源、工业、多数中概 ADR、医疗大盘
 *   - AMEX  ：ETF / NYSE Arca（TradingView 对 SPY/QQQ 等统一用 AMEX 前缀）
 *
 * 用法：usExchange('BABA') → 'NYSE'；未收录默认 'NASDAQ'
 */

// 常见 NYSE 上市股票（覆盖自选池 + 常用标的，其余默认 NASDAQ）
const NYSE_SET = new Set([
  // 中概 / ADR
  'BABA', 'TSM', 'EDU', 'CSIQ', 'YUMC', 'ZTO', 'YSG', 'CHT', 'TME', 'BEKE',
  'XPEV', 'NIO', 'CRCL', 'GDHG',
  // 金融
  'JPM', 'BAC', 'C', 'GS', 'MS', 'WFC', 'AXP', 'V', 'MA', 'ICE', 'CBOE',
  'SYF', 'SCHW', 'BLK', 'BK', 'AMP', 'AIG', 'BAP', 'CFG', 'ACGL', 'MET',
  'PRU', 'ALL', 'TRV', 'AON', 'ARES',
  // 消费
  'WMT', 'COST', 'TGT', 'HD', 'LOW', 'MCD', 'DPZ', 'KO', 'PEP', 'PG', 'NKE',
  'DECK', 'CASY', 'BBY', 'TJX', 'GAP', 'M', 'DG', 'DLTR', 'MDLZ', 'KMB',
  'CL', 'EL', 'ULTA', 'WBA', 'AOS', 'PM', 'MO', 'STZ', 'TAP', 'YUM',
  // 医疗（NYSE 部分）
  'JNJ', 'PFE', 'MRK', 'ABBV', 'LLY', 'BMY', 'ABT', 'MDT', 'SYK', 'BSX',
  'EW', 'ZBH', 'DHR', 'TMO', 'UNH', 'MCK', 'CAH', 'HUM', 'CI', 'ELV',
  'WST', 'BDX', 'ALC', 'NVO', 'HCA', 'AET', 'VEEV',
  // 工业 / 能源 / 公用 / 通信
  'BA', 'CAT', 'DE', 'GE', 'HON', 'MMM', 'ETN', 'EMR', 'PH', 'AWK', 'CEG',
  'GEV', 'AER', 'CPRT', 'CBRE', 'CCI', 'ATI', 'AU', 'SLB', 'HAL', 'OXY',
  'COP', 'EOG', 'PSX', 'VLO', 'MPC', 'KMI', 'WMB', 'NEM', 'FCX', 'XOM',
  'CVX', 'UPS', 'FDX', 'UNP', 'CSX', 'NSC', 'LMT', 'RTX', 'NOC', 'GD',
  'LHX', 'DAL', 'LUV', 'HLT', 'MGM', 'CCL', 'RCL', 'APH', 'TEL', 'T',
  'VZ', 'DIS', 'EIX', 'NPK', 'ICE',
]);

// ETF / NYSE Arca（TradingView 统一 AMEX 前缀）
const AMEX_SET = new Set([
  'SPY', 'VOO', 'IVV', 'QQQ', 'DIA', 'GLD', 'SLV', 'SHV', 'TLT', 'IEF',
  'HYG', 'LQD', 'VTI', 'IWM', 'EFA', 'EEM', 'ARKK', 'XLK', 'XLF', 'XLE',
  'XLV', 'XLY', 'XLI', 'XLP', 'XLU', 'XLB', 'XLRE', 'XLC', 'NVDS', 'UAMY',
]);

/**
 * 返回股票在 TradingView 的交易所前缀：'NASDAQ' | 'NYSE' | 'AMEX'
 */
export function usExchange(symbol) {
  const s = String(symbol || '').trim().toUpperCase();
  if (!s) return 'NASDAQ';
  if (AMEX_SET.has(s)) return 'AMEX';
  if (NYSE_SET.has(s)) return 'NYSE';
  return 'NASDAQ';
}

/**
 * 生成 TradingView 技术指标页链接
 * 例：usTradingViewUrl('MSFT') → https://cn.tradingview.com/symbols/NASDAQ-MSFT/technicals/
 */
export function usTradingViewUrl(symbol) {
  const s = String(symbol || '').trim().toUpperCase();
  if (!s) return '';
  return `https://cn.tradingview.com/symbols/${usExchange(s)}-${s}/technicals/`;
}

/**
 * 生成新浪财经美股行情页链接
 * 例：usSinaUrl('MSFT') → https://finance.sina.com.cn/stock/usstock/s/msft.shtml
 */
export function usSinaUrl(symbol) {
  const s = String(symbol || '').trim().toUpperCase();
  if (!s) return '';
  return `https://finance.sina.com.cn/stock/usstock/s/${s.toLowerCase()}.shtml`;
}
