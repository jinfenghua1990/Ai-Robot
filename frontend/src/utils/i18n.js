/**
 * 数据质量相关翻译工具
 * 英文标识 → 中文显示
 */

// 置信度
export const confidenceMap = {
  high: '高',
  medium: '中',
  low: '低',
  disputed: '争议',
  no_data: '无数据',
};

// 处理动作
export const actionMap = {
  accept: '接受',
  correct: '已修正',
  reject: '拒绝',
  review: '待审核',
};

// 数据源名称
export const sourceMap = {
  eastmoney: '东方财富',
  em: '东方财富',
  em_push2: '东财push2',
  sina: '新浪',
  guosen: '国信证券',
  tencent: '腾讯财经',
  tushare: 'Tushare',
  tdx: '通达信',
  akshare: 'AKShare',
  efinance: 'efinance',
  qstock: 'qstock',
  adata: 'adata',
  ths: '同花顺',
  netease: '网易财经',
  cninfo: '巨潮资讯',
  mootdx: 'mootdx',
  baostock: 'baostock',
  sina_quote: '新浪行情',
  tencent_kline: '腾讯K线',
  itick: 'iTick',
  jqdata: '聚宽数据',
};

// 指标名称
export const indicatorMap = {
  main_force_inflow: '主力净流入',
  net_inflow: '净流入',
  retail_flow: '小单净流入',
  price: '价格',
  price_chg: '涨跌幅',
  net_flow: '净额',
  money_inflow: '资金流入',
  money_outflow: '资金流出',
  rise_ratio: '上涨率',
};

// 翻译函数
export const t = (value, map) => {
  if (!value) return value;
  return map[value] || value;
};

// 翻译置信度
export const tConfidence = (c) => t(c, confidenceMap);

// 翻译动作
export const tAction = (a) => t(a, actionMap);

// 翻译数据源（支持逗号分隔的多源）
export const tSource = (s) => {
  if (!s) return s;
  return s.split(',').map(src => t(src.trim(), sourceMap)).join('、');
};

// 翻译指标
export const tIndicator = (i) => t(i, indicatorMap);
