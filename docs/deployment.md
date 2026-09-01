# 部署

面向单机 Linux 生产环境：systemd 托管后端，前端构建为静态资源。

## 前置

- Python 3.9+、Node.js 18+/npm。
- 复制并填写环境变量：`cp .env.example .env.local`，至少设置 `STUDY_INITIAL_PASSWORD` 与 `GRADE_API_KEY`。
- **公网部署必须设 `STUDY_PUBLIC_BASE`**（如 `https://408.xpliang.tech`）。留空时后端会自动探测本机地址写进草稿纸二维码，在云主机上会探测成内网地址（如 `10.x`），手机扫了打不开。
- 校验环境：`bash check-env.sh`。

## 一键部署

```bash
bash deploy.sh
```

`deploy.sh` 会依次：

1. 在 `backend/.venv` 创建虚拟环境并安装 `backend/requirements.txt`；
2. 仅当 `backend/data/study.db` 不存在时，运行一次 `backend/seed.py` 播种题库（重部署不会清空练习记录）；
3. 在 `frontend/` 执行 `npm ci && npm run build`；
4. 以仓库内 `cs408.service` 为模板安装到 `/etc/systemd/system/cs408.service`，并 `daemon-reload`、`enable`、`restart`；
5. 轮询 `http://127.0.0.1:8408/api/health` 做健康检查。

默认部署路径为 `/root/sysStuByAI/408cs`；部署到其他目录时，`deploy.sh` 会按实际根目录改写 unit 中的绝对路径。可用 `STUDY_PROJECT_ROOT` 覆盖根目录、`STUDY_PORT` 覆盖端口。

> 安装 systemd unit 需要 root 权限（写入 `/etc/systemd/system/`）。

## 服务管理

```bash
systemctl status cs408.service
journalctl -u cs408.service -f
systemctl restart cs408.service
```

## Cloudflare Tunnel：选择一种入口模式

当前公网域名为 `https://408.xpliang.tech`。开发预览与生产部署的 Tunnel 指向不同端口，**只能按实际运行模式选择其一，不能混用**。

| 模式 | 本机进程 | Cloudflare Tunnel ingress | 适用场景 |
|---|---|---|---|
| 开发 / 临时预览 | Vite `127.0.0.1:5408`，并代理 API 到后端 `127.0.0.1:8408` | `http://127.0.0.1:5408` | 运行 `bash start-dev.sh`，需要热更新 |
| 构建后单端口 | Uvicorn `127.0.0.1:8408`，直接托管 `frontend/dist` | `http://127.0.0.1:8408` | systemd 稳定运行 |

开发模式：

```bash
STUDY_PUBLIC_ORIGIN=https://408.xpliang.tech bash start-dev.sh
```

`start-dev.sh` 会配置 Vite 接受该 Tunnel Host，并让 `/api`、`/drafts`、`/u` 转发给 `8408`。开发预览时若 Tunnel 指向 `8408`，会绕过 Vite（只会得到旧的构建产物或 404）；构建后单端口运行时若 Tunnel 仍指向 `5408`，则会出现 Cloudflare 502。

构建后单端口模式：

```bash
cd frontend && npm run build
systemctl restart cs408.service
```

FastAPI 在检测到 `frontend/dist` 后会提供 SPA 静态文件和 history 路由回落；此时 Tunnel 必须指向 `8408`。公网二维码还需在 `.env.local` 设置：

```bash
STUDY_PUBLIC_BASE=https://408.xpliang.tech
```

此前文档中的 `cs408.ncnb.me`、`8104`、`cs408v2.service` 与 `/root/cs408-v2` 均为历史环境记录，不适用于本仓库，不能作为部署命令执行。
