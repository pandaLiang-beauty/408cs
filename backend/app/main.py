"""FastAPI 入口：初始化库、挂路由、草稿静态、统一错误为 {error}。"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import auth, schema
from .api import router
from .upload import router as upload_router
from .annotations import router as annotation_router
from .image_host import router as image_host_router
from .config import DIST_DIR, DRAFTS_DIR, settings
from .db import connect
from . import llmconfig


def _init_and_seed() -> None:
    """建表；用 .env.local 的 STUDY_INITIAL_PASSWORD 同步单用户密码（env 为准）；首次播种大模型配置。"""
    with connect() as conn:
        schema.initialize(conn)
        if settings.INITIAL_PASSWORD:
            h = auth.hash_password(settings.INITIAL_PASSWORD)
            row = conn.execute('SELECT id FROM users ORDER BY id LIMIT 1').fetchone()
            if row:
                conn.execute('UPDATE users SET password_hash=? WHERE id=?', (h, row['id']))
            else:
                conn.execute("INSERT INTO users(name, password_hash) VALUES('me', ?)", (h,))
            conn.commit()
        llmconfig.migrate_and_seed(conn)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _init_and_seed()
    yield


app = FastAPI(title='cs408', lifespan=lifespan)


@app.exception_handler(HTTPException)
async def _http_exc(request, exc: HTTPException):
    return JSONResponse({'error': exc.detail}, status_code=exc.status_code)


app.include_router(router)
app.include_router(upload_router)
app.include_router(annotation_router)
app.include_router(image_host_router)
app.mount('/drafts', StaticFiles(directory=str(DRAFTS_DIR)), name='drafts')

# 生产单端口：前端 dist 由后端托管。必须最后注册——前面的 /api、/drafts、/u 先匹配，
# 剩下的路径命中静态文件就返回文件，否则回落 index.html（Vue history 模式深链接）。
if DIST_DIR.is_dir():
    @app.get('/{full_path:path}', include_in_schema=False)
    def _spa(full_path: str):
        target = (DIST_DIR / full_path).resolve()
        if full_path and target.is_file() and DIST_DIR.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(DIST_DIR / 'index.html')
