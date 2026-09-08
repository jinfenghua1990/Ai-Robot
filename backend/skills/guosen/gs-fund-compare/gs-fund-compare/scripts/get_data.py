"""
基金对比查询脚本。

功能：
- 支持多只基金同时查询和对比
- 返回基金基本信息、业绩数据、基金经理等对比结果
- 结果输出为对比表格形式的 Excel + 描述 txt
"""

import argparse
import asyncio
import json
import os
import ssl
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd

# 配置中文字体


# API Key（从环境变量读取）
SKILL_ID = "7627085587157205043"
GS_API_KEY = os.getenv(f"COZE_GUOSEN_API_KEY_{SKILL_ID}")


# API基础地址
BASE_URL = "https://dgzt.guosen.com.cn/skills"

DEFAULT_FUND_API_URL = f"{BASE_URL}/gsfinancing/fundinfo/getfunddetail/1.0"
DEFAULT_MANAGER_API_URL = f"{BASE_URL}/gsfinancing/fundmanager/getManagerInfoByOfcode/1.0"
DEFAULT_RATE_API_URL = f"{BASE_URL}/gsfinancing/fundinfo/getfundrate/1.0"
DEFAULT_CAPINFO_API_URL = f"{BASE_URL}/gsfinancing/fundinfo/getfundcapinfo/2.0"
DEFAULT_ANALYSIS_API_URL = f"{BASE_URL}/zebra/gsfinancing/fundinfo/getfundAnalysis/1.0"
DEFAULT_PERFORMANCE_API_URL = f"{BASE_URL}/zebra/gsfinancing/fundinfo/getfundperformance/2.0"
DEFAULT_PLOT_API_URL = f"{BASE_URL}/zebra/gsfinancing/fundinfo/getjjxqfundperformplot/1.0"
DEFAULT_SCALE_API_URL = f"{BASE_URL}/gsfinancing/fundinfo/getfundscale/1.0"

# 公共 SSL Context - 兼容旧版 TLS 重协商
_ssl_ctx = ssl.create_default_context()
_ssl_ctx.options |= 0x4  # OP_LEGACY_SERVER_CONNECT

# 走势图周期配置
PERIODS = {
    "1m": "1M",
    "3m": "3M",
    "6m": "6M",
    "1y": "1Y",
    "3y": "3Y",
}

# 沪深300指数代码
INDEX_CODE = "HS300"

# 颜色配置
CHART_COLORS = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f']


# 枚举值映射字典 - 基于接口文档描述
ENUM_VALUE_MAP = {
    # 基金类型 oftype
    "oftype": {
        "1": "股票型",
        "2": "混合型",
        "3": "债券型",
        "4": "货币型",
        "6": "QDII",
        "7": "其他",
    },
    # 是否是指数基金 isindex
    "isindex": {
        "0": "否",
        "1": "是",
    },
    # 是否是QDII isqdii
    "isqdii": {
        "0": "否",
        "1": "是",
    },
    # 基金状态 ofstatus
    "ofstatus": {
        "0": "正常开放",
        "1": "认购时期",
        "2": "发行成功",
        "3": "发行失败",
        "4": "基金停止交易",
        "5": "停止申购",
        "6": "停止赎回",
        "7": "权益登记",
        "8": "红利发放",
        "9": "基金封闭",
        "a": "基金终止",
        "q": "认购前",
    },
    # 是否可定投 timeropen
    "timeropen": {
        "1": "是",
    },
    # 风险级别 ofriskvalue
    "ofriskvalue": {
        "1": "低风险",
        "2": "中低风险",
        "3": "中风险",
        "4": "中高风险",
        "5": "高风险",
    },
    # 评级 ratingInfo
    "ratingInfo": {
        "1": "一星",
        "2": "二星",
        "3": "三星",
        "4": "四星",
        "5": "五星",
    },
    # 基金类型(数据结构) fundType
    "fundType": {
        "1": "契约型封闭式",
        "2": "开放式",
        "3": "LOF",
        "4": "ETF",
        "5": "FOF",
        "6": "创新型封闭式",
        "7": "开放式(带固定封闭期)",
        "8": "ETF联接基金",
        "9": "半开放式",
    },
    # 是否FOF基金 ifFOF
    "ifFOF": {
        "0": "否",
        "1": "是",
    },
    # 所属投资品种 investtype
    "investtype": {
        "6": "货币型",
        "7": "债券型",
        "8": "混合型",
        "9": "偏股型",
        "A": "股票型",
        "B": "其他",
    },
    # 投资期限 investlimit
    "investlimit": {
        "1": "0-1年",
        "2": "1-3年",
        "3": "3-5年",
        "4": "5年以上",
    },
    # 特殊类别 sptype
    "sptype": {
        "1": "养老FOF基金",
    },
    # 指数基金展示标志 showindexflag
    "showindexflag": {
        "1": "展示跟踪指数",
    },
    # 理财型基金标志 financeflag
    "financeflag": {
        "理财型基金": "是",
    },
    # 是否是经典老基 isoldfundflag
    "isoldfundflag": {
        "1": "是",
    },
    # 是否有产品月报 hasmonthreport
    "hasmonthreport": {
        "1": "有",
    },
    # 是否支持跨境理财通 iscrossBorder
    "iscrossBorder": {
        "0": "不支持",
        "1": "支持",
    },
    # 是否香港互认基金 isxghr
    "isxghr": {
        "1": "是",
    },
    # 是否是交银施罗德基金 isJYSLD
    "isJYSLD": {
        "1": "是",
    },
    # 是否支持实时估值查询 estallow
    "estallow": {
        "0": "不支持",
        "1": "支持",
    },
    # 是否个税递延养老基金 taxdelaytype
    "taxdelaytype": {
        "0": "否",
        "1": "是",
    },
    # ========== 基金经理详细信息接口枚举值 ==========
    # 基金类型 fundStyle
    "fundStyle": {
        "1": "偏股型",
        "2": "债券型",
    },
    # 基金经理性别 gender
    "gender": {
        "m": "男",
        "f": "女",
    },
    # 是否新锐基金经理 sunriseMgrFlag
    "sunriseMgrFlag": {
        "0": "否",
        "1": "是",
    },
    # 业绩类别 performType
    "performType": {
        "0": "全部",
        "1": "偏股型",
        "2": "债券型",
    },
    # 代销标记 saleFlag
    "saleFlag": {
        "0": "非代销",
        "1": "国信代销",
    },
    # ========== 基金费率接口枚举值 ==========
    # 费率类别 feetype
    "feetype": {
        "RG": "认购费率",
        "SG": "申购费率",
        "SH": "赎回费率",
    },
    # 申购、认购费率是否完整 feeNotStartZero
    "feeNotStartZero": {
        "0": "完整或没有",
        "1": "不完整",
    },
    # 认购费率是否为空 rgFeeFlag
    "rgFeeFlag": {
        "0": "否",
        "1": "是",
    },
    # 申购费率是否为空 sgFeeFlag
    "sgFeeFlag": {
        "0": "否",
        "1": "是",
    },
    # 赎回费率是否为空 shFeeFlag
    "shFeeFlag": {
        "0": "否",
        "1": "是",
    },
    # 是否是后端基金 backfundflag
    "backfundflag": {
        "1": "是",
    },
}


# 用于对比展示的关键字段（按类别分组）
COMPARISON_FIELDS = [
    # 基本信息（用于对比展示）
    ("ofcode", "基金代码"),
    ("secuabbr", "基金简称"),
    ("secucname", "基金全称"),
    ("oftype", "基金类型"),
    ("fundType", "基金类型(数据结构)"),
    ("ofstatus", "基金状态"),
    ("investadvisor", "基金管理人"),
    ("trusteename", "基金托管人"),
    
    # 规模信息
    ("endamt", "资产规模(元)"),
    ("endshares", "份额规模"),
    ("establishmentdate", "成立日期"),
    ("estyear", "已成立年数"),

    # 购买信息
    ("buyamt", "购买起点"),
    ("timeropen", "是否可定投"),
    ("tmingamt", "定投起点"),
    ("pbuytop", "个人当日最高限额"),
    
    # 风险评级
    ("ofriskvalue", "风险级别"),
    ("ratingInfo", "济安评级"),
    
    # 业绩表现
    ("singlemonth", "近1月收益率"),
    ("threemonth", "近3月收益率"),
    ("sixmonth", "近6月收益率"),
    ("singleyear", "近1年收益率"),
    ("thisyear", "今年以来收益率"),
    ("sincestart", "成立以来收益率"),
    ("threeYear", "近3年收益率"),
    
    # 净值信息
    ("unitnetvalue", "单位净值"),
    ("tradingday", "净值日期"),
    
    # 投资信息
    ("investtype", "投资品种"),
    ("investlimit", "投资期限"),
    ("isindex", "是否指数基金"),
    ("isqdii", "是否QDII"),
    ("ifFOF", "是否FOF"),
    
    # 特色信息
    ("iscrossBorder", "跨境理财通"),
    ("taxdelaytype", "个税递延养老"),
]

# 费率信息字段（用于整合到对比表格）
RATE_COMPARISON_FIELDS = [
    ("年管理费", "年管理费"),
    ("年托管费", "年托管费"),
    ("年销售服务费", "年销售服务费"),
    ("认购费率", "认购费率"),
    ("申购费率", "申购费率"),
    ("赎回费率", "赎回费率"),
]

# 资产配置信息字段（用于整合到对比表格）
# 大类占比字段 - 从 data1 结果集获取
ASSET_ALLOCATION_FIELDS = [
    ("股票占比", "股票占比"),
    ("债券占比", "债券占比"),
    ("现金占比", "现金占比"),
    ("基金占比", "基金占比"),
    ("其他占比", "其他占比"),
    ("净资产", "净资产"),
    ("报告期", "报告期"),
]



NO_API_KEY_MSG = """
该技能依赖国信证券小信智慧助手的数据服务，需要先配置API Key。
配置步骤:
1. 访问  https://www.guosen.com.cn/gs/xxskills/index.html 注册/登录账号
2. 登录后获取您的API Key。登录位置：网页一级标题栏-登录。登录后，点击账号，在弹窗上可一键复制API Key。
3. 在技能凭证配置中填入API Key
""".strip()


def _map_enum_value(field: str, value: str) -> str:
    """将枚举值转换为可读的中文描述。"""
    if value is None:
        return ""
    
    value_str = str(value).strip()
    
    # 先精确匹配
    if field in ENUM_VALUE_MAP:
        enum_map = ENUM_VALUE_MAP[field]
        if value_str in enum_map:
            return enum_map[value_str]
    
    # 如果是"是否"类型的字段，且值为"1"，返回"是"
    if value_str == "1":
        if field.startswith("is") or field in ["timeropen", "estallow", "taxdelaytype"]:
            return "是"
    
    # 如果是"是否"类型的字段，且值为"0"，返回"否"
    if value_str == "0":
        if field.startswith("is") or field in ["estallow", "taxdelaytype"]:
            return "否"
    
    return value_str


def _get_default_output_dir() -> Path:
    """返回默认输出目录路径（skill目录下的guosen目录）。"""
    # 从脚本位置向上找到skill目录: skill/gs-fund-compare/scripts/get_data.py
    script_dir = Path(__file__).resolve().parent
    # 向上三级: scripts -> gs-fund-compare -> skill
    skill_dir = script_dir.parent.parent.parent
    return skill_dir / "guosen" / "gs-fund-compare"


def _flatten_value(v: Any) -> str:
    """将任意值规范为字符串表示。"""
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


async def query_single_fund(
        fund_code: str,
        api_url: str = DEFAULT_FUND_API_URL,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    查询单个基金的详细信息。

    返回: (fund_data, error)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
            params = {"ofcode": fund_code, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
            if GS_API_KEY:
                params["apiKey"] = GS_API_KEY
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP 错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    # 检查接口返回状态
    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    # 获取数据
    fund_data = data.get("data", [{}])[0] if data.get("data") else {}
    if not fund_data:
        return None, "未获取到基金数据"

    return fund_data, None


def _build_comparison_table(funds_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    构建基金对比表格。
    每只基金作为一列，字段作为行，便于横向对比。
    """
    rows = []

    for field, label in COMPARISON_FIELDS:
        row = {"字段": label}
        for i, fund_data in enumerate(funds_data):
            value = fund_data.get(field, "")
            if value is not None and str(value).strip():
                # 对枚举值进行映射
                mapped_value = _map_enum_value(field, value)
                # 使用基金简称作为列名
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                row[fund_name] = mapped_value
            else:
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                row[fund_name] = ""

        # 只有当有至少一列有值时才添加该行
        if any(v for k, v in row.items() if k != "字段"):
            rows.append(row)

    return rows


def _format_percentage(value: Any) -> str:
    """格式化百分比值，保留两位小数，无数据返回 --"""
    if value is None or str(value).strip() == "":
        return "--"
    try:
        # 尝试转换为浮点数
        float_val = float(str(value).strip())
        return f"{float_val:.2f}%"
    except (ValueError, TypeError):
        return "--"


def _build_comparison_table_with_rates(
        funds_data: List[Dict[str, Any]],
        rate_info_dict: Dict[str, Dict[str, str]],
        capinfo_allocation_dict: Optional[Dict[str, Dict[str, str]]] = None,
        capinfo_holdings_dict: Optional[Dict[str, List[Dict[str, Any]]]] = None,
        risk_control_dict: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None,
        performance_dict: Optional[Dict[str, Dict[str, List[Dict[str, Any]]]]] = None,
        scale_dict: Optional[Dict[str, Dict[str, Dict[str, str]]]] = None
) -> List[Dict[str, Any]]:
    """
    构建基金对比表格（包含费率信息、资产配置信息、规模信息）。
    每只基金作为一列，字段作为行，便于横向对比。
    """
    rows = []

    # 先添加基本字段
    for field, label in COMPARISON_FIELDS:
        row = {"字段": label}
        for i, fund_data in enumerate(funds_data):
            value = fund_data.get(field, "")
            if value is not None and str(value).strip():
                mapped_value = _map_enum_value(field, value)
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                row[fund_name] = mapped_value
            else:
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                row[fund_name] = ""

        if any(v for k, v in row.items() if k != "字段"):
            rows.append(row)

    # 添加费率信息字段
    for field, label in RATE_COMPARISON_FIELDS:
        row = {"字段": label}
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            rate_info = rate_info_dict.get(fund_name, {})
            row[fund_name] = rate_info.get(field, "")

        # 只有当有至少一列有值时才添加该行
        if any(v for k, v in row.items() if k != "字段"):
            rows.append(row)

    # 添加资产配置整合行
    if capinfo_allocation_dict:
        # 获取报告期（统一取第一个基金的报告期）
        report_date = ""
        for fund_name, allocation in capinfo_allocation_dict.items():
            report_date = allocation.get("报告期", "")
            if report_date:
                break

        # 创建资产占比行
        row = {"字段": f"资产占比\n{report_date}"}
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            allocation = capinfo_allocation_dict.get(fund_name, {})

            # 格式化各类占比
            stock = _format_percentage(allocation.get("股票占比", ""))
            bond = _format_percentage(allocation.get("债券占比", ""))
            cash = _format_percentage(allocation.get("现金占比", ""))
            fund_ratio = _format_percentage(allocation.get("基金占比", ""))
            other = _format_percentage(allocation.get("其他占比", ""))

            # 构建显示文本
            # 格式：基金 94.69% 股票 91.51% 债券 0.99% 现金 7.58% 其它 --
            allocation_text = f"基金 {fund_ratio}\n股票 {stock}\n债券 {bond}\n现金 {cash}\n其它 {other}"
            row[fund_name] = allocation_text

        rows.append(row)

    # 添加基金规模信息（资产规模、份额规模、投资人结构）
    if scale_dict:
        # 资产规模行
        asset_row = {"字段": "资产规模"}
        share_row = {"字段": "份额规模"}
        holder_row = {"字段": "投资人结构"}

        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            scale_info = scale_dict.get(fund_name, {})

            # 资产规模
            asset_info = scale_info.get("资产规模", {})
            if asset_info.get("value"):
                asset_date = asset_info.get("date", "")
                asset_value = asset_info.get("value", "")
                asset_unit = asset_info.get("unit", "")
                asset_row[fund_name] = f"{asset_value} {asset_unit}"
                if asset_date:
                    asset_row["字段"] = f"资产规模({asset_date})"
            else:
                asset_row[fund_name] = "--"

            # 份额规模
            share_info = scale_info.get("份额规模", {})
            if share_info.get("value"):
                share_date = share_info.get("date", "")
                share_value = share_info.get("value", "")
                share_unit = share_info.get("unit", "")
                share_row[fund_name] = f"{share_value} {share_unit}"
                if share_date:
                    share_row["字段"] = f"份额规模({share_date})"
            else:
                share_row[fund_name] = "--"

            # 投资人结构
            holder_info = scale_info.get("投资人结构", {})
            inst_pct = holder_info.get("机构占比", "")
            person_pct = holder_info.get("个人占比", "")
            if inst_pct or person_pct:
                # 格式：机构 XX% 个人 XX%
                holder_texts = []
                if inst_pct:
                    holder_texts.append(f"机构 {inst_pct}")
                if person_pct:
                    holder_texts.append(f"个人 {person_pct}")
                holder_row[fund_name] = "\n".join(holder_texts)
            else:
                holder_row[fund_name] = "--"

        rows.append(asset_row)
        rows.append(share_row)
        rows.append(holder_row)

    # 添加重仓持股整合行
    if capinfo_holdings_dict:
        # 获取报告期（统一取第一个基金的报告期）
        report_date = ""
        for fund_name, holdings_list in capinfo_holdings_dict.items():
            if holdings_list:
                # 从第一个重仓股获取报告期
                # 注意：API返回的data2没有报告期字段，我们从data1获取
                break

        # 尝试从资产配置中获取报告期
        if capinfo_allocation_dict:
            for fund_name, allocation in capinfo_allocation_dict.items():
                report_date = allocation.get("报告期", "")
                if report_date:
                    break

        # 创建重仓持股行
        row = {"字段": f"重仓持股\n{report_date}"}

        # 先构建每只基金的重仓股文本
        fund_holding_texts = []
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            holdings_list = capinfo_holdings_dict.get(fund_name, [])

            if not holdings_list:
                fund_holding_texts.append("")
                continue

            # 过滤掉"十大重仓基金总和"这类汇总行
            valid_holdings = [h for h in holdings_list if h.get("股票名称") and "十大重仓" not in h.get("股票名称", "")]

            if not valid_holdings:
                fund_holding_texts.append("")
                continue

            # 构建重仓股文本
            lines = []
            total_ratio = 0.0
            for holding in valid_holdings[:10]:  # 最多10只
                name = holding.get("股票名称", "")
                ratio_str = holding.get("占净值比例", "").replace("%", "")
                industry = holding.get("申万行业", "")

                try:
                    ratio = float(ratio_str) if ratio_str else 0
                    total_ratio += ratio
                except (ValueError, TypeError):
                    ratio = 0

                # 格式：股票名称(所属行业) 占净值比例%
                if name and ratio_str:
                    lines.append(f"{name}({industry}) {ratio_str}%")

            # 添加总和行
            if lines:
                lines.append(f"--(十大重仓股总和) {total_ratio:.2f}%")

            fund_holding_texts.append("\n".join(lines))

        # 检查是否有任何基金有持仓
        has_any_holding = any(text for text in fund_holding_texts)

        # 填充每一列
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            holding_text = fund_holding_texts[i] if i < len(fund_holding_texts) else ""

            if not holding_text:
                row[fund_name] = "暂无持仓股票"
            else:
                row[fund_name] = holding_text

        # 只有当至少有一个基金有持仓时才添加该行（或全部显示暂无持仓股票也添加）
        rows.append(row)

    # 添加风险控制信息（近一年、近三年、近五年）
    if risk_control_dict:
        # 近一年、近三年、近五年的标签
        period_labels = [
            ("1y", "近一年"),
            ("3y", "近三年"),
            ("5y", "近五年"),
        ]

        for period_key, period_label in period_labels:
            # 创建风险控制行
            row = {"字段": f"风险控制\n({period_label})"}

            for i, fund_data in enumerate(funds_data):
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                risk_info = risk_control_dict.get(fund_name, {}).get(period_key, {})

                mdd = risk_info.get("最大回撤", "")
                sharpe = risk_info.get("夏普比率", "")
                std = risk_info.get("波动率", "")

                # 如果三个指标都为空，显示 --
                if not mdd and not sharpe and not std:
                    row[fund_name] = "--"
                else:
                    # 格式：最大回撤 XX% 夏普比率 X.XX 波动率 XX%
                    lines = []
                    if mdd:
                        lines.append(f"最大回撤 {mdd}")
                    else:
                        lines.append("最大回撤 --")

                    if sharpe:
                        lines.append(f"夏普比率 {sharpe}")
                    else:
                        lines.append("夏普比率 --")

                    if std:
                        lines.append(f"波动率 {std}")
                    else:
                        lines.append("波动率 --")

                    row[fund_name] = "\n".join(lines)

            rows.append(row)

    # 添加业绩信息（阶段业绩、年度业绩、季度业绩）
    if performance_dict:
        rows.extend(_build_performance_tables(funds_data, performance_dict))

    return rows


def _build_performance_tables(
        funds_data: List[Dict[str, Any]],
        performance_dict: Dict[str, Dict[str, List[Dict[str, Any]]]]
) -> List[Dict[str, Any]]:
    """
    构建业绩对比表格（阶段业绩、年度业绩、季度业绩）。

    从data中获取阶段业绩（包含收益率和同类排名分位点）。
    只在有实际数据时添加年度和季度业绩行。
    """
    rows = []

    # period字段映射 - API返回的period值到显示名称
    period_mapping = [
        ("date_1w", "近一周"),
        ("date_1m", "近一月"),
        ("date_3m", "近三月"),
        ("date_6m", "近六月"),
        ("date_1y", "近一年"),
        ("date_3y", "近三年"),
        ("date_5y", "近五年"),
    ]

    # 构建阶段业绩行 - 从data中获取（阶段业绩数据在 data 字段中）
    for period_key, period_label in period_mapping:
        row = {"字段": f"阶段业绩\n({period_label})"}
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            perf_data = performance_dict.get(fund_name, {})
            data = perf_data.get("data", [])

            # 查找对应的 reporttype 数据（阶段业绩的字段是 reporttype，如 date_1w, date_1m 等）
            perf_item = None
            for item in data:
                if item.get("reporttype") == period_key:
                    perf_item = item
                    break

            if perf_item:
                rate = perf_item.get("profit", "") or perf_item.get("rate", "")
                rank = perf_item.get("profitRank", "")
                rank_total = perf_item.get("profitRankTotal", "")
                if rate:
                    # 显示格式：涨跌幅 排名/总排名（如 144.65% 100/100）
                    row[fund_name] = f"{rate}% {rank}/{rank_total}" if rank else f"{rate}%"
                else:
                    row[fund_name] = "--"
            else:
                row[fund_name] = "--"

        rows.append(row)

    # 检查是否有年度业绩数据（data3）
    has_annual_data = False
    for fund_name in performance_dict:
        if performance_dict[fund_name].get("data3"):
            has_annual_data = True
            break

    # 构建年度业绩行 - 从data3获取
    # reporttype 字段格式：如 "2024"
    if has_annual_data:
        # 从 data3 中动态获取所有年份
        all_years = set()
        for fund_name in performance_dict:
            data3 = performance_dict[fund_name].get("data3", [])
            for item in data3:
                reporttype = item.get("reporttype", "")
                # 只取纯数字的年份（如 "2024"）
                if reporttype and reporttype.isdigit():
                    all_years.add(reporttype)
        # 按年份降序排序
        years = sorted(all_years, reverse=True)

        for year in years:
            row = {"字段": f"年度业绩\n({year}年)"}
            for i, fund_data in enumerate(funds_data):
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                perf_data = performance_dict.get(fund_name, {})
                data3 = perf_data.get("data3", [])

                # 查找对应的year数据
                perf_item = None
                for item in data3:
                    if item.get("reporttype") == year:
                        perf_item = item
                        break

                if perf_item:
                    rate = perf_item.get("profit", "")
                    rank = perf_item.get("profitRank", "")
                    rank_total = perf_item.get("profitRankTotal", "")
                    if rate or rank:
                        row[fund_name] = f"{rate}% {rank}/{rank_total}"
                    else:
                        row[fund_name] = "--"
                else:
                    row[fund_name] = "--"

            rows.append(row)

    # 检查是否有季度业绩数据（data4）
    has_quarter_data = False
    for fund_name in performance_dict:
        if performance_dict[fund_name].get("data4"):
            has_quarter_data = True
            break

    # 构建季度业绩行 - 从data4获取
    # reporttype 字段格式：如 "2025Q3"
    if has_quarter_data:
        # 从 data4 中动态获取所有季度
        all_quarters = set()
        for fund_name in performance_dict:
            data4 = performance_dict[fund_name].get("data4", [])
            for item in data4:
                reporttype = item.get("reporttype", "")
                # 只取包含 Q 的季度格式（如 "2025Q3"）
                if reporttype and 'Q' in reporttype:
                    all_quarters.add(reporttype)
        # 按季度降序排序
        quarters = sorted(all_quarters, reverse=True)

        for quarter in quarters:
            row = {"字段": f"季度业绩\n({quarter})"}
            for i, fund_data in enumerate(funds_data):
                fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
                perf_data = performance_dict.get(fund_name, {})
                data4 = perf_data.get("data4", [])

                # 查找对应的quarter数据
                perf_item = None
                for item in data4:
                    if item.get("reporttype") == quarter:
                        perf_item = item
                        break

                if perf_item:
                    rate = perf_item.get("profit", "")
                    rank = perf_item.get("profitRank", "")
                    rank_total = perf_item.get("profitRankTotal", "")
                    if rate or rank:
                        row[fund_name] = f"{rate}% {rank}/{rank_total}"
                    else:
                        row[fund_name] = "--"
                else:
                    row[fund_name] = "--"

            rows.append(row)

    return rows


def _build_detail_table(fund_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    构建单只基金的详细信息表格。
    """
    # 使用完整的字段列表
    from typing import List as TypingList
    
    rows = []
    for field, label in COMPARISON_FIELDS:
        value = fund_data.get(field, "")
        if value is not None and str(value).strip():
            mapped_value = _map_enum_value(field, value)
            rows.append({
                "字段": label,
                "值": mapped_value
            })
    return rows


# 基金费率信息字段映射
RATE_FIELDS = [
    # rates数组中的费率信息
    ("feetype", "费率类别"),
    ("feetypedesc", "费率类别名称"),
    ("feerange", "适用范围"),
    ("feerate", "基准费率"),
    ("ratefee", "折后费率"),
    ("freeratedesc", "基准费率描述"),
    ("ratefreedesc", "折后费率描述"),
]

# 年费率信息字段
YEAR_RATE_FIELDS = [
    ("managementfee", "年管理费"),
    ("storefee", "年托管费"),
    ("servicefee", "年销售服务费"),
    ("feeNotStartZero", "申购认购费率是否完整"),
    ("rgFeeFlag", "认购费率是否为空"),
    ("sgFeeFlag", "申购费率是否为空"),
    ("shFeeFlag", "赎回费率是否为空"),
    ("backfundflag", "是否后端基金"),
    ("tacode", "基金公司代码"),
    ("oftype", "基金类型"),
]


def _map_rate_enum_value(field: str, value: str) -> str:
    """将基金费率枚举值转换为可读的中文描述。"""
    if value is None or str(value).strip() == "":
        return ""

    value_str = str(value).strip()

    # 费率类别映射
    if field == "feetype":
        fee_map = {
            "1": "认购费率",
            "2": "申购费率",
            "6": "赎回费率",
        }
        return fee_map.get(value_str, value_str)

    if field in ENUM_VALUE_MAP:
        enum_map = ENUM_VALUE_MAP[field]
        if value_str in enum_map:
            return enum_map[value_str]

    return value_str


def _parse_integrated_rate(rate_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析基金费率信息，将多行整合为一行。
    返回包含年管理费、年托管费、年销售服务费、认购费率、申购费率、赎回费率的字典。
    """
    result = {
        "年管理费": "",
        "年托管费": "",
        "年销售服务费": "",
        "认购费率": "",
        "申购费率": "",
        "赎回费率": "",
    }

    if not rate_data:
        return result

    data_list = rate_data.get("data", [])
    if not data_list:
        return result

    # 获取年费率信息
    fees_list = data_list[0].get("fees", [])
    if fees_list and len(fees_list) > 0:
        year_rates = fees_list[0]
        result["年管理费"] = year_rates.get("managementfee", "")
        result["年托管费"] = year_rates.get("storefee", "")
        result["年销售服务费"] = year_rates.get("servicefee", "") or ""

    # 按费率类别分组
    rates_by_type = {"1": [], "2": [], "6": []}  # 认购、申购、赎回

    for item in data_list:
        rates_list = item.get("rates", [])
        for rate_item in rates_list:
            feetype = rate_item.get("feetype", "")
            feerange = rate_item.get("feerange", "")
            freeratedesc = rate_item.get("freeratedesc", "")
            ratefreedesc = rate_item.get("ratefreedesc", "")

            if feetype in rates_by_type:
                # 格式：适用范围 基准费率描述(折后：折后费率描述)
                if freeratedesc and ratefreedesc and freeratedesc != ratefreedesc:
                    fee_desc = f"{feerange} {freeratedesc}(折后：{ratefreedesc})"
                else:
                    fee_desc = f"{feerange} {freeratedesc}"

                rates_by_type[feetype].append(fee_desc)

    # 整合费率信息
    if rates_by_type["1"]:  # 认购费率
        result["认购费率"] = "\n".join(rates_by_type["1"])
    if rates_by_type["2"]:  # 申购费率
        result["申购费率"] = "\n".join(rates_by_type["2"])
    if rates_by_type["6"]:  # 赎回费率
        result["赎回费率"] = "\n".join(rates_by_type["6"])

    return result


def _build_rate_table(rate_data: Dict[str, Any], fund_name: str) -> List[Dict[str, Any]]:
    """构建基金费率信息表格（已整合为单行格式）。"""
    integrated_rate = _parse_integrated_rate(rate_data)
    if not integrated_rate or all(not v for v in integrated_rate.values()):
        return []

    row = {"所属基金": fund_name}
    row.update(integrated_rate)
    return [row]


# 基金经理详细信息字段映射
MANAGER_INFO_FIELDS = [
    ("mgrName", "基金经理"),
    ("company", "所属基金公司"),
    ("mgrExp", "管理经验(年)"),
    ("mgrFundExp", "担任本基金管理经验(年)"),
    ("fundStyle", "基金类型"),
    ("accessDate", "上任日期"),
    ("dimissDate", "离任日期"),
    ("performRate", "任职回报(%)"),
    ("gender", "性别"),
    ("sunriseMgrFlag", "是否新锐基金经理"),
    ("performType", "业绩类别"),
    ("curFunds", "管理基金数"),
    ("mgrAmount", "管理规模"),
    ("mgrAmountRank", "管理规模排名"),
    ("arrRate", "年化收益率(%)"),
    ("arrRateRank", "年化收益率排名"),
    ("monthMgrRate", "近1月收益率(%)"),
    ("thrMonthMgrRate", "近3月收益率(%)"),
    ("sixMonthMgrRate", "近6月收益率(%)"),
    ("yearMgrRate", "近1年收益率(%)"),
    ("thrYearMgrRate", "近3年收益率(%)"),
    ("mgrlabels", "基金经理标签"),
    ("resume", "简介"),
]


def _map_manager_enum_value(field: str, value: str) -> str:
    """将基金经理枚举值转换为可读的中文描述。"""
    if value is None or str(value).strip() == "":
        return ""
    
    value_str = str(value).strip()
    
    if field in ENUM_VALUE_MAP:
        enum_map = ENUM_VALUE_MAP[field]
        if value_str in enum_map:
            return enum_map[value_str]
    
    # 特殊处理
    if field in ["sunriseMgrFlag", "gender"]:
        if value_str == "1":
            return "是" if field == "sunriseMgrFlag" else "男"
        if value_str == "0":
            return "否" if field == "sunriseMgrFlag" else "女"
    
    return value_str


# ============================================================
# 基金规模信息相关函数
# ============================================================

async def query_fund_scale(
        fund_code: str,
        secuid: str = "",
        api_url: str = DEFAULT_SCALE_API_URL,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    查询基金规模信息。

    参数:
        fund_code: 基金代码
        secuid: 基金ID（可选）
        api_url: API 地址

    返回: (scale_data, error)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
            params = {"ofcode": fund_code, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
            if secuid:
                params["secuid"] = secuid
            if GS_API_KEY:
                params["apiKey"] = GS_API_KEY
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP 错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    # 检查接口返回状态
    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    # 获取数据
    scale_data = data
    if not scale_data:
        return None, "未获取到基金规模数据"

    return scale_data, None


def _parse_fund_scale(scale_data: Dict[str, Any]) -> Dict[str, Dict[str, str]]:
    """
    解析基金规模信息。

    返回:
        {
            "资产规模": {"value": "8.35", "unit": "亿元", "date": "2025-12-31"},
            "份额规模": {"value": "14.62", "unit": "亿份", "date": "2025-12-31"},
            "投资人结构": {"机构占比": "8.08%", "个人占比": "91.92%"}
        }
    """
    result = {
        "资产规模": {"value": "", "unit": "", "date": ""},
        "份额规模": {"value": "", "unit": "", "date": ""},
        "投资人结构": {"机构占比": "", "个人占比": ""}
    }

    if not scale_data:
        return result

    # data1: 资产规模（净资产，单位：亿元）
    data1_list = scale_data.get("data1", [])
    if data1_list and len(data1_list) > 0:
        # 取最新日期的数据
        latest_item = data1_list[0]
        netvalue = latest_item.get("netvalue")
        if netvalue is not None:
            # 转换为亿元
            result["资产规模"] = {
                "value": str(netvalue),
                "unit": "亿元",
                "date": latest_item.get("enddate", "")
            }

    # data2: 份额规模（持有份额，单位：亿份）
    data2_list = scale_data.get("data2", [])
    if data2_list and len(data2_list) > 0:
        latest_item = data2_list[0]
        endshares = latest_item.get("endshares")
        if endshares is not None:
            # 转换为亿份
            result["份额规模"] = {
                "value": str(endshares),
                "unit": "亿份",
                "date": latest_item.get("enddate", "")
            }

    # data3: 投资人结构（机构占比、个人占比）
    data3_list = scale_data.get("data3", [])
    if data3_list and len(data3_list) > 0:
        latest_item = data3_list[0]
        inst_pct = latest_item.get("institutionholdratio", "")
        person_pct = latest_item.get("individualholdratio", "")
        if inst_pct is not None:
            inst_pct = f"{inst_pct}%"
        if person_pct is not None:
            person_pct = f"{person_pct}%"
        result["投资人结构"] = {
            "机构占比": inst_pct,
            "个人占比": person_pct
        }

    return result


# ============================================================
# 资产配置信息相关函数
# ============================================================

async def query_fund_capinfo(
        fund_code: str,
        secuid: str,
        api_url: str = DEFAULT_CAPINFO_API_URL,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    查询基金资产配置信息。

    参数:
        fund_code: 基金代码
        secuid: 基金ID，从 getfunddetail 接口返回
        api_url: API 地址

    返回: (capinfo_data, error)
    """
    try:
        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
            params = {"ofcode": fund_code, "secuid": secuid, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
            if GS_API_KEY:
                params["apiKey"] = GS_API_KEY
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP 错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    # 检查接口返回状态
    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    # 获取数据
    capinfo_data = data
    if not capinfo_data:
        return None, "未获取到资产配置数据"

    return capinfo_data, None


def _parse_asset_allocation(capinfo_data: Dict[str, Any]) -> Dict[str, str]:
    """
    解析资产配置信息（data1 大类占比）。

    返回包含股票/债券/现金/基金/其他占比的字典。
    """
    result = {
        "股票占比": "",
        "债券占比": "",
        "现金占比": "",
        "基金占比": "",
        "其他占比": "",
        "净资产": "",
        "报告期": "",
    }

    if not capinfo_data:
        return result

    # 从 data1 获取大类占比
    data1_list = capinfo_data.get("data1", [])
    if data1_list and len(data1_list) > 0:
        data1 = data1_list[0]
        result["股票占比"] = data1.get("stockmvratioinnv", "")
        result["债券占比"] = data1.get("bondmvratioinnv", "")
        result["现金占比"] = data1.get("mfratioinnv", "")
        result["基金占比"] = data1.get("fundmvratioinnv", "")
        result["其他占比"] = data1.get("oaratioinnv", "")
        result["净资产"] = data1.get("netvalue", "")
        result["报告期"] = data1.get("enddate", "")

    return result


def _parse_top_holdings(capinfo_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    解析十大重仓股信息（data2）。

    返回包含重仓股名称、占比、行业信息的列表。
    """
    if not capinfo_data:
        return []

    # 从 data2 获取重仓股信息
    data2_list = capinfo_data.get("data2", [])

    holdings = []
    for item in data2_list:
        # 申万行业在 firstindustry 字段
        holdings.append({
            "股票名称": item.get("holdingsecuabbr", ""),
            "占净值比例": item.get("ratioinnv", ""),
            "申万行业": item.get("firstindustry", ""),
            "证券代码": item.get("stkcode", ""),
            "持仓市值": item.get("marketvalue", ""),
            "持股数": item.get("rationinsv", ""),
        })

    return holdings


# ============================================================

async def query_fund_analysis(
        fund_code: str,
        period: Optional[str] = None,
        api_url: str = DEFAULT_ANALYSIS_API_URL,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    查询基金分析信息（风险控制指标和业绩信息）。

    参数:
        fund_code: 基金代码
        period: 周期 (1y-近一年, 3y-近三年, 5y-近五年)，不传则获取所有数据
        api_url: API 地址

    返回: (analysis_data, error)
    """
    try:
        params = {"ofcode": fund_code, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
        if period:
            params["period"] = period

        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
            if GS_API_KEY:
                params["apiKey"] = GS_API_KEY
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP 错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    # 检查接口返回状态
    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    # 获取完整数据（包含data, data2, data3, data4）
    analysis_data = data.get("data", [])
    extra_data = {
        "data": analysis_data,
        "data2": data.get("data2", []),
        "data3": data.get("data3", []),
        "data4": data.get("data4", []),
    }

    # 如果没有数据
    if not analysis_data and not extra_data["data2"] and not extra_data["data3"] and not extra_data["data4"]:
        return None, "未获取到分析数据"

    return extra_data, None


async def query_fund_performance(
        fund_code: str,
        api_url: str = DEFAULT_PERFORMANCE_API_URL,
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    查询基金业绩概述和阶段业绩信息（年度业绩、季度业绩）。

    参数:
        fund_code: 基金代码
        api_url: API 地址

    返回: (performance_data, error)
    performance_data 包含 data1(阶段业绩), data2(阶段业绩), data3(年度业绩), data4(季度业绩)
    """
    try:
        params = {"mfcode": fund_code, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
        async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
            if GS_API_KEY:
                params["apiKey"] = GS_API_KEY
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP 错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    # 检查接口返回状态
    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    # 获取各类业绩数据
    # data1: 阶段业绩
    # data2: 阶段业绩（备用）
    # data3: 年度业绩
    # data4: 季度业绩
    performance_data = {
        "data1": data.get("data1", []),
        "data2": data.get("data2", []),
        "data3": data.get("data3", []),
        "data4": data.get("data4", []),
    }

    return performance_data, None


def _parse_risk_control(analysis_data: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """
    解析基金风险控制信息。

    返回包含近一年、近三年、近五年风险指标的字典。
    结构: {period: {最大回撤, 夏普比率, 波动率, date}}
    """
    result = {
        "1y": {"最大回撤": "", "夏普比率": "", "波动率": "", "date": ""},
        "3y": {"最大回撤": "", "夏普比率": "", "波动率": "", "date": ""},
        "5y": {"最大回撤": "", "夏普比率": "", "波动率": "", "date": ""},
    }

    if not analysis_data:
        return result

    # period 可能是 "date_1y", "date_3y", "date_5y" 或 "1y", "3y", "5y"
    period_map = {
        "1y": "1y", "date_1y": "1y",
        "3y": "3y", "date_3y": "3y",
        "5y": "5y", "date_5y": "5y",
    }

    for item in analysis_data:
        period = item.get("period", "")
        if period not in period_map:
            continue

        key = period_map[period]
        # 最大回撤 mdd, 夏普比率 sharpe, 波动率 std
        mdd = item.get("mdd", "")
        sharpe = item.get("sharpe", "")
        std = item.get("std", "")
        date = item.get("date", "")

        # 格式化数据，添加%
        if mdd:
            mdd = mdd.strip()
            if not mdd.endswith("%"):
                mdd = mdd + "%"

        if std:
            std = std.strip()
            if not std.endswith("%"):
                std = std + "%"

        result[key] = {
            "最大回撤": mdd,
            "夏普比率": sharpe,
            "波动率": std,
            "date": date,
        }

    return result


def _build_asset_allocation_table(
        funds_data: List[Dict[str, Any]],
        capinfo_dict: Dict[str, Dict[str, str]]
) -> List[Dict[str, Any]]:
    """
    构建资产配置对比表格（大类占比）。

    每只基金作为一列，字段作为行。
    """
    rows = []

    # 添加大类占比字段
    for field, label in ASSET_ALLOCATION_FIELDS:
        row = {"字段": label}
        for i, fund_data in enumerate(funds_data):
            fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
            allocation_info = capinfo_dict.get(fund_name, {})
            row[fund_name] = allocation_info.get(field, "")

        # 只有当有至少一列有值时才添加该行
        if any(v for k, v in row.items() if k != "字段"):
            rows.append(row)

    return rows


def _build_top_holdings_table(
        funds_data: List[Dict[str, Any]],
        capinfo_dict: Dict[str, List[Dict[str, Any]]]
) -> List[Dict[str, Any]]:
    """
    构建十大重仓股对比表格。

    将所有基金的十大重仓股整合到一个表格中。
    """
    rows = []

    for i, fund_data in enumerate(funds_data):
        fund_name = fund_data.get("secuabbr") or fund_data.get("ofcode", f"基金{i+1}")
        holdings_list = capinfo_dict.get(fund_name, [])

        # 只取前10只重仓股
        for idx, holding in enumerate(holdings_list[:10], 1):
            row = {
                "序号": idx,
                "所属基金": fund_name,
                "股票名称": holding.get("股票名称", ""),
                "占净值比例": holding.get("占净值比例", ""),
                "申万行业": holding.get("申万行业", ""),
            }
            rows.append(row)

    return rows


def _build_managers_table(managers_data: List[Dict[str, Any]], fund_name: str) -> List[Dict[str, Any]]:
    """构建基金经理信息表格。"""
    if not managers_data:
        return []
    
    rows = []
    for manager in managers_data:
        row = {"所属基金": fund_name}
        # 添加基金经理详细信息字段
        for field, label in MANAGER_INFO_FIELDS:
            value = manager.get(field, "")
            # 对枚举值进行映射
            mapped_value = _map_manager_enum_value(field, value)
            row[label] = mapped_value
        rows.append(row)
    return rows


def _build_output_files(
        *,
        output_dir: Path,
        funds_data: List[Dict[str, Any]],
        all_managers: List[Tuple[str, List[Dict[str, Any]]]],
        all_rates: List[Tuple[str, Dict[str, Any]]],
        all_capinfos: List[Tuple[str, Dict[str, Any]]],
        all_analysis: List[Tuple[str, List[Dict[str, Any]], Dict[str, List]]],
        all_scales: List[Tuple[str, Dict[str, Dict[str, str]]]],
        errors: List[str],
) -> Tuple[Path, Path]:
    """将查询结果写入本地文件。"""
    unique_suffix = uuid.uuid4().hex[:8]
    file_path = output_dir / f"gs-fund-compare_{unique_suffix}.xlsx"
    desc_path = output_dir / f"gs-fund-compare_{unique_suffix}_description.txt"

    # 解析费率信息并添加到基金数据中
    rate_info_dict = {}
    for fund_name, rate_data in all_rates:
        integrated_rate = _parse_integrated_rate(rate_data)
        rate_info_dict[fund_name] = integrated_rate

    # 解析资产配置信息
    # 大类占比 dict
    capinfo_allocation_dict = {}
    # 十大重仓股 list
    capinfo_holdings_dict = {}
    for fund_name, capinfo_data in all_capinfos:
        allocation_info = _parse_asset_allocation(capinfo_data)
        holdings_list = _parse_top_holdings(capinfo_data)
        capinfo_allocation_dict[fund_name] = allocation_info
        capinfo_holdings_dict[fund_name] = holdings_list

    # 解析基金规模信息
    scale_dict = {}
    for fund_name, scale_data in all_scales:
        scale_info = _parse_fund_scale(scale_data)
        scale_dict[fund_name] = scale_info

    # 解析风险控制信息和业绩信息
    risk_control_dict = {}
    performance_dict = {}
    for item in all_analysis:
        if len(item) >= 3:
            fund_name, risk_data, perf_data = item[0], item[1], item[2]
        else:
            fund_name, risk_data = item[0], item[1]
            perf_data = {"data2": [], "data3": [], "data4": []}
        risk_info = _parse_risk_control(risk_data)
        risk_control_dict[fund_name] = risk_info
        performance_dict[fund_name] = perf_data

    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        # Sheet 1: 基金对比表格（整合费率信息、资产配置、规模信息、重仓持股、风险控制、业绩信息）
        comparison_rows = _build_comparison_table_with_rates(
            funds_data, rate_info_dict, capinfo_allocation_dict, capinfo_holdings_dict,
            risk_control_dict, performance_dict, scale_dict
        )
        # 获取所有基金名称作为列名
        fund_names = [fd.get("secuabbr") or fd.get("ofcode", f"基金{i+1}")
                      for i, fd in enumerate(funds_data)]
        columns = ["字段"] + fund_names
        if comparison_rows:
            df_compare = pd.DataFrame(comparison_rows)
            # 确保列顺序
            df_compare = df_compare.reindex(columns=columns, fill_value="")
        else:
            df_compare = pd.DataFrame(columns=columns)
        df_compare.to_excel(writer, sheet_name="基金对比", index=False)

        # Sheet 2: 基金经理对比
        all_manager_rows = []
        for fund_name, managers in all_managers:
            all_manager_rows.extend(_build_managers_table(managers, fund_name))
        if all_manager_rows:
            df_managers = pd.DataFrame(all_manager_rows)
        else:
            df_managers = pd.DataFrame(columns=["所属基金", "基金经理"])
        df_managers.to_excel(writer, sheet_name="基金经理对比", index=False)

    # 生成基金名称列表
    fund_names = [fd.get("secucname") or fd.get("secuabbr") or fd.get("ofcode") 
                  for fd in funds_data]
    
    description_lines = [
        "基金对比查询结果说明",
        "=" * 40,
        f"对比基金数量: {len(funds_data)}",
        f"对比基金: {', '.join(fund_names)}",
        f"数据文件路径: {file_path}",
        f"描述文件路径: {desc_path}",
    ]
    
    if errors:
        description_lines.append("")
        description_lines.append("查询错误:")
        for err in errors:
            description_lines.append(f"  - {err}")
    
    description_lines.extend([
        "",
        "数据说明:",
        "- 基金对比: 多只基金关键指标横向对比（含费率、资产配置、重仓持股、风险控制）",
        "- 基金经理对比: 基金经理信息对比",
    ])
    
    desc_path.write_text("\n".join(description_lines), encoding="utf-8")
    return file_path, desc_path


async def compare_funds(
        fund_codes: List[str],
        output_dir: Optional[Path] = None,
        api_url: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对比多只基金的详细信息。
    
    参数:
        fund_codes: 基金代码列表
        output_dir: 输出目录
        api_url: API 地址
    
    返回:
        包含文件路径、数量及错误信息的结果字典
    """
    output_dir = output_dir or _get_default_output_dir()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    url = api_url or DEFAULT_FUND_API_URL
    
    result = {
        "file_path": None,
        "description_path": None,
        "fund_count": 0,
        "fund_names": [],
        "errors": [],
        "chart_final_returns": {},
    }

    funds_data = []
    all_managers = []
    all_rates = []
    all_capinfos = []  # 资产配置信息
    all_analysis = []  # 风险控制信息
    all_scales = []  # 基金规模信息

    # 并发查询每只基金的详细信息
    async def query_fund_all_info(fund_code: str) -> Tuple[Optional[Dict], Optional[str], Optional[str], Optional[Dict], Optional[Dict], Optional[Dict], Optional[Dict], Optional[Dict], Optional[Dict]]:
        """并发查询单只基金的全部信息"""
        fund_data, error = await query_single_fund(fund_code, url)
        if error:
            return None, error, None, None, None, None, None, None, None

        fund_name = fund_data.get("secuabbr") or fund_code
        secuid = fund_data.get("secuid", "")

        # 并发查询该基金的所有附加信息
        managers_task = _query_manager_info(fund_code)
        rate_task = _query_rate_info(fund_code)
        capinfo_task = _query_capinfo(fund_data, fund_code, fund_name)
        analysis_task = _query_analysis_info(fund_code)
        scale_task = query_fund_scale(fund_code, secuid)

        manager_result, rate_result, capinfo_result, analysis_result, scale_result = await asyncio.gather(
            managers_task, rate_task, capinfo_task, analysis_task, scale_task, return_exceptions=True
        )

        # 处理经理信息
        if isinstance(manager_result, Exception):
            managers = []
        else:
            managers = manager_result

        # 处理费率信息
        if isinstance(rate_result, Exception):
            rate_data = {}
        else:
            rate_data = rate_result

        # 处理资产配置信息
        if isinstance(capinfo_result, Exception):
            capinfo_data = {}
        else:
            capinfo_data = capinfo_result

        # 处理分析信息
        if isinstance(analysis_result, Exception):
            combined_data = []
            combined_performance = {"data2": [], "data3": [], "data4": []}
        else:
            combined_data, combined_performance = analysis_result

        # 处理规模信息
        if isinstance(scale_result, Exception):
            scale_data = {}
        elif isinstance(scale_result, tuple):
            # query_fund_scale returns (data, error)
            scale_data = scale_result[0] if scale_result[0] else {}
        else:
            scale_data = scale_result

        return fund_data, None, fund_name, managers, rate_data, capinfo_data, combined_data, combined_performance, scale_data

    async def _query_manager_info(fund_code: str):
        """查询基金经理信息"""
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
                params = {"ofcode": fund_code, "fundFlag": "1", "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
                if GS_API_KEY:
                    params["apiKey"] = GS_API_KEY
                resp = await client.get(DEFAULT_MANAGER_API_URL, params=params)
                data = resp.json()
                mgr_info_list = data.get("mgrInfo", [])
                managers = []
                for mgr in mgr_info_list:
                    managers.append({
                        "mgrName": mgr.get("mgrName", ""),
                        "mgrId": mgr.get("mgrId", ""),
                        "company": mgr.get("company", ""),
                        "companyId": mgr.get("companyId", ""),
                        "mgrExp": mgr.get("mgrExp", ""),
                        "mgrFundExp": mgr.get("mgrFundExp", ""),
                        "resume": mgr.get("resume", ""),
                        "mgrlabels": mgr.get("mgrlabels", ""),
                        "gender": mgr.get("gender", ""),
                        "sunriseMgrFlag": mgr.get("sunriseMgrFlag", ""),
                        "performType": mgr.get("performType", ""),
                        "curFunds": mgr.get("curFunds", ""),
                        "mgrAmount": mgr.get("mgrAmount", ""),
                        "mgrAmountRank": mgr.get("mgrAmountRank", ""),
                        "arrRate": mgr.get("arrRate", ""),
                        "arrRateRank": mgr.get("arrRateRank", ""),
                        "monthMgrRate": mgr.get("monthMgrRate", ""),
                        "thrMonthMgrRate": mgr.get("thrMonthMgrRate", ""),
                        "sixMonthMgrRate": mgr.get("sixMonthMgrRate", ""),
                        "yearMgrRate": mgr.get("yearMgrRate", ""),
                        "thrYearMgrRate": mgr.get("thrYearMgrRate", ""),
                        "fundStyle": mgr.get("fundStyle", ""),
                        "accessDate": mgr.get("accessDate", ""),
                        "dimissDate": mgr.get("dimissDate", ""),
                        "performRate": mgr.get("performRate", ""),
                        "mgrFundList": mgr.get("mgrFundList", []),
                    })
                return managers
        except Exception as e:
            return []

    async def _query_rate_info(fund_code: str):
        """查询费率信息"""
        try:
            async with httpx.AsyncClient(timeout=30.0, verify=_ssl_ctx) as client:
                params = {"ofcode": fund_code, "softName": "goldsun_skills", "skillName": "gs-fund-compare"}
                if GS_API_KEY:
                    params["apiKey"] = GS_API_KEY
                resp = await client.get(DEFAULT_RATE_API_URL, params=params)
                return resp.json()
        except Exception as e:
            return {}

    async def _query_capinfo(fund_data: Dict, fund_code: str, fund_name: str):
        """查询资产配置信息"""
        try:
            secuid = fund_data.get("secuid", "")
            if secuid:
                capinfo_data, _ = await query_fund_capinfo(fund_code, secuid)
                return capinfo_data if capinfo_data else {}
            return {}
        except Exception as e:
            return {}

    async def _query_analysis_info(fund_code: str):
        """并发查询风险控制和业绩信息"""
        # 并发查询三个周期
        analysis_data_1y, _ = await query_fund_analysis(fund_code, "1y")
        analysis_data_3y, _ = await query_fund_analysis(fund_code, "3y")
        analysis_data_5y, _ = await query_fund_analysis(fund_code, "5y")
        
        # 合并data
        combined_data = []
        for ad in [analysis_data_1y, analysis_data_3y, analysis_data_5y]:
            if ad and isinstance(ad, dict):
                combined_data.extend(ad.get("data", []))
        
        # 合并业绩数据
        combined_performance = {"data": combined_data, "data2": [], "data3": [], "data4": []}
        for ad in [analysis_data_1y, analysis_data_3y, analysis_data_5y]:
            if ad and isinstance(ad, dict):
                combined_performance["data2"].extend(ad.get("data2", []))
                combined_performance["data3"].extend(ad.get("data3", []))
                combined_performance["data4"].extend(ad.get("data4", []))
        
        # 查询年度和季度业绩
        perf_data, _ = await query_fund_performance(fund_code)
        if perf_data:
            if perf_data.get("data2"):
                combined_performance["data"].extend(perf_data["data2"])
            if perf_data.get("data3"):
                combined_performance["data3"].extend(perf_data["data3"])
            if perf_data.get("data4"):
                combined_performance["data4"].extend(perf_data["data4"])
        
        return combined_data, combined_performance

    # 并发查询所有基金
    results = await asyncio.gather(*[query_fund_all_info(fc) for fc in fund_codes], return_exceptions=True)

    for r in results:
        if isinstance(r, Exception):
            result["errors"].append(f"查询失败: {r}")
            continue
        fund_data, error, fund_name, managers, rate_data, capinfo_data, combined_data, combined_performance, scale_data = r
        if error:
            result["errors"].append(error)
            continue

        funds_data.append(fund_data)
        all_managers.append((fund_name, managers))
        all_rates.append((fund_name, rate_data))
        all_capinfos.append((fund_name, capinfo_data))
        all_analysis.append((fund_name, combined_data, combined_performance))
        all_scales.append((fund_name, scale_data))

    if not funds_data:
        result["error"] = "未能获取任何基金数据"
        return result

    try:
        file_path, desc_path = _build_output_files(
            output_dir=output_dir,
            funds_data=funds_data,
            all_managers=all_managers,
            all_rates=all_rates,
            all_capinfos=all_capinfos,
            all_analysis=all_analysis,
            all_scales=all_scales,
            errors=result["errors"],
        )
    except Exception as exc:
        result["error"] = f"写入结果文件失败: {exc!s}"
        return result

    # 生成业绩走势图
    try:
        fund_codes_for_chart = [fd.get("ofcode") for fd in funds_data]
        chart_result = await generate_performance_charts(fund_codes_for_chart, output_dir)
        result["chart_final_returns"] = chart_result["final_returns"]
        
        # 更新description文件，添加走势图信息
        try:
            _update_description_with_charts(desc_path, chart_result, fund_codes_for_chart)
        except Exception as e:
            result["errors"].append(f"更新描述文件失败: {e}")
    except Exception as exc:
        result["errors"].append(f"生成走势图失败: {exc!s}")

    result["file_path"] = str(file_path)
    result["description_path"] = str(desc_path)
    result["fund_count"] = len(funds_data)
    result["fund_names"] = [fd.get("secucname") or fd.get("secuabbr") or fd.get("ofcode") 
                           for fd in funds_data]
    return result


def _update_description_with_charts(
    desc_path: Path,
    chart_result: Dict[str, Any],
    fund_codes: List[str],
) -> None:
    """更新description文件，添加走势图信息。"""
    if not desc_path.exists():
        return
    
    # 读取现有内容
    existing_lines = desc_path.read_text(encoding="utf-8").split("\n")
    
    # 找到合适的位置插入走势图信息（在"数据说明"之后）
    insert_idx = len(existing_lines)
    for i, line in enumerate(existing_lines):
        if line.startswith("数据说明:"):
            insert_idx = i + 1
            break
    
    new_lines = []
    new_lines.append("")
    new_lines.append("Performance Charts:")
    
    image_paths = chart_result.get("image_paths", [])
    final_returns = chart_result.get("final_returns", {})
    
    for period, period_name in PERIODS.items():
        filename = f"{'_'.join(fund_codes)}_HS300_{period}.jpg"
        new_lines.append(f"  - {period_name}: {filename}")
    
    new_lines.append("")
    new_lines.append("Cumulative Return by Period:")
    
    for period, period_name in PERIODS.items():
        new_lines.append(f"  {period_name}:")
        returns = final_returns.get(period, {})
        for fc in fund_codes:
            ret = returns.get(fc)
            if ret is not None:
                new_lines.append(f"    - {fc}: {ret:.2f}%")
            else:
                new_lines.append(f"    - {fc}: --")
        hs300_ret = returns.get("HS300")
        if hs300_ret is not None:
            new_lines.append(f"    - HS300: {hs300_ret:.2f}%")
    
    # 插入新内容
    existing_lines.insert(insert_idx, "\n".join(new_lines))
    desc_path.write_text("\n".join(existing_lines), encoding="utf-8")


def run_cli() -> None:
    """命令行执行入口。"""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(
        description="基金对比查询：支持多只基金同时查询和对比",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python get_fund_detail.py 000001
  python get_fund_detail.py 000001,161039
  python get_fund_detail.py 000001 161039 018956
  python get_fund_detail.py --funds 000001,161039 --output gs-fund-compare
        """
    )
    parser.add_argument("fund_codes", nargs="*", help="基金代码（支持空格或逗号分隔）")
    parser.add_argument("--funds", dest="funds_opt", help="基金代码（逗号分隔）")
    parser.add_argument("--output", dest="output_dir", help="输出目录")
    args = parser.parse_args()

    # 校验 API Key
    if not GS_API_KEY:
        print(NO_API_KEY_MSG)
        sys.exit(1)

    # 解析基金代码
    fund_codes = []
    if args.funds_opt:
        # 逗号分隔
        fund_codes = [f.strip() for f in args.funds_opt.split(",") if f.strip()]
    if args.fund_codes:
        # 位置参数
        fund_codes.extend([f.strip() for f in args.fund_codes if f.strip()])
    
    # 去重
    fund_codes = list(dict.fromkeys(fund_codes))
    
    if not fund_codes:
        print("错误: 请提供基金代码", file=sys.stderr)
        parser.print_help(sys.stderr)
        sys.exit(1)

    # 数量限制提示
    if len(fund_codes) < 2:
        print(f"提示: 当前对比 {len(fund_codes)} 只基金，建议输入2-4只基金进行对比", file=sys.stderr)

    # 输出目录
    output_dir = Path(args.output_dir) if args.output_dir else _get_default_output_dir()

    async def _main() -> None:
        try:
            result = await compare_funds(fund_codes=fund_codes, output_dir=output_dir)
        except Exception as exc:
            print(f"错误: {exc}", file=sys.stderr)
            sys.exit(1)

        if "error" in result:
            print(f"错误: {result['error']}", file=sys.stderr)
            sys.exit(2)

        print(f"文件: {result['file_path']}")
        print(f"描述: {result['description_path']}")
        print(f"对比基金数量: {result['fund_count']}")
        print(f"对比基金: {', '.join(result['fund_names'])}")
        
        if result.get("errors"):
            print("\n部分基金查询失败:")
            for err in result["errors"]:
                print(f"  - {err}")

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_main())
    finally:
        loop.close()


# ============================================================================
# 走势图生成功能
# ============================================================================


async def query_fund_performance_plot(
    fund_code: str,
    period: str,
    index: str = INDEX_CODE,
    api_url: str = DEFAULT_PLOT_API_URL,
) -> Tuple[Optional[List[Dict]], Optional[str]]:
    """查询基金业绩走势数据。"""
    try:
        params = {
            "ofcode": fund_code,
            "period": period,
            "index": index,
            "softName": "goldsun_skills",
            "skillName": "gs-fund-compare"
        }
        if GS_API_KEY:
            params["apiKey"] = GS_API_KEY
        async with httpx.AsyncClient(timeout=60.0, verify=_ssl_ctx) as client:
            resp = await client.get(api_url, params=params)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as exc:
        return None, f"HTTP错误: {exc.response.status_code}"
    except Exception as exc:
        return None, f"请求失败: {exc!s}"

    result_obj = data.get("result", [{}])[0] if data.get("result") else {}
    if result_obj.get("code") != 0:
        return None, f"接口错误: {result_obj.get('msg', '未知错误')}"

    data_list = data.get("data", [])
    if not data_list:
        return None, "未获取到走势数据"

    return data_list, None


def calculate_cumulative_return(data_list: List[Dict]) -> Tuple[List, List, List]:
    """计算累计收益率。"""
    dates = []
    fund_returns = []
    index_returns = []
    
    last_valid_index_return = 0.0  # 用于填充缺失的沪深300收益
    
    for item in data_list:
        trading_date = item.get("tradingdate", "")
        if not trading_date:
            continue
        
        try:
            date = datetime.strptime(trading_date, "%Y%m%d")
        except (ValueError, TypeError):
            continue
        
        # 基金收益
        profit_val = item.get("profit")
        if not profit_val or str(profit_val).strip() == "":
            continue
        try:
            fund_return = float(profit_val)
        except (ValueError, TypeError):
            continue
        
        # 沪深300指数收益 - 如果为空，使用前一个有效值填充
        index_val = item.get("profitIndex")
        if index_val and str(index_val).strip():
            try:
                index_return = float(index_val)
                last_valid_index_return = index_return  # 更新最后的有效值
            except (ValueError, TypeError):
                index_return = last_valid_index_return  # 使用前一个有效值
        else:
            index_return = last_valid_index_return  # 使用前一个有效值
        
        dates.append(date)
        fund_returns.append(fund_return)
        index_returns.append(index_return)
    
    return dates, fund_returns, index_returns


async def get_period_plot_data(
    fund_codes: List[str],
    period: str,
) -> Tuple[Dict[str, float], Dict[str, Dict], List[str]]:
    """
    获取周期数据：查询一次API，返回最终收益和绑图数据。
    返回: (final_returns, all_fund_data, errors)
    """
    results = {}
    all_fund_data = {}
    errors = []
    first_fund_index_returns = None
    
    # 并发查询所有基金的API
    async def query_single(fund_code: str):
        data_list, error = await query_fund_performance_plot(fund_code, period)
        return fund_code, data_list, error
    
    query_results = await asyncio.gather(*[query_single(fc) for fc in fund_codes], return_exceptions=True)
    
    for r in query_results:
        if isinstance(r, Exception):
            errors.append(str(r))
            continue
        fund_code, data_list, error = r
        if error:
            errors.append(f"{fund_code}: {error}")
            results[fund_code] = None
            continue
        
        if not data_list:
            results[fund_code] = None
            continue
        
        # 处理绑图数据
        dates, fund_returns, index_returns = calculate_cumulative_return(data_list)
        if dates:
            all_fund_data[fund_code] = {
                "dates": dates,
                "fund_returns": fund_returns,
                "index_returns": index_returns,
            }
        
        # 获取最终收益
        last_item = data_list[-1]
        fund_profit = last_item.get("profit")
        if fund_profit and str(fund_profit).strip():
            try:
                results[fund_code] = float(fund_profit)
            except:
                results[fund_code] = None
        else:
            results[fund_code] = None
        
        # 获取沪深300收益
        if first_fund_index_returns is None:
            index_profit = None
            for item in reversed(data_list):
                idx_val = item.get("profitIndex")
                if idx_val and str(idx_val).strip():
                    index_profit = idx_val
                    break
            
            if index_profit:
                try:
                    first_fund_index_returns = float(index_profit)
                except:
                    first_fund_index_returns = None
    
    results["HS300"] = first_fund_index_returns
    return results, all_fund_data, errors


async def generate_performance_charts(
    fund_codes: List[str],
    output_dir: Path,
) -> Dict[str, Any]:
    """生成基金业绩走势图（优化：每周期API只查询一次）。"""
    periods = list(PERIODS.keys())
    
    # 并发获取所有周期的数据
    async def get_period_data(period: str) -> Tuple[str, Dict, Optional[str], List[str]]:
        """获取单个周期的所有数据（只查询一次API）"""
        returns, fund_data, errors = await get_period_plot_data(fund_codes, period)
        return period, returns, errors
    
    # 并发执行所有周期
    results = await asyncio.gather(*[get_period_data(p) for p in periods], return_exceptions=True)
    
    final_returns = {}
    all_errors = []
    
    for r in results:
        if isinstance(r, Exception):
            all_errors.append(str(r))
            continue
        period, returns, errors = r
        final_returns[period] = returns
        if errors:
            all_errors.extend(errors)
    
    return {
        "final_returns": final_returns,
        "errors": all_errors,
    }


if __name__ == "__main__":
    run_cli()
