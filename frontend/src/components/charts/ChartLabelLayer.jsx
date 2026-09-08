import { useState, useEffect, useRef } from 'react';

/**
 * 图表右侧外部标签层 —— 替代 ECharts 内置 endLabel，彻底避免标签重叠
 *
 * 原理：用 echartsInstance.convertToPixel 把每条线的最终值转为 y 像素坐标，
 *       按坐标排序后强制最小间距（minGap），用绝对定位渲染，保证永不重叠。
 *
 * chartRef: ReactECharts 的 ref（通过 .getEchartsInstance() 取实例）
 * items: [{ key, label, value, valueText, color, isPositive, isSelected, dimmed, onClick }]
 */
export default function ChartLabelLayer({ chartRef, items, width = 160, minGap = 18 }) {
  const [positions, setPositions] = useState([]);
  const rafRef = useRef(0);

  useEffect(() => {
    const compute = () => {
      const instance = chartRef.current?.getEchartsInstance?.();
      if (!instance || !items || items.length === 0) {
        setPositions([]);
        return;
      }
      try {
        const calculated = items
          .map(item => {
            const y = instance.convertToPixel({ yAxisIndex: 0 }, item.value);
            return { ...item, y: Number.isFinite(y) ? y : null };
          })
          .filter(item => item.y !== null);

        // 按 y 坐标排序（y 小的在上方）
        calculated.sort((a, b) => a.y - b.y);

        // 强制最小间距：相邻标签若距离不足 minGap，向下推开
        for (let i = 1; i < calculated.length; i++) {
          if (calculated[i].y - calculated[i - 1].y < minGap) {
            calculated[i].y = calculated[i - 1].y + minGap;
          }
        }

        setPositions(calculated);
      } catch {
        // 图表未就绪，跳过本次计算
      }
    };

    // 双 RAF 确保图表完成渲染再读取坐标
    cancelAnimationFrame(rafRef.current);
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = requestAnimationFrame(compute);
    });

    const onResize = () => {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = requestAnimationFrame(compute);
    };
    window.addEventListener('resize', onResize);

    return () => {
      cancelAnimationFrame(rafRef.current);
      window.removeEventListener('resize', onResize);
    };
  }, [items, chartRef, minGap]);

  if (positions.length === 0) return null;

  return (
    <div className="absolute top-0 right-0 pointer-events-none" style={{ width: `${width}px`, height: '100%' }}>
      {positions.map(p => (
        <div
          key={p.key}
          className="absolute flex items-center gap-1 whitespace-nowrap"
          style={{
            top: `${p.y}px`,
            right: '4px',
            transform: 'translateY(-50%)',
            opacity: p.dimmed ? 0.3 : 1,
            pointerEvents: p.onClick ? 'auto' : 'none',
            cursor: p.onClick ? 'pointer' : 'default',
          }}
          onClick={p.onClick}
        >
          <span style={{ color: p.color, fontSize: 11, fontWeight: p.isSelected ? 700 : 600 }}>
            {p.label}
          </span>
          <span style={{ color: p.isPositive ? '#ef4444' : '#22c55e', fontSize: 11, fontWeight: 600 }}>
            {p.valueText}
          </span>
        </div>
      ))}
    </div>
  );
}
