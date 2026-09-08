const STORAGE_KEY = 'airobot_indicator_settings';

export const DEFAULT_SETTINGS = {
  watchlist: {
    sentiment: true,
    momentum: true,
    mainForce: true,
    technical: true,
    sector: true,
    risk: true,
  },
  trading: {
    sentiment: true,
    momentum: false,
    mainForce: false,
    technical: false,
    sector: false,
    risk: false,
  },
  standaloneMainForce: false,
};

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    // Ignore malformed or unavailable local storage.
  }
  return DEFAULT_SETTINGS;
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // Ignore unavailable local storage.
  }
}
