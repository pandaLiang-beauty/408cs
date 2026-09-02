"""草稿纸手机上传：电脑端生成二维码 → 手机扫码打开本页 → 拍照/选图上传 → 写回该场做题记录。

安全说明：本模块的两个路由**不走登录鉴权**，凭据是 URL 里的 token——
随机 32 字节、单次可用、10 分钟过期、且只绑定某一份卷的某一道题。
开发期后端需监听 0.0.0.0 手机才能访问（仅限同一局域网）；上线后用 STUDY_PUBLIC_BASE 指向公网域名。
"""
import base64
import re
import secrets
import socket
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse

from .config import DRAFTS_DIR, settings
from .db import get_db

router = APIRouter()
TTL_MINUTES = 10


def _now():
    return datetime.now(timezone.utc)


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
<label class=pick for=f>📷 拍照或从相册选择</label>
<input id=f type=file accept="image/*">
<img id=pv hidden><button id=go disabled>上传</button><div id=m class=msg></div>
</div><script>
var f=document.getElementById('f'),pv=document.getElementById('pv'),go=document.getElementById('go'),m=document.getElementById('m'),data=null;
f.onchange=function(){var file=f.files[0];if(!file)return;var r=new FileReader();
r.onload=function(){data=r.result;pv.src=data;pv.hidden=false;go.disabled=false;m.textContent='';};r.readAsDataURL(file);};
go.onclick=function(){if(!data)return;go.disabled=true;m.textContent='上传中…';m.className='msg';
fetch(location.pathname,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_base64:data})})
.then(function(r){return r.json().then(function(j){if(!r.ok)throw new Error(j.error||'上传失败');return j;});})
.then(function(){m.textContent='✓ 已上传，回电脑上看即可';m.className='msg ok';})
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
async def upload_submit(token: str, request: Request, conn=Depends(get_db)):
    r = _load_token(conn, token)
    body = await request.json()
    raw = (body or {}).get('image_base64') or ''
    if ',' in raw:
        raw = raw.split(',', 1)[1]
    if not raw or len(raw) > 12_000_000:          # ~9MB 图片上限
        raise HTTPException(status_code=400, detail='图片为空或过大')
    try:
        blob = base64.b64decode(re.sub(r'\s+', '', raw), validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail='图片格式不正确')
    it = conn.execute('SELECT id FROM session_items WHERE session_id=? AND question_id=?',
                      (r['session_id'], r['question_id'])).fetchone()
    if not it:
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    fname = f"s{r['session_id']}_q{r['question_id']}.png"
    (DRAFTS_DIR / fname).write_bytes(blob)
    conn.execute('UPDATE session_items SET draft_path=?, updated_at=? WHERE id=?',
                 (fname, _now().isoformat(), it['id']))
    conn.execute('UPDATE draft_tokens SET used_at=? WHERE token=?', (_now().isoformat(), token))
    conn.commit()
    return {'ok': True, 'draft_url': '/drafts/' + fname}
