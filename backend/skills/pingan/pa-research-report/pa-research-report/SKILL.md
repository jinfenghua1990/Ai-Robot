---
name: pa-research-report
description: 研报知识库检索工具。根据用户查询的行业、公司或主题关键词,从平安证券研报知识库中检索最相关的研报片段,并提炼总结,返回内容摘要及对应的研报来源、发布日期等信息。适用场景:券商研究、公司研究、行业研究、主题研究、研报观点、评级依据、风险提示、业绩预测等内容的查询。仅做知识库内容召回和摘要,不涉及意图推理或最终结论编排;不用于实时行情、公告新闻、财务数据查询、基金/ETF筛选或直接投资建议。触发词:研报、行业报告、知识检索、行业分析、市场研究、检索研报。
license: Proprietary
compatibility: Python 3.x;需联网访问 ai.stock.pingan.com(平安证券Skills开放平台)。仅做知识库召回与摘要。
metadata:
  category: knowledge-retrieval
  version: "1.0"
  data-source: "平安证券研报知识库"
  language: zh-CN
allowed-tools:
  - Bash(python scripts/research_report.py:*)
  - Bash(python3 scripts/research_report.py:*)
---

# Research Report — 研报检索技能

## 快速开始

使用技能目录下的 Python 脚本执行检索:

```bash
python scripts/research_report.py [关键词] [top_k] [threshold]
```

**参数说明**

- **关键词**(必填):搜索主题,如 `半导体`、`新能源`、`AI芯片`
- **top_k**(可选):返回结果数量,默认 `10`
- **threshold**(可选):相似度阈值,默认 `0.3`(范围 0.1-0.9)

**示例**:

```bash
python scripts/research_report.py 半导体 10 0.3
python scripts/research_report.py AI芯片 5 0.4
```

## 工作流

### 1. 解析用户意图

本地 Agent 接收用户自然语言问题,判断是否属于研报查询场景。

#### 1.1 场景适用性判断

首先判断用户输入是否属于**研报查询场景**。

- **适用场景**:查询某只股票/公司/行业/主题研报、研报观点、评级依据、风险提示、业绩预测、估值或产业链信息。
- **不适用场景**:实时行情、盘口、K 线、交易类问题;公告、新闻、财务指标查询;ETF/基金筛选;直接投资建议。
- **处理规则**:若属于不适用场景,请直接拒绝回答或引导用户至其他工具。

#### 1.2 结构化字段提取

若属于适用场景,需从用户输入中提取以下核心字段。这些字段构成最终请求体的核心部分,详细规则见 1.2 字段表与 1.4 请求体构造。

| 字段名 | 类型 | 必填 | 默认值 | 范围 | 说明 | 示例 |
| --- | --- | --- | --- | --- | --- | --- |
| `intent_tags` | Array\<String\> | 是 | 无 | | 意图标签数组,可选值:`"研报"`、`"公司研究"`、`"行业研究"`、`"主题研究"`。客户端可审计字段 | `["研报","公司研究"]` |
| `keywords` | Array\<String\> | 是 | 无 | 非空数组 | 从用户问题中提取的核心词数组,由本地模型识别。客户端可审计字段 | `["中国平安"]` |
| `entities` | Object | 否 | `{}` | | 结构化实体容器,包含子字段:`stocks`(股票列表)、`industries`(行业列表)、`topics`(主题列表)、`institutions`(机构列表)、`time_range`(时间范围) | `{"stocks":["中国平安"]}` |
| `question` | String | 是 | 无 | | 用户原始问题或更适合检索的简短改写 | `"帮我查一下关于中国平安最近的研报观点"` |
| `query_type` | String | 是 | 无 | | 查询类型标识,固定为 `research_report_query` | `"research_report_query"` |
| `top_k` | Integer | 否 | `10` | `1`-`50` | 召回结果数量。旧接口参数名 `top_k` | `10` |
| `vector_similarity` | Float | 否 | `0.3` | `0`-`1`,步长 `0.01` | 相似度阈值,越低召回越多。旧接口参数名 `threshold` | `0.3` |
| `size` | Integer | 否 | `3` | `1+` | 最终展示给用户的片段数量 | `3` |

> **审计说明**:`intent_tags`、`keywords` 和 `entities` 是客户端可审计字段。一期接口默认不接收这些字段,脚本会在本地输出中保留它们;新接口支持后,可设置环境变量开启透传。

**示例转换**:

**用户输入**:`帮我查一下关于中国平安最近的研报观点`

**解析结果**:

- `query_type`:`"research_report_query"`
- `intent_tags`:`["研报","公司研究"]`
- `keywords`:`["中国平安"]`
- `entities.stocks`:`["中国平安"]`
- `question`:`"帮我查一下关于中国平安最近的研报观点"`
- `top_k`:`10`(默认值)
- `vector_similarity`:`0.3`
- `size`:`3`(默认值)

#### 1.3 参数补全与优化

对于宽泛主题(如仅输入"科技"),尝试识别 2-3 个相关细分关键词组合进行检索(如 `["科技","半导体","AI"]`),以提高召回精度。

#### 1.4 请求体构造

如果用户未指定参数,使用默认值(`top_k=10`,`threshold=0.3`)。Agent 将解析后的结构化数据构造为脚本可执行的调用。

##### 模式 A:结构化 JSON 请求(Agent 侧中间表示)

```json
{
  "query_type": "research_report_query",
  "question": "我想查一下中国平安最近的研报观点",
  "intent_tags": ["研报", "公司研究"],
  "keywords": ["中国平安"],
  "entities": {
    "stocks": ["中国平安"],
    "industries": [],
    "topics": [],
    "institutions": [],
    "time_range": "最近30天"
  },
  "top_k": 10,
  "vector_similarity": 0.3,
  "size": 3
}
```

脚本会将上述结构收敛为实际的知识库接口调用(请求体仅含 `knowledge_id`、`query`、`retrieval_setting`),其余审计字段在本地保留。接口请求示例:

```bash
curl -XPOST https://ai.stock.pingan.com/restapi/yanbao/e-server-transfer-service/dify/retrieval \
  -H "X-API-Key: $PINGAN_SKILL_APIKEY" \
  -H "Content-Type: application/json" \
  -H "requestID: skill_test_$(date +%s)" \
  -H "Authorization: Bearer e4c34022e6a64e0d83dfea24b1540415" \
  -d '{
    "knowledge_id": "1_5_520_v2",
    "query": "半导体",
    "retrieval_setting": {
      "top_k": 10,
      "score_threshhold": 0.3
    }
  }'
```

> **api_key 配置**:接口 `X-API-Key` 优先读环境变量 `PINGAN_SKILL_APIKEY`,其次读 `scripts/.env` 中的 `PINGAN_SKILL_APIKEY`(脚本已随附 `.env`,开箱即用)。`Authorization Token` 与 `knowledge_id` 内置在 `DEFAULT_CONFIG`;如需覆盖,可在环境变量或 `scripts/.env` 中设置:`RESEARCH_API_URL`(接口地址)、`RESEARCH_KNOWLEDGE_ID`(知识库 ID)、`RESEARCH_TOKEN`(Authorization Bearer Token)。

##### 标签预筛选召回

接口支持按标签 ID 预筛选:把一个 JSON 字符串放进 `query` 入参,在指定标签(并集)范围内召回,可提升召回速度与精确度。请求示例:

```bash
curl -XPOST https://ai.stock.pingan.com/restapi/yanbao/e-server-transfer-service/dify/retrieval \
  -H "X-API-Key: $PINGAN_SKILL_APIKEY" \
  -H "Content-Type: application/json" \
  -H "requestID: skill_test_$(date +%s)" \
  -H "Authorization: Bearer e4c34022e6a64e0d83dfea24b1540415" \
  -d '{
    "knowledge_id": "1_5_520_v2",
    "query": "{\"question\": \"半导体\", \"label_value_ids\": [125]}",
    "retrieval_setting": {
      "top_k": 10,
      "score_threshhold": 0.3
    }
  }'
```

`label_value_ids` 来自 `scripts/label_value_ids`(第四列「标签值」→ 第三列「标签 id」,含「研报分类」「研报行业」两类)。脚本会**自动**完成以下流程,无需手动指定:

1. 按关键词匹配 `label_value_ids` 中的标签值(先精确匹配,再子串匹配);
2. 命中标签时,优先发起**标签过滤召回**(并集);若召回为空,再**回退全库召回**(不带标签过滤);
3. 未命中任何标签时,直接全库召回。

输出中的「召回模式」字段会标注实际方式:`标签过滤(...)`、`全库召回(标签过滤无有效结果,已回退;...)` 或 `全库召回(未匹配到相关标签)`。

##### 模式选择决策树

| 用户输入 | 选择模式 |
| --- | --- |
| 包含明确实体/时间范围 | 模式 A(JSON) |
| 仅简短关键词 | 模式 B(命令行,见第 2 步) |
| 宽泛主题 | 模式 A + 关键词扩展(参考 1.3) |

### 2. 执行检索脚本

在执行检索前,请确保当前工作目录包含 `scripts/research_report.py` 文件。由于不同操作系统的路径分隔符和目录切换命令存在差异,请根据当前终端环境选择对应的执行方式。

```bash
# 检测当前环境
echo $OSTYPE                  # Linux/macOS 输出 linux-gnu/darwin;Windows Git Bash 同理
echo $COMSPEC                 # Windows cmd 输出 C:\Windows\system32\cmd.exe
echo $PSVersionTable          # PowerShell(需在 PowerShell 中执行)
```

| 环境标识 | 检测命令 | 切换目录命令 | 脚本路径写法 |
| --- | --- | --- | --- |
| **Windows cmd** | `$COMSPEC` 包含 `cmd.exe` | `cd /d "%~dp0"` | `scripts\research_report.py`(反斜杠) |
| **Windows PowerShell** | `$PSVersionTable` 存在 | `Set-Location $PSScriptRoot` | `scripts\research_report.py`(反斜杠) |
| **Git Bash (Win)** | `$OSTYPE` 包含 `linux` | `cd "$(dirname "$0")"` | `scripts/research_report.py`(正斜杠) |
| **Linux / macOS** | `$OSTYPE` 为 `linux-gnu` 或 `darwin` | `cd "$(dirname "$0")"` | `scripts/research_report.py`(正斜杠) |

**执行命令**:

```bash
# 进入 skill 目录后执行
python scripts/research_report.py "用户查询关键词" 10 0.3
```

> **免确认执行**:`python` 命令默认会请求确认。命令权限由 harness 的 `settings.json` 管理(SKILL.md 本身无法授予),如需免确认,在 `~/.claude/settings.json` 的 `permissions.allow` 中加入:
> ```json
> "Bash(python scripts/research_report.py:*)",
> "Bash(python3 scripts/research_report.py:*)"
> ```
> 注:以上两条规则已默认配置,匹配 `python`/`python3` 直接调用本脚本的命令;若改用 `cd ... && python ...` 或绝对路径形式,可能仍会触发确认。

**提示**:如果命令执行报错(如路径不存在),请检查当前工作目录是否正确,确认 `scripts/research_report.py` 文件是否存在。Windows 环境下注意路径分隔符的使用。

> **中文编码问题**
> - 脚本内部已使用 `ensure_ascii=False` 以正确输出中文。
> - 若 Windows 终端显示乱码,脚本已在开头对 `win32` 平台自动重配置 `sys.stdout`/`sys.stderr` 为 UTF-8,一般无需额外处理。

**召回率优化策略**:

- **默认阈值**:`0.3` 通常能平衡准确率与召回率。
- **结果为空**:尝试将 `threshold` 降低至 `0.2`,或扩展关键词(如将"科技"扩展为"科技,半导体,AI")。
- **结果噪音大**:适当提高 `threshold` 至 `0.4`,或增加 `top_k` 后在应用层过滤。
- **标签预筛选**:脚本自动用 `label_value_ids` 先做标签过滤召回,无结果时回退全库(详见 1.4 标签预筛选召回)。

**路径错误排查**:

若报错 `FileNotFoundError` 或 `No such file`,请确认当前工作目录是否正确(使用 `pwd` 或 `cd` 查看),并确认 `scripts` 文件夹存在、`research_report.py` 文件未被误删。

### 3. 解析与总结

脚本返回检索结果后,建议按照以下步骤进行数据清洗与结构化展示,以确保输出内容的准确性和可读性。脚本内部已实现排序、去重与格式化,本节描述其规则与后端返回格式参考。

#### 3.0 后端返回格式(参考)

本小节为后端接口完整响应格式参考。脚本核心处理逻辑见 3.1 数据预处理与去重。

##### 完整响应示例

```json
{
  "records": [
    {
      "content": "研报召回片段正文...",
      "score": 0.4,
      "title": "example.pdf",
      "metadata": {
        "description": "example.pdf"
      }
    }
  ],
  "msg": null
}
```

##### records 核心字段(Agent 常用)

| 字段名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `content` | String | 是 | **段落完整内容**,优先使用 |
| `score` | Float | 是 | **综合相似度分数**,范围 0-1,越高越相关 |
| `title` | String | 否 | 文档名称(用于引用展示) |
| `metadata.description` | String | 否 | 文档描述/名称(常与 `title` 一致) |

##### 数据优先级读取策略

- **内容首选**:`content` → 段落完整内容
- **引用来源**:`title`(文档名,缺失时回退 `metadata.description`)

##### 响应码

| 状态码 | 说明 | 处理方式 |
| --- | --- | --- |
| `200` 且 `msg` 为 `null` | 成功 | 正常解析 |
| `200` 且 `msg` 非空(如 `knowledge_id入参不满足要求`) | 参数错误 | 检查 `knowledge_id` 是否正确 |
| `401`(`AUTH_KEY_INVALID`) | API Key 无效或不存在 | 检查环境变量或 `.env` 中的 `PINGAN_SKILL_APIKEY` |
| `403` | 权限不足 | 提示无权限 |
| `404` | 知识库不存在 | 提示知识库不存在 |
| `5xx` | 服务器错误 | 提示服务暂不可用 |

#### 3.1 数据预处理与去重

脚本在提取核心内容前已执行以下逻辑:

1. **阈值过滤**:服务端不会按 `score_threshhold` 过滤结果,脚本在本地按 `threshold` 过滤 `score >= threshold` 的片段。
2. **按相似度排序**:根据 `score` 字段对结果降序排列,确保高相关性结果优先展示。
3. **文档级去重**:若同一文档(通过 `title` 标识)出现多个片段,**仅保留相似度最高**的一个片段,避免冗余展示。并统计去重后的有效文档数量,用于后续汇总统计。

#### 3.2 核心摘要提取规范

从清洗后的结果中提取关键信息时,遵循以下原则:

1. **片段截取**:展示前 `5` 个最高相似度的片段;若片段过长,截取前 `200-300` 字并在末尾添加省略号 `...`,保持界面整洁。
2. **上下文完整性**:尽量保留段落的完整语义,避免在句子中间截断;若片段中包含关键实体(如人名、机构名、数值),确保核心信息不被截断。

#### 3.3 来源文档标识

仅展示文档名称(`title`)作为引用来源,不再输出原文链接:

1. **文档名**:必须包含文档名称(`title`);`title` 缺失时回退到 `metadata.description`,均缺失时显示"未知文档"。

#### 3.4 结构化输出模板

脚本最终按以下 Markdown 格式组装输出,以便前端渲染或日志记录:

```markdown
## 检索结果汇总

**关键词**: 半导体
**检索到 N 条结果,去重后 M 篇文档**

### 相关文档
- 文档名称1 (N条)
- 文档名称2 (M条)

### 核心摘要

**结果 1** (相似度: 0.xxxx)
[内容摘要]
**文档**: 来源文档名
```

#### 3.5 异常处理建议

- **无结果处理**:若去重后结果为空,脚本返回明确提示:`未找到相关文档,请尝试调整关键词或降低相似度阈值`。
- **格式错误处理**:若 `title` 缺失,展示为"未知文档",避免渲染错误。

### 4. 回答用户

基于最相关的 3-5 个片段提供总结;标注信息来源(文档名)和相似度;添加免责声明(如涉及投资建议)。

## 错误处理

当脚本执行失败或返回异常时,应遵循以下处理流程。

### 认证问题

| 症状 | 解决方案 |
| --- | --- |
| API Key 缺失/无效(返回 `401` / `AUTH_KEY_INVALID`) | **动作**:拦截请求,提示用户检查环境变量或 `scripts/.env` 中的 `PINGAN_SKILL_APIKEY` 配置;**日志**:记录 `Auth Error` 日志 |
| Token 已过期或权限不足 | 联系管理员刷新 `RESEARCH_TOKEN` |

### API 业务错误(400/500)

| 症状 | 解决方案 |
| --- | --- |
| 返回 `200` 但 `msg` 非空(如 `knowledge_id入参不满足要求`) | **动作**:解析 `msg` 字段提取具体错误信息;**反馈**:向用户展示友好提示,如"检索失败,请检查关键词格式或稍后重试";**日志**:记录完整请求参数和响应内容 |
| 返回 `403`/`404` 状态码 | 检查 `knowledge_id` 是否正确或知识库是否有访问权限 |
| 返回 `5xx` 状态码 | 知识库服务异常,提示服务暂不可用;**日志**:记录完整请求参数和响应内容 |

### 无有效结果(records 为空)

- **动作**:不返回空页面,而是提供引导性建议。
- **反馈**:提示"未找到相关研报,建议您尝试以下关键词:[推荐关键词列表]"或"请尝试降低相似度阈值"。

### 网络/超时错误

- **动作**:捕获超时异常,提示用户检查网络连接。
- **重试**:可尝试自动重试一次(最多 2 次),若仍失败则报错。

## 推荐检索关键词

常见主题与关键词对应关系:

| 用户查询 | 推荐关键词 |
| --- | --- |
| 半导体 | 半导体、芯片、集成电路、EDA、晶圆 |
| 人工智能 | AI、人工智能、大模型、LLM、NLP |
| 新能源 | 新能源、光伏、风电、储能、电池 |
| 医药 | 医药、生物医药、创新药、CXO、疫苗 |
| 金融 | 银行、券商、保险、基金、金融科技 |
| 消费 | 消费、零售、电商、白酒、家电 |

---

> 以上内容来源于内部研报知识库,仅供参考学习,不构成任何投资建议。投资有风险,决策需谨慎。
