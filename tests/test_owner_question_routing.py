"""Owner-only questions follow responsibility without inventing source tasks."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import Conflict
from coopagents.identity import IdentityStore
from coopagents import workflow


class OwnerQuestionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('owner-routing-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Requester')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Owner')
        self.c = self.s.identity.add_member(self.a['web_token'], 'Next owner')
        self.target = self.task('api', self.b)

    def task(self, name, owner=None):
        task = self.s.tasks.create_task(self.a['web_token'], name, name, 'src/' + name)
        return self.s.tasks.claim_task(owner['agent_token'], task['id'], name) if owner else task

    def ask(self, **extra):
        data = {'request_key': 'question', 'body': 'Which field?', 'target_task_id': self.target['id']}
        data.update(extra)
        return self.s.call('ask_owner', self.a['agent_token'], data)

    def change(self, operation, target=None, **extra):
        target = target or self.target
        current = next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id'] == target['id'])
        return self.s.call(operation, self.a['web_token'], {'task_id': current['id'],
            'expected_revision': current['revision'], 'request_key': uuid4().hex, 'summary': 'Responsibility changed', **extra})

    def answer(self, result, member):
        request = result['request']
        return self.s.messages.reply(member['agent_token'], request['id'], uuid4().hex,
                                      request['context_version'], 'Use user_id')['replies'][-1]

    def test_unassigned_question_is_durable_and_claim_routes_without_retry(self):
        target = self.task('unowned')
        queued = self.ask(target_task_id=target['id'])
        self.assertEqual(queued['status'], 'unassigned')
        self.assertIsNone(queued['request'])
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM workflow_questions').fetchone()[0], 1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 0)
        self.s = CoordinationService(self.path)
        self.s.tasks.claim_task(self.b['agent_token'], target['id'], 'claim')
        with self.s.identity.db.connect() as db:
            delivered = db.execute('SELECT * FROM message_requests').fetchone()
            self.assertIsNotNone(delivered, 'claim must route inside its own transaction')
            self.assertEqual(delivered['receiver_member_id'], self.b['member_id'])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM tasks').fetchone()[0], 2)
        result = self.ask(target_task_id=target['id'])
        self.assertEqual(result['routing'], 'task_owner')
        self.assertEqual(result['request']['id'], delivered['id'])

    def test_handoff_retains_history_but_only_exact_current_reply_can_be_confirmed(self):
        initial = self.ask()
        old = initial['request']
        self.s.messages.read_inbox(self.b['agent_token'])
        old_reply = self.answer(initial, self.b)
        self.s.call('read_replies', self.a['agent_token'], {})
        self.change('force_handoff', target_member_id=self.c['member_id'])
        current = self.ask()
        self.assertNotEqual(current['request']['id'], old['id'])
        self.assertEqual(current['request']['receiver_member_id'], self.c['member_id'])
        self.assertEqual(current['request']['owner_route_state'], 'current')
        self.assertEqual(current['request']['owner_target_task_id'], self.target['id'])
        for operation in ('reply', 'resolve', 'ack', 'assign'):
            with self.subTest(operation=operation), self.assertRaises(Conflict):
                if operation == 'reply':
                    self.s.messages.reply(self.b['agent_token'], old['id'], 'stale', old['context_version'], 'old')
                elif operation == 'resolve':
                    self.s.messages.resolve_request(self.a['agent_token'], old['id'], old['context_version'])
                elif operation == 'ack':
                    self.s.messages.acknowledge(self.b['agent_token'], old['id'])
                else:
                    self.s.messages.assign_receiver(self.a['web_token'], old['id'], self.b['member_id'])
        self.assertEqual(self.s.messages.read_inbox(self.b['agent_token'])['requests'], [])
        new_reply = self.answer(current, self.c)
        with self.assertRaises(Conflict):
            self.s.messages.resolve_request(self.a['agent_token'], current['request']['id'], current['request']['context_version'])
        reads = self.s.call('read_replies', self.a['agent_token'], {})['replies']
        self.assertEqual({r['id']: r['route_state'] for r in reads}, {old_reply['id']: 'historical', new_reply['id']: 'current'})
        self.s.messages.resolve_request(self.a['agent_token'], current['request']['id'], current['request']['context_version'])
        closed = self.ask()
        self.assertEqual(closed['status'], 'closed')
        self.assertEqual(closed['request']['owner_route_state'], 'closed')
        self.change('force_handoff', target_member_id=self.b['member_id'])
        self.assertEqual(self.ask()['status'], 'closed', 'a resolved question must not reopen implicitly')
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 2)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0], 1)

    def test_release_cancel_reopen_and_same_owner_new_epoch_invalidate_previous_routes(self):
        first = self.ask()
        self.change('release_task')
        self.assertEqual(self.ask()['status'], 'unassigned')
        self.s.tasks.claim_task(self.b['agent_token'], self.target['id'], 'second')
        second = self.ask()
        self.assertNotEqual(second['request']['id'], first['request']['id'])
        self.change('cancel_task')
        self.assertEqual(self.ask()['status'], 'target_cancelled')
        self.assertIsNone(self.ask()['request'])
        self.change('reopen_task')
        self.assertEqual(self.ask()['status'], 'unassigned')
        self.s.tasks.claim_task(self.c['agent_token'], self.target['id'], 'third')
        third = self.ask()
        self.assertGreater(third['route_version'], second['route_version'])
        self.assertEqual(third['request']['receiver_member_id'], self.c['member_id'])

    def test_fixed_member_messages_do_not_follow_task_responsibility(self):
        direct = self.s.messages.send_request(self.a['agent_token'], 'fixed', self.b['member_id'],
                                               self.target['id'], 1, 'Named person question')
        following = self.ask()
        self.change('force_handoff', target_member_id=self.c['member_id'])
        self.s.messages.reply(self.b['agent_token'], direct['id'], 'fixed-answer', 1, 'Personal answer')
        self.s.messages.resolve_request(self.a['agent_token'], direct['id'], 1)
        records = self.s.messages.list_requests(self.a['agent_token'])
        fixed = next(r for r in records if r['id'] == direct['id'])
        self.assertEqual(fixed['receiver_member_id'], self.b['member_id'])
        self.assertIsNone(fixed.get('owner_route_state'))
        self.assertNotEqual(self.ask()['request']['id'], following['request']['id'])

    def test_retry_keeps_selected_task_and_rejects_changed_payload_after_scope_changes(self):
        first = self.ask(target_task_id=None, scope='src/api')
        self.task('api/nested')
        self.change('force_handoff', target_member_id=self.c['member_id'])
        retry = self.ask(target_task_id=None, scope='src/api')
        self.assertEqual(retry['target']['id'], self.target['id'])
        self.assertNotEqual(retry['request']['id'], first['request']['id'])
        with self.assertRaises(Conflict):
            self.ask(target_task_id=None, scope='src/api', context='changed')
        self.assertEqual(self.ask(request_key='new', target_task_id=None, scope='src/api')['status'], 'ambiguous')

    def test_helpers_and_tables_exist_for_identity_store_without_workflow_store(self):
        self.assertTrue(callable(getattr(workflow, 'request_route_info', None)))
        self.assertTrue(callable(getattr(workflow, 'live_owner_route_sql', None)))
        bare = IdentityStore(self.path.with_name('bare-' + uuid4().hex + '.sqlite3'))
        with bare.db.connect() as db:
            self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='workflow_owner_routes'").fetchone())
            self.assertIsNone(workflow.request_route_info(db, 99))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests r WHERE ' + workflow.live_owner_route_sql()).fetchone()[0], 0)
        first = self.ask()
        self.change('force_handoff', target_member_id=self.c['member_id'])
        current = self.ask()
        with self.s.identity.db.connect() as db:
            old = workflow.request_route_info(db, first['request']['id'])
            self.assertEqual(old['state'], 'historical')
            self.assertFalse(old['current'])
            self.assertEqual(old['current_request_id'], current['request']['id'])
            ids = [r[0] for r in db.execute('SELECT r.id FROM message_requests r WHERE ' + workflow.live_owner_route_sql())]
            self.assertEqual(ids, [current['request']['id']])

    def test_routing_failure_rolls_back_claim_and_question_atomically(self):
        target = self.task('queued')
        self.ask(target_task_id=target['id'])
        self.assertTrue(callable(getattr(workflow, '_route_owner_question', None)))
        with patch('coopagents.workflow._route_owner_question', side_effect=RuntimeError('synthetic route failure')):
            with self.assertRaises(RuntimeError):
                self.s.tasks.claim_task(self.b['agent_token'], target['id'], 'claim')
        with self.s.identity.db.connect() as db:
            self.assertIsNone(db.execute('SELECT owner_member_id FROM tasks WHERE id=?', (target['id'],)).fetchone()[0])
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 0)

    def test_concurrent_claims_create_one_current_route(self):
        target = self.task('concurrent')
        self.ask(target_task_id=target['id'])
        def claim(person):
            try:
                return self.s.tasks.claim_task(person['agent_token'], target['id'], uuid4().hex)['owner_member_id']
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = [owner for owner in pool.map(claim, (self.b, self.c)) if owner]
        self.assertEqual(len(winners), 1)
        result = self.ask(target_task_id=target['id'])
        self.assertIsNotNone(result['request'])
        self.assertEqual(result['request']['receiver_member_id'], winners[0])
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 1)

    def test_legacy_question_migration_keeps_original_request_and_routes_to_current_owner(self):
        self.assertTrue(callable(getattr(workflow, 'initialize', None)))
        path = self.path.with_name('legacy-owner-' + uuid4().hex + '.sqlite3')
        with patch('coopagents.workflow.initialize'):
            identity = IdentityStore(path)
        a = identity.create_room('Legacy', 'Requester')
        b = identity.add_member(a['web_token'], 'Old owner')
        c = identity.add_member(a['web_token'], 'Current owner')
        values = [None, 'src/legacy', None, None, 'Question', '', None, None]
        digest = hashlib.sha256(json.dumps(values, ensure_ascii=True).encode()).hexdigest()
        with identity.db.connect(write=True) as db:
            task_id = db.execute('''INSERT INTO tasks(room_id,intent_key,title,scope,state,owner_member_id,created_at,
                creator_member_id,revision,ownership_epoch,epoch_started_at,claimed_at) VALUES(?,?,?,?,'claimed',?,?,?,2,2,?,?)''',
                (a['room_id'], 'legacy', 'Legacy', 'src/legacy', c['member_id'], '2000-01-01', a['member_id'],
                 '2003-01-01', '2000-01-01')).lastrowid
            request_id = db.execute('''INSERT INTO message_requests(room_id,sender_member_id,receiver_member_id,
                initial_receiver_member_id,task_id,context_version,body,request_key,created_at) VALUES(?,?,?,?,?,1,?,?,?)''',
                (a['room_id'], a['member_id'], b['member_id'], b['member_id'], task_id,
                 'Question', 'legacy-domain-key', '2001-01-01')).lastrowid
            db.execute('INSERT INTO message_deliveries(request_id,room_id,receiver_member_id) VALUES(?,?,?)',
                       (request_id, a['room_id'], b['member_id']))
            db.execute('''CREATE TABLE workflow_questions(room_id TEXT,member_id TEXT,request_key TEXT,
                payload_hash TEXT,target_task_id INTEGER,initial_owner TEXT,initial_revision INTEGER,
                dependency_id INTEGER,request_id INTEGER,created_at TEXT,PRIMARY KEY(room_id,member_id,request_key))''')
            db.execute('INSERT INTO workflow_questions VALUES(?,?,?,?,?,?,?,NULL,?,?)',
                       (a['room_id'], a['member_id'], 'question', digest, task_id, b['member_id'], 1, request_id, '2001-01-01'))
        upgraded = CoordinationService(path)
        result = upgraded.call('ask_owner', a['agent_token'], {'request_key': 'question', 'body': 'Question', 'scope': 'src/legacy'})
        self.assertNotEqual(result['request']['id'], request_id)
        self.assertEqual(result['request']['receiver_member_id'], c['member_id'])
        with upgraded.identity.db.connect() as db:
            self.assertEqual(workflow.request_route_info(db, request_id)['state'], 'historical')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 2)
        reopened = CoordinationService(path)
        with reopened.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_requests').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
