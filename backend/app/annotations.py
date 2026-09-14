"""试卷边栏批注：按作答记录保存文字锚点，重做不覆盖，重试不重复创建。"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import auth, scheduler
from .db import get_db

router = APIRouter(prefix='/api/sessions', dependencies=[Depends(auth.require_user)])


class AnnotationIn(BaseModel):
    question_id: int
    client_id: str = Field(default_factory=lambda: uuid.uuid4().hex, min_length=1, max_length=64, pattern=r'^[A-Za-z0-9_-]+$')
    region: str = Field(max_length=32)
    quote: str = Field(default='', max_length=10000)
    start_offset: Optional[int] = Field(default=None, ge=0, le=2_000_000)
    end_offset: Optional[int] = Field(default=None, ge=0, le=2_000_000)
    prefix: str = Field(default='', max_length=100)
    suffix: str = Field(default='', max_length=100)
    body: str = Field(min_length=1, max_length=5000)


class AnnotationPatch(BaseModel):
    body: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    resolved: Optional[bool] = None


SELECT_ANNOTATION = (
    'SELECT a.*, si.session_id, si.question_id FROM annotations a '
    'JOIN session_items si ON si.id=a.session_item_id '
)


def public(row):
    result = {key: row[key] for key in (
        'id', 'session_id', 'question_id', 'region', 'quote', 'start_offset',
        'end_offset', 'prefix', 'suffix', 'body', 'created_at', 'updated_at')}
    result['resolved'] = bool(row['resolved'])
    return result


def get_annotation(conn, sid, aid):
    row = conn.execute(SELECT_ANNOTATION + 'WHERE si.session_id=? AND a.id=?', (sid, aid)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail='这次试卷中没有该批注')
    return row


def checked_body(body):
    if not body.strip():
        raise HTTPException(status_code=400, detail='请填写批注内容')
    return body.strip()


@router.get('/{sid}/annotations')
def list_annotations(sid: int, conn=Depends(get_db)):
    if not conn.execute('SELECT 1 FROM sessions WHERE id=?', (sid,)).fetchone():
        raise HTTPException(status_code=404, detail='做题记录不存在')
    rows = conn.execute(SELECT_ANNOTATION + 'WHERE si.session_id=? ORDER BY si.position,a.id', (sid,)).fetchall()
    return [public(row) for row in rows]


@router.post('/{sid}/annotations')
def add_annotation(sid: int, body: AnnotationIn, conn=Depends(get_db)):
    item = conn.execute(
        'SELECT si.id,si.verdict,s.status,q.qtype,q.options_json,q.answer_html '
        'FROM session_items si JOIN sessions s ON s.id=si.session_id '
        'JOIN questions q ON q.id=si.question_id WHERE si.session_id=? AND si.question_id=?',
        (sid, body.question_id)).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail='该题不在这次试卷中')
    if item['status'] != 'graded':
        raise HTTPException(status_code=409, detail='交卷后才能添加复盘批注')
    allowed = {'question', 'stem'}
    if item['qtype'] == 'choice':
        allowed.update('option:' + option['key'] for option in json.loads(item['options_json']))
    if item['answer_html'] and (item['status'] == 'graded' or item['verdict']):
        allowed.add('explanation')
    if body.region not in allowed:
        raise HTTPException(status_code=400, detail='不能在该位置添加批注')
    if body.region == 'question':
        if body.quote or body.start_offset is not None or body.end_offset is not None:
            raise HTTPException(status_code=400, detail='整题批注不需要文字选区')
    else:
        try:
            quote_length = len(body.quote.encode('utf-16-le')) // 2  # DOM Range 按 UTF-16 计偏移
        except UnicodeEncodeError:
            quote_length = 0
        if (not body.quote.strip() or not quote_length or body.start_offset is None
                or body.end_offset is None or body.end_offset - body.start_offset != quote_length):
            raise HTTPException(status_code=400, detail='文字选区无效，请重新选择')
    content = checked_body(body.body)
    values = (item['id'], body.client_id, body.region, body.quote, body.start_offset,
              body.end_offset, body.prefix, body.suffix, content)
    now = scheduler.now_iso()
    # 同一个客户端草稿重试时只创建一次；不会改写已经保存或编辑过的批注。
    conn.execute(
        'INSERT INTO annotations(session_item_id,client_id,region,quote,start_offset,end_offset,prefix,suffix,body,created_at,updated_at) '
        'VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(client_id) DO NOTHING', (*values, now, now))
    row = conn.execute(SELECT_ANNOTATION + 'WHERE a.client_id=?', (body.client_id,)).fetchone()
    if row['session_item_id'] != item['id']:
        conn.rollback()
        raise HTTPException(status_code=409, detail='批注请求已用于另一道题，请重新添加')
    if tuple(row[key] for key in ('session_item_id', 'client_id', 'region', 'quote', 'start_offset', 'end_offset', 'prefix', 'suffix', 'body')) != values:
        conn.rollback()
        raise HTTPException(status_code=409, detail='这条批注已经保存且内容有变化，请刷新后编辑原批注；当前草稿已保留')
    conn.commit()
    return public(row)


@router.patch('/{sid}/annotations/{aid}')
def edit_annotation(sid: int, aid: int, body: AnnotationPatch, conn=Depends(get_db)):
    get_annotation(conn, sid, aid)
    sets, values = [], []
    if body.body is not None:
        sets.append('body=?')
        values.append(checked_body(body.body))
    if body.resolved is not None:
        sets.append('resolved=?')
        values.append(int(body.resolved))
    if sets:
        conn.execute('UPDATE annotations SET ' + ','.join(sets) + ',updated_at=? WHERE id=?',
                     (*values, scheduler.now_iso(), aid))
        conn.commit()
    return public(get_annotation(conn, sid, aid))


@router.delete('/{sid}/annotations/{aid}')
def delete_annotation(sid: int, aid: int, conn=Depends(get_db)):
    get_annotation(conn, sid, aid)
    conn.execute('DELETE FROM annotations WHERE id=?', (aid,))
    conn.commit()
    return {'ok': True}
