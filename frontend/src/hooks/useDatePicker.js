import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const fmtDate = (n) => {
  return `${n.getFullYear()}-${String(n.getMonth()+1).padStart(2,'0')}-${String(n.getDate()).padStart(2,'0')}`;
};

// 默认“盘后数据”= 前一个交易日：今天-1，跳过周末（周六→周五，周日→周五）
const prevTradingDay = () => {
  const n = new Date();
  n.setDate(n.getDate() - 1);
  const dow = n.getDay();
  if (dow === 0) n.setDate(n.getDate() - 2);      // 周日 -> 上周五
  else if (dow === 6) n.setDate(n.getDate() - 1); // 周六 -> 周五
  return fmtDate(n);
};

export function useDatePicker() {
  // 默认“盘后”= 前一个交易日（昨天/跳过周末），打开即有盘后数据、无需手动选。
  // 异步拉 /api/latest-date 做校正：若最新盘后日已是今天（收盘后已生成），仍回退到前一个交易日；
  // 若今天尚无盘后数据（latest-date 落在更早日期），则采用该有数据的日期。
  const [selectedDate, setSelectedDate] = useState(prevTradingDay());
  const [loadingDate, setLoadingDate] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { ok, data } = await apiFetch('/api/latest-date');
        if (!cancelled && ok && data && data.date) {
          const latest = data.date;   // YYYY-MM-DD（ISO，可直接字典序比较）
          const prev = prevTradingDay();
          // 不晚于“前一天”：latest 比前一天更晚（即今天）时用前一天，否则用 latest
          setSelectedDate(latest > prev ? prev : latest);
        }
      } catch {
        // 保留 prevTradingDay 的回退值
      } finally {
        if (!cancelled) setLoadingDate(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const changeDate = (offset) => {
    if (!selectedDate) return;
    const [y, m, d] = selectedDate.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + offset);
    setSelectedDate(fmtDate(dt));
  };

  return { selectedDate, setSelectedDate, changeDate, loadingDate };
}
