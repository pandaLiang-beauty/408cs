#!/usr/bin/env bash
set -euo pipefail

# cs408 生产部署（单机 Linux + systemd）：建虚拟环境、装依赖、导题库、构建前端、安装并重启 cs408.service。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"
BACKEND_HOST="${STUDY_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${STUDY_PORT:-8408}"
SERVICE_NAME="${CS408_SERVICE_NAME:-cs408.service}"
SERVICE_PATH="/etc/systemd/system/$SERVICE_NAME"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi
BACKEND_PORT="${STUDY_PORT:-$BACKEND_PORT}"

select_python() {
  if [[ -n "${STUDY_PYTHON:-}" ]]; then
    echo "$STUDY_PYTHON"
  elif command -v python3 >/dev/null 2>&1; then
    command -v python3
  else
    command -v python
  fi
}

[[ -d "$ROOT_DIR/backend/app" && -d "$ROOT_DIR/frontend/src" ]] || {
  echo "项目结构不完整：$ROOT_DIR" >&2
  exit 1
}

# 1) 后端虚拟环境与依赖。
cd "$ROOT_DIR/backend"
"$(select_python)" -m compileall -q app seed.py
if [[ ! -x .venv/bin/python ]]; then
  "$(select_python)" -m venv .venv
fi
.venv/bin/python -m pip install -q --upgrade pip wheel
.venv/bin/pip install -q -r requirements.txt

# 2) 首次部署才播种题库（数据库已存在则跳过，避免重部署清空练习记录）。
if [[ ! -f data/study.db ]]; then
  .venv/bin/python seed.py
fi

# 3) 构建前端。
cd "$ROOT_DIR/frontend"
npm ci
npm run build

# 4) 以仓库内 cs408.service 为模板安装 systemd unit（按实际根目录 / 端口改写）。
sed -e "s#/root/sysStuByAI/408cs#$ROOT_DIR#g" \
    -e "s#--port 8408#--port $BACKEND_PORT#g" \
    -e "s#STUDY_PORT=8408#STUDY_PORT=$BACKEND_PORT#g" \
    "$ROOT_DIR/cs408.service" > "$SERVICE_PATH"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"

# 5) 健康检查。
for _ in $(seq 1 30); do
  curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health" >/dev/null 2>&1 && break
  sleep 1
done
curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/health"
printf '\n'
echo "deployed cs408: backend http://$BACKEND_HOST:$BACKEND_PORT (service: $SERVICE_NAME)"
