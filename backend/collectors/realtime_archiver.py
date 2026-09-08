"""
盘后归档器
- 把最后一次实时快照的权威值写入历史表
- 盘后补齐未采集股票
- 复验pending审核记录
"""
import json
import statistics
import logging
from datetime import datetime
from sqlalchemy import func
from db.session import get_db_session
from db.models import RealtimeSectorFlow, RealtimeStockFlow, SectorFlow, StockFlow, ManualReviewQueue
# 注意：collect_realtime_snapshot 在 realtime_collector 中定义，
# 反向引用会形成循环 import；此处改用延迟 import（见 _trigger_post_close_snapshot）
from collectors.tdx_collector import get_stock_money_flow
from collectors.astock_collector import batch_realtime_quotes
from analyzers.cross_validator import cross_validate

logger = logging.getLogger(__name__)


def _backfill_missing_stocks(trade_date, db):
    """盘后补齐：对盘中未采集的股票用多源验证补采日线数据"""
    # 获取已归档的股票代码
    existing_codes = {s.ts_code for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}

    # 获取全市场个股资金流向（东方财富批量）
    all_stocks = get_stock_money_flow(trade_date)
    if not all_stocks:
        print('[backfill] No stock data from eastmoney')
        return

    missing = [s for s in all_stocks if s['ts_code'] not in existing_codes]
    if not missing:
        print('[backfill] All stocks already archived')
        return

    print(f'[backfill] 补齐 {len(missing)} 只未归档股票')

    # 用腾讯财经批量验证价格
    ts_codes = [s['ts_code'] for s in missing[:200]]  # 限制200只
    tencent_prices = batch_realtime_quotes(ts_codes) if ts_codes else {}

    snapshot_time = datetime.now().replace(second=0, microsecond=0)
    backfilled = 0
    for s in missing[:200]:
        ts_code = s['ts_code']
        name = s.get('name', '')
        main_flow = float(s.get('main_force_inflow', 0) or 0)
        price = float(s.get('price', 0) or 0)
        price_chg = float(s.get('price_chg', 0) or 0)

        # 交叉验证价格
        price_sources = {'eastmoney': {'value': price}}
        if ts_code in tencent_prices:
            price_sources['tencent'] = {'value': tencent_prices[ts_code].get('price')}

        price_result = cross_validate(
            ts_code=ts_code, name=name, indicator='price',
            sources_data=price_sources, snapshot_time=snapshot_time,
            trade_date=trade_date,
        )
        authority_price = price_result['authority_value'] if price_result['authority_value'] is not None else price

        # 写入历史表
        db.add(StockFlow(
            trade_date=trade_date, ts_code=ts_code, name=name,
            sector=s.get('sector', ''), net_inflow=main_flow,
            main_force_inflow=main_flow, retail_flow=float(s.get('retail_flow', 0) or 0),
            price_chg=price_chg, price=authority_price,
        ))
        backfilled += 1

    print(f'[backfill] 补齐完成: {backfilled} 只')


def _reverify_pending_reviews(trade_date, db):
    """
    盘后复验pending审核记录：
    1. 重新采集多源数据验证
    2. CV≤15% → 自动通过
    3. CV>15% → 取中位数作为最终值（低置信度），标注"盘后复验仍分歧"
    4. 确保所有pending记录都有最终值，不再遗留
    """
    pending = db.query(ManualReviewQueue).filter_by(status='pending').all()
    if not pending:
        print('[reverify] 无pending审核记录')
        return

    print(f'[reverify] 复验 {len(pending)} 条pending记录')

    # 批量获取腾讯财经价格（用于价格指标复验）
    ts_codes = list({r.ts_code for r in pending})
    tencent_data = batch_realtime_quotes(ts_codes) if ts_codes else {}

    # 批量获取国信证券数据（用于资金流向复验）
    guosen_data = {}
    try:
        from collectors.guosen_collector import guosen_single_fund_flow
        for code in ts_codes[:20]:  # 限制20只避免额度问题
            data = guosen_single_fund_flow(code)
            if data:
                guosen_data[code] = data
    except Exception as e:
        print(f'[reverify] 国信证券采集失败: {e}')

    auto_passed = 0
    forced_pass = 0

    for r in pending:
        # 重新采集多源数据
        new_sources = {}

        # 东方财富：从最新快照获取
        latest_rt = db.query(RealtimeStockFlow).filter_by(
            trade_date=trade_date, ts_code=r.ts_code
        ).order_by(RealtimeStockFlow.snapshot_time.desc()).first()

        if latest_rt:
            if r.indicator == 'main_force_inflow':
                new_sources['eastmoney'] = float(latest_rt.main_force_inflow or 0)
            elif r.indicator == 'price':
                new_sources['eastmoney'] = float(latest_rt.price or 0)
            elif r.indicator == 'price_chg':
                new_sources['eastmoney'] = float(latest_rt.price_chg or 0)

        # 腾讯财经：价格
        if r.ts_code in tencent_data and r.indicator == 'price':
            new_sources['tencent'] = float(tencent_data[r.ts_code].get('price', 0) or 0)

        # 国信证券：资金流向+价格
        if r.ts_code in guosen_data:
            gd = guosen_data[r.ts_code]
            if r.indicator == 'main_force_inflow' and gd.get('main_force_inflow') is not None:
                new_sources['guosen'] = float(gd['main_force_inflow'])

        # 合并原始数据
        try:
            old_raw = json.loads(r.sources_data) if r.sources_data else {}
            for k, v in old_raw.items():
                val = v.get('value') if isinstance(v, dict) else v
                if val is not None and k not in new_sources:
                    new_sources[k] = float(val)
        except Exception:
            logger.debug('handled exception', exc_info=True)

        vals = list(new_sources.values())
        if not vals:
            # 无数据，强制拒绝
            r.status = 'rejected'
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验] 无有效数据，拒绝'
            forced_pass += 1
            continue

        median = statistics.median(vals)
        mean = statistics.mean(vals)
        std = statistics.stdev(vals) if len(vals) > 1 else 0
        cv = (std / abs(mean) * 100) if mean else 0

        if cv <= 15.0:
            # CV≤15%：自动通过
            if cv <= 5.0:
                final_value = statistics.mean(vals)
                confidence = '高'
                reason = f'盘后复验CV={cv:.1f}%≤5%，取平均值'
            else:
                final_value = median
                confidence = '中'
                reason = f'盘后复验CV={cv:.1f}%≤15%，取中位数'
            r.status = 'approved'
            r.final_value = final_value
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验·{confidence}置信度] {reason}'
            r.sources_data = json.dumps(new_sources, ensure_ascii=False, default=str)
            auto_passed += 1
            print(f'  {r.ts_code} {r.indicator}: ✅ 复验通过({confidence}) CV={cv:.1f}% 值={final_value:.2f}')
        else:
            # CV>15%：盘后仍分歧，取中位数作为最终值（低置信度）
            final_value = median
            r.status = 'approved'
            r.final_value = final_value
            r.reviewed_by = 'auto_reverify'
            r.reviewed_at = datetime.now()
            r.reason = f'[盘后复验·低置信度] CV={cv:.1f}%>15%，盘后仍分歧，取中位数。建议次日关注'
            r.sources_data = json.dumps(new_sources, ensure_ascii=False, default=str)
            forced_pass += 1
            print(f'  {r.ts_code} {r.indicator}: ⚠️ 盘后仍分歧 CV={cv:.1f}%，取中位数={final_value:.2f}')

        # 同步更新历史表的权威值
        hist = db.query(StockFlow).filter_by(
            trade_date=trade_date, ts_code=r.ts_code
        ).first()
        if hist and r.final_value is not None:
            if r.indicator == 'main_force_inflow':
                hist.main_force_inflow = r.final_value
            elif r.indicator == 'price':
                hist.price = r.final_value
            elif r.indicator == 'price_chg':
                hist.price_chg = r.final_value

    print(f'[reverify] 完成: 自动通过{auto_passed}条，强制取中位数{forced_pass}条')


def archive_today_snapshot_to_history(trade_date):
    """
    收盘后归档：多源交叉验证后写入历史表
    1. 先触发一次多源采集+交叉验证（确保权威值是最新的）
    2. 把权威值写入历史表（每天一条）
    3. 对于盘中未采集的股票，盘后补齐
    """
    print(f'[archive] === 盘后归档开始 {trade_date} ===')

    # 步骤1：盘后再采集一次多源数据+交叉验证
    print('[archive] 步骤1: 盘后多源采集+交叉验证...')
    # 延迟 import 避免 realtime_collector ↔ realtime_archiver 循环引用
    from collectors.realtime_collector import collect_realtime_snapshot
    collect_realtime_snapshot(trade_date)

    try:
        with get_db_session() as db:
            # 步骤2：取最后一次快照的权威值写入历史表
            # 板块归档
            last_sector_time = db.query(func.max(RealtimeSectorFlow.snapshot_time)).filter_by(
                trade_date=trade_date
            ).scalar()
            last_stock_time = db.query(func.max(RealtimeStockFlow.snapshot_time)).filter_by(
                trade_date=trade_date
            ).scalar()

            if last_sector_time:
                sectors = db.query(RealtimeSectorFlow).filter_by(
                    trade_date=trade_date, snapshot_time=last_sector_time
                ).all()
                existing = {s.sector: s for s in db.query(SectorFlow).filter_by(trade_date=trade_date).all()}
                for rt in sectors:
                    hist = existing.get(rt.sector)
                    if hist:
                        hist.money_inflow = rt.money_inflow
                        hist.money_outflow = rt.money_outflow
                        hist.net_flow = rt.net_flow
                        hist.rise_ratio = rt.rise_ratio
                    else:
                        db.add(SectorFlow(
                            trade_date=trade_date, sector=rt.sector,
                            money_inflow=rt.money_inflow, money_outflow=rt.money_outflow,
                            net_flow=rt.net_flow, rise_ratio=rt.rise_ratio,
                        ))
                print(f'[archive] 步骤2: 板块归档 {len(sectors)} 个')

            # 个股归档：使用交叉验证后的权威值
            if last_stock_time:
                stocks = db.query(RealtimeStockFlow).filter_by(
                    trade_date=trade_date, snapshot_time=last_stock_time
                ).all()
                existing = {s.ts_code: s for s in db.query(StockFlow).filter_by(trade_date=trade_date).all()}
                archived_count = 0
                high_confidence_count = 0
                for rt in stocks:
                    hist = existing.get(rt.ts_code)
                    # 使用交叉验证后的权威值（rt.main_force_inflow 已经是权威值）
                    if hist:
                        hist.net_inflow = rt.net_inflow
                        hist.main_force_inflow = rt.main_force_inflow
                        hist.retail_flow = rt.retail_flow
                        hist.price_chg = rt.price_chg
                        hist.price = rt.price
                        hist.sector = rt.sector
                        hist.name = rt.name
                    else:
                        db.add(StockFlow(
                            trade_date=trade_date, ts_code=rt.ts_code, name=rt.name,
                            sector=rt.sector, net_inflow=rt.net_inflow,
                            main_force_inflow=rt.main_force_inflow, retail_flow=rt.retail_flow,
                            price_chg=rt.price_chg, price=rt.price,
                        ))
                    archived_count += 1
                    if rt.confidence == 'high':
                        high_confidence_count += 1
                print(f'[archive] 步骤2: 个股归档 {archived_count} 只 (高置信度: {high_confidence_count}只)')

            # 步骤3：盘后补齐 - 对盘中未采集的股票用多源验证补采
            print('[archive] 步骤3: 盘后补齐日线...')
            _backfill_missing_stocks(trade_date, db)

            # 步骤4：复验pending审核记录（盘后重新采集多源数据验证）
            print('[archive] 步骤4: 复验pending审核记录...')
            _reverify_pending_reviews(trade_date, db)

            db.commit()
        print(f'[archive] === 盘后归档完成 {trade_date} ===')
    except Exception as e:
        db.rollback()
        logger.exception(f'[archive] Error')
