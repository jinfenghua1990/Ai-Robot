import { useEffect, useState, useMemo } from 'react';
import MoneyFlowChart from '../components/charts/MoneyFlowChart';
import { apiFetch } from '../utils/request';
import { POLL_INTERVAL } from '../utils/constants';

// 泛分类概念——不是市场热点主题，过滤掉
const GENERIC_CONCEPTS = new Set([
  '融资融券', '股权激励', '含B股', '含H股', '含GDR', '基金重仓', '保险重仓',
  'QFII重仓', '社保重仓', '信托重仓', '券商重仓', '业绩预升', '业绩预降',
  '送转潜力', '分拆上市', '整体上市', '资产注入', '重组概念', '摘帽概念',
  '准ST股', 'ST板块', '科创50', '超大盘', '央企50', '外资背景', '金融参股',
  '参股金融', '高校背景', '本月解禁', '出口退税', '股期概念', '未股改',
  '三板精选', '涉矿概念', '博彩概念', '赛马概念', '猪肉', '鸡肉',
  '乡村振兴', '土地流转', '生态农业', '水产品', '食品安全',
  '京津冀', '上海本地', '深圳本地', '前海概念', '天津自贸', '海南自贸',
  '上海自贸', '福建自贸', '武汉规划', '图们江', '黄河三角', '长株潭',
  '皖江区域', '陕甘宁', '成渝特区', '海峡西岸', '沿海发展', '三沙概念',
  '雄安新区', '东亚自贸', '日韩贸易', '海上丝路', '朝鲜改革',
  '民营医院', '民营银行', '内贸规划', '文化振兴', '体育概念',
  '迪士尼', '网络游戏', '电商概念', '互联金融', '电子支付',
  '奢侈品', '婴童概念', '代糖概念', '维生素', '草甘膦',
  '超级细菌', '甲型流感', '减肥药', '免疫治疗', '抗癌',
  '基因概念', '基因测序', '生物疫苗', '生物育种', '仿制药',
  '水务改革', '水域改革', '污水处理', '固废处理', '空气治理',
  '垃圾分类', '绿色照明', '低碳经济', '循环经济', '节能环保',
  '核污防治', '地热能', '可燃冰', '页岩气', '油气改革',
  '恒大概念', '百度概念', '小米概念', '特斯拉', '苹果概念',
  '华为概念', '华为汽车', '华为海思', '华为鸿蒙', '鸿蒙概念',
  '金融改革', '自贸区', '航运概念', '水利建设', '建筑节能',
  '信息安全', '宽带提速', '触摸屏', '消费电子', '汽车电子',
  '无线耳机', '智能穿戴', '智能家居', '智能电网', '智能机器',
  '3D打印', '超导概念', '石墨烯', '聚氨酯', '碳纤维',
  '风电', '风能', '风能概念', '碳中和', '碳交易',
  '国产软件', '国企改革', '大飞机', '卫星导航', '海工装备',
  '物联网', '充电桩', '高压快充',
]);

export default function ConceptFlowComparePage() {
  const [rankData, setRankData] = useState(null);
  const [flowData, setFlowData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [topN, setTopN] = useState(15);
  const [bottomN, setBottomN] = useState(10);
  const [showAll, setShowAll] = useState(false);

  const fetchData = async () => {
    setLoading(true);
    setError(null);

    const [rankRes, flowRes] = await Promise.all([
      apiFetch('/api/concept-sector-flow-rank'),
      apiFetch(`/api/realtime/v1/money-flow?dimension=concept&top_n=${topN}&bottom_n=${bottomN}`),
    ]);

    if (rankRes.ok && rankRes.data) setRankData(rankRes.data);
    if (flowRes.ok && flowRes.data) setFlowData(flowRes.data);

    if (!rankRes.ok && !flowRes.ok) setError('获取数据失败');
    setLoading(false);
  };

  useEffect(() => {
    fetchData();
    const timer = setInterval(fetchData, POLL_INTERVAL);
    return () => clearInterval(timer);
  }, [topN, bottomN]);

  // 分时数据拆分：净流入 vs 净流出
  const { inflowSeries, outflowSeries } = useMemo(() => {
    if (!flowData?.series?.length) return { inflowSeries: [], outflowSeries: [] };
    const inS = [];
    const outS = [];
    flowData.series.forEach(s => {
      const lastVal = s.data[s.data.length - 1] || 0;
      if (lastVal >= 0) inS.push(s);
      else outS.push(s);
    });
    // 净流入按最终值降序，净流出按最终值升序（流出最多的在上）
    inS.sort((a, b) => (b.data[b.data.length - 1] || 0) - (a.data[a.data.length - 1] || 0));
    outS.sort((a, b) => (a.data[a.data.length - 1] || 0) - (b.data[b.data.length - 1] || 0));
    return { inflowSeries: inS, outflowSeries: outS };
  }, [flowData]);

  // 获取分时图中的概念名称集合
  const flowConceptSet = useMemo(() => {
    if (!flowData?.series) return new Set();
    return new Set(flowData.series.map(s => s.name));
  }, [flowData]);

  // 统计卡片
  const stats = useMemo(() => {
    const inCount = inflowSeries.length;
    const outCount = outflowSeries.length;
    const totalIn = inflowSeries.reduce((sum, s) => sum + (s.data[s.data.length - 1] || 0), 0);
    const totalOut = outflowSeries.reduce((sum, s) => sum + (s.data[s.data.length - 1] || 0), 0);
    return { inCount, outCount, totalIn, totalOut };
  }, [inflowSeries, outflowSeries]);

  // 盘后排名：默认过滤泛分类，可切换显示全部
  const filteredSectors = useMemo(() => {
    if (!rankData?.sectors) return { inflow: [], outflow: [], weakestInflow: [] };
    const list = showAll
      ? rankData.sectors
      : rankData.sectors.filter(s => !GENERIC_CONCEPTS.has(s.sector));
    const inflow = list.filter(s => s.net_flow > 0).slice(0, 30);
    const outflow = list.filter(s => s.net_flow < 0).slice(0, 20);
    // 当无净流出板块时，展示资金流入最弱的10个作为参考
    const weakestInflow = outflow.length === 0
      ? [...list].filter(s => s.net_flow > 0).sort((a, b) => a.net_flow - b.net_flow).slice(0, 10)
      : [];
    return { inflow, outflow, weakestInflow };
  }, [rankData, showAll]);

  return (
    <div className="p-3 md:p-4 space-y-3" style={{ background: 'var(--bg-primary)', minHeight: '100vh' }}>
      {/* 标题栏 */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h1 className="text-lg font-bold" style={{ color: 'var(--text-primary)' }}>
            概念板块资金流向
          </h1>
          <p className="text-xs" style={{ color: 'var(--text-muted)' }}>
            左侧盘后排名 · 右侧净流入/净流出分时走势并排
            {rankData?.actual_date && <span className="ml-2">({rankData.actual_date})</span>}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <label className="text-xs flex items-center gap-1" style={{ color: 'var(--text-secondary)' }}>
            流入Top
            <select
              value={topN}
              onChange={e => setTopN(Number(e.target.value))}
              className="px-1.5 py-1 rounded text-xs border bg-transparent"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
            >
              {[10, 12, 15, 18, 20].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <label className="text-xs flex items-center gap-1" style={{ color: 'var(--text-secondary)' }}>
            流出Top
            <select
              value={bottomN}
              onChange={e => setBottomN(Number(e.target.value))}
              className="px-1.5 py-1 rounded text-xs border bg-transparent"
              style={{ borderColor: 'var(--border-color)', color: 'var(--text-primary)' }}
            >
              {[5, 8, 10, 12, 15].map(n => <option key={n} value={n}>{n}</option>)}
            </select>
          </label>
          <button
            onClick={() => setShowAll(!showAll)}
            className={`px-2.5 py-1.5 rounded-md text-xs border transition-all ${
              showAll ? 'bg-[var(--accent-blue)] text-white border-[var(--accent-blue)]' : ''
            }`}
            style={!showAll ? {
              borderColor: 'var(--border-color)',
              color: 'var(--text-secondary)',
              background: 'var(--bg-card)',
            } : {}}
          >
            {showAll ? '全量模式' : '过滤模式'}
          </button>
          <button
            onClick={fetchData}
            className="px-3 py-1.5 rounded-md text-xs font-medium border"
            style={{ borderColor: 'var(--border-color)', color: 'var(--text-secondary)', background: 'var(--bg-card)' }}
          >
            刷新
          </button>
        </div>
      </div>

      {/* 统计卡片 */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <StatCard label="净流入板块" value={stats.inCount} color="text-red-500" />
          <StatCard label="净流出板块" value={stats.outCount} color="text-green-500" />
          <StatCard label="累计净流入" value={`+${stats.totalIn.toFixed(1)}亿`} color="text-red-500" />
          <StatCard label="累计净流出" value={`${stats.totalOut.toFixed(1)}亿`} color="text-green-500" />
        </div>
      )}

      {/* 左右布局 */}
      <div className="flex flex-col lg:flex-row gap-3" style={{ height: 'calc(100vh - 230px)', minHeight: '520px' }}>
        {/* 左侧：盘后排名（上下分区） */}
        <div
          className="lg:w-[320px] shrink-0 rounded-xl border overflow-hidden flex flex-col"
          style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
        >
          <div className="px-3 py-2 border-b flex items-center justify-between" style={{ borderColor: 'var(--border-color)' }}>
            <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
              盘后资金排名
              {!showAll && <span className="ml-1 text-[10px] font-normal" style={{ color: 'var(--text-muted)' }}>(已过滤)</span>}
            </span>
            <span className="text-[10px]" style={{ color: 'var(--text-muted)' }}>
              {filteredSectors.inflow.length + filteredSectors.outflow.length + filteredSectors.weakestInflow.length}个板块
            </span>
          </div>
          <div className="flex-1 overflow-y-auto">
            {loading && !rankData ? (
              <div className="p-4 text-center text-xs" style={{ color: 'var(--text-muted)' }}>加载中...</div>
            ) : (
              <>
                {/* 净流入区 */}
                <div className="px-2 py-1.5 text-[10px] font-semibold text-red-500 sticky top-0 z-10" style={{ background: 'var(--bg-card)' }}>
                  ▼ 净流入 ({filteredSectors.inflow.length})
                </div>
                {filteredSectors.inflow.map((s, i) => (
                  <SectorRow key={s.sector} rank={i + 1} sector={s} hasFlow={flowConceptSet.has(s.sector)} positive />
                ))}
                {/* 净流出区 / 资金流入最弱区 */}
                {filteredSectors.outflow.length > 0 ? (
                  <>
                    <div className="px-2 py-1.5 text-[10px] font-semibold text-green-500 sticky top-0 z-10" style={{ background: 'var(--bg-card)' }}>
                      ▲ 净流出 ({filteredSectors.outflow.length})
                    </div>
                    {filteredSectors.outflow.map((s, i) => (
                      <SectorRow key={s.sector} rank={i + 1} sector={s} hasFlow={flowConceptSet.has(s.sector)} />
                    ))}
                  </>
                ) : filteredSectors.weakestInflow.length > 0 ? (
                  <>
                    <div className="px-2 py-1.5 text-[10px] font-semibold sticky top-0 z-10" style={{ background: 'var(--bg-card)', color: 'var(--text-muted)' }}>
                      ▲ 资金流入最弱 ({filteredSectors.weakestInflow.length})
                      <span className="ml-1 text-[9px] font-normal" style={{ color: 'var(--text-muted)' }}>· 今日普涨无净流出</span>
                    </div>
                    {filteredSectors.weakestInflow.map((s, i) => (
                      <SectorRow key={s.sector} rank={i + 1} sector={s} hasFlow={flowConceptSet.has(s.sector)} positive weak />
                    ))}
                  </>
                ) : (
                  <div className="px-3 py-4 text-center text-[10px]" style={{ color: 'var(--text-muted)' }}>
                    今日无净流出板块
                  </div>
                )}
              </>
            )}
          </div>
        </div>

        {/* 右侧：两个图表并排 */}
        <div className="flex-1 flex flex-col lg:flex-row gap-3 min-w-0">
          {/* 净流入分时图 */}
          <div
            className="flex-1 rounded-xl border p-3 min-w-0 flex flex-col"
            style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-red-500" />
              <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                净流入 Top{inflowSeries.length}
              </span>
              {stats?.totalIn > 0 && (
                <span className="text-[10px] font-mono text-red-500 ml-auto">
                  +{stats.totalIn.toFixed(1)}亿
                </span>
              )}
            </div>
            <div className="flex-1 min-h-0">
              {loading && !flowData ? (
                <div className="h-full rounded-lg animate-pulse" style={{ background: 'var(--bg-hover)' }} />
              ) : inflowSeries.length > 0 ? (
                <MoneyFlowChart
                  series={inflowSeries}
                  timeline={flowData?.timeline || []}
                  height="100%"
                  unit="yi"
                />
              ) : (
                <div className="flex items-center justify-center h-full text-xs" style={{ color: 'var(--text-muted)' }}>
                  暂无净流入分时数据
                </div>
              )}
            </div>
          </div>

          {/* 净流出分时图 */}
          <div
            className="flex-1 rounded-xl border p-3 min-w-0 flex flex-col"
            style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}
          >
            <div className="flex items-center gap-2 mb-2">
              <span className="w-2 h-2 rounded-full bg-green-500" />
              <span className="text-xs font-semibold" style={{ color: 'var(--text-primary)' }}>
                净流出 Top{outflowSeries.length}
              </span>
              {stats?.totalOut < 0 && (
                <span className="text-[10px] font-mono text-green-500 ml-auto">
                  {stats.totalOut.toFixed(1)}亿
                </span>
              )}
            </div>
            <div className="flex-1 min-h-0">
              {loading && !flowData ? (
                <div className="h-full rounded-lg animate-pulse" style={{ background: 'var(--bg-hover)' }} />
              ) : outflowSeries.length > 0 ? (
                <MoneyFlowChart
                  series={outflowSeries}
                  timeline={flowData?.timeline || []}
                  height="100%"
                  unit="yi"
                  yAxisName="净流出(亿)"
                />
              ) : (
                <div className="flex flex-col items-center justify-center h-full gap-2">
                  <div className="text-xs" style={{ color: 'var(--text-muted)' }}>
                    今日无净流出板块
                  </div>
                  <div className="text-[10px]" style={{ color: 'var(--text-muted)', opacity: 0.7 }}>
                    全市场概念板块均为净流入
                  </div>
                </div>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* 数据说明 */}
      <div className="text-[10px] px-1" style={{ color: 'var(--text-muted)' }}>
        数据说明：左侧为概念板块盘后资金流向排名（新浪概念分类），右侧为净流入/净流出分时累计走势并排展示。
        过滤模式下隐藏融资融券、股权激励等泛分类概念，仅显示市场热点主题。
        右侧分时数据来源于新浪分钟级采集，部分概念可能无分时数据。
      </div>
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className="rounded-lg p-3 border" style={{ background: 'var(--bg-card)', borderColor: 'var(--border-color)' }}>
      <div className="text-xs" style={{ color: 'var(--text-muted)' }}>{label}</div>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
    </div>
  );
}

function SectorRow({ rank, sector, hasFlow, positive, weak }) {
  const flowYi = sector.net_flow / 10000;
  return (
    <div
      className="flex items-center px-3 py-1.5 border-b text-xs hover:bg-[var(--bg-hover)] transition-colors"
      style={{ borderColor: 'var(--border-color)', opacity: weak ? 0.6 : 1 }}
    >
      <span className="w-5 text-center font-mono text-[10px]" style={{ color: 'var(--text-muted)' }}>
        {rank}
      </span>
      <span className="flex-1 truncate mx-2 flex items-center gap-1" style={{ color: weak ? 'var(--text-muted)' : 'var(--text-primary)' }}>
        {sector.sector}
        {hasFlow && (
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-blue-400 shrink-0" title="有分时数据" />
        )}
      </span>
      <span className="text-[10px] mr-1.5" style={{ color: 'var(--text-muted)' }}>
        {sector.rise_ratio ? `${sector.rise_ratio > 0 ? '+' : ''}${sector.rise_ratio.toFixed(2)}%` : '--'}
      </span>
      <span className={`font-mono font-semibold text-[11px] ${positive ? 'text-red-500' : 'text-green-500'}`} style={weak ? { opacity: 0.7 } : {}}>
        {positive ? '+' : ''}{flowYi.toFixed(1)}亿
      </span>
    </div>
  );
}
