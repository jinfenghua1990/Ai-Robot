"""
定时采集调度器
盘中实时采集 + 盘后分析 + 数据维护
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from collectors.tdx_collector import collect_daily_data
from analyzers.heat_score import calculate_heat_scores
from analyzers.lifecycle import update_lifecycle
from analyzers.rotation import calculate_rotation
from analyzers.money_flow import calculate_money_flow_path
from datetime import datetime, timedelta

scheduler = AsyncIOScheduler()

def start_scheduler():
    """启动定时采集调度器"""
    # 盘中采集（9:30-15:00 每30分钟）
    scheduler.add_job(scheduled_collect, 'cron', hour='9-14', minute='0,30')
    # 收盘全量采集
    scheduler.add_job(scheduled_collect, 'cron', hour='15', minute='0')
    # 盘后分析
    scheduler.add_job(scheduled_analyze, 'cron', hour='15', minute='30')
    # 数据维护（每日凌晨清理30天前数据）
    scheduler.add_job(cleanup_old_data, 'cron', hour='6', minute='0')
    scheduler.start()
    print('[scheduler] Started')


def scheduled_collect():
    """定时采集任务"""
    today = datetime.now().strftime('%Y-%m-%d')
    print(f'[scheduler] Collecting data for {today}')
    try:
        collect_daily_data(today)
    except Exception as e:
        print(f'[scheduler] Collect error: {e}')


def scheduled_analyze():
    """盘后分析任务"""
    today = datetime.now().strftime('%Y-%m-%d')
    print(f'[scheduler] Analyzing for {today}')
    try:
        calculate_heat_scores(today)
        update_lifecycle(today)
        calculate_rotation(today)
        calculate_money_flow_path(today)
    except Exception as e:
        print(f'[scheduler] Analyze error: {e}')


def cleanup_old_data():
    """清理30天前的数据"""
    from db.connection import get_db
    from db.models import SectorFlow, StockFlow, LeaderLifecycle
    cutoff = (datetime.now() - timedelta(days=30)).date()
    db = next(get_db())
    try:
        db.query(SectorFlow).filter(SectorFlow.trade_date < cutoff).delete()
        db.query(StockFlow).filter(StockFlow.trade_date < cutoff).delete()
        db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date < cutoff).delete()
        db.commit()
        print(f'[scheduler] Cleaned data before {cutoff}')
    except Exception as e:
        db.rollback()
        print(f'[scheduler] Cleanup error: {e}')
    finally:
        db.close()
