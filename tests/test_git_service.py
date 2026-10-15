"""Integration through the production boundary/lifespan, with an offline provider."""
from pathlib import Path
from uuid import uuid4
import unittest
import threading
from unittest.mock import patch
from starlette.testclient import TestClient
from coopagents.api import create_app
from test_github_sync import FakeProvider


class GitServiceTests(unittest.TestCase):
    def test_worker_receives_shutdown_signal_and_retains_callback(self):
        root=Path('.local/test-evidence')/str(uuid4());root.mkdir(parents=True)
        app=create_app(root/'worker.sqlite3',base_url='http://127.0.0.1',github_app=FakeProvider())
        entered=threading.Event();callbacks=[]
        def pending(*,limit,should_stop):
            self.assertEqual(limit,1)
            self.assertFalse(should_stop())
            callbacks.append(should_stop);entered.set()
            return 0
        with patch.object(app.state.service.github,'process_pending',side_effect=pending):
            with TestClient(app,base_url='http://127.0.0.1'):
                self.assertTrue(entered.wait(5))
        self.assertTrue(callbacks[0]())

    def test_app_callback_snapshot_and_agent_commit_link(self):
        root=Path('.local/test-evidence')/str(uuid4());root.mkdir(parents=True)
        app=create_app(root/'app.sqlite3',base_url='http://127.0.0.1',github_app=FakeProvider())
        service=app.state.service
        owner=service.identity.create_room('Git','Owner')
        service.repositories.bind_repository(owner['web_token'],'github.com/acme/demo')
        task=service.tasks.create_task(owner['web_token'],'git','Delivery','src')
        service.tasks.claim_task(owner['agent_token'],task['id'])
        headers={'Authorization':'Bearer '+owner['web_token']}
        with TestClient(app,base_url='http://127.0.0.1') as client:
            begun=client.post('/api/git/github/authorize',headers=headers,json={})
            self.assertEqual(begun.status_code,200,begun.text)
            state=begun.json()['state']
            callback=client.get('/api/git/github/callback',params={'state':state,'code':'code'})
            self.assertEqual(callback.status_code,200,callback.text)
            self.assertEqual(client.post('/api/git/github/finish',headers=headers,json={'state':state}).status_code,200)
            linked=service.call('link_delivery',owner['agent_token'],{'task_id':task['id'],'commit_sha':'a'*40})
            self.assertEqual(linked['commit_sha'],'a'*40)
            snap=client.get('/api/snapshot',headers=headers).json()
            self.assertEqual(snap['git']['connection']['status'],'active')
            self.assertEqual(client.get('/api/git/binding?secret=no',headers=headers).status_code,400)
            self.assertEqual(client.get('/static/git.js').status_code,200)
            self.assertIn('GitHub',client.get('/static/git.js').text)

    def test_disabled_app_keeps_existing_projects_working(self):
        root=Path('.local/test-evidence')/str(uuid4());root.mkdir(parents=True)
        app=create_app(root/'disabled.sqlite3',base_url='http://127.0.0.1')
        owner=app.state.service.identity.create_room('Old','Owner')
        with TestClient(app,base_url='http://127.0.0.1') as client:
            headers={'Authorization':'Bearer '+owner['web_token']}
            snap=client.get('/api/snapshot',headers=headers)
            self.assertEqual(snap.status_code,200)
            self.assertFalse(snap.json()['git']['github_configured'])
            self.assertIsNone(snap.json()['git']['connection'])
