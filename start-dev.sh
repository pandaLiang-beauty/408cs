#!/usr/bin/env bash
set -euo pipefail

# cs408 开发启动脚本：后台拉起后端(uvicorn :8408 --reload) 与前端(vite :3000)。
# 兼容 Windows Git Bash(.venv/Scripts) 与 Linux/macOS(.venv/bin) 的虚拟环境路径。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_PORT:-8408}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-3000}"  # 前端端口在 frontend/vite.config.js 中固定为 3000

# 用于创建虚拟环境的基础解释器。
select_python() {
  if [[ -n "${STUDY_PYTHON:-}" ]]; then
    echo "$STUDY_PYTHON"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  elif command -v python >/dev/null 2>&1; then
    command -v python
  else
    echo "未找到 python3/python" >&2
    exit 1
  fi
}

# 解析虚拟环境内的 python：Windows 为 .venv/Scripts，POSIX 为 .venv/bin。
venv_python() {
  local base="$ROOT_DIR/backend/.venv"
  if [[ -x "$base/Scripts/python.exe" ]]; then
    echo "$base/Scripts/python.exe"
  elif [[ -x "$base/Scripts/python" ]]; then
    echo "$base/Scripts/python"
  elif [[ -x "$base/bin/python" ]]; then
    echo "$base/bin/python"
  fi
}

[[ -d "$ROOT_DIR/backend/app" && -d "$ROOT_DIR/frontend/src" ]] || {
  echo "项目结构不完整：$ROOT_DIR (需要 backend/app 与 frontend/src)" >&2
  exit 1
}

# 后端：首次运行创建虚拟环境，然后安装/更新依赖。
if [[ -z "$(venv_python)" ]]; then
  echo "创建虚拟环境 backend/.venv ..."
  "$(select_python)" -m venv "$ROOT_DIR/backend/.venv"
  "$(venv_python)" -m pip install -q --upgrade pip wheel
fi
PY_BIN="$(venv_python)"
[[ -n "$PY_BIN" ]] || { echo "无法定位虚拟环境 python" >&2; exit 1; }
"$PY_BIN" -m pip install -q -r "$ROOT_DIR/backend/requirements.txt"

cd "$ROOT_DIR/backend"
"$PY_BIN" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
  > "$ROOT_DIR/backend/server.log" 2>&1 &
echo $! > "$ROOT_DIR/backend/server.pid"
echo "后端启动中：http://$BACKEND_HOST:$BACKEND_PORT  (日志 backend/server.log)"

# 前端：安装依赖并启动 Vite（端口与 /api 代理见 frontend/vite.config.js）。
cd "$ROOT_DIR/frontend"
npm install
npm run dev > "$ROOT_DIR/frontend/server.log" 2>&1 &
echo $! > "$ROOT_DIR/frontend/server.pid"
echo "前端启动中：http://127.0.0.1:$FRONTEND_PORT  (日志 frontend/server.log)"

echo "cs408 dev 已在后台启动。停止：bash stop-dev.sh"
