# V2（9001）前端接入 / 迁移清单

> 目标：让 V2「右侧多因子决策系统」(9001) 的数据，用 9000 那套好看的 React UI 呈现。
> 编写日期：2026-07-30

---

## 0. 现实核对（重要，先读）

本次迁移**不能**按"复制 9000 的 components/styles/router 覆盖 9001"来做，因为两套前端根本不是同构：

| 维度 | 9000 主服务前端 | 9001 V2 前端 |
|---|---|---|
| 技术栈 | React 18 + Vite 5 + Tailwind + react-router-dom + echarts/recharts/lightweight-charts/framer-motion/lucide-react | **纯原生 JS**（3 个文件） |
| 文件 | `frontend/src/` 下 20 个子目录（pages/aihf、dsa、gostock、openclaw、portfolio、tagents、vibe…） | `v2_app/static/`：`app.js` + `index.html` + `styles.css` |
| 构建 | 有 `package.json` + Vite 构建 | **无**构建配置、无 package.json |
| 接口契约 | 调 `/api/...`（60+ 路由） | 仅 `/api/v2/...`（24 路由，多因子决策子集） |

结论：
1. 9001 没有"组件层/路由层"可覆盖，只有 3 个手写原生文件 → 不是覆盖，是**重构**。
2. 9000 的 React 组件绑定 `/api/...`（panorama / stock/list / dsa 等），V2 上**不存在**这些接口 → 直接复制会导致白屏/报错，"显示效果完全一致"无法靠复制实现。

---

## 1. 推荐方案 A：把 V2 接进 9000 前端（同源反代 + 新建 V2 页面）

保留唯一 React 应用（9000），在主后端加 `/api/v2/* → 9001` 同源反代，再在 React 里新建 V2 视图调 `/api/v2/*`。
- 零跨域、零前端复制、工作量最小、保住 9000 生产级服务
- 顺带把现有前端自带的 `QuantVNextPage` / `LifecycleV2Page` 真正接到后端

### A-1. 后端反代（复制 main.py 现有 `/api/v1` 模板，指向 9001）

参照 `backend/main.py` 行 350–438 的 `_dsa_proxy` 写法，新增一段：

```python
# ---------------------------------------------------------------------------
# V2 多因子决策子系统集成（9001）
# 反向代理 /api/v2/* 到 v2_app（127.0.0.1:9001），同源、零跨域
# ---------------------------------------------------------------------------
V2_BACKEND_URL = os.environ.get("V2_BACKEND_URL", "http://127.0.0.1:9001")

async def _v2_proxy(request: Request, path: str):
    target = f"{V2_BACKEND_URL}/{path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    method = request.method
    skip_req = {'host', 'content-length', 'transfer-encoding', 'connection'}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip_req}
    body = await request.body()
    client: _httpx.AsyncClient = app.state.http_client
    try:
        upstream = await client.request(method, target, headers=headers,
                                        content=body or None, timeout=60)
        skip_resp = {'content-encoding', 'transfer-encoding', 'connection', 'content-length'}
        resp_headers = {k: v for k, v in upstream.headers.items()
                        if k.lower() not in skip_resp}
        return Response(content=upstream.content, status_code=upstream.status_code,
                        headers=resp_headers,
                        media_type=upstream.headers.get('content-type'))
    except Exception as e:
        return JSONResponse({"error": "V2 backend unavailable", "detail": str(e),
                             "hint": "请启动 V2 后端：uvicorn v2_app.main:app --port 9001"},
                            status_code=503)

@app.api_route("/api/v2/{full_path:path}",
               methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def v2_api_proxy(full_path: str, request: Request):
    return await _v2_proxy(request, f"api/v2/{full_path}")
```

验证：`curl -s --noproxy '*' http://127.0.0.1:9000/api/v2/health` 应返回 `{"status":"ok"}`。

### A-2. 前端 API 客户端

新建 `frontend/src/api/v2.js`：

```js
const base = '/api/v2';
async function v2(path, opts) {
  const r = await fetch(`${base}${path}`, opts);
  if (!r.ok) throw new Error(`V2 ${path} -> ${r.status}`);
  return r.json();
}
export const v2api = {
  health:      () => v2('/health'),
  dashboard:   () => v2('/dashboard'),
  candidates:  () => v2('/candidates'),
  lifecycle:   () => v2('/factor-lifecycle'),
  holdings:    () => v2('/holdings'),
  tradePreview:(p) => v2('/trade/preview', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(p)}),
  yuzi:        () => v2('/yuzi'),
  sectors:     () => v2('/sectors'),
  stock:       (code) => v2(`/stock/${code}`),
  watchlist:   () => v2('/watchlist'),
  collection:  () => v2('/collection/status'),
  quality:     () => v2('/system/quality'),
};
```

### A-3. 新建 V2 页面（React）

在 `frontend/src/pages/` 下新增（每个页面用现有组件库 echarts/recharts/lucide，风格与 9000 一致）：

| 页面文件 | 调 V2 接口 | 对应 9001 原生页 |
|---|---|---|
| `V2DashboardPage.jsx` | `/dashboard` | 总览 |
| `V2CandidatesPage.jsx` | `/candidates` | 候选股 |
| `V2FactorLifecyclePage.jsx` | `/factor-lifecycle` | 因子生命周期 |
| `V2HoldingsPage.jsx` | `/holdings` | 持仓 |
| `V2TradePage.jsx` | `/trade/preview`、`/trade/execute` | 交易（默认预览，execute 需 ACTION_KEY + confirm） |
| `V2YuziPage.jsx` | `/yuzi` | 游资 |
| `V2SectorsPage.jsx` | `/sectors` | 板块 |
| `V2StockPage.jsx` | `/stock/{code}` | 个股 |

### A-4. 路由 + 侧边栏

- `App.jsx`：懒加载上述页面，加路由 `/v2/*`（如 `/v2/dashboard`、`/v2/candidates`…）。
- `Layout.jsx`：在「🤖 AI 决策 (DSA)」组旁新增「V2 多因子」组，或并入决策组。保留旧 9000 链接兼容。

### A-5. 接口映射（V2 返回 → 组件字段）

V2 响应形状需逐接口核对（先用 `curl` 抓样本），在页面内做轻量映射，不污染通用组件。示例：

| V2 字段（待核对） | 组件用途 |
|---|---|
| `factor_count` / `observation_count` / `candidate_count` | Dashboard KPI 卡 |
| `candidates[].code / name / score / signals` | 候选列表行 |
| `factors[].name / status / ic / regime` | 因子生命周期表 |
| `holdings[].symbol / pnl / weight` | 持仓表 |

> 注意：V2 有安全闸门——`V2_TRADING_ENABLED` 环境变量 + `ACTION_KEY` 请求头 + `confirm` 参数；前端交易页默认只走 `/trade/preview`，execute 需显式确认。

---

## 2. 备选方案 B：把 React 前端搬到 9001（不推荐）

用 React 构建产物替换 `v2_app/static/` 的 3 个原生文件，让 v2_app 自己托管 SPA，并写 adapter 把 `/api/...` 改指 `/api/v2/*`。

- 代价：要维护**两套** React 构建；V2 缺大多数 9000 接口，多数 9000 页面是死重；失去 9001 轻量零依赖优势。
- 仅当"9001 必须完全自包含、不能依赖 9000"时才考虑。

---

## 3. 执行顺序（方案 A）

1. ✅ 后端反代（A-1）+ 重启 9000，`curl /api/v2/health` 验证
2. 前端 `v2.js` 客户端（A-2）
3. 逐页面实现（A-3），每做完一个用 dev server 核对数据
4. 路由 + 侧边栏（A-4）
5. `vite build` → 部署 dist（sandbox 用 `vite build --outDir dist.new`，main.py 已优先读 dist.new）
6. 推 GitHub（ghp_ token + HTTP/1.1 重试套路）

---

## 4. 待你确认

- [ ] 选 A（接进 9000）还是 B（搬到 9001）？
- [ ] V2 哪些页面优先（建议先 dashboard + candidates + factor-lifecycle）？
- [ ] 交易页是否启用 execute（需你提供 ACTION_KEY 策略）？
