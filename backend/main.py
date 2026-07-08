"""
AIROBOT 市场指挥舱 - FastAPI 入口
端口 9000，同时服务 API 和前端
"""
import sys, os
import logging
import uuid
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.gzip import GZipMiddleware
from contextlib import asynccontextmanager

# 启用慢查询监听（>200ms 记录到 logger）
import utils.slow_query_logger  # noqa: F401

from api import heatmap, rotation, lifecycle, lifecycle_v2, lifecycle_v3, money_flow, screener, portfolio, baihu, trading, analysis, bs_signals, realtime, quality, watchlist, bs_screener, bs_backtest, leader_system, leader_history, mx_skills, sync_pkg, sina_sync, stock_research, focus_stocks, panorama, concept_sector, strategy_tags, auto_trading, mx_trading, trading_system, yuzi, yuzi_tracker, super_panel, money_flow_detail, index_flow, liangjia_report, strategy_resonance, global_market, market_stage
from api.rate_limit import RateLimitMiddleware
from collectors.scheduler import start_scheduler, scheduler
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow
from sqlalchemy import func
from config import CORS_ORIGINS


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 创建共享 httpx 客户端（复用 TCP 连接，减少 30+ 处独立创建的开销）
    import httpx
    app.state.http_client = httpx.AsyncClient(
        timeout=10,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=5),
        headers={"User-Agent": "AIROBOT/1.0"},
    )
    # 将共享客户端注入到 _shared 模块，供非路由函数使用
    from api.watchlist._shared import set_shared_http_client
    set_shared_http_client(app.state.http_client)
    # 启动时开始定时采集
    start_scheduler()
    # 确保新表/新列存在（轻量级迁移）
    _ensure_bs_strategy_columns()
    # 预热自选股缓存（后台异步，不阻塞启动）
    from api.watchlist import _refresh_watchlist_cache
    _refresh_watchlist_cache()
    # 聚合预热其他热点缓存（串行，避免外部API限流）
    import asyncio
    asyncio.create_task(_refresh_caches())
    yield
    # 关闭时清理：必须先停 scheduler（停止所有 job），再关 http_client
    # 否则 job 仍在用 http_client → 'RuntimeError: handler is closed'
    try:
        scheduler.shutdown(wait=False)
    except Exception:
        pass
    await app.state.http_client.aclose()


async def _refresh_caches():
    """聚合预热/刷新各模块缓存，串行调用避免外部API限流"""
    try:
        from api.concept_sector import _refresh_hot_cache
        from api.heatmap import refresh_heatmap_cache
        from api.analysis import refresh_signal_cache
        # 纯DB缓存先行（快）
        _refresh_hot_cache()
        refresh_heatmap_cache()
        # 预热 index-flow（避免首次访问 25 秒卡顿）
        try:
            import httpx
            async with httpx.AsyncClient(timeout=30) as client:
                await client.get('http://localhost:9000/api/index-flow/rank')
            print('[startup] index-flow cache preheated')
        except Exception as e:
            print(f'[startup] index-flow preheat skip: {e}')
        # 依赖妙想API的缓存（慢，盘中才有意义，盘前失败可忽略）
        await refresh_signal_cache()
        print('[startup] cache warmup done')
    except Exception as e:
        print(f'[startup] cache warmup error: {e}')


def _ensure_bs_strategy_columns():
    """确保 bs_strategies 和 bs_backtest_results 表存在"""
    from db.connection import engine, Base
    from db.models import BSStrategy, BSBacktestResult
    from sqlalchemy import text
    # 先确保表存在
    Base.metadata.create_all(bind=engine, tables=[BSStrategy.__table__, BSBacktestResult.__table__])
    # 确保个股研究沉淀新表存在（资讯搜索/金融数据查询/AI分析缓存）
    from db.models import StockNewsSearch, StockDataQuery, AIAnalysisCache
    Base.metadata.create_all(bind=engine, tables=[
        StockNewsSearch.__table__, StockDataQuery.__table__, AIAnalysisCache.__table__,
    ])
    # 确保个股特征每日表存在（CHOPPY/TREND/IMPULSE 三态判定）
    from db.models import StockFeaturesDaily
    Base.metadata.create_all(bind=engine, tables=[StockFeaturesDaily.__table__])
    # StockFeaturesDaily 新增 rsi_14 列（RSI(14) 技术指标，用于 7 段技术形态判定）
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE stock_features_daily ADD COLUMN IF NOT EXISTS rsi_14 DOUBLE PRECISION"
        ))
        conn.commit()
    # 确保模拟盘持仓/账户快照表存在（支持历史盈亏回溯）
    from db.models import SimPositionSnapshot, SimAccountSnapshot
    Base.metadata.create_all(bind=engine, tables=[
        SimPositionSnapshot.__table__, SimAccountSnapshot.__table__,
    ])
    # 确保概念板块相关表存在
    from db.models import ConceptSector, ConceptSectorFlow, RealtimeConceptSectorFlow
    Base.metadata.create_all(bind=engine, tables=[
        ConceptSector.__table__, ConceptSectorFlow.__table__, RealtimeConceptSectorFlow.__table__,
    ])
    # 确保策略结果表 + 运行日志 + 个股信号预计算表存在
    from db.models import StrategyResult, StrategyRunLog, WatchlistSignalDaily
    Base.metadata.create_all(bind=engine, tables=[
        StrategyResult.__table__, StrategyRunLog.__table__, WatchlistSignalDaily.__table__,
    ])
    # 确保游资系统 4.0 交易信号日报表存在
    from db.models import TradingSignalDaily
    Base.metadata.create_all(bind=engine, tables=[TradingSignalDaily.__table__])
    # 确保游资龙虎榜（席位字典/共振信号/席位明细）表存在
    from db.models import YuziDict, YuziQuantSignal, YuziSeatDaily
    Base.metadata.create_all(bind=engine, tables=[
        YuziDict.__table__, YuziQuantSignal.__table__, YuziSeatDaily.__table__,
    ])
    # YuziDict 新增 style 列（操作风格:稳健/一日游/砸盘/接力/低吸/趋势/首板/机构）
    with engine.connect() as conn:
        conn.execute(text(
            "ALTER TABLE yuzi_dict ADD COLUMN IF NOT EXISTS style VARCHAR(50) DEFAULT '稳健'"
        ))
        conn.commit()
    # 确保游资 20 天生命周期跟踪表存在
    from db.models import YuziLifecycleTracker
    Base.metadata.create_all(bind=engine, tables=[YuziLifecycleTracker.__table__])
    # 兼容旧列: net_return_7d → net_return_20d
    with engine.connect() as conn:
        conn.execute(text("""
            DO $$
            BEGIN
              IF EXISTS(SELECT 1 FROM information_schema.columns
                        WHERE table_name='yuzi_lifecycle_tracker' AND column_name='net_return_7d')
                AND NOT EXISTS(SELECT 1 FROM information_schema.columns
                               WHERE table_name='yuzi_lifecycle_tracker' AND column_name='net_return_20d')
              THEN
                ALTER TABLE yuzi_lifecycle_tracker RENAME COLUMN net_return_7d TO net_return_20d;
              END IF;
            END$$;
        """))
        conn.commit()
    # 确保自动化交易配置+日志表存在，并初始化默认配置行
    from db.models import AutoTradeConfig, AutoTradeLog, SimAccount, SimPosition, SimOrder
    from db.connection import get_db
    from db.session import get_db_session
    Base.metadata.create_all(bind=engine, tables=[
        AutoTradeConfig.__table__, AutoTradeLog.__table__,
        SimAccount.__table__, SimPosition.__table__, SimOrder.__table__,
    ])
    # 先确保 auto_trade_config 新列存在，再查询（避免 SQLAlchemy 模型与表结构不一致）
    with engine.connect() as conn:
        for col_def in [
            ('buy_quantity', 'INTEGER DEFAULT 100'),
            ('sell_quantity', 'INTEGER DEFAULT 100'),
        ]:
            conn.execute(text(
                f"ALTER TABLE auto_trade_config ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()
    with get_db_session() as _db:
        if not _db.query(AutoTradeConfig).filter_by(id=1).first():
            _db.add(AutoTradeConfig(id=1))
            _db.commit()
    # 再确保新列存在（兼容旧表）
    with engine.connect() as conn:
        # bs_strategies 新列
        for col in ['volume_filter', 'ma20_filter', 'ma60_trend', 'rsi_filter', 'strong_volume']:
            conn.execute(text(
                f"ALTER TABLE bs_strategies ADD COLUMN IF NOT EXISTS {col} BOOLEAN DEFAULT FALSE"
            ))
        # bs_backtest_results 新列
        for col_def in [
            ('name', 'VARCHAR(50)'),
            ('ma60_trend', 'BOOLEAN DEFAULT FALSE'),
            ('rsi_filter', 'BOOLEAN DEFAULT FALSE'),
            ('strong_volume', 'BOOLEAN DEFAULT FALSE'),
            ('macd_filter', 'BOOLEAN DEFAULT FALSE'),
            ('kdj_filter', 'BOOLEAN DEFAULT FALSE'),
            ('stop_loss_pct', 'NUMERIC(5,2) DEFAULT 0'),
        ]:
            conn.execute(text(
                f"ALTER TABLE bs_backtest_results ADD COLUMN IF NOT EXISTS {col_def[0]} {col_def[1]}"
            ))
        conn.commit()


app = FastAPI(title="AIROBOT 市场指挥舱", lifespan=lifespan)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GZip 压缩：压缩 API 响应与静态资源（含 echarts 等大体积 JS），首屏传输体积显著下降
app.add_middleware(GZipMiddleware, minimum_size=512)

# 限流中间件
app.add_middleware(RateLimitMiddleware)

# API路由
app.include_router(heatmap.router)
app.include_router(rotation.router)
app.include_router(lifecycle.router)
app.include_router(lifecycle_v2.router)
app.include_router(lifecycle_v3.router)
app.include_router(money_flow.router)
app.include_router(screener.router)
app.include_router(portfolio.router)
app.include_router(baihu.router)
app.include_router(trading.router)
app.include_router(analysis.router)
app.include_router(bs_signals.router)
app.include_router(realtime.router)
app.include_router(quality.router)
app.include_router(watchlist.router)
app.include_router(bs_screener.router)
app.include_router(bs_backtest.router)
app.include_router(leader_system.router)
app.include_router(leader_history.router)
app.include_router(mx_skills.router)
app.include_router(sync_pkg.router)
app.include_router(sina_sync.router)
app.include_router(stock_research.router)
app.include_router(focus_stocks.router)
app.include_router(panorama.router)
app.include_router(index_flow.router)
app.include_router(concept_sector.router)
app.include_router(strategy_tags.router)
app.include_router(auto_trading.router)
app.include_router(mx_trading.router)
app.include_router(trading_system.router)
app.include_router(yuzi.router)
app.include_router(yuzi_tracker.router)
app.include_router(super_panel.router)
app.include_router(money_flow_detail.router)
app.include_router(liangjia_report.router)
app.include_router(strategy_resonance.router)
app.include_router(global_market.router)
app.include_router(market_stage.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "AIROBOT"}


# 全局异常处理：未捕获异常返回统一结构 + request_id 日志，避免 500 裸奔
logger = logging.getLogger("airobat")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    rid = uuid.uuid4().hex[:8]
    logger.exception("Unhandled error", extra={"request_id": rid})
    return JSONResponse(status_code=500, content={
        "title": "INTERNAL_ERROR",
        "status": 500,
        "detail": "服务器内部错误，请稍后重试",
        "request_id": rid,
    })


@app.get("/api/latest-date")
def latest_date():
    """返回数据库中最新有数据的交易日期"""
    with get_db_session() as db:
        result = db.query(func.max(SectorFlow.trade_date)).scalar()
        if result:
            return {"date": result.strftime('%Y-%m-%d')}
        return {"date": None}


# 前端静态资源（构建后存在）
frontend_dist = os.path.join(os.path.dirname(__file__), '..', 'frontend', 'dist')
if os.path.exists(frontend_dist):
    app.mount("/assets", StaticFiles(directory=os.path.join(frontend_dist, 'assets')), name="assets")

    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # API路径返回真实 404 状态码
        if full_path.startswith('api/'):
            raise HTTPException(status_code=404, detail="Not found")
        index_path = os.path.join(frontend_dist, 'index.html')
        if os.path.exists(index_path):
            return FileResponse(index_path, media_type='text/html', headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            })
        return JSONResponse({"error": "Frontend not built"}, status_code=503)


if __name__ == '__main__':
    import uvicorn
    from config import API_PORT
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
