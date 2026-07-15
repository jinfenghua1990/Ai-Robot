"""
盘后研究采集（填补本地"定性/新闻/因果"层空白）
- 目标池 = 自选股 ∪ 当日强势股(涨幅>=阈值) ∪ 龙头生命周期活跃股
- 对每只目标股调用妙想资讯搜索 + 金融数据查询（自动落库 stock_news_search / stock_data_query）
- 生成 AI 综合分析并落库 ai_analysis_cache：
    优先走配置的 LLM（AI_LLM_API_KEY），未配置则用妙想结构化内容作基线（model='mx-search-baseline'）
设计原则：完全复用现有 api.mx_skills 的存库逻辑，不重复造轮子；懒加载避免循环依赖。
"""
import logging
import json
import asyncio
from datetime import datetime

from config import (
    AI_LLM_API_KEY, AI_LLM_BASE_URL, AI_LLM_MODEL,
    RESEARCH_LIMIT_UP_PCT, RESEARCH_ACTIVE_STAGES, RESEARCH_THROTTLE,
)

logger = logging.getLogger(__name__)


def _to_6digit(ts_code: str) -> str:
    """300017.SZ -> 300017 ; 300017 -> 300017"""
    if not ts_code:
        return ts_code
    return ts_code.split('.')[0]


def get_research_targets(today: str = None) -> list:
    """返回去重后的目标池 [(code6, name, source_csv), ...]"""
    from db.session import get_db_session
    from db.models import Watchlist, StockFlow, LeaderLifecycle

    today = today or datetime.now().strftime('%Y-%m-%d')
    targets: dict = {}  # code6 -> {'name': str, 'sources': set}

    with get_db_session() as db:
        # 1) 自选股
        for w in db.query(Watchlist).all():
            code = _to_6digit(w.stock_code)
            if not code:
                continue
            t = targets.setdefault(code, {'name': w.stock_name or '', 'sources': set()})
            t['sources'].add('watchlist')
            if not t['name'] and w.stock_name:
                t['name'] = w.stock_name

        # 2) 当日强势股（涨幅 >= 阈值，默认 9%）
        for r in db.query(StockFlow).filter(
            StockFlow.trade_date == today,
            StockFlow.price_chg >= RESEARCH_LIMIT_UP_PCT,
        ).all():
            code = _to_6digit(r.ts_code)
            if not code:
                continue
            t = targets.setdefault(code, {'name': r.name or '', 'sources': set()})
            t['sources'].add('strong_move')
            if not t['name'] and r.name:
                t['name'] = r.name

        # 3) 龙头生命周期活跃阶段
        for r in db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == today,
            LeaderLifecycle.stage.in_(RESEARCH_ACTIVE_STAGES),
        ).all():
            code = _to_6digit(r.ts_code)
            if not code:
                continue
            t = targets.setdefault(code, {'name': r.name or '', 'sources': set()})
            t['sources'].add('leader_active')
            if not t['name'] and r.name:
                t['name'] = r.name

    return [(c, v['name'], ','.join(sorted(v['sources']))) for c, v in targets.items()]


def _lookup_name(code6: str) -> str:
    from db.session import get_db_session
    from db.models import Watchlist, StockFlow, LeaderLifecycle
    with get_db_session() as db:
        w = db.query(Watchlist).filter(Watchlist.stock_code == code6).first()
        if w and w.stock_name:
            return w.stock_name
        r = db.query(StockFlow).filter(
            StockFlow.ts_code.like(code6 + '.%')).order_by(StockFlow.trade_date.desc()).first()
        if r and r.name:
            return r.name
        l = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.ts_code.like(code6 + '.%')).order_by(LeaderLifecycle.trade_date.desc()).first()
        if l and l.name:
            return l.name
    return ''


# ==================== C6: 可插拔"网上数据源"注册表 ====================
# 每个 source 是 async 函数 (code6, name) -> dict，返回 {"news": 文本, "data": 表或None, "tag": 来源标识}
# 现有源均基于妙想；未来新增东财研报/雪球热度/交易所公告等，只需实现一个函数并追加到 RESEARCH_SOURCES。
# 落库复用 api.mx_skills 的 save 逻辑（每次 mx 查询带 stock_code 即自动写入 stock_news_search / stock_data_query）。

async def _src_mx_news_data(code6, name):
    """妙想主源：资讯搜索 + 金融数据查询（原逻辑）"""
    from api.mx_skills import mx_search_query, mx_data_query, NLQuery
    news_content, data_tables = '', None
    try:
        news_resp = await mx_search_query(NLQuery(
            query=f"{name} 最新公告 利好 利空 近期催化因素",
            stock_code=code6, stock_name=name))
        news_content = (news_resp or {}).get('content', '') or ''
    except Exception as e:
        logger.warning(f'[research] {code6} 资讯搜索失败: {e}')
    try:
        data_resp = await mx_data_query(NLQuery(
            query=f"{name} 近一年营收 净利润 毛利率 主力资金流向",
            stock_code=code6, stock_name=name))
        data_tables = (data_resp or {}).get('tables')
    except Exception as e:
        logger.warning(f'[research] {code6} 数据查询失败: {e}')
    return {"news": news_content, "data": data_tables, "tag": "mx-main"}


async def _src_mx_research_report(code6, name):
    """妙想扩展源：机构研报 / 评级 / 目标价 / 盈利预测（演示新源接入，丰富研究层）"""
    from api.mx_skills import mx_search_query, NLQuery
    content = ''
    try:
        resp = await mx_search_query(NLQuery(
            query=f"{name} 最新研报 机构评级 目标价 盈利预测",
            stock_code=code6, stock_name=name))
        content = (resp or {}).get('content', '') or ''
    except Exception as e:
        logger.warning(f'[research] {code6} 研报搜索失败: {e}')
    return {"news": content, "data": None, "tag": "mx-report"}


# 数据源注册表（顺序执行；新增源只需实现函数并追加到此）
RESEARCH_SOURCES = [_src_mx_news_data, _src_mx_research_report]


async def collect_research_for_stock(code6: str, name: str):
    """对单只股票跑全部已注册网上数据源，聚合并自动落库；返回 (news_content, data_tables)"""
    news_parts = []
    data_tables = None
    for src in RESEARCH_SOURCES:
        try:
            res = await src(code6, name)
        except Exception as e:
            logger.warning(f'[research] {code6} 数据源 {getattr(src, "__name__", src)} 失败: {e}')
            continue
        if res.get("news"):
            news_parts.append(res["news"])
        if res.get("data") and data_tables is None:
            data_tables = res["data"]
        # 源间轻微节流，避免对妙想猛打
        if RESEARCH_THROTTLE > 0:
            await asyncio.sleep(min(RESEARCH_THROTTLE, 0.5))
    news_content = "\n\n".join(p for p in news_parts if p)
    return news_content, data_tables


def _build_baseline(code6, name, news_content, data_tables) -> dict:
    """无 LLM 时，用妙想结构化内容构造基线分析（仍填补 ai_analysis_cache 空白）"""
    sections = []
    if news_content:
        sections.append({"title": "资讯/事件", "content": news_content})
    if data_tables:
        try:
            tables = data_tables if isinstance(data_tables, list) else json.loads(data_tables)
            rows = []
            for tb in (tables or [])[:3]:
                rows.append(str(tb)[:1000])
            if rows:
                sections.append({"title": "关键财务/数据", "content": "\n".join(rows)})
        except Exception:
            logger.debug("research: financial data section skip", exc_info=False)
    if not sections:
        return None
    return {
        "summary": f"{name}({code6}) 盘后研究基线：基于妙想资讯+数据，未做 LLM 综合。",
        "sections": sections,
        "generated_by": "mx-search-baseline",
    }


def _extract_json(text):
    """从模型返回中稳健提取 JSON：兼容裸 JSON、```json 围栏、前后多余文本。"""
    if not isinstance(text, str):
        text = str(text)
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        return json.loads(text)
    except Exception:
        s, e = text.find("{"), text.rfind("}")
        if s != -1 and e != -1 and e > s:
            return json.loads(text[s:e + 1])
        raise


async def _call_llm(code6, name, news_content, data_tables) -> dict:
    """可选：调用配置的 LLM 生成综合分析 JSON。
    期望结构：{summary, bull_points:[], bear_points:[], catalysts:[], conclusion}
    兼容模型把 JSON 包在 ```json ``` 中、或返回非标准 JSON 的情况。
    """
    from api.watchlist._shared import _get_http_client

    tables_txt = ''
    if data_tables:
        try:
            tables = data_tables if isinstance(data_tables, list) else json.loads(data_tables)
            tables_txt = json.dumps(tables, ensure_ascii=False, default=str)[:4000]
        except Exception:
            tables_txt = str(data_tables)[:4000]

    user_prompt = (
        f"股票：{name}({code6})\n\n"
        f"【妙想资讯搜索结果】\n{news_content or '无'}\n\n"
        f"【妙想金融数据结果】\n{tables_txt or '无'}\n\n"
        "请基于以上信息，输出 JSON："
        "{\"summary\":\"一句话总结\",\"bull_points\":[利好点],\"bear_points\":[风险点],"
        "\"catalysts\":[近期催化事件],\"conclusion\":\"操作结论\"}"
    )

    client = _get_http_client()
    resp = await client.post(
        f"{AI_LLM_BASE_URL.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {AI_LLM_API_KEY}", "Content-Type": "application/json"},
        json={
            "model": AI_LLM_MODEL,
            "messages": [
                {"role": "system", "content": "你是资深 A 股基本面与事件驱动分析师，输出严格 JSON，不要额外文本。"},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "response_format": {"type": "json_object"},
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()["choices"][0]["message"]["content"]
    result = _extract_json(data)
    # 结构化兜底：确保关键字段存在
    result.setdefault("summary", f"{name}({code6}) LLM 综合分析")
    result.setdefault("bull_points", [])
    result.setdefault("bear_points", [])
    result.setdefault("catalysts", [])
    result.setdefault("conclusion", "")
    return result


async def synthesize_and_store(code6, name, news_content, data_tables):
    """生成 AI 综合分析并落库 ai_analysis_cache（含当日去重）"""
    from db.session import get_db_session
    from db.models import AIAnalysisCache

    # 当日去重：已写过则跳过，避免手动+定时重复写入
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with get_db_session() as db:
            existing = db.query(AIAnalysisCache).filter(
                AIAnalysisCache.stock_code == code6,
                AIAnalysisCache.created_at >= today_start,
            ).count()
            if existing > 0:
                logger.info(f'[research] {code6} 今日分析已存在，跳过')
                return
    except Exception:
        logger.debug('[research] dedup check failed', exc_info=True)

    analysis = None
    model = None
    if AI_LLM_API_KEY:
        model = AI_LLM_MODEL
        try:
            analysis = await _call_llm(code6, name, news_content, data_tables)
        except Exception as e:
            logger.warning(f'[research] LLM 合成失败，回退妙想基线: {e}')
            analysis = None
    if not analysis:
        model = 'mx-search-baseline'
        analysis = _build_baseline(code6, name, news_content, data_tables)
    if not analysis:
        return

    try:
        with get_db_session() as db:
            db.add(AIAnalysisCache(
                stock_code=code6,
                analysis_type='comprehensive',
                analysis_data=json.dumps(analysis, ensure_ascii=False, default=str),
                data_sources=json.dumps(
                    {'news': bool(news_content), 'data': bool(data_tables)},
                    ensure_ascii=False),
                model=model,
            ))
            db.commit()
        logger.info(f'[research] AI 分析已落库 {code6} (model={model})')
    except Exception as e:
        logger.warning(f'[research] 写 ai_analysis_cache 失败 {code6}: {e}')


async def run_research_for_stock(code6: str, name: str = ''):
    """单只股票研究采集（供手动触发 / API 调用）"""
    if not name:
        name = _lookup_name(code6)
    news_content, data_tables = await collect_research_for_stock(code6, name)
    await synthesize_and_store(code6, name, news_content, data_tables)
    return name


# 防重入锁：避免手动触发与定时任务、或多次定时任务重叠导致猛打妙想/卡死事件循环
_collect_lock = asyncio.Lock()


async def run_research_collection(today: str = None):
    """盘后研究采集主流程（供定时任务调用）
    带防重入锁 + 节流，避免对妙想猛打导致限流或共享 httpx 客户端挂死事件循环。
    """
    if _collect_lock.locked():
        logger.info('[research] 采集任务已在运行中，跳过本次触发')
        return 0
    async with _collect_lock:
        today = today or datetime.now().strftime('%Y-%m-%d')
        targets = get_research_targets(today)
        logger.info(f'[research] 目标池 {len(targets)} 只')
        logger.info(f'[research] LLM 模式: '
                    f'{"启用(" + AI_LLM_MODEL + ")" if AI_LLM_API_KEY else "未配置(使用 mx-search-baseline)"}')
        done = 0
        total = len(targets)
        for i, (code6, name, src) in enumerate(targets):
            try:
                news_content, data_tables = await collect_research_for_stock(code6, name)
                await synthesize_and_store(code6, name, news_content, data_tables)
                done += 1
            except Exception as e:
                logger.warning(f'[research] {code6} 采集异常: {e}')
            # 节流：每只之间间隔，给妙想喘息，也避免共享客户端连接耗尽
            if RESEARCH_THROTTLE > 0 and i < total - 1:
                await asyncio.sleep(RESEARCH_THROTTLE)
        logger.info(f'[research] 采集完成：{done}/{total}')
        return done
