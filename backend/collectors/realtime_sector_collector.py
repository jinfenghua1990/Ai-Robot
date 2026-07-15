"""
实时板块资金流向采集器
数据源：新浪(主) → 东方财富(降级)
"""
import logging
from datetime import datetime
from db.session import get_db_session
from db.models import RealtimeSectorFlow
from collectors.tdx_collector import get_sector_money_flow

logger = logging.getLogger(__name__)


def _now_truncated():
    """当前时间截断到分钟（秒数归零）"""
    return datetime.now().replace(second=0, microsecond=0)


def collect_realtime_sector_flow(trade_date):
    """
    采集板块实时资金流向快照
    数据源：新浪(主) → 东方财富(降级)
    """
    snapshot_time = _now_truncated()
    print(f'[realtime] Collecting sector flow snapshot at {snapshot_time}')

    # 复用现有采集函数（新浪→东方财富→Tushare）
    sector_flows = get_sector_money_flow(trade_date)
    if not sector_flows:
        print('[realtime] No sector flow data')
        return 0

    # 判断数据源
    source = 'sina'  # get_sector_money_flow 优先用新浪
    # 简单判断：如果板块数<40 可能是东方财富或Tushare
    if len(sector_flows) < 40:
        source = 'em'

    with get_db_session() as db:
        saved = 0
        try:
            for sf in sector_flows:
                record = RealtimeSectorFlow(
                    snapshot_time=snapshot_time,
                    trade_date=trade_date,
                    sector=sf['sector'],
                    money_inflow=sf.get('money_inflow'),
                    money_outflow=sf.get('money_outflow'),
                    net_flow=sf.get('net_flow'),
                    rise_ratio=sf.get('rise_ratio'),
                    source=source,
                )
                db.add(record)
                saved += 1
            db.commit()
            logger.info(f'[realtime] Saved {saved} sector snapshots (source={source})')
        except Exception as e:
            db.rollback()
            logger.warning(f'[realtime] Sector save error: {e}')
    return saved
