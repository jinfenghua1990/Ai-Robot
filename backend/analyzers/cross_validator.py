"""
多渠道数据交叉验证引擎
- 对同一指标的多源数据进行交叉验证
- 计算偏差、中位数、加权平均
- 识别异常源，生成质量评分
- 记录质量日志，触发人工审核
"""
import sys, os, json, statistics
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from datetime import datetime, date
from db.connection import get_db
from db.session import get_db_session
from db.models import DataQualityLog, ManualReviewQueue, DataSourceReliability

# 数据源默认权重（基于历史可靠性，可动态调整）
DEFAULT_WEIGHTS = {
    'eastmoney': 0.30,   # 东方财富（个股资金流向主源）
    'sina':      0.25,   # 新浪（板块资金流向主源）
    'guosen':    0.20,   # 国信证券（验证源）
    'tencent':   0.15,   # 腾讯财经（价格/PE/PB）
    'tushare':   0.07,   # Tushare（降级源）
    'tdx':       0.03,   # 通达信（价格补充）
    'akshare':   0.12,   # AKShare（行情验证源）
    'efinance':  0.10,   # efinance（行情/资金补充）
    'adata':     0.08,   # adata（聚合多源验证）
    'qstock':    0.08,   # qstock（行情/资金补充）
    'ths':       0.15,   # 同花顺（资金流向/龙虎榜）
    'mootdx':    0.05,   # mootdx（TCP行情补充）
    'baostock':  0.06,   # baostock（盘后日K验证）
    'sina_quote': 0.10,  # 新浪行情（批量极速验证）
    'tencent_kline': 0.08, # 腾讯K线（前复权验证）
    'netease':   0.05,   # 网易财经（价格补充）
    'itick':     0.12,   # iTick（实时行情，低延迟验证）
    'jqdata':    0.18,   # 聚宽数据（高质量日K/财务）
}

# 偏差阈值（按指标类型差异化）
DEVIATION_THRESHOLD_PCT = {
    'price': 0.02,        # 价格类 2%（价格应高度一致）
    'volume': 0.10,       # 成交量 10%（量能波动大）
    'money_flow': 0.15,   # 资金流向 15%（大额波动正常）
    'pe_pb': 0.05,        # 估值指标 5%
    'default': 0.05,      # 默认 5%
}
DEVIATION_THRESHOLD_ABS = 100   # 100万绝对阈值（资金流向类）


def get_threshold(metric_type: str = 'default') -> float:
    """获取指定指标类型的偏差阈值"""
    return DEVIATION_THRESHOLD_PCT.get(metric_type, DEVIATION_THRESHOLD_PCT['default'])


def _infer_metric_type(indicator: str) -> str:
    """根据指标名推断指标类型（用于差异化阈值）"""
    if not indicator:
        return 'default'
    ind_lower = indicator.lower()
    if any(k in ind_lower for k in ['price', 'close', 'open', 'high', 'low', '现价', '价格']):
        return 'price'
    if any(k in ind_lower for k in ['volume', 'vol', '成交量', '量比']):
        return 'volume'
    if any(k in ind_lower for k in ['flow', 'inflow', 'outflow', 'net', 'main_force', '资金', '主力', '净流入']):
        return 'money_flow'
    if any(k in ind_lower for k in ['pe', 'pb', 'roe', '估值']):
        return 'pe_pb'
    return 'default'


def get_dynamic_weights(target_date=None):
    """获取动态权重（基于数据源可靠性统计）"""
    try:
        with get_db_session() as db:
            if target_date is None:
                target_date = date.today()
            # 查最近7天的可靠性统计
            from datetime import timedelta
            week_ago = target_date - timedelta(days=7)
            records = db.query(DataSourceReliability).filter(
                DataSourceReliability.date >= week_ago
            ).all()

            if not records:
                return DEFAULT_WEIGHTS.copy()

            # 按数据源聚合
            source_stats = {}
            for r in records:
                if r.source not in source_stats:
                    source_stats[r.source] = {'total': 0, 'outliers': 0, 'deviations': []}
                source_stats[r.source]['total'] += r.total_count or 0
                source_stats[r.source]['outliers'] += r.outlier_count or 0
                if r.avg_deviation is not None:
                    source_stats[r.source]['deviations'].append(float(r.avg_deviation))

            # 计算动态权重：可靠性越高权重越大
            weights = {}
            total_reliability = 0
            for source, stats in source_stats.items():
                total = stats['total']
                outliers = stats['outliers']
                if total == 0:
                    reliability = 50
                else:
                    # 可靠性 = 100 - (异常率 * 100) - (平均偏差 * 0.5)
                    outlier_rate = outliers / total
                    avg_dev = statistics.mean(stats['deviations']) if stats['deviations'] else 0
                    reliability = max(10, 100 - outlier_rate * 100 - avg_dev * 0.5)
                weights[source] = reliability
                total_reliability += reliability

            # 归一化
            if total_reliability > 0:
                weights = {k: v / total_reliability for k, v in weights.items()}

            # 合并默认权重（对于没有统计数据的源）
            for src, w in DEFAULT_WEIGHTS.items():
                if src not in weights:
                    weights[src] = w * 0.5  # 降权
                    total_reliability += weights[src]
            weights = {k: v / total_reliability for k, v in weights.items()}
        return weights
    except Exception as e:
        print(f'[validator] get_dynamic_weights error: {e}')
        return DEFAULT_WEIGHTS.copy()


def cross_validate(ts_code, name, indicator, sources_data, snapshot_time=None, trade_date=None):
    """
    交叉验证核心函数
    sources_data = {
        'eastmoney': {'value': 8919.35, ...},
        'guosen':    {'value': 8920.10, ...},
        'tencent':   {'value': None, ...},  # None表示该源无此数据
    }
    返回: {
        'authority_value': 8919.5,
        'confidence': 'high',
        'sources_used': ['eastmoney', 'guosen'],
        'sources_count': 2,
        'outliers': [],
        'deviation_pct': 0.01,
        'quality_score': 92.5,
        'action': 'accept',
        'is_corrected': False,
    }
    """
    if snapshot_time is None:
        snapshot_time = datetime.now().replace(second=0, microsecond=0)
    if trade_date is None:
        trade_date = snapshot_time.date()

    # 1. 过滤无效数据
    valid = {}
    for src, data in sources_data.items():
        val = data.get('value') if isinstance(data, dict) else data
        if val is not None and val != 0:  # 0可能是无效值
            valid[src] = float(val)
        elif val == 0 and indicator in ('price',):  # 价格为0肯定是无效的，但其他指标0可能是真实的
            pass  # 跳过
        elif val == 0:
            valid[src] = 0.0  # 保留0值用于非价格指标

    if not valid:
        return {
            'authority_value': None, 'confidence': 'no_data', 'sources_used': [],
            'sources_count': 0, 'outliers': [], 'deviation_pct': 0,
            'quality_score': 0, 'action': 'reject', 'is_corrected': False,
        }

    values = list(valid.values())
    srcs = list(valid.keys())

    # 2. 单源情况
    if len(valid) == 1:
        return {
            'authority_value': values[0], 'confidence': 'low', 'sources_used': srcs,
            'sources_count': 1, 'outliers': [], 'deviation_pct': 0,
            'quality_score': 40, 'action': 'accept', 'is_corrected': False,
        }

    # 3. 多源：计算统计指标
    median = statistics.median(values)
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0
    # 变异系数（CV）
    cv = (std / abs(mean) * 100) if mean else 0

    # 4. 偏差检测：标记偏离中位数超过阈值的源（按指标类型差异化阈值）
    metric_type = _infer_metric_type(indicator)
    threshold_pct = get_threshold(metric_type)
    threshold = max(abs(median) * threshold_pct, DEVIATION_THRESHOLD_ABS)
    outliers = []
    for src, val in valid.items():
        if abs(val - median) > threshold:
            outliers.append(src)

    # 5. 仲裁决策
    # === 核心规则：多源差异≤5% → 取平均值正常录入 ===
    non_outlier_srcs = [s for s in srcs if s not in outliers]
    non_outlier_values = [valid[s] for s in non_outlier_srcs]

    if len(non_outlier_srcs) >= 3 and cv <= 5.0:
        # 3源及以上，差异≤5%：取简单平均值，高置信度
        authority_value = statistics.mean(non_outlier_values)
        confidence = 'high'
        action = 'accept'
        is_corrected = len(outliers) > 0
    elif len(non_outlier_srcs) >= 2 and cv <= 5.0:
        # 2源，差异≤5%：取平均值，中置信度
        authority_value = statistics.mean(non_outlier_values)
        confidence = 'medium'
        action = 'accept'
        is_corrected = len(outliers) > 0
    elif len(non_outlier_srcs) >= 2:
        # 多数一致但差异>5%：取非异常源的加权平均
        weights = get_dynamic_weights(trade_date)
        total_weight = sum(weights.get(s, 0.1) for s in non_outlier_srcs)
        if total_weight > 0:
            authority_value = sum(valid[s] * weights.get(s, 0.1) for s in non_outlier_srcs) / total_weight
        else:
            authority_value = median
        confidence = 'medium'
        action = 'accept'
        is_corrected = True
    elif len(non_outlier_srcs) == 1:
        # 只有一个非异常源
        authority_value = valid[non_outlier_srcs[0]]
        confidence = 'medium'
        action = 'accept'
        is_corrected = True
    else:
        # 全部都是异常（各源分歧极大）
        authority_value = median
        confidence = 'disputed'
        action = 'review'
        is_corrected = True

    # 6. 质量评分（0-100）
    quality_score = _calculate_quality_score(
        sources_count=len(valid),
        outliers_count=len(outliers),
        cv=cv,
        confidence=confidence,
    )

    # 7. 记录质量日志
    _log_quality(
        snapshot_time=snapshot_time,
        trade_date=trade_date,
        ts_code=ts_code,
        name=name,
        indicator=indicator,
        sources_data={k: {'value': v} for k, v in valid.items()},
        authority_value=authority_value,
        outliers=outliers,
        quality_score=quality_score,
        action=action,
    )

    # 8. 严重异常触发自动审核或人工审核
    if action == 'review' or (len(outliers) > 0 and quality_score < 50):
        # 先尝试自动审核
        auto_result = _try_auto_review(
            ts_code=ts_code, name=name, indicator=indicator,
            sources_data=valid, outliers=outliers,
            authority_value=authority_value, cv=cv,
        )
        if not auto_result:
            # 自动审核无法处理，触发人工审核
            _trigger_manual_review(
                ts_code=ts_code, name=name, indicator=indicator,
                sources_data=valid, outliers=outliers,
                authority_value=authority_value, reason=f'多源分歧(CV={cv:.1f}%)',
            )

    # 9. 更新数据源可靠性统计
    _update_source_reliability(trade_date, valid, outliers, median)

    return {
        'authority_value': round(authority_value, 2),
        'confidence': confidence,
        'sources_used': srcs,
        'sources_count': len(valid),
        'outliers': outliers,
        'deviation_pct': round(cv, 2),
        'quality_score': round(quality_score, 2),
        'action': action,
        'is_corrected': is_corrected,
    }


def _calculate_quality_score(sources_count, outliers_count, cv, confidence):
    """计算质量评分（0-100）"""
    # 完整性（30分）：数据源数量
    completeness = min(30, sources_count * 7.5)
    # 一致性（40分）：变异系数越小越好
    consistency = max(0, 40 - cv * 2)
    # 可靠性（30分）：异常源越少越好
    if sources_count > 0:
        reliability = 30 * (1 - outliers_count / sources_count)
    else:
        reliability = 0
    score = completeness + consistency + reliability
    # 置信度加成
    if confidence == 'high':
        score = min(100, score + 5)
    elif confidence == 'disputed':
        score = max(0, score - 15)
    return score


def _log_quality(snapshot_time, trade_date, ts_code, name, indicator,
                 sources_data, authority_value, outliers, quality_score, action):
    """记录质量日志"""
    try:
        with get_db_session() as db:
            log = DataQualityLog(
                snapshot_time=snapshot_time,
                trade_date=trade_date,
                ts_code=ts_code,
                name=name,
                indicator=indicator,
                sources_data=json.dumps(sources_data, ensure_ascii=False, default=str),
                authority_value=authority_value,
                outliers=','.join(outliers),
                quality_score=quality_score,
                action=action,
            )
            db.add(log)
            db.commit()
    except Exception as e:
        db.rollback()
        print(f'[validator] log_quality error: {e}')


def _trigger_manual_review(ts_code, name, indicator, sources_data, outliers,
                           authority_value, reason):
    """触发人工审核"""
    try:
        with get_db_session() as db:
            review = ManualReviewQueue(
                ts_code=ts_code,
                name=name,
                indicator=indicator,
                reason=reason,
                sources_data=json.dumps(sources_data, ensure_ascii=False, default=str),
                status='pending',
            )
            db.add(review)
            db.commit()
            print(f'[validator] Manual review triggered for {ts_code}.{indicator}: {reason}')
    except Exception as e:
        db.rollback()
        print(f'[validator] trigger_review error: {e}')


def _try_auto_review(ts_code, name, indicator, sources_data, outliers,
                     authority_value, cv):
    """
    尝试自动审核（在触发人工审核之前）
    规则：
    1. CV≤5% → 自动通过，取平均值（高置信度）
    2. CV≤15% → 自动通过，取中位数（中置信度）
    3. CV>15% → 返回False，转人工审核
    返回: True=已自动处理, False=需人工审核
    """
    try:
        with get_db_session() as db:
            vals = list(sources_data.values())
            if not vals:
                return False

            median = statistics.median(vals)
            decision = False
            final_value = None
            confidence = ''
            reason = ''

            if cv <= 5.0:
                decision = True
                final_value = statistics.mean(vals)
                confidence = '高'
                reason = f'CV={cv:.1f}%≤5%，取平均值'
            elif cv <= 15.0:
                decision = True
                final_value = median
                confidence = '中'
                reason = f'CV={cv:.1f}%≤15%，取中位数（各源略有偏差）'
            else:
                return False  # 需人工审核

            if decision:
                review = ManualReviewQueue(
                    ts_code=ts_code,
                    name=name,
                    indicator=indicator,
                    reason=f'[自动审核·{confidence}置信度] {reason}',
                    sources_data=json.dumps(sources_data, ensure_ascii=False, default=str),
                    status='approved',
                    final_value=final_value,
                    reviewed_by='auto_review',
                    reviewed_at=datetime.now(),
                )
                db.add(review)
                db.commit()
                print(f'[validator] Auto-approved {ts_code}.{indicator}: {reason} → {final_value:.2f}')
                return True
    except Exception as e:
        db.rollback()
        print(f'[validator] auto_review error: {e}')
        return False


def _update_source_reliability(target_date, valid_data, outliers, median):
    """更新数据源可靠性统计"""
    try:
        with get_db_session() as db:
            for src, val in valid_data.items():
                record = db.query(DataSourceReliability).filter_by(
                    date=target_date, source=src
                ).first()
                if not record:
                    record = DataSourceReliability(
                        date=target_date, source=src,
                        total_count=0, outlier_count=0, avg_deviation=0,
                        reliability_score=100,
                    )
                    db.add(record)
                record.total_count = (record.total_count or 0) + 1
                if src in outliers:
                    record.outlier_count = (record.outlier_count or 0) + 1
                # 更新平均偏差
                deviation = abs(val - median) / abs(median) * 100 if median else 0
                old_avg = float(record.avg_deviation or 0)
                old_count = (record.total_count or 1) - 1
                if old_count > 0:
                    record.avg_deviation = (old_avg * old_count + deviation) / record.total_count
                else:
                    record.avg_deviation = deviation
                # 更新可靠性评分
                outlier_rate = record.outlier_count / record.total_count if record.total_count else 0
                record.reliability_score = max(0, 100 - outlier_rate * 100 - float(record.avg_deviation or 0) * 0.5)
            db.commit()
    except Exception as e:
        db.rollback()
        print(f'[validator] update_reliability error: {e}')


def detect_anomalies(ts_code, name, indicator, value, history_values=None):
    """
    异常检测（规则+统计）
    history_values: 该指标的历史值列表（用于统计检测）
    返回: {'is_anomaly': bool, 'reason': str, 'severity': 'low/medium/high'}
    """
    anomalies = []

    # 规则检测
    if indicator == 'main_force_inflow':
        # 主力净流入 > 100亿 可疑
        if abs(value) > 1000000:  # 100亿（万元）
            anomalies.append({'severity': 'high', 'reason': f'主力净流入{value/10000:.0f}亿异常大'})
        # 涨停股主力净流入为负可疑
        if value < -50000:  # 流出超5亿
            anomalies.append({'severity': 'medium', 'reason': f'主力净流出{abs(value)/10000:.0f}亿'})

    elif indicator == 'price':
        if value <= 0:
            anomalies.append({'severity': 'high', 'reason': '价格≤0'})
        if value > 10000:
            anomalies.append({'severity': 'medium', 'reason': f'价格{value}元异常高'})

    elif indicator == 'price_chg':
        if abs(value) > 20:  # 创业板/科创板涨跌停20%
            anomalies.append({'severity': 'high', 'reason': f'涨跌幅{value}%超限'})

    # 统计检测（需要历史数据）
    if history_values and len(history_values) >= 5:
        mean = statistics.mean(history_values)
        std = statistics.stdev(history_values)
        if std > 0:
            z_score = abs(value - mean) / std
            if z_score > 3:
                anomalies.append({'severity': 'high', 'reason': f'Z-Score={z_score:.1f}（偏离3σ）'})
            elif z_score > 2:
                anomalies.append({'severity': 'medium', 'reason': f'Z-Score={z_score:.1f}（偏离2σ）'})

        # 箱线图检测
        sorted_vals = sorted(history_values)
        q1 = sorted_vals[len(sorted_vals) // 4]
        q3 = sorted_vals[3 * len(sorted_vals) // 4]
        iqr = q3 - q1
        if iqr > 0:
            if value < q1 - 1.5 * iqr or value > q3 + 1.5 * iqr:
                anomalies.append({'severity': 'medium', 'reason': '超出箱线图范围'})

    if anomalies:
        severity = max(a['severity'] for a in anomalies)
        return {
            'is_anomaly': True,
            'reason': '; '.join(a['reason'] for a in anomalies),
            'severity': severity,
        }
    return {'is_anomaly': False, 'reason': '', 'severity': 'low'}


if __name__ == '__main__':
    # 测试交叉验证
    print('=== 测试1：多源一致 ===')
    r = cross_validate('600519.SH', '贵州茅台', 'main_force_inflow', {
        'eastmoney': {'value': 5507},
        'guosen':    {'value': 5510},
        'tencent':   {'value': 5500},
    })
    print(f'  结果: {r}')

    print('\n=== 测试2：存在异常源 ===')
    r = cross_validate('000001.SZ', '平安银行', 'main_force_inflow', {
        'eastmoney': {'value': 8919},
        'guosen':    {'value': 8920},
        'tushare':   {'value': 50000},  # 异常
    })
    print(f'  结果: {r}')

    print('\n=== 测试3：单源 ===')
    r = cross_validate('002475.SZ', '立讯精密', 'price', {
        'tencent': {'value': 73.7},
    })
    print(f'  结果: {r}')
