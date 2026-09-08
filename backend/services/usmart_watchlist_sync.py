"""盈立(uSMART)自选股同步服务

数据流：
  本地盈立客户端(Electron, CDP 9222) → Vuex selfStock.selfData → 分组列表
    ├─ 美股(US) → us_instruments + us_universe_memberships(US_WATCHLIST)
    └─ 港股(HK) → market_instruments + market_universe_memberships(HK_WATCHLIST)

依赖：
  - 盈立客户端以 --remote-debugging-port=9222 启动且已登录
  - websocket-client（系统 Python 已安装）
"""
from __future__ import annotations

import base64
import json
import logging
import os
import time
import urllib.request
from datetime import datetime
from typing import Optional

from db.session import get_db_session
from market_quant.repository import MarketInstrument, MarketUniverseMembership
from us_quant.repository import USInstrument, USUniverseMembership

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)  # 定时任务需要留痕（全局默认 WARNING 会吞掉 info）

# ─── 配置 ──────────────────────────────────────────────────────────────────

CDP_PORT = int(os.environ.get("USMART_CDP_PORT", "9222"))
CDP_HTTP = f"http://127.0.0.1:{CDP_PORT}"
CDP_WS_BASE = f"ws://127.0.0.1:{CDP_PORT}/devtools/page"

US_WATCHLIST_CODE = "US_WATCHLIST"
HK_WATCHLIST_CODE = "HK_WATCHLIST"

NAV_TIMEOUT = 15          # 导航到自选页等待上限（秒）
POLL_INTERVAL = 2         # 数据加载轮询间隔（秒）
MAX_POLLS = 10            # 最多轮询次数

# ─── 掉线自动恢复配置 ──────────────────────────────────────────────────────

# 盈立客户端 electron-store 配置（记住的账号密码，base64 存储）
USMART_CONFIG_PATH = os.path.expanduser("~/Library/Application Support/uSmart/config.json")
USMART_CONFIG_KEY = "ORDINARY-USER"
# 手机端登录会把电脑端踢下线；同步时自动重新登录（设 USMART_AUTO_RELOGIN=0 关闭）
AUTO_RELOGIN = os.environ.get("USMART_AUTO_RELOGIN", "1") != "0"
LOGIN_WAIT_SECONDS = 25   # 自动登录后等待页面跳转上限（秒）
LOGIN_POLL_INTERVAL = 2

_STATUS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "..", "data", "usmart_sync_status.json")

# ─── CDP 工具 ─────────────────────────────────────────────────────────────

# 注入页面执行的 JS：确保在自选页并返回分组数据
_READ_JS = r"""
(async function(){
  function read(){
    var app = document.querySelector('#app');
    if (!app || !app.__vue__) return {ready:false, reason:'no-vue', groups:[]};
    var store = app.__vue__.$store;
    if (!store || !store.state || !store.state.selfStock) return {ready:false, reason:'no-store', groups:[]};
    var sd = store.state.selfStock.selfData || {};
    var groups = sd.group || [];
    return {
      ready: true,
      hasValid: !!sd.hasValidStock,
      groups: groups.map(function(g){
        return {
          gid: g.gid,
          gname: g.gname || '',
          symbols: (g.list || []).map(function(item){
            return {
              stock: String(item.stock || item.code || item.symbol || '').trim(),
              market: String(item.market || item.marketType || item.market_type || '').toLowerCase()
            };
          })
        };
      })
    };
  }
  var probe = read();
  if (probe.ready && probe.hasValid) return probe;
  // 导航到自选页触发加载
  try {
    var app = document.querySelector('#app').__vue__;
    if (location.hash.indexOf('optionalStock') < 0) {
      await app.$router.push('/quote/optionalStock');
    }
  } catch(e) {}
  return {ready: true, hasValid: false, groups: [], navigating: true};
})()
"""

# 轮询 JS：返回当前自选数据（含加载完成标记）
_POLL_JS = r"""
(function(){
  var app = document.querySelector('#app');
  if (!app || !app.__vue__) return {ready:false, reason:'no-vue', groups:[]};
  var store = app.__vue__.$store;
  if (!store || !store.state || !store.state.selfStock) return {ready:false, reason:'no-store', groups:[]};
  var sd = store.state.selfStock.selfData || {};
  var groups = sd.group || [];
  return {
    ready: true,
    hasValid: !!sd.hasValidStock,
    groups: groups.map(function(g){
      return {
        gid: g.gid,
        gname: g.gname || '',
        symbols: (g.list || []).map(function(item){
          return {
            stock: String(item.stock || item.code || item.symbol || '').trim(),
            market: String(item.market || item.marketType || item.market_type || '').toLowerCase()
          };
        })
      };
    })
  };
})()
"""


def _http_json(path: str, timeout: float = 5.0) -> Optional[dict]:
    """请求 CDP HTTP 端点（/json）"""
    try:
        with urllib.request.urlopen(f"{CDP_HTTP}{path}", timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        logger.warning("[usmart] CDP HTTP %s 失败: %s", path, exc)
        return None


def _discover_page_ws() -> Optional[str]:
    """发现主页面（index.html）的 WebSocket 调试地址"""
    pages = _http_json("/json")
    if not pages:
        return None
    for page in pages:
        url = page.get("url", "")
        if "index.html" in url:
            return page.get("webSocketDebuggerUrl")
    return None


def discover_cdp_status() -> dict:
    """返回可操作的 CDP 状态，区分端口未开与没有页面目标。"""
    version = _http_json("/json/version", timeout=2.0)
    if version is None:
        return {"available": False, "page_count": 0,
                "reason": "未检测到盈立调试端口（9222），请保持客户端开启并启用调试端口。"}
    pages = _http_json("/json", timeout=2.0)
    if not pages:
        return {"available": False, "page_count": 0,
                "reason": "盈立调试端口已开启，但没有可同步页面；请打开盈立主界面或登录页后再同步。"}
    page_count = sum(1 for page in pages if page.get("webSocketDebuggerUrl"))
    if not _discover_page_ws():
        return {"available": False, "page_count": page_count,
                "reason": "已发现调试页面，但不是盈立主页面；请切换到盈立行情/自选页面。"}
    return {"available": True, "page_count": page_count, "reason": ""}


def _ws_eval(ws_url: str, expression: str, timeout: float = 30.0) -> Optional[dict]:
    """通过 CDP WebSocket 执行 JS，返回 result 值（dict）"""
    import websocket
    try:
        ws = websocket.create_connection(ws_url, timeout=timeout)
    except Exception as exc:
        logger.warning("[usmart] CDP 连接失败: %s", exc)
        return None
    try:
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "awaitPromise": True,
                       "returnByValue": True},
        }))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") != 1:
                continue
            result = msg.get("result", {})
            if "exceptionDetails" in result:
                logger.warning("[usmart] JS 执行异常: %s",
                               result["exceptionDetails"].get("exception", {}).get("description", "")[:300])
                return None
            value = result.get("result", {}).get("value")
            if isinstance(value, dict):
                return value
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (TypeError, ValueError):
                    return {"raw": value}
            return None
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ─── 登录态检测与自动恢复 ──────────────────────────────────────────────────

_LOGIN_STATE_JS = r"""
(function(){
  var app = document.querySelector('#app');
  var vue = app && app.__vue__;
  var hash = location.hash || '';
  var btn = document.querySelector('button.login-button, .login-btn, .el-button.login-button');
  var logged = false;
  try {
    var st = vue && vue.$store && vue.$store.state;
    var notice = (st && st.notice) || {};
    var userData = st && st.login && st.login.userData;
    var hasUserData = !!(userData && typeof userData === 'object' && Object.keys(userData).length);
    // sharedState.selfStock 是本地缓存的自选列表，不代表已登录。
    // 旧逻辑把缓存数量当成登录凭证，导致掉线后永远不会触发自动重登。
    logged = hasUserData || notice.hasUsStock === true || notice.hasHkStock === true;
  } catch(e) {}
  var state = 'unknown';
  if (btn || hash.indexOf('login') >= 0) state = 'login_page';
  else if (logged) state = 'logged_in';
  else state = 'login_page';
  return {state: state, hash: hash, logged: logged, hasBtn: !!btn};
})()
"""

_FILL_LOGIN_JS = r"""
(async function(){
  var phone = __PHONE__;
  var pwd = __PWD__;
  function setVal(el, val){
    var setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
    setter.call(el, val);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
  }
  function isLoginPage(){
    return !!document.querySelector('button.login-button, .login-btn') || location.hash.indexOf('login') >= 0;
  }
  // 若不在登录页，先导航过去
  if (!isLoginPage()) {
    try {
      var app0 = document.querySelector('#app');
      if (app0 && app0.__vue__ && app0.__vue__.$router) {
        await app0.__vue__.$router.push('/login');
        await new Promise(function(r){ setTimeout(r, 1500); });
      }
    } catch(e) {}
  }
  var inputs = document.querySelectorAll('input');
  var phoneEl = null, pwdEl = null;
  for (var i = 0; i < inputs.length; i++) {
    var t = (inputs[i].type || '').toLowerCase();
    var ph = (inputs[i].placeholder || '').toLowerCase();
    if (t === 'password') { pwdEl = inputs[i]; }
    else if (!phoneEl && /手机|账号|phone/i.test(ph)) { phoneEl = inputs[i]; }
  }
  var info = {phoneFound: !!phoneEl, pwdFound: !!pwdEl, loginPage: isLoginPage()};
  if (phoneEl && phone) setVal(phoneEl, phone);
  if (pwdEl && pwd) setVal(pwdEl, pwd);
  await new Promise(function(r){ setTimeout(r, 400); });
  var btn = document.querySelector('button.login-button') || document.querySelector('.login-btn');
  info.btnFound = !!btn;
  if (btn) { btn.click(); info.clicked = true; }
  return info;
})()
"""

_SMS_CHECK_JS = r"""
(function(){
  var t = (document.body.innerText || '');
  var sms = t.indexOf('验证码') >= 0 && t.indexOf('发送') >= 0;
  return {sms: sms, sample: t.slice(0, 150)};
})()
"""


def _check_login_state(ws_url: str) -> str:
    """检测盈立页面登录态: logged_in / login_page / unknown"""
    data = _ws_eval(ws_url, _LOGIN_STATE_JS, timeout=10)
    if not data:
        return "unknown"
    return data.get("state", "unknown")


def _load_saved_credentials() -> Optional[tuple]:
    """从盈立 config.json 读取记住的账号密码（base64），仅用于本机自动重登

    返回 (phone, pwd) 或 None
    """
    try:
        with open(USMART_CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        entry = cfg.get(USMART_CONFIG_KEY, {})
        raw = entry.get("value") if isinstance(entry, dict) else entry
        if isinstance(raw, str):
            accounts = json.loads(raw)
            for acc in accounts:
                phone = base64.b64decode(acc.get("phone", "") + "==").decode("utf-8", "ignore")
                pwd = base64.b64decode(acc.get("pwd", "") + "==").decode("utf-8", "ignore")
                if phone and pwd:
                    return phone, pwd
    except Exception as exc:
        logger.warning("[usmart] 读取记住的账号失败: %s", exc)
    return None


def _auto_login(ws_url: str) -> dict:
    """自动重新登录盈立（掉线恢复）

    返回: {"ok": bool, "status": str, "error": str}
      status: relogin_ok / need_sms / no_credentials / disabled / failed
    """
    if not AUTO_RELOGIN:
        return {"ok": False, "status": "disabled",
                "error": "掉线自动重登已关闭（USMART_AUTO_RELOGIN=0）"}
    creds = _load_saved_credentials()
    if not creds:
        return {"ok": False, "status": "no_credentials",
                "error": "config.json 未找到记住的账号，请手动在盈立客户端登录"}
    phone, pwd = creds
    expr = _FILL_LOGIN_JS.replace("__PHONE__", json.dumps(phone, ensure_ascii=False)) \
        .replace("__PWD__", json.dumps(pwd, ensure_ascii=False))
    data = _ws_eval(ws_url, expr, timeout=15)
    if not data:
        return {"ok": False, "status": "failed", "error": "无法在登录页执行自动登录"}
    logger.info("[usmart] 自动登录已提交: %s", data)

    # 轮询等待登录结果（登录成功会刷新页面，每次都重新发现连接）
    for _ in range(int(LOGIN_WAIT_SECONDS / LOGIN_POLL_INTERVAL)):
        time.sleep(LOGIN_POLL_INTERVAL)
        ws = _discover_page_ws()
        if not ws:
            continue
        state = _check_login_state(ws)
        if state == "logged_in":
            return {"ok": True, "status": "relogin_ok", "error": ""}
        if state == "login_page":
            sms = _ws_eval(ws, _SMS_CHECK_JS, timeout=10)
            if sms and sms.get("sms"):
                return {"ok": False, "status": "need_sms",
                        "error": "触发新设备短信验证，请在盈立客户端窗口输入验证码"}
    return {"ok": False, "status": "failed", "error": "自动登录超时（仍在登录页）"}


def fetch_usmart_watchlist(max_wait: int = 30) -> dict:
    """读取盈立客户端自选（美股/港股）

    返回: {"US": [ticker...], "HK": [code...], "total": int,
           "source": "cdp", "ok": bool, "error": str}
    """
    ws_url = _discover_page_ws()
    if not ws_url:
        return {"ok": False, "error": f"未发现盈立调试页面（127.0.0.1:{CDP_PORT}）",
                "US": [], "HK": [], "total": 0, "source": "cdp"}

    # 掉线自动恢复：手机端登录会把电脑端踢下线，同步时自动重登
    login_state = _check_login_state(ws_url)
    login_status = "logged_in"
    if login_state == "login_page":
        relogin = _auto_login(ws_url)
        if not relogin.get("ok"):
            return {"ok": False,
                    "error": relogin.get("error", "自动重登失败"),
                    "login": relogin.get("status", "failed"),
                    "US": [], "HK": [], "total": 0, "source": "cdp"}
        login_status = "relogin_ok"
        ws_url = _discover_page_ws() or ws_url

    data = _ws_eval(ws_url, _READ_JS, timeout=NAV_TIMEOUT + 5)
    if not data:
        return {"ok": False, "error": "无法在盈立页面执行脚本（可能未登录）",
                "US": [], "HK": [], "total": 0, "source": "cdp"}

    # 轮询等待自选数据加载
    groups = data.get("groups", [])
    has_valid = data.get("hasValid", False)
    if not has_valid:
        for _ in range(MAX_POLLS):
            time.sleep(POLL_INTERVAL)
            data = _ws_eval(ws_url, _POLL_JS, timeout=10)
            if not data:
                continue
            groups = data.get("groups", [])
            has_valid = data.get("hasValid", False)
            loaded = any(g.get("symbols") for g in groups)
            if has_valid or loaded:
                break

    us: list[str] = []
    hk: list[str] = []
    for group in groups:
        gname = group.get("gname", "")
        for item in group.get("symbols", []):
            code = item.get("stock", "")
            if not code:
                continue
            market = (item.get("market", "") or "").lower()
            if market in ("us", "us-stock", "usa"):
                us.append(code)
            elif market in ("hk", "hk-stock"):
                hk.append(code)
            else:
                # 按分组名兜底
                if "港股" in gname:
                    hk.append(code)
                elif "美股" in gname:
                    us.append(code)

    us = _dedupe_upper(us)
    hk = _dedupe_hk(hk)
    logger.info("[usmart] 自选读取完成: US=%d HK=%d", len(us), len(hk))
    return {"ok": True, "US": us, "HK": hk, "total": len(us) + len(hk),
            "source": "cdp", "login": login_status, "error": ""}


def _dedupe_upper(codes: list[str]) -> list[str]:
    seen: set = set()
    out: list[str] = []
    for c in codes:
        c = c.strip().upper()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _dedupe_hk(codes: list[str]) -> list[str]:
    seen: set = set()
    out: list[str] = []
    for c in codes:
        c = c.strip().upper()
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


# ─── 数据库写入 ────────────────────────────────────────────────────────────

def sync_us_stocks(codes: list[str]) -> int:
    """美股自选 → us_instruments + US_WATCHLIST 池（幂等）"""
    codes = _dedupe_upper(codes)
    now = datetime.now()
    with get_db_session() as db:
        for code in codes:
            inst = db.query(USInstrument).filter(USInstrument.symbol == code).first()
            if not inst:
                db.add(USInstrument(symbol=code, is_active=True,
                                    universe_source="usmart_watchlist",
                                    created_at=now, updated_at=now))
        db.query(USUniverseMembership).filter(
            USUniverseMembership.universe_code == US_WATCHLIST_CODE,
            USUniverseMembership.effective_to.is_(None),
        ).update({"effective_to": now}, synchronize_session=False)
        for rank, code in enumerate(codes, start=1):
            db.add(USUniverseMembership(
                symbol=code, universe_code=US_WATCHLIST_CODE, tier="WATCH",
                rank=rank, effective_from=now,
                inclusion_reason="盈立自选同步", source="usmart_watchlist",
                config_version="v1",
            ))
        db.commit()
    logger.info("[usmart] 美股自选写入完成: %d 只", len(codes))
    # 后台补采缺失行业（stockanalysis.com），不阻塞同步；新股票自动带板块
    try:
        from services.us_sector_fetcher import backfill_sectors_async
        backfill_sectors_async(codes)
    except Exception as exc:
        logger.warning("[usmart] 行业补采启动失败: %s", exc)
    return len(codes)


def sync_hk_stocks(codes: list[str]) -> int:
    """港股自选 → market_instruments + HK_WATCHLIST 池（幂等）"""
    codes = _dedupe_hk(codes)
    now = datetime.now()
    with get_db_session() as db:
        for code in codes:
            inst = db.query(MarketInstrument).filter(
                MarketInstrument.market == "HK",
                MarketInstrument.symbol == code,
            ).first()
            if not inst:
                db.add(MarketInstrument(
                    market="HK", symbol=code, provider_symbol=code,
                    exchange="HKEX", is_active=True, is_etf=False,
                    source="usmart_watchlist", created_at=now,
                ))
        db.query(MarketUniverseMembership).filter(
            MarketUniverseMembership.market == "HK",
            MarketUniverseMembership.universe_code == HK_WATCHLIST_CODE,
            MarketUniverseMembership.effective_to.is_(None),
        ).update({"effective_to": now}, synchronize_session=False)
        for rank, code in enumerate(codes, start=1):
            db.add(MarketUniverseMembership(
                market="HK", universe_code=HK_WATCHLIST_CODE, symbol=code,
                tier="WATCH", rank=rank, effective_from=now,
                inclusion_reason="盈立自选同步", source="usmart_watchlist",
                config_version="v1",
            ))
        db.commit()
    logger.info("[usmart] 港股自选写入完成: %d 只", len(codes))
    return len(codes)


# ─── 状态记录 ──────────────────────────────────────────────────────────────

def _save_status(payload: dict):
    try:
        os.makedirs(os.path.dirname(_STATUS_FILE), exist_ok=True)
        with open(_STATUS_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("[usmart] 状态保存失败: %s", exc)


def get_last_status() -> dict:
    try:
        if os.path.exists(_STATUS_FILE):
            with open(_STATUS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"ok": False, "error": "尚未同步过"}


# ─── 总入口 ────────────────────────────────────────────────────────────────

def run_sync(markets: str = "US,HK") -> dict:
    """同步盈立自选 → 9000 服务股票池

    Args:
        markets: 逗号分隔，可选 US / HK，默认都同步
    """
    started = datetime.now()
    wanted = {m.strip().upper() for m in markets.split(",") if m.strip()}
    wanted &= {"US", "HK"}
    if not wanted:
        wanted = {"US", "HK"}

    fetched = fetch_usmart_watchlist()
    if not fetched.get("ok"):
        result = {"ok": False, "error": fetched.get("error", "读取盈立自选失败"),
                  "login": fetched.get("login", "unknown"),
                  "US": [], "HK": [], "synced_at": started.isoformat()}
        _save_status(result)
        return result

    us_codes = fetched.get("US", []) if "US" in wanted else []
    hk_codes = fetched.get("HK", []) if "HK" in wanted else []

    result = {
        "ok": True,
        "US": {"count": sync_us_stocks(us_codes)},
        "HK": {"count": sync_hk_stocks(hk_codes)},
        "source": "cdp",
        "login": fetched.get("login", "logged_in"),
        "synced_at": started.isoformat(),
    }
    _save_status(result)
    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    print(json.dumps(run_sync(), ensure_ascii=False, indent=2))
