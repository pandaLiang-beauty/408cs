# 当前状态

_更新于 2026-09-18_

- 阶段：本地生产级已就绪（扁平后端、单用户登录、强化池 SRS、大题 AI 批改均已跑通验收）。
- 题库：真题 **720 道选择题 + 126 道综合题**（2009–2026，18 套），模拟题 **240 + 42**（6 套），经典练习 **1057 + 11**（24 个专题）。经典题已接入强化选题，详见 [经典练习说明](classic-exercises.md)。
- 批改：当前使用 `https://api.ncnb.me/v1` 的 `gemini-3.8-flash-high`（「Gemini 3.8 Flash High (ncnb)」配置档，可在设置中切换；[模型实测对比](model-comparison-2026-09-16.md)）。前端等待覆盖后端的 120 秒批改窗口；失败保留已提交作答，重试恢复已完成结果，分数和参考答案支持刷新恢复。
- 复盘：交卷后支持选中文字添加边栏批注、整题批注及原文定位，批注按每次作答独立保存，详见 [复盘批注说明](review-annotations.md)。
- 运行方式：静态前端由单个 Uvicorn 进程托管，无 Vite 常驻进程、无自动重载；`bash start-prod.sh` 启动，`bash stop-dev.sh` 停止。
- 端口：当前进程同时监听 `127.0.0.1:5408` / `127.0.0.1:8408`，两个入口均提供页面和 API，Cloudflare Tunnel 可继续指向 `5408`。
- 数据：SQLite `backend/data/study.db`。

## 边界提示

- 本仓库为独立 cs408，勿从 `/root/sysStuByAI/204english`、`/root/sysStuByAI/302math`、`pro-study-platform` 或 `_reference` 引入代码或数据。
