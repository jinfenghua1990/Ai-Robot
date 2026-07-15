"""
一键上传 API
- POST /api/git-push   将当前仓库改动 add + commit + push 到 GitHub (Ai-Robot)

安全说明：
- 使用 subprocess 列表形式调用 git，绝不拼接用户输入到 shell，避免命令注入。
- commit message 仅作 git 参数传递，不进入 shell 解析。
- 显式指定部署专用 SSH 密钥，确保 uvicorn 常驻进程环境下也能认证。
"""
import os
import subprocess
from datetime import datetime
from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from api.auth import verify_api_key

router = APIRouter(prefix="/api", tags=["git"])

# 仓库根目录（相对本文件计算，避免依赖进程 cwd）
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

# 部署专用 SSH 密钥（确保 uvicorn 进程环境下也能认证；密钥无口令）
_KEY = os.path.expanduser("~/.ssh/airobot_deploy_ed25519")
GIT_SSH_COMMAND = f"ssh -i {_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=no"


def _run(args: list):
    return subprocess.run(
        args,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "GIT_SSH_COMMAND": GIT_SSH_COMMAND,
            "HOME": os.path.expanduser("~"),
        },
        timeout=120,
    )


@router.post("/git-push", dependencies=[Depends(verify_api_key)])
def git_push(payload: dict = Body(default={})):
    """将本地改动提交并推送到远程 main 分支。

    请求体可选字段:
        message (str): 自定义提交说明；省略则用「网页一键上传: <时间>」
    返回:
        { ok, had_changes, commit_message, output }
    """
    try:
        # 1. 是否有未提交改动
        status = _run(["git", "status", "--porcelain"])
        has_changes = bool(status.stdout.strip())

        # 2. 暂存全部（.gitignore 已排除 .trash/ backups/ 等本地产物）
        _run(["git", "add", "-A"])

        # 3. 有改动才提交
        commit_msg = None
        if has_changes:
            commit_msg = (payload or {}).get("message") or \
                f"网页一键上传: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            _run(["git", "commit", "-q", "-m", commit_msg])

        # 4. 推送到 origin/main
        push = _run(["git", "push", "origin", "main"])
        output = (push.stdout + push.stderr).strip()

        return {
            "ok": push.returncode == 0,
            "had_changes": has_changes,
            "commit_message": commit_msg,
            "output": output[-800:],  # 截断，避免响应过大
        }
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error": "git push 超时(>120s)，请稍后重试"},
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
