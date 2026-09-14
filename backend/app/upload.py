"""草稿纸手机上传：电脑端生成二维码 → 手机扫码打开本页 → 拍照/选图上传 → 写回该场做题记录。

安全说明：本模块的两个路由**不走登录鉴权**，凭据是 URL 里的 token——
随机 32 字节、单次可用、10 分钟过期、且只绑定某一份卷的某一道题。
开发期后端需监听 0.0.0.0 手机才能访问（仅限同一局域网）；上线后用 STUDY_PUBLIC_BASE 指向公网域名。
"""
import base64
import binascii
import re
import secrets
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from .config import DRAFTS_DIR, settings
from .db import get_db

router = APIRouter()
TTL_MINUTES = 10


class ImageUploadIn(BaseModel):
    image_base64: str


def _now():
    return datetime.now(timezone.utc)


def draft_state(conn, item_id: int) -> dict:
    rows = conn.execute(
        'SELECT id,stored_name,created_at FROM draft_images WHERE session_item_id=? ORDER BY id',
        (item_id,),
    ).fetchall()
    images = [{
        'id': row['id'],
        # 迁移的旧文件也带稳定版本，避免浏览器继续使用覆盖前的缓存。
        'url': f"/drafts/{Path(row['stored_name']).name}?v={row['id']}",
        'created_at': row['created_at'],
    } for row in rows]
    return {'drafts': images, 'draft_url': images[-1]['url'] if images else ''}


def _decode_image(raw: str):
    raw = raw.split(',', 1)[1] if ',' in raw else raw
    if not raw or len(raw) > 12_000_000:  # ~9MB 图片上限，手机和本机选图共用
        raise HTTPException(status_code=400, detail='图片为空或过大（单张最多 9 MB）')
    try:
        blob = base64.b64decode(re.sub(r'\s+', '', raw), validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail='图片格式不正确')
    signatures = (
        ('.png', blob.startswith(b'\x89PNG\r\n\x1a\n')),
        ('.jpg', blob.startswith(b'\xff\xd8\xff')),
        ('.webp', len(blob) >= 12 and blob[:4] == b'RIFF' and blob[8:12] == b'WEBP'),
        ('.gif', blob.startswith((b'GIF87a', b'GIF89a'))),
    )
    extension = next((ext for ext, matches in signatures if matches), '')
    if not extension:
        raise HTTPException(status_code=400, detail='仅支持 PNG、JPEG、WebP 或 GIF 图片')
    return blob, extension


def save_draft_image(conn, session_id: int, question_id: int, raw: str, token=None) -> dict:
    """两种上传入口都追加独立文件；令牌、图片关联与作答记录一起提交。"""
    it = conn.execute('SELECT id FROM session_items WHERE session_id=? AND question_id=?',
                      (session_id, question_id)).fetchone()
    if not it:
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    blob, extension = _decode_image(raw)
    fname = f's{session_id}_q{question_id}_{secrets.token_hex(12)}{extension}'
    path = DRAFTS_DIR / fname
    now = _now().isoformat()
    written = False
    try:
        with conn:
            if token is not None:
                claimed = conn.execute(
                    'UPDATE draft_tokens SET used_at=? WHERE token=? AND session_id=?'
                    ' AND question_id=? AND used_at IS NULL AND expires_at>?',
                    (now, token, session_id, question_id, now),
                ).rowcount
                if claimed != 1:
                    raise HTTPException(status_code=410, detail='链接已使用或过期，请在电脑上重新生成二维码')
            conn.execute(
                'INSERT INTO draft_images(session_item_id,stored_name,created_at) VALUES(?,?,?)',
                (it['id'], fname, now),
            )
            with path.open('xb') as dest:
                written = True
                dest.write(blob)
            conn.execute('UPDATE session_items SET draft_path=?,updated_at=? WHERE id=?',
                         (fname, now, it['id']))
    except Exception:
        if written:
            path.unlink(missing_ok=True)
        raise
    return {'ok': True, **draft_state(conn, it['id'])}


def lan_ip() -> str:
    """取本机在局域网中的地址（不真的发包，只看内核选的源地址）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 80))
        return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'
    finally:
        s.close()


def public_base() -> str:
    """二维码里用的地址：优先 env 指定的公网地址，否则局域网 IP + 后端端口。"""
    if settings.PUBLIC_BASE:
        return settings.PUBLIC_BASE.rstrip('/')
    return f'http://{lan_ip()}:{settings.PORT}'


def issue_token(conn, session_id: int, question_id: int) -> dict:
    conn.execute('DELETE FROM draft_tokens WHERE expires_at < ?', (_now().isoformat(),))
    token = secrets.token_urlsafe(24)
    exp = (_now() + timedelta(minutes=TTL_MINUTES)).isoformat()
    conn.execute('INSERT INTO draft_tokens(token, session_id, question_id, expires_at)'
                 ' VALUES(?,?,?,?)', (token, session_id, question_id, exp))
    conn.commit()
    return {'token': token, 'url': f'{public_base()}/u/{token}',
            'expires_at': exp, 'ttl_minutes': TTL_MINUTES}


def _load_token(conn, token: str):
    r = conn.execute('SELECT * FROM draft_tokens WHERE token=?', (token,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail='链接无效')
    if r['used_at']:
        raise HTTPException(status_code=410, detail='该链接已使用过，请在电脑上重新生成二维码')
    if r['expires_at'] < _now().isoformat():
        raise HTTPException(status_code=410, detail='链接已过期，请在电脑上重新生成二维码')
    return r


PAGE = """<!doctype html><html lang=zh><head><meta charset=utf-8>
<meta name=viewport content="width=device-width,initial-scale=1">
<title>上传草稿纸</title><style>
body{margin:0;padding:24px;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif;background:#e7e4dd;color:#1c1a17}
.card{max-width:520px;margin:0 auto;background:#fdfdfb;border:1px solid #ddd7cc;border-radius:12px;padding:20px}
h1{font-size:18px;margin:0 0 6px}p.sub{margin:0 0 16px;color:#6d675d;font-size:13px}
label.pick{display:block;padding:14px;border:1px dashed #b04a2f;border-radius:10px;color:#b04a2f;text-align:center;font-weight:600}
input[type=file]{display:none}img{max-width:100%;margin-top:14px;border-radius:8px;border:1px solid #ddd7cc}
button{margin-top:14px;width:100%;padding:13px;border:0;border-radius:10px;background:#b04a2f;color:#fff;font-size:16px;font-weight:600}
button:disabled{opacity:.5}.msg{margin-top:12px;font-size:14px}.ok{color:#2f7d47}.bad{color:#c23b3b}
</style></head><body><div class=card>
<h1>上传草稿纸</h1><p class=sub>__LABEL__</p>
<p class=sub>每次追加一张草稿。继续上传时，请在电脑上重新生成二维码。</p>
<label class=pick for=f>📷 拍照或从相册选择</label>
<input id=f type=file accept="image/png,image/jpeg,image/webp,image/gif">
<img id=pv hidden><button id=go disabled>上传</button><div id=m class=msg></div>
</div><script>
var f=document.getElementById('f'),pv=document.getElementById('pv'),go=document.getElementById('go'),m=document.getElementById('m'),data=null;
f.onchange=function(){var file=f.files[0];if(!file)return;var r=new FileReader();
r.onload=function(){data=r.result;pv.src=data;pv.hidden=false;go.disabled=false;m.textContent='';};r.readAsDataURL(file);};
go.onclick=function(){if(!data)return;go.disabled=true;m.textContent='上传中…';m.className='msg';
fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:data})})
.then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||'上传失败');return j;});})
.then(function(){f.disabled=true;go.textContent='已上传';m.textContent='✓ 已追加草稿，回电脑上看即可。继续上传请扫描新的二维码。';m.className='msg ok';})
.catch(function(e){m.textContent='✗ '+e.message;m.className='msg bad';go.disabled=false;});};
</script></body></html>"""


@router.get('/u/{token}', response_class=HTMLResponse)
def upload_page(token: str, conn=Depends(get_db)):
    r = _load_token(conn, token)
    q = conn.execute('SELECT year, number, qtype, source FROM questions WHERE id=?',
                     (r['question_id'],)).fetchone()
    label = '题目'
    if q:
        origin = f"模拟卷{q['year']}" if q['source'] == 'simulate' else f"{q['year']} 年真题"
        label = f"{origin} · 第 {q['number']} 题"
    return HTMLResponse(PAGE.replace('__LABEL__', label))


@router.post('/u/{token}')
def upload_submit(token: str, body: ImageUploadIn, conn=Depends(get_db)):
    r = _load_token(conn, token)
    return save_draft_image(conn, r['session_id'], r['question_id'], body.image_base64, token)
