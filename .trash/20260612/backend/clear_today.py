"""删除今天数据并重新采集"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from db.connection import get_db
from db.models import SectorFlow, StockFlow, LeaderLifecycle
from datetime import datetime

db = next(get_db())
today = datetime.now().date()
db.query(SectorFlow).filter(SectorFlow.trade_date == today).delete()
db.query(StockFlow).filter(StockFlow.trade_date == today).delete()
db.query(LeaderLifecycle).filter(LeaderLifecycle.trade_date == today).delete()
db.commit()
print(f'Deleted data for {today}')
db.close()
