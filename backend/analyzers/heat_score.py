"""
热度评分计算器
heat_score = net_flow_normalized * 0.4 + limit_up_count_normalized * 0.3 + rise_ratio_normalized * 0.3
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import logging
import numpy as np
from db.connection import get_db
from db.session import get_db_session
from db.models import SectorFlow

logger = logging.getLogger(__name__)


def calculate_heat_scores(trade_date):
    """计算指定日期所有板块的热度评分"""
    try:
        with get_db_session() as db:
            sectors = db.query(SectorFlow).filter_by(trade_date=trade_date).all()
            if not sectors:
                print(f'[heat] No sector data for {trade_date}')
                return
        
            net_flows = np.array([float(s.net_flow or 0) for s in sectors])
            limit_ups = np.array([float(s.limit_up_count or 0) for s in sectors])
            rises = np.array([float(s.rise_ratio or 0) for s in sectors])
        
            def normalize(arr):
                if len(arr) == 0:
                    return arr
                if arr.max() == arr.min():
                    return np.ones_like(arr) * 0.5
                return (arr - arr.min()) / (arr.max() - arr.min())
        
            nf_norm = normalize(net_flows)
            lu_norm = normalize(limit_ups)
            rr_norm = normalize(rises)
        
            for i, sector in enumerate(sectors):
                score = nf_norm[i] * 0.4 + lu_norm[i] * 0.3 + rr_norm[i] * 0.3
                sector.heat_score = round(float(score * 100), 2)  # 0-100分
        
            db.commit()
            print(f'[heat] Calculated heat scores for {len(sectors)} sectors')
    except Exception as e:
        db.rollback()
        logger.exception(f'[heat] Error')
        return {'error': str(e)}


if __name__ == '__main__':
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    calculate_heat_scores(today)
