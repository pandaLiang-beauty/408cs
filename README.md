# 考研 408 做题

单用户的考研 408（计算机学科专业基础综合）做题与复盘工具。架构见 [`docs/architecture.md`](docs/architecture.md)，部署见 [`docs/deployment.md`](docs/deployment.md)，进展见 [`docs/current-status.md`](docs/current-status.md)。

## 技术栈

- 后端：FastAPI + Uvicorn（`127.0.0.1:8408`）
- 前端：Vue 3 + Vite（开发 `127.0.0.1:5408`）
- 数据库：SQLite（`backend/data/study.db`）
- 批改：可切换的 AI 网关（OpenAI / Anthropic / Responses 兼容格式，当前模型见「设置」）

## 安装

需要 Python 3.9+ 与 Node.js 18+/npm。

```bash
cp .env.example .env.local
# 编辑 .env.local，至少设置 STUDY_INITIAL_PASSWORD 与 GRADE_API_KEY
bash check-env.sh
```

## 运行（开发）

```bash
bash start-dev.sh   # 后台启动后端(:8408 --reload) 与前端(:5408)
```

打开 `http://127.0.0.1:5408/`。停止：

```bash
bash stop-dev.sh
```

脚本兼容 Windows Git Bash（`.venv/Scripts`）与 Linux/macOS（`.venv/bin`）两种虚拟环境路径。

## 构建 / 部署

当前服务器没有 systemd，使用静态模式：前端构建后由一个 Uvicorn 进程托管，
同时提供 `5408` / `8408` 两个入口，无 Vite 常驻进程、无 `--reload`。
Cloudflare Tunnel 可以继续指向 `5408`。

```bash
(cd frontend && npm run build -- --emptyOutDir false)
bash stop-dev.sh
bash start-prod.sh
```

访问地址保持 `http://127.0.0.1:5408/`；停止仍用 `bash stop-dev.sh`。
修改前端后需要重新构建，修改后端后需要重启；日常使用无需运行开发服务。

单机生产部署（创建虚拟环境、导入题库、构建前端、安装并重启 `cs408.service`）：

```bash
bash deploy.sh
```

详见 [`docs/deployment.md`](docs/deployment.md)。

## 备份

数据库为 SQLite。停止服务后可直接复制，或用 SQLite 在线备份（含 WAL 内容，无需停服）：

```bash
sqlite3 backend/data/study.db ".backup 'backend/data/study.backup-$(date +%Y%m%d-%H%M%S).db'"
```

`backend/data/raw/`（题库原始 HTML）、`backend/data/drafts/`（草稿）、
`backend/data/note_images/`（笔记图片）与 `backend/data/image_host/`（图床图片）不入版本库，如需保留请另行备份。

强化题库已接入 CSGraduates 的经典练习，支持专题来源和交卷后解析。导入数量、选题优先级及增量导入命令见 [经典练习说明](docs/classic-exercises.md)。

交卷后可选中题干、选项或解析文字，在右侧边栏添加复盘批注；每次作答独立保存。使用方法见 [复盘批注说明](docs/review-annotations.md)。

左上角「图床」会在当前页面弹出快捷浮层，可上传、粘贴或拖入图片，复制直链或 Markdown 图片链接后继续写批注。使用与备份见 [图床说明](docs/image-host.md)。
