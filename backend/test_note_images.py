import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import api, schema


PNG_1X1 = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


class NoteImageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        schema.initialize(self.conn)
        self.conn.execute(
            "INSERT INTO questions(year,subject,number,stem_html) VALUES(2024,'操作系统',1,'题干')"
        )
        self.question_id = self.conn.execute('SELECT id FROM questions').fetchone()['id']
        self.tempdir = tempfile.TemporaryDirectory()
        self.dir_patch = patch.object(api, 'NOTE_IMAGES_DIR', Path(self.tempdir.name))
        self.dir_patch.start()

    def tearDown(self):
        self.dir_patch.stop()
        self.tempdir.cleanup()
        self.conn.close()

    def image(self, filename='clipboard.png'):
        return api.NoteImageIn(
            image_base64='data:image/png;base64,' + base64.b64encode(PNG_1X1).decode(),
            filename=filename,
        )

    def test_image_only_note_is_persisted_and_returned(self):
        note = api.add_note(
            api.NoteIn(question_id=self.question_id, images=[self.image()]), self.conn
        )

        self.assertEqual(note['body'], '')
        self.assertEqual(len(note['images']), 1)
        self.assertEqual(note['images'][0]['mime_type'], 'image/png')
        self.assertEqual(note['images'][0]['filename'], 'clipboard.png')
        stored = self.conn.execute('SELECT stored_name FROM note_images').fetchone()['stored_name']
        self.assertEqual((Path(self.tempdir.name) / stored).read_bytes(), PNG_1X1)

    def test_existing_note_accepts_more_images(self):
        note = api.add_note(api.NoteIn(question_id=self.question_id, body='错因'), self.conn)
        updated = api.add_note_images(
            note['id'], api.NoteIn(images=[self.image(), self.image('second.png')]), self.conn
        )

        self.assertEqual([item['filename'] for item in updated['images']], ['clipboard.png', 'second.png'])

    def test_last_image_cannot_be_removed_from_image_only_note(self):
        note = api.add_note(
            api.NoteIn(question_id=self.question_id, images=[self.image()]), self.conn
        )

        with self.assertRaises(HTTPException) as raised:
            api.delete_note_image(note['images'][0]['id'], self.conn)
        self.assertEqual(raised.exception.status_code, 400)

    def test_deleting_note_removes_its_files(self):
        note = api.add_note(
            api.NoteIn(question_id=self.question_id, body='有图', images=[self.image()]), self.conn
        )
        stored = self.conn.execute('SELECT stored_name FROM note_images').fetchone()['stored_name']
        path = Path(self.tempdir.name) / stored

        api.delete_note(note['id'], self.conn)

        self.assertFalse(path.exists())
        self.assertEqual(self.conn.execute('SELECT COUNT(*) count FROM notes').fetchone()['count'], 0)


if __name__ == '__main__':
    unittest.main()
