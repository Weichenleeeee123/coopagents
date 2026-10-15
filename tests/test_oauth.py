import unittest
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch
from coopagents.identity import IdentityStore
from coopagents.accounts import AccountStore
from coopagents.oauth import GitHubOAuth
from coopagents.errors import AccessDenied

class OAuthTests(unittest.TestCase):
    def setUp(self):
        folder = Path('.local/c1-tests')
        folder.mkdir(parents=True, exist_ok=True)
        self.accounts = AccountStore(IdentityStore(folder / (str(uuid4()) + '.sqlite3')))
        self.oauth = GitHubOAuth.configured(self.accounts, 'cloud', 'https://example.com', 'client', 'secret')

    def test_state_browser_binding_one_use_and_pkce(self):
        result = self.oauth.start()
        self.assertIn('code_challenge_method=S256', result['url'])
        self.assertIn('scope=', result['url'])
        with self.assertRaises(AccessDenied):
            self.oauth.consume(result['state'], 'wrong')
        verifier = self.oauth.consume(result['state'], result['browser_token'])
        self.assertGreaterEqual(len(verifier), 43)
        with self.assertRaises(AccessDenied):
            self.oauth.consume(result['state'], result['browser_token'])

    def test_expiry_future_and_persistent_replay(self):
        result = self.oauth.start()
        with patch('coopagents.oauth.time.time', return_value=0):
            with self.assertRaises(AccessDenied):
                self.oauth.consume(result['state'], result['browser_token'])
        other = GitHubOAuth.configured(self.accounts, 'cloud', 'https://example.com', 'client', 'secret')
        other.consume(result['state'], result['browser_token'])
        with self.assertRaises(AccessDenied):
            self.oauth.consume(result['state'], result['browser_token'])

    def test_identity_numeric_id_and_no_name_join(self):
        local = self.accounts.bootstrap('same-name', 'correct horse battery staple')
        with patch.object(self.oauth, '_json', side_effect=[{'access_token': 'provider-secret'}, {'id': 123, 'login': 'same-name'}]):
            info = self.oauth.exchange('code', 'verifier')
        self.assertNotEqual(info['account']['id'], local['id'])
        self.assertNotIn('provider-secret', str(info))
        with patch.object(self.oauth, '_json', side_effect=[{'access_token': 'provider-secret'}, {'id': '123', 'login': 'same-name'}]):
            with self.assertRaises(AccessDenied):
                self.oauth.exchange('code', 'verifier')

    def test_config_fail_closed(self):
        self.assertIsNone(GitHubOAuth.configured(self.accounts, 'cloud', None, None, None))
        for mode, origin, cid, secret in [('cloud',None,'client','secret'), ('cloud','https://example.com','client',None), ('self-hosted','https://example.com','client','secret')]:
            with self.assertRaises(ValueError):
                GitHubOAuth.configured(self.accounts, mode, origin, cid, secret)
    def test_callback_http_redirect_replay_and_failure(self):
        from starlette.testclient import TestClient
        from coopagents.api import create_app
        from urllib.parse import urlsplit, parse_qs
        app = create_app(Path('.local/c1-tests') / (str(uuid4()) + '.sqlite3'), public_url='https://example.com', mode='cloud', github_client_id='client', github_client_secret='secret')
        with TestClient(app, base_url='https://example.com', follow_redirects=False) as client:
            self.assertEqual(client.get('/account/oauth/github/start',headers={'Sec-Fetch-Site':'cross-site'}).status_code,403)
            start = client.get('/account/oauth/github/start',headers={'Sec-Fetch-Site':'same-origin'})
            self.assertEqual(start.status_code,302)
            self.assertIn('Secure',start.headers['set-cookie'])
            state=parse_qs(urlsplit(start.headers['location']).query)['state'][0]
            with patch('coopagents.oauth.GitHubOAuth._json',side_effect=[{'access_token':'provider-secret'},{'id':456,'login':'user'}]):
                response=client.get('/account/oauth/github/callback',params={'state':state,'code':'code'},headers={'Sec-Fetch-Site':'cross-site'})
            self.assertEqual(response.status_code,303)
            self.assertEqual(client.get('/account/session').status_code,200)
            self.assertEqual(client.get('/account/oauth/github/callback',params={'state':state,'code':'code'}).status_code,401)
            start=client.get('/account/oauth/github/start')
            state=parse_qs(urlsplit(start.headers['location']).query)['state'][0]
            with patch('coopagents.oauth.GitHubOAuth._json',side_effect=RuntimeError('provider-secret')):
                response=client.get('/account/oauth/github/callback',params={'state':state,'code':'code'})
            self.assertEqual(response.status_code,401)
            self.assertNotIn('provider-secret',response.text)
            self.assertNotIn('coopagents_oauth_state',client.cookies)
            self.assertEqual(client.get('/account/session?unexpected=1').status_code,400)

    def test_concurrent_state_consume_only_one_wins(self):
        from concurrent.futures import ThreadPoolExecutor
        info=self.oauth.start()
        def consume(_):
            try:
                self.oauth.consume(info['state'],info['browser_token'])
                return True
            except AccessDenied:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(consume,range(4))),1)
    def test_state_storage_capacity_and_reuse(self):
        with patch('coopagents.oauth.STATE_LIMIT',2):
            first=self.oauth.start()
            self.oauth.start()
            with self.assertRaises(AccessDenied):
                self.oauth.start()
            self.oauth.consume(first['state'],first['browser_token'])
            self.oauth.start()
        with self.accounts.db.connect() as connection:
            self.assertEqual(connection.execute('SELECT count(*) FROM account_oauth_states').fetchone()[0],2)

    def test_redirects_are_blocked(self):
        from coopagents.oauth import NoRedirect
        with self.assertRaises(AccessDenied):
            NoRedirect().redirect_request(None,None,302,'redirect',{},'https://evil.example')
    def test_environment_secret_sources_bounded_and_exclusive(self):
        from coopagents.config import github_oauth_from_env
        self.assertEqual(github_oauth_from_env({}),{})
        with self.assertRaises(ValueError):
            github_oauth_from_env({'COOPAGENTS_GITHUB_CLIENT_ID':'client'})
        with self.assertRaises(ValueError):
            github_oauth_from_env({'COOPAGENTS_GITHUB_CLIENT_ID':'client','COOPAGENTS_GITHUB_CLIENT_SECRET':'secret','COOPAGENTS_GITHUB_CLIENT_SECRET_FILE':'ignored'})
        path=Path('.local/c1-tests')/(str(uuid4())+'.secret')
        path.write_text('secret\n',encoding='ascii')
        env={'COOPAGENTS_GITHUB_CLIENT_ID':'client','COOPAGENTS_GITHUB_CLIENT_SECRET_FILE':str(path)}
        self.assertEqual(github_oauth_from_env(env),{'github_client_id':'client','github_client_secret':'secret'})
        path.write_text('x'*4097,encoding='ascii')
        with self.assertRaises(ValueError):
            github_oauth_from_env(env)
    def test_oauth_routes_return_503_when_shared_workers_busy(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from starlette.testclient import TestClient
        from coopagents.api import create_app
        entered=threading.Barrier(3)
        release=threading.Event()
        def blocked(*args,**kwargs):
            entered.wait(timeout=5)
            release.wait(timeout=5)
            return {}
        with patch('coopagents.accounts.AccountStore.session_info',side_effect=blocked):
            app=create_app(Path('.local/c1-tests')/(str(uuid4())+'.sqlite3'),public_url='https://example.com',mode='cloud',github_client_id='client',github_client_secret='secret')
            accounts=app.state.service.accounts
            account=accounts.oauth_account('github','789','busy-test')
            session=accounts.create_session(account['id'])
            provider=GitHubOAuth.configured(accounts,'cloud','https://example.com','client','secret')
            state=provider.start()
            cookies={'Cookie':'coopagents_account='+session['session_token']+'; coopagents_oauth_state='+state['browser_token']}
            with TestClient(app,base_url='https://example.com',follow_redirects=False) as client:
                with ThreadPoolExecutor(max_workers=2) as pool:
                    futures=[pool.submit(client.get,'/account/session',headers=cookies) for _ in range(2)]
                    try:
                        entered.wait(timeout=5)
                        start=client.get('/account/oauth/github/start',headers=cookies)
                        callback=client.get('/account/oauth/github/callback',params={'state':state['state'],'code':'code'},headers=cookies)
                        for response in (start,callback):
                            self.assertEqual(response.status_code,503,response.text)
                            self.assertEqual(response.json(),{'error':'Busy','message':'Service busy; try again later'})
                    finally:
                        release.set()
                        for future in futures:
                            future.result(timeout=5)
