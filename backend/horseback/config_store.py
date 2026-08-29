"""iFinD MCP 密钥的本机安全存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import tempfile


TOKEN_ENV = "IFIND_AUTH_TOKEN"
TOKEN_FILE_ENV = "IFIND_TOKEN_FILE"


def normalize_token(value: str) -> str:
    token = re.sub(r"\\([._-])", r"\1", str(value or "").strip())
    parts = token.split(".")
    if len(parts) != 5 or any(not part or not re.fullmatch(r"[A-Za-z0-9_-]+", part) for part in parts):
        raise ValueError("iFinD 密钥格式无效，应为五段式 JWE")
    return token


def default_token_path(env=None) -> Path:
    env = os.environ if env is None else env
    configured = str(env.get(TOKEN_FILE_ENV, "")).strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / "Library" / "Application Support" / "AIROBOT" / "ifind.json"


class TokenStore:
    def __init__(self, path: Path | str | None = None, env=None):
        self.env = os.environ if env is None else env
        self.path = Path(path).expanduser() if path else default_token_path(self.env)

    def load(self) -> str:
        env_token = str(self.env.get(TOKEN_ENV, "")).strip()
        if env_token:
            return normalize_token(env_token)
        if not self.path.exists():
            raise FileNotFoundError("iFinD 密钥尚未配置")
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("iFinD 密钥文件不可读") from exc
        return normalize_token(payload.get("token", ""))

    def save(self, value: str) -> None:
        token = normalize_token(value)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=".ifind-", delete=False
            ) as handle:
                temporary = Path(handle.name)
                json.dump({"token": token}, handle, ensure_ascii=False)
                handle.write("\n")
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        except Exception:
            if temporary and temporary.exists():
                temporary.unlink()
            raise

    def status(self) -> dict:
        env_token = str(self.env.get(TOKEN_ENV, "")).strip()
        if env_token:
            try:
                normalize_token(env_token)
                return {"configured": True, "source": "environment"}
            except ValueError:
                return {"configured": False, "source": "environment_invalid"}
        if not self.path.exists():
            return {"configured": False, "source": "none"}
        try:
            self.load()
            return {"configured": True, "source": "file"}
        except (FileNotFoundError, ValueError):
            return {"configured": False, "source": "file_invalid"}
