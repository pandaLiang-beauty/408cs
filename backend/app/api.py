"""cs408 HTTP 路由 + 内联数据访问（单科目自用工具，无需单独 repository 层）。

做题以 session 为中心：进卷=建/续 session，答题即自动存 session_item，交卷才批改跑 SRS。
同一题在不同卷里各占一行 session_item（各自 chosen/模糊/草稿）；笔记按题聚合成笔记库。
"""
import base64
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from . import auth, grading, scheduler, llmconfig, upload, plan
from .config import DRAFTS_DIR
from .db import get_db

router = APIRouter(prefix='/api')
SUBJECT_ORDER = {'数据结构': 0, '组成原理': 1, '操作系统': 2, '计算机网络': 3}


def _to_public(row) -> dict:
    """题目对外形态：不含正确答案/参考答案。"""
    return {
        'id': row['id'], 'year': row['year'], 'subject': row['subject'], 'number': row['number'],
        'qtype': row['qtype'], 'source': row['source'], 'stem_html': row['stem_html'],
        'options': json.loads(row['options_json'] or '[]'), 'tags': row['tags'],
    }


def _draft_url(path) -> str:
    return ('/drafts/' + os.path.basename(path)) if path else ''


def _item_public(si, q, graded: bool) -> dict:
    """一条做题记录对外形态；未交卷不泄露正确答案/参考答案。"""
    d = {
        'chosen': si['chosen'], 'fuzzy': bool(si['fuzzy']),
        'is_correct': si['is_correct'], 'result': si['result'],
        'draft_url': _draft_url(si['draft_path']),
        'answer_text': si['answer_text'], 'verdict': si['verdict'], 'comment': si['comment'],
    }
    if graded:
        d['answer'] = q['answer']
        d['reference_html'] = q['answer_html']
    return d


def _session_payload(conn, sess) -> dict:
    """一场做题的完整状态：题目 + 每题做题记录（供进卷/刷新恢复）。"""
    graded = sess['status'] == 'graded'
    rows = conn.execute(
        'SELECT si.*, q.id qid, q.year, q.subject, q.number, q.qtype, q.source, q.stem_html,'
        ' q.options_json, q.tags, q.answer, q.answer_html'
        ' FROM session_items si JOIN questions q ON q.id=si.question_id'
        ' WHERE si.session_id=? ORDER BY si.position', (sess['id'],)).fetchall()
    questions, items = [], {}
    for r in rows:
        q = _to_public(r)
        q['id'] = r['qid']   # r['id'] 是 session_items.id；题目 id 取 q.id 的别名 qid
        questions.append(q)
        items[r['qid']] = _item_public(r, r, graded)
    return {'session_id': sess['id'], 'kind': sess['kind'], 'year': sess['year'],
            'status': sess['status'], 'questions': questions, 'items': items}


class LoginIn(BaseModel):
    password: str


class CreateSessionIn(BaseModel):
    kind: str = 'exam'          # exam | reinforce
    year: int | None = None     # exam 必填
    all: bool = False           # reinforce：True=不限到期全池
    fresh: bool = False         # True=另起一场新记录（「再做一次」）


class PatchItemIn(BaseModel):
    chosen: str | None = None
    fuzzy: bool | None = None


class DraftIn(BaseModel):
    question_id: int
    image_base64: str


class DraftTokenIn(BaseModel):
    question_id: int


class GradeIn(BaseModel):
    question_id: int
    answer_text: str


class NoteIn(BaseModel):
    question_id: int | None = None
    session_id: int | None = None
    body: str = ''


class LlmProfileIn(BaseModel):
    name: str = ''
    api_format: str = 'openai'          # openai | anthropic | responses
    base_url: str = ''
    model: str = ''
    temperature: float = 0.2
    api_key: str | None = None          # 留空=保留原密钥（前端不回填明文）


class ActiveIn(BaseModel):
    profile_id: int


class PromptIn(BaseModel):
    grade_prompt: str = ''


class PlanConfigIn(BaseModel):
    exam_date: str


@router.get('/health')
def health():
    return {'ok': True}


@router.post('/auth/login')
def login(body: LoginIn, response: Response, conn=Depends(get_db)):
    row = conn.execute('SELECT id, name, password_hash FROM users ORDER BY id LIMIT 1').fetchone()
    if not row or not auth.verify_password(body.password, row['password_hash']):
        raise HTTPException(status_code=401, detail='密码错误')
    auth.set_session_cookie(response, row['id'], row['name'])
    return {'ok': True, 'user': {'name': row['name']}}


@router.post('/auth/logout')
def logout(response: Response):
    auth.clear_session_cookie(response)
    return {'ok': True}


@router.get('/auth/me')
def me(request: Request):
    data = auth.current_user(request)
    if data:
        return {'authenticated': True, 'user': {'name': data.get('name')}}
    return {'authenticated': False}


def _get_session(conn, sid: int):
    sess = conn.execute('SELECT * FROM sessions WHERE id=?', (sid,)).fetchone()
    if not sess:
        raise HTTPException(status_code=404, detail='做题记录不存在')
    return sess


@router.get('/years')
def years(conn=Depends(get_db), _=Depends(auth.require_user)):
    rows = conn.execute("SELECT year, COUNT(*) c FROM questions WHERE source='exam'"
                        ' GROUP BY year ORDER BY year DESC').fetchall()
    return [{'year': r['year'], 'count': r['c']} for r in rows]


def _exam_question_ids(conn, year: int):
    rows = conn.execute("SELECT id, subject, number FROM questions WHERE source='exam' AND year=?",
                        (year,)).fetchall()
    ordered = sorted(rows, key=lambda r: (SUBJECT_ORDER.get(r['subject'], 9), r['number']))
    return [r['id'] for r in ordered]


def _reinforce_question_ids(conn, all_pool: bool):
    """按薄弱知识点组强化卷：同知识点「新题优先」，穿插做错/模糊过的原题；最多 30 题。"""
    now = scheduler.now_iso()
    if all_pool:
        pts = conn.execute('SELECT tag FROM point_schedule ORDER BY due_at').fetchall()
    else:
        pts = conn.execute('SELECT tag FROM point_schedule WHERE due_at<=? ORDER BY due_at',
                           (now,)).fetchall()
    if not pts:
        return []
    recent_cut = scheduler.hours_ago_iso(12)  # 12h 内刚做过的先不重复
    per_point = {}
    for pt in pts:
        tag = pt['tag']
        rows = conn.execute(
            'SELECT q.id, q.tags, COUNT(si.id) attempts, MAX(si.updated_at) last_done,'
            " MAX(CASE WHEN si.result IN ('wrong','fuzzy') THEN 1 ELSE 0 END) ever_missed"
            ' FROM questions q LEFT JOIN session_items si ON si.question_id=q.id'
            " WHERE q.qtype='choice' AND q.tags LIKE ?"
            ' GROUP BY q.id', (f'%{tag}%',)).fetchall()
        # LIKE 只是粗筛，再用精确 token 过滤，避免“二叉树”误配“二叉树遍历”
        rows = [r for r in rows if tag in scheduler.split_tags(r['tags'])]
        rows = [r for r in rows if not (r['last_done'] and r['last_done'] > recent_cut)]
        new = [r['id'] for r in rows if r['attempts'] == 0]
        missed = [r['id'] for r in rows if r['attempts'] and r['ever_missed']]
        others = [r['id'] for r in rows if r['attempts'] and not r['ever_missed']]
        per_point[tag] = new + missed + others   # 新题优先，其次原错题，最后已掌握的
    order = [pt['tag'] for pt in pts]
    picked, seen = [], set()
    while len(picked) < 30 and any(per_point[t] for t in order):
        for t in order:
            if not per_point[t]:
                continue
            qid = per_point[t].pop(0)
            if qid not in seen:
                seen.add(qid)
                picked.append(qid)
                if len(picked) >= 30:
                    break
    return picked


def _open_session_id(conn, kind: str, year=None, all_pool: bool = False, fresh: bool = False) -> int:
    """建/续一场做题，返回 session id。fresh=False 时优先续接未交卷的同类卷。"""
    if kind == 'exam':
        if not year:
            raise HTTPException(status_code=400, detail='真题卷需指定年份')
        if not fresh:
            s = conn.execute("SELECT id FROM sessions WHERE kind='exam' AND year=? AND status='doing'"
                             ' ORDER BY id DESC LIMIT 1', (year,)).fetchone()
            if s:
                return s['id']
        qids = _exam_question_ids(conn, year)
        if not qids:
            raise HTTPException(status_code=404, detail='该年份暂无题目')
    elif kind == 'reinforce':
        if not fresh:
            s = conn.execute("SELECT id FROM sessions WHERE kind='reinforce' AND status='doing'"
                             ' ORDER BY id DESC LIMIT 1').fetchone()
            if s:
                return s['id']
        qids = _reinforce_question_ids(conn, all_pool)
    else:
        raise HTTPException(status_code=400, detail='未知卷型')
    cur = conn.execute('INSERT INTO sessions(kind,year,status) VALUES(?,?,?)',
                       (kind, year if kind == 'exam' else None, 'doing'))
    sid = cur.lastrowid
    for pos, qid in enumerate(qids):
        conn.execute('INSERT INTO session_items(session_id,question_id,position) VALUES(?,?,?)',
                     (sid, qid, pos))
    conn.commit()
    return sid


@router.post('/sessions')
def create_session(body: CreateSessionIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    """建/续一场做题。fresh=False 时优先续接未交卷的同类卷；fresh=True 另起新记录。"""
    sid = _open_session_id(conn, body.kind, body.year, body.all, body.fresh)
    return _session_payload(conn, _get_session(conn, sid))


@router.get('/sessions/{sid}')
def get_session(sid: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    return _session_payload(conn, _get_session(conn, sid))


@router.get('/reinforce/stats')
def reinforce_stats(conn=Depends(get_db), _=Depends(auth.require_user)):
    now = scheduler.now_iso()
    due = conn.execute('SELECT COUNT(*) c FROM point_schedule WHERE due_at<=?', (now,)).fetchone()['c']
    pool = conn.execute('SELECT COUNT(*) c FROM point_schedule').fetchone()['c']
    return {'due': due, 'pool': pool}


@router.patch('/sessions/{sid}/items/{qid}')
def patch_item(sid: int, qid: int, body: PatchItemIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    """答题自动保存：改选项/模糊即存。已交卷的卷不再改。"""
    sess = _get_session(conn, sid)
    if sess['status'] != 'doing':
        raise HTTPException(status_code=409, detail='该卷已交卷，不能再改')
    sets, vals = [], []
    if body.chosen is not None:
        sets.append('chosen=?'); vals.append(body.chosen)
    if body.fuzzy is not None:
        sets.append('fuzzy=?'); vals.append(1 if body.fuzzy else 0)
    if sets:
        sets.append('updated_at=?'); vals.append(scheduler.now_iso())
        vals += [sid, qid]
        conn.execute(f'UPDATE session_items SET {",".join(sets)} WHERE session_id=? AND question_id=?', vals)
        conn.commit()
    return {'ok': True}


@router.post('/sessions/{sid}/submit')
def submit(sid: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """交卷：批改本卷所有选择题（作答已自动存好），跑 SRS，标记 graded。大题不入此统计。"""
    sess = _get_session(conn, sid)
    rows = conn.execute(
        'SELECT si.*, q.qtype, q.answer, q.tags FROM session_items si JOIN questions q ON q.id=si.question_id'
        " WHERE si.session_id=? AND q.qtype='choice'", (sid,)).fetchall()
    correct = 0
    for si in rows:
        is_correct = 1 if (si['chosen'] and si['chosen'] == si['answer']) else 0
        result = scheduler.verdict_to_result(is_correct, 1 if si['fuzzy'] else 0)
        conn.execute('UPDATE session_items SET is_correct=?,result=?,updated_at=? WHERE id=?',
                     (is_correct, result, scheduler.now_iso(), si['id']))
        if sess['status'] != 'graded':   # 幂等：重复交卷不重复推调度
            for tag in scheduler.split_tags(si['tags']):
                scheduler.update_point(conn, tag, result)
        correct += is_correct
    fuzzy = sum(1 for si in rows if si['fuzzy'])
    conn.execute("UPDATE sessions SET status='graded', graded_at=? WHERE id=?",
                 (scheduler.now_iso(), sid))
    conn.commit()
    total = len(rows)
    return {'total': total, 'correct': correct, 'wrong': total - correct, 'fuzzy': fuzzy,
            **_session_payload(conn, _get_session(conn, sid))}


@router.post('/sessions/{sid}/draft')
def save_draft(sid: int, body: DraftIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    """草稿纸（本机选图）：每场做题各存一份（文件名带 session）。"""
    _get_session(conn, sid)
    it = conn.execute('SELECT id FROM session_items WHERE session_id=? AND question_id=?',
                      (sid, body.question_id)).fetchone()
    if not it:
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    img = body.image_base64.split(',', 1)[1] if ',' in body.image_base64 else body.image_base64
    fname = f's{sid}_q{body.question_id}.png'
    (DRAFTS_DIR / fname).write_bytes(base64.b64decode(img))
    conn.execute('UPDATE session_items SET draft_path=?,updated_at=? WHERE id=?',
                 (fname, scheduler.now_iso(), it['id']))
    conn.commit()
    return {'ok': True, 'draft_url': '/drafts/' + fname}


@router.post('/sessions/{sid}/draft-token')
def draft_token(sid: int, body: DraftTokenIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    """签发一次性上传链接（供电脑端生成二维码，手机扫码上传草稿纸）。"""
    _get_session(conn, sid)
    if not conn.execute('SELECT 1 FROM session_items WHERE session_id=? AND question_id=?',
                        (sid, body.question_id)).fetchone():
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    return upload.issue_token(conn, sid, body.question_id)


@router.get('/sessions/{sid}/draft')
def get_draft(sid: int, question_id: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """轮询用：手机传完后电脑端据此刷新草稿缩略图。"""
    it = conn.execute('SELECT draft_path, updated_at FROM session_items'
                      ' WHERE session_id=? AND question_id=?', (sid, question_id)).fetchone()
    if not it:
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    return {'draft_url': _draft_url(it['draft_path']), 'updated_at': it['updated_at']}


@router.post('/sessions/{sid}/grade_subjective')
def grade_subjective(sid: int, body: GradeIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    """大题 AI 批改：独立于交卷，写回本场做题记录并入 SRS。"""
    _get_session(conn, sid)
    student = (body.answer_text or '').strip()
    if not student:
        raise HTTPException(status_code=400, detail='请先写出你的作答')
    cfg = llmconfig.active_config(conn)
    if not grading.configured(cfg):
        raise HTTPException(status_code=500, detail='AI 未配置（去「设置」新建/选择一个可用的大模型档）')
    q = conn.execute("SELECT stem_html, answer_html FROM questions WHERE id=? AND qtype='subjective'",
                     (body.question_id,)).fetchone()
    if not q:
        raise HTTPException(status_code=404, detail='题目不存在或非大题')
    it = conn.execute('SELECT id FROM session_items WHERE session_id=? AND question_id=?',
                      (sid, body.question_id)).fetchone()
    if not it:
        raise HTTPException(status_code=404, detail='该题不在此卷中')
    try:
        j = grading.grade(cfg, q['stem_html'], q['answer_html'], student)
    except Exception as e:
        raise HTTPException(status_code=502, detail='AI 批改失败：' + str(e))
    verdict = j.get('verdict', '部分对')
    result = 'correct' if verdict == '对' else ('wrong' if verdict == '错' else 'fuzzy')
    conn.execute('UPDATE session_items SET answer_text=?,verdict=?,comment=?,is_correct=?,result=?,updated_at=?'
                 ' WHERE id=?',
                 (student, verdict, j.get('comment', ''), 1 if verdict == '对' else 0, result,
                  scheduler.now_iso(), it['id']))
    scheduler.update(conn, body.question_id, result)
    conn.commit()
    return {'verdict': verdict, 'score_ratio': j.get('score_ratio'),
            'comment': j.get('comment', ''), 'reference_html': q['answer_html']}

def _note_row(r) -> dict:
    return {'id': r['id'], 'question_id': r['question_id'], 'session_id': r['session_id'],
            'body': r['body'], 'created_at': r['created_at'], 'updated_at': r['updated_at']}


@router.get('/notes')
def list_notes(question_id: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """某题的全部笔记（一题多条），按时间正序——看题时聚合到一起。"""
    rows = conn.execute('SELECT * FROM notes WHERE question_id=? ORDER BY created_at', (question_id,)).fetchall()
    return [_note_row(r) for r in rows]


@router.post('/notes')
def add_note(body: NoteIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    if not body.question_id:
        raise HTTPException(status_code=400, detail='缺 question_id')
    if not (body.body or '').strip():
        raise HTTPException(status_code=400, detail='笔记为空')
    cur = conn.execute('INSERT INTO notes(question_id,session_id,body) VALUES(?,?,?)',
                       (body.question_id, body.session_id, body.body.strip()))
    conn.commit()
    return _note_row(conn.execute('SELECT * FROM notes WHERE id=?', (cur.lastrowid,)).fetchone())


@router.patch('/notes/{nid}')
def edit_note(nid: int, body: NoteIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    r = conn.execute('SELECT id FROM notes WHERE id=?', (nid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail='笔记不存在')
    conn.execute('UPDATE notes SET body=?,updated_at=? WHERE id=?',
                 ((body.body or '').strip(), scheduler.now_iso(), nid))
    conn.commit()
    return _note_row(conn.execute('SELECT * FROM notes WHERE id=?', (nid,)).fetchone())


@router.delete('/notes/{nid}')
def delete_note(nid: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    conn.execute('DELETE FROM notes WHERE id=?', (nid,))
    conn.commit()
    return {'ok': True}


@router.get('/notebook')
def notebook(conn=Depends(get_db), _=Depends(auth.require_user)):
    """笔记库：所有笔记 + 所属题目信息，按题聚合返回。"""
    rows = conn.execute(
        'SELECT n.id, n.body, n.created_at, n.updated_at, q.id qid, q.year, q.number,'
        ' q.subject, q.qtype, q.tags, q.stem_html'
        ' FROM notes n JOIN questions q ON q.id=n.question_id'
        ' ORDER BY q.year DESC, q.number, n.created_at').fetchall()
    groups = {}
    for r in rows:
        g = groups.setdefault(r['qid'], {
            'question_id': r['qid'], 'year': r['year'], 'number': r['number'],
            'subject': r['subject'], 'qtype': r['qtype'], 'tags': r['tags'],
            'stem_html': r['stem_html'], 'notes': []})
        g['notes'].append({'id': r['id'], 'body': r['body'],
                           'created_at': r['created_at'], 'updated_at': r['updated_at']})
    return list(groups.values())


@router.get('/settings/llm')
def get_llm(conn=Depends(get_db), _=Depends(auth.require_user)):
    return llmconfig.public_view(conn)


@router.post('/settings/llm/profiles')
def create_profile(body: LlmProfileIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    if body.api_format not in llmconfig.VALID_FORMATS:
        raise HTTPException(status_code=400, detail='不支持的 API 格式')
    llmconfig.create_profile(conn, body.name, body.api_format, body.base_url,
                             body.model, body.temperature, body.api_key)
    return llmconfig.public_view(conn)


@router.put('/settings/llm/profiles/{pid}')
def update_profile(pid: int, body: LlmProfileIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    if body.api_format not in llmconfig.VALID_FORMATS:
        raise HTTPException(status_code=400, detail='不支持的 API 格式')
    if not llmconfig.update_profile(conn, pid, body.name, body.api_format, body.base_url,
                                    body.model, body.temperature, body.api_key):
        raise HTTPException(status_code=404, detail='配置档不存在')
    return llmconfig.public_view(conn)


@router.delete('/settings/llm/profiles/{pid}')
def delete_profile(pid: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    llmconfig.delete_profile(conn, pid)
    return llmconfig.public_view(conn)


@router.put('/settings/llm/active')
def set_active(body: ActiveIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    if not llmconfig.set_active(conn, body.profile_id):
        raise HTTPException(status_code=404, detail='配置档不存在')
    return llmconfig.public_view(conn)


@router.put('/settings/llm/prompt')
def set_prompt(body: PromptIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    llmconfig.set_grade_prompt(conn, body.grade_prompt)
    return llmconfig.public_view(conn)


@router.get('/settings/llm/models')
def llm_models(profile_id: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """从指定档的网关拉取可用模型列表（供前端下拉）。"""
    cfg = llmconfig.get_profile_cfg(conn, profile_id)
    if not cfg:
        raise HTTPException(status_code=404, detail='配置档不存在')
    if not (cfg.get('base_url') and cfg.get('api_key')):
        raise HTTPException(status_code=400, detail='该档需先填 base_url / api_key 并保存')
    try:
        return {'models': grading.list_models(cfg)}
    except Exception as e:
        raise HTTPException(status_code=502, detail='拉取模型失败：' + str(e))


@router.post('/settings/llm/test')
def test_llm(profile_id: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """用指定档发一句极简请求，验证 base_url / key / 模型 / 格式是否可用。"""
    cfg = llmconfig.get_profile_cfg(conn, profile_id)
    if not cfg:
        raise HTTPException(status_code=404, detail='配置档不存在')
    if not grading.configured(cfg):
        raise HTTPException(status_code=400, detail='该档需先填 base_url / api_key / 模型')
    try:
        reply = grading.chat(cfg, [{'role': 'user', 'content': '只回复两个字：可用'}], timeout=60)
    except Exception as e:
        raise HTTPException(status_code=502, detail='调用失败：' + str(e))
    return {'ok': True, 'reply': (reply or '').strip()[:100]}


@router.get('/plan')
def get_plan(conn=Depends(get_db), _=Depends(auth.require_user)):
    """首页排程：倒计时 + 今日任务 + 补做 + 未来预排。"""
    return plan.view(conn)


@router.get('/plan/calendar')
def get_calendar(ym: str | None = None, conn=Depends(get_db), _=Depends(auth.require_user)):
    """月历视图：过去/今天用落库任务，未来用预排。ym 形如 2026-08，缺省当月。"""
    return plan.calendar(conn, ym)


@router.post('/plan/tasks/{tid}/start')
def start_task(tid: int, conn=Depends(get_db), _=Depends(auth.require_user)):
    """开始某项任务：建/续对应的卷，并把 session 绑到任务上（交卷后任务自动算完成）。"""
    plan.ensure_through_today(conn)
    r = conn.execute('SELECT * FROM daily_tasks WHERE id=?', (tid,)).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail='任务不存在')
    if r['session_id']:
        s = conn.execute('SELECT * FROM sessions WHERE id=?', (r['session_id'],)).fetchone()
        if s:
            return {'session_id': s['id'], 'mode': s['kind'], 'year': s['year']}
    if r['kind'] in ('exam', 'mock'):
        sid = _open_session_id(conn, 'exam', r['ref_year'])
        mode, year = 'exam', r['ref_year']
    else:
        sid = _open_session_id(conn, 'reinforce')
        mode, year = 'reinforce', None
    conn.execute('UPDATE daily_tasks SET session_id=? WHERE id=?', (sid, tid))
    conn.commit()
    return {'session_id': sid, 'mode': mode, 'year': year}


@router.put('/plan/config')
def put_plan_config(body: PlanConfigIn, conn=Depends(get_db), _=Depends(auth.require_user)):
    plan.ensure_config(conn)
    conn.execute('UPDATE plan_config SET exam_date=? WHERE id=1', (body.exam_date,))
    conn.commit()
    return plan.view(conn)



