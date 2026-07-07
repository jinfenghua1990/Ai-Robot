import { getStockUrl } from '../utils/stockLink';

/**
 * 新浪财经个股跳转按钮
 * 小型图标按钮，避免整行点击误触
 */
export default function SinaLink({ tsCode, size = 'sm' }) {
  const url = getStockUrl(tsCode);
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
        background: 'rgba(255, 77, 0, 0.1)',
        color: '#ff4d00',
        border: '1px solid rgba(255, 77, 0, 0.3)',
      }}
      title="跳转新浪财经查看个股详情"
    >
      📡
    </a>
  );
}
