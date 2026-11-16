"""Task-focused read snapshots, conservative recovery and decision projections."""
import base64
from contextlib import contextmanager
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError


class TeamWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('team-workflow-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Frontend')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        self.c = self.s.identity.add_member(self.a['web_token'], 'QA')
        self.front = self.task(self.a, 'frontend')
        self.back = self.task(self.b, 'backend')
        self.unrelated = self.task(self.a, 'unrelated')
        self.auth = dict(task_id=self.front['id'], session_key='frontend',
                         ownership_epoch=self.front['ownership_epoch'])

    def task(self, person, name, claim=True):
        task = self.s.tasks.create_task(person['web_token'], name, name, 'src/' + name)
        return self.s.tasks.claim_task(person['agent_token'], task['id'], name) if claim else task

    def brief(self, person=None, **data):
        self.assertTrue('work_brief' in self.s.operations, 'task-focused brief operation is missing')
        return self.s.call('work_brief', (person or self.a)['agent_token'], data)

    def workflow(self, person=None, kind='agent', **data):
        self.assertTrue('read_workflow' in self.s.operations, 'read-only workflow operation is missing')
        return self.s.call('read_workflow', (person or self.a)[kind + '_token'], data)

    def dependency(self):
        return self.s.call('ask_owner', self.a['agent_token'], dict(request_key=str(uuid4()),
            body='Which field?', source_task_id=self.front['id'], target_task_id=self.back['id'],
            expected_revision=self.front['revision'], session_key='frontend',
            ownership_epoch=self.front['ownership_epoch']))['dependency']

    def request(self, receiver=None, task_id=None, sender=None, body='Which field?'):
        sender = sender or self.a
        return self.s.messages.send_request(sender['agent_token'], str(uuid4()),
            (receiver or self.b)['member_id'], task_id, 1, body)

    def reply(self, request, person=None, body='Use user_id'):
        return self.s.messages.reply((person or self.b)['agent_token'], request['id'], str(uuid4()),
                                     request['context_version'], body)['replies'][-1]

    def current(self, task):
        return next(t for t in self.s.tasks.list_tasks(self.a['agent_token']) if t['id'] == task['id'])

    def transition(self, operation, task, **extra):
        return self.s.call(operation, self.a['web_token'], dict(task_id=task['id'],
            expected_revision=self.current(task)['revision'], request_key=str(uuid4()), summary='Changed', **extra))

    def test_operations_are_explicit_and_normal_snapshot_has_projection(self):
        self.assertIn('read_workflow', self.s.operations)
        self.assertIn('work_brief', self.s.operations)
        self.assertEqual(self.s.operations['read_workflow'][0], 'any')
        self.assertEqual(self.s.operations['work_brief'][0], 'agent')
        self.assertIn('workflow', self.s.snapshot(self.a['agent_token'], web=False))
        self.assertEqual(self.workflow(kind='web')['source'], 'team_workflow')
        with self.assertRaises(AccessDenied):
            self.s.call('work_brief', self.a['web_token'], {})

    def test_task_focus_excludes_unrelated_tasks_and_includes_direct_dependencies(self):
        dep = self.dependency()
        self.request(task_id=self.unrelated['id'], body='unrelated secret marker')
        result = self.brief(**self.auth)
        tasks = [i['id'] for i in result['items'] if i['kind'] == 'task']
        self.assertIn(self.front['id'], tasks)
        self.assertIn(self.back['id'], tasks)
        self.assertNotIn(self.unrelated['id'], tasks)
        self.assertNotIn('unrelated secret marker', json.dumps(result))
        dependency = next(i for i in result['items'] if i['kind'] == 'dependency')
        self.assertEqual(dependency['id'], dep['id'])
        self.assertEqual(result['execution_target'], self.auth)

    def test_execution_authority_precedes_cursor_fast_path(self):
        first = self.brief(**self.auth)
        for extra in (dict(session_key='wrong'), dict(ownership_epoch=99)):
            data = {**self.auth, **extra, 'after_cursor': first['cursor']}
            with self.assertRaises((AccessDenied, Conflict)):
                self.brief(**data)
        self.transition('force_handoff', self.front, target_member_id=self.b['member_id'])
        with self.assertRaises((AccessDenied, Conflict)):
            self.brief(**self.auth, after_cursor=first['cursor'])

    def test_execution_fields_without_task_and_invalid_limits_are_rejected(self):
        for data in (dict(session_key='loose'), dict(ownership_epoch=1), dict(limit=True),
                     dict(limit=0), dict(limit=51)):
            with self.assertRaises(ValidationError):
                self.brief(**data)
        other = self.s.identity.create_room('Other', 'Other')
        foreign = self.task(other, 'foreign')
        with self.assertRaises(NotFound):
            self.workflow(task_id=foreign['id'])

    def test_cursor_is_stable_bound_and_content_changes_reset_instead_of_fake_delta(self):
        first = self.brief(**self.auth)
        second = self.brief(**self.auth)
        self.assertEqual(first['cursor'], second['cursor'])
        unchanged = self.brief(**self.auth, after_cursor=first['cursor'])
        self.assertTrue(unchanged['unchanged'])
        self.assertEqual(unchanged['items'], [])
        self.assertFalse(unchanged['delta'])
        self.request(task_id=self.front['id'])
        changed = self.brief(**self.auth, after_cursor=first['cursor'])
        self.assertEqual(changed['reset_reason'], 'content_changed')
        self.assertFalse(changed['delta'])
        self.assertTrue(changed['items'])
        self.assertEqual(self.brief(**self.auth, limit=1, after_cursor=changed['cursor'])['reset_reason'], 'scope_changed')
        self.assertEqual(self.brief(after_cursor=changed['cursor'])['reset_reason'], 'scope_changed')
        self.assertEqual(self.brief(self.b, after_cursor=changed['cursor'])['reset_reason'], 'scope_changed')

    def test_bad_future_and_foreign_cursors_reset_safely(self):
        self.assertEqual(self.brief(after_cursor='malformed')['reset_reason'], 'invalid_cursor')
        first = self.brief()
        body = json.loads(base64.urlsafe_b64decode(first['cursor'] + '=' * (-len(first['cursor']) % 4)))
        body['offset'] = 10**9
        future = base64.urlsafe_b64encode(json.dumps(body).encode()).decode().rstrip('=')
        self.assertEqual(self.brief(after_cursor=future)['reset_reason'], 'invalid_cursor')
        other = self.s.identity.create_room('Other', 'Other')
        self.assertEqual(self.brief(other, after_cursor=first['cursor'])['reset_reason'], 'scope_changed')

    def test_byte_budget_and_cursor_continue_every_record_without_skips(self):
        for _ in range(45):
            self.request(task_id=self.front['id'], body='很长的共享消息' * 400)
        seen, cursor = [], None
        for _ in range(100):
            result = self.brief(**self.auth, limit=50, after_cursor=cursor)
            self.assertLessEqual(len(json.dumps(result).encode('utf-8')), 16000)
            self.assertEqual(result['totals']['request'], 45)
            seen += [i['id'] for i in result['items'] if i['kind'] == 'request']
            if not result['has_more']:
                break
            self.assertTrue(result['items'])
            cursor = result['next_cursor']
        self.assertEqual(len(seen), 45)
        self.assertEqual(len(set(seen)), 45)
        self.assertLessEqual(len(json.dumps(self.workflow()).encode('utf-8')), 16000)

    def test_reads_do_not_write_receipts_or_call_recursive_snapshot(self):
        req = self.request(task_id=self.front['id'])
        self.reply(req)
        with patch.object(self.s, 'snapshot', side_effect=AssertionError('recursive snapshot')):
            self.brief(**self.auth)
            self.workflow()
        with self.s.identity.db.connect() as db:
            for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT resolved_at FROM message_requests').fetchone()[0])

    def test_ordinary_lifecycle_and_exact_reply_reads_survive_reopen(self):
        req = self.request(task_id=self.front['id'])
        self.s.messages.read_inbox(self.b['agent_token'])
        self.s.messages.acknowledge(self.b['agent_token'], req['id'])
        reply = self.reply(req)
        before = self.workflow()['requests'][0]
        self.assertTrue(before['delivered'])
        self.assertTrue(before['recipient_read'])
        self.assertTrue(before['processing'])
        self.assertTrue(before['replied'])
        self.assertFalse(before['sender_reply_read'])
        self.s.call('read_replies', self.a['agent_token'], {})
        self.s = CoordinationService(self.path)
        after = self.workflow()['requests'][0]
        self.assertTrue(after['sender_reply_read'])
        self.assertEqual(after['latest_reply_id'], reply['id'])
        self.assertIsNotNone(after['replies'][0]['sender_read_at'])
        self.assertFalse(after['model_comprehension_proven'])

    def test_new_reply_is_not_marked_read_by_receipt_for_previous_reply(self):
        req = self.request(task_id=self.front['id'])
        self.reply(req)
        self.s.call('read_replies', self.a['agent_token'], {})
        self.reply(req, body='Updated answer')
        item = self.workflow()['requests'][0]
        self.assertFalse(item['sender_reply_read'])
        self.assertTrue(item['replies'][0]['sender_read_at'])
        self.assertIsNone(item['replies'][1]['sender_read_at'])

    def test_dependency_recipient_read_is_unknown_and_old_route_is_historical(self):
        dep = self.dependency()
        self.s.call('reply_dependency', self.b['agent_token'], dict(dependency_id=dep['id'],
            expected_revision=dep['revision'], request_key='answer', body='user_id',
            session_key='backend', ownership_epoch=self.back['ownership_epoch']))
        item = self.workflow()['requests'][0]
        self.assertIsNone(item['recipient_read'])
        self.assertTrue(item['replied'])
        self.assertEqual(item['route_state'], 'current')
        self.transition('force_handoff', self.back, target_member_id=self.c['member_id'])
        requests = self.workflow()['requests']
        self.assertEqual({r['route_state'] for r in requests}, {'current', 'historical'})
        historical = next(r for r in requests if r['route_state'] == 'historical')
        self.assertEqual(historical['wait_reason'], 'historical_route')

    def test_onboarding_milestones_use_one_exchange_between_distinct_members(self):
        own = self.request(receiver=self.a)
        self.reply(own, self.a)
        self.s.call('read_replies', self.a['agent_token'], {})
        self.assertFalse(self.workflow()['onboarding']['two_member_exchange_complete'])
        first = self.request()
        self.reply(first)
        second = self.request(receiver=self.c)
        self.reply(second, self.c)
        self.s.call('read_replies', self.a['agent_token'], dict(after_id=0, limit=2))
        onboarding = self.workflow()['onboarding']
        self.assertTrue(onboarding['two_member_exchange_complete'])
        self.assertEqual(onboarding['addressed_exchange']['request_id'], first['id'])
        self.assertFalse(onboarding['model_comprehension_proven'])

    def test_unrelated_exchange_receipts_cannot_complete_another_milestone(self):
        req = self.request()
        self.reply(req)
        self.s.call('read_replies', self.a['agent_token'], {})
        unrelated = self.request(receiver=self.c)
        self.s.messages.read_inbox(self.c['agent_token'])
        onboarding = self.workflow()['onboarding']['addressed_exchange']
        self.assertEqual(onboarding['request_id'], req['id'])
        self.assertNotEqual(onboarding['request_id'], unrelated['id'])

    def test_human_decisions_keep_contract_version_and_handoff_revision_exact(self):
        contract = self.s.contracts.propose(self.b['agent_token'], 'api', 0, 'API', 'Needs decision')
        self.transition('propose_handoff', self.front, target_member_id=self.b['member_id'])
        agent = self.workflow(self.b)['decisions']
        contract_card = next(c for c in agent if c['kind'] == 'contract')
        handoff = next(c for c in agent if c['kind'] == 'handoff')
        self.assertFalse(contract_card['eligible'])
        self.assertEqual(contract_card['payload'], {'contract_id': contract['id'], 'version': 1})
        self.assertNotIn('expected_revision', contract_card['payload'])
        self.assertEqual(handoff['payload']['expected_revision'], self.current(self.front)['revision'])
        self.assertNotIn('version', handoff['payload'])
        human = self.workflow(self.b, kind='web')['decisions']
        self.assertTrue(next(c for c in human if c['kind'] == 'handoff')['eligible'])
        self.assertTrue(next(c for c in human if c['kind'] == 'contract')['eligible'])

    def test_only_current_undecided_contract_head_and_eligible_delivery_are_cards(self):
        contract = self.s.contracts.propose(self.b['agent_token'], 'api', 0, 'API', 'Version one')
        self.s.contracts.propose(self.b['agent_token'], 'api', 1, 'API', 'Version two')
        suggestion = self.s.delivery.suggest(self.a['agent_token'], self.front['id'], 'delivery',
                                           branch='feature', session_key='frontend', ownership_epoch=self.front['ownership_epoch'])
        cards = self.workflow(kind='web')['decisions']
        self.assertEqual(next(c for c in cards if c['kind'] == 'contract')['payload']['version'], 2)
        self.assertTrue(next(c for c in cards if c['kind'] == 'delivery')['eligible'])
        self.assertFalse(next(c for c in self.workflow(self.b, kind='web')['decisions'] if c['kind'] == 'delivery')['eligible'])
        self.s.contracts.decide(self.a['web_token'], contract['id'], 2, 'rejected')
        self.transition('force_handoff', self.front, target_member_id=self.b['member_id'])
        cards = self.workflow()['decisions']
        self.assertFalse(any(c['kind'] == 'contract' for c in cards))
        self.assertFalse(any(c['kind'] == 'delivery' and c['id'] == suggestion['id'] for c in cards))

    def test_unassigned_task_is_claim_action_without_fictitious_assign(self):
        task = self.task(self.a, 'unassigned', False)
        card = next(c for c in self.workflow()['decisions'] if c['kind'] == 'unassigned_task')
        self.assertEqual(card['operation'], 'claim_task')
        self.assertEqual(card['payload'], {'task_id': task['id']})
        self.assertTrue(card['eligible'])
        self.assertFalse(card['requires_human'])
        self.assertNotEqual(card['operation'], 'assign')

    def test_agreement_changes_are_current_execution_scoped(self):
        contract = self.s.contracts.propose(self.b['agent_token'], 'api', 0, 'API', 'Version one')
        self.s.contracts.decide(self.a['web_token'], contract['id'], 1, 'approved')
        self.s.call('record_agreement_use', self.a['agent_token'], dict(**self.auth, contract_id=contract['id'], version=1))
        self.s.contracts.propose(self.b['agent_token'], 'api', 1, 'API', 'Version two')
        self.s.contracts.decide(self.a['web_token'], contract['id'], 2, 'approved')
        result = self.brief(**self.auth)
        change = next(i for i in result['items'] if i['kind'] == 'agreement_change')
        self.assertTrue(change['review_required'])
        self.assertEqual(change['effective_version'], 2)
        self.transition('force_handoff', self.front, target_member_id=self.b['member_id'])
        self.assertEqual(self.workflow()['agreement_changes'], [])

    def test_session_timestamps_are_observations_not_model_availability(self):
        self.s.call('checkpoint', self.a['agent_token'], dict(session_key='frontend', tool='codex-cli', event='startup'))
        member = next(m for m in self.workflow()['member_activity'] if m['member_id'] == self.a['member_id'])
        self.assertIsNotNone(member['last_checkpoint_at'])
        self.assertEqual(member['model_responsiveness'], 'unknown')
        self.assertFalse(member['availability_proven'])

    def test_each_projection_resolves_identity_and_all_facts_in_one_read_transaction(self):
        self.assertTrue('work_brief' in self.s.operations)
        original = self.s.identity.db.connect
        for method in (self.s.team_workflow.read_workflow, self.s.team_workflow.work_brief):
            traces, writes, connections = [], [], []
            @contextmanager
            def observed_connect(*args, **kwargs):
                self.assertFalse(kwargs.get('write'))
                with original(*args, **kwargs) as db:
                    connections.append(db)
                    db.set_trace_callback(traces.append)
                    yield db
                    writes.append(db.total_changes)
            with patch.object(self.s.identity.db, 'connect', observed_connect):
                method(self.a['agent_token'])
            self.assertEqual(len(connections), 1)
            self.assertEqual(writes, [0])
            self.assertEqual(traces[0], 'BEGIN')
            self.assertTrue(any('credentials' in sql for sql in traces))

    def test_cursor_survives_reopen_and_hidden_reply_changes_are_not_skipped(self):
        req = self.request(task_id=self.front['id'])
        for _ in range(4):
            self.reply(req)
        first = self.brief(**self.auth)
        self.s = CoordinationService(self.path)
        self.assertTrue(self.brief(**self.auth, after_cursor=first['cursor'])['unchanged'])
        self.s.call('read_replies', self.a['agent_token'], dict(limit=1))
        self.assertEqual(self.brief(**self.auth, after_cursor=first['cursor'])['reset_reason'], 'content_changed')

    def test_cancelled_dependency_routes_are_historical_not_satisfied(self):
        dep = self.dependency()
        self.s.call('cancel_dependency', self.a['agent_token'], dict(dependency_id=dep['id'],
            expected_revision=dep['revision'], request_key='cancel', summary='Need withdrawn',
            session_key='frontend', ownership_epoch=self.front['ownership_epoch']))
        result = self.workflow()
        request = result['requests'][0]
        self.assertEqual(request['route_state'], 'historical')
        self.assertFalse(request['dependency_satisfied'])
        self.assertFalse(result['onboarding']['two_member_exchange_complete'])

    def test_long_execution_keys_remain_exact_in_action_payloads(self):
        key = '界' * 200
        task = self.s.tasks.create_task(self.a['web_token'], 'long-key', 'Long execution', 'long')
        task = self.s.tasks.claim_task(self.a['agent_token'], task['id'], key)
        result = self.brief(task_id=task['id'], session_key=key, ownership_epoch=task['ownership_epoch'])
        projected = next(i for i in result['items'] if i['kind'] == 'task')
        self.assertEqual(projected['execution_target']['session_key'], key)
        self.assertLessEqual(len(json.dumps(result).encode()), 16000)

    def test_focused_contract_card_never_falls_back_to_an_old_pending_head(self):
        related = self.request(task_id=self.front['id'])
        unrelated = self.request(task_id=self.unrelated['id'])
        contract = self.s.contracts.propose(self.b['agent_token'], 'api', 0, 'API', 'Old pending', related['id'])
        self.s.contracts.propose(self.b['agent_token'], 'api', 1, 'API', 'Unrelated current', unrelated['id'])
        cards = self.workflow(task_id=self.front['id'])['decisions']
        self.assertFalse(any(c['kind'] == 'contract' and c['id'] == contract['id'] for c in cards))


if __name__ == '__main__':
    unittest.main()
