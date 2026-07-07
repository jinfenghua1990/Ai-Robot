"""检查审核队列中的记录，判断哪些可以自动通过"""
import sys, os, json, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.connection import get_db
from db.models import ManualReviewQueue

db = next(get_db())
reviews = db.query(ManualReviewQueue).filter_by(status='pending').all()
print(f'待审核记录: {len(reviews)}条\n')

auto_pass_ids = []
manual_ids = []

for r in reviews:
    raw = json.loads(r.sources_data) if r.sources_data else {}
    values = {}
    for k, v in raw.items():
        if isinstance(v, dict):
            val = v.get('value')
        else:
            val = v
        if val is not None:
            values[k] = float(val)
    vals = list(values.values())

    if len(vals) >= 2:
        median = statistics.median(vals)
        # 去掉异常源（偏离中位数>5%或>100万）
        non_outlier = {k: v for k, v in values.items() if abs(v - median) <= max(abs(median)*0.05, 100)}
        non_outlier_vals = list(non_outlier.values())

        if len(non_outlier_vals) >= 2:
            non_mean = statistics.mean(non_outlier_vals)
            non_std = statistics.stdev(non_outlier_vals) if len(non_outlier_vals) > 1 else 0
            non_cv = (non_std / abs(non_mean) * 100) if non_mean else 0
            auto_value = statistics.mean(non_outlier_vals)
            can_auto = non_cv <= 5.0
            status = '可自动通过' if can_auto else '需人工'
            print(f'ID={r.id} {r.ts_code} {r.indicator}')
            print(f'  全部值: {values}')
            print(f'  非异常值: {non_outlier} CV={non_cv:.1f}% {status}')
            print(f'  自动通过值: {auto_value:.2f}')
            if can_auto:
                auto_pass_ids.append((r.id, auto_value))
            else:
                manual_ids.append(r.id)
        else:
            print(f'ID={r.id} {r.ts_code} {r.indicator}: 非异常源不足2个，需人工')
            manual_ids.append(r.id)
    elif len(vals) == 1:
        print(f'ID={r.id} {r.ts_code} {r.indicator}: 单源值={vals[0]}，自动通过')
        auto_pass_ids.append((r.id, vals[0]))
    else:
        print(f'ID={r.id} {r.ts_code} {r.indicator}: 无有效值')
        manual_ids.append(r.id)
    print()

print(f'=== 汇总 ===')
print(f'可自动通过: {len(auto_pass_ids)}条 (IDs: {[x[0] for x in auto_pass_ids]})')
print(f'需人工审核: {len(manual_ids)}条 (IDs: {manual_ids})')
db.close()
