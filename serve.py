"""用一个 Uvicorn 进程提供静态前端和 API，保留 5408 / 8408 两个入口。"""
import logging
import os
import socket
import sys
from contextlib import ExitStack
from pathlib import Path

import uvicorn

ROOT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT_DIR / 'backend'))

from app.config import DIST_DIR, settings


def main() -> None:
    if not (DIST_DIR / 'index.html').is_file():
        raise SystemExit('缺少 frontend/dist/index.html，请先在 frontend 执行 npm run build。')

    backend_host = os.environ.get('STUDY_BACKEND_HOST', '127.0.0.1')
    endpoints = dict.fromkeys([
        (backend_host, settings.PORT),
        (os.environ.get('STUDY_FRONTEND_HOST', '127.0.0.1'),
         int(os.environ.get('STUDY_FRONTEND_PORT', '5408'))),
    ])
    config = uvicorn.Config(
        'app.main:app', host=backend_host, port=settings.PORT,
        workers=1, reload=False,
    )

    # 先取得全部监听端口，再启动应用；任一端口冲突都会退出并释放已取得的 socket。
    # 两个入口共用同一个应用和数据库连接逻辑，不需要常驻 Vite 或另加代理进程。
    with ExitStack() as stack:
        sockets = []
        for host, port in endpoints:
            family = socket.AF_INET6 if ':' in host else socket.AF_INET
            try:
                sock = stack.enter_context(socket.create_server((host, port), family=family))
            except OSError as exc:
                raise SystemExit(f'无法监听 {host}:{port}: {exc}') from exc
            sockets.append(sock)
            logging.getLogger('uvicorn.error').info('静态前端与 API 入口：http://%s:%s', host, port)

        server = uvicorn.Server(config)
        server.run(sockets=sockets)
        if not server.started:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
