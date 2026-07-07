import { useState, useRef, useEffect } from 'react';
import { qualityOrder, qualityColors } from '../StageBar';
import { apiFetch } from '../../utils/request';

/**
 * 个股强度选择器（自选股卡片 2×2 按钮组里的一个格子）
 * - 显示当前 quality_status 徽章（劣质/中性/偏强/强势/极强/核心/淘汰）
 * - 点击弹出下拉菜单，可选择7个值之一
 * - 调用 PUT /api/watchlist/{code}/quality 更新后端
 *
 * props:
 *   stockCode  - 股票代码
 *   value      - 当前 quality_status（如 '核心'）
 *   onChange    - 可选，更新成功后回调
 */
export default function QualityPicker({ stockCode, value = '中性', onChange }) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const ref = useRef(null);
  const currentValue = value || '中性';

  // 外部点击关闭
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [open]);

  const handleSelect = async (q) => {
    if (q === currentValue || loading) {
      setOpen(false);
      return;
    }
    setLoading(true);
    try {
      const { ok, data } = await apiFetch(`/api/watchlist/${stockCode}/quality`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quality_status: q }),
      });
      if (ok && data?.success) {
        onChange?.(q);
      }
    } catch (e) {
      /* silent */
    } finally {
      setLoading(false);
      setOpen(false);
    }
  };

  const color = qualityColors[currentValue] || '#64748B';

  return (
    <div ref={ref} className="relative">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
        className="px-1.5 py-0.5 rounded text-[10px] font-bold text-center whitespace-nowrap h-7 inline-flex items-center justify-center w-full cursor-pointer"
        style={{ background: `${color}22`, color, border: `1px solid ${color}55` }}
        title="点击修改个股强度"
      >
        {currentValue}
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute top-full left-0 mt-1 z-50 rounded-md shadow-lg border overflow-hidden min-w-[80px]"
          style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          {qualityOrder.map((q) => {
            const c = qualityColors[q];
            const active = q === currentValue;
            return (
              <button
                key={q}
                disabled={loading}
                onClick={() => handleSelect(q)}
                className="block w-full text-left px-2 py-1 text-[11px] font-medium disabled:opacity-50 transition-colors"
                style={{
                  background: active ? `${c}22` : 'transparent',
                  color: active ? c : 'var(--text-primary)',
                }}
                onMouseEnter={(e) => { if (!active) e.currentTarget.style.background = `${c}11`; }}
                onMouseLeave={(e) => { if (!active) e.currentTarget.style.background = 'transparent'; }}
              >
                {q}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
