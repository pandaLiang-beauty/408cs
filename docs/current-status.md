# 当前状态

_更新于 2026-08-28_

- 阶段：本地生产级已就绪（扁平后端、单用户登录、强化池 SRS、大题 AI 批改均已跑通验收）。
- 题库：**717 道选择题 + 126 道大题**（主观题）；原始试卷 HTML 见 `backend/data/raw/`（2009–2026，18 套）。
- 批改：主观大题接入 vyceai `gpt-5.6-luna` 批改网关。
- 端口：后端 `127.0.0.1:8408`，前端开发 `127.0.0.1:3000`。
- 数据：SQLite `backend/data/study.db`。

## 边界提示

- 本仓库为独立 cs408，勿从 `/root/sysStuByAI/204english`、`/root/sysStuByAI/302math`、`pro-study-platform` 或 `_reference` 引入代码或数据。
