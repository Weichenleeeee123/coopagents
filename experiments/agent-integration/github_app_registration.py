"""Human-approved GitHub App manifest registration with private local storage.

Official flow: https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest
No App is created until the user submits the form and confirms it on GitHub.
"""
import argparse
import csv
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import threading
import time
from urllib.parse import parse_qs, quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4

REPOSITORY = 'Weichenleeeee123/coopagents-1-0-acceptance-20261031'
EVENTS = ['push', 'pull_request', 'check_run', 'check_suite', 'status', 'release']
MAX_RESPONSE = 512 * 1024


from coopagents.github_binding_page import binding_page


def manifest(public_origin, redirect_url, name):
    parsed = urlsplit(public_origin)
    if (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
            or parsed.path not in ('', '/') or parsed.query or parsed.fragment
            or any(char.isspace() for char in public_origin)):
        raise ValueError('Public origin must be an HTTPS origin without credentials or a path')
    # Accessing port also rejects invalid port syntax before generating the form.
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError('Invalid public origin port')
    origin = public_origin.rstrip('/')
    if not isinstance(name, str) or not 1 <= len(name) <= 34:
        raise ValueError('App name must contain 1 to 34 characters')
    return {'name': name, 'url': origin, 'description': 'Private Coopagents 1.0 acceptance App',
            'public': False, 'redirect_url': redirect_url,
            'callback_urls': [origin + '/api/git/github/callback'],
            'hook_attributes': {'url': origin + '/api/git/github/webhook', 'active': True},
            'default_permissions': dict.fromkeys(('contents', 'pull_requests', 'checks', 'statuses', 'metadata'), 'read'),
            'default_events': list(EVENTS)}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def exchange_manifest_code(code):
    if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,512}', code):
        raise ValueError('Invalid manifest code')
    request = Request('https://api.github.com/app-manifests/' + quote(code, safe='') + '/conversions',
                      method='POST', data=b'', headers={
                          'Accept': 'application/vnd.github+json',
                          'X-GitHub-Api-Version': '2022-11-28',
                          'User-Agent': 'coopagents-private-app-registration'})
    with build_opener(NoRedirect()).open(request, timeout=20) as response:
        if response.status != 201:
            raise ValueError('GitHub manifest conversion did not succeed')
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('GitHub manifest response exceeded size limit')
        data = json.loads(raw)
    keys = ('id', 'slug', 'client_id', 'client_secret', 'pem', 'webhook_secret')
    if (not isinstance(data, dict) or type(data.get('id')) is not int or data['id'] <= 0
            or any(not isinstance(data.get(key), str) or not data[key] for key in keys[1:])
            or not re.fullmatch(r'[A-Za-z0-9_-]+', data['slug'])):
        raise ValueError('GitHub manifest response is incomplete')
    return {key: data[key] for key in keys}


def protect_directory(folder):
    folder = Path(folder)
    if folder.is_symlink():
        raise ValueError('Private output must not be a symbolic link')
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if os.name == 'nt':
        identity = subprocess.run(['whoami', '/user', '/fo', 'csv', '/nh'],
                                  capture_output=True, text=True, timeout=10, check=True)
        sid = next(csv.reader(identity.stdout.strip().splitlines()))[-1]
        if not re.fullmatch(r'S-1-[0-9-]+', sid):
            raise ValueError('Unable to establish private output owner')
        result = subprocess.run(['icacls', str(folder), '/inheritance:r', '/grant:r',
                                 '*' + sid + ':(OI)(CI)F'], capture_output=True, timeout=10)
        if result.returncode:
            raise ValueError('Unable to restrict private output permissions')
    else:
        folder.chmod(0o700)


def save_private(folder, data):
    target = Path(folder) / 'github-app-private.json'
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as output:
        json.dump(data, output, indent=2)
        output.write('\n')
        output.flush()
        os.fsync(output.fileno())
    return target


def registration_server(public_origin, folder, *, name='Coopagents private acceptance',
                        exchange=exchange_manifest_code, preview=None, preview_slug=None):
    if preview not in (None, 'ready', 'registered', 'error', 'verified'):
        raise ValueError('Invalid preview state')
    if preview_slug is not None and not re.fullmatch(r'[A-Za-z0-9_-]+', preview_slug):
        raise ValueError('Invalid preview App slug')
    settings = manifest(public_origin, 'http://127.0.0.1:1/callback', name)
    protect_directory(folder)

    class Handler(BaseHTTPRequestHandler):
        # Deliberately suppress request paths, codes, query strings, and errors.
        def log_message(self, *args):
            pass

        def send_page(self, status, content):
            if not content.startswith('<!doctype html>'):
                content = binding_page('error', app_name=name, message={
                    400: '授权信息不完整或已失效，请重新发起连接。',
                    403: '此页面仅接受本机发起的连接请求。',
                    404: '这个接入页面不存在，请返回发起连接的页面。',
                    409: '此授权已处理，无需重复提交。',
                    502: '暂时无法完成 GitHub 授权，请重新发起连接。'
                }.get(status, '连接未完成，请重新发起授权。'))
            body = content.encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'none'; style-src 'unsafe-inline'; form-action https://github.com; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Connection', 'close')
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            server = self.server
            expected_host = '127.0.0.1:' + str(server.server_port)
            origin = self.headers.get('Origin')
            if (self.headers.get_all('Host') != [expected_host]
                    or origin is not None and origin != 'http://' + expected_host):
                return self.send_page(403, 'Request rejected.')
            if len(self.path) > 4096:
                return self.send_page(400, 'Request rejected.')
            parsed = urlsplit(self.path)
            if preview:
                if parsed.path != '/preview/' + preview or parsed.query:
                    return self.send_page(404, 'Not found.')
                return self.send_page(200, binding_page(preview, app_name=preview_slug or name,
                                      slug=preview_slug or 'synthetic-preview-app', preview=True, repository=REPOSITORY))
            if parsed.path == server.start_path and not parsed.query:
                action = 'https://github.com/settings/apps/new?state=' + server.state
                return self.send_page(200, binding_page('ready', app_name=name, settings=server.manifest, action=action, repository=REPOSITORY))
            if parsed.path != '/callback':
                return self.send_page(404, 'Not found.')
            try:
                query = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=4)
            except ValueError:
                return self.send_page(400, 'Invalid callback.')
            state = query.get('state', [])
            code = query.get('code', [])
            if (len(state) != 1 or not secrets.compare_digest(state[0], server.state)
                    or len(code) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]{1,512}', code[0])):
                return self.send_page(400, 'Invalid callback.')
            with server.consume_lock:
                if server.consumed:
                    return self.send_page(409, 'Callback already used.')
                server.consumed = True
            try:
                data = exchange(code[0])
                target = save_private(folder, data)
                installation_url = 'https://github.com/apps/' + quote(data['slug'], safe='') + '/installations/new'
                print(json.dumps({'status': 'registered', 'app_id': data['id'], 'slug': data['slug'],
                                  'private_file': str(target), 'installation_url': installation_url,
                                  'install_only_repository': REPOSITORY}), flush=True)
                self.send_page(200, binding_page('registered', app_name=data['slug'], slug=data['slug'], repository=REPOSITORY))
                server.succeeded = True
            except Exception:
                # Exceptions may contain the one-time code or secret API response.
                server.failed = True
                self.send_page(502, 'Registration exchange failed. Private details were not displayed. Start a new flow.')

    class BoundedServer(HTTPServer):
        def get_request(self):
            connection, address = super().get_request()
            connection.settimeout(5)
            return connection, address

    server = BoundedServer(('127.0.0.1', 0), Handler)
    server.timeout = 1
    server.state = secrets.token_urlsafe(32)
    server.start_path = '/start/' + secrets.token_urlsafe(24)
    server.consume_lock = threading.Lock()
    server.consumed = server.succeeded = server.failed = False
    settings['redirect_url'] = 'http://127.0.0.1:' + str(server.server_port) + '/callback'
    server.manifest = settings
    return server


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--public-origin')
    parser.add_argument('--name', default='Coopagents private acceptance')
    parser.add_argument('--wait-seconds', type=int, default=900)
    parser.add_argument('--preview', choices=('ready', 'registered', 'error', 'verified'),
                        help='Serve a non-mutating page preview; never exchanges authorization codes')
    parser.add_argument('--preview-slug', help='Public App slug used only for the preview installation link')
    args = parser.parse_args(argv)
    if not 1 <= args.wait_seconds <= 3600:
        parser.error('--wait-seconds must be between 1 and 3600')
    if not args.preview and not args.public_origin:
        parser.error('--public-origin is required for registration')
    if args.preview_slug and not args.preview:
        parser.error('--preview-slug requires --preview')
    root = Path(__file__).resolve().parents[2]
    folder = root / '.local/github-app-registration' / uuid4().hex
    try:
        server = registration_server(args.public_origin or 'https://preview.invalid', folder, name=args.name,
                                     preview=args.preview, preview_slug=args.preview_slug)
    except Exception:
        print('Unable to prepare secure registration. Check public origin and private directory permissions.')
        return 1
    try:
        print(json.dumps({'status': 'preview' if args.preview else 'awaiting_user_approval',
                          'open_url': 'http://127.0.0.1:' + str(server.server_port) + (
                              '/preview/' + args.preview if args.preview else server.start_path),
                          'private_directory': str(folder), 'install_only_repository': REPOSITORY}), flush=True)
        deadline = time.monotonic() + args.wait_seconds
        while time.monotonic() < deadline and not server.succeeded and not server.failed:
            server.handle_request()
        if not server.succeeded and not args.preview:
            print('Registration was not completed. All local files retained.', flush=True)
            return 1
        return 0
    finally:
        server.server_close()


if __name__ == '__main__':
    raise SystemExit(main())
