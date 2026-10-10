"""Two-member restart acceptance over real HTTP, retaining all evidence."""
import unittest
from concurrent.futures import ThreadPoolExecutor
from transport_support import LiveService


class RestartAcceptance(unittest.TestCase):
    def test_claim_offline_delivery_and_versions_survive_service_restart(self):
        live = LiveService()
        try:
            owner, member = live.bootstrap()
            def post(path, token, data):
                status, result, _ = live.request('POST', path, token, data)
                self.assertEqual(status, 200, result)
                return result
            task = post('/api/tasks', owner['web_token'], {'intent_key': 'p4-auth', 'title': 'Login schema', 'scope': 'src/login'})
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda token: live.request('POST', f"/api/tasks/{task['id']}/claim", token, {}),
                                        (owner['agent_token'], member['agent_token'])))
            self.assertEqual(sorted(r[0] for r in results), [200, 409])
            winner = next(r[1]['owner_member_id'] for r in results if r[0] == 200)
            request = post('/api/requests', owner['agent_token'], {'request_key': 'offline-schema', 'context_version': 1,
                           'receiver_member_id': member['member_id'], 'body': 'Does v1 return user_id?'})
            proposal = post('/api/contracts', owner['agent_token'], {'contract_key': 'login-schema', 'expected_version': 0,
                            'title': 'Login v1', 'body': 'user_id: string', 'source_request_id': request['id']})
            post(f"/api/contracts/{proposal['id']}/decision", owner['web_token'], {'version': 1, 'decision': 'approved'})
            post('/api/contracts', owner['agent_token'], {'contract_key': 'login-schema', 'expected_version': 1,
                  'title': 'Login v2', 'body': 'user_id and login_ticket: string'})
            database = live.database
            live.close()
            live = LiveService(database)
            status, snapshot, _ = live.request('GET', '/api/snapshot', owner['web_token'])
            self.assertEqual(status, 200)
            self.assertEqual(snapshot['tasks'][0]['owner_member_id'], winner)
            self.assertEqual(snapshot['contracts'][0]['current_version'], 2)
            self.assertEqual(snapshot['contracts'][0]['effective_version'], 1)
            self.assertIsNone(snapshot['requests'][0]['read_at'])
            self.assertIsNone(snapshot['requests'][0]['processed_at'])
            status, inbox, _ = live.request('GET', '/api/inbox', member['agent_token'])
            self.assertEqual(status, 200)
            self.assertEqual(inbox['requests'][0]['id'], request['id'])
            self.assertIsNone(inbox['requests'][0]['processed_at'])
            post(f"/api/requests/{request['id']}/ack", member['agent_token'], {})
            post(f"/api/requests/{request['id']}/reply", member['agent_token'], {'request_key': 'answer', 'context_version': 1,
                  'body': 'Confirmed user_id: string', 'evidence': 'P4 restart acceptance'})
            resolved = post(f"/api/requests/{request['id']}/resolve", owner['agent_token'], {'context_version': 1})
            self.assertTrue(resolved['resolved_at'])
            status, outsider, _ = live.request('POST', '/api/rooms', data={'name': 'Other', 'owner_name': 'Other'})
            self.assertEqual(status, 200)
            self.assertEqual(live.request('GET', '/api/tasks', outsider['web_token'])[1], [])
            self.assertEqual(live.request('GET', '/api/requests', outsider['web_token'])[1], [])
        finally:
            live.close()
