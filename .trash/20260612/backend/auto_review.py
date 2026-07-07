"""自动审核通过机制：对已有审核记录按规则自动处理"""
import sys, os, json, statistics
from datetime import datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.connection import get_db
from db.models import ManualReviewQueue

def auto_review():
    """
    自动审核规则：
    1. 多源差异≤5% → 自动通过，取平均值（高置信度）
    2. 去掉异常源后≥2源且差异≤5% → 自动通过，取非异常源平均值
    3. 多源差异≤15% → 自动通过，取中位数（中置信度，标注略有偏差）
    4. 单源数据 → 自动通过，取单源值（低置信度）
    5. 差异>15% → 保留人工审核
    """
    db = next(get_db())
    reviews = db.query(ManualReviewQueue).filter_by(status='pending').all()
    print(f'待审核记录: {len(reviews)}条\n')

    auto_passed = 0
    kept_manual = 0

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
        decision = None
        final_value = None
        reason = ''
        confidence = ''

        if len(vals) == 0:
            decision = 'keep_manual'
            reason = '无有效数据'
        elif len(vals) == 1:
            # 单源：自动通过
            decision = 'auto_pass'
            final_value = vals[0]
            confidence = '低'
            reason = f'单源数据({list(values.keys())[0]})，自动通过'
        else:
            median = statistics.median(vals)
            mean = statistics.mean(vals)
            std = statistics.stdev(vals)
            cv = (std / abs(mean) * 100) if mean else 0

            # 去掉异常源
            non_outlier = {k: v for k, v in values.items()
                          if abs(v - median) <= max(abs(median) * 0.05, 100)}
            non_outlier_vals = list(non_outlier.values())

            if len(non_outlier_vals) >= 2:
                non_mean = statistics.mean(non_outlier_vals)
                non_std = statistics.stdev(non_outlier_vals) if len(non_outlier_vals) > 1 else 0
                non_cv = (non_std / abs(non_mean) * 100) if non_mean else 0

                if non_cv <= 5.0:
                    # 非异常源差异≤5%：自动通过，取平均值
                    decision = 'auto_pass'
                    final_value = statistics.mean(non_outlier_vals)
                    confidence = '高'
                    outliers = [k for k in values if k not in non_outlier]
                    reason = f'非异常源CV={non_cv:.1f}%≤5%，取平均值'
                    if outliers:
                        reason += f'，排除异常源({",".join(outliers)})'
                elif cv <= 15.0:
                    # 全部源差异≤15%：自动通过，取中位数
                    decision = 'auto_pass'
                    final_value = median
                    confidence = '中'
                    reason = f'各源CV={cv:.1f}%≤15%，取中位数（各源略有偏差）'
                else:
                    decision = 'keep_manual'
                    reason = f'各源分歧大CV={cv:.1f}%>15%，需人工'
            else:
                if cv <= 15.0:
                    decision = 'auto_pass'
                    final_value = median
                    confidence = '中'
                    reason = f'各源CV={cv:.1f}%≤15%，取中位数'
                else:
                    decision = 'keep_manual'
                    reason = f'各源分歧大CV={cv:.1f}%>15%，需人工'

        # 执行决策
        if decision == 'auto_pass':
            r.status = 'approved'
            r.final_value = final_value
            r.reviewed_by = 'auto_review'
            r.reviewed_at = datetime.now()
            r.reason = f'[自动审核·{confidence}置信度] {reason}'
            auto_passed += 1
            print(f'ID={r.id} {r.ts_code} {r.indicator}: ✅ 自动通过({confidence}) 值={final_value:.2f}')
            print(f'  原因: {reason}')
        else:
            kept_manual += 1
            print(f'ID={r.id} {r.ts_code} {r.indicator}: ⏳ 保留人工审核')
            print(f'  原因: {reason}')
        print()

    db.commit()
    print(f'=== 汇总 ===')
    print(f'自动通过: {auto_passed}条')
    print(f'保留人工: {kept_manual}条')
    db.close()


if __name__ == '__main__':
    auto_review()
