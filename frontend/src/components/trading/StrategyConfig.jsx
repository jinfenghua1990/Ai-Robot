import { useState, useEffect } from 'react';

const PARAM_META = {
  stop_loss_pct: { label: '止损线', unit: '%', desc: '亏损超过此值触发清仓信号', min: -20, max: 0, step: 0.5 },
  take_profit_pct: { label: '止盈线', unit: '%', desc: '盈利超过此值触发减仓信号', min: 5, max: 50, step: 0.5 },
  add_position_pct: { label: '加仓盈利门槛', unit: '%', desc: '盈利超过此值且板块向上时考虑加仓', min: 0, max: 20, step: 0.5 },
  sector_heat_threshold: { label: '板块热度预警', desc: '板块热度低于此值发出风险预警', min: 10, max: 80, step: 5 },
  sector_trend_days: { label: '趋势观察天数', unit: '天', desc: '板块趋势计算的回看天数', min: 2, max: 10, step: 1 },
  max_position_pct: { label: '单股仓位上限', unit: '%', desc: '单只股票最大仓位比例', min: 5, max: 50, step: 1 },
  sector_decline_days: { label: '板块连跌预警', unit: '天', desc: '板块连续下跌天数触发减仓', min: 1, max: 7, step: 1 },
};

/**
 * 策略参数配置面板
 */
export default function StrategyConfig({ config, onUpdate }) {
  const [local, setLocal] = useState(config);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => { setLocal(config); }, [config]);

  const handleChange = (key, value) => {
    setLocal(prev => ({ ...prev, [key]: value }));
    setSaved(false);
  };

  const handleSave = async () => {
    setSaving(true);
    await onUpdate(local);
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = () => {
    setLocal(config);
    setSaved(false);
  };

  return (
    <div className="rounded-xl border p-3 space-y-2" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>策略参数配置</h3>
        <div className="flex items-center gap-2">
          <button
            onClick={handleReset}
            className="px-3 py-1 rounded-lg text-xs border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)' }}
          >
            重置
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="px-3 py-1 rounded-lg text-xs text-white"
            style={{ background: saving ? '#999' : 'var(--accent-color, #3b82f6)' }}
          >
            {saving ? '保存中...' : saved ? '✅ 已保存' : '保存'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-2">
        {Object.entries(PARAM_META).map(([key, meta]) => (
          <div key={key} className="space-y-1">
            <div className="flex items-center justify-between">
              <label className="text-xs" style={{ color: 'var(--text-secondary)' }}>{meta.label}</label>
              <div className="flex items-center gap-1">
                <input
                  type="number"
                  value={local[key] ?? ''}
                  onChange={e => handleChange(key, parseFloat(e.target.value))}
                  min={meta.min}
                  max={meta.max}
                  step={meta.step}
                  className="w-16 px-2 py-1 rounded border text-xs text-right"
                  style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
                />
                {meta.unit && <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{meta.unit}</span>}
              </div>
            </div>
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{meta.desc}</div>
          </div>
        ))}
      </div>
    </div>
  );
}
