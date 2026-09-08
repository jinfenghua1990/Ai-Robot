"""飞书推送服务 —— 移植自 tickflow-stock-panel (MIT) 的 webhook_adapter 飞书部分。

把监控规则告警推送到飞书群自定义机器人 Webhook。

接入方法：
  1. 飞书群 → 群设置 → 群推送 Webhook → 添加「自定义机器人」
  2. 复制 Webhook 地址（形如 https://open.feishu.cn/open-apis/bot/v2/hook/xxx）
  3. （可选）安全设置 → 启用「签名校验」，记录签名密钥(secret)
  4. 配置环境变量 FEISHU_WEBHOOK_URL / FEISHU_WEBHOOK_SECRET（或写入 .env）

设计：失败静默降级，绝不因推送失败阻断告警主流程。
      去重不在本层做，复用 MonitorRuleEngine 的 cooldown。
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

# 单次推送最长字符（飞书单条文本消息上限 30KB，保守截断避免刷屏）
_MAX_LEN = 500

# 飞书自定义机器人 Webhook 前缀（用于 URL 合法性校验）
FEISHU_HOOK_PREFIX = "https://open.feishu.cn/open-apis/bot/v2/hook/"

# 配置读取：环境变量（可在 .env / autostart 注入）
_CFG_URL = os.environ.get("FEISHU_WEBHOOK_URL", "")
_CFG_SECRET = os.environ.get("FEISHU_WEBHOOK_SECRET", "")


def get_feishu_config() -> dict:
    """返回当前生效的飞书配置（每次读取环境变量，支持运行中变更）。"""
    return {
        "url": os.environ.get("FEISHU_WEBHOOK_URL", _CFG_URL) or "",
        "secret": os.environ.get("FEISHU_WEBHOOK_SECRET", _CFG_SECRET) or "",
    }


def is_valid_feishu_url(url: str) -> bool:
    """校验是否为合法的飞书自定义机器人 Webhook 地址。"""
    return bool(url) and url.startswith(FEISHU_HOOK_PREFIX)


def _gen_sign(timestamp: str, secret: str) -> str:
    """计算飞书自定义机器人签名。

    算法（官方）：把 `timestamp + "\n" + secret` 作为签名字符串(key)，
    用 HmacSHA256 计算空字符串的签名结果，再 Base64 编码。
    """
    string_to_sign = f"{timestamp}\n{secret}"
    hmac_code = hmac.new(
        string_to_sign.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(hmac_code).decode("utf-8")


def _truncate(text: str) -> str:
    """截断超长文本。"""
    text = (text or "").strip()
    return text[:_MAX_LEN] + ("…" if len(text) > _MAX_LEN else "")


_FEISHU_MAX_ATTEMPTS = 3


def _post_feishu(webhook_url: str, payload: dict, secret: str) -> bool:
    """发送飞书 webhook 请求并判定成败。

    成功响应：HTTP 200 且业务 code=0。
    瞬时失败（网络/超时/HTTP 5xx）带退避重试；永久失败（4xx/业务 code≠0）不重试。
    最终失败记 WARNING，保证「推送丢了」在日志里可见。
    """
    import httpx

    last_err = ""
    for attempt in range(1, _FEISHU_MAX_ATTEMPTS + 1):
        try:
            # 启用签名校验时，请求体须带 timestamp + sign（每次重试都重算，防时间戳过期）
            if secret:
                timestamp = str(int(time.time()))
                payload = dict(payload)
                payload["timestamp"] = timestamp
                payload["sign"] = _gen_sign(timestamp, secret)

            resp = httpx.post(webhook_url, json=payload, timeout=5.0)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    return True  # 非 JSON 的 200，视为成功
                if isinstance(data, dict):
                    code = data.get("code", data.get("StatusCode", 0))
                    if code == 0:
                        return True
                    # 业务失败(签名错/格式错等): 重试无益，直接失败
                    logger.warning("飞书推送业务失败(不重试): %s", data)
                    return False
                return True  # 200 且 JSON 非 dict，视为成功
            # 4xx 客户端错误(URL 失效等): 不重试; 5xx: 落入重试
            last_err = f"HTTP {resp.status_code}: {resp.text[:200]}"
            if resp.status_code < 500:
                logger.warning("飞书推送失败(不重试, 客户端错误): %s", last_err)
                return False
        except Exception as e:  # noqa: BLE001 — 网络/超时，可重试
            last_err = str(e)

        if attempt < _FEISHU_MAX_ATTEMPTS:
            time.sleep(min(2 ** (attempt - 1), 3))  # 退避: 1s, 2s

    logger.warning("飞书 Webhook 推送最终失败(已重试 %d 次): %s", _FEISHU_MAX_ATTEMPTS, last_err)
    return False


def send_feishu(webhook_url: str, title: str, body: str, secret: str = "") -> bool:
    """推送一条文本消息到飞书群推送 Webhook。

    Args:
        webhook_url: 飞书自定义机器人 Webhook 地址
        title:       消息标题（与正文拼接为一条文本）
        body:        消息正文
        secret:      签名密钥（机器人启用了「签名校验」时必填；留空则不带签名）

    Returns:
        True=成功送达, False=失败或 URL 非法。
        失败静默，不抛异常（Webhook 是辅助通道，不能阻断告警主流程）。
    """
    if not is_valid_feishu_url(webhook_url):
        return False

    text = _truncate(f"{title}\n{body}".strip())
    if not text:
        return False

    payload: dict = {"msg_type": "text", "content": {"text": text}}
    return _post_feishu(webhook_url, payload, secret)


# 独立线程池：webhook 慢/重试不拖累行情轮询与告警主流程
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="feishu")


def submit_feishu(title: str, body: str) -> None:
    """异步投递（线程池），失败静默记 WARNING。按当前环境变量配置投递。"""
    try:
        cfg = get_feishu_config()
        if not cfg["url"]:
            logger.info("飞书推送跳过：FEISHU_WEBHOOK_URL 未配置（title=%s）", title)
            return
        _executor.submit(send_feishu, cfg["url"], title, body, cfg["secret"])
    except Exception as e:  # noqa: BLE001
        logger.warning("飞书推送提交异常: %s", e)


def push_rule_trigger(rule: dict, symbol: str, name: str, feats: dict, price: float, change_pct: float) -> None:
    """规则触发时的飞书推送（组装告警文案 + 异步投递）。"""
    try:
        channels = rule.get("webhook_channels") or []
        if "feishu" not in channels:
            return
        sev = rule.get("severity", "info")
        sev_label = {"info": "普通", "warn": "警告", "critical": "严重"}.get(sev, sev)
        msg = rule.get("message") or ""
        conds = "；".join(
            f"{c.get('field')} {c.get('op')} {c.get('value')}"
            for c in rule.get("conditions", [])
            if c.get("op") != "truth"
        )
        title = f"🚨 监控告警[{sev_label}] {rule.get('name', '')}"
        body = (f"{symbol} {name}\n"
                f"现价 {price} · 涨跌 {change_pct:+.2f}%\n"
                f"条件: {conds or '信号成立'}")
        if msg:
            body += f"\n推送: {msg}"
        submit_feishu(title, body)
    except Exception as e:  # noqa: BLE001
        logger.warning("飞书规则推送组装异常: %s", e)
