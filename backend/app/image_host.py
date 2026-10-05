"""独立图床：登录后上传、查看列表，随机图片直链可用于 Markdown。"""
import secrets
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import auth
from .config import IMAGE_HOST_DIR, settings
from .db import get_db
from .upload import _decode_image

router = APIRouter(prefix='/api/image-host')
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MIME_TYPES = {'.png': 'image/png', '.jpg': 'image/jpeg',
              '.webp': 'image/webp', '.gif': 'image/gif'}


class HostedImageIn(BaseModel):
    image_base64: str
    filename: str = ''


def _image_row(row):
    url = f"/api/image-host/files/{row['stored_name']}"
    return {
        'id': row['id'], 'filename': row['original_name'],
        'mime_type': row['mime_type'], 'size_bytes': row['size_bytes'],
        'created_at': row['created_at'], 'url': url,
        # 无公网配置的开发环境由浏览器补全当前站点地址，避免返回代理后的后端端口。
        'public_url': settings.PUBLIC_BASE.rstrip('/') + url if settings.PUBLIC_BASE else url,
    }


@router.get('')
def list_images(before_id: Optional[int] = Query(None, ge=1), limit: int = Query(48, ge=1, le=100),
                conn=Depends(get_db), _=Depends(auth.require_user)):
    rows = conn.execute(
        'SELECT * FROM hosted_images WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT ?',
        (before_id, before_id, limit + 1),
    ).fetchall()
    return {'images': [_image_row(row) for row in rows[:limit]],
            'next_cursor': rows[limit - 1]['id'] if len(rows) > limit else None}


@router.post('', status_code=201)
def upload_image(body: HostedImageIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    raw = body.image_base64
    encoded = raw.split(',', 1)[-1]
    if len(encoded) > ((MAX_IMAGE_BYTES + 2) // 3) * 4:
        raise HTTPException(status_code=413, detail='单张图片不能超过 8 MB')
    blob, extension = _decode_image(raw)
    if len(blob) > MAX_IMAGE_BYTES:
        raise HTTPException(status_code=413, detail='单张图片不能超过 8 MB')
    safe_name = Path(body.filename.replace('\\', '/')).name
    safe_name = ''.join(char for char in safe_name if char.isprintable())[:200]
    filename = safe_name or f'图片{extension}'
    stored_name = secrets.token_hex(24) + extension
    path = IMAGE_HOST_DIR / stored_name
    written = False
    try:
        with conn:
            cursor = conn.execute(
                'INSERT INTO hosted_images(stored_name,original_name,mime_type,size_bytes) VALUES(?,?,?,?)',
                (stored_name, filename, MIME_TYPES[extension], len(blob)),
            )
            with path.open('xb') as dest:
                written = True
                dest.write(blob)
            row = conn.execute('SELECT * FROM hosted_images WHERE id=?', (cursor.lastrowid,)).fetchone()
    except Exception:
        if written:
            path.unlink(missing_ok=True)
        raise
    return _image_row(row)


@router.get('/files/{stored_name}')
def view_image(stored_name: str, conn=Depends(get_db)):
    # 不依赖会话 Cookie，保证复制的链接在 Markdown 和其他设备中也能显示。
    # 只有上传和列表需要登录；文件使用 192 位随机名称，不暴露递增 ID 或原始文件名。
    row = conn.execute('SELECT * FROM hosted_images WHERE stored_name=?', (stored_name,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='图片不存在')
    path = IMAGE_HOST_DIR / row['stored_name']
    if not path.is_file():
        raise HTTPException(status_code=404, detail='图片文件不存在')
    return FileResponse(path, media_type=row['mime_type'], headers={
        'Cache-Control': 'public, max-age=31536000, immutable',
        'X-Content-Type-Options': 'nosniff',
    })
