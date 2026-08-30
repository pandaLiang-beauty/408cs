# AGENTS.md

## 仓库边界

- 本仓库 `408cs` 是独立的单用户考研 408 做题系统（生产默认路径 `/root/sysStuByAI/408cs`）。
- 后端业务代码在扁平的 `backend/app/`（不做多层分包——单科目、单用户，不需要 monorepo 那套 platform/业务 分层）。
- 业务前端代码属于 `frontend/src/`（接口层在 `frontend/src/api/cs408/`）。
- 题库播种脚本是 `backend/seed.py`（一次性，非常规流程）。
- 绝不从 `/root/sysStuByAI/204english`、`/root/sysStuByAI/302math`、`pro-study-platform`（含任何 `pro-study-platform-*`）或 `_reference` 引入代码、数据或配置。
- 不添加指向仓库外代码、数据、环境、媒体或配置的符号链接。
- 不新增其他学科目录或学科切换层。

## 目录

- `backend/app/`：扁平后端。`config`(环境) / `db` / `auth`(单用户登录) / `schema`(建表) / `scheduler`(强化池 SRS) / `grading`(AI 批改) / `api`(路由+内联查询) / `main`(入口)。
- `backend/seed.py`：一次性题库播种（解析 `data/raw/*.html` → `study.db`）。
- `frontend/src/`：前端界面、状态与接口层。

## 端口

- 后端：`127.0.0.1:8408`
- 前端（开发）：`127.0.0.1:3000`

## Verification

依次运行：

1. `cd backend && python -m compileall -q app seed.py`
2. `cd frontend && npm run build`
3. `curl -fsS http://127.0.0.1:8408/api/health`
