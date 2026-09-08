"""
一键上传 API
- POST /api/git-push   将当前仓库源码改动 add + commit + push 到 GitHub (Ai-Robot)

安全说明：
- 使用 subprocess 列表形式调用 git，绝不拼接用户输入到 shell，避免命令注入。
- commit message 仅作 git 参数传递，不进入 shell 解析。
- 显式指定部署专用 SSH 密钥，确保 uvicorn 常驻进程环境下也能认证。
- 仅允许 main 分支推送，且拒绝把本地运行时/用户状态文件纳入一键提交。
- git add / commit / push 任一步失败都会明确返回失败，不再出现“commit 失败但 push 成功”的假成功。
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

# 这些是运行时/用户私有状态，不允许被网页“一键上传”误提交。
# 部分旧基线仍在 Git 中跟踪，因此不能只依赖 .gitignore；这里用 pathspec 显式排除，
# 并在提交前再次检查暂存区，形成第二道保护。
RUNTIME_STATE_PATHS = {
    "portfolio.json",
    "watchlist.json",
    "focus.json",
    "stock_notes.json",
    "auto_trade_audit.json",
    "auto_trade_global.json",
    "auto_trade_stocks.json",
    "backend.log",
}


def _run(args: list[str]):
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


def _failure(step: str, result: subprocess.CompletedProcess, status_code: int = 500):
    detail = (result.stderr or result.stdout or f"{step} failed").strip()
    return JSONResponse(
        status_code=status_code,
        content={"ok": False, "step": step, "error": detail[-800:]},
    )


@router.post("/git-push", dependencies=[Depends(verify_api_key)])
def git_push(payload: dict = Body(default={})):
    """将本地源码改动提交并推送到远程 main 分支。

    请求体可选字段:
        message (str): 自定义提交说明；省略则用「网页一键上传: <时间>」
    返回:
        { ok, had_changes, commit_message, output }
    """
    try:
        # 0. Fail closed：网页上传只允许在 Ai-Robot 的 main 上执行。
        branch = _run(["git", "branch", "--show-current"])
        if branch.returncode != 0:
            return _failure("branch_check", branch)
        current_branch = branch.stdout.strip()
        if current_branch != "main":
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "step": "branch_check",
                    "error": f"当前分支为 {current_branch or 'DETACHED'}，网页一键上传只允许 main",
                },
            )

        remote = _run(["git", "remote", "get-url", "origin"])
        if remote.returncode != 0:
            return _failure("remote_check", remote)
        remote_url = remote.stdout.strip()
        if "jinfenghua1990/Ai-Robot" not in remote_url:
            return JSONResponse(
                status_code=409,
                content={"ok": False, "step": "remote_check", "error": "origin 不是 jinfenghua1990/Ai-Robot，拒绝推送"},
            )

        # 1. 暂存源码，但显式排除本地运行时/用户状态。
        stage_args = ["git", "add", "-A", "--", "."]
        stage_args.extend(f":(exclude){path}" for path in sorted(RUNTIME_STATE_PATHS))
        staged = _run(stage_args)
        if staged.returncode != 0:
            return _failure("git_add", staged)

        # 2. 如果调用前已经有人把私有运行时文件放进暂存区，直接阻断而不是偷偷提交。
        staged_names = _run(["git", "diff", "--cached", "--name-only"])
        if staged_names.returncode != 0:
            return _failure("staged_files_check", staged_names)
        staged_paths = {line.strip() for line in staged_names.stdout.splitlines() if line.strip()}
        blocked = sorted(staged_paths & RUNTIME_STATE_PATHS)
        if blocked:
            return JSONResponse(
                status_code=409,
                content={
                    "ok": False,
                    "step": "runtime_state_guard",
                    "error": "检测到本地运行时/用户状态已在暂存区，已阻止上传",
                    "blocked_paths": blocked,
                },
            )

        # 3. 以暂存区为准判断是否真的有可提交源码改动。
        diff = _run(["git", "diff", "--cached", "--quiet"])
        if diff.returncode not in (0, 1):
            return _failure("staged_diff_check", diff)
        has_changes = diff.returncode == 1

        commit_msg = None
        if has_changes:
            commit_msg = str((payload or {}).get("message") or "").strip() or \
                f"网页一键上传: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
            commit = _run(["git", "commit", "-q", "-m", commit_msg])
            if commit.returncode != 0:
                return _failure("git_commit", commit)

        # 4. 明确推送本地 main -> origin/main；失败返回非 2xx。
        push = _run(["git", "push", "origin", "main:main"])
        if push.returncode != 0:
            return _failure("git_push", push, status_code=502)
        output = (push.stdout + push.stderr).strip()

        return {
            "ok": True,
            "had_changes": has_changes,
            "commit_message": commit_msg,
            "branch": current_branch,
            "output": output[-800:],
        }
    except subprocess.TimeoutExpired:
        return JSONResponse(
            status_code=504,
            content={"ok": False, "error": "Git 操作超时(>120s)，请稍后重试"},
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
