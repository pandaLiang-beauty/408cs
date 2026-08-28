#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从已有做题记录(session_items)重建 point_schedule（知识点强化池）。
按时间顺序把每条选择题批改结果喂给 scheduler.update_point，等价于“重放”历史。
可重复运行（先清空 point_schedule 再重放）。用法（backend/）：python rebuild_points.py"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.config import DB_PATH  # noqa: E402
from app import schema, scheduler  # noqa: E402


def main():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    schema.initialize(conn)
    conn.execute('DELETE FROM point_schedule')
    rows = conn.execute(
        "SELECT si.result, q.tags FROM session_items si JOIN questions q ON q.id=si.question_id"
        " WHERE q.qtype='choice' AND si.result!='' ORDER BY si.updated_at").fetchall()
    n = 0
    for r in rows:
        for tag in scheduler.split_tags(r['tags']):
            scheduler.update_point(conn, tag, r['result'])
            n += 1
    conn.commit()
    pool = conn.execute('SELECT COUNT(*) c FROM point_schedule').fetchone()['c']
    print(f'重放 {len(rows)} 条批改记录（{n} 次知识点更新）→ 薄弱知识点 {pool} 个')
    conn.close()


if __name__ == '__main__':
    main()
