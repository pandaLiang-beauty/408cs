import sqlite3
import unittest

from fastapi import HTTPException
from pydantic import ValidationError

from app import annotations as api, schema


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        schema.initialize(self.conn)
        self.conn.execute('INSERT INTO questions(id,year,number,stem_html,options_json,answer_html) VALUES(1,2009,1,?,?,?)',
                          ('题干含有中文和数学符号。', '[{"key":"A","text":"选项甲"},{"key":"B","text":"选项乙"}]', '<p>解题过程。</p>'))
        self.conn.execute("INSERT INTO sessions(id,kind,year,status) VALUES(1,'exam',2009,'graded'),(2,'exam',2009,'graded'),(3,'exam',2009,'doing')")
        self.conn.execute("INSERT INTO session_items(session_id,question_id,chosen,result) VALUES(1,1,'A','wrong'),(2,1,'B','correct'),(3,1,'','')")
        self.conn.execute("INSERT INTO notes(question_id,session_id,body) VALUES(1,1,'原有笔记')")
        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def create(self, sid=1, **kwargs):
        payload = dict(question_id=1, region='stem', quote='中文', start_offset=4, end_offset=6,
                       prefix='题干含有', suffix='和数学符号。', body='注意这个条件')
        payload.update(kwargs)
        return api.add_annotation(sid, api.AnnotationIn(**payload), self.conn)

    def test_annotations_are_scoped_to_attempt_and_do_not_change_answers_or_notes(self):
        before = [tuple(row) for row in self.conn.execute('SELECT * FROM session_items ORDER BY id')]
        first = self.create()
        self.assertEqual(api.list_annotations(2, self.conn), [])
        second = self.create(sid=2, body='第二次作答的想法')
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(api.list_annotations(1, self.conn)[0]['body'], '注意这个条件')
        self.assertEqual(api.list_annotations(2, self.conn)[0]['body'], '第二次作答的想法')
        self.assertEqual([tuple(row) for row in self.conn.execute('SELECT * FROM session_items ORDER BY id')], before)
        self.assertEqual(self.conn.execute('SELECT body FROM notes').fetchone()[0], '原有笔记')

    def test_edit_resolve_reopen_and_delete_leave_the_anchor_intact(self):
        saved = self.create()
        edited = api.edit_annotation(1, saved['id'], api.AnnotationPatch(body='更新后的思路', resolved=True), self.conn)
        self.assertEqual(edited['body'], '更新后的思路')
        self.assertTrue(edited['resolved'])
        self.assertEqual(edited['quote'], saved['quote'])
        self.assertEqual(edited['created_at'], saved['created_at'])
        reopened = api.edit_annotation(1, saved['id'], api.AnnotationPatch(resolved=False), self.conn)
        self.assertFalse(reopened['resolved'])
        api.delete_annotation(1, saved['id'], self.conn)
        self.assertEqual(api.list_annotations(1, self.conn), [])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM session_items').fetchone()[0], 3)

    def test_retry_is_idempotent_and_cannot_overwrite_an_edited_comment(self):
        first = self.create(client_id='same-draft')
        second = self.create(client_id='same-draft')
        self.assertEqual(first['id'], second['id'])
        api.edit_annotation(1, first['id'], api.AnnotationPatch(body='已经编辑过'), self.conn)
        with self.assertRaises(HTTPException) as raised:
            self.create(client_id='same-draft')
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(api.list_annotations(1, self.conn)[0]['body'], '已经编辑过')

    def test_cross_attempt_writes_and_client_id_reuse_are_rejected(self):
        saved = self.create(client_id='first-attempt')
        for action in (
            lambda: api.edit_annotation(2, saved['id'], api.AnnotationPatch(body='跨卷修改'), self.conn),
            lambda: api.delete_annotation(2, saved['id'], self.conn),
            lambda: self.create(sid=2, client_id='first-attempt'),
            lambda: self.create(question_id=999),
        ):
            with self.assertRaises(HTTPException):
                action()
        self.assertEqual(api.list_annotations(1, self.conn), [saved])

    def test_only_visible_regions_can_be_annotated(self):
        self.create(region='option:A', quote='选项甲', start_offset=0, end_offset=3)
        self.create(region='explanation', quote='解题过程', start_offset=0, end_offset=4)
        for kwargs in ({'region':'option:C'}, {'region':'unknown'}, {'sid':3,'region':'explanation'}):
            with self.assertRaises(HTTPException):
                self.create(**kwargs)

    def test_question_level_annotation_and_unicode_offsets(self):
        saved = self.create(region='question', quote='', start_offset=None, end_offset=None)
        self.assertEqual(saved['region'], 'question')
        unicode = self.create(quote='中😀文', start_offset=0, end_offset=4)
        self.assertEqual(unicode['quote'], '中😀文')
        with self.assertRaises(HTTPException):
            self.create(quote='中😀文', start_offset=0, end_offset=3)

    def test_blank_body_and_invalid_selection_are_rejected(self):
        for kwargs in ({'body':' \n '}, {'quote':''}, {'end_offset':5}, {'region':'question'}):
            with self.assertRaises(HTTPException):
                self.create(**kwargs)
        for kwargs in ({'body':'x'*5001}, {'start_offset':-1}, {'quote':'x'*10001}):
            with self.assertRaises(ValidationError):
                self.create(**kwargs)
        self.assertEqual(api.list_annotations(1, self.conn), [])

    def test_reinitializing_schema_keeps_annotations_and_old_records(self):
        saved = self.create()
        schema.initialize(self.conn)
        schema.initialize(self.conn)
        self.assertEqual(api.list_annotations(1, self.conn), [saved])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM sessions').fetchone()[0], 3)

    def test_review_annotation_is_available_only_after_submission(self):
        with self.assertRaises(HTTPException) as raised:
            self.create(sid=3)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(api.list_annotations(3, self.conn), [])
        self.conn.execute("UPDATE sessions SET status='graded' WHERE id=3")
        saved = self.create(sid=3)
        self.assertEqual(saved['session_id'], 3)

    def test_unknown_session_has_no_annotation_list(self):
        with self.assertRaises(HTTPException) as raised:
            api.list_annotations(999, self.conn)
        self.assertEqual(raised.exception.status_code, 404)


if __name__ == '__main__':
    unittest.main()
