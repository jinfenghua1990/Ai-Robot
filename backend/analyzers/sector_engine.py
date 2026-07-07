"""
板块趋势引擎（Level 1）
职责：板块评分、分类、过滤
核心思想：先选板块，再选龙头

评分维度（0-10分）：
- heat_score 板块热度（0-100）→ 2分
- net_flow 净流入资金 → 2分
- limit_up_count 涨停家数 → 2分
- avg_chg 平均涨幅（近5日趋势）→ 2分
- rise_ratio 上涨家数占比 → 1分
- leader_strength 龙头强度 → 1分

分类：
- STRONG_TREND（≥8分）：主升板块，可交易
- ROTATION（5-7分）：轮动板块，轻仓
- DOWN_TREND（<5分）：下降板块，禁止交易
"""
from datetime import date, timedelta
from sqlalchemy import desc, distinct
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow, StockFlow


def calc_sector_score(sector_data, history=None):
    """计算板块评分（0-10）

    Args:
        sector_data: 当天 SectorFlow 记录
        history: 近5天 SectorFlow 记录列表（用于趋势判断）

    Returns:
        dict: score, details(各维度得分), state
    """
    score = 0
    details = {}

    # 1. 板块热度（heat_score 0-100）
    heat = float(sector_data.heat_score or 0)
    if heat >= 60:
        score += 2
        details['heat'] = 2
    elif heat >= 40:
        score += 1
        details['heat'] = 1
    else:
        details['heat'] = 0

    # 2. 净流入资金（net_flow，单位元）
    net_flow = float(sector_data.net_flow or 0)
    if net_flow > 1000000:  # 净流入超100万
        score += 2
        details['flow'] = 2
    elif net_flow > 100000:  # 净流入超10万
        score += 1
        details['flow'] = 1
    else:
        details['flow'] = 0

    # 3. 涨停家数
    limit_up = int(sector_data.limit_up_count or 0)
    if limit_up >= 3:
        score += 2
        details['limit_up'] = 2
    elif limit_up >= 1:
        score += 1
        details['limit_up'] = 1
    else:
        details['limit_up'] = 0

    # 4. 平均涨幅趋势（用近5日 avg_chg 替代 ma20_trend）
    avg_chg = float(sector_data.avg_chg or 0)
    # 如果有历史数据，判断趋势
    if history and len(history) >= 3:
        recent_chgs = [float(h.avg_chg or 0) for h in history[:5]]
        trend_up = sum(1 for c in recent_chgs if c > 0) >= 3
        if avg_chg > 0 and trend_up:
            score += 2
            details['trend'] = 2
        elif avg_chg > 0:
            score += 1
            details['trend'] = 1
        else:
            details['trend'] = 0
    else:
        # 无历史数据时，当天涨幅>0即给分
        if avg_chg > 2:
            score += 2
            details['trend'] = 2
        elif avg_chg > 0:
            score += 1
            details['trend'] = 1
        else:
            details['trend'] = 0

    # 5. 上涨家数占比（rise_ratio）
    rise_ratio = float(sector_data.rise_ratio or 0)
    # rise_ratio 可能是百分比(0-100)或小数(0-1)，统一处理
    rise_pct = rise_ratio if rise_ratio > 1 else rise_ratio * 100
    if rise_pct > 50:
        score += 1
        details['breadth'] = 1
    else:
        details['breadth'] = 0

    # 6. 龙头强度
    leader_str = float(sector_data.leader_strength or 0)
    if leader_str >= 7:
        score += 1
        details['leader'] = 1
    else:
        details['leader'] = 0

    # 分类（根据实际数据分布调整阈值）
    if score >= 4:
        state = "STRONG_TREND"
        state_label = "主升"
    elif score >= 2:
        state = "ROTATION"
        state_label = "轮动"
    else:
        state = "DOWN_TREND"
        state_label = "下降"

    return {
        'score': score,
        'details': details,
        'state': state,
        'state_label': state_label,
        'heat': heat,
        'net_flow': net_flow,
        'limit_up_count': limit_up,
        'avg_chg': avg_chg,
        'rise_ratio': rise_ratio,
        'leader_stock': sector_data.leader_stock,
        'leader_strength': leader_str,
    }


def get_sector_ranking(target_date=None, top_n=30):
    """获取板块评分排名

    Args:
        target_date: 目标日期，默认最新交易日
        top_n: 返回前N个板块

    Returns:
        dict: strong/rotation/down 三个分类列表 + all 完整排名
    """
    with get_db_session() as db:
        if target_date is None:
            target_date = db.query(SectorFlow.trade_date).order_by(
                desc(SectorFlow.trade_date)
            ).first()[0]

        # 当天所有板块数据
        sectors_today = db.query(SectorFlow).filter(
            SectorFlow.trade_date == target_date
        ).all()

        if not sectors_today:
            return {'strong': [], 'rotation': [], 'down': [], 'all': [], 'date': None}

        # 获取近5天历史数据（用于趋势判断）
        five_days_ago = target_date - timedelta(days=7)
        history_all = db.query(SectorFlow).filter(
            SectorFlow.trade_date >= five_days_ago,
            SectorFlow.trade_date < target_date
        ).order_by(desc(SectorFlow.trade_date)).all()

        # 按板块分组历史
        history_by_sector = {}
        for h in history_all:
            if h.sector not in history_by_sector:
                history_by_sector[h.sector] = []
            history_by_sector[h.sector].append(h)

        # 计算每个板块评分
        ranked = []
        for s in sectors_today:
            history = history_by_sector.get(s.sector, [])
            result = calc_sector_score(s, history)
            result['sector'] = s.sector
            result['trade_date'] = target_date.isoformat()
            ranked.append(result)

        # 按评分排序
        ranked.sort(key=lambda x: x['score'], reverse=True)

        # 分类
        strong = [r for r in ranked if r['state'] == 'STRONG_TREND']
        rotation = [r for r in ranked if r['state'] == 'ROTATION']
        down = [r for r in ranked if r['state'] == 'DOWN_TREND']

        return {
            'strong': strong[:10],
            'rotation': rotation[:10],
            'down': down[:10],
            'all': ranked[:top_n],
            'date': target_date.isoformat(),
            'summary': {
                'total': len(ranked),
                'strong_count': len(strong),
                'rotation_count': len(rotation),
                'down_count': len(down),
            },
        }


def get_tradable_sectors(target_date=None):
    """获取可交易板块（STRONG + ROTATION）

    用于龙头引擎的输入过滤
    Returns: list of sector names
    """
    ranking = get_sector_ranking(target_date)
    tradable = [s['sector'] for s in ranking['strong'] + ranking['rotation']]
    return tradable


def build_sector_top_map(start_date, end_date, top_n=10,
                         mode='strong_rotation', valid_sectors=None):
    """预计算回测区间内每个交易日的 TopN 上升趋势板块集合（无未来函数）。

    用于 BS 回测的板块趋势过滤器：B 点信号触发时，要求该股所属板块在当日 TopN。

    Args:
        start_date/end_date: 'YYYY-MM-DD' 字符串或 date 对象
        top_n: 每日取前N个板块
        mode: 'strong_rotation'=STRONG+ROTATION按分排序; 'strong_only'=仅STRONG
        valid_sectors: 可选的白名单板块集合(set)，None时自动从StockFlow distinct获取

    Returns:
        {date_iso_str: set(sector_names)}，无数据的日期不在dict中
    """
    # 统一为 date 对象
    if isinstance(start_date, str):
        start_date = date.fromisoformat(start_date)
    if isinstance(end_date, str):
        end_date = date.fromisoformat(end_date)

    with get_db_session() as db:
        # 多取10天给 calc_sector_score 的 history 维度用
        lookback_start = start_date - timedelta(days=10)
        rows = db.query(SectorFlow).filter(
            SectorFlow.trade_date >= lookback_start,
            SectorFlow.trade_date <= end_date,
        ).order_by(SectorFlow.trade_date).all()

        if not rows:
            return {}

        # 白名单：真实有股票的板块（剔除"行业"后缀幽灵板块）
        if valid_sectors is None:
            stock_sectors = set(s[0] for s in db.query(distinct(StockFlow.sector))
                                .filter(StockFlow.sector.isnot(None),
                                        StockFlow.sector != '').all())
        else:
            stock_sectors = set(valid_sectors)

        # 按 date 组织当日板块；按 sector 组织历史（升序）
        by_date = {}
        hist_by_sector = {}
        for r in rows:
            d = r.trade_date
            by_date.setdefault(d, []).append(r)
            hist_by_sector.setdefault(r.sector, []).append(r)
        # 历史按日期升序，后续取最近5条用 [-5:] 后再反转降序
        for s in hist_by_sector:
            hist_by_sector[s].sort(key=lambda x: x.trade_date)

        result = {}
        for d, sectors_today in by_date.items():
            if d < start_date or d > end_date:
                continue
            ranked = []
            for s in sectors_today:
                if stock_sectors and s.sector not in stock_sectors:
                    continue  # 幽灵板块跳过
                # history: 严格取 trade_date < 当日 的最近5条（降序，最近在前）
                hist = [h for h in hist_by_sector.get(s.sector, []) if h.trade_date < d][-5:][::-1]
                sc = calc_sector_score(s, hist)
                if mode == 'strong_only' and sc['state'] != 'STRONG_TREND':
                    continue
                if mode == 'strong_rotation' and sc['state'] not in ('STRONG_TREND', 'ROTATION'):
                    continue
                ranked.append((sc['score'], s.sector))
            ranked.sort(reverse=True)
            top_set = set(sec for _, sec in ranked[:top_n])
            if top_set:
                result[d.isoformat()] = top_set
        return result
