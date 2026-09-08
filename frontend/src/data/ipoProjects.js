// ─────────────────────────────────────────────────────────────────────────
// IPO 项目跟踪配置（数据驱动）
//
// 设计说明：
//  · 后端暂无「新股日历 / 申购 / 中签 / 上市日」接口，因此 IPO 进程由本配置维护。
//  · 页面按当前时间(Date.now)自动计算「所处阶段 + 实时倒计时」，日期到了自动推进，
//    无需改组件代码——只改这里的 stages / 日期即可。
//  · 上市后(listed=true 且 code 有值)，后跟踪模块会自动拉取该公司自身实时行情。
//
// 字段说明：
//  · stages[].date：'YYYY-MM-DD'（按北京时间解析）；为 null 表示「待披露/尚未确定」。
//  · issuePrice：发行价（元），用于「较发行价涨跌幅」；为 null 时显示「待补充」。
//  · totalShares：总股本（股），用于市值估算；为 null 时隐藏市值。
//  · 以上金融数字请确保与招股书/公告一致后再填，避免误导。
// ─────────────────────────────────────────────────────────────────────────

export const IPO_PROJECTS = {
  // 长鑫科技（CXMT）—— 已上市
  cxmt: {
    key: 'cxmt',
    name: '长鑫科技',
    code: '688825', // 上市后代码
    board: '科创板',
    listed: true,
    issuePrice: null, // 发行价待补充（填数字即可启用「较发行价」）
    totalShares: null, // 总股本待补充（填数字即可启用市值估算）
    stages: [
      { key: 'filed', label: '申报受理', date: '2025-12-20' },
      { key: 'inquiry', label: '问询', date: '2026-02-10' },
      { key: 'passed', label: '过会', date: '2026-04-15' },
      { key: 'register', label: '注册生效', date: '2026-06-20' },
      { key: 'price', label: '询价定价', date: '2026-07-15' },
      { key: 'subscribe', label: '网上申购', date: '2026-07-16' },
      { key: 'lottery', label: '中签缴款', date: '2026-07-20' },
      { key: 'result', label: '发行结果', date: '2026-07-22' },
      { key: 'listed', label: '上市交易', date: '2026-07-28' },
    ],
  },

  // 宇树科技（Unitree）—— 申报中，未上市
  unitree: {
    key: 'unitree',
    name: '宇树科技',
    code: null, // 未上市，代码待定
    board: '科创板',
    listed: false,
    issuePrice: null,
    totalShares: null,
    stages: [
      { key: 'filed', label: '申报受理', date: '2026-06-30' },
      { key: 'inquiry', label: '问询', date: null },
      { key: 'passed', label: '过会', date: null },
      { key: 'register', label: '注册生效', date: null },
      { key: 'price', label: '询价定价', date: null },
      { key: 'subscribe', label: '网上申购', date: null },
      { key: 'lottery', label: '中签缴款', date: null },
      { key: 'result', label: '发行结果', date: null },
      { key: 'listed', label: '上市交易', date: null },
    ],
  },
};

// 解析配置里的日期为时间戳（北京时间）
export function parseStageDate(d) {
  if (!d) return null;
  return Date.parse(d + 'T00:00:00+08:00');
}
