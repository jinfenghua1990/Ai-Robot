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
 *
 *   // 外部传入 AbortSignal 取消请求
 *   const ctrl = new AbortController();
 *   apiFetch('/api/foo', { signal: ctrl.signal });
 *   ctrl.abort();  // 立即取消，不会等重试 backoff
 */
export async function apiFetch(url, options = {}, timeout = 8000, retries = 2) {
  // 仅对 GET（幂等读）做重试，避免 POST/PUT/DELETE 等写操作因重试导致重复提交
  const method = (options.method || 'GET').toUpperCase();
  const maxAttempts = method === 'GET' ? retries + 1 : 1;
  // 外部 signal（可选）：来自调用方 AbortController，用于取消请求
  const externalSignal = options.signal;
  let lastError = null;

  for (let attempt = 0; attempt < maxAttempts; attempt++) {
    // 外部已取消则立刻退出，不等 backoff
    if (externalSignal?.aborted) {
      return { ok: false, data: null, error: '请求已取消', status: 0 };
    }

    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeout);
    // 联动外部 signal：外部 abort 时立即 abort 内部 ctrl（无需等 timeout）
    const onExternalAbort = () => ctrl.abort();
    if (externalSignal) externalSignal.addEventListener('abort', onExternalAbort, { once: true });

    try {
      // 注意：fetch 的 signal 用内部 ctrl.signal，而非外部 signal
      // （外部 signal 通过上面的 listener 联动到 ctrl，避免重试时复用已 aborted 的 signal）
      const resp = await fetch(url, { ...options, signal: ctrl.signal });
      if (resp.ok) {
        const data = await resp.json();
        return { ok: true, data, error: null, status: resp.status };
      }
      // 429 限流：按 Retry-After 等待后重试（仅 GET）
      if (resp.status === 429 && attempt < maxAttempts - 1) {
        const retryAfter = Number(resp.headers.get('Retry-After')) || 2;
        lastError = 'HTTP 429 限流';
        await new Promise((r) => {
          const t = setTimeout(r, Math.min(retryAfter, 5) * 1000);
          if (externalSignal) {
            externalSignal.addEventListener('abort', () => { clearTimeout(t); r(); }, { once: true });
          }
        });
        continue;
      }
      // 4xx（非 429）：客户端错误，不重试；解析响应体提取服务端错误信息
      if (resp.status < 500) {
        let body = null;
        try { body = await resp.json(); } catch { /* 非 JSON 响应体 */ }
        const errMsg = body?.error || body?.message || `HTTP ${resp.status}`;
        return { ok: false, data: null, error: errMsg, status: resp.status };
      }
      // 5xx：服务端错误，走重试
      lastError = `HTTP ${resp.status}`;
    } catch (err) {
      // 外部取消：立即返回，不重试
      if (externalSignal?.aborted) {
        return { ok: false, data: null, error: '请求已取消', status: 0 };
      }
      // 网络错误 / 超时（AbortError）：瞬态故障，走重试
      lastError = err.name === 'AbortError' ? '请求超时' : err.message;
    } finally {
      clearTimeout(timer);
      if (externalSignal) externalSignal.removeEventListener('abort', onExternalAbort);
    }
    // 指数退避 + 抖动；最后一次失败前不等待
    if (attempt < maxAttempts - 1) {
      const backoff = Math.min(1000 * 2 ** attempt, 4000) + Math.random() * 300;
      await new Promise((r) => {
        const t = setTimeout(r, backoff);
        if (externalSignal) {
          externalSignal.addEventListener('abort', () => { clearTimeout(t); r(); }, { once: true });
        }
      });
      if (externalSignal?.aborted) {
        return { ok: false, data: null, error: '请求已取消', status: 0 };
      }
    }
  }
  return { ok: false, data: null, error: lastError || '请求失败', status: 0 };
}
