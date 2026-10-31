"""Synthetic registration security checks; retained artifacts, no GitHub mutation."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4
from unittest.mock import patch


class RegistrationTests(unittest.TestCase):
    def load(self):
        path = Path(__file__).with_name('github_app_registration.py')
        self.assertTrue(path.is_file(), 'Manifest registration helper must exist')
        spec = importlib.util.spec_from_file_location('github_app_registration', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_manifest_uses_read_only_private_app_and_exact_public_routes(self):
        helper = self.load()
        manifest = helper.manifest('https://acceptance.example', 'http://127.0.0.1:12345/callback', 'Acceptance')
        self.assertFalse(manifest['public'])
        self.assertEqual(manifest['callback_urls'], ['https://acceptance.example/api/git/github/callback'])
        self.assertEqual(manifest['hook_attributes'], {'url': 'https://acceptance.example/api/git/github/webhook', 'active': True})
        self.assertEqual(manifest['default_permissions'], dict.fromkeys(('contents', 'pull_requests', 'checks', 'statuses', 'metadata'), 'read'))
        # GitHub's real registration form rejects implicit installation events.
        self.assertEqual(manifest['default_events'],
                         ['push', 'pull_request', 'check_run', 'check_suite', 'status', 'release'])
        for origin in ('http://example.com', 'https://user:pass@example.com', 'https://example.com/path', 'https://example.com?x=y'):
            with self.assertRaises(ValueError):
                helper.manifest(origin, 'http://127.0.0.1:12345/callback', 'Acceptance')

    def test_callback_rejects_state_host_origin_and_replay_without_secret_output(self):
        helper = self.load()
        folder = Path('.local/test-evidence/github-app-registration') / uuid4().hex
        folder.mkdir(parents=True)
        private = {'id': 123, 'slug': 'synthetic-app', 'client_id': 'synthetic-client',
                   'client_secret': 'client-secret-marker', 'pem': 'private-pem-marker',
                   'webhook_secret': 'webhook-secret-marker'}
        exchanges = []
        def exchange(code):
            exchanges.append(code)
            return private
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            server = helper.registration_server('https://acceptance.example', folder, exchange=exchange)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            origin = 'http://127.0.0.1:' + str(server.server_port)
            try:
                for path, headers in [('/callback?code=synthetic-code&state=wrong', {}),
                                      (server.start_path, {'Host': 'evil.example'}),
                                      (server.start_path, {'Origin': 'https://evil.example'})]:
                    with self.assertRaises(HTTPError) as denied:
                        urlopen(Request(origin + path, headers=headers), timeout=5)
                    self.assertIn(denied.exception.code, (400, 403))
                self.assertEqual(exchanges, [])
                with urlopen(origin + server.start_path, timeout=5) as response:
                    page = response.read().decode()
                    self.assertEqual(response.headers['Cache-Control'], 'no-store')
                self.assertIn('https://github.com/settings/apps/new?state=', page)
                callback = origin + '/callback?code=synthetic-code&state=' + server.state
                with urlopen(callback, timeout=5) as response:
                    result = response.read().decode()
                with self.assertRaises(HTTPError) as replay:
                    urlopen(callback, timeout=5)
                self.assertEqual(replay.exception.code, 409)
                self.assertEqual(exchanges, ['synthetic-code'])
                saved = json.loads((folder / 'github-app-private.json').read_text())
                self.assertEqual(saved, private)
                combined = output.getvalue() + page + result
                for secret in ('synthetic-code', *[private[k] for k in ('client_secret', 'pem', 'webhook_secret')]):
                    self.assertNotIn(secret, combined)
            finally:
                server.shutdown()
                thread.join(5)
                server.server_close()

    def test_secret_exchange_disables_redirects_and_bounds_response(self):
        helper = self.load()
        redirect = helper.NoRedirect()
        self.assertIsNone(redirect.redirect_request(None, None, 302, '', {}, 'https://evil.example'))
        with self.assertRaises(ValueError):
            helper.exchange_manifest_code('../not-a-code')
        class Oversized:
            status = 201
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self, limit):
                self.limit = limit
                return b'x' * limit
        response = Oversized()
        class Opener:
            def open(self, request, timeout):
                self.request, self.timeout = request, timeout
                return response
        opener = Opener()
        with patch.object(helper, 'build_opener', return_value=opener):
            with self.assertRaisesRegex(ValueError, 'size limit'):
                helper.exchange_manifest_code('synthetic-code')
        self.assertEqual(response.limit, helper.MAX_RESPONSE + 1)
        self.assertEqual(opener.timeout, 20)
        self.assertEqual(opener.request.get_method(), 'POST')
        self.assertEqual(opener.request.full_url, 'https://api.github.com/app-manifests/synthetic-code/conversions')


if __name__ == '__main__':
    unittest.main()
