---
name: gs-smart-stock-picking
description: 国信智能选股skill，用于根据各种财务指标和技术指标筛选符合条件的股票。当用户需要根据特定条件查找股票时使用此skill。任务只在主agent执行,不在子agent执行。
---

# 国信智能选股 Skill

## 概述

此skill提供国信证券智能选股接口的调用能力，用于根据财务指标、技术指标、市值等条件筛选符合条件的股票。

## skill使用引导

### 首次使用流程

1. **检查API Key配置状态**

   - 首先读取 `SECRET.md` 文件中的 `gs_api_key` 字段

   - 如果存在且不为空，直接使用该API Key进行查询

   - 如果不存在或为空，引导用户获取API Key

2. **引导用户获取API Key**

   当检测到没有有效的API Key时，向用户说明：

   > 使用国信智能选股功能需要先配置API Key。请按以下步骤获取：

   > 1. 访问 https://www.guosen.com.cn/gs/xxskills/index.html 注册/登录账号

   > 2. 登录后，点击网页一级标题栏的"登录"按钮，在弹窗上可一键复制API Key

   > 3. 获取后请告诉我您的API Key，我来帮您配置

3. **保存API Key**

   用户提供API Key后，智能体需要：

   - 将API Key写入 `SECRET.md` 文件，字段名为 `gs_api_key`

   - 确认写入成功后，继续执行用户的选股查询

   - 如果写入失败，提示用户并询问是否重试

4. **更新API Key**

   如果用户需要更换API Key，可以使用指令如"更新国信API Key"或"更换我的API Key"，智能体应：

   - 引导用户提供新的API Key

   - 更新 `SECRET.md` 中的 `gs_api_key` 字段

   - 确认更新成功

### API Key 存储格式

在 `SECRET.md` 文件中，API Key 应按以下格式存储：

- gs_api_key: 用户的国信证券API Key



## 使用场景

当Agent需要回答以下类型的问题时，应使用此skill：

- 根据财务指标筛选股票（如市盈率、市净率、净利润等）
- 根据技术指标选股（如均线、MACD、KDJ等）
- 查找满足特定条件的股票组合
- 行业板块筛选
- 涨停板、跌停板股票查询
- 资金流向筛选

## 接口信息

### 基本信息

- **接口地址**: `/mcp/smart_stock_picking`
- **请求方法**: GET
- **完整URL**: `https://dgzt.guosen.com.cn/skills/agent/mcp/smart_stock_picking?searchstring={条件}&searchtype={类型}&apiKey={API密钥}&softName=goldsun_skills`
- **认证方式**: 通过请求参数apiKey进行身份验证

### 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| searchstring | String | 是 | 选股条件，例如："市盈率小于20的银行股" |
| searchtype | String | 是 | 搜索类型，详见下表 |
| apiKey | String | 是 | API密钥，用于身份验证，每次调用技能时由用户配置 |
| softName | String | 是 | 固定字符串，送goldsun_skills |

### searchtype 搜索类型

| 类型值 | 说明 |
|--------|------|
| stock | 股票 |
| fund | 基金 |
| HK_stock | 港股 |
| US_stock | 美股 |
| NEEQ | 新三板 |
| index | 指数 |

### 响应格式

成功响应：
```json
{
  "result": [
        {
            "code": 0,
            "msg": "请求成功"
        }
    ],
  "data": {
    "tables": [
      // 返回的数据表格
    ]
  }
}
```

失败响应：
```json
{
    "result": [
        {
        	"code": -1,
        	"msg": "查询失败:no data."
        }    
    ],
    "data": null
}
```

## 调用示例

### HTTP请求示例

```http
GET /mcp/smart_stock_picking?searchstring=市盈率小于20的银行股&searchtype=stock&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port
```

### 查询不同类型资产

```http
# 查询股票
GET /mcp/smart_stock_picking?searchstring=市盈率小于20的银行股&searchtype=stock&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port

# 查询基金
GET /mcp/smart_stock_picking?searchstring=近一年收益超过20%的基金&searchtype=fund&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port

# 查询港股
GET /mcp/smart_stock_picking?searchstring=当前macd为金叉的价格最高的前十只股票&searchtype=HK_stock&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port

# 查询美股
GET /mcp/smart_stock_picking?searchstring=苹果相关股票&searchtype=US_stock&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port

# 查询指数
GET /mcp/smart_stock_picking?searchstring=上证指数&searchtype=index&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port

# 查新三板
GET /mcp/smart_stock_picking?searchstring=最近放量上涨的10家公司&searchtype=NEEQ&softName=goldsun_skills&apiKey=your-api-key HTTP/1.1
Host: your-server-host:port
```

### 响应示例

```json
{
    "result":  [
        {
            "code": 0,
            "msg": "请求成功"
        }
    ],
    "data": [
        {
            "table": {
                "港股@macd金叉(条件说明)[20260319]": [
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉",
                    "2026年03月19日港股macd金叉"
                ],
                "港股@收盘价排名名次[20260319]": [
                    17,
                    20,
                    71,
                    86,
                    213,
                    257,
                    358,
                    361,
                    474,
                    517
                ],
                "港股@收盘价[20260319]": [
                    "287.600",
                    "217.600",
                    "88.000",
                    "76.050",
                    "33.340",
                    "25.820",
                    "15.610",
                    "15.480",
                    "9.670",
                    "8.330"
                ],
                "股票简称": [
                    "云知声",
                    "泡泡玛特",
                    "海致科技集团",
                    "讯飞医疗科技",
                    "瑞声科技",
                    "中信证券",
                    "中国财险",
                    "广发证券",
                    "极兔速递-W",
                    "九源基因"
                ],
                "港股@收盘价排名[20260319]": [
                    "17/2722",
                    "20/2722",
                    "71/2722",
                    "86/2722",
                    "213/2722",
                    "257/2722",
                    "358/2722",
                    "361/2722",
                    "474/2722",
                    "517/2722"
                ],
                "港股@收盘价排名基数[20260319]": [
                    2722,
                    2722,
                    2722,
                    2722,
                    2722,
                    2722,
                    2722,
                    2722,
                    2722,
                    2722
                ],
                "股票代码": [
                    "9678.HK",
                    "9992.HK",
                    "2706.HK",
                    "2506.HK",
                    "2018.HK",
                    "6030.HK",
                    "2328.HK",
                    "1776.HK",
                    "1519.HK",
                    "2566.HK"
                ]
            }
        }
    ]
}
```

## 查询条件示例

以下是一些常用的指标选股查询条件：

| 查询类型 | 示例searchstring | 说明 |
|----------|------------------|------|
| 市盈率筛选 | "市盈率小于15的股票" | 筛选PE低于指定值的股票 |
| 市净率筛选 | "市净率小于2的股票" | 筛选PB低于指定值的股票 |
| 净利润筛选 | "净利润增长超过30%的股票" | 筛选净利润同比增长的股票 |
| 行业筛选 | "医药行业股票" | 筛选特定行业的股票 |
| 资金流向 | "主力资金净流入的股票" | 筛选资金流入的股票 |
| 涨停板 | "今日涨停的股票" | 筛选涨停股票 |
| 跌停板 | "今日跌停的股票" | 筛选跌停股票 |
| 综合筛选 | "市盈率小于20且净利润增长超过20%的科技股" | 多条件组合筛选 |

## 技能使用说明

**请严格调用脚本来执行skill！！！**

脚本gs_stock_picking.py文件在scripts目录底下

### 脚本运行方式

1. **前提条件**:
   - 安装 Python 3.6 或更高版本
   - 安装 requests 库: `pip install requests`

2. **运行命令**:
   ```bash
   python gs_stock_picking.py --searchstring "市盈率小于20的银行股" --searchtype stock --api-key your-api-key
   ```

3. **参数说明**:
   | 参数 | 说明 | 示例 |
   |------|------|------|
   | --searchstring | 选股条件，中文描述即可 | "市盈率小于20的银行股" |
   | --searchtype | 搜索类型 | stock, fund, HK_stock, US_stock, NEEQ, index |
   | --api-key | API密钥，用于身份验证 | your-api-key |

### 脚本返回结果解释

脚本会打印以下信息:

1. **查询信息**:
   - 查询条件
   - 搜索类型

2. **执行状态**:
   - 状态码: 0 表示成功，-1 表示失败
   - 消息: 描述执行结果

3. **返回数据**:
   - 如果查询成功且有数据，会打印每个结果的表格数据
   - 表格数据包含多个字段，具体字段取决于查询条件

### 示例输出

```
查询条件: 市盈率小于20的银行股
搜索类型: stock
正在查询...
状态码: 0
消息: 请求成功

结果 #1:
股票简称:
  - 工商银行
  - 建设银行
  - 农业银行
股票代码:
  - 601398.SH
  - 601939.SH
  - 601288.SH
市盈率:
  - 5.2
  - 5.5
  - 5.8
```
## 风险提示文案
风险提示：选股结果和实时行情可能有一定差异，选股结果仅作参考，不构成投资建议，请用户自主决策并自行承担投资风险。

## 注意事项

1. **认证方式**: 请求通过MCP网关统一鉴权，需在调用skill时提供有效的 `apiKey`
2. **查询内容**: searchstring参数需要清晰描述筛选条件，用户输入的中文描述即可
3. **搜索类型**: 根据查询目标选择正确的searchtype参数
4. **返回数据**: 返回的股票数据可能包含多个字段，具体字段取决于查询条件
5. **脚本依赖**: 脚本需要 requests 库，使用前请确保已安装
6. **错误处理**: 脚本会捕获请求异常并打印错误信息
7. **风险提示**: 每次skill调用后固定输出风险提示文案，这一点很重要，请牢记！
