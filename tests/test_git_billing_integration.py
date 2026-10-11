"""The merged application owns both provider workers and preserves both APIs."""
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from uuid import uuid4

from starlette.testclient import TestClient

from crewmesh.api import create_app
from test_billing_api import CONFIG, ORIGIN
from test_billing_service import FixtureTransport
from test_github_sync import FakeProvider


class GitBillingIntegrationTests(unittest.TestCase):
    def test_cloud_routes_and_both_workers_share_lifespan(self):
        root = Path('.local/test-evidence') / str(uuid4())
        root.mkdir(parents=True)
        app = create_app(root / 'combined.sqlite3', mode='cloud', public_url=ORIGIN,
                         github_app=FakeProvider(), billing_config=CONFIG)
        service = app.state.service
        service.billing.client.transport = FixtureTransport()
        account = service.accounts.oauth_account('github', '9001', 'integration-owner')
        session = service.accounts.create_session(account['id'])
        token = session['session_token']
        team = service.workspaces.create_team(token, 'Combined')['team_id']
        project = service.workspaces.create_project(token, team, 'Git')['room_id']
        credential = service.workspaces.project_credential(token, project)
        service.repositories.bind_repository(credential['web_token'], 'github.com/acme/demo')
        git_entered, billing_entered = threading.Event(), threading.Event()
        callbacks = []

        def git_pass(*, limit, should_stop):
            callbacks.append(should_stop)
            git_entered.set()
            return 0

        def billing_pass():
            billing_entered.set()
            return False

        with patch.object(service.github, 'process_pending', side_effect=git_pass), \
                patch.object(service.billing, 'process_next', side_effect=billing_pass):
            with TestClient(app, base_url=ORIGIN) as client:
                self.assertTrue(git_entered.wait(5))
                self.assertTrue(billing_entered.wait(5))
                billing = client.get('/account/teams/' + team + '/billing',
                                     headers={'Cookie': 'crewmesh_account=' + token})
                self.assertEqual(billing.status_code, 200, billing.text)
                self.assertTrue(billing.json()['checkout_available'])
                headers = {'Authorization': 'Bearer ' + credential['web_token']}
                snapshot = client.get('/api/snapshot', headers=headers)
                self.assertEqual(snapshot.status_code, 200, snapshot.text)
                self.assertTrue(snapshot.json()['git']['github_configured'])
                self.assertEqual(snapshot.json()['git']['binding']['repository'], 'github.com/acme/demo')
                begun = client.post('/api/git/github/authorize', headers=headers, json={})
                self.assertEqual(begun.status_code, 200, begun.text)
                callback = client.get('/api/git/github/callback',
                                      params={'state': begun.json()['state'], 'code': 'code'})
                self.assertEqual(callback.status_code, 200, callback.text)
                self.assertEqual(client.get('/account/teams/' + team + '/billing?secret=no').status_code, 400)

        self.assertTrue(all(stop() for stop in callbacks))
        self.assertTrue(app.state.billing_worker.stop.is_set())
        self.assertTrue(app.state.billing_worker.task.done())
        self.assertTrue(app.state.billing_worker.runtime.closed)
