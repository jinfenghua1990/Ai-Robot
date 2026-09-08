import { useState, useMemo, useCallback } from 'react';

/**
 * 策略选股结果紧凑表格（替代满屏 SignalCard 卡片）
 *
 * Props:
 * - columns: [{ key, label, render(row), sortable?, align?, type?('percent'|'money'|'number') }]
 * - rows: 原始数据数组
 * - getRowKey: (row) => 唯一标识
 * - cardComponent: 可选卡片组件（用于卡片视图）
 * - cardProps: 卡片组件 props
 * - pageSize: 每页条数（默认 20）
 * - searchPlaceholder: 搜索框占位文字
 * - extraToolbar: 额外工具栏内容
 * - emptyText: 无数据提示文字
 * - defaultView: 'table' | 'card'（默认 'table'）
 */


/** 格式化单元格值 */
function fmt(val, type) {
  if (val == null || val === '') return '-';
  if (type === 'percent') {
    const n = Number(val);
    if (isNaN(n)) return val;
    const sign = n > 0 ? '+' : '';
    return `${sign}${n.toFixed(2)}%`;
  }
  if (type === 'money') {
    const n = Number(val);
    if (isNaN(n)) return val;
    const abs = Math.abs(n);
    if (abs >= 1e8) return `${(n / 1e8).toFixed(2)}亿`;
    if (abs >= 1e4) return `${(n / 1e4).toFixed(2)}万`;
    return n.toFixed(0);
  }
  if (type === 'number') {
    const n = Number(val);
    if (isNaN(n)) return val;
    return n.toFixed(2);
  }
  return val;
}

/** 获取排序用的数值 */
function sortVal(val, type) {
  if (val == null || val === '') return -Infinity;
  if (type === 'percent' || type === 'money' || type === 'number') {
    const n = Number(val);
    return isNaN(n) ? -Infinity : n;
  }
  return String(val).toLowerCase();
}

export default function StrategyResultsTable({
  columns = [],
  rows = [],
  getRowKey,
  cardComponent: CardComp,
  cardProps = {},
  pageSize = 20,
  searchPlaceholder = '搜索代码 / 名称 / 板块...',
  extraToolbar,
  emptyText = '暂无选股结果',
  defaultView = 'table',
}) {
  const [view, setView] = useState(defaultView);
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState(null);
  const [sortAsc, setSortAsc] = useState(true);
  const [currentPage, setCurrentPage] = useState(0);

  const handleSort = useCallback((key) => {
    if (sortKey === key) {
      setSortAsc(v => !v);
    } else {
      setSortKey(key);
      setSortAsc(true);
    }
    setCurrentPage(0);
  }, [sortKey]);

  // 列信息查找
  const colMap = useMemo(() => {
    const m = {};
    columns.forEach(c => { m[c.key] = c; });
    return m;
  }, [columns]);

  // 搜索 + 排序
  const processed = useMemo(() => {
    let result = [...rows];

    // 搜索（在所有列内容中查找）
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      result = result.filter(row =>
        columns.some(col => {
          const rendered = col.render ? col.render(row) : row[col.key];
          return String(rendered || '').toLowerCase().includes(q);
        })
      );
    }

    // 排序
    if (sortKey) {
      const col = colMap[sortKey];
      result.sort((a, b) => {
        const va = sortVal(col?.render ? col.render(a) : a[sortKey], col?.type);
        const vb = sortVal(col?.render ? col.render(b) : b[sortKey], col?.type);
        if (va < vb) return sortAsc ? -1 : 1;
        if (va > vb) return sortAsc ? 1 : -1;
        return 0;
      });
    }

    return result;
  }, [rows, search, sortKey, sortAsc, columns, colMap]);

  const totalPages = Math.max(1, Math.ceil(processed.length / pageSize));
  // 确保当前页不越界
  const safePage = Math.min(currentPage, totalPages - 1);
  const paged = processed.slice(safePage * pageSize, (safePage + 1) * pageSize);

  // 排序箭头
  const sortArrow = (key) => {
    if (sortKey !== key) return <span style={{ opacity: 0.2 }}> ↕</span>;
    return sortAsc ? <span> ↑</span> : <span> ↓</span>;
  };

  // 确定涨跌颜色
  const changeColor = (val) => {
    const n = Number(val);
    if (isNaN(n)) return 'var(--text-secondary)';
    if (n > 0) return '#ef4444'; // A股红色涨
    if (n < 0) return '#22c55e'; // 绿色跌
    return 'var(--text-secondary)';
  };

  const cellColor = (col, val) => {
    if (col?.type === 'percent') return changeColor(val);
    return 'var(--text-primary)';
  };

  const Toolbar = (
    <div className="flex items-center gap-2 mb-2 flex-wrap">
      <input
        type="text"
        value={search}
        onChange={(e) => { setSearch(e.target.value); setCurrentPage(0); }}
        placeholder={searchPlaceholder}
        className="px-3 py-1.5 rounded-lg border text-sm flex-1 min-w-[180px] outline-none"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
      />
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{processed.length} 只</span>
      {extraToolbar}
      {/* 视图切换 */}
      <div className="flex rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
        <button
          onClick={() => setView('table')}
          className="px-2.5 py-1 text-xs font-medium transition-colors"
          style={{
            background: view === 'table' ? 'var(--accent-blue)' : 'transparent',
            color: view === 'table' ? '#fff' : 'var(--text-secondary)',
          }}
        >📋 表格</button>
        <button
          onClick={() => setView('card')}
          className="px-2.5 py-1 text-xs font-medium transition-colors"
          style={{
            background: view === 'card' ? 'var(--accent-blue)' : 'transparent',
            color: view === 'card' ? '#fff' : 'var(--text-secondary)',
          }}
        >🃏 卡片</button>
      </div>
    </div>
  );

  // 分页组件
  const Pagination = totalPages > 1 && (
    <div className="flex items-center justify-center gap-2 mt-3 pt-2 border-t" style={{ borderColor: 'var(--border-color)' }}>
      <button
        onClick={() => setCurrentPage(p => Math.max(0, p - 1))}
        disabled={safePage === 0}
        className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
      >上一页</button>
      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{safePage + 1} / {totalPages} 页</span>
      <button
        onClick={() => setCurrentPage(p => Math.min(totalPages - 1, p + 1))}
        disabled={safePage >= totalPages - 1}
        className="px-3 py-1 rounded-lg text-xs border disabled:opacity-30"
        style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
      >下一页</button>
    </div>
  );

  if (processed.length === 0) {
    return (
      <div>
        {Toolbar}
        <div className="flex items-center justify-center h-32 text-sm" style={{ color: 'var(--text-muted)' }}>{emptyText}</div>
      </div>
    );
  }

  // 卡片视图
  if (view === 'card' && CardComp) {
    return (
      <div>
        {Toolbar}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3 max-h-[700px] overflow-y-auto">
          {paged.map(row => (
            <CardComp key={getRowKey(row)} signal={row} {...cardProps} />
          ))}
        </div>
        {Pagination}
      </div>
    );
  }

  // 表格视图
  return (
    <div>
      {Toolbar}

      {/* 表头 */}
      <div className="rounded-lg border overflow-hidden" style={{ borderColor: 'var(--border-color)' }}>
        <div className="overflow-x-auto">
          <div
            className="grid gap-2 px-2.5 py-2 text-[11px] font-semibold border-b"
            style={{
              borderColor: 'var(--border-color)',
              background: 'var(--bg-hover)',
              color: 'var(--text-secondary)',
              gridTemplateColumns: columns.map(c => c.width || '1fr').join(' '),
            }}
          >
            {columns.map(col => (
              <div
                key={col.key}
                className={`flex items-center cursor-pointer select-none ${col.align === 'right' ? 'justify-end' : ''}`}
                style={{ whiteSpace: 'nowrap' }}
                onClick={() => col.sortable !== false && handleSort(col.key)}
                title={col.sortable !== false ? '点击排序' : ''}
              >
                {col.label}
                {col.sortable !== false && <span className="text-[9px] ml-0.5">{sortArrow(col.key)}</span>}
              </div>
            ))}
          </div>

          {/* 数据行 */}
          <div className="max-h-[600px] overflow-y-auto">
            {paged.map((row, i) => (
              <div
                key={getRowKey(row, i)}
                className="grid gap-2 px-2.5 py-1.5 text-xs border-b transition-colors"
                style={{
                  borderColor: 'var(--border-color)',
                  background: i % 2 === 0 ? 'var(--bg-card)' : 'var(--bg-surface)',
                  gridTemplateColumns: columns.map(c => c.width || '1fr').join(' '),
                }}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--bg-hover)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = i % 2 === 0 ? 'var(--bg-card)' : 'var(--bg-surface)';
                }}
              >
                {columns.map(col => {
                  const val = col.render ? col.render(row) : row[col.key];
                  const align = col.align || (col.type ? 'right' : 'left');
                  return (
                    <div
                      key={col.key}
                      className="truncate"
                      style={{
                        textAlign: align,
                        color: cellColor(col, val),
                        fontWeight: col.type === 'percent' ? 600 : 400,
                      }}
                      title={val != null ? String(val) : ''}
                    >
                      {fmt(val, col.type)}
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        </div>
      </div>

      {Pagination}
    </div>
  );
}
