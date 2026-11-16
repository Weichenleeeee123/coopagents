"""Persistent frozen brief batches; SQLite fixtures never execute native agents."""
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict


class BriefDeltaTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('brief-delta-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.a = self.s.identity.create_room('Project', 'Frontend')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        self.front = self.task(self.a, 'front')
        self.other = self.task(self.a, 'other')
        self.back = self.task(self.b, 'back')
        self.focus = dict(task_id=self.front['id'], session_key='front', ownership_epoch=self.front['ownership_epoch'])

    def task(self, member, key, claim=True):
        task = self.s.tasks.create_task(member['web_token'], key, key, key)
        return self.s.tasks.claim_task(member['agent_token'], task['id'], key) if claim else task

    def brief(self, cursor=None, *, focus=True, limit=20, member=None, **extra):
        args = {**(self.focus if focus else {}), 'limit': limit, **extra}
        if cursor is not None:
            args['after_cursor'] = cursor
        return self.s.call('work_brief', (member or self.a)['agent_token'], args)

    def drain(self, first, *, focus=True, limit=20):
        all_items, page = list(first['items']), first
        for _ in range(100):
            self.assertLessEqual(len(json.dumps(page).encode()), 16000)
            if not page['has_more']:
                return all_items, page['cursor']
            self.assertTrue(page['items'], 'a bounded batch must advance on every nonterminal page')
            page = self.brief(page['next_cursor'], focus=focus, limit=limit)
            all_items.extend(page['items'])
        self.fail('brief batch did not terminate')

    def request(self, *, sender=None, receiver=None, task_id='focus', body='Which field?'):
        return self.s.messages.send_request((sender or self.a)['agent_token'], uuid4().hex,
            (receiver or self.b)['member_id'], self.front['id'] if task_id == 'focus' else task_id, 1, body)

    def reply(self, req, body='Use user_id'):
        return self.s.messages.reply(self.b['agent_token'], req['id'], uuid4().hex, 1, body)['replies'][-1]

    def contract(self, key='api'):
        return self.s.contracts.propose(self.b['agent_token'], key, 0, key, 'x' * 1000 + 'tail')

    def test_first_snapshot_has_stable_keys_and_repeat_cursor_is_unchanged(self):
        first = self.brief()
        self.assertFalse(first['delta'])
        self.assertFalse(first['resync'])
        self.assertTrue(all(i['change'] == 'snapshot' for i in first['items']))
        self.assertEqual(len({i['item_key'] for i in first['items']}), len(first['items']))
        _, cursor = self.drain(first)
        unchanged = self.brief(cursor)
        self.assertTrue(unchanged['unchanged'])
        self.assertEqual(unchanged['items'], [])
        self.assertEqual(unchanged['cursor'], cursor)

    def test_added_then_updated_request_does_not_resend_unchanged_tasks(self):
        _, cursor = self.drain(self.brief())
        req = self.request()
        added, cursor = self.drain(self.brief(cursor))
        item = next(i for i in added if i['kind'] == 'request')
        self.assertEqual(item['id'], req['id'])
        self.assertEqual(item['change'], 'added')
        self.assertFalse(any(i['kind'] == 'task' for i in added))
        self.reply(req)
        updated, _ = self.drain(self.brief(cursor))
        changed = next(i for i in updated if i['kind'] == 'request')
        self.assertEqual(changed['item_key'], item['item_key'])
        self.assertEqual(changed['change'], 'updated')

    def test_removed_decision_is_tombstone_without_deleting_contract_history(self):
        contract = self.contract()
        before, cursor = self.drain(self.brief())
        card = next(i for i in before if i['kind'] == 'decision')
        self.s.contracts.decide(self.a['web_token'], contract['id'], 1, 'approved')
        delta = self.brief(cursor)
        self.assertTrue(delta['delta'])
        self.assertFalse(delta['reset'])
        tombstone = next(i for i in delta['items'] if i['item_key'] == card['item_key'])
        self.assertEqual(tombstone['change'], 'removed')
        self.assertTrue(tombstone['removed'])
        self.assertNotIn('operation', tombstone.get('decision', {}))
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM contract_versions').fetchone()[0], 1)

    def test_snapshot_pages_are_frozen_and_new_work_arrives_in_next_delta(self):
        original = {self.request()['id'] for _ in range(6)}
        first = self.brief(limit=2)
        late = self.request()['id']
        items, cursor = self.drain(first, limit=2)
        self.assertEqual({i['id'] for i in items if i['kind'] == 'request'}, original)
        delta, _ = self.drain(self.brief(cursor, limit=2), limit=2)
        self.assertEqual([i['id'] for i in delta if i['kind'] == 'request'], [late])
        self.assertEqual(next(i for i in delta if i['kind'] == 'request')['change'], 'added')

    def test_delta_pages_are_frozen_and_mid_batch_reply_is_not_skipped(self):
        _, cursor = self.drain(self.brief(limit=2), limit=2)
        requests = [self.request() for _ in range(5)]
        first = self.brief(cursor, limit=2)
        self.reply(requests[-1])
        items, cursor = self.drain(first, limit=2)
        self.assertTrue(all(i['change'] == 'added' for i in items if i['kind'] == 'request'))
        following, _ = self.drain(self.brief(cursor, limit=2), limit=2)
        self.assertEqual([(i['id'], i['change']) for i in following if i['kind'] == 'request'],
                         [(requests[-1]['id'], 'updated')])

    def test_restart_preserves_pending_page_and_completed_baseline(self):
        requests = {self.request()['id'] for _ in range(4)}
        first = self.brief(limit=1)
        self.s = CoordinationService(self.path)
        items, cursor = self.drain(first, limit=1)
        self.assertEqual({i['id'] for i in items if i['kind'] == 'request'}, requests)
        self.s = CoordinationService(self.path)
        self.assertTrue(self.brief(cursor, limit=1)['unchanged'])

    def test_expired_missing_and_malformed_cursors_explicitly_resync(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.brief_deltas'))
        _, cursor = self.drain(self.brief())
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE brief_delta_snapshots SET expires_at=0')
        expired = self.brief(cursor)
        self.assertEqual(expired['reset_reason'], 'cursor_expired')
        self.assertTrue(expired['resync'])
        with self.s.identity.db.connect(write=True) as db:
            db.execute('DELETE FROM brief_delta_snapshots')
        missing = self.brief(expired['cursor'])
        self.assertEqual(missing['reset_reason'], 'cursor_missing')
        malformed = self.brief('not-a-cursor')
        self.assertEqual(malformed['reset_reason'], 'invalid_cursor')
        self.assertTrue(malformed['reset'])
        self.assertTrue(all(i['change'] == 'snapshot' for i in malformed['items']))
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE brief_delta_snapshots SET state_json=? WHERE snapshot_id=?',
                       ('{}', malformed['snapshot_id']))
        corrupt = self.brief(malformed['cursor'])
        self.assertEqual(corrupt['reset_reason'], 'cursor_unrecoverable')
        self.assertTrue(corrupt['resync'])

    def test_scope_limit_member_and_room_are_bound_to_cursor(self):
        _, cursor = self.drain(self.brief())
        for kwargs in ({'limit': 1}, {'focus': False}, {'focus': False, 'member': self.b}):
            result = self.brief(cursor, **kwargs)
            self.assertTrue(result['resync'])
            self.assertEqual(result['reset_reason'], 'scope_changed')
        other = self.s.identity.create_room('Other', 'Other')
        self.assertEqual(self.brief(cursor, focus=False, member=other)['reset_reason'], 'scope_changed')

    def test_retired_epoch_is_denied_before_serving_a_frozen_cached_page(self):
        first = self.brief(limit=1)
        self.s.call('force_handoff', self.a['web_token'], dict(task_id=self.front['id'],
            expected_revision=self.front['revision'], request_key='move', summary='Move', target_member_id=self.b['member_id']))
        with self.assertRaises((AccessDenied, Conflict)):
            self.brief(first['cursor'], limit=1)

    def test_hidden_read_and_excerpt_tail_changes_still_emit_updated_items(self):
        req = self.request()
        for _ in range(4):
            self.reply(req)
        _, cursor = self.drain(self.brief())
        self.s.call('read_replies', self.a['agent_token'], {'limit': 1})
        delta = self.brief(cursor)
        self.assertTrue(any(i['kind'] == 'request' and i['change'] == 'updated' for i in delta['items']))
        contract = self.contract()
        self.s.contracts.decide(self.a['web_token'], contract['id'], 1, 'approved')
        self.s.call('record_agreement_use', self.a['agent_token'], dict(**self.focus, contract_id=contract['id'], version=1))
        _, cursor = self.drain(self.brief())
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE contract_versions SET body=? WHERE contract_id=?', ('x' * 1000 + 'changed-tail', contract['id']))
        changed = self.brief(cursor)
        self.assertTrue(any(i['kind'] == 'agreement_change' and i['change'] == 'updated' for i in changed['items']))

    def test_compound_item_keys_cover_same_contract_reviews_for_two_tasks(self):
        contract = self.contract()
        self.s.contracts.decide(self.a['web_token'], contract['id'], 1, 'approved')
        for task, key in ((self.front, 'front'), (self.other, 'other')):
            self.s.call('record_agreement_use', self.a['agent_token'], dict(task_id=task['id'], session_key=key,
                ownership_epoch=task['ownership_epoch'], contract_id=contract['id'], version=1))
        self.s.contracts.propose(self.b['agent_token'], 'api', 1, 'API2', 'New')
        self.s.contracts.decide(self.a['web_token'], contract['id'], 2, 'approved')
        items, _ = self.drain(self.brief(focus=False), focus=False)
        cards = [i for i in items if i['kind'] == 'decision' and i['decision']['kind'] == 'agreement_review']
        self.assertEqual(len(cards), 2)
        self.assertEqual(len({i['item_key'] for i in cards}), 2)

    def test_member_pending_fallback_does_not_mix_another_owned_task(self):
        _, cursor = self.drain(self.brief())
        outgoing = self.s.call('ask_owner', self.a['agent_token'], dict(request_key='owner', body='Q', target_task_id=self.back['id']))
        incoming = self.request(sender=self.b, receiver=self.a, task_id=None)
        excluded = self.s.call('ask_owner', self.b['agent_token'], dict(request_key='other', body='OTHER-TASK-MARKER', target_task_id=self.other['id']))
        items, cursor = self.drain(self.brief(cursor))
        ids = {i['id'] for i in items if i['kind'] == 'request'}
        self.assertTrue({incoming['id'], outgoing['request']['id']} <= ids)
        self.assertNotIn(excluded['request']['id'], ids)
        self.assertFalse(any(i['kind'] == 'task' and i['id'] == self.other['id'] for i in items))
        self.assertTrue(self.brief(cursor)['unchanged'])
        target = self.task(self.a, 'unowned', claim=False)
        self.s.call('ask_owner', self.a['agent_token'], dict(request_key='queued', body='Q', target_task_id=target['id']))
        queued, cursor = self.drain(self.brief(cursor))
        queue_item = next(i for i in queued if i['kind'] == 'owner_question')
        self.assertEqual(queue_item['brief_scope'], 'member_pending')
        self.s.tasks.claim_task(self.b['agent_token'], target['id'], 'new-owner')
        routed, _ = self.drain(self.brief(cursor))
        self.assertTrue(any(i['item_key'] == queue_item['item_key'] and i['change'] == 'removed' for i in routed))
        self.assertTrue(any(i['kind'] == 'request' and i['change'] == 'added' for i in routed))

    def test_cache_retention_is_bounded_and_never_writes_business_receipts(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.brief_deltas'))
        with patch('coopagents.brief_deltas.MAX_PER_BINDING', 3):
            _, first_cursor = self.drain(self.brief())
            cursor = first_cursor
            for _ in range(6):
                self.request()
                _, cursor = self.drain(self.brief(cursor))
        with self.s.identity.db.connect() as db:
            self.assertLessEqual(db.execute('SELECT COUNT(*) FROM brief_delta_snapshots').fetchone()[0], 3)
            for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads', 'contract_decisions'):
                self.assertEqual(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0], 0)
        self.assertTrue(self.brief(first_cursor)['resync'])

    def test_large_snapshot_and_delta_pages_fit_wire_budget_without_lost_keys(self):
        reqs = {self.request(body='中文长消息' * 500)['id'] for _ in range(35)}
        items, cursor = self.drain(self.brief(limit=50), limit=50)
        self.assertEqual({i['id'] for i in items if i['kind'] == 'request'}, reqs)
        self.assertTrue(any(i.get('excerpted') and i.get('source_read') for i in items if i['kind'] == 'request'))
        self.reply(next(r for r in self.s.messages.list_requests(self.a['agent_token']) if r['id'] in reqs))
        delta, _ = self.drain(self.brief(cursor, limit=50), limit=50)
        self.assertEqual(len([i for i in delta if i['kind'] == 'request']), 1)

    def test_oversized_unicode_record_is_excerpted_instead_of_stalling_a_page(self):
        legacy = self.task(self.a, 'legacy', claim=False)
        legacy = self.s.tasks.claim_task(self.a['agent_token'], legacy['id'])
        self.focus = {'task_id': legacy['id'], 'ownership_epoch': legacy['ownership_epoch']}
        dep = self.s.call('create_dependency', self.a['agent_token'], dict(source_task_id=legacy['id'],
            target_task_id=self.back['id'], expected_revision=legacy['revision'], request_key='large', need='Large'))
        for index in range(2):
            dep = self.s.call('reply_dependency', self.b['agent_token'], dict(dependency_id=dep['id'],
                expected_revision=dep['revision'], request_key=str(index), body='😀' * 3500,
                evidence='😀' * 1000, session_key='back', ownership_epoch=self.back['ownership_epoch']))
            self.s.call('read_dependency', self.a['agent_token'], dict(dependency_id=dep['id'],
                session_key='😀' * 199 + str(index), ownership_epoch=legacy['ownership_epoch']))
        items, _ = self.drain(self.brief(limit=50), limit=50)
        request = next(i for i in items if i['kind'] == 'request')
        self.assertTrue(request['excerpted'])
        self.assertTrue(request['source_read'])
        self.assertEqual(len(request['replies'][0]['dependency_confirmation_read']['session_key']), 200)


if __name__ == '__main__':
    unittest.main()
