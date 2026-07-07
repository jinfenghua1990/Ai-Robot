import { useState, useEffect } from 'react';
import { apiFetch } from '../utils/request';

const todayStr = () => {
  const n = new Date();
  return `${n.getFullYear()}-${String(n.getMonth()+1).padStart(2,'0')}-${String(n.getDate()).padStart(2,'0')}`;
};

export function useDatePicker() {
  const [selectedDate, setSelectedDate] = useState('');

  useEffect(() => {
    (async () => {
      const { ok, data } = await apiFetch('/api/latest-date');
      if (ok && data?.date) setSelectedDate(data.date);
      else setSelectedDate(todayStr());
    })();
  }, []);

  const changeDate = (offset) => {
    if (!selectedDate) return;
    const [y, m, d] = selectedDate.split('-').map(Number);
    const dt = new Date(y, m - 1, d);
    dt.setDate(dt.getDate() + offset);
    setSelectedDate(`${dt.getFullYear()}-${String(dt.getMonth()+1).padStart(2,'0')}-${String(dt.getDate()).padStart(2,'0')}`);
  };

  return { selectedDate, setSelectedDate, changeDate };
}
