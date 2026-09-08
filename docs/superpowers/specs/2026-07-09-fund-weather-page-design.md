# 资金气象雷达二级页面设计

## 目标
做一个独立二级页面 `/fund-weather`，把自选股按机构/游资双轨资金博弈翻译成四种天气形态，给用户一个全景资金气象看板。

## 页面结构
1. 顶部：四种天气统计卡片（暴风雨/阴转晴/台风/艳阳）
2. 主体：按天气分组的股票列表
3. 每行：股票名称/代码、技术形态、机构5日净流入、游资5日净流入、AI动作指令

## 数据层
- 复用 `/api/watchlist` 的 signal 列表（含 technical.stage、quote、sectorTrend）
- 新增聚合：从 `YuziSeatDaily` JOIN `YuziDict`，按 `ts_code` 聚合近5日机构/游资净买入
- 机构识别：`yuzi_group='机构'` 或 `seat_name LIKE '%机构专用%'`
- 游资识别：`yuzi_group IN ('顶级游资','实力游资','假游资')`

## 天气判定规则
| 天气 | 条件 |
|---|---|
| ⛈️ 暴风雨 | 技术破位 + 游资5日净卖出 + 机构5日净买入 ≤ 0 |
| 🌤️ 阴转晴 | 技术破位 + 机构5日净买入 > 阈值 + 游资5日净卖出 |
| 🌪️ 台风 | 近5日涨幅 > 15% + 游资5日净买入 > 阈值 + 机构5日净卖出 |
| ☀️ 艳阳 | 技术非破位且偏多/多头 + 机构5日净买入 > 0 + 游资5日净买入 > 0 |
| ☁️ 多云 | 不满足以上任一条件 |

## API
- `GET /api/fund-weather` → 返回 `{weather_groups: [{weather, label, color, stocks: [...]}]}`

## 前端
- 路径：`/fund-weather`
- 组件：`FundWeatherPage.jsx`
- 路由：在 `App.jsx` 注册
- 每只股票可点击进入 `/stock/:code`

## 范围
MVP 只做页面展示，暂不做实时推送和 SignalCard 嵌入。后续根据效果决定是否全量接入。
