#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""给模拟卷选择题自动打知识点标签：从真题已有的知识点体系里给每题选最贴切的一个。
用现有 AI 网关(gpt-5.6-luna)。分批(每批 8 题)以减少调用次数。可重复运行——只处理 tags 为空的题。
用法（在 backend/）：python tag_simulate.py"""
import json
import os
import re
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import DB_PATH  # noqa: E402
from app.grading import _chat, _strip_html, configured  # noqa: E402

BATCH = int(os.environ.get('TAG_BATCH', '8'))


def _taxonomy(conn):
    rows = conn.execute("SELECT DISTINCT tags FROM questions WHERE source='exam' AND tags!=''").fetchall()
    tags = set()
    for r in rows:
        for t in re.split(r'[,，、|]', r['tags']):
            t = t.strip()
            if t:
                tags.add(t)
    return sorted(tags)


def _extract_array(text):
    m = re.search(r'\[.*\]', text or '', re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None


def _tag_batch(taxonomy, items):
    """items: [(number, subject, stem_text)] -> {number: tag}。"""
    lst = '、'.join(taxonomy)
    qs = '\n'.join(f"{n}.【{subj}】{stem[:300]}" for n, subj, stem in items)
    sys_p = (
        '你是408命题专家。为每道选择题标注一个最贴切的“知识点”。'
        '优先从下面的知识点清单里选原词；只有清单里确实没有合适的，才可新造一个不超过8字的简洁知识点。'
        '只输出 JSON 数组，元素形如 {"n":题号,"tag":"知识点"}，不要多余文字。\n'
        f'【知识点清单】{lst}'
    )
    content = _chat([{'role': 'system', 'content': sys_p}, {'role': 'user', 'content': qs}], timeout=180)
    arr = _extract_array(content) or []
    out = {}
    for e in arr:
        try:
            out[int(e['n'])] = str(e['tag']).strip()
        except Exception:
            pass
    return out


def main():
    if not configured():
        print('AI 未配置（缺 .env.local 的 GRADE_API_KEY）')
        return
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    taxonomy = _taxonomy(conn)
    print(f'知识点体系：{len(taxonomy)} 个')
    todo = conn.execute(
        "SELECT id, number, subject, stem_html, options_json FROM questions"
        " WHERE source='simulate' AND qtype='choice' AND tags='' ORDER BY year, number").fetchall()
    print(f'待打标签模拟选择题：{len(todo)}')
    done = 0
    for i in range(0, len(todo), BATCH):
        chunk = todo[i:i + BATCH]
        items = []
        for r in chunk:
            opts = ' '.join(o.get('text', '') for o in json.loads(r['options_json'] or '[]'))
            items.append((r['number'], r['subject'], _strip_html(r['stem_html']) + ' ' + _strip_html(opts)))
        # 题号可能跨套重复，这里用批内下标映射回具体行
        num2row = {}
        for idx, r in enumerate(chunk):
            num2row.setdefault(r['number'], []).append(r)
        try:
            tags = _tag_batch(taxonomy, [(r['number'], r['subject'],
                                          _strip_html(r['stem_html'])) for r in chunk])
        except Exception as e:
            print(f'  批 {i//BATCH+1} 调用失败：{e}；跳过')
            continue
        for r in chunk:
            tag = tags.get(r['number'], '')
            if tag:
                conn.execute('UPDATE questions SET tags=? WHERE id=?', (tag, r['id']))
                done += 1
        conn.commit()
        print(f'  批 {i//BATCH+1}/{(len(todo)+BATCH-1)//BATCH} 完成，累计打标 {done}')
        time.sleep(1)
    left = conn.execute("SELECT COUNT(*) c FROM questions WHERE source='simulate' AND qtype='choice' AND tags=''").fetchone()['c']
    print(f'完成：本次打标 {done}，仍空 {left}')
    conn.close()


if __name__ == '__main__':
    main()
