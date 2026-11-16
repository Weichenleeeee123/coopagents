"""Fake-store/remote routing checks; no native hooks, servers or model calls."""
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import inspect
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from mcp.types import CallToolResult, TextContent, Tool

from coopagents import space_wake
from coopagents.space_bridge import Bridge, native_alias_advertised


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Store:
    def __init__(self):
        self.known, self.claimed, self.status = set(), [], []
        self.generation = 'current'

    def register(self, *args):
        return self.generation

    def current(self, session, generation):
        return generation == self.generation

    def mark(self, session, generation, status, now):
        self.status.append(status)

    def unseen(self, keys):
        return [key for key in keys if key not in self.known]

    def baseline(self, keys, session, now):
        self.known.update(keys)

    def claim(self, keys, session, now, policy):
        fresh = self.unseen(keys)
        self.known.update(fresh)
        self.claimed.extend(fresh)
        return fresh, None


class SessionWatcherRoutingTests(unittest.TestCase):
    def watcher(self, items, *, session='native-a', presence=None, store=None, **kwargs):
        self.assertIn('presence', inspect.signature(space_wake.Watcher).parameters)
        self.clock, self.store = Clock(), store or Store()
        self.presence_calls = []
        def report(state):
            self.presence_calls.append(state)
            return presence(state) if presence else {}
        with patch.object(space_wake, 'WakeState', return_value=self.store):
            return space_wake.Watcher(Path('unused-private-profile.json'), 'claude', session, 'Stop',
                digest=items if callable(items) else lambda: {'items': items}, presence=report,
                clock=self.clock, sleep=self.clock.sleep, cursor=lambda: None,
                policy=space_wake.Policy(min_interval=0, max_per_hour=100, debounce=0, poll=5), **kwargs)

    def item(self, key, *, scope='session', target='native-a', kind='request', identifier=7):
        return dict(kind=kind, id=identifier, delivery_key=key,
                    delivery_scope=scope, target_session_key=target)

    def test_delivery_key_is_bounded_and_legacy_items_remain_compatible(self):
        self.assertEqual(space_wake.item_key(self.item('request:7:session:abc')), 'request:7:session:abc')
        self.assertEqual(space_wake.item_key({'kind': 'reply', 'id': 3}), 'reply:3')
        for key in ('', 'unsafe\nkey', 'x' * 257, 'private text with spaces', None):
            with self.subTest(key=repr(key)[:20]), self.assertRaises(ValueError):
                space_wake.item_key(self.item(key))

    def test_baseline_and_claim_ignore_another_native_session(self):
        foreign = self.item('request:7:session:foreign', target='native-b')
        own = self.item('reply:8:session:own', kind='reply', identifier=8)
        member = self.item('handoff:9:member:fallback', scope='member', target=None, kind='handoff', identifier=9)
        watcher = self.watcher([foreign, own, member])
        self.assertEqual(watcher.run(0, baseline=True), ('quiet', 'deadline'))
        self.assertEqual(self.store.known, {own['delivery_key'], member['delivery_key']})
        self.assertNotIn(foreign['delivery_key'], self.store.claimed)
        self.assertEqual(self.presence_calls, ['watching'])

    def test_foreign_watcher_cannot_swallow_target_and_member_fallback_can_redeliver(self):
        store = Store()
        targeted = self.item('request:7:session:lease-one')
        unrelated = self.watcher([targeted], session='native-b', store=store)
        self.assertEqual(unrelated.run(0), ('quiet', 'deadline'))
        self.assertEqual(store.known, set())
        self.assertEqual(self.watcher([targeted], store=store).run(0)[0], 'wake')
        fallback = self.item('request:7:member:lease-stopped', scope='member', target=None)
        self.assertEqual(self.watcher([fallback], session='native-b', store=store).run(0)[0], 'wake')
        self.assertEqual(len(store.claimed), 2)

    def test_poll_refreshes_presence_and_owner_exit_reports_stopped(self):
        watcher = self.watcher([], owners=[123], alive=lambda pid: self.clock.now < 1008)
        self.assertEqual(watcher.run(20), ('quiet', 'owner_exited'))
        self.assertEqual(self.presence_calls, ['watching', 'watching', 'stopped'])
        self.assertEqual(self.store.claimed, [])

    def test_waking_and_quiet_deadline_preserve_the_short_native_lease(self):
        watcher = self.watcher([self.item('request:7:session:own')])
        self.assertEqual(watcher.run(0)[0], 'wake')
        self.assertEqual(self.presence_calls, ['watching'])
        self.assertEqual(self.watcher([]).run(0), ('quiet', 'deadline'))
        self.assertEqual(self.presence_calls, ['watching'])

    def test_throttled_delivery_still_refreshes_the_live_watcher_lease(self):
        store = Store()
        store.claim = lambda keys, session, now, policy: ([], now + 300)
        watcher = self.watcher([self.item('request:7:session:own')], store=store)
        self.assertEqual(watcher.run(16), ('quiet', 'deadline'))
        self.assertEqual(self.presence_calls, ['watching'] * 4)

    def test_auth_denial_stops_without_retrying_presence_or_reading_messages(self):
        def denied(state):
            raise space_wake.AuthDenied()
        watcher = self.watcher([self.item('request:7:session:own')], presence=denied)
        self.assertEqual(watcher.run(20), ('quiet', 'auth_denied'))
        self.assertEqual(self.presence_calls, ['watching'])
        self.assertEqual(self.store.known, set())

    def test_digest_auth_denial_does_not_retry_or_send_stopped(self):
        def denied():
            raise space_wake.AuthDenied()
        self.assertEqual(self.watcher(denied).run(20), ('quiet', 'auth_denied'))
        self.assertEqual(self.presence_calls, ['watching'])

    def test_superseded_watcher_does_not_stop_the_new_watchers_lease(self):
        def digest():
            self.store.generation = 'replacement'
            return {'items': []}
        self.assertEqual(self.watcher(digest).run(10), ('quiet', 'superseded'))
        self.assertEqual(self.presence_calls, ['watching'])

    def test_default_remote_helpers_send_only_trusted_native_session_metadata(self):
        self.assertTrue(hasattr(space_wake, 'remote_presence'), 'presence HTTP helper is missing')
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        response = dict(room_id='r', member_id='m', items=[])
        with patch.object(space_wake, 'read_profile', return_value=profile), \
                patch('coopagents.space_runtime.request', return_value=response) as request:
            space_wake.remote_digest(Path('unused'), session_key='native-a')
            self.assertEqual(request.call_args.kwargs['data'], {'session_key': 'native-a'})
            space_wake.remote_presence(Path('unused'), 'native-a', 'claude', 'watching')
            self.assertEqual(request.call_args.args[:2], (profile['origin'], '/api/operations/session_presence'))
            self.assertEqual(request.call_args.kwargs['data'], dict(session_key='native-a', tool='claude-code',
                state='watching', ttl_seconds=90))
            self.assertEqual(request.call_args.kwargs['token'], profile['agent_token'])
            self.assertFalse(any('/read' in call.args[1] or '/ack' in call.args[1] for call in request.call_args_list))

    def test_default_watcher_passes_native_id_to_presence_and_digest(self):
        self.assertTrue(hasattr(space_wake, 'remote_presence'), 'presence HTTP helper is missing')
        with patch.object(space_wake, 'WakeState', return_value=Store()), \
                patch.object(space_wake, 'remote_presence', return_value={}) as presence, \
                patch.object(space_wake, 'remote_digest', return_value={'items': []}) as digest:
            watcher = space_wake.Watcher(Path('unused'), 'codex', 'native-a', 'Stop')
            self.assertEqual(watcher._items(), {})
            self.assertEqual(presence.call_args.args, (Path('unused'), 'native-a', 'codex', 'watching'))
            self.assertEqual(digest.call_args.kwargs, {'session_key': 'native-a'})

    def test_remote_auth_errors_are_translated_and_identity_mismatch_is_denied(self):
        self.assertTrue(hasattr(space_wake, 'remote_presence'), 'presence HTTP helper is missing')
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        with patch.object(space_wake, 'read_profile', return_value=profile):
            for code in (401, 403):
                with patch('coopagents.space_runtime.request', side_effect=HTTPError(profile['origin'], code, '', {}, None)) as request:
                    with self.assertRaises(space_wake.AuthDenied):
                        space_wake.remote_presence(Path('unused'), 'native-a', 'claude', 'watching')
                    self.assertEqual(request.call_count, 1)
            with patch('coopagents.space_runtime.request', return_value={'room_id': 'r', 'member_id': 'other'}):
                with self.assertRaises(space_wake.AuthDenied):
                    space_wake.remote_presence(Path('unused'), 'native-a', 'claude', 'watching')

    def test_old_service_presence_is_explicitly_unsupported_without_a_lease(self):
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        with patch.object(space_wake, 'read_profile', return_value=profile):
            for code in (404, 405):
                with self.subTest(code=code), patch('coopagents.space_runtime.request',
                        side_effect=HTTPError(profile['origin'], code, '', {}, None)) as request:
                    result = space_wake.remote_presence(Path('unused'), 'native-a', 'claude', 'watching')
                    self.assertIs(result['routing_supported'], False)
                    self.assertIs(result['lease_recorded'], False)
                    self.assertEqual(result['state'], 'unsupported')
                    self.assertEqual(request.call_count, 1)

    def test_old_digest_retries_empty_payload_once_and_validates_legacy_identity(self):
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        legacy = dict(room_id='r', member_id='m', items=[{'kind': 'request', 'id': 7}])
        unsupported = lambda: HTTPError(profile['origin'], 400, '', {}, None)
        with patch.object(space_wake, 'read_profile', return_value=profile) as read:
            with patch('coopagents.space_runtime.request', side_effect=[unsupported(), legacy]) as request:
                result = space_wake.remote_digest(Path('unused'), session_key='native-a')
                self.assertFalse(result['routing_supported'])
                self.assertEqual(result['items'], legacy['items'])
                self.assertNotIn('routing_supported', legacy)
                self.assertEqual([call.kwargs['data'] for call in request.call_args_list],
                                 [{'session_key': 'native-a'}, {}])
                self.assertEqual(read.call_count, 1, 'one attempt must retain its trusted profile identity')
            with patch('coopagents.space_runtime.request', side_effect=[unsupported(), {**legacy, 'member_id': 'foreign'}]) as request:
                with self.assertRaises(space_wake.AuthDenied):
                    space_wake.remote_digest(Path('unused'), session_key='native-a')
                self.assertEqual(request.call_count, 2)
            for code in (401, 403, 500):
                expected = space_wake.AuthDenied if code in (401, 403) else HTTPError
                errors = [HTTPError(profile['origin'], 400, '', {}, None),
                          HTTPError(profile['origin'], code, '', {}, None)]
                with self.subTest(fallback_code=code), patch('coopagents.space_runtime.request', side_effect=errors) as request:
                    with self.assertRaises(expected):
                        space_wake.remote_digest(Path('unused'), session_key='native-a')
                    self.assertEqual(request.call_count, 2)

    def test_digest_fallback_is_bounded_and_auth_network_server_errors_never_fallback(self):
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        with patch.object(space_wake, 'read_profile', return_value=profile):
            for code in (401, 403, 500, 503):
                error = HTTPError(profile['origin'], code, '', {}, None)
                expected = space_wake.AuthDenied if code in (401, 403) else HTTPError
                with self.subTest(code=code), patch('coopagents.space_runtime.request', side_effect=error) as request:
                    with self.assertRaises(expected):
                        space_wake.remote_digest(Path('unused'), session_key='native-a')
                    self.assertEqual(request.call_count, 1)
                    with self.assertRaises(expected):
                        space_wake.remote_presence(Path('unused'), 'native-a', 'claude', 'watching')
                    self.assertEqual(request.call_count, 2)
            with patch('coopagents.space_runtime.request', side_effect=OSError('offline')) as request:
                with self.assertRaises(OSError):
                    space_wake.remote_digest(Path('unused'), session_key='native-a')
                self.assertEqual(request.call_count, 1)
            errors = [HTTPError(profile['origin'], 400, '', {}, None) for _ in range(2)]
            with patch('coopagents.space_runtime.request', side_effect=errors) as request:
                with self.assertRaises(HTTPError):
                    space_wake.remote_digest(Path('unused'), session_key='native-a')
                self.assertEqual(request.call_count, 2)
            with patch('coopagents.space_runtime.request', side_effect=HTTPError(profile['origin'], 400, '', {}, None)) as request:
                with self.assertRaises(HTTPError):
                    space_wake.remote_digest(Path('unused'))
                self.assertEqual(request.call_count, 1)

    def test_watcher_can_use_old_member_digest_without_claiming_a_session_lease(self):
        profile = dict(origin='http://127.0.0.1:9', room_id='r', member_id='m', agent_token='private-token')
        def old_service(origin, path, *, token, data):
            self.assertEqual((origin, token), (profile['origin'], profile['agent_token']))
            if path.endswith('/session_presence'):
                raise HTTPError(origin, 404, '', {}, None)
            if data:
                raise HTTPError(origin, 400, '', {}, None)
            return dict(room_id='r', member_id='m', items=[{'kind': 'request', 'id': 7}])
        clock, store = Clock(), Store()
        with patch.object(space_wake, 'read_profile', return_value=profile), \
                patch.object(space_wake, 'WakeState', return_value=store), \
                patch('coopagents.space_runtime.request', side_effect=old_service) as request:
            watcher = space_wake.Watcher(Path('unused'), 'claude', 'native-a', 'Stop', clock=clock,
                sleep=clock.sleep, cursor=lambda: None, policy=space_wake.Policy(debounce=0))
            self.assertEqual(watcher.run(0)[0], 'wake')
            self.assertEqual(store.claimed, ['request:7'])
            self.assertEqual(request.call_count, 3)


class FakeRemote:
    def __init__(self, result, advertises=True):
        self.result, self.calls = result, []
        self.advertises = advertises

    async def list_tools(self, cursor=None):
        properties = {'native_session_id': {'type': 'string'}} if self.advertises else {}
        return SimpleNamespace(tools=[Tool(name='register_session', description='Existing tool',
            input_schema={'type': 'object', 'properties': properties})], next_cursor=None)

    async def call_tool(self, name, arguments):
        self.calls.append((name, deepcopy(arguments)))
        if name == 'register_session' and len(self.calls) > 1:
            raise OSError('private failure must not replace a successful claim')
        return self.result


def sdk_result(payload, error=False):
    return CallToolResult(is_error=error, structured_content=payload, content=[TextContent(type='text', text='retained')])


class BridgeNativeAliasTests(unittest.TestCase):
    def test_malformed_alias_schema_does_not_claim_backend_support(self):
        for field in ({'anyOf': None}, {'type': 'integer'}, False):
            tool = SimpleNamespace(name='register_session', input_schema={
                'type': 'object', 'properties': {'native_session_id': field}})
            self.assertFalse(native_alias_advertised(tool))

    def invoke(self, name, arguments, payload, *, environment=None, client='codex-mcp-client', error=False,
               advertises=True, discover=True):
        bridge = Bridge.__new__(Bridge)
        bridge.identity, bridge.profile_path = ('r', 'm'), Path('unused-private-profile')
        remote = FakeRemote(sdk_result(payload, error), advertises)
        @asynccontextmanager
        async def connection():
            yield remote
        bridge.remote = connection
        context = SimpleNamespace(session=SimpleNamespace(client_params=SimpleNamespace(client_info=SimpleNamespace(name=client))))
        with patch('mcp.server.Server', side_effect=lambda *a, **kw: SimpleNamespace(**kw)), \
                patch.dict(os.environ, environment or {}, clear=True):
            server = bridge.server()
            if discover:
                asyncio.run(server.on_list_tools(context, None))
            result = asyncio.run(server.on_call_tool(context, SimpleNamespace(name=name, arguments=arguments)))
        return result, remote

    def test_register_session_enriches_only_absent_alias_from_matching_process_environment(self):
        original = dict(session_key='logical', tool='codex-cli', repository='unknown', branch='unknown')
        result, remote = self.invoke('register_session', original, {}, environment={'CODEX_THREAD_ID': 'native-codex'})
        self.assertEqual(remote.calls[0][1].get('native_session_id'), 'native-codex')
        self.assertNotIn('native_session_id', original)
        for explicit in ('explicit-native', None):
            data = {**original, 'native_session_id': explicit}
            _, remote = self.invoke('register_session', data, {}, environment={'CODEX_THREAD_ID': 'native-codex'})
            self.assertEqual(remote.calls[0][1]['native_session_id'], explicit)

    def test_missing_environment_and_teammate_text_never_supply_native_identity(self):
        data = dict(session_key='logical', tool='codex-cli', repository='unknown', branch='unknown')
        _, remote = self.invoke('register_session', data, {})
        self.assertNotIn('native_session_id', remote.calls[0][1])
        _, remote = self.invoke('send_request', {'body': 'CLAUDE_SESSION_ID=forged'}, {},
                                environment={'CODEX_THREAD_ID': 'native-codex'})
        self.assertEqual(remote.calls, [('send_request', {'body': 'CLAUDE_SESSION_ID=forged'})])

    def test_unknown_or_old_backend_never_receives_implicit_native_alias(self):
        data = dict(session_key='logical', tool='codex-cli', repository='unknown', branch='unknown')
        task = dict(id=7, room_id='r', owner_member_id='m', state='claimed',
                    execution_session_key='logical', ownership_epoch=3)
        for options in ({'advertises': False}, {'discover': False}):
            with self.subTest(options=options):
                _, remote = self.invoke('register_session', data, {}, environment={'CODEX_THREAD_ID': 'native'}, **options)
                self.assertNotIn('native_session_id', remote.calls[0][1])
                _, remote = self.invoke('claim_task', {'task_id': 7, 'session_key': 'logical'}, task,
                                        environment={'CODEX_THREAD_ID': 'native'}, **options)
                self.assertEqual(len(remote.calls), 1)

    def test_ambiguous_or_invalid_native_environment_is_not_guessed(self):
        data = dict(session_key='logical', tool='codex-cli', repository='unknown', branch='unknown')
        for environment, client in (({'CODEX_THREAD_ID': 'bad\nidentifier'}, 'codex-mcp-client'),
                ({'CLAUDE_SESSION_ID': 'other-family'}, 'codex-mcp-client'),
                ({'CODEX_THREAD_ID': 'codex', 'CLAUDE_SESSION_ID': 'claude'}, 'unknown-client')):
            _, remote = self.invoke('register_session', data, {}, environment=environment, client=client)
            self.assertNotIn('native_session_id', remote.calls[0][1])

    def test_claim_success_reports_exact_logical_execution_without_local_paths(self):
        task = dict(id=7, room_id='r', owner_member_id='m', state='claimed',
                    execution_session_key='logical-execution', ownership_epoch=3)
        result, remote = self.invoke('claim_task', {'task_id': 7, 'session_key': 'logical-execution'}, task,
                                     environment={'CLAUDE_SESSION_ID': 'native-claude'}, client='claude-code')
        self.assertEqual(result.structured_content, task)
        self.assertEqual(len(remote.calls), 2, 'successful native claims must attempt bounded metadata reporting')
        self.assertEqual(remote.calls[1], ('register_session', dict(session_key='logical-execution',
            tool='claude-code', repository='unknown', branch='unknown', task_id=7, ownership_epoch=3,
            native_session_id='native-claude')))
        self.assertEqual(len(remote.calls), 2, 'metadata failure is best effort and never retried')

    def test_failed_or_foreign_claim_never_reports_an_execution_alias(self):
        task = dict(id=7, room_id='r', owner_member_id='m', state='claimed',
                    execution_session_key='logical', ownership_epoch=3)
        for extra, error in (({}, True), ({'room_id': 'foreign'}, False), ({'owner_member_id': 'other'}, False),
                             ({'id': 8}, False), ({'ownership_epoch': True}, False),
                             ({'execution_session_key': 'different'}, False), ({'state': 'open'}, False)):
            with self.subTest(extra=extra, error=error):
                _, remote = self.invoke('claim_task', {'task_id': 7, 'session_key': 'logical'}, {**task, **extra},
                                        environment={'CODEX_THREAD_ID': 'native'}, error=error)
                self.assertEqual(len(remote.calls), 1)


if __name__ == '__main__':
    unittest.main()
