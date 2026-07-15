import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { apiFetch } from '../utils/request';

const WEATHER_ORDER = ['storm', 'cloudy_to_sunny', 'typhoon', 'sunny', 'cloudy'];

export default function FundWeatherPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    let active = true;
    setLoading(true);
    (async () => {
      try {
        const { ok, data: d } = await apiFetch('/api/fund-weather');
        if (!active) return;
        if (!ok) {
          setError('获取气象雷达失败');
          setData(null);
        } else {
          setData(d);
          setError('');
        }
      } catch (e) {
        if (!active) return;
        setError(e.message || '网络错误');
      } finally {
        if (active) setLoading(false);
      }
    })();
    return () => { active = false; };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>加载气象雷达...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-4 rounded-lg" style={{ background: 'var(--bg-card)', color: 'var(--text-primary)' }}>
        <div className="text-red-500">{error}</div>
      </div>
    );
  }

  const groups = data?.weather_groups || [];
  const ordered = WEATHER_ORDER.map(key => groups.find(g => g.weather === key)).filter(Boolean);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold" style={{ color: 'var(--text-primary)' }}>🌦️ 资金气象雷达</h1>
        <div className="text-xs" style={{ color: 'var(--text-muted)' }}>生成于 {data?.generated_at || '-'}</div>
      </div>

      <div className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
        将自选股按机构/游资双轨资金博弈翻译成天气形态。技术破位 + 游资砸盘 = 雷暴；机构逆市吸筹 = 阴转晴；游资狂拉 + 机构出货 = 台风；双轨共振 = 艳阳。
      </div>

      {ordered.length === 0 ? (
        <div className="p-8 text-center rounded-lg" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
          暂无数据，请先添加自选股
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
          {ordered.map(group => (
            <div
              key={group.weather}
              className="rounded-lg border overflow-hidden"
              style={{ background: 'var(--bg-card)', borderColor: group.border }}
            >
              <div
                className="px-4 py-3 flex items-center justify-between"
                style={{ background: group.bg, borderBottom: `1px solid ${group.border}` }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-xl">{group.emoji}</span>
                  <div>
                    <div className="font-bold" style={{ color: group.color }}>{group.label}</div>
                    <div className="text-xs" style={{ color: 'var(--text-secondary)' }}>{group.action}</div>
                  </div>
                </div>
                <div
                  className="text-2xl font-bold"
                  style={{ color: group.color }}
                >
                  {group.count}
                </div>
              </div>

              <div className="divide-y" style={{ borderColor: 'var(--border-color)' }}>
                {group.stocks.length === 0 ? (
                  <div className="px-4 py-6 text-center text-sm" style={{ color: 'var(--text-muted)' }}>
                    暂无股票
                  </div>
                ) : (
                  group.stocks.map(stock => (
                    <div
                      key={stock.code}
                      className="px-4 py-3 cursor-pointer hover:opacity-80 transition-opacity"
                      style={{ color: 'var(--text-primary)' }}
                      onClick={() => navigate(`/stock/${stock.code}`)}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold">{stock.name || stock.code}</span>
                          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>{stock.code}</span>
                          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'var(--bg-hover)', color: 'var(--text-secondary)' }}>
                            {stock.sector || '—'}
                          </span>
                        </div>
                        <div className="text-sm font-mono" style={{ color: stock.change_pct >= 0 ? 'var(--flow-up)' : 'var(--flow-down)' }}>
                          {stock.change_pct >= 0 ? '+' : ''}{stock.change_pct}%
                        </div>
                      </div>

                      <div className="grid grid-cols-2 gap-2 text-xs mt-2">
                        <div className="flex items-center gap-1">
                          <span style={{ color: 'var(--text-muted)' }}>🏛️ 正规军:</span>
                          <span style={{ color: stock.inst_net_5d > 0 ? 'var(--flow-up)' : stock.inst_net_5d < 0 ? 'var(--flow-down)' : 'var(--text-primary)' }}>
                            {stock.inst_net_5d > 0 ? '+' : ''}{stock.inst_net_5d_fmt}
                          </span>
                        </div>
                        <div className="flex items-center gap-1">
                          <span style={{ color: 'var(--text-muted)' }}>⚔️ 敢死队:</span>
                          <span style={{ color: stock.yuzi_net_5d > 0 ? 'var(--flow-up)' : stock.yuzi_net_5d < 0 ? 'var(--flow-down)' : 'var(--text-primary)' }}>
                            {stock.yuzi_net_5d > 0 ? '+' : ''}{stock.yuzi_net_5d_fmt}
                          </span>
                        </div>
                      </div>

                      <div className="flex items-center justify-between mt-2 text-xs">
                        <span style={{ color: 'var(--text-muted)' }}>技术形态: {stock.technical_stage || '—'}</span>
                        <span style={{ color: 'var(--text-muted)' }}>动作: {stock.action}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
