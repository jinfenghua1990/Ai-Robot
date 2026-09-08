import { useState, useEffect, useCallback, useRef } from "react";
import { Link } from "react-router-dom";
import { TrendingUp, FileText, Newspaper, Rss, RefreshCw, Loader2, ExternalLink, AlertCircle, Sparkles, Lightbulb, Star } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { PageHeader } from "@/components/ui/PageHeader";
import { GlassCard } from "@/components/ui/GlassCard";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { SaveNoteButton } from "@/components/ui/SaveNoteButton";
import { api, ApiError, type RadarData, type Industry, type Announcement, type NewsItem } from "@/lib/api";

import { hasLlm, chatStream } from "@/lib/llm";
import { cn } from "@/lib/utils";

const TABS = [
  { key: "events", label: "事件概率", icon: TrendingUp, integrated: false, desc: "全球宏观预期概率（公开数据、免登录只读），后续接入" },
  { key: "filings", label: "A股公告", icon: FileText, integrated: true, desc: "汇总关注列表里各个股的近期公告（东财公开披露）" },
  { key: "news", label: "公开新闻", icon: Newspaper, integrated: true, desc: "汇总关注列表里各个股的近期新闻（公开源）" },
  { key: "investment-news", label: "Investment News", icon: Rss, integrated: true, desc: "12 赛道全球公开 RSS 资讯（集成自 investment-news 仓库）" },
];

interface Digest { loading?: boolean; text?: string; err?: string; needKey?: boolean }

async function loadSharedWatch(): Promise<string[]> {
  try {
    const resp = await fetch("/api/shared/watchlist/codes");
    if (!resp.ok) return [];
    const data = await resp.json();
    return Array.isArray(data?.codes) ? data.codes.filter((c: string) => /^\d{6}$/.test(c)) : [];
  } catch {
    return [];
  }
}

// 时间解析：兼容中文日期（2026年07月15日）、ISO（2026-07-15T10:30:00）、常见格式
const parseTs = (s: string): number => {
  const raw = (s || "").trim();
  if (!raw) return 0;
  // 尝试直接解析
  let t = Date.parse(raw);
  if (!Number.isNaN(t)) return t;
  // 中文日期：2026年07月15日 10:30
  const cn = raw.match(/(\d{4})年(\d{1,2})月(\d{1,2})日(?:\s+(\d{1,2}):(\d{1,2})(?::(\d{1,2}))?)?/);
  if (cn) {
    const [, y, mo, d, h = "0", mi = "0", se = "0"] = cn;
    t = Date.parse(`${y}-${mo.padStart(2, "0")}-${d.padStart(2, "0")}T${h.padStart(2, "0")}:${mi.padStart(2, "0")}:${se.padStart(2, "0")}`);
    if (!Number.isNaN(t)) return t;
  }
  // 空格分隔 → T
  t = Date.parse(raw.replace(" ", "T"));
  return Number.isNaN(t) ? 0 : t;
};

function InvestmentNewsPanel() {
  const [data, setData] = useState<RadarData | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [active, setActive] = useState("ai");
  const [refreshing, setRefreshing] = useState(false);
  const [digests, setDigests] = useState<Record<string, Digest>>({});
  const [bulk, setBulk] = useState<{ running: boolean; done: number; total: number }>({ running: false, done: 0, total: 0 });
  const [autoRun, setAutoRun] = useState(true);
  const [intervalMin, setIntervalMin] = useState(30);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    api.radar().then(setData).catch((e) => setErr(e instanceof ApiError ? e.message : "加载失败"));
  }, []);

  // 自动运行：挂载即跑一次；autoRun 开启时按 intervalMin 定时循环（抓取 + 提炼）。
  // 提炼依赖前端 LLM（用户自己的 AI），故必须在前端执行，无法纯后端定时。
  useEffect(() => {
    if (!autoRun) return;
    void runPipeline();
    const id = setInterval(() => { void runPipeline(); }, intervalMin * 60000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoRun, intervalMin]);

  const refresh = async () => {
    setRefreshing(true); setErr(null);
    try { setData(await api.radarRefresh()); }
    catch (e) { setErr(e instanceof ApiError ? e.message : "刷新失败"); }
    finally { setRefreshing(false); }
  };

  // 自动运行管线：先抓取最新资讯，若有 AI 接入则自动提炼全部赛道要点。
  const runPipeline = async () => {
    await refresh();
    if (!hasLlm()) return;
    let inds: Industry[] = [];
    try {
      const d = await api.radar();
      inds = d?.industries || [];
    } catch { return; }
    const targets = inds.filter((i) => i.items.length > 0);
    if (!targets.length) return;
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    setBulk({ running: true, done: 0, total: targets.length });
    for (const ind of targets) {
      if (ac.signal.aborted) break;
      await genDigest(ind, ac.signal);
      setBulk((b) => ({ ...b, done: b.done + 1 }));
    }
    setBulk((b) => ({ ...b, running: false }));
  };

  const industries: Industry[] = data?.industries || [];
  const cur = industries.find((i) => i.key === active) || industries[0];
  const hasData = !!data?.generated_at;

  const genDigest = async (ind: Industry, signal?: AbortSignal) => {
    if (!hasLlm()) { setDigests((d) => ({ ...d, [ind.key]: { needKey: true } })); return; }
    setDigests((d) => ({ ...d, [ind.key]: { loading: true } }));
    const ctx = ind.items.slice(0, 25).map((it) => `[${it.time}] ${it.source}｜${it.zh || it.title}`).join("\n");
    const prompt =
      `以下是「${ind.name}」赛道近期资讯。请提炼「今日要点」3-5 条：每条一句话（≤40 字），` +
      `只客观陈述重要事件 / 趋势，不推荐标的、不预测涨跌、不构成建议。直接用「- 」列点，不要多余前后缀。\n\n${ctx}`;
    try {
      let acc = "";
      await chatStream([{ role: "user", content: prompt }], `${ind.name}赛道资讯`, {
        onDelta: (t) => {
          if (signal?.aborted) return;
          acc += t;
          setDigests((d) => ({ ...d, [ind.key]: { text: acc } }));
        },
      });
      if (signal?.aborted) return;
    } catch (e) {
      if (signal?.aborted) return;
      setDigests((d) => ({ ...d, [ind.key]: { err: e instanceof ApiError ? e.message : "生成失败" } }));
    }
  };

  // 一键提炼全部赛道要点（串行，带进度 + AbortController 可取消）
  const genAll = async () => {
    if (!hasLlm()) { if (cur) setDigests((d) => ({ ...d, [cur.key]: { needKey: true } })); return; }
    // 取消上一次
    abortRef.current?.abort();
    const ac = new AbortController();
    abortRef.current = ac;
    const targets = industries.filter((i) => i.items.length > 0);
    setBulk({ running: true, done: 0, total: targets.length });
    for (const ind of targets) {
      if (ac.signal.aborted) break;
      await genDigest(ind, ac.signal);
      setBulk((b) => ({ ...b, done: b.done + 1 }));
    }
    setBulk((b) => ({ ...b, running: false }));
  };

  const cancelGenAll = () => {
    abortRef.current?.abort();
    setBulk((b) => ({ ...b, running: false }));
  };

  const dg = cur ? digests[cur.key] : undefined;

  return (
    <div className="animate-fade-in">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-muted-foreground">
            {hasData ? `${data!.stats.total_sources} 个公开源 · 近 ${data!.recent_days} 天 · 更新于 ${data!.generated_at}` : "12 赛道 · 108 个公开源"}
          </span>
          <label className="inline-flex items-center gap-1.5 text-xs text-muted-foreground cursor-pointer select-none">
            <input type="checkbox" checked={autoRun} onChange={(e) => setAutoRun(e.target.checked)} className="accent-primary h-3.5 w-3.5" />
            自动运行
          </label>
          <select
            value={intervalMin}
            onChange={(e) => setIntervalMin(Number(e.target.value))}
            disabled={!autoRun}
            className="rounded-lg border border-border bg-transparent px-1.5 py-1 text-xs text-muted-foreground disabled:opacity-40"
          >
            <option value={15}>每 15 分钟</option>
            <option value={30}>每 30 分钟</option>
            <option value={60}>每 60 分钟</option>
          </select>
          <button onClick={() => void runPipeline()} disabled={refreshing || bulk.running}
            className="inline-flex items-center gap-1.5 rounded-lg border border-primary/40 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/10 disabled:opacity-50">
            {bulk.running ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            立即运行
          </button>
        </div>
        <div className="flex items-center gap-2">
          {hasData && (
            <>
              {bulk.running ? (
                <button onClick={cancelGenAll}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-destructive/30 px-3 py-1.5 text-sm text-destructive hover:bg-destructive/5">
                  <Loader2 className="h-4 w-4 animate-spin" /> 取消提炼
                </button>
              ) : (
                <button onClick={genAll} disabled={refreshing}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary shadow-glow hover:bg-primary/25 disabled:opacity-50">
                  <Sparkles className="h-4 w-4" />
                  一键提炼全部要点
                </button>
              )}
              {bulk.running && <span className="text-xs text-muted-foreground">{bulk.done}/{bulk.total}</span>}
            </>
          )}
          <button onClick={refresh} disabled={refreshing || bulk.running}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
            {refreshing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            {refreshing ? "抓取中…" : "刷新"}
          </button>
        </div>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {!hasData && !err ? (
        <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
          还没有抓取资讯，点上方<b className="text-foreground">「刷新」</b>拉取（约 20-40 秒）。
        </div>
      ) : (
        <>
          {/* 赛道筛选 —— 暖橙边框 pill */}
          <div className="mb-4 flex flex-wrap gap-2">
            {industries.map((ind) => (
              <button key={ind.key} onClick={() => setActive(ind.key)}
                className={cn(
                  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-all duration-200 hover:scale-105",
                  active === ind.key
                    ? "border-primary bg-primary/15 font-medium text-primary shadow-glow scale-105"
                    : "border-primary/25 text-muted-foreground hover:border-primary/60 hover:text-foreground",
                )}>
                <span className="h-2 w-2 rounded-full" style={{ background: ind.accent }} />
                {ind.name}<span className="text-muted-foreground/50">{ind.items.length}</span>
              </button>
            ))}
          </div>

          {cur && (
            <>
              {/* 今日要点总结框（暖橙框） */}
              <div className="mb-4 rounded-xl border border-primary/30 bg-primary/5 p-4 animate-fade-in">
                <div className="mb-2 flex items-center justify-between">
                  <span className="flex items-center gap-1.5 text-sm font-semibold text-primary">
                    <Lightbulb className="h-4 w-4" /> 今日要点 · {cur.name}
                  </span>
                  {(dg?.text || dg?.err || dg?.needKey) && (
                    <button onClick={() => genDigest(cur)} className="text-xs text-muted-foreground hover:text-primary">重新提炼</button>
                  )}
                </div>
                {dg?.loading ? (
                  <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-3.5 w-3.5 animate-spin" /> AI 正在读这个赛道的资讯…</p>
                ) : dg?.text ? (
                  <>
                    <div className="prose prose-sm prose-invert max-w-none text-foreground"><ReactMarkdown remarkPlugins={[remarkGfm]}>{dg.text}</ReactMarkdown></div>
                    <div className="mt-2"><SaveNoteButton kind="今日要点" title={`${cur.name} 今日要点`} content={dg.text} /></div>
                  </>
                ) : dg?.needKey ? (
                  <p className="text-sm text-muted-foreground">还没接入 AI。<Link to="/settings" className="text-primary">先接入你的 AI</Link>，即可一键提炼本赛道今日要点。</p>
                ) : dg?.err ? (
                  <p className="text-sm text-destructive">{dg.err}</p>
                ) : (
                  <button onClick={() => genDigest(cur)}
                    className="inline-flex items-center gap-1.5 rounded-lg bg-primary/15 px-3 py-1.5 text-sm font-medium text-primary hover:bg-primary/25">
                    <Sparkles className="h-4 w-4" /> 让 AI 提炼今日要点
                  </button>
                )}
              </div>

              {/* 资讯列表 —— 卡片化 + 逐项入场动画（切赛道时重放），用 url+title 作稳定 key */}
              <div key={active} className="space-y-1.5 animate-fade-in">
                {cur.items.length === 0 ? (
                  <p className="py-6 text-center text-sm text-muted-foreground/60">近 {data!.recent_days} 天该赛道暂无更新</p>
                ) : (
                  cur.items.map((it) => (
                    <a key={`${it.url}-${it.title}`} href={it.url} target="_blank" rel="noreferrer"
                      className="group flex items-baseline gap-3 rounded-lg px-3 -mx-3 py-1.5 text-sm transition-all duration-200 hover:bg-primary/[0.07] hover:shadow-glow animate-fade-up"
                      style={{ animationDelay: `${Math.min(cur.items.indexOf(it), 20) * 45}ms` }}>
                      <span className="w-24 shrink-0 font-mono text-xs text-muted-foreground/70">{it.time}</span>
                      <span className="w-20 shrink-0 truncate text-xs text-muted-foreground">{it.source}</span>
                      <span className="flex-1 group-hover:text-primary transition-colors duration-200">{it.zh || it.title}</span>
                      <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60 transition-colors duration-200" />
                    </a>
                  ))
                )}
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}

// 关注股公告 / 新闻聚合：从本地关注列表取代码，复用批量接口一次拉取、按时间倒序合并。
// 只做公开信息聚合，标的均为用户自己关注列表里的，不预置、不推荐。
interface FeedRow { code: string; name: string; when: string; title: string; meta?: string; url?: string }
const MAX_ROWS = 60;

function WatchlistFeed({ kind }: { kind: "filings" | "news" }) {
  const [codes, setCodes] = useState<string[]>([]);
  const [rows, setRows] = useState<FeedRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [depNote, setDepNote] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const load = useCallback(async (cs: string[]) => {
    if (!cs.length) { setRows([]); return; }
    setLoading(true); setErr(null); setDepNote(null);
    try {
      // 股名（一次批量），失败则退回显示代码
      const nameOf: Record<string, string> = {};
      try {
        const quotes = await api.quote(cs.join(","));
        for (const c of cs) if (quotes[c]?.name) nameOf[c] = quotes[c].name;
      } catch { /* 忽略：无股名不影响公告/新闻 */ }

      const out: FeedRow[] = [];
      if (kind === "filings") {
        // 批量拉取公告，一次请求替代 N 个并发
        try {
          const batchData = await api.announcementsBatch(cs.join(","));
          for (const [c, anns] of Object.entries(batchData)) {
            for (const x of anns) {
              out.push({ code: c, name: nameOf[c] || c, when: x.date, title: x.title.replace(/^[^:：]*[:：]/, ""), meta: x.type, url: x.url });
            }
          }
        } catch (e) {
          // 批量接口失败时降级为逐个请求
          if (e instanceof ApiError && e.status === 404) {
            const res = await Promise.all(
              cs.map((c) => api.announcements(c).then((a) => ({ c, a })).catch(() => ({ c, a: [] as Announcement[] }))),
            );
            for (const { c, a } of res)
              for (const x of a)
                out.push({ code: c, name: nameOf[c] || c, when: x.date, title: x.title.replace(/^[^:：]*[:：]/, ""), meta: x.type, url: x.url });
          } else {
            throw e;
          }
        }
      } else {
        let dep: string | null = null;
        try {
          // 批量拉取新闻
          const batchData = await api.newsBatch(cs.join(","));
          for (const [c, news] of Object.entries(batchData)) {
            for (const x of news) {
              out.push({ code: c, name: nameOf[c] || c, when: x.发布时间 || "", title: x.新闻标题 || "", url: x.新闻链接 });
            }
          }
        } catch (e) {
          // 降级为逐个请求
          if (e instanceof ApiError && (e.status === 404 || e.status === 501)) {
            const res = await Promise.all(
              cs.map((c) =>
                api.news(c).then((n) => ({ c, n })).catch((e2) => {
                  if (e2 instanceof ApiError && e2.status === 501) dep = e2.message;
                  return { c, n: [] as NewsItem[] };
                }),
              ),
            );
            for (const { c, n } of res)
              for (const x of n)
                out.push({ code: c, name: nameOf[c] || c, when: x.发布时间 || "", title: x.新闻标题 || "", url: x.新闻链接 });
            if (dep && out.length === 0) setDepNote(dep);
          } else {
            throw e;
          }
        }
        if (depNote && out.length === 0) setDepNote(depNote);
      }
      // 按真实时间倒序
      out.sort((p, q) => parseTs(q.when) - parseTs(p.when));
      setRows(out.slice(0, MAX_ROWS));
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [kind]);

  useEffect(() => { loadSharedWatch().then(cs => { setCodes(cs); load(cs); }); }, [load]);

  const refresh = () => { setTick(t => t + 1); loadSharedWatch().then(cs => { setCodes(cs); load(cs); }); };

  if (!codes.length) {
    return (
      <div className="rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">
        还没有共享自选股。到顶部 <span className="text-primary">⭐ 自选股</span> 中添加（6 位代码），这里会汇总它们的{kind === "filings" ? "公告" : "新闻"}。
      </div>
    );
  }

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Star className="h-3.5 w-3.5 text-primary/70" /> 关注 {codes.length} 只 · 共 {rows.length} 条{kind === "filings" ? "公告" : "新闻"}（近期）
        </span>
        <button onClick={refresh} disabled={loading}
          className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50">
          {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {loading ? "拉取中…" : "刷新"}
        </button>
      </div>

      {err && (
        <div className="mb-3 flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <AlertCircle className="h-4 w-4 shrink-0" /> {err}
        </div>
      )}

      {depNote ? (
        <p className="py-6 text-center text-xs text-warning">{depNote}（安装后新闻即可用）</p>
      ) : loading && rows.length === 0 ? (
        <p className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> 正在汇总关注股的{kind === "filings" ? "公告" : "新闻"}…</p>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center text-sm text-muted-foreground/60">关注列表里的个股近期暂无{kind === "filings" ? "公告" : "新闻"}。</p>
      ) : (
        <div key={tick} className="space-y-1.5 animate-fade-in">
          {rows.map((r) => (
            <a key={`${r.code}-${r.url}-${r.title}`} href={r.url || undefined} target={r.url ? "_blank" : undefined} rel="noreferrer"
              className={cn("group flex items-baseline gap-3 rounded-lg px-3 -mx-3 py-1.5 text-sm transition-all duration-200 hover:bg-primary/[0.07] hover:shadow-glow animate-fade-up", r.url && "cursor-pointer")}
              style={{ animationDelay: `${Math.min(rows.indexOf(r), 20) * 45}ms` }}>
              <span className="w-20 shrink-0 font-mono text-xs text-muted-foreground/70">{(r.when || "").slice(kind === "filings" ? 0 : 5, kind === "filings" ? 10 : 16)}</span>
              <span className="w-16 shrink-0 truncate text-xs text-primary/90" title={r.code}>{r.name}</span>
              {kind === "filings" && r.meta && <span className="hidden w-20 shrink-0 truncate text-xs text-muted-foreground sm:block">{r.meta}</span>}
              <span className="flex-1 group-hover:text-primary">{r.title}</span>
              {r.url && <ExternalLink className="mt-0.5 h-3 w-3 shrink-0 text-muted-foreground/0 group-hover:text-primary/60" />}
            </a>
          ))}
        </div>
      )}
    </div>
  );
}

export function Intel() {
  const [tab, setTab] = useState("investment-news");
  const cur = TABS.find((t) => t.key === tab)!;

  return (
    <div>
      <PageHeader title="资讯雷达" subtitle="多来源资讯中心：AI 帮你跨源捞资讯、提炼要点" />

      <div className="mb-4 flex flex-wrap gap-2">
        {TABS.map(({ key, label, icon: Icon, integrated }) => (
          <button key={key} onClick={() => setTab(key)}
            className={cn("inline-flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm transition-colors",
              tab === key ? "bg-primary/15 font-medium text-primary shadow-glow" : "text-muted-foreground hover:bg-muted/50")}>
            <Icon className="h-4 w-4" /> {label}
            {integrated && <span className="rounded-full bg-primary/20 px-1.5 py-0.5 text-[10px] font-medium text-primary">集成</span>}
          </button>
        ))}
      </div>

      <GlassCard glow>
        <div className="mb-3 flex items-center gap-2">
          <cur.icon className="h-5 w-5 text-primary" />
          <h3 className="font-semibold">{cur.label}</h3>
          {cur.integrated && <span className="rounded-full bg-primary/15 px-2 py-0.5 text-[10px] text-primary">investment-news</span>}
        </div>
        {cur.key === "investment-news" ? (
          <InvestmentNewsPanel />
        ) : cur.key === "filings" ? (
          <WatchlistFeed kind="filings" />
        ) : cur.key === "news" ? (
          <WatchlistFeed kind="news" />
        ) : (
          <>
            <p className="text-sm text-muted-foreground">{cur.desc}</p>
            <div className="mt-4 rounded-lg border border-dashed border-border/70 p-8 text-center text-sm text-muted-foreground/70">该数据源规划中——可先用右侧「Investment News」看 12 赛道公开资讯，或用「A 股公告 / 公开新闻」看关注股动态。</div>
          </>
        )}
      </GlassCard>

      <p className="mt-3 text-[11px] text-muted-foreground/60">
        只做公开信息聚合、不做推荐、不预测涨跌。公告 / 新闻均来自你关注列表里个股的公开披露与公开源；赛道资讯已按合规词表过滤。今日要点由你自己配置的 AI 提炼。
      </p>
      <Disclaimer />
    </div>
  );
}
