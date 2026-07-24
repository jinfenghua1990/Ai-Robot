"""
🎯 多策略共振 API
- GET /api/strategy-resonance  聚合当日所有策略命中，按共振数排序

共振 = 同一只股票被多个策略同时命中，不同维度共振意味着更强信号。

V4.0 子共振：liangjia_report 内部 5 种形态拆分为独立虚拟策略维度参与共振计数
  - pullback(回踩) / breakout(突破) / trend(趋势) → 各算 1 次共振
  - repair(修复) → 算 1 次但标注低权重
  - weak(偏弱) → 不参与共振
"""
from datetime import datetime, date
from collections import defaultdict
from typing import Optional
import json

from fastapi import APIRouter, Query
from sqlalchemy import desc, func

from db.session import get_db_session
from db.models import StrategyResult, StockDailyKline
from services.strategy_runner import STRATEGIES, get_strategy_meta
from api.validators import validate_date
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# 朱雀 V3.0 形态 → 虚拟策略 key & icon 映射
_V4_PATTERN_META = {
    'pullback':  {'key': 'v4_pullback',  'name': '朱雀V3.0回踩',  'icon': '📉'},
    'breakout':  {'key': 'v4_breakout',  'name': '朱雀V3.0突破',  'icon': '🚀'},
    'trend':     {'key': 'v4_trend',     'name': '朱雀V3.0趋势',  'icon': '📈'},
    'repair':    {'key': 'v4_repair',    'name': '朱雀V3.0修复',  'icon': '🔧'},
    # 'weak' 不映射 → 跳过不参与共振
}


@router.get("/api/strategy-resonance")
def get_strategy_resonance(
    date: str = Query(None, description="YYYY-MM-DD，默认今天"),
    min_count: int = Query(2, description="最小共振数过滤，默认2"),
):
    """返回当日被多个策略同时命中的股票，按共振数降序排序
    V4.0 的 pullback/breakout/trend/repair 形态各算一个独立共振维度。
    """
    trade_date_str = validate_date(date)

    with get_db_session() as db:
        rows = db.query(StrategyResult).filter(
            StrategyResult.trade_date == trade_date_str
        ).order_by(desc(StrategyResult.score)).all()

        if not rows:
            return {
                'trade_date': trade_date_str,
                'total_stocks': 0,
                'total_hits': 0,
                'strategy_meta': _build_strategy_meta(),
                'stocks': [],
            }

        # 按 ts_code 分组，V4.0 按形态展开为独立虚拟策略
        grouped = defaultdict(lambda: {'name': '', 'sector': '', 'strategies': [], 'total_score': 0})

        for r in rows:
            key = r.ts_code

            # 跳过风险退出策略（卖出信号，不参与共振维度计数）
            if r.strategy_key == 'risk_exit':
                continue

            # V4.0 子共振：按形态拆成虚拟策略维度
            if r.strategy_key == 'liangjia_report':
                pattern = _extract_v4_pattern(r)
                if pattern is None:
                    continue  # 无法识别形态 → 跳过
                if pattern == 'weak':
                    continue  # 结构偏弱 → 不参与共振

                pmeta = _V4_PATTERN_META.get(pattern, {})
                if not pmeta:
                    continue

                # 仅在首次访问时设置 name/sector，避免同一 ts_code 多策略命中时重复覆盖
                if not grouped[key]['name']:
                    grouped[key]['name'] = r.name or ''
                if not grouped[key]['sector']:
                    grouped[key]['sector'] = r.sector or ''
                grouped[key]['strategies'].append({
                    'strategy_key': pmeta['key'],
                    'strategy_name': pmeta['name'],
                    'icon': pmeta['icon'],
                    'score': float(r.score) if r.score else 0,
                    'parent_strategy': 'liangjia_report',
                })
                grouped[key]['total_score'] += float(r.score) if r.score else 0
                continue

            # 非 V4.0 策略：照常处理
            meta = get_strategy_meta(r.strategy_key) or {'icon': '📌'}
            score = float(r.score) if r.score else 0
            # 仅在首次访问时设置 name/sector，避免同一 ts_code 多策略命中时重复覆盖
            if not grouped[key]['name']:
                grouped[key]['name'] = r.name or ''
            if not grouped[key]['sector']:
                grouped[key]['sector'] = r.sector or ''
            grouped[key]['strategies'].append({
                'strategy_key': r.strategy_key,
                'strategy_name': r.strategy_name or meta.get('name', r.strategy_key),
                'icon': meta.get('icon', '📌'),
                'score': score,
            })
            grouped[key]['total_score'] += score

        # 构建股票列表并过滤
        stocks = []
        for ts_code, info in grouped.items():
            resonance_count = len(info['strategies'])
            if resonance_count < min_count:
                continue
            stocks.append({
                'ts_code': ts_code,
                'secCode': ts_code.split('.')[0] if '.' in ts_code else ts_code,
                'name': info['name'],
                'sector': info['sector'],
                'resonance_count': resonance_count,
                'total_score': round(info['total_score'], 2),
                'strategies': info['strategies'],
            })

        # ── 价格数据：批量查询最新 K 线和 20 日涨幅 ──
        if stocks:
            ts_codes = [s['ts_code'] for s in stocks]
            td = datetime.strptime(trade_date_str, '%Y-%m-%d').date() \
                if isinstance(trade_date_str, str) else trade_date_str

            # 最新 K 线（单条分组取最大 trade_date）
            latest_subq = db.query(
                StockDailyKline.ts_code,
                func.max(StockDailyKline.trade_date).label('max_date')
            ).filter(
                StockDailyKline.ts_code.in_(ts_codes),
                StockDailyKline.trade_date <= td
            ).group_by(StockDailyKline.ts_code).subquery()

            latest_rows = db.query(StockDailyKline).join(
                latest_subq,
                (StockDailyKline.ts_code == latest_subq.c.ts_code) &
                (StockDailyKline.trade_date == latest_subq.c.max_date)
            ).all()

            kline_map = {k.ts_code: k for k in latest_rows}

            # 20 个交易日前日期
            recent_dates = db.query(StockDailyKline.trade_date).filter(
                StockDailyKline.trade_date <= td
            ).distinct().order_by(StockDailyKline.trade_date.desc()).limit(20).all()

            date_20d_ago = recent_dates[-1][0] if recent_dates else None

            # 20 日前 K 线（批量）
            kline_map_20d = {}
            if date_20d_ago:
                rows_20d = db.query(StockDailyKline).filter(
                    StockDailyKline.ts_code.in_(ts_codes),
                    StockDailyKline.trade_date == date_20d_ago
                ).all()
                kline_map_20d = {k.ts_code: k for k in rows_20d}

            # 回填价格字段
            for s in stocks:
                kl = kline_map.get(s['ts_code'])
                s['latest_price'] = float(kl.close) if kl and kl.close is not None else None
                s['pct_chg'] = float(kl.pct_chg) if kl and kl.pct_chg is not None else None

                kl20 = kline_map_20d.get(s['ts_code'])
                if kl and kl.close is not None and kl20 and kl20.close is not None:
                    s['return_20d'] = round((float(kl.close) / float(kl20.close) - 1) * 100, 2)
                else:
                    s['return_20d'] = None

        # ── sector 兜底：当日 StockFlow 缺失时，从历史 StockFlow 找最近一条非空 sector ──
        empty_sector_codes = [s['ts_code'] for s in stocks if not s.get('sector')]
        if empty_sector_codes:
            # 用 DISTINCT ON 取每只股票最近一条非空 sector（PostgreSQL 语法）
            from sqlalchemy import text
            sector_lookup_sql = text("""
                SELECT DISTINCT ON (ts_code) ts_code, sector
                FROM stock_flow
                WHERE ts_code = ANY(:codes)
                  AND sector IS NOT NULL
                  AND sector != ''
                ORDER BY ts_code, trade_date DESC
            """)
            rows = db.execute(sector_lookup_sql, {'codes': empty_sector_codes}).fetchall()
            sector_fallback = {r.ts_code: r.sector for r in rows}
            filled = 0
            for s in stocks:
                if not s.get('sector') and s['ts_code'] in sector_fallback:
                    s['sector'] = sector_fallback[s['ts_code']]
                    filled += 1
            if filled:
                logger.info(f'[strategy_resonance] sector 兜底：{filled}/{len(empty_sector_codes)} 只股票从历史数据回填')

        # 按共振数降序 → 总分降序
        stocks.sort(key=lambda x: (x['resonance_count'], x['total_score']), reverse=True)

        return {
            'trade_date': trade_date_str,
            'total_stocks': len(stocks),
            'total_hits': sum(s['resonance_count'] for s in stocks),  # 实际共振维度数
            'strategy_meta': _build_strategy_meta(),
            'stocks': stocks,
        }


def _extract_v4_pattern(row) -> Optional[str]:
    """从 V4.0 的 detail_json 中提取 pattern 字段"""
    ts_code = getattr(row, 'ts_code', '?')
    try:
        if row.detail_json:
            detail = json.loads(row.detail_json) if isinstance(row.detail_json, str) else row.detail_json
            return detail.get('pattern')
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning("[strategy_resonance] extract v4 pattern from detail_json failed ts_code=%s: %s", ts_code, e)
    # 回退：从 scores_json 里找（旧版本可能存这里）
    try:
        if row.scores_json:
            scores = json.loads(row.scores_json) if isinstance(row.scores_json, str) else row.scores_json
            return scores.get('pattern')
    except (json.JSONDecodeError, TypeError, AttributeError) as e:
        logger.warning("[strategy_resonance] extract v4 pattern from scores_json failed ts_code=%s: %s", ts_code, e)
    return None


def _build_strategy_meta():
    """构建策略元数据图例（含 V4.0 子形态，排除 risk_exit）"""
    meta = [
        {'key': s['key'], 'name': s['name'], 'icon': s.get('icon', '📌')}
        for s in STRATEGIES if s['key'] != 'risk_exit'
    ]
    # 追加 V4.0 子维度
    for pm in _V4_PATTERN_META.values():
        meta.append({'key': pm['key'], 'name': pm['name'], 'icon': pm['icon']})
    return meta
