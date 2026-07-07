---
name: gs_stock_market_query
description: 查询沪深A股、北交所、港股、美股的实时行情、历史行情、资金流向、涨跌幅排名等。Invoke when user asks for stock quotes, market data, stock prices, historical data, fund flow, or stock rankings.
---

# 股市行情查询

本skill提供查询股市行情的能力，包括实时行情、历史行情、资金流向、涨跌幅排名等功能。

## 服务地址

默认服务地址: `https://dgzt.guosen.com.cn/skills`

## 密钥来源与安全说明
- 本技能使用一个环境变量：`GS_API_KEY`。
- `GS_API_KEY` 由国信证券接口服务签发，用于接口鉴权。
- 在提供密钥前，请先确认密钥来源、可用范围、有效期及是否支持重置/撤销。
- **禁止在代码、提示词、日志或输出文件中硬编码/明文暴露密钥**。


## 核心数据约束
### 必须指定明确的查询对象
要求：查询语句中必须包含明确的证券名称、代码、指数名称或板块 / 概念名称；
禁止：纯泛指表述，如”某只股票”、”某个行业”、”一些热门股”等。
示例类型	示例内容
❌ 错误示例	查询某热门股票的行情
✅ 正确示例	查询宁德时代今日行情
✅ 正确示例	查询 300750 近 20 个交易日的历史行情
✅ 正确示例	查询电力板块的涨跌幅排行
###  单次查询实体上限 
受后端接口限制，若用户请求超出上述限制，Skill 将拆分为多次调用，分批获取后合并结果，并在描述文件中说明分批情况。
数据类型	单次最多证券实体数	超出处理方式
实时行情	10 个	自动拆分为多次调用，合并结果
历史行情	1 个	自动逐一调用
资金流向	1 个	自动逐一调用

### 行情数据时效性说明
实时行情	仅在交易时段（A 股 09:30–15:00，港股 09:30–16:00）返回最新价；非交易时段返回上一交易日收盘价
历史行情	数据截止至最近已收盘的交易日；默认返回最近 20 个交易日
北向/南向资金	每日收盘后更新，当日数据在收盘后约 30 分钟可用


## 查询示例
### 实时行情
1. 查询贵州茅台当前的股价和涨跌幅
2. 宁德时代、比亚迪今天的实时行情
3. 查询腾讯控股（港股）现在的最新价和成交量
### 历史 K 线
1. 查询格力电器近 20 个交易日的日 K 数据
2. 查询 300750 从 2025 年 1 月 1 日到 3 月 15 日的历史行情
3. 中芯国际近三个月每日收盘价和涨跌幅
### 资金流向
1. 查询宁德时代今日的主力资金净流入情况
2. 比亚迪大单和超大单资金今天的买入卖出情况
3. 今日北向资金持仓最多的 A 股个股是哪些？
4. 查询南向资金（港股通）今日买入最多的港股
### 板块涨跌幅排行
1. 今日行业涨跌幅排名
2. 电力板块内各成分股的实时涨跌幅
3. 查询宁德时代所属板块的整体行情表现
4. 今天涨幅最大的概念板块是哪些？
### 涨跌停分析
1. 今日 A 股涨停家数和涨停成因分析
2. 查询今日封板时间最长的涨停股
3. 有哪些股票今日出现跌停？
### ETF 与概念联动
1. 当前市场最热门的概念板块有哪些？
2. 持有比亚迪股票的 ETF 有哪些？
3. 半导体行业 ETF（588000）的十大重仓股

## 功能范围

### 1. 查询单个证券实时行情

**接口**: `GET /gsnews/market/agentbot/queryHQInfo/1.0`

查询单个证券，可返回关联指数信息。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码，如 `000001`, `600519` |
| setCode | 否 | integer | 证券市场代码，默认 0 |
| target | 否 | integer | 站点信息 0-沪深京(默认)，3-港股美股 |

**setCode 市场代码**:
- `0`: 深圳
- `1`: 上海
- `2`: 北交所
- `-1`: 港股
- `74`: 美股

### 2. 查询多个证券实时行情

**接口**: `GET /gsnews/market/agentbot/queryCombHQ/1.0`

查询多个证券实时行情，不返回关联指数信息。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码，可多个逗号分隔 |
| setCode | 是 | string | 证券市场代码，多个用逗号分隔 |
| target | 否 | integer | 站点，0-沪深京(默认)，3-港股美股 |

### 3. 查询资金流向

**接口**: `GET /gsnews/market/agentbot/queryFundFlow/1.0`

查询ETF、个股的资金流向。仅支持沪深市场。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| period | 是 | string | 周期，单位为日，最多60日 |
| code | 否 | string | 证券代码 |
| setCode | 是 | string | 证券市场代码，0-深圳，1-上海 |

### 4. 查询涨幅排名

**接口**: `GET /gsnews/market/agentbot/queryMultiHQ/1.0`

大盘个股涨幅前N、大盘ETF涨幅前N、行业板块个股涨幅前N。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| setDomain | 是 | integer | 查询类型 |
| wantNum | 是 | integer | 返回数量，最多80 |
| sortType | 否 | integer | 1-涨幅(默认)，2-跌幅 |
| target | 否 | integer | 0-沪深(默认)，3-港股美股 |

**setDomain 查询类型**:
| setDomain | 说明 |
|-----------|------|
| 0 | 上证A股 |
| 2 | 深证A股 |
| 14515 | 北交所 |
| 6 | 沪深A股 |
| 14 | 创业板 |
| 11005 | 沪深ETF基金 |

### 5. 查询个股关联板块

**接口**: `GET /gsnews/market/agentbot/queryRelatedCombHQ/1.0`

查询个股关联板块。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| setCode | 是 | integer | 证券市场代码 |
| target | 否 | integer | 站点信息 0-沪深京(默认)，3-港股美股 |

### 6. 查询近n个交易日日行情

**接口**: `GET /gsnews/market/agentbot/queryPastHQInfo/1.0`

查询近n个交易日日行情。

**参数**:
| 参数 | 必填 | 类型 | 说明 |
|------|------|------|------|
| code | 是 | string | 证券代码 |
| setCode | 是 | string | 证券市场代码 |
| wantNums | 是 | integer | 近n个交易日 |
| target | 否 | integer | 0-沪深京(默认)，3-港股美股 |
| mas | 否 | string | 要计算的MA周期，多个以逗号分隔 |

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
1. 根据用户需求选择查询类型:
```bash
# 查询单个股票实时行情
python3 {baseDir}/scripts/get_data.py single_hq --code 600519 --set_code 1

# 查询多只股票实时行情
python3 {baseDir}/scripts/get_data.py comb_hq --codes 600519,000001 --set_codes 1,0

# 查询资金流向
python3 {baseDir}/scripts/get_data.py fund_flow --code 600519 --set_code 1 --period 10

# 查询涨幅排名
python3 {baseDir}/scripts/get_data.py multi_hq --set_domain 6 --want_num 10

# 查询个股关联板块
python3 {baseDir}/scripts/get_data.py related_comb --code 600519 --set_code 1

# 查询历史行情
python3 {baseDir}/scripts/get_data.py past_hq --code 600519 --set_code 1 --want_nums 20
```

2. 代码调用

```python
import sys
sys.path.insert(0, "{baseDir}/scripts")
from get_data import (
    query_single_hq,
    query_comb_hq,
    query_fund_flow,
    query_multi_hq,
    query_related_comb_hq,
    query_past_hq
)

# 查询上证指数
result = query_single_hq("600519", set_code=1)

# 查询多只股票
result = query_comb_hq(["600519", "000001"], [1, 0])

# 查询资金流向
result = query_fund_flow("600519", set_code=1, period=10)

# 查询沪深A股涨幅前10
result = query_multi_hq(set_domain=6, want_num=10)

# 查询个股关联板块
result = query_related_comb_hq("600519", set_code=1)

# 查询历史行情
result = query_past_hq("600519", set_code=1, want_nums=20)
```

3. 返回字段说明

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



## 常用市场代码参考

| 市场 | setCode | 说明 |
|------|---------|------|
| 深圳 | 0 | 深证A股 |
| 上海 | 1 | 上证A股 |
| 北交所 | 2 | 北京证券交易所 |
| 港股 | -1 | 香港股票 |
| 美股 | 74 | 美国股票 |

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
- 禁止在代码或提示词中硬编码账号 ID 或 token。
- 环境变量按敏感信息处理，不在日志或回复中泄露。
- 返回数据仅供参考，不作为投资建议。

## 注意事项
- API Key 需要从 `./memory.md` 的 `GS_API_KEY` 字段读取，不要硬编码
- 调用脚本前必须设置环境变量 `GS_API_KEY`
- **重要**: 如果 API 调用失败，直接提醒用户"数据获取失败"，**不要**尝试从联网搜索或其他渠道获取数据
- 返回数据仅供参考，不作为投资建议。