"""Real shared-domain workflows; these are not native or two-user acceptance."""
import json
from pathlib import Path
import unittest
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound


class TeamWorkflowScenarioTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('workflow-scenario-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.frontend = self.s.identity.create_room('Workflow scenario', 'Frontend member')
        self.backend = self.s.identity.add_member(self.frontend['web_token'], 'Backend member')
        self.front = self.task(self.frontend, 'frontend', 'src/ui')
        self.back = self.task(self.backend, 'backend', 'src/api')
        self.front_auth = dict(session_key='frontend', ownership_epoch=self.front['ownership_epoch'])
        self.back_auth = dict(session_key='backend', ownership_epoch=self.back['ownership_epoch'])

    def task(self, person, key, scope, claim=True):
        task = self.s.tasks.create_task(person['web_token'], key, key, scope)
        return self.s.tasks.claim_task(person['agent_token'], task['id'], key) if claim else task

    def call(self, operation, person=None, kind='agent', **data):
        return self.s.call(operation, (person or self.frontend)[kind + '_token'], data)

    def workflow(self, person=None, **data):
        return self.call('read_workflow', person, **data)

    def ask_dependency(self, **extra):
        data = dict(request_key='frontend-needs-pagination', body='Which pagination field is required?',
            scope='src/api', source_task_id=self.front['id'], expected_revision=self.front['revision'],
            context='The frontend must implement the current interface.', **self.front_auth)
        data.update(extra)
        return self.call('ask_owner', **data)

    def test_offline_recovery_explicit_answer_use_agreement_change_and_human_handoff(self):
        question = self.ask_dependency()
        dep = question['dependency']
        pending = self.workflow(task_id=self.front['id'])['requests'][0]
        self.assertEqual(pending['wait_reason'], 'awaiting_recipient_read')
        self.assertTrue(pending['delivered'])
        self.assertFalse(pending['replied'])

        # No backend activity is performed while it is "offline". A new service
        # instance recovers the same durable execution; no model turn is implied.
        brief = self.call('work_brief', task_id=self.front['id'], limit=50, **self.front_auth)
        self.s = CoordinationService(self.path)
        recovered = self.workflow(self.backend, task_id=self.back['id'])['requests'][0]
        self.assertEqual(recovered['id'], question['request']['id'])
        self.assertFalse(recovered['replied'])
        self.call('read_inbox', self.backend)
        self.call('acknowledge', self.backend, request_id=recovered['id'])
        answered = self.call('reply_dependency', self.backend, dependency_id=dep['id'],
            expected_revision=dep['revision'], request_key='backend-pagination-answer',
            body='Use next_cursor as an optional string.', evidence='Protocol fixture: src/api pagination schema',
            **self.back_auth)
        changed = self.call('work_brief', task_id=self.front['id'], limit=50,
            after_cursor=brief['cursor'], **self.front_auth)
        self.assertEqual(changed['reset_reason'], 'content_changed')
        self.assertFalse(changed['delta'])

        replies = self.call('read_replies', task_id=self.front['id'])
        reply = replies['replies'][0]
        self.assertEqual(reply['id'], answered['latest_reply']['id'])
        self.assertEqual(reply['route_state'], 'current')
        with self.assertRaises(Conflict):
            self.call('resolve_dependency', dependency_id=dep['id'], expected_revision=answered['revision'],
                reply_id=reply['id'], request_key='too-early', summary='Explicit reply read is insufficient',
                **self.front_auth)
        projected = self.workflow(task_id=self.front['id'])
        self.assertFalse(projected['requests'][0]['dependency_satisfied'])
        self.assertTrue(projected['onboarding']['two_member_exchange_complete'])
        self.assertFalse(projected['model_consumption_proven'])
        read = self.call('read_dependency', dependency_id=dep['id'], **self.front_auth)
        self.assertTrue(read['read_recorded'])
        closed = self.call('resolve_dependency', dependency_id=dep['id'], expected_revision=read['revision'],
            reply_id=read['latest_reply']['id'], request_key='accept-pagination-answer',
            summary='Frontend will use the returned next_cursor field.', **self.front_auth)
        self.assertEqual(closed['status'], 'satisfied')
        self.call('report_progress', task_id=self.front['id'], state='working',
            summary='Implementing the agreed next_cursor field.', **self.front_auth)

        contract = self.call('propose_contract', self.backend, contract_key='pagination', expected_version=0,
            title='Pagination', body='next_cursor is an optional string.', source_request_id=question['request']['id'])
        self.call('decision', kind='web', contract_id=contract['id'], version=1, decision='approved')
        first = self.call('record_agreement_use', task_id=self.front['id'], contract_id=contract['id'],
            version=1, **self.front_auth)
        self.assertFalse(first['review_required'])
        self.call('propose_contract', self.backend, contract_key='pagination', expected_version=1,
            title='Pagination v2', body='next_cursor is a nullable string.', source_request_id=question['request']['id'])
        draft = self.workflow(task_id=self.front['id'])
        self.assertEqual(draft['agreement_changes'][0]['effective_version'], 1)
        self.assertFalse(draft['agreement_changes'][0]['review_required'])
        self.call('decision', kind='web', contract_id=contract['id'], version=2, decision='approved')
        approved = self.workflow(task_id=self.front['id'])
        self.assertTrue(approved['agreement_changes'][0]['review_required'])
        self.assertTrue(any(c['kind'] == 'agreement_review' for c in approved['decisions']))
        adopted = self.call('record_agreement_use', task_id=self.front['id'], contract_id=contract['id'],
            version=2, **self.front_auth)
        self.assertFalse(adopted['review_required'])

        proposed = self.call('propose_handoff', task_id=self.front['id'], expected_revision=self.front['revision'],
            request_key='handoff-for-review', summary='Backend member will continue integration.',
            target_member_id=self.backend['member_id'], **self.front_auth)
        card = next(c for c in self.call('read_workflow', self.backend, kind='web',
            task_id=self.front['id'])['decisions'] if c['kind'] == 'handoff')
        self.assertTrue(card['eligible'])
        self.assertEqual(card['authority'], 'proposed_recipient_web_user')
        with self.assertRaises(AccessDenied):
            self.call('accept_handoff', self.backend, task_id=self.front['id'],
                expected_revision=proposed['revision'], request_key='agent-cannot-accept', summary='Attempted accept')
        self.assertTrue(any(c['kind'] == 'handoff' for c in self.call('read_workflow', self.backend,
            kind='web', task_id=self.front['id'])['decisions']))

    def test_ambiguity_queued_dependency_and_fixed_recipient_have_distinct_routing(self):
        third = self.s.identity.add_member(self.frontend['web_token'], 'Documentation member')
        self.task(third, 'nested-api', 'src/api/auth')
        ambiguous = self.ask_dependency(scope='src/api/auth')
        self.assertEqual(ambiguous['status'], 'ambiguous')
        self.assertEqual(len(ambiguous['candidates']), 2)
        self.assertIsNone(ambiguous['request'])
        self.assertEqual(self.s.messages.list_requests(self.frontend['agent_token']), [])
        unassigned = self.task(third, 'unassigned', 'src/jobs', claim=False)
        queued = self.ask_dependency(scope='src/jobs')
        self.assertEqual(queued['status'], 'unassigned')
        self.assertIsNone(queued['request'])
        self.assertEqual(self.workflow()['requests'], [])
        self.s.tasks.claim_task(third['agent_token'], unassigned['id'], 'unassigned')
        routed = self.ask_dependency(scope='src/jobs')
        self.assertEqual(routed['dependency']['id'], queued['dependency']['id'])
        self.assertEqual(routed['request']['receiver_member_id'], third['member_id'])

        ordinary = self.call('ask_owner', request_key='fixed-api-question', body='Which logging format?',
            target_task_id=self.back['id'])
        moved = self.call('force_handoff', kind='web', task_id=self.back['id'],
            expected_revision=self.back['revision'], request_key='transfer-api', summary='Responsibility changed',
            target_member_id=third['member_id'])
        self.assertEqual(moved['owner_member_id'], third['member_id'])
        retry = self.call('ask_owner', request_key='fixed-api-question', body='Which logging format?',
            target_task_id=self.back['id'])
        self.assertEqual(retry['routing'], 'fixed_recipient')
        self.assertTrue(retry['target_changed'])
        self.assertEqual(retry['request']['receiver_member_id'], self.backend['member_id'])

    def test_room_isolation_and_peeks_do_not_manufacture_read_evidence(self):
        local = self.ask_dependency()
        foreign = self.s.identity.create_room('Other room', 'Foreign member')
        foreign_task = self.task(foreign, 'foreign-secret-task-marker', 'src/api')
        request = self.s.messages.send_request(foreign['agent_token'], 'foreign-question',
            foreign['member_id'], foreign_task['id'], 1, 'foreign-secret-question-marker')
        self.s.messages.reply(foreign['agent_token'], request['id'], 'foreign-answer', 1,
            'foreign-secret-answer-marker')
        state = self.workflow()
        self.assertNotIn('foreign-secret', json.dumps(state))
        self.assertEqual(self.call('read_replies')['replies'], [])
        self.call('work_brief', task_id=self.front['id'], **self.front_auth)
        self.s.snapshot(self.frontend['agent_token'], web=False)
        with self.s.identity.db.connect() as db:
            for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table + ' WHERE ' +
                    ('dependency_id=?' if table == 'dependency_reads' else 'room_id=?'),
                    (local['dependency']['id'] if table == 'dependency_reads' else self.frontend['room_id'],)).fetchone()[0], 0)
        with self.assertRaises(NotFound):
            self.call('read_workflow', task_id=foreign_task['id'])
        with self.assertRaises(NotFound):
            self.call('read_replies', task_id=foreign_task['id'])
        with self.assertRaises(NotFound):
            self.call('ask_owner', request_key='cross-room', body='Do not deliver', target_task_id=foreign_task['id'])


if __name__ == '__main__':
    unittest.main()
