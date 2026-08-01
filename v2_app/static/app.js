const app = document.getElementById('app');
const state = { page: 'overview', dashboard: null, candidates: [], sectors: [], actions: null, detail: null };
const labels = { TRIGGERED: '已触发', READY: '准备', WATCH: '观察', HOLD: '持有', NO_CHASE: '禁止追高', INVALID: '失效', STRONG: '偏强', RANGE: '震荡', WEAK: '偏弱' };
const dimLabels = { market: '市场环境', sector: '板块主线', strength: '个股强度', trend: '趋势结构', volume_price: '量价行为', position: '交易位置', risk: '风险质量' };

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || data.error || `请求失败 ${response.status}`);
  return data;
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#039;' }[char]));
}
function pct(value, digits = 1) { return value == null ? '—' : `${(Number(value) * 100).toFixed(digits)}%`; }
function score(value) { return value == null ? '—' : Number(value).toFixed(1); }
function tag(text, tone = '') { return `<span class="tag ${tone}">${esc(text)}</span>`; }
function stateTag(value) {
  const tone = value === 'TRIGGERED' ? 'red' : value === 'READY' ? 'amber' : value === 'HOLD' ? 'green' : value === 'INVALID' ? '' : 'blue';
  return tag(labels[value] || value, tone);
}
function holdingAction(item) {
  const review = item.v2 || {};
  const tone = review.decision === 'SELL_REVIEW' ? 'red' : review.decision === 'HOLD' ? 'green' : 'amber';
  const action = review.decision_label || '仅账户数据';
  const note = review.reason || '暂无 V2 持仓复核';
  const code = esc(item.code || '');
  const quantity = Number(item.available_quantity || item.quantity || 0);
  return `${tag(action, tone)}<div class="metric-note">${esc(note)}</div>${quantity > 0 ? `<button class="button small preview-sell" data-sell-code="${code}" data-sell-quantity="${quantity}">预览卖出</button>` : ''}`;
}
function loading(text = '正在读取 V2 数据…') {
  app.innerHTML = `<div class="loading-card">
    <div class="loading-spinner" aria-hidden="true"></div>
    <strong>${esc(text)}</strong>
    <span>正在读取最近完成交易日、股票池和因子评分；首次计算可能需要十几秒。</span>
    <div class="loading-skeleton" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
  </div>`;
}
function errorBox(error) { app.innerHTML = `<div class="notice danger"><strong>新 V2 页面读取失败</strong>${esc(error.message || error)}<br><span>请先确认 PostgreSQL 和 9000/9001 新程序已启动。</span></div>`; }

function marketBanner(market) {
  if (!market) return '<div class="notice warn"><strong>没有完成交易日数据</strong>数据库暂时没有可计算的日线。</div>';
  return `<div class="market-banner">
    <div><div class="metric-label">信号交易日 ${esc(market.trade_date)}</div><div class="market-state ${esc(market.state)}">${esc(labels[market.state] || market.state)} · ${esc(market.sentiment)}</div></div>
    <div class="market-facts"><span>上涨比例<b>${pct(market.breadth)}</b></span><span>涨停<b>${market.limit_up}</b></span><span>跌停<b>${market.limit_down}</b></span><span>20日市场收益<b>${pct(market.market_return_20d)}</b></span></div>
  </div>`;
}

function metric(label, value, note, tone = '') { return `<div class="card metric-${tone}"><div class="metric-label">${label}</div><div class="metric-value">${value}</div><div class="metric-note">${note}</div></div>`; }

function signalRow(item) {
  const dims = (item.resonance_dimensions || []).map(key => tag(dimLabels[key] || key, 'blue')).join('');
  const patterns = (item.patterns || []).map(pattern => tag(`${pattern.label}：${pattern.text}`, 'amber')).join('');
  return `<tr class="clickable" data-code="${esc(item.code)}">
    <td><b>#${item.rank}</b></td><td><div class="stock-name">${esc(item.name)}</div><div class="stock-code">${esc(item.code)}</div></td>
    <td>${esc(item.sector)}</td><td><span class="score">${score(item.factor_score)}</span></td>
    <td>${stateTag(item.trading_state)}</td><td><b>${item.resonance_count}</b> / 6</td>
    <td>${dims}${patterns}</td><td>${tag(item.lifecycle, item.lifecycle === '退潮' ? '' : 'green')}</td>
  </tr>`;
}

function table(title, items, hint = '') {
  return `<div class="section"><div class="section-title"><h3>${title}</h3><span>${hint}</span></div><div class="table-wrap"><table><thead><tr><th>排名</th><th>股票</th><th>板块</th><th>因子综合分</th><th>交易状态</th><th>共振</th><th>独立证据</th><th>生命周期</th></tr></thead><tbody>${items.length ? items.map(signalRow).join('') : `<tr><td colspan="8"><div class="empty">暂无符合条件的股票</div></td></tr>`}</tbody></table></div></div>`;
}

function bindRows() { document.querySelectorAll('tr[data-code]').forEach(row => row.addEventListener('click', () => showDetail(row.dataset.code))); }

async function loadBase() {
  const [dashboard, candidates] = await Promise.all([api('/api/v2/dashboard'), api('/api/v2/candidates?limit=80')]);
  state.dashboard = dashboard; state.candidates = candidates.signals || [];
}

function renderOverview() {
  const d = state.dashboard || {}; const c = state.candidates || [];
  const counts = d.state_counts || {};
  app.innerHTML = `<div class="page-head"><div><h2>系统总览</h2><p>先看市场环境，再看可执行信号；总分不是买入理由，只有“已触发（TRIGGERED）”才是右侧触发。</p></div><div class="actions"><button class="button" id="refresh">刷新计算</button><button class="button primary" id="persist">保存本日快照</button></div></div>
    ${marketBanner(d.market)}
    <div class="grid grid-4 section">
      ${metric(d.production_ready ? '生产股票池' : '研究股票池', d.universe_count || 0, `已过滤 ST ${d.st_filtered_count || 0} 只；日线/成交量有效`, 'blue')}
      ${metric(d.production_ready ? '共振通过' : '研究共振通过', d.resonance_eligible || 0, '至少4个机会维度，趋势通过，风险闸门通过', 'green')}
      ${metric('右侧已触发', d.triggered || 0, '已触发；仍需人工确认与账户风控', 'red')}
      ${metric('信号交易日', d.trade_date || '—', '不是自然日；只使用最近完成的日线', 'amber')}
    </div>
    <div class="section card"><div class="section-title"><h3>交易状态分布</h3><span>风险维度不计入机会共振，只能否决</span></div><div class="state-grid">${['TRIGGERED','READY','WATCH','HOLD','NO_CHASE','INVALID'].map(key => `<div class="state-box state-${key}"><strong>${counts[key] || 0}</strong><span>${labels[key]}</span></div>`).join('')}</div></div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>今日排名前10</h3><span>全市场横向排名后展示</span></div><div class="table-wrap"><table><thead><tr><th>排名</th><th>股票</th><th>分数</th><th>状态</th><th>共振</th></tr></thead><tbody>${c.slice(0, 10).map(item => `<tr class="clickable" data-code="${esc(item.code)}"><td>#${item.rank}</td><td><b>${esc(item.name)}</b><div class="stock-code">${esc(item.code)}</div></td><td class="score">${score(item.factor_score)}</td><td>${stateTag(item.trading_state)}</td><td>${item.resonance_count}/6</td></tr>`).join('')}</tbody></table></div></div>
      <div class="card"><div class="section-title"><h3>如何使用这一页</h3><span>V2 决策顺序</span></div><div class="notice"><strong>1. 市场环境</strong>市场偏弱时，候选只能观察或禁止追高，不会因为个股分高而强行买入。</div><div class="notice section"><strong>2. 独立证据</strong>共振至少4个机会维度，趋势必须有效；风险只做闸门，不能增加共振数量。</div><div class="notice warn section"><strong>3. 交易状态</strong>主升不等于买入。只有已触发状态才能进入交易预览，且当前新程序默认不下单。</div></div></div>
    <div class="footer-note">数据来源：${esc((d.data_sources || {}).daily_bars || '旧库')}；没有把旧策略命中数当成胜率。</div>`;
  bindRows();
  document.getElementById('refresh').onclick = () => { state.dashboard = null; loadPage('overview'); };
  document.getElementById('persist').onclick = async () => { document.getElementById('persist').disabled = true; try { await api('/api/v2/snapshot/persist', { method: 'POST' }); alert('本日 V2 快照已保存'); } catch (e) { alert(e.message); } finally { document.getElementById('persist').disabled = false; } };
}

async function renderSectors() {
  const data = await api('/api/v2/sectors?limit=50'); state.sectors = data.sectors || [];
  app.innerHTML = `<div class="page-head"><div><h2>板块流动</h2><p>板块资金是独立证据，必须与个股趋势、强度和交易位置共同判断。</p></div><span class="muted">评分日 ${esc(data.trade_date || '—')} · 资金日 ${esc(state.sectors[0]?.flow_date || '—')}</span></div><div class="notice">资金流入只说明板块环境改善，不等于个股可以买入；右侧触发仍由 V2 交易状态决定。</div><div class="card"><div class="table-wrap"><table><thead><tr><th>板块</th><th>资金净流入</th><th>热度</th><th>上涨比例</th><th>平均涨跌</th><th>股票数</th><th>平均因子分</th><th>共振/触发</th></tr></thead><tbody>${state.sectors.length ? state.sectors.map(item => `<tr><td><b>${esc(item.sector)}</b></td><td class="${Number(item.net_flow || 0) >= 0 ? 'positive' : 'negative'}">${item.net_flow == null ? '—' : Number(item.net_flow).toFixed(0)}</td><td>${item.heat_score == null ? '—' : Number(item.heat_score).toFixed(1)}</td><td>${item.rise_ratio == null ? '—' : (Number(item.rise_ratio) * 100).toFixed(1) + '%'}</td><td>${item.avg_chg == null ? '—' : Number(item.avg_chg).toFixed(2) + '%'}</td><td>${item.count}</td><td class="score">${score(item.avg_score)}</td><td>${item.eligible}/${item.triggered}</td></tr>`).join('') : `<tr><td colspan="8"><div class="empty">暂无板块数据</div></td></tr>`}</tbody></table></div></div>`;
}

async function renderCandidates() {
  const data = await api('/api/v2/candidates?limit=500'); state.candidates = data.signals || [];
  app.innerHTML = `<div class="page-head"><div><h2>选股中心</h2><p>全市场 ${data.universe_count} 只先计算、后排序；排名前端只负责展示。</p></div>${marketBanner(data.market)}</div><div class="filters"><input id="search" placeholder="搜索股票名称 / 代码 / 板块" /><select id="stateFilter"><option value="">全部交易状态</option>${['TRIGGERED','READY','WATCH','NO_CHASE','INVALID'].map(key => `<option value="${key}">${labels[key]}</option>`).join('')}</select><select id="resonanceFilter"><option value="">全部共振</option><option value="4">≥4个机会维度</option><option value="5">≥5个机会维度</option></select></div><div id="candidateTable"></div>`;
  const draw = () => { const q = (document.getElementById('search').value || '').toLowerCase(); const sf = document.getElementById('stateFilter').value; const rf = Number(document.getElementById('resonanceFilter').value || 0); const list = state.candidates.filter(item => (!q || `${item.name}${item.code}${item.sector}`.toLowerCase().includes(q)) && (!sf || item.trading_state === sf) && (!rf || item.resonance_count >= rf)); document.getElementById('candidateTable').innerHTML = table('全市场因子排名', list, `显示 ${list.length} 条`); bindRows(); };
  document.getElementById('search').oninput = draw; document.getElementById('stateFilter').onchange = draw; document.getElementById('resonanceFilter').onchange = draw; draw();
}

function actionCard(title, items, tone) { return `<div class="card"><div class="section-title"><h3>${title}</h3><span>${items.length} 条</span></div>${items.length ? items.slice(0, 10).map(item => `<div class="detail section"><div class="section-title"><b>${esc(item.name)} <span class="stock-code">${esc(item.code)}</span></b><span class="score">${score(item.factor_score)}</span></div><div>${stateTag(item.trading_state)} ${tag(`${item.resonance_count}个机会维度`, tone)} ${(item.patterns || []).map(p => tag(`${p.label}形态`, 'amber')).join('')}</div><div class="metric-note">${esc((item.reasons || []).slice(0, 3).join('；'))}</div></div>`).join('') : '<div class="empty">暂无</div>'}</div>`; }
async function renderActions() { const data = await api('/api/v2/actions?limit=30'); state.actions = data; app.innerHTML = `<div class="page-head"><div><h2>量化动作</h2><p>这里展示“可执行性”，不是旧策略数量比赛。游资/形态只负责解释，不改变因子综合分。</p></div><div class="notice warn">当前外部下单关闭</div></div>${marketBanner(data.market)}<div class="grid grid-3 section">${actionCard('已触发（TRIGGERED）', data.triggered || [], 'red')}${actionCard('准备（READY）', data.ready || [], 'amber')}${actionCard('禁止追高（NO_CHASE）', data.no_chase || [], '')}</div><div class="section notice"><strong>卖出/失效原则</strong>持仓页会单独显示实时或缓存持仓；新系统不会因为“形态标签消失”就伪造卖出成交，实际成交必须通过委托回报核对。</div>`; }

function holdingRows(account) { return (account.positions || []).map(item => `<tr><td><b>${esc(item.name || item.code)}</b><div class="stock-code">${esc(item.code)}</div></td><td>${item.quantity}</td><td>${Number(item.avg_cost || 0).toFixed(2)}</td><td>${Number(item.last_price || 0).toFixed(2)}</td><td>${Number(item.market_value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</td><td class="${item.unrealized_pnl >= 0 ? 'positive' : 'negative'}">${Number(item.unrealized_pnl || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}</td><td>${holdingAction(item)}</td></tr>`).join(''); }
function bindHoldingActions() { document.querySelectorAll('.preview-sell').forEach(button => { button.onclick = async event => { event.stopPropagation(); button.disabled = true; try { const result = await api('/api/v2/trade/preview', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ action: 'sell', code: button.dataset.sellCode, quantity: Number(button.dataset.sellQuantity), confirm: false }) }); alert(`卖出预览：${result.reason || '仅预览'}\n${result.signal ? `${result.signal.name}｜状态 ${labels[result.signal.trading_state] || result.signal.trading_state}` : ''}`); } catch (e) { alert(e.message); } finally { button.disabled = false; } }; }); }
async function renderHoldings() { const account = await api('/api/v2/holdings?live=false'); app.innerHTML = `<div class="page-head"><div><h2>持仓与交易</h2><p>持仓来源与信号来源分开显示；缓存账户不等于实时成交回报。</p></div><div class="actions"><button class="button" id="liveHoldings">请求实时账户</button><button class="button" id="orders">查看 V2 审计</button></div></div><div class="notice warn"><strong>新程序默认只读</strong>${esc(account.v2_summary || '卖出复核只提示，不会自动下单。')}；买卖执行必须同时开启环境开关、配置开关、操作密钥并 confirm=true。</div><div class="grid grid-4 section">${metric('总资产', Number(account.total_assets || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 }), account.source, 'blue')}${metric('现金', Number(account.cash || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 }), '账户余额', 'green')}${metric('持仓市值', Number(account.market_value || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 }), `${account.positions?.length || 0} 只`, 'amber')}${metric('浮动盈亏', Number(account.unrealized_pnl || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 }), account.data_quality, Number(account.unrealized_pnl || 0) >= 0 ? 'green' : 'red')}</div><div class="card section"><div class="section-title"><h3>持仓明细</h3><span>${esc((account.limitations || []).join('；'))}</span></div><div class="table-wrap"><table><thead><tr><th>股票</th><th>数量</th><th>成本</th><th>现价</th><th>市值</th><th>浮动盈亏</th><th>V2持仓决定</th></tr></thead><tbody>${holdingRows(account) || '<tr><td colspan="7"><div class="empty">缓存中没有持仓；点击“请求实时账户”检查妙想接口。</div></td></tr>'}</tbody></table></div></div>`; bindHoldingActions(); document.getElementById('liveHoldings').onclick = async () => { document.getElementById('liveHoldings').disabled = true; try { const live = await api('/api/v2/holdings?live=true'); renderHoldingsWith(live); } catch (e) { alert(e.message); } }; document.getElementById('orders').onclick = async () => { const data = await api('/api/v2/orders?live=false'); alert((data.orders || []).length ? JSON.stringify(data.orders.slice(0, 10), null, 2) : '暂无 V2 审计'); }; }
function renderHoldingsWith(account) { const values = [account.total_assets, account.cash, account.market_value, account.unrealized_pnl]; app.querySelectorAll('.grid-4 .metric-value').forEach((node, index) => { if (values[index] != null) node.textContent = Number(values[index]).toLocaleString('zh-CN', { maximumFractionDigits: 0 }); }); const body = app.querySelector('tbody'); body.innerHTML = holdingRows(account) || '<tr><td colspan="7"><div class="empty">没有持仓</div></td></tr>'; const notice = app.querySelector('.notice.warn'); notice.innerHTML = `<strong>${esc(account.source)}</strong>${esc(account.v2_summary || '')}；${esc((account.limitations || []).join('；'))}`; bindHoldingActions(); }

function signed(value, suffix = '%') { return value == null ? '—' : `${Number(value) >= 0 ? '+' : ''}${Number(value).toFixed(2)}${suffix}`; }
function researchMetric(label, value, note = '') { return `<div class="detail"><b>${esc(label)}</b><div class="metric-value">${value}</div><div class="metric-note">${esc(note)}</div></div>`; }
function renderUnifiedResearch(data) {
  const d = data.factor_decision || {};
  const factorStatus = d.trading_state ? stateTag(d.trading_state) : tag('暂无 V2 快照', 'amber');
  const factorScore = d.factor_score == null ? '—' : score(d.factor_score);
  const returnRows = Object.entries(data.returns || {}).map(([key, value]) => `<div class="detail"><b>${({d1:'1日', d5:'5日', d20:'20日', d60:'60日'})[key]}</b><div class="${Number(value || 0) >= 0 ? 'positive' : 'negative'}">${signed(value)}</div></div>`).join('');
  const reasons = (d.reasons || []).map(x => `<div class="metric-note">• ${esc(x)}</div>`).join('') || '<div class="metric-note">尚未产生 V2 因子快照；仅展示真实基础数据。</div>';
  app.innerHTML = `<div class="page-head"><div><h2>${esc(data.name)} <span class="stock-code">${esc(data.code)}</span></h2><p>${esc(data.sector)} · 数据日 ${esc(data.trade_date || '—')} · 基础数据与因子结论分层展示</p></div><button class="button" id="backCandidates">返回选股中心</button></div>
    <div class="grid grid-4">${researchMetric('最新收盘', data.price == null ? '—' : Number(data.price).toFixed(2), `当日 ${signed(data.price_change)}`)}${researchMetric('因子综合分', factorScore, d.score_mode === 'PRODUCTION' ? '生产因子评分' : '研究因子评分')}${researchMetric('交易状态', factorStatus, d.lifecycle ? `生命周期：${d.lifecycle}` : '暂无因子结论')}${researchMetric('独立共振', d.resonance_count == null ? '—' : `${d.resonance_count}/6`, d.resonance_reason || '趋势必须有效，风险只做闸门')}</div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>真实市场数据</h3><span>来自旧库，不参与伪造评分</span></div><div class="grid grid-4">${returnRows}</div><div class="grid grid-3 section">${researchMetric('MA5', data.trend?.ma5 == null ? '—' : Number(data.trend.ma5).toFixed(2))}${researchMetric('MA20', data.trend?.ma20 == null ? '—' : Number(data.trend.ma20).toFixed(2))}${researchMetric('MA60', data.trend?.ma60 == null ? '—' : Number(data.trend.ma60).toFixed(2))}</div><div class="grid grid-3 section">${researchMetric('距80日高点', signed(data.trend?.distance_to_high))}${researchMetric('20日支撑', data.trend?.support_20d == null ? '—' : Number(data.trend.support_20d).toFixed(2))}${researchMetric('5日量比', data.volume?.ratio_to_5d == null ? '—' : `${Number(data.volume.ratio_to_5d).toFixed(2)}x`)}</div></div><div class="card"><div class="section-title"><h3>V2 因子与交易决策</h3><span>不混入旧策略分数</span></div><div class="notice"><strong>通过证据</strong>${(d.resonance_dimensions || []).map(x => tag(dimLabels[x] || x, 'green')).join('') || '暂无'}</div><div class="notice warn section"><strong>限制条件</strong>${(d.failed_dimensions || []).map(x => tag(dimLabels[x] || x)).join('') || '暂无'}</div><div class="section">${reasons}</div></div></div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>量价与资金</h3><span>事实数据</span></div><div class="grid grid-3">${researchMetric('今日成交量', data.volume?.today == null ? '—' : Number(data.volume.today).toLocaleString('zh-CN', {maximumFractionDigits:0}))}${researchMetric('5日均量', data.volume?.avg5 == null ? '—' : Number(data.volume.avg5).toLocaleString('zh-CN', {maximumFractionDigits:0}))}${researchMetric('主力净流', data.money_flow?.main_force_inflow == null ? '—' : Number(data.money_flow.main_force_inflow).toLocaleString('zh-CN', {maximumFractionDigits:0}))}</div></div><div class="card"><div class="section-title"><h3>风险与位置</h3><span>辅助风控，不单独买卖</span></div><div class="grid grid-3">${researchMetric('80日最大回撤', signed(data.risk?.max_drawdown_80d))}${researchMetric('20日波动区间', signed(data.risk?.range_20d))}${researchMetric('近期高点', data.trend?.recent_high == null ? '—' : Number(data.trend.recent_high).toFixed(2))}</div></div></div>
    <div class="footer-note">基础数据：${esc(data.source?.market_data || '—')}；因子结论：${esc(data.source?.factor_data || '—')}。旧系统资讯与报告将作为辅助研究资料接入，不参与 Factor Score。</div>`;
  document.getElementById('backCandidates').onclick = () => loadPage('candidates');
}
async function showDetail(code) { try { const data = await api(`/api/v2/stock/${encodeURIComponent(code)}/research`); state.detail = data; renderUnifiedResearch(data); } catch (e) { alert(e.message); } }
function renderDetail(item, history = {}) { const bars = history.bars || []; const latest = bars[bars.length - 1] || {}; const dims = Object.values(item.dimensions || {}).map(dim => `<div class="dimension-row"><span class="label">${esc(dim.label)}</span><div class="bar"><i class="${dim.valid ? '' : 'invalid'}" style="width:${dim.valid ? Math.max(2, Number(dim.score || 0)) : 5}%"></i></div><strong>${dim.valid ? score(dim.score) : '无效'}</strong></div>`).join(''); app.innerHTML = `<div class="page-head"><div><h2>${esc(item.name)} <span class="stock-code">${esc(item.code)}</span></h2><p>${esc(item.sector)} · 信号日 ${esc(item.trade_date)} · 有效至 ${esc(item.signal_valid_until || '—')}</p></div><button class="button" id="backCandidates">返回选股中心</button></div><div class="grid grid-4"><div class="card"><div class="metric-label">因子综合分</div><div class="metric-value">${score(item.factor_score)}</div><div>${stateTag(item.trading_state)} ${tag(item.lifecycle, 'green')}</div></div><div class="card"><div class="metric-label">最新收盘</div><div class="metric-value">${latest.close == null ? '—' : Number(latest.close).toFixed(2)}</div><div class="metric-note">${esc(latest.trade_date || '—')} · ${latest.pct_chg == null ? '—' : Number(latest.pct_chg).toFixed(2) + '%'}</div></div><div class="card"><div class="metric-label">独立机会共振</div><div class="metric-value">${item.resonance_count} / 6</div><div>${(item.resonance_dimensions || []).map(key => tag(dimLabels[key] || key, 'blue')).join('')}</div></div><div class="card"><div class="metric-label">历史行情</div><div class="metric-value">${bars.length} 日</div><div class="metric-note">真实 stock_daily_kline</div></div></div><div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>七维评分</h3><span>风险只做闸门</span></div><div class="dimension-list">${dims}</div></div><div class="card"><div class="section-title"><h3>决策解释</h3><span>${esc(item.resonance_reason)}</span></div><div class="notice"><strong>通过证据</strong>${(item.resonance_dimensions || []).map(key => tag(dimLabels[key] || key, 'green')).join('') || '无'}</div><div class="notice warn section"><strong>失败/限制</strong>${(item.failed_dimensions || []).map(key => tag(dimLabels[key] || key)).join('') || '无'}</div><div class="section">${(item.reasons || []).map(reason => `<div class="metric-note">• ${esc(reason)}</div>`).join('')}</div></div></div><div class="card section"><div class="section-title"><h3>最近行情</h3><span>仅展示真实数据，不生成额外信号</span></div><div class="table-wrap"><table><thead><tr><th>日期</th><th>开盘</th><th>最高</th><th>最低</th><th>收盘</th><th>涨跌</th><th>成交额</th></tr></thead><tbody>${bars.slice(-15).reverse().map(bar => `<tr><td>${esc(bar.trade_date)}</td><td>${Number(bar.open || 0).toFixed(2)}</td><td>${Number(bar.high || 0).toFixed(2)}</td><td>${Number(bar.low || 0).toFixed(2)}</td><td>${Number(bar.close || 0).toFixed(2)}</td><td class="${Number(bar.pct_chg || 0) >= 0 ? 'positive' : 'negative'}">${Number(bar.pct_chg || 0).toFixed(2)}%</td><td>${bar.amount == null ? '—' : Number(bar.amount).toLocaleString('zh-CN', {maximumFractionDigits: 0})}</td></tr>`).join('') || '<tr><td colspan="7">暂无行情</td></tr>'}</tbody></table></div></div>`; document.getElementById('backCandidates').onclick = () => loadPage('candidates'); }

async function renderAnalysis() { app.innerHTML = `<div class="page-head"><div><h2>个股研究中心</h2><p>一个入口同时查看真实行情、量价资金、V2 因子研究与交易结论；旧策略不参与新评分。</p></div></div><div class="card"><div class="filters"><input id="stockCode" placeholder="例如 000001.SZ 或 000001" /><button class="button primary" id="openStock">开始个股研究</button></div><div class="muted-box">输入股票代码，或从选股中心、自选、持仓页面点击股票进入。基础数据和因子决策会明确分区。</div></div>`; document.getElementById('openStock').onclick = () => { const code = document.getElementById('stockCode').value.trim(); if (code) showDetail(code); }; }

async function renderWatchlist() {
  const data = await api('/api/v2/watchlist');
  const rows = data.watchlist || [];
  app.innerHTML = `<div class="page-head"><div><h2>自选</h2><p>自选只负责跟踪；真正的评分和交易状态统一来自 V2 因子系统。</p></div><div class="actions"><input id="watchCode" placeholder="股票代码" /><input id="watchName" placeholder="中文名称（可选）" /><button class="button primary" id="addWatch">加入自选</button><button class="button" id="reloadWatch">刷新</button></div></div><div class="notice"><strong>当前 ${rows.length} 只</strong> 旧自选数据已接入，新页面不再读取旧策略分数。</div><div class="card section"><div class="table-wrap"><table><thead><tr><th>股票</th><th>分组</th><th>V2因子分</th><th>交易状态</th><th>共振</th><th>质量标签</th><th>操作</th></tr></thead><tbody>${rows.length ? rows.map(row => { const s = row.signal; return `<tr class="clickable" data-code="${esc(s?.code || row.code)}"><td><b>${esc(row.name || s?.name || row.code)}</b><div class="stock-code">${esc(row.code)}</div></td><td>${tag(row.group_name || '默认')}</td><td class="score">${s ? score(s.factor_score) : '—'}</td><td>${s ? stateTag(s.trading_state) : tag('暂无信号')}</td><td>${s ? `${s.resonance_count}/6` : '—'}</td><td>${tag(row.quality_status || '普通', row.quality_status === '强势' || row.quality_status === '核心' ? 'green' : '')}</td><td><button class="button small remove-watch" data-code="${esc(row.code)}">移除</button></td></tr>`; }).join('') : '<tr><td colspan="7"><div class="empty">暂无自选，输入股票代码后加入。</div></td></tr>'}</tbody></table></div></div>`;
  document.getElementById('reloadWatch').onclick = () => loadPage('watchlist');
  document.getElementById('addWatch').onclick = async () => { const code = document.getElementById('watchCode').value.trim(); const name = document.getElementById('watchName').value.trim(); if (!code) return; try { await api('/api/v2/watchlist', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({code, name}) }); loadPage('watchlist'); } catch (e) { alert(e.message); } };
  bindRows();
  document.querySelectorAll('.remove-watch').forEach(button => { button.onclick = async event => { event.stopPropagation(); if (!confirm(`确认移除 ${button.dataset.code}？`)) return; try { await api(`/api/v2/watchlist/${encodeURIComponent(button.dataset.code)}`, { method: 'DELETE' }); loadPage('watchlist'); } catch (e) { alert(e.message); } }; });
}

async function renderYuzi() {
  const data = await api('/api/v2/yuzi');
  const rows = data.signals || [];
  app.innerHTML = `<div class="page-head"><div><h2>游资</h2><p>龙虎榜作为外部资金证据展示，不直接增加 V2 因子分，也不单独触发买入。</p></div><span class="muted">数据日 ${esc(data.trade_date || '—')}</span></div><div class="notice warn"><strong>使用边界</strong>游资净买入、席位共振和上榜原因只能辅助解释；必须与市场、板块、趋势和风险维度同时成立。</div><div class="card section"><div class="table-wrap"><table><thead><tr><th>股票</th><th>板块</th><th>游资净买入</th><th>游资共振</th><th>游资评分</th><th>涨跌</th><th>上榜原因</th></tr></thead><tbody>${rows.length ? rows.map(row => `<tr class="clickable" data-code="${esc(row.code)}"><td><b>${esc(row.name || row.code)}</b><div class="stock-code">${esc(row.code)}</div></td><td>${esc(row.sector || '—')}</td><td class="positive">${row.total_net_buy == null ? '—' : Number(row.total_net_buy).toFixed(0)} 万</td><td>${row.resonance_count || 0}</td><td class="score">${score(row.quant_score)}</td><td>${row.change_pct == null ? '—' : Number(row.change_pct).toFixed(2) + '%'}</td><td>${esc(row.list_reason || row.list_tag || '—')}</td></tr>`).join('') : '<tr><td colspan="7"><div class="empty">暂无最新游资龙虎榜聚合数据。</div></td></tr>'}</tbody></table></div></div>`;
  bindRows();
}

async function renderValidation() { app.innerHTML = `<div class="page-head"><div><h2>因子验证</h2><p>IC / Rank IC / 分状态收益只来自历史截面；验证结果不会自动改生产权重。</p></div><button class="button primary" id="runValidation">运行最近20日验证</button></div><div id="validationBody" class="card"><div class="loading">点击运行后计算，可能需要几十秒…</div></div>`; document.getElementById('runValidation').onclick = async () => { document.getElementById('validationBody').innerHTML = '<div class="loading">正在严格按日期截断历史…</div>'; try { const data = await api('/api/v2/validation?days=20&limit=300&persist=true'); const rows = (data.rows || []).sort((a,b) => Math.abs(b.rank_ic || 0) - Math.abs(a.rank_ic || 0)); document.getElementById('validationBody').innerHTML = `<div class="notice"><strong>研究样本</strong>交易日 ${esc(data.trade_date)} · 股票 ${data.research_universe_count} · 样本 ${data.sample_count} · 仅 Rank IC > 0 且样本≥30 才标记通过。</div><div class="section"><div class="table-wrap"><table><thead><tr><th>因子</th><th>样本</th><th>IC</th><th>Rank IC</th><th>平均5日收益</th><th>生产建议</th></tr></thead><tbody>${rows.map(row => `<tr><td><b>${esc(row.factor_name)}</b></td><td>${row.sample_count}</td><td>${row.ic == null ? '—' : Number(row.ic).toFixed(3)}</td><td>${row.rank_ic == null ? '—' : Number(row.rank_ic).toFixed(3)}</td><td>${pct(row.mean_forward_return)}</td><td>${row.passed ? tag('保留观察', 'green') : tag('暂不放大', 'amber')}</td></tr>`).join('')}</tbody></table></div></div><div class="section"><h3>状态收益对照</h3><div class="grid grid-3">${Object.entries(data.horizons?.['5']?.states || {}).map(([key, value]) => `<div class="detail"><b>${labels[key] || key}</b><div class="metric-note">样本 ${value.count} · 均值 ${pct(value.mean)} · 胜率 ${pct(value.win_rate)}</div></div>`).join('')}</div></div>`; } catch (e) { document.getElementById('validationBody').innerHTML = `<div class="notice danger">${esc(e.message)}</div>`; } }; }

async function renderSystem() { const [health, registry, config] = await Promise.all([api('/api/v2/health'), api('/api/v2/registry'), api('/api/v2/config')]); app.innerHTML = `<div class="page-head"><div><h2>系统状态</h2><p>这里专门区分“系统可运行”和“因子有证据”，不使用假健康分。</p></div><button class="button" id="saveSnapshot">保存本日快照</button></div><div class="grid grid-3"><div class="card"><div class="metric-label">服务状态</div><div class="metric-value positive">${esc(health.status)}</div><div class="metric-note">端口由启动命令决定；旧程序不受影响</div></div><div class="card"><div class="metric-label">生产因子</div><div class="metric-value">${health.production_factor_count}</div><div class="metric-note">七个独立维度</div></div><div class="card"><div class="metric-label">股票池</div><div class="metric-value">${health.eligible_universe}</div><div class="metric-note">最近完成交易日：${esc(health.trade_date || '—')}</div></div></div><div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>数据契约</h3><span>只读接入旧库</span></div><div class="detail"><b>行情</b><div class="metric-note">stock_daily_kline · 日期截断 · OHLCV</div></div><div class="detail section"><b>股票元数据</b><div class="metric-note">stock_flow · 中文名称/行业 · ST 过滤</div></div><div class="detail section"><b>板块资金</b><div class="metric-note">sector_flow · 没有数据时明确显示缺失</div></div></div><div class="card"><div class="section-title"><h3>交易保护</h3><span>${config.enabled ? '已打开' : '关闭'}</span></div><div class="notice warn"><strong>外部下单：${config.enabled ? '配置已打开' : '关闭'}</strong>新程序默认 V2_TRADING_ENABLED=false；买卖必须预览、确认、密钥三重条件。</div><div class="detail section"><b>账户模式</b><div class="metric-note">${config.account_source === 'dedicated' ? '专用交易账户' : '持仓页展示账户（默认）'}</div></div></div></div><div class="card section"><div class="section-title"><h3>因子目录</h3><span>${registry.factor_count} 个</span></div><div class="table-wrap"><table><thead><tr><th>因子</th><th>分类</th><th>来源</th><th>周期</th><th>方向</th><th>生产</th></tr></thead><tbody>${registry.factors.map(item => `<tr><td><b>${esc(item.label)}</b><div class="stock-code">${esc(item.name)}</div></td><td>${esc(item.category_label)}</td><td>${esc(item.source)}</td><td>${item.period || '—'}</td><td>${item.direction > 0 ? '越高越好' : '越低越好'}</td><td>${item.production ? tag('生产', 'green') : tag('研究')}</td></tr>`).join('')}</tbody></table></div></div>`; document.getElementById('saveSnapshot').onclick = async () => { try { await api('/api/v2/snapshot/persist', { method: 'POST' }); alert('已保存'); } catch (e) { alert(e.message); } }; }

async function renderQuality() {
  const [quality, collection] = await Promise.all([api('/api/v2/system/quality'), api('/api/v2/collection/status')]);
  const sources = quality.sources || [];
  const anomalies = quality.anomalies || [];
  const freshness = (collection.freshness || {}).tables || [];
  app.innerHTML = `<div class="page-head"><div><h2>数据质量</h2><p>独立展示旧采集系统的数据质量与新鲜度；只读，不会自动篡改历史行情。</p></div></div>
    <div class="grid grid-3"><div class="card"><div class="metric-label">已接入数据源</div><div class="metric-value">${quality.source_count || 0}</div><div class="metric-note">来源：9000 数据质量接口</div></div><div class="card"><div class="metric-label">异常记录</div><div class="metric-value">${quality.anomaly_count || 0}</div><div class="metric-note">仅提示，需人工确认</div></div><div class="card"><div class="metric-label">待审核</div><div class="metric-value">${quality.pending_review_count || 0}</div><div class="metric-note">交易日 ${esc(quality.trade_date || '—')}</div></div></div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>数据源质量</h3><span>质量分与异常率</span></div><div class="table-wrap"><table><thead><tr><th>来源</th><th>样本</th><th>质量分</th><th>异常率</th></tr></thead><tbody>${sources.map(x => `<tr><td>${esc(x.source || '—')}</td><td>${x.total_count ?? '—'}</td><td>${x.score == null ? '—' : Number(x.score).toFixed(1)}</td><td>${x.outlier_rate == null ? '—' : Number(x.outlier_rate).toFixed(2) + '%'}</td></tr>`).join('') || '<tr><td colspan="4">暂无质量数据</td></tr>'}</tbody></table></div></div><div class="card"><div class="section-title"><h3>采集新鲜度</h3><span>${esc(collection.collector_owner || '9000 采集器')}</span></div><div class="table-wrap"><table><thead><tr><th>数据表</th><th>最新日期</th><th>滞后天数</th><th>状态</th></tr></thead><tbody>${freshness.slice(0, 12).map(x => `<tr><td>${esc(x.table)}</td><td>${esc(x.latest || '—')}</td><td>${x.gap_days ?? '—'}</td><td>${x.fresh ? tag('正常', 'green') : tag('滞后/缺失', 'amber')}</td></tr>`).join('') || '<tr><td colspan="4">暂无新鲜度数据</td></tr>'}</tbody></table></div></div></div>
    <div class="card section"><div class="section-title"><h3>异常样本</h3><span>前 10 条</span></div><div class="table-wrap"><table><thead><tr><th>股票/对象</th><th>指标</th><th>偏差</th><th>处理</th></tr></thead><tbody>${anomalies.slice(0, 10).map(x => `<tr><td>${esc(x.name || x.ts_code || '—')}</td><td>${esc(x.indicator || '多源数据')}</td><td>${x.deviation_pct == null ? '—' : Number(x.deviation_pct).toFixed(1) + '%'}</td><td>${x.is_corrected ? tag('已修正', 'green') : tag('待确认', 'amber')}</td></tr>`).join('') || '<tr><td colspan="4">暂无异常样本</td></tr>'}</tbody></table></div></div>`;
}

async function renderCollection() {
  const data = await api('/api/v2/system/quality-dashboard');
  const overview = data.overview || {};
  const services = data.services || [];
  const sources = data.sources || [];
  const anomalies = data.anomalies || [];
  const reviews = data.review_queue || {};
  const freshness = data.freshness || {};
  const tables = freshness.sources || freshness.tables || [];
  const statusLabel = {up:'运行中', down:'离线', ready:'就绪', idle:'待命'};
  const statusTone = {up:'green', down:'red', ready:'amber', idle:'amber'};
  const confidence = overview.confidence_distribution || {};
  const maxScore = Math.max(1, ...sources.map(x => Number(x.avg_score || 0)));
  app.innerHTML = `<div class="page-head"><div><h2>数据中心</h2><p>已迁移 9000 数据质量工作台：服务、采集新鲜度、质量评分、审核队列与异常数据。9001 仅只读展示。</p></div><button class="button" id="reloadQuality">刷新</button></div>
    <div class="card"><div class="section-title"><h3>服务状态</h3><span>${services.filter(x => x.status === 'up').length} 在线 · ${services.filter(x => x.status === 'down').length} 离线</span></div><div class="grid grid-3">${services.map(s => `<div class="detail"><b><span class="status-dot" style="background:${s.status === 'up' ? '#43a977' : s.status === 'down' ? '#d14b52' : '#bd7a18'}"></span>${esc(s.label || s.key || '服务')}</b><div class="metric-note">${esc(s.detail || '—')}</div><div>${tag(statusLabel[s.status] || '待命', statusTone[s.status] || 'amber')}</div></div>`).join('') || '<div class="muted-box">暂无服务状态数据</div>'}</div></div>
    <div class="card section"><div class="section-title"><h3>数据新鲜度</h3><span>只读采集监控</span></div><div class="table-wrap"><table><thead><tr><th>数据表</th><th>最新日期</th><th>滞后天数</th><th>状态</th></tr></thead><tbody>${tables.map(x => { const fresh = x.fresh ?? x.status === 'fresh'; const latest = x.latest || x.latest_date; const delay = x.gap_days ?? x.delay_days; return `<tr><td>${esc(x.table)}</td><td>${esc(latest || '—')}</td><td>${delay ?? '—'}</td><td>${fresh ? tag('正常', 'green') : tag('滞后/缺失', 'amber')}</td></tr>`; }).join('') || '<tr><td colspan="4">暂无新鲜度数据</td></tr>'}</tbody></table></div></div>
    <div class="grid grid-5 section">${metric('平均质量分', overview.avg_quality_score == null ? '—' : Number(overview.avg_quality_score).toFixed(1), '实时多源质量日志', 'green')}${metric('总股票数', overview.total_stocks || 0, '最新实时快照', 'blue')}${metric('多源验证', overview.multi_source_validated || 0, '来源数大于 1', 'blue')}${metric('已修正', overview.action_stats?.correct || 0, '质量日志', 'amber')}${metric('待审核', overview.pending_reviews || 0, '需人工确认', 'red')}</div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>置信度分布</h3><span>实时股票数据</span></div>${[['高置信',confidence.high,'green'],['中置信',confidence.medium,'amber'],['低置信',confidence.low,'red'],['争议',confidence.disputed,'blue']].map(x => `<div class="detail"><div class="section-title"><b>${x[0]}</b><strong>${x[1] || 0}</strong></div><div class="bar"><i class="${x[2] === 'red' ? 'invalid' : ''}" style="width:${Math.min(100, Number(x[1] || 0) / Math.max(1, Number(overview.total_stocks || 1)) * 100)}%"></i></div></div>`).join('')}</div><div class="card"><div class="section-title"><h3>数据源可靠性评分</h3><span>近 7 日</span></div>${sources.slice(0, 12).map(s => `<div class="detail"><div class="section-title"><b>${esc(s.source)}</b><strong>${Number(s.avg_score || 0).toFixed(1)}</strong></div><div class="bar"><i style="width:${Math.min(100, Number(s.avg_score || 0) / maxScore * 100)}%"></i></div><div class="metric-note">样本 ${s.total_count || 0} · 异常率 ${Number(s.outlier_rate || 0).toFixed(2)}%</div></div>`).join('') || '<div class="muted-box">暂无数据源评分</div>'}</div></div>
    <div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>审核队列</h3><span>${reviews.count || 0} 条 · 仅展示</span></div><div class="table-wrap"><table><thead><tr><th>股票</th><th>指标</th><th>原因</th><th>时间</th></tr></thead><tbody>${(reviews.items || []).slice(0, 15).map(x => `<tr><td><b>${esc(x.name || '—')}</b><div class="stock-code">${esc(x.ts_code || '')}</div></td><td>${esc(x.indicator || '—')}</td><td>${esc(x.reason || '—')}</td><td>${esc(x.created_at || '—')}</td></tr>`).join('') || '<tr><td colspan="4">暂无待审核数据</td></tr>'}</tbody></table></div></div><div class="card"><div class="section-title"><h3>异常数据</h3><span>${anomalies.length} 条</span></div><div class="table-wrap"><table><thead><tr><th>股票</th><th>主力净流</th><th>偏差</th><th>置信度</th></tr></thead><tbody>${anomalies.slice(0, 15).map(x => `<tr><td><b>${esc(x.name || '—')}</b><div class="stock-code">${esc(x.ts_code || '')}</div></td><td>${x.main_force_inflow == null ? '—' : Number(x.main_force_inflow / 10000).toFixed(2) + '亿'}</td><td>${x.deviation_pct == null ? '—' : '偏差 ' + Number(x.deviation_pct).toFixed(1) + '%'}</td><td>${tag(x.confidence === 'disputed' ? '争议' : '低置信', x.confidence === 'disputed' ? 'blue' : 'red')}</td></tr>`).join('') || '<tr><td colspan="4">暂无异常数据</td></tr>'}</tbody></table></div></div></div>`;
  document.getElementById('reloadQuality').onclick = () => loadPage('collection');
}

async function loadPage(page) { state.page = page; const globalPage = ['system', 'quality', 'collection'].includes(page); document.querySelector('.app-shell')?.classList.toggle('global-page', globalPage); document.querySelectorAll('.nav-tab').forEach(tab => tab.classList.toggle('active', !globalPage && tab.dataset.page === page)); document.querySelectorAll('.top-system').forEach(tab => tab.classList.toggle('active', tab.dataset.page === page)); loading(); try { if (page === 'overview') { if (!state.dashboard) await loadBase(); renderOverview(); } else if (page === 'sectors') await renderSectors(); else if (page === 'candidates') await renderCandidates(); else if (page === 'yuzi') await renderYuzi(); else if (page === 'actions') await renderActions(); else if (page === 'watchlist') await renderWatchlist(); else if (page === 'holdings') await renderHoldings(); else if (page === 'analysis') await renderAnalysis(); else if (page === 'validation') await renderValidation(); else if (page === 'system') await renderSystem(); else if (page === 'quality') await renderQuality(); else if (page === 'collection') await renderCollection(); } catch (e) { errorBox(e); } }
document.querySelectorAll('.nav-tab').forEach(tab => tab.addEventListener('click', () => loadPage(tab.dataset.page)));
document.querySelectorAll('.top-system').forEach(button => button.addEventListener('click', () => loadPage(button.dataset.page)));
document.querySelectorAll('.market-tab:not([disabled])').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('.market-tab').forEach(tab => tab.classList.toggle('active', tab === button));
  if (button.dataset.market === 'cn') loadPage('overview');
}));

// Factor governance view: the original pages remain available, but the
// research and system pages now expose lifecycle status explicitly.
const factorStatusLabels = { candidate: '候选', observation: '观察', production: '生产', suspended: '停用', retired: '淘汰' };

async function renderValidation() {
  app.innerHTML = `<div class="page-head"><div><h2>因子验证中心</h2><p>验证结果先进入生命周期评估；20日用于快速观察，120日用于生产准入评估。</p></div><div class="actions"><label class="muted">验证窗口 <select id="validationDays"><option value="20">20日快速观察</option><option value="60">60日阶段观察</option><option value="120">120日生产准入</option><option value="240">240日长期验证</option></select></label><button class="button primary" id="runValidation">运行验证</button></div></div><div id="validationBody" class="card"><div class="loading">选择窗口后运行，长窗口可能需要几分钟…</div></div>`;
  document.getElementById('runValidation').onclick = async () => {
    document.getElementById('validationBody').innerHTML = '<div class="loading">正在严格按信号日期截断历史并计算 IC、Rank IC、ICIR、分层收益…</div>';
    try {
      const days = document.getElementById('validationDays')?.value || '20';
      const data = await api(`/api/v2/validation?days=${days}&limit=300&persist=true`);
      const rows = (data.rows || []).sort((a, b) => Math.abs(b.rank_ic || 0) - Math.abs(a.rank_ic || 0));
      const lifecycle = await api('/api/v2/factor-lifecycle?limit=500');
      const summary = lifecycle.factor_status_summary || {};
      document.getElementById('validationBody').innerHTML = `<div class="notice"><strong>研究样本</strong>有效信号日 ${data.research_days} · 股票 ${data.research_universe_count} · 前瞻样本 ${data.sample_count} · 生产准入要求至少120个有效信号日。</div><div class="state-grid section">${Object.keys(factorStatusLabels).map(key => `<div class="state-box"><strong>${summary[key] || 0}</strong><span>${factorStatusLabels[key]}</span></div>`).join('')}</div><div class="section"><div class="table-wrap"><table><thead><tr><th>因子</th><th>样本</th><th>IC</th><th>Rank IC</th><th>ICIR</th><th>缺失率</th><th>单调性</th><th>扣成本收益</th><th>建议</th></tr></thead><tbody>${rows.map(row => `<tr><td><b>${esc(row.factor_name)}</b></td><td>${row.sample_count}</td><td>${row.ic == null ? '—' : Number(row.ic).toFixed(3)}</td><td>${row.rank_ic == null ? '—' : Number(row.rank_ic).toFixed(3)}</td><td>${row.icir == null ? '—' : Number(row.icir).toFixed(2)}</td><td>${pct(row.missing_rate)}</td><td>${row.monotonicity == null ? '—' : pct(row.monotonicity)}</td><td>${pct(row.cost_adjusted_return)}</td><td>${tag(factorStatusLabels[row.recommended_status] || row.recommended_status, row.recommended_status === 'production' ? 'green' : row.recommended_status === 'candidate' ? '' : 'amber')}</td></tr>`).join('')}</tbody></table></div></div><div class="section notice"><strong>生命周期已写入数据库</strong>本次保存 ${data.saved_rows || 0} 条验证/结果记录，更新 ${data.lifecycle_updated || 0} 个因子状态；停用和淘汰不会被自动复活。</div>`;
    } catch (e) {
      document.getElementById('validationBody').innerHTML = `<div class="notice danger">${esc(e.message)}</div>`;
    }
  };
}

async function renderSystem() {
  const [health, registry, config] = await Promise.all([api('/api/v2/health'), api('/api/v2/registry'), api('/api/v2/config')]);
  const summary = health.factor_status_summary || {};
  const summaryText = Object.entries(factorStatusLabels).map(([key, label]) => `${label} ${summary[key] || 0}`).join(' · ');
  app.innerHTML = `<div class="page-head"><div><h2>系统状态</h2><p>区分“系统可运行”和“因子有证据”，不把已实现公式直接伪装成生产因子。</p></div><button class="button" id="saveSnapshot">保存本日快照</button></div><div class="grid grid-4"><div class="card"><div class="metric-label">服务状态</div><div class="metric-value positive">${esc(health.status)}</div><div class="metric-note">两个端口均由新 V2 提供</div></div><div class="card"><div class="metric-label">因子目录</div><div class="metric-value">${health.factor_catalog_count || registry.factor_count}</div><div class="metric-note">${esc(summaryText)}</div></div><div class="card"><div class="metric-label">正式生产因子</div><div class="metric-value">${health.production_factor_count || 0}</div><div class="metric-note">${health.production_ready ? '生产因子评分' : '观察因子研究评分'}</div></div><div class="card"><div class="metric-label">股票池</div><div class="metric-value">${health.eligible_universe}</div><div class="metric-note">最近完成交易日：${esc(health.trade_date || '—')}</div></div></div><div class="grid grid-2 section"><div class="card"><div class="section-title"><h3>数据契约</h3><span>只读接入旧库</span></div><div class="detail"><b>行情</b><div class="metric-note">日线行情表 · 日期截断 · OHLCV</div></div><div class="detail section"><b>股票元数据</b><div class="metric-note">股票流数据 · 中文名称/行业 · ST 过滤</div></div><div class="detail section"><b>板块资金</b><div class="metric-note">板块资金表 · 没有数据时明确显示缺失</div></div></div><div class="card"><div class="section-title"><h3>交易保护</h3><span>${config.enabled ? '已打开' : '关闭'}</span></div><div class="notice warn"><strong>外部下单：${config.enabled ? '配置已打开' : '关闭'}</strong>新程序默认 V2_TRADING_ENABLED=false；买卖必须预览、确认、密钥三重条件。</div><div class="detail section"><b>评分状态</b><div class="metric-note">${health.production_ready ? '生产因子评分' : '观察因子研究评分，禁止正式触发买入'}</div></div></div></div><div class="card section"><div class="section-title"><h3>因子目录与准入状态</h3><span>${registry.factor_count} 个</span></div><div class="table-wrap"><table><thead><tr><th>因子</th><th>分类</th><th>来源</th><th>周期</th><th>方向</th><th>状态</th><th>是否参与研究评分</th></tr></thead><tbody>${registry.factors.map(item => `<tr><td><b>${esc(item.label)}</b><div class="stock-code">${esc(item.factor_name)}</div></td><td>${esc(item.category)}</td><td>${esc(item.source || '—')}</td><td>${item.period || '—'}</td><td>${item.direction > 0 ? '越高越好' : '越低越好'}</td><td>${tag(factorStatusLabels[item.status] || item.status, item.status === 'production' ? 'green' : item.status === 'retired' ? '' : 'amber')}</td><td>${item.enabled_in_score ? '是' : '否'}</td></tr>`).join('')}</tbody></table></div></div>`;
  document.getElementById('saveSnapshot').onclick = async () => { try { await api('/api/v2/snapshot/persist', { method: 'POST' }); alert('已保存本日因子与信号快照'); } catch (e) { alert(e.message); } };
}

const renderValidationWithChineseFactorLabels = renderValidation;
renderValidation = async function() {
  await renderValidationWithChineseFactorLabels();
  const head = app.querySelector('.page-head .actions') || app.querySelector('.page-head');
  if (head && !document.getElementById('persistResearchSnapshot')) {
    const researchButton = document.createElement('button');
    researchButton.className = 'button';
    researchButton.id = 'persistResearchSnapshot';
    researchButton.textContent = '保存全因子研究值';
    researchButton.onclick = async () => {
      researchButton.disabled = true;
      try {
        const result = await api('/api/v2/research/snapshot/persist', { method: 'POST' });
        alert(`已保存 ${result.factor_values} 条全因子值；候选因子仍不参与评分`);
      } catch (e) {
        alert(e.message);
      } finally {
        researchButton.disabled = false;
      }
    };
    head.appendChild(researchButton);
  }
  const runButton = document.getElementById('runValidation');
  if (!runButton || !runButton.onclick) return;
  const originalAction = runButton.onclick;
  runButton.onclick = async function() {
    await originalAction();
    const registryData = await api('/api/v2/registry');
    const factorLabels = Object.fromEntries((registryData.factors || []).map(item => [item.factor_name, item.label]));
    const tables = app.querySelectorAll('table');
    const validationTable = tables[tables.length - 1];
    if (validationTable && validationTable.tBodies[0]) {
      [...validationTable.tBodies[0].rows].forEach(row => {
        const key = row.cells[0]?.querySelector('.stock-code')?.textContent?.trim() || row.cells[0]?.textContent?.trim();
        const label = factorLabels[key];
        const title = row.cells[0]?.querySelector('b');
        if (label && title) title.textContent = label;
      });
    }
  };
};

const renderSystemWithChineseCategories = renderSystem;
renderSystem = async function() {
  await renderSystemWithChineseCategories();
  const pageHead = app.querySelector('.page-head');
  if (pageHead) {
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.innerHTML = '<button class="button primary" id="runSystemCheck">一键系统检查</button>';
    pageHead.appendChild(actions);
    const checkBox = document.createElement('div');
    checkBox.id = 'systemCheckResult';
    checkBox.className = 'card section';
    checkBox.innerHTML = '<div class="muted-box">点击“一键系统检查”，检查数据库、采集、服务、测试和代码状态。</div>';
    app.insertBefore(checkBox, app.firstChild.nextSibling);
    document.getElementById('runSystemCheck').onclick = async () => {
      const button = document.getElementById('runSystemCheck');
      button.disabled = true;
      checkBox.innerHTML = '<div class="loading">正在执行只读体检，测试项目可能需要几十秒…</div>';
      try {
        const result = await api('/api/v2/system/check', {method: 'POST'});
        const label = result.status === 'ok' ? '全部正常' : result.status === 'warning' ? '有警告' : '有失败项';
        const tone = result.status === 'ok' ? 'green' : result.status === 'warning' ? 'amber' : 'red';
        checkBox.innerHTML = `<div class="section-title"><h3>系统检查：${tag(label, tone)}</h3><span>${esc(result.checked_at || '')}</span></div><div class="grid grid-3 section"><div class="detail"><b>检查项</b><div class="metric-value">${result.summary.total}</div></div><div class="detail"><b>警告</b><div class="metric-value">${result.summary.warnings}</div></div><div class="detail"><b>失败</b><div class="metric-value">${result.summary.errors}</div></div></div><div class="table-wrap"><table><thead><tr><th>检查项</th><th>状态</th><th>结果</th></tr></thead><tbody>${(result.checks || []).map(item => `<tr><td><b>${esc(item.name)}</b></td><td>${tag(item.status === 'ok' ? '正常' : item.status === 'warning' ? '警告' : '失败', item.status === 'ok' ? 'green' : item.status === 'warning' ? 'amber' : 'red')}</td><td>${esc(item.detail)}</td></tr>`).join('')}</tbody></table></div>`;
      } catch (e) { checkBox.innerHTML = `<div class="notice danger">一键检查失败：${esc(e.message)}</div>`; }
      finally { button.disabled = false; }
    };
  }
  const collection = await api('/api/v2/collection/status');
  const freshnessRows = (collection.freshness.tables || []).slice(0, 12).map(item => `<tr><td>${esc(item.table)}</td><td>${esc(item.latest || '无')}</td><td>${item.gap_days == null ? '—' : item.gap_days}</td><td>${item.fresh ? tag('正常', 'green') : tag('滞后/缺失', 'amber')}</td></tr>`).join('');
  const collectionCard = document.createElement('div');
  collectionCard.className = 'card section';
  collectionCard.innerHTML = `<div class="section-title"><h3>数据采集与新鲜度</h3><span>${esc(collection.collector_owner || '旧采集器')}</span></div><div class="notice"><strong>单一采集执行者</strong>${esc(collection.message || '')}<br>9001 只读状态，不会重复拉取或重复写库。</div><div class="table-wrap"><table><thead><tr><th>数据表</th><th>最新日期</th><th>滞后天数</th><th>状态</th></tr></thead><tbody>${freshnessRows || '<tr><td colspan="4">暂无采集新鲜度数据</td></tr>'}</tbody></table></div>`;
  app.appendChild(collectionCard);
  const quality = await api('/api/v2/system/quality');
  const qualityCard = document.createElement('div');
  qualityCard.className = 'card section';
  const qualityRows = (quality.sources || []).slice(0, 10).map(item => `<tr><td>${esc(item.source || '—')}</td><td>${item.total_count ?? '—'}</td><td>${item.score == null ? '—' : Number(item.score).toFixed(1)}</td><td>${item.outlier_rate == null ? '—' : Number(item.outlier_rate).toFixed(2) + '%'}</td></tr>`).join('');
  const anomalyRows = (quality.anomalies || []).slice(0, 5).map(item => `<tr><td>${esc(item.name || item.ts_code || '—')}</td><td>${esc(item.indicator || '多源数据')}</td><td>${item.deviation_pct == null ? '—' : Number(item.deviation_pct).toFixed(1) + '%'}</td><td>${item.is_corrected ? tag('已修正', 'green') : tag('待确认', 'amber')}</td></tr>`).join('');
  qualityCard.innerHTML = `<div class="section-title"><h3>数据质量与异常</h3><span>交易日 ${esc(quality.trade_date || '—')}</span></div><div class="grid grid-3"><div class="detail"><b>数据源</b><div class="metric-value">${quality.source_count || 0}</div><div class="metric-note">已接入质量统计</div></div><div class="detail"><b>异常记录</b><div class="metric-value">${quality.anomaly_count || 0}</div><div class="metric-note">展示前 10 条</div></div><div class="detail"><b>待审核</b><div class="metric-value">${quality.pending_review_count || 0}</div><div class="metric-note">需要人工确认</div></div></div><div class="grid grid-2 section"><div><div class="section-title"><h4>数据源质量</h4><span>不参与 V2 评分</span></div><div class="table-wrap"><table><thead><tr><th>来源</th><th>样本</th><th>质量分</th><th>异常率</th></tr></thead><tbody>${qualityRows || '<tr><td colspan="4">暂无质量数据</td></tr>'}</tbody></table></div></div><div><div class="section-title"><h4>异常样本</h4><span>仅提示，不自动改数据</span></div><div class="table-wrap"><table><thead><tr><th>股票</th><th>指标</th><th>偏差</th><th>处理</th></tr></thead><tbody>${anomalyRows || '<tr><td colspan="4">暂无异常</td></tr>'}</tbody></table></div></div></div>`;
  app.appendChild(qualityCard);
  const serviceStatus = app.querySelector('.grid-4 .metric-value.positive');
  if (serviceStatus && serviceStatus.textContent.trim() === 'ok') serviceStatus.textContent = '正常';
  const registryData = await api('/api/v2/registry');
  const tables = app.querySelectorAll('table');
  const factorTable = tables[tables.length - 1];
  if (factorTable && factorTable.tBodies[0]) {
    const header = factorTable.tHead?.rows[0];
    if (header) {
      const admissionHeader = document.createElement('th');
      admissionHeader.textContent = '允许生产';
      header.appendChild(admissionHeader);
    }
    [...factorTable.tBodies[0].rows].forEach((row, index) => {
      const item = registryData.factors[index];
      if (item && row.cells[1]) row.cells[1].textContent = item.category_label || item.category;
      if (item) {
        const admissionCell = row.insertCell(-1);
        admissionCell.textContent = item.allow_production ? '是' : '否';
      }
    });
  }
};

function applyTheme(isDark) {
  document.body.classList.toggle('theme-dark', isDark);
  const toggle = document.getElementById('themeToggle');
  if (!toggle) return;
  toggle.textContent = isDark ? '☀️ 白天' : '🌙 黑夜';
  toggle.setAttribute('aria-pressed', String(isDark));
  toggle.setAttribute('title', isDark ? '切换到白天模式' : '切换到黑夜模式');
}

function initTheme() {
  let isDark = false;
  try { isDark = localStorage.getItem('airobot-v2-theme') === 'dark'; } catch (_) {}
  applyTheme(isDark);
  const toggle = document.getElementById('themeToggle');
  if (!toggle) return;
  toggle.addEventListener('click', () => {
    const next = !document.body.classList.contains('theme-dark');
    applyTheme(next);
    try { localStorage.setItem('airobot-v2-theme', next ? 'dark' : 'light'); } catch (_) {}
  });
}

initTheme();
loadPage('overview');
