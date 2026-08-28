"""大模型多档配置：llm_profiles(多个网关档) + app_settings(选中哪档 / 全局批改提示词)。
可在线增删改、切换当前使用的档。首次从旧 llm_config 或 .env 的 GRADE_* 迁移出一档。
打标签是一次性脚本，不在此；grade_prompt 与网关无关，故全局单份。"""
from urllib.parse import urlparse

from .config import settings
from .grading import SYSTEM_PROMPT

VALID_FORMATS = ('openai', 'anthropic', 'responses')


def _name_from_url(url: str, fallback: str = '默认') -> str:
    host = urlparse(url or '').hostname or ''
    return host or fallback


def migrate_and_seed(conn) -> None:
    """保证 app_settings 存在；profiles 为空时从旧 llm_config 或 env 迁出一档并设为当前。"""
    if not conn.execute('SELECT 1 FROM app_settings WHERE id=1').fetchone():
        conn.execute('INSERT INTO app_settings(id, active_profile_id, grade_prompt) VALUES(1, NULL, ?)',
                     ('',))
    if conn.execute('SELECT COUNT(*) c FROM llm_profiles').fetchone()['c'] == 0:
        old = conn.execute('SELECT * FROM llm_config WHERE id=1').fetchone()
        if old and (old['base_url'] or old['api_key']):
            fmt, base, key, model, temp = (old['api_format'], old['base_url'], old['api_key'],
                                           old['model'], old['temperature'])
            gp = old['grade_prompt'] or ''
        else:
            fmt, base, key, model, temp, gp = ('openai', settings.GRADE_BASE_URL,
                                               settings.GRADE_API_KEY, settings.GRADE_MODEL, 0.2, '')
        cur = conn.execute(
            'INSERT INTO llm_profiles(name, api_format, base_url, api_key, model, temperature)'
            ' VALUES(?,?,?,?,?,?)', (_name_from_url(base), fmt, base, key, model, temp))
        conn.execute('UPDATE app_settings SET active_profile_id=?, grade_prompt=? WHERE id=1',
                     (cur.lastrowid, gp))
    conn.commit()


def _row_to_cfg(r) -> dict:
    return {'id': r['id'], 'name': r['name'], 'api_format': r['api_format'], 'base_url': r['base_url'],
            'api_key': r['api_key'], 'model': r['model'], 'temperature': r['temperature']}


def grade_prompt(conn) -> str:
    r = conn.execute('SELECT grade_prompt FROM app_settings WHERE id=1').fetchone()
    return (r['grade_prompt'] if r and r['grade_prompt'] else SYSTEM_PROMPT)


def active_config(conn) -> dict:
    """当前选中的档（含 grade_prompt），供批改用；没有可用档时抛给调用方判断 configured。"""
    s = conn.execute('SELECT active_profile_id FROM app_settings WHERE id=1').fetchone()
    r = None
    if s and s['active_profile_id']:
        r = conn.execute('SELECT * FROM llm_profiles WHERE id=?', (s['active_profile_id'],)).fetchone()
    if not r:
        r = conn.execute('SELECT * FROM llm_profiles ORDER BY id LIMIT 1').fetchone()
    if not r:
        return {'api_format': 'openai', 'base_url': '', 'api_key': '', 'model': '',
                'temperature': 0.2, 'grade_prompt': grade_prompt(conn)}
    cfg = _row_to_cfg(r)
    cfg['grade_prompt'] = grade_prompt(conn)
    return cfg


def get_profile_cfg(conn, pid: int):
    r = conn.execute('SELECT * FROM llm_profiles WHERE id=?', (pid,)).fetchone()
    return _row_to_cfg(r) if r else None


def create_profile(conn, name, api_format, base_url, model, temperature, api_key) -> int:
    fmt = api_format if api_format in VALID_FORMATS else 'openai'
    cur = conn.execute(
        'INSERT INTO llm_profiles(name, api_format, base_url, api_key, model, temperature)'
        ' VALUES(?,?,?,?,?,?)',
        (name or _name_from_url(base_url), fmt, (base_url or '').rstrip('/'),
         api_key or '', model or '', temperature))
    # 若尚无选中档，新建的自动设为当前
    conn.execute('UPDATE app_settings SET active_profile_id=COALESCE(active_profile_id, ?) WHERE id=1',
                 (cur.lastrowid,))
    conn.commit()
    return cur.lastrowid


def update_profile(conn, pid, name, api_format, base_url, model, temperature, api_key) -> bool:
    if not conn.execute('SELECT 1 FROM llm_profiles WHERE id=?', (pid,)).fetchone():
        return False
    fmt = api_format if api_format in VALID_FORMATS else 'openai'
    base_url = (base_url or '').rstrip('/')
    if api_key:
        conn.execute('UPDATE llm_profiles SET name=?,api_format=?,base_url=?,api_key=?,model=?,temperature=? WHERE id=?',
                     (name, fmt, base_url, api_key, model, temperature, pid))
    else:
        conn.execute('UPDATE llm_profiles SET name=?,api_format=?,base_url=?,model=?,temperature=? WHERE id=?',
                     (name, fmt, base_url, model, temperature, pid))
    conn.commit()
    return True


def delete_profile(conn, pid) -> None:
    conn.execute('DELETE FROM llm_profiles WHERE id=?', (pid,))
    # 若删的是当前档，回退到任意一个
    s = conn.execute('SELECT active_profile_id FROM app_settings WHERE id=1').fetchone()
    if not s['active_profile_id'] or s['active_profile_id'] == pid:
        nxt = conn.execute('SELECT id FROM llm_profiles ORDER BY id LIMIT 1').fetchone()
        conn.execute('UPDATE app_settings SET active_profile_id=? WHERE id=1',
                     (nxt['id'] if nxt else None,))
    conn.commit()


def set_active(conn, pid) -> bool:
    if not conn.execute('SELECT 1 FROM llm_profiles WHERE id=?', (pid,)).fetchone():
        return False
    conn.execute('UPDATE app_settings SET active_profile_id=? WHERE id=1', (pid,))
    conn.commit()
    return True


def set_grade_prompt(conn, prompt: str) -> None:
    conn.execute('UPDATE app_settings SET grade_prompt=? WHERE id=1', ((prompt or '').strip(),))
    conn.commit()


def public_view(conn) -> dict:
    """前端展示：多档列表(不回传明文密钥) + 当前档 + 全局批改提示词。"""
    s = conn.execute('SELECT active_profile_id FROM app_settings WHERE id=1').fetchone()
    active_id = s['active_profile_id'] if s else None
    profiles = []
    for r in conn.execute('SELECT * FROM llm_profiles ORDER BY id'):
        profiles.append({'id': r['id'], 'name': r['name'], 'api_format': r['api_format'],
                         'base_url': r['base_url'], 'model': r['model'],
                         'temperature': r['temperature'], 'has_key': bool(r['api_key'])})
    return {'profiles': profiles, 'active_id': active_id,
            'grade_prompt': grade_prompt(conn), 'default_grade_prompt': SYSTEM_PROMPT}
