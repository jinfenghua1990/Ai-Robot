---
name: gs_stock_financial_query
description: 查询A股、港股财务数据，包括利润表、资产负债表、现金流量表。Invoke when user asks for financial data, financial statements, profit, balance sheet, cash flow, or financial metrics.
---

# 财务数据查询

本skill提供查询A股、港股财务数据的能力，包括利润表、资产负债表、现金流量表等财务报表数据。

## 服务地址

默认服务地址: `https://dgzt.guosen.com.cn/skills`

## 密钥来源与安全说明

- 本技能使用一个环境变量：`GS_API_KEY`。
- `GS_API_KEY` 由国信证券接口服务签发，用于接口鉴权。
- 在提供密钥前，请先确认密钥来源、可用范围、有效期及是否支持重置/撤销。
- **禁止在代码、提示词、日志或输出文件中硬编码/明文暴露密钥**。

## 典型查询示例
### 基础财务指标查询
1. 贵州茅台近三年的营业收入和净利润是多少？
2. 宁德时代最新季度的毛利率和净利润率分别是多少？
3. 比亚迪的资产负债率和流动比率如何？
### 财务三表查询
1. 查询中国平安2024年的利润表关键数据
2. 招商银行最近五年的资产负债表核心指标
3. 对比贵州茅台、五粮液、泸州老窖近三年的毛利率
4. 查询宁德时代、比亚迪的营收增长率、净利润、ROE
5. 超出5个实体时，系统自动截取前5家进行查询，并在描述文件中提示
### 港股财务数据查询
1.查询腾讯控股最新的关键财务指标
2.小米集团近三年的营业收入和归母净利润
3.阿里巴巴港股的资产负债表和现金流量表
### 单季度与 TTM 查询
1. 宁德时代2024Q3的单季度营业收入和归母净利润
2. 格力电器 EPS TTM 和 ROE TTM
3. 美的集团最近四个季度的单季度净利润环比变化
### 研发与分红数据
1. 查询科大讯飞近三年的研发费用及研发费用率
2. 中国神华历年分红金额和股息率

## 功能范围

### 1. 查询A股资产负债表

**接口**: `GET /gsnews/gsf10/financial/balanceSheet/1.0`

查询A股上市公司资产负债表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码，如 `600000`, `000001` |
| market | 是 | string | 证券市场，SH-上海，SZ-深圳 |
| reportType | 否 | string | 财报类型：Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报，默认为Q0 |
| reportYear | 否 | string | 财报年份，如 `2024` |
| count | 否 | string | 财报数量 |

### 2. 查询A股利润表

**接口**: `GET /gsnews/gsf10/financial/incomeStatement/1.0`

查询A股上市公司利润表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| market | 是 | string | 证券市场，SH-上海，SZ-深圳 |
| reportType | 否 | string | 财报类型：Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报，默认为Q0 |
| reportYear | 否 | string | 财报年份 |
| count | 否 | string | 财报数量 |

### 3. 查询A股现金流量表

**接口**: `GET /gsnews/gsf10/financial/cashFlowStatement/1.0`

查询A股上市公司现金流量表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| market | 是 | string | 证券市场，SH-上海，SZ-深圳 |
| reportType | 否 | string | 财报类型：Q0-最新，Q4-年报，Q2-半年报，Q3-三季报，Q1-一季报，默认为Q0 |
| reportYear | 否 | string | 财报年份 |
| count | 否 | string | 财报数量 |

### 4. 查询港股资产负债表

**接口**: `GET /gsnews/hkf10/financial/balanceSheet/1.0`

查询港股上市公司资产负债表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码，如 `02020` |
| market | 是 | string | 证券市场，HK |
| reportYear | 否 | string | 报告日期，如 `2021-06-30` |
| reportType | 否 | string | 报告类型：Q1-一季报，Q2-中报，Q3-三季报，Q4-年报 |
| count | 否 | string | 查询期数，默认为1 |

### 5. 查询港股利润表

**接口**: `GET /gsnews/hkf10/financial/incomeStatement/1.0`

查询港股上市公司利润表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| market | 是 | string | 证券市场，HK |
| reportYear | 否 | string | 报告日期 |
| reportType | 否 | string | 报告类型：Q1-一季报，Q2-中报，Q3-三季报，Q4-年报 |
| count | 否 | string | 查询期数，默认为1 |

### 6. 查询港股现金流量表

**接口**: `GET /gsnews/hkf10/financial/cashFlowStatement/1.0`

查询港股上市公司现金流量表。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| market | 是 | string | 证券市场，HK |
| reportYear | 否 | string | 报告日期 |
| reportType | 否 | string | 报告类型：Q1-一季报，Q2-中报，Q3-三季报，Q4-年报 |
| count | 否 | string | 查询期数，默认为1 |

## 前提条件

### 1. 获取 API Key

请联系系统管理员获取 `GS_API_KEY`。

### 2. 配置环境变量

```bash
# macOS 添加到 ~/.zshrc，Linux 添加到 ~/.bashrc
export GS_API_KEY="your_api_key_here"
```

**Windows PowerShell:**
```powershell
$env:GS_API_KEY="your_api_key_here"
```

## 操作步骤
### 步骤 1: 获取并配置 API Key

**检查 API Key 配置**:
- 尝试读取 `./memory.md` 文件中的 `GS_API_KEY` 字段
- 如果文件不存在或字段未配置，引导用户获取

**获取 API Key**（当未配置时）:
1. 访问国信证券 Skill 聚合网站: https://www.guosen.com.cn/gs/xxskills/index.html
2. 注册/登录账号
3. 点击网页顶部「登录」按钮
4. 登录后点击账号，在弹窗中一键复制 API Key

**保存 API Key**:
- 注册成功后，**立即**将以下内容写入 `./memory.md`:
  ```markdown
  GS_API_KEY=your_actual_api_key_here
  ```
- 如果 `./memory.md` 文件不存在，创建该文件并写入上述内容
- 如果文件已存在，添加或更新 `GS_API_KEY` 字段

**使用脚本读取 API Key**:
- 调用 `scripts/get_data.py` 时，脚本会自动从环境变量读取 `GS_API_KEY`
- 智能体需要先从 `./memory.md` 读取 `GS_API_KEY`，然后将其设置为环境变量供脚本使用

### 步骤 2: 执行查询
1. 根据用户需求选择查询接口:
```bash
# 查询A股资产负债表
python3 {baseDir}/scripts/get_data.py a_balance --code 600519 --market SH

# 查询A股利润表
python3 {baseDir}/scripts/get_data.py a_income --code 600519 --market SH --report_type Q4

# 查询A股现金流量表
python3 {baseDir}/scripts/get_data.py a_cashflow --code 600519 --market SH --count 4

# 查询港股资产负债表
python3 {baseDir}/scripts/get_data.py hk_balance --code 02020

# 查询港股利润表
python3 {baseDir}/scripts/get_data.py hk_income --code 02020 --count 4

# 查询港股现金流量表
python3 {baseDir}/scripts/get_data.py hk_cashflow --code 02020
```

### 2. 代码调用

```python
import sys
sys.path.insert(0, "{baseDir}/scripts")
from get_data import (
    query_a_stock_balance_sheet,
    query_a_stock_income_statement,
    query_a_stock_cash_flow_statement,
    query_hk_stock_balance_sheet,
    query_hk_stock_income_statement,
    query_hk_stock_cash_flow_statement,
)

# 查询A股资产负债表
result = query_a_stock_balance_sheet("600519", "SH")

# 查询A股利润表
result = query_a_stock_income_statement("600519", "SH", report_type="Q4")

# 查询A股现金流量表
result = query_a_stock_cash_flow_statement("600519", "SH", count=4)

# 查询港股资产负债表
result = query_hk_stock_balance_sheet("02020")

# 查询港股利润表
result = query_hk_stock_income_statement("02020", count=4)

# 查询港股现金流量表
result = query_hk_stock_cash_flow_statement("02020")
```

### 3. 返回字段说明

各接口返回字段请参考接口文档。统一返回格式如下:

```json
{
    "result": {
        "code": 0,
        "msg": "请求成功"
    },
    "data": { ... }
}
```

**数据字段匹配规则**: 返回数据中的字段值通过info数组中的key匹配获取具体指标值。

## 环境变量

| 变量 | 说明 | 默认 |
|---|---|---|
| `GS_API_KEY` | 国信接口鉴权 key（必填） | 空 |

## 常见问题

**错误: GS_API_KEY is required.**  
→ 需配置GS_API_KEY，请联系管理员获取并手动配置

**接口返回错误怎么办？**  
→ 检查证券代码是否正确，确认市场代码是否匹配

## 合规说明
- API Key 需要从 `./memory.md` 的 `GS_API_KEY` 字段读取，不要硬编码
- 调用脚本前必须设置环境变量 `GS_API_KEY`
- **重要**: 如果 API 调用失败，直接提醒用户"数据获取失败"，**不要**尝试从联网搜索或其他渠道获取数据
- 禁止在代码或提示词中硬编码账号 ID 或 token。
- 环境变量按敏感信息处理，不在日志或回复中泄露。
- 返回数据仅供参考，不作为投资建议。