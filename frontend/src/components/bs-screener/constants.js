// BSScreener 默认选股参数与信号类型常量
// 默认参数经 V7 全A股大规模调优验证（5206 只股票）
// V7: ATR(30,2.2)+MA60+MACD+RSI(40-60) 交易胜率 41.8% 个股胜率 44.4% 盈亏比 1.63
// V6: ATR(30,2.0)+MA60+MACD+RSI(30-70) 交易胜率 37.2% 个股胜率 42.1% 盈亏比 1.34
// V7 关键: RSI 严格区间 40-60 过滤超买超卖假信号，ATR 乘数 2.2 更精准
import { B_SIGNAL_COLOR, S_SIGNAL_COLOR } from '../../utils/colors';

export const DEFAULT_BS_PARAMS = {
  atr_period: 30,
  atr_multiplier: 2.2,
  scan_limit: 50,
  sector: '',
  signal_type: 'B',
  volume_filter: false,
  ma20_filter: false,
  ma60_trend: true,
  rsi_filter: true,
  rsi_lower: 40,
  rsi_upper: 60,
  strong_volume: false,
  macd_filter: true,
  kdj_filter: false,
  stop_loss_pct: 0,
  ma60_rising: false,
};

export const SIGNAL_TYPES = [
  { value: 'B', label: 'B点（买入）', color: B_SIGNAL_COLOR },
  { value: 'S', label: 'S点（卖出）', color: S_SIGNAL_COLOR },
  { value: 'ALL', label: '全部信号', color: '#3b82f6' },
];
