"""Stable, bounded, secret-free workflow diagnostics; no live host or network."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import importlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.identity import _token_hash


class WorkflowDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.workflow_diagnostics'), 'workflow diagnostics module is missing')
        self.module = importlib.import_module('coopagents.workflow_diagnostics')
        self.root = Path('.local/test-evidence') / ('workflow-diagnostics-' + uuid4().hex)
        self.s = CoordinationService(self.root / 'domain.sqlite3')
        self.a = self.s.identity.create_room('Project', 'Requester')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        self.front = self.task(self.a, 'front')
        self.back = self.task(self.b, 'back')

    def task(self, member, name, claim=True):
        task = self.s.tasks.create_task(self.a['web_token'], name, name, 'src/' + name)
        return self.s.tasks.claim_task(member['agent_token'], task['id'], name) if claim else task

    def view(self, member=None, **extra):
        return self.s.team_workflow.read_workflow((member or self.a)['agent_token'], **extra)

    def diagnostic(self, component, request_id=None, **extra):
        return next(item for item in self.view(**extra)['diagnostics'] if item['component'] == component
                    and (request_id is None or item['evidence'].get('request_id') == request_id))

    def bind(self, member=None, task=None):
        member, task = member or self.a, task or self.front
        self.s.activity.register_session(member['agent_token'], task['execution_session_key'], 'codex-cli', 'repo', 'main',
            task['id'], task['ownership_epoch'], native_session_id='native-' + task['execution_session_key'])

    def facts(self):
        with self.s.identity.db.connect() as db:
            return {table: [tuple(row) for row in db.execute('SELECT * FROM ' + table)] for table in
                    ('message_requests', 'message_receipts', 'message_replies', 'workflow_reply_reads', 'session_presence', 'task_session_routes')}

    def test_server_unknowns_do_not_invent_network_native_load_or_hook_trust(self):
        projection = self.view()
        diagnostics = projection['diagnostics']
        for component in ('network', 'native_mcp', 'hook_trust'):
            item = next(d for d in diagnostics if d['component'] == component)
            self.assertEqual(item['status'], 'unknown')
            self.assertTrue(item['next_action']['action'])
        self.assertFalse(projection['model_consumption_proven'])
        self.assertNotIn('checked_at', json.dumps(diagnostics))
        self.assertNotIn('age_seconds', json.dumps(diagnostics))

    def test_message_lifecycle_facts_have_distinct_diagnostics_without_implicit_receipts(self):
        request = self.s.messages.send_request(self.a['agent_token'], 'question', self.b['member_id'], None, 1, 'PRIVATE_BODY')
        before = self.facts()
        self.assertEqual(self.diagnostic('message', request['id'])['status'], 'delivered_unread')
        self.assertEqual(self.facts(), before)
        self.s.messages.read_inbox(self.b['agent_token'])
        self.assertEqual(self.diagnostic('message', request['id'])['status'], 'recipient_read_no_reply')
        self.s.messages.acknowledge(self.b['agent_token'], request['id'])
        self.assertEqual(self.diagnostic('message', request['id'])['status'], 'processing_reported')
        self.s.messages.reply(self.b['agent_token'], request['id'], 'reply', 1, 'PRIVATE_REPLY')
        self.assertEqual(self.diagnostic('message', request['id'])['status'], 'reply_unread')
        self.s.workflow.read_replies(self.a['agent_token'])
        read = self.diagnostic('message', request['id'])
        self.assertEqual(read['status'], 'reply_read_waiting_confirmation')
        self.assertTrue(read['evidence']['sender_reply_read'])
        self.s.messages.resolve_request(self.a['agent_token'], request['id'], 1)
        self.assertEqual(self.diagnostic('message', request['id'])['status'], 'resolved')
        self.assertNotIn('PRIVATE_', json.dumps(self.view()['diagnostics']))

    def test_owner_history_and_unassigned_queue_have_concrete_recovery(self):
        old = self.s.workflow.ask_owner(self.a['agent_token'], 'owner', 'Field?', target_task_id=self.back['id'])['request']
        self.s.lifecycle.force_handoff(self.a['web_token'], self.back['id'], self.back['revision'], 'move', 'Change owner', target_member_id=self.a['member_id'])
        history = self.diagnostic('message', old['id'])
        self.assertEqual(history['status'], 'historical_route')
        self.assertEqual(history['next_action']['action'], 'refresh_current_responsibility')
        unassigned = self.task(self.a, 'unassigned', claim=False)
        self.s.workflow.ask_owner(self.a['agent_token'], 'queued', 'Field?', target_task_id=unassigned['id'])
        queue = self.diagnostic('owner_question')
        self.assertEqual(queue['status'], 'owner_unassigned')
        self.assertEqual(queue['next_action']['action'], 'wait_for_owner_assignment')

    def test_execution_alias_lease_and_credential_failure_are_different_components_of_recovery(self):
        self.assertEqual(self.diagnostic('execution', task_id=self.front['id'])['status'], 'native_alias_missing')
        self.bind()
        self.assertEqual(self.diagnostic('execution', task_id=self.front['id'])['status'], 'watcher_unobserved')
        self.s.session_routing.presence(self.a['agent_token'], 'native-front', 'codex-cli')
        active = self.diagnostic('execution', task_id=self.front['id'])
        self.assertEqual(active['status'], 'watcher_lease_active')
        self.assertFalse(active['evidence']['availability_proven'])
        with patch.object(self.module, '_now', return_value=datetime.now(timezone.utc) + timedelta(seconds=301)):
            self.assertEqual(self.diagnostic('execution', task_id=self.front['id'])['status'], 'watcher_stale')
        self.s.session_routing.presence(self.a['agent_token'], 'native-front', 'codex-cli', state='stopped')
        self.assertEqual(self.diagnostic('execution', task_id=self.front['id'])['status'], 'watcher_stopped')
        replacement = {**self.a, 'agent_token': self.s.identity.connect_agent(self.a['web_token'])['agent_token']}
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE credentials SET revoked_at=? WHERE token_hash=?', (datetime.now(timezone.utc).isoformat(), _token_hash(self.a['agent_token'])))
        item = next(d for d in self.view(replacement, task_id=self.front['id'])['diagnostics'] if d['component'] == 'execution')
        self.assertEqual(item['status'], 'credential_unavailable')
        self.assertEqual(item['next_action']['action'], 'reconnect_personal_credential')
        self.assertNotIn('credential_hash', json.dumps(item))

    def test_retired_execution_requires_refresh_without_approving_or_claiming(self):
        self.bind()
        self.s.lifecycle.force_handoff(self.a['web_token'], self.front['id'], self.front['revision'], 'move-front', 'Changed', target_member_id=self.b['member_id'])
        result = self.diagnostic('execution', task_id=self.front['id'])
        self.assertEqual(result['status'], 'execution_retired')
        self.assertEqual(result['next_action']['action'], 'refresh_current_task')
        forbidden = {'claim_task', 'decision', 'accept_handoff', 'force_handoff', 'install_wake', 'approve'}
        self.assertNotIn(result['next_action']['action'], forbidden)

    def test_diagnostics_are_bounded_stable_and_do_not_modify_business_state(self):
        for index in range(18):
            self.s.messages.send_request(self.a['agent_token'], str(index), self.b['member_id'], None, 1, 'x' * 4000)
        before = self.facts()
        projection = self.view()
        self.assertLessEqual(len(json.dumps(projection, sort_keys=True).encode()), 16000)
        self.assertLessEqual(len(projection['diagnostics']), 8)
        self.assertLessEqual(len(json.dumps(projection['diagnostics'], sort_keys=True).encode()), 2500)
        self.assertTrue(projection['diagnostics_truncated'])
        cursor = None
        for _ in range(100):
            page = self.s.team_workflow.work_brief(self.a['agent_token'], after_cursor=cursor, limit=10)
            self.assertLessEqual(len(json.dumps(page, sort_keys=True).encode()), 16000)
            cursor = page['cursor']
            if not page['has_more']:
                break
        again = self.s.team_workflow.work_brief(self.a['agent_token'], after_cursor=cursor, limit=10)
        self.assertTrue(again['unchanged'])
        self.assertEqual(again['diagnostics'], page['diagnostics'])
        self.assertEqual(self.facts(), before)

    def write_profile(self):
        profile = self.root / 'local' / 'profile.json'
        profile.parent.mkdir(parents=True)
        profile.write_text(json.dumps({'schema_version': 1, 'origin': 'http://127.0.0.1:9',
            'room_id': 'room', 'member_id': 'member', 'agent_token': 'SECRET_AGENT',
            'control_origin': 'http://127.0.0.1:9', 'control_token': 'SECRET_CONTROL'}), encoding='utf-8')
        return profile

    def test_missing_local_state_is_unknown_without_creating_files_or_directories(self):
        root = self.root / 'absent'
        result = self.module.local_diagnostics(root / 'profile.json')
        self.assertFalse(root.exists())
        self.assertTrue(result['read_only'])
        self.assertFalse(result['model_consumption_proven'])
        self.assertTrue(all(d['status'] != 'pass' for d in result['diagnostics']))

    def test_existing_local_state_is_read_only_allowlisted_and_never_starts_a_host(self):
        profile = self.write_profile()
        folder = profile.parent
        (folder / 'native-host.json').write_text(json.dumps({'schema_version': 1, 'room_id': 'room', 'member_id': 'member', 'desired_running': False, 'blocked': False}), encoding='utf-8')
        with closing(sqlite3.connect(folder / 'bridge-events.sqlite3')) as db:
            db.execute('CREATE TABLE state(room,member,cursor,floor,reset)')
            db.execute("INSERT INTO state VALUES('room','member',7,2,'local_cache_expired')")
            db.execute('CREATE TABLE events(id INTEGER,body TEXT)')
            db.execute("INSERT INTO events VALUES(7,'SECRET_EVENT_BODY')")
            db.commit()
        with closing(sqlite3.connect(folder / 'wake-state.sqlite3')) as db:
            db.execute('CREATE TABLE watchers(session,tool,event,status,started,seen,pid)')
            db.execute("INSERT INTO watchers VALUES('SECRET_AGENT','codex','Stop','stopped',1,1,999999)")
            db.execute('CREATE TABLE settings(key,value)')
            db.execute("INSERT INTO settings VALUES('codex_standby','90')")
            db.execute('CREATE TABLE wakes(id,session,at,items)')
            db.commit()
        hooks = folder / 'hooks.json'
        hooks.write_text(json.dumps({'hooks': {'Stop': [{'hooks': [{'command': 'python -m coopagents.space_wake SECRET_CONTROL'}]}]}, 'token': 'SECRET_HOOK_TOKEN'}), encoding='utf-8')
        before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        with (patch('subprocess.run', side_effect=AssertionError('No native command')),
              patch('coopagents.space_host.ensure', side_effect=AssertionError('No host start'))):
            result = self.module.local_diagnostics(profile, transport_status='offline', hook_paths=[hooks],
                outbox={'counts': {'queued_locally': 2, 'blocked': 1, 'synced_to_service': 3}, 'raw_error': 'SECRET_OUTBOX'})
        serialized = json.dumps(result)
        for secret in ('SECRET_AGENT', 'SECRET_CONTROL', 'SECRET_EVENT_BODY', 'SECRET_HOOK_TOKEN', 'SECRET_OUTBOX', 'credential_hash'):
            self.assertNotIn(secret, serialized)
        self.assertEqual({p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}, before)
        cards = {d['component']: d for d in result['diagnostics']}
        self.assertEqual(cards['host_policy']['status'], 'stopped_by_user')
        self.assertEqual(cards['event_cache']['status'], 'reset_required')
        self.assertEqual(cards['watcher']['status'], 'stopped')
        self.assertEqual(cards['hook_trust']['status'], 'unknown')
        self.assertEqual(cards['native_mcp']['status'], 'unknown')
        self.assertEqual(cards['outbox']['evidence']['blocked'], 1)

    def test_denied_or_raw_transport_errors_do_not_become_identity_success_or_error_echo(self):
        profile = self.write_profile()
        denied = self.module.local_diagnostics(profile, transport_status='auth_denied')
        identity = next(d for d in denied['diagnostics'] if d['component'] == 'identity')
        self.assertEqual(identity['status'], 'rejected')
        self.assertEqual(identity['next_action']['action'], 'reconnect_personal_credential')
        raw = self.module.local_diagnostics(profile, transport_status='bad Bearer SECRET_ERROR')
        self.assertNotIn('SECRET_ERROR', json.dumps(raw))

    def test_corrupt_or_foreign_local_cache_does_not_create_or_dump_state(self):
        profile = self.write_profile()
        path = profile.with_name('bridge-events.sqlite3')
        path.write_bytes(b'SECRET_CORRUPT_DATABASE')
        original = path.read_bytes()
        result = self.module.local_diagnostics(profile)
        self.assertNotIn('SECRET_CORRUPT', json.dumps(result))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(next(d for d in result['diagnostics'] if d['component'] == 'event_cache')['status'], 'unknown')

    def test_local_doctor_seam_is_pure_read_only_and_never_grants_trust(self):
        from coopagents.onboarding_doctor import workflow_diagnostics_check
        profile = self.write_profile()
        with patch('subprocess.run', side_effect=AssertionError('No native command')):
            result = workflow_diagnostics_check(profile, transport_status='offline')
        self.assertEqual(result['id'], 'workflow_diagnostics')
        self.assertNotEqual(result['status'], 'pass')
        self.assertIn('diagnostics', result['evidence'])

    def test_unknown_harness_does_not_inspect_or_claim_codex_hook_configuration(self):
        profile = self.write_profile()
        with patch('coopagents.space_wake.settings_path', side_effect=AssertionError('Do not guess another host')):
            result = self.module.local_diagnostics(profile, tool='unknown-native', project_dir=profile.parent)
        hooks = next(d for d in result['diagnostics'] if d['component'] == 'hooks_configuration')
        self.assertEqual(hooks['status'], 'unknown')
        self.assertEqual(hooks['evidence']['files_inspected'], 0)

    def test_transport_observation_accepts_a_recorded_timestamp_without_inventing_age(self):
        profile = self.write_profile()
        observed = datetime(2026, 11, 16, tzinfo=timezone.utc).timestamp()
        result = self.module.local_diagnostics(profile, transport_status='offline', observed_at=observed)
        transport = next(d for d in result['diagnostics'] if d['component'] == 'transport')
        self.assertEqual(transport['evidence']['observed_at'], '2026-11-16T00:00:00+00:00')
        self.assertNotIn('age_seconds', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
