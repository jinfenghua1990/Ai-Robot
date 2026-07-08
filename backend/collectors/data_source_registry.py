"""
数据源注册器 - 可扩展的多数据源管理
后续添加新数据源只需要在 DATA_SOURCES 中添加一条配置 + 实现采集函数
"""
import os
from utils.http_constants import clear_proxy_env

clear_proxy_env()


# ============================================================
# 数据源配置表（后续扩展只需在此添加配置）
# ============================================================
DATA_SOURCES = {
    # === 已集成的数据源 ===
    'eastmoney': {
        'display_name': '东方财富',
        'rate_limited': True,        # 有额度限制，少用
        'indicators': ['main_force_inflow', 'price', 'price_chg', 'sector_flow', 'net_inflow'],
        'priority': 1,               # 优先级（数字越小越优先）
        'available': True,
        'protocol': 'HTTP',
        'note': 'datacenter接口，有额度限制，全市场批量',
    },
    'em_push2': {
        'display_name': '东财push2',
        'rate_limited': False,       # 无额度限制
        'indicators': ['main_force_inflow', 'price'],
        'priority': 2,
        'available': True,
        'protocol': 'HTTP',
        'note': 'push2.eastmoney.com，无额度限制，个股逐个查询',
    },
    'sina': {
        'display_name': '新浪财经',
        'rate_limited': False,
        'indicators': ['sector_flow', 'price', 'price_chg'],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': '板块资金流向主源，个股实时行情可用',
    },
    'tencent': {
        'display_name': '腾讯财经',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'pe_ttm', 'pb', 'mcap'],
        'priority': 2,
        'available': True,
        'protocol': 'HTTP',
        'note': 'qt.gtimg.cn，批量行情，a-stock-data底层数据源',
    },
    'tdx': {
        'display_name': '通达信',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline', 'quote'],
        'priority': 3,
        'available': True,
        'protocol': 'TCP',
        'note': 'pytdx TCP协议，不封IP，无额度限制',
    },
    'akshare': {
        'display_name': 'AKShare',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'main_force_inflow', 'sector_flow'],
        'priority': 3,
        'available': True,
        'protocol': 'HTTP',
        'note': '开源库，整合东财/新浪/同花顺，实时行情可用(新浪)',
    },
    'guosen': {
        'display_name': '国信证券',
        'rate_limited': True,        # 有额度限制，少用
        'indicators': ['main_force_inflow', 'price', 'price_chg'],
        'priority': 4,
        'available': True,
        'protocol': 'HTTP',
        'note': '有API Key额度限制，仅Top10验证',
    },
    'tushare': {
        'display_name': 'Tushare',
        'rate_limited': True,        # 有额度限制
        'indicators': ['main_force_inflow', 'price', 'price_chg', 'daily'],
        'priority': 5,
        'available': True,
        'protocol': 'HTTP',
        'note': '有积分限制，降级使用',
    },

    # === 扩展数据源（已测试启用）===
    'efinance': {
        'display_name': 'efinance',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'main_force_inflow', 'financial_report'],
        'priority': 4,
        'available': True,
        'protocol': 'HTTP',
        'note': '开源库，基于东财数据，行情/资金/财报',
    },
    'qstock': {
        'display_name': 'qstock',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'main_force_inflow', 'research_report'],
        'priority': 5,
        'available': True,
        'protocol': 'HTTP',
        'note': '开源库，整合多源，行情/资金/研报',
    },
    'adata': {
        'display_name': 'adata',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline'],
        'priority': 4,
        'available': True,
        'protocol': 'HTTP',
        'note': '开源库，聚合多源，日线/分钟线',
    },
    'ths': {
        'display_name': '同花顺',
        'rate_limited': False,
        'indicators': ['main_force_inflow', 'price', 'dragon_tiger'],
        'priority': 3,
        'available': True,
        'protocol': 'HTTP',
        'note': 'data.10jqka.com.cn，资金流向/龙虎榜，反爬降级容错',
    },
    'netease': {
        'display_name': '网易财经',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline'],
        'priority': 4,
        'available': True,           # 启用但可能不稳定
        'protocol': 'HTTP',
        'note': 'api.money.126.net，SSL不稳定，自动降级',
    },
    'cninfo': {
        'display_name': '巨潮资讯',
        'rate_limited': False,
        'indicators': ['announcement', 'financial_report'],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': 'cninfo.com.cn，公告/财报权威源',
    },
    'mootdx': {
        'display_name': 'mootdx',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline', 'quote'],
        'priority': 3,
        'available': True,
        'protocol': 'TCP',
        'note': '通达信TCP增强版，无额度限制，TCP协议不封IP',
    },

    # === 新增数据源（2024扩展）===
    'baostock': {
        'display_name': 'baostock',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline', 'daily'],
        'priority': 5,
        'available': True,
        'protocol': 'TCP',
        'note': '免费开源，无token，日K线/分钟线，盘后数据',
    },
    'sina_quote': {
        'display_name': '新浪行情',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'quote'],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': 'hq.sinajs.cn，批量实时行情，无额度限制，极速',
    },
    'tencent_kline': {
        'display_name': '腾讯K线',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline'],
        'priority': 2,
        'available': True,
        'protocol': 'HTTP',
        'note': 'web.ifzq.gtimg.cn，前复权K线，无额度限制',
    },

    # === 新增数据源（2026扩展）===
    'itick': {
        'display_name': 'iTick',
        'rate_limited': False,
        'indicators': ['price', 'price_chg', 'kline', 'quote'],
        'priority': 2,
        'available': True,
        'protocol': 'HTTP',
        'note': 'itick.org，A股/港股/美股实时行情，HTTP+WebSocket，延迟200ms，免费5次/秒',
    },
    'jqdata': {
        'display_name': '聚宽数据',
        'rate_limited': True,
        'indicators': ['price', 'price_chg', 'daily', 'financial_report', 'kline'],
        'priority': 4,
        'available': True,
        'protocol': 'HTTP',
        'note': 'JoinQuant jqdatasdk，高质量A股数据，日K/财务/指数成分股，免费额度',
    },

    # === Vibe-Research 深度数据源（接入 AIROBOT，作为二级数据源）===
    # 实时行情/资金/龙虎榜/概念板块优先走 AIROBOT 自有源；
    # 财报/估值/研报/公告/新闻/互动易/解禁/大宗/股东户数/美港股/资讯雷达优先走 Vibe。
    'vibe_astock': {
        'display_name': 'Vibe-Research A股深度',
        'rate_limited': False,
        'indicators': [
            'valuation', 'financials', 'finance', 'financial_report', 'reports', 'research_report',
            'news', 'announcements', 'announcement', 'disclosure', 'margin', 'block_trade',
            'holders', 'dividend', 'fund_flow', 'dragon_tiger', 'lockup', 'blocks',
            'hot_concepts', 'investor_qa', 'industry', 'kline', 'info',
        ],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': 'Vibe-Research 东财接口聚合，财报/估值/研报/公告/新闻/筹码/资金面/解禁/板块',
    },
    'vibe_newsradar': {
        'display_name': 'Vibe-Research 资讯雷达',
        'rate_limited': False,
        'indicators': ['news_radar', 'rss_feed'],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': 'Vibe-Research 108 赛道 RSS 资讯雷达',
    },
    'vibe_market': {
        'display_name': 'Vibe-Research 市场总览',
        'rate_limited': False,
        'indicators': ['market_overview', 'market_emotion', 'turnover_top', 'global_indices'],
        'priority': 2,
        'available': True,
        'protocol': 'HTTP',
        'note': 'Vibe-Research 市场总览/短线情绪/成交额榜/全球指数，作为 AIROBOT 补充',
    },
    'vibe_gstock': {
        'display_name': 'Vibe-Research 美港股',
        'rate_limited': False,
        'indicators': ['global_stock', 'us_hk_quote'],
        'priority': 1,
        'available': True,
        'protocol': 'HTTP',
        'note': 'Vibe-Research 东财域内美港股聚合，作为 AIROBOT global_market 补充',
    },
}


def get_all_sources():
    """获取所有数据源配置（含未启用的）"""
    return DATA_SOURCES


def get_available_sources():
    """获取所有已启用的数据源"""
    return {k: v for k, v in DATA_SOURCES.items() if v['available']}


def get_sources_for_indicator(indicator):
    """获取支持某指标的所有可用数据源，按优先级排序"""
    sources = [(k, v) for k, v in DATA_SOURCES.items()
               if v['available'] and indicator in v['indicators']]
    return sorted(sources, key=lambda x: x[1]['priority'])


def get_unlimited_sources(indicator=None):
    """获取无额度限制的数据源（用于高频采集）"""
    sources = {k: v for k, v in DATA_SOURCES.items()
               if v['available'] and not v['rate_limited']}
    if indicator:
        sources = {k: v for k, v in sources.items() if indicator in v['indicators']}
    return sources


def get_rate_limited_sources(indicator=None):
    """获取有额度限制的数据源（用于低频验证）"""
    sources = {k: v for k, v in DATA_SOURCES.items()
               if v['available'] and v['rate_limited']}
    if indicator:
        sources = {k: v for k, v in sources.items() if indicator in v['indicators']}
    return sources


def register_source(name, config):
    """动态注册新数据源（运行时扩展）
    config = {
        'display_name': 'xxx',
        'rate_limited': False,
        'indicators': ['price', ...],
        'priority': 5,
        'available': True,
        'protocol': 'HTTP',
        'note': 'xxx',
    }
    """
    DATA_SOURCES[name] = config
    print(f'[registry] Registered data source: {name} ({config.get("display_name", "")})')


def get_source_info():
    """获取数据源统计信息（供前端展示）"""
    all_sources = list(DATA_SOURCES.values())
    available = [s for s in all_sources if s['available']]
    unlimited = [s for s in available if not s['rate_limited']]
    rate_limited = [s for s in available if s['rate_limited']]
    pending = [s for s in all_sources if not s['available']]

    # 按指标统计
    indicator_coverage = {}
    for s in available:
        for ind in s['indicators']:
            if ind not in indicator_coverage:
                indicator_coverage[ind] = []
            indicator_coverage[ind].append(s['display_name'])

    return {
        'total': len(all_sources),
        'available_count': len(available),
        'unlimited_count': len(unlimited),
        'rate_limited_count': len(rate_limited),
        'pending_count': len(pending),
        'indicator_coverage': indicator_coverage,
        'sources': DATA_SOURCES,
    }


if __name__ == '__main__':
    info = get_source_info()
    print(f"数据源总数: {info['total']}")
    print(f"已启用: {info['available_count']} (无限制: {info['unlimited_count']}, 有额度: {info['rate_limited_count']})")
    print(f"待集成: {info['pending_count']}")
    print("\n=== 按指标覆盖 ===")
    for ind, sources in info['indicator_coverage'].items():
        print(f"  {ind}: {', '.join(sources)}")
    print("\n=== 支持主力净流入的无限制数据源 ===")
    for name, cfg in get_unlimited_sources('main_force_inflow').items():
        print(f"  {cfg['display_name']} (优先级:{cfg['priority']})")
