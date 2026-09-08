# 独立 LLM Gateway

服务地址：`http://127.0.0.1:9002`

接口：

- `GET /health`
- `GET /v1/models`
- `POST /v1/chat/completions`

9002 只负责 LLM 网关；AIROBOT 通过 HTTP 调用它，不把页面或代码合并到 9000。

启动配置读取环境变量：

- `LLM_UPSTREAM_BASE_URL`：真实的 OpenAI 兼容上游地址
- `LLM_UPSTREAM_API_KEY`：上游密钥
- `LLM_GATEWAY_API_KEY`：调用 9002 的密钥
- `LLM_MODEL`：默认模型名

在上游地址配置完成前，`/health` 会正常返回，但聊天接口会返回 503，这是为了避免静默循环调用或伪造模型结果。
