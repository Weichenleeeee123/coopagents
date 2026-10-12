from pathlib import Path
import unittest
from uuid import uuid4

from starlette.applications import Starlette
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from httpx2 import Headers
from crewmesh.coordination import CoordinationService


class RealtimeTests(unittest.TestCase):
    def setUp(self):
        self.service = CoordinationService(Path('.local/realtime-tests') / (str(uuid4()) + '.sqlite3'))
        self.room = self.service.identity.create_room('room', 'owner')

    def client(self, **options):
        from crewmesh.realtime import events_route
        return TestClient(Starlette(routes=[events_route(self.service, base_url='http://localhost:8000', poll_interval=.01, heartbeat_interval=.03, **options)]), base_url='http://localhost:8000')

    def test_auth_replay_and_revocation(self):
        with self.client() as client:
            with client.websocket_connect('ws://localhost:8000/api/events', headers={'origin': 'http://localhost:8000'}) as ws:
                ws.send_json({'token': self.room['agent_token'], 'after_id': 0})
                self.assertEqual(ws.receive_json()['type'], 'ready')
                self.assertEqual(ws.receive_json()['type'], 'events')
                self.service.identity.rotate_agent(self.room['web_token'])
                with self.assertRaises(WebSocketDisconnect) as closed:
                    while True:
                        ws.receive_json()
                self.assertEqual(closed.exception.code, 4401)

    def test_reject_origin_host_query_and_auth(self):
        with self.client() as client:
            for path, headers in [('/api/events?token=secret', {}), ('/api/events', {'origin': 'https://evil.example'}), ('/api/events', {'host': 'evil.example'}),
                                  ('/api/events', {'sec-fetch-site': 'cross-site'}),
                                  ('/api/events', Headers([('host', 'localhost:8000'), ('host', 'localhost:8000')])),
                                  ('/api/events', Headers([('origin', 'http://localhost:8000'), ('origin', 'http://localhost:8000')]))]:
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect('ws://localhost:8000' + path, headers=headers):
                        pass
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                ws.send_json({'token': 'invalid', 'after_id': 0})
                with self.assertRaises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                self.assertEqual(closed.exception.code, 4401)

    def test_future_reset_and_no_business_frames(self):
        with self.client() as client:
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                ws.send_json({'token': self.room['web_token'], 'after_id': 999999})
                self.assertEqual(ws.receive_json()['type'], 'ready')
                self.assertEqual(ws.receive_json()['reason'], 'future_cursor')
                ws.send_json({'operation': 'create_task'})
                with self.assertRaises(WebSocketDisconnect) as closed:
                    while True:
                        ws.receive_json()
                self.assertEqual(closed.exception.code, 4400)

    def test_first_frame_size_schema_and_timeout(self):
        with self.client(auth_timeout=.03, frame_limit=128) as client:
            for raw in ('{}', '{broken', 'x' * 129, '{"token":"x","after_id":true}'):
                with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                    ws.send_text(raw)
                    with self.assertRaises(WebSocketDisconnect):
                        ws.receive_json()
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                with self.assertRaises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                self.assertEqual(closed.exception.code, 4408)
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                ws.send_json({'token': self.room['web_token'], 'after_id': True})
                with self.assertRaises(WebSocketDisconnect) as closed:
                    ws.receive_json()
                self.assertEqual(closed.exception.code, 4400)

    def test_slow_server_send_has_bounded_backpressure(self):
        import asyncio
        import json
        from crewmesh.realtime import events_route
        app = Starlette(routes=[events_route(self.service, base_url='http://localhost:8000', send_timeout=.02)])
        messages = iter([{'type': 'websocket.connect'}, {'type': 'websocket.receive', 'text': json.dumps({'token': self.room['web_token'], 'after_id': 0})}])
        sent = []
        async def receive():
            return next(messages)
        async def send(message):
            if message['type'] == 'websocket.send':
                await asyncio.Event().wait()
            sent.append(message)
        async def run():
            await asyncio.wait_for(app({'type': 'websocket', 'path': '/api/events', 'raw_path': b'/api/events', 'root_path': '', 'query_string': b'', 'scheme': 'ws', 'server': ('localhost', 8000), 'client': ('localhost', 123), 'headers': [(b'host', b'localhost:8000')], 'subprotocols': []}, receive, send), .5)
        asyncio.run(run())
        self.assertEqual(sent[-1], {'type': 'websocket.close', 'code': 4408, 'reason': ''})

    def test_connection_limits_release_and_heartbeat(self):
        with self.client(per_identity=1, max_connections=2) as client:
            with client.websocket_connect('ws://localhost:8000/api/events') as first:
                first.send_json({'token': self.room['web_token'], 'after_id': 0})
                first.receive_json()
                page = first.receive_json()
                with client.websocket_connect('ws://localhost:8000/api/events') as second:
                    second.send_json({'token': self.room['web_token'], 'after_id': 0})
                    with self.assertRaises(WebSocketDisconnect) as closed:
                        second.receive_json()
                    self.assertEqual(closed.exception.code, 4429)
                self.assertEqual(first.receive_json()['type'], 'heartbeat')
            with client.websocket_connect('ws://localhost:8000/api/events') as reconnect:
                reconnect.send_json({'token': self.room['web_token'], 'after_id': page['cursor']})
                self.assertEqual(reconnect.receive_json()['type'], 'ready')
                self.assertEqual(reconnect.receive_json()['type'], 'heartbeat')
        with self.client(max_connections=1) as client:
            with client.websocket_connect('ws://localhost:8000/api/events'):
                with self.assertRaises(WebSocketDisconnect):
                    with client.websocket_connect('ws://localhost:8000/api/events'):
                        pass

    def test_hosted_route_before_mcp_and_public_origin(self):
        from crewmesh.api import create_app
        app = create_app(Path('.local/realtime-tests') / (str(uuid4()) + '.sqlite3'), base_url='http://localhost:8000')
        room = app.state.service.identity.create_room('hosted', 'owner')
        with TestClient(app, base_url='http://localhost:8000') as client:
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                ws.send_json({'token': room['web_token'], 'after_id': 0})
                self.assertEqual(ws.receive_json()['type'], 'ready')
        from crewmesh.realtime import events_route
        public_app = Starlette(routes=[events_route(self.service, public_url='https://crew.example')])
        with TestClient(public_app) as client:
            with client.websocket_connect('wss://crew.example/api/events', headers={'origin': 'https://crew.example'}) as ws:
                ws.send_json({'token': self.room['web_token'], 'after_id': 0})
                self.assertEqual(ws.receive_json()['type'], 'ready')
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('wss://crew.example/api/events', headers={'origin': 'http://crew.example'}):
                    pass

    def test_hosted_account_session_revoked_during_idle_stream(self):
        from crewmesh.api import Service
        service = Service(Path('.local/realtime-tests') / (str(uuid4()) + '.sqlite3'))
        service.accounts.bootstrap('owner', 'long password 123')
        session = service.accounts.login('owner', 'long password 123')['session_token']
        team = service.workspaces.create_team(session, 'Team')['team_id']
        room = service.workspaces.create_project(session, team, 'Project')['room_id']
        credential = service.workspaces.project_credential(session, room)['web_token']
        from crewmesh.realtime import events_route
        app = Starlette(routes=[events_route(service, base_url='http://localhost:8000', poll_interval=.01)])
        with TestClient(app) as client:
            with client.websocket_connect('ws://localhost:8000/api/events') as ws:
                ws.send_json({'token': credential, 'after_id': 0})
                self.assertEqual(ws.receive_json()['type'], 'ready')
                ws.receive_json()
                service.accounts.logout(session)
                with self.assertRaises(WebSocketDisconnect) as closed:
                    while True:
                        ws.receive_json()
                self.assertEqual(closed.exception.code, 4401)

    def test_real_loopback_socket_replays_after_task_mutation(self):
        import json
        from websockets.sync.client import connect
        from transport_support import LiveService
        live = LiveService()
        try:
            room = live.app.state.service.identity.create_room('wire', 'owner')
            cursor = live.app.state.service.change_events.read(room['web_token'])['cursor']
            live.app.state.service.tasks.create_task(room['web_token'], 'wire-key', 'title', 'scope')
            with connect(live.url.replace('http://', 'ws://') + '/api/events', open_timeout=3) as ws:
                ws.send(json.dumps({'token': room['web_token'], 'after_id': cursor}))
                self.assertEqual(json.loads(ws.recv(timeout=3))['type'], 'ready')
                page = json.loads(ws.recv(timeout=3))
                self.assertEqual(page['events'][0]['topic'], 'tasks')
        finally:
            live.close()

    def test_real_loopback_socket_rejects_oversized_auth_at_transport(self):
        from websockets.sync.client import connect
        from websockets.exceptions import ConnectionClosedError
        from transport_support import LiveService
        live = LiveService()
        try:
            with connect(live.url.replace('http://', 'ws://') + '/api/events', open_timeout=3) as ws:
                ws.send('x' * 4097)
                with self.assertRaises(ConnectionClosedError) as closed:
                    ws.recv(timeout=3)
                self.assertEqual(closed.exception.rcvd.code, 1009)
        finally:
            live.close()


if __name__ == '__main__':
    unittest.main()

