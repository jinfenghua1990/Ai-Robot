"""
数据质量 API
- /api/quality/overview        质量总览（各置信度分布、平均分）
- /api/quality/logs            质量日志查询
- /api/quality/review-queue    人工审核队列
- /api/quality/review/{id}     处理审核
- /api/quality/sources         数据源可靠性统计
- /api/quality/anomalies       异常数据列表
"""
from fastapi import APIRouter, Query, Body
from sqlalchemy import func, desc, and_
from datetime import datetime, date, timedelta
from db.connection import get_db
from db.session import get_db_session
from db.models import (
    DataQualityLog, ManualReviewQueue, DataSourceReliability,
    RealtimeStockFlow, RealtimeSectorFlow,
    SectorFlow, StockFlow, LeaderLifecycle, BSStrategy
)
import json

router = APIRouter(prefix="/api/quality", tags=["quality"])


@router.get("/overview")
def quality_overview(trade_date: str = Query(None)):
    """质量总览"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        # 个股数据置信度分布
        latest_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter(
            RealtimeStockFlow.trade_date == target_date
        ).scalar()

        confidence_dist = {'high': 0, 'medium': 0, 'low': 0, 'disputed': 0}
        avg_score = 0
        total_stocks = 0
        multi_source_count = 0

        if latest_time:
            stocks = db.query(RealtimeStockFlow).filter_by(
                trade_date=target_date, snapshot_time=latest_time
            ).all()
            total_stocks = len(stocks)
            for s in stocks:
                conf = s.confidence or 'low'
                confidence_dist[conf] = confidence_dist.get(conf, 0) + 1
                if s.sources_count and s.sources_count > 1:
                    multi_source_count += 1

            # 平均质量评分（从质量日志表）
            avg_score_row = db.query(func.avg(DataQualityLog.quality_score)).filter(
                DataQualityLog.trade_date == target_date
            ).scalar()
            avg_score = float(avg_score_row) if avg_score_row else 0

        # 今日质量日志统计
        log_stats = db.query(
            DataQualityLog.action,
            func.count('*').label('cnt')
        ).filter(DataQualityLog.trade_date == target_date).group_by(DataQualityLog.action).all()
        action_stats = {row.action: row.cnt for row in log_stats}

        # 待审核数量
        pending_review = db.query(ManualReviewQueue).filter_by(status='pending').count()

        return {
            "trade_date": target_date.isoformat(),
            "latest_snapshot": latest_time.strftime('%Y-%m-%d %H:%M:%S') if latest_time else None,
            "total_stocks": total_stocks,
            "multi_source_validated": multi_source_count,
            "confidence_distribution": confidence_dist,
            "avg_quality_score": round(avg_score, 2),
            "action_stats": action_stats,
            "pending_reviews": pending_review,
        }


@router.get("/logs")
def quality_logs(
    trade_date: str = Query(None),
    indicator: str = Query(None),
    action: str = Query(None),
    limit: int = Query(50, le=200),
):
    """质量日志查询"""
    with get_db_session() as db:
        q = db.query(DataQualityLog)
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
            q = q.filter(DataQualityLog.trade_date == target_date)
        else:
            # 默认今天
            q = q.filter(DataQualityLog.trade_date == date.today())
        if indicator:
            q = q.filter(DataQualityLog.indicator == indicator)
        if action:
            q = q.filter(DataQualityLog.action == action)
        # 只看异常和审核的
        q = q.filter(DataQualityLog.action.in_(['correct', 'review', 'reject']))
        logs = q.order_by(desc(DataQualityLog.created_at)).limit(limit).all()
        return {
            "count": len(logs),
            "logs": [{
                "id": l.id,
                "snapshot_time": l.snapshot_time.strftime('%H:%M:%S') if l.snapshot_time else None,
                "ts_code": l.ts_code,
                "name": l.name,
                "indicator": l.indicator,
                "sources_data": json.loads(l.sources_data) if l.sources_data else {},
                "authority_value": float(l.authority_value) if l.authority_value else None,
                "outliers": l.outliers,
                "quality_score": float(l.quality_score) if l.quality_score else 0,
                "action": l.action,
            } for l in logs],
        }


@router.get("/review-queue")
def review_queue(status: str = Query('pending')):
    """人工审核队列"""
    with get_db_session() as db:
        items = db.query(ManualReviewQueue).filter_by(status=status).order_by(
            desc(ManualReviewQueue.created_at)
        ).limit(100).all()
        return {
            "count": len(items),
            "status_filter": status,
            "items": [{
                "id": r.id,
                "created_at": r.created_at.strftime('%Y-%m-%d %H:%M:%S') if r.created_at else None,
                "ts_code": r.ts_code,
                "name": r.name,
                "indicator": r.indicator,
                "reason": r.reason,
                "sources_data": json.loads(r.sources_data) if r.sources_data else {},
                "status": r.status,
                "final_value": float(r.final_value) if r.final_value else None,
            } for r in items],
        }


@router.post("/review/{review_id}")
def handle_review(review_id: int, action: str = Body(..., embed=True), final_value: float = Body(None, embed=True), reviewer: str = Body('admin', embed=True)):
    """处理审核：approve / reject"""
    try:
        with get_db_session() as db:
            item = db.query(ManualReviewQueue).filter_by(id=review_id).first()
            if not item:
                return {"error": "Review not found"}, 404
            item.status = 'approved' if action == 'approve' else 'rejected'
            item.reviewed_by = reviewer
            item.reviewed_at = datetime.now()
            if final_value is not None:
                item.final_value = final_value
            db.commit()
            return {"status": "ok", "review_id": review_id, "action": item.status}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


@router.get("/sources")
def source_reliability(days: int = Query(7, le=30)):
    """数据源可靠性统计"""
    with get_db_session() as db:
        cutoff = date.today() - timedelta(days=days)
        records = db.query(DataSourceReliability).filter(
            DataSourceReliability.date >= cutoff
        ).order_by(desc(DataSourceReliability.date)).all()

        # 按数据源聚合
        source_summary = {}
        for r in records:
            if r.source not in source_summary:
                source_summary[r.source] = {
                    'source': r.source,
                    'total_count': 0,
                    'outlier_count': 0,
                    'deviations': [],
                    'scores': [],
                    'daily': [],
                }
            s = source_summary[r.source]
            s['total_count'] += r.total_count or 0
            s['outlier_count'] += r.outlier_count or 0
            if r.avg_deviation is not None:
                s['deviations'].append(float(r.avg_deviation))
            if r.reliability_score is not None:
                s['scores'].append(float(r.reliability_score))
            s['daily'].append({
                'date': r.date.isoformat(),
                'total': r.total_count,
                'outliers': r.outlier_count,
                'avg_deviation': float(r.avg_deviation or 0),
                'score': float(r.reliability_score or 0),
            })

        # 计算汇总
        result = []
        for src, data in source_summary.items():
            outlier_rate = data['outlier_count'] / data['total_count'] * 100 if data['total_count'] else 0
            result.append({
                'source': src,
                'total_count': data['total_count'],
                'outlier_count': data['outlier_count'],
                'outlier_rate': round(outlier_rate, 2),
                'avg_deviation': round(sum(data['deviations']) / len(data['deviations']), 2) if data['deviations'] else 0,
                'avg_score': round(sum(data['scores']) / len(data['scores']), 2) if data['scores'] else 0,
                'daily': data['daily'],
            })

        # 附加权重信息（来自交叉验证引擎的 DEFAULT_WEIGHTS）
        try:
            from analyzers.cross_validator import DEFAULT_WEIGHTS
            for item in result:
                item['weight'] = DEFAULT_WEIGHTS.get(item['source'], 0.05)
        except Exception:
            for item in result:
                item['weight'] = 0.05

        result.sort(key=lambda x: x['avg_score'], reverse=True)
        return {"days": days, "sources": result}


@router.get("/data-sources")
def data_sources_config():
    """获取所有数据源配置（来自数据源注册器，含待集成的）"""
    from collectors.data_source_registry import get_source_info
    info = get_source_info()
    return info


@router.get("/error-stats")
def error_stats():
    """获取各数据源出错率统计"""
    try:
        from collectors.extended_collectors import get_error_stats
        return get_error_stats()
    except Exception:
        logger.debug(f"error_stats failed", exc_info=True)
        return {}


@router.post("/auto-review")
def trigger_auto_review():
    """手动触发自动审核（处理pending状态的审核记录）"""
    import sys, os, statistics, json
    from datetime import datetime
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from db.models import ManualReviewQueue

    try:
        with get_db_session() as db:
            reviews = db.query(ManualReviewQueue).filter_by(status='pending').all()
            auto_passed = 0
            kept_manual = 0
            for r in reviews:
                raw = json.loads(r.sources_data) if r.sources_data else {}
                values = {}
                for k, v in raw.items():
                    val = v.get('value') if isinstance(v, dict) else v
                    if val is not None:
                        values[k] = float(val)
                vals = list(values.values())
                if not vals:
                    kept_manual += 1
                    continue
                median = statistics.median(vals)
                mean = statistics.mean(vals)
                std = statistics.stdev(vals) if len(vals) > 1 else 0
                cv = (std / abs(mean) * 100) if mean else 0
                if cv <= 5.0:
                    r.status = 'approved'
                    r.final_value = statistics.mean(vals)
                    r.reviewed_by = 'auto_review'
                    r.reviewed_at = datetime.now()
                    r.reason = f'[自动审核·高置信度] CV={cv:.1f}%≤5%，取平均值'
                    auto_passed += 1
                elif cv <= 15.0:
                    r.status = 'approved'
                    r.final_value = median
                    r.reviewed_by = 'auto_review'
                    r.reviewed_at = datetime.now()
                    r.reason = f'[自动审核·中置信度] CV={cv:.1f}%≤15%，取中位数'
                    auto_passed += 1
                else:
                    kept_manual += 1
            db.commit()
            return {"auto_passed": auto_passed, "kept_manual": kept_manual, "total": len(reviews)}
    except Exception as e:
        db.rollback()
        return {"error": str(e)}


@router.get("/anomalies")
def anomaly_list(trade_date: str = Query(None), limit: int = Query(50, le=200)):
    """异常数据列表（低置信度/被修正/有异常源）"""
    with get_db_session() as db:
        if trade_date:
            target_date = datetime.strptime(trade_date, '%Y-%m-%d').date()
        else:
            target_date = date.today()

        q = db.query(RealtimeStockFlow).filter(
            RealtimeStockFlow.trade_date == target_date,
            and_(
                RealtimeStockFlow.confidence.in_(['low', 'disputed']),
            )
        )
        anomalies = q.order_by(desc(RealtimeStockFlow.deviation_pct)).limit(limit).all()
        return {
            "trade_date": target_date.isoformat(),
            "count": len(anomalies),
            "anomalies": [{
                "ts_code": a.ts_code,
                "name": a.name,
                "sector": a.sector,
                "main_force_inflow": float(a.main_force_inflow or 0),
                "price": float(a.price or 0),
                "confidence": a.confidence,
                "sources_count": a.sources_count,
                "sources_used": a.sources_used,
                "deviation_pct": float(a.deviation_pct or 0),
                "is_corrected": a.is_corrected,
                "correction_note": a.correction_note,
                "snapshot_time": a.snapshot_time.strftime('%H:%M') if a.snapshot_time else None,
            } for a in anomalies],
        }


from utils import is_trading_day as _is_trading_day
import logging
logger = logging.getLogger(__name__)


def _last_trading_day(d: date) -> date:
    """获取最近的交易日（不含今天）"""
    prev = d - timedelta(days=1)
    while prev.weekday() >= 5:
        prev -= timedelta(days=1)
    return prev


def _trading_day_diff(today: date, data_date: date) -> int:
    """计算交易日差（跳过周末）"""
    if data_date >= today:
        return 0
    diff = 0
    cur = data_date
    while cur < today:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            diff += 1
    return diff


@router.get("/data-freshness")
def data_freshness():
    """数据更新状态监控：检测各数据源是否为最新状态
    返回每个数据表的最新更新日期、是否滞后、滞后天数、状态
    """
    with get_db_session() as db:
        today = date.today()
        now = datetime.now()
        is_trading_day = _is_trading_day(today)
        last_trade_day = _last_trading_day(today)
        # 盘中时间判断（9:30-11:30, 13:00-15:00）
        hm = now.hour * 100 + now.minute
        is_trading_hours = is_trading_day and (
            (930 <= hm <= 1130) or (1300 <= hm <= 1500)
        )

        sources = []

        # === 盘后数据源 ===
        # 1. 板块资金流向
        sector_latest = db.query(func.max(SectorFlow.trade_date)).scalar()
        sector_status = _check_freshness(sector_latest, today, is_trading_day, last_trade_day, "盘后")
        sources.append({
            "name": "板块资金流向",
            "table": "sector_flow",
            "category": "盘后",
            "latest_date": sector_latest.isoformat() if sector_latest else None,
            "latest_time": None,
            **sector_status,
        })

        # 2. 个股资金流向
        stock_latest = db.query(func.max(StockFlow.trade_date)).scalar()
        stock_status = _check_freshness(stock_latest, today, is_trading_day, last_trade_day, "盘后")
        sources.append({
            "name": "个股资金流向",
            "table": "stock_flow",
            "category": "盘后",
            "latest_date": stock_latest.isoformat() if stock_latest else None,
            "latest_time": None,
            **stock_status,
        })

        # 3. 龙头生命周期
        leader_latest = db.query(func.max(LeaderLifecycle.trade_date)).scalar()
        leader_status = _check_freshness(leader_latest, today, is_trading_day, last_trade_day, "盘后")
        sources.append({
            "name": "龙头生命周期",
            "table": "leader_lifecycle",
            "category": "盘后",
            "latest_date": leader_latest.isoformat() if leader_latest else None,
            "latest_time": None,
            **leader_status,
        })

        # === 实时数据源 ===
        # 4. 实时板块资金流向
        rt_sector_row = db.query(RealtimeSectorFlow).order_by(
            desc(RealtimeSectorFlow.trade_date), desc(RealtimeSectorFlow.snapshot_time)
        ).first()
        rt_sector_date = rt_sector_row.trade_date if rt_sector_row else None
        rt_sector_time = rt_sector_row.snapshot_time if rt_sector_row else None
        rt_sector_status = _check_realtime_freshness(
            rt_sector_date, rt_sector_time, today, now, is_trading_hours
        )
        sources.append({
            "name": "实时板块资金",
            "table": "realtime_sector_flow",
            "category": "实时",
            "latest_date": rt_sector_date.isoformat() if rt_sector_date else None,
            "latest_time": rt_sector_time.strftime('%H:%M:%S') if rt_sector_time else None,
            **rt_sector_status,
        })

        # 5. 实时个股资金流向
        rt_stock_row = db.query(RealtimeStockFlow).order_by(
            desc(RealtimeStockFlow.trade_date), desc(RealtimeStockFlow.snapshot_time)
        ).first()
        rt_stock_date = rt_stock_row.trade_date if rt_stock_row else None
        rt_stock_time = rt_stock_row.snapshot_time if rt_stock_row else None
        rt_stock_status = _check_realtime_freshness(
            rt_stock_date, rt_stock_time, today, now, is_trading_hours
        )
        sources.append({
            "name": "实时个股资金",
            "table": "realtime_stock_flow",
            "category": "实时",
            "latest_date": rt_stock_date.isoformat() if rt_stock_date else None,
            "latest_time": rt_stock_time.strftime('%H:%M:%S') if rt_stock_time else None,
            **rt_stock_status,
        })

        # 6. 数据质量日志
        dq_latest = db.query(func.max(DataQualityLog.trade_date)).scalar()
        dq_status = _check_freshness(dq_latest, today, is_trading_day, last_trade_day, "盘后")
        sources.append({
            "name": "数据质量日志",
            "table": "data_quality_log",
            "category": "盘后",
            "latest_date": dq_latest.isoformat() if dq_latest else None,
            "latest_time": None,
            **dq_status,
        })

        # 7. BS策略配置
        bs_latest = db.query(func.max(BSStrategy.created_at)).scalar()
        bs_status = _check_runtime_freshness(bs_latest, now, hours=24)
        sources.append({
            "name": "BS策略配置",
            "table": "bs_strategies",
            "category": "运行时",
            "latest_date": bs_latest.strftime('%Y-%m-%d') if bs_latest else None,
            "latest_time": bs_latest.strftime('%H:%M:%S') if bs_latest else None,
            **bs_status,
        })

        # 汇总统计
        stale_count = sum(1 for s in sources if s["status"] == "stale")
        fresh_count = sum(1 for s in sources if s["status"] == "fresh")
        error_count = sum(1 for s in sources if s["status"] == "error")
        max_delay = max((s.get("delay_days", 0) for s in sources), default=0)

        return {
            "check_time": now.strftime('%Y-%m-%d %H:%M:%S'),
            "today": today.isoformat(),
            "is_trading_day": is_trading_day,
            "is_trading_hours": is_trading_hours,
            "last_trade_day": last_trade_day.isoformat(),
            "summary": {
                "total": len(sources),
                "fresh": fresh_count,
                "stale": stale_count,
                "error": error_count,
                "max_delay_days": max_delay,
                "overall_status": "error" if error_count > 0 else "stale" if stale_count > 0 else "fresh",
            },
            "sources": sources,
        }


def _check_freshness(data_date, today, is_trading_day, last_trade_day, category):
    """检查盘后数据新鲜度"""
    if data_date is None:
        return {"status": "error", "delay_days": 99, "message": "无数据", "expected_date": None}

    expected = today if is_trading_day and datetime.now().hour >= 16 else last_trade_day
    delay = _trading_day_diff(today, data_date)

    if data_date >= expected:
        return {"status": "fresh", "delay_days": 0, "message": "最新", "expected_date": expected.isoformat()}
    elif delay <= 1:
        return {"status": "stale", "delay_days": delay, "message": f"滞后{delay}个交易日", "expected_date": expected.isoformat()}
    else:
        return {"status": "stale", "delay_days": delay, "message": f"严重滞后{delay}个交易日", "expected_date": expected.isoformat()}


def _check_realtime_freshness(data_date, snapshot_time, today, now, is_trading_hours):
    """检查实时数据新鲜度"""
    if data_date is None:
        return {"status": "error", "delay_days": 99, "message": "无数据", "expected_date": None}

    delay = _trading_day_diff(today, data_date)
    if delay > 0:
        return {"status": "stale", "delay_days": delay, "message": f"数据日期滞后{delay}天", "expected_date": today.isoformat()}

    # 盘中检查快照时间
    if is_trading_hours and snapshot_time:
        minutes_ago = (now.hour * 60 + now.minute) - (snapshot_time.hour * 60 + snapshot_time.minute)
        if minutes_ago > 10:
            return {"status": "stale", "delay_days": 0, "message": f"盘中快照已{minutes_ago}分钟未更新", "expected_date": today.isoformat()}
        return {"status": "fresh", "delay_days": 0, "message": "盘中实时", "expected_date": today.isoformat()}

    return {"status": "fresh", "delay_days": 0, "message": "最新", "expected_date": today.isoformat()}


def _check_runtime_freshness(updated_at, now, hours=24):
    """检查运行时数据新鲜度"""
    if updated_at is None:
        return {"status": "error", "delay_days": 99, "message": "无数据", "expected_date": None}
    diff = now - updated_at
    if diff.total_seconds() < hours * 3600:
        return {"status": "fresh", "delay_days": 0, "message": "最新", "expected_date": None}
    else:
        days = int(diff.total_seconds() / 86400)
        return {"status": "stale", "delay_days": days, "message": f"{days}天未更新", "expected_date": None}
