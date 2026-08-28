#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""一次性种子脚本：解析 data/raw/*.html（csgraduates 408 真题）→ study.db 的 questions 表。
自用工具，题库是固定的历史真题，跑一次即可（有新一年真题时再手动跑）。
用法（在 backend/ 下）：python seed.py"""
import glob
import json
import os
import re
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # backend/
from app.config import RAW_DIR, DB_PATH  # noqa: E402
from app import schema  # noqa: E402

RE_H4 = re.compile(r'<h4 id=([^>\s]+)>')
RE_H5 = re.compile(r'<h5 id=(\d+)>')
RE_CHOICE = re.compile(r'<div class="choice-container[^"]*"([^>]*)>')
RE_ANSBOX = re.compile(r'<div class="answer-container[^"]*"[^>]*>')
RE_ANSWER = re.compile(r'data-answer=([^\s>]+)')
RE_TAGS = re.compile(r'data-tags=(?:"([^"]*)"|([^\s>]+))')
SUBJECT_CANON = {
    '数据结构': '数据结构', '组成原理': '组成原理', '计算机组成原理': '组成原理',
    '操作系统': '操作系统', '计算机网络': '计算机网络',
}


def absolutize(s):
    return re.sub(r'(src|href)=("?)/(?!/)', r'\1=\2https://www.csgraduates.com/', s or '')


def parse_options(slice_html):
    """兼容两种选项写法：普通 choice-option(带 choice-text) 与内联 choice-option-inline(仅字母，内容在题干图里)。"""
    options = []
    for m in re.finditer(r'<label class=choice-option[^>]*>(.*?)</label>', slice_html, re.S):
        block = m.group(1)
        mv = re.search(r'value=([A-Z])', block)
        if not mv:
            continue
        mt = re.search(r'<span class=choice-text>(.*)$', block, re.S)
        text = re.sub(r'</span>\s*$', '', mt.group(1).strip()) if mt else ''
        options.append({'key': mv.group(1), 'text': absolutize(text.strip())})
    return options
# SEED_PLACEHOLDER

def _subject_at(pos, h4list):
    subj = ''
    for sm in h4list:
        if sm.start() < pos:
            subj = SUBJECT_CANON.get(re.sub(r'-\d+$', '', sm.group(1)), subj)
        else:
            break
    return subj


def _clean(s):
    return absolutize(re.sub(r'\s+', ' ', re.sub(r'^\s*\d*\s*</h5>\s*', '', s or ''))).strip()


def parse_year(year, html):
    h4list = list(RE_H4.finditer(html))
    h5list = list(RE_H5.finditer(html))
    out = []
    for idx, m in enumerate(h5list):
        number = int(m.group(1))
        start = m.end()
        end = h5list[idx + 1].start() if idx + 1 < len(h5list) else len(html)
        seg = html[start:end]
        cut = re.search(r'<h[34] id=', seg)
        if cut:
            seg = seg[:cut.start()]
        mend = seg.find('</main>')   # 每年最后一题会读到页面 <main> 之后的页脚/侧栏/工具条，截断丢弃
        if mend != -1:
            seg = seg[:mend]
        subject = _subject_at(m.start(), h4list)
        ch = RE_CHOICE.search(seg)
        if ch:
            options = parse_options(seg[ch.end():])
            ma = RE_ANSWER.search(ch.group(1))
            mt = RE_TAGS.search(ch.group(1))
            if not ma or len(options) < 2:
                continue
            out.append({'year': year, 'subject': subject, 'number': number, 'qtype': 'choice',
                        'stem_html': _clean(seg[:ch.start()]), 'options': options,
                        'answer': ma.group(1).strip(), 'answer_html': '',
                        'tags': (mt.group(1) or mt.group(2) or '').strip() if mt else ''})
            continue
        ab = RE_ANSBOX.search(seg)
        if ab:
            stem = _clean(seg[:ab.start()])
            ans = re.sub(r'(\s*</div>)+\s*$', '', absolutize(re.sub(r'\s+', ' ', seg[ab.end():])).strip())
            if len(stem) < 8:
                continue
            out.append({'year': year, 'subject': subject, 'number': number, 'qtype': 'subjective',
                        'stem_html': stem, 'options': [], 'answer': '', 'answer_html': ans, 'tags': ''})
    return out


def main():
    records = []
    for path in sorted(glob.glob(os.path.join(str(RAW_DIR), '*.html'))):
        year = int(os.path.splitext(os.path.basename(path))[0])
        text = open(path, 'rb').read().decode('utf-8', 'ignore')
        records.extend(parse_year(year, text))
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    schema.initialize(conn)
    conn.execute('DELETE FROM questions')  # 重新播种题库（级联清空 attempts/强化池）
    for r in records:
        conn.execute(
            'INSERT INTO questions(year,subject,number,qtype,stem_html,options_json,answer,answer_html,tags,source_url)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?)',
            (r['year'], r['subject'], r['number'], r['qtype'], r['stem_html'],
             json.dumps(r['options'], ensure_ascii=False), r['answer'], r['answer_html'], r['tags'],
             f"https://www.csgraduates.com/study_methods/408quiz/{r['year']}/"),
        )
    conn.commit()
    c = sum(1 for r in records if r['qtype'] == 'choice')
    s = sum(1 for r in records if r['qtype'] == 'subjective')
    print(f'播种完成：选择 {c} · 大题 {s} → {DB_PATH}')
    conn.close()


if __name__ == '__main__':
    main()

