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
export async function apiFetch(url, options = {}) {
  try {
    const resp = await fetch(url, options);
    if (!resp.ok) {
      return { ok: false, data: null, error: `HTTP ${resp.status}`, status: resp.status };
    }
    const data = await resp.json();
    return { ok: true, data, error: null, status: resp.status };
  } catch (err) {
    return { ok: false, data: null, error: err.message, status: 0 };
  }
}
