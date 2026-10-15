"""Additional personal connection credentials retain existing connections."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from urllib.request import urlopen
from transport_support import LiveService


class AgentConnectTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    def connect(self, token, data=None, origin=True):
        return self.live.request('POST', '/api/agent-connect', token, data or {},
                                 {'Origin': self.live.url} if origin else {})

    def test_additional_credential_current_identity_expiry_and_revoke(self):
        status, result, headers = self.connect(self.member['web_token'])
        self.assertEqual(status, 200)
        self.assertEqual(result['member_id'], self.member['member_id'])
        self.assertEqual(result['room_id'], self.member['room_id'])
        self.assertIn('no-store', headers['Cache-Control'])
        for token in (result['agent_token'], self.member['agent_token']):
            self.assertEqual(self.live.request('GET', '/api/me', token)[0], 200)
        self.assertNotIn(result['agent_token'], str(self.live.request('GET', '/api/snapshot', self.member['web_token'])[1]))
        with patch('coopagents.identity._utcnow', return_value=datetime.now(timezone.utc) + timedelta(days=91)):
            self.assertEqual(self.live.request('GET', '/api/me', result['agent_token'])[0], 401)
        self.live.request('POST', '/api/agent-token', self.member['web_token'], {})
        self.assertEqual(self.live.request('GET', '/api/me', result['agent_token'])[0], 401)

    def test_auth_origin_and_self_reported_identity_denied(self):
        self.assertEqual(self.connect(None)[0], 401)
        self.assertEqual(self.connect(self.owner['agent_token'])[0], 401)
        self.assertEqual(self.connect(self.owner['web_token'], origin=False)[0], 403)
        self.assertEqual(self.connect(self.owner['web_token'], {'member_id': self.member['member_id']})[0], 400)
        self.assertEqual(self.live.request('POST', '/api/agent-connect', self.owner['web_token'], {}, {'Origin':'https://foreign.example'})[0], 403)

    def test_public_skill_and_reference_have_no_private_credentials(self):
        for name in ('SKILL.md', 'protocol.md'):
            with urlopen(self.live.url + '/skills/coopagents-connect/' + name) as response:
                self.assertEqual(response.status, 200)
                content = response.read().decode()
                self.assertNotIn(self.owner['agent_token'], content)
                self.assertIn('nosniff', response.headers['X-Content-Type-Options'])


    def test_managed_project_permission_and_account_session_revocation(self):
        service = self.live.app.app.state.service
        accounts, workspaces = service.accounts, service.workspaces
        account = accounts.bootstrap('connectowner', 'Synthetic connect password 123')
        session = accounts.create_session(account['id'])['session_token']
        team = workspaces.create_team(session, 'Connect team')['team_id']
        room = workspaces.create_project(session, team, 'Allowed project')['room_id']
        web = workspaces.project_credential(session, room)['web_token']
        status, result, _ = self.connect(web)
        self.assertEqual(status, 200)
        self.assertEqual(result['room_id'], room)
        accounts.logout(session)
        self.assertEqual(self.connect(web)[0], 401)
        # Agent credential remains personal, independent of the browser session.
        self.assertEqual(self.live.request('GET', '/api/me', result['agent_token'])[0], 200)
        current = accounts.login('connectowner', 'Synthetic connect password 123')['session_token']
        workspaces.remove_project_member(current, room, account['id'])
        self.assertEqual(self.live.request('GET', '/api/me', result['agent_token'])[0], 401)
        self.assertEqual(self.connect(web)[0], 401)

    def test_credential_limit_rejects_without_issuing_or_revoking(self):
        issued = []
        for _ in range(31):
            status, result, _ = self.connect(self.member['web_token'])
            self.assertEqual(status, 200)
            issued.append(result['agent_token'])
        self.assertEqual(self.connect(self.member['web_token'])[0], 409)
        self.assertEqual(self.live.request('GET', '/api/me', issued[0])[0], 200)
        self.assertEqual(self.live.request('GET', '/api/me', self.member['agent_token'])[0], 200)
