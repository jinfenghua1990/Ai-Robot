#!/bin/bash
# AIROBOT preflight v1 — git push --force 唯一准入凭证
# 用法: scripts/preflight-v1.sh <sha>
# 规格: 原子脚本 / 绝对路径 / git 官方 exe / 接受 SHA 参数 /
#       JSON report 写到仓库之外 / exit 0 = 全绿 = 唯一允许 --force 的凭证
#       包含核心系统回归测试(语法编译 + FastAPI app 导入 + 内嵌 V2 路由 + 核心模块导入 + pytest 全套 + 前端真实构建 + 备份 anchor 远端存在性)
set -u

REPO="/Users/gino/Projects/AIROBOT"
GIT_BIN="/opt/homebrew/bin/git"
PY="$REPO/backend/.venv/bin/python"
NPM_BIN="/opt/homebrew/bin/npm"
OUT_DIR="/tmp/airobot-preflight"
ANCHOR_BRANCH="backup/pre-clean-20260908"

SHA_ARG="${1:-}"
if [ -z "$SHA_ARG" ]; then
  echo "usage: $0 <sha>" >&2
  exit 2
fi

mkdir -p "$OUT_DIR"
TS="$(date +%Y%m%d-%H%M%S)"
REPORT="$OUT_DIR/preflight-$TS.json"
TMP_JSON="$(mktemp "$OUT_DIR/entries.XXXXXX")"

PASS=0
FAIL=0

add_check() { # id desc status detail
  local id="$1" desc="$2" status="$3" detail="$4"
  if [ "$status" = "pass" ]; then PASS=$((PASS+1)); else FAIL=$((FAIL+1)); fi
  detail="${detail//\\/\\\\}"
  detail="${detail//\"/\\\"}"
  detail="${detail//$'\n'/ }"
  detail="${detail//$'\r'/ }"
  printf '{"id":"%s","desc":"%s","status":"%s","detail":"%s"},\n' "$id" "$desc" "$status" "$detail" >> "$TMP_JSON"
}

run_check() { # id desc fn
  local id="$1" desc="$2" fn="$3"
  local out rc
  out="$($fn 2>&1)"
  rc=$?
  if [ $rc -eq 0 ]; then
    add_check "$id" "$desc" "pass" "${out:0:400}"
  else
    add_check "$id" "$desc" "fail" "${out:0:400}"
  fi
}

chk_git_bin()      { test -x "$GIT_BIN"; }
chk_py_bin()       { test -x "$PY"; }
chk_npm_bin()      { test -x "$NPM_BIN"; }
chk_repo_identity(){ "$GIT_BIN" -C "$REPO" remote get-url origin | grep -q "jinfenghua1990/Ai-Robot"; }
chk_sha_exists()   { "$GIT_BIN" -C "$REPO" rev-parse --verify "$SHA_ARG^{commit}" >/dev/null; }
chk_anchor_origin(){ "$GIT_BIN" ls-remote origin "refs/heads/$ANCHOR_BRANCH" | grep -q .; }
chk_backend_syntax(){ cd "$REPO" && "$PY" -m compileall -q backend/api backend/services backend/analyzers backend/strategies backend/us_quant v2_app; }
chk_app_import()   { cd "$REPO" && "$PY" -c "import backend.main as m; assert 'AIROBOT' in m.app.title, m.app.title"; }
chk_v2_embed()     { cd "$REPO" && "$PY" -c 'from v2_app.main import app; paths={getattr(r,"path","") for r in app.routes}; required={"/api/v2/health","/api/v2/dashboard","/api/v2/candidates","/api/v2/sectors","/api/v2/actions","/api/v2/yuzi","/api/v2/watchlist","/api/v2/watchlist/{code}","/api/v2/holdings","/api/v2/orders","/api/v2/trade/preview","/api/v2/stock/{code}","/api/v2/stock/{code}/research","/api/v2/factor-lifecycle","/api/v2/validation","/api/v2/registry","/api/v2/system/quality","/api/v2/collection/status","/api/v2/system/quality-dashboard","/api/v2/system/check","/api/v2/snapshot/persist","/api/v2/research/snapshot/persist","/api/v2/config"}; missing=sorted(required-paths); assert not missing, f"missing V2 routes: {missing}"; print(f"embedded V2 routes OK ({len(required)} required)")'; }
chk_core_import()  { cd "$REPO/backend" && "$PY" -c "import api.watchlist, api.us_quant, api.hk_strategy, services.trading_system"; }
chk_pytest()       { cd "$REPO" && "$PY" -m pytest "$REPO/tests" -q --no-header 2>&1 | tail -1 | grep -qE '^[0-9]+ passed'; }
chk_frontend_files(){ test -f "$REPO/frontend/package.json" && test -f "$REPO/frontend/vite.config.js" && test -f "$REPO/frontend/src/main.jsx" && test -f "$REPO/frontend/src/App.jsx"; }
chk_frontend_build(){ cd "$REPO/frontend" && "$NPM_BIN" run build >/dev/null; }

run_check git_bin          "git 官方 exe 存在且可执行 ($GIT_BIN)"        chk_git_bin
run_check py_bin           "项目 venv python 存在 ($PY)"                 chk_py_bin
run_check npm_bin          "Homebrew npm 存在且可执行 ($NPM_BIN)"         chk_npm_bin
run_check repo_identity    "仓库身份 = jinfenghua1990/Ai-Robot"          chk_repo_identity
run_check sha_exists       "目标 SHA 可解析为 commit"                    chk_sha_exists
run_check anchor_on_origin "备份 anchor 分支存在于 origin (旧历史可恢复)" chk_anchor_origin
run_check backend_syntax   "核心 Python + v2_app 语法编译零错误"          chk_backend_syntax
run_check app_import       "FastAPI app (backend.main) 导入成功"          chk_app_import
run_check v2_embed         "9000 内嵌 V2 必需 API 路由完整"               chk_v2_embed
run_check core_import      "核心模块导入 (watchlist/us_quant/hk_strategy/trading_system)" chk_core_import
run_check pytest_suite     "pytest 全套通过"                             chk_pytest
run_check frontend_files   "前端关键文件齐全 (package.json/vite/main/App)" chk_frontend_files
run_check frontend_build   "前端 npm run build 真实构建通过"              chk_frontend_build

TARGET_SHA="$("$GIT_BIN" -C "$REPO" rev-parse "$SHA_ARG^{commit}" 2>/dev/null || echo "unresolvable")"
ANCHOR_SHA="$("$GIT_BIN" ls-remote origin "refs/heads/$ANCHOR_BRANCH" 2>/dev/null | awk '{print $1}')"
REMOTE_URL="$("$GIT_BIN" -C "$REPO" remote get-url origin 2>/dev/null || echo "unknown")"

if [ "$FAIL" -eq 0 ]; then VERDICT="GREEN"; RC=0; else VERDICT="RED"; RC=1; fi

{
  printf '{\n'
  printf '  "schema": "airobot.preflight/v1",\n'
  printf '  "generated_at": "%s",\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')"
  printf '  "repo": "%s",\n' "$REPO"
  printf '  "remote_url": "%s",\n' "$REMOTE_URL"
  printf '  "target_sha_arg": "%s",\n' "$SHA_ARG"
  printf '  "target_sha": "%s",\n' "$TARGET_SHA"
  printf '  "anchor_branch": "%s",\n' "$ANCHOR_BRANCH"
  printf '  "anchor_sha": "%s",\n' "${ANCHOR_SHA:-unavailable}"
  printf '  "checks": [\n'
  sed '$ s/,$//' "$TMP_JSON" >> "$REPORT.partial" && cat "$REPORT.partial"
  printf '  ],\n'
  printf '  "summary": {"total": %d, "passed": %d, "failed": %d},\n' "$((PASS+FAIL))" "$PASS" "$FAIL"
  printf '  "verdict": "%s"\n' "$VERDICT"
  printf '}\n'
} > "$REPORT"
rm -f "$REPORT.partial" "$TMP_JSON"

echo "REPORT: $REPORT"
echo "VERDICT: $VERDICT (passed=$PASS failed=$FAIL)"
cat "$REPORT"
exit $RC
