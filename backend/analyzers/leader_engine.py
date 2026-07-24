from typing import Optional, Dict, Any
"""
龙头引擎（Level 3，完整生命周期驱动版）

职责：在可交易板块内，基于「实时计算」识别龙头、评分、选取主龙和候选，
并具备跨日记忆——跟踪主龙处于 蓄势→突破→主升→分歧→衰退 哪一阶段演进，
识别板块轮动、主龙走弱时触发衰退预警并排序接棒候选。

⚠️ 本引擎不再读取 LeaderLifecycle 预计算表（那是当日涨停股的静态标签，
   strength/stage/连板 写死且从未演进，无法真实反映龙头）。

真实数据来源：
- StockFeaturesDaily：个股每日真实特征（均线/RSI/量比/主力净流入/趋势一致性…）
- StockFlow：真实涨幅(price_chg)、真实主力净流入(main_force_inflow)、板块、名称
- StockDailyKline：真实连板天数（近 N 日连续涨停计数）
- sector_engine.get_sector_ranking：可交易板块（强势/轮动）
- LeaderTrack：跨日状态记忆（当前主龙 + 近 N 日阶段演进轨迹）

评分维度（0-10分），全部基于实时计算：
- 技术形态 technical       → 3分（破位→顶部 7 段）
- 主力资金 mainForce      → 2分
- 资金动能 momentum       → 2分
- 情绪温度 sentiment      → 1分
- 真实涨幅 change_rate    → 1分
- 真实连板 consecutive_days→ 1分
- 板块内排名 sector_rank  → 0.5分

主龙选取：score ≥ 7 的第一名（结合跨日状态与衰退预警）
候选龙：接棒排序前 3（score ≥ 4 且 phase 处于 突破/主升/rising）
切换规则：新龙头评分比当前高 1.5 分以上 + 涨幅更强，或当前走弱而新龙头处于上升期；
          或当前主龙进入衰退（phase=衰退 / phase_trend=falling 且评分回落）时触发接棒
"""
import json
from collections import defaultdict
from datetime import datetime, date, timedelta

from sqlalchemy import desc, func, between

from db.session import get_db_session
from db.models import (
    StockFeaturesDaily, StockFlow, SectorFlow, StockDailyKline, LeaderTrack,
)
from analyzers.sector_engine import get_sector_ranking
from analyzers.stock_scores import (
    calc_sentiment, calc_risk, calc_momentum, calc_main_force, calc_technical,
)


# ===== 工具函数 =====
def _clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


def _features_to_dict(f) -> dict:
    """把 StockFeaturesDaily ORM 对象转成 stock_scores 所需的 features dict（真实值）"""
    return {
        'rsi_14': f.rsi_14,
        'volume_ratio': f.volume_ratio,
        'close_vs_ma20': f.close_vs_ma20,
        'higher_high_flag': f.higher_high_flag,
        'higher_low_flag': f.higher_low_flag,
        'trend_consistency_score': f.trend_consistency_score,
        'ma20_slope': f.ma20_slope,
        'main_net_inflow_3d': f.main_net_inflow_3d,
        'flow_continuity': f.flow_continuity,
        'sector_strength': f.sector_strength,
        'noise_ratio': f.noise_ratio,
        'atr_14': f.atr_14,
    }


def _build_sector_trend(sf) -> dict:
    """把 SectorFlow 真实聚合数据转成 calc_* 所需的 sector_trend dict 形状"""
    if sf is None:
        return None
    net = float(sf.net_flow or 0)
    rise = float(sf.rise_ratio or 0)
    avg = float(sf.avg_chg or 0)
    return {
        'available': True,
        'latest_heat': _clamp(50 + avg * 3, 0, 100),
        'flow_direction': 'inflow' if net > 0 else ('outflow' if net < 0 else 'stable'),
        'total_net_flow': net,
        'rise_ratio': rise,
        'heat_trend': 'stable',
        'sector_strength': avg,
    }


def _compute_consecutive_limit_up(kmap: dict, ts_code: str, target_obj: date) -> int:
    """真实连板天数：从 StockDailyKline 近 N 日记录里，自 target_date 向前数连续涨停日数。

    涨停判定：pct_chg >= 9.5（主板 10% 阈值，留出误差）。
    """
    recs = sorted(kmap.get(ts_code, []), key=lambda x: x[0])
    count = 0
    for d, pct in reversed(recs):
        if d > target_obj:
            continue
        if pct >= 9.5:
            count += 1
        else:
            break
    return count


# ===== 技术形态映射（与前端 STAGE_COLORS 一致：破位/弱势/震荡/偏多/多头/突破/顶部） =====
def _technical_stage_from_features(cv: float, tc: float, hh: int, rsi: float) -> str:
    """基于真实特征合成当日技术形态（7 段）。"""
    if cv <= -0.08:
        return '破位'
    if cv <= -0.02:
        return '弱势'
    if cv < 0.03:
        return '震荡'
    if cv < 0.08:
        return '偏多'
    if cv < 0.15:
        return '多头'
    if hh == 1 or cv >= 0.15:
        return '突破'
    if rsi >= 80:
        return '顶部'
    return '多头'


# ===== 阶段演进（历史 N 日回溯） =====
def calc_lifecycle(stock_code: str, db, target_date: date, n: int = 12):
    """基于近 n 日真实特征(StockFeaturesDaily)回溯个股生命周期阶段与演进趋势。

    Args:
        stock_code: 6 位代码
        db: 数据库会话
        target_date: 目标日期
        n: 回溯交易日数

    Returns:
        dict: {
            'phase': '蓄势'|'突破'|'主升'|'分歧'|'衰退',
            'phase_trend': 'rising'|'flat'|'falling',
            'track': [ {date, technical_stage, score, close_vs_ma20, consecutive_days}, ... ],
            'technical_stage': 最新技术形态,
        }
    """
    end = target_date
    start = target_date - timedelta(days=n)
    feats = db.query(StockFeaturesDaily).filter(
        StockFeaturesDaily.stock_code == stock_code,
        StockFeaturesDaily.trade_date.between(start.strftime('%Y%m%d'), end.strftime('%Y%m%d')),
    ).order_by(StockFeaturesDaily.trade_date).all()

    if not feats:
        return {'phase': '蓄势', 'phase_trend': 'flat', 'track': [], 'technical_stage': '震荡'}

    track = []
    for f in feats:
        cv = float(f.close_vs_ma20 or 0)
        tc = float(f.trend_consistency_score or 0)
        hh = int(f.higher_high_flag or 0)
        rsi = float(f.rsi_14 or 50)
        # 技术位置分 0-100：close_vs_ma20 主导 + 趋势一致性 + 创新高
        pos_score = _clamp(50 + cv * 200, 0, 100)
        tech_score = _clamp(pos_score * 0.6 + tc * 100 * 0.4 + hh * 5, 0, 100)
        stage = _technical_stage_from_features(cv, tc, hh, rsi)
        track.append({
            'date': f.trade_date,
            'technical_stage': stage,
            'score': round(tech_score, 1),
            'close_vs_ma20': round(cv, 4),
            'consecutive_days': 0,  # 由调用方用当日真实连板填充
        })

    scores = [t['score'] for t in track]
    latest = track[-1]
    tc_latest = float(feats[-1].trend_consistency_score or 0)
    cv_latest = float(feats[-1].close_vs_ma20 or 0)
    rsi_latest = float(feats[-1].rsi_14 or 50)

    phase = _lifecycle_phase(latest['technical_stage'], scores, tc_latest, cv_latest, rsi_latest)
    phase_trend = _phase_trend(scores)

    return {
        'phase': phase,
        'phase_trend': phase_trend,
        'track': track,
        'technical_stage': latest['technical_stage'],
    }


def _lifecycle_phase(latest_stage: str, scores: list, tc_latest: float,
                    cv_latest: float, rsi_latest: float) -> str:
    """由最新技术形态 + 近 3 日评分斜率判定生命周期阶段。"""
    if len(scores) >= 2:
        slope = scores[-1] - scores[0]
    else:
        slope = 0

    # 衰退优先判定
    if latest_stage in ('破位', '弱势'):
        return '衰退'
    if slope < -5 and latest_stage in ('多头', '突破', '顶部', '偏多'):
        return '衰退'
    # 分歧：高位滞涨 / RSI 超买回落
    if latest_stage == '顶部' or (rsi_latest > 80 and slope < 0):
        return '分歧'
    # 主升：多头 + 趋势一致性强
    if latest_stage in ('多头', '突破') and tc_latest > 0.5:
        return '主升'
    # 突破：偏多/多头 且价格脱离均线或上行
    if latest_stage in ('偏多', '多头', '突破') and (cv_latest > 0.03 or slope > 0):
        return '突破'
    # 蓄势：弱势/震荡 且趋势未起
    if latest_stage in ('弱势', '震荡', '偏多') and tc_latest < 0.4:
        return '蓄势'
    return '蓄势' if latest_stage in ('弱势', '震荡') else '突破'


def _phase_trend(scores: list) -> str:
    """近 3 日 vs 前 3 日 技术位置分斜率。"""
    if len(scores) < 3:
        return 'flat'
    recent = scores[-3:]
    early = scores[-6:-3] if len(scores) >= 6 else scores[:1]
    delta = sum(recent) / len(recent) - sum(early) / len(early)
    if delta > 3:
        return 'rising'
    if delta < -3:
        return 'falling'
    return 'flat'


# ===== 跨日状态记忆 =====
def _read_current_leader_track(db) -> Optional[dict]:
    """读取当前主龙状态（is_active=True 的最近一条）。"""
    rec = db.query(LeaderTrack).filter(
        LeaderTrack.is_active == True
    ).order_by(LeaderTrack.last_date.desc()).first()
    if not rec:
        return None
    return {
        'ts_code': rec.ts_code,
        'name': rec.name,
        'sector': rec.sector,
        'enter_date': rec.enter_date.isoformat() if rec.enter_date else None,
        'current_phase': rec.current_phase,
        'phase_trend': rec.phase_trend,
        'track_json': rec.track_json,
        'consecutive_days_as_leader': rec.consecutive_days_as_leader,
        'last_date': rec.last_date.isoformat() if rec.last_date else None,
    }


def _last_track_score(cur_track: dict):
    """从历史轨迹取上一日 score（用于判断评分回落）。"""
    try:
        hist = json.loads(cur_track.get('track_json') or '[]')
        if hist:
            return float(hist[-1].get('score', 0))
    except Exception:
        pass
    return None


def _persist_leader_track(db, leader: dict, lc: dict, target_date: date, cur_track: Optional[dict]):
    """持久化当前主龙状态：仍在任则追加轨迹并延续连续天数；换龙则停旧立新。"""
    ts_code = leader['ts_code']
    point = {
        'date': target_date.isoformat(),
        'phase': (lc or {}).get('phase') or leader['stage'],
        'score': leader['score'],
        'technical_stage': leader['stage'],
        'consecutive_days': leader['consecutive_days'],
    }
    existing = db.query(LeaderTrack).filter(
        LeaderTrack.is_active == True,
        LeaderTrack.ts_code == ts_code,
    ).first()
    if existing:
        hist = json.loads(existing.track_json or '[]')
        hist.append(point)
        hist = hist[-20:]  # 保留最近 20 日
        existing.current_phase = point['phase']
        existing.phase_trend = (lc or {}).get('phase_trend') or 'flat'
        existing.track_json = json.dumps(hist, ensure_ascii=False)
        existing.consecutive_days_as_leader = existing.consecutive_days_as_leader + 1
        existing.last_date = target_date
        existing.sector = leader['sector']
        existing.name = leader['name']
    else:
        # 新主龙：停用所有旧 active
        db.query(LeaderTrack).filter(LeaderTrack.is_active == True).update({'is_active': False})
        db.add(LeaderTrack(
            ts_code=ts_code,
            name=leader['name'],
            sector=leader['sector'],
            enter_date=target_date,
            current_phase=point['phase'],
            phase_trend=(lc or {}).get('phase_trend') or 'flat',
            track_json=json.dumps([point], ensure_ascii=False),
            consecutive_days_as_leader=1,
            last_date=target_date,
            is_active=True,
        ))
    db.commit()


# ===== 板块轮动图谱 =====
def _build_sector_rotation(sector_ranking: dict, computed: list, cur_track: Optional[dict]) -> dict:
    cur_sector = (cur_track or {}).get('sector')
    by_sector = defaultdict(list)
    for c in computed[:20]:
        by_sector[c['sector'] or '未知'].append(c)
    sector_avg = {
        s: round(sum(x['score'] for x in v) / len(v), 2)
        for s, v in by_sector.items()
    }
    return {
        'current_leader_sector': cur_sector,
        'strong_sectors': [s['sector'] for s in sector_ranking.get('strong', [])],
        'rotation_sectors': [s['sector'] for s in sector_ranking.get('rotation', [])],
        'sector_avg_score': sector_avg,
    }


# ===== 主龙选取（结合跨日状态 + 衰退预警） =====
def _select_leader(computed: list, cur_track: Optional[dict], lifecycle_map: dict):
    """返回 (leader, decay_warning, old_leader)。"""
    top = computed[0] if computed else None
    if not top:
        return None, False, None

    cur_code = (cur_track or {}).get('ts_code')
    cur_in = next((c for c in computed if c['ts_code'] == cur_code), None)

    decay_warning = False
    if cur_track and cur_in:
        lc = lifecycle_map.get(cur_code, {})
        cur_score = cur_in['score']
        prev_score = _last_track_score(cur_track)
        # 衰退：phase=衰退，或 趋势拐头 且 评分较昨日回落
        if lc.get('phase') == '衰退' or (
            lc.get('phase_trend') == 'falling' and prev_score is not None
            and cur_score < prev_score - 0.3
        ):
            decay_warning = True
        switch, _ = should_switch(cur_in, top)
        if not decay_warning and not switch:
            return cur_in, False, None   # 维持当前主龙
        return top, decay_warning, cur_in

    # 无当前主龙：选评分最强者
    if top['score'] >= 7:
        return top, False, None
    return None, False, None


# ===== 评分 =====
def calc_leader_score(metrics: dict, sector_rank: int = 1) -> dict:
    """基于真实计算指标计算龙头评分（0-10）

    Args:
        metrics: {
            'technical': {stage,score} | None,
            'main_force': {stage,score} | None,
            'momentum': {stage,score} | None,
            'sentiment': {stage,score} | None,
            'risk': {stage,score} | None,
            'change_rate': float,
            'consecutive_days': int,
        }
        sector_rank: 该股票在板块内的排名（1=最强）

    Returns:
        dict: score, stage, strength, state, details
    """
    t = (metrics.get('technical') or {}).get('score', 50)
    mf = (metrics.get('main_force') or {}).get('score', 50)
    mo = (metrics.get('momentum') or {}).get('score', 50)
    se = (metrics.get('sentiment') or {}).get('score', 50)

    score = 0.0
    # 技术形态（权重最高）
    score += t / 100 * 3
    # 主力资金
    score += mf / 100 * 2
    # 资金动能
    score += mo / 100 * 2
    # 情绪温度
    score += se / 100 * 1

    # 真实涨幅
    chg = float(metrics.get('change_rate') or 0)
    if chg >= 9.5:
        score += 1
    elif chg >= 5:
        score += 0.7
    elif chg >= 1:
        score += 0.3

    # 真实连板
    days = int(metrics.get('consecutive_days') or 0)
    if days >= 4:
        score += 1
    elif days >= 2:
        score += 0.5

    # 板块内排名
    if sector_rank == 1:
        score += 0.5

    score = round(min(10, score), 1)

    # 阶段：优先用真实技术形态
    stage = (metrics.get('technical') or {}).get('stage') or '震荡'

    # 强度：真实各维加权（0-100），用于前端展示
    strength = round(t * 0.5 + mf * 0.3 + mo * 0.1 + se * 0.1, 1)

    # 状态判定
    if score >= 7:
        state = "LEADER"
    elif score >= 4:
        state = "CANDIDATE"
    elif score >= 2:
        state = "WATCH"
    else:
        state = "WEAK"

    return {
        'score': score,
        'stage': stage,
        'strength': strength,
        'state': state,
        'details': {
            'technical': round(t, 1),
            'mainForce': round(mf, 1),
            'momentum': round(mo, 1),
            'sentiment': round(se, 1),
            'change': round(chg, 2),
            'days': days,
            'rank': sector_rank,
        },
    }


def should_switch(current_leader: dict, new_leader: dict):
    """是否应该切换主龙（防乱换），基于真实技术阶段与评分"""
    if not current_leader:
        return True, '无当前主龙'

    diff = new_leader['score'] - current_leader['score']
    if diff > 1.5:
        if new_leader['change_rate'] > current_leader['change_rate']:
            return True, f'新龙头评分高{diff:.1f}分且涨幅更强'

    # 当前主龙走弱（破位/弱势），新龙头处于上升期（偏多/多头/突破/顶部）
    weak_stages = ('破位', '弱势')
    rising_stages = ('偏多', '多头', '突破', '顶部')
    if current_leader['stage'] in weak_stages and new_leader['stage'] in rising_stages:
        return True, '当前主龙走弱，新龙头处于上升期'

    return False, '维持当前主龙'


def run_leader_engine(target_date=None):
    """运行龙头引擎（完整生命周期驱动）

    流程：
    1. 获取可交易板块（sector_engine）
    2. 取当日真实特征(StockFeaturesDaily) + 真实资金(StockFlow)候选池（限制在可交易板块；若无则全量兜底）
    3. 批量取真实连板(StockDailyKline) + 板块趋势(SectorFlow)
    4. 对每只候选实时计算 6 维 + 涨幅 + 连板 → 龙头评分
    5. 板块内排名 → 总分排序
    6. 跨日生命周期跟踪：读当前主龙 → 对 top 候选+当前主龙回溯 N 日阶段演进
    7. 板块轮动图谱 → 主龙选取(结合衰退预警/接棒) → 持久化 LeaderTrack

    Returns:
        dict: leader, candidates, all_stocks, all_count, sector_filter, sector_rotation,
              decay_warning, successor_candidates, current_leader_track, date, message
    """
    with get_db_session() as db:
        # Step 1: 可交易板块
        sector_ranking = get_sector_ranking(target_date)
        tradable_sectors = set(
            [s['sector'] for s in sector_ranking.get('strong', []) + sector_ranking.get('rotation', [])]
        )

        if not tradable_sectors:
            return {
                'leader': None, 'candidates': [], 'all_stocks': [], 'all_count': 0,
                'sector_filter': sector_ranking, 'sector_rotation': {},
                'decay_warning': False, 'successor_candidates': [], 'current_leader_track': None,
                'date': None, 'message': '无可交易板块',
            }

        # Step 2: 确定日期（以 StockFeaturesDaily 最新交易日为准）
        if target_date is None:
            feat_date_str = db.query(func.max(StockFeaturesDaily.trade_date)).scalar()
            if not feat_date_str:
                return {
                    'leader': None, 'candidates': [], 'all_stocks': [], 'all_count': 0,
                    'sector_filter': sector_ranking, 'sector_rotation': {},
                    'decay_warning': False, 'successor_candidates': [], 'current_leader_track': None,
                    'date': None, 'message': '无个股特征数据',
                }
            target_date = datetime.strptime(feat_date_str, '%Y%m%d').date()

        date_str = target_date.strftime('%Y%m%d')   # 用于 StockFeaturesDaily(String YYYYMMDD)
        date_obj = target_date                       # 用于 Date 类型字段

        # Step 3: 候选池 = 当日有真实特征 + 真实资金的股票
        feats = db.query(StockFeaturesDaily).filter(
            StockFeaturesDaily.trade_date == date_str
        ).all()
        flows = db.query(StockFlow).filter(StockFlow.trade_date == date_obj).all()
        flow_map = {f.ts_code.split('.')[0]: f for f in flows}  # 6 位代码 -> flow

        # 限制在可交易板块；若过滤后为空，则全量兜底（保证页面有数据）
        candidates_raw = []
        for f in feats:
            flow = flow_map.get(f.stock_code)
            if not flow:
                continue
            if flow.sector and flow.sector in tradable_sectors:
                candidates_raw.append((f, flow))
        if not candidates_raw:
            for f in feats:
                flow = flow_map.get(f.stock_code)
                if flow:
                    candidates_raw.append((f, flow))

        if not candidates_raw:
            return {
                'leader': None, 'candidates': [], 'all_stocks': [], 'all_count': 0,
                'sector_filter': sector_ranking, 'sector_rotation': {},
                'decay_warning': False, 'successor_candidates': [], 'current_leader_track': None,
                'date': target_date.isoformat(), 'message': '当日无候选股（特征/资金数据缺失）',
            }

        # Step 4: 真实连板（批量取近 15 日 K 线）
        codes = [flow.ts_code for _, flow in candidates_raw]
        start_obj = target_date - timedelta(days=15)
        klines = db.query(StockDailyKline).filter(
            StockDailyKline.trade_date.between(start_obj, date_obj),
            StockDailyKline.ts_code.in_(codes),
        ).all()
        kmap = defaultdict(list)
        for k in klines:
            kmap[k.ts_code].append((k.trade_date, float(k.pct_chg or 0)))

        # 板块趋势 map（真实）
        sector_flows = db.query(SectorFlow).filter(SectorFlow.trade_date == date_obj).all()
        sector_trend_map = {sf.sector: _build_sector_trend(sf) for sf in sector_flows}
        sector_info_map = {s['sector']: s for s in sector_ranking.get('all', [])}

        # Step 5: 计算每只候选的真实指标
        computed = []
        for f, flow in candidates_raw:
            features = _features_to_dict(f)
            quote = {'changePct': float(flow.price_chg or 0)}
            sector_trend = sector_trend_map.get(flow.sector)

            technical = calc_technical(features)
            main_force = calc_main_force(quote, features, sector_trend)
            momentum = calc_momentum(sector_trend, features)
            sentiment = calc_sentiment(quote, sector_trend, features)
            risk = calc_risk(features, None, None)

            days = _compute_consecutive_limit_up(kmap, flow.ts_code, date_obj)

            metrics = {
                'technical': technical, 'main_force': main_force,
                'momentum': momentum, 'sentiment': sentiment, 'risk': risk,
                'change_rate': float(flow.price_chg or 0),
                'consecutive_days': days,
            }
            score_info = calc_leader_score(metrics, sector_rank=1)  # 暂定 1，稍后按板块内重排

            sec_info = sector_info_map.get(flow.sector or '')
            computed.append({
                'ts_code': flow.ts_code,
                'name': flow.name or f.stock_code,
                'sector': flow.sector or '',
                'score': score_info['score'],
                'stage': score_info['stage'],
                'strength': score_info['strength'],
                'state': score_info['state'],
                'consecutive_days': days,
                'change_rate': float(flow.price_chg or 0),
                'sector_score': sec_info.get('score') if sec_info else 0,
                'sector_state': sec_info.get('state') if sec_info else 'UNKNOWN',
                'sector_state_label': sec_info.get('state_label') if sec_info else '未知',
                'details': score_info['details'],
                'trade_date': target_date.isoformat(),
                '_intensity': score_info['details']['technical'] * 0.5
                              + score_info['details']['mainForce'] * 0.3
                              + score_info['details']['momentum'] * 0.1
                              + score_info['details']['sentiment'] * 0.1,
            })

        # Step 6: 按板块内排名重算 sector_rank 并微调（板块内按强度排序给 rank）
        by_sector = defaultdict(list)
        for c in computed:
            by_sector[c['sector'] or '未知'].append(c)
        for sec, sec_stocks in by_sector.items():
            sec_stocks.sort(key=lambda x: x['_intensity'], reverse=True)
            for rank, s in enumerate(sec_stocks, 1):
                if rank != 1:
                    s['score'] = round(max(0, s['score'] - 0.5), 1)
                s['details']['rank'] = rank

        # Step 7: 总分排序
        computed.sort(key=lambda x: x['score'], reverse=True)
        for c in computed:
            c.pop('_intensity', None)

        # Step 8: 跨日生命周期跟踪
        # 8.1 当前主龙状态
        cur_track = _read_current_leader_track(db)

        # 8.2 对 top 候选 + 当前主龙 回溯 N 日阶段演进
        watch_codes = {c['ts_code'].split('.')[0] for c in computed[:10]}
        if cur_track:
            watch_codes.add(cur_track['ts_code'].split('.')[0])
        lifecycle_map = {}
        for code in watch_codes:
            lc = calc_lifecycle(code, db, target_date, n=12)
            days = _compute_consecutive_limit_up(kmap, f'{code}.SZ', date_obj) \
                or _compute_consecutive_limit_up(kmap, f'{code}.SH', date_obj)
            for t in lc['track']:
                t['consecutive_days'] = days
            lifecycle_map[f'{code}.SZ'] = lc
            lifecycle_map[f'{code}.SH'] = lc

        # 8.3 给 computed 附加生命周期字段
        for c in computed:
            lc = lifecycle_map.get(c['ts_code'])
            if lc:
                c['phase'] = lc['phase']
                c['phase_trend'] = lc['phase_trend']
                c['track'] = lc['track']
            else:
                c['phase'] = '蓄势'
                c['phase_trend'] = 'flat'
                c['track'] = []

        # 8.4 板块轮动图谱
        sector_rotation = _build_sector_rotation(sector_ranking, computed, cur_track)

        # 8.5 主龙选取（结合跨日状态 + 衰退预警）
        leader, decay_warning, old_leader = _select_leader(computed, cur_track, lifecycle_map)

        # 8.6 接棒候选排序（phase 处于 突破/主升 且 rising，再按 score）
        successors = [c for c in computed if c['ts_code'] != (leader or {}).get('ts_code')]
        successors.sort(key=lambda x: (
            x.get('phase') in ('突破', '主升'),
            x.get('phase_trend') == 'rising',
            x['score'],
        ), reverse=True)
        successor_candidates = successors[:3]

        # 8.7 候选列表：无衰退预警时展示非主龙 top；有预警时展示接棒候选
        if leader:
            candidates_out = successor_candidates if decay_warning else [
                c for c in computed[1:] if c['score'] >= 4
            ][:3]
        else:
            candidates_out = computed[:5]

        # 8.8 持久化 LeaderTrack
        if leader:
            _persist_leader_track(db, leader, lifecycle_map.get(leader['ts_code']), target_date, cur_track)

        return {
            'leader': leader,
            'candidates': candidates_out,
            'all_stocks': computed[:20],
            'all_count': len(computed),
            'sector_filter': sector_ranking,
            'sector_rotation': sector_rotation,
            'decay_warning': decay_warning,
            'successor_candidates': successor_candidates,
            'current_leader_track': cur_track,
            'date': target_date.isoformat(),
            'message': 'ok' if leader else '无强主龙（score<7）',
        }
