const BASE = '/api/v2';

async function v2(path, opts = {}) {
  const url = `${BASE}${path}`;
  const response = await fetch(url, opts);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || data.message || data.error || `请求失败 ${response.status}`);
  }
  return data;
}

export const v2api = {
  health: () => v2('/health'),
  dashboard: () => v2('/dashboard'),
  candidates: (limit = 80, state) => {
    const params = new URLSearchParams();
    if (limit) params.set('limit', String(limit));
    if (state) params.set('state', state);
    return v2(`/candidates?${params.toString()}`);
  },
  sectors: (limit = 50) => v2(`/sectors?limit=${limit}`),
  actions: (limit = 30) => v2(`/actions?limit=${limit}`),
  yuzi: (limit = 100) => v2(`/yuzi?limit=${limit}`),
  watchlist: () => v2('/watchlist'),
  addWatchlist: (code, name = '', note = '', group = '默认') =>
    v2('/watchlist', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code, name, note, group }),
    }),
  removeWatchlist: (code) =>
    v2(`/watchlist/${encodeURIComponent(code)}`, { method: 'DELETE' }),
  holdings: (live = false) => v2(`/holdings?live=${live}`),
  orders: (live = false) => v2(`/orders?live=${live}`),
  tradePreview: (action, code, quantity, price) =>
    v2('/trade/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, code, quantity, price, confirm: false }),
    }),
  stockResearch: (code) => v2(`/stock/${encodeURIComponent(code)}/research`),
  stock: (code) => v2(`/stock/${encodeURIComponent(code)}`),
  factorLifecycle: (limit = 500) => v2(`/factor-lifecycle?limit=${limit}`),
  validation: (days = 20, limit = 300, persist = true) =>
    v2(`/validation?days=${days}&limit=${limit}&persist=${persist}`),
  registry: () => v2('/registry'),
  systemQuality: () => v2('/system/quality'),
  collectionStatus: () => v2('/collection/status'),
  qualityDashboard: () => v2('/system/quality-dashboard'),
  systemCheck: () =>
    v2('/system/check', { method: 'POST' }),
  persistSnapshot: () =>
    v2('/snapshot/persist', { method: 'POST' }),
  persistResearchSnapshot: () =>
    v2('/research/snapshot/persist', { method: 'POST' }),
  config: () => v2('/config'),
  setConfig: (data) =>
    v2('/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    }),
};
