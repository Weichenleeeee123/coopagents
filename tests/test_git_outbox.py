"""Git adapter outbox unit seams, with synthetic transport and no live service."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from uuid import uuid4

from coopagents.git_adapter import LocalAdapter
from coopagents.errors import ValidationError


class GitOutboxTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.local_outbox'), 'local outbox is missing')
        from coopagents import local_outbox
        self.m = local_outbox
        self.root = Path('.local/test-evidence') / ('git-outbox-' + uuid4().hex)
        self.repo = self.root / 'repo'; self.repo.mkdir(parents=True)
        self.local = {'workspace_id': 'workspace', 'repository': 'github.com/acme/demo'}
        self.workspace = SimpleNamespace(root=self.repo, inspect=lambda: dict(self.local))
        self.state = self.root / 'state'
        self.online, self.member, self.fail = True, 'member', None
        self.calls = []
        self.args = {'request_key': 'question', 'body': 'PRIVATE-QUESTION', 'target_task_id': 1}
        self.adapter = self.adapter_for('old-token')

    def adapter_for(self, token):
        with patch('coopagents.git_adapter.GitWorkspace', return_value=self.workspace):
            adapter = LocalAdapter(self.repo, 'https://example.invalid', 'room', token, state_root=self.state)
        adapter.request = self.transport
        return adapter

    def transport(self, path, data=None):
        self.calls.append((path, copy.deepcopy(data)))
        if not self.online:
            raise self.m.OutboxError('network')
        if self.fail:
            raise self.m.OutboxError(self.fail)
        if path == '/api/me':
            return {'me': {'room_id': 'room', 'member_id': self.member, 'kind': 'agent'}}
        if path == '/api/git/binding':
            return {'repository': self.local['repository']}
        return {'id': 7, 'ok': True}

    def learn_then_queue(self):
        self.adapter.forward('whoami', {})
        self.online = False
        return self.adapter.forward('ask_owner', self.args)

    def test_known_verified_identity_queues_offline_and_token_rotation_keeps_same_intent(self):
        first = self.learn_then_queue()
        self.assertEqual(first['status'], 'queued_locally')
        self.assertFalse(first['delivered'])
        rotated = self.adapter_for('new-token')
        second = rotated.forward('ask_owner', self.args)
        self.assertEqual(second['outbox_id'], first['outbox_id'])
        self.assertEqual(rotated.outbox_summary()['counts']['queued_locally'], 1)
        self.assertNotIn('old-token', json.dumps(rotated.outbox_summary()))

    def test_unknown_identity_cannot_be_invented_to_queue(self):
        self.online = False
        with self.assertRaises(ValidationError):
            self.adapter.forward('ask_owner', self.args)
        self.assertEqual(sum(self.adapter.outbox_summary()['counts'].values()), 0)

    def test_authorization_failure_is_blocked_not_queued_as_network_loss(self):
        self.learn_then_queue()
        self.online, self.fail = True, 'auth'
        with self.assertRaises(ValidationError):
            self.adapter.forward('ask_owner', self.args)
        self.assertEqual(self.adapter.outbox_summary()['counts']['blocked'], 1)

    def test_new_member_cannot_replay_original_members_queue(self):
        self.learn_then_queue()
        self.online, self.member = True, 'another-member'
        self.calls.clear()
        with self.assertRaises(ValidationError):
            self.adapter.forward('ask_owner', self.args)
        self.assertFalse(any(path == '/api/operations/ask_owner' for path, _ in self.calls))
        self.assertEqual(self.adapter.outbox_summary()['counts']['blocked'], 1)

    def test_recovery_revalidates_connection_and_sends_original_epoch_only(self):
        self.adapter.forward('whoami', {})
        args = {'dependency_id': 9, 'expected_revision': 2, 'request_key': 'answer', 'body': 'A',
                'session_key': 'old', 'ownership_epoch': 3}
        self.online = False
        self.adapter.forward('reply_dependency', args)
        self.online = True; self.calls.clear()
        result = self.adapter.flush_outbox()
        self.assertEqual(result['counts']['synced_to_service'], 1)
        self.assertEqual(self.calls[0][0], '/api/me')
        self.assertIn('/api/git/binding', [p for p, _ in self.calls])
        sent = next(payload for path, payload in self.calls if path == '/api/dependencies/9/reply')
        self.assertEqual(sent, {key: value for key, value in args.items() if key != 'dependency_id'})

    def test_explicit_stop_performs_no_identity_or_transport_request(self):
        self.learn_then_queue()
        self.online = True; self.calls.clear()
        result = self.adapter.flush_outbox(stopped=lambda: True)
        self.assertEqual(self.calls, [])
        self.assertEqual(result['counts']['queued_locally'], 1)

    def test_request_classifies_http_and_transport_errors_without_raw_details(self):
        for status, reason in ((401, 'auth'), (403, 'auth'), (409, 'conflict'), (400, 'validation'),
                               (429, 'quota'), (503, 'server')):
            with patch.object(self.adapter.opener, 'open', side_effect=HTTPError('https://example.invalid', status,
                    'PRIVATE-RAW-ERROR', {}, None)):
                with self.assertRaises(ValidationError) as caught:
                    LocalAdapter.request(self.adapter, '/api/me')
            self.assertEqual(caught.exception.reason, reason)
            self.assertNotIn('PRIVATE', str(caught.exception))
        with patch.object(self.adapter.opener, 'open', side_effect=URLError('PRIVATE-TRANSPORT')):
            with self.assertRaises(ValidationError) as caught:
                LocalAdapter.request(self.adapter, '/api/me')
        self.assertEqual(caught.exception.reason, 'network')

    def test_changed_local_project_configuration_is_not_an_offline_queue_permission(self):
        self.adapter.forward('whoami', {})
        directory = self.repo / '.coopagents'; directory.mkdir()
        (directory / 'project.json').write_text(json.dumps({'schema_version': 1, 'project_ref': 'foreign',
            'repository': self.local['repository']}), encoding='utf-8')
        self.online = False
        with self.assertRaises(ValidationError):
            self.adapter.forward('ask_owner', self.args)
        self.assertEqual(sum(self.adapter.outbox_summary()['counts'].values()), 0)

    def test_partial_current_identity_cannot_reuse_a_previous_successful_identity(self):
        self.learn_then_queue()
        self.online, self.member = True, None
        self.calls.clear()
        result = self.adapter.flush_outbox()
        self.assertFalse(any(path == '/api/operations/ask_owner' for path, _ in self.calls))
        self.assertEqual(result['counts']['blocked'], 1)

    def test_auth_denial_on_a_read_blocks_pending_recovery_without_queuing_the_read(self):
        self.learn_then_queue()
        self.online, self.fail = True, 'auth'
        with self.assertRaises(ValidationError):
            self.adapter.forward('read_team', {})
        summary = self.adapter.outbox_summary()
        self.assertEqual(summary['counts']['blocked'], 1)
        self.assertEqual([item['operation'] for item in summary['items']], ['ask_owner'])

    def test_online_ambiguous_owner_result_keeps_its_native_structure(self):
        transport = self.adapter.request
        self.adapter.request = lambda path, data=None: (
            {'status': 'ambiguous', 'request': None, 'candidates': [{'id': 1}, {'id': 2}]}
            if path == '/api/operations/ask_owner' else transport(path, data))
        result = self.adapter.forward('ask_owner', self.args)
        self.assertEqual(result['status'], 'ambiguous')
        self.assertEqual(len(result['candidates']), 2)
        self.assertEqual(sum(self.adapter.outbox_summary()['counts'].values()), 0)


if __name__ == '__main__':
    unittest.main()
