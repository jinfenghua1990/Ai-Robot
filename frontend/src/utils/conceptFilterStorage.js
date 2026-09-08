const STORAGE_KEY = 'panorama_concept_filter_selected';

export const ALL_CONCEPTS = '__ALL__';

const LEGACY_DEFAULT = [
  '算力', '共封装光学CPO', '液冷', '人形机器人', '机器人概念',
  'AI应用', '核聚变', '商业航天', '低空经济', '固态电池',
  '铜缆高速连接', '车路云', '存储芯片', 'PCB概念', '人工智能',
];

function isLegacyDefault(values) {
  return values.length === LEGACY_DEFAULT.length
    && values.every((value, index) => value === LEGACY_DEFAULT[index]);
}

export function loadSelectedConcepts() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const values = JSON.parse(raw);
      if (Array.isArray(values)) return isLegacyDefault(values) ? [ALL_CONCEPTS] : values;
    }
  } catch {
    // Ignore malformed or unavailable local storage.
  }
  return [ALL_CONCEPTS];
}

export function saveSelectedConcepts(values) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(values));
  } catch {
    // Ignore unavailable local storage.
  }
}
