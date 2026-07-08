"""
资金流向数据中转层（Money Flow Middleman）
- 盘中每分钟/每 5 分钟抓取外部概念/行业板块资金流
- 三道防错：网络容错 → 前向填充(FFill) → 累计平滑
- 写入 realtime_money_flow_snapshot 表，并维护内存缓存供 FastAPI 直接读取
"""
import sys, os
import logging
import threading
import requests
from datetime import date, datetime, time
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.connection import get_db
from db.session import get_db_session
from db.models import RealtimeMoneyFlowSnapshot
from sqlalchemy import func
from utils.http_constants import SINA_HEADERS

logger = logging.getLogger(__name__)

# =====================================================================
# 内存缓存
# 结构: {dimension: {block_name: {"09:30": 1.2, "09:31": 1.5, ...}}}
# =====================================================================
DATA_CACHE: Dict[str, Dict[str, Dict[str, float]]] = {"concept": {}, "industry": {}}
LAST_VALID_SNAPSHOT: Dict[str, Dict[str, float]] = {"concept": {}, "industry": {}}
_CACHE_LOCK = threading.RLock()

# SINA_HEADERS imported from utils.http_constants


def generate_market_time_slots() -> List[str]:
    """生成 A 股标准交易分钟时间点 (09:30-11:30, 13:00-15:00)"""
    slots = []
    for h in range(9, 12):
        for m in range(60):
            if (h == 9 and m >= 30) or h == 10 or (h == 11 and m <= 30):
                slots.append(f"{h:02d}:{m:02d}")
    for h in range(13, 15):
        for m in range(60):
            slots.append(f"{h:02d}:{m:02d}")
    slots.append("15:00")
    return slots


MARKET_TIMELINE = generate_market_time_slots()


def _is_market_open(minute: str) -> bool:
    return minute in MARKET_TIMELINE


def _now_truncated():
    return datetime.now().replace(second=0, microsecond=0)


def _should_ffill(name: str, val: Optional[float], last: float) -> bool:
    """判断是否需要前向填充：None，或非首分钟突变为 0"""
    if val is None:
        return True
    if val == 0.0 and last != 0.0:
        return True
    return False


def fetch_raw_data_from_sina_concept() -> List[dict]:
    """
    从新浪财经抓取概念板块实时资金流向。
    返回 [{block_name, net_amount}, ...]，net_amount 单位：元。
    """
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'
    items = []
    for page in range(1, 20):
        try:
            resp = requests.get(url, params={
                'page': page, 'num': 100, 'sort': 'netamount', 'asc': 0, 'fenlei': 1
            }, timeout=10, headers=SINA_HEADERS)
            data = resp.json()
            if not data:
                break
            for item in data:
                name = item.get('name', '').strip()
                net = item.get('netamount')
                if name and net is not None:
                    items.append({
                        'block_name': name,
                        'net_amount': float(net),
                    })
            if len(data) < 100:
                break
        except Exception as e:
            logger.error(f'[middleman] sina concept page {page} error: {e}')
            break
    return items


def fetch_raw_data_from_sina_industry() -> List[dict]:
    """
    从新浪财经抓取行业板块实时资金流向。
    fenlei=0 为行业板块。
    """
    url = 'http://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk'
    items = []
    for page in range(1, 20):
        try:
            resp = requests.get(url, params={
                'page': page, 'num': 100, 'sort': 'netamount', 'asc': 0, 'fenlei': 0
            }, timeout=10, headers=SINA_HEADERS)
            data = resp.json()
            if not data:
                break
            for item in data:
                name = item.get('name', '').strip()
                net = item.get('netamount')
                if name and net is not None:
                    items.append({
                        'block_name': name,
                        'net_amount': float(net),
                    })
            if len(data) < 100:
                break
        except Exception as e:
            logger.error(f'[middleman] sina industry page {page} error: {e}')
            break
    return items


def fetch_raw_data(dimension: str) -> List[dict]:
    """根据维度抓取原始数据"""
    if dimension == 'industry':
        return fetch_raw_data_from_sina_industry()
    return fetch_raw_data_from_sina_concept()


def _restore_cache_from_db(dimension: str):
    """启动时从数据库恢复当天缓存"""
    today = date.today()
    with get_db_session() as db:
        rows = db.query(RealtimeMoneyFlowSnapshot).filter_by(
            trade_date=today, dimension=dimension
        ).order_by(RealtimeMoneyFlowSnapshot.minute).all()
        with _CACHE_LOCK:
            for r in rows:
                if r.block_name not in DATA_CACHE[dimension]:
                    DATA_CACHE[dimension][r.block_name] = {}
                DATA_CACHE[dimension][r.block_name][r.minute] = float(r.net_inflow_yi)
                LAST_VALID_SNAPSHOT[dimension][r.block_name] = float(r.net_inflow_yi)
        if rows:
            logger.info(
                f'[middleman] [{dimension}] restored {len(rows)} snapshots from DB, '
                f'latest {max(r.minute for r in rows)}'
            )


def _bulk_upsert_snapshots(records: List[RealtimeMoneyFlowSnapshot]):
    """批量写入/更新数据库（预加载现有记录 → 内存 map，避免 N 次 SELECT）"""
    if not records:
        return
    try:
        with get_db_session() as db:
            # 1) 按 (trade_date, dimension) 一次性批量加载已有记录
            date_dim_pairs = {(r.trade_date, r.dimension) for r in records}
            all_existing = []
            for td, dim in date_dim_pairs:
                batch = db.query(RealtimeMoneyFlowSnapshot).filter_by(
                    trade_date=td, dimension=dim
                ).all()
                all_existing.extend(batch)
            exist_map = {
                (e.trade_date, e.dimension, e.block_name, e.minute): e
                for e in all_existing
            }

            # 2) 内存 map 查找，零 DB 查询
            for rec in records:
                key = (rec.trade_date, rec.dimension, rec.block_name, rec.minute)
                existing = exist_map.get(key)
                if existing:
                    existing.net_inflow_yi = rec.net_inflow_yi
                    existing.source = rec.source
                else:
                    db.add(rec)
            db.commit()
    except Exception as e:
        db.rollback()
        logger.exception(f'[middleman] bulk upsert error: {e}')


def collect_realtime_money_flow_snapshot(dimension: str = 'concept', trade_date: Optional[date] = None, force: bool = False):
    """
    核心中转调度器：抓取、清洗、FFill、累计、持久化。
    返回保存的记录数。
    force=True 时可在非交易时段强制采集（用于测试/补数据）。
    """
    if trade_date is None:
        trade_date = date.today()

    # 首次调用时恢复缓存
    if not DATA_CACHE[dimension] and not LAST_VALID_SNAPSHOT[dimension]:
        _restore_cache_from_db(dimension)

    now = datetime.now()
    current_hm = now.strftime('%H:%M')

    if not force and not _is_market_open(current_hm):
        logger.info(f'[middleman] [{dimension}] {current_hm} 不在交易时段，跳过')
        return 0

    logger.info(f'[middleman] [{dimension}] {current_hm} 开始抓取与清洗...')

    # 1. 网络容错
    try:
        raw_data = fetch_raw_data(dimension)
    except Exception as e:
        logger.error(f'[middleman] [{dimension}] 外部接口失败: {e}，降级使用前一分钟数据')
        raw_data = []

    # 收集所有应存在的板块
    all_block_names = set(DATA_CACHE[dimension].keys())
    for item in raw_data:
        name = item.get('block_name')
        if name:
            all_block_names.add(name)

    records_to_save = []
    saved_count = 0

    with _CACHE_LOCK:
        for name in all_block_names:
            raw_item = next((x for x in raw_data if x.get('block_name') == name), None)
            raw_val = raw_item.get('net_amount') if raw_item else None
            val_in_yi = (raw_val / 1e8) if raw_val is not None else None
            last_val = LAST_VALID_SNAPSHOT[dimension].get(name, 0.0)

            # 2. 数据清洗 + FFill
            if _should_ffill(name, val_in_yi, last_val):
                clean_val = last_val
                source = 'ffill'
                logger.warning(
                    f'[middleman] [{dimension}] [{name}] 数据异常({raw_val})，'
                    f'FFill填充为 {clean_val:.2f} 亿'
                )
            else:
                clean_val = round(val_in_yi, 2)
                source = 'api'

            # 3. 累计值（新浪返回的 netamount 已经是当日累计净流入，直接保存）
            cumulative_val = clean_val

            LAST_VALID_SNAPSHOT[dimension][name] = cumulative_val
            if name not in DATA_CACHE[dimension]:
                DATA_CACHE[dimension][name] = {}
            DATA_CACHE[dimension][name][current_hm] = cumulative_val
            saved_count += 1

            records_to_save.append(RealtimeMoneyFlowSnapshot(
                trade_date=trade_date,
                dimension=dimension,
                block_name=name,
                minute=current_hm,
                net_inflow_yi=cumulative_val,
                source=source,
            ))

    # 4. 持久化
    _bulk_upsert_snapshots(records_to_save)
    logger.info(f'[middleman] [{dimension}] {current_hm} 保存 {saved_count} 条记录')
    return saved_count


def get_money_flow_response(dimension: str = 'concept', top_n: int = 10, bottom_n: int = 5):
    """
    组装给 ECharts 的多折线数据。
    返回 {status, dimension, trade_date, timeline, series}。
    """
    # 缓存为空时先从数据库恢复（服务重启后）
    if not DATA_CACHE.get(dimension):
        _restore_cache_from_db(dimension)

    with _CACHE_LOCK:
        cache = {k: dict(v) for k, v in DATA_CACHE.get(dimension, {}).items()}

    if not cache:
        return {
            'status': 'success',
            'dimension': dimension,
            'trade_date': date.today().isoformat(),
            'timeline': MARKET_TIMELINE,
            'series': [],
        }

    # 非交易时段快照（如 20:28）不在标准 timeline 里，需要映射到 15:00 展示
    latest_snapshot_minute = None
    for name, time_series in cache.items():
        if time_series:
            last_time = max(time_series.keys())
            if latest_snapshot_minute is None or last_time > latest_snapshot_minute:
                latest_snapshot_minute = last_time

    use_close_mapping = latest_snapshot_minute and latest_snapshot_minute not in MARKET_TIMELINE

    latest_rank = []
    for name, time_series in cache.items():
        if time_series:
            last_time = max(time_series.keys())
            latest_rank.append((name, time_series[last_time]))

    latest_rank.sort(key=lambda x: x[1], reverse=True)

    top_blocks = [x[0] for x in latest_rank[:top_n]]
    bottom_blocks = [x[0] for x in latest_rank[-bottom_n:]] if len(latest_rank) > top_n else []
    target_blocks = list(dict.fromkeys(top_blocks + bottom_blocks))

    echarts_series = []
    for block_name in target_blocks:
        data_points = []
        running_val = 0.0
        for t in MARKET_TIMELINE:
            if t in cache.get(block_name, {}):
                running_val = cache[block_name][t]
            # 非交易时段：把最新快照值放到 15:00
            if use_close_mapping and t == '15:00' and block_name in cache:
                running_val = cache[block_name].get(latest_snapshot_minute, running_val)
            data_points.append(round(running_val, 2))

        echarts_series.append({
            'name': block_name,
            'type': 'line',
            'smooth': True,
            'data': data_points,
        })

    return {
        'status': 'success',
        'dimension': dimension,
        'trade_date': date.today().isoformat(),
        'timeline': MARKET_TIMELINE,
        'series': echarts_series,
    }
