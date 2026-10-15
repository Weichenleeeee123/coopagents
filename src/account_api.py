"""Cookie authenticated account HTTP routes. Domain stores own authorization."""
import threading
import hashlib
import hmac
import json
import time
import unicodedata
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse
from starlette.routing import Route
from .errors import AccessDenied, ValidationError

COOKIE = 'coopagents_account'
THROTTLE_LIMIT = 10000

class AccountBusy(Exception):
    pass


def cookie_token(request, name=COOKIE, required=True):
    values = []
    for header in request.headers.getlist('cookie'):
        for part in header.split(';'):
            key, sep, value = part.strip().partition('=')
            if key == name and sep:
                values.append(value)
    if len(values) > 1 or (required and len(values) != 1) or any(not 1 <= len(value) <= 128 for value in values):
        raise AccessDenied('Account cookie not accepted')
    return values[0] if values else None


def session_response(info, secure):
    token = info['session_token']
    response = JSONResponse({key: value for key, value in info.items() if key != 'session_token'})
    response.set_cookie(COOKIE, token, max_age=604800, httponly=True, secure=secure, samesite='lax', path='/')
    return response


class LoginThrottle:
    """Persist short windows, without permanent account lockout or global lockout."""
    def __init__(self, db):
        self.db = db
        with db.connect(write=True) as c:
            c.execute('CREATE TABLE IF NOT EXISTS account_login_throttle(key TEXT PRIMARY KEY,window REAL NOT NULL,attempts INTEGER NOT NULL)')

    def attempt(self, username, address):
        now = time.time()
        username = unicodedata.normalize('NFKC', username).strip().casefold()
        keys = [(hashlib.sha256(('user:' + username).encode()).hexdigest(), 20),
                (hashlib.sha256(('ip:' + address).encode()).hexdigest(), 60)]
        with self.db.connect(write=True) as c:
            for key, limit in keys:
                row = c.execute('SELECT window,attempts FROM account_login_throttle WHERE key=?', (key,)).fetchone()
                start, count = (row['window'], row['attempts']) if row and now - row['window'] < 60 else (now, 0)
                if count >= limit:
                    raise AccessDenied('Login temporarily unavailable; try again later')
                if row is None and c.execute('SELECT count(*) FROM account_login_throttle').fetchone()[0] >= THROTTLE_LIMIT:
                    expired = c.execute('SELECT key FROM account_login_throttle WHERE window<=? ORDER BY window LIMIT 1', (now - 60,)).fetchone()
                    if expired is None:
                        raise AccessDenied('Login temporarily unavailable; try again later')
                    c.execute('UPDATE account_login_throttle SET key=?,window=?,attempts=0 WHERE key=?', (key, now, expired['key']))
                c.execute('INSERT INTO account_login_throttle VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET window=excluded.window,attempts=excluded.attempts', (key, start, count + 1))


def account_routes(service, *, mode, origin, bootstrap_secret, oauth):
    from .api import error_payload, validate, fields
    accounts, workspaces = service.accounts, service.workspaces
    expensive = threading.BoundedSemaphore(2)
    throttle = LoginThrottle(accounts.db)
    service.login_throttle = throttle
    secure = bool(origin and origin.startswith('https://'))
    bootstrap_hash = hashlib.sha256(bootstrap_secret.encode()).digest() if bootstrap_secret else None

    def schema(required='', optional=None):
        return fields(required, optional)

    operations = {
        '/account/teams': (workspaces.create_team, schema('name')),
        '/account/password': (accounts.change_password, schema('current_password new_password')),
        '/account/logout': (accounts.logout, schema()),
        '/account/teams/{team_id}/projects': (workspaces.create_project, schema('name', {'repository': ''})),
        '/account/teams/{team_id}/claim': (workspaces.claim_legacy_project, schema('owner_web_token')),
        '/account/teams/{team_id}/invites': (workspaces.create_invite, {**schema('', {'role': 'member'}), 'project_ids': (list, False, [])}),
        '/account/teams/{team_id}/members/{account_id}/role': (workspaces.change_role, schema('role')),
        '/account/teams/{team_id}/members/{account_id}/remove': (workspaces.remove_member, schema()),
        '/account/teams/{team_id}/members/{account_id}/reset-password': (workspaces.reset_password, schema('new_password')),
        '/account/projects/{room_id}/select': (workspaces.project_credential, schema()),
        '/account/projects/{room_id}/members/{account_id}/grant': (workspaces.grant_project, schema()),
        '/account/projects/{room_id}/members/{account_id}/remove': (workspaces.remove_project_member, schema()),
    }
    reads = {
        '/account/session': accounts.session_info,
        '/account/teams': workspaces.list_teams,
        '/account/teams/{team_id}/projects': workspaces.list_projects,
        '/account/teams/{team_id}/managed-projects': workspaces.list_managed_projects,
        '/account/teams/{team_id}/members': workspaces.list_members,
    }

    async def execute(method, *args, **kwargs):
        # Bounds password work as well as database work outside the event loop.
        if not expensive.acquire(blocking=False):
            raise AccountBusy()
        try:
            return await run_in_threadpool(method, *args, **kwargs)
        finally:
            expensive.release()

    async def handle(request):
        try:
            path = request.url.path
            expected_origin = origin or str(request.base_url).rstrip('/')
            if request.method == 'POST':
                if request.headers.getlist('origin') != [expected_origin]:
                    return JSONResponse({'error': 'AccessDenied', 'message': 'Origin not accepted'}, status_code=403)
            token = cookie_token(request, required=False)
            if path == '/account/config':
                return JSONResponse({'mode': mode, 'local_login_enabled': mode == 'self-hosted',
                    'bootstrap_enabled': mode == 'self-hosted' and bootstrap_hash is not None and await execute(accounts.local_setup_available),
                    'github_oauth_enabled': oauth is not None})
            if request.method == 'GET':
                if not token:
                    raise AccessDenied('Account cookie required')
                try:
                    result = await execute(reads[request.scope['account_pattern']], token, **request.path_params)
                except AccessDenied:
                    if path != '/account/session':
                        raise
                    response = JSONResponse({'error': 'AccessDenied', 'message': 'Account session not accepted'}, status_code=401)
                    response.delete_cookie(COOKIE, httponly=True, secure=secure, samesite='lax', path='/')
                    return response
                return JSONResponse(result)
            if mode == 'cloud' and (path in ('/account/login', '/account/bootstrap', '/account/password') or path.endswith('/reset-password')):
                raise AccessDenied('Local account authentication disabled')
            if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/json':
                raise ValidationError('Content type must be application/json')
            try:
                data = json.loads(await request.body())
            except (ValueError, UnicodeError):
                raise ValidationError('Malformed JSON') from None
            if path == '/account/logout':
                validate(data, schema())
                try:
                    if not token:
                        raise AccessDenied('Account session not accepted')
                    await execute(accounts.authenticate, token)
                except AccessDenied:
                    response = JSONResponse({'ok': True})
                    response.delete_cookie(COOKIE, httponly=True, secure=secure, samesite='lax', path='/')
                    return response
            if path == '/account/invites/preview':
                data = validate(data, schema('invite_token'))
                return JSONResponse(await execute(workspaces.preview_invite, **data), headers={'Cache-Control': 'no-store'})
            if token and path not in ('/account/login', '/account/bootstrap'):
                csrf = request.headers.getlist('x-coopagents-csrf')
                if len(csrf) != 1:
                    raise AccessDenied('CSRF credential required')
                await execute(accounts.authenticate, token, csrf[0])
            if path == '/account/bootstrap':
                if bootstrap_hash is None or len(request.headers.getlist('x-coopagents-bootstrap')) != 1 or not hmac.compare_digest(hashlib.sha256(request.headers['x-coopagents-bootstrap'].encode()).digest(), bootstrap_hash):
                    raise AccessDenied('Bootstrap credential not accepted')
                data = validate(data, schema('username password', {'display_name': None}))
                account = await execute(accounts.bootstrap, **data)
                return session_response(await execute(accounts.create_session, account['id']), secure)
            if path == '/account/login':
                data = validate(data, schema('username password'))
                await execute(throttle.attempt, data['username'], request.client.host if request.client else '')
                return session_response(await execute(accounts.login, **data), secure)
            if path == '/account/invites/accept':
                if token:
                    data = validate(data, schema('invite_token'))
                    return JSONResponse(await execute(workspaces.accept_invite, session_token=token, **data))
                if mode == 'cloud':
                    raise AccessDenied('GitHub account session required')
                data = validate(data, schema('invite_token username password', {'display_name': None}))
                await execute(throttle.attempt, data['username'], request.client.host if request.client else '')
                result = await execute(workspaces.accept_invite, **data)
                info = await execute(accounts.create_session, result['account']['id'])
                return session_response({**result, **info}, secure)
            if not token:
                raise AccessDenied('Account cookie required')
            method, body_schema = operations[request.scope['account_pattern']]
            data = validate(data, body_schema)
            if 'project_ids' in data:
                project_ids = data['project_ids']
                if len(project_ids) > 200 or any(type(value) is not str or not value.strip() or len(value) > 120 for value in project_ids):
                    raise ValidationError('Project IDs must contain at most 200 nonempty strings of at most 120 characters')
                try:
                    for value in project_ids:
                        value.encode('utf-8')
                except UnicodeEncodeError:
                    raise ValidationError('Project IDs must contain valid Unicode') from None
            result = await execute(method, token, **request.path_params, **data)
            response = JSONResponse(result if result is not None else {'ok': True})
            if path in ('/account/logout', '/account/password'):
                response.delete_cookie(COOKIE, httponly=True, secure=secure, samesite='lax', path='/')
            return response
        except AccountBusy:
            return JSONResponse({'error': 'Busy', 'message': 'Service busy; try again later'}, status_code=503)
        except Exception as error:
            payload, status = error_payload(error)
            return JSONResponse(payload, status_code=status)

    result = []
    patterns = set(operations) | set(reads) | {'/account/config', '/account/bootstrap', '/account/login', '/account/invites/accept', '/account/invites/preview'}
    for pattern in sorted(patterns):
        async def endpoint(request, pattern=pattern):
            request.scope['account_pattern'] = pattern
            return await handle(request)
        methods = (['GET'] if pattern in reads or pattern == '/account/config' else []) + (['POST'] if pattern in operations or pattern in ('/account/bootstrap', '/account/login', '/account/invites/accept', '/account/invites/preview') else [])
        result.append(Route(pattern, endpoint, methods=methods))
    if oauth:
        result.extend(oauth.routes(service, execute, secure))
    return result
