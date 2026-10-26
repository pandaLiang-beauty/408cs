#!/usr/bin/env bash
set -euo pipefail

# 无 systemd 的 Linux 环境：运行已构建的前端，单个后端进程监听 5408 / 8408。
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"
if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

PY_BIN="$ROOT_DIR/backend/.venv/bin/python"
BACKEND_PORT="${STUDY_PORT:-8408}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5408}"
PID_FILE="$ROOT_DIR/backend/server.pid"
[[ -x "$PY_BIN" ]] || { echo "缺少 backend/.venv/bin/python，请先安装后端依赖。" >&2; exit 1; }
[[ -f "$ROOT_DIR/frontend/dist/index.html" ]] || {
  echo "缺少静态构建，请先在 frontend 执行 npm run build。" >&2
  exit 1
}
for tool in setsid netstat curl; do
  command -v "$tool" >/dev/null || { echo "缺少命令：$tool" >&2; exit 1; }
done

port_pid() {
  netstat -tlnp 2>/dev/null | awk -v p=":$1\$" '
    $1 ~ /^tcp/ && $4 ~ p { split($NF, a, "/"); if (a[1] ~ /^[0-9]+$/) { print a[1]; exit } }'
}
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  owner="$(port_pid "$port")"
  [[ -z "$owner" ]] || {
    echo "端口 $port 已被 pid $owner 占用。请先运行 bash stop-dev.sh。" >&2
    exit 1
  }
done

cd "$ROOT_DIR/backend"
setsid "$PY_BIN" "$ROOT_DIR/serve.py" >> "$ROOT_DIR/backend/server.log" 2>&1 < /dev/null &
server_pid=$!
ready=0
cleanup_failed_start() {
  if [[ "$ready" == 0 ]]; then
    kill -- "-$server_pid" 2>/dev/null || kill "$server_pid" 2>/dev/null || true
    if [[ -f "$PID_FILE" && "$(cat "$PID_FILE")" == "$server_pid" ]]; then
      rm -f "$PID_FILE"
    fi
  fi
}
trap cleanup_failed_start EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
echo "$server_pid" > "$PID_FILE"

for _ in $(seq 1 60); do
  kill -0 "$server_pid" 2>/dev/null || break
  if curl -q --noproxy '*' -fs --max-time 1 -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" &&
     curl -q --noproxy '*' -fs --max-time 1 -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/" &&
     [[ "$(port_pid "$BACKEND_PORT")" == "$server_pid" &&
        "$(port_pid "$FRONTEND_PORT")" == "$server_pid" ]]; then
    ready=1
    break
  fi
  sleep 0.5
done
[[ "$ready" == 1 ]] || { echo "启动失败，见 backend/server.log。" >&2; exit 1; }
echo "cs408 静态模式已启动：单进程 pid $server_pid，入口 :$FRONTEND_PORT / :$BACKEND_PORT。"
echo "日志：backend/server.log；停止：bash stop-dev.sh。"
