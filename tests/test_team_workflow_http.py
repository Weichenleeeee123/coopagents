"""Authenticated HTTP workflow envelopes, errors and retained read evidence.

These are loopback protocol regressions, not native-model acceptance evidence.
"""
from contextlib import closing
import json
import sqlite3
import unittest
from uuid import uuid4

from transport_support import LiveService


class TeamWorkflowHTTPTests(unittest.TestCase):
    def setUp(self):
        self.live = LiveService()
        self.addCleanup(self.live.close)
        self.a, self.b = self.live.bootstrap()
        self.front = self.task(self.a, 'frontend')
        self.back = self.task(self.b, 'backend')
        self.focus = {'task_id': self.front['id'], 'session_key': 'frontend',
                      'ownership_epoch': self.front['ownership_epoch']}

    def op(self, name, person=None, data=None, *, kind='agent', expected=200):
        status, result, headers = self.live.request('POST', '/api/operations/' + name,
            (person or self.a)[kind + '_token'], data if data is not None else {},
            headers={'Origin': self.live.url})
        self.assertEqual(status, expected, result)
        self.assertIn('no-store', headers.get('Cache-Control', ''))
        self.assertIn('application/json', headers.get('Content-Type', ''))
        return result

    def task(self, person, key, claim=True):
        task = self.op('create_task', person, {'intent_key': key, 'title': key, 'scope': 'src/' + key}, kind='web')
        return self.op('claim_task', person, {'task_id': task['id'], 'session_key': key}) if claim else task

    def addressed_reply(self):
        request = self.op('send_request', data={'request_key': uuid4().hex, 'context_version': 1,
            'receiver_member_id': self.b['member_id'], 'task_id': self.front['id'], 'body': 'Which field?'})
        replied = self.op('reply', self.b, {'request_id': request['id'], 'request_key': uuid4().hex,
            'context_version': 1, 'body': 'Use user_id', 'evidence': 'src/backend/schema.py'})
        return request, replied['replies'][-1]

    def receipt_counts(self):
        with closing(sqlite3.connect(self.live.database)) as db:
            return tuple(db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                         for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads'))

    def test_workflow_operations_return_private_json_to_agent_and_web(self):
        request, _ = self.addressed_reply()
        for person, kind in ((self.a, 'agent'), (self.a, 'web'), (self.b, 'agent'), (self.b, 'web')):
            view = self.op('read_workflow', person, kind=kind)
            self.assertEqual(view['source'], 'team_workflow')
            self.assertTrue(view['read_only'])
            self.assertEqual(view['requests'][0]['id'], request['id'])
            self.assertFalse(view['model_consumption_proven'])
            serialized = json.dumps(view)
            for member in (self.a, self.b):
                self.assertNotIn(member['agent_token'], serialized)
                self.assertNotIn(member['web_token'], serialized)
        status, snapshot, headers = self.live.request('GET', '/api/snapshot', self.a['web_token'])
        self.assertEqual(status, 200)
        self.assertIn('no-store', headers.get('Cache-Control', ''))
        self.assertEqual(snapshot['workflow']['requests'][0]['id'], request['id'])

    def test_http_authentication_validation_and_error_responses_are_not_cached(self):
        for token in (None, 'invalid-workflow-credential'):
            status, body, headers = self.live.request('POST', '/api/operations/read_workflow', token, {})
            self.assertEqual(status, 401)
            self.assertEqual(body['error'], 'AccessDenied')
            self.assertIn('no-store', headers.get('Cache-Control', ''))
        self.op('work_brief', kind='web', expected=401)
        for payload in ({'limit': True}, {'limit': 0}, {'limit': 51}, {'task_id': True},
                        {'session_key': 'loose'}, {'ownership_epoch': 1}, {'unexpected': 'field'}):
            with self.subTest(payload=payload):
                self.assertEqual(self.op('work_brief', data=payload, expected=400)['error'], 'ValidationError')
        for raw in (b'[]', b'{', b'{"limit":NaN}'):
            status, body, headers = self.live.request('POST', '/api/operations/work_brief',
                self.a['agent_token'], headers={'Content-Type': 'application/json'}, raw=raw)
            self.assertEqual(status, 400, body)
            self.assertIn('no-store', headers.get('Cache-Control', ''))

    def test_execution_and_room_authority_apply_before_unchanged_cursor(self):
        first = self.op('work_brief', data=self.focus)
        for override, code in (({'session_key': 'wrong'}, 409), ({'ownership_epoch': 99}, 409)):
            denied = self.op('work_brief', data={**self.focus, **override, 'after_cursor': first['cursor']}, expected=code)
            self.assertEqual(denied['error'], 'Conflict')
        self.op('work_brief', self.b, {**self.focus, 'after_cursor': first['cursor']}, expected=401)
        # Team transparency is separate from permission to execute a task.
        self.assertEqual(self.op('read_workflow', self.b, {'task_id': self.front['id']})['focus']['task_id'], self.front['id'])
        status, other, _ = self.live.request('POST', '/api/rooms', data={'name': 'Other', 'owner_name': 'Other'})
        self.assertEqual(status, 200)
        for operation in ('read_workflow', 'work_brief'):
            self.op(operation, other, {'task_id': self.front['id']}, expected=404)
        moved = self.op('force_handoff', data={'task_id': self.front['id'], 'expected_revision': self.front['revision'],
            'request_key': 'move', 'summary': 'Backend continues', 'target_member_id': self.b['member_id']}, kind='web')
        self.assertGreater(moved['ownership_epoch'], self.front['ownership_epoch'])
        self.op('work_brief', data={**self.focus, 'after_cursor': first['cursor']}, expected=401)

    def test_wire_budget_focus_and_content_cursor_cover_all_returned_requests(self):
        unrelated = self.task(self.a, 'unrelated')
        self.op('send_request', data={'request_key': 'unrelated', 'context_version': 1,
            'receiver_member_id': self.b['member_id'], 'task_id': unrelated['id'], 'body': 'EXCLUDED-HTTP-MARKER'})
        identifiers = set()
        for index in range(18):
            request = self.op('send_request', data={'request_key': str(index), 'context_version': 1,
                'receiver_member_id': self.b['member_id'], 'task_id': self.front['id'], 'body': '中文共享内容' * 500})
            identifiers.add(request['id'])
        cursor, seen, final = None, [], None
        for _ in range(30):
            status, raw, headers = self.live.request('POST', '/api/operations/work_brief', self.a['agent_token'],
                {**self.focus, 'limit': 50, 'after_cursor': cursor}, parse_json=False)
            self.assertEqual(status, 200)
            self.assertLessEqual(len(raw), 16000)
            self.assertIn('no-store', headers.get('Cache-Control', ''))
            self.assertNotIn(b'EXCLUDED-HTTP-MARKER', raw)
            final = json.loads(raw)
            seen += [item['id'] for item in final['items'] if item['kind'] == 'request']
            if not final['has_more']:
                break
            self.assertTrue(final['items'])
            cursor = final['next_cursor']
        self.assertEqual(set(seen), identifiers)
        self.assertEqual(len(seen), len(identifiers))
        same = self.op('work_brief', data={**self.focus, 'limit': 50, 'after_cursor': final['cursor']})
        self.assertTrue(same['unchanged'])
        malformed = self.op('work_brief', data={**self.focus, 'after_cursor': 'not-a-cursor'})
        self.assertEqual(malformed['reset_reason'], 'invalid_cursor')
        self.assertFalse(malformed['delta'])

    def test_projection_peeks_and_explicit_reply_evidence_survive_service_reopen(self):
        request, reply = self.addressed_reply()
        self.assertEqual(self.receipt_counts(), (0, 0, 0))
        self.op('work_brief', data=self.focus)
        before = self.op('read_workflow')['requests'][0]
        self.assertFalse(before['sender_reply_read'])
        self.assertIsNone(before['recipient_read'])
        self.assertEqual(self.receipt_counts(), (0, 0, 0))
        page = self.op('read_replies', data={'task_id': self.front['id']})
        self.assertEqual(page['replies'][0]['id'], reply['id'])
        self.assertEqual(self.receipt_counts(), (0, 1, 0))
        saved = self.op('work_brief', data=self.focus)
        database = self.live.database
        self.live.close()
        self.live = LiveService(database)
        self.addCleanup(self.live.close)
        unchanged = self.op('work_brief', data={**self.focus, 'after_cursor': saved['cursor']})
        self.assertTrue(unchanged['unchanged'])
        restored = self.op('read_workflow')['requests'][0]
        self.assertEqual(restored['id'], request['id'])
        self.assertTrue(restored['sender_reply_read'])
        self.assertFalse(restored['resolved'])
        self.assertFalse(restored['model_comprehension_proven'])
        self.assertEqual(self.receipt_counts(), (0, 1, 0))

    def test_dependency_http_projection_separates_recipient_and_confirmation_reads(self):
        question = self.op('ask_owner', data={'request_key': 'dependency', 'body': 'Which field?',
            'source_task_id': self.front['id'], 'target_task_id': self.back['id'],
            'expected_revision': self.front['revision'], 'session_key': 'frontend',
            'ownership_epoch': self.front['ownership_epoch']})
        dep = question['dependency']
        replied = self.op('reply_dependency', self.b, {'dependency_id': dep['id'],
            'expected_revision': dep['revision'], 'request_key': 'dependency-answer', 'body': 'user_id',
            'session_key': 'backend', 'ownership_epoch': self.back['ownership_epoch']})
        view = self.op('read_workflow', data={'task_id': self.front['id']})
        request = view['requests'][0]
        self.assertEqual(request['route_state'], 'current')
        self.assertIsNone(request['recipient_read'])
        self.assertTrue(request['replied'])
        self.assertFalse(request['sender_reply_read'])
        self.assertIsNone(request['replies'][0]['dependency_confirmation_read_at'])
        self.assertEqual(self.receipt_counts(), (0, 0, 0))
        self.op('read_dependency', data={'dependency_id': dep['id'], 'session_key': 'frontend',
                                        'ownership_epoch': self.front['ownership_epoch']})
        after = self.op('read_workflow', data={'task_id': self.front['id']})['requests'][0]
        self.assertIsNotNone(after['replies'][0]['dependency_confirmation_read_at'])
        self.assertFalse(after['sender_reply_read'])
        self.assertFalse(after['dependency_satisfied'])
        self.assertEqual(after['latest_reply_id'], replied['latest_reply']['id'])
        self.assertEqual(self.receipt_counts(), (0, 0, 1))

    def test_agreement_use_and_review_cards_cross_authenticated_operation_routes(self):
        contract = self.op('propose_contract', self.b, {'contract_key': 'api', 'expected_version': 0,
            'title': 'API', 'body': 'Use cursor'})
        self.op('decision', data={'contract_id': contract['id'], 'version': 1, 'decision': 'approved'}, kind='web')
        usage = {'task_id': self.front['id'], 'contract_id': contract['id'], 'version': 1,
                 'session_key': 'frontend', 'ownership_epoch': self.front['ownership_epoch']}
        self.op('record_agreement_use', data=usage)
        self.op('record_agreement_use', self.b, usage, expected=401)
        self.op('record_agreement_use', data=usage, kind='web', expected=401)
        self.op('propose_contract', self.b, {'contract_key': 'api', 'expected_version': 1,
            'title': 'API version two', 'body': 'Use next_cursor'})
        self.op('decision', data={'contract_id': contract['id'], 'version': 2, 'decision': 'approved'}, kind='web')
        agent = self.op('read_workflow')
        card = next(c for c in agent['decisions'] if c['kind'] == 'agreement_review')
        self.assertTrue(card['eligible'])
        self.assertEqual(card['payload'], {**usage, 'version': 2})
        self.assertFalse(card['requires_human'])
        member = self.op('read_workflow', self.b)
        self.assertFalse(next(c for c in member['decisions'] if c['kind'] == 'agreement_review')['eligible'])
        current = self.op('record_agreement_use', data=card['payload'])
        self.assertFalse(current['review_required'])

    def test_human_card_payloads_and_eligibility_match_http_authority(self):
        contract = self.op('propose_contract', self.b, {'contract_key': 'pending', 'expected_version': 0,
            'title': 'Pending', 'body': 'Human decision required'})
        handoff = self.op('propose_handoff', data={**self.focus, 'expected_revision': self.front['revision'],
            'request_key': 'handoff', 'summary': 'Backend finishes', 'target_member_id': self.b['member_id']})
        self.task(self.a, 'unowned', claim=False)
        self.op('suggest_delivery', data={**self.focus, 'request_key': 'suggestion', 'branch': 'feature'})
        agent = self.op('read_workflow', self.b)
        contract_card = next(c for c in agent['decisions'] if c['kind'] == 'contract')
        self.assertEqual(contract_card['payload'], {'contract_id': contract['id'], 'version': 1})
        self.assertFalse(contract_card['eligible'])
        handoff_card = next(c for c in agent['decisions'] if c['kind'] == 'handoff')
        self.assertEqual(handoff_card['payload'], {'task_id': self.front['id'], 'expected_revision': handoff['revision']})
        self.assertFalse(handoff_card['eligible'])
        self.op('decision', self.b, {**contract_card['payload'], 'decision': 'approved'}, expected=401)
        self.op('accept_handoff', self.b, {**handoff_card['payload'], 'request_key': 'denied', 'summary': 'Cannot impersonate human'}, expected=401)
        human = self.op('read_workflow', self.b, kind='web')
        self.assertTrue(next(c for c in human['decisions'] if c['kind'] == 'handoff')['eligible'])
        self.assertFalse(next(c for c in human['decisions'] if c['kind'] == 'delivery')['eligible'])
        manager = self.op('read_workflow', kind='web')
        delivery = next(c for c in manager['decisions'] if c['kind'] == 'delivery')
        self.assertTrue(delivery['eligible'])
        self.op('decide_delivery', self.b, {**delivery['payload'], 'decision': 'rejected'}, kind='web', expected=401)
        self.assertEqual(self.op('decide_delivery', data={**delivery['payload'], 'decision': 'rejected'}, kind='web')['status'], 'rejected')
        unowned = next(c for c in agent['decisions'] if c['kind'] == 'unassigned_task')
        self.assertEqual(unowned['operation'], 'claim_task')
        self.assertFalse(unowned['requires_human'])


if __name__ == '__main__':
    unittest.main()
