import threading
import unittest
from pathlib import Path
from uuid import uuid4
from starlette.testclient import TestClient
from coopagents.coordination import CoordinationService
from coopagents.space_server import create_control_app


class BoardTests(unittest.TestCase):
    def setUp(self):
        directory = Path('.local/board-tests') / uuid4().hex
        directory.mkdir(parents=True)
        self.service = CoordinationService(directory / 'space.sqlite3')
        self.owner = self.service.identity.create_room('Board', 'Owner')
        self.origin = 'http://127.0.0.1:8769'
        self.client = TestClient(create_control_app(self.origin, 'control', threading.Event(),
            self.owner['room_id'], service=self.service, source_token=self.owner['agent_token']),
            base_url=self.origin, client=('127.0.0.1', 1234))

    def open(self):
        response = self.client.post('/board/open', json={}, headers={'Authorization': 'Bearer control'})
        self.assertEqual(response.status_code, 200)
        return response.json()['url'].split('#', 1)[1]

    def session(self):
        response = self.client.post('/board/session', json={'ticket': self.open()}, headers={'Origin': self.origin})
        self.assertEqual(response.status_code, 200)
        return response.json()['token']

    def test_shell_is_anonymous_and_static_is_whitelisted(self):
        response = self.client.get('/board')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(self.owner['agent_token'], response.text)
        self.assertIn("script-src 'self'", response.headers['content-security-policy'])
        self.assertEqual(self.client.get('/board/static/app.js').status_code, 404)
        self.assertEqual(self.client.get('/board/snapshot').status_code, 401)

    def test_ticket_one_use_same_origin_and_capability_is_narrow(self):
        ticket = self.open()
        self.assertEqual(self.client.post('/board/session', json={'ticket': ticket}).status_code, 401)
        self.assertEqual(self.client.post('/board/session', json={'ticket': ticket}, headers={'Origin': 'https://evil.test'}).status_code, 403)
        result = self.client.post('/board/session', json={'ticket': ticket}, headers={'Origin': self.origin})
        token = result.json()['token']
        self.assertNotEqual(token, self.owner['agent_token'])
        self.assertEqual(self.client.post('/board/session', json={'ticket': ticket}, headers={'Origin': self.origin}).status_code, 401)
        headers = {'Authorization': 'Bearer ' + token}
        self.assertEqual(self.client.get('/board/snapshot', headers=headers).status_code, 200)
        for path in ('/status', '/stop'):
            result = self.client.get(path, headers=headers) if path == '/status' else self.client.post(path, json={}, headers=headers)
            self.assertEqual(result.status_code, 401)
        self.assertEqual(self.client.post('/api/operations/read_inbox', json={}, headers=headers).status_code, 404)

    def test_snapshot_does_not_mark_messages_read_and_revocation_denies(self):
        token = self.session()
        self.service.messages.send_request(self.owner['agent_token'], 'board-read', self.owner['member_id'], None, 1, 'Question')
        headers = {'Authorization': 'Bearer ' + token}
        first = self.client.get('/board/snapshot', headers=headers).json()['requests'][0]
        self.assertIsNone(first['read_at'])
        self.assertIsNone(first['processed_at'])
        self.client.get('/board/snapshot', headers=headers)
        self.assertIsNone(self.service.messages.list_requests(self.owner['agent_token'])[0]['read_at'])
        self.service.identity.rotate_agent(self.owner['web_token'])
        self.assertEqual(self.client.get('/board/snapshot', headers=headers).status_code, 401)

    def test_expiry_and_maps_are_bounded(self):
        from coopagents.space_board import BoardAccess
        clock = [1.0]
        access = BoardAccess(self.service, self.owner['agent_token'], clock=lambda: clock[0], limit=2)
        old = access.issue()
        clock[0] += 61
        from coopagents.errors import AccessDenied
        with self.assertRaises(AccessDenied):
            access.consume(old)
        one, two, three = access.issue(), access.issue(), access.issue()
        self.assertLessEqual(len(access.tickets), 2)
        with self.assertRaises(AccessDenied):
            access.consume(one)
        session = access.consume(two)
        second = access.consume(three)
        third = access.consume(access.issue())
        self.assertLessEqual(len(access.sessions), 2)
        with self.assertRaises(AccessDenied):
            access.authenticate(session)
        access.authenticate(second)
        access.authenticate(third)
        clock[0] += 3601
        with self.assertRaises(AccessDenied):
            access.authenticate(third)

    def test_host_public_and_agent_credentials_cannot_open_board(self):
        for token in ('', self.owner['agent_token'], self.owner['web_token']):
            self.assertEqual(self.client.post('/board/open', json={}, headers={'Authorization': 'Bearer '+token}).status_code, 401)
        self.assertEqual(self.client.get('/board', headers={'Host': 'evil.test'}).status_code, 400)
        from coopagents.space_server import create_space_app
        public = TestClient(create_space_app(self.service, room_id=self.owner['room_id'], origin=self.origin), base_url=self.origin)
        self.assertIn(public.get('/board').status_code, (401, 404))
        self.assertIn(public.post('/board/open', json={}).status_code, (401, 404))

    def test_non_owner_source_is_rejected(self):
        from coopagents.space_board import BoardAccess
        from coopagents.errors import AccessDenied
        invitation = self.service.identity.create_invite(self.owner['web_token'])
        member = self.service.identity.join_invite(invitation['invite_token'], 'Member')
        with self.assertRaises(AccessDenied):
            BoardAccess(self.service, member['agent_token'])

    def test_board_websocket_uses_only_board_session(self):
        token = self.session()
        with self.client.websocket_connect('ws://127.0.0.1:8769/api/events', headers={'Origin': self.origin}) as ws:
            ws.send_json({'token': token, 'after_id': 0})
            self.assertEqual(ws.receive_json()['type'], 'ready')
        from starlette.websockets import WebSocketDisconnect
        with self.assertRaises(WebSocketDisconnect) as error:
            with self.client.websocket_connect('ws://127.0.0.1:8769/api/events', headers={'Origin': self.origin}) as ws:
                ws.send_json({'token': self.owner['agent_token'], 'after_id': 0})
                ws.receive_json()
        self.assertEqual(error.exception.code, 4401)
