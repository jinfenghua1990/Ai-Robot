import { useDatePicker } from '../hooks/useDatePicker';

/**
 * 公共日期导航组件
 * 用法：<DateNavigator selectedDate={selectedDate} setSelectedDate={setSelectedDate} changeDate={changeDate} />
 * 或直接传 useDatePicker() 展开：<DateNavigator {...useDatePicker()} />
 */
export default function DateNavigator({ selectedDate, setSelectedDate, changeDate, extra }) {
  return (
    <div className="flex items-center gap-2">
      <button onClick={() => changeDate(-1)} className="px-2 py-1 rounded-md border text-xs whitespace-nowrap" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>← 前一天</button>
      <input
        type="date"
        value={selectedDate}
        onChange={(e) => setSelectedDate(e.target.value)}
        className="px-2 py-1 rounded-md border text-xs"
        style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-primary)' }}
      />
      <button onClick={() => changeDate(1)} className="px-2 py-1 rounded-md border text-xs whitespace-nowrap" style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}>后一天 →</button>
      {extra}
    </div>
  );
}