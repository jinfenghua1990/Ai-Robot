export const STOCK_TABLE_SURFACE = 'var(--bg-secondary)';

/** Shared presentation frame for the portfolio and watchlist tables. */
export default function StockTableFrame({ children, minWidth, tableLayout = 'auto', footer = null }) {
  return (
    <div className="rounded-xl border overflow-hidden" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="overflow-x-auto no-scrollbar">
        <table className="w-full text-[11px]" style={{ borderCollapse: 'collapse', minWidth, tableLayout }}>
          {children}
        </table>
      </div>
      {footer}
    </div>
  );
}
