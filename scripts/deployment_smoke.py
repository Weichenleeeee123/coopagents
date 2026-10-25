"""Real Docker/Caddy TLS acceptance. Retains containers, volumes and evidence.

Run from repository root: python scripts/deployment_smoke.py --image coopagents:0.7.0
Requires Docker Engine and the pinned Caddy image. No external DNS or CA needed.
"""
import argparse
import http.client
import json
from pathlib import Path
import secrets
import shutil
import socket
import ssl
import subprocess
import time
from uuid import uuid4

CADDY = 'caddy:2.11.2-alpine@sha256:834468128c7696cec0ceea6172f7d692daf645ae51983ca76e39da54a97c570d'


class LoopbackTLS(http.client.HTTPSConnection):
    def connect(self):
        connection = socket.create_connection(('127.0.0.1', self.port), self.timeout)
        self.sock = self._context.wrap_socket(connection, server_hostname='coopagents.localhost')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='coopagents:0.7.0')
    parser.add_argument('--docker', default=shutil.which('docker'))
    args = parser.parse_args()
    if not args.docker:
        parser.error('Docker executable is required')
    identifier = 'coopagents-p4-' + uuid4().hex[:12]
    evidence = Path('.local/deployment-smoke') / identifier
    evidence.mkdir(parents=True)
    evidence = evidence.resolve()
    app, proxy = identifier + '-app', identifier + '-proxy'
    restored_app = identifier + '-restored-app'
    started = []
    result = {'checks': [], 'image': args.image, 'evidence_id': identifier}

    def docker(*arguments):
        completed = subprocess.run([args.docker, *arguments], capture_output=True, text=True, timeout=180)
        if completed.returncode:
            raise RuntimeError('Docker operation failed: ' + completed.stderr[:1000])
        return completed.stdout.strip()

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        result['checks'].append(name)

    try:
        docker('network', 'create', identifier)
        docker('volume', 'create', identifier + '-data')
        # Private CA used only by this test. Production uses deploy/Caddyfile ACME.
        config = evidence / 'Caddyfile'
        config.write_text('{\n servers {\n strict_sni_host on\n }\n}\ncoopagents.localhost {\n tls internal\n reverse_proxy app:8787\n}\n', encoding='utf-8')
        docker('run', '-d', '--name', proxy, '--network', identifier,
               '-p', '127.0.0.1::443', '--mount', f'type=bind,source={config},target=/etc/caddy/Caddyfile,readonly', CADDY)
        started.append(proxy)
        details = json.loads(docker('inspect', proxy))[0]
        port = int(details['NetworkSettings']['Ports']['443/tcp'][0]['HostPort'])
        proxy_ip = details['NetworkSettings']['Networks'][identifier]['IPAddress']
        origin = f'https://coopagents.localhost:{port}'
        bootstrap = secrets.token_urlsafe(32)
        environment = evidence / 'app.env'
        environment.write_text('\n'.join((
            'COOPAGENTS_MODE=self-hosted', 'COOPAGENTS_HOST=0.0.0.0', 'COOPAGENTS_PUBLIC_URL=' + origin,
            'COOPAGENTS_TRUSTED_PROXIES=' + proxy_ip, 'COOPAGENTS_BOOTSTRAP_SECRET=' + bootstrap)) + '\n', encoding='utf-8')
        docker('run', '-d', '--name', app, '--network', identifier, '--network-alias', 'app',
               '--read-only', '--tmpfs', '/tmp', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--mount', f'type=volume,source={identifier}-data,target=/data', '--env-file', str(environment), args.image)
        started.append(app)
        ca = evidence / 'root.crt'
        deadline = time.monotonic() + 45
        while True:
            try:
                docker('cp', proxy + ':/data/caddy/pki/authorities/local/root.crt', str(ca))
                break
            except RuntimeError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        context = ssl.create_default_context(cafile=str(ca))

        def request(path, data=None, token=None, headers=None, include_headers=False, raw_response=False):
            connection = LoopbackTLS('coopagents.localhost', port, timeout=10, context=context)
            merged = {'Host': f'coopagents.localhost:{port}', **(headers or {})}
            if token:
                merged['Authorization'] = 'Bearer ' + token
            body = json.dumps(data).encode() if data is not None else None
            if body is not None:
                merged['Content-Type'] = 'application/json'
            try:
                connection.request('POST' if body is not None else 'GET', path, body, merged)
                response = connection.getresponse()
                raw = response.read()
                if raw_response:
                    data = raw
                else:
                    try:
                        data = json.loads(raw) if raw else None
                    except ValueError:
                        data = raw.decode('utf-8', errors='replace')
                return (response.status, data, dict(response.getheaders())) if include_headers else (response.status, data)
            finally:
                connection.close()

        while True:
            try:
                if request('/ready')[0] == 200:
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('TLS service not ready')
            time.sleep(1)
        check('verified TLS certificate and DB readiness through Caddy', request('/ready') == (200, {'status': 'ready'}))
        check('container runs as UID 10001', docker('exec', app, 'id', '-u') == '10001')
        check('backend has no published port', not json.loads(docker('inspect', app))[0]['NetworkSettings']['Ports'].get('8787/tcp'))
        check('wrong Host rejected', request('/health', headers={'Host': 'evil.example'})[0] != 200)
        check('cross-site Origin rejected', request('/health', headers={'Origin': 'https://evil.example'})[0] == 403)
        status, account, response_headers = request('/account/bootstrap',
            {'username': 'tls-owner', 'password': secrets.token_urlsafe(24)},
            headers={'X-Coopagents-Bootstrap': bootstrap, 'Origin': origin}, include_headers=True)
        check('HTTPS local account bootstrap', status == 200)
        cookie = response_headers.get('set-cookie', response_headers.get('Set-Cookie', ''))
        check('account cookie is Secure HttpOnly SameSite=Lax', all(flag.lower() in cookie.lower() for flag in ('Secure', 'HttpOnly', 'SameSite=Lax')))
        account_headers = {'Origin': origin, 'Cookie': cookie.split(';', 1)[0], 'X-Coopagents-CSRF': account['csrf_token']}
        check('account cookie restores session through TLS', request('/account/session', headers=account_headers)[0] == 200)
        check('account write requires CSRF', request('/account/teams', {'name': 'denied'}, headers={'Origin': origin, 'Cookie': account_headers['Cookie']})[0] == 401)
        status, team = request('/account/teams', {'name': 'C1 TLS team'}, headers=account_headers)
        check('CSRF authenticated team creation', status == 200)
        status, project = request('/account/teams/' + team['team_id'] + '/projects', {'name': 'C1 TLS project'}, headers=account_headers)
        check('CSRF authenticated project creation', status == 200)
        status, selected = request('/account/projects/' + project['room_id'] + '/select', {}, headers=account_headers)
        check('authorized account project selection', status == 200)
        status, account_task = request('/api/tasks', {'intent_key': 'account-persist', 'title': 'C1 persistence', 'scope': 'src'}, selected['web_token'], {'Origin': origin})
        check('selected project credential accesses project API', status == 200)
        billing_path = '/account/teams/' + team['team_id'] + '/billing'

        def unlimited_billing():
            status, summary = request(billing_path, headers=account_headers)
            return (status == 200 and summary['mode'] == 'self-hosted'
                    and summary['enabled'] is False and summary['plan'] == 'unlimited'
                    and summary['paid'] is False and summary['status'] == 'disabled'
                    and summary['limits'] == {'members': None, 'projects': None}
                    and summary['usage'] == {'members': 1, 'projects': 1}
                    and summary['over_limit'] == {'members': False, 'projects': False}
                    and summary.get('price') is None and not summary.get('checkout_available', False))

        check('self-hosted billing is disabled unlimited with actual account/project usage', unlimited_billing())
        check('anonymous account billing GET rejected', request(billing_path)[0] == 401)
        check('project web bearer cannot read account billing', request(billing_path, token=selected['web_token'])[0] == 401)
        for operation in ('checkout', 'portal', 'sync'):
            check('self-hosted owner billing ' + operation + ' conflicts with valid cookie and CSRF',
                  request(billing_path + '/' + operation, {}, headers=account_headers)[0] == 409)
        source_root = Path(__file__).resolve().parent.parent
        for asset in ('billing.js', 'git.js'):
            status, body, asset_headers = request('/static/' + asset, include_headers=True, raw_response=True)
            asset_headers = {key.lower(): value for key, value in asset_headers.items()}
            check(asset + ' packaged bytes served over verified TLS',
                  status == 200 and body == (source_root / 'src/static' / asset).read_bytes())
            check(asset + ' JavaScript MIME and nosniff',
                  asset_headers.get('content-type', '').split(';')[0] == 'text/javascript'
                  and asset_headers.get('x-content-type-options') == 'nosniff')
            policy = asset_headers.get('content-security-policy', '')
            check(asset + ' same-origin script and frame security policy',
                  "script-src 'self'" in policy and "frame-ancestors 'none'" in policy
                  and 'unsafe-inline' not in policy)
        room = {'name': 'P4 deployment test', 'owner_name': 'Owner'}
        check('public anonymous room creation rejected', request('/api/rooms', room)[0] == 401)
        status, owner = request('/api/rooms', room, headers={'X-Coopagents-Bootstrap': bootstrap, 'Origin': origin})
        check('HTTPS bootstrap room creation', status == 200)
        check('project agent bearer cannot read account billing', request(billing_path, token=owner['agent_token'])[0] == 401)
        # Unmounted paths first pass the catch-all MCP authentication boundary.
        check('self-hosted Stripe webhook is not mounted',
              request('/billing/stripe/webhook', {})[0] == 401
              and request('/billing/stripe/webhook', {}, token=owner['agent_token'])[0] == 404)
        status, task = request('/api/tasks', {'intent_key': 'container-persist', 'title': 'Persistence', 'scope': 'src'}, owner['web_token'], {'Origin': origin})
        check('HTTPS authenticated task creation', status == 200)
        rpc = {'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-11-25', 'capabilities': {}, 'clientInfo': {'name': 'P4 TLS smoke', 'version': '1'}}}
        status, initialized = request('/mcp', rpc, owner['agent_token'], {'Origin': origin, 'Accept': 'application/json, text/event-stream'})
        check('authenticated MCP initialization over verified TLS', status == 200 and initialized['result']['serverInfo']['name'] == 'Coopagents')
        check('web credential refused by MCP', request('/mcp', rpc, owner['web_token'], {'Accept': 'application/json, text/event-stream'})[0] == 401)
        docker('exec', app, 'python', '-m', 'coopagents.backup', 'backup', '/data/coopagents.sqlite3', '/data/backup.sqlite3')
        docker('exec', app, 'python', '-m', 'coopagents.backup', 'restore', '/data/backup.sqlite3', '/data/restored.sqlite3')
        check('container online backup and restore', True)
        restored_check = "from coopagents.identity import IdentityStore; from coopagents.accounts import AccountStore; from coopagents.workspaces import WorkspaceStore; i=IdentityStore('/data/restored.sqlite3'); a=AccountStore(i); w=WorkspaceStore(a); c=i.db.connect(); db=c.__enter__(); assert db.execute('SELECT count(*) FROM accounts WHERE username=?', ('tls-owner',)).fetchone()[0]==1; assert db.execute('SELECT count(*) FROM teams WHERE name=?', ('C1 TLS team',)).fetchone()[0]==1; assert db.execute('SELECT count(*) FROM tasks WHERE intent_key=?', ('account-persist',)).fetchone()[0]==1; assert db.execute('SELECT count(*) FROM session_project_credentials p JOIN account_sessions s ON s.token_hash=p.session_hash WHERE s.revoked_at IS NULL').fetchone()[0]>=1; c.__exit__(None,None,None)"
        docker('exec', app, 'python', '-c', restored_check)
        check('restored DB retains account workspace task and session project mapping', True)
        docker('restart', app)
        deadline = time.monotonic() + 30
        while True:
            try:
                status, snapshot = request('/api/snapshot', token=owner['web_token'])
                if status == 200:
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Restart did not recover')
            time.sleep(1)
        check('volume preserves task and credential after container restart', snapshot['tasks'][0]['id'] == task['id'])
        check('account session persists after container restart', request('/account/session', headers=account_headers)[0] == 200)
        status, projects = request('/account/teams/' + team['team_id'] + '/projects', headers=account_headers)
        check('account team project persists after restart', status == 200 and projects[0]['room_id'] == project['room_id'])
        status, reselected = request('/account/projects/' + project['room_id'] + '/select', {}, headers=account_headers)
        check('account can reselect authorized project after restart', status == 200)
        status, account_snapshot = request('/api/snapshot', token=reselected['web_token'])
        check('account project task persists after restart', status == 200 and account_snapshot['tasks'][0]['id'] == account_task['id'])
        check('self-hosted unlimited billing and actual usage persist after restart', unlimited_billing())
        # Serve the restored database through the same verified TLS origin/CA.
        # The old app, both databases and every container/volume remain retained.
        docker('stop', app)
        docker('run', '-d', '--name', restored_app, '--network', identifier, '--network-alias', 'restored-app',
               '--read-only', '--tmpfs', '/tmp', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges:true',
               '--mount', f'type=volume,source={identifier}-data,target=/data', '--env-file', str(environment),
               '--env', 'COOPAGENTS_DATABASE=/data/restored.sqlite3', args.image)
        started.append(restored_app)
        restored_config = evidence / 'Caddyfile-restored'
        restored_config.write_text('{\n servers {\n strict_sni_host on\n }\n}\ncoopagents.localhost {\n tls internal\n reverse_proxy restored-app:8787\n}\n', encoding='utf-8')
        docker('cp', str(restored_config), proxy + ':/tmp/Caddyfile-restored')
        docker('exec', proxy, 'caddy', 'reload', '--config', '/tmp/Caddyfile-restored', '--adapter', 'caddyfile')
        deadline = time.monotonic() + 30
        while True:
            try:
                if request('/ready')[0] == 200:
                    break
            except (OSError, ValueError, http.client.HTTPException):
                pass
            if time.monotonic() > deadline:
                raise RuntimeError('Restored TLS service not ready')
            time.sleep(1)
        check('restored account session works through verified TLS', request('/account/session', headers=account_headers)[0] == 200)
        check('new-path backup restore keeps self-hosted billing disabled unlimited and actual usage', unlimited_billing())
        result['status'] = 'passed'
    except Exception as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        for name in reversed(started):
            try:
                (evidence / (name + '.log')).write_text(docker('logs', name), encoding='utf-8')
                docker('stop', name)
            except Exception:
                result['stop_warning'] = True
        with (evidence / 'result.json').open('x', encoding='utf-8') as stream:
            json.dump(result, stream, indent=2)
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
