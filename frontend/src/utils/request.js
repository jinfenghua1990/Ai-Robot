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

/**
 * 把接口返回的错误值转换成可直接展示的文本。
 * 后端有时会返回 { detail: ... } / { message: ... }，直接拼接会显示
 * "[object Object]"，因此所有页面统一经过这里处理。
 */
export function formatApiError(value, fallback = '请求失败') {
  if (value == null || value === '') return fallback;
  if (typeof value === 'string') {
    const text = value.trim();
    if (text === 'Invalid API key') return '写入会话无效，请刷新页面后重试';
    if (text === 'API_READ_KEY 未配置，服务拒绝写操作') return '服务未配置写入密钥，请检查 API_READ_KEY';
    return text || fallback;
  }
  if (value instanceof Error) return value.message || fallback;
  if (Array.isArray(value)) {
    const text = value.map((item) => formatApiError(item, '')).filter(Boolean).join('、');
    return text || fallback;
  }
  if (typeof value === 'object') {
    const nested = value.message ?? value.detail ?? value.error ?? value.msg ?? value.reason;
    if (nested != null && nested !== value) return formatApiError(nested, fallback);
    try {
      const json = JSON.stringify(value);
      return json && json !== '{}' ? json : fallback;
    } catch {
      return fallback;
    }
  }
  return String(value);
}

export async function apiFetch(url, options = {}, timeout = 8000, retries = 2) {
  // 仅对 GET（幂等读）做重试，避免 POST/PUT/DELETE 等写操作因重试导致重复提交
  const method = (options.method || 'GET').toUpperCase();
  let maxAttempts = method === 'GET' ? retries + 1 : 1;
  // 外部 signal（可选）：来自调用方 AbortController，用于取消请求
  const externalSignal = options.signal;
  let lastError = null;
  let authRefreshAttempted = false;

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
      // 若请求带 body 但未显式声明 Content-Type，自动补 application/json，
      // 否则 FastAPI 无法解析 JSON 请求体，会返回 422（导致所有写操作静默失败）。
      const reqHeaders = { ...(options.headers || {}) };
      if (options.body != null && !reqHeaders['Content-Type']) {
        reqHeaders['Content-Type'] = 'application/json';
      }
      const resp = await fetch(url, { ...options, headers: reqHeaders, signal: ctrl.signal });
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
      // 页面可能在服务重启或密钥轮换前打开，旧 HttpOnly cookie 会导致
      // 写请求第一次返回 401。刷新根页面只更新 cookie，不把密钥暴露给 JS，
      // 且第一次请求已被鉴权中间件拦截，不会产生重复写入。
      if (resp.status === 401 && method !== 'GET' && !authRefreshAttempted) {
        let body = null;
        try { body = await resp.clone().json(); } catch { /* 非 JSON 响应体 */ }
        const authDetail = body?.detail ?? body?.error ?? body?.message;
        const authCode = typeof authDetail === 'object' ? authDetail?.code : body?.code;
        const authRawMessage = typeof authDetail === 'object'
          ? authDetail?.message ?? authDetail?.detail ?? ''
          : String(authDetail ?? '');
        if (authCode === 'UNAUTHORIZED' || authRawMessage.includes('Invalid API key')) {
          authRefreshAttempted = true;
          maxAttempts = Math.max(maxAttempts, attempt + 2);
          try {
            await fetch('/', { method: 'GET', credentials: 'same-origin', cache: 'no-store' });
          } catch { /* 下一次请求会返回原始鉴权错误 */ }
          continue;
        }
      }
      // 4xx（非 429）：客户端错误，不重试；解析响应体提取服务端错误信息
      if (resp.status < 500) {
        let body = null;
        try { body = await resp.json(); } catch { /* 非 JSON 响应体 */ }
        // FastAPI HTTPException 返回 {"detail": "..."}，兼容 error/message 两种格式
        const errMsg = formatApiError(body?.detail ?? body?.error ?? body?.message, `HTTP ${resp.status}`);
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
