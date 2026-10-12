"""Shared account-free joining and business HTTP permissions."""
from pathlib import Path
from uuid import uuid4
import unittest
from unittest.mock import patch

from crewmesh.coordination import CoordinationService
from crewmesh.errors import AccessDenied


class SpaceIdentityTests(unittest.TestCase):
    def setUp(self):
        self.service = CoordinationService(Path('.local/test-evidence') / (uuid4().hex + '.sqlite3'))
        self.owner = self.service.identity.create_room('Space', 'Owner')

    def test_wrong_space_does_not_consume_invitation(self):
        invitation = self.service.identity.create_invite(self.owner['web_token'])
        with self.assertRaises(AccessDenied):
            self.service.identity.join_invite(invitation['invite_token'], 'Peer', expected_room_id='wrong')
        joined = self.service.identity.join_invite(invitation['invite_token'], 'Peer', expected_room_id=self.owner['room_id'])
        self.assertEqual(joined['room_id'], self.owner['room_id'])

    def test_revocation_requires_owner_and_revokes_both_credentials(self):
        peer = self.service.identity.add_member(self.owner['web_token'], 'Peer')
        with self.assertRaises(AccessDenied):
            self.service.identity.revoke_member(peer['web_token'], self.owner['member_id'])
        invitation = self.service.identity.create_invite(self.owner['web_token'])
        self.service.identity.revoke_invite(self.owner['web_token'], invitation['invite_token'])
        with self.assertRaises(AccessDenied):
            self.service.identity.join_invite(invitation['invite_token'], 'Denied')
        self.service.identity.revoke_member(self.owner['web_token'], peer['member_id'])
        for key in ('web_token', 'agent_token'):
            with self.assertRaises(AccessDenied):
                self.service.identity.authenticate(peer[key])

    def test_shared_http_rejects_bootstrap_and_agent_management(self):
        from starlette.applications import Starlette
        from starlette.testclient import TestClient
        from crewmesh.coordination_http import coordination_routes
        with TestClient(Starlette(routes=coordination_routes(self.service, base_url='http://127.0.0.1')), base_url='http://127.0.0.1') as client:
            headers = {'Authorization': 'Bearer ' + self.owner['agent_token']}
            self.assertEqual(client.get('/api/agent-snapshot', headers=headers).status_code, 200)
            self.assertEqual(client.post('/api/operations/create_room', headers=headers, json={}).status_code, 401)
            self.assertEqual(client.post('/api/operations/create_task', headers=headers, json={'intent_key':'x','title':'X','scope':'src'}).status_code, 401)
            web = {'Authorization':'Bearer '+self.owner['web_token'],'Origin':'http://127.0.0.1'}
            self.assertEqual(client.post('/api/operations/create_task', headers=web, json={'intent_key':'x','title':'X','scope':'src'}).status_code, 200)
            web['Origin'] = 'https://hostile.example'
            self.assertEqual(client.post('/api/operations/invite', headers=web, json={}).status_code, 401)

    def test_http_domain_error_subclasses_keep_permission_response(self):
        from starlette.applications import Starlette
        from starlette.testclient import TestClient
        from crewmesh.coordination_http import coordination_routes
        class ProviderDenied(AccessDenied):
            pass
        with TestClient(Starlette(routes=coordination_routes(self.service)), base_url='http://127.0.0.1') as client:
            with patch.object(self.service, 'call', side_effect=ProviderDenied('Provider denied')):
                result = client.post('/api/operations/claim_task', headers={'Authorization':'Bearer '+self.owner['agent_token']}, json={'task_id':1})
                self.assertEqual(result.status_code, 401)


if __name__ == '__main__':
    unittest.main()
