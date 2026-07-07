import { useState } from 'react';

const TABS = [
  { key: 'search', label: '资讯搜索', icon: '📰', desc: '金融新闻/公告/研报/政策' },
  { key: 'data', label: '金融数据', icon: '📊', desc: '行情/财务/关系经营数据' },
];

const EXAMPLES = {
  search: [
    '贵州茅台最新公告',
    '半导体板块政策利好',
    '美联储加息影响分析',
    '新能源汽车产业链研报',
    'A股市场交易规则',
  ],
  data: [
    '东方财富最新价',
    '贵州茅台近3年ROE',
    '宁德时代十大股东',
    '半导体板块成分股',
    '中芯国际主营业务',
  ],
};

export default function MxToolsPage() {
  const [tab, setTab] = useState('search');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const handleQuery = async (e) => {
    e?.preventDefault();
    const q = query.trim();
    if (!q) { setError('请输入查询内容'); return; }
    setLoading(true); setError(null); setResults(null);
    try {
      const endpoint = tab === 'search' ? '/api/mx/search' : '/api/mx/data';
      const resp = await fetch(endpoint, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: q }),
      });
      const d = await resp.json();
      if (d.detail) setError(d.detail);
      else if (d.error) setError(d.error);
      else setResults(d);
    } catch (err) {
      setError('请求失败: ' + err.message);
    }
    setLoading(false);
  };

  const switchTab = (newTab) => {
    setTab(newTab);
    setQuery('');
    setResults(null);
    setError(null);
  };

  return (
    <div className="space-y-4">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>
          妙想工具
          <span className="ml-2 px-1.5 py-0.5 rounded text-[10px] font-normal align-middle" style={{ background: 'rgba(234,179,8,0.1)', color: '#eab308' }}>
            东方财富 · 付费API
          </span>
        </h2>
      </div>

      {/* Tab 切换 */}
      <div className="flex gap-2">
        {TABS.map(t => (
          <button
            key={t.key}
            onClick={() => switchTab(t.key)}
            className="rounded-lg border px-4 py-2 text-left transition-all flex-1"
            style={{
              borderColor: tab === t.key ? 'rgba(234,179,8,0.5)' : 'var(--border-color)',
              background: tab === t.key ? 'rgba(234,179,8,0.08)' : 'var(--bg-card)',
            }}
          >
            <div className="font-medium text-sm" style={{ color: tab === t.key ? '#eab308' : 'var(--text-primary)' }}>
              {t.icon} {t.label}
            </div>
            <div className="text-xs mt-0.5" style={{ color: 'var(--text-muted)' }}>{t.desc}</div>
          </button>
        ))}
      </div>

      {/* 查询输入 */}
      <div className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
        <form onSubmit={handleQuery} className="flex gap-2 mb-2">
          <input
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={tab === 'search' ? '输入搜索词，如「贵州茅台最新公告」「半导体政策利好」' : '输入查询，如「东方财富最新价」「贵州茅台近3年ROE」'}
            className="flex-1 px-3 py-1.5 rounded-lg border text-sm outline-none"
            style={{ borderColor: 'var(--border-color)', background: 'var(--bg-surface)', color: 'var(--text-primary)' }}
          />
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-1.5 rounded-lg text-sm font-medium whitespace-nowrap"
            style={{ background: loading ? 'rgba(234,179,8,0.4)' : '#eab308', color: '#fff', opacity: loading ? 0.7 : 1 }}
          >
            {loading ? '查询中...' : '🔍 查询'}
          </button>
        </form>
        <div className="flex flex-wrap gap-1">
          {(EXAMPLES[tab] || []).map(ex => (
            <button key={ex} onClick={() => setQuery(ex)}
              className="px-2 py-0.5 rounded text-[11px] border transition-all"
              style={{ borderColor: 'rgba(234,179,8,0.3)', color: 'var(--text-secondary)', background: 'rgba(234,179,8,0.05)' }}>
              {ex}
            </button>
          ))}
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="rounded-lg p-3 text-sm" style={{ background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.3)', color: '#ef4444' }}>
          ⚠ {error}
        </div>
      )}

      {/* 加载中 */}
      {loading && (
        <div className="rounded-xl border p-8 text-center" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-sm" style={{ color: 'var(--text-muted)' }}>⏳ 妙想API调用中，请稍候...</div>
        </div>
      )}

      {/* 资讯搜索结果 */}
      {tab === 'search' && results && !loading && (
        <div className="rounded-xl border p-4" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
          <div className="text-xs mb-3" style={{ color: 'var(--text-muted)' }}>
            搜索: <strong style={{ color: 'var(--text-primary)' }}>{results.query}</strong>
          </div>
          {results.content ? (
            <div className="text-sm whitespace-pre-wrap leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
              {results.content}
            </div>
          ) : (
            <div className="text-sm" style={{ color: 'var(--text-muted)' }}>未找到相关资讯</div>
          )}
        </div>
      )}

      {/* 金融数据结果 */}
      {tab === 'data' && results && !loading && (
        <div className="space-y-3">
          {results.condition && (
            <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
              查询条件: <strong style={{ color: 'var(--text-primary)' }}>{results.condition}</strong>
              {' · '}共 <strong style={{ color: '#ef4444' }}>{results.total_rows}</strong> 行
            </div>
          )}
          {results.tables && results.tables.length > 0 ? (
            results.tables.map((table, ti) => (
              <div key={ti} className="rounded-xl border p-3" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                {table.sheet_name && (
                  <h3 className="text-sm font-medium mb-2" style={{ color: 'var(--text-secondary)' }}>{table.sheet_name}</h3>
                )}
                <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="sticky top-0 z-10">
                      <tr className="border-b" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)' }}>
                        {(table.fieldnames || []).map(col => (
                          <th key={col} className="text-left py-2 px-3 font-medium whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{col}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {(table.rows || []).map((row, ri) => (
                        <tr key={ri} className="border-b" style={{ borderColor: 'var(--border-light)' }}>
                          {(table.fieldnames || []).map(col => (
                            <td key={col} className="py-2 px-3 whitespace-nowrap" style={{ color: 'var(--text-secondary)' }}>{row[col] ?? '-'}</td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            ))
          ) : (
            <div className="rounded-xl border p-6 text-center text-sm" style={{ borderColor: 'var(--border-color)', background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
              {results.error || '未找到相关数据'}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
