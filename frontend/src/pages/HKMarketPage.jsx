/**
 * 港股中心（合并：行情 + 策略）
 * 路由: /hk-market
 *  - 行情：港股智能行情（指数 + 选股看板 + 技术信号 + 一键跟踪）
 *  - 策略：港股策略扫描（规则勾选 + 命中股票）
 * 原 /hk-strategy 已并入本页"策略"标签页。
 */
import { useState } from 'react';
import GlobalMarketPage from './GlobalMarketPage';
import HKStrategyPage from './HKStrategyPage';

const TABS = [
  { key: 'market', label: '🇭🇰 港股行情', icon: '📈' },
  { key: 'strategy', label: '🎯 策略扫描', icon: '🎯' },
];

export default function HKMarketPage() {
  const [tab, setTab] = useState('market');

  return (
    <div style={{ minHeight: '100%' }}>
      {/* 顶部 Tab 切换栏 */}
      <div
        className="flex items-center gap-1 px-4 pt-3 border-b sticky top-0 z-30"
        style={{ background: 'var(--bg-primary)', borderColor: 'var(--border-color)' }}
      >
        {TABS.map(t => {
          const active = tab === t.key;
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className="px-3 py-1.5 text-xs font-medium transition-colors"
              style={{
                borderBottom: active ? '2px solid var(--accent-blue)' : '2px solid transparent',
                color: active ? 'var(--accent-blue)' : 'var(--text-muted)',
                background: 'transparent',
                cursor: 'pointer',
              }}
            >
              {t.label}
            </button>
          );
        })}
      </div>

      {/* 内容区 */}
      <div>
        {tab === 'market' ? <GlobalMarketPage market="HK" /> : <HKStrategyPage />}
      </div>
    </div>
  );
}
