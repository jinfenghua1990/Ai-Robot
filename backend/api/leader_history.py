"""
龙头历史统计 API
GET /api/leader/history - 历史主龙记录列表
GET /api/leader/stats - 统计汇总（平均寿命/切换次数/活跃板块数）
"""
import logging
from fastapi import APIRouter, Query
from sqlalchemy import desc
from db.connection import get_db
from db.session import get_db_session
from db.models import LeaderHistory

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/api/leader/history")
def leader_history(limit: int = Query(100, description="返回条数限制")):
    """历史主龙记录列表

    返回按日期倒序的主龙记录
    """
    with get_db_session() as db:
        records = db.query(LeaderHistory).order_by(
            desc(LeaderHistory.trade_date), desc(LeaderHistory.leader_score)
        ).limit(limit).all()

        return [
            {
                'date': r.trade_date,
                'sector': r.sector,
                'leader_code': r.leader_code,
                'leader_name': r.leader_name,
                'leader_score': float(r.leader_score) if r.leader_score else 0,
                'sector_score': float(r.sector_score) if r.sector_score else 0,
                'stage': r.stage,
            }
            for r in records
        ]


@router.get("/api/leader/stats")
def leader_stats(days: int = Query(20, description="统计近N个交易日")):
    """龙头统计汇总

    返回：
    - avg_life_days: 龙头平均寿命（同一板块连续担任主龙的平均天数）
    - switch_count: 龙头切换次数
    - active_sectors: 近N个交易日出现过主龙的板块数
    - total_records: 总记录数
    - date_range: 日期范围
    - sector_breakdown: 各板块的龙头统计
    """
    with get_db_session() as db:
        # 获取全部历史记录（按日期+板块排序）
        all_records = db.query(LeaderHistory).order_by(
            LeaderHistory.trade_date, LeaderHistory.sector
        ).all()

        if not all_records:
            return {
                'avg_life_days': 0,
                'switch_count': 0,
                'active_sectors': 0,
                'total_records': 0,
                'date_range': None,
                'sector_breakdown': [],
            }

        # === 1. 计算龙头平均寿命 ===
        # 按板块分组，计算每个板块内龙头连续担任天数
        sector_groups = {}
        for r in all_records:
            if r.sector not in sector_groups:
                sector_groups[r.sector] = []
            sector_groups[r.sector].append(r)

        all_lifespans = []
        for sector, records in sector_groups.items():
            # 同一板块内，按日期排序
            records.sort(key=lambda x: x.trade_date)
            # 计算连续担任主龙的天数
            current_leader = None
            current_days = 0
            for r in records:
                if r.leader_code != current_leader:
                    if current_leader is not None and current_days > 0:
                        all_lifespans.append(current_days)
                    current_leader = r.leader_code
                    current_days = 1
                else:
                    current_days += 1
            # 最后一段
            if current_days > 0:
                all_lifespans.append(current_days)

        avg_life = sum(all_lifespans) / len(all_lifespans) if all_lifespans else 0

        # === 2. 龙头切换次数 ===
        switch_count = 0
        for sector, records in sector_groups.items():
            records.sort(key=lambda x: x.trade_date)
            prev_leader = None
            for r in records:
                if prev_leader is not None and r.leader_code != prev_leader:
                    switch_count += 1
                prev_leader = r.leader_code

        # === 3. 活跃板块数（近N个交易日） ===
        # 取最近N个交易日
        all_dates = sorted(set(r.trade_date for r in all_records), reverse=True)
        recent_dates = set(all_dates[:days])
        recent_sectors = set(
            r.sector for r in all_records if r.trade_date in recent_dates
        )

        # === 4. 板块维度统计 ===
        sector_breakdown = []
        for sector, records in sector_groups.items():
            leaders = list(set(r.leader_name for r in records if r.leader_name))
            sector_breakdown.append({
                'sector': sector,
                'record_count': len(records),
                'leader_count': len(leaders),
                'leaders': leaders[:5],  # 前5个龙头
                'avg_score': sum(float(r.leader_score or 0) for r in records) / len(records),
            })
        sector_breakdown.sort(key=lambda x: x['record_count'], reverse=True)

        return {
            'avg_life_days': round(avg_life, 1),
            'switch_count': switch_count,
            'active_sectors': len(recent_sectors),
            'total_records': len(all_records),
            'date_range': {
                'start': all_dates[-1] if all_dates else None,
                'end': all_dates[0] if all_dates else None,
            },
            'sector_breakdown': sector_breakdown[:10],
        }
