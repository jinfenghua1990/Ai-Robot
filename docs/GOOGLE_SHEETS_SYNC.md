# Google Sheets 同步

AIROBOT 的 Google Sheets 同步使用 Google OAuth，不保存 Google 密码。授权后会维护一个名为「AIROBOT 投资同步」的表格，包含：

- `自选`：A 股、港股、美股自选、中文名、行业/板块、分组和 Google Finance 公式列
- `持仓`：数量、成本价、现价、当日盈亏/涨幅、持仓盈亏/收益率、市值和仓位
- `指标`：MA5/20/60、RSI14、MACD、KDJ、强 B/S 状态及六项策略检查
- `信号`：美股策略信号、状态、评分、计划入场/止损/目标
- `说明`：同步范围、数据来源和限制

## 一次性配置

1. 在 Google Cloud Console 创建项目并启用 **Google Sheets API**。
2. 创建 OAuth Client ID（Web application）。
3. 添加授权回调地址：

   `http://127.0.0.1:9000/api/google-sheets/oauth/callback`

   如果从局域网地址访问服务，建议仍在本机用 `127.0.0.1:9000` 完成授权；或者将实际访问地址写入 `GOOGLE_SHEETS_REDIRECT_URI` 并在 Google Cloud 中登记完全相同的地址。

4. 在项目根目录 `.env` 增加：

   ```dotenv
   GOOGLE_SHEETS_CLIENT_ID=你的ClientID
   GOOGLE_SHEETS_CLIENT_SECRET=你的ClientSecret
   GOOGLE_SHEETS_REDIRECT_URI=http://127.0.0.1:9000/api/google-sheets/oauth/callback
   ```

5. 重启 9000 服务，进入 `/us-market?tab=health`，点击「连接 Google Sheets」，完成授权后点击「立即同步」。

授权文件默认保存到 `backend/data/google_sheets_token.json`，权限限制为当前用户可读写；页面的「断开」会删除该文件。

## 自动更新

完成授权后，9000 服务每 15 分钟自动同步一次；未完成 OAuth 时任务只读本地状态，不会向 Google 发请求。页面也提供各个页签对应的 CSV 导出入口，便于未配置 OAuth 时手动导入。
