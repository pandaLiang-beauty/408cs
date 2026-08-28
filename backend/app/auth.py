"""单用户登录：pbkdf2 存密码、HMAC 签名的 HttpOnly 会话 Cookie、FastAPI 依赖。"""
import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Optional

from fastapi import HTTPException, Request, Response

from .config import settings

COOKIE = 'cs408_session'


def hash_password(pw: str, salt: Optional[str] = None) -> str:
    salt = salt or secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 100_000)
    return f'pbkdf2$100000${salt}${dk.hex()}'


def verify_password(pw: str, stored: str) -> bool:
    try:
        _algo, iters, salt, h = stored.split('$')
        dk = hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), h)
    except Exception:
        return False


def _sign(payload: str) -> str:
    return hmac.new(settings.SESSION_SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()


def make_token(user_id: int, name: str) -> str:
    payload = base64.urlsafe_b64encode(
        json.dumps({'uid': user_id, 'name': name, 'ts': int(time.time())}).encode()
    ).decode()
    return f'{payload}.{_sign(payload)}'


def verify_token(token: str):
    try:
        payload, sig = token.rsplit('.', 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return None
        data = json.loads(base64.urlsafe_b64decode(payload.encode()))
        if int(time.time()) - int(data['ts']) > settings.SESSION_MAX_AGE:
            return None
        return data
    except Exception:
        return None


def current_user(request: Request):
    tok = request.cookies.get(COOKIE)
    return verify_token(tok) if tok else None


def require_user(request: Request):
    data = current_user(request)
    if not data:
        raise HTTPException(status_code=401, detail='未登录')
    return data


def set_session_cookie(response: Response, user_id: int, name: str) -> None:
    response.set_cookie(COOKIE, make_token(user_id, name), httponly=True,
                        samesite='lax', max_age=settings.SESSION_MAX_AGE, path='/')


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path='/')
