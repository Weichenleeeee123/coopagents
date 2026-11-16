"""Responsibility questions and explicit reply reads; evidence is retained."""
from pathlib import Path
import unittest
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('workflow-' + str(uuid4()) + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Frontend')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        self.c = self.s.identity.add_member(self.a['web_token'], 'QA')
        self.source = self.task(self.a, 'frontend', 'src/ui')
        self.target = self.task(self.b, 'backend', 'src/api')
        self.auth = dict(session_key='frontend', ownership_epoch=self.source['ownership_epoch'])
        self.target_auth = dict(session_key='backend', ownership_epoch=self.target['ownership_epoch'])

    def task(self, member, key, scope, claim=True):
        task = self.s.tasks.create_task(member['web_token'], key, key, scope)
        return self.s.tasks.claim_task(member['agent_token'], task['id'], key) if claim else task

    def ask(self, **extra):
        self.assertIn('ask_owner', self.s.operations, 'owner question operation is missing')
        data = dict(request_key='question', body='Which pagination fields?', scope='src/api')
        data.update(extra)
        return self.s.call('ask_owner', self.a['agent_token'], data)

    def task_ask(self, **extra):
        data = dict(source_task_id=self.source['id'], expected_revision=self.source['revision'], **self.auth)
        data.update(extra)
        return self.ask(**data)

    def transfer(self, task, member):
        current = next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id'] == task['id'])
        return self.s.call('force_handoff', self.a['web_token'], dict(task_id=task['id'],
            expected_revision=current['revision'], request_key=str(uuid4()), summary='Responsibility changed',
            target_member_id=member['member_id']))

    def test_member_question_routes_to_unique_declared_owner_and_retries(self):
        result = self.ask(context='Need this for the frontend')
        self.assertEqual(result['status'], 'delivered')
        self.assertEqual(result['request']['receiver_member_id'], self.b['member_id'])
        self.assertEqual(result['target']['id'], self.target['id'])
        self.assertEqual(self.ask(context='Need this for the frontend')['request']['id'], result['request']['id'])
        with self.assertRaises(Conflict):
            self.ask(body='Different question')
        self.transfer(self.target, self.c)
        retry = self.ask(context='Need this for the frontend')
        self.assertEqual(retry['request']['id'], result['request']['id'])
        self.assertTrue(retry['target_changed'])
        self.assertEqual(len(self.s.messages.list_requests(self.a['agent_token'])), 1)

    def test_ambiguous_not_found_and_unassigned_do_not_send_unaddressed_messages(self):
        self.assertEqual(self.ask(scope='missing')['status'], 'not_found')
        self.task(self.c, 'nested', 'src/api/auth')
        self.assertEqual(self.ask(scope='src/api/auth')['status'], 'ambiguous')
        unowned = self.task(self.c, 'unowned', 'unowned', False)
        self.assertEqual(self.ask(scope=None, target_task_id=unowned['id'])['status'], 'unassigned')
        self.assertEqual(self.s.messages.list_requests(self.a['agent_token']), [])

    def test_task_question_reuses_dependency_and_tracks_current_owner_on_retry(self):
        first = self.task_ask()
        dep = first['dependency']
        self.assertEqual(first['status'], 'delivered')
        self.assertEqual(dep['source_task_id'], self.source['id'])
        self.transfer(self.target, self.c)
        retry = self.task_ask()
        self.assertEqual(retry['dependency']['id'], dep['id'])
        self.assertNotEqual(retry['dependency']['current_request_id'], dep['current_request_id'])
        self.assertEqual(retry['request']['receiver_member_id'], self.c['member_id'])

    def test_unique_unassigned_task_dependency_waits_and_routes_after_claim(self):
        unowned = self.task(self.c, 'unowned', 'unowned', False)
        queued = self.task_ask(scope=None, target_task_id=unowned['id'])
        self.assertEqual(queued['status'], 'unassigned')
        self.assertIsNone(queued['request'])
        self.s.tasks.claim_task(self.c['agent_token'], unowned['id'], 'unowned')
        resumed = self.task_ask(scope=None, target_task_id=unowned['id'])
        self.assertEqual(resumed['status'], 'delivered')
        self.assertEqual(resumed['request']['receiver_member_id'], self.c['member_id'])

    def test_selector_limits_source_revision_and_authority_are_explicit(self):
        for data in (dict(target_task_id=self.target['id']), dict(scope=None), dict(body='x'*501),
                     dict(context='x'*3001), dict(session_key='unused'), dict(expected_revision=0)):
            with self.subTest(data=list(data)):
                with self.assertRaises(ValidationError):
                    self.ask(**data)
        with self.assertRaises(ValidationError):
            self.ask(source_task_id=self.source['id'], **self.auth)
        with self.assertRaises((Conflict, AccessDenied)):
            self.task_ask(session_key='wrong')
        other = self.s.identity.create_room('Other', 'Other')
        foreign = self.task(other, 'foreign', 'foreign')
        with self.assertRaises(NotFound):
            self.ask(scope=None, target_task_id=foreign['id'])
        with self.assertRaises(AccessDenied):
            self.s.call('ask_owner', self.a['web_token'], dict(request_key='x', body='Q', scope='src/api'))

    def test_replies_are_sender_scoped_paginated_and_record_exact_reads_only(self):
        request = self.ask()['request']
        replies = [self.s.messages.reply(self.b['agent_token'], request['id'], str(i), 1, 'Answer '+str(i))['replies'][-1] for i in range(3)]
        result = self.s.call('read_replies', self.a['agent_token'], dict(limit=2))
        self.assertEqual([r['id'] for r in result['replies']], [r['id'] for r in replies[:2]])
        self.assertTrue(result['has_more'])
        self.assertFalse(result['model_consumption_proven'])
        second = self.s.call('read_replies', self.a['agent_token'], dict(after_id=result['next_cursor']))
        self.assertEqual([r['id'] for r in second['replies']], [replies[2]['id']])
        self.assertEqual(self.s.call('read_replies', self.c['agent_token'], {})['replies'], [])
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM workflow_reply_reads').fetchone()[0], 3)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT resolved_at FROM message_requests').fetchone()[0])

    def test_historical_dependency_reply_read_does_not_confirm_current_dependency(self):
        dep = self.task_ask()['dependency']
        answered = self.s.call('reply_dependency', self.b['agent_token'], dict(dependency_id=dep['id'],
            expected_revision=dep['revision'], request_key='answer', body='cursor:string', **self.target_auth))
        page = self.s.call('read_replies', self.a['agent_token'], {})
        self.assertEqual(page['replies'][0]['dependency_id'], dep['id'])
        self.assertEqual(page['replies'][0]['route_state'], 'current')
        with self.assertRaises(Conflict):
            self.s.call('resolve_dependency', self.a['agent_token'], dict(dependency_id=dep['id'],
                expected_revision=answered['revision'], reply_id=answered['latest_reply']['id'],
                request_key='confirm', summary='Enough', **self.auth))
        self.transfer(self.target, self.c)
        page = self.s.call('read_replies', self.a['agent_token'], {})
        self.assertEqual(page['replies'][0]['route_state'], 'historical')
        reopened = CoordinationService(self.path)
        page = reopened.call('read_replies', self.a['agent_token'], {})
        self.assertIsNotNone(page['replies'][0]['read_at'])

    def test_reply_cursor_validation_and_foreign_task(self):
        self.ask()
        for data in (dict(after_id=-1), dict(after_id=True), dict(limit=0), dict(limit=51)):
            with self.assertRaises(ValidationError):
                self.s.call('read_replies', self.a['agent_token'], data)
        other = self.s.identity.create_room('Other', 'Other')
        task = self.task(other, 'other', 'other')
        with self.assertRaises(NotFound):
            self.s.call('read_replies', self.a['agent_token'], dict(task_id=task['id']))

    def test_sent_reply_reader_includes_same_member_requests_and_task_dependencies(self):
        request = self.s.messages.send_request(self.a['agent_token'], 'self', self.a['member_id'],
            None, 1, 'Question for another of my sessions')
        self.s.messages.reply(self.a['agent_token'], request['id'], 'self-answer', 1, 'Known answer')
        self.assertIn('read_replies', self.s.operations)
        first = self.s.call('read_replies', self.a['agent_token'], {})
        self.assertEqual(first['replies'][0]['body'], 'Known answer')
        changed = self.transfer(self.target, self.a)
        claimed = self.s.tasks.claim_task(self.a['agent_token'], changed['id'], 'backend-self')
        dep = self.task_ask()['dependency']
        self.s.call('reply_dependency', self.a['agent_token'], dict(dependency_id=dep['id'],
            expected_revision=dep['revision'], request_key='same-member-answer', body='Shared schema',
            session_key='backend-self', ownership_epoch=claimed['ownership_epoch']))
        page = self.s.call('read_replies', self.a['agent_token'], dict(after_id=first['next_cursor']))
        self.assertEqual(page['replies'][0]['body'], 'Shared schema')
