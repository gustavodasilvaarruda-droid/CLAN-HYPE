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


    def test_auto_ovo_channel_disabled_by_default(self):
        with patch.dict(os.environ, {'HYPE_AUTO_OVO_RELEASE_BASE_URL': ''}):
            health = self.client.get('/hype-updates/auto-ovo/health')
            manifest = self.client.get('/hype-updates/auto-ovo/manifest.properties')
            jar = self.client.get('/hype-updates/auto-ovo/releases/hype-auto-ovo-h20.jar')
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.json['manifest_present'])
        self.assertEqual(health.json['service'], 'hype-auto-ovo-updates')
        self.assertEqual(manifest.status_code, 404)
        self.assertEqual(jar.status_code, 404)

    def test_auto_ovo_manifest_is_independent_of_r717(self):
        folder = self.directory / 'auto-ovo'
        folder.mkdir()
        (folder / 'manifest.properties').write_text('test-only', encoding='utf-8')
        r = self.client.get('/hype-updates/auto-ovo/manifest.properties')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, b'test-only')
        self.assertIn('no-store', r.headers['Cache-Control'])
        self.assertTrue(self.client.get('/hype-updates/auto-ovo/health').json['manifest_present'])
        self.assertEqual(self.client.get('/hype-updates/manifest.properties').status_code, 404)

    def test_auto_ovo_releases_allowlist_and_local_file(self):
        folder = self.directory / 'auto-ovo' / 'releases'
        folder.mkdir(parents=True)
        (folder / 'hype-auto-ovo-h20.jar').write_bytes(b'test-only')
        r = self.client.get('/hype-updates/auto-ovo/releases/hype-auto-ovo-h20.jar')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.data, b'test-only')
        for name in ('hypeclient-r20.jar', 'latest.jar', 'hype-auto-ovo-h0.jar', 'hype-auto-ovo-h20.zip'):
            with self.subTest(name=name):
                self.assertEqual(
                    self.client.get('/hype-updates/auto-ovo/releases/' + name).status_code, 404
                )

    def test_auto_ovo_redirect_requires_own_https_storage_variable(self):
        with patch.dict(os.environ, {
            'HYPE_AUTO_OVO_RELEASE_BASE_URL': '',
            'HYPE_UPDATES_RELEASE_BASE_URL': 'https://github.com/example/client-updates'
        }):
            self.assertEqual(
                self.client.get('/hype-updates/auto-ovo/releases/hype-auto-ovo-h21.jar').status_code, 404
            )
        with patch.dict(os.environ, {
            'HYPE_AUTO_OVO_RELEASE_BASE_URL': 'https://github.com/example/releases/download/auto-ovo'
        }):
            r = self.client.get('/hype-updates/auto-ovo/releases/hype-auto-ovo-h21.jar')
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            r.headers['Location'],
            'https://github.com/example/releases/download/auto-ovo/hype-auto-ovo-h21.jar'
        )

    def test_auto_ovo_bad_external_urls_rejected(self):
        for base in ('http://github.com/demo', 'https://u:pw@github.com/demo',
                     'https://github.com/demo?token=x', 'https://github.com/demo#x'):
            with self.subTest(base=base):
                with patch.dict(os.environ, {'HYPE_AUTO_OVO_RELEASE_BASE_URL': base}):
                    r = self.client.get('/hype-updates/auto-ovo/releases/hype-auto-ovo-h20.jar')
                self.assertEqual(r.status_code, 503)

    def test_auto_ovo_endpoints_are_read_only(self):
        self.assertEqual(
            self.client.post('/hype-updates/auto-ovo/manifest.properties').status_code, 405
        )

if __name__ == '__main__':
    unittest.main()
