"""
重点关注股票 API
- 返回按科技赛道分组的重点关注股票列表
- 数据维度与 /api/watchlist 完全对齐（quote/buyPower/marketState/qualityStatus/sectorTrend/bsSignal）
- 前端可直接复用 SignalCard 组件
- 支持一键添加到自选股
"""
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from db.connection import get_db
from db.session import get_db_session
from services.signal_builder import build_signal_for_stock, build_signal_from_precomputed
from db.models import WatchlistSignalDaily

router = APIRouter()

# ============================================================
# 科技赛道重点关注股票池（基于市场热点梳理）
# ============================================================
FOCUS_STOCKS = [
    {
        "sector": "MLCC",
        "icon": "",
        "color": "#3b82f6",
        "stocks": [
            {"code": "300726", "name": "国瓷材料"},
            {"code": "000636", "name": "风华高科"},
            {"code": "002138", "name": "三环集团"},
            {"code": "603678", "name": "火炬电子"},
        ],
    },
    {
        "sector": "CPO",
        "icon": "🔴",
        "color": "#ef4444",
        "stocks": [
            {"code": "002281", "name": "光迅科技"},
            {"code": "300308", "name": "中际旭创"},
            {"code": "300502", "name": "新易盛"},
            {"code": "300394", "name": "天孚通信"},
            {"code": "000988", "name": "华工科技"},
        ],
    },
    {
        "sector": "PCB",
        "icon": "🟢",
        "color": "#22c55e",
        "stocks": [
            {"code": "300476", "name": "胜宏科技"},
            {"code": "002384", "name": "东山精密"},
            {"code": "002916", "name": "深南电路"},
            {"code": "002463", "name": "沪电股份"},
        ],
    },
    {
        "sector": "存储芯片",
        "icon": "🟦",
        "color": "#6366f1",
        "stocks": [
            {"code": "603986", "name": "兆易创新"},
            {"code": "688525", "name": "佰维存储"},
            {"code": "301571", "name": "德明利"},
            {"code": "300456", "name": "江波龙"},
        ],
    },
    {
        "sector": "先进封装",
        "icon": "🟪",
        "color": "#a855f7",
        "stocks": [
            {"code": "002156", "name": "通富微电"},
            {"code": "600584", "name": "长电科技"},
            {"code": "002185", "name": "华天科技"},
            {"code": "603005", "name": "晶方科技"},
        ],
    },
    {
        "sector": "光纤光缆",
        "icon": "",
        "color": "#f97316",
        "stocks": [
            {"code": "601869", "name": "长飞光纤"},
            {"code": "600487", "name": "亨通光电"},
            {"code": "600522", "name": "中天科技"},
            {"code": "000066", "name": "烽火通信"},
        ],
    },
    {
        "sector": "AI PC",
        "icon": "🖥️",
        "color": "#06b6d4",
        "stocks": [
            {"code": "000725", "name": "京东方A"},
            {"code": "603890", "name": "春秋电子"},
            {"code": "300346", "name": "苏大维格"},
            {"code": "688486", "name": "龙芯中科"},
        ],
    },
    {
        "sector": "AI芯片",
        "icon": "🧠",
        "color": "#ec4899",
        "stocks": [
            {"code": "688256", "name": "寒武纪"},
            {"code": "688041", "name": "海光信息"},
            {"code": "688691", "name": "灿芯股份"},
            {"code": "688396", "name": "华润微"},
        ],
    },
    {
        "sector": "AI服务器",
        "icon": "🖧",
        "color": "#14b8a6",
        "stocks": [
            {"code": "601138", "name": "工业富联"},
            {"code": "000977", "name": "浪潮信息"},
            {"code": "002049", "name": "紫光国微"},
            {"code": "603019", "name": "中科曙光"},
        ],
    },
    {
        "sector": "OCS",
        "icon": "💎",
        "color": "#8b5cf6",
        "stocks": [
            {"code": "688195", "name": "腾景科技"},
            {"code": "002222", "name": "福晶科技"},
            {"code": "300620", "name": "光库科技"},
            {"code": "688205", "name": "德科立"},
        ],
    },
    {
        "sector": "培育钻石",
        "icon": "💠",
        "color": "#0ea5e9",
        "stocks": [
            {"code": "600172", "name": "黄河旋风"},
            {"code": "002149", "name": "西部材料"},
            {"code": "300179", "name": "四方达"},
        ],
    },
    {
        "sector": "玻璃基板",
        "icon": "🔲",
        "color": "#64748b",
        "stocks": [
            {"code": "002436", "name": "兴森科技"},
            {"code": "603773", "name": "沃格光电"},
            {"code": "600707", "name": "彩虹股份"},
            {"code": "600876", "name": "凯盛科技"},
            {"code": "002855", "name": "捷荣技术"},
        ],
    },
    {
        "sector": "陶瓷基板",
        "icon": "🏺",
        "color": "#d97706",
        "stocks": [
            {"code": "600353", "name": "旭光电子"},
            {"code": "003031", "name": "中瓷电子"},
            {"code": "002913", "name": "奥士康"},
            {"code": "002151", "name": "北斗星通"},
        ],
    },
    {
        "sector": "高速链接",
        "icon": "⚡",
        "color": "#e11d48",
        "stocks": [
            {"code": "002475", "name": "立讯精密"},
            {"code": "300913", "name": "兆龙互连"},
            {"code": "002130", "name": "沃尔核材"},
            {"code": "688668", "name": "鼎通科技"},
        ],
    },
    {
        "sector": "铜箔",
        "icon": "🟫",
        "color": "#b45309",
        "stocks": [
            {"code": "301217", "name": "铜冠铜箔"},
            {"code": "600110", "name": "诺德股份"},
            {"code": "688388", "name": "嘉元科技"},
            {"code": "301511", "name": "德福科技"},
        ],
    },
    {
        "sector": "树脂",
        "icon": "🍃",
        "color": "#16a34a",
        "stocks": [
            {"code": "601208", "name": "东材科技"},
            {"code": "605589", "name": "圣泉集团"},
            {"code": "002245", "name": "蔚蓝锂芯"},
            {"code": "603002", "name": "宏昌电子"},
        ],
    },
    {
        "sector": "电子布",
        "icon": "🧵",
        "color": "#475569",
        "stocks": [
            {"code": "603256", "name": "宏和科技"},
            {"code": "600176", "name": "中国巨石"},
            {"code": "002080", "name": "中材科技"},
            {"code": "301526", "name": "国际复材"},
        ],
    },
    {
        "sector": "液冷",
        "icon": "❄️",
        "color": "#0284c7",
        "stocks": [
            {"code": "002837", "name": "英维克"},
            {"code": "000811", "name": "冰轮环境"},
            {"code": "300969", "name": "恒帅股份"},
            {"code": "002126", "name": "银轮股份"},
        ],
    },
    {
        "sector": "六氟化钨",
        "icon": "⚗️",
        "color": "#7c3aed",
        "stocks": [
            {"code": "688146", "name": "中船特气"},
            {"code": "002971", "name": "和远气体"},
            {"code": "600378", "name": "昊华科技"},
            {"code": "688268", "name": "华特气体"},
        ],
    },
    {
        "sector": "碳酸铁锂",
        "icon": "🔋",
        "color": "#059669",
        "stocks": [
            {"code": "002591", "name": "恒大高新"},
            {"code": "600096", "name": "云天化"},
            {"code": "300014", "name": "亿纬锂能"},
            {"code": "002125", "name": "湘潭电化"},
        ],
    },
]

@router.get("/api/focus-stocks")
async def get_focus_stocks():
    """获取重点关注股票列表（按赛道分组，含完整 signal 数据，与自选股维度对齐）"""
    with get_db_session() as db:
        # 展开所有股票
        all_stocks = [
            (s["code"], s["name"], sector_data["sector"])
            for sector_data in FOCUS_STOCKS
            for s in sector_data["stocks"]
        ]

        # 优先从预计算表读取（毫秒级），缺失时才现场计算
        import asyncio

        # 取最近一日的预计算数据
        latest_date = db.query(WatchlistSignalDaily.trade_date).order_by(
            WatchlistSignalDaily.trade_date.desc()
        ).first()
        precomputed_map = {}
        if latest_date:
            rows = db.query(WatchlistSignalDaily).filter(
                WatchlistSignalDaily.trade_date == latest_date[0]
            ).all()
            for r in rows:
                # ts_code (600000.SH) → code (600000)
                code = r.ts_code.split('.')[0] if r.ts_code else ''
                if code:
                    precomputed_map[code] = r

        # 分批构造 signal：预计算命中用快速路径，未命中用现场计算
        BATCH = 20
        all_signals = []
        precomputed_hits = 0
        for i in range(0, len(all_stocks), BATCH):
            batch = all_stocks[i:i + BATCH]
            tasks = []
            for code, name, sector_name in batch:
                pre = precomputed_map.get(code)
                if pre is not None:
                    precomputed_hits += 1
                    tasks.append(build_signal_from_precomputed(
                        code, name, pre,
                        extra_positive=[{"label": "赛道", "value": sector_name, "type": "positive"}],
                        db=db,
                    ))
                else:
                    tasks.append(build_signal_for_stock(code, name, sector_name, db))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for r in results:
                if not isinstance(r, Exception) and r is not None:
                    all_signals.append(r)

        # 批量补充 moneyFlow/hitTags/actionHint（与自选股 build_watchlist 完全一致口径）
        from services.signal_builder import _enrich_signals_with_watchlist_extras
        await _enrich_signals_with_watchlist_extras(db, all_signals)

        # 按赛道分组
        signal_map = {s['secCode']: s for s in all_signals}
        sectors_result = []
        for sector_data in FOCUS_STOCKS:
            sector_signals = [
                signal_map[s["code"]]
                for s in sector_data["stocks"]
                if s["code"] in signal_map
            ]
            sectors_result.append({
                "sector": sector_data["sector"],
                "icon": sector_data["icon"],
                "color": sector_data["color"],
                "stocks": sector_signals,
            })

        # 统计
        total_stocks = len(all_signals)
        up_count = sum(1 for s in all_signals if s.get("quote") and s["quote"]["changePct"] > 0)
        down_count = sum(1 for s in all_signals if s.get("quote") and s["quote"]["changePct"] < 0)
        limit_up_count = sum(1 for s in all_signals if s.get("quote") and s["quote"]["changePct"] >= 9.8)

        return {
            "sectors": sectors_result,
            "summary": {
                "total_sectors": len(sectors_result),
                "total_stocks": total_stocks,
                "up_count": up_count,
                "down_count": down_count,
                "flat_count": total_stocks - up_count - down_count,
                "limit_up_count": limit_up_count,
            },
            "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }


@router.get("/api/focus-stocks/sectors")
async def get_focus_sectors():
    """仅获取赛道列表（不含行情，用于快速加载）"""
    return {
        "sectors": [
            {"sector": s["sector"], "icon": s["icon"], "color": s["color"], "count": len(s["stocks"])}
            for s in FOCUS_STOCKS
        ]
    }


class AddFocusStockRequest(BaseModel):
    stockCode: str
    stockName: str = ''
    group: str = '重点关注'


@router.post("/api/focus-stocks/add-to-watchlist")
async def add_focus_to_watchlist(req: AddFocusStockRequest):
    """将重点关注股票添加到自选股"""
    from db.session import get_db_session
    from db.models import Watchlist

    try:
        with get_db_session() as db:
            existing = db.query(Watchlist).filter_by(stock_code=req.stockCode).first()
            if existing:
                return {'success': True, 'message': '已在自选股中', 'already_exists': True}

            item = Watchlist(
                stock_code=req.stockCode,
                stock_name=req.stockName,
                note='重点关注',
                group_name=req.group,
            )
            db.add(item)
            db.commit()
            return {'success': True, 'message': f'{req.stockName} 已添加到自选股'}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/focus-stocks/batch-add-to-watchlist")
async def batch_add_to_watchlist(req: dict):
    """批量将选中的重点关注股票添加到自选股"""
    from db.session import get_db_session
    from db.models import Watchlist

    stock_codes = req.get("stock_codes", [])
    if not stock_codes:
        return {'success': True, 'added': 0, 'skipped': 0}

    focus_map = {}
    for sector_data in FOCUS_STOCKS:
        for s in sector_data["stocks"]:
            focus_map[s["code"]] = s["name"]

    added = 0
    skipped = 0
    try:
        with get_db_session() as db:
            for code in stock_codes:
                name = focus_map.get(code, '')
                existing = db.query(Watchlist).filter_by(stock_code=code).first()
                if existing:
                    skipped += 1
                    continue
                item = Watchlist(
                    stock_code=code,
                    stock_name=name,
                    note='重点关注',
                    group_name='重点关注',
                )
                db.add(item)
                added += 1
            db.commit()
            return {'success': True, 'added': added, 'skipped': skipped}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/focus-stocks/batch-add")
async def batch_add_focus_stocks(req: dict):
    """批量添加赛道内所有股票到自选股"""
    from db.session import get_db_session
    from db.models import Watchlist

    sector_name = req.get("sector", "")
    group = req.get("group", "重点关注")

    # 找到对应赛道
    sector_data = next((s for s in FOCUS_STOCKS if s["sector"] == sector_name), None)
    if not sector_data:
        raise HTTPException(status_code=404, detail=f"赛道「{sector_name}」不存在")

    try:
        with get_db_session() as db:
            added = []
            skipped = []
            for stock in sector_data["stocks"]:
                existing = db.query(Watchlist).filter_by(stock_code=stock["code"]).first()
                if existing:
                    skipped.append(stock["name"])
                    continue
                item = Watchlist(
                    stock_code=stock["code"],
                    stock_name=stock["name"],
                    note=f'重点关注-{sector_name}',
                    group_name=group,
                )
                db.add(item)
                added.append(stock["name"])
            db.commit()
            return {
                'success': True,
                'added': len(added),
                'skipped': len(skipped),
                'added_list': added,
                'skipped_list': skipped,
            }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
