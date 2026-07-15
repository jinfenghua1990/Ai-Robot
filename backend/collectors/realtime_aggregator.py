"""
盘中实时聚合器（DB-first 中转层 - 实时轨）

数据流（每 5 秒轮询,零外部调用）:
    realtime_stock_flow 表（由 scheduled_realtime_snapshot 每分钟写入,唯一外部采集入口）
        → 本模块读最新一批快照 → 内存聚合大单/主动率/承接指标
        → 写入 REALTIME_STATE dict → FastAPI /api/v1/stock/super_panel 直接读
        → 同时落库 stock_realtime_tick（供 V 字反转回溯,保持兼容）

设计原则（DB-first）:
- 采集与运算彻底分离:外部行情只由 realtime_collector 采集一次进 realtime_stock_flow
- 本模块不做任何外部 HTTP 请求（不拉东财/腾讯/新浪）,仅读本地库 + 本地运算
- 带宽竞争消除:东财请求量降到每分钟 1 次（snapshot 单路）
"""
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================
# 内存中转：单只股票的实时态
# ============================================================
@dataclass
class RealtimeState:
    """单只股票的盘中实时态（数据来自 realtime_stock_flow,无盘口）"""
    ts_code: str

    # 最近一次快照
    last_price: float = 0.0
    last_volume: int = 0                                # 累计成交量(手)
    last_amount: float = 0.0                            # 累计成交额(元)
    last_bid_price_1: float = 0.0
    last_bid_vol_1: int = 0
    last_ask_price_1: float = 0.0
    last_ask_vol_1: int = 0
    last_turnover_rate: float = 0.0
    last_main_force_inflow: float = 0.0                 # 主力净流入(元)
    last_snapshot_time: Optional[datetime] = None
    last_source: str = ''
    last_close: float = 0.0                             # 昨收价(realtime_stock_flow 不含,置0)
    last_pct_chg: float = 0.0                           # 涨跌幅 %(源端已算)

    # 大单检测（分钟级代理,基于主力净流入）
    large_buy_count_3s: int = 0
    large_sell_count_3s: int = 0
    large_order_active_ratio: float = 0.0               # 主动买入比 %

    # 千单频次（分钟级代理）
    thousand_count_1m: int = 0

    # 滑窗:保留接口,分钟级下仅记录批次（不再做秒级滑窗）
    _thousand_log: deque = field(default_factory=deque)
    _active_log: deque = field(default_factory=deque)

    # 累计当日大单笔数
    total_large_buy_today: int = 0
    total_large_sell_today: int = 0
    total_thousand_today: int = 0

    def update_from_flow(self, flow):
        """从 realtime_stock_flow 行更新实时态（DB-first,无外部调用）
        flow: db.models.RealtimeStockFlow 实例
        """
        self.last_price = float(flow.price or 0)
        self.last_pct_chg = float(flow.price_chg or 0)
        # main_force_inflow 库里单位是万元,统一转元保持与下游一致
        mfi = float(flow.main_force_inflow or 0) * 10000
        self.last_main_force_inflow = mfi
        self.last_snapshot_time = flow.snapshot_time
        self.last_source = flow.source or 'db'
        self.last_close = 0.0
        # 基于主力净流入更新大单/主动率（无盘口降级）
        self.record_flow_inflow(mfi)

    def record_flow_inflow(self, main_force_inflow_yuan: float):
        """无盘口环境下,用主力净流入(元)代理大单主动率与方向计数
        - 主动率:主力净流入为正→主动买,负→主动卖,1000万为强信号阈值
        - 方向计数:分钟级,每只每分钟一次
        """
        scale = 10_000_000.0  # 1000万
        ratio = 50.0 + (main_force_inflow_yuan / scale) * 50.0
        self.large_order_active_ratio = round(max(0.0, min(100.0, ratio)), 1)
        if main_force_inflow_yuan > 0:
            self.large_buy_count_3s = 1
            self.large_sell_count_3s = 0
            self.total_large_buy_today += 1
        elif main_force_inflow_yuan < 0:
            self.large_buy_count_3s = 0
            self.large_sell_count_3s = 1
            self.total_large_sell_today += 1
        else:
            self.large_buy_count_3s = 0
            self.large_sell_count_3s = 0
        # 千单频次代理:|主力净流入| >= 1000万 视为有大单活跃
        if abs(main_force_inflow_yuan) >= scale:
            self.thousand_count_1m = 1
            self.total_thousand_today += 1
        else:
            self.thousand_count_1m = 0


# 全局字典（进程级）
REALTIME_STATE: Dict[str, RealtimeState] = {}

# 最近已处理的快照批次时间（去重:避免重复批次重复写库）
_last_processed_snapshot_time = None


def get_or_create_state(ts_code: str) -> RealtimeState:
    if ts_code not in REALTIME_STATE:
        REALTIME_STATE[ts_code] = RealtimeState(ts_code=ts_code)
    return REALTIME_STATE[ts_code]


def serialize_state(ts_code: str) -> Optional[dict]:
    """序列化单只股票的实时态供 API 返回"""
    s = REALTIME_STATE.get(ts_code)
    if not s:
        return None
    pct = s.last_pct_chg
    if not pct and s.last_close and s.last_price:
        pct = round((s.last_price - s.last_close) / s.last_close * 100, 2)
    return {
        'current_price': s.last_price,
        'pct_chg': pct,
        'last_close': s.last_close,
        'volume': s.last_volume,
        'amount': s.last_amount,
        'bid_price_1': s.last_bid_price_1,
        'bid_vol_1': s.last_bid_vol_1,
        'ask_price_1': s.last_ask_price_1,
        'ask_vol_1': s.last_ask_vol_1,
        'turnover_rate': s.last_turnover_rate,
        'main_force_inflow': s.last_main_force_inflow,
        'large_order_active_ratio': s.large_order_active_ratio,
        'large_buy_count_3s': s.large_buy_count_3s,
        'large_sell_count_3s': s.large_sell_count_3s,
        'thousand_order_count_per_min': s.thousand_count_1m,
        'total_large_buy_today': s.total_large_buy_today,
        'total_large_sell_today': s.total_large_sell_today,
        'total_thousand_today': s.total_thousand_today,
        'support_level_eval': _evaluate_support(s),
        'snapshot_time': s.last_snapshot_time.isoformat() if s.last_snapshot_time else None,
        'source': s.last_source,
    }


def _evaluate_support(s: RealtimeState) -> str:
    """基于主力净流入 + 涨跌幅 评价承接力度（无盘口降级）"""
    mfi = s.last_main_force_inflow or 0
    pct = s.last_pct_chg or 0
    if mfi > 0 and pct > 0:
        return '🟢 主力净流入 + 上涨，主动买入承接强'
    if mfi > 0 and pct <= 0:
        return '🟡 主力净流入但价未涨，承接偏强'
    if mfi < 0 and pct < 0:
        return '🔴 主力净流出 + 下跌，承接弱'
    if mfi < 0 and pct >= 0:
        return '🟡 主力净流出但价抗跌，承接偏弱'
    return '⚪ 中性'


# ============================================================
# 调度入口：每 5 秒轮询（DB-first,零外部调用）
# ============================================================
def collect_realtime_snapshot():
    """
    DB-first 盘中聚合（每 5 秒轮询,scheduled 仅在交易时段触发）:
    1. 读 realtime_stock_flow 最新一批快照（由 collect_realtime_stock_flow 每分钟写入）
    2. 更新 REALTIME_STATE 内存 dict（供 super_panel 读）
    3. 仅当有新快照批次时,落库 stock_realtime_tick（供 V 字反转回溯,保持兼容）
    本函数不做任何外部 HTTP 请求。
    """
    global _last_processed_snapshot_time
    from db.session import get_db_session
    from db.models import RealtimeStockFlow
    from sqlalchemy import func

    today = datetime.now().date()
    try:
        with get_db_session() as db:
            latest = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
                RealtimeStockFlow.trade_date == today
            ).scalar()
            if not latest:
                logger.debug('[realtime_aggregator] 暂无实时快照数据（可能非交易时段）')
                return
            if _last_processed_snapshot_time and latest <= _last_processed_snapshot_time:
                # 无新批次,跳过（REALTIME_STATE 已是最新）
                return
            rows = db.query(RealtimeStockFlow).filter(
                RealtimeStockFlow.trade_date == today,
                RealtimeStockFlow.snapshot_time == latest,
            ).all()
    except Exception as e:
        logger.warning(f'[realtime_aggregator] 读取 realtime_stock_flow 失败: {e}')
        return

    if not rows:
        return

    logger.info(f'[realtime_aggregator] 处理 {len(rows)} 只股票 (snapshot={latest})')

    # 1) 更新内存态（本地运算,无网络）
    for flow in rows:
        state = get_or_create_state(flow.ts_code)
        state.update_from_flow(flow)

    # 2) 新批次:落库 stock_realtime_tick（保持 core.py V 字反转检测兼容）
    tick_rows = []
    for flow in rows:
        mfi = float(flow.main_force_inflow or 0) * 10000
        tick_rows.append({
            'snapshot_time': flow.snapshot_time,
            'trade_date': today,
            'ts_code': flow.ts_code,
            'price': float(flow.price or 0),
            'volume': 0,
            'amount': 0,
            'bid_price_1': 0,
            'bid_vol_1': 0,
            'ask_price_1': 0,
            'ask_vol_1': 0,
            'turnover_rate': 0,
            'main_force_inflow': mfi,
            'source': 'realtime_stock_flow',
        })
    if tick_rows:
        try:
            from db.connection import engine
            from sqlalchemy import text
            with engine.connect() as conn:
                conn.execute(
                    text("""
                        INSERT INTO stock_realtime_tick
                        (snapshot_time, trade_date, ts_code, price, volume, amount,
                         bid_price_1, bid_vol_1, ask_price_1, ask_vol_1,
                         turnover_rate, main_force_inflow, source)
                        VALUES (:snapshot_time, :trade_date, :ts_code, :price, :volume, :amount,
                                :bid_price_1, :bid_vol_1, :ask_price_1, :ask_vol_1,
                                :turnover_rate, :main_force_inflow, :source)
                    """),
                    tick_rows
                )
                conn.commit()
        except Exception as e:
            logger.warning(f'[realtime_aggregator] tick 落库失败: {e}')

    _last_processed_snapshot_time = latest


# ============================================================
# 收盘清理
# ============================================================
def cleanup_realtime_after_close():
    """收盘 15:30 后清理实时数据(tick/盘口/1分钟资金流向快照均保留 30 天)"""
    from db.connection import engine
    from sqlalchemy import text
    cutoff = datetime.now().date() - timedelta(days=30)
    with engine.connect() as conn:
        conn.execute(text("DELETE FROM stock_realtime_orderbook WHERE trade_date < :cutoff"), {"cutoff": cutoff})
        conn.execute(text("DELETE FROM stock_realtime_tick WHERE trade_date < :cutoff"), {"cutoff": cutoff})
        conn.execute(text("DELETE FROM realtime_stock_flow WHERE trade_date < :cutoff"), {"cutoff": cutoff})
        conn.commit()
    logger.info(f'[realtime_aggregator] cleanup done (keep tick/orderbook/realtime_stock_flow since {cutoff}')
