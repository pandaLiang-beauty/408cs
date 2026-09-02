#!/usr/bin/env bash
set -euo pipefail

# cs408 开发启动脚本：后台拉起后端(uvicorn :8408 --reload) 与前端(vite :5408)。
# 兼容 Windows Git Bash(.venv/Scripts) 与 Linux/macOS(.venv/bin) 的虚拟环境路径。

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

# 监听 0.0.0.0：手机要能扫码访问 /u/<token> 上传草稿纸（同一局域网）。
# 想只本机可见就设 STUDY_BACKEND_HOST=127.0.0.1（那时二维码只能自己电脑打开）。
BACKEND_HOST="${STUDY_BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${STUDY_PORT:-8408}"
FRONTEND_PORT="${STUDY_FRONTEND_PORT:-5408}"

# 端口口径：前端 5+科目代码、后端 8+科目代码（408 → 5408/8408），子域能直接推出端口。
# 下面三个变量给 frontend/vite.config.js 用：端口、/api 的代理目标、隧道域名。
# STUDY_PUBLIC_ORIGIN 必须有值——vite 的 allowedHosts 空着时，从 408.xpliang.tech
# 进来的请求会被它当 DNS rebinding 直接 403。后端监听 0.0.0.0，代理仍走 127.0.0.1。
export STUDY_FRONTEND_PORT="$FRONTEND_PORT"
export STUDY_LOCAL_BACKEND="${STUDY_LOCAL_BACKEND:-http://127.0.0.1:$BACKEND_PORT}"
export STUDY_PUBLIC_ORIGIN="${STUDY_PUBLIC_ORIGIN:-https://408.xpliang.tech}"

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

# 谁在监听这个端口。这台机器没有 ss / lsof / fuser，只有 netstat；
# netstat -tlnp 的末列是 "pid/程序名"，取出 pid 部分。没人监听就输出空。
port_pid() {
  netstat -tlnp 2>/dev/null | awk -v p=":$1\$" '
    $1 ~ /^tcp/ && $4 ~ p { split($NF, a, "/"); if (a[1] ~ /^[0-9]+$/) { print a[1]; exit } }'
}

[[ -d "$ROOT_DIR/backend/app" && -d "$ROOT_DIR/frontend/src" ]] || {
  echo "项目结构不完整：$ROOT_DIR (需要 backend/app 与 frontend/src)" >&2
  exit 1
}

# 后端：只在虚拟环境缺失时才建、才装依赖。不要每次启动都 pip install——本机
# /root/.pip/pip.conf 里那个 ga.dp.tech:8118 代理是坏的（返 503），每次装都会失败并
# 把整个脚本带崩（set -e）。真要装时用 PIP_CONFIG_FILE=/dev/null 绕开它走阿里镜像。
if [[ -z "$(venv_python)" ]]; then
  echo "创建虚拟环境 backend/.venv ..."
  "$(select_python)" -m venv "$ROOT_DIR/backend/.venv"
  PY_TMP="$(venv_python)"
  PIP_CONFIG_FILE=/dev/null "$PY_TMP" -m pip install -q --upgrade pip wheel \
    -i https://mirrors.aliyun.com/pypi/simple/
  PIP_CONFIG_FILE=/dev/null "$PY_TMP" -m pip install -q -r "$ROOT_DIR/backend/requirements.txt" \
    -i https://mirrors.aliyun.com/pypi/simple/
fi
PY_BIN="$(venv_python)"
[[ -n "$PY_BIN" ]] || { echo "无法定位虚拟环境 python" >&2; exit 1; }

cd "$ROOT_DIR/backend"
# 起之前先确认端口是空的，理由同前端：端口被别的进程占着时，下面的 curl 探活
# 会被那个进程应答，脚本就会误判"启动成功"。
if [[ -n "$(port_pid "$BACKEND_PORT")" ]]; then
  echo "端口 $BACKEND_PORT 已被 pid $(port_pid "$BACKEND_PORT") 占用。先跑 bash stop-dev.sh" >&2
  exit 1
fi
# setsid + </dev/null：这台机器没有 systemd，全靠手起，进程必须脱离当前终端的会话，
# 否则调用方的 shell 一退就被连带杀掉。就绪判断用 curl 探活（--noproxy '*' 是因为
# /root/.curlrc 里那个代理是坏的），不要用 ss —— 本机没装 ss，只有 netstat。
setsid "$PY_BIN" -m uvicorn app.main:app --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload \
  > "$ROOT_DIR/backend/server.log" 2>&1 < /dev/null &
backend_pid=$!
for _ in $(seq 1 60); do
  ps -p "$backend_pid" >/dev/null 2>&1 || break
  curl --noproxy '*' -fs -o /dev/null "http://127.0.0.1:$BACKEND_PORT/api/health" && break
  sleep 0.5
done
ps -p "$backend_pid" >/dev/null 2>&1 || { echo "后端启动失败（见 backend/server.log）" >&2; exit 1; }
echo "$backend_pid" > "$ROOT_DIR/backend/server.pid"
echo "后端已启动：http://$BACKEND_HOST:$BACKEND_PORT  (pid $backend_pid, 日志 backend/server.log)"

# 前端：依赖已装好就别再跑 npm install（省启动时间，也避开网络抖动）。
# 端口与 /api、/drafts、/u 的代理都在 frontend/vite.config.js 里。
cd "$ROOT_DIR/frontend"
[[ -d node_modules ]] || npm install
[[ -x node_modules/.bin/vite ]] || { echo "缺少 node_modules/.bin/vite（先跑 npm install）" >&2; exit 1; }

# 起之前先确认端口是空的。曾经出过这样一档事：stop-dev 没真正杀干净，5408 上留着
# 一个跑了一整天的旧 vite；新的 vite 静默漂到 5409，而下面的探活 curl 5408 被那个
# 幽灵应答，于是脚本高高兴兴报"启动成功"，隧道那头连的却始终是旧进程。
if [[ -n "$(port_pid "$FRONTEND_PORT")" ]]; then
  echo "端口 $FRONTEND_PORT 已被 pid $(port_pid "$FRONTEND_PORT") 占用。先跑 bash stop-dev.sh" >&2
  exit 1
fi

# 直接调 vite，不经 npm run dev：npm 只是外面一层壳，setsid 记下的 $! 会是 npm 的 pid，
# stop-dev 照着 pid 文件 kill 掉的也是 npm，真正的 vite 就被留下来成了孤儿。
# --strictPort：端口被占就退出，绝不静默换端口——端口口径(5408)是对外契约，
# 前面还有 Cloudflare 按 5408 发布，漂了就等于服务悄悄搬家。
setsid node_modules/.bin/vite --host "${STUDY_FRONTEND_HOST:-127.0.0.1}" \
  --port "$FRONTEND_PORT" --strictPort \
  > "$ROOT_DIR/frontend/server.log" 2>&1 < /dev/null &
frontend_pid=$!
for _ in $(seq 1 60); do
  # 进程先死掉就别再空等满 30 秒。
  ps -p "$frontend_pid" >/dev/null 2>&1 || break
  curl --noproxy '*' -fs -o /dev/null "http://127.0.0.1:$FRONTEND_PORT/" && break
  sleep 0.5
done
ps -p "$frontend_pid" >/dev/null 2>&1 || { echo "前端启动失败（见 frontend/server.log）" >&2; exit 1; }
# 探活过了还不够，得确认 5408 上坐着的确实是我们刚起的这个。
listening_pid="$(port_pid "$FRONTEND_PORT")"
[[ "$listening_pid" == "$frontend_pid" ]] || {
  echo "前端端口 $FRONTEND_PORT 被 pid ${listening_pid:-未知} 占着，不是刚起的 $frontend_pid" >&2
  exit 1
}
echo "$frontend_pid" > "$ROOT_DIR/frontend/server.pid"
echo "前端已启动：http://127.0.0.1:$FRONTEND_PORT  (pid $frontend_pid, 日志 frontend/server.log)"

echo "cs408 dev 已在后台启动。停止：bash stop-dev.sh"
