import io
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import api, grading, schema


CFG = {'base_url': 'https://gateway.example/v1', 'api_key': 'test-key', 'model': 'test-model'}
PARTIAL = {'verdict': '部分对', 'score_ratio': 0.4, 'comment': '结论正确，反例不成立。'}


class GatewayTests(unittest.TestCase):
    def test_disabled_model_error_is_actionable(self):
        payload = {'error': {'message': 'This model is temporarily disabled', 'code': 'model_disabled'}}
        error = urllib.error.HTTPError(CFG['base_url'], 503, 'Unavailable', {}, io.BytesIO(json.dumps(payload).encode()))
        with patch.object(grading.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaisesRegex(grading.GatewayError, '模型已被网关停用'):
                grading.chat(CFG, [])

    def test_gateway_error_does_not_expose_credentials(self):
        payload = {'error': {'message': 'Invalid key: test-key'}}
        error = urllib.error.HTTPError(CFG['base_url'], 401, 'Unauthorized', {}, io.BytesIO(json.dumps(payload).encode()))
        with patch.object(grading.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(grading.GatewayError) as raised:
                grading.chat(CFG, [])
        self.assertIn('401', str(raised.exception))
        self.assertNotIn(CFG['api_key'], str(raised.exception))

    def test_non_json_gateway_error_and_timeout_remain_retryable(self):
        errors = (
            urllib.error.HTTPError(CFG['base_url'], 502, 'Bad Gateway', {}, io.BytesIO(b'<html>Bad Gateway</html>')),
            TimeoutError('timed out'),
            urllib.error.URLError(TimeoutError('handshake timed out')),
        )
        for error in errors:
            with self.subTest(error=type(error).__name__), patch.object(grading.urllib.request, 'urlopen', side_effect=error):
                with self.assertRaises(grading.GatewayError):
                    grading.chat(CFG, [])

    def test_valid_fenced_grade_is_accepted(self):
        with patch.object(grading, 'chat', return_value='```json\n' + json.dumps(PARTIAL) + '\n```'):
            self.assertEqual(grading.grade(CFG, '题干', '参考答案', '作答'), PARTIAL)

    def test_invalid_grades_are_not_replaced_with_half_credit(self):
        invalid = [None, '服务暂不可用', '{}']
        for field, values in {
            'verdict': ['未知', None], 'score_ratio': [None, True, '0.5', -1, 2, float('nan')],
            'comment': [None, [], '  '],
        }.items():
            invalid.extend(json.dumps({**PARTIAL, field: value}) for value in values)
        for content in invalid:
            with self.subTest(content=content), patch.object(grading, 'chat', return_value=content):
                with self.assertRaises(grading.GatewayError):
                    grading.grade(CFG, '题干', '参考答案', '作答')


class SubjectiveGradingTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.path = Path(self.tempdir.name) / 'study.db'
        self.conn = self.connect()
        schema.initialize(self.conn)
        self.conn.execute("INSERT INTO questions(id,year,number,qtype,stem_html,answer_html) VALUES(41,2009,41,'subjective','题干','参考答案')")
        self.conn.execute("INSERT INTO sessions(id,year,status) VALUES(9,2009,'doing')")
        self.conn.execute('INSERT INTO session_items(session_id,question_id) VALUES(9,41)')
        self.conn.commit()
        self.config_patch = patch.object(api.llmconfig, 'active_config', return_value=CFG)
        self.config_patch.start()

    def connect(self):
        conn = sqlite3.connect(self.path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys=ON')
        return conn

    def tearDown(self):
        self.config_patch.stop()
        self.conn.close()
        self.tempdir.cleanup()

    def grade(self, answer='我的反例', conn=None):
        return api.grade_subjective(9, api.GradeIn(question_id=41, answer_text=answer), conn or self.conn)

    def item(self):
        return self.conn.execute('SELECT * FROM session_items WHERE session_id=9 AND question_id=41').fetchone()

    def test_failed_grading_keeps_answer_and_can_be_retried(self):
        with patch.object(grading, 'grade', side_effect=grading.GatewayError('模型已被停用')):
            with self.assertRaises(HTTPException) as raised:
                self.grade()
        self.assertEqual(raised.exception.status_code, 502)
        self.assertEqual(self.item()['answer_text'], '我的反例')
        self.assertEqual(self.item()['verdict'], '')
        self.assertIsNone(self.item()['score_ratio'])
        self.assertIsNone(self.item()['grading_started_at'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM review_schedule').fetchone()[0], 0)
        with patch.object(grading, 'grade', return_value=PARTIAL):
            self.assertEqual(self.grade()['score_ratio'], 0.4)

    def test_retries_restore_full_result_without_regrading_or_rescheduling(self):
        with patch.object(grading, 'grade', return_value=PARTIAL) as model:
            first = self.grade()
            self.assertEqual(self.grade(), first)
            self.assertEqual(self.grade('另一份作答'), first)
            self.assertEqual(first['answer_text'], '我的反例')
            model.assert_called_once()
        restored = api.get_session(9, self.conn)['items'][41]
        for field in ('verdict', 'score_ratio', 'comment', 'reference_html'):
            self.assertEqual(restored[field], first[field])
        self.assertEqual(self.conn.execute('SELECT reps FROM review_schedule').fetchone()[0], 1)

    def test_concurrent_retry_does_not_call_model_twice(self):
        entered, release = threading.Event(), threading.Event()

        def slow_grade(*args):
            entered.set()
            if not release.wait(5):
                raise RuntimeError('test timed out')
            return PARTIAL

        other = self.connect()
        try:
            with patch.object(grading, 'grade', side_effect=slow_grade) as model, ThreadPoolExecutor(max_workers=1) as pool:
                pending = pool.submit(self.grade, '第一份作答', other)
                try:
                    self.assertTrue(entered.wait(5))
                    with self.assertRaises(HTTPException) as raised:
                        self.grade('重试作答')
                    self.assertEqual(raised.exception.status_code, 409)
                    self.assertEqual(self.item()['answer_text'], '第一份作答')
                finally:
                    release.set()
                self.assertEqual(pending.result(timeout=5)['score_ratio'], 0.4)
                model.assert_called_once()
        finally:
            other.close()
        self.assertEqual(self.conn.execute('SELECT reps FROM review_schedule').fetchone()[0], 1)

    def test_expired_request_can_be_retried_after_restart(self):
        self.conn.execute("UPDATE session_items SET grading_started_at='2000-01-01T00:00:00+00:00'")
        self.conn.commit()
        with patch.object(grading, 'grade', return_value=PARTIAL):
            self.assertEqual(self.grade()['score_ratio'], 0.4)
        self.assertIsNone(self.item()['grading_started_at'])

    def test_storage_failure_does_not_leave_partial_grade_or_busy_state(self):
        with patch.object(grading, 'grade', return_value=PARTIAL), patch.object(api.scheduler, 'update', side_effect=RuntimeError('storage failure')):
            with self.assertRaises(RuntimeError):
                self.grade()
        self.assertEqual(self.item()['answer_text'], '我的反例')
        self.assertEqual(self.item()['verdict'], '')
        self.assertIsNone(self.item()['grading_started_at'])

    def test_schema_upgrade_preserves_old_answers_without_inventing_scores(self):
        self.conn.execute("UPDATE session_items SET answer_text='旧作答',verdict='部分对'")
        self.conn.execute('ALTER TABLE session_items DROP COLUMN score_ratio')
        self.conn.execute('ALTER TABLE session_items DROP COLUMN grading_started_at')
        self.conn.commit()
        schema.initialize(self.conn)
        schema.initialize(self.conn)
        self.assertEqual(self.item()['answer_text'], '旧作答')
        self.assertEqual(self.item()['verdict'], '部分对')
        self.assertIsNone(self.item()['score_ratio'])


if __name__ == '__main__':
    unittest.main()
