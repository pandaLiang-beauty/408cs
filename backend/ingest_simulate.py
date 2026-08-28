#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""增量导入 408 模拟卷（data/raw_sim/{1..6}.html）到 questions 表，source='simulate'。
非破坏：只 INSERT 尚不存在的题（按 source+year(=套号)+number 去重），绝不 DELETE，
以免级联清空已有的做题记录/笔记/强化池。用法（在 backend/）：python ingest_simulate.py"""
import glob
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import DB_PATH  # noqa: E402
from app import schema  # noqa: E402
import seed  # noqa: E402  复用真题解析器（parse_year 已含页脚截断）

RAW_SIM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data', 'raw_sim')


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    schema.initialize(conn)  # 确保 source 列已就位

    inserted = skipped = 0
    for path in sorted(glob.glob(os.path.join(RAW_SIM_DIR, '*.html'))):
        set_no = int(os.path.splitext(os.path.basename(path))[0])
        html = open(path, 'rb').read().decode('utf-8', 'ignore')
        records = seed.parse_year(set_no, html)  # year 字段在此复用为“套号”
        for r in records:
            exists = conn.execute(
                "SELECT 1 FROM questions WHERE source='simulate' AND year=? AND number=?",
                (set_no, r['number'])).fetchone()
            if exists:
                skipped += 1
                continue
            conn.execute(
                'INSERT INTO questions(year,subject,number,qtype,source,stem_html,options_json,'
                'answer,answer_html,tags,source_url)'
                " VALUES(?,?,?,?,'simulate',?,?,?,?,?,?)",
                (set_no, r['subject'], r['number'], r['qtype'], r['stem_html'],
                 json.dumps(r['options'], ensure_ascii=False), r['answer'], r['answer_html'],
                 r['tags'], f"https://www.csgraduates.com/study_methods/408simulate/{set_no}/"),
            )
            inserted += 1
    conn.commit()
    tot = conn.execute("SELECT COUNT(*) c FROM questions WHERE source='simulate'").fetchone()['c']
    print(f'模拟卷导入完成：新增 {inserted} · 跳过(已存在) {skipped} · 库内模拟题合计 {tot}')
    conn.close()


if __name__ == '__main__':
    main()
