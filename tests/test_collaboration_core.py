"""Task-free collaboration through the normal host and native stdio registrations."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest
from uuid import uuid4

from mcp import Client, StdioServerParameters

from coopagents import space_runtime
from coopagents.collaboration_core import CollaborationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError
from coopagents.space_connect import bridge_command


class CollaborationTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/collaboration-tests') / uuid4().hex / 'space.sqlite3'
        self.service = CollaborationService(self.path)
        self.alice = self.service.identity.create_room('Demo', 'Alice')
        self.bob = self.service.identity.add_member(self.alice['web_token'], 'Bob')

    def share(self, member, subject, **kwargs):
        return self.service.call('share_work', member['agent_token'], dict(subject=subject, summary='Shared intent', **kwargs))

    def test_simultaneous_starts_negative_controls_expiry_and_isolation(self):
        now = datetime.now(timezone.utc)
        self.service.awareness.clock = lambda: now
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda m: self.share(m, 'Checkout'), [self.alice, self.bob]))
        self.assertEqual(sorted(len(r['related_work']) for r in results), [0, 1])
        self.share(self.alice, '首页', also_called='landing, homepage')
        self.assertEqual(self.share(self.bob, 'public landing')['related_work'][0]['subject'], '首页')
        self.share(self.alice, 'billing page')
        self.assertEqual(self.share(self.bob, 'profile page')['related_work'], [])
        self.share(self.alice, 'billing settings')
        self.assertEqual(self.share(self.bob, 'account settings')['related_work'], [])
        other = self.service.identity.create_room('Elsewhere', 'Stranger')
        self.assertEqual(self.share(other, 'Checkout')['related_work'], [])
        now += timedelta(hours=6)
        self.assertEqual(self.share(self.bob, 'Checkout')['related_work'], [])
        with self.assertRaises(AccessDenied):
            self.service.call('find_related', self.alice['web_token'], {'subject': 'Checkout'})
        self.assertEqual(self.service.wake_digest(self.bob['agent_token'])['items'], [])

    def test_choice_requires_addressed_evidence_and_preserves_revisions(self):
        a, b = self.alice['agent_token'], self.bob['agent_token']
        def answer(key):
            request = self.service.send_request(a, key, self.bob['member_id'], 'Which implementation?')
            reply = self.service.messages.reply(b, request['id'], key, 1, 'Agreed', 'src/'+key)
            return dict(subject='Checkout', summary='Use the agreed path', request_id=request['id'],
                        reply_id=reply['replies'][0]['id'], expected_revision=0)
        first = answer('checkout')
        with self.assertRaises(NotFound):
            self.service.call('remember_choice', b, first)
        with self.assertRaises(ValidationError):
            self.service.call('remember_choice', a, first | {'reference': 'not-in-the-answer'})
        self.assertEqual(self.service.call('remember_choice', a, first)['revision'], 1)
        second = answer('updated')
        with self.assertRaises(Conflict):
            self.service.call('remember_choice', a, second)
        self.service.call('remember_choice', a, dict(second, expected_revision=1))
        self.assertEqual(self.service.call('remember_choice', a, first)['revision'], 1)
        restored = CollaborationService(self.path)
        choice, = restored.awareness.find_related(b, 'Checkout')['choices']
        self.assertEqual((choice['revision'], choice['reference']), (2, 'src/updated'))
        other = restored.identity.create_room('Separate', 'Third')['agent_token']
        self.assertEqual(restored.awareness.find_related(other, 'Checkout')['choices'], [])

    def test_existing_workflow_room_keeps_identity_direct_receipts_and_task_state(self):
        from coopagents.coordination import CoordinationService
        path = self.path.with_name('old.sqlite3')
        old = CoordinationService(path)
        alice = old.identity.create_room('Old room', 'Alice')
        bob = old.identity.add_member(alice['web_token'], 'Bob')
        task = old.tasks.create_task(alice['web_token'], 'home', 'Build home', 'web')
        a, b = alice['agent_token'], bob['agent_token']
        tracked = old.messages.send_request(a, 'tracked', bob['member_id'], task['id'], 1, 'task message')
        direct = old.messages.send_request(a, 'direct', bob['member_id'], None, 1, 'direct message')
        old.messages.reply(b, direct['id'], 'answer', 1, 'Here', 'pages/index.tsx')
        old.workflow.read_replies(a)
        core = CollaborationService(path)
        self.assertEqual(core.wake_digest(a)['items'], [])
        self.assertEqual([r['id'] for r in core.messages.read_inbox(b)['requests']], [direct['id']])
        with self.assertRaises(NotFound):
            core.messages.reply(b, tracked['id'], 'bad', 1, 'wrong runtime')
        self.assertEqual(len(CoordinationService(path).tasks.list_tasks(a)), 1)

    def test_self_hosted_factory_and_historical_outbox_use_the_core(self):
        import secrets
        from starlette.testclient import TestClient
        from coopagents.api import create_app

        secret = secrets.token_urlsafe(32)
        origin = 'https://team.example'
        app = create_app(self.path.with_name('hosted.sqlite3'), public_url=origin, bootstrap_secret=secret)
        self.assertIsInstance(app.state.service, CollaborationService)
        with TestClient(app, base_url=origin) as client:
            room = {'name': 'Team', 'owner_name': 'Alice'}
            self.assertEqual(client.post('/api/rooms', json=room).status_code, 401)
            owner = client.post('/api/rooms', json=room, headers={'x-coopagents-bootstrap': secret}).json()
            web = {'Origin': origin, 'Authorization': 'Bearer ' + owner['web_token']}
            invite = client.post('/api/invites', json={}, headers=web).json()
            member = client.post('/api/join', json={'invite_token': invite['invite_token'], 'display_name': 'B'}).json()
            agent = {'Authorization': 'Bearer '+owner['agent_token']}
            msg = dict(receiver_member_id=member['member_id'], request_key='retried', body='Same route?', task_id=None)
            path = '/api/operations/send_request'
            first = client.post(path, headers=agent, json=msg)
            self.assertEqual(first.status_code, 200, first.text)
            self.assertEqual(client.post(path, headers=agent, json=msg).json()['id'], first.json()['id'])
            self.assertEqual(client.post(path, headers=agent, json=msg | {'task_id': 1}).status_code, 400)
            peer = {'Authorization': 'Bearer '+member['agent_token']}
            digest = '/api/operations/wake_digest'
            self.assertEqual(client.post(digest, headers=peer, json={}).json()['counts']['request'], 1)
            client.get('/api/inbox', headers=peer)
            self.assertEqual(client.post(digest, headers=peer, json={}).json()['counts']['request'], 0)
            self.assertEqual(client.post('/api/operations/create_task', headers=web, json={}).status_code, 404)
            self.assertEqual(client.get('/ready').status_code, 200)
            client.post('/api/operations/revoke_member', headers=web, json={'member_id': member['member_id']})
            self.assertEqual(client.post(digest, headers=peer, json={}).status_code, 401)

    def test_fresh_default_schema(self):
        with self.service.identity.db.connect() as db:
            names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(names, {'rooms', 'members', 'invitations', 'credentials', 'sqlite_sequence',
                                 'work_subjects', 'work_terms', 'work_signals', 'implementation_choices',
                                 'message_requests', 'message_deliveries', 'message_replies', 'message_receipts',
                                 'message_reply_reads', 'room_event_streams', 'room_change_events'})


class NativeCollaborationTests(unittest.TestCase):
    def test_two_pages_and_a_fresh_session(self):
        root = Path('.local/collaboration-tests') / uuid4().hex
        created = space_runtime.create('Demo', 'Alice', root/'owner', network='local')
        owner = Path(created['profile'])
        self.addCleanup(space_runtime.stop, owner)
        self.assertEqual(created['runtime'], 'collaboration')
        from coopagents.onboarding_doctor import profile_checks
        checks = {item['id']: item['status'] for item in profile_checks(owner)['checks']}
        self.assertEqual(checks['collaboration_lookup'], 'pass')
        self.assertNotIn('git_write_ready', checks)
        def join(name):
            invite = space_runtime.invite(owner)
            return Path(space_runtime.join(invite['invitation_file'], name, root/name)['profile'])
        bob, third = join('Bob'), join('Chen')
        def client(path):
            python, *args = bridge_command(path.resolve())
            return Client(StdioServerParameters(command=python, args=args), cache=None)
        async def call(agent, tool, **arguments):
            result = await agent.call_tool(tool, arguments)
            self.assertFalse(result.is_error, result.content)
            return result.structured_content
        async def coordinate():
            async with client(owner) as a, client(bob) as b:
                tools = {t.name for t in (await b.list_tools()).tools}
                self.assertIn('share_work', tools)
                self.assertNotIn('claim_task', tools)
                result = await call(a, 'share_work', subject='首页', summary='实现演示入口', reference='web/Home.tsx')
                self.assertEqual(result['related_work'], [])
                discovered = await call(b, 'share_work', subject='演示首页', summary='准备搭建入口', reference='app/index.tsx')
                peer, = discovered['related_work']
                req = await call(b, 'send_request', receiver_member_id=peer['member_id'], request_key='verify',
                                 body='Do both serve the public landing route? Can we use your implementation?')
                inbox, = (await call(a, 'read_inbox'))['requests']
                self.assertEqual(inbox['id'], req['id'])
                await call(a, 'reply', request_id=req['id'], context_version=1, request_key='confirm',
                           body='Yes, use the existing demo route.', evidence='web/Home.tsx')
                reply, = (await call(b, 'read_replies'))['replies']
                await call(b, 'remember_choice', subject=peer['subject'], summary='演示入口使用已接入路由的首页',
                           request_id=req['id'], reply_id=reply['id'], expected_revision=0)
        asyncio.run(coordinate())
        space_runtime.stop(owner)
        space_runtime.start(owner)
        async def subsequent():
            async with client(third) as c:
                result = await call(c, 'share_work', subject='首页搜索', summary='给首页加搜索')
                choice, = result['choices']
                self.assertEqual(choice['reference'], 'web/Home.tsx')
                negative = await call(c, 'find_related', subject='账号设置')
                self.assertEqual(negative, {'related_work': [], 'choices': []})
        asyncio.run(subsequent())
