"""
集中配置：所有路径、端口、机器人映射都在这里。
不再在代码里写死绝对路径。
"""
from pathlib import Path
import os

if __package__ in (None, ""):
    from api.hermes_native.strategies.catalog import (
        DEFAULT_CUSTOM_STRATEGY_KEYS,
        build_all_robot_ids,
        build_robot_id_to_key,
        build_robot_strategy_map,
        build_strategy_catalog,
    )
else:
    from api.hermes_native.strategies.catalog import (
        DEFAULT_CUSTOM_STRATEGY_KEYS,
        build_all_robot_ids,
        build_robot_id_to_key,
        build_robot_strategy_map,
        build_strategy_catalog,
    )


# ── 1. 基础路径（可被环境变量覆盖） ─────────────────────────────────────
_HERMES_HOME_RAW = Path(os.getenv("HERMES_HOME", "/Users/gino/Projects/AIROBOT/backend/.hermes-legacy")).expanduser().resolve()
_HERMES_HOME_PARENT = _HERMES_HOME_RAW.parent
_HERMES_HOME_CHECK = _HERMES_HOME_RAW / "data" / "strategies" / "output" / "baihu" / "result.json"
_HERMES_HOME_PARENT_CHECK = _HERMES_HOME_PARENT / "data" / "strategies" / "output" / "baihu" / "result.json"
if _HERMES_HOME_RAW.name == "main" and _HERMES_HOME_PARENT_CHECK.exists():
    if (not _HERMES_HOME_CHECK.exists()) or (
        _HERMES_HOME_PARENT_CHECK.stat().st_mtime > _HERMES_HOME_CHECK.stat().st_mtime
    ):
        HERMES_HOME = _HERMES_HOME_PARENT
    else:
        HERMES_HOME = _HERMES_HOME_RAW
else:
    HERMES_HOME = _HERMES_HOME_RAW

# 前端构建产物目录
# 优先级：环境变量 > 同级 frontend/dist
_BACKEND_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _BACKEND_DIR.parent
_DEFAULT_FRONTEND = _PROJECT_ROOT / "frontend" / "dist"

if os.getenv("FRONTEND_DIST"):
    FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST")).expanduser().resolve()
else:
    FRONTEND_DIST = _DEFAULT_FRONTEND

# 服务端口
PORT = int(os.getenv("COCKPIT_PORT", "8788"))
HOST = os.getenv("COCKPIT_HOST", "127.0.0.1")

ROBOT_STRATEGY_MAP = build_robot_strategy_map(HERMES_HOME)
ROBOT_ID_TO_KEY = build_robot_id_to_key(ROBOT_STRATEGY_MAP)
ALL_ROBOT_IDS = build_all_robot_ids(ROBOT_STRATEGY_MAP)
STRATEGY_CATALOG = build_strategy_catalog()
