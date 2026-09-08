import { useEffect, useState } from 'react';

const STORAGE_PREFIX = 'airobot_viewmode';

export function useViewMode(key, defaultView = 'card') {
  const storageKey = `${STORAGE_PREFIX}:${key}`;
  const [view, setView] = useState(() => {
    try {
      const stored = localStorage.getItem(storageKey);
      return stored === 'table' || stored === 'card' ? stored : defaultView;
    } catch {
      return defaultView;
    }
  });
  useEffect(() => {
    try {
      localStorage.setItem(storageKey, view);
    } catch {
      // Ignore unavailable local storage.
    }
  }, [storageKey, view]);
  return [view, setView];
}
