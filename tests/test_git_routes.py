from pathlib import Path
import unittest
from uuid import uuid4
from starlette.applications import Starlette
from starlette.testclient import TestClient
from coopagents.api import Service
from coopagents.github_sync import GitHubSync
from coopagents.git_routes import git_routes
from test_github_sync import FakeProvider


class GitRoutesTests(unittest.TestCase):
    def setUp(self):
        root=Path('.local/test-evidence')/str(uuid4());root.mkdir(parents=True)
        self.service=Service(root/'routes.sqlite3')
        self.owner=self.service.identity.create_room('Room','Owner')
        self.service.repositories.bind_repository(self.owner['web_token'],'github.com/acme/demo')
        self.sync=GitHubSync(self.service.identity,self.service.repositories,FakeProvider())
        self.client=TestClient(Starlette(routes=git_routes(self.service,self.sync)))
        self.headers={'authorization':'Bearer '+self.owner['web_token']}
    def test_authorization_finish_strict_schema_and_callback_no_tokens(self):
        response=self.client.post('/api/git/github/authorize',headers=self.headers,json={'unexpected':True})
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/git/github/authorize',headers=self.headers,json={})
        self.assertEqual(response.status_code,200)
        state=response.json()['state']
        callback=self.client.get('/api/git/github/callback',params={'state':state,'code':'code'})
        self.assertEqual(callback.status_code,200)
        self.assertNotIn('EPHEMERAL_USER_TOKEN',callback.text)
        finish=self.client.post('/api/git/github/finish',headers=self.headers,json={'state':state})
        self.assertEqual(finish.status_code,200)
    def test_duplicate_signature_headers_and_oversized_body_rejected(self):
        response=self.client.post('/api/git/github/webhook',headers=[('x-hub-signature-256','a'),('x-hub-signature-256','b'),('x-github-delivery','d'),('x-github-event','push')],content=b'{}')
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/git/github/webhook',content=b'x'*65537)
        self.assertEqual(response.status_code,400)
    def test_link_rejects_bool_pr_and_unknown_fields(self):
        response=self.client.post('/api/git/github/link',headers=self.headers,json={'task_id':1,'pr_number':True})
        self.assertEqual(response.status_code,400)
        response=self.client.post('/api/git/github/refresh',headers=self.headers,json={'task_id':1})
        self.assertEqual(response.status_code,400)

    def test_explicit_commit_link_accepts_only_complete_sha(self):
        begun=self.sync.begin_authorization(self.owner['web_token'])
        self.sync.complete_authorization(begun['state'],'code')
        self.sync.finish_authorization(self.owner['web_token'],begun['state'])
        task=self.service.tasks.create_task(self.owner['web_token'],'commit','Commit','src')
        response=self.client.post('/api/git/github/link',headers=self.headers,json={'task_id':task['id'],'commit_sha':'a'*40})
        self.assertEqual(response.status_code,200)
        response=self.client.post('/api/git/github/link',headers=self.headers,json={'task_id':task['id'],'commit_sha':'abc'})
        self.assertEqual(response.status_code,400)
