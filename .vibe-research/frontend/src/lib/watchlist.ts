/**
 * 自选股 —— 统一读 AIROBOT 共享数据层（watchlist.json），所有子系统共享。
 * 不再使用 localStorage，所有增删直接写入共享 JSON。
 */

let _cachedCodes: string[] | null = null;

async function fetchCodes(): Promise<string[]> {
  try {
    const resp = await fetch("/api/shared/watchlist/codes");
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data.codes) ? data.codes.filter((c: string) => /^\d{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

export async function loadWatch(): Promise<string[]> {
  _cachedCodes = await fetchCodes();
  return _cachedCodes;
}

export function loadWatchSync(): string[] {
  // 同步版本返回缓存（如果没有缓存则返回空，调用方应调用 loadWatch()）
  return _cachedCodes || [];
}

export async function saveWatch(codes: string[]) {
  // 全量替换：先删不在新列表中的，再增新列表中的
  const current = await fetchCodes();
  const toRemove = current.filter((c) => !codes.includes(c));
  const toAdd = codes.filter((c) => !current.includes(c));
  for (const code of toRemove) {
    try {
      await fetch("/api/shared/watchlist/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ code }),
      });
    } catch { /* 静默 */ }
  }
  if (toAdd.length > 0) {
    try {
      await fetch("/api/shared/watchlist/add", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ codes: toAdd }),
      });
    } catch { /* 静默 */ }
  }
  _cachedCodes = codes;
}

// 从任意文本里抽取 6 位 A 股代码（逗号 / 空格 / 换行 / 顿号分隔都行，方便一次粘贴一串）。
export function parseCodes(raw: string): string[] {
  const tokens = raw.split(/[^\d]+/).filter(Boolean);
  return Array.from(new Set(tokens.filter((t) => /^\d{6}$/.test(t))));
}

// 把用户输入的一串代码并入已有自选，返回去重后的新列表 + 实际新增数量。
export function addCodes(existing: string[], raw: string): { next: string[]; added: number } {
  const incoming = parseCodes(raw).filter((c) => !existing.includes(c));
  return { next: [...existing, ...incoming], added: incoming.length };
}