"""全市场 F10 批量预拉（免费源：Tushare + 东方财富）+ 写入 stock_f10 / stock_universe

用途：
- 把全市场 A 股（stock_basic 上市状态）的基础信息写入 stock_universe（名称/行业/板块）。
- 逐只拉 F10（财务 fina_indicator+income+daily_basic / 机构 top10_floatholders / 评级东方财富），
  按 ts_code 缓存进 stock_f10（TTL 1 天）。
- call_tushare_mcp 自带全局令牌桶限流（250/min），逐只调用即可，无需额外 sleep。
- 支持断点续拉：stock_f10 已存在且 fetched_at 在 TTL 内则跳过（--force 强制重拉）。

全市场体量约 5500 只，3 接口/只 ≈ 1.6 万次调用，按 250/min 约 60+ 分钟。
建议作为后台任务运行（run_in_background），首次跑完后每日增量很快。

用法：
  python scripts/backfill_f10_full.py --layer all --limit 300     # 小批量验证
  python scripts/backfill_f10_full.py --layer all                 # 全量（后台）
  python scripts/backfill_f10_full.py --layer financials          # 仅财务+估值
  python scripts/backfill_f10_full.py --layer institution         # 仅机构
  python scripts/backfill_f10_full.py --layer all --force         # 强制重拉
"""
import argparse
import json
import logging
import sys
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill_f10")

# 让脚本能 import 项目模块（backend/ 为根）
sys.path.insert(0, "/Users/gino/Projects/AIROBOT/backend")

from dotenv import load_dotenv
load_dotenv("/Users/gino/Projects/AIROBOT/.env")

from sqlalchemy import select, func
from db.connection import SessionLocal, engine, Base
from db.models import StockUniverse, StockF10

# 复用研报中心的免费 F10 拉取逻辑（内部已带 PG 缓存）
from services.f10_provider import (
    _fetch_financials, _fetch_institution, _fetch_rating,
    CACHE_TTL_HOURS, _cache_set,
)
from collectors.tdx_collector import call_tushare_mcp


def load_universe(force_refresh: bool = False) -> int:
    """拉全市场上市股票基础信息写入 stock_universe。返回写入/更新行数。"""
    existing = {}
    with SessionLocal() as db:
        for row in db.execute(select(StockUniverse)).scalars().all():
            existing[row.ts_code] = row

    rows = call_tushare_mcp(
        "stock_basic",
        params={"list_status": "L", "exchange": ""},
        fields=["ts_code", "name", "industry", "market", "list_status"],
    )
    if not rows:
        logger.warning("stock_basic 返回空，跳过 universe 更新")
        return 0

    count = 0
    with SessionLocal() as db:
        for r in rows:
            tc = r.get("ts_code")
            if not tc:
                continue
            obj = existing.get(tc) or StockUniverse(ts_code=tc)
            obj.name = r.get("name") or ""
            obj.industry = r.get("industry") or ""
            obj.market = r.get("market") or ""
            obj.list_status = r.get("list_status") or "L"
            obj.is_active = (r.get("list_status") == "L")
            db.merge(obj)
            existing[tc] = obj
            count += 1
        db.commit()
    logger.info("stock_universe 写入/更新 %s 只", count)
    return count


def _is_fresh(ts_code: str) -> bool:
    with SessionLocal() as db:
        row = db.get(StockF10, ts_code)
        if row and row.fetched_at:
            return datetime.now() - row.fetched_at < timedelta(hours=CACHE_TTL_HOURS)
    return False


def backfill(layer: str, limit: int = None, force: bool = False,
              pull_rating: bool = False) -> dict:
    """逐只拉 F10 并落 stock_f10。layer: financials | institution | all

    pull_rating: 是否拉东方财富评级/目标价。默认 False —— 本环境东财接口无数据，
    且每只都打 HTTP 会显著拖慢全量；单只报告走 fetch_f10 时仍按需尝试。
    """
    # 确保 universe 已加载（提供覆盖池与名称/行业）
    load_universe()

    with SessionLocal() as db:
        q = select(StockUniverse).where(StockUniverse.is_active == True)
        if limit:
            # 按主键顺序取前 N 只（便于小批量验证可复现）
            q = q.order_by(StockUniverse.ts_code).limit(limit)
        else:
            q = q.order_by(StockUniverse.ts_code)
        codes = [r.ts_code for r in db.execute(q).scalars().all()]

    logger.info("覆盖池 %s 只，开始拉取 layer=%s (pull_rating=%s)", len(codes), layer, pull_rating)
    stats = {"total": len(codes), "financials_ok": 0, "institution_ok": 0,
             "rating_ok": 0, "skipped": 0, "errors": 0}
    t0 = datetime.now()

    for i, tc in enumerate(codes, 1):
        try:
            if not force and _is_fresh(tc):
                stats["skipped"] += 1
                continue
            financials = None
            institution = None
            rating = None
            if layer in ("financials", "all"):
                financials = _fetch_financials(tc)
                if financials:
                    stats["financials_ok"] += 1
            if layer in ("institution", "all"):
                institution = _fetch_institution(tc)
                if institution:
                    stats["institution_ok"] += 1
            if pull_rating and layer in ("all",):
                rating = _fetch_rating(tc)
                if rating:
                    stats["rating_ok"] += 1
            if financials or institution or rating:
                _cache_set(tc, financials, institution, rating)
        except Exception as e:
            stats["errors"] += 1
            logger.warning("[%s] 拉取异常: %s", tc, e)

        if i % 100 == 0:
            el = (datetime.now() - t0).total_seconds()
            logger.info("进度 %s/%s | 耗时 %.0fs | %s", i, len(codes), el, stats)

    el = (datetime.now() - t0).total_seconds()
    logger.info("完成 layer=%s | 总耗时 %.0fs | %s", layer, el, stats)
    return stats


def main():
    ap = argparse.ArgumentParser(description="全市场 F10 批量预拉")
    ap.add_argument("--layer", choices=["financials", "institution", "all"],
                    default="all", help="拉取层级（默认 all）")
    ap.add_argument("--limit", type=int, default=None,
                    help="仅处理前 N 只（按 ts_code 排序），用于小批量验证")
    ap.add_argument("--force", action="store_true", help="强制重拉（忽略 TTL 缓存）")
    ap.add_argument("--with-rating", action="store_true",
                    help="同时拉东方财富评级/目标价（本环境通常无数据，默认跳过以加速）")
    ap.add_argument("--universe-only", action="store_true",
                    help="仅刷新 stock_universe 基础信息表，不拉 F10")
    args = ap.parse_args()

    if args.universe_only:
        n = load_universe(force_refresh=True)
        logger.info("universe-only 完成，写入 %s 只", n)
        return

    # 建表（首次运行确保 stock_universe / stock_f10 存在）
    Base.metadata.create_all(bind=engine, tables=[StockUniverse.__table__, StockF10.__table__])

    if args.limit:
        backfill(args.layer, limit=args.limit, force=args.force, pull_rating=args.with_rating)
    else:
        backfill(args.layer, force=args.force, pull_rating=args.with_rating)


if __name__ == "__main__":
    main()
