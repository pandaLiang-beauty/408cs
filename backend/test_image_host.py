import base64
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import auth, image_host, schema
from app.db import get_db


PNG = base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='
)


class ImageHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'images'
        self.directory.mkdir()
        self.conn = sqlite3.connect(Path(self.temp.name) / 'study.db', check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        schema.initialize(self.conn)
        self.dir_patch = patch.object(image_host, 'IMAGE_HOST_DIR', self.directory)
        self.dir_patch.start()
        self.addCleanup(self.dir_patch.stop)
        self.base_patch = patch.object(image_host.settings, 'PUBLIC_BASE', 'https://408.example.test')
        self.base_patch.start()
        self.addCleanup(self.base_patch.stop)
        app = FastAPI()
        app.include_router(image_host.router)
        app.dependency_overrides[get_db] = lambda: self.conn
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.client.cookies.set(auth.COOKIE, auth.make_token(1, 'me'))

    def upload(self, filename='截图.png', blob=PNG):
        return self.client.post('/api/image-host', json={
            'image_base64': 'data:image/png;base64,' + base64.b64encode(blob).decode(),
            'filename': filename,
        })

    def test_upload_persists_original_image_with_public_link(self):
        response = self.upload()
        self.assertEqual(response.status_code, 201)
        image = response.json()
        self.assertEqual(image['public_url'], 'https://408.example.test' + image['url'])
        self.assertEqual(image['size_bytes'], len(PNG))
        self.assertEqual(image['filename'], '截图.png')
        self.assertRegex(image['url'], r'/api/image-host/files/[0-9a-f]{48}\.png$')
        # 再次初始化模拟重启，既有链接与文件仍可用。
        schema.initialize(self.conn)
        listed = self.client.get('/api/image-host').json()['images']
        self.assertEqual(listed, [image])
        self.client.cookies.clear()
        content = self.client.get(image['url'])
        self.assertEqual(content.status_code, 200)
        self.assertEqual(content.content, PNG)
        self.assertEqual(content.headers['content-type'], 'image/png')
        self.assertEqual(content.headers['x-content-type-options'], 'nosniff')

    def test_upload_and_list_require_login(self):
        self.client.cookies.clear()
        self.assertEqual(self.upload().status_code, 401)
        self.assertEqual(self.client.get('/api/image-host').status_code, 401)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_filename_cannot_change_storage_path_or_content_type(self):
        image = self.upload('..\\folder/<test>.html').json()
        self.assertEqual(image['filename'], '<test>.html')
        self.assertEqual(image['mime_type'], 'image/png')
        self.assertTrue(image['url'].endswith('.png'))
        self.assertEqual(len(list(self.directory.iterdir())), 1)
        self.assertEqual(self.client.get('/api/image-host/files/unknown.png').status_code, 404)

    def test_invalid_and_oversized_images_leave_no_records(self):
        for blob in (b'', b'<svg onload="alert(1)"></svg>', b'<html>not an image</html>'):
            self.assertEqual(self.upload(blob=blob).status_code, 400)
        self.assertEqual(self.client.post('/api/image-host', json={'image_base64': 'not base64!'}).status_code, 400)
        # 覆盖刚好达到限制，以及 Base64 长度相同但解码后超限的情况。
        with patch.object(image_host, 'MAX_IMAGE_BYTES', len(PNG)):
            self.assertEqual(self.upload(blob=PNG + b'x').status_code, 413)
            self.assertEqual(self.upload(blob=PNG).status_code, 201)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM hosted_images').fetchone()[0], 1)

    def test_disk_failure_rolls_back_metadata(self):
        with patch.object(Path, 'open', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.upload()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM hosted_images').fetchone()[0], 0)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_cursor_pagination_survives_new_uploads(self):
        first, second, third = [self.upload(f'{index}.png').json() for index in range(3)]
        page = self.client.get('/api/image-host?limit=2').json()
        self.assertEqual([image['id'] for image in page['images']], [third['id'], second['id']])
        self.upload('new.png')
        older = self.client.get('/api/image-host', params={'before_id': page['next_cursor'], 'limit': 2}).json()
        self.assertEqual(older['images'], [first])
        self.assertIsNone(older['next_cursor'])
        self.assertEqual(self.client.get('/api/image-host?limit=0').status_code, 422)

    def test_missing_file_returns_404_and_unconfigured_base_uses_relative_url(self):
        with patch.object(image_host.settings, 'PUBLIC_BASE', ''):
            image = self.upload().json()
        self.assertEqual(image['public_url'], image['url'])
        next(self.directory.iterdir()).unlink()
        self.assertEqual(self.client.get(image['url']).status_code, 404)


if __name__ == '__main__':
    unittest.main()
