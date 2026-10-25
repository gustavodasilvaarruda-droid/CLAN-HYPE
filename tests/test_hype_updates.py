"""Tests for the HYPE update read-only Flask routes."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from flask import Flask
from modules.hype_updates import hype_updates_bp

class HypeUpdatesTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'HYPE_UPDATES_DIR': str(self.directory), 'HYPE_UPDATES_RELEASE_BASE_URL': ''})
        self.env.start()
        self.addCleanup(self.env.stop)
        app = Flask(__name__)
        app.register_blueprint(hype_updates_bp)
        self.client = app.test_client()

    def test_no_manifest_until_published(self):
        response = self.client.get('/hype-updates/manifest.properties')
        self.assertEqual(response.status_code, 404)

    def test_serves_manifest_without_cache(self):
        (self.directory / 'manifest.properties').write_text('release=1', encoding='utf-8')
        response = self.client.get('/hype-updates/manifest.properties')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_release_allowlist(self):
        folder = self.directory / 'releases'
        folder.mkdir()
        (folder / 'hypeclient-r1.jar').write_bytes(b'test')
        self.assertEqual(self.client.get('/hype-updates/releases/hypeclient-r1.jar').status_code, 200)
        self.assertEqual(self.client.get('/hype-updates/releases/latest.jar').status_code, 404)

    def test_missing_release_is_404_without_external_storage(self):
        response = self.client.get('/hype-updates/releases/hypeclient-r7.jar')
        self.assertEqual(response.status_code, 404)

    def test_redirects_to_persistent_https_release(self):
        with patch.dict(os.environ, {
            'HYPE_UPDATES_RELEASE_BASE_URL':
                'https://github.com/example/HYPE/releases/download/client-updates'
        }):
            response = self.client.get('/hype-updates/releases/hypeclient-r718.jar')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.headers['Location'],
            'https://github.com/example/HYPE/releases/download/client-updates/hypeclient-r718.jar'
        )
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_local_release_preferred_to_remote(self):
        releases = self.directory / 'releases'
        releases.mkdir()
        (releases / 'hypeclient-r7.jar').write_bytes(b'local-release')
        with patch.dict(os.environ, {'HYPE_UPDATES_RELEASE_BASE_URL': 'https://github.com/example/releases/download/test'}):
            response = self.client.get('/hype-updates/releases/hypeclient-r7.jar')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b'local-release')

    def test_invalid_external_storage_urls_are_rejected(self):
        invalid_bases = (
            'http://github.com/example/releases/download/test',
            'https://username:secret@github.com/releases',
            'https://github.com/releases?token=secret',
            'https://github.com/releases#fragment',
            'https:///missing-host',
            'https://github.com/path\\\\evil',
        )
        for base in invalid_bases:
            with self.subTest(base=base):
                with patch.dict(os.environ, {'HYPE_UPDATES_RELEASE_BASE_URL': base}):
                    response = self.client.get('/hype-updates/releases/hypeclient-r7.jar')
                self.assertEqual(response.status_code, 503)

    def test_filename_allowlist_enforced_before_remote_redirect(self):
        with patch.dict(os.environ, {'HYPE_UPDATES_RELEASE_BASE_URL': 'https://github.com/example/releases/download/test'}):
            self.assertEqual(
                self.client.get('/hype-updates/releases/latest.jar').status_code, 404
            )

    def test_read_only(self):
        self.assertEqual(self.client.post('/hype-updates/manifest.properties').status_code, 405)

if __name__ == '__main__':
    unittest.main()
