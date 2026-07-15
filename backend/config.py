import os
from dotenv import load_dotenv
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg2://airobot@localhost:5432/airobot")
READ_ONLY_DB_URL = os.getenv("READ_ONLY_DB_URL", DATABASE_URL)
TUSHARE_TOKEN = os.getenv("TUSHARE_TOKEN", "")
API_PORT = int(os.getenv("API_PORT", "9000"))
API_READ_KEY = os.getenv("API_READ_KEY", "")
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:9000,http://127.0.0.1:9000").split(",") if o.strip()]
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("RATE_LIMIT_MAX_REQUESTS", "300"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))

# 国信证券接口
GS_API_KEY = os.getenv("GS_API_KEY", "")
GS_API_BASE_URL = os.getenv("GS_API_BASE_URL", "https://dgzt.guosen.com.cn/skills")

# Astock Data skill (data.quantgo.ai)
QGDATA_TOKEN = os.getenv("QGDATA_TOKEN", "")
QGDATA_BASE_URL = os.getenv("QGDATA_BASE_URL", "https://data.quantgo.ai")

# 东方财富妙想 Skills API
# MX_APIKEY: 妙想全量接口（资讯/选股/数据/自选股/模拟盘查询等）—— 第一套 key
MX_APIKEY = os.getenv("MX_APIKEY", "")
# MX_TRADING_APIKEY: 妙想自动化交易专用（买/卖/撤/资金/持仓）—— 第二套 key
# 若未单独配置则回退到 MX_APIKEY
MX_TRADING_APIKEY = os.getenv("MX_TRADING_APIKEY", "") or MX_APIKEY
MX_API_URL = os.getenv("MX_API_URL", "https://mkapi2.dfcfs.com/finskillshub")

# iTick 实时行情API
ITICK_TOKEN = os.getenv("ITICK_TOKEN", "")
ITICK_BASE_URL = os.getenv("ITICK_BASE_URL", "https://api.itick.org")

# 通达信 Hub（F10 财务/评级/机构 live 拉取，供研报中心 consumer 使用）
# 未配置 TDX_HUB_TOKEN 时 consumer 会优雅降级：F10 字段留空而非中断
TDX_HUB_URL = os.getenv("TDX_HUB_URL", "http://tdxhub.icfqs.com:7615/TQLEX")
TDX_HUB_TOKEN = os.getenv("TDX_HUB_TOKEN", "")

# 聚宽 JoinQuant jqdatasdk
JQDATA_ACCOUNT = os.getenv("JQDATA_ACCOUNT", "")
JQDATA_PASSWORD = os.getenv("JQDATA_PASSWORD", "")

# ============================================================
# 盘后研究采集（填补 stock_news_search / stock_data_query / ai_analysis_cache 空白）
# ============================================================
# 可选：AI 综合分析 LLM。留空则不调用 LLM，用妙想搜索内容作基线分析（model='mx-search-baseline'）
# 兼容 .env 中的 LLM_* 命名与旧 AI_LLM_* 命名，优先使用 AI_LLM_*，未配置则回退到 LLM_*
AI_LLM_API_KEY = os.getenv("AI_LLM_API_KEY") or os.getenv("LLM_API_KEY", "")
AI_LLM_BASE_URL = os.getenv("AI_LLM_BASE_URL") or os.getenv("LLM_BASE_URL", "https://api.openai.com/v1")
AI_LLM_MODEL = os.getenv("AI_LLM_MODEL") or os.getenv("LLM_MODEL", "gpt-4o-mini")
# 当日强势股纳入阈值（涨幅 %），默认 9（创业板 20% 涨停也覆盖）
RESEARCH_LIMIT_UP_PCT = float(os.getenv("RESEARCH_LIMIT_UP_PCT", "9.0"))
# 龙头生命周期纳入的活跃阶段
RESEARCH_ACTIVE_STAGES = [s.strip() for s in os.getenv("RESEARCH_ACTIVE_STAGES", "加速,主升,启动").split(",") if s.strip()]
# 研究采集节流（每只股票之间的间隔秒数，避免猛打妙想导致限流/连接挂死事件循环）
RESEARCH_THROTTLE = float(os.getenv("RESEARCH_THROTTLE", "1.0"))

# ============================================================
# 缓存 TTL 统一配置（秒）
# ============================================================
CACHE_TTL_QUOTE = int(os.getenv("CACHE_TTL_QUOTE", "30"))
CACHE_TTL_KLINE = int(os.getenv("CACHE_TTL_KLINE", "3600"))
CACHE_TTL_WATCHLIST = int(os.getenv("CACHE_TTL_WATCHLIST", "300"))
CACHE_TTL_LIFECYCLE = int(os.getenv("CACHE_TTL_LIFECYCLE", "300"))
CACHE_TTL_HEATMAP = int(os.getenv("CACHE_TTL_HEATMAP", "300"))
CACHE_TTL_CONCEPT = int(os.getenv("CACHE_TTL_CONCEPT", "300"))
CACHE_TTL_MX_SKILLS = int(os.getenv("CACHE_TTL_MX_SKILLS", "60"))
CACHE_TTL_MX_TRADING = int(os.getenv("CACHE_TTL_MX_TRADING", "300"))

# 缓存最大条目数
CACHE_MAX_QUOTE = int(os.getenv("CACHE_MAX_QUOTE", "500"))
CACHE_MAX_KLINE = int(os.getenv("CACHE_MAX_KLINE", "300"))
