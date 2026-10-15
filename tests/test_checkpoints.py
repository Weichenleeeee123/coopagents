"""Collaboration checkpoint evidence is retained under .local/test-evidence."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.api import Service
from coopagents.errors import AccessDenied, NotFound, ValidationError


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.path = Path('.local/test-evidence') / ('checkpoints-' + str(uuid4()) + '.sqlite3')
        self.service = Service(self.path)
        self.owner = self.service.identity.create_room('Room', 'Owner')
        self.peer = self.service.identity.add_member(self.owner['web_token'], 'Peer')
        self.other = self.service.identity.create_room('Other', 'Other')

    def checkpoint(self, member=None, **kwargs):
        self.assertTrue('checkpoint' in self.service.operations, 'checkpoint operation missing')
        return self.service.call('checkpoint', (member or self.owner)['agent_token'],
            dict(session_key='session', tool='codex-cli', event='SessionStart', **kwargs))

    def test_checkpoint_authentic_identity_sessions_sources_and_server_time(self):
        first = self.checkpoint()
        record = first['checkpoint']
        self.assertEqual(record['member_id'], self.owner['member_id'])
        self.assertEqual(record['source'], 'hook')
        self.assertIsNotNone(datetime.fromisoformat(record['updated_at']).tzinfo)
        self.service.call('checkpoint', self.owner['agent_token'],
            {'session_key': 'second', 'tool': 'claude-code', 'event': 'manual'})
        self.service.call('checkpoint', self.owner['agent_token'],
            {'session_key': 'third', 'tool': 'codex-cli', 'event': 'completion'})
        self.checkpoint(self.peer)
        records = self.service.snapshot(self.owner['web_token'])['collaboration']['checkpoints']
        self.assertEqual(len(records), 4)
        self.assertEqual({r['source'] for r in records}, {'hook', 'manual', 'tool'})
        self.assertEqual(self.service.snapshot(self.other['web_token'])['collaboration']['checkpoints'], [])

    def test_checkpoint_peeks_related_pending_messages_and_effective_contracts(self):
        task = self.service.tasks.create_task(self.owner['web_token'], 't', 'Own', 'src')
        self.service.tasks.claim_task(self.owner['agent_token'], task['id'])
        request = self.service.messages.send_request(self.peer['agent_token'], request_key='r', context_version=1, body='Please coordinate',
            receiver_member_id=self.owner['member_id'], task_id=task['id'])
        contract = self.service.contracts.propose(self.peer['agent_token'], 'c', 0, 'API', 'Approved body')
        self.service.contracts.decide(self.owner['web_token'], contract['id'], 1, 'approved')
        self.service.contracts.propose(self.peer['agent_token'], 'c', 1, 'Draft', 'Not approved')
        result = self.checkpoint(task_id=task['id'])
        brief = result['brief']
        self.assertEqual(brief['tasks'][0]['id'], task['id'])
        self.assertEqual(brief['requests'][0]['id'], request['id'])
        self.assertEqual(brief['contracts'][0]['body'], 'Approved body')
        with self.service.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_replies').fetchone()[0], 0)
            self.assertIsNone(db.execute('SELECT resolved_at FROM message_requests').fetchone()[0])

    def test_checkpoint_includes_replies_without_new_receipts_and_bounds_data(self):
        for i in range(15):
            task = self.service.tasks.create_task(self.owner['web_token'], str(i), 'T' * 200, 'scope')
            self.service.tasks.claim_task(self.owner['agent_token'], task['id'])
            request = self.service.messages.send_request(self.owner['agent_token'], request_key=str(i), context_version=1, body='x' * 4000,
                receiver_member_id=self.peer['member_id'], task_id=task['id'])
            self.service.messages.reply(self.peer['agent_token'], request['id'], str(i), 1, 'R' * 4000)
        with self.service.identity.db.connect() as db:
            count = db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0]
        result = self.checkpoint()
        self.assertLessEqual(len(json.dumps(result, ensure_ascii=False)), 20000)
        self.assertTrue(result['brief']['truncated'])
        self.assertTrue(result['brief']['requests'][0]['replies'])
        with self.service.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM message_receipts').fetchone()[0], count)

    def test_checkpoint_auth_and_task_ownership(self):
        self.checkpoint()
        for token in (self.owner['web_token'], 'invalid'):
            with self.assertRaises(AccessDenied):
                self.service.call('checkpoint', token, {'session_key': 's', 'tool': 'codex-cli', 'event': 'manual'})
        task = self.service.tasks.create_task(self.peer['web_token'], 't', 'Peer task', 'src')
        self.service.tasks.claim_task(self.peer['agent_token'], task['id'])
        with self.assertRaises(AccessDenied):
            self.checkpoint(task_id=task['id'])
        with self.assertRaises(NotFound):
            self.checkpoint(self.other, task_id=task['id'])
        self.service.identity.rotate_agent(self.owner['web_token'])
        with self.assertRaises(AccessDenied):
            self.checkpoint()

    def test_freshness_exact_five_minutes_and_hook_evidence_survives_manual(self):
        self.checkpoint()
        at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        with patch('coopagents.checkpoints._utc_now', return_value=at.isoformat()):
            self.checkpoint()
        with patch('coopagents.checkpoints._now', return_value=at + timedelta(seconds=299)):
            record = self.service.snapshot(self.owner['web_token'])['collaboration']['checkpoints'][0]
            self.assertFalse(record['stale'])
        with patch('coopagents.checkpoints._now', return_value=at + timedelta(seconds=300)):
            record = self.service.snapshot(self.owner['web_token'])['collaboration']['checkpoints'][0]
            self.assertTrue(record['stale'])
        self.service.call('checkpoint', self.owner['agent_token'],
            {'session_key': 'session', 'tool': 'codex-cli', 'event': 'manual'})
        record = self.service.snapshot(self.owner['web_token'])['collaboration']['checkpoints'][0]
        self.assertEqual(record['source'], 'manual')
        self.assertEqual(record['last_hook_at'], at.isoformat())

    def test_diagnostic_requires_readback_and_proof_and_is_member_private(self):
        self.assertTrue('diagnostic_start' in self.service.operations, 'diagnostic operation missing')
        token = self.owner['agent_token']
        start = self.service.call('diagnostic_start', token, {'challenge': 'unique-client-challenge'})
        self.assertEqual(start['status'], 'sent')
        self.assertNotIn('proof', start)
        args = {'diagnostic_id': start['diagnostic_id']}
        for member in (self.peer, self.other):
            with self.assertRaises(NotFound):
                self.service.call('diagnostic_read', member['agent_token'], args)
        with self.assertRaises(ValidationError):
            self.service.call('diagnostic_complete', token, dict(args, proof='not-a-proof'))
        read = self.service.call('diagnostic_read', token, args)
        self.assertEqual(read['challenge'], 'unique-client-challenge')
        self.assertEqual(read['status'], 'read_back')
        completed = self.service.call('diagnostic_complete', token, dict(args, proof=read['proof']))
        self.assertEqual(completed['status'], 'completed')
        view = self.service.snapshot(self.owner['web_token'])['collaboration']
        self.assertEqual(view['diagnostics'][0]['status'], 'completed')
        self.assertEqual(view['checkpoints'], [])
        self.assertNotIn(read['proof'], json.dumps(view))
        self.assertEqual(self.service.snapshot(self.peer['web_token'])['collaboration']['diagnostics'], [])
        with self.assertRaises(ValidationError):
            self.service.call('diagnostic_start', token, {'challenge': 'x' * 129})

    def test_additive_upgrade_reopen_preserves_existing_data(self):
        task = self.service.tasks.create_task(self.owner['web_token'], 'old', 'Existing', 'src')
        self.checkpoint()
        reopened = Service(self.path)
        view = reopened.snapshot(self.owner['web_token'])
        self.assertEqual(view['tasks'][0]['id'], task['id'])
        self.assertEqual(len(view['collaboration']['checkpoints']), 1)

    def test_upgrade_from_database_without_collaboration_tables(self):
        from coopagents.identity import IdentityStore
        legacy_path=self.path.with_name('legacy-'+str(uuid4())+'.sqlite3')
        identity=IdentityStore(legacy_path)
        owner=identity.create_room('Legacy', 'Owner')
        with identity.db.connect() as db:
            self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='collaboration_checkpoints'").fetchone())
        upgraded=Service(legacy_path)
        view=upgraded.snapshot(owner['web_token'])
        self.assertEqual(view['room']['name'],'Legacy')
        self.assertEqual(view['collaboration']['checkpoints'],[])

    def test_brief_excludes_unrelated_requests_and_unapproved_contracts(self):
        self.service.messages.send_request(self.peer['agent_token'],'unrelated',self.peer['member_id'],None,1,'Private unrelated')
        self.service.contracts.propose(self.peer['agent_token'],'draft',0,'Draft','Unapproved body')
        brief=self.checkpoint()['brief']
        self.assertEqual(brief['requests'],[])
        self.assertEqual(brief['contracts'],[])

    def test_individual_excerpts_report_truncation(self):
        self.service.messages.send_request(self.peer['agent_token'],'long',self.owner['member_id'],None,1,'x'*4000)
        brief=self.checkpoint()['brief']
        self.assertTrue(brief['truncated'])
        self.assertTrue(brief['requests'][0]['excerpted'])


if __name__ == '__main__':
    unittest.main()
