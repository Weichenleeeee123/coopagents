"""Protected local intent persistence; callbacks never contact a real service."""
import copy
from contextlib import closing
import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import Mock, patch
from urllib.error import URLError
from uuid import uuid4

from coopagents.errors import Conflict, ValidationError


class LocalOutboxTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.local_outbox'), 'local outbox is missing')
        from coopagents import local_outbox
        self.m = local_outbox
        self.path = Path('.local/test-evidence') / ('outbox-' + uuid4().hex) / 'outbox.sqlite3'
        self.box = self.m.LocalOutbox(self.path, 'room', 'member')
        self.args = {'request_key': 'q', 'target_task_id': 1, 'body': 'PRIVATE-BODY-CANARY'}
        self.identity = lambda: {'me': {'room_id': 'room', 'member_id': 'member', 'kind': 'agent'}}

    def test_only_explicit_idempotent_technical_operations_are_supported(self):
        expected = {'ask_owner', 'send_request', 'reply', 'reply_dependency', 'create_dependency'}
        for op in expected:
            self.assertTrue(self.box.supports(op))
        for op in ('read_inbox', 'read_replies', 'acknowledge', 'resolve_request', 'report_progress',
                   'decision', 'create_task', 'start', 'register_session'):
            self.assertFalse(self.box.supports(op))
            with self.assertRaises(ValidationError):
                self.box.enqueue(op, self.args)

    def test_reopen_deduplicates_intent_without_disclosing_payload(self):
        first = self.box.enqueue('ask_owner', self.args)
        self.assertEqual(first['status'], 'queued_locally')
        self.assertFalse(first['delivered'])
        self.assertFalse(first['service_applied'])
        reopened = self.m.LocalOutbox(self.path, 'room', 'member')
        self.assertEqual(reopened.enqueue('ask_owner', self.args)['outbox_id'], first['outbox_id'])
        summary = reopened.summary()
        self.assertEqual(summary['counts']['queued_locally'], 1)
        self.assertNotIn('PRIVATE-BODY-CANARY', json.dumps(summary))
        self.assertNotIn('request_key', json.dumps(summary))
        before = self.path.read_bytes()
        reopened.summary()
        self.assertEqual(self.path.read_bytes(), before)

    def test_original_identity_binding_cannot_be_reassigned(self):
        self.box.enqueue('ask_owner', self.args)
        with self.assertRaises(ValidationError):
            self.m.LocalOutbox(self.path, 'room', 'another-member')
        self.assertEqual(self.box.summary()['counts']['queued_locally'], 1)

    def test_same_operation_key_with_changed_payload_is_a_conflict(self):
        self.box.enqueue('ask_owner', self.args)
        with self.assertRaises(Conflict):
            self.box.enqueue('ask_owner', {**self.args, 'body': 'different'})
        self.assertEqual(self.box.summary()['counts']['queued_locally'], 1)

    def test_successful_current_call_completes_only_matching_original_intent(self):
        original = self.box.enqueue('ask_owner', self.args)
        self.box.enqueue('ask_owner', {**self.args, 'request_key': 'other'})
        result = self.box.complete('ask_owner', self.args, {'id': 9, 'server_secret': 'RESPONSE-SECRET'})
        self.assertEqual(result['outbox_id'], original['outbox_id'])
        self.assertEqual(result['status'], 'synced_to_service')
        self.assertTrue(result['service_applied'])
        self.assertFalse(result['model_consumption_proven'])
        self.assertEqual(self.box.summary()['counts']['queued_locally'], 1)
        self.assertNotIn(b'RESPONSE-SECRET', self.path.read_bytes())

    def test_response_lost_replay_preserves_key_and_server_idempotence(self):
        self.box.enqueue('ask_owner', self.args)
        applied, calls = {}, []
        def sender(op, args):
            calls.append(copy.deepcopy(args))
            applied.setdefault(args['request_key'], 7)
            if len(calls) == 1:
                raise URLError('RAW-SECRET-NETWORK-ERROR')
            return {'id': applied[args['request_key']]}
        with patch('coopagents.local_outbox.time.time', return_value=100):
            self.box.flush(self.identity, sender)
        self.box = self.m.LocalOutbox(self.path, 'room', 'member')
        with patch('coopagents.local_outbox.time.time', return_value=200):
            result = self.box.flush(self.identity, sender)
        self.assertEqual(len(applied), 1)
        self.assertEqual(calls, [self.args, self.args])
        self.assertEqual(result['counts']['synced_to_service'], 1)
        self.assertNotIn('RAW-SECRET', json.dumps(result))

    def test_auth_conflict_validation_and_quota_block_without_retry_or_raw_errors(self):
        for reason in ('auth', 'conflict', 'validation', 'quota'):
            box = self.m.LocalOutbox(self.path.with_name(reason + '.sqlite3'), 'room', 'member')
            box.enqueue('ask_owner', self.args)
            sender = Mock(side_effect=self.m.OutboxError(reason))
            result = box.flush(self.identity, sender)
            self.assertEqual(result['counts']['blocked'], 1)
            self.assertEqual(result['items'][0]['reason'], reason)
            box.flush(Mock(side_effect=AssertionError('blocked entries must not reconnect')), sender)
            self.assertEqual(sender.call_count, 1)

    def test_identity_mismatch_never_sends_as_the_new_member(self):
        self.box.enqueue('ask_owner', self.args)
        sender = Mock()
        result = self.box.flush(lambda: {'room_id': 'room', 'member_id': 'other', 'kind': 'agent'}, sender)
        sender.assert_not_called()
        self.assertEqual(result['counts']['blocked'], 1)
        self.assertEqual(result['items'][0]['reason'], 'identity_mismatch')

    def test_stop_before_or_between_items_does_not_connect_or_restart(self):
        self.box.enqueue('ask_owner', self.args)
        self.box.enqueue('ask_owner', {**self.args, 'request_key': 'second'})
        verify, sender = Mock(), Mock()
        self.box.flush(verify, sender, stopped=lambda: True)
        verify.assert_not_called(); sender.assert_not_called()
        stopped = [False]
        def send(op, args):
            stopped[0] = True
            return {'id': 1}
        result = self.box.flush(self.identity, send, stopped=lambda: stopped[0])
        self.assertEqual(result['counts']['synced_to_service'], 1)
        self.assertEqual(result['counts']['queued_locally'], 1)

    def test_network_backoff_and_attempt_limit_are_bounded(self):
        self.box.enqueue('ask_owner', self.args)
        verify, sender = Mock(side_effect=self.identity), Mock(side_effect=self.m.OutboxError('server', status_code=503))
        with patch('coopagents.local_outbox.MAX_ATTEMPTS', 3):
            for now in (100, 100, 200, 300, 400):
                with patch('coopagents.local_outbox.time.time', return_value=now):
                    self.box.flush(verify, sender)
        self.assertEqual(sender.call_count, 3)
        item = self.box.summary()['items'][0]
        self.assertEqual(item['status'], 'blocked')
        self.assertEqual(item['reason'], 'retry_exhausted')
        self.assertEqual(item['attempts'], 3)

    def test_capacity_and_payload_limits_do_not_discard_old_records(self):
        with patch('coopagents.local_outbox.MAX_ENTRIES', 1):
            first = self.box.enqueue('ask_owner', self.args)
            self.assertEqual(self.box.enqueue('ask_owner', self.args)['outbox_id'], first['outbox_id'])
            with self.assertRaises(ValidationError):
                self.box.enqueue('ask_owner', {**self.args, 'request_key': 'second'})
        with patch('coopagents.local_outbox.MAX_PAYLOAD_BYTES', 20):
            with self.assertRaises(ValidationError):
                self.box.enqueue('ask_owner', {**self.args, 'request_key': 'oversized'})
        self.assertEqual(sum(self.box.summary()['counts'].values()), 1)

    def test_original_epoch_and_arguments_are_never_rewritten_on_recovery(self):
        args = {'dependency_id': 9, 'expected_revision': 2, 'request_key': 'reply', 'body': 'Answer',
                'session_key': 'retired-session', 'ownership_epoch': 3}
        self.box.enqueue('reply_dependency', args)
        seen = []
        def sender(op, payload):
            seen.append(copy.deepcopy(payload))
            payload['ownership_epoch'] = 999
            raise self.m.OutboxError('conflict', status_code=409)
        self.box.flush(self.identity, sender)
        self.assertEqual(seen, [args])
        with closing(sqlite3.connect(self.path)) as db:
            saved = json.loads(db.execute('SELECT arguments_json FROM outbox_intents').fetchone()[0])
        self.assertEqual(saved, args)

    def test_failed_tool_result_is_not_marked_service_applied(self):
        self.box.enqueue('ask_owner', self.args)
        result = self.box.flush(self.identity, lambda op, args: {'is_error': True, 'error': 'RAW-PRIVATE'})
        self.assertEqual(result['counts']['synced_to_service'], 0)
        self.assertEqual(result['counts']['blocked'], 1)
        self.assertNotIn('RAW-PRIVATE', json.dumps(result))

    def test_verification_network_failure_is_bounded_without_sending_payload(self):
        self.box.enqueue('ask_owner', self.args)
        sender = Mock()
        with patch('coopagents.local_outbox.MAX_ATTEMPTS', 2):
            for now in (100, 200, 300):
                with patch('coopagents.local_outbox.time.time', return_value=now):
                    self.box.flush(Mock(side_effect=URLError('secret')), sender)
        sender.assert_not_called()
        self.assertEqual(self.box.summary()['items'][0]['reason'], 'retry_exhausted')

    def test_constructor_uses_existing_private_path_protection(self):
        self.assertEqual(self.m.stored_identity(self.path), {'room_id': 'room', 'member_id': 'member'})
        self.assertIsNone(self.m.stored_identity(self.path.with_name('absent.sqlite3')))
        with patch('coopagents.local_outbox.protect', wraps=self.m.protect) as protect:
            self.m.LocalOutbox(self.path.with_name('protected.sqlite3'), 'room', 'member')
        self.assertTrue(protect.called)

    def test_recovery_revalidates_allowlist_and_payload_integrity_before_sender(self):
        self.box.enqueue('ask_owner', self.args)
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("UPDATE outbox_intents SET operation='decision'")
            db.commit()
        sender = Mock(return_value={'id': 1})
        summary = self.box.flush(self.identity, sender)
        sender.assert_not_called()
        self.assertEqual(summary['counts']['blocked'], 1)
        self.assertEqual(summary['items'][0]['reason'], 'validation')

    def test_unknown_stop_callback_state_fails_closed_without_leaking_its_exception(self):
        self.box.enqueue('ask_owner', self.args)
        verify, sender = Mock(), Mock()
        result = self.box.flush(verify, sender, stopped=Mock(side_effect=RuntimeError('PRIVATE-STOP-ERROR')))
        verify.assert_not_called(); sender.assert_not_called()
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_ambiguous_owner_resolution_is_not_a_service_applied_question(self):
        self.box.enqueue('ask_owner', self.args)
        result = self.box.flush(self.identity, lambda op, args: {'status': 'ambiguous', 'request': None})
        self.assertEqual(result['counts']['blocked'], 1)
        self.assertEqual(result['counts']['synced_to_service'], 0)

    def test_storage_errors_expose_only_safe_classification(self):
        with patch('coopagents.local_outbox.sqlite3.connect', side_effect=sqlite3.DatabaseError('PRIVATE-DB-ERROR')):
            with self.assertRaises(ValidationError) as caught:
                self.box.summary()
        self.assertNotIn('PRIVATE', str(caught.exception))

    def test_batch_stops_on_auth_quota_or_identity_but_not_independent_validation_conflict(self):
        for reason in ('auth', 'quota', 'identity_mismatch', 'conflict', 'validation'):
            with self.subTest(reason=reason):
                box = self.m.LocalOutbox(self.path.with_name(reason + '-batch.sqlite3'), 'room', 'member')
                box.enqueue('ask_owner', self.args)
                box.enqueue('ask_owner', {**self.args, 'request_key': 'second'})
                sender = Mock(side_effect=[self.m.OutboxError(reason), {'id': 2}])
                summary = box.flush(self.identity, sender)
                stop_batch = reason in ('auth', 'quota', 'identity_mismatch')
                self.assertEqual(sender.call_count, 1 if stop_batch else 2)
                self.assertEqual(summary['items'][0]['status'], 'blocked')
                self.assertEqual(summary['items'][1]['attempts'], 0 if stop_batch else 1)
                self.assertEqual(summary['items'][1]['status'], 'queued_locally' if stop_batch else 'synced_to_service')
                self.assertIsNone(summary['items'][1]['reason'])


if __name__ == '__main__':
    unittest.main()
