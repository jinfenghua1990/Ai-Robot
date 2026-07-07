# -*- coding: utf-8 -*-
"""
ETF智能筛选脚本
支持专业榜单筛选（接口46.18）和自定义筛选（接口46.20）
"""

import os
import sys
import argparse
import json
import ssl
import time
import pandas as pd
import httpx

# API基础地址（测试环境，后续切换生产环境时修改此处）
BASE_URL = "https://dgzt.guosen.com.cn/skills/gsfinancing/selected/ETF"

# 筛选结果最多返回条数
MAX_RESULTS = 100

# 专业榜单配置
PROFESSIONAL_LISTS = {
    (1, 11): {"name": "热点赛道", "classId": 1, "listId": 11},
    (1, 13): {"name": "T+0短线突破", "classId": 1, "listId": 13},
    (2, 21): {"name": "高分红低波动", "classId": 2, "listId": 21},
    (2, 22): {"name": "能涨又能跌", "classId": 2, "listId": 22},
    (2, 23): {"name": "低估且优质", "classId": 2, "listId": 23},
    (2, 24): {"name": "低估且弹性大", "classId": 2, "listId": 24},
    (2, 25): {"name": "稳做绩优生", "classId": 2, "listId": 25},
    (3, 31): {"name": "全市场热门", "classId": 3, "listId": 31},
    (3, 32): {"name": "平衡资产配置", "classId": 3, "listId": 32},
}

# 接口46.18 ETF字段中文名映射（基于接口文档 + 实际返回）
FIELD_MAP_4618 = {
    "ofcode": "产品代码",
    "ofname": "产品名称",
    "market": "市场",
    "day5range": "近5日涨幅",
    "day5Rage": "近5日涨幅",
    "profit": "收益",
    "nowrange": "实时涨跌",
    "nowRage": "实时涨跌",
    "nowprice": "最新价",
    "endamt": "最新规模",
    "ismatch": "是否匹配",
    "matchamt": "最新成交额",
    "isopt": "是否自选",
    "day60range": "近60日涨幅",
    "isT0": "是否T+0",
    "etflabel": "ETF标签",
    "perfomance": "业绩",
    "etfdes": "ETF描述",
    "zcgName": "资产管理公司",
    "perfomanceName": "业绩名称",
    "des": "描述",
}

# 接口46.20 ETF字段中文名映射（基于接口文档 + 实际返回）
FIELD_MAP_4620 = {
    "ofcode": "产品代码",
    "ofname": "产品名称",
    "market": "市场",
    "nowprice": "最新价",
    "nowrange": "实时涨跌",
    "avgrange": "平均涨跌幅",
    "isopt": "是否自选",
    "matchamt": "成交额(万)",
    "endamt": "规模(亿)",
    "class1": "一级类型",
    "class2": "二级类型",
    "temperRegion": "指数估值",
    "temperRegion1": "指数估值(精简)",
    "estyear": "成立年限",
    "tgfandglf": "费率",
    "tacode": "基金公司",
    "taName": "基金公司名称",
    "mgrAmount": "基金经理规模",
    "isT0": "是否T+0",
    "isrzrq": "是否融资融券",
    "is20perrange": "是否20%涨跌幅",
    "isdxtp": "是否短线突破",
    "isLowwave": "是否低波",
    "profit1w": "近1周收益",
    "profit1m": "近1月收益",
    "profit3m": "近3月收益",
    "profit6m": "近6月收益",
    "profit1y": "近1年收益",
    "profit3y": "近3年收益",
    "profit5y": "近5年收益",
    "profitthisy": "今年来收益",
    "profitthisyear": "今年来收益",
    "profitest": "成立以来收益",
    "profit1wrank": "近1周排名",
    "profit1mrank": "近1月排名",
    "profit3mrank": "近3月排名",
    "profit6mrank": "近6月排名",
    "profit1yrank": "近1年排名",
    "profit3yrank": "近3年排名",
    "profit5yrank": "近5年排名",
    "profitthisyrank": "今年来排名",
    "profitestrank": "成立以来排名",
    "profitsinceyrank": "成立以来排名",
    "profitthisyyrank": "近1年年化排名",
    "dt1y": "定投1年",
    "dt3y": "定投3年",
    "dt5y": "定投5年",
    "drawback1m": "近1月回撤",
    "drawback3m": "近3月回撤",
    "drawback6m": "近6月回撤",
    "drawback1y": "近1年回撤",
    "drawback3y": "近3年回撤",
    "drawback5y": "近5年回撤",
    "drawbackthisy": "今年来回撤",
    "drawbackest": "成立以来回撤",
    "std6mrank": "近6月波动率排名",
    "std1yrank": "近1年波动率排名",
    "std3yrank": "近3年波动率排名",
    "sharpe1yrank": "近1年夏普比率",
    "sharpe3yrank": "近3年夏普比率",
    "sharpe6mrank": "近6月夏普比率",
    "range3d": "近3日涨跌幅",
    "range5d": "近5日涨跌幅",
    "range10d": "近10日涨跌幅",
    "range20d": "近20日涨跌幅",
    "range60d": "近60日涨跌幅",
    "rangethisy": "今年来涨跌幅",
    "premiumrate": "溢价率",
    "avg20dmatchamt": "20日日均成交额",
    "hayjqidu": "行业景气度",
    "diviendyield": "指数股息率",
    "hotrank": "人气排名",
    "hyqsdu": "行业趋势度",
}


NO_API_KEY_MSG = """
该技能依赖国信证券小信智慧助手的数据服务，需要先配置API Key。
配置步骤:
1. 访问  https://www.guosen.com.cn/gs/xxskills/index.html 注册/登录账号
2. 登录后获取您的API Key。登录位置：网页一级标题栏-登录。登录后，点击账号，在弹窗上可一键复制API Key。
3. 在技能凭证配置中填入API Key
""".strip()


def get_api_key():
    """从环境变量获取API Key"""
    skill_id = "7627056463827140634"
    api_key = os.getenv(f"COZE_GUOSEN_API_KEY_{skill_id}")
    if not api_key:
        print(NO_API_KEY_MSG)
        sys.exit(1)
    return api_key


def call_api(url, params=None, api_key=None):
    """调用API接口，apiKey和softName作为URL参数传递"""
    params = params or {}
    params["softName"] = "goldsun_skills"
    params["skillName"] = "gs-etf-filter"
    if api_key:
        params["apiKey"] = api_key
    try:
        ssl_ctx = ssl.create_default_context()
        ssl_ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT，兼容旧版TLS协商
        with httpx.Client(timeout=30, verify=ssl_ctx) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPError as e:
        print(f"API调用失败: {e}")
        return None
    except Exception as e:
        print(f"请求异常: {e}")
        return None


def get_professional_list(class_id, list_id, api_key=None, order_col="nowrange", order_type="0", user_code=None):
    """调用接口46.18 - 专业榜单筛选"""
    url = f"{BASE_URL}/filterListDetail/1.0"
    params = {
        "classId": str(class_id),
        "listId": str(list_id),
        "orderCol": order_col,
        "orderType": order_type
    }
    if user_code:
        params["userCode"] = user_code
    print(f"\n调用专业榜单接口: classId={class_id}, listId={list_id}")
    return call_api(url, params, api_key=api_key)


def get_custom_filter(api_key=None, **kwargs):
    """调用接口46.20 - 自定义筛选"""
    url = f"{BASE_URL}/filterSearch/1.0"
    params = {
        "orderCol": kwargs.get("order_col", "nowrange"),
        "orderType": kwargs.get("order_type", "0")
    }
    # 映射参数名
    param_map = {
        "user_code": "userCode", "class1": "class1", "class2": "class2",
        "endamt": "endamt", "estyear": "estyear", "tgfandglf": "tgfandglf",
        "tacode": "tacode", "mgrAmount": "mgrAmount",
        "isT0": "isT0", "isrzrq": "isrzrq", "is20perrange": "is20perrange",
        "isdxtp": "isdxtp", "isLowwave": "isLowwave",
        "profit": "profit", "profitrank": "profitrank", "dt": "dt",
        "drawback": "drawback", "std": "std", "sharpe": "sharpe",
        "pricerange": "pricerange", "premiumrate": "premiumrate",
        "matchamt": "matchamt", "avg20dmatchamt": "avg20dmatchamt",
        "temperRegion": "temperRegion", "temperRegion1": "temperRegion1",
        "hayjqidu": "hayjqidu", "diviendyield": "diviendyield",
        "hotrank": "hotrank", "hyqsdu": "hyqsdu",
        "filter_flag": "filterFlag",
    }
    for local_name, api_name in param_map.items():
        value = kwargs.get(local_name)
        if value is not None:
            params[api_name] = value
    print(f"\n调用自定义筛选接口")
    return call_api(url, params, api_key=api_key)


def rename_fields(etf_dict, field_map):
    """根据字段映射字典，将API字段名转为中文名。未映射的字段保留原名。"""
    renamed = {}
    for k, v in etf_dict.items():
        new_key = field_map.get(k, k)
        renamed[new_key] = v
    return renamed


def parse_professional_result(data):
    """
    解析接口46.18专业榜单结果。
    API返回结构: {"result": [...], "data": [{listName, listDes, listLabel, list: [ETF对象]}]}
    ETF对象字段完全保留原始返回。
    """
    if not data or "data" not in data:
        print("数据为空或无data字段")
        return [], {}

    data_obj = data["data"]
    if not isinstance(data_obj, list) or len(data_obj) == 0:
        return [], {}

    list_data = data_obj[0]
    list_name = list_data.get("listName", "")
    list_des = list_data.get("listDes", "")
    list_label = list_data.get("listLabel", "")
    list_profit = list_data.get("listprofit", "")
    profit_type = list_data.get("profitType", "")
    filter_info = list_data.get("filterInfoList", "")

    print(f"\n榜单名称: {list_name}")
    print(f"榜单描述: {list_des}")
    print(f"榜单标签: {list_label}")
    print(f"收益类型: {profit_type}")
    print(f"榜单平均收益: {list_profit}")

    info = {
        "榜单名称": list_name,
        "榜单描述": list_des,
        "榜单标签": list_label,
        "收益类型": profit_type,
        "榜单平均收益": list_profit,
    }

    etf_list = list_data.get("list", [])
    results = [rename_fields(etf, FIELD_MAP_4618) for etf in etf_list]
    if len(results) > MAX_RESULTS:
        print(f"结果超过{MAX_RESULTS}条，截取前{MAX_RESULTS}条")
        results = results[:MAX_RESULTS]
    return results, info


def parse_custom_result(data):
    """
    解析接口46.20自定义筛选结果。
    API返回结构: {"result": [...], "data": [ETF对象, ...], "data1": [{etfNum: ...}]}
    ETF对象字段完全保留原始返回。
    """
    if not data or "data" not in data:
        return [], {}

    data_obj = data["data"]
    info = {}

    # 获取总记录数
    data1 = data.get("data1")
    if data1:
        if isinstance(data1, list) and len(data1) > 0:
            info["总记录数"] = data1[0].get("etfNum", str(len(data_obj)))
        elif isinstance(data1, dict):
            info["总记录数"] = data1.get("etfNum", str(len(data_obj)))

    if isinstance(data_obj, list):
        results = [rename_fields(etf, FIELD_MAP_4620) for etf in data_obj]
    else:
        results = []

    if len(results) > MAX_RESULTS:
        print(f"结果超过{MAX_RESULTS}条，截取前{MAX_RESULTS}条")
        results = results[:MAX_RESULTS]

    print(f"\n符合筛选条件的ETF数量: {len(results)}")
    return results, info


def save_results(results, info, output_dir, prefix="gs-etf-filter"):
    """保存筛选结果到Excel和文本文件"""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")

    excel_file = os.path.join(output_dir, f"{prefix}_{timestamp}.xlsx")
    txt_file = os.path.join(output_dir, f"{prefix}_{timestamp}.txt")

    # 保存Excel - 使用API返回的所有字段
    if results:
        df = pd.DataFrame(results)
        df.to_excel(excel_file, index=False)
        print(f"\nExcel文件: {excel_file}")
        print(f"Excel列名: {list(df.columns)}")

    # 保存文本描述
    with open(txt_file, "w", encoding="utf-8") as f:
        f.write("=" * 50 + "\n")
        f.write("ETF筛选结果\n")
        f.write("=" * 50 + "\n\n")
        if info:
            for k, v in info.items():
                f.write(f"{k}: {v}\n")
            f.write("\n")
        f.write(f"筛选到 {len(results)} 只ETF\n\n")
        for i, etf in enumerate(results, 1):
            code = etf.get("产品代码", "")
            name = etf.get("产品名称", "")
            f.write(f"{i}. {code} - {name}\n")
            # 写入该ETF的所有字段值
            for k, v in etf.items():
                if k not in ("产品代码", "产品名称") and v != "":
                    f.write(f"   {k}: {v}\n")
            f.write("\n")
    print(f"描述文件: {txt_file}")
    return excel_file, txt_file


def is_professional_list_mode(args):
    """判断是否使用专业榜单模式"""
    if args.class_id is not None and args.list_id is not None:
        return (args.class_id, args.list_id) in PROFESSIONAL_LISTS
    return False


def main():
    parser = argparse.ArgumentParser(
        description="ETF智能筛选工具 - 支持专业榜单和自定义筛选",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # 专业榜单筛选
  python get_data.py --class-id 2 --list-id 21
  python get_data.py --class-id 1 --list-id 13 --order-col nowrange

  # 自定义筛选
  python get_data.py --class1 2 --endamt "10,100000" --tgfandglf "0,0.5"
  python get_data.py --class1 1 --profitrank "profit1yrank:25"
  python get_data.py --class1 1 --order-col sharpe1yrank --order-type 1
        """
    )

    # 专业榜单参数
    parser.add_argument("--class-id", type=int, choices=[1, 2, 3],
                        help="榜单分类: 1-短线热榜, 2-中长期精选, 3-特色品种")
    parser.add_argument("--list-id", type=int,
                        help="榜单ID: classId=1时11-热点赛道/13-T+0短线突破; "
                             "classId=2时21-高分红低波动/22-能涨又能跌/23-低估且优质/24-低估且弹性大/25-稳做绩优生; "
                             "classId=3时31-全市场热门/32-平衡资产配置")

    # 通用参数
    parser.add_argument("--order-col", default="nowrange",
                        help="排序字段 (默认: nowrange)")
    parser.add_argument("--order-type", default="0", choices=["0", "1"],
                        help="排序类型: 0-降序, 1-升序 (默认: 0)")
    parser.add_argument("--user-code",
                        help="用户代码 (查自选时必传)")
    parser.add_argument("--output-dir",
                        help="输出目录")

    # 自定义筛选参数 - 基本信息
    parser.add_argument("--class1",
                        help="一级类型: 1-行业, 2-宽基, 3-风格策略, 4-跨境, 5-债券, 6-黄金, 7-货币")
    parser.add_argument("--class2",
                        help="二级类型: 科技-11, 金融地产-12, 军工-13, 制造-14, 消费-15, 医药-16, 周期-17, 其它-18等")
    parser.add_argument("--endamt",
                        help="规模(亿): 如10,50表示10-50亿, 0,1表示0-1亿")
    parser.add_argument("--estyear",
                        help="成立年限: 大于等于n年传n")
    parser.add_argument("--tgfandglf",
                        help="费率(托管费+管理费): 如0,0.3表示小于等于0.3%%")
    parser.add_argument("--tacode",
                        help="基金公司代码")
    parser.add_argument("--mgr-amount",
                        help="基金经理规模(亿): 如5,10表示5-10亿")

    # 自定义筛选参数 - 交易属性
    parser.add_argument("--is-t0", action="store_const", const="1",
                        help="是否T+0")
    parser.add_argument("--is-rzrq", action="store_const", const="1",
                        help="是否融资融券")
    parser.add_argument("--is-20perrange", action="store_const", const="1",
                        help="是否20%%涨跌幅")
    parser.add_argument("--is-dxtp", action="store_const", const="1",
                        help="是否短线突破")
    parser.add_argument("--is-lowwave", action="store_const", const="1",
                        help="是否低波")

    # 自定义筛选参数 - 收益表现
    parser.add_argument("--profit",
                        help="净值涨跌幅: 格式如profit1w:5,6;profit1m:-5.2,6.9")
    parser.add_argument("--profitrank",
                        help="涨跌幅排名: 格式如profit1wrank:5.6;profit1mrank:6.9")
    parser.add_argument("--dt",
                        help="定投回测: 格式如dt1y:5,6;dt3y:-5.2,6.9")

    # 自定义筛选参数 - 风险波动
    parser.add_argument("--drawback",
                        help="回撤: 格式如drawback1m:5.6;drawback1y:20")
    parser.add_argument("--std",
                        help="波动率: 格式如std1yrank:5.6")
    parser.add_argument("--sharpe",
                        help="夏普比率: 格式如sharpe1yrank:5.6")

    # 自定义筛选参数 - 行情指标
    parser.add_argument("--pricerange",
                        help="价格涨跌幅: 格式如range5d:5,6;range10d:-5.2,6.9")
    parser.add_argument("--premiumrate",
                        help="溢价率: 如5,6表示5%%到6%%")
    parser.add_argument("--matchamt",
                        help="成交额(万): 如0,100表示100万以下,100000,100000000表示10亿以上")
    parser.add_argument("--avg20dmatchamt",
                        help="20日日均成交额(万)")

    # 自定义筛选参数 - 基本面
    parser.add_argument("--temper-region",
                        help="指数估值: 1-高温,2-较高温,3-常温,4-较低温,5-低温,多个用分号连接")
    parser.add_argument("--temper-region1",
                        help="指数估值(精简): 1-高温,2-常温,3-低温")
    parser.add_argument("--hayjqidu",
                        help="行业景气度: 高:-3,中:-2,低:-1")
    parser.add_argument("--diviendyield",
                        help="指数股息率: 如5,6表示5%%到6%%")

    # 自定义筛选参数 - 趋势热度
    parser.add_argument("--hotrank",
                        help="人气排名: 如100表示前100名")
    parser.add_argument("--hyqsdu",
                        help="行业趋势度: 强:-3,中:-2,弱:-1")

    # 其他
    parser.add_argument("--filter-flag",
                        help="筛选类型: 1-只返回数量")

    args = parser.parse_args()

    # 从环境变量获取API Key
    api_key = get_api_key()

    # 确定输出目录
    if args.output_dir:
        output_dir = args.output_dir
    else:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(os.path.dirname(script_dir), "output")

    if is_professional_list_mode(args):
        # ========== 专业榜单接口46.18 ==========
        print("=" * 50)
        print("使用专业榜单筛选模式")
        print("=" * 50)

        result = get_professional_list(
            class_id=args.class_id,
            list_id=args.list_id,
            api_key=api_key,
            order_col=args.order_col,
            order_type=args.order_type,
            user_code=args.user_code
        )

        if not result:
            print("获取数据失败")
            sys.exit(1)

        results, info = parse_professional_result(result)
        excel_file, txt_file = save_results(results, info, output_dir)
        print(f"\n文件: {excel_file}")
        print(f"描述: {txt_file}")
        print(f"ETF数量: {len(results)}")
    else:
        # ========== 自定义筛选接口46.20 ==========
        print("=" * 50)
        print("使用自定义筛选模式")
        print("=" * 50)

        result = get_custom_filter(
            api_key=api_key,
            order_col=args.order_col,
            order_type=args.order_type,
            user_code=args.user_code,
            class1=args.class1,
            class2=args.class2,
            endamt=args.endamt,
            estyear=args.estyear,
            tgfandglf=args.tgfandglf,
            tacode=args.tacode,
            mgrAmount=args.mgr_amount,
            isT0=args.is_t0,
            isrzrq=args.is_rzrq,
            is20perrange=args.is_20perrange,
            isdxtp=args.is_dxtp,
            isLowwave=args.is_lowwave,
            profit=args.profit,
            profitrank=args.profitrank,
            dt=args.dt,
            drawback=args.drawback,
            std=args.std,
            sharpe=args.sharpe,
            pricerange=args.pricerange,
            premiumrate=args.premiumrate,
            matchamt=args.matchamt,
            avg20dmatchamt=args.avg20dmatchamt,
            temperRegion=args.temper_region,
            temperRegion1=args.temper_region1,
            hayjqidu=args.hayjqidu,
            diviendyield=args.diviendyield,
            hotrank=args.hotrank,
            hyqsdu=args.hyqsdu,
            filter_flag=args.filter_flag,
        )

        if result is None:
            print("获取数据失败")
            sys.exit(1)

        results, info = parse_custom_result(result)
        excel_file, txt_file = save_results(results, info, output_dir)
        print(f"\n文件: {excel_file}")
        print(f"描述: {txt_file}")
        print(f"ETF数量: {len(results)}")


if __name__ == "__main__":
    main()
