"""The public workbench serves packaged assets without opening private APIs."""
from importlib.resources import files
import unittest
import shutil
import subprocess
from pathlib import Path
from urllib.request import urlopen
from urllib.error import HTTPError
from transport_support import LiveService


class WebTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()

    def tearDown(self):
        self.live.close()

    def test_public_page_and_assets_have_security_headers(self):
        for path, mime, resource in [('/', 'text/html', 'index.html'),
                                    ('/static/styles.css', 'text/css', 'styles.css'),
                                    ('/static/app.js', 'text/javascript', 'app.js')]:
            with urlopen(self.live.url + path) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(response.headers.get_content_type(), mime)
                self.assertEqual(response.read(), files('crewmesh').joinpath('static', resource).read_bytes())
                policy = response.headers['Content-Security-Policy']
                self.assertIn("script-src 'self'", policy)
                self.assertIn("frame-ancestors 'none'", policy)
                self.assertNotIn('unsafe-inline', policy)
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')

    def test_public_page_does_not_open_private_operations(self):
        self.assertEqual(self.live.request('GET', '/api/snapshot')[0], 401)
        owner, _ = self.live.bootstrap()
        self.assertEqual(self.live.request('GET', '/api/snapshot', owner['web_token'])[0], 200)
        self.assertEqual(self.live.request('POST', '/api/tasks/1/claim', owner['web_token'], {})[0], 401)

    def test_asset_paths_are_fixed_and_do_not_expose_source(self):
        for path in ('/static/api.py', '/static/../identity.py', '/docs/agent-connection.md'):
            with self.assertRaises(HTTPError) as rejected:
                urlopen(self.live.url + path)
            self.assertNotEqual(rejected.exception.code, 200)
            rejected.exception.close()
        with urlopen(self.live.url + '/favicon.ico') as response:
            self.assertEqual(response.status, 204)

    @unittest.skipUnless(shutil.which('node'), 'Node is needed for browser session regression checks')
    def test_delayed_response_bodies_cannot_mutate_new_session(self):
        root = Path(__file__).resolve().parent.parent
        result = subprocess.run(['node', str(root / 'tests/web_session_regression.js'),
                                 str(root / 'src/static/app.js')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
