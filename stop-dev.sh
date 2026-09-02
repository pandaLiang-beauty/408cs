#!/usr/bin/env bash
# 停止开发用的后端(uvicorn :8408) 与前端(vite :5408)。
# 不用 set -e：允许部分目标本就未运行。兼容 Windows Git Bash 与 Linux/macOS。
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

BACKEND_PORT="${STUDY_PORT:-8408}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5408}"

kill_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if command -v taskkill >/dev/null 2>&1; then
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
  else
    # start-dev 用 setsid 起的进程是自己进程组的组长，负号一起收掉它的子进程
    # （vite 会拉起 esbuild，uvicorn --reload 会拉起 worker）。组杀不成再退回单杀。
    kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  fi
}

# 谁在监听这个端口（同 start-dev.sh 的 port_pid）。本机只有 netstat。
port_pid() {
  netstat -tlnp 2>/dev/null | awk -v p=":$1\$" '
    $1 ~ /^tcp/ && $4 ~ p { split($NF, a, "/"); if (a[1] ~ /^[0-9]+$/) { print a[1]; exit } }'
}

# 通过 pid 文件停止（start-dev.sh 写入）。
for pid_file in "$ROOT_DIR/backend/server.pid" "$ROOT_DIR/frontend/server.pid"; do
  if [[ -s "$pid_file" ]]; then
    pid="$(tr -cd '0-9' < "$pid_file")"
    if [[ -n "$pid" ]]; then
      kill_pid "$pid"
      echo "stopped pid $pid ($pid_file)"
    fi
    rm -f "$pid_file"
  fi
done

# 按端口兜底清理。原来这里依次探 taskkill / fuser / lsof——这台机器一个都没有，
# 三个分支全部落空，整个函数是个无声的空操作。5408 上那个跑了一整天的幽灵 vite
# 就是这么活下来的：pid 文件记的是 npm 的 pid，杀了壳留下真身，兜底又不生效。
# 本机只有 netstat，就按 netstat 来。
kill_port() {
  local port="$1" pid tries
  for tries in 1 2 3 4 5 6 7 8 9 10; do
    pid="$(port_pid "$port")"
    [[ -n "$pid" ]] || return 0
    kill_pid "$pid"
    echo "killed pid $pid (:$port)"
    sleep 0.3
  done
  # 十轮还没放手就上 SIGKILL。
  pid="$(port_pid "$port")"
  if [[ -n "$pid" ]]; then
    kill -9 -- "-$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
    echo "force-killed pid $pid (:$port)"
  fi
}

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

# 收尾核对：端口真空了才算停成功，别再让脚本报喜不报忧。
leftover=""
for port in "$BACKEND_PORT" "$FRONTEND_PORT"; do
  pid="$(port_pid "$port")"
  [[ -n "$pid" ]] && leftover="$leftover :$port(pid $pid)"
done
if [[ -n "$leftover" ]]; then
  echo "cs408 dev 未完全停止，仍在监听:$leftover" >&2
  exit 1
fi

echo "cs408 dev 已停止 (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT)。"
