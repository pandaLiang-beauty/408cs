# 架构

cs408 是一个独立仓库的单用户考研 408 做题应用，前后端只服务 408 业务。

## 结构

单科目、单用户，后端刻意**扁平**，不做 monorepo 那套 platform/业务 分层：

- `backend/app/`：`config`(环境) / `db`(SQLite) / `auth`(单用户登录·会话) / `schema`(建表) / `scheduler`(强化池 SRS) / `grading`(AI 批改网关+rubric) / `api`(路由+内联查询) / `main`(入口)。
- `backend/seed.py`：一次性题库播种脚本（解析 `data/raw/*.html` → `study.db`），非常规流程。
- `frontend/src/`：前端。`api/`（含 `api/cs408/`）为接口层，`components/`、`views/`、`stores/` 为界面与状态。

## 数据

- 单一 SQLite 数据库 `backend/data/study.db`（WAL 模式，`*.db-wal` / `*.db-shm` 为运行期边车文件）。
- 题库原始 HTML 位于 `backend/data/raw/`（2009–2026），草稿位于 `backend/data/drafts/`，均不入版本控制。

## 登录

- 单用户。首次启动用 `STUDY_INITIAL_PASSWORD` 创建账号，会话由 `SESSION_SECRET` 签名的 Cookie 维持。

## 批改网关

- 主观大题判分经 AI 网关（`app/grading.py`）转发至 vyceai（OpenAI 兼容），模型 `gpt-5.6-luna`，配置见 `GRADE_BASE_URL` / `GRADE_API_KEY` / `GRADE_MODEL`。

## 强化池（SRS）

- 错题与薄弱题进入强化池，按间隔重复（SRS）安排复习：做对延长间隔，做错缩短并重排，形成个性化的复盘队列。
