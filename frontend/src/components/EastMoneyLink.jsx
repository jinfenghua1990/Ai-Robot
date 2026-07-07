import { getEastMoneyUrl } from '../utils/stockLink';

/**
 * 东方财富个股跳转按钮
 * 小型图标按钮，避免整行点击误触
 */
export default function EastMoneyLink({ tsCode, size = 'sm' }) {
  const url = getEastMoneyUrl(tsCode);
  if (!url) return null;

  const sizeClass = size === 'sm' ? 'px-1.5 py-0.5 text-xs' : 'px-2 py-1 text-sm';

  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      onClick={e => e.stopPropagation()}
      className={`${sizeClass} rounded font-medium inline-flex items-center gap-0.5 no-underline`}
      style={{
        background: 'rgba(59, 130, 246, 0.1)',
        color: '#3b82f6',
        border: '1px solid rgba(59, 130, 246, 0.3)',
      }}
      title="跳转东方财富查看实时行情"
    >
      📈
    </a>
  );
}
