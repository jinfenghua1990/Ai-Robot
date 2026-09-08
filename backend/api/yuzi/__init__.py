"""
游资龙虎榜 API 包
- GET /api/yuzi/seats                席位字典列表（含增删改接口）
- GET /api/yuzi/billboard            当日席位榜（按大佬汇总：净买/净卖/上榜股）
- GET /api/yuzi/resonance            当日共振信号池（按股汇总：净买/共振数/评分）
- GET /api/yuzi/seat-stats           某游资近 N 日战绩
- POST /api/yuzi/seats               新增席位
- PUT  /api/yuzi/seats/{id}          修改席位
- DELETE /api/yuzi/seats/{id}        删除席位
- POST /api/yuzi/refresh             触发盘后清洗（拉 Tushare 当日 top_list/top_inst）
"""
from .router import router

__all__ = ["router"]
