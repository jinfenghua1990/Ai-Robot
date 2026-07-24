"""
主题聚类模块
===========
将相关概念聚合成产业主线，过滤情绪标签

核心功能：
1. 过滤情绪标签（昨日连板、昨日涨停等）
2. 概念聚类到产业主线
3. 主力资金流向判断
4. 主线级别判定
"""

from typing import Any
from collections import defaultdict

# 需要过滤的情绪标签
SENTIMENT_TAGS = {
    "昨日连板",
    "昨日连板_含一字",
    "昨日涨停",
    "昨日涨停_含一字",
    "昨日首板",
    "今日涨停",
    "今日涨停_含一字",
    "连板",
    "首板",
    "涨停",
    "东方财富热股",
    "同花顺热股",
    "微盘股",
    "高价股",
    "低股价",
    "北证50",
    "北交所",
    "ST股",
    "*ST",
    "退市",
}

# 产业主线聚类映射
THEME_CLUSTERS = {
    "半导体": [
        "半导体", "芯片", "集成电路", "IC", "光刻机", "光刻胶", "EUV",
        "先进封装", "Chiplet", "HBM", "存储芯片", "GPU", "CPU",
        "AI芯片", "算力芯片", "汽车芯片", "功率半导体", "三代半导体",
        "氮化镓", "碳化硅", "GaN", "SiC",
    ],
    "AI人工智能": [
        "人工智能", "AI", "大模型", "AIGC", "ChatGPT", "GPT",
        "AI服务器", "AI算力", "AI芯片", "AI应用", "AI训练",
        "机器视觉", "自然语言", "语音识别", "知识图谱",
    ],
    "算力": [
        "算力", "服务器", "AI服务器", "液冷", "数据中心",
        "云计算", "边缘计算", "高性能计算", "HPC",
        "光模块", "CPO", "铜缆高速连接", "PCB", "光通信模块",
    ],
    "机器人": [
        "机器人", "工业机器人", "人形机器人", "服务机器人",
        "减速器", "伺服电机", "控制器", "机器视觉",
        "特斯拉供应链", "比亚迪供应链", "汽车零部件",
    ],
    "工业母机": [
        "工业母机", "数控机床", "机床", "CNC",
        "工业自动化", "PLC", "变频器", "传感器",
        "智能制造", "工业互联网", "MES",
    ],
    "新能源汽车": [
        "新能源车", "电动车", "新能源汽车", "比亚迪", "特斯拉",
        "锂电池", "动力电池", "固态电池", "钠离子电池",
        "锂矿", "正极", "负极", "电解液", "隔膜",
        "充电桩", "换电", "储能",
    ],
    "光伏": [
        "光伏", "太阳能", "硅片", "电池片", "组件",
        "逆变器", "支架", "银浆", "EVA",
        "TOPCon", "HJT", "钙钛矿",
    ],
    "风电": [
        "风电", "风机", "叶片", "塔筒", "海风",
        "整机", "铸件", "轴承",
    ],
    "电力": [
        "电力", "电网", "虚拟电厂", "电力改革",
        "水电", "火电", "核电", "绿电",
    ],
    "黄金": [
        "黄金", "贵金属", "金矿", "黄金概念", "避险",
    ],
    "有色金属": [
        "有色", "铜", "铝", "锌", "铅", "镍", "稀土",
        "小金属", "金属铜", "金属铝", "钨", "锑",
        "工业金属", "新材料", "稀土永磁",
    ],
    "化工": [
        "化工", "化学制品", "精细化工", "新材料",
        "钛白粉", "MDI", "TDI", "环氧丙烷",
    ],
    "医药医疗": [
        "医药", "中药", "创新药", "仿制药", "生物医药",
        "医疗器械", "医疗设备", "医疗服务", "医美",
        "疫苗", "体外诊断", "CXO",
    ],
    "消费电子": [
        "消费电子", "手机", "电子", "半导体", "元器件",
        "被动元件", "PCB", "FPC", "连接器",
        "VR", "AR", "MR", "智能穿戴", "TWS",
    ],
    "汽车": [
        "汽车", "整车", "零部件", "汽车零部件",
        "智能化", "自动驾驶", "车联网", "激光雷达",
    ],
    "地产建筑": [
        "房地产", "地产", "建筑", "建材", "家装",
        "园林", "物业", "保障房", "旧改",
    ],
    "银行金融": [
        "银行", "保险", "证券", "金融",
        "数字货币", "跨境支付", "金融科技",
    ],
    "军工": [
        "军工", "国防", "航天", "航空", "船舶",
        "无人机", "导弹", "卫星", "大飞机",
    ],
    "低空经济": [
        "低空经济", "eVTOL", "飞行汽车", "通航",
        "无人机", "空管", "低空基建",
    ],
    "数据要素": [
        "数据要素", "数据确权", "数据安全", "数据交易所",
        "大数据", "云计算", "数字经济", "智慧城市",
    ],
    "国企改革": [
        "国企改革", "央企", "国企", "混合所有制",
        "并购重组", "股权激励",
    ],
    "商业航天": [
        "商业航天", "卫星互联网", "火箭", "SpaceX",
    ],
    "白酒": [
        "白酒", "酿酒", "酒", "贵州茅台", "五粮液", "泸州老窖",
    ],
    "煤炭": [
        "煤炭", "煤", "动力煤", "焦煤", "炼焦煤",
    ],
    "游戏": [
        "游戏", "网络游戏", "手游", "电竞", "元宇宙", "短剧",
    ],
    "通信": [
        "通信", "5G", "6G", "光通信", "光纤", "运营商",
    ],
}

# 反向映射：概念 -> 产业
CONCEPT_TO_INDUSTRY = {}
for industry, keywords in THEME_CLUSTERS.items():
    for keyword in keywords:
        CONCEPT_TO_INDUSTRY[keyword] = industry


def filter_sentiment_tags(concepts: list) -> list:
    """过滤情绪标签，保留产业概念"""
    filtered = []
    for c in concepts:
        # 支持 dict 或 string 格式
        if isinstance(c, dict):
            # Check multiple possible name keys
            name = c.get("name") or c.get("board_name") or c.get("concept_name") or ""
        elif isinstance(c, str):
            name = c
        else:
            continue

        # 检查是否包含情绪标签关键词
        is_sentiment = False
        for tag in SENTIMENT_TAGS:
            if tag in name:
                is_sentiment = True
                break
        if not is_sentiment:
            filtered.append(c)
    return filtered


def cluster_concepts(concepts: list) -> tuple[list[dict], list]:
    """
    将概念聚类到产业主线
    返回：([{industry, concepts: [], total_change, avg_strength, ...}], unclustered)
    """
    # 按产业分组
    industry_groups: dict[str, list] = defaultdict(list)
    unclustered = []

    for c in concepts:
        # 支持 dict 或 string 格式
        if isinstance(c, dict):
            name = c.get("name", "")
            change = c.get("change", 0)
            strength = c.get("strength", 0)
            hot = c.get("hot", 0)
        elif isinstance(c, str):
            name = c
            change = 0
            strength = 0
            hot = 0
        else:
            continue

        matched = False

        # 精确匹配
        if name in CONCEPT_TO_INDUSTRY:
            industry = CONCEPT_TO_INDUSTRY[name]
            industry_groups[industry].append(c)
            matched = True
        else:
            # 模糊匹配
            for keyword, industry in CONCEPT_TO_INDUSTRY.items():
                if keyword in name:
                    industry_groups[industry].append(c)
                    matched = True
                    break

        if not matched:
            unclustered.append(c)

    # 构建聚类结果
    result = []
    for industry, items in industry_groups.items():
        if not items:
            continue

        # 计算汇总指标（支持 dict 或 string 格式）
        total_change = 0
        total_strength = 0
        total_hot = 0
        concept_names = []
        valid_items = []

        for item in items:
            if isinstance(item, dict):
                total_change += item.get("change", 0) or 0
                total_strength += item.get("strength", 0) or 0
                total_hot += item.get("hot", 0) or 0
                concept_names.append(item.get("name", ""))
                valid_items.append(item)
            elif isinstance(item, str):
                concept_names.append(item)

        avg_change = total_change / len(items) if items else 0
        avg_strength = total_strength / len(items) if items else 0
        max_flow = max((item.get("capital_flow", 0) or 0) for item in valid_items) if valid_items else 0

        result.append({
            "industry": industry,
            "concepts": concept_names,
            "concept_details": valid_items,
            "change": round(avg_change, 2),
            "strength": round(avg_strength, 1),
            "hot": total_hot,
            "capital_flow": max_flow,
            "count": len(items),
        })

    # 按涨幅排序
    result.sort(key=lambda x: x.get("change", 0), reverse=True)

    return result, unclustered


def determine_theme_level(item: dict[str, Any], history: list[dict] = None) -> str:
    """
    判断主线级别
    核心主线 / 次主线 / 支线 / 防御线 / 情绪线
    """
    change = item.get("change", 0) or 0
    strength = item.get("strength", 0) or 0
    capital_flow = item.get("capital_flow", 0) or 0
    count = item.get("count", 0)

    # 核心主线：涨幅>2%，强度>80，资金强流入
    if change > 2 and strength > 80 and capital_flow > 0:
        return "核心主线"

    # 次主线：涨幅>1.5%，强度>60，资金流入
    if change > 1.5 and strength > 60 and capital_flow >= 0:
        return "次主线"

    # 支线：涨幅>1%，有资金支撑
    if change > 1 and strength > 40:
        return "支线"

    # 防御线：黄金等避险板块
    if item.get("industry") in ["黄金", "电力", "银行金融"]:
        return "防御线"

    # 情绪线：涨幅大但无实质
    if strength > 70 and capital_flow < 0:
        return "情绪线"

    return "支线"


def determine_persistence(industry: str, history: list[dict] = None) -> str:
    """
    判断持续性
    3日增强 / 增强 / 轮动 / 修复 / 衰减
    """
    if not history:
        return "轮动"

    # 获取近3日该行业的数据
    industry_data = [h for h in history if h.get("industry") == industry]
    if len(industry_data) < 2:
        return "轮动"

    # 按日期排序
    sorted_data = sorted(industry_data, key=lambda x: x.get("date", ""))
    changes = [d.get("change", 0) or 0 for d in sorted_data]

    # 近3日变化趋势
    if len(changes) >= 3 and changes[-1] > changes[-2] > changes[-3]:
        return "3日增强"
    if len(changes) >= 2 and changes[-1] > changes[-2]:
        return "增强"
    if len(changes) >= 2 and changes[-1] < changes[-2] * 0.5:
        return "衰减"
    if len(changes) >= 2 and changes[-1] < 0 and changes[-2] < 0:
        return "修复"

    return "轮动"


def determine_market定性(industry: str, theme_level: str) -> str:
    """判断市场定性"""
    mapping = {
        ("半导体", "核心主线"): "科技核心",
        ("AI人工智能", "核心主线"): "AI浪潮",
        ("算力", "核心主线"): "算力爆发",
        ("新能源汽车", "核心主线"): "新能源车",
        ("机器人", "核心主线"): "制造升级",
        ("工业母机", "核心主线"): "制造升级",
        ("黄金", "防御线"): "防御避险",
        ("医药医疗", "核心主线"): "医药创新",
        ("消费电子", "核心主线"): "消费电子",
    }
    return mapping.get((industry, theme_level), "轮动")


def build_market_structure(
    concepts: list[dict],
    industry_moneyflow: list[dict] = None,
    stock_moneyflow: list[dict] = None,
    history: list[dict] = None,
) -> dict[str, Any]:
    """
    构建市场主线与轮动结构
    """
    # 1. 过滤情绪标签
    filtered = filter_sentiment_tags(concepts)

    # 2. 聚类
    clustered, unclustered = cluster_concepts(filtered)

    # 3. 判定主线级别
    for item in clustered:
        item["theme_level"] = determine_theme_level(item, history)
        item["persistence"] = determine_persistence(item["industry"], history)
        item["market定性"] = determine_market定性(item["industry"], item["theme_level"])

    # 4. 构建输出
    return {
        "clusters": clustered,
        "unclustered": unclustered,
        "sentiment_filtered": len(concepts) - len(filtered),
    }


# 测试
if __name__ == "__main__":
    test_concepts = [
        {"name": "半导体", "change": 2.5, "strength": 85, "capital_flow": 1000},
        {"name": "先进封装", "change": 2.3, "strength": 82, "capital_flow": 800},
        {"name": "Chiplet", "change": 2.1, "strength": 80, "capital_flow": 600},
        {"name": "昨日连板", "change": 5.0, "strength": 95, "capital_flow": -100},
        {"name": "黄金", "change": 1.5, "strength": 70, "capital_flow": 500},
    ]

    result = build_market_structure(test_concepts)
    import json
    print(json.dumps(result, ensure_ascii=False, indent=2))
