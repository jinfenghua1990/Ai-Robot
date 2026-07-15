import { useState, useEffect } from 'react';
import { INDICATOR_META } from './StageBar';

const STORAGE_KEY = 'airobot_indicator_settings';

// 默认配置：watchlist 模式全开，trading 模式只开核心3个
export const DEFAULT_SETTINGS = {
  watchlist: {
    sentiment: true,
    momentum: true,
    mainForce: true,
    technical: true,
    sector: true,
    risk: true,
  },
  trading: {
    sentiment: true,
    momentum: false,
    mainForce: false,
    technical: false,
    sector: false,
    risk: false,
  },
  // 主力资金专项独立模式：只显示 mainForce
  standaloneMainForce: false,
};

export function loadSettings() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch (e) {
    // ignore
  }
  return DEFAULT_SETTINGS;
}

export function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch (e) {
    // ignore
  }
}

export default function IndicatorSettings({ open, onClose, settings, onChange }) {
  if (!open) return null;

  const toggle = (mode, key) => {
    const newSettings = {
      ...settings,
      [mode]: { ...settings[mode], [key]: !settings[mode][key] },
    };
    onChange(newSettings);
    saveSettings(newSettings);
  };

  const toggleStandalone = () => {
    const newSettings = {
      ...settings,
      standaloneMainForce: !settings.standaloneMainForce,
    };
    onChange(newSettings);
    saveSettings(newSettings);
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      style={{ background: 'rgba(0,0,0,0.5)' }}
      onClick={onClose}
    >
      <div
        className="rounded-lg border max-w-md w-full mx-4 p-4 max-h-[80vh] overflow-y-auto"
        style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-bold" style={{ color: 'var(--text-primary)' }}>
            指标模块组合
          </h3>
          <button
            onClick={onClose}
            className="text-xs px-2 py-1 rounded"
            style={{ background: 'var(--bg-hover)', color: 'var(--text-muted)' }}
          >
            ✕
          </button>
        </div>

        {/* 主力资金专项独立模式 */}
        <div
          className="rounded-md p-2 mb-3 border"
          style={{
            background: settings.standaloneMainForce ? 'rgba(239,68,68,0.05)' : 'var(--bg-hover)',
            borderColor: settings.standaloneMainForce ? 'rgba(239,68,68,0.3)' : 'transparent',
          }}
        >
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={settings.standaloneMainForce}
              onChange={toggleStandalone}
              className="cursor-pointer"
            />
            <div className="flex-1">
              <div className="text-xs font-bold" style={{ color: 'var(--text-primary)' }}>
                主力资金专项独立模式
              </div>
              <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                开启后卡片只显示主力资金专项指标，便于深度分析主力行为
              </div>
            </div>
          </label>
        </div>

        {/* watchlist 模式指标 */}
        <div className="mb-3">
          <div className="text-[10px] font-bold mb-2" style={{ color: 'var(--text-muted)' }}>
            自选股模式指标
          </div>
          <div className="space-y-1.5">
            {Object.entries(INDICATOR_META).map(([key, meta]) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.watchlist[key]}
                  onChange={() => toggle('watchlist', key)}
                  className="cursor-pointer"
                />
                <div className="flex-1">
                  <div className="text-xs" style={{ color: 'var(--text-primary)' }}>
                    {meta.label}
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    {meta.desc}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>

        {/* trading 模式指标 */}
        <div>
          <div className="text-[10px] font-bold mb-2" style={{ color: 'var(--text-muted)' }}>
            交易/龙头模式指标
          </div>
          <div className="space-y-1.5">
            {Object.entries(INDICATOR_META).map(([key, meta]) => (
              <label key={key} className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={settings.trading[key]}
                  onChange={() => toggle('trading', key)}
                  className="cursor-pointer"
                />
                <div className="flex-1">
                  <div className="text-xs" style={{ color: 'var(--text-primary)' }}>
                    {meta.label}
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    {meta.desc}
                  </div>
                </div>
              </label>
            ))}
          </div>
        </div>

        <div className="mt-3 pt-3 border-t flex gap-2" style={{ borderColor: 'var(--border-color)' }}>
          <button
            onClick={() => {
              const newSettings = {
                ...DEFAULT_SETTINGS,
                watchlist: Object.fromEntries(Object.keys(INDICATOR_META).map(k => [k, true])),
                trading: { ...DEFAULT_SETTINGS.trading },
              };
              onChange(newSettings);
              saveSettings(newSettings);
            }}
            className="flex-1 text-xs py-1.5 rounded"
            style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
          >
            watchlist 全开
          </button>
          <button
            onClick={() => {
              const newSettings = {
                ...DEFAULT_SETTINGS,
                watchlist: { sentiment: true, momentum: false, mainForce: true, technical: false, sector: false, risk: false },
                trading: { sentiment: true, momentum: false, mainForce: false, technical: false, sector: false, risk: false },
                standaloneMainForce: false,
              };
              onChange(newSettings);
              saveSettings(newSettings);
            }}
            className="flex-1 text-xs py-1.5 rounded"
            style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
          >
            精简模式
          </button>
          <button
            onClick={() => {
              onChange(DEFAULT_SETTINGS);
              saveSettings(DEFAULT_SETTINGS);
            }}
            className="flex-1 text-xs py-1.5 rounded"
            style={{ background: 'var(--bg-hover)', color: 'var(--text-primary)' }}
          >
            重置默认
          </button>
        </div>
      </div>
    </div>
  );
}
