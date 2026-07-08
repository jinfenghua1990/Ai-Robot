"""
盘中实时聚合器（双轨制中转层 - 实时轨）

数据流（每 3 秒）:
    iTick/mootdx 拉 tick → 写入 stock_realtime_tick → 内存聚合大单指标
    → 写入 REALTIME_STATE dict → FastAPI /api/v1/stock/super_panel 直接读

为什么用进程内 dict 而非 Redis:
- 部署单实例,无分布式需求
- 避免引入 Redis 依赖
- 进程重启 = 数据从 0 重算,可接受
- 如需多实例,只需把 REALTIME_STATE 替换为 redis.Redis 即可,API 不变
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
    """单只股票的盘中实时态"""
    ts_code: str

    # 最近一次 tick
    last_price: float = 0.0
    last_volume: int = 0                                # 累计成交量(手)
    last_amount: float = 0.0                            # 累计成交额(元)
    last_bid_price_1: float = 0.0
    last_bid_vol_1: int = 0
    last_ask_price_1: float = 0.0
    last_ask_vol_1: int = 0
    last_turnover_rate: float = 0.0
    last_main_force_inflow: float = 0.0
    last_snapshot_time: Optional[datetime] = None
    last_source: str = ''
    last_close: float = 0.0                             # 昨收价(用于算 pct_chg)
    last_pct_chg: float = 0.0                           # 涨跌幅 %(源端已算)

    # 大单检测（近 3 秒）
    large_buy_count_3s: int = 0
    large_sell_count_3s: int = 0
    large_order_active_ratio: float = 0.0               # 主动买入比 %

    # 千单频次（近 1 分钟滑窗）
    thousand_count_1m: int = 0

    # 滑窗:近 60 秒每笔大单(用于千单频次)
    _thousand_log: deque = field(default_factory=deque)

    # 滑窗:近 3 秒每笔大单方向(用于主动率)
    _active_log: deque = field(default_factory=deque)

    # 累计当日大单笔数
    total_large_buy_today: int = 0
    total_large_sell_today: int = 0
    total_thousand_today: int = 0

    def add_tick(self, tick: dict):
        """更新最新 tick,并触发大单检测"""
        self.last_price = float(tick.get('price', 0) or 0)
        self.last_volume = int(tick.get('volume', 0) or 0)
        self.last_amount = float(tick.get('amount', 0) or 0)
        self.last_bid_price_1 = float(tick.get('bid_price_1', 0) or 0)
        self.last_bid_vol_1 = int(tick.get('bid_vol_1', 0) or 0)
        self.last_ask_price_1 = float(tick.get('ask_price_1', 0) or 0)
        self.last_ask_vol_1 = int(tick.get('ask_vol_1', 0) or 0)
        self.last_turnover_rate = float(tick.get('turnover_rate', 0) or 0)
        self.last_main_force_inflow = float(tick.get('main_force_inflow', 0) or 0)
        self.last_snapshot_time = tick.get('snapshot_time', datetime.now())
        self.last_source = tick.get('source', '')
        self.last_close = float(tick.get('last_close', 0) or 0)
        self.last_pct_chg = float(tick.get('pct_chg', 0) or 0)

    def record_large_order(self, side: str, lots: int):
        """记录一笔大单(用于统计主动率和千单频次)
        side: 'buy' / 'sell'
        lots: 本笔成交量(手)
        """
        now = datetime.now()
        # 千单频次(>=1000 手)
        if lots >= 1000:
            self._thousand_log.append((now, side, lots))
            self.total_thousand_today += 1
            # 清理 1 分钟之外
            cutoff = now - timedelta(seconds=60)
            while self._thousand_log and self._thousand_log[0][0] < cutoff:
                self._thousand_log.popleft()
            self.thousand_count_1m = len(self._thousand_log)

        # 大单(>= 100 手)用于主动率
        if lots >= 100:
            self._active_log.append((now, side, lots))
            cutoff = now - timedelta(seconds=3)
            while self._active_log and self._active_log[0][0] < cutoff:
                self._active_log.popleft()
            buys = sum(1 for _, s, _ in self._active_log if s == 'buy')
            sells = sum(1 for _, s, _ in self._active_log if s == 'sell')
            total = buys + sells
            self.large_buy_count_3s = buys
            self.large_sell_count_3s = sells
            self.large_order_active_ratio = round(buys / total * 100, 1) if total > 0 else 0.0

            if side == 'buy':
                self.total_large_buy_today += 1
            else:
                self.total_large_sell_today += 1


# 全局字典（进程级）
REALTIME_STATE: Dict[str, RealtimeState] = {}


def get_or_create_state(ts_code: str) -> RealtimeState:
    if ts_code not in REALTIME_STATE:
        REALTIME_STATE[ts_code] = RealtimeState(ts_code=ts_code)
    return REALTIME_STATE[ts_code]


def serialize_state(ts_code: str) -> Optional[dict]:
    """序列化单只股票的实时态供 API 返回"""
    s = REALTIME_STATE.get(ts_code)
    if not s:
        return None
    # 优先用源端已算好的 pct_chg(腾讯接口直接给)
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
    """根据买一/卖一盘口 + 主动率 评价承接力度"""
    if s.last_bid_vol_1 == 0 and s.last_ask_vol_1 == 0:
        return '⚪ 无盘口数据'

    # 买盘远大于卖盘 = 强承接
    if s.last_bid_vol_1 > 0 and s.last_ask_vol_1 > 0:
        ratio = s.last_bid_vol_1 / max(s.last_ask_vol_1, 1)
        if ratio > 2.0 and s.large_order_active_ratio > 60:
            return '🟢 买盘万手托单 + 主动买入强，承接极强'
        if ratio > 1.5:
            return '🟢 买盘较强，承接良好'
        if ratio < 0.5 and s.large_order_active_ratio < 40:
            return '🔴 卖盘压制 + 主动卖出，承接弱'
        if ratio < 0.7:
            return '🟡 卖盘略强，承接一般'
    return '⚪ 盘口中性'


# ============================================================
# 调度入口：每 3 秒调一次
# ============================================================
def collect_realtime_snapshot():
    """
    盘中 3 秒轮询:
    1. 拉取 watchlist + 自选股 + 重点关注 + 20天跟踪股的 ts_code 列表
    2. 批量调 iTick / mootdx 拉 tick + 盘口
    3. 写入 REALTIME_STATE 内存 dict(供 API 读)
    4. 同步落库 stock_realtime_tick(供历史回溯)
    """
    from db.session import get_db_session
    from db.models import (
        StockRealtimeTick, StockRealtimeOrderbook, Watchlist,
        YuziLifecycleTracker, YuziQuantSignal,
    )
    from sqlalchemy import distinct

    # 1) 拉取全市场股票列表 + 重点池
    codes = set()
    priority_codes = set()
    try:
        with get_db_session() as db:
            # 全市场：以今日 StockFlow 为准（约 5500 只）
            today_str = datetime.now().strftime('%Y%m%d')
            from db.models import StockFlow
            for r in db.query(distinct(StockFlow.ts_code)).filter(StockFlow.trade_date == today_str).all():
                codes.add(r[0])

            # 重点池：自选股 / 20天跟踪 / 今日共振高分股
            # 自选股
            for r in db.query(distinct(Watchlist.stock_code)).all():
                code = _normalize_code(r[0])
                if code:
                    priority_codes.add(code)
                    codes.add(code)
            # 20天跟踪 active(30 天窗口, 覆盖 20 个交易日)
            for r in db.query(distinct(YuziLifecycleTracker.ts_code)).filter(
                YuziLifecycleTracker.trigger_date >= (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')
            ).all():
                if r[0]:
                    priority_codes.add(r[0])
                    codes.add(r[0])
            # 今日共振高分股
            for r in db.query(distinct(YuziQuantSignal.ts_code)).filter(
                YuziQuantSignal.quant_score >= 70
            ).all():
                if r[0]:
                    priority_codes.add(r[0])
                    codes.add(r[0])
    except Exception as e:
        logger.warning(f'[realtime_aggregator] load watchlist failed: {e}')
        return

    if not codes:
        return

    codes = list(codes)
    priority_codes = list(priority_codes)
    logger.info(f'[realtime_aggregator] collecting {len(codes)} stocks ({len(priority_codes)} priority)')

    # 2) 批量拉取(已有 realtime_collector 封装,直接复用)
    try:
        quotes = _collect_realtime_intraday(codes, priority_codes=priority_codes)
    except Exception as e:
        logger.error(f'[realtime_aggregator] quote fetch failed: {e}', exc_info=True)
        return

    # 3) 更新内存 + 写库
    now = datetime.now()
    today = now.date()
    tick_rows = []
    for code, q in quotes.items():
        tick = {
            'price': q.get('price', 0),
            'last_close': q.get('last_close', 0),
            'pct_chg': q.get('pct_chg', 0),
            'volume': q.get('volume', 0),
            'amount': q.get('amount', 0),
            'bid_price_1': q.get('bid_price_1', 0) or q.get('bid1', 0),
            'bid_vol_1': q.get('bid_vol_1', 0) or q.get('bid_vol1', 0),
            'ask_price_1': q.get('ask_price_1', 0) or q.get('ask1', 0),
            'ask_vol_1': q.get('ask_vol_1', 0) or q.get('ask_vol1', 0),
            'turnover_rate': q.get('turnover_rate', 0),
            'main_force_inflow': q.get('main_force_inflow', 0),
            'snapshot_time': now,
            'source': q.get('source', 'tencent'),
        }
        state = get_or_create_state(code)
        state.add_tick(tick)

        # 估算大单方向(用盘口推断)
        if tick['bid_vol_1'] and tick['bid_vol_1'] > tick['ask_vol_1'] * 1.5 and tick['price'] >= tick['bid_price_1']:
            state.record_large_order('buy', tick['bid_vol_1'])
        elif tick['ask_vol_1'] and tick['ask_vol_1'] > tick['bid_vol_1'] * 1.5:
            state.record_large_order('sell', tick['ask_vol_1'])

        # 准备落库（复用 tick dict，扩展 DB 专属字段）
        tick_rows.append({**tick, 'ts_code': code, 'trade_date': today})

    # 4) 批量写库(每 3 秒一次,数据量大;超过 500 条用 bulk_insert_mappings)
    if tick_rows:
        try:
            from db.connection import engine
            from sqlalchemy import text
            # 参数化批量 INSERT，避免 SQL 注入
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
            logger.warning(f'[realtime_aggregator] tick write failed: {e}')


def _normalize_code(code: str) -> str:
    """6 位代码 → ts_code 格式"""
    if not code:
        return ''
    code = str(code).strip()
    if '.' in code:
        return code
    if code.startswith('6') or code.startswith('9'):
        return f'{code}.SH'
    if code.startswith('8') or code.startswith('4'):
        return f'{code}.BJ'
    return f'{code}.SZ'


def _collect_realtime_intraday(ts_codes: list, priority_codes: Optional[list] = None,
                               tencent_batch_size: int = 400) -> dict:
    """
    批量拉取 ts_codes 列表的实时行情 + 五档
    返回: {ts_code: {
        price, change_pct, last_close, volume, amount, turnover_rate,
        bid1..bid5, ask1..ask5, bid_vol1..bid_vol5, ask_vol1..ask_vol5,
        main_force_inflow, source
    }}
    多源降级: 腾讯批量(主, 分 400 只一批) → 东方财富 push2(单股,慢但含五档,仅重点池)
    """
    out = {}
    if not ts_codes:
        return out
    priority_set = set(priority_codes or [])

    # 1) 腾讯批量拉价格 + 涨跌幅 + 昨收(快,无封IP)
    try:
        from collectors.astock_collector import tencent_quote
        codes = [tc.split('.')[0] for tc in ts_codes]
        for i in range(0, len(codes), tencent_batch_size):
            batch_codes = codes[i:i + tencent_batch_size]
            batch_tcs = ts_codes[i:i + tencent_batch_size]
            try:
                batch = tencent_quote(batch_codes)
            except Exception as e:
                logger.warning(f'[realtime_aggregator] tencent batch {i}-{i+len(batch_codes)} failed: {e}')
                continue
            for tc, raw in zip(batch_tcs, [batch.get(c) for c in batch_codes]):
                if not raw:
                    continue
                out[tc] = {
                    'price': raw.get('price', 0),
                    'pct_chg': raw.get('change_pct', 0),
                    'last_close': raw.get('last_close', 0),
                    'volume': int(raw.get('amount_wan', 0) / max(raw.get('price', 1), 0.01) * 100) if raw.get('price') else 0,
                    'amount': float(raw.get('amount_wan', 0)) * 10000,  # 万 → 元
                    'turnover_rate': raw.get('turnover_pct', 0),
                    'source': 'tencent',
                }
    except Exception as e:
        logger.warning(f'[realtime_aggregator] tencent batch failed: {e}')

    # 2) 东方财富 push2 拉五档 + 分钟资金流向(慢,仅对重点池,避免全市场 5500*2 次请求)
    for tc in priority_set:
        if tc not in out:
            continue
        try:
            from collectors.astock_collector import eastmoney_fund_flow_minute
            code = tc.split('.')[0]
            flows = eastmoney_fund_flow_minute(code)
            if flows:
                last = flows[-1] if isinstance(flows, list) else flows
                # 推大单净流入(万元 → 元)
                main = float(last.get('super_net', 0) or 0) + float(last.get('large_net', 0) or 0)
                out[tc]['main_force_inflow'] = main * 10000
        except Exception:
            pass
        # 5 档(快速从 sina 拉,单只级别)
        try:
            from collectors.astock_collector import _sina_orderbook
            code = tc.split('.')[0]
            ob = _sina_orderbook(code)
            if ob:
                out[tc].update(ob)
        except Exception:
            pass
    return out


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
