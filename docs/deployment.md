# 部署

面向单机 Linux 生产环境：systemd 托管后端，前端构建为静态资源。

## 前置

- Python 3.9+、Node.js 18+/npm。
- 复制并填写环境变量：`cp .env.example .env.local`，至少设置 `STUDY_INITIAL_PASSWORD` 与 `GRADE_API_KEY`。
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
