"""定时任务失败告警：任务失败立刻通知用户。

通道组合（按可用性自动降级，全部失败静默，绝不阻断任务主流程）：
  1. macOS 系统通知（osascript）—— 本机零配置，最直接
  2. 飞书 Webhook（配置 FEISHU_WEBHOOK_URL 后自动启用）—— 远程可收

去重：同一告警 key 在冷却窗口（默认 30 分钟）内只报一次，
避免盘中每 30 分钟的刷新任务反复失败时刷屏。
"""
from __future__ import annotations

import logging
import subprocess
import threading
import time

logger = logging.getLogger(__name__)

# 同一 key 的冷却秒数
_COOLDOWN_SECONDS = 30 * 60

# 进程内冷却表：key -> 上次通知时间戳
_last_sent: dict[str, float] = {}
_lock = threading.Lock()


def _macos_notify(title: str, message: str) -> None:
    """弹 macOS 系统通知（带声音）。失败静默。"""
    try:
        subprocess.run(
            [
                "osascript", "-e",
                f'display notification "{message}" with title "{title}" sound name "Basso"',
            ],
            timeout=5,
            check=False,
            capture_output=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("[job-alert] macOS 通知失败: %s", exc)


def _feishu_notify(title: str, message: str) -> None:
    """飞书 Webhook（未配置时自动跳过）。复用 services/feishu_notify。"""
    try:
        from services.feishu_notify import submit_feishu
        submit_feishu(title, message)
    except Exception as exc:  # noqa: BLE001
        logger.warning("[job-alert] 飞书推送失败: %s", exc)


def notify_failure(strategy: str, reason: str, detail: str = "", key: str | None = None) -> None:
    """任务失败立刻通知。后台线程执行，调用方零阻塞。

    Args:
        strategy: 策略名（如 "回马枪 1.1.5" / "横盘蓄势"）
        reason:   失败摘要（如 "实时扫描失败"）
        detail:   错误详情（异常信息等，可为空）
        key:      去重键；默认 strategy+reason，冷却窗口内不重复报
    """
    dedup_key = key or f"{strategy}:{reason}"
    now = time.monotonic()
    with _lock:
        last = _last_sent.get(dedup_key)
        if last is not None and now - last < _COOLDOWN_SECONDS:
            return
        _last_sent[dedup_key] = now

    title = f"⚠️ {strategy} · {reason}"
    message = detail[:180] if detail else "详见后端日志"
    threading.Thread(
        target=_dispatch, args=(title, message), daemon=True, name="job-alert"
    ).start()


def _dispatch(title: str, message: str) -> None:
    _macos_notify(title, message)
    _feishu_notify(title, message)
