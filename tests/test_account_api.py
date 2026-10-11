import unittest
from functools import partial
from unittest.mock import patch
from crewmesh.api import create_app
from transport_support import LiveService

SECRET = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789'
PASSWORD = 'correct horse battery staple'

class AccountHTTPTests(unittest.TestCase):
    def setUp(self):
        with patch('transport_support.create_app', partial(create_app, bootstrap_secret=SECRET)):
            self.live = LiveService()
        self.addCleanup(self.live.close)
        self.headers = {'Origin': self.live.url}

    def post(self, path, data, headers=None):
        return self.live.request('POST', path, data=data, headers=headers or self.headers)

    def bootstrap(self):
        status, info, headers = self.post('/account/bootstrap', {'username': 'owner', 'password': PASSWORD}, {**self.headers, 'X-Crewmesh-Bootstrap': SECRET})
        self.assertEqual(status, 200, info)
        self.assertNotIn('session_token', info)
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=lax', cookie)
        self.headers.update({'Cookie': cookie.split(';')[0], 'X-Crewmesh-CSRF': info['csrf_token']})
        return info

    def test_origin_cookie_csrf_and_logout(self):
        self.assertEqual(self.live.request('POST', '/account/bootstrap', data={'username': 'owner', 'password': PASSWORD})[0], 403)
        self.assertEqual(self.post('/account/bootstrap', {'username': 'owner', 'password': PASSWORD})[0], 401)
        self.bootstrap()
        self.assertEqual(self.live.request('GET', '/account/session', headers=self.headers)[0], 200)
        self.assertEqual(self.post('/account/teams', {'name': 'Team'}, {'Origin': self.live.url, 'Cookie': self.headers['Cookie']})[0], 401)
        self.assertEqual(self.post('/account/teams', {'name': 'Team', 'account_id': 'forged'})[0], 400)
        self.assertEqual(self.post('/account/teams', {'name': 'Team'}, {**self.headers, 'Cookie': self.headers['Cookie'] + '; ' + self.headers['Cookie']})[0], 401)
        self.assertEqual(self.post('/account/logout', {})[0], 200)
        self.assertEqual(self.live.request('GET', '/account/session', headers=self.headers)[0], 401)

    def test_project_scopes_invitation_removal_and_bearer(self):
        self.bootstrap()
        team = self.post('/account/teams', {'name': 'Team'})[1]['team_id']
        project = self.post(f'/account/teams/{team}/projects', {'name': 'Project'})[1]['room_id']
        token = self.post(f'/account/projects/{project}/select', {})[1]['web_token']
        self.assertEqual(self.live.request('GET', '/api/me', token)[0], 200)
        self.assertEqual(self.live.request('GET', '/account/teams', token)[0], 401)
        invite = self.post(f'/account/teams/{team}/invites', {'project_ids': [project]})[1]['invite_token']
        owner_headers = dict(self.headers)
        status, member, cookies = self.post('/account/invites/accept', {'invite_token': invite, 'username': 'member', 'password': PASSWORD}, {'Origin': self.live.url})
        self.assertEqual(status, 200, member)
        self.headers = {'Origin': self.live.url, 'Cookie': cookies['Set-Cookie'].split(';')[0], 'X-Crewmesh-CSRF': member['csrf_token']}
        member_token = self.post(f'/account/projects/{project}/select', {})[1]['web_token']
        self.headers = owner_headers
        self.assertEqual(self.post(f"/account/teams/{team}/members/{member['account']['id']}/remove", {})[0], 200)
        self.assertEqual(self.live.request('GET', '/api/me', member_token)[0], 401)
        self.assertEqual(self.post('/account/logout', {})[0], 200)
        self.assertEqual(self.live.request('GET', '/api/me', token)[0], 401)

    def test_cloud_disables_local_auth(self):
        with patch('transport_support.create_app', partial(create_app, mode='cloud')):
            live = LiveService()
        self.addCleanup(live.close)
        self.assertFalse(live.request('GET', '/account/config')[1]['local_login_enabled'])
        for path in ('login', 'bootstrap', 'password'):
            self.assertEqual(live.request('POST', '/account/' + path, data={}, headers={'Origin': live.url})[0], 401)
    def test_public_secure_cookie_and_cloud_legacy_disabled(self):
        from starlette.testclient import TestClient
        from pathlib import Path
        from uuid import uuid4
        app = create_app(Path('.local/c1-tests') / (str(uuid4()) + '.sqlite3'), public_url='https://example.com', bootstrap_secret=SECRET)
        with TestClient(app, base_url='https://example.com') as client:
            response = client.post('/account/bootstrap', json={'username': 'owner', 'password': PASSWORD}, headers={'Origin':'https://example.com', 'X-Crewmesh-Bootstrap':SECRET})
            self.assertEqual(response.status_code, 200)
            self.assertIn('Secure', response.headers['set-cookie'])
            self.assertFalse(client.get('/account/config').json()['bootstrap_enabled'])
        app = create_app(Path('.local/c1-tests') / (str(uuid4()) + '.sqlite3'), public_url='https://example.com', mode='cloud')
        with TestClient(app, base_url='https://example.com') as client:
            for path in ('/api/rooms', '/api/join'):
                self.assertEqual(client.post(path, json={}).status_code, 401)

    def test_existing_account_invite_csrf_and_no_password_fields(self):
        self.bootstrap()
        first = self.post('/account/teams', {'name':'First'})[1]['team_id']
        second = self.post('/account/teams', {'name':'Second'})[1]['team_id']
        invite = self.post(f'/account/teams/{first}/invites', {})[1]['invite_token']
        _, member, cookie = self.post('/account/invites/accept', {'invite_token':invite,'username':'member','password':PASSWORD}, {'Origin':self.live.url})
        invite = self.post(f'/account/teams/{second}/invites', {})[1]['invite_token']
        self.headers = {'Origin':self.live.url, 'Cookie':cookie['Set-Cookie'].split(';')[0], 'X-Crewmesh-CSRF':member['csrf_token']}
        self.assertEqual(self.post('/account/invites/accept', {'invite_token':invite, 'username':'forged'})[0],400)
        self.assertEqual(self.post('/account/invites/accept', {'invite_token':invite}, {'Origin':self.live.url,'Cookie':self.headers['Cookie']})[0],401)
        self.assertEqual(self.post('/account/invites/accept', {'invite_token':invite})[0],200)

    def test_persisted_login_rate_window(self):
        self.bootstrap()
        for _ in range(20):
            self.assertEqual(self.post('/account/login', {'username':'owner','password':'incorrect long password'})[0],401)
        status, body, _ = self.post('/account/login', {'username':'owner','password':PASSWORD})
        self.assertEqual(status,401)
        self.assertIn('temporarily',body['message'])
        with self.live.app.state.service.accounts.db.connect(write=True) as connection:
            connection.execute('UPDATE account_login_throttle SET window=0')
        self.assertEqual(self.post('/account/login', {'username':'owner','password':PASSWORD})[0],200)
    def test_throttle_bounded_storage_and_expired_reuse(self):
        from crewmesh.account_api import LoginThrottle
        from crewmesh.errors import AccessDenied
        throttle=LoginThrottle(self.live.app.state.service.accounts.db)
        with patch('crewmesh.account_api.THROTTLE_LIMIT',2):
            throttle.attempt('first','127.0.0.1')
            with self.assertRaises(AccessDenied):
                throttle.attempt('second','127.0.0.1')
            with throttle.db.connect(write=True) as connection:
                connection.execute('UPDATE account_login_throttle SET window=0')
            throttle.attempt('second','127.0.0.1')
        with throttle.db.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_login_throttle').fetchone()[0],2)

    def test_busy_password_work_rejected_without_queue(self):
        from concurrent.futures import ThreadPoolExecutor
        import threading
        from starlette.testclient import TestClient
        from pathlib import Path
        from uuid import uuid4
        app=create_app(Path('.local/c1-tests')/(str(uuid4())+'.sqlite3'))
        entered=threading.Barrier(3)
        release=threading.Event()
        def blocked(**kwargs):
            entered.wait(timeout=5)
            release.wait(timeout=5)
            raise RuntimeError('test release')
        with TestClient(app,base_url='http://127.0.0.1') as client, patch.object(app.state.service.accounts,'login',side_effect=blocked):
            def login():
                return client.post('/account/login',json={'username':'first','password':PASSWORD},headers={'Origin':'http://127.0.0.1'})
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures=[pool.submit(login) for _ in range(2)]
                try:
                    entered.wait(timeout=5)
                    self.assertEqual(login().status_code,503)
                finally:
                    release.set()
                    for future in futures:
                        future.result(timeout=5)
    def test_role_project_reset_and_password_http_routes(self):
        self.bootstrap()
        team=self.post('/account/teams',{'name':'Team'})[1]['team_id']
        project=self.post(f'/account/teams/{team}/projects',{'name':'Project'})[1]['room_id']
        owner_headers=dict(self.headers)
        invite=self.post(f'/account/teams/{team}/invites',{})[1]['invite_token']
        _, member, cookie=self.post('/account/invites/accept',{'invite_token':invite,'username':'member','password':PASSWORD},{'Origin':self.live.url})
        aid=member['account']['id']
        self.assertEqual(self.post(f'/account/teams/{team}/members/{aid}/role',{'role':'admin','account_id':'forged'})[0],400)
        self.assertEqual(self.post(f'/account/teams/{team}/members/{aid}/role',{'role':'admin'})[0],200)
        self.assertEqual(self.post(f'/account/projects/{project}/members/{aid}/grant',{})[0],200)
        member_headers={'Origin':self.live.url,'Cookie':cookie['Set-Cookie'].split(';')[0],'X-Crewmesh-CSRF':member['csrf_token']}
        self.headers=member_headers
        self.assertTrue(self.live.request('GET',f'/account/teams/{team}/managed-projects',headers=self.headers)[1][0]['has_access'])
        token=self.post(f'/account/projects/{project}/select',{})[1]['web_token']
        self.headers=owner_headers
        self.assertEqual(self.post(f'/account/projects/{project}/members/{aid}/remove',{})[0],200)
        self.assertEqual(self.live.request('GET','/api/me',token)[0],401)
        self.assertEqual(self.post(f'/account/teams/{team}/members/{aid}/reset-password',{'new_password':'new correct horse battery'})[0],200)
        self.assertEqual(self.live.request('GET','/account/session',headers=member_headers)[0],401)
        self.assertEqual(self.post('/account/password',{'current_password':PASSWORD,'new_password':'another correct horse battery'})[0],200)
        self.assertEqual(self.live.request('GET','/account/session',headers=owner_headers)[0],401)
    def test_rejected_origin_drains_arriving_body_before_response(self):
        import http.client
        import time
        connection=http.client.HTTPConnection('127.0.0.1',self.live.port,timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest('POST','/account/login')
        connection.putheader('Origin','https://evil.example')
        connection.putheader('Content-Type','application/json')
        connection.putheader('Content-Length','2')
        connection.endheaders()
        connection.send(b'{')
        time.sleep(.03)
        connection.send(b'}')
        response=connection.getresponse()
        self.assertEqual(response.status,403)
        self.assertIn(b'Origin not accepted',response.read())
    def test_boundary_rejection_consumes_pending_chunks(self):
        import asyncio
        from crewmesh.api import LocalBoundary
        received=[]
        sent=[]
        async def upstream(scope,receive,send):
            self.fail('Rejected request reached app')
        async def receive():
            received.append(True)
            return {'type':'http.request','body':b'x','more_body':len(received)==1}
        async def send(message):
            sent.append(message)
        scope={'type':'http','method':'POST','scheme':'http','server':('127.0.0.1',80),'path':'/account/login','headers':[(b'host',b'127.0.0.1'),(b'origin',b'https://evil.example')]}
        asyncio.run(LocalBoundary(upstream)(scope,receive,send))
        self.assertEqual(len(received),2)
        self.assertEqual(sent[0]['status'],403)
    def test_invitation_project_ids_strict_array_schema(self):
        self.bootstrap()
        team=self.post('/account/teams',{'name':'Team'})[1]['team_id']
        for project_ids in ([{}],[[]],[True],[1],[None],[''],['   '],['x'*121],['id']*201):
            with self.subTest(project_ids=project_ids):
                status,body,_=self.post(f'/account/teams/{team}/invites',{'project_ids':project_ids})
                self.assertEqual(status,400,body)
                self.assertEqual(body['error'],'ValidationError')
    def test_revoked_cookie_can_login_again_and_logout_is_idempotent(self):
        info=self.bootstrap()
        old_cookie=self.headers['Cookie']
        account_id=info['account']['id']
        new_password='new correct horse battery'
        accounts=self.live.app.state.service.accounts
        with accounts.db.connect(write=True) as connection:
            accounts._reset_password(connection,account_id,new_password)
        status,body,cookies=self.live.request('GET','/account/session',headers={'Cookie':old_cookie})
        self.assertEqual(status,401,body)
        self.assertIn('Max-Age=0',cookies['Set-Cookie'])
        status,body,cookies=self.post('/account/login',{'username':'owner','password':new_password},{'Origin':self.live.url,'Cookie':old_cookie})
        self.assertEqual(status,200,body)
        self.assertNotEqual(cookies['Set-Cookie'].split(';')[0],old_cookie)
        for cookie in (old_cookie,None):
            headers={'Origin':self.live.url}
            if cookie:
                headers['Cookie']=cookie
            status,body,cookies=self.post('/account/logout',{},headers)
            self.assertEqual(status,200,body)
            self.assertIn('Max-Age=0',cookies['Set-Cookie'])

    def test_initial_bootstrap_ignores_stale_single_cookie(self):
        status,body,_=self.post('/account/bootstrap',{'username':'owner','password':PASSWORD},{'Origin':self.live.url,'X-Crewmesh-Bootstrap':SECRET,'Cookie':'crewmesh_account=stale'})
        self.assertEqual(status,200,body)
    def test_expired_cookie_can_login_but_valid_logout_requires_csrf(self):
        self.bootstrap()
        old_cookie=self.headers['Cookie']
        origin_cookie={'Origin':self.live.url,'Cookie':old_cookie}
        self.assertEqual(self.post('/account/logout',{},origin_cookie)[0],401)
        status,_,cookies=self.live.request('GET','/account/teams/nonexistent/members',headers=self.headers)
        self.assertEqual(status,401)
        self.assertIsNone(cookies['Set-Cookie'])
        with self.live.app.state.service.accounts.db.connect(write=True) as connection:
            connection.execute("UPDATE account_sessions SET expires_at='2020-01-01T00:00:00+00:00'")
        status,body,_=self.post('/account/login',{'username':'owner','password':PASSWORD},origin_cookie)
        self.assertEqual(status,200,body)
        # Invalid sessions stay the existing-account invitation branch until the
        # browser clears the cookie; they cannot create a replacement account.
        self.assertEqual(self.post('/account/invites/accept',{'invite_token':'invalid','username':'other','password':PASSWORD},origin_cookie)[0],401)
