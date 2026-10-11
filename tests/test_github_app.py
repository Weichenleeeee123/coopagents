"""REST adapter protocol tests use an offline HTTP transport, not live GitHub."""
import json
import os
import time
import unittest
from unittest.mock import patch
import httpx2 as httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
from crewmesh.github_app import GitHubApp, GitHubError
from crewmesh.errors import AccessDenied, ValidationError


class GitHubAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537,key_size=2048)
        cls.pem = cls.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()).decode()
    def app(self, handler):
        app = GitHubApp('123','Iv1.app-client','secret',self.pem,'webhook-secret','https://crew.example/api/git/github/callback')
        app._client = httpx.Client(transport=httpx.MockTransport(handler),follow_redirects=False)
        return app
    def token_response(self):
        return {'token':'narrow-token','repositories':[{'id':11}],
                'permissions':{'contents':'read','pull_requests':'read','checks':'read','statuses':'read','metadata':'read'}}
    def pr_summary(self,number=7):
        return {'number':number,'state':'open','merged_at':None,'base':{'repo':{'id':11}},
                'head':{'sha':'b'*40,'ref':'feature','repo':{'id':99}}}
    def test_jwt_is_rs256_and_short_lived(self):
        app = self.app(lambda r: httpx.Response(200,json={}))
        claims = jwt.decode(app.jwt(),self.key.public_key(),algorithms=['RS256'])
        self.assertEqual(claims['iss'],'123')
        self.assertLessEqual(claims['exp']-claims['iat'],600)
    def test_config_disabled_partial_and_https_callback(self):
        with patch.dict(os.environ,{},clear=True): self.assertFalse(GitHubApp.from_env('https://crew.example').enabled)
        with patch.dict(os.environ,{'CREWMESH_GITHUB_APP_ID':'123'},clear=True):
            with self.assertRaises(ValidationError): GitHubApp.from_env('https://crew.example')
        with self.assertRaises(ValidationError): GitHubApp('123','client','secret',self.pem,'secret','http://crew.example/api/git/github/callback')
    def test_fixed_origin_no_redirect_credentials_and_narrow_install_token(self):
        requests=[]
        def handler(request):
            requests.append(request)
            if request.url.path.endswith('/access_tokens'):
                self.assertEqual(json.loads(request.content)['repository_ids'],[11])
                return httpx.Response(201,json=dict(self.token_response(),token='installation-token'))
            return httpx.Response(302,headers={'location':'https://evil.example/steal'})
        app=self.app(handler)
        self.assertEqual(app.installation_token(22,11),'installation-token')
        with self.assertRaises(GitHubError): app.request('GET','/repos/acme/demo','installation-token')
        self.assertEqual(len(requests),2)
        self.assertTrue(all(r.url.host=='api.github.com' for r in requests))
        with self.assertRaises(ValidationError): app.request('GET','https://evil.example','secret')
    def test_oauth_user_scope_proof_paginated_and_this_app(self):
        def handler(r):
            if r.url.host=='github.com':
                self.assertEqual(r.headers['accept'],'application/json')
                self.assertNotIn('authorization',r.headers)
                return httpx.Response(200,json={'access_token':'user-token'})
            path=r.url.path
            if path=='/user/installations': return httpx.Response(200,json={'total_count':1,'installations':[{'id':22}]})
            if path=='/app/installations/22': return httpx.Response(200,json={'id':22,'app_id':123,'suspended_at':None})
            if path=='/user/installations/22/repositories':
                page=int(r.url.params['page'])
                repos=[{'id':i,'full_name':'acme/other'+str(i)} for i in range(1,101)] if page==1 else [{'id':11,'full_name':'acme/demo'}]
                return httpx.Response(200,json={'total_count':101,'repositories':repos})
            raise AssertionError(path)
        app=self.app(handler)
        proof=app.verify_user_repository(app.exchange_code('code'),'github.com/acme/demo')
        self.assertEqual(proof['repository_id'],11)
        app.request=lambda *a,**k: {'id':22,'app_id':999,'suspended_at':None}
        with self.assertRaises(AccessDenied): app.verify_installation(22)
    def test_provider_errors_are_safe_retryable_and_response_bounded(self):
        app=self.app(lambda r:httpx.Response(429,json={'secret':'raw-provider-secret'}))
        with self.assertRaises(GitHubError) as caught: app.request('GET','/app','token')
        self.assertTrue(caught.exception.retryable)
        self.assertNotIn('raw-provider-secret',str(caught.exception))
        app=self.app(lambda r:httpx.Response(200,content=b'x'*2_000_001))
        with self.assertRaises(GitHubError): app.request('GET','/app','token')
        app=self.app(lambda r:httpx.Response(404,json={}))
        with self.assertRaises(AccessDenied): app.verify_installation(22)

    def test_rest_reconciliation_checks_current_head_and_missing_fork_checks(self):
        seen=[]
        def handler(r):
            seen.append(r.url.path)
            path=r.url.path
            if path=='/app/installations/22': return httpx.Response(200,json={'id':22,'app_id':123})
            if path.endswith('/access_tokens'): return httpx.Response(201,json=self.token_response())
            if path=='/repositories/11': return httpx.Response(200,json={'id':11,'full_name':'acme/demo'})
            if path=='/repos/acme/demo/git/ref/heads/feature': return httpx.Response(200,json={'object':{'sha':'a'*40}})
            if path=='/repos/acme/demo/pulls': return httpx.Response(200,json=[self.pr_summary()])
            if path=='/repos/acme/demo/pulls/7': return httpx.Response(200,json={
                'number':7,'state':'open','merged':False,'html_url':'https://evil.example/secret',
                'base':{'repo':{'id':11}},'head':{'sha':'b'*40,'ref':'feature','repo':{'id':99}}})
            if path.endswith('/check-runs') or path.endswith('/statuses'): return httpx.Response(404,json={})
            raise AssertionError(path)
        app=self.app(handler)
        state=app.repository_state(22,11,'acme/demo',branches=['feature'],pr_numbers=[7])
        self.assertEqual(state['branches']['feature'],'a'*40)
        self.assertEqual(state['pull_requests'][0]['head_repository_id'],99)
        self.assertEqual(state['pull_requests'][0]['checks'],[])
        self.assertNotIn('evil.example',str(state))
        self.assertIn('/repos/acme/demo/commits/'+'b'*40+'/check-runs',seen)

    def reconciliation_handler(self,r):
        path=r.url.path
        if path=='/app/installations/22': return httpx.Response(200,json={'id':22,'app_id':123})
        if path.endswith('/access_tokens'): return httpx.Response(201,json=self.token_response())
        if path=='/repositories/11': return httpx.Response(200,json={'id':11,'full_name':'acme/demo'})
        if path=='/repos/acme/demo/pulls': return httpx.Response(200,json=[])
        if path=='/repos/acme/demo/pulls/999': return httpx.Response(404,json={})
        if path=='/repos/acme/demo/git/ref/heads/feature': return httpx.Response(200,json={'object':{'sha':'a'*40}})
        if path=='/repos/acme/demo/commits/'+'a'*40: return httpx.Response(200,json={'sha':'a'*40})
        if path.endswith('/check-runs'): return httpx.Response(200,json={'check_runs':[{'head_sha':'a'*40,'status':'completed','conclusion':'success'}]})
        if path.endswith('/statuses'): return httpx.Response(200,json=[{'state':'success','context':'ci'}])
        raise AssertionError(path)

    def test_missing_pr_is_unavailable_without_revoking_valid_repository(self):
        app=self.app(self.reconciliation_handler)
        state=app.repository_state(22,11,'acme/demo',branches=['feature'],pr_numbers=[999])
        self.assertEqual(state['branches']['feature'],'a'*40)
        self.assertEqual(state['unavailable_pr_numbers'],[999])

    def test_branch_and_explicit_commit_fetch_checks_at_exact_sha(self):
        app=self.app(self.reconciliation_handler)
        state=app.repository_state(22,11,'acme/demo',branches=['feature'],commit_shas=['a'*40])
        self.assertEqual(state['commits']['a'*40]['checks'][0]['head_sha'],'a'*40)
        self.assertEqual(state['commits']['a'*40]['statuses'][0]['head_sha'],'a'*40)

    def test_pr_detail_number_must_match_requested_number(self):
        def handler(r):
            if r.url.path=='/repos/acme/demo/pulls': return httpx.Response(200,json=[self.pr_summary()])
            if r.url.path=='/repos/acme/demo/pulls/7': return httpx.Response(200,json={
                'number':99,'state':'open','merged':False,'base':{'repo':{'id':11}},
                'head':{'sha':'a'*40,'ref':'feature','repo':{'id':11}}})
            return self.reconciliation_handler(r)
        with self.assertRaises(GitHubError): self.app(handler).repository_state(22,11,'acme/demo',pr_numbers=[7])

    def test_installation_token_unexpected_repositories_or_write_permissions_denied(self):
        for changes in [{'repositories':[{'id':11},{'id':99}]},{'permissions':{'contents':'write'}}, {'repositories':[]}]:
            app=self.app(lambda r:httpx.Response(201,json=dict(self.token_response(),**changes)))
            with self.subTest(changes=changes),self.assertRaises(GitHubError): app.installation_token(22,11)

    def test_missing_commit_and_branch_preserve_other_objects(self):
        def handler(r):
            if r.url.path in ['/repos/acme/demo/commits/'+'c'*40,'/repos/acme/demo/git/ref/heads/deleted']:
                return httpx.Response(404,json={})
            return self.reconciliation_handler(r)
        state=self.app(handler).repository_state(22,11,'acme/demo',branches=['feature','deleted'],commit_shas=['c'*40])
        self.assertEqual(state['branches'],{'feature':'a'*40})
        self.assertEqual(state['unavailable_commit_shas'],['c'*40])
        self.assertEqual(state['commits']['a'*40]['checks'][0]['conclusion'],'success')

    def test_malformed_provider_pr_is_terminal_safe_error(self):
        def handler(r):
            if r.url.path=='/repos/acme/demo/pulls': return httpx.Response(200,json=[self.pr_summary()])
            if r.url.path=='/repos/acme/demo/pulls/7': return httpx.Response(200,json=[])
            return self.reconciliation_handler(r)
        with self.assertRaises(GitHubError) as caught: self.app(handler).repository_state(22,11,'acme/demo',pr_numbers=[7])
        self.assertFalse(caught.exception.retryable)

    def test_secondary_limit_body_without_headers_is_retryable(self):
        app=self.app(lambda r:httpx.Response(403,json={'message':'You have exceeded a secondary rate limit. secret-provider-details'}))
        with self.assertRaises(GitHubError) as caught: app.request('GET','/app','token')
        self.assertTrue(caught.exception.retryable)
        self.assertTrue(caught.exception.rate_limited)
        self.assertGreaterEqual(caught.exception.retry_after,60)
        self.assertNotIn('secret-provider-details',str(caught.exception))

    def test_rate_limit_delay_uses_retry_after_reset_and_bounds(self):
        for headers,minimum,maximum in [({'retry-after':'120'},120,120),
                ({'x-ratelimit-remaining':'0','x-ratelimit-reset':str(int(time.time())+300)},298,301),
                ({'retry-after':'999999999999'},86400,86400),({'retry-after':'-2'},60,60)]:
            app=self.app(lambda r:httpx.Response(403,headers=headers,json={'message':'secondary rate limit'}))
            with self.subTest(headers=headers),self.assertRaises(GitHubError) as caught: app.request('GET','/app','token')
            self.assertGreaterEqual(caught.exception.retry_after,minimum)
            self.assertLessEqual(caught.exception.retry_after,maximum)
        app=self.app(lambda r:httpx.Response(403,json={'message':'Resource not accessible by integration'}))
        with self.assertRaises(AccessDenied): app.request('GET','/app','token')

    def test_recent_open_discovery_does_not_fetch_historical_details_or_checks(self):
        seen=[]
        def handler(r):
            seen.append(r.url.path)
            if r.url.path=='/repos/acme/demo/pulls':
                self.assertEqual(r.url.params['state'],'open')
                self.assertEqual(r.url.params['per_page'],'50')
                self.assertEqual(r.url.params['page'],'1')
                return httpx.Response(200,json=[self.pr_summary(i) for i in range(1,51)])
            return self.reconciliation_handler(r)
        state=self.app(handler).repository_state(22,11,'acme/demo')
        self.assertEqual(len(state['pull_requests']),50)
        self.assertTrue(state['discovery']['truncated'])
        self.assertFalse(any('/pulls/' in path or '/check-runs' in path for path in seen))
        self.assertLessEqual(len(seen),5)

    def test_explicit_closed_pr_is_fetched_outside_open_discovery(self):
        def handler(r):
            if r.url.path=='/repos/acme/demo/pulls/7': return httpx.Response(200,json=dict(self.pr_summary(),state='closed',merged=True))
            return self.reconciliation_handler(r)
        state=self.app(handler).repository_state(22,11,'acme/demo',pr_numbers=[7])
        self.assertTrue(state['pull_requests'][0]['merged'])

    def test_current_checks_are_bounded_and_truncation_is_reported(self):
        def handler(r):
            if r.url.path.endswith('/check-runs'):
                self.assertEqual(r.url.params['page'],'1')
                return httpx.Response(200,json={'total_count':150,'check_runs':[{'head_sha':'a'*40,'name':str(i),'status':'completed','conclusion':'success'} for i in range(100)]})
            if r.url.path.endswith('/statuses'):
                self.assertEqual(r.url.params['page'],'1')
                return httpx.Response(200,json=[{'state':'success','context':str(i)} for i in range(100)])
            return self.reconciliation_handler(r)
        state=self.app(handler).repository_state(22,11,'acme/demo',branches=['feature'])
        commit=state['commits']['a'*40]
        self.assertEqual(len(commit['checks']),100)
        self.assertTrue(commit['checks_truncated'])
        self.assertTrue(commit['statuses_truncated'])

    def test_reconciliation_request_count_and_deadline_are_bounded(self):
        app=self.app(self.reconciliation_handler)
        app.MAX_OPERATION_REQUESTS=2
        with self.assertRaises(GitHubError): app.repository_state(22,11,'acme/demo')
        app=self.app(self.reconciliation_handler)
        app.OPERATION_SECONDS=0
        with self.assertRaises(GitHubError): app.repository_state(22,11,'acme/demo')

    def test_only_current_base_branch_candidates_fetch_detail(self):
        seen=[]
        summary=dict(self.pr_summary(),head={'sha':'a'*40,'ref':'feature','repo':{'id':11}})
        def handler(r):
            seen.append(r.url.path)
            if r.url.path=='/repos/acme/demo/pulls': return httpx.Response(200,json=[summary])
            if r.url.path=='/repos/acme/demo/pulls/7': return httpx.Response(200,json=dict(summary,merged=False))
            return self.reconciliation_handler(r)
        state=self.app(handler).repository_state(22,11,'acme/demo',branches=['feature'])
        self.assertTrue(state['pull_requests'][0]['checks_verified'])
        self.assertIn('/repos/acme/demo/pulls/7',seen)

    def test_operation_deadline_is_checked_during_streamed_response(self):
        seen=[]
        class SlowChunk(httpx.SyncByteStream):
            def __iter__(self):
                seen.append('streamed')
                time.sleep(0.1)
                yield b'{}'
        app=self.app(lambda r:httpx.Response(200,stream=SlowChunk()))
        app.jwt=lambda:'offline-jwt'
        app.OPERATION_SECONDS=0.05
        with self.assertRaises(GitHubError) as caught: app.repository_state(22,11,'acme/demo')
        self.assertTrue(caught.exception.retryable)
        self.assertEqual(seen,['streamed'])
