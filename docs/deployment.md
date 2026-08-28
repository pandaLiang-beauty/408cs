# 部署

面向单机 Linux 生产环境：systemd 托管后端，前端构建为静态资源。

## 前置

- Python 3.9+、Node.js 18+/npm。
- 复制并填写环境变量：`cp .env.example .env.local`，至少设置 `STUDY_INITIAL_PASSWORD` 与 `GRADE_API_KEY`。
- **公网部署必须设 `STUDY_PUBLIC_BASE`**（如 `https://cs408.ncnb.me`）。留空时后端会自动探测本机地址写进草稿纸二维码，在云主机上会探测成内网地址（如 `10.x`），手机扫了打不开。
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

默认部署路径为 `/root/cs408`；部署到其他目录时，`deploy.sh` 会按实际根目录改写 unit 中的绝对路径。可用 `STUDY_PROJECT_ROOT` 覆盖根目录、`STUDY_PORT` 覆盖端口。

> 安装 systemd unit 需要 root 权限（写入 `/etc/systemd/system/`）。

## 服务管理

```bash
systemctl status cs408.service
journalctl -u cs408.service -f
systemctl restart cs408.service
```

## 现网部署（193.112.97.187 · Cloudflare Tunnel）

实际线上环境与上面的 `deploy.sh` 有两点不同，按这套走：

| | 值 |
|---|---|
| 域名 | `https://cs408.ncnb.me`（Cloudflare Tunnel，面板配 ingress → `http://127.0.0.1:8104`） |
| 服务 | `cs408v2.service`，监听 `127.0.0.1:8104` |
| 代码 | 裸仓库 `/root/git/cs408v2.git` → 工作目录 `/root/cs408-v2` |
| 解释器 | 系统只有 Python 3.9.12，**代码须保持 3.9 兼容**（不可用 `str | None` 这类 PEP 604 写法） |

两条硬约束：

- **前端在本地构建**，只上传 `frontend/dist`。服务器仅约 1.3G 可用内存，在上面跑 `npm run build` 有 OOM 风险，因此**不要在现网执行 `deploy.sh`**（它会构建前端）。
- 隧道只暴露一个端口，故前端由后端托管（见 `app/main.py` 末尾的 SPA 回落），不经 nginx 或 `study-entry` 网关。

更新流程：

```bash
# 本地
npm --prefix frontend run build
git commit -am "..." && git bundle create /tmp/cs408v2.bundle --all
# 上传 bundle 与 dist 后，在服务器执行
git --git-dir=/root/git/cs408v2.git fetch /tmp/cs408v2.bundle master:master
git --git-dir=/root/git/cs408v2.git --work-tree=/root/cs408-v2 checkout -f master
systemctl restart cs408v2
```

`/root/cs408`、`/root/english`、`/root/math` 与 `pro-study-platform-*` 服务属于旧系统，部署时不要触碰。
