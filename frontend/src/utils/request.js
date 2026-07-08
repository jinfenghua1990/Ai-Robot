/**
 * 统一 API 请求封装
 *
 * 替换散落在各 Page 的 fetch(...).then(r=>r.json()).catch(()=>null) 模板。
 * 返回 { ok, data, error, status } 结构，调用方按 ok 分支处理即可。
 *
 * 用法：
 *   const { ok, data, error } = await apiFetch('/api/watchlist');
 *   if (!ok) { 处理错误; return; }
 *   使用 data;
 *
 *   // POST 请求
 *   const { ok } = await apiFetch('/api/watchlist/add', {
 *     method: 'POST',
 *     headers: { 'Content-Type': 'application/json' },
 *     body: JSON.stringify({ stockCode: '000001' }),
 *   });
 */
export async function apiFetch(url, options = {}, timeout = 8000, retries = 2) {
  // 仅对 GET（幂等读）做重试，避免 POST/PUT/DELETE 等写操作因重试导致重复提交
  const method = (options.method || 'GET').toUpperCase();
  const maxAttempts = method === 'GET' ? retries + 1 : 1;
  let lastError = null;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    try {
      const resp = await fetch(url, { ...options, signal: ctrl.signal });
      if (resp.ok) {
        const data = await resp.json();
        return { ok: true, data, error: null, status: resp.status };
      }
      // 4xx（含 429 限流）不重试：客户端错误/服务端限流应由调用方按状态处理
      if (resp.status < 500) {
        return { ok: false, data: null, error: `HTTP ${resp.status}`, status: resp.status };
      }
      lastError = `HTTP ${resp.status}`;
    } catch (err) {
      // 网络错误 / 超时（AbortError）：瞬态故障，走重试
      lastError = err.name === 'AbortError' ? '请求超时' : err.message;
    } finally {
      clearTimeout(timer);
    }
    // 指数退避 + 抖动；最后一次失败前不等待
    if (attempt < maxAttempts - 1) {
      const backoff = Math.min(1000 * 2 ** attempt, 4000) + Math.random() * 300;
      await new Promise((r) => setTimeout(r, backoff));
    }
  }
  return { ok: false, data: null, error: lastError || '请求失败', status: 0 };
}
