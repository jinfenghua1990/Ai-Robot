"""
龙头历史写入服务
职责：每日主龙选出后，写入 leader_history 表
规则：同一天同一板块只允许一条记录，存在则更新
"""
import logging
from db.models import LeaderHistory

logger = logging.getLogger(__name__)


def save_daily_leader(db, trade_date, sector, leader):
    """保存每日主龙记录（同日同板块只保留一条，存在则更新）

    Args:
        db: 数据库会话
        trade_date: 交易日期字符串 YYYY-MM-DD
        sector: 板块名称
        leader: 主龙数据字典，需包含 ts_code, name, score, sector_score, stage
    """
    date_str = trade_date if isinstance(trade_date, str) else trade_date.isoformat()

    # 查询是否已存在同日同板块的记录
    existing = db.query(LeaderHistory).filter(
        LeaderHistory.trade_date == date_str,
        LeaderHistory.sector == sector,
    ).first()

    if existing:
        # 更新已有记录
        existing.leader_code = leader.get('ts_code', '')
        existing.leader_name = leader.get('name', '')
        existing.leader_score = leader.get('score', 0)
        existing.sector_score = leader.get('sector_score', 0)
        existing.stage = leader.get('stage', 'unknown')
        logger.debug(f'更新龙头历史: {date_str} {sector} {leader.get("name")}')
    else:
        # 新增记录
        record = LeaderHistory(
            trade_date=date_str,
            sector=sector,
            leader_code=leader.get('ts_code', ''),
            leader_name=leader.get('name', ''),
            leader_score=leader.get('score', 0),
            sector_score=leader.get('sector_score', 0),
            stage=leader.get('stage', 'unknown'),
        )
        db.add(record)
        logger.debug(f'新增龙头历史: {date_str} {sector} {leader.get("name")}')

    db.commit()
