"""GitHub OAuth with persistent single use browser-bound state and S256 PKCE."""
import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Route
from .config import public_origin
from .errors import AccessDenied

STATE_COOKIE = 'crewmesh_oauth_state'
STATE_LIMIT = 10000

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise AccessDenied('GitHub authentication failed')

class GitHubOAuth:
    @classmethod
    def configured(cls, accounts, mode, origin, client_id, client_secret):
        if client_id is None and client_secret is None:
            return None
        if mode != 'cloud' or not origin or not client_id or not client_secret:
            raise ValueError('GitHub OAuth requires cloud mode, HTTPS origin, client ID and secret')
        if not isinstance(client_id, str) or len(client_id) > 256 or not isinstance(client_secret, str) or len(client_secret) > 4096 or any(c.isspace() for c in client_id):
            raise ValueError('Invalid GitHub OAuth configuration')
        return cls(accounts, public_origin(origin), client_id, client_secret)

    def __init__(self, accounts, origin, client_id, client_secret):
        self.accounts, self.origin = accounts, origin
        self.client_id, self.client_secret = client_id, client_secret
        self.callback = origin + '/account/oauth/github/callback'
        with accounts.db.connect(write=True) as c:
            c.execute('CREATE TABLE IF NOT EXISTS account_oauth_states(state_hash TEXT PRIMARY KEY,browser_hash TEXT NOT NULL,verifier TEXT NOT NULL,created_at REAL NOT NULL,used_at REAL)')

    @staticmethod
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def start(self):
        state, browser, verifier = (secrets.token_urlsafe(32) for _ in range(3))
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        with self.accounts.db.connect(write=True) as c:
            if c.execute('SELECT count(*) FROM account_oauth_states').fetchone()[0] >= STATE_LIMIT:
                reusable = c.execute('SELECT state_hash FROM account_oauth_states WHERE used_at IS NOT NULL OR created_at<=? ORDER BY created_at LIMIT 1', (time.time() - 600,)).fetchone()
                if reusable is None:
                    raise AccessDenied('GitHub authentication temporarily unavailable')
                c.execute('UPDATE account_oauth_states SET state_hash=?,browser_hash=?,verifier=?,created_at=?,used_at=NULL WHERE state_hash=?', (self.digest(state), self.digest(browser), verifier, time.time(), reusable['state_hash']))
            else:
                c.execute('INSERT INTO account_oauth_states VALUES(?,?,?,?,NULL)', (self.digest(state), self.digest(browser), verifier, time.time()))
        query = urlencode({'client_id': self.client_id, 'redirect_uri': self.callback, 'state': state, 'scope': '', 'code_challenge': challenge, 'code_challenge_method': 'S256'})
        return {'url': 'https://github.com/login/oauth/authorize?' + query, 'state': state, 'browser_token': browser}

    def consume(self, state, browser):
        if not isinstance(state, str) or not isinstance(browser, str) or not 1 <= len(state) <= 256 or not 1 <= len(browser) <= 256:
            raise AccessDenied('OAuth state not accepted')
        now = time.time()
        with self.accounts.db.connect(write=True) as c:
            row = c.execute('SELECT * FROM account_oauth_states WHERE state_hash=?', (self.digest(state),)).fetchone()
            if row is None or row['used_at'] is not None or not 0 <= now - row['created_at'] <= 600 or not hmac.compare_digest(row['browser_hash'], self.digest(browser)):
                raise AccessDenied('OAuth state not accepted')
            c.execute('UPDATE account_oauth_states SET used_at=?,verifier=? WHERE state_hash=?', (now, '', self.digest(state)))
            return row['verifier']

    def _json(self, url, *, data=None, token=None):
        headers = {'Accept': 'application/json', 'User-Agent': 'Crewmesh', 'X-GitHub-Api-Version': '2022-11-28'}
        if token:
            headers['Authorization'] = 'Bearer ' + token
        if data is not None:
            data = urlencode(data).encode()
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request = Request(url, data=data, headers=headers)
        with build_opener(NoRedirect()).open(request, timeout=10) as response:
            raw = response.read(65537)
            if response.status != 200 or len(raw) > 65536:
                raise AccessDenied('GitHub authentication failed')
        result = json.loads(raw)
        if not isinstance(result, dict):
            raise AccessDenied('GitHub authentication failed')
        return result

    def exchange(self, code, verifier):
        try:
            result = self._json('https://github.com/login/oauth/access_token', data={'client_id': self.client_id, 'client_secret': self.client_secret, 'code': code, 'redirect_uri': self.callback, 'code_verifier': verifier})
            token = result.get('access_token')
            if not isinstance(token, str) or not token or len(token) > 4096:
                raise AccessDenied('GitHub authentication failed')
            user = self._json('https://api.github.com/user', token=token)
            if type(user.get('id')) is not int or user['id'] <= 0 or not isinstance(user.get('login'), str):
                raise AccessDenied('GitHub authentication failed')
            account = self.accounts.oauth_account('github', str(user['id']), user['login'])
            return self.accounts.create_session(account['id'])
        except Exception:
            raise AccessDenied('GitHub authentication failed') from None

    def routes(self, service, execute, secure):
        from .account_api import AccountBusy, cookie_token, session_response
        async def start(request):
            try:
                origins = request.headers.getlist('origin')
                if (origins and origins != [self.origin]) or request.headers.get('sec-fetch-site') == 'cross-site':
                    return JSONResponse({'error': 'AccessDenied', 'message': 'Origin not accepted'}, status_code=403)
                await execute(service.login_throttle.attempt, 'oauth:' + (request.client.host if request.client else ''), request.client.host if request.client else '')
                info = await execute(self.start)
                response = RedirectResponse(info['url'], status_code=302)
                response.set_cookie(STATE_COOKIE, info['browser_token'], max_age=600, httponly=True, secure=True, samesite='lax', path='/')
                return response
            except AccountBusy:
                return JSONResponse({'error': 'Busy', 'message': 'Service busy; try again later'}, status_code=503)
            except Exception:
                return JSONResponse({'error': 'AccessDenied', 'message': 'GitHub authentication failed'}, status_code=401)

        async def callback(request):
            try:
                query = request.query_params
                if set(query) not in ({'state', 'code'}, {'state', 'error'}) or any(len(query.getlist(k)) != 1 for k in query) or any(not 1 <= len(v) <= 2048 for v in query.values()):
                    raise AccessDenied('OAuth callback not accepted')
                browser = cookie_token(request, STATE_COOKIE)
                verifier = await execute(self.consume, query['state'], browser)
                if 'error' in query:
                    raise AccessDenied('GitHub authentication failed')
                info = await execute(self.exchange, query['code'], verifier)
                response = RedirectResponse('/', status_code=303)
                # Reuse central cookie policy without exposing session JSON.
                response.headers['set-cookie'] = session_response(info, True).headers['set-cookie']
            except AccountBusy:
                response = JSONResponse({'error': 'Busy', 'message': 'Service busy; try again later'}, status_code=503)
            except Exception:
                response = JSONResponse({'error': 'AccessDenied', 'message': 'GitHub authentication failed'}, status_code=401)
            response.delete_cookie(STATE_COOKIE, httponly=True, secure=True, samesite='lax', path='/')
            return response
        return [Route('/account/oauth/github/start', start, methods=['GET']), Route('/account/oauth/github/callback', callback, methods=['GET'])]
