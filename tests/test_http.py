import http.client
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

from transport_support import LiveService


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.owner, self.member = self.live.bootstrap()

    def call(self, method, path, token=None, data=None):
        status, result, _ = self.live.request(method, path, token, data)
        self.assertEqual(status, 200, result)
        return result

    def test_complete_workflow(self):
        web, agent, other = self.owner['web_token'], self.owner['agent_token'], self.member['agent_token']
        self.assertEqual(self.call('GET', '/health'), {'status': 'ok'})
        self.assertEqual(self.call('GET', '/api/me', web)['me']['member_id'], self.owner['member_id'])
        task = self.call('POST', '/api/tasks', web, {'intent_key': 't', 'title': 'Build', 'scope': 'src'})
        tid = task['id']
        self.assertEqual(self.call('POST', f'/api/tasks/{tid}/claim', agent, {})['owner_member_id'], self.owner['member_id'])
        status, conflict, _ = self.live.request('POST', f'/api/tasks/{tid}/claim', other, {})
        self.assertEqual(status, 409)
        self.assertEqual(conflict['owner_member_id'], self.owner['member_id'])
        self.call('POST', '/api/tasks', web, {'intent_key': 't2', 'title': 'Other', 'scope': 'src/api'})
        self.call('POST', '/api/sessions', agent, {'session_key': 's', 'tool': 'codex-cli', 'repository': 'repo', 'branch': 'main', 'task_id': tid})
        self.call('POST', f'/api/tasks/{tid}/progress', agent, {'state': 'working', 'summary': 'Testing', 'evidence': 'test'})
        request = self.call('POST', '/api/requests', agent, {'request_key': 'r', 'receiver_member_id': None, 'context_version': 1, 'body': 'Question'})
        rid = request['id']
        self.call('POST', f'/api/requests/{rid}/assign', web, {'receiver_member_id': self.member['member_id']})
        inbox = self.call('GET', '/api/inbox?after_id=0&limit=50', other)
        self.assertEqual(inbox['requests'][0]['id'], rid)
        self.assertEqual(self.call('GET', '/api/inbox?after_id=' + str(inbox['next_cursor']), other)['requests'], [])
        self.call('POST', f'/api/requests/{rid}/ack', other, {})
        self.call('POST', f'/api/requests/{rid}/reply', other, {'request_key': 'reply', 'context_version': 1, 'body': 'Answer', 'evidence': 'test'})
        self.call('POST', f'/api/requests/{rid}/resolve', web, {'context_version': 1})
        contract = self.call('POST', '/api/contracts', agent, {'contract_key': 'c', 'expected_version': 0, 'title': 'Schema', 'body': 'v1', 'source_request_id': rid, 'commit_ref': 'abc'})
        self.call('POST', f"/api/contracts/{contract['id']}/decision", web, {'version': 1, 'decision': 'approved'})
        for name in ('tasks', 'sessions', 'progress', 'overlaps', 'requests', 'contracts', 'events'):
            self.assertTrue(self.call('GET', '/api/' + name, web), name)
        snapshot = self.call('GET', '/api/snapshot', web)
        self.assertEqual(len(snapshot['members']), 2)
        self.assertIn('server_time', snapshot)

    def test_validation_auth_and_boundaries(self):
        web, agent = self.owner['web_token'], self.owner['agent_token']
        cases = [('GET', '/api/me', None, None, 401), ('GET', '/api/snapshot', agent, None, 401),
                 ('POST', '/api/tasks', agent, {'intent_key': 't', 'title': 't', 'scope': 's'}, 401),
                 ('POST', '/api/invites', self.member['web_token'], {}, 401),
                 ('POST', '/api/tasks', web, {'intent_key': 't', 'title': 't', 'scope': 's', 'author': 'fake'}, 400),
                 ('POST', '/api/contracts', agent, {'contract_key': 'c', 'title': 't', 'body': 'b', 'expected_version': True}, 400),
                 ('POST', '/api/tasks', web, [], 400), ('POST', '/api/tasks', web, {'title': '\ud800'}, 400),
                 ('GET', '/api/inbox?after_id=bad', agent, None, 400), ('GET', '/api/me?token=secret', None, None, 400)]
        for method, path, token, data, expected in cases:
            with self.subTest(path=path, data=data):
                self.assertEqual(self.live.request(method, path, token, data)[0], expected)
        for path in ('/api/rooms', '/api/tasks', '/mcp'):
            self.assertEqual(self.live.request('POST', path, agent, {}, {'Origin': 'https://evil.example'})[0], 403)
        self.assertEqual(self.live.request('GET', '/health', headers={'Host': 'evil.example'})[0], 400)
        self.assertEqual(self.live.request('POST', '/api/rooms', raw=b'\xff', headers={'Content-Type': 'application/json'})[0], 400)
        self.assertEqual(self.live.request('POST', '/api/rooms', raw=b'{}')[0], 400)
        self.assertEqual(self.live.request('POST', '/api/rooms', raw=b' ' * 65537, headers={'Content-Type': 'application/json'})[0], 413)
        conn = http.client.HTTPConnection('127.0.0.1', self.live.port, timeout=10)
        conn.request('POST', '/api/rooms', body=iter([b'x' * 40000, b'x' * 30000]), headers={'Content-Type': 'application/json'}, encode_chunked=True)
        self.assertEqual(conn.getresponse().status, 413)
        conn.close()
        rotated = self.call('POST', '/api/agent-token', web, {})
        self.assertEqual(self.live.request('GET', '/api/me', agent)[0], 401)
        self.assertEqual(self.call('GET', '/api/me', rotated['agent_token'])['me']['kind'], 'agent')
        with patch('crewmesh.identity._utcnow', return_value=datetime.now(timezone.utc) + timedelta(days=100)):
            self.assertEqual(self.live.request('GET', '/api/me', rotated['agent_token'])[0], 401)
        with patch('crewmesh.tasks.TaskStore.list_tasks', side_effect=RuntimeError('secret-token')):
            # Bound method is already stored; patch it directly in the registered service.
            with patch.dict(self.live.app.app.state.service.reads, {'tasks': lambda token: (_ for _ in ()).throw(RuntimeError('secret-token'))}):
                status, body, _ = self.live.request('GET', '/api/tasks', web)
                self.assertEqual(status, 500)
                self.assertNotIn('secret-token', str(body))

    def test_room_visibility(self):
        other = self.call('POST', '/api/rooms', data={'name': 'Other', 'owner_name': 'Other'})
        task = self.call('POST', '/api/tasks', self.owner['web_token'], {'intent_key': 't', 'title': 'Build', 'scope': 'src'})
        status, body, _ = self.live.request('POST', f"/api/tasks/{task['id']}/claim", other['agent_token'], {})
        self.assertEqual(status, 404)
        self.assertNotIn('owner_member_id', body)
        self.assertEqual(self.call('GET', '/api/tasks', other['web_token']), [])


