import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

from fastapi import HTTPException

from app import api, schema, upload


PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)
GIF = base64.b64decode('R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7')


def data_url(blob, mime='image/png'):
    return f'data:{mime};base64,' + base64.b64encode(blob).decode()


class DraftImageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        schema.initialize(self.conn)
        self.conn.execute(
            "INSERT INTO questions(id,year,subject,number,stem_html) VALUES(13,2009,'组成原理',13,'题干')")
        for sid in (9, 10):
            self.conn.execute("INSERT INTO sessions(id,year) VALUES(?,2009)", (sid,))
            self.conn.execute('INSERT INTO session_items(session_id,question_id) VALUES(?,13)', (sid,))
        self.conn.commit()
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)
        self.dir_patch = patch.object(upload, 'DRAFTS_DIR', self.directory)
        self.dir_patch.start()

    def tearDown(self):
        self.dir_patch.stop()
        self.tempdir.cleanup()
        self.conn.close()

    def save(self, blob=PNG, sid=9):
        return api.save_draft(sid, api.DraftIn(question_id=13, image_base64=data_url(blob)), self.conn)

    def image_bytes(self, image):
        return (self.directory / Path(urlsplit(image['url']).path).name).read_bytes()

    def test_second_upload_keeps_first_image_and_restores_both_on_reload(self):
        first = self.save()
        second = self.save(GIF)

        self.assertEqual(len(second['drafts']), 2)
        self.assertEqual(first['drafts'][0], second['drafts'][0])
        self.assertNotEqual(first['draft_url'], second['draft_url'])
        self.assertEqual([self.image_bytes(image) for image in second['drafts']], [PNG, GIF])
        self.assertTrue(urlsplit(second['draft_url']).path.endswith('.gif'))
        restored = api.get_session(9, self.conn)['items'][13]
        self.assertEqual(restored['drafts'], second['drafts'])
        self.assertEqual(restored['draft_url'], second['draft_url'])

    def test_old_single_draft_migrates_once_and_survives_more_uploads(self):
        (self.directory / 's9_q13.png').write_bytes(PNG)
        self.conn.execute("UPDATE session_items SET draft_path='s9_q13.png' WHERE session_id=9")
        self.conn.execute('DROP TABLE draft_images')
        self.conn.commit()

        schema.initialize(self.conn)
        schema.initialize(self.conn)
        migrated = api.get_draft(9, 13, self.conn)
        self.assertEqual(len(migrated['drafts']), 1)
        self.assertIn('?v=', migrated['draft_url'])
        self.assertEqual(self.image_bytes(migrated['drafts'][0]), PNG)

        added = self.save(GIF)
        schema.initialize(self.conn)
        restored = api.get_draft(9, 13, self.conn)
        self.assertEqual(restored['drafts'], added['drafts'])
        self.assertEqual([self.image_bytes(image) for image in restored['drafts']], [PNG, GIF])

    def test_drafts_stay_with_their_own_attempt(self):
        first = self.save(sid=9)
        second = self.save(GIF, sid=10)

        self.assertEqual(api.get_draft(9, 13, self.conn)['drafts'], first['drafts'])
        self.assertEqual(api.get_draft(10, 13, self.conn)['drafts'], second['drafts'])
        self.assertNotEqual(first['draft_url'], second['draft_url'])

    def test_answer_edits_do_not_change_draft_urls(self):
        uploaded = self.save()
        api.patch_item(9, 13, api.PatchItemIn(chosen='A', fuzzy=True), self.conn)

        self.assertEqual(api.get_draft(9, 13, self.conn)['drafts'], uploaded['drafts'])

    def test_phone_uploads_append_with_fresh_tokens(self):
        local = self.save()
        for blob in (GIF, PNG):
            token = upload.issue_token(self.conn, 9, 13)['token']
            result = upload.upload_submit(token, upload.ImageUploadIn(image_base64=data_url(blob)), self.conn)

        self.assertEqual(len(result['drafts']), 3)
        self.assertEqual(result['drafts'][0], local['drafts'][0])
        self.assertEqual([self.image_bytes(image) for image in result['drafts']], [PNG, GIF, PNG])

    def test_used_token_cannot_append_twice_even_after_a_stale_validation(self):
        token = upload.issue_token(self.conn, 9, 13)['token']
        stale_token = upload._load_token(self.conn, token)
        body = upload.ImageUploadIn(image_base64=data_url(PNG))
        first = upload.upload_submit(token, body, self.conn)

        with patch.object(upload, '_load_token', return_value=stale_token):
            with self.assertRaises(HTTPException) as raised:
                upload.upload_submit(token, body, self.conn)
        self.assertEqual(raised.exception.status_code, 410)
        self.assertEqual(api.get_draft(9, 13, self.conn)['drafts'], first['drafts'])
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_invalid_image_keeps_token_available_and_existing_draft_intact(self):
        first = self.save()
        token = upload.issue_token(self.conn, 9, 13)['token']
        with self.assertRaises(HTTPException) as raised:
            upload.upload_submit(token, upload.ImageUploadIn(image_base64=data_url(b'not an image')), self.conn)

        self.assertEqual(raised.exception.status_code, 400)
        self.assertIsNone(upload._load_token(self.conn, token)['used_at'])
        self.assertEqual(api.get_draft(9, 13, self.conn)['drafts'], first['drafts'])
        self.assertEqual(self.image_bytes(first['drafts'][0]), PNG)

    def test_database_failure_cleans_new_file_and_does_not_consume_token(self):
        first = self.save()
        token = upload.issue_token(self.conn, 9, 13)['token']
        self.conn.execute(
            "CREATE TRIGGER fail_draft_update BEFORE UPDATE OF draft_path ON session_items "
            "BEGIN SELECT RAISE(ABORT, 'test failure'); END")
        self.conn.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            upload.upload_submit(token, upload.ImageUploadIn(image_base64=data_url(GIF)), self.conn)

        self.assertIsNone(upload._load_token(self.conn, token)['used_at'])
        self.assertEqual(api.get_draft(9, 13, self.conn)['drafts'], first['drafts'])
        self.assertEqual(len(list(self.directory.iterdir())), 1)

    def test_question_outside_session_cannot_receive_a_draft(self):
        with self.assertRaises(HTTPException) as raised:
            api.save_draft(9, api.DraftIn(question_id=999, image_base64=data_url(PNG)), self.conn)

        self.assertEqual(raised.exception.status_code, 404)
        self.assertEqual(list(self.directory.iterdir()), [])


if __name__ == '__main__':
    unittest.main()
