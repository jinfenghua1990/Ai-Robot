"""
实时数据采集器 —— 编排层
盘中每15分钟采集一次，写入 realtime_sector_flow / realtime_stock_flow / realtime_concept_sector_flow 表
多源采集 + 交叉验证 + 质量评分

具体实现已拆分到以下独立模块：
  - realtime_sector_collector    板块资金流向
  - realtime_stock_collector     个股资金流向（含多源交叉验证）
  - realtime_concept_collector   概念板块资金流向（含多源聚合）
  - realtime_archiver            盘后归档、补齐、复验

数据源优先级（额度优化版）：
  - 板块资金流向：新浪(主) → 东方财富(降级)
  - 个股资金流向：东方财富datacenter(全市场批量,1次API) → 东财push2+新浪(Top20验证) → 国信证券(Top10验证)
  - 实时价格：腾讯财经(主,Top50) → 通达信(验证,Top20) → 东方财富(已含)
  ※ 东方财富datacenter和国信证券有额度限制，尽量少用
  ※ 通达信(TCP)和新浪(无限制)可多用
"""
# 重新导出，保持原有 from collectors.realtime_collector import ... 的兼容性
from collectors.realtime_sector_collector import collect_realtime_sector_flow
from collectors.realtime_stock_collector import collect_realtime_stock_flow, _build_fallback_stock_flows
from collectors.realtime_concept_collector import (
    collect_realtime_concept_sector_flow,
    _compute_concept_flows_from_stocks,
)
from collectors.realtime_archiver import (
    archive_today_snapshot_to_history,
    _backfill_missing_stocks,
    _reverify_pending_reviews,
)


def collect_realtime_snapshot(trade_date):
    """采集一次完整的实时快照（板块+个股+概念板块）"""
    print(f'[realtime] === Snapshot for {trade_date} ===')
    sector_count = collect_realtime_sector_flow(trade_date)
    stock_count = collect_realtime_stock_flow(trade_date)
    # 概念板块放在个股之后，便于用成分股计算补充新浪没有的热门概念
    concept_count = collect_realtime_concept_sector_flow(trade_date)
    print(f'[realtime] Snapshot done: {sector_count} sectors, {concept_count} concepts, {stock_count} stocks')
    return {'sector_count': sector_count, 'concept_count': concept_count, 'stock_count': stock_count}


if __name__ == '__main__':
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    # 测试采集
    result = collect_realtime_snapshot(today)
    print(result)
