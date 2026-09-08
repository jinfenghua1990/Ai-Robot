/** 美股代码 → 中文主营说明（用于盘后策略列表快速识别） */
export const US_BUSINESS_CN = {
  ALC: '眼科医疗器械与隐形眼镜', BTI: '烟草与尼古丁产品', COKE: '可口可乐装瓶与饮料分销',
  ELS: '房车与度假社区运营', EXR: '自助仓储与不动产运营', FLR: '工程设计与建筑服务',
  GXO: '合同物流与供应链服务', KO: '饮料与非酒精饮品',
  AAPL: '消费电子、软件与数字服务', MSFT: '软件、云计算与企业服务', NVDA: 'GPU芯片与人工智能计算',
  GOOGL: '互联网搜索、广告与云服务', AMZN: '电商零售与云计算', TSLA: '电动汽车与储能',
  JPM: '商业银行与综合金融服务', JNJ: '制药、医疗器械与健康消费品',
};

export function usBusinessCN(symbol) {
  return US_BUSINESS_CN[symbol] || '';
}
