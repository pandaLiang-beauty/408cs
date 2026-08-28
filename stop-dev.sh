#!/usr/bin/env bash
# 停止开发用的后端(uvicorn :8408) 与前端(vite :3000)。
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
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-3000}"

kill_pid() {
  local pid="$1"
  [[ -n "$pid" ]] || return 0
  if command -v taskkill >/dev/null 2>&1; then
    taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
  else
    kill "$pid" >/dev/null 2>&1 || true
  fi
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

# 按端口兜底清理（兼容 Windows netstat 与 Linux fuser/lsof）。
kill_port() {
  local port="$1"
  if command -v taskkill >/dev/null 2>&1 && command -v netstat >/dev/null 2>&1; then
    netstat -ano 2>/dev/null \
      | grep -E "[:.]${port}[[:space:]].*LISTENING" \
      | awk '{print $NF}' | sort -u \
      | while read -r pid; do
          [[ -n "$pid" ]] && taskkill //F //T //PID "$pid" >/dev/null 2>&1 || true
        done
  elif command -v fuser >/dev/null 2>&1; then
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -ti tcp:"$port" 2>/dev/null | xargs -r kill 2>/dev/null || true
  fi
}

kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"

echo "cs408 dev 已停止 (backend :$BACKEND_PORT, frontend :$FRONTEND_PORT)。"
