"""
龙头引擎（Level 2）
职责：在可交易板块内，识别龙头、评分、选取主龙和候选

只在 sector_engine 输出的 STRONG_TREND + ROTATION 板块中运行

评分维度（0-10分）：
- change_rate 涨幅 → 3分
- consecutive_days 连板天数 → 2分
- strength 强度 → 2分
- stage 生命周期阶段 → 2分
- sector_rank 板块内排名 → 1分

主龙选取：score ≥ 7 的第一名
候选龙：主龙之后的2-3名（score ≥ 5）
切换规则：新龙头评分比当前高1.5分以上 + 量比>1.2
"""
from sqlalchemy import desc
from db.connection import get_db
from db.session import get_db_session
from db.models import LeaderLifecycle
from analyzers.sector_engine import get_sector_ranking


def calc_leader_score(stock, sector_rank=1):
    """计算龙头评分（0-10）

    Args:
        stock: LeaderLifecycle 记录
        sector_rank: 该股票在板块内的排名（1=最强）

    Returns:
        dict: score, details, state
    """
    score = 0
    details = {}

    # 1. 涨幅
    change = float(stock.change_rate or 0)
    if change > 8:
        score += 3
        details['change'] = 3
    elif change > 5:
        score += 2
        details['change'] = 2
    elif change > 1:
        score += 1
        details['change'] = 1
    else:
        details['change'] = 0

    # 2. 连板天数
    days = int(stock.consecutive_days or 1)
    if days >= 4:
        score += 2
        details['days'] = 2
    elif days >= 2:
        score += 1
        details['days'] = 1
    else:
        details['days'] = 0

    # 3. 强度
    strength = float(stock.strength or 0)
    if strength >= 7:
        score += 2
        details['strength'] = 2
    elif strength >= 5:
        score += 1
        details['strength'] = 1
    else:
        details['strength'] = 0

    # 4. 趋势阶段（兼容新旧命名）
    stage = stock.stage or ''
    if stage in ('主升', '加速', '发酵'):  # 加速=旧"发酵"
        score += 2
        details['stage'] = 2
    elif stage in ('突破', '启动'):  # 突破=旧"启动"
        score += 1
        details['stage'] = 1
    else:
        details['stage'] = 0

    # 5. 板块内排名
    if sector_rank == 1:
        score += 1
        details['rank'] = 1
    else:
        details['rank'] = 0

    # 状态判定（根据实际数据分布调整阈值）
    if score >= 5:
        state = "LEADER"       # 主龙
    elif score >= 3:
        state = "CANDIDATE"    # 候选
    elif score >= 2:
        state = "WATCH"        # 观察
    else:
        state = "WEAK"         # 弱势

    return {
        'score': score,
        'details': details,
        'state': state,
        'change_rate': change,
        'consecutive_days': days,
        'strength': strength,
        'stage': stage,
        'sector_rank': sector_rank,
    }


def should_switch(current_leader, new_leader):
    """是否应该切换主龙（防乱换）

    Args:
        current_leader: 当前主龙数据
        new_leader: 新候选主龙数据

    Returns:
        tuple: (是否切换, 原因)
    """
    if not current_leader:
        return True, '无当前主龙'

    diff = new_leader['score'] - current_leader['score']
    if diff > 1.5:
        # 新龙头明显更强
        if new_leader['change_rate'] > current_leader['change_rate']:
            return True, f'新龙头评分高{diff:.1f}分且涨幅更强'

    # 当前主龙衰退（阶段变为衰退/分歧），考虑切换（兼容新旧命名）
    if current_leader['stage'] in ('衰退', '退潮', '分歧') and new_leader['stage'] in ('主升', '加速', '发酵', '突破', '启动'):
        return True, '当前主龙衰退，新龙头处于上升期'

    return False, '维持当前主龙'


def run_leader_engine(target_date=None):
    """运行龙头引擎

    流程：
    1. 获取可交易板块（来自板块引擎）
    2. 在可交易板块中获取所有龙头候选
    3. 按板块分组，计算板块内排名
    4. 计算龙头评分
    5. 选取主龙 + 候选

    Returns:
        dict: leader(主龙), candidates(候选), all_stocks(所有), sector_filter
    """
    with get_db_session() as db:
        # Step 1: 获取可交易板块
        sector_ranking = get_sector_ranking(target_date)
        tradable_sectors = set(
            [s['sector'] for s in sector_ranking['strong'] + sector_ranking['rotation']]
        )

        if not tradable_sectors:
            return {
                'leader': None,
                'candidates': [],
                'all_stocks': [],
                'sector_filter': sector_ranking,
                'message': '无可交易板块',
            }

        # Step 2: 确定日期
        if target_date is None:
            target_date = db.query(LeaderLifecycle.trade_date).order_by(
                desc(LeaderLifecycle.trade_date)
            ).first()[0]

        # Step 3: 获取可交易板块内的所有龙头候选
        stocks = db.query(LeaderLifecycle).filter(
            LeaderLifecycle.trade_date == target_date,
            LeaderLifecycle.sector.in_(tradable_sectors),
        ).order_by(desc(LeaderLifecycle.strength)).all()

        # 回退：若板块名不匹配（两套分类系统）或 sector 大量为空，按 strength 全量取
        if not stocks:
            stocks = db.query(LeaderLifecycle).filter(
                LeaderLifecycle.trade_date == target_date,
            ).order_by(desc(LeaderLifecycle.strength)).limit(100).all()

        if not stocks:
            return {
                'leader': None,
                'candidates': [],
                'all_stocks': [],
                'sector_filter': sector_ranking,
                'message': '当日无龙头候选数据',
                'date': target_date.isoformat(),
            }

        # Step 4: 按板块分组，计算板块内排名
        by_sector = {}
        for s in stocks:
            sec = s.sector or '未知'
            if sec not in by_sector:
                by_sector[sec] = []
            by_sector[sec].append(s)

        # 每个板块内按 strength 排序，计算排名
        all_scored = []
        for sec, sec_stocks in by_sector.items():
            sec_stocks.sort(key=lambda x: float(x.strength or 0), reverse=True)
            for rank, s in enumerate(sec_stocks, 1):
                result = calc_leader_score(s, rank)
                result['ts_code'] = s.ts_code
                result['name'] = s.name
                result['sector'] = sec
                result['trade_date'] = target_date.isoformat()
                # 找板块评分
                sec_info = next((x for x in sector_ranking['all'] if x['sector'] == sec), None)
                result['sector_score'] = sec_info['score'] if sec_info else 0
                result['sector_state'] = sec_info['state'] if sec_info else 'UNKNOWN'
                result['sector_state_label'] = sec_info['state_label'] if sec_info else '未知'
                all_scored.append(result)

        # Step 5: 按评分排序
        all_scored.sort(key=lambda x: x['score'], reverse=True)

        # Step 6: 选取主龙 + 候选
        leader = None
        candidates = []

        if all_scored and all_scored[0]['score'] >= 5:
            leader = all_scored[0]
            # 候选：主龙之后 score≥3 的，最多3只
            for s in all_scored[1:]:
                if s['score'] >= 3 and len(candidates) < 3:
                    candidates.append(s)
        else:
            # 没有强主龙，取前5作为候选
            candidates = all_scored[:5]

        return {
            'leader': leader,
            'candidates': candidates,
            'all_stocks': all_scored[:20],  # 热度池前20
            'all_count': len(all_scored),
            'sector_filter': sector_ranking,
            'date': target_date.isoformat(),
            'message': 'ok' if leader else '无强主龙（score<7）',
        }
