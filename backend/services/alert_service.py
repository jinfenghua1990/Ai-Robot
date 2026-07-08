"""数据采集告警服务

为实时采集任务提供统一告警入口：
- 记录采集失败、断层、数据量异常等告警到 data_collection_alert 表
- 提供查询最近告警的 API 方法
- 提供实时数据断层检测方法
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date, timedelta
from typing import Optional, Dict, Any, List
from sqlalchemy import func
from db.session import get_db_session
from db.models import DataCollectionAlert, RealtimeStockFlow


_GapThreshold = {
    'trading': 600,    # 交易时段：最新快照与当前时间差超过 10 分钟视为断层
    'after_hours': 3600 * 4,  # 收盘后 4 小时内不告警
}


def record_alert(level: str, category: str, message: str,
                 trade_date: Optional[date] = None,
                 details: Optional[Dict[str, Any]] = None) -> None:
    """记录一条采集告警到数据库。"""
    if trade_date is None:
        trade_date = date.today()
    try:
        with get_db_session() as db:
            alert = DataCollectionAlert(
                level=level,
                category=category,
                message=message,
                details=json.dumps(details, ensure_ascii=False, default=str) if details else None,
                trade_date=trade_date,
            )
            db.add(alert)
            db.commit()
    except Exception as e:
        print(f'[alert_service] failed to record alert: {e}')


def get_recent_alerts(level: Optional[str] = None,
                      category: Optional[str] = None,
                      hours: int = 24,
                      limit: int = 50) -> List[Dict[str, Any]]:
    """查询最近告警。"""
    since = datetime.now() - timedelta(hours=hours)
    with get_db_session() as db:
        q = db.query(DataCollectionAlert).filter(DataCollectionAlert.created_at >= since)
        if level:
            q = q.filter(DataCollectionAlert.level == level)
        if category:
            q = q.filter(DataCollectionAlert.category == category)
        rows = q.order_by(DataCollectionAlert.created_at.desc()).limit(limit).all()
        return [
            {
                'id': r.id,
                'level': r.level,
                'category': r.category,
                'message': r.message,
                'details': json.loads(r.details) if r.details else None,
                'trade_date': r.trade_date.isoformat() if r.trade_date else None,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


def check_realtime_data_gap(trade_date: Optional[date] = None,
                            min_expected_stocks: int = 4000) -> Optional[Dict[str, Any]]:
    """检查实时数据是否断层。

    返回告警详情 dict 或 None。
    """
    if trade_date is None:
        trade_date = date.today()

    with get_db_session() as db:
        latest_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
            RealtimeStockFlow.trade_date == trade_date
        ).scalar()
        row_count = db.query(func.count('*')).filter(
            RealtimeStockFlow.trade_date == trade_date
        ).scalar()

    if latest_time is None:
        result = {
            'level': 'error',
            'category': 'collection_gap',
            'message': f'[{trade_date}] 今日无任何实时个股快照数据，实时采集完全中断',
            'details': {'row_count': 0, 'latest_time': None},
        }
        record_alert(**result, trade_date=trade_date)
        return result

    now = datetime.now()
    gap_seconds = int((now - latest_time).total_seconds())

    # 简单交易时段判定（9:30-11:30, 13:00-15:00）
    weekday = now.weekday()
    in_trading_hours = False
    if weekday < 5:
        hm = now.hour * 100 + now.minute
        if (930 <= hm <= 1130) or (1300 <= hm <= 1500):
            in_trading_hours = True

    alerts = []
    if in_trading_hours and gap_seconds > _GapThreshold['trading']:
        alerts.append({
            'level': 'error',
            'category': 'collection_gap',
            'message': f'[{trade_date}] 实时数据断层：最新快照 {latest_time}，距今 {gap_seconds // 60} 分钟',
            'details': {'latest_time': latest_time.isoformat(), 'gap_seconds': gap_seconds},
        })

    # 检查数据量（按最新时间点应该覆盖全市场，而不是总行数）
    with get_db_session() as db:
        latest_snapshot_count = db.query(func.count('*')).filter(
            RealtimeStockFlow.trade_date == trade_date,
            RealtimeStockFlow.snapshot_time == latest_time
        ).scalar()

    if latest_snapshot_count < min_expected_stocks:
        alerts.append({
            'level': 'warning',
            'category': 'quantity_anomaly',
            'message': f'[{trade_date}] 最新快照 {latest_time} 仅覆盖 {latest_snapshot_count} 只股票，低于预期 {min_expected_stocks}',
            'details': {
                'latest_time': latest_time.isoformat(),
                'latest_snapshot_count': latest_snapshot_count,
                'min_expected_stocks': min_expected_stocks,
            },
        })

    for a in alerts:
        record_alert(**a, trade_date=trade_date)
    return alerts[0] if alerts else None


def check_collection_result(trade_date: Optional[date] = None,
                            saved_count: int = 0,
                            expected_count: int = 5000,
                            duration_seconds: Optional[float] = None) -> None:
    """在单次采集完成后检查数据量/耗时异常。"""
    if trade_date is None:
        trade_date = date.today()
    details: Dict[str, Any] = {'saved_count': saved_count, 'expected_count': expected_count}
    if duration_seconds is not None:
        details['duration_seconds'] = round(duration_seconds, 2)

    if saved_count == 0:
        record_alert(
            level='critical',
            category='source_failure',
            message=f'[{trade_date}] 实时个股采集保存 0 条，主数据源可能完全失败',
            details=details,
            trade_date=trade_date,
        )
    elif saved_count < expected_count * 0.5:
        record_alert(
            level='error',
            category='quantity_anomaly',
            message=f'[{trade_date}] 实时个股采集仅保存 {saved_count} 条，约为预期的 {saved_count / expected_count:.0%}',
            details=details,
            trade_date=trade_date,
        )
    elif saved_count < expected_count * 0.8:
        record_alert(
            level='warning',
            category='quantity_anomaly',
            message=f'[{trade_date}] 实时个股采集保存 {saved_count} 条，约为预期的 {saved_count / expected_count:.0%}',
            details=details,
            trade_date=trade_date,
        )

    if duration_seconds and duration_seconds > 300:
        record_alert(
            level='warning',
            category='source_failure',
            message=f'[{trade_date}] 单次实时个股采集耗时 {duration_seconds:.0f} 秒，超过 5 分钟',
            details=details,
            trade_date=trade_date,
        )
