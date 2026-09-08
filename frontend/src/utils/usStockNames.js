/**
 * 美股股票中文名映射
 * 覆盖：盈立自选池 / 核心扫描池候选 / 持仓 / 信号 及常见大盘股、中概股、ETF
 * 未收录的股票回退英文名（simplifyUSName 精简掉后缀词）
 */

export const US_NAMES_CN = {
  // ── 科技巨头 ──
  AAPL: '苹果', MSFT: '微软', NVDA: '英伟达', GOOGL: '谷歌', GOOG: '谷歌',
  AMZN: '亚马逊', META: 'Meta', NFLX: '奈飞', AMD: '超威半导体', AVGO: '博通',
  INTC: '英特尔', ORCL: '甲骨文', CRM: '赛富时', ADBE: '奥多比', CSCO: '思科',
  QCOM: '高通', TXN: '德州仪器', MU: '美光科技', AMAT: '应用材料', LRCX: '泛林集团',
  KLAC: '科磊', ADI: '亚德诺', MRVL: '迈威尔科技', NTAP: '网存', TER: '泰瑞达',
  STX: '希捷', WDC: '西部数据', SNDK: '闪迪', SMCI: '超微电脑', SNOW: '雪花',
  PLTR: 'Palantir', CRWD: 'CrowdStrike', NOW: 'ServiceNow', INTU: '直觉（财捷）',
  PANW: '派拓网络', ZS: 'Zscaler', NET: 'Cloudflare', DDOG: 'Datadog',
  LITE: 'Lumentum', COIN: 'Coinbase', HOOD: '罗宾汉', MSTR: 'MicroStrategy',
  RBLX: 'Roblox', SPOT: '声田', SNAP: 'Snap', PINS: 'Pinterest', OKTA: 'Okta',
  UBER: '优步', LYFT: '来福车', ABNB: '爱彼迎', SHOP: 'Shopify', SQ: 'Block',
  PYPL: '贝宝', SOFI: 'SoFi', NBIS: 'Nebius', APLD: '应用数字', CRCL: 'Circle',
  DELL: '戴尔', TSLA: '特斯拉', A: '安捷伦',

  // ── 中概股 ──
  BABA: '阿里巴巴', PDD: '拼多多', JD: '京东', BIDU: '百度', NTES: '网易',
  TCOM: '携程', EDU: '新东方', WB: '微博', XPEV: '小鹏汽车', TSM: '台积电',
  CSIQ: '阿特斯太阳能', GDS: '万国数据', YUMC: '百胜中国', ZTO: '中通快递',
  KC: '金山云', YSG: '逸仙电商', CHT: '中华电信', NIO: '蔚来', LI: '理想汽车',
  BILI: '哔哩哔哩', IQ: '爱奇艺', TME: '腾讯音乐',
  BEKE: '贝壳', FUTU: '富途控股', TIGR: '老虎证券',

  // ── 金融 ──
  JPM: '摩根大通', BAC: '美国银行', C: '花旗集团', GS: '高盛', MS: '摩根士丹利',
  WFC: '富国银行', AXP: '美国运通', V: '维萨', MA: '万事达', ICE: '洲际交易所',
  CBOE: '芝加哥期权交易所', SYF: '森信金融', SCHW: '嘉信理财',
  BLK: '贝莱德', BK: '纽约梅隆', AMP: '阿默普莱斯金融', AIG: '美国国际集团',
  BAP: 'Credicorp', CFG: '公民金融', ACGL: 'Arch资本', MET: '大都会人寿',
  PRU: '保德信金融', ALL: '好事达', TRV: '旅行者保险', AON: '怡安',

  // ── 消费 / 零售 ──
  WMT: '沃尔玛', COST: '好市多', TGT: '塔吉特', HD: '家得宝', LOW: '劳氏',
  MCD: '麦当劳', SBUX: '星巴克', YUM: '百胜集团', DPZ: '达美乐比萨',
  KO: '可口可乐', PEP: '百事', PG: '宝洁', NKE: '耐克', LULU: '露露乐蒙',
  DECK: '德克斯户外', CASY: '凯西百货', EBAY: '易趣', BBY: '百思买',
  TJX: 'TJX公司', GAP: '盖璞', M: '梅西百货', DG: '达乐', DLTR: '美元树',
  MDLZ: '亿滋国际', KMB: '金佰利', CL: '高露洁', EL: '雅诗兰黛',
  ULTA: 'Ulta美妆', WBA: '沃尔格林', AOS: '艾欧史密斯',
  PM: '菲利普莫里斯', MO: '奥驰亚', STZ: '星座品牌', TAP: '莫尔森库尔斯',

  // ── 医疗健康 ──
  JNJ: '强生', PFE: '辉瑞', MRK: '默沙东', ABBV: '艾伯维', LLY: '礼来',
  BMY: '百时美施贵宝', GILD: '吉利德', AMGN: '安进', VRTX: '福泰制药',
  REGN: '再生元', MRNA: '莫德纳', BIIB: '渤健', ABT: '雅培', MDT: '美敦力',
  SYK: '史赛克', BSX: '波士顿科学', EW: '爱德华兹生命科学', ZBH: '捷迈邦美',
  ISRG: '直觉外科', DHR: '丹纳赫', TMO: '赛默飞世尔', UNH: '联合健康',
  MCK: '麦克森', CAH: '卡地纳健康', HUM: '哈门那', CI: '信诺',
  ELV: 'Elevance健康', WST: '西氏医药', BDX: '碧迪医疗', ALC: '爱尔康', BTI: '英美烟草',
  NVO: '诺和诺德', HCA: 'HCA医疗', AET: '安泰保险', VEEV: 'Veeva系统',

  // ── 工业 / 能源 / 材料 ──
  BA: '波音', CAT: '卡特彼勒', DE: '迪尔', GE: '通用电气', HON: '霍尼韦尔',
  MMM: '3M', ETN: '伊顿', EMR: '艾默生电气', PH: '派克汉尼汾',
  EIX: '爱迪生国际', AWK: '美国水务', CEG: '星座能源', GEV: 'GE Vernova',
  ARES: '阿瑞斯管理', AER: 'AerCap航空租赁', CPRT: '科帕特', CBRE: '世邦魏理仕',
  CCI: '皇冠城堡', ATI: 'ATI公司', AU: '盎格鲁金矿',
  SLB: '斯伦贝谢', HAL: '哈里伯顿', OXY: '西方石油', COP: '康菲石油',
  EOG: 'EOG能源', PSX: '菲利普斯66', VLO: '瓦莱罗', MPC: '马拉松石油',
  KMI: '金德摩根', WMB: '威廉姆斯', NEM: '纽蒙特', FCX: '自由港麦克莫兰',
  XOM: '埃克森美孚', CVX: '雪佛龙', UPS: '联合包裹', FDX: '联邦快递',
  UNP: '联合太平洋', CSX: 'CSX运输', NSC: '诺福克南方', LMT: '洛克希德马丁',
  RTX: '雷神技术', NOC: '诺斯罗普格鲁曼', GD: '通用动力', LHX: 'L3哈里斯',
  AAL: '美国航空', DAL: '达美航空', UAL: '美联航', LUV: '西南航空',
  HLT: '希尔顿', BKNG: '缤客', MGM: '美高梅', CCL: '嘉年华邮轮',
  RCL: '皇家加勒比', APH: '安费诺', TEL: 'TE连接', POWL: '鲍威尔实业',
  ZBRA: '斑马技术', T: '美国电话电报', VZ: '威瑞森', TMUS: 'T-Mobile',
  CHTR: '特许通讯', CMCSA: '康卡斯特', DIS: '迪士尼', WBD: '华纳兄弟探索',
  UAMY: '美国锑业', AMSC: '美国超导', NPK: 'National Presto',

  // ── 常用 ETF / 指数 ──
  SPY: '标普500 ETF', VOO: '标普500 ETF', IVV: '标普500 ETF', QQQ: '纳指100 ETF',
  DIA: '道指ETF', GLD: '黄金ETF', SLV: '白银ETF', SHV: '短期国债ETF',
  TLT: '长久期国债ETF', IEF: '中期国债ETF', HYG: '高收益债ETF', LQD: '投资级债ETF',
  VTI: '全市场ETF', IWM: '罗素2000 ETF', EFA: '发达市场ETF', EEM: '新兴市场ETF',
  ARKK: 'ARK创新ETF', XLK: '科技板块ETF', XLF: '金融板块ETF', XLE: '能源板块ETF',
  XLV: '医疗板块ETF', XLY: '消费板块ETF', XLI: '工业板块ETF', XLP: '必需消费ETF',
  XLU: '公用事业ETF', XLB: '材料板块ETF', XLRE: '房地产ETF', XLC: '通信板块ETF',
  SKHY: 'SK海力士', SKHYV: 'SK海力士-WI', NVDS: '英伟达多空ETF', SPCX: 'SpaceX',
  GDHG: '黄金天堂集团', CRWV: 'CoreWeave', CBRS: 'Cerebras Systems',
  FAST: '快扣',
};

/** 获取美股中文名（未收录返回空串，由调用方回退英文名/代码） */
export function usNameCN(symbol) {
  if (!symbol) return '';
  return US_NAMES_CN[symbol.toUpperCase()] || '';
}

/** 精简英文全名：去掉 Common Stock / Class A / Corporation 等后缀，避免表格过宽 */
export function simplifyUSName(name) {
  if (!name) return '';
  return String(name)
    .replace(/Common Stock$/i, '')
    .replace(/Ordinary Shares$/i, '')
    .replace(/\bClass [A-Z]\b/g, '')
    .replace(/\b(Inc\.?|Corporation|Corp\.?|Company|Ltd\.?|Limited|Co\.?|Holdings?|Group|PLC|N\.V\.?)\b/g, '')
    .replace(/\s{2,}/g, ' ')
    .replace(/[,\s]+$/, '')
    .trim();
}
