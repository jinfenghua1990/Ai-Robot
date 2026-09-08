/**
 * 个股行情跳转按钮（A股 / 港股 / 美股通用）
 * - A股（tsCode）: finance.sina.com.cn/realstock/company/{sh|sz}{code}/nc.shtml
 * - 港股（market="HK" + code）: stock.finance.sina.com.cn/hkstock/quotes/{5位数字}.html
 * - 美股（market="US" + code）: TradingView 技术指标页 + 新浪财经美股行情页（两个链接）
 *
 * 用法（兼容两种接口）:
 *   <SinaLink tsCode="600000.SH" />          // A股（旧用法，自动识别交易所）
 *   <SinaLink market="US" code="AAPL" />     // 美股 → TradingView + 新浪财经
 *   <SinaLink market="HK" code="00700" />    // 港股
 */
import { sinaUrl } from '../utils/sinaUrl';

export default function SinaLink({ tsCode, market, code, size = 'sm' }) {
  const url = code != null ? sinaUrl(market, code) : sinaUrl(tsCode);
  if (!url) return null;

  const sizeClass = size === 'xs' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-1 text-sm';
  const isUs = code != null && market === 'US';
  const urls = isUs ? url : [url];
  if (isUs && urls.length === 0) return null;

  return (
    <span className="inline-flex items-center gap-1" onClick={e => e.stopPropagation()}>
      {urls.map((u, i) => (
        <a
          key={i}
          href={u}
          target="_blank"
          rel="noopener noreferrer"
          onClick={e => e.stopPropagation()}
          className={`${sizeClass} rounded font-medium inline-flex items-center gap-0.5 no-underline`}
          style={{
            background: 'rgba(41, 98, 255, 0.12)',
            color: '#4d7cff',
            border: '1px solid rgba(41, 98, 255, 0.35)',
          }}
          title={isUs && i === 1 ? '跳转新浪财经查看美股行情' : '跳转 TradingView 查看技术指标'}
        >
          {isUs && i === 1 ? '新' : '📈'}
        </a>
      ))}
    </span>
  );
}
