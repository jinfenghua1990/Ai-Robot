"""
重置 yuzi_lifecycle_tracker.day_filled，让 update_lifecycle 能填 d1-d20
（迁移 7 天 → 20 天专用）
"""
from db.session import get_db_session
from db.models import YuziLifecycleTracker
from sqlalchemy import text

with get_db_session() as db:
    # 把所有记录 day_filled 重置为 0, 让 update_lifecycle 从 d1 重新填
    # final_outcome 和 net_return_20d 会由 day_diff >= 20 触发重算
    n = db.query(YuziLifecycleTracker).update({YuziLifecycleTracker.day_filled: 0})
    db.commit()
    print(f'reset day_filled: {n} rows')

# 显示重置后的状态
with get_db_session() as db:
    total = db.query(YuziLifecycleTracker).count()
    print(f'total rows: {total}')
