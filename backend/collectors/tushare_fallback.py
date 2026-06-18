"""
Tushare 备选数据源
当 pytdx 不可用时使用
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import tushare as ts
    TUSHARE_AVAILABLE = True
except ImportError:
    TUSHARE_AVAILABLE = False
    ts = None

def get_tushare_api():
    """获取Tushare API实例"""
    if not TUSHARE_AVAILABLE:
        return None
    from config import TUSHARE_TOKEN
    if TUSHARE_TOKEN:
        ts.set_token(TUSHARE_TOKEN)
        return ts.pro_api()
    return None

def get_stock_list_tushare():
    """获取A股股票列表"""
    pro = get_tushare_api()
    if not pro:
        return []
    try:
        df = pro.stock_basic(exchange='', list_status='L', fields='ts_code,symbol,name,area,industry')
        return df.to_dict('records') if df is not None else []
    except Exception as e:
        print(f'[tushare] get_stock_list error: {e}')
        return []
