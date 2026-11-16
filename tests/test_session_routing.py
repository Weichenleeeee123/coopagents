"""Leased native aliases route facts only; retained SQLite, no running service."""
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import importlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from uuid import uuid4

from coopagents.coordination import CoordinationService
from coopagents.errors import AccessDenied, Conflict, NotFound, ValidationError
from coopagents.identity import _token_hash


class SessionRoutingTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('coopagents.session_routing'), 'session routing store is missing')
        self.module = importlib.import_module('coopagents.session_routing')
        self.path = Path('.local/test-evidence') / ('session-routing-' + uuid4().hex + '.sqlite3')
        self.s = CoordinationService(self.path)
        self.routing = self.module.SessionRoutingStore(self.s.identity)
        self.a = self.s.identity.create_room('Project', 'Frontend')
        self.b = self.s.identity.add_member(self.a['web_token'], 'Backend')
        self.front = self.task(self.a, 'front')
        self.back = self.task(self.b, 'back')
        self.now = datetime.now(timezone.utc)
        self.clock = patch('coopagents.session_routing._now', side_effect=lambda: self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)

    def task(self, member, name):
        task = self.s.tasks.create_task(self.a['web_token'], name, name, 'src/' + name)
        return self.s.tasks.claim_task(member['agent_token'], task['id'], name)

    def bind(self, member, task, native=None, **extra):
        data = dict(session_key=task['execution_session_key'], tool='codex-cli', repository='repo', branch='main',
                    task_id=task['id'], ownership_epoch=task['ownership_epoch'])
        if native is not None:
            data['native_session_id'] = native
        data.update(extra)
        return self.s.activity.register_session(member['agent_token'], **data)

    def presence(self, member=None, native='native-back', **extra):
        data = dict(session_key=native, tool='codex-cli', state='watching', ttl_seconds=90)
        data.update(extra)
        return self.routing.presence((member or self.b)['agent_token'], **data)

    def digest(self, member=None, native=None):
        return self.s.wake.digest((member or self.b)['agent_token'], session_key=native)

    def ask(self, source=False):
        args = dict(request_key=str(uuid4()), body='Which field?', target_task_id=self.back['id'])
        if source:
            args.update(source_task_id=self.front['id'], expected_revision=self.front['revision'],
                        session_key='front', ownership_epoch=self.front['ownership_epoch'])
        return self.s.workflow.ask_owner(self.a['agent_token'], **args)

    def facts(self):
        with self.s.identity.db.connect() as db:
            return {table: db.execute('SELECT COUNT(*) FROM ' + table).fetchone()[0]
                    for table in ('message_receipts', 'workflow_reply_reads', 'dependency_reads')}

    def test_alias_is_only_a_candidate_until_presence_is_active(self):
        self.bind(self.b, self.back, 'native-back')
        question = self.ask()['request']
        before = self.facts()
        fallback = self.digest()['items'][0]
        self.assertEqual(fallback['delivery_scope'], 'member')
        self.assertIsNone(fallback['target_session_key'])
        self.presence()
        self.presence(native='unrelated-native')
        self.assertEqual(self.digest()['items'], [])
        self.assertEqual(self.digest(native='unrelated-native')['items'], [])
        item = self.digest(native='native-back')['items'][0]
        self.assertEqual(item['request_id'], question['id'])
        self.assertEqual(item['delivery_scope'], 'session')
        self.assertEqual(item['target_session_key'], 'native-back')
        self.assertEqual(item['execution_target'], {'task_id': self.back['id'], 'session_key': 'back', 'ownership_epoch': self.back['ownership_epoch']})
        self.assertNotEqual(item['delivery_key'], fallback['delivery_key'])
        self.assertEqual(self.facts(), before)

    def test_default_alias_needs_a_real_lease_and_does_not_claim_native_execution(self):
        self.bind(self.b, self.back)
        self.ask()
        self.assertEqual(self.digest()['items'][0]['delivery_scope'], 'member')
        reported = self.presence(native='back')
        self.assertFalse(reported['model_consumption_proven'])
        self.assertFalse(reported['availability_proven'])
        self.assertEqual(self.digest(native='back')['items'][0]['target_session_key'], 'back')

    def test_dependency_incoming_uses_target_and_reply_uses_source_execution(self):
        self.bind(self.a, self.front, 'native-front')
        self.bind(self.b, self.back, 'native-back')
        self.presence(self.a, 'native-front')
        self.presence()
        dep = self.ask(source=True)['dependency']
        incoming = self.digest(native='native-back')['items'][0]
        self.assertEqual(incoming['execution_target']['task_id'], self.back['id'])
        self.assertEqual(self.digest(native='not-back')['items'], [])
        answered = self.s.dependencies.reply_dependency(self.b['agent_token'], dep['id'], dep['revision'],
            'answer', 'field:string', session_key='back', ownership_epoch=self.back['ownership_epoch'])
        reply = next(i for i in self.digest(self.a, 'native-front')['items'] if i['kind'] == 'reply')
        self.assertEqual(reply['id'], answered['latest_reply']['id'])
        self.assertEqual(reply['execution_target']['task_id'], self.front['id'])
        self.assertEqual(self.digest(self.a)['items'], [])
        self.assertEqual(self.digest(self.a, 'native-back')['items'], [])

    def test_same_member_other_session_reply_is_delivered_then_explicit_read_stops_wake(self):
        other = self.task(self.a, 'same-member-back')
        self.bind(self.a, self.front, 'native-front')
        self.bind(self.a, other, 'native-other')
        self.presence(self.a, 'native-front')
        self.presence(self.a, 'native-other')
        dep = self.s.dependencies.create_dependency(self.a['agent_token'], self.front['id'], other['id'],
            'Field?', self.front['revision'], 'same-dep', session_key='front', ownership_epoch=self.front['ownership_epoch'])
        self.s.dependencies.reply_dependency(self.a['agent_token'], dep['id'], dep['revision'], 'same-answer', 'field:string',
            session_key='same-member-back', ownership_epoch=other['ownership_epoch'])
        items = self.digest(self.a, 'native-front')['items']
        self.assertEqual([item['kind'] for item in items], ['reply'])
        self.s.workflow.read_replies(self.a['agent_token'])
        self.assertEqual(self.digest(self.a, 'native-front')['items'], [])

    def test_expiry_immediately_falls_back_with_a_new_delivery_key(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.ask()
        directed = self.digest(native='native-back')['items'][0]
        self.now += timedelta(seconds=90)
        fallback = self.digest()['items'][0]
        self.assertEqual(fallback['delivery_scope'], 'member')
        self.assertIsNone(fallback['target_session_key'])
        self.assertEqual(fallback['execution_target'], directed['execution_target'])
        self.assertNotEqual(fallback['delivery_key'], directed['delivery_key'])

    def test_heartbeat_keeps_key_but_stop_and_resume_create_fresh_delivery_generations(self):
        self.bind(self.b, self.back, 'native-back')
        first = self.presence()
        self.ask()
        original = self.digest(native='native-back')['items'][0]['delivery_key']
        self.now += timedelta(seconds=10)
        heartbeat = self.presence()
        self.assertEqual(heartbeat['generation'], first['generation'])
        self.assertEqual(self.digest(native='native-back')['items'][0]['delivery_key'], original)
        self.presence(state='stopped')
        stopped = self.digest()['items'][0]
        self.assertEqual(stopped['delivery_scope'], 'member')
        self.assertNotEqual(stopped['delivery_key'], original)
        resumed = self.presence()
        self.assertGreater(resumed['generation'], heartbeat['generation'])
        self.assertNotEqual(self.digest(native='native-back')['items'][0]['delivery_key'], original)

    def test_active_native_binding_cannot_be_replaced_but_stopped_binding_can_recover(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.ask()
        with self.assertRaises(Conflict):
            self.bind(self.b, self.back, 'new-native')
        self.assertEqual(self.digest(native='new-native')['items'], [])
        self.presence(state='stopped')
        self.bind(self.b, self.back, 'new-native')
        self.presence(native='new-native')
        self.assertEqual(self.digest(native='new-native')['items'][0]['target_session_key'], 'new-native')

    def test_omitted_alias_preserves_an_existing_live_native_binding(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.ask()
        previous = self.digest(native='native-back')['items'][0]['delivery_key']
        self.bind(self.b, self.back)
        self.assertEqual(self.digest(native='native-back')['items'][0]['delivery_key'], previous)

    def test_codex_family_aliases_are_compatible_without_fabricating_a_host(self):
        self.bind(self.b, self.back, 'native-back', tool='codex-desktop')
        reported = self.presence(tool='codex-cli')
        self.ask()
        self.assertEqual(reported['tool'], 'codex-cli')
        item = self.digest(native='native-back')['items'][0]
        self.assertEqual(item['delivery_scope'], 'session')
        self.assertEqual(item['execution_target']['session_key'], 'back')

    def test_native_filter_does_not_lose_older_member_fallback_behind_another_session_page(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        older = self.s.messages.send_request(self.a['agent_token'], 'older', self.b['member_id'], None, 1, 'Member-level')
        for _ in range(3):
            self.ask()
        with patch('coopagents.wake_digest.LIMIT', 2):
            items = self.digest(native='different-native')['items']
        self.assertEqual([item['request_id'] for item in items], [older['id']])
        self.assertEqual(items[0]['delivery_scope'], 'member')

    def test_foreign_or_stale_execution_cannot_register_a_native_alias(self):
        for person, extra, error in ((self.a, {}, AccessDenied),
                (self.b, {'session_key': 'wrong'}, Conflict),
                (self.b, {'ownership_epoch': self.back['ownership_epoch'] + 1}, Conflict)):
            with self.assertRaises(error):
                self.bind(person, self.back, 'native-back', **extra)
        startup = self.s.activity.register_session(self.b['agent_token'], 'loose', 'codex-cli', 'repo', 'main', native_session_id='native-back')
        self.assertIsNone(startup['task_id'])
        with self.s.identity.db.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM task_session_routes').fetchone()[0], 0)

    def test_retired_task_execution_falls_back_instead_of_using_an_old_live_alias(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.s.messages.send_request(self.a['agent_token'], 'direct', self.b['member_id'], self.back['id'], 1, 'Direct question')
        previous = self.digest(native='native-back')['items'][0]
        self.s.lifecycle.release_task(self.b['agent_token'], self.back['id'], self.back['revision'], 'release', 'Done',
            session_key='back', ownership_epoch=self.back['ownership_epoch'])
        fallback = self.digest()['items'][0]
        self.assertEqual(fallback['delivery_scope'], 'member')
        self.assertIsNone(fallback['execution_target'])
        self.assertNotEqual(fallback['delivery_key'], previous['delivery_key'])

    def test_presence_credential_isolation_and_revocation_fallback(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.ask()
        token = self.s.identity.connect_agent(self.b['web_token'])['agent_token']
        replacement = {**self.b, 'agent_token': token}
        for state in ('watching', 'stopped'):
            with self.assertRaises((AccessDenied, Conflict)):
                self.presence(replacement, state=state)
        self.assertEqual(self.digest(replacement, 'native-back')['items'], [])
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE credentials SET revoked_at=? WHERE token_hash=?', (self.now.isoformat(), _token_hash(self.b['agent_token'])))
        fallback = self.digest(replacement)['items'][0]
        self.assertEqual(fallback['delivery_scope'], 'member')
        self.presence(replacement)
        self.bind(replacement, self.back, 'native-back')
        self.assertEqual(self.digest(replacement, 'native-back')['items'][0]['delivery_scope'], 'session')
        serialized = json.dumps(self.presence(replacement)) + json.dumps(fallback)
        self.assertNotIn('credential_hash', serialized)
        self.assertNotIn(token, serialized)

    def test_concurrent_live_bindings_cannot_replace_the_first_current_execution_route(self):
        self.presence(native='one-native')
        self.presence(native='two-native')
        def bind(native):
            try:
                self.bind(self.b, self.back, native)
                return native
            except Conflict:
                return None
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(bind, ('one-native', 'two-native')))
        winner = next(value for value in outcomes if value is not None)
        self.assertEqual(sum(value is not None for value in outcomes), 1)
        self.ask()
        self.assertEqual(self.digest(native=winner)['items'][0]['target_session_key'], winner)

    def test_concurrent_presence_heartbeats_keep_one_stable_generation(self):
        with ThreadPoolExecutor(max_workers=4) as pool:
            generations = list(pool.map(lambda _: self.presence()['generation'], range(4)))
        self.assertEqual(generations, [1, 1, 1, 1])

    def test_expired_mapping_credential_cannot_keep_work_session_targeted(self):
        self.bind(self.b, self.back, 'native-back')
        self.presence()
        self.ask()
        replacement = {**self.b, 'agent_token': self.s.identity.connect_agent(self.b['web_token'])['agent_token']}
        with self.s.identity.db.connect(write=True) as db:
            db.execute('UPDATE credentials SET expires_at=? WHERE token_hash=?',
                       (self.now.isoformat(), _token_hash(self.b['agent_token'])))
        self.assertEqual(self.digest(replacement)['items'][0]['delivery_scope'], 'member')
        with self.assertRaises(AccessDenied):
            self.presence()

    def test_presence_validation_authentication_and_room_isolation(self):
        for data in ({'ttl_seconds': True}, {'ttl_seconds': 0}, {'ttl_seconds': 301}, {'ttl_seconds': 1.5},
                     {'native': ''}, {'native': 'x' * 201}, {'native': 'bad\nkey'}, {'state': 'online'}, {'tool': 'invented'}):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.presence(**data)
        with self.assertRaises(AccessDenied):
            self.routing.presence(self.b['web_token'], 'native-back', 'codex-cli')
        other = self.s.identity.create_room('Other', 'Other')
        self.presence(other)
        self.assertEqual(self.digest(other, 'native-back')['items'], [])
        with self.assertRaises(NotFound):
            self.bind(other, self.back, 'native-back')

    def test_legacy_no_mapping_items_remain_member_level_and_read_replies_are_not_repeated(self):
        request = self.s.messages.send_request(self.a['agent_token'], 'ordinary', self.b['member_id'], None, 1, 'Question')
        incoming = self.digest()['items'][0]
        self.assertEqual(incoming['delivery_scope'], 'member')
        self.assertIsNone(incoming['execution_target'])
        self.s.messages.reply(self.b['agent_token'], request['id'], 'ordinary-answer', 1, 'Answer')
        self.assertEqual(self.digest(self.a)['counts']['reply'], 1)
        self.s.workflow.read_replies(self.a['agent_token'])
        self.assertEqual(self.digest(self.a)['counts']['reply'], 0)


if __name__ == '__main__':
    unittest.main()
