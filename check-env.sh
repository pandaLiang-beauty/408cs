#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="${STUDY_PROJECT_ROOT:-$SCRIPT_DIR}"

if [[ -f "$ROOT_DIR/.env.local" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "$ROOT_DIR/.env.local"
  set +a
fi

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

missing=0
warn=0

ok()      { echo -e "${GREEN}✓ $1${NC}"; }
warning() { echo -e "${YELLOW}⚠ $1${NC}"; warn=1; }
bad()     { echo -e "${RED}✗ $1${NC}"; missing=1; }

echo "检查 cs408 运行环境..."

# Python 3.9+（Windows 上可能是 python，Linux 上是 python3）。
python_bin=""
for cand in "${STUDY_PYTHON:-}" python3 python; do
  [[ -n "$cand" ]] || continue
  if command -v "$cand" >/dev/null 2>&1; then
    python_bin="$(command -v "$cand")"
    break
  fi
done
if [[ -n "$python_bin" ]] && "$python_bin" - <<'PY'
import sys
raise SystemExit(0 if sys.version_info >= (3, 9) else 1)
PY
then
  ok "Python 可用: $("$python_bin" --version 2>&1)"
else
  bad "未找到 Python 3.9+（需要 python3 或 python）。"
fi

# Node.js + npm。
if command -v node >/dev/null 2>&1; then
  ok "Node 可用: $(node --version)"
else
  bad "未找到 node，需要 Node.js 18+。"
fi
if command -v npm >/dev/null 2>&1; then
  ok "npm 可用: $(npm --version)"
else
  bad "未找到 npm。"
fi

# .env.local 及必需密钥。
if [[ -f "$ROOT_DIR/.env.local" ]]; then
  ok ".env.local 存在"
else
  bad ".env.local 不存在；请执行 cp .env.example .env.local 并填写密钥。"
fi

for var in STUDY_INITIAL_PASSWORD GRADE_API_KEY; do
  if [[ -n "${!var:-}" ]]; then
    ok "$var 已设置"
  else
    bad "$var 未设置（在 .env.local 中填写）。"
  fi
done

# 可选但推荐的项。
for var in GRADE_BASE_URL GRADE_MODEL SESSION_SECRET; do
  if [[ -n "${!var:-}" ]]; then
    ok "$var 已设置"
  else
    warning "$var 未设置（批改 / 会话相关，建议设置）。"
  fi
done

# 提示仍为占位符的敏感项。
for var in STUDY_INITIAL_PASSWORD SESSION_SECRET; do
  if [[ "${!var:-}" == "change-me" ]]; then
    warning "$var 仍为占位符 change-me，请改为真实值。"
  fi
done

ok "数据库模式: SQLite (backend/data/study.db)"

echo ""
if [[ "$missing" -eq 1 ]]; then
  echo -e "${RED}环境检查未通过。${NC}"
  exit 1
fi
if [[ "$warn" -eq 1 ]]; then
  echo -e "${YELLOW}环境检查通过，但存在警告。${NC}"
else
  echo -e "${GREEN}环境检查通过。${NC}"
fi
