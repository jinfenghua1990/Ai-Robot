"""研报中心 API（PG 支撑版本）

端点契约与旧 JSON 文件版保持一致，前端无需改动：
  POST /request                  提交分析请求（入队 pending，consumer 自动消费）
  GET  /requests                 列出请求（可按 status 过滤）
  GET  /result/{id}              获取报告（解析 report_json）
  GET  /results                  列出已完成报告
  GET  /notifications            通知列表 + 未读数
  POST /notifications/read/{id}  标记已读
  GET  /status/{id}              查询请求状态
  POST /generate-recap          生成盘后复盘（sina 指数，落 PG）
  GET  /recap                    获取最新复盘
  POST /generate-recaps-batch   批量补最近5个交易日复盘
"""
import json
import os
import uuid
from datetime import datetime, timedelta

from fastapi import APIRouter, Query, Body
from sqlalchemy import select, desc

from db.connection import SessionLocal
from db.models import AnalysisRequest, AnalysisReport, Notification

router = APIRouter(prefix="/api/analysis", tags=["analysis"])


# ---------- 请求入队 ----------

@router.post("/request")
def create_request(
    stock_code: str = Body(...),
    stock_name: str = Body(''),
    source: str = Body('tdx', description="tdx/ifind"),
):
    """提交个股分析请求（入队 pending，由 analysis_consumer 自动消费生成）"""
    rid = uuid.uuid4().hex[:12]
    now = datetime.now()
    req = AnalysisRequest(
        id=rid,
        stock_code=stock_code.strip(),
        stock_name=stock_name or stock_code,
        source=source,
        status='pending',
        created_at=now,
        updated_at=now,
    )
    with SessionLocal() as db:
        db.add(req)
        db.commit()
    return {'ok': True, 'request_id': rid, 'status': 'pending'}


@router.get("/requests")
def list_requests(status: str = Query('', description="pending/completed/failed/all")):
    """列出分析请求"""
    with SessionLocal() as db:
        q = select(AnalysisRequest)
        if status and status != 'all':
            q = q.where(AnalysisRequest.status == status)
        q = q.order_by(desc(AnalysisRequest.created_at))
        items = db.execute(q).scalars().all()
        data = [{
            'id': r.id, 'stock_code': r.stock_code, 'stock_name': r.stock_name,
            'source': r.source, 'status': r.status, 'error': r.error,
            'created_at': r.created_at.isoformat() if r.created_at else '',
            'updated_at': r.updated_at.isoformat() if r.updated_at else '',
        } for r in items]
    return {'ok': True, 'requests': data, 'count': len(data)}


@router.get("/result/{request_id}")
def get_result(request_id: str):
    """获取分析结果（解析 report_json）"""
    with SessionLocal() as db:
        rep = db.get(AnalysisReport, request_id)
        if not rep:
            return {'ok': False, 'error': 'not_found'}
        data = json.loads(rep.report_json)
    return {'ok': True, 'result': data}


@router.get("/results")
def list_results(limit: int = Query(50), source: str = Query('')):
    """列出所有已完成的报告"""
    with SessionLocal() as db:
        q = select(AnalysisReport)
        if source:
            q = q.where(AnalysisReport.source == source)
        q = q.order_by(desc(AnalysisReport.created_at)).limit(limit)
        items = db.execute(q).scalars().all()
        data = [json.loads(r.report_json) for r in items]
    return {'ok': True, 'results': data, 'count': len(data)}


@router.get("/notifications")
def get_notifications():
    """获取通知列表 + 未读数"""
    with SessionLocal() as db:
        items = db.execute(
            select(Notification).order_by(desc(Notification.created_at)).limit(20)
        ).scalars().all()
        data = [{
            'id': n.id, 'source': n.source, 'stock_code': n.stock_code,
            'stock_name': n.stock_name, 'title': n.title, 'read': n.read,
            'created_at': n.created_at.isoformat() if n.created_at else '',
        } for n in items]
        unread = sum(1 for n in items if not n.read)
    return {'ok': True, 'notifications': data, 'unread_count': unread}


@router.post("/notifications/read/{notif_id}")
def mark_notification_read(notif_id: str):
    """标记通知已读"""
    with SessionLocal() as db:
        n = db.get(Notification, notif_id)
        if n:
            n.read = True
            db.commit()
    return {'ok': True}


@router.get("/status/{request_id}")
def get_request_status(request_id: str):
    """查询请求状态"""
    with SessionLocal() as db:
        req = db.get(AnalysisRequest, request_id)
        if not req:
            return {'ok': False, 'error': 'not_found'}
        has_result = db.get(AnalysisReport, request_id) is not None
    return {
        'ok': True,
        'request': {
            'id': req.id, 'stock_code': req.stock_code, 'stock_name': req.stock_name,
            'source': req.source, 'status': req.status, 'error': req.error,
            'created_at': req.created_at.isoformat() if req.created_at else '',
            'updated_at': req.updated_at.isoformat() if req.updated_at else '',
        },
        'has_result': has_result,
    }


# ---------- 盘后复盘（sina 指数）----------

def recap_exists(date_str: str) -> bool:
    rid = f"recap_{date_str}"
    with SessionLocal() as db:
        return db.get(AnalysisReport, rid) is not None


def build_and_persist_recap(date_str: str, now: datetime):
    """采集 sina 指数并生成复盘报告落 PG（幂等：今日已存在且含指数数据则跳过）。返回 (rid, created)。"""
    rid = f"recap_{date_str}"
    # 已存在且已有指数数据则跳过；占位（空指数）则覆盖重生成
    with SessionLocal() as db:
        rep = db.get(AnalysisReport, rid)
        if rep:
            try:
                d = json.loads(rep.report_json)
                if d.get("indices"):
                    return rid, False
            except Exception:
                logger.debug("report_json parse failed", exc_info=False)
    indices_data = _collect_indices()
    recap = {
        'id': rid, 'stock_code': 'MARKET', 'stock_name': 'A股市场',
        'source': 'recap', 'created_at': now.isoformat(),
        'report_type': '盘后复盘报告', 'date': date_str,
        'indices': indices_data,
        'summary': {
            'rating': '中性', 'confidence': '高',
            'key_points': _recap_points(indices_data),
        },
        'disclaimer': '盘后复盘报告基于免费公开数据生成，仅供参考，不构成投资建议',
    }
    _persist_report(rid, 'MARKET', 'A股市场', 'recap', recap)
    return rid, True


@router.post("/generate-recap")
def generate_market_recap():
    """盘后复盘：采集当日市场数据生成复盘报告（落 PG）"""
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    rid, created = build_and_persist_recap(date_str, now)
    return {'ok': True, 'request_id': rid, 'status': 'already_exists' if not created else 'created'}


@router.get("/recap")
def get_latest_recap():
    """获取最新复盘报告"""
    with SessionLocal() as db:
        rep = db.execute(
            select(AnalysisReport).where(AnalysisReport.source == 'recap')
            .order_by(desc(AnalysisReport.created_at)).limit(1)
        ).scalars().first()
        if not rep:
            return {'ok': True, 'has_recap': False, 'recap': None}
        recap = json.loads(rep.report_json)
    return {'ok': True, 'has_recap': True, 'recap': recap}


@router.post("/generate-recaps-batch")
def batch_generate_recaps():
    """批量生成最近5个工作日复盘（占位，落 PG）"""
    results = []
    now = datetime.now()
    for i in range(5):
        d = now - timedelta(days=i)
        if d.weekday() >= 5:
            continue
        date_str = d.strftime('%Y-%m-%d')
        rid = f'recap_{date_str}'
        with SessionLocal() as db:
            if db.get(AnalysisReport, rid):
                continue
        recap = {
            'id': rid, 'stock_code': 'MARKET', 'stock_name': 'A股市场',
            'source': 'recap', 'created_at': d.isoformat(),
            'report_type': '盘后复盘报告', 'date': date_str, 'indices': {},
            'summary': {'rating': '中性', 'confidence': '低', 'key_points': [f'{date_str} 市场复盘报告（盘后数据）']},
            'disclaimer': '仅供参考，不构成投资建议',
        }
        _persist_report(rid, 'MARKET', 'A股市场', 'recap', recap)
        results.append(date_str)
    return {'ok': True, 'generated': results}


# ---------- 内部辅助 ----------

def _persist_report(rid, stock_code, stock_name, source, report_dict):
    """写 AnalysisReport + AnalysisRequest(completed) + Notification 到 PG。"""
    report_dict.setdefault('id', rid)
    rep = AnalysisReport(
        id=rid, stock_code=stock_code, stock_name=stock_name, source=source,
        report_type=report_dict.get('report_type', ''),
        rating=report_dict.get('summary', {}).get('rating', ''),
        target_price=str(report_dict.get('summary', {}).get('target_price', '')),
        confidence=report_dict.get('summary', {}).get('confidence', ''),
        report_json=json.dumps(report_dict, ensure_ascii=False),
        created_at=datetime.now(),
    )
    req = AnalysisRequest(
        id=rid, stock_code=stock_code, stock_name=stock_name, source=source,
        status='completed', created_at=datetime.now(), updated_at=datetime.now(),
    )
    notif = Notification(
        id=f'notif_{rid}', source=source, stock_code=stock_code, stock_name=stock_name,
        title=f'{date_str_title(report_dict)} 复盘报告' if source == 'recap' else f'{stock_name}({stock_code}) 个股分析报告',
        read=False, created_at=datetime.now(),
    )
    with SessionLocal() as db:
        db.merge(rep)
        db.merge(req)
        db.merge(notif)
        db.commit()


def date_str_title(report_dict):
    return report_dict.get('date', '')


def _collect_indices():
    indices_data = {}
    try:
        import httpx
        index_codes = {
            '上证指数': 's_sh000001', '深证成指': 's_sz399001',
            '创业板指': 's_sz399006', '科创50': 's_sh000688',
        }
        for name, code in index_codes.items():
            url = f'http://hq.sinajs.cn/list={code}'
            resp = httpx.get(url, headers={'Referer': 'https://finance.sina.com.cn'}, timeout=5)
            if resp.status_code == 200:
                parts = resp.text.split(',')
                if len(parts) >= 4:
                    indices_data[name] = {
                        'price': float(parts[1]) if parts[1] else 0,
                        'change_pct': float(parts[3]) if parts[3] else 0,
                    }
    except Exception:
        logger.debug("sina index parse failed", exc_info=False)
    return indices_data


def _recap_points(indices_data):
    pts = []
    for name in ['上证指数', '深证成指', '创业板指']:
        v = indices_data.get(name)
        if v:
            pts.append(f'{name} {v["price"]}点 ({(v["change_pct"]):.2f}%)')
    if not pts:
        pts.append('指数数据暂未采集')
    return pts
