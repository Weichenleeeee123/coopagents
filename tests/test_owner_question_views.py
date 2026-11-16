"""Owner-question route facts in read-only domain views; retained SQLite data."""
from pathlib import Path
import json
import unittest
from uuid import uuid4

from coopagents.coordination import CoordinationService


class OwnerQuestionViewTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('owner-question-views-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Requester')
        self.b = self.s.identity.add_member(self.a['web_token'], 'First owner')
        self.c = self.s.identity.add_member(self.a['web_token'], 'Current owner')
        self.target = self.task('backend', self.b)

    def task(self, name, member, claim=True):
        task = self.s.tasks.create_task(self.a['web_token'], name, name, 'src/' + name)
        return self.s.tasks.claim_task(member['agent_token'], task['id'], name) if claim else task

    def ask(self, key='question', task=None):
        return self.s.call('ask_owner', self.a['agent_token'], {
            'request_key': key, 'body': 'Which backend field?', 'target_task_id': (task or self.target)['id']})

    def transfer(self):
        current = next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id'] == self.target['id'])
        return self.s.call('force_handoff', self.a['web_token'], dict(task_id=current['id'],
            expected_revision=current['revision'], request_key=str(uuid4()), summary='Changed responsibility',
            target_member_id=self.c['member_id']))

    def checkpoint(self, member=None):
        return self.s.call('checkpoint', (member or self.a)['agent_token'],
            dict(session_key='view-check', tool='codex-cli', event='manual'))['brief']

    def wake(self, member=None):
        return self.s.call('wake_digest', (member or self.a)['agent_token'], {})

    def workflow(self, member=None, **data):
        return self.s.call('read_workflow', (member or self.a)['agent_token'], data)

    def message_facts(self):
        with self.s.identity.db.connect() as db:
            return {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                    for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads')} | {
                        'resolved': db.execute('SELECT COUNT(*) FROM message_requests WHERE resolved_at IS NOT NULL').fetchone()[0]}

    def test_old_owner_delivery_leaves_wake_and_checkpoint_but_history_remains_visible(self):
        first = self.ask()['request']
        self.assertIn(first['id'], [item['request_id'] for item in self.wake(self.b)['items']])
        self.transfer()
        current = self.ask()['request']
        self.assertNotEqual(first['id'], current['id'])
        before = self.message_facts()
        self.assertEqual(self.wake(self.b)['counts']['request'], 0)
        self.assertIn(current['id'], [item['request_id'] for item in self.wake(self.c)['items']])
        self.assertEqual(self.checkpoint(self.b)['requests'], [])
        self.assertEqual([r['id'] for r in self.checkpoint()['requests']], [current['id']])
        projection = {r['id']: r for r in self.workflow()['requests']}
        self.assertEqual(projection[first['id']]['route_state'], 'historical')
        self.assertEqual(projection[first['id']]['wait_reason'], 'historical_route')
        self.assertEqual(projection[first['id']]['next_actions'], [])
        self.assertEqual(projection[current['id']]['route_state'], 'current')
        self.assertIsNone(projection[current['id']]['dependency_id'])
        self.assertEqual(self.message_facts(), before)

    def test_historical_reply_is_not_a_current_wake_item_or_current_onboarding_exchange(self):
        first = self.ask()['request']
        reply = self.s.messages.reply(self.b['agent_token'], first['id'], 'answer', first['context_version'], 'Use old_field')['replies'][-1]
        self.assertIn(reply['id'], [item['id'] for item in self.wake()['items'] if item['kind'] == 'reply'])
        self.transfer()
        current = self.ask()['request']
        before = self.message_facts()
        self.assertEqual(self.wake()['counts']['reply'], 0)
        projection = self.workflow()
        old = next(r for r in projection['requests'] if r['id'] == first['id'])
        self.assertTrue(old['replied'])
        self.assertEqual(old['route_state'], 'historical')
        self.assertEqual(old['next_actions'], [])
        self.assertEqual(projection['onboarding']['addressed_exchange']['request_id'], current['id'])
        self.assertFalse(projection['onboarding']['two_member_exchange_complete'])
        self.assertFalse(self.checkpoint()['requests'][0]['replies'])
        self.assertEqual(self.message_facts(), before)

    def test_queued_question_is_explicit_without_fake_delivery_then_claim_routes_it(self):
        target = self.task('unassigned', self.c, claim=False)
        self.assertIsNone(self.ask('queued', target)['request'])
        before = self.message_facts()
        self.assertEqual(self.wake()['items'], [])
        self.assertEqual(self.wake(self.b)['items'], [])
        queue = self.workflow()['owner_questions']
        self.assertEqual(len(queue), 1)
        self.assertEqual(queue[0]['question_key'], 'queued')
        self.assertEqual(queue[0]['target_task_id'], target['id'])
        self.assertEqual(queue[0]['status'], 'queued')
        self.assertEqual(queue[0]['wait_reason'], 'awaiting_owner')
        self.assertIsNone(queue[0]['current_request_id'])
        self.assertEqual(self.checkpoint()['owner_questions'][0]['wait_reason'], 'awaiting_owner')
        self.assertEqual(self.message_facts(), before)
        self.s.tasks.claim_task(self.c['agent_token'], target['id'], 'new-owner')
        current = self.ask('queued', target)['request']
        self.assertEqual(current['receiver_member_id'], self.c['member_id'])
        self.assertEqual(self.workflow()['owner_questions'], [])
        self.assertIn(current['id'], [item['request_id'] for item in self.wake(self.c)['items']])
        self.assertEqual(next(r for r in self.workflow()['requests'] if r['id'] == current['id'])['route_state'], 'current')

    def test_explicit_member_question_does_not_follow_its_associated_task_owner(self):
        direct = self.s.messages.send_request(self.a['agent_token'], 'direct', self.b['member_id'],
            self.target['id'], 1, 'A question explicitly for you')
        reply = self.s.messages.reply(self.b['agent_token'], direct['id'], 'direct-answer', 1, 'Personal answer')['replies'][-1]
        self.transfer()
        before = self.message_facts()
        self.assertIn(direct['id'], [r['request_id'] for r in self.wake(self.b)['items']])
        self.assertEqual(self.wake(self.c)['counts']['request'], 0)
        self.assertIn(reply['id'], [r['id'] for r in self.wake()['items'] if r['kind'] == 'reply'])
        self.assertEqual(self.checkpoint()['requests'][0]['id'], direct['id'])
        self.assertEqual(self.workflow()['requests'][0]['route_state'], 'ordinary')
        self.assertEqual(self.message_facts(), before)

    def test_retired_questions_are_filtered_before_pending_limits(self):
        old = {self.ask('q-' + str(i))['request']['id'] for i in range(8)}
        self.transfer()
        before = self.message_facts()
        self.assertEqual(self.checkpoint(self.b)['requests'], [])
        current = self.checkpoint()['requests']
        self.assertTrue(current)
        self.assertTrue(old.isdisjoint({r['id'] for r in current}))
        self.assertEqual(self.wake(self.b)['counts']['request'], 0)
        self.assertEqual(self.message_facts(), before)

    def test_queue_is_durable_room_scoped_and_subject_to_brief_budget(self):
        target = self.task('waiting', self.c, claim=False)
        self.ask('private-queue', target)
        self.s = CoordinationService(self.path)
        other = self.s.identity.create_room('Other', 'Other')
        self.assertEqual(self.workflow(other)['owner_questions'], [])
        self.assertEqual(self.checkpoint(other)['owner_questions'], [])
        self.assertEqual(self.workflow()['owner_questions'][0]['question_key'], 'private-queue')
        self.assertEqual(self.s.call('work_brief', self.a['agent_token'], {})['totals']['owner_question'], 1)

    def test_queued_questions_obey_checkpoint_and_work_brief_bounds_without_receipts(self):
        target = self.task('bounded-queue', self.c, claim=False)
        expected = {'queued-' + str(i) for i in range(8)}
        for key in sorted(expected):
            self.s.call('ask_owner', self.a['agent_token'], dict(request_key=key, body='Q' * 500,
                context='x' * 3000, target_task_id=target['id']))
        before = self.message_facts()
        checkpoint = self.checkpoint()
        self.assertEqual(len(checkpoint['owner_questions']), 6)
        self.assertTrue(checkpoint['truncated'])
        self.assertLessEqual(len(json.dumps(checkpoint, ensure_ascii=False).encode()), 16000)
        seen, cursor = [], None
        for _ in range(30):
            page = self.s.call('work_brief', self.a['agent_token'], {'limit': 2, 'after_cursor': cursor})
            self.assertLessEqual(len(json.dumps(page, sort_keys=True).encode()), 16000)
            self.assertEqual(page['totals']['owner_question'], 8)
            seen.extend(item['question_key'] for item in page['items'] if item['kind'] == 'owner_question')
            if not page['has_more']:
                break
            cursor = page['next_cursor']
        else:
            self.fail('Queued question pagination did not complete')
        self.assertEqual(set(seen), expected)
        self.assertEqual(len(seen), 8)
        self.assertEqual(self.wake()['items'], [])
        self.assertEqual(self.message_facts(), before)

    def test_cancelled_target_is_not_live_and_exposes_a_blocked_owner_question(self):
        first = self.ask()['request']
        current = next(t for t in self.s.tasks.list_tasks(self.a['web_token']) if t['id'] == self.target['id'])
        self.s.call('cancel_task', self.a['web_token'], dict(task_id=current['id'],
            expected_revision=current['revision'], request_key='cancel', summary='Target retired'))
        before = self.message_facts()
        self.assertEqual(self.wake(self.b)['counts']['request'], 0)
        self.assertEqual(self.checkpoint()['requests'], [])
        queue = self.workflow()['owner_questions']
        self.assertEqual(queue[0]['status'], 'blocked')
        self.assertEqual(queue[0]['wait_reason'], 'target_cancelled')
        old = next(r for r in self.workflow()['requests'] if r['id'] == first['id'])
        self.assertIn(old['route_state'], ('historical', 'closed'))
        self.assertEqual(old['next_actions'], [])
        self.assertEqual(self.message_facts(), before)


if __name__ == '__main__':
    unittest.main()
