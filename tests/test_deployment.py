"""Public configuration and real HTTP reverse-proxy boundary regressions."""
import json
from pathlib import Path
import secrets
import socket
import threading
import time
import os
import io
import unittest
from unittest.mock import patch
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from uuid import uuid4

import uvicorn
from coopagents.api import create_app


class DeploymentTests(unittest.TestCase):
    def test_public_origin_and_secret_fail_closed(self):
        for origin in ('http://team.example', 'https://user@team.example',
                       'https://team.example/', 'https://team.example?q=x',
                       'https://team.example#x', 'https://team.example:0',
                       'https://team.example:99999', 'https://team.example:',
                       'https://*.example', 'https://team.example\\evil'):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                create_app('.local/test-evidence/invalid.sqlite3', public_url=origin,
                           bootstrap_secret=secrets.token_urlsafe(32))
        with self.assertRaises(ValueError):
            create_app('.local/test-evidence/invalid.sqlite3', public_url='https://team.example')
        with self.assertRaises(ValueError):
            create_app('.local/test-evidence/invalid.sqlite3', public_url='https://team.example', bootstrap_secret='weak')

    def test_proxy_configuration_requires_explicit_addresses(self):
        from coopagents.config import trusted_proxies
        self.assertEqual(trusted_proxies(''), [])
        self.assertEqual(trusted_proxies('127.0.0.1,10.0.0.0/24'), ['127.0.0.1', '10.0.0.0/24'])
        for value in ('*', '0.0.0.0/0', '::/0', 'proxy.example', '127.0.0.1,'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                trusted_proxies(value)

    def test_secret_sources_and_server_proxy_defaults(self):
        from coopagents.config import bootstrap_from_env
        from coopagents.server import main
        secret = secrets.token_urlsafe(32)
        path = Path('.local/test-evidence') / (str(uuid4()) + '.secret')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret + '\n', encoding='ascii')
        self.assertEqual(bootstrap_from_env({'COOPAGENTS_BOOTSTRAP_SECRET_FILE': str(path)}), secret)
        self.assertEqual(bootstrap_from_env({'COOPAGENTS_BOOTSTRAP_SECRET': secret}), secret)
        with self.assertRaises(ValueError):
            bootstrap_from_env({'COOPAGENTS_BOOTSTRAP_SECRET': secret, 'COOPAGENTS_BOOTSTRAP_SECRET_FILE': str(path)})
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['coopagents']), patch('coopagents.api.create_app', return_value='app'), patch('uvicorn.run') as run:
            main()
            self.assertEqual(run.call_args.kwargs['host'], '127.0.0.1')
            self.assertFalse(run.call_args.kwargs['proxy_headers'])
            self.assertEqual(run.call_args.kwargs['forwarded_allow_ips'], [])
        env = {'COOPAGENTS_HOST': '0.0.0.0', 'COOPAGENTS_PORT': '9090', 'COOPAGENTS_PUBLIC_URL': 'https://team.example',
               'COOPAGENTS_BOOTSTRAP_SECRET_FILE': str(path), 'COOPAGENTS_TRUSTED_PROXIES': '10.0.0.2'}
        with patch.dict(os.environ, env, clear=True), patch('sys.argv', ['coopagents']), patch('coopagents.api.create_app', return_value='app') as create, patch('uvicorn.run') as run:
            main()
            config=dict(create.call_args.kwargs)
            self.assertFalse(config.pop('github_app').enabled)
            self.assertEqual(config, {'public_url': 'https://team.example', 'bootstrap_secret': secret})
            self.assertEqual(run.call_args.kwargs['host'], '0.0.0.0')
            self.assertEqual(run.call_args.kwargs['port'], 9090)
            self.assertTrue(run.call_args.kwargs['proxy_headers'])
            self.assertEqual(run.call_args.kwargs['forwarded_allow_ips'], ['10.0.0.2'])

    def test_nonlocal_binding_fails_closed_without_public_config(self):
        from coopagents.server import main
        with patch.dict(os.environ, {}, clear=True), patch('sys.argv', ['coopagents', '--host', '0.0.0.0']), patch('sys.stderr', new_callable=io.StringIO) as stderr, patch('uvicorn.run') as run:
            with self.assertRaises(SystemExit) as failure:
                main()
            self.assertEqual(failure.exception.code, 2)
            self.assertIn('Non-loopback binding requires', stderr.getvalue())
            run.assert_not_called()

    def test_public_http_and_sdk_security(self):
        secret = secrets.token_urlsafe(32)
        app = create_app(Path('.local/test-evidence') / (str(uuid4()) + '.sqlite3'),
                         public_url='https://team.example', bootstrap_secret=secret)
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, access_log=False, log_level='critical', proxy_headers=False))
        thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    self.fail('Service failed to start')
                time.sleep(.01)

            def request(path, data=None, headers=None):
                merged = {'Host': 'team.example', **(headers or {})}
                body = json.dumps(data).encode() if data is not None else None
                if body is not None:
                    merged['Content-Type'] = 'application/json'
                req = Request(f'http://127.0.0.1:{port}' + path, data=body, headers=merged)
                try:
                    response = urlopen(req, timeout=10)
                except HTTPError as error:
                    response = error
                with response:
                    return response.status, json.loads(response.read())

            self.assertEqual(request('/health'), (200, {'status': 'ok'}))
            self.assertEqual(request('/ready'), (200, {'status': 'ready'}))
            self.assertEqual(request('/health', headers={'Host': 'evil.example'})[0], 400)
            self.assertEqual(request('/health', headers={'Origin': 'https://evil.example'})[0], 403)
            self.assertEqual(request('/health', headers={'X-Forwarded-Host': 'evil.example', 'X-Forwarded-Proto': 'https'}), (200, {'status': 'ok'}))
            room = {'name': 'Public team', 'owner_name': 'Owner'}
            self.assertEqual(request('/api/rooms', room)[0], 401)
            self.assertEqual(request('/api/rooms', room, {'X-Coopagents-Bootstrap': 'wrong'})[0], 401)
            self.assertEqual(request('/api/rooms', room, {'X-Coopagents-Bootstrap': secret, 'Origin': 'https://evil.example'})[0], 403)
            status, owner = request('/api/rooms', room, {'X-Coopagents-Bootstrap': secret, 'Origin': 'https://team.example'})
            self.assertEqual(status, 200)
            rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize',
                   'params': {'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'test', 'version': '1'}}}
            hdr = {'Authorization': 'Bearer ' + owner['agent_token'], 'Accept': 'application/json, text/event-stream', 'Origin': 'https://team.example'}
            status, result = request('/mcp', rpc, hdr)
            self.assertEqual(status, 200, result)
            self.assertEqual(result['result']['serverInfo']['name'], 'Coopagents')
            self.assertEqual(request('/mcp', rpc, {**hdr, 'Origin': 'https://evil.example'})[0], 403)
            self.assertEqual(request('/mcp', rpc, {**hdr, 'Host': 'evil.example'})[0], 400)
            with patch.object(app.state.service.identity.db, 'connect', side_effect=RuntimeError('private database path')):
                self.assertEqual(request('/ready'), (503, {'status': 'unavailable'}))
        finally:
            server.should_exit = True
            thread.join(10)
            sock.close()
