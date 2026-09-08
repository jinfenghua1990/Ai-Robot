/** Shared timing constants used across the frontend */

/** How long a toast notification stays visible (ms) */
export const TOAST_DURATION = 3000;

/** Standard polling interval for realtime data (ms) */
export const POLL_INTERVAL = 30000;

/** Slow polling interval for infrequent updates, e.g. 5-min refresh (ms) */
export const SLOW_POLL_INTERVAL = 300000;

/** Whether the A-share market is currently in a live trading session (weekdays 9:30-11:30 / 13:00-15:00, Beijing time). Used to gate realtime polling so we don't hammer the backend after hours. */
export const isMarketOpenNow = () => {
  const now = new Date();
  const wd = now.getDay();
  if (wd === 0 || wd === 6) return false;
  const t = now.getHours() * 60 + now.getMinutes();
  return (t >= 570 && t <= 690) || (t >= 780 && t <= 900);
};
