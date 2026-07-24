import { useState, useEffect } from 'react';
import { apiFetch } from '../../utils/request';
import { stripCode } from '../../utils/format';

/**
 * 全局跟踪列表缓存（避免 N 个 TrackButton 发 N 次相同请求）
 */
let _trackerCache = null;
let _trackerCachePromise = null;

async function getTrackerList() {
  if (_trackerCache) return _trackerCache;
  if (_trackerCachePromise) return _trackerCachePromise;
  _trackerCachePromise = (async () => {
    try {
      const { ok, data } = await apiFetch('/api/stock-tracker');
      if (ok && Array.isArray(data)) {
        _trackerCache = data;
      }
    } catch (e) { /* silent */ }
    _trackerCachePromise = null;
    return _trackerCache || [];
  })();
  return _trackerCachePromise;
}

/** 缓存 60 秒后自动失效 */
setInterval(() => { _trackerCache = null; }, 60000);

/**
 * 个股跟踪按键：悬浮在任意股票位置，一键加入/查看跟踪
 * - 首次渲染时检查该股是否已在跟踪列表（全局缓存，避免重复请求）
 * - 显示"📈 跟踪"或"✓ 已跟踪"
 * - 支持 size 属性（xs/sm/md），默认 sm
 */
export default function TrackButton({ stockCode, stockName, size = 'sm', className = '' }) {
  const [tracked, setTracked] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState('');

  const code = stripCode(stockCode);

  const sizeClass = size === 'xs'
    ? 'px-1.5 py-0 text-[10px] h-5'
    : size === 'md'
    ? 'px-2.5 py-1 text-xs h-7'
    : 'px-2 py-0.5 text-xs h-6';

  useEffect(() => {
    if (!code) return;
    (async () => {
      try {
        const list = await getTrackerList();
        if (Array.isArray(list)) {
          const found = list.find(s => String(s.stock_code) === code);
          if (found) setTracked(true);
        }
      } catch (e) { /* silent */ }
    })();
  }, [code]);

  const handleToggle = async (e) => {
    e.stopPropagation();
    e.preventDefault();
    if (loading) return;

    if (tracked) return;

    setLoading(true);
    setErr('');
    try {
      const { ok, error } = await apiFetch('/api/stock-tracker', {
        method: 'POST',
        body: JSON.stringify({ stock_code: code, stock_name: stockName || code }),
      });
      if (ok) {
        setTracked(true);
        // 更新缓存
        _trackerCache = null;
      } else {
        if (error && error.includes('已在跟踪列表')) setTracked(true);
        else setErr(error || '失败');
      }
    } catch (e) { setErr('网络错误'); }
    setLoading(false);
  };

  if (!code) return null;

  return (
    <span
      onClick={handleToggle}
      title={tracked ? '已在跟踪列表中' : (err || '加入股票跟踪')}
      className={`inline-flex items-center gap-0.5 ${sizeClass} rounded font-medium cursor-pointer transition-all select-none ${className}`}
      style={tracked
        ? { background: 'rgba(34,197,94,0.12)', color: '#22c55e', border: '1px solid rgba(34,197,94,0.3)' }
        : { background: 'rgba(234,179,8,0.1)', color: '#eab308', border: '1px solid rgba(234,179,8,0.3)' }
      }
    >
      {loading ? '...' : tracked ? '✓' : '📈'}
      {tracked ? ' 已跟踪' : ' 跟踪'}
    </span>
  );
}