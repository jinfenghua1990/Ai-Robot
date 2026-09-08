/**
 * 美股代码 → 行业板块（中文）映射表
 * 数据源：东财/新浪美股行业分类（行业相对稳定，手工维护）
 * 未收录的代码返回空字符串，前端不显示板块徽标
 */
export const US_SECTORS_CN = {
  ALC: '医疗器械', BTI: '烟草消费', COKE: '饮料', ELS: '房地产/房车社区', EXR: '房地产/仓储REIT',
  FLR: '工程建设', GXO: '物流', LEVI: '服装零售', OMC: '传媒广告', OTIS: '工业/电梯设备',
  RITM: '房地产金融', RYN: '林业与木材', SHOP: '电商软件', SNN: '医疗器械', TFX: '医疗器械', TRU: '金融信息服务',
  // ── 半导体 ──
  NVDA: '半导体', AVGO: '半导体', AMD: '半导体', MU: '半导体', INTC: '半导体',
  TSM: '半导体', ASML: '半导体', MRVL: '半导体', QCOM: '半导体', AMAT: '半导体设备',
  LRCX: '半导体设备', KLAC: '半导体设备', TER: '半导体设备', ARM: '半导体',
  SMCI: '计算机设备', SKHYV: '半导体', SKHY: '半导体', CBRS: '半导体',
  // ── 存储 ──
  WDC: '存储', SNDK: '存储', STX: '存储',
  // ── 软件 / 云 ──
  MSFT: '软件', ORCL: '软件', CRM: '软件', SNOW: '软件', INTU: '软件',
  ADBE: '软件', NOW: '软件', PLTR: '软件', DDOG: '软件', NET: '软件',
  MDB: '软件', PANW: '网络安全', CRWD: '网络安全', ZS: '网络安全',
  // ── 互联网 ──
  GOOGL: '互联网', GOOG: '互联网', META: '互联网', NFLX: '流媒体',
  AMZN: '电商零售', EBAY: '电商零售', BKNG: '互联网旅游', ABNB: '互联网旅游',
  // ── 消费电子 ──
  AAPL: '消费电子', DELL: '计算机设备', HPE: '计算机设备', IBM: '计算机设备',
  APH: '电子元件', TEL: '电子元件', LITE: '光通信', COHR: '光通信',
  // ── 汽车 ──
  TSLA: '汽车', GM: '汽车', F: '汽车', RIVN: '汽车',
  // ── 航空 / 军工 ──
  AAL: '航空', SPCX: '航天军工', BA: '航天军工', RTX: '航天军工',
  LMT: '航天军工', NOC: '航天军工', GD: '航天军工',
  // ── 工业 ──
  HON: '工业综合', MMM: '工业综合', GE: '工业综合', GEV: '电力设备',
  FAST: '工业分销', CAT: '工程机械', DE: '农机设备', ETN: '电气设备',
  PH: '工业综合', UNP: '铁路物流', UPS: '物流', FDX: '物流',
  URI: '建筑机械', PWR: '工程建设', CARR: '空调设备', TT: '工业综合',
  EMR: '工业自动化', ZBRA: '工业物联网', POWL: '电力设备', AMSC: '电力设备',
  AOS: '水暖设备', VRT: '电力设备',
  // ── 金融 ──
  JPM: '银行', BAC: '银行', WFC: '银行', C: '银行', GS: '投行',
  MS: '投行', V: '支付', MA: '支付', AXP: '信用卡', COF: '金融',
  SCHW: '券商', BLK: '资管', BX: '资管', KKR: '资管', HOOD: '券商',
  COIN: '数字货币', ICE: '金融数据', SPGI: '金融数据', MCO: '金融数据',
  CME: '交易所', CRCL: '金融科技',
  // ── 保险 ──
  UNH: '保险', CVS: '医疗零售',
  // ── 医药医疗 ──
  JNJ: '医疗健康', ABBV: '制药', MRK: '制药', PFE: '制药', NVO: '制药',
  AMGN: '生物制药', GILD: '生物制药', TMO: '医疗器械', DHR: '医疗器械',
  ISRG: '医疗器械', BSX: '医疗器械', MDT: '医疗器械', SYK: '医疗器械',
  REGN: '生物制药', VRTX: '生物制药', MRNA: '生物制药', BMY: '制药',
  CI: '健康保险', HCA: '医院', ABT: '医疗设备', WST: '医疗耗材',
  LLY: '制药',
  // ── 能源 ──
  XOM: '石油天然气', CVX: '石油天然气', COP: '石油天然气', OXY: '石油天然气',
  EOG: '石油天然气', DVN: '石油天然气', SLB: '油服', HAL: '油服',
  MPC: '炼油', VLO: '炼油', LNG: '天然气', FANG: '石油天然气',
  // ── 材料 ──
  FCX: '有色矿业', NEM: '黄金矿业', NUE: '钢铁', STLD: '钢铁',
  AA: '电解铝', CCJ: '铀矿',
  // ── 消费 ──
  WMT: '商超零售', COST: '仓储零售', TGT: '商超零售', TJX: '折扣零售',
  HD: '家居建材', LOW: '家居建材', NKE: '鞋服', DECK: '鞋服',
  MCD: '餐饮', SBUX: '餐饮', DPZ: '餐饮', CMG: '餐饮', YUM: '餐饮',
  ORLY: '汽车配件', AZO: '汽车配件', ROST: '折扣零售',
  PG: '日用消费', KO: '饮料', PEP: '饮料', PM: '烟草', MO: '烟草',
  MDLZ: '食品', CL: '日用消费', MNST: '饮料', KHC: '食品', KR: '商超零售',
  HLT: '酒店', MAR: '酒店', RCL: '邮轮', CCL: '邮轮', DIS: '传媒娱乐',
  // ── 公用事业 ──
  NEE: '电力', CEG: '电力', VST: '电力', SO: '电力', DUK: '电力',
  AEP: '电力', SRE: '电力', EXC: '电力', EIX: '公用事业',
  // ── 房地产 ──
  DLR: '数据中心REIT', AMT: '通信塔REIT', PLD: '物流REIT', EQIX: '数据中心REIT',
  O: '商业REIT', SPG: '商业REIT',
  // ── ETF ──
  SPY: '大盘ETF', QQQ: '科技ETF', NVDS: '杠杆ETF', SOXX: '半导体ETF',
  SMH: '半导体ETF', XLK: '科技ETF', XLC: '通信ETF', XLY: '消费ETF',
  XLF: '金融ETF', XLI: '工业ETF', XLV: '医疗ETF', XLE: '能源ETF',
  XLB: '材料ETF', XLP: '必需消费ETF', XLU: '公用事业ETF', XLRE: '房地产ETF',
};

/** 美股代码 → 行业中文名；未收录返回 ''（前端不显示徽标） */
export function usSectorCN(sym) {
  return US_SECTORS_CN[sym] || '';
}
