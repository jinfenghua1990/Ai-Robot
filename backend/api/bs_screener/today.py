"""GET /api/bs-screener/today  +  GET /api/bs-screener/strategy-picks
读盘后定时任务落库的预计算结果
"""
import json
from fastapi import APIRouter, HTTPException, Query

from db.connection import get_db
from db.session import get_db_session
from db.models import BSDailyScan, LeaderLifecycle

router = APIRouter()

LEADER_STAGES = ['突破', '加速', '启动', '发酵']


@router.get("/api/bs-screener/today")
def bs_screener_today(backtest_id: int = Query(..., description="BSBacktestResult.id")):
    """读取今日预扫描结果（盘后定时任务已落库 bs_daily_scan 表）"""
    with get_db_session() as db:
        row = db.query(BSDailyScan).filter(
            BSDailyScan.backtest_id == backtest_id
        ).order_by(BSDailyScan.trade_date.desc()).first()
        if not row:
            raise HTTPException(status_code=404, detail='今日无预扫描结果，请点击开始扫描')
        signals = json.loads(row.signals_json or '[]')
        summary = json.loads(row.summary_json or '{}')
        return {
            'signals': signals,
            'summary': summary,
            'scanned': row.scanned,
            'trade_date': row.trade_date.strftime('%Y-%m-%d') if row.trade_date else '',
            'generated_at': row.generated_at.strftime('%Y-%m-%d %H:%M:%S') if row.generated_at else '',
            'precomputed': True,
        }


@router.get("/api/bs-screener/strategy-picks")
def strategy_picks_today():
    """返回当前保留策略（BS-科创-V7、BS-创业-V9）今日命中的个股清单。
    前端用于在 Watchlist / 模拟盘 / 自动化页面上标记"策略命中"徽章。
    """
    with get_db_session() as db:
        retained_names = ['BS-科创-V7', 'BS-创业-V9']
        rows = db.query(BSDailyScan).filter(
            BSDailyScan.strategy_name.in_(retained_names)
        ).order_by(BSDailyScan.trade_date.desc()).all()
        if not rows:
            return {
                'date': '',
                'picks': [],
                'code_to_strategies': {},
                'summary': {n: 0 for n in retained_names},
            }
        latest_date = max(r.trade_date for r in rows)
        today_rows = [r for r in rows if r.trade_date == latest_date]

        picks = []
        code_to_strategies = {}
        summary = {n: 0 for n in retained_names}
        for r in today_rows:
            signals = json.loads(r.signals_json or '[]')
            for s in signals:
                raw_code = s.get('secCode') or s.get('code') or ''
                code = raw_code.split('.')[0] if raw_code else ''
                if not code:
                    continue
                item = {
                    'code': code,
                    'name': s.get('secName') or s.get('name', ''),
                    'sector': s.get('sector', ''),
                    'strategy': r.strategy_name,
                    'dimension': r.dimension,
                    'signal': s.get('signal', 'B'),
                    'reasons': s.get('reasons', []) or [],
                    'score': s.get('score'),
                }
                picks.append(item)
                code_to_strategies.setdefault(code, [])
                if r.strategy_name not in code_to_strategies[code]:
                    code_to_strategies[code].append(r.strategy_name)
                summary[r.strategy_name] = summary.get(r.strategy_name, 0) + 1

        if latest_date:
            # 强势阶段标记为"游资龙头"，所有阶段都返回供前端显示
            leader_rows = db.query(LeaderLifecycle).filter(
                LeaderLifecycle.trade_date == latest_date,
            ).all()
            for lr in leader_rows:
                code = lr.ts_code.split('.')[0] if lr.ts_code else ''
                if not code:
                    continue
                stage = lr.stage or ''
                is_strong = stage in LEADER_STAGES
                # 强势阶段用"游资龙头"标签，其他阶段用"阶段:XXX"标签
                tag = '游资龙头' if is_strong else f'游资阶段:{stage}'
                if code not in code_to_strategies:
                    code_to_strategies[code] = []
                    picks.append({
                        'code': code,
                        'name': lr.name or '',
                        'sector': lr.sector or '',
                        'strategy': tag,
                        'dimension': 'leader',
                        'signal': 'L',
                        'reasons': [f'龙头阶段:{stage}'],
                        'score': float(lr.strength) if lr.strength else None,
                    })
                if tag not in code_to_strategies[code]:
                    code_to_strategies[code].append(tag)
                summary[tag] = summary.get(tag, 0) + 1

        return {
            'date': latest_date.strftime('%Y-%m-%d') if hasattr(latest_date, 'strftime') else str(latest_date),
            'picks': picks,
            'code_to_strategies': code_to_strategies,
            'summary': summary,
        }
