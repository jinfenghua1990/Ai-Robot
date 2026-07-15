"""一次性回填：把 analysis_reports/{requests,results,notifications} 下现有 JSON 导入 PG

目的：研报中心改为 PG 支撑后，旧 JSON 报告需迁移进库，前端才不丢数据。
可重复运行（用 merge 按主键 upsert）。
"""
import json
import os
import sys
from datetime import datetime

BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BACKEND)

from db.connection import SessionLocal
from db.models import AnalysisRequest, AnalysisReport, Notification


def _parse(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


def main():
    base = os.path.join(BACKEND, "analysis_reports")
    req_dir = os.path.join(base, "requests")
    res_dir = os.path.join(base, "results")
    notif_dir = os.path.join(base, "notifications")

    with SessionLocal() as db:
        # 1) requests
        rc = 0
        if os.path.isdir(req_dir):
            for fn in os.listdir(req_dir):
                if not fn.endswith(".json"):
                    continue
                d = json.load(open(os.path.join(req_dir, fn), encoding="utf-8"))
                db.merge(AnalysisRequest(
                    id=d["id"], stock_code=d.get("stock_code", ""),
                    stock_name=d.get("stock_name", ""), source=d.get("source", "tdx"),
                    status=d.get("status", "pending"), error=d.get("error"),
                    created_at=_parse(d.get("created_at")), updated_at=_parse(d.get("updated_at")),
                ))
                rc += 1
        # 2) results（报告）
        wc = 0
        if os.path.isdir(res_dir):
            for fn in os.listdir(res_dir):
                if not fn.endswith(".json"):
                    continue
                d = json.load(open(os.path.join(res_dir, fn), encoding="utf-8"))
                rid = d.get("id") or fn[:-5]
                summ = d.get("summary", {})
                db.merge(AnalysisReport(
                    id=rid, stock_code=d.get("stock_code", ""), stock_name=d.get("stock_name", ""),
                    source=d.get("source", "tdx"), report_type=d.get("report_type", ""),
                    rating=summ.get("rating", ""), target_price=str(summ.get("target_price", "")),
                    confidence=summ.get("confidence", ""),
                    report_json=json.dumps(d, ensure_ascii=False),
                    created_at=_parse(d.get("created_at")),
                ))
                wc += 1
        # 3) notifications
        nc = 0
        if os.path.isdir(notif_dir):
            for fn in os.listdir(notif_dir):
                if not fn.endswith(".json"):
                    continue
                d = json.load(open(os.path.join(notif_dir, fn), encoding="utf-8"))
                db.merge(Notification(
                    id=d["id"], source=d.get("source", ""), stock_code=d.get("stock_code", ""),
                    stock_name=d.get("stock_name", ""), title=d.get("title", ""),
                    read=bool(d.get("read", False)), created_at=_parse(d.get("created_at")),
                ))
                nc += 1
        db.commit()
        print(f"backfilled: requests={rc} reports={wc} notifications={nc}")


if __name__ == "__main__":
    main()
